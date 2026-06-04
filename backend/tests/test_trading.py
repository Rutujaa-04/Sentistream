import pytest
import time
import json
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch, ANY

from app.trading.strategy import ThresholdStrategy
from app.trading.price_feed import PriceFeed
from app.trading.portfolio_service import PortfolioService
from app.worker import ConsumerWorker
from app.config import settings

def test_threshold_strategy_logic():
    # Cooldown is 1s to make testing easy
    strategy = ThresholdStrategy(threshold=0.75, cooldown_seconds=1.0)
    
    # 1. Under threshold should return None
    assert strategy.should_trade("AAPL", "positive", 0.74) is None
    
    # 2. Above threshold should return buy
    assert strategy.should_trade("AAPL", "positive", 0.76) == "buy"
    
    # 3. Cooldown should suppress subsequent trade immediately
    assert strategy.should_trade("AAPL", "positive", 0.85) is None
    
    # 4. Different ticker should not be throttled by AAPL's cooldown
    assert strategy.should_trade("TSLA", "positive", 0.85) == "buy"
    
    # 5. Sleep past cooldown duration
    time.sleep(1.1)
    assert strategy.should_trade("AAPL", "negative", 0.80) == "sell"

@pytest.mark.asyncio
async def test_price_feed_caching_and_fallback():
    feed = PriceFeed()
    # Reset internal states to prevent contamination
    feed.cache = {}
    feed.api_key = "dummy-key"
    
    # Mock self.session
    mock_session = MagicMock()
    feed.session = mock_session
    
    # Mock session get response
    mock_resp = AsyncMock()
    mock_resp.status = 200
    mock_resp.json.return_value = {"c": 215.5}
    
    # Custom async context manager mock
    class AsyncContextManagerMock:
        async def __aenter__(self):
            return mock_resp
        async def __aexit__(self, exc_type, exc, tb):
            pass
            
    mock_session.get.return_value = AsyncContextManagerMock()
    
    # First lookup should query Finnhub
    price1 = await feed.get_price("AAPL")
    assert price1 == 215.5
    assert mock_session.get.call_count == 1
    
    # Second lookup should serve from cache (mock session get should NOT be called again)
    price2 = await feed.get_price("AAPL")
    assert price2 == 215.5
    assert mock_session.get.call_count == 1
    
    # Check fallback behavior when Finnhub fails
    mock_resp.status = 500
    # Clear cache for AAPL to force a fetch
    feed.cache.pop("AAPL")
    price_fallback = await feed.get_price("AAPL")
    # Modern mock fallback price for AAPL is 210.0
    assert price_fallback == 210.0

@pytest.mark.asyncio
async def test_portfolio_service_reconstruction():
    # 1. Setup mock ClickHouse database
    mock_db = MagicMock()
    # Seed a known sequence of trades
    mock_db.query_raw_trades = AsyncMock(return_value=[
        {"ticker": "AAPL", "action": "buy", "quantity": 100, "price": 200.0},
        {"ticker": "AAPL", "action": "buy", "quantity": 50, "price": 210.0},
        {"ticker": "AAPL", "action": "sell", "quantity": 150, "price": 220.0},
        {"ticker": "TSLA", "action": "buy", "quantity": 10, "price": 250.0}
    ])
    
    # 2. Setup mock PriceFeed returning a higher price for TSLA ($260)
    mock_price_feed = MagicMock()
    mock_price_feed.get_price = AsyncMock(return_value=260.0)
    
    service = PortfolioService(mock_db, mock_price_feed)
    state = await service.reconstruct_portfolio()
    
    # 3. Assertions matching mathematically exact sequence
    # Initial Cash = 100,000
    # Buy 100 AAPL at 200 -> Cash 80,000
    # Buy 50 AAPL at 210 -> Cash 69,500
    # Sell 150 AAPL at 220 -> Cash 102,500. Cost basis: 100*200 + 50*210 = 30,500. Avg Cost = 30,500/150 = 203.333
    # Realized Profit = 150 * (220 - 203.333) = 150*220 - 30,500 = 33,000 - 30,500 = +2,500 realized P&L
    # Closed trade counts as a win.
    # Buy 10 TSLA at 250 -> Cash 100,000. Open Position: 10 shares of TSLA at cost basis 2,500
    # Current TSLA price = 260 -> Market Value = 2,600. Unrealized P&L = 2,600 - 2,500 = +100
    # Total Portfolio Value = Cash (100,000) + MV (2,600) = 102,600
    assert state["cash_usd"] == 100000.0
    assert state["realized_pnl_usd"] == 2500.0
    assert state["win_rate"] == 1.0
    assert state["unrealized_pnl_usd"] == 100.0
    assert state["portfolio_value_usd"] == 102600.0
    
    # Open positions detail checking
    assert len(state["positions"]) == 1
    tsla_pos = state["positions"][0]
    assert tsla_pos["ticker"] == "TSLA"
    assert tsla_pos["shares"] == 10
    assert tsla_pos["avg_price"] == 250.0
    assert tsla_pos["current_price"] == 260.0
    assert tsla_pos["market_value"] == 2600.0
    assert tsla_pos["unrealized_pnl"] == 100.0

@pytest.mark.asyncio
async def test_worker_insufficient_capital():
    worker = ConsumerWorker("test_worker")
    worker.redis_client = AsyncMock()
    worker.trading_engine = AsyncMock()
    worker.price_feed = AsyncMock()
    worker.strategy = MagicMock()
    
    # Set worker in-memory cash to 0.0 (too low to buy)
    worker.portfolio_cash = 0.0
    worker.total_portfolio_value = 100000.0  # value exists, but cash is zero
    
    # Strategy should return buy signal
    worker.strategy.should_trade.return_value = "buy"
    worker.price_feed.get_price.return_value = 200.0
    
    # Mock model
    worker.model = MagicMock()
    worker.model.infer.return_value = {"label": "positive", "confidence": 0.9, "latency_ms": 10.0, "tokenization_latency_ms": 1.0}
    worker.get_drift_detector = MagicMock()
    mock_detector = MagicMock()
    mock_detector.update.return_value = None
    worker.get_drift_detector.return_value = mock_detector
    
    # Mock DB inserts
    worker.db = MagicMock()
    worker.db.insert_headline = AsyncMock()
    worker.db.insert_telemetry = AsyncMock()
    worker.db.insert_drift_alert = AsyncMock()
    
    # Run process_message
    fields = {
        "id": "mock-uuid-1",
        "ticker": "AAPL",
        "headline_text": "Apple announces revolutionary product",
        "source": "mock_source",
        "ingested_at": str(time.time())
    }
    
    await worker.process_message("message-id-1", fields)
    
    # Assertions
    # 1. Trading engine execute_order should NOT have been called (insufficient cash)
    worker.trading_engine.execute_order.assert_not_called()
    
    # 2. Redis Client should have published an insufficient capital event
    worker.redis_client.publish.assert_any_call(
        "sentistream:sentiment_events",
        ANY
    )
    
    # Ensure event published contains "insufficient_capital"
    args, kwargs = worker.redis_client.publish.call_args_list[0]
    payload = json.loads(args[1])
    assert payload["type"] == "insufficient_capital"
    assert payload["data"]["ticker"] == "AAPL"
