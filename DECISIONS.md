# SentiStream Architectural Decisions (ADR)

This file documents the key design decisions, trade-offs, and rationale behind SentiStream's architecture.

---

## 1. Process-Local Price Feed Singletons (No Cross-Process Caching)
- **Context**: The backend consists of two main processes: the FastAPI gateway (`main.py`) and the background consumer stream daemon (`worker.py`).
- **Decision**: The `PriceFeed` class operates as a process-local singleton within each OS process, rather than using a shared Redis cache or database cache for Finnhub quotes.
- **Rationale**: 
  - Exposes process boundaries cleanly. 
  - Prevents complex cache-invalidation logic and database queries for live quotes.
  - Rate limiting is handled independently in each process (with 30-second TTL caches), reducing quote quota usage while keeping local development overhead extremely low.

---

## 2. Exposing Telemetry from Background Worker (Port 8001 Scraper)
- **Context**: The stream consumer daemon (`worker.py`) is a background process without an HTTP interface. It needs to expose metrics to Prometheus.
- **Decision**: Start a dedicated background thread running a lightweight HTTP server on port `8001` via `prometheus_client.start_http_server`.
- **Rationale**:
  - Avoids dependencies on external brokers like Prometheus Pushgateway.
  - Scraping port `8001` is standard, robust, and decouples metrics collection from the FastAPI endpoint, preventing worker crashes from affecting gateway availability.

---

## 3. Excluding `/metrics` Route from Request Middleware Tracking
- **Context**: FastAPI request metrics (HTTP duration and request counts) are tracked via a global HTTP middleware.
- **Decision**: Explicitly bypass route tracking when the URL path matches `/metrics`.
- **Rationale**:
  - Prevents Prometheus scraper requests (occurring every 15 seconds) from inflating the actual request volume (`HTTP_REQUEST_COUNT`) and latency metrics (`HTTP_REQUEST_LATENCY`).
  - Ensures metrics graphs display authentic dashboard and user traffic.

---

## 4. Resetting Z-Score Gauge on Warmup Guards and Quiet Tickers
- **Context**: The sentiment rolling Z-score gauge is stateful and labeled by `ticker`. Prometheus gauges do not automatically expire or clear.
- **Decision**:
  - When a ticker's rolling sentiment window drops below the minimum sample threshold (30 samples) or exhibits flat variance, the `DriftDetector` explicitly updates `self.last_z` to `0.0` and sets the Prometheus Gauge to `0.0`.
  - When a ticker goes quiet (no headlines processed for over 60 seconds), the background queue poller in the worker daemon explicitly sets its Z-score gauge to `0.0` and resets the detector's last Z-score value.
- **Rationale**:
  - Prevents stale Z-score metrics from persisting on the Grafana dashboard for quiet tickers, providing accurate MLOps telemetry.

---

## 5. Dual ONNX Inference Sessions (Memory & Cold-Start Tradeoff)
- **Context**: Setting up the Model Registry and A/B Testing framework requires routing headline inference to different versioned ONNX model models (`v1` and `v2`).
- **Decision**: Accept loading two separate `InferenceSession` instances (totaling ~210MB RAM footprint) concurrently within the background worker process at boot.
- **Rationale**:
  - Memory consumption of 210MB is well within acceptable limits for the local Docker compose and standard host machines.
  - Initializing both models at worker startup avoids runtime "first-request" latency degradation for either version.
  - While it slightly increases the initial cold-start duration of the worker container, it guarantees stable, deterministic p99 latency benchmarks (< 50ms) for both user-facing endpoints immediately from the first live headline processed.

