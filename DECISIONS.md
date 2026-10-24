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
- **Status**: Superseded by Decision 13. The INT8 challenger is now loaded only when its artifact passes evaluation and the operator opts into an experiment; the full-precision baseline remains the default.

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

---

## 11. Periodic Portfolio Marks and Sampled Drawdown (2026-10-24)
- **Context**: The existing historical curve replayed each trade at its transaction price, used a fabricated initial timestamp, and could not show market movement between trades. Current portfolio state already distinguishes realized from unrealized P&L, but no historical equity marks were persisted.
- **Decision**: The worker reconstructs the current paper portfolio and persists equity, cash, realized/unrealized/total P&L, quote-source quality, and holdings every `PORTFOLIO_SNAPSHOT_INTERVAL_SECONDS` (60 seconds by default). Snapshot timestamps use second precision, which matches the cadence and supports ClickHouse 24.3 TTL; ClickHouse retains snapshots for 365 days. The API returns the latest bounded sample (default 1,000 points) with drawdown measured against the initial capital and prior sampled peaks.
- **Rationale**: A periodic ledger-derived mark-to-market series exposes the value of open positions across time, while the stored holdings and P&L split preserve an audit trail of each observation. A bounded history keeps dashboard payload and query size predictable.
- **Data quality**: Finnhub marks are labeled `live`; fallback quote marks are labeled `simulated_fallback`; mixed or unavailable source metadata is explicit. The dashboard shows observation count and sample scope. The sample maximum drawdown is not presented as a full tick-level risk estimate.
- **Reset behavior**: Portfolio reset truncates both trade history and snapshot history to avoid mixing portfolios in the same series.
- **Limit**: Snapshot history is sampled at the worker's configured cadence, so moves between observations can be missed.

---

## 12. Aligned SPY Benchmark Marks (2026-10-24)
- **Context**: A portfolio return is difficult to interpret without a comparable market return over the same window. The project already has a Finnhub quote client and a persisted periodic portfolio snapshot series.
- **Decision**: At each snapshot, request a fresh SPY quote without applying the demo jitter used by simulated trading marks, then persist the quote, ticker, and source with the portfolio observation. The analytics API computes portfolio return and SPY buy-and-hold return from the first to last aligned observation. It reports excess return in percentage points only when there are at least two Finnhub SPY observations and the portfolio mark is live or cash-only.
- **Rationale**: Storing the benchmark quote on the same row guarantees matching timestamps and avoids joining unrelated sampling schedules. Excluding fallback portfolio or benchmark prices prevents simulated values from being presented as measured market-relative performance.
- **Migration**: New benchmark columns are created with the snapshot table and added idempotently to existing installations. Older rows default to `unknown` and are excluded from comparisons.
- **Limit**: The benchmark is SPY and relies on Finnhub availability; without live marks the dashboard reports that there are not yet enough eligible observations. Returns cover the latest API sample (up to 1,000 marks), not the full retained year.

---

## 13. Hash-Bound Model Artifact Evaluation and Traffic Gate (2026-10-24)
- **Context**: The prior startup copied one INT8 model into both routing slots and enabled an 80/20 split regardless of model identity or quality. The dashboard showed routing telemetry but had no labeled quality comparison.
- **Decision**: Compare the exported full-precision ONNX baseline (`v1`) with the independently generated INT8 artifact (`v2`) on a pinned, stratified 10% holdout from Financial PhraseBank `sentences_allagree`. Report accuracy, weighted/macro F1, expected calibration error, multiclass Brier score, per-class support, dataset/archive fingerprints, and model SHA-256 hashes. Require at least 100 examples, weighted-F1 drop no greater than 0.01, macro-F1 drop no greater than 0.02, and ECE increase no greater than 0.03 for eligibility.
- **Traffic control**: Route all headlines to `v1` by default. Enable the deterministic 80/20 split only if the evaluation report passes, both installed artifact hashes match the report and are distinct, and `MODEL_EXPERIMENT_ENABLED=true`. Load the challenger session only after that gate passes.
- **Rationale**: Quantization is a real accuracy/calibration versus latency/size trade-off. Separating this artifact comparison from traffic assignment prevents an unmeasured candidate from affecting results; hash binding invalidates stale reports after any artifact replacement.
- **Dataset handling**: Fetch the dataset archive at a pinned Hugging Face revision into the local cache; do not commit or package the dataset itself. Financial PhraseBank is CC BY-NC-SA 3.0, so this evaluation data is for non-commercial use unless separate rights are obtained.
- **First measured result**: On the pinned 227-example test split, FP32 scored 0.9648 accuracy, 0.9655 weighted F1, 0.9491 macro F1, and 0.0463 ECE. INT8 scored 0.9736 accuracy, 0.9740 weighted F1, 0.9608 macro F1, and 0.1124 ECE. The candidate is rejected because its ECE increase (0.0660) exceeds the 0.03 limit; all traffic remains on FP32. The generated report is local because model binaries and reports are excluded from Git.
- **Limit**: The baseline and challenger share the same trained checkpoint; this comparison measures full-precision versus INT8 quantization, not two separately fine-tuned architectures. A future learned challenger needs its own versioned training artifact and a separately licensed or internally labeled holdout.

---

## 14. News Provenance, Publication Freshness, and Syndication Deduplication (2026-10-25)
- **Context**: RSS ingestion assigned every fallback item the same `rss_fallback` source and replaced publisher time with ingestion time. The existing title/ticker key did not normalize Unicode, punctuation, or repeated whitespace, and the dashboard did not distinguish publication freshness from processing time.
- **Decision**: Persist a stable feed identifier, publisher/source label, nullable publisher `published_at`, and separate ingestion/processing timestamps. Derive RSS feed identity from its host; keep Finnhub's publisher label while identifying the API feed as `finnhub:general`. Parse RSS `published_parsed`/`updated_parsed` and Finnhub's source epoch; leave publication time null when absent rather than inventing it.
- **Deduplication**: Normalize Unicode compatibility forms, case, punctuation, and whitespace, then derive a stable source-independent headline/ticker UUID. Use Redis SETNX with a configurable 24-hour default TTL to collapse exact syndicated copies across feeds. Do not use fuzzy matching because it can merge distinct stories with similar titles.
- **Analytics**: Add an additive ClickHouse migration and `/api/v1/news-quality` summary for publication timestamp coverage and latest publication/ingestion age grouped by ticker and feed. The dashboard shows the overall 24-hour timestamp coverage and per-feed freshness.
- **Rationale**: Separate event time from pipeline arrival time so freshness and latency are interpretable; stable provenance allows feed-level coverage monitoring; source-independent normalization suppresses exact syndicated repeats while retaining traceable source identity.
- **Limit**: Deduplication is exact after normalization and lasts only for the configured Redis TTL. Publication-time coverage is available only for retained headline rows (7 days); feed freshness describes the latest stored publication time and does not establish source completeness.
