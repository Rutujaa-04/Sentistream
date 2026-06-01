import os
import sys
import asyncio
import json
import uuid
from typing import Set, Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import redis.asyncio as aioredis
import structlog

# Add parent directory to path to import properly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import settings
from app.database import ClickHouseDatabase
from app.model import SentimentModel

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)
logger = structlog.get_logger()

class ConnectionManager:
    def __init__(self):
        # Maps WebSocket connection to their registered subscription tickers
        # Empty set or None = subscribed to all tickers
        self.active_connections: Dict[WebSocket, Set[str]] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections[websocket] = set() # Start with no specific filter (default to all)
        logger.info("WebSocket client connected", count=len(self.active_connections))

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            del self.active_connections[websocket]
            logger.info("WebSocket client disconnected", count=len(self.active_connections))

    def subscribe(self, websocket: WebSocket, tickers: List[str]):
        """Registers a set of stock tickers for a specific client to filter broadcasts."""
        if websocket in self.active_connections:
            normalized = {ticker.strip().upper() for ticker in tickers if ticker.strip()}
            self.active_connections[websocket] = normalized
            logger.info("Client updated subscriptions", tickers=list(normalized))

    async def broadcast(self, event_type: str, data: dict):
        """Fans out the serialized event payload only to clients subscribed to the target ticker."""
        payload = {
            "type": event_type,
            "data": data
        }
        json_payload = json.dumps(payload)
        ticker = data.get("ticker", "SPY").upper()

        disconnected_clients = []
        for websocket, subscriptions in self.active_connections.items():
            # If subscriptions is empty, client receives all tickers. Otherwise, only matching tickers.
            if not subscriptions or ticker in subscriptions or ticker == "SPY":
                try:
                    await websocket.send_text(json_payload)
                except Exception:
                    disconnected_clients.append(websocket)

        # Clean up dead connections
        for client in disconnected_clients:
            self.disconnect(client)

manager = ConnectionManager()
db = ClickHouseDatabase()
redis_client: Optional[aioredis.Redis] = None
pubsub_task: Optional[asyncio.Task] = None

async def redis_pubsub_listener():
    """Background listener task that consumes from Redis Pub/Sub and broadcasts to WebSockets."""
    global redis_client
    logger.info("Starting Redis Pub/Sub listener task...")
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("sentistream:sentiment_events")
    
    try:
        async for message in pubsub.listen():
            if message["type"] != "message":
                continue
                
            payload = json.loads(message["data"])
            event_type = payload.get("type")
            data = payload.get("data")
            
            await manager.broadcast(event_type, data)
    except asyncio.CancelledError:
        logger.info("Redis Pub/Sub listener cancelled.")
    except Exception as e:
        logger.error("Error in Redis Pub/Sub listener", error=str(e))
    finally:
        await pubsub.unsubscribe("sentistream:sentiment_events")
        await pubsub.close()

# FastAPI Lifespan Context Manager
async def lifespan(app: FastAPI):
    global redis_client, pubsub_task
    logger.info("Bootstrapping SentiStream API Gateway...")
    
    # 1. Initialize and Warm ClickHouse Connections
    await db.initialize()
    
    # 2. Initialize Redis Connection Client
    redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
    await redis_client.ping()
    logger.info("Redis connection warmed up successfully.")
    
    # 3. Instantiate and Pre-load ONNX Model (Prevents first-request cold-start latency)
    try:
        _ = SentimentModel()
        logger.info("Sentiment ONNX Model pre-loaded successfully.")
    except Exception as e:
        logger.critical("Model load failed during startup", error=str(e))
        
    # 4. Start Redis Pub/Sub Listener Task
    pubsub_task = asyncio.create_task(redis_pubsub_listener())
    
    yield
    
    # Graceful Shutdown
    logger.info("Shutting down SentiStream API Gateway...")
    if pubsub_task:
        pubsub_task.cancel()
        try:
            await pubsub_task
        except asyncio.CancelledError:
            pass
    if redis_client:
        await redis_client.close()
    await db.close()

