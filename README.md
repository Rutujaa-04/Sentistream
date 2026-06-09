# SentiStream

**SentiStream** is a real-time, event-driven MLOps sentiment analytics and quantitative paper trading pipeline for financial headlines. It is designed to demonstrate high-performance data engineering, machine learning service deployment, and real-time observability.

---

## 🚀 Pipeline Architecture

SentiStream is built using a decoupled, event-driven architecture designed for high throughput, low latency, and statistical reliability:

```mermaid
graph TD
    Ingestor[Finnhub & RSS Ingestor] -->|JSON Payload| Redis[Redis Stream: raw_headlines]
    Redis -->|Group Consume| Worker[Consumer Worker]
    
    subgraph Worker Process (Stream Processing)
        ModelRegistry[Model Registry: Champion v1 & Challenger v2]
        DriftDetector[Z-Score Drift Detector]
        Strategy[Threshold-Based Trading Strategy]
        ExecutionEngine[Execution Engine: Alpaca / Simulated]
    end
    
    Worker --> ModelRegistry
    Worker --> DriftDetector
    Worker --> Strategy
    Worker --> ExecutionEngine
    
    Worker -->|Batched Columnar Write| ClickHouse[(ClickHouse OLAP)]
    Worker -->|Prometheus Metrics Port 8001| Prometheus[Prometheus Scraper]
    Worker -->|Redis Pub/Sub| Gateway[FastAPI Gateway]
    
    Gateway -->|WebSockets Full-Duplex| ReactUI[React Observability Dashboard]
    ClickHouse -->|REST OLAP Aggregations| ReactUI
    Prometheus -->|Data Source| Grafana[Grafana Dashboard]
```

### Decoupled Core Components
1. **News Ingestor (`ingestor.py`)**: Asynchronously polls Finnhub's financial news API with token-bucket rate limiting and falls back automatically to financial RSS feeds (Google News, Yahoo Finance) on API rate limits or failures. Implements SHA-256 deduplication to prevent duplicate processing.
2. **Broker Queue (Redis Streams)**: Buffers raw ingest payloads in the `raw_headlines` stream to decouple ingestion from inference.
3. **Consumer Worker (`worker.py`)**: Consumes the stream, routes text to versioned INT8-quantized FinBERT ONNX models, updates Z-score drift stats, evaluates trading signals, executes simulated trades, and persists results.
4. **Database Manager (ClickHouse OLAP)**: Stores large-volume columnar data for structured news headlines, latency profiles, drift alerts, and trading transactions.
5. **API Gateway (`main.py`)**: Serves REST endpoints for historical OLAP statistics, manages full-duplex client WebSockets connections, and listens to Redis Pub/Sub events for real-time broadcasts.
6. **Observability UI (React & Vite)**: Displays live ticker news streams, A/B model performance metrics, portfolio positions, real-time capital warning triggers, and historical P&L charts.

---

## 💎 Core Features

### 1. Dual ONNX Model Registry & A/B Testing
* Concurrently runs **Champion (`v1`)** and **Challenger (`v2`)** INT8-quantized FinBERT models locally via CPU execution threads.
* Implements a deterministic **80/20 A/B split** based on the headline UUID's hash modulo:
  $$\text{Model Version} = \text{v1} \text{ if } \text{int(headline\_id[:8], 16) \% 10 < 8} \text{ else } \text{v2}$$
  This ensures stable model assignment across worker restarts and Dead Letter Queue (DLQ) replays, preventing metric contamination.
* Logs latency percentiles and evaluation throughput directly in ClickHouse and Prometheus, grouped by model version.

### 2. Sentiment Drift Detection
* Tracks statistical drift of news sentiment using a rolling Z-score window.
* Automatically triggers alerts when the rolling Z-score exceeds $\pm 2.0$ standard deviations.
* Automatically resets active gauges to `0.0` for quiet tickers (no headlines processed for over 60 seconds) to prevent stale dashboards.

