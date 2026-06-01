from abc import ABC, abstractmethod

class BaseExecutionEngine(ABC):
    @abstractmethod
    async def initialize(self):
        """Initializes connection clients or credentials for the adapter."""
        pass

    @abstractmethod
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
        Executes a simulated or real trade order.

        Args:
            ticker: Stock ticker symbol (e.g. AAPL, TSLA).
            action: Order side ("buy" | "sell" | "hold").
            quantity: Number of shares to transact.
            price_at_signal: Asset price at signal trigger time.
            signal_source_id: Unique UUID of the headline that triggered this trade.
            confidence_score: FinBERT model sentiment classification confidence.

        Returns:
            str: Unique trade execution ID.
        """
        pass
