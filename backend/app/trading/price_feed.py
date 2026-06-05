import os
import sys
import time
from typing import Dict, Tuple

import aiohttp
import structlog

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import settings

logger = structlog.get_logger()

class PriceFeed:
    _instance = None

    def __new__(cls, *args, **kwargs):
        if not cls._instance:
            cls._instance = super(PriceFeed, cls).__new__(cls, *args, **kwargs)
        return cls._instance

    def __init__(self):
        # Prevent re-initialization if __init__ is called multiple times on the singleton
        if not hasattr(self, "initialized"):
            self.cache: Dict[str, Tuple[float, float]] = {}  # ticker -> (price, timestamp)
            self.session = None
            self.api_key = settings.FINNHUB_API_KEY
            self.fallback_prices = {
                "SPY": 530.0,
                "AAPL": 210.0,
                "TSLA": 250.0,
                "NVDA": 950.0
            }
            self.initialized = True

    async def initialize(self):
        """Initializes client session if not already active."""
        if not self.session:
            self.session = aiohttp.ClientSession()

    async def close(self):
        """Closes HTTP client session."""
        if self.session:
            await self.session.close()
            self.session = None

    async def get_price(self, ticker: str) -> float:
        """
        Retrieves the price for a stock ticker, using an in-memory 30-second cache,
        polling Finnhub quote API as primary and falling back to mock prices on error.
        """
        ticker = ticker.strip().upper()
        now = time.time()

        # 1. Check cache first
        if ticker in self.cache:
            cached_price, cached_time = self.cache[ticker]
            if now - cached_time < 30.0:
                logger.info("Serving price from cache", ticker=ticker, price=cached_price)
                return cached_price

        # 2. Query Finnhub quote API
        if self.api_key:
            url = f"https://finnhub.io/api/v1/quote?symbol={ticker}&token={self.api_key}"
            try:
                if not self.session:
                    self.session = aiohttp.ClientSession()
                async with self.session.get(url, timeout=5) as response:
                    if response.status == 200:
                        data = await response.json()
                        current_price = data.get("c")
                        # Validate response has a positive current price
                        if current_price is not None and isinstance(current_price, (int, float)) and current_price > 0.0:
                            self.cache[ticker] = (float(current_price), now)
                            logger.info("Fetched live quote from Finnhub API", ticker=ticker, price=current_price)
                            return float(current_price)
                        else:
                            logger.warning("Finnhub quote API returned invalid price structure", ticker=ticker, data=data)
                    elif response.status == 429:
                        logger.warning("Finnhub quote API rate limit hit (429)", ticker=ticker)
                    else:
                        logger.warning("Finnhub quote API returned non-200 status", ticker=ticker, status=response.status)
            except Exception as e:
                logger.warning("Finnhub quote API lookup crashed", ticker=ticker, error=str(e))
        else:
            logger.warning("Finnhub API key missing, quote query skipping to fallback", ticker=ticker)

        # 3. Fallback to mock prices
        fallback_price = self.fallback_prices.get(ticker, 150.0)
        # Cache mock prices to avoid warning spam
        self.cache[ticker] = (fallback_price, now)
        logger.warning("Serving mock fallback price (warning: stale metrics)", ticker=ticker, price=fallback_price)
        return fallback_price
