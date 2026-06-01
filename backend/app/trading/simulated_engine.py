import os
import sys
import uuid
import time
import json
from typing import Optional
import redis.asyncio as aioredis
import structlog

# Add parent directory to path to import properly
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from app.config import settings
from app.trading.base_engine import BaseExecutionEngine
from app.database import ClickHouseDatabase

logger = structlog.get_logger()

class SimulatedExecutionEngine(BaseExecutionEngine):
    def __init__(self):
        self.db: Optional[ClickHouseDatabase] = None
        self.redis_client: Optional[aioredis.Redis] = None

    async def initialize(self):
        """Initializes database and broker connection clients."""
        logger.info("Initializing Simulated Trading Execution Engine...")
        self.db = ClickHouseDatabase()
        await self.db.initialize()
        self.redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)

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
        Executes a simulated paper trade, persists it in ClickHouse, 
        and publishes a real-time event via Redis Pub/Sub.
        """
        trade_id = str(uuid.uuid4())
        executed_at = time.time()
        
        logger.info(
            "Simulating trade order execution",
            trade_id=trade_id,
            ticker=ticker,
            action=action.upper(),
            quantity=quantity,
            price=price_at_signal
        )
        
        try:
            # 1. Persist the trade record in ClickHouse
            await self.db.insert_paper_trade(
                trade_id=trade_id,
                ticker=ticker,
                action=action,
                quantity=quantity,
                price_at_signal=price_at_signal,
                signal_source=signal_source_id,
                confidence_score=confidence_score
            )
            
            # 2. Publish real-time event to Redis Pub/Sub for WebSockets dashboard fanning
            event_payload = {
                "type": "paper_trade",
                "data": {
                    "trade_id": trade_id,
                    "ticker": ticker,
                    "action": action,
                    "quantity": quantity,
                    "price": price_at_signal,
                    "executed_at": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(executed_at))
                }
            }
            await self.redis_client.publish("sentistream:sentiment_events", json.dumps(event_payload))
            logger.info("Successfully executed and published simulated trade", trade_id=trade_id)
            
        except Exception as e:
            logger.error("Failed to execute simulated trade", trade_id=trade_id, error=str(e))
            raise e
            
        return trade_id
