"""Tests for Russian Telegram HTML formatting and N/A degradation."""

from __future__ import annotations

from datetime import datetime, timezone

from ant_monitor.config import MonitorConfig
from ant_monitor.formatter import format_scheduled_report, format_urgent_alert
from ant_monitor.models import (
    AlertEvent,
    AlertKind,
    BinanceFuturesSnapshot,
    MarketSnapshot,
    NasdaqSpotSnapshot,
    NasdaqTradingStatus,
    NewsItem,
)


def test_format_scheduled_report_full_snapshot() -> None:
    cfg = MonitorConfig(telegram_bot_token="t", telegram_chat_id="c")
    # 16:50 UTC == 19:50 MSK
    ts = datetime(2026, 11, 19, 16, 50, tzinfo=timezone.utc)
    snap = MarketSnapshot(
        timestamp=ts,
        binance=BinanceFuturesSnapshot(
            symbol="ANTUSDT",
            last_price=104.20,
            price_change_percent=6.1,
            quote_volume=285_400_000.0,
            high_price=106.0,
            low_price=97.0,
            mark_price=104.15,
            index_price=103.80,
            last_funding_rate=0.0001,
            fetched_at=ts,
        ),
        nasdaq=NasdaqSpotSnapshot(
            symbol="ANT",
            price=103.85,
            status=NasdaqTradingStatus.OPEN,
            has_intraday_candles=True,
            source="yfinance",
            fetched_at=ts,
        ),
        news=(
            NewsItem(
                title="Anthropic <ANT> jumps on Nasdaq debut",
                link="https://news.example.com/ant?a=1&b=2",
                published_at=ts,
                content_hash="abc",
            ),
        ),
    )

    text = format_scheduled_report(snap, cfg)
    assert "19:50 МСК" in text
    assert "$104.20" in text
    assert "+6.1%" in text
    assert "$104.15" in text
    assert "$103.80" in text
    assert "+0.34%" in text
    assert "$285.4M" in text
    assert "Торги открыты" in text
    assert "$103.85" in text
    assert "-26.1%" in text
    assert "$27.15" in text
    assert "Anthropic &lt;ANT&gt; jumps on Nasdaq debut" in text
    assert 'href="https://news.example.com/ant?a=1&amp;b=2"' in text


def test_format_scheduled_report_degrades_to_na() -> None:
    cfg = MonitorConfig(telegram_bot_token="t", telegram_chat_id="c")
    snap = MarketSnapshot(
        timestamp=datetime(2026, 11, 19, 16, 50, tzinfo=timezone.utc),
        binance=None,
        nasdaq=None,
        news=(),
    )
    text = format_scheduled_report(snap, cfg)
    assert "Last Price: N/A" in text
    assert "Статус: N/A" in text
    assert "Запас до ликвидации: N/A" in text
    assert "Новых заголовков нет" in text


def test_format_urgent_alert() -> None:
    snap = MarketSnapshot(
        timestamp=datetime(2026, 11, 19, 16, 50, tzinfo=timezone.utc),
        binance=None,
        nasdaq=None,
    )
    ev = AlertEvent(
        kind=AlertKind.LOW_THRESHOLD,
        title="ОПАСНАЯ ЗОНА <85>",
        details="Mark Price: $84.00",
        snapshot=snap,
    )
    text = format_urgent_alert(ev)
    assert "ANT ALERT" in text
    assert "19:50 МСК" in text
    assert "ОПАСНАЯ ЗОНА &lt;85&gt;" in text
