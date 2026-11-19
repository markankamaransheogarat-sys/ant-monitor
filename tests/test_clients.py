"""Tests for Binance, Nasdaq, and Telegram HTTP clients."""

from __future__ import annotations

import json

import httpx
import pytest

from ant_monitor.clients.binance import BinanceFuturesClient
from ant_monitor.clients.nasdaq import NasdaqSpotClient, classify_nasdaq_status
from ant_monitor.clients.telegram import TelegramClient
from ant_monitor.models import NasdaqTradingStatus


@pytest.mark.asyncio
async def test_binance_client_happy_path_and_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/ticker/24hr"):
            return httpx.Response(
                200,
                json={
                    "lastPrice": "104.20",
                    "priceChangePercent": "6.10",
                    "quoteVolume": "285400000.0",
                    "highPrice": "106.0",
                    "lowPrice": "97.5",
                },
            )
        if request.url.path.endswith("/premiumIndex"):
            return httpx.Response(
                200,
                json={
                    "markPrice": "104.15",
                    "indexPrice": "103.80",
                    "lastFundingRate": "0.0001",
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        api = BinanceFuturesClient(client, symbol="ANTUSDT")
        snap = await api.fetch_snapshot()
        assert snap is not None
        assert snap.last_price == pytest.approx(104.20)
        assert snap.mark_price == pytest.approx(104.15)
        assert snap.index_price == pytest.approx(103.80)
        assert snap.quote_volume == pytest.approx(285_400_000.0)

    def fail_handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="Service Unavailable")

    async with httpx.AsyncClient(transport=httpx.MockTransport(fail_handler)) as client:
        api = BinanceFuturesClient(client, symbol="ANTUSDT")
        assert await api.fetch_snapshot() is None


def test_classify_nasdaq_status_handles_ipo_cross_and_first_print() -> None:
    assert (
        classify_nasdaq_status(None, False, 83.0)
        == NasdaqTradingStatus.WAITING_IPO_CROSS
    )
    assert (
        classify_nasdaq_status(83.0, False, 83.0)
        == NasdaqTradingStatus.WAITING_IPO_CROSS
    )
    assert classify_nasdaq_status(83.0, True, 83.0) == NasdaqTradingStatus.OPEN
    assert classify_nasdaq_status(103.85, False, 83.0) == NasdaqTradingStatus.OPEN


@pytest.mark.asyncio
async def test_nasdaq_client_falls_back_to_finnhub_when_yfinance_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_yf(_symbol: str, *_args: object) -> tuple[float | None, bool]:
        raise RuntimeError("Yahoo rate limited")

    monkeypatch.setattr("ant_monitor.clients.nasdaq._fetch_yfinance_sync", broken_yf)

    def handler(request: httpx.Request) -> httpx.Response:
        if "finnhub.io" in str(request.url):
            return httpx.Response(200, json={"c": 103.85})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = NasdaqSpotClient(
            http_client=http_client,
            symbol="ANT",
            ipo_reference_price=83.0,
            finnhub_api_key="fh-key",
        )
        snap = await client.fetch_snapshot()
        assert snap is not None
        assert snap.price == pytest.approx(103.85)
        assert snap.status == NasdaqTradingStatus.OPEN
        assert snap.source == "finnhub"


@pytest.mark.asyncio
async def test_nasdaq_client_returns_unavailable_when_all_sources_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_yf(_symbol: str, *_args: object) -> tuple[float | None, bool]:
        raise TimeoutError("timed out")

    monkeypatch.setattr("ant_monitor.clients.nasdaq._fetch_yfinance_sync", broken_yf)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(500))
    ) as http_client:
        client = NasdaqSpotClient(http_client=http_client, symbol="ANT")
        snap = await client.fetch_snapshot()
        assert snap is not None
        assert snap.price is None
        assert snap.status == NasdaqTradingStatus.UNAVAILABLE


@pytest.mark.asyncio
async def test_telegram_client_send_success_and_error() -> None:
    captured: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(json.loads(request.content.decode()))
        if "badtoken" in str(request.url):
            return httpx.Response(401, json={"ok": False})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        ok_tg = TelegramClient(http_client, bot_token="good", chat_id="999")
        assert await ok_tg.send_message("<b>Hi</b>") is True
        assert captured[0]["chat_id"] == "999"
        assert captured[0]["parse_mode"] == "HTML"

        bad_tg = TelegramClient(http_client, bot_token="badtoken", chat_id="999")
        assert await bad_tg.send_message("Hi") is False