### 3. Quantitative Paper Trading & Alpaca Brokerage
* Executes a threshold-based Long-Only strategy:
  * **Confidently Positive** (sentiment score $\ge 0.75$): Buy an allocation equal to 5% of net portfolio value.
  * **Confidently Negative** (sentiment score $\ge 0.75$): Sell/liquidate the entire ticker position (no shorting).
* Enforces a strict 60-second cooldown period per ticker.
* Supports **Alpaca Brokerage Integration** for real-time paper orders, alongside a robust local **Simulated Engine** for offline development.
* Implements capital-depletion validation and dispatches WebSocket notifications for out-of-cash errors.

### 4. ClickHouse OLAP Analytics & P&L Charts
* Custom SVG charts render real-time telemetry data without external heavy charting libraries.
* Exposes **p50, p95, and p99 latency percentile** aggregations.
* Plots the **Portfolio Historical P&L Path** by sequentially reconstructing cash balance and position valuations after each trade execution.

---

## 🛠️ Local Installation & Setup

### Prerequisites
* Python 3.11+
* Node.js 20+
* Docker & Docker Compose (for ClickHouse, Redis, Prometheus, and Grafana)

### 1. Start Docker Services
```bash
docker-compose up -d
```
This boots:
* **Redis** (Port 6379)
* **ClickHouse** (Port 9000 & HTTP 8123)
* **Prometheus** (Port 9090)
* **Grafana** (Port 3000)

### 2. Configure Environment
Create a `.env` file in the root directory:
```env
REDIS_URL=redis://localhost:6379
CLICKHOUSE_HOST=localhost
CLICKHOUSE_PORT=9000
CLICKHOUSE_DATABASE=default
CLICKHOUSE_USER=default
CLICKHOUSE_PASSWORD=

# ML Models
INITIAL_PORTFOLIO_CAPITAL=100000.0
TRADING_ENGINE=simulated # 'simulated' or 'alpaca'

# (Optional) Alpaca credentials
ALPACA_API_KEY=your_alpaca_key
ALPACA_SECRET_KEY=your_alpaca_secret
ALPACA_PAPER_BASE_URL=https://paper-api.alpaca.markets

# (Optional) Finnhub News key
FINNHUB_API_KEY=your_finnhub_key
```

### 3. Setup Virtual Environment & Dependencies
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

### 4. Initialize Models
Populate the model directory with ONNX assets:
```bash
python backend/app/model.py
```
*(If version files are missing, SentiStream automatically initializes `models/finbert-int8-v1.onnx` and `models/finbert-int8-v2.onnx` by copying the base quantized asset).*

### 5. Launch Backend Daemons
In separate terminal tabs (with virtualenv activated):

* **API Gateway**:
  ```bash
  PYTHONPATH=backend ./venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
  ```
* **Consumer Worker**:
  ```bash
  PYTHONPATH=backend ./venv/bin/python backend/app/worker.py
  ```
* **News Ingestor**:
  ```bash
  PYTHONPATH=backend ./venv/bin/python backend/app/ingestor.py
  ```

### 6. Start Frontend Development Server
```bash
cd frontend
npm install
npm run dev
```
Open `http://localhost:5173` to view the live dashboard!

---

## 🧪 Testing Guide

### 1. Run Unit & Integration Tests
Executes testing modules covering the trading engine, strategy cooldowns, drift alert algorithms, and database migrations:
```bash
PYTHONPATH=backend ./venv/bin/pytest
```

### 2. Seed Mock Transactions
Injects real-time financial headlines into Redis to test pipeline execution and trigger strategy trades:
```bash
PYTHONPATH=backend ./venv/bin/python scripts/seed_test_data.py --mode=trades
```

### 3. E2E Browser Testing (Playwright)
Validates frontend components, WebSocket streaming updates, and reconnection resiliency:
```bash
cd frontend
npx playwright test
```

### 4. Load Testing (Locust)
Simulates concurrent stream writes and high API endpoint query load:
```bash
./venv/bin/locust -f backend/tests/locustfile.py --headless -u 10 -r 2 --run-time 5m --host http://localhost:8000
```
