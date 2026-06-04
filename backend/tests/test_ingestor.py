import uuid

import pytest
import redis.asyncio as aioredis
from app.config import settings
from app.ingestor import NewsIngestor, compute_hash


def test_dedup_hash_deterministic():
    # Hash for identical headline + ticker must be deterministic
    h1 = compute_hash("Apple beats earnings expectations by 5%.", "AAPL")
    h2 = compute_hash("Apple beats earnings expectations by 5%.", "AAPL")
    assert h1 == h2
    
    # Hash for different headline or ticker must vary
    h3 = compute_hash("Apple beats earnings expectations by 5%.", "TSLA")
    h4 = compute_hash("Tesla beats earnings expectations by 5%.", "TSLA")
    assert h1 != h3
    assert h3 != h4

@pytest.mark.asyncio
async def test_seen_deduplication():
    # Setup Redis client using our configured url
    try:
        redis_client = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        await redis_client.ping()
    except Exception:
        pytest.skip("Local Redis server is offline. Skipping Redis-based deduplication test.")

    # Initialize a temporary ingestor instance
    ingestor = NewsIngestor()
    ingestor.redis_client = redis_client
    
    # Generate unique test hash to avoid conflicts
    test_hash = f"test_{uuid.uuid4().hex}"
    
    try:
        # First check: should be unrecognized (not seen, returns False)
        is_seen1 = await ingestor.check_seen(test_hash)
        assert is_seen1 is False
        
        # Second check: should be recognized (seen, returns True)
        is_seen2 = await ingestor.check_seen(test_hash)
        assert is_seen2 is True
    finally:
        # Clean up test key and close connection
        await redis_client.delete(f"sentistream:seen:{test_hash}")
        await redis_client.close()
