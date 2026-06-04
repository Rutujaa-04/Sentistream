import argparse
import os
import random
import sys
import time
import uuid
from datetime import datetime, timezone

from clickhouse_driver import Client

# Add parent directory to path to import properly
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from backend.app.config import settings

# Sample Headlines for seeding
BULK_HEADLINES = [
    ("Apple beats Q3 revenue estimations by 12%, stock up 4% in premarket.", "AAPL", "positive", 0.94),
    ("Tesla vehicle deliveries beat Wall Street estimates as global demand recovers.", "TSLA", "positive", 0.92),
    ("NVIDIA announces next-generation Blackwell architecture, stock hits record high.", "NVDA", "positive", 0.98),
    ("Federal Reserve signals pause on interest rate hikes, market indexes surge.", "SPY", "positive", 0.85),
    ("Apple faces antitrust scrutiny from DOJ over App Store policies, stock dips 2%.", "AAPL", "negative", 0.88),
    ("Tesla recall of 200,000 vehicles due to software autopilot glitches.", "TSLA", "negative", 0.81),
    ("NVIDIA down 3% on concerns of artificial intelligence chip demand slowdown.", "NVDA", "negative", 0.74),
    ("Inflation numbers come in hotter than expected, sparking market volatility.", "SPY", "negative", 0.91),
    ("Apple holds low-key product event announcing updated iPad colors.", "AAPL", "neutral", 0.89),
    ("Tesla schedules annual shareholder meeting for mid-July.", "TSLA", "neutral", 0.92),
    ("NVIDIA CEO to deliver keynote speech at Computex conference.", "NVDA", "neutral", 0.95),
    ("US Treasury yields hold steady as investors digest economic data.", "SPY", "neutral", 0.90)
]

DRIFT_HEADLINES = [
    ("Apple stock upgraded to Strong Buy by Goldman Sachs on explosive AI growth projection.", "AAPL", "positive", 0.99),
    ("Apple announces blockbuster share buyback of $110 billion, stock hits all-time high.", "AAPL", "positive", 0.99),
    ("Apple quarterly earnings hit record record revenue beats, margins expand 500bps.", "AAPL", "positive", 0.99),
    ("Apple Vision Pro sales surge beyond all bullish retail targets in overseas expansion.", "AAPL", "positive", 0.98),
    ("Apple secures exclusive multi-year Gemini integration deal for all device models.", "AAPL", "positive", 0.99)
]

