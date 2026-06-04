import pytest
from app.model import SentimentModel

def test_inference_returns_valid_label():
    # Load model (since it is a singleton, this fetches the existing instance if already warmed)
    model = SentimentModel()
    
    # Run inference on a highly positive financial headline
    result = model.infer("NVIDIA beats quarterly revenue expectations and shares soar in premarket trading.")
    
    # Assert classification attributes
    assert result["label"] in {"positive", "negative", "neutral"}
    assert 0.0 <= result["confidence"] <= 1.0
    assert result["latency_ms"] >= 0.0
    assert result["tokenization_latency_ms"] >= 0.0
    assert result["total_latency_ms"] >= 0.0

def test_localization_rejection():
    model = SentimentModel()
    # Verify localization checker (currently returns True for standard setups)
    assert model.is_english("This is an English headline.") is True
