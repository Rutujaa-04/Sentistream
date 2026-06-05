import time
import uuid
from locust import User, HttpUser, task, between
import redis
from backend.app.config import settings

class RedisPipelineUser(User):
    # Simulates the news ingestion pipeline writing to Redis stream.
    # At 100 messages/min in total, if we run with 1 user, wait_time should be ~0.6 seconds.
    wait_time = between(0.55, 0.65)

    def on_start(self):
        # Initialize Redis connection from config url
        self.redis_client = redis.Redis.from_url(settings.REDIS_URL, decode_responses=True)

    @task
    def push_headline(self):
        tickers = ["AAPL", "TSLA", "NVDA", "SPY"]
        headlines = [
            "Apple hits record high on AI optimism.",
            "Tesla autopilot recall affects 200k vehicles.",
            "NVIDIA Blackwell chips face shipping delay.",
            "Federal Reserve hints at interest rate cuts."
        ]
        
        # Pick a random ticker and headline
        idx = int(time.time_ns())
        ticker = tickers[idx % len(tickers)]
        text = headlines[idx % len(headlines)]
        
        payload = {
            "id": str(uuid.uuid4()),
            "ticker": ticker,
            "headline_text": text,
            "source": "locust_load_tester",
            "ingested_at": str(time.time())
        }
        
        start_time = time.perf_counter()
        try:
            # Write to raw_headlines stream
            self.redis_client.xadd("raw_headlines", payload, maxlen=1000, approximate=True)
            total_time = int((time.perf_counter() - start_time) * 1000)
            
            # Fire success event to Locust reporting with exact names requested by user
            self.environment.events.request.fire(
                request_type="redis_xadd",
                name="raw_headlines",
                response_time=total_time,
                response_length=0,
                exception=None
            )
        except Exception as e:
            total_time = int((time.perf_counter() - start_time) * 1000)
            self.environment.events.request.fire(
                request_type="redis_xadd",
                name="raw_headlines",
                response_time=total_time,
                response_length=0,
                exception=e
            )

class FastAPIUser(HttpUser):
    # Simulates active dashboard clients querying FastAPI REST endpoints.
    wait_time = between(1.0, 3.0)

    @task(3)
    def get_headlines(self):
        self.client.get("/api/v1/headlines?limit=20")

    @task(2)
    def get_portfolio(self):
        self.client.get("/api/v1/portfolio")

    @task(2)
    def get_latency(self):
        self.client.get("/api/v1/latency-percentiles?window=1h")

    @task(1)
    def get_metrics(self):
        self.client.get("/metrics")
