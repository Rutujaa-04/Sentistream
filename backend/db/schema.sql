-- ClickHouse Schema DDL for SentiStream

-- 1. Table: headlines
-- Stores all ingested news headlines, their sources, and the model's sentiment predictions.
CREATE TABLE IF NOT EXISTS headlines (
    id UUID,
    ticker String,
    headline_text String,
    source String,
    sentiment_label Enum8('positive' = 0, 'negative' = 1, 'neutral' = 2, 'undefined' = 3),
    confidence_score Float64,
    ingested_at DateTime64(3, 'UTC'),
    processed_at DateTime64(3, 'UTC')
) ENGINE = MergeTree()
ORDER BY (ticker, processed_at)
TTL processed_at + INTERVAL 7 DAY
SETTINGS index_granularity = 8192;

-- 2. Table: inference_telemetry
-- Stores system latency telemetry for performance profiling and observability.
CREATE TABLE IF NOT EXISTS inference_telemetry (
    headline_id UUID,
    inference_latency_ms Float64,
    tokenization_latency_ms Float64,
    total_latency_ms Float64,
    worker_id String,
    recorded_at DateTime64(3, 'UTC')
) ENGINE = MergeTree()
ORDER BY (recorded_at)
TTL recorded_at + INTERVAL 7 DAY
SETTINGS index_granularity = 8192;

-- 3. Table: drift_alerts
-- Stores statistical sentiment drift alerts triggered by the Z-score monitor.
CREATE TABLE IF NOT EXISTS drift_alerts (
    alert_id UUID,
    ticker String,
    z_score Float64,
    window_mean Float64,
    window_std Float64,
    direction Enum8('bullish_spike' = 0, 'bearish_spike' = 1),
    triggered_threshold Float64,
    alerted_at DateTime64(3, 'UTC')
) ENGINE = MergeTree()
ORDER BY (ticker, alerted_at)
TTL alerted_at + INTERVAL 30 DAY
SETTINGS index_granularity = 8192;

-- 4. Table: paper_trades (Phase 2 / Quantitative Trading Engine)
-- Stores simulated orders and executions for portfolio P&L tracking.
CREATE TABLE IF NOT EXISTS paper_trades (
    trade_id UUID,
    ticker String,
    action Enum8('buy' = 0, 'sell' = 1, 'hold' = 2),
    quantity Int32,
    price_at_signal Float64,
    signal_source UUID, -- References headlines.id
    confidence_score Float64,
    executed_at DateTime64(3, 'UTC')
) ENGINE = MergeTree()
ORDER BY (ticker, executed_at)
SETTINGS index_granularity = 8192;
