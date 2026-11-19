"""Asynchronous Binance USD-M Futures market client."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

import httpx

from ant_monitor.models import BinanceFuturesSnapshot

logger = logging.getLogger(__name__)

BINANCE_FAPI_BASE = "https://fapi.binance.com"


class BinanceFuturesClient:
    """Fetches 24h ticker stats and mark/index pricing for a Binance USD-M symbol."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        symbol: str = "ANTUSDT",
        base_url: str = BINANCE_FAPI_BASE,
    ) -> None:
        self._client = http_client
        self._symbol = symbol
        self._base_url = base_url.rstrip("/")

    async def fetch_snapshot(self) -> BinanceFuturesSnapshot | None:
        """Fetch ticker/24hr and premiumIndex concurrently; return None on failure."""
        ticker_url = f"{self._base_url}/fapi/v1/ticker/24hr"
        premium_url = f"{self._base_url}/fapi/v1/premiumIndex"
        params = {"symbol": self._symbol}

        try:
            ticker_resp, premium_resp = await asyncio.gather(
                self._client.get(ticker_url, params=params),
                self._client.get(premium_url, params=params),
            )
            ticker_resp.raise_for_status()
            premium_resp.raise_for_status()

            ticker = ticker_resp.json()
            premium = premium_resp.json()

            return BinanceFuturesSnapshot(
                symbol=self._symbol,
                last_price=float(ticker["lastPrice"]),
                price_change_percent=float(ticker["priceChangePercent"]),
                quote_volume=float(ticker["quoteVolume"]),
                high_price=float(ticker["highPrice"]),
                low_price=float(ticker["lowPrice"]),
                mark_price=float(premium["markPrice"]),
                index_price=float(premium["indexPrice"]),
                last_funding_rate=float(premium.get("lastFundingRate", 0.0)),
                fetched_at=datetime.now(timezone.utc),
            )
        except (httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            logger.warning("Binance fetch failed for %s: %s", self._symbol, exc)
            return None
