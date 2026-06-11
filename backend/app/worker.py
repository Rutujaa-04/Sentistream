import asyncio
import json
import os
import sys
import time
import uuid
from typing import Any, Dict, Optional

import redis.asyncio as aioredis
import structlog
from app.metrics import (
    DLQ_BACKLOG,
    DRIFT_ALERTS,
    HEADLINES_PROCESSED,
    INFERENCE_LATENCY,
    PORTFOLIO_CASH,
    PORTFOLIO_TOTAL_VALUE,
    POSITION_SHARES,
    REDIS_STREAM_BACKLOG,
    ROLLING_Z_SCORE,
    TOKENIZATION_LATENCY,
    TRADES_EXECUTED,
)
from prometheus_client import start_http_server

# Add parent directory to path to import properly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import settings
from app.database import ClickHouseDatabase
from app.drift import DriftDetector
from app.model import SentimentModel
from app.trading.alpaca_engine import AlpacaExecutionEngine
from app.trading.portfolio_service import PortfolioService
from app.trading.price_feed import PriceFeed
from app.trading.simulated_engine import SimulatedExecutionEngine
from app.trading.strategy import ThresholdStrategy

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)
logger = structlog.get_logger()

class ConsumerWorker:
    def __init__(self, worker_name: str):
        self.worker_name = worker_name
        self.redis_client: Optional[aioredis.Redis] = None
        self.model: Optional[SentimentModel] = None
        self.db: Optional[ClickHouseDatabase] = None
        self.trading_engine = None
        self.price_feed: Optional[PriceFeed] = None
        self.portfolio_service: Optional[PortfolioService] = None
        self.strategy: Optional[ThresholdStrategy] = None
        
        # In-memory portfolio tracking state (incrementally updated)
        self.portfolio_cash = float(settings.INITIAL_PORTFOLIO_CAPITAL)
        self.portfolio_positions: Dict[str, Dict[str, Any]] = {}  # ticker -> {"shares": int, "avg_price": float}
        self.total_portfolio_value = float(settings.INITIAL_PORTFOLIO_CAPITAL)
        self.strategy_mode = "long_only"
        self.last_settings_read_time = 0.0
        
        # Registry of drift detectors isolated by ticker to prevent contamination
        self.drift_detectors: Dict[str, DriftDetector] = {}
        # Tracks the last time a headline was processed for a ticker to detect quiet tickers
        self.last_headline_time: Dict[str, float] = {}
        self.backlog_task: Optional[asyncio.Task] = None
        self.settings_listener_task: Optional[asyncio.Task] = None
        self.is_running = True

    async def initialize(self):
        """Initializes database, model and broker connection objects."""
        logger.info("Initializing Consumer Worker...", name=self.worker_name)
        
        # 1. Initialize Redis Client
        self.redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        
        # 2. Initialize ClickHouse Client
        self.db = ClickHouseDatabase()
        await self.db.initialize()
        
        # 3. Load ONNX Model Singleton
        self.model = SentimentModel()
        
        # 4. Initialize Trading Strategy & Price Feed Singleton
        self.price_feed = PriceFeed()
        await self.price_feed.initialize()
        
        self.strategy = ThresholdStrategy(threshold=0.75)
        self.portfolio_service = PortfolioService(self.db, self.price_feed)

        # Start background Prometheus metrics scraper server
        try:
            start_http_server(port=8001, addr="0.0.0.0")
            logger.info("Prometheus HTTP metrics server running on port 8001")
        except Exception as e:
            logger.error("Failed to start Prometheus server (may already be running)", error=str(e))

        # 5. Cold-start in-memory portfolio state from ClickHouse trade logs
        portfolio_state = await self.portfolio_service.reconstruct_portfolio()
        self.portfolio_cash = float(portfolio_state["cash_usd"])
        self.portfolio_positions = {
            pos["ticker"]: {"shares": int(pos["shares"]), "avg_price": float(pos["avg_price"])}
            for pos in portfolio_state["positions"]
        }
        self.total_portfolio_value = float(portfolio_state["portfolio_value_usd"])
        
        # Set initial Prometheus gauges
        PORTFOLIO_CASH.set(self.portfolio_cash)
        PORTFOLIO_TOTAL_VALUE.set(self.total_portfolio_value)
        for ticker, pos in self.portfolio_positions.items():
            POSITION_SHARES.labels(ticker=ticker).set(pos["shares"])
            
        logger.info(
            "Worker portfolio state cold-started successfully",
            cash=self.portfolio_cash,
            positions=self.portfolio_positions,
            total_value=self.total_portfolio_value
        )
        
        # 6. Initialize Hexagonal Trading Adapter based on config
        engine_type = settings.TRADING_ENGINE.lower()
        if engine_type == "alpaca":
            self.trading_engine = AlpacaExecutionEngine()
        else:
            self.trading_engine = SimulatedExecutionEngine()
        await self.trading_engine.initialize()
        
        # 7. Ensure Redis Consumer Group exists
        await self.setup_consumer_group()

        # 8. Warm strategy settings cache
        try:
            mode = await self.redis_client.get("sentistream:settings:strategy_mode")
            self.strategy_mode = mode if mode else "long_only"
        except Exception as e:
            logger.error("Failed to warm strategy settings cache, using default long_only", error=str(e))
            self.strategy_mode = "long_only"
        self.last_settings_read_time = time.time()

    async def get_strategy_mode(self) -> str:
        """Helper to retrieve cached strategy mode or fetch from Redis if TTL expired."""
        now = time.time()
        if now - self.last_settings_read_time > 30.0:
            try:
                mode = await self.redis_client.get("sentistream:settings:strategy_mode")
                if mode:
                    self.strategy_mode = mode
                self.last_settings_read_time = now
                logger.info("Refreshed strategy settings cache", strategy_mode=self.strategy_mode)
            except Exception as e:
                logger.error("Failed to refresh strategy settings, using cached value", strategy_mode=self.strategy_mode, error=str(e))
        return self.strategy_mode

    async def listen_settings_updates(self):
        """Listens to settings updates published via Redis Pub/Sub for instant cache invalidation or portfolio resets."""
        pubsub = self.redis_client.pubsub()
        await pubsub.subscribe("sentistream:settings:updates")
        try:
            while self.is_running:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    try:
                        data = json.loads(message["data"])
                        # Handle strategy mode updates
                        new_mode = data.get("strategy_mode")
                        if new_mode in ("long_only", "long_short"):
                            self.strategy_mode = new_mode
                            self.last_settings_read_time = time.time()
                            logger.info("Instantly updated strategy mode via Pub/Sub", strategy_mode=self.strategy_mode)
                        
                        # Handle portfolio reset event
                        action = data.get("action")
                        if action == "reset_portfolio":
                            initial_capital = float(settings.INITIAL_PORTFOLIO_CAPITAL)
                            self.portfolio_cash = initial_capital
                            self.portfolio_positions = {}
                            self.total_portfolio_value = initial_capital
                            
                            # Reset Prometheus gauges
                            PORTFOLIO_CASH.set(self.portfolio_cash)
                            PORTFOLIO_TOTAL_VALUE.set(self.total_portfolio_value)
                            POSITION_SHARES.clear()
                            
                            if self.strategy and hasattr(self.strategy, "last_trade_time"):
                                self.strategy.last_trade_time.clear()
                            
                            logger.info("Portfolio state reset completed in worker")
                            
                            # Broadcast a reset signal to frontend so the UI updates instantly
                            reset_payload = {
                                "type": "portfolio_reset",
                                "data": {
                                    "cash_usd": self.portfolio_cash,
                                    "portfolio_value_usd": self.total_portfolio_value,
                                    "positions": []
                                }
                            }
                            await self.redis_client.publish("sentistream:sentiment_events", json.dumps(reset_payload))
                            
                    except Exception as parse_err:
                        logger.error("Failed to parse settings update message", error=str(parse_err))
                await asyncio.sleep(0.5)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error("Error in settings update Pub/Sub listener", error=str(e))
        finally:
            await pubsub.unsubscribe("sentistream:settings:updates")


    async def setup_consumer_group(self):
        """Idempotently creates the Redis Stream consumer group."""
        stream = "raw_headlines"
        group = "sentistream_workers"
        try:
            # Check if stream exists or create placeholder
            await self.redis_client.xgroup_create(
                name=stream,
                groupname=group,
                id="0",
                mkstream=True
            )
            logger.info("Created new Redis consumer group", stream=stream, group=group)
        except aioredis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                # Consumer group already exists, which is fine
                logger.info("Redis consumer group already active", stream=stream, group=group)
            else:
                logger.error("Failed to initialize consumer group", error=str(e))
                raise e

    async def route_to_dlq(self, raw_message_id: str, payload: dict, error_msg: str):
        """Routes failed or corrupted stream messages to the Dead Letter Queue (DLQ) stream."""
        logger.error(
            "Routing corrupted message to DLQ", 
            message_id=raw_message_id, 
            error=error_msg, 
            ticker=payload.get("ticker", "UNKNOWN")
        )
        dlq_payload = {
            "headline_id": payload.get("id", str(uuid.uuid4())),
            "raw_stream_id": raw_message_id,
            "ticker": payload.get("ticker", "UNKNOWN"),
            "headline_text": payload.get("headline_text", "UNKNOWN"),
            "source": payload.get("source", "UNKNOWN"),
            "failed_at": str(time.time()),
            "error_message": error_msg
        }
        
        # Write to DLQ stream, bounded to 500 items max
        await self.redis_client.xadd(
            name="dlq_headlines",
            fields=dlq_payload,
            maxlen=500,
            approximate=True
        )
        
        # Acknowledge the original stream so it doesn't block the consumer group
        await self.redis_client.xack("raw_headlines", "sentistream_workers", raw_message_id)

    def get_drift_detector(self, ticker: str) -> DriftDetector:
        """Lazy-instantiates a ticker-isolated Z-score drift detector."""
        if ticker not in self.drift_detectors:
            self.drift_detectors[ticker] = DriftDetector(
                window_size=settings.DRIFT_WINDOW_SIZE,
                z_threshold=settings.DRIFT_ALERT_Z_THRESHOLD,
                min_samples=settings.DRIFT_MIN_SAMPLES
            )
        return self.drift_detectors[ticker]

    async def send_slack_alert(self, ticker: str, direction: str, z_score: float, threshold: float):
        """Sends a notification to a Slack webhook when statistical sentiment drift is detected."""
        webhook_url = settings.SLACK_WEBHOOK_URL
        if not webhook_url or not webhook_url.startswith("http"):
            logger.info("Slack webhook URL not configured or invalid, skipping Slack alert", ticker=ticker)
            return

        payload = {
            "text": f"🚨 *SentiStream Statistical Sentiment Drift Alert* 🚨\n"
                    f"*Ticker*: `{ticker}`\n"
                    f"*Direction*: `{direction.replace('_', ' ').upper()}`\n"
                    f"*Rolling Z-Score*: `{z_score:+.2f}` (Threshold: `{threshold:+.1f}`)\n"
                    f"*System Action*: Logged to ClickHouse & Metrics updated."
        }
        try:
            import aiohttp
            async with aiohttp.ClientSession() as session:
                async with session.post(webhook_url, json=payload, timeout=5) as resp:
                    if resp.status in (200, 201):
                        logger.info("Successfully dispatched drift alert to Slack webhook", ticker=ticker)
                    else:
                        logger.warning("Slack webhook returned non-success status", status=resp.status, ticker=ticker)
        except Exception as e:
            logger.error("Failed to send Slack webhook alert", error=str(e), ticker=ticker)

    async def process_message(self, message_id: str, fields: dict):
        """Orchestrates the lifecycle of a single financial news headline message."""
        t_total_start = time.perf_counter()
        model_version = "v1"
        
        try:
            # 1. Deserialize message payload
            headline_id = fields["id"]
            ticker = fields["ticker"].strip().upper()
            if not ticker:
                raise ValueError("Ticker symbol cannot be empty")
            headline_text = fields["headline_text"]
            source = fields["source"]
            ingested_at = float(fields["ingested_at"])
            
            # Deterministic 80/20 A/B split based on headline ID hash
            try:
                clean_hex = headline_id[:8].replace("-", "")
                model_version = "v1" if int(clean_hex, 16) % 10 < 8 else "v2"
            except Exception:
                model_version = "v1"
            
            # 2. Run Quantized ONNX Inference
            inference = self.model.infer(headline_text, model_version=model_version)
            
            # Observe inference latencies in Prometheus (converting ms to seconds)
            INFERENCE_LATENCY.labels(model_version=model_version).observe(inference["latency_ms"] / 1000.0)
            TOKENIZATION_LATENCY.labels(model_version=model_version).observe(inference["tokenization_latency_ms"] / 1000.0)
            
            # Increment pipeline processed counter
            HEADLINES_PROCESSED.labels(ticker=ticker, sentiment=inference["label"], status="success", model_version=model_version).inc()
            
            # 3. Calculate Statistical Sentiment Drift
            # Convert label to numeric score for math calculations: pos=1.0, neg=-1.0, neu=0.0
            sentiment_score = 0.0
            if inference["label"] == "positive":
                sentiment_score = 1.0
            elif inference["label"] == "negative":
                sentiment_score = -1.0
                
            detector = self.get_drift_detector(ticker)
            drift_signal = detector.update(sentiment_score, ticker)
            
            # Update last processed headline time for this ticker
            self.last_headline_time[ticker] = time.time()
            
            # Update Prometheus rolling Z-score gauge
            ROLLING_Z_SCORE.labels(ticker=ticker).set(detector.last_z)
            
            # 4. Write data to ClickHouse (Headlines, Telemetry, and Drift Alerts)
            # DDL matches exact ClickHouse structure
            processed_at = time.time()
            
            # A. Write Headline Record
            await self.db.insert_headline(
                headline_id=headline_id,
                ticker=ticker,
                headline_text=headline_text,
                source=source,
                sentiment_label=inference["label"],
                confidence_score=inference["confidence"],
                ingested_at=ingested_at,
                processed_at=processed_at,
                model_version=model_version
            )
            
            # B. Write Telemetry Metrics
            t_total_end = time.perf_counter()
            total_latency = (t_total_end - t_total_start) * 1000.0
            
            await self.db.insert_telemetry(
                headline_id=headline_id,
                inference_latency_ms=inference["latency_ms"],
                tokenization_latency_ms=inference["tokenization_latency_ms"],
                total_latency_ms=total_latency,
                worker_id=self.worker_name,
                model_version=model_version
            )
            
            # C. Write Drift Alert if Z-score exceeded threshold
            drift_alert_id = None
            if drift_signal:
                drift_alert_id = str(uuid.uuid4())
                await self.db.insert_drift_alert(
                    alert_id=drift_alert_id,
                    ticker=ticker,
                    z_score=drift_signal.z_score,
                    window_mean=drift_signal.window_mean,
                    window_std=drift_signal.window_std,
                    direction=drift_signal.direction,
                    triggered_threshold=drift_signal.triggered_threshold
                )
                DRIFT_ALERTS.labels(ticker=ticker, direction=drift_signal.direction).inc()
                logger.warning(
                    "Statistical Sentiment Drift Alert triggered", 
                    ticker=ticker, 
                    z_score=drift_signal.z_score, 
                    direction=drift_signal.direction
                )
                # Dispatch alert to Slack webhook asynchronously
                asyncio.create_task(self.send_slack_alert(
                    ticker=ticker,
                    direction=drift_signal.direction,
                    z_score=drift_signal.z_score,
                    threshold=drift_signal.triggered_threshold
                ))

            # D. Execute Paper Trade Order if strategy triggers a signal
            bypass_cooldown = source in ("trades_seeder", "playwright_e2e_test", "trades_generator")
            trade_action = self.strategy.should_trade(ticker, inference["label"], inference["confidence"], bypass_cooldown=bypass_cooldown)
            if trade_action:
                current_price = await self.price_feed.get_price(ticker, bypass_cache=bypass_cooldown)
                strategy_mode = await self.get_strategy_mode()
                
                # Check current position sign
                current_shares = 0
                if ticker in self.portfolio_positions:
                    current_shares = self.portfolio_positions[ticker]["shares"]
                
                if trade_action == "buy":
                    if strategy_mode == "long_short" and current_shares < 0:
                        # COVER: Close the short position completely
                        qty = abs(current_shares)
                        required_cost = qty * current_price
                        
                        # Cost override to simulate capital depletion (test-only)
                        if settings.FORCE_TRADE_COST_USD > 0.0 or source == "playwright_e2e_test":
                            required_cost = max(settings.FORCE_TRADE_COST_USD, 100001.0)
                            
                        if qty <= 0 or self.portfolio_cash < required_cost:
                            logger.warning(
                                "Insufficient capital to execute cover order",
                                ticker=ticker,
                                required_cash=round(required_cost, 2),
                                available_cash=round(self.portfolio_cash, 2),
                                quantity=qty
                            )
                        else:
                            trade_id = await self.trading_engine.execute_order(
                                ticker=ticker,
                                action="buy",
                                quantity=qty,
                                price_at_signal=current_price,
                                signal_source_id=headline_id,
                                confidence_score=inference["confidence"]
                            )
                            # Update in-memory state incrementally
                            self.portfolio_cash -= required_cost
                            self.portfolio_positions.pop(ticker, None)
                            
                            # Update Prometheus metrics
                            TRADES_EXECUTED.labels(ticker=ticker, action="buy").inc()
                            PORTFOLIO_CASH.set(self.portfolio_cash)
                            POSITION_SHARES.labels(ticker=ticker).set(0)
                            
                            # Publish paper_trade event
                            trade_payload = {
                                "type": "paper_trade",
                                "data": {
                                    "trade_id": trade_id,
                                    "ticker": ticker,
                                    "action": "buy",
                                    "quantity": qty,
                                    "price": current_price,
                                    "executed_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(processed_at))
                                }
                            }
                            await self.redis_client.publish("sentistream:sentiment_events", json.dumps(trade_payload))
                    else:
                        # BUY LONG: Open or add to a long position (5% allocation)
                        trade_size = 0.05 * self.total_portfolio_value
                        qty = int(trade_size / current_price)
                        required_cost = qty * current_price
                        
                        # Cost override to simulate capital depletion (test-only)
                        if settings.FORCE_TRADE_COST_USD > 0.0 or source == "playwright_e2e_test":
                            required_cost = max(settings.FORCE_TRADE_COST_USD, 100001.0)
                            
                        if qty <= 0 or self.portfolio_cash < required_cost:
                            logger.warning(
                                "Insufficient capital to execute buy order",
                                ticker=ticker,
                                required_cash=round(required_cost, 2),
                                available_cash=round(self.portfolio_cash, 2),
                                quantity=qty
                            )
                            # Publish warning to Redis Pub/Sub so dashboard can display it
                            warning_payload = {
                                "type": "insufficient_capital",
                                "data": {
                                    "ticker": ticker,
                                    "required_cash": round(required_cost, 2),
                                    "available_cash": round(self.portfolio_cash, 2)
                                }
                            }
                            await self.redis_client.publish("sentistream:sentiment_events", json.dumps(warning_payload))
                        else:
                            trade_id = await self.trading_engine.execute_order(
                                ticker=ticker,
                                action="buy",
                                quantity=qty,
                                price_at_signal=current_price,
                                signal_source_id=headline_id,
                                confidence_score=inference["confidence"]
                            )
                            # Update in-memory state incrementally
                            self.portfolio_cash -= required_cost
                            if ticker not in self.portfolio_positions:
                                self.portfolio_positions[ticker] = {"shares": 0, "avg_price": 0.0}
                                
                            held = self.portfolio_positions[ticker]["shares"]
                            avg_price = self.portfolio_positions[ticker]["avg_price"]
                            total_cost = (held * avg_price) + required_cost
                            new_held = held + qty
                            self.portfolio_positions[ticker] = {
                                "shares": new_held,
                                "avg_price": total_cost / new_held
                            }
                            
                            # Update Prometheus metrics
                            TRADES_EXECUTED.labels(ticker=ticker, action="buy").inc()
                            PORTFOLIO_CASH.set(self.portfolio_cash)
                            POSITION_SHARES.labels(ticker=ticker).set(new_held)
                            
                            # Publish paper_trade event
                            trade_payload = {
                                "type": "paper_trade",
                                "data": {
                                    "trade_id": trade_id,
                                    "ticker": ticker,
                                    "action": "buy",
                                    "quantity": qty,
                                    "price": current_price,
                                    "executed_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(processed_at))
                                }
                            }
                            await self.redis_client.publish("sentistream:sentiment_events", json.dumps(trade_payload))
                
                elif trade_action == "sell":
                    if current_shares > 0:
                        # LIQUIDATE: Close the long position completely
                        qty = current_shares
                        trade_id = await self.trading_engine.execute_order(
                            ticker=ticker,
                            action="sell",
                            quantity=qty,
                            price_at_signal=current_price,
                            signal_source_id=headline_id,
                            confidence_score=inference["confidence"]
                        )
                        # Update in-memory state incrementally
                        proceeds = qty * current_price
                        self.portfolio_cash += proceeds
                        self.portfolio_positions.pop(ticker, None)
                        
                        # Update Prometheus metrics
                        TRADES_EXECUTED.labels(ticker=ticker, action="sell").inc()
                        PORTFOLIO_CASH.set(self.portfolio_cash)
                        POSITION_SHARES.labels(ticker=ticker).set(0)
                        
                        # Publish paper_trade event
                        trade_payload = {
                            "type": "paper_trade",
                            "data": {
                                "trade_id": trade_id,
                                "ticker": ticker,
                                "action": "sell",
                                "quantity": qty,
                                "price": current_price,
                                "executed_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(processed_at))
                            }
                        }
                        await self.redis_client.publish("sentistream:sentiment_events", json.dumps(trade_payload))
                    else:
                        if strategy_mode == "long_short":
                            # SHORT: Open or add to a short position (5% allocation)
                            trade_size = 0.05 * self.total_portfolio_value
                            qty = int(trade_size / current_price)
                            proceeds = qty * current_price
                            
                            if qty > 0:
                                trade_id = await self.trading_engine.execute_order(
                                    ticker=ticker,
                                    action="sell",
                                    quantity=qty,
                                    price_at_signal=current_price,
                                    signal_source_id=headline_id,
                                    confidence_score=inference["confidence"]
                                )
                                # Update in-memory state incrementally: proceeds added to cash, shares decreases
                                self.portfolio_cash += proceeds
                                if ticker not in self.portfolio_positions:
                                    self.portfolio_positions[ticker] = {"shares": 0, "avg_price": 0.0}
                                    
                                held_abs = abs(self.portfolio_positions[ticker]["shares"])
                                avg_price = self.portfolio_positions[ticker]["avg_price"]
                                total_cost = (held_abs * avg_price) + proceeds
                                new_held_abs = held_abs + qty
                                new_held = -new_held_abs
                                self.portfolio_positions[ticker] = {
                                    "shares": new_held,
                                    "avg_price": total_cost / new_held_abs
                                }
                                
                                # Update Prometheus metrics
                                TRADES_EXECUTED.labels(ticker=ticker, action="sell").inc()
                                PORTFOLIO_CASH.set(self.portfolio_cash)
                                POSITION_SHARES.labels(ticker=ticker).set(new_held)
                                
                                # Publish paper_trade event
                                trade_payload = {
                                    "type": "paper_trade",
                                    "data": {
                                        "trade_id": trade_id,
                                        "ticker": ticker,
                                        "action": "sell",
                                        "quantity": qty,
                                        "price": current_price,
                                        "executed_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(processed_at))
                                    }
                                }
                                await self.redis_client.publish("sentistream:sentiment_events", json.dumps(trade_payload))
                            else:
                                logger.warning("Short trade size quantity rounded down to 0", ticker=ticker)
                        else:
                            logger.info("Sell signal ignored because position is flat", ticker=ticker)

                # Recompute total portfolio value
                positions_mv = 0.0
                for tk, pos_data in self.portfolio_positions.items():
                    tk_price = await self.price_feed.get_price(tk)
                    positions_mv += pos_data["shares"] * tk_price
                self.total_portfolio_value = self.portfolio_cash + positions_mv
                
                # Update total portfolio value gauge
                PORTFOLIO_TOTAL_VALUE.set(self.total_portfolio_value)

            # 5. Broadcast real-time event to FastAPI clients via Redis Pub/Sub
            event_payload = {
                "type": "sentiment",
                "data": {
                    "id": headline_id,
                    "ticker": ticker,
                    "headline": headline_text,
                    "sentiment": inference["label"],
                    "confidence": inference["confidence"],
                    "latency_ms": round(inference["latency_ms"], 2),
                    "source": source,
                    "processed_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(processed_at)),
                    "model_version": model_version
                }
            }
            await self.redis_client.publish("sentistream:sentiment_events", json.dumps(event_payload))
            
            if drift_signal:
                alert_payload = {
                    "type": "drift_alert",
                    "data": {
                        "alert_id": drift_alert_id,
                        "ticker": ticker,
                        "z_score": drift_signal.z_score,
                        "direction": drift_signal.direction,
                        "alerted_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(processed_at))
                    }
                }
                await self.redis_client.publish("sentistream:sentiment_events", json.dumps(alert_payload))

            # 6. Acknowledge message as processed
            await self.redis_client.xack("raw_headlines", "sentistream_workers", message_id)
            logger.info("Successfully processed message", message_id=message_id, ticker=ticker, sentiment=inference["label"])

        except KeyError as e:
            ticker_label = fields.get("ticker", "UNKNOWN").strip().upper() if isinstance(fields, dict) else "UNKNOWN"
            HEADLINES_PROCESSED.labels(ticker=ticker_label, sentiment="unknown", status="error", model_version=model_version).inc()
            await self.route_to_dlq(message_id, fields, f"Missing required payload key: {str(e)}")
        except Exception as e:
            ticker_label = fields.get("ticker", "UNKNOWN").strip().upper() if isinstance(fields, dict) else "UNKNOWN"
            HEADLINES_PROCESSED.labels(ticker=ticker_label, sentiment="unknown", status="error", model_version=model_version).inc()
            await self.route_to_dlq(message_id, fields, f"Processing execution failed: {str(e)}")

    async def record_queue_backlogs(self):
        """Periodically records queue lengths for raw stream and DLQ into Prometheus gauges."""
        while self.is_running:
            try:
                if self.redis_client:
                    raw_len = await self.redis_client.xlen("raw_headlines")
                    dlq_len = await self.redis_client.xlen("dlq_headlines")
                    REDIS_STREAM_BACKLOG.set(raw_len)
                    DLQ_BACKLOG.set(dlq_len)

                # Reset Z-score gauge to 0.0 for quiet tickers to prevent stale values
                now = time.time()
                for ticker, last_time in list(self.last_headline_time.items()):
                    if now - last_time > 60.0:
                        ROLLING_Z_SCORE.labels(ticker=ticker).set(0.0)
                        if ticker in self.drift_detectors:
                            self.drift_detectors[ticker].last_z = 0.0
            except Exception as e:
                logger.error("Failed to query stream queue backlogs or reset quiet ticker gauges", error=str(e))
            await asyncio.sleep(5)

    async def start_consuming(self):
        """Starts the Redis consumer loop utilizing consumer group offsets."""
        logger.info("Consumer loop started. Reading stream raw_headlines...")
        
        # Start background queue backlog logging task
        self.backlog_task = asyncio.create_task(self.record_queue_backlogs())
        # Start background settings updates listener task
        self.settings_listener_task = asyncio.create_task(self.listen_settings_updates())
        
        while self.is_running:
            try:
                # Read from raw_headlines stream using consumer group
                # ">" means read only newly arrived messages that have not been read by other consumers
                # COUNT=10 processes up to 10 messages in a single batch
                # BLOCK=1000 blocks for 1000ms if the stream is empty
                response = await self.redis_client.xreadgroup(
                    groupname="sentistream_workers",
                    consumername=self.worker_name,
                    streams={"raw_headlines": ">"},
                    count=10,
                    block=1000
                )
                
                if not response:
                    continue
                    
                # Parse Redis stream response layout: [[stream_name, [[message_id, fields_dict]]]]
                for stream_name, messages in response:
                    for message_id, fields in messages:
                        await self.process_message(message_id, fields)
                        
            except aioredis.ConnectionError:
                logger.error("Redis Connection lost. Attempting reconnect in 5s...")
                await asyncio.sleep(5)
            except Exception as e:
                logger.critical("Critical error in consumer loop", error=str(e))
                await asyncio.sleep(1)

    async def close(self):
        """Gracefully shuts down database and broker connection clients."""
        logger.info("Gracefully closing Consumer Worker...")
        self.is_running = False
        if self.backlog_task:
            self.backlog_task.cancel()
            try:
                await self.backlog_task
            except asyncio.CancelledError:
                pass
        if self.settings_listener_task:
            self.settings_listener_task.cancel()
            try:
                await self.settings_listener_task
            except asyncio.CancelledError:
                pass
        if self.trading_engine and hasattr(self.trading_engine, "close"):
            await self.trading_engine.close()
        if self.price_feed:
            await self.price_feed.close()
        if self.redis_client:
            await self.redis_client.close()
        if self.db:
            await self.db.close()

async def main():
    worker_id = f"worker_{os.getpid()}"
    worker = ConsumerWorker(worker_id)
    await worker.initialize()
    try:
        await worker.start_consuming()
    except KeyboardInterrupt:
        logger.info("Worker stopped by user.")
    finally:
        await worker.close()

if __name__ == "__main__":
    asyncio.run(main())