app = FastAPI(
    title="SentiStream API",
    description="Real-Time Sentiment Analytics & Quantitative Observability Gateway",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS restricted to Vite Dev Server
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==========================================
# REST DIAGNOSTICS & HEALTH
# ==========================================

@app.get("/ping")
async def ping():
    """Active connection warmup validation check."""
    t0 = time.perf_counter()
    try:
        # Validate ClickHouse
        await asyncio.to_thread(db.client.execute, "SELECT 1")
        # Validate Redis
        await redis_client.ping()
        latency = (time.perf_counter() - t0) * 1000.0
        
        return {
            "status": "ok",
            "clickhouse": "warm",
            "redis": "warm",
            "onnx_model": "loaded",
            "latency_ms": round(latency, 2)
        }
    except Exception as e:
        logger.error("Warmup ping check degraded", error=str(e))
        raise HTTPException(
            status_code=503, 
            detail={"status": "degraded", "error": str(e)}
        )

@app.get("/health")
async def health():
    """Returns granular health metrics across pipeline backup nodes."""
    try:
        # ClickHouse row count
        rows = await asyncio.to_thread(db.client.execute, "SELECT count() FROM headlines")
        ch_rows = rows[0][0] if rows else 0
        
        # Redis stream depth
        stream_len = await redis_client.xlen("raw_headlines")
        dlq_len = await redis_client.xlen("dlq_headlines")
        
        return {
            "status": "healthy",
            "components": {
                "redis": {
                    "status": "ok",
                    "stream_length": stream_len,
                    "dlq_length": dlq_len
                },
                "clickhouse": {
                    "status": "ok",
                    "rows_7d": ch_rows
                },
                "onnx": {
                    "status": "ok",
                    "model": "finbert-int8"
                }
            }
        }
    except Exception as e:
        logger.error("System health check failed", error=str(e))
        raise HTTPException(
            status_code=503,
            detail={"status": "unhealthy", "error": str(e)}
        )

# ==========================================
# TIME-SERIES ANALYTICS ENDPOINTS
# ==========================================

@app.get("/api/v1/latency-percentiles")
async def get_latency_percentiles(window: str = Query(default="1h", pattern="^(1h|6h|24h)$")):
    """Retrieves real-time processing latency benchmarks aggregated by 1-minute buckets."""
    hours = 1
    if window == "6h":
        hours = 6
    elif window == "24h":
        hours = 24
        
    try:
        data = await db.query_latency_percentiles(window_hours=hours)
        return {
            "window": window,
            "data": data
        }
    except Exception as e:
        logger.error("Failed to query latency percentiles", error=str(e))
        raise HTTPException(status_code=500, detail="ClickHouse query failed.")

@app.get("/api/v1/sentiment-trends")
async def get_sentiment_trends(
    ticker: Optional[str] = Query(default=None),
    hours: int = Query(default=6, ge=1, le=24)
):
    """Retrieves rolling sentiment buckets aggregated by minute."""
    try:
        data = await db.query_sentiment_trends(ticker=ticker, hours=hours)
        return {
            "ticker": ticker,
            "hours": hours,
            "data": data
        }
    except Exception as e:
        logger.error("Failed to query sentiment trends", error=str(e))
        raise HTTPException(status_code=500, detail="ClickHouse query failed.")

@app.get("/api/v1/drift-alerts")
async def get_drift_alerts(
    ticker: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200)
):
    """Retrieves sparse statistical drift alerts from storage."""
    try:
        data = await db.query_drift_alerts(ticker=ticker, limit=limit)
        return {
            "ticker": ticker,
            "alerts": data
        }
    except Exception as e:
        logger.error("Failed to query drift alerts", error=str(e))
        raise HTTPException(status_code=500, detail="ClickHouse query failed.")

@app.get("/api/v1/portfolio")
async def get_portfolio_summary():
    """Retrieves simulated paper trading portfolio and P&L results."""
    try:
        data = await db.query_portfolio_summary()
        return data
    except Exception as e:
        logger.error("Failed to query portfolio summary", error=str(e))
        raise HTTPException(status_code=500, detail="ClickHouse query failed.")

# ==========================================
# WEBSOCKET STREAMING GATEWAY
# ==========================================

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Manages full duplex real-time client WebSocket sessions."""
    await manager.connect(websocket)
    try:
        while True:
            # Handle incoming client messages (e.g., subscription changes)
            text_data = await websocket.receive_text()
            try:
                message = json.loads(text_data)
                msg_type = message.get("type")
                
                if msg_type == "subscribe":
                    tickers = message.get("tickers", [])
                    manager.subscribe(websocket, tickers)
                    # Respond with acknowledgment
                    await websocket.send_text(json.dumps({
                        "type": "subscribed",
                        "tickers": tickers
                    }))
            except json.JSONDecodeError:
                logger.warning("WebSocket client sent malformed JSON")
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception as e:
        logger.error("Error in WebSocket session", error=str(e))
        manager.disconnect(websocket)
