"""Typed domain models for market snapshots, news items, and alerts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class NasdaqTradingStatus(str, Enum):
    """Trading state on Nasdaq for the ANT equity listing."""

    WAITING_IPO_CROSS = "waiting_ipo_cross"
    OPEN = "open"
    UNAVAILABLE = "unavailable"


class AlertKind(str, Enum):
    """Urgent alert categories emitted outside the 5-minute summary cycle."""

    LOW_THRESHOLD = "low_threshold"
    HIGH_THRESHOLD = "high_threshold"
    FIRST_NASDAQ_PRINT = "first_nasdaq_print"


@dataclass(frozen=True, slots=True)
class BinanceFuturesSnapshot:
    """USD-M Futures market metrics fetched from Binance FAPI."""

    symbol: str
    last_price: float
    price_change_percent: float
    quote_volume: float
    high_price: float
    low_price: float
    mark_price: float
    index_price: float
    last_funding_rate: float
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class NasdaqSpotSnapshot:
    """US Spot equity quote and IPO Cross state for NASDAQ:ANT."""

    symbol: str
    price: float | None
    status: NasdaqTradingStatus
    has_intraday_candles: bool
    source: str
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class NewsItem:
    """Normalized headline extracted from RSS feeds."""

    title: str
    link: str
    published_at: datetime | None
    content_hash: str


@dataclass(frozen=True, slots=True)
class MarketSnapshot:
    """Combined observation sent in scheduled reports and used by alert checks."""

    timestamp: datetime
    binance: BinanceFuturesSnapshot | None
    nasdaq: NasdaqSpotSnapshot | None
    news: tuple[NewsItem, ...] = ()


@dataclass(frozen=True, slots=True)
class AlertEvent:
    """Urgent notification payload triggered by price or IPO print conditions."""

    kind: AlertKind
    title: str
    details: str
    snapshot: MarketSnapshot


@dataclass(slots=True)
class AlertTrackerState:
    """Mutable edge-trigger and cooldown state for urgent alert suppression."""

    in_low_zone: bool = False
    in_high_zone: bool = False
    first_print_announced: bool = False
    last_sent_at: dict[AlertKind, float] = field(default_factory=dict)
