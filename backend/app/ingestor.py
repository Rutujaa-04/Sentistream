import asyncio
import os
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

import aiohttp
import feedparser
import redis.asyncio as aioredis
import structlog
from pydantic import BaseModel

# Import configurations
# Add parent directory to path to import properly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import settings

# Initialize structured logging
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer()
    ]
)
logger = structlog.get_logger()

# RSS Feeds for Fallback Ingestion
RSS_FEEDS = [
    "https://www.marketwatch.com/rss/marketupdate",
    "https://finance.yahoo.com/news/rssindex",
]

class IngestedHeadline(BaseModel):
    id: str  # SHA-256 hash of headline_text + ticker
    ticker: str
    headline_text: str
    source: str
    ingested_at: float  # Unix timestamp

def compute_hash(text: str, ticker: str) -> str:
    """Computes a unique, deterministic version 5 UUID for database and deduplication."""
    namespace = uuid.NAMESPACE_DNS
    name = f"{text.strip().lower()}:{ticker.strip().upper()}"
    return str(uuid.uuid5(namespace, name))

class NewsIngestor:
    def __init__(self):
        self.redis_client: Optional[aioredis.Redis] = None
        self.session: Optional[aiohttp.ClientSession] = None
        self.rss_fallback_active = False
        
    async def initialize(self):
        """Initializes connection clients."""
        logger.info("Initializing News Ingestor clients...", redis_url=settings.REDIS_URL)
        self.redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        self.session = aiohttp.ClientSession()
        
    async def close(self):
        """Gracefully closes all open connections."""
        logger.info("Closing Ingestor clients...")
        if self.session:
            await self.session.close()
        if self.redis_client:
            await self.redis_client.close()

    async def check_seen(self, headline_hash: str) -> bool:
        """Atomic seen check via Redis SETNX with a 24-hour expiration."""
        key = f"sentistream:seen:{headline_hash}"
        # Set if not exists, expire in 24 hours (86400 seconds)
        is_new = await self.redis_client.set(key, "1", ex=86400, nx=True)
        return not is_new  # If set succeeded, it is NOT seen (False), otherwise it IS seen (True)

    async def fetch_finnhub_news(self) -> List[Dict[str, Any]]:
        """Fetches general financial news headlines from the Finnhub API."""
        if not settings.FINNHUB_API_KEY:
            raise ValueError("FINNHUB_API_KEY is not configured.")

        url = f"https://finnhub.io/api/v1/news?category=general&token={settings.FINNHUB_API_KEY}"
        
        async with self.session.get(url, timeout=10) as response:
            if response.status == 429:
                logger.warning("Finnhub API rate limited (429). Triggering RSS fallback.")
                self.rss_fallback_active = True
                return []
            elif response.status != 200:
                logger.warning("Finnhub API error", status=response.status)
                self.rss_fallback_active = True
                return []
                
            data = await response.json()
            # If successfully fetched news, reset fallback flag
            if self.rss_fallback_active:
                logger.info("Finnhub recovered. Deactivating RSS fallback.")
                self.rss_fallback_active = False
            return data

    async def fetch_rss_news(self) -> List[Dict[str, Any]]:
        """Parses fallbacks from major financial RSS feeds using feedparser."""
        logger.info("Fetching headlines via financial RSS feeds...")
        headlines = []
        
        for feed_url in RSS_FEEDS:
            try:
                # feedparser is blocking, so execute in an async executor thread
                loop = asyncio.get_event_loop()
                feed = await loop.run_in_executor(None, feedparser.parse, feed_url)
                
                for entry in feed.entries[:20]:  # Limit to top 20 items per feed
                    # Normalize RSS fields to Finnhub equivalent schema
                    headline_text = entry.title if hasattr(entry, "title") else ""
                    # RSS headlines do not target specific stocks, so assign general market ticker (SPY)
                    ticker = "SPY"
                    if not headline_text:
                        continue
                        
                    headlines.append({
                        "headline": headline_text,
                        "datetime": time.time(),
                        "related": ticker,
                        "source": "rss_fallback"
                    })
            except Exception as e:
                logger.error("Error parsing RSS feed", url=feed_url, error=str(e))
                
        return headlines

    async def publish_to_stream(self, headline: IngestedHeadline):
        """Serializes and publishes the headline to the Redis raw_headlines stream."""
        payload = {
            "id": headline.id,
            "ticker": headline.ticker,
            "headline_text": headline.headline_text,
            "source": headline.source,
            "ingested_at": str(headline.ingested_at)
        }
        
        # MAXLEN ~ 1000 maintains memory bounds on free-tier Redis
        await self.redis_client.xadd(
            name="raw_headlines",
            fields=payload,
            maxlen=1000,
            approximate=True
        )
        logger.info(
            "Published headline to Redis Stream", 
            ticker=headline.ticker, 
            headline_text=headline.headline_text[:50], 
            source=headline.source
        )

    async def run_pipeline(self):
        """Core execution loop of the ingestion pipeline."""
        logger.info("Starting ingestion loop...", poll_interval=settings.POLL_INTERVAL)
        
        while True:
            try:
                raw_headlines = []
                
                # Determine source based on failover status
                if self.rss_fallback_active or not settings.FINNHUB_API_KEY:
                    raw_headlines = await self.fetch_rss_news()
                else:
                    try:
                        raw_headlines = await self.fetch_finnhub_news()
                    except Exception as e:
                        logger.error("Finnhub fetch crashed. Falling back to RSS.", error=str(e))
                        self.rss_fallback_active = True
                        raw_headlines = await self.fetch_rss_news()

                # Process, deduplicate and stream new headlines
                new_count = 0
                for item in raw_headlines:
                    headline_text = item.get("headline", "").strip()
                    ticker = item.get("related", "SPY").strip().upper()
                    
                    if not headline_text:
                        continue
                        
                    headline_hash = compute_hash(headline_text, ticker)
                    
                    # Deduplication check
                    is_seen = await self.check_seen(headline_hash)
                    if is_seen:
                        continue
                        
                    # Create and validate schema
                    headline_obj = IngestedHeadline(
                        id=headline_hash,
                        ticker=ticker,
                        headline_text=headline_text,
                        source=item.get("source", "finnhub"),
                        ingested_at=float(item.get("datetime", time.time()))
                    )
                    
                    # Publish to Redis Stream
                    await self.publish_to_stream(headline_obj)
                    new_count += 1
                    
                logger.info("Ingestion iteration completed", total_processed=len(raw_headlines), newly_ingested=new_count)
                
            except Exception as e:
                logger.error("Ingestion loop encountered error", error=str(e))
                
            # Wait for next polling cycle
            await asyncio.sleep(settings.POLL_INTERVAL)

async def main():
    # If a Finnhub API Key is not set, warn the user
    if not settings.FINNHUB_API_KEY:
        logger.warning(
            "FINNHUB_API_KEY is empty. The ingestor will run exclusively in OFFLINE/RSS Fallback mode.",
            rss_feeds=RSS_FEEDS
        )
        
    ingestor = NewsIngestor()
    await ingestor.initialize()
    try:
        await ingestor.run_pipeline()
    except KeyboardInterrupt:
        logger.info("Ingestor stopped by user.")
    finally:
        await ingestor.close()

if __name__ == "__main__":
    asyncio.run(main())
