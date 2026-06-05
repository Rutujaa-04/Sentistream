from prometheus_client import Counter, Histogram, Gauge

# 1. Model Inference Telemetry Metrics
INFERENCE_LATENCY = Histogram(
    "sentistream_inference_latency_seconds",
    "FinBERT model inference latency in seconds",
    buckets=[0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05, 0.075, 0.1, 0.25]
)

TOKENIZATION_LATENCY = Histogram(
    "sentistream_tokenization_latency_seconds",
    "Model text tokenization latency in seconds",
    buckets=[0.0005, 0.001, 0.002, 0.003, 0.004, 0.005, 0.0075, 0.01, 0.025]
)

HEADLINES_PROCESSED = Counter(
    "sentistream_headlines_processed_total",
    "Total headlines processed by the pipeline",
    ["ticker", "sentiment", "status"]
)

# 2. Sentiment Drift Monitoring Metrics
DRIFT_ALERTS = Counter(
    "sentistream_drift_alerts_total",
    "Total statistical sentiment drift alerts triggered",
    ["ticker", "direction"]
)

ROLLING_Z_SCORE = Gauge(
    "sentistream_rolling_z_score",
    "Active statistical Z-score of rolling sentiment scores",
    ["ticker"]
)

# 3. Quantitative Paper Trading Metrics
TRADES_EXECUTED = Counter(
    "sentistream_trades_executed_total",
    "Total paper trades executed by the quant engine",
    ["ticker", "action"]
)

PORTFOLIO_CASH = Gauge(
    "sentistream_portfolio_cash_usd",
    "Current simulated portfolio cash balance in USD"
)

PORTFOLIO_TOTAL_VALUE = Gauge(
    "sentistream_portfolio_total_value_usd",
    "Current total portfolio value (cash + position market value) in USD"
)

POSITION_SHARES = Gauge(
    "sentistream_position_shares",
    "Number of shares currently held for a ticker",
    ["ticker"]
)

# 4. Stream Queue Backlog Metrics
REDIS_STREAM_BACKLOG = Gauge(
    "sentistream_redis_stream_backlog",
    "Number of pending headlines in the raw_headlines stream queue"
)

DLQ_BACKLOG = Gauge(
    "sentistream_dlq_backlog",
    "Number of failed headlines in the dlq_headlines stream queue"
)
