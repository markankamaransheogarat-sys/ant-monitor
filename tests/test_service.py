"""Tests for service resilience, config validation, and startup dispatch."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest

from ant_monitor.config import MonitorConfig
from ant_monitor.models import NasdaqSpotSnapshot, NasdaqTradingStatus
from ant_monitor.service import AntMonitorService


class _FailingBinance:
    async def fetch_snapshot(self):
        raise RuntimeError("Binance down")


class _StubNasdaq:
    async def fetch_snapshot(self):
        return NasdaqSpotSnapshot(
            symbol="ANT",
            price=83.0,
            status=NasdaqTradingStatus.WAITING_IPO_CROSS,
            has_intraday_candles=False,
            source="yfinance",
            fetched_at=datetime.now(timezone.utc),
        )


class _StubNews:
    async def fetch_recent_news(self):
        return ()


class _SpyTelegram:
    def __init__(self) -> None:
        self.messages: list[str] = []

    async def send_message(self, text: str) -> bool:
        self.messages.append(text)
        return True


def test_config_validation_enforces_http_timeout_and_telegram() -> None:
    bad_timeout = MonitorConfig(
        telegram_bot_token="t",
        telegram_chat_id="c",
        http_timeout_seconds=6.0,
    )
    with pytest.raises(ValueError, match="HTTP_TIMEOUT_SECONDS"):
        bad_timeout.validate(require_telegram=True)

    missing_tg = MonitorConfig(telegram_bot_token="", telegram_chat_id="")
    with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
        missing_tg.validate(require_telegram=True)
    missing_tg.validate(require_telegram=False)


def test_config_reads_proxy_url_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PROXY_URL", "http://127.0.0.1:8080")
    cfg = MonitorConfig.from_env()
    assert cfg.proxy_url == "http://127.0.0.1:8080"


@pytest.mark.asyncio
async def test_service_sends_startup_message_even_if_one_source_raises() -> None:
    cfg = MonitorConfig(
        telegram_bot_token="t",
        telegram_chat_id="c",
        poll_interval_seconds=300,
        alert_interval_seconds=45,
    )
    spy = _SpyTelegram()
    service = AntMonitorService(
        config=cfg,
        binance_client=_FailingBinance(),  # type: ignore[arg-type]
        nasdaq_client=_StubNasdaq(),  # type: ignore[arg-type]
        news_client=_StubNews(),  # type: ignore[arg-type]
        telegram_client=spy,  # type: ignore[arg-type]
    )

    stop_event = asyncio.Event()
    task = asyncio.create_task(service.run(stop_event=stop_event))
    await asyncio.sleep(0.05)
    stop_event.set()
    await asyncio.wait_for(task, timeout=1.0)

    assert len(spy.messages) == 1
    assert "Last Price: N/A" in spy.messages[0]
    assert "Ожидание первого принта на Nasdaq" in spy.messages[0]
