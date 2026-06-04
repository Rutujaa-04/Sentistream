import numpy as np
from app.drift import DriftDetector


def test_z_score_fires_above_threshold():
    # Set up detector
    detector = DriftDetector(window_size=50, z_threshold=2.0, min_samples=30)
    
    # Seed stable baseline of neutral/alternating sentiment (so std dev is non-zero)
    # 15 positive (1.0), 15 negative (-1.0) -> mean = 0.0, std = 1.0
    for i in range(15):
        detector.update(1.0, "AAPL")
        detector.update(-1.0, "AAPL")
        
    # Standard update matching the distribution should not alert
    assert detector.update(0.0, "AAPL") is None

    # Inject extreme positive outlier. With mean ~0.0, std ~1.0:
    # A score of 5.0 will be 5 standard deviations away, firing the Z-score trigger
    result = detector.update(5.0, "AAPL")
    assert result is not None
    assert result.z_score > 2.0
    assert result.direction == "bullish_spike"

def test_insufficient_samples_suppresses_alert():
    detector = DriftDetector(window_size=50, z_threshold=2.0, min_samples=30)
    for _ in range(29):
        # Even with extreme changes, below min_samples should suppress alert
        assert detector.update(5.0, "AAPL") is None

def test_degenerate_data_handling_zero_std():
    detector = DriftDetector(window_size=50, z_threshold=2.0, min_samples=30)
    # Seed stable identical baseline (mean = 0.5, std = 0.0)
    for _ in range(40):
        detector.update(0.5, "AAPL")
    
    # We append 0.5 again, meaning standard deviation remains 0.0.
    # The detector has a safety guard `std < 1e-9` that prevents division by zero and returns None.
    result = detector.update(0.5, "AAPL")
    assert result is None

def test_context_isolation():
    detector_a = DriftDetector(window_size=50, min_samples=30)
    detector_b = DriftDetector(window_size=50, min_samples=30)
    
    # Update detector_a with positive sentiment
    for _ in range(35):
        detector_a.update(1.0, "AAPL")
    
    # Update detector_b with negative sentiment
    for i in range(35):
        detector_b.update(-1.0, "TSLA")
        
    # Check that they maintain completely isolated rolling window states
    assert len(detector_a.window) == 35
    assert len(detector_b.window) == 35
    assert np.all(np.array(detector_a.window) == 1.0)
    assert np.all(np.array(detector_b.window) == -1.0)
