import asyncio
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from clickhouse_driver import Client

# Add parent directory to path to import properly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from app.config import settings

logger = structlog.get_logger()

class ClickHouseDatabase:
    def __init__(self):
        self.client: Optional[Client] = None
        self.lock = asyncio.Lock()

    async def execute(self, query: str, params: Any = None) -> Any:
        """Executes a ClickHouse query under an asyncio lock to prevent simultaneous connection queries."""
        async with self.lock:
            if params is not None:
                return await asyncio.to_thread(self.client.execute, query, params)
            return await asyncio.to_thread(self.client.execute, query)

    async def initialize(self):
        """Initializes clickhouse connection client and runs migrations."""
        logger.info("Initializing ClickHouse database client...", host=settings.CLICKHOUSE_HOST, port=settings.CLICKHOUSE_PORT)
        try:
            self.client = Client(
                host=settings.CLICKHOUSE_HOST,
                port=settings.CLICKHOUSE_PORT,
                user=settings.CLICKHOUSE_USER,
                password=settings.CLICKHOUSE_PASSWORD,
                database=settings.CLICKHOUSE_DATABASE
            )
            # Idempotently set up tables at startup
            await self.run_migrations()
        except Exception as e:
            logger.error("Failed to connect to ClickHouse database", error=str(e))
            raise e

    async def run_migrations(self):
        """Idempotently executes table DDL schema configurations at boot."""
        workspace_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        schema_path = os.path.join(workspace_dir, "backend", "db", "schema.sql")
        
        if not os.path.exists(schema_path):
            logger.warning("schema.sql not found. Skipping automatic migration checks.", path=schema_path)
            return

        logger.info("Applying schema migrations...")
        with open(schema_path, "r", encoding="utf-8") as f:
            sql = f.read()

        # Split multiple queries by semicolon, filtering out comment lines and whitespace
        statements = []
        for stmt in sql.split(";"):
            # Strip out lines starting with sql comments (--)
            non_comment_lines = []
            for line in stmt.splitlines():
                line_stripped = line.strip()
                if not line_stripped.startswith("--"):
                    non_comment_lines.append(line)
            cleaned = "\n".join(non_comment_lines).strip()
            if cleaned:
                statements.append(cleaned)

        for stmt in statements:
            try:
                # Wrap blocking clickhouse-driver calls in separate worker threads 
                # so we never block FastAPI's async event loop!
                await self.execute(stmt)
            except Exception as e:
                logger.error("Migration query failed", statement=stmt[:50], error=str(e))
                raise e
                
        logger.info("Database schema setup completed successfully.")

    # ==========================================
    # INSERT METHODS (Async/Decoupled)
    # ==========================================

    async def insert_headline(
        self,
        headline_id: str,
        ticker: str,
        headline_text: str,
        source: str,
        sentiment_label: str,
        confidence_score: float,
        ingested_at: float,
        processed_at: float,
        model_version: str = "v1"
    ):
        """Inserts a sentiment-analyzed financial news headline."""
        query = """
            INSERT INTO headlines (
                id, ticker, headline_text, source, sentiment_label, 
                confidence_score, ingested_at, processed_at, model_version
            ) VALUES
        """
        # Convert floats to clickhouse-compatible timestamps
        ingested_dt = datetime.fromtimestamp(ingested_at, tz=timezone.utc).replace(tzinfo=None)
        processed_dt = datetime.fromtimestamp(processed_at, tz=timezone.utc).replace(tzinfo=None)
        
        row = (
            headline_id,
            ticker,
            headline_text,
            source,
            sentiment_label,
            confidence_score,
            ingested_dt,
            processed_dt,
            model_version
        )
        
        await self.execute(query, [row])

    async def insert_telemetry(
        self,
        headline_id: str,
        inference_latency_ms: float,
        tokenization_latency_ms: float,
        total_latency_ms: float,
        worker_id: str,
        model_version: str = "v1"
    ):
        """Inserts pipeline latency telemetry for system profiling."""
        query = """
            INSERT INTO inference_telemetry (
                headline_id, inference_latency_ms, tokenization_latency_ms, 
                total_latency_ms, worker_id, recorded_at, model_version
            ) VALUES
        """
        recorded_dt = datetime.now(timezone.utc).replace(tzinfo=None)
        row = (
            headline_id,
            inference_latency_ms,
            tokenization_latency_ms,
            total_latency_ms,
            worker_id,
            recorded_dt,
            model_version
        )
        await self.execute(query, [row])

    async def insert_drift_alert(
        self,
        alert_id: str,
        ticker: str,
        z_score: float,
        window_mean: float,
        window_std: float,
        direction: str,
        triggered_threshold: float
    ):
        """Inserts a statistical sentiment drift alert record."""
        query = """
            INSERT INTO drift_alerts (
                alert_id, ticker, z_score, window_mean, window_std, 
                direction, triggered_threshold, alerted_at
            ) VALUES
        """
        alerted_dt = datetime.now(timezone.utc).replace(tzinfo=None)
        row = (
            alert_id,
            ticker,
            z_score,
            window_mean,
            window_std,
            direction,
            triggered_threshold,
            alerted_dt
        )
        await self.execute(query, [row])

    async def insert_paper_trade(
        self,
        trade_id: str,
        ticker: str,
        action: str,
        quantity: int,
        price_at_signal: float,
        signal_source: str,
        confidence_score: float
    ):
        """Inserts a simulated paper trade record (Phase 2)."""
        query = """
            INSERT INTO paper_trades (
                trade_id, ticker, action, quantity, price_at_signal, 
                signal_source, confidence_score, executed_at
            ) VALUES
        """
        executed_dt = datetime.now(timezone.utc).replace(tzinfo=None)
        row = (
            trade_id,
            ticker,
            action,
            quantity,
            price_at_signal,
            signal_source,
            confidence_score,
            executed_dt
        )
        await self.execute(query, [row])

    # ==========================================
    # QUERY METHODS (High-performance OLAP)
    # ==========================================

    async def query_latency_percentiles(self, window_hours: int = 1) -> List[Dict[str, Any]]:
        """
        Runs a highly optimized ClickHouse columnar query calculating real-time 
        p50, p95, and p99 processing percentiles aggregated by 1-minute buckets.
        """
        query = f"""
            SELECT 
                toStartOfMinute(recorded_at) AS bucket,
                quantile(0.5)(total_latency_ms) AS p50,
                quantile(0.95)(total_latency_ms) AS p95,
                quantile(0.99)(total_latency_ms) AS p99,
                count(*) AS samples
            FROM inference_telemetry
            WHERE recorded_at >= now() - INTERVAL {window_hours} HOUR
            GROUP BY bucket
            ORDER BY bucket ASC
        """
        rows = await self.execute(query)
        
        results = []
        for bucket, p50, p95, p99, samples in rows:
            results.append({
                "bucket": bucket.isoformat() + "Z" if hasattr(bucket, "isoformat") else str(bucket),
                "p50_ms": round(float(p50), 2),
                "p95_ms": round(float(p95), 2),
                "p99_ms": round(float(p99), 2),
                "samples": int(samples)
            })
        return results

    async def query_sentiment_trends(self, ticker: Optional[str] = None, hours: int = 6) -> List[Dict[str, Any]]:
        """
        Aggregates positive, negative, and neutral sentiment counts 
        by 1-minute buckets over a given historical range using ClickHouse's 
        fast countIf conditional filters.
        """
        where_clause = f"WHERE processed_at >= now() - INTERVAL {hours} HOUR"
        if ticker:
            where_clause += f" AND ticker = '{ticker.upper()}'"

        query = f"""
            SELECT 
                toStartOfMinute(processed_at) AS bucket,
                countIf(sentiment_label = 'positive') AS positive,
                countIf(sentiment_label = 'negative') AS negative,
                countIf(sentiment_label = 'neutral') AS neutral,
                count(*) AS total
            FROM headlines
            {where_clause}
            GROUP BY bucket
            ORDER BY bucket ASC
        """
        rows = await self.execute(query)
        
        results = []
        for bucket, pos, neg, neu, total in rows:
            results.append({
                "bucket": bucket.isoformat() + "Z" if hasattr(bucket, "isoformat") else str(bucket),
                "positive": int(pos),
                "negative": int(neg),
                "neutral": int(neu),
                "total": int(total)
            })
        return results

    async def query_recent_headlines(self, ticker: Optional[str] = None, limit: int = 20) -> List[Dict[str, Any]]:
        """Retrieves recent sentiment-analyzed headlines from ClickHouse, joining with latency telemetry."""
        where_clause = ""
        if ticker:
            where_clause = f"WHERE h.ticker = '{ticker.upper()}'"
 
        query = f"""
            SELECT 
                h.id, h.ticker, h.headline_text, h.source, h.sentiment_label, 
                h.confidence_score, h.processed_at,
                COALESCE(t.inference_latency_ms, 0.0) AS latency_ms,
                h.model_version
            FROM headlines h
            LEFT JOIN inference_telemetry t ON h.id = t.headline_id
            {where_clause}
            ORDER BY h.processed_at DESC
            LIMIT {limit}
        """
        rows = await self.execute(query)
        
        results = []
        for hid, tk, text, source, sentiment, confidence, processed_at, latency, model_version in rows:
            results.append({
                "id": str(hid),
                "ticker": tk,
                "headline": text,
                "source": source,
                "sentiment": sentiment,
                "confidence": float(confidence),
                "latency_ms": round(float(latency), 2),
                "processed_at": processed_at.isoformat() + "Z" if hasattr(processed_at, "isoformat") else str(processed_at),
                "model_version": model_version if model_version else "v1"
            })
        return results

    async def query_drift_alerts(self, ticker: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Retrieves sparse statistical drift alerts from storage."""
        where_clause = ""
        if ticker:
            where_clause = f"WHERE ticker = '{ticker.upper()}'"

        query = f"""
            SELECT 
                alert_id, ticker, z_score, window_mean, window_std, 
                direction, triggered_threshold, alerted_at
            FROM drift_alerts
            {where_clause}
            ORDER BY alerted_at DESC
            LIMIT {limit}
        """
        rows = await self.execute(query)
        
        results = []
        for alert_id, tk, z_score, w_mean, w_std, direction, thres, alerted_at in rows:
            results.append({
                "alert_id": str(alert_id),
                "ticker": tk,
                "z_score": float(z_score),
                "window_mean": float(w_mean),
                "window_std": float(w_std),
                "direction": direction,
                "triggered_threshold": float(thres),
                "alerted_at": alerted_at.isoformat() + "Z" if hasattr(alerted_at, "isoformat") else str(alerted_at)
            })
        return results

    async def query_raw_trades(self) -> List[Dict[str, Any]]:
        """Queries raw paper trade records from the database sorted by execution time."""
        query = """
            SELECT 
                trade_id, ticker, action, quantity, price_at_signal, 
                signal_source, confidence_score, executed_at
            FROM paper_trades
            ORDER BY executed_at ASC
        """
        rows = await self.execute(query)
        
        results = []
        for trade_id, ticker, action, qty, price, sig_src, conf, exec_at in rows:
            results.append({
                "trade_id": str(trade_id),
                "ticker": ticker,
                "action": action,
                "quantity": int(qty),
                "price": float(price),
                "signal_source": str(sig_src),
                "confidence_score": float(conf),
                "executed_at": exec_at.isoformat() + "Z" if hasattr(exec_at, "isoformat") else str(exec_at)
            })
        return results

    async def clear_paper_trades(self):
        """Truncates the paper_trades table in ClickHouse."""
        query = "TRUNCATE TABLE paper_trades"
        await self.execute(query)


    async def query_ab_stats(self) -> List[Dict[str, Any]]:
        """Queries ClickHouse for aggregate latency and counts grouped by model version."""
        query = """
            SELECT 
                COALESCE(NULLIF(model_version, ''), 'v1') AS version,
                count(*) AS total_count,
                avg(inference_latency_ms) AS avg_latency_ms,
                quantile(0.5)(inference_latency_ms) AS p50_ms,
                quantile(0.95)(inference_latency_ms) AS p95_ms,
                quantile(0.99)(inference_latency_ms) AS p99_ms
            FROM inference_telemetry
            GROUP BY version
            ORDER BY version ASC
        """
        rows = await self.execute(query)
        results = []
        for version, total_count, avg_latency, p50, p95, p99 in rows:
            results.append({
                "model_version": version,
                "total_count": int(total_count),
                "avg_latency_ms": round(float(avg_latency), 2),
                "p50_ms": round(float(p50), 2),
                "p95_ms": round(float(p95), 2),
                "p99_ms": round(float(p99), 2)
            })
        return results

    async def close(self):
        """Safely disconnects client connections."""
        logger.info("Closing ClickHouse connection...")
        if self.client:
            # clickhouse-driver does not require custom async closing
            self.client = None
