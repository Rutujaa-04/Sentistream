import time
from abc import ABC, abstractmethod
from typing import Dict, Optional

import structlog

logger = structlog.get_logger()

class BaseStrategy(ABC):
    @abstractmethod
    def should_trade(self, ticker: str, sentiment: str, confidence: float, bypass_cooldown: bool = False) -> Optional[str]:
        """
        Evaluates whether a trade should be executed.
        Returns:
            str: "buy" | "sell" or None
        """
        pass


class ThresholdStrategy(BaseStrategy):
    def __init__(self, threshold: float = 0.75, cooldown_seconds: float = 60.0):
        self.threshold = threshold
        self.cooldown_seconds = cooldown_seconds
        # In-memory cooldown tracking per ticker
        self.last_trade_time: Dict[str, float] = {}

    def should_trade(self, ticker: str, sentiment: str, confidence: float, bypass_cooldown: bool = False) -> Optional[str]:
        """
        Applies a threshold and a time-based cooldown to decide trade signals.
        """
        ticker = ticker.strip().upper()
        
        # We only trade on positive or negative sentiment
        if sentiment not in ("positive", "negative"):
            return None

        # Check confidence threshold
        if confidence <= self.threshold:
            return None

        # Check per-ticker cooldown
        current_time = time.time()
        last_time = self.last_trade_time.get(ticker, 0.0)
        elapsed = current_time - last_time
        
        if not bypass_cooldown and elapsed < self.cooldown_seconds:
            logger.info(
                "Trade signal suppressed by cooldown",
                ticker=ticker,
                sentiment=sentiment,
                confidence=confidence,
                elapsed_seconds=round(elapsed, 2),
                cooldown_seconds=self.cooldown_seconds
            )
            return None

        # Determine action side
        action = "buy" if sentiment == "positive" else "sell"
        
        # Update cooldown timestamp
        self.last_trade_time[ticker] = current_time
        
        logger.info(
            "Trade signal generated",
            ticker=ticker,
            sentiment=sentiment,
            confidence=confidence,
            action=action.upper()
        )
        return action
