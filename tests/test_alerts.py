"""Tests for spread math, liquidation buffer calculations, and urgent alert triggers."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from ant_monitor.alerts import (
    compute_liquidation_buffer,
    compute_spread_pct,
    evaluate_urgent_alerts,
)
from ant_monitor.config import MonitorConfig
from ant_monitor.models import (
    AlertKind,
    AlertTrackerState,
    BinanceFuturesSnapshot,
    MarketSnapshot,
    NasdaqSpotSnapshot,
    NasdaqTradingStatus,
)


def _cfg(**overrides: object) -> MonitorConfig:
    base = {
        "telegram_bot_token": "tok",
        "telegram_chat_id": "123",
        "alert_cooldown_seconds": 900,
    }
    base.update(overrides)
    return MonitorConfig(**base)  # type: ignore[arg-type]


def _binance(
    mark: float, index: float = 103.8, last: float | None = None
) -> BinanceFuturesSnapshot:
    return BinanceFuturesSnapshot(
        symbol="ANTUSDT",
        last_price=last if last is not None else mark,
        price_change_percent=6.1,
        quote_volume=285_400_000.0,
        high_price=108.0,
        low_price=96.0,
        mark_price=mark,
        index_price=index,
        last_funding_rate=0.0001,
        fetched_at=datetime(2026, 11, 19, 16, 50, tzinfo=timezone.utc),
    )


def _nasdaq(
    price: float | None,
    status: NasdaqTradingStatus,
    candles: bool = False,
) -> NasdaqSpotSnapshot:
    return NasdaqSpotSnapshot(
        symbol="ANT",
        price=price,
        status=status,
        has_intraday_candles=candles,
        source="yfinance",
        fetched_at=datetime(2026, 11, 19, 16, 50, tzinfo=timezone.utc),
    )


def test_spread_and_liquidation_buffer_match_spec_example() -> None:
    spread = compute_spread_pct(104.15, 103.80)
    assert spread is not None
    assert spread == pytest.approx(0.33718689, rel=1e-4)
    assert compute_spread_pct(100.0, 0.0) is None

    buf = compute_liquidation_buffer(104.15, 77.0)
    assert buf is not None
    pct, usd = buf
    assert f"{pct:.1f}%" == "-26.1%"
    assert usd == pytest.approx(27.15, abs=1e-6)
    assert compute_liquidation_buffer(0.0, 77.0) is None


def test_low_and_high_alerts_edge_trigger_and_cooldown() -> None:
    cfg = _cfg()
    state = AlertTrackerState()
    now = datetime(2026, 11, 19, 16, 50, tzinfo=timezone.utc)

    # Normal range -> no alerts
    snap_ok = MarketSnapshot(timestamp=now, binance=_binance(100.0), nasdaq=None)
    assert evaluate_urgent_alerts(snap_ok, cfg, state, now_mono=10.0) == []

    # Drop below $85 -> triggers LOW_THRESHOLD immediately
    snap_low = MarketSnapshot(timestamp=now, binance=_binance(84.5), nasdaq=None)
    events = evaluate_urgent_alerts(snap_low, cfg, state, now_mono=50.0)
    assert [e.kind for e in events] == [AlertKind.LOW_THRESHOLD]

    # Still below $85 within cooldown -> suppressed
    assert evaluate_urgent_alerts(snap_low, cfg, state, now_mono=100.0) == []

    # Still below $85 after cooldown -> re-emits
    events_repeat = evaluate_urgent_alerts(snap_low, cfg, state, now_mono=960.0)
    assert [e.kind for e in events_repeat] == [AlertKind.LOW_THRESHOLD]

    # Cross above $110 -> triggers HIGH_THRESHOLD
    snap_high = MarketSnapshot(timestamp=now, binance=_binance(111.2), nasdaq=None)
    events_high = evaluate_urgent_alerts(snap_high, cfg, state, now_mono=1000.0)
    assert [e.kind for e in events_high] == [AlertKind.HIGH_THRESHOLD]


def test_first_nasdaq_print_fires_once_on_open() -> None:
    cfg = _cfg()
    state = AlertTrackerState()
    now = datetime(2026, 11, 19, 16, 50, tzinfo=timezone.utc)

    waiting = MarketSnapshot(
        timestamp=now,
        binance=_binance(104.0),
        nasdaq=_nasdaq(83.0, NasdaqTradingStatus.WAITING_IPO_CROSS, candles=False),
    )
    assert evaluate_urgent_alerts(waiting, cfg, state, now_mono=10.0) == []

    opened = MarketSnapshot(
        timestamp=now,
        binance=_binance(104.0),
        nasdaq=_nasdaq(103.85, NasdaqTradingStatus.OPEN, candles=True),
    )
    events = evaluate_urgent_alerts(opened, cfg, state, now_mono=55.0)
    assert [e.kind for e in events] == [AlertKind.FIRST_NASDAQ_PRINT]
    assert "Спред Binance Mark к Nasdaq" in events[0].details

    # Subsequent ticks must not repeat the first-print alert
    assert evaluate_urgent_alerts(opened, cfg, state, now_mono=2000.0) == []
