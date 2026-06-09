import json
import os
import sys
import time
import uuid
from typing import Optional

import aiohttp
import redis.asyncio as aioredis
import structlog

# Add parent directory to path to import properly
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app.config import settings
from app.database import ClickHouseDatabase
from app.trading.base_engine import BaseExecutionEngine

logger = structlog.get_logger()

class AlpacaExecutionEngine(BaseExecutionEngine):
    """
    Adapter demonstrating how to execute trades via the real Alpaca Brokerage API.
    This illustrates the power of Hexagonal Architecture: we can swap our local 
    simulation for real market transactions without changing our core pipeline logic.
    """
    def __init__(self):
        self.db: Optional[ClickHouseDatabase] = None
        self.redis_client: Optional[aioredis.Redis] = None
        self.session: Optional[aiohttp.ClientSession] = None
        
        # Alpaca Paper Trading Credentials
        self.api_key = settings.ALPACA_API_KEY
        self.api_secret = settings.ALPACA_API_SECRET
        self.base_url = "https://paper-api.alpaca.markets/v2"

    async def initialize(self):
        """Initializes API sessions, databases, and message brokers."""
        logger.info("Initializing Alpaca Brokerage Trading Engine...", base_url=self.base_url)
        self.db = ClickHouseDatabase()
        await self.db.initialize()
        
        self.redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        self.session = aiohttp.ClientSession()

    async def execute_order(
        self,
        ticker: str,
        action: str,
        quantity: int,
        price_at_signal: float,
        signal_source_id: str,
        confidence_score: float
    ) -> str:
        """
        Submits a market order directly to Alpaca's paper trading API, 
        persists the execution details in ClickHouse, and broadcasts it.
        """
        if not self.api_key or not self.api_secret:
            logger.error("Alpaca API credentials missing. Falling back to local simulation logic.")
            # Self-contained fallback: execute locally so the pipeline never breaks
            trade_id = str(uuid.uuid4())
            await self.db.insert_paper_trade(
                trade_id=trade_id,
                ticker=ticker,
                action=action,
                quantity=quantity,
                price_at_signal=price_at_signal,
                signal_source=signal_source_id,
                confidence_score=confidence_score
            )
            return f"simulated_fallback_{trade_id}"

        # 1. Prepare Alpaca Order Request Payload
        url = f"{self.base_url}/orders"
        headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "Content-Type": "application/json"
        }
        
        order_payload = {
            "symbol": ticker.upper(),
            "qty": str(quantity),
            "side": action.lower(),  # buy | sell
            "type": "market",
            "time_in_force": "day"
        }

        logger.info("Submitting order to Alpaca API", ticker=ticker, action=action.upper(), qty=quantity)
        
        try:
            # 2. Submit order request to Alpaca Broker
            async with self.session.post(url, headers=headers, json=order_payload, timeout=10) as response:
                if response.status not in (200, 201):
                    error_text = await response.text()
                    logger.error("Alpaca API rejected order", status=response.status, detail=error_text)
                    raise ConnectionError(f"Alpaca API error: {error_text}")
                    
                data = await response.json()
                alpaca_order_id = data.get("id")
                logger.info("Order successfully executed on Alpaca paper broker", order_id=alpaca_order_id)
                
            # 3. Log trade execution in local ClickHouse database
            await self.db.insert_paper_trade(
                trade_id=alpaca_order_id,
                ticker=ticker,
                action=action,
                quantity=quantity,
                price_at_signal=price_at_signal,
                signal_source=signal_source_id,
                confidence_score=confidence_score
            )

            # 4. Publish real-time transaction event via Redis Pub/Sub
            event_payload = {
                "type": "paper_trade",
                "data": {
                    "trade_id": alpaca_order_id,
                    "ticker": ticker,
                    "action": action,
                    "quantity": quantity,
                    "price": price_at_signal,
                    "executed_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
                }
            }
            await self.redis_client.publish("sentistream:sentiment_events", json.dumps(event_payload))
            return alpaca_order_id

        except Exception as e:
            logger.error("Alpaca execution adapter failed", error=str(e))
            raise e

    async def close(self):
        """Gracefully closes all open HTTP, database, and Redis connections."""
        logger.info("Closing Alpaca adapter...")
        if self.session:
            await self.session.close()
        if self.redis_client:
            await self.redis_client.close()
        if self.db:
            await self.db.close()
