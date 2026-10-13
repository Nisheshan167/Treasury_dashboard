import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str = "sqlite:///treasury.db"
    openai_api_key: str = ""
    openai_model: str = "gpt-4.1"
    te_api_key: str = ""
    fred_api_key: str = ""
    quote_feed_url: str = ""
    quote_feed_token: str = ""
    research_interval_minutes: int = 360
    ai_daily_request_limit: int = 8
    quote_interval_seconds: int = 60
    auto_collect: bool = True
    te_10y_symbol: str = "USGG10YR:IND"
    te_30y_symbol: str = "USGG30Y:IND"

    @classmethod
    def load(cls, secrets=None):
        secrets = dict(secrets or {})
        def get(key, default):
            value = secrets.get(key, os.getenv(key, default))
            return default if value == "" and not isinstance(default, str) else value
        return cls(
            database_url=str(get("DATABASE_URL", cls.database_url) or cls.database_url),
            openai_api_key=str(get("OPENAI_API_KEY", "")),
            openai_model=str(get("OPENAI_MODEL", cls.openai_model)),
            te_api_key=str(get("TRADING_ECONOMICS_KEY", "")),
            fred_api_key=str(get("FRED_API_KEY", "")),
            quote_feed_url=str(get("QUOTE_FEED_URL", "")),
            quote_feed_token=str(get("QUOTE_FEED_TOKEN", "")),
            research_interval_minutes=max(30, int(get("RESEARCH_INTERVAL_MINUTES", 360))),
            ai_daily_request_limit=max(0, int(get("AI_DAILY_REQUEST_LIMIT", 8))),
            quote_interval_seconds=max(30, int(get("QUOTE_INTERVAL_SECONDS", 60))),
            auto_collect=str(get("AUTO_COLLECT", "true")).lower() == "true",
            te_10y_symbol=str(get("TE_10Y_SYMBOL", cls.te_10y_symbol)),
            te_30y_symbol=str(get("TE_30Y_SYMBOL", cls.te_30y_symbol)),
        )
