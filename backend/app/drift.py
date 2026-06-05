import collections
from typing import NamedTuple, Optional

import numpy as np


class DriftSignal(NamedTuple):
    ticker: str
    z_score: float
    direction: str  # "bullish_spike" | "bearish_spike"
    window_mean: float
    window_std: float
    triggered_threshold: float

class DriftDetector:
    def __init__(self, window_size: int = 100, z_threshold: float = 2.0, min_samples: int = 30):
        """
        Initializes the stateful statistical Z-score drift detector.
        
        Args:
            window_size: Max length of the rolling window deque.
            z_threshold: Z-score standard deviation boundary (2.0 = 95th percentile).
            min_samples: Minimum required entries before drift can fire.
        """
        self.window = collections.deque(maxlen=window_size)
        self.z_threshold = z_threshold
        self.min_samples = min_samples
        self.last_z = 0.0

    def update(self, score: float, ticker: str) -> Optional[DriftSignal]:
        """
        Appends a new sentiment score, updates rolling statistics, and detects Z-score drift.
        
        Args:
            score: Numeric sentiment score (1.0 = positive, -1.0 = negative, 0.0 = neutral).
            ticker: Stock ticker symbol.
        """
        self.window.append(score)
        
        # 1. Warmup guard: suppress alerts if we have insufficient history
        if len(self.window) < self.min_samples:
            self.last_z = 0.0
            return None

        # 2. Compute rolling metrics using numpy
        arr = np.array(self.window)
        mean = float(arr.mean())
        std = float(arr.std())

        # 3. Degenerate case guard: if all scores are identical (std = 0.0), Z-score is mathematically undefined
        if std < 1e-9:
            self.last_z = 0.0
            return None

        # 4. Calculate Z-score standard deviation from rolling baseline
        z = (score - mean) / std
        self.last_z = z

        # 5. Outlier check
        if abs(z) > self.z_threshold:
            direction = "bullish_spike" if z > 0 else "bearish_spike"
            return DriftSignal(
                ticker=ticker,
                z_score=round(z, 4),
                direction=direction,
                window_mean=round(mean, 4),
                window_std=round(std, 4),
                triggered_threshold=self.z_threshold
            )
            
        return None
