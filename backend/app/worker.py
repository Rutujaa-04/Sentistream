import os
import sys
import asyncio
import json
import time
import uuid
from typing import Optional, Dict
import redis.asyncio as aioredis
import structlog
from pydantic import ValidationError

# Add parent directory to path to import properly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import settings
from app.model import SentimentModel
from app.drift import DriftDetector
from app.database import ClickHouseDatabase

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
        
        # 4. Ensure Redis Consumer Group exists
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
