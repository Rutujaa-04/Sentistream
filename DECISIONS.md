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

---

## 6. Support for Position Scaling (Adding to Existing Positions)
- **Context**: In Long-Only and Long-Short strategy modes, a new buy/sell signal could arrive when the portfolio already holds a position in the target asset. We had to decide whether to restrict execution to only opening positions from a flat state or to allow adding to existing positions.
- **Decision**: Keep the original Phase 2 design behavior, allowing the worker to add to existing positions on subsequent signals above threshold after the cooldown has elapsed, up to capital constraints.
- **Rationale**: 
  - Allows faster and more efficient capital deployment, preventing the system from staying idle with excess cash when subsequent strong positive/negative signals occur.
  - Generates more realistic simulated trading curves and P&L history profiles that reflect consecutive momentum or sentiment-driven movements in individual assets.

---

## 7. Short-Covering Sizing and Liquidation Symmetry
- **Context**: In Long-Short strategy mode, we need to handle opposing signals (e.g. a positive sentiment buy signal when we hold a negative short position). We must decide whether covering is done in incremental steps (e.g. 5% capital allocation slices) or if we fully cover (liquidate) the short position on a single buy signal.
- **Decision**: Cover the entire short position completely on any positive sentiment buy signal (and similarly, liquidate the entire long position on any negative sentiment sell signal).
- **Rationale**:
  - **Symmetry**: This matches the Long-Only and Long-Short behavior where an opposing signal liquidates the entire long position.
  - **Risk Management**: Short positions carry unlimited theoretical risk. Fully covering on a reverse sentiment signal ensures that the portfolio immediately stops losing money if market sentiment shifts against the short position.
  - **Sizing Simplicity**: Avoids hanging short position remnants or complex multi-step partial coverage that would complicate demo P&L tracking and lead to outsized realized P&L swings.

---

## 8. Production-Readiness and Hosted-Demo Decisions (2026-10-23)

### 8.1 Compose as the first deployment target
- **Context**: The repository had a Compose file for infrastructure only, while the API, worker, ingestor, and frontend were launched manually. A public demo needs one reproducible deployment surface.
- **Decision**: Extend Docker Compose to run the complete app on one host. Build one backend image and run it with separate API, worker, and ingestor commands; build the React site into an Nginx image; place Caddy in front for public HTTP(S).
- **Rationale**: This keeps the existing Redis/ClickHouse architecture and provides the simplest migration from local demo to a small VM. It avoids introducing Kubernetes or an orchestrator before the project needs horizontal scaling.

### 8.2 Same-origin browser routes and WebSocket scheme
- **Context**: Browser requests were hardcoded to `localhost`, which points to each visitor's own machine after deployment, and the WebSocket URL used unencrypted `ws://`.
- **Decision**: Default frontend calls to same-origin `/api`, `/ping`, `/health`, and `/ws`. Derive `ws:` versus `wss:` from the page protocol, allow explicit Vite build-time API/WebSocket overrides, and proxy API and WebSocket traffic through Nginx.
- **Rationale**: Same-origin routing keeps production API calls on the deployed host, avoids CORS as a requirement for the standard deployment, and selects secure WebSockets automatically under HTTPS.

### 8.3 Public deployment boundaries
- **Context**: The API included unauthenticated test injection, strategy mutation, and portfolio reset endpoints. Redis, ClickHouse, API, and monitoring services should not be reachable from the public network.
- **Decision**: Test injection and dashboard controls are disabled by default and forcibly disabled when `APP_ENV=production`. Publish only Caddy's 80/443 ports; keep app/data services on the private Compose network. Bind optional Prometheus/Grafana host ports to loopback.
- **Rationale**: A public showcase should be read-only until a real authentication and authorization layer exists. Hiding buttons alone is insufficient, so the backend also rejects those writes. Loopback-bound monitoring supports SSH-tunnel access without exposing admin tools.
- **Code detail**: Ticker query filters accept only a bounded ticker-symbol character set before they reach interpolated ClickHouse filters.

### 8.4 Configuration precedence
- **Context**: The settings loader read process environment first and then overwrote it with `.env`, which could make container or hosting configuration silently lose to a local file.
- **Decision**: Apply configuration in the order defaults, `.env`, then process environment.
- **Rationale**: Host-provided settings and secrets must override developer-local values in containers and hosted deployments.

### 8.5 Readiness reflects ONNX initialization
- **Context**: Startup logged an ONNX model load failure but `/ping` and `/health` still claimed the model was available.
- **Decision**: Track successful model initialization and return degraded/unavailable readiness when it fails.
- **Rationale**: Orchestrators and operators need health endpoints to describe actual serving capability so an incomplete demo is not presented as ready.

