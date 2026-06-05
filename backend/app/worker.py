import asyncio
import json
import os
import sys
import time
import uuid
from typing import Any, Dict, Optional

import redis.asyncio as aioredis
import structlog

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
        
        # Registry of drift detectors isolated by ticker to prevent contamination
        self.drift_detectors: Dict[str, DriftDetector] = {}
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

        # 5. Cold-start in-memory portfolio state from ClickHouse trade logs
        portfolio_state = await self.portfolio_service.reconstruct_portfolio()
        self.portfolio_cash = float(portfolio_state["cash_usd"])
        self.portfolio_positions = {
            pos["ticker"]: {"shares": int(pos["shares"]), "avg_price": float(pos["avg_price"])}
            for pos in portfolio_state["positions"]
        }
        self.total_portfolio_value = float(portfolio_state["portfolio_value_usd"])
        logger.info(
            "Worker portfolio state cold-started successfully",
            cash=self.portfolio_cash,
            positions=self.portfolio_positions,
            total_value=self.total_portfolio_value
        )
        
        # 6. Initialize Hexagonal Trading Adapter based on config
        engine_type = os.environ.get("TRADING_ENGINE", "simulated").lower()
        if engine_type == "alpaca":
            self.trading_engine = AlpacaExecutionEngine()
        else:
            self.trading_engine = SimulatedExecutionEngine()
        await self.trading_engine.initialize()
        
        # 7. Ensure Redis Consumer Group exists
        await self.setup_consumer_group()

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

    async def process_message(self, message_id: str, fields: dict):
        """Orchestrates the lifecycle of a single financial news headline message."""
        t_total_start = time.perf_counter()
        
        try:
            # 1. Deserialize message payload
            headline_id = fields["id"]
            ticker = fields["ticker"].strip().upper()
            headline_text = fields["headline_text"]
            source = fields["source"]
            ingested_at = float(fields["ingested_at"])
            
            # 2. Run Quantized ONNX Inference
            inference = self.model.infer(headline_text)
            
            # 3. Calculate Statistical Sentiment Drift
            # Convert label to numeric score for math calculations: pos=1.0, neg=-1.0, neu=0.0
            sentiment_score = 0.0
            if inference["label"] == "positive":
                sentiment_score = 1.0
            elif inference["label"] == "negative":
                sentiment_score = -1.0
                
            detector = self.get_drift_detector(ticker)
            drift_signal = detector.update(sentiment_score, ticker)
            
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
                processed_at=processed_at
            )
            
            # B. Write Telemetry Metrics
            t_total_end = time.perf_counter()
            total_latency = (t_total_end - t_total_start) * 1000.0
            
            await self.db.insert_telemetry(
                headline_id=headline_id,
                inference_latency_ms=inference["latency_ms"],
                tokenization_latency_ms=inference["tokenization_latency_ms"],
                total_latency_ms=total_latency,
                worker_id=self.worker_name
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
                logger.warning(
                    "Statistical Sentiment Drift Alert triggered", 
                    ticker=ticker, 
                    z_score=drift_signal.z_score, 
                    direction=drift_signal.direction
                )

            # D. Execute Paper Trade Order if strategy triggers a signal
            trade_action = self.strategy.should_trade(ticker, inference["label"], inference["confidence"])
            if trade_action:
                current_price = await self.price_feed.get_price(ticker)
                
                if trade_action == "buy":
                    # Allocate 5% of total capital per trade
                    trade_size = 0.05 * self.total_portfolio_value
                    qty = int(trade_size / current_price)
                    required_cost = qty * current_price
                    
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
                    # Liquidate entire position of ticker
                    if ticker in self.portfolio_positions and self.portfolio_positions[ticker]["shares"] > 0:
                        qty = self.portfolio_positions[ticker]["shares"]
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
                        logger.info("Sell signal ignored because position is flat", ticker=ticker)

                # Recompute total portfolio value
                positions_mv = 0.0
                for tk, pos_data in self.portfolio_positions.items():
                    tk_price = await self.price_feed.get_price(tk)
                    positions_mv += pos_data["shares"] * tk_price
                self.total_portfolio_value = self.portfolio_cash + positions_mv

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
                    "processed_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(processed_at))
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
            await self.route_to_dlq(message_id, fields, f"Missing required payload key: {str(e)}")
        except Exception as e:
            await self.route_to_dlq(message_id, fields, f"Processing execution failed: {str(e)}")

    async def start_consuming(self):
        """Starts the Redis consumer loop utilizing consumer group offsets."""
        logger.info("Consumer loop started. Reading stream raw_headlines...")
        
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
