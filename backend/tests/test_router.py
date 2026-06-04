import pytest
from fastapi.testclient import TestClient
from app.main import app

def test_ping_endpoint():
    # Wrap in context manager to trigger FastAPI startup lifespan (connects to CH & Redis, loads ONNX)
    with TestClient(app) as client:
        response = client.get("/ping")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["clickhouse"] == "warm"
        assert data["redis"] == "warm"
        assert data["onnx_model"] == "loaded"
        assert "latency_ms" in data

def test_health_endpoint():
    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "components" in data
        assert data["components"]["redis"]["status"] == "ok"
        assert data["components"]["clickhouse"]["status"] == "ok"
        assert data["components"]["onnx"]["status"] == "ok"

def test_sentiment_trends_endpoint():
    with TestClient(app) as client:
        # Default query: SPY or general trends (should return list)
        response = client.get("/api/v1/sentiment-trends?hours=6")
        assert response.status_code == 200
        data = response.json()
        assert "data" in data
        assert isinstance(data["data"], list)

def test_drift_alerts_endpoint():
    with TestClient(app) as client:
        response = client.get("/api/v1/drift-alerts?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert "alerts" in data
        assert isinstance(data["alerts"], list)

def test_portfolio_endpoint():
    with TestClient(app) as client:
        response = client.get("/api/v1/portfolio")
        assert response.status_code == 200
        data = response.json()
        assert "total_trades" in data
        assert "total_pnl_usd" in data
        assert "positions" in data