### 8.6 Analytics claims and model routing labels
- **Context**: The UI displayed a correlation value derived from a fixed formula, and described `v1`/`v2` as champion/challenger even though missing model files are copied from the same base artifact.
- **Decision**: Replace the derived correlation with “Not measured” and relabel the version cards as routing slots, with an explicit note that they report traffic/latency and do not compare model quality.
- **Rationale**: Show only measured analytics and distinguish operational routing telemetry from a valid experiment. A quality comparison requires separate model artifacts and labeled evaluation data.

### 8.7 Runtime dependency and data-service choices
- **Context**: The single Python requirements file included training/export packages in the serving image, Redis ran without persistence and could evict keys, and monitoring configuration targeted host ports rather than Compose service names.
- **Decision**: Add a pinned serving-only requirements file; keep training dependencies in the existing ML requirements. Enable Redis AOF persistence with `noeviction`; use named volumes for Redis, ClickHouse, Caddy, Prometheus, and Grafana; scrape API and worker by their Compose DNS names.
- **Rationale**: Keep serving images smaller, retain queued/settings data through restarts, avoid silently evicting stream keys, and make telemetry work inside the Compose network. `noeviction` means writes can fail at the configured memory ceiling, so capacity monitoring remains necessary.
- **Build detail**: Docker ignore files exclude the local virtual environment, Node modules, model binaries, and generated artifacts from build contexts. Model files are mounted separately at runtime.

### 8.8 Deployment documentation and model artifacts
- **Context**: Model binaries are ignored by Git and the previous README's “initialize model” command did not create them.
- **Decision**: Document the ONNX export command, expected mounted files, complete Compose startup, local URL, observability profile, and production domain/DNS steps. Keep the model binaries out of Git.
- **Rationale**: Large generated binaries should not inflate repository history. A reproducible export plus an explicit artifact requirement makes the deployment prerequisite clear; a hosted artifact registry can be added when the project selects one.

---

## 9. Serving Dependency Security Boundary (2026-10-23)
- **Context**: CI's security job first failed on unignored vulnerabilities in the ML/training dependency set (Transformers 4.57.6, Datasets 4.8.5, ONNX 1.21.0, and transitive packages). Once narrowed to the exact deployed runtime set, it found 56 advisories in `aiohttp==3.13.3`, all with fixes at or before 3.14.4. The ONNX export path currently pins `optimum-onnx==0.1.0`, whose release supports Transformers 4.56/4.57; moving that stack to Transformers 5 without an exporter migration is not a safe patch-level update.
- **Decision**: The deployed runtime loads the local `tokenizer.json` artifact using the standalone `tokenizers` package, upgrades aiohttp to 3.14.5, and CI's deployment security gate audits `backend/requirements-runtime.txt`, the exact Python dependency set installed by `backend/Dockerfile`. Training and ONNX export dependencies remain in `backend/requirements.txt` and are not shipped to the public serving image.
- **Rationale**: This removes the vulnerable Transformers package from the always-on API/worker/ingestor image without breaking model training and export. It aligns the gate with the production attack surface instead of suppressing the reported advisories with broad ignores.
- **Operational detail**: Model packaging must include `models/finbert-onnx/tokenizer.json` (or a fine-tuned checkpoint containing `tokenizer.json`) alongside the ONNX model. Missing local tokenizer assets now fail startup with an actionable error instead of downloading an implicit public model.
- **Limit**: This change does not claim the development/training toolchain is vulnerability-free. The ML dependency set needs a separate exporter migration and security review before it can be treated as a secured build environment.

---

## 10. Redis Stream Recovery and Retry Telemetry (2026-10-23)
- **Context**: A worker crash leaves messages in the consumer group's pending-entry list, where the existing `>` read never sees them again. Processing exceptions were sent directly to the DLQ without retrying, and the backlog gauge measured total stream length rather than work still awaiting acknowledgement.
- **Decision**: Reclaim abandoned entries with Redis `XAUTOCLAIM` after a configurable idle period; retry unexpected processing failures up to a configurable limit by leaving the message pending; send malformed messages immediately to the DLQ and exhausted messages there with their retry count. Store retry counts in a Redis hash keyed by stream ID, and clear retry metadata after acknowledging success or DLQ persistence.
- **Rationale**: Redis Streams provides durable pending ownership and idle-age based recovery without introducing a separate broker. Keeping retry counts in Redis allows another worker to continue the retry budget after a process restart.
- **Telemetry**: Report unacknowledged count, oldest pending idle age, scheduled retry count, and retained DLQ length. The age metric is pending idle time since last delivery, not total time since the headline was ingested.
- **Trade-off**: Delivery is at least once. A failure after an external or database side effect can cause that headline to be processed again; idempotent trade execution and persistence remain necessary before scaling to multiple workers or live broker execution.
