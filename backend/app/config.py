import os

from pydantic import BaseModel, Field


class Settings(BaseModel):
    # API Keys
    FINNHUB_API_KEY: str = Field(default="")
    ALPACA_API_KEY: str = Field(default="")
    ALPACA_API_SECRET: str = Field(default="")

    # Message Broker
    REDIS_URL: str = Field(default="redis://localhost:6379")

    # Analytics Database
    CLICKHOUSE_HOST: str = Field(default="localhost")
    CLICKHOUSE_PORT: int = Field(default=9000)
    CLICKHOUSE_HTTP_PORT: int = Field(default=8123)
    CLICKHOUSE_USER: str = Field(default="default")
    CLICKHOUSE_PASSWORD: str = Field(default="")
    CLICKHOUSE_DATABASE: str = Field(default="default")

    # Statistical Drift Detection
    DRIFT_WINDOW_SIZE: int = Field(default=100)
    DRIFT_ALERT_Z_THRESHOLD: float = Field(default=2.0)
    DRIFT_MIN_SAMPLES: int = Field(default=30)

    # Ingestion Parameters
    POLL_INTERVAL: int = Field(default=60)
    LOG_LEVEL: str = Field(default="INFO")

    # Paper Trading Strategy Selection
    TRADING_STRATEGY: str = Field(default="threshold")
    TRADING_ENGINE: str = Field(default="simulated")
    INITIAL_PORTFOLIO_CAPITAL: float = Field(default=100000.0)
    FORCE_TRADE_COST_USD: float = Field(default=0.0)

    @classmethod
    def load(cls):
        # Gather defaults from class fields
        env_data = {}
        for name, field in cls.model_fields.items():
            val = os.environ.get(name)
            if val is not None:
                env_data[name] = val
            else:
                env_data[name] = field.default

        # Attempt to read from .env file inside workspace
        env_path = ".env"
        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        # Clean up quotes around value
                        v = v.strip().strip('"').strip("'")
                        if k in cls.model_fields:
                            env_data[k] = v
        
        # Parse and validate with Pydantic
        return cls(**env_data)

settings = Settings.load()
