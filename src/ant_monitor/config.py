"""Configuration loading and validation for ANT Monitor."""

from __future__ import annotations

import os
from dataclasses import dataclass
from dotenv import load_dotenv

DEFAULT_RSS_URL = (
    "https://news.google.com/rss/search"
    "?q=Anthropic+IPO+ANT+stock&hl=en-US&gl=US&ceid=US:en"
)


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


@dataclass(frozen=True, slots=True)
class MonitorConfig:
    """Runtime settings loaded from environment variables and `.env`."""

    telegram_bot_token: str
    telegram_chat_id: str
    entry_price: float = 106.5
    liquidation_price: float = 77.0
    alert_low_threshold: float = 85.0
    alert_high_threshold: float = 110.0
    ipo_reference_price: float = 83.0
    binance_symbol: str = "ANTUSDT"
    nasdaq_symbol: str = "ANT"
    poll_interval_seconds: int = 300
    alert_interval_seconds: int = 45
    alert_cooldown_seconds: int = 900
    http_timeout_seconds: float = 5.0
    news_window_minutes: int = 30
    news_max_items: int = 2
    news_rss_url: str = DEFAULT_RSS_URL
    finnhub_api_key: str = ""
    polygon_api_key: str = ""
    proxy_url: str = ""
    log_file: str = "monitor.log"
    log_level: str = "INFO"

    def validate(self, require_telegram: bool = True) -> None:
        """Validate configuration bounds before starting loops."""
        if require_telegram:
            if not self.telegram_bot_token.strip():
                raise ValueError("TELEGRAM_BOT_TOKEN is required")
            if not self.telegram_chat_id.strip():
                raise ValueError("TELEGRAM_CHAT_ID is required")
        if self.http_timeout_seconds <= 0 or self.http_timeout_seconds > 5.0:
            raise ValueError("HTTP_TIMEOUT_SECONDS must be in (0, 5.0]")
        if self.poll_interval_seconds <= 0:
            raise ValueError("POLL_INTERVAL_SECONDS must be positive")
        if self.alert_interval_seconds <= 0:
            raise ValueError("ALERT_INTERVAL_SECONDS must be positive")
        if self.alert_low_threshold >= self.alert_high_threshold:
            raise ValueError("ALERT_LOW_THRESHOLD must be < ALERT_HIGH_THRESHOLD")
        if self.liquidation_price <= 0:
            raise ValueError("LIQUIDATION_PRICE must be positive")

    @classmethod
    def from_env(cls, dotenv_path: str | None = None) -> "MonitorConfig":
        """Load configuration from `.env` (if present) and process environment."""
        load_dotenv(dotenv_path=dotenv_path, override=False)
        return cls(
            telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "").strip(),
            telegram_chat_id=os.getenv("TELEGRAM_CHAT_ID", "").strip(),
            entry_price=_env_float("ENTRY_PRICE", 106.5),
            liquidation_price=_env_float("LIQUIDATION_PRICE", 77.0),
            alert_low_threshold=_env_float("ALERT_LOW_THRESHOLD", 85.0),
            alert_high_threshold=_env_float("ALERT_HIGH_THRESHOLD", 110.0),
            ipo_reference_price=_env_float("IPO_REFERENCE_PRICE", 83.0),
            binance_symbol=os.getenv("BINANCE_SYMBOL", "ANTUSDT").strip().upper(),
            nasdaq_symbol=os.getenv("NASDAQ_SYMBOL", "ANT").strip().upper(),
            poll_interval_seconds=_env_int("POLL_INTERVAL_SECONDS", 300),
            alert_interval_seconds=_env_int("ALERT_INTERVAL_SECONDS", 45),
            alert_cooldown_seconds=_env_int("ALERT_COOLDOWN_SECONDS", 900),
            http_timeout_seconds=_env_float("HTTP_TIMEOUT_SECONDS", 5.0),
            news_window_minutes=_env_int("NEWS_WINDOW_MINUTES", 30),
            news_max_items=_env_int("NEWS_MAX_ITEMS", 2),
            news_rss_url=os.getenv("NEWS_RSS_URL", DEFAULT_RSS_URL).strip()
            or DEFAULT_RSS_URL,
            finnhub_api_key=os.getenv("FINNHUB_API_KEY", "").strip(),
            polygon_api_key=os.getenv("POLYGON_API_KEY", "").strip(),
            proxy_url=os.getenv("PROXY_URL", "").strip(),
            log_file=os.getenv("LOG_FILE", "monitor.log").strip() or "monitor.log",
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper() or "INFO",
        )