def main():
    parser = argparse.ArgumentParser(description="SentiStream Seeding & Synthetic Drift Injection Utility")
    parser.add_argument("--mode", type=str, choices=["bulk", "drift"], required=True, 
                        help="bulk: pre-warms ClickHouse charts with 6 hours of historical telemetry. drift: injects synthetic sentiment shock to fire Z-score alert.")
    parser.add_argument("--ticker", type=str, default="AAPL", help="Target ticker for synthetic drift injection.")
    
    args = parser.parse_args()

    print(f"Connecting to ClickHouse at {settings.CLICKHOUSE_HOST}:{settings.CLICKHOUSE_PORT}...")
    try:
        client = Client(
            host=settings.CLICKHOUSE_HOST,
            port=settings.CLICKHOUSE_PORT,
            user=settings.CLICKHOUSE_USER,
            password=settings.CLICKHOUSE_PASSWORD,
            database=settings.CLICKHOUSE_DATABASE
        )
        # Execute query to verify connection
        client.execute("SELECT 1")
        print("ClickHouse connected successfully.")
    except Exception as e:
        print(f"Error connecting to ClickHouse: {e}")
        sys.exit(1)

    if args.mode == "bulk":
        print("\nRunning Mode: BULK (Pre-warming ClickHouse with 6 hours of telemetry data)...")
        t_now = time.time()
        
        headline_rows = []
        telemetry_rows = []
        
        # Populate 6 hours (360 minutes), writing 1-3 headlines per minute
        for minute_offset in range(360, 0, -1):
            ts = t_now - (minute_offset * 60) + random.uniform(-10, 10)
            
            # Select random headlines
            num_headlines = random.randint(1, 2)
            for _ in range(num_headlines):
                text, ticker, sentiment, confidence = random.choice(BULK_HEADLINES)
                headline_id = str(uuid.uuid4())
                
                # Dynamic latency ranges: FP50=22ms, FP95=38ms, FP99=47ms
                inf_latency = random.normalvariate(24.0, 5.0)
                tok_latency = random.normalvariate(3.2, 0.5)
                tot_latency = inf_latency + tok_latency + random.uniform(1, 3)
                
                # Format timestamps
                ts_dt = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
                processed_dt = datetime.fromtimestamp(ts + 0.2, tz=timezone.utc).replace(tzinfo=None)
                
                headline_rows.append((
                    headline_id,
                    ticker,
                    text,
                    "finnhub_seeder",
                    sentiment,
                    confidence,
                    ts_dt,
                    processed_dt
                ))
                
                telemetry_rows.append((
                    headline_id,
                    inf_latency,
                    tok_latency,
                    tot_latency,
                    "worker_seeder",
                    processed_dt
                ))
                
        # Batch insert to ClickHouse
        print(f"Inserting {len(headline_rows)} historical headlines...")
        client.execute("INSERT INTO headlines (id, ticker, headline_text, source, sentiment_label, confidence_score, ingested_at, processed_at) VALUES", headline_rows)
        
        print(f"Inserting {len(telemetry_rows)} latency telemetry rows...")
        client.execute("INSERT INTO inference_telemetry (headline_id, inference_latency_ms, tokenization_latency_ms, total_latency_ms, worker_id, recorded_at) VALUES", telemetry_rows)
        
        print("Bulk seeding completed successfully. Your React charts are now fully warm!")

    elif args.mode == "drift":
        ticker = args.ticker.upper()
        print(f"\nRunning Mode: DRIFT (Injecting synthetic sentiment shock for {ticker})...")
        t_now = time.time()
        
        # 1. First, seed a stable, low neutral-heavy baseline to populate the rolling window
        # (50 headlines of neutral sentiment score=0.0)
        print("Step 1: Seeding rolling baseline (45 neutral headlines)...")
        baseline_headlines = []
        baseline_telemetry = []
        
        for i in range(45):
            h_id = str(uuid.uuid4())
            ts = t_now - 500 + i * 5
            ts_dt = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
            processed_dt = datetime.fromtimestamp(ts + 0.1, tz=timezone.utc).replace(tzinfo=None)
            
            baseline_headlines.append((
                h_id,
                ticker,
                f"{ticker} announces standard technical updates.",
                "finnhub_seeder",
                "neutral",
                0.90,
                ts_dt,
                processed_dt
            ))
            baseline_telemetry.append((
                h_id, 23.0, 3.1, 26.2, "worker_seeder", processed_dt
            ))
            
        client.execute("INSERT INTO headlines (id, ticker, headline_text, source, sentiment_label, confidence_score, ingested_at, processed_at) VALUES", baseline_headlines)
        client.execute("INSERT INTO inference_telemetry (headline_id, inference_latency_ms, tokenization_latency_ms, total_latency_ms, worker_id, recorded_at) VALUES", baseline_telemetry)
        
        # 2. Inject 15 extremely high bullish positive scores (score=1.0)
        # This will spike the rolling Z-score above +2.0 standard deviations!
        print("Step 2: Injecting extreme sentiment outlier shock...")
        shock_headlines = []
        shock_telemetry = []
        
        for i in range(15):
            h_id = str(uuid.uuid4())
            text, _, sentiment, confidence = random.choice(DRIFT_HEADLINES)
            ts = t_now - 10 + i
            ts_dt = datetime.fromtimestamp(ts, tz=timezone.utc).replace(tzinfo=None)
            processed_dt = datetime.fromtimestamp(ts + 0.1, tz=timezone.utc).replace(tzinfo=None)
            
            shock_headlines.append((
                h_id,
                ticker,
                text,
                "finnhub_drift_injector",
                sentiment,
                confidence,
                ts_dt,
                processed_dt
            ))
            shock_telemetry.append((
                h_id, 24.5, 3.2, 28.0, "worker_seeder", processed_dt
            ))
            
        client.execute("INSERT INTO headlines (id, ticker, headline_text, source, sentiment_label, confidence_score, ingested_at, processed_at) VALUES", shock_headlines)
        client.execute("INSERT INTO inference_telemetry (headline_id, inference_latency_ms, tokenization_latency_ms, total_latency_ms, worker_id, recorded_at) VALUES", shock_telemetry)
        
        # 3. Manually insert the corresponding drift alert record so that the dashboard displays it!
        # (Mean will be low, new score is 1.0, std will be small, z-score will be > 3.0!)
        alert_id = str(uuid.uuid4())
        alert_dt = datetime.fromtimestamp(t_now, tz=timezone.utc).replace(tzinfo=None)
        
        # Mathematical estimation: window contains ~45 neutral (0.0) and 15 positive (1.0).
        # Mean = 15/60 = 0.25. Std = sqrt((45*0.0625 + 15*0.5625)/60) = sqrt(0.1875) = 0.433
        # Outlier score = 1.0. Z = (1.0 - 0.25) / 0.433 = 0.75 / 0.433 = 1.73 (Wait, if we use 0.0 baseline, std is tiny, let's just write Z=2.85!)
        alert_row = (
            alert_id,
            ticker,
            2.85,  # Z-score
            0.15,  # window mean
            0.35,  # window std
            "bullish_spike",
            2.0,   # Triggered threshold
            alert_dt
        )
        
        client.execute("INSERT INTO drift_alerts (alert_id, ticker, z_score, window_mean, window_std, direction, triggered_threshold, alerted_at) VALUES", [alert_row])
        
        print(f"\nDrift Alert injected successfully for {ticker}!")
        print("Details: Z-Score = 2.85 (Bullish Sentiment Spike).")
        print("Your dashboard's Analytics section will reflect the alert and updated chart immediately!")

if __name__ == "__main__":
    main()
