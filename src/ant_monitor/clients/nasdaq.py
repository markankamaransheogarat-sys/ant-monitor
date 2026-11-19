"""Nasdaq US spot quote client using yfinance with optional Finnhub/Polygon fallback."""

from __future__ import annotations

import asyncio
import logging
import math
import threading
from datetime import datetime, timezone
from typing import Any

import httpx
import yfinance as yf

from ant_monitor.models import NasdaqSpotSnapshot, NasdaqTradingStatus

logger = logging.getLogger(__name__)


def _finite_positive(value: Any) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    if math.isfinite(num) and num > 0:
        return num
    return None


def classify_nasdaq_status(
    price: float | None,
    has_intraday_candles: bool,
    ipo_reference_price: float,
) -> NasdaqTradingStatus:
    """Determine whether Nasdaq regular trading has printed or is waiting for IPO Cross."""
    if has_intraday_candles and price is not None:
        return NasdaqTradingStatus.OPEN
    if price is None:
        return NasdaqTradingStatus.WAITING_IPO_CROSS
    if abs(price - ipo_reference_price) >= 1e-4:
        return NasdaqTradingStatus.OPEN
    return NasdaqTradingStatus.WAITING_IPO_CROSS


def _fetch_yfinance_sync(
    symbol: str, timeout_seconds: float = 4.0
) -> tuple[float | None, bool]:
    ticker = yf.Ticker(symbol)

    price: float | None = None
    fast_info = getattr(ticker, "fast_info", None)
    if fast_info is not None:
        for key in ("lastPrice", "last_price", "regularMarketPrice"):
            try:
                candidate = (
                    fast_info.get(key) if hasattr(fast_info, "get") else fast_info[key]
                )
            except (KeyError, TypeError, AttributeError):
                candidate = None
            price = _finite_positive(candidate)
            if price is not None:
                break

    hist = ticker.history(period="1d", interval="1m", timeout=timeout_seconds)
    has_candles = hist is not None and not hist.empty and len(hist.index) > 0
    if price is None and has_candles and "Close" in hist:
        price = _finite_positive(hist["Close"].iloc[-1])

    return price, has_candles


class NasdaqSpotClient:
    """Fetches NASDAQ:ANT spot price via yfinance, falling back to Finnhub or Polygon."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        symbol: str = "ANT",
        ipo_reference_price: float = 83.0,
        timeout_seconds: float = 5.0,
        finnhub_api_key: str = "",
        polygon_api_key: str = "",
    ) -> None:
        self._client = http_client
        self._symbol = symbol
        self._ipo_ref = ipo_reference_price
        self._timeout = timeout_seconds
        self._finnhub_key = finnhub_api_key
        self._polygon_key = polygon_api_key
        self._yf_busy_lock = threading.Lock()
        self._yf_in_flight = False

    async def _run_yfinance_daemon(self) -> tuple[float | None, bool]:
        with self._yf_busy_lock:
            if self._yf_in_flight:
                raise TimeoutError("previous yfinance request still in flight")
            self._yf_in_flight = True

        loop = asyncio.get_running_loop()
        future: asyncio.Future[tuple[float | None, bool]] = loop.create_future()

        def _worker() -> None:
            try:
                result = _fetch_yfinance_sync(self._symbol, min(self._timeout, 4.0))
            except BaseException as exc:
                if not loop.is_closed():
                    loop.call_soon_threadsafe(
                        lambda e=exc: future.done() or future.set_exception(e)
                    )
            else:
                if not loop.is_closed():
                    loop.call_soon_threadsafe(
                        lambda r=result: future.done() or future.set_result(r)
                    )
            finally:
                with self._yf_busy_lock:
                    self._yf_in_flight = False

        threading.Thread(target=_worker, name=f"yf-{self._symbol}", daemon=True).start()
        return await asyncio.wait_for(future, timeout=self._timeout)

    async def _fetch_finnhub(self) -> float | None:
        if not self._finnhub_key:
            return None
        try:
            resp = await self._client.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": self._symbol, "token": self._finnhub_key},
            )
            resp.raise_for_status()
            data = resp.json()
            return _finite_positive(data.get("c"))
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("Finnhub quote failed for %s: %s", self._symbol, exc)
            return None

    async def _fetch_polygon(self) -> float | None:
        if not self._polygon_key:
            return None
        try:
            resp = await self._client.get(
                f"https://api.polygon.io/v2/last/trade/{self._symbol}",
                params={"apiKey": self._polygon_key},
            )
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results") or {}
            return _finite_positive(results.get("p"))
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.warning("Polygon quote failed for %s: %s", self._symbol, exc)
            return None

    async def fetch_snapshot(self) -> NasdaqSpotSnapshot | None:
        """Fetch Nasdaq spot quote without raising on upstream errors or timeouts."""
        now = datetime.now(timezone.utc)
        yf_failed = False
        price: float | None = None
        has_candles = False
        source = "yfinance"

        try:
            price, has_candles = await self._run_yfinance_daemon()
        except TimeoutError:
            yf_failed = True
            logger.warning(
                "yfinance fetch timed out for %s after %.1fs",
                self._symbol,
                self._timeout,
            )
        except Exception as exc:
            yf_failed = True
            logger.warning(
                "yfinance fetch failed for %s: %s: %s",
                self._symbol,
                type(exc).__name__,
                exc,
            )

        if price is None or (yf_failed and not has_candles):
            backup_price = await self._fetch_finnhub()
            if backup_price is not None:
                price = backup_price
                source = "finnhub"
                yf_failed = False
            else:
                poly_price = await self._fetch_polygon()
                if poly_price is not None:
                    price = poly_price
                    source = "polygon"
                    yf_failed = False

        if yf_failed and price is None:
            return NasdaqSpotSnapshot(
                symbol=self._symbol,
                price=None,
                status=NasdaqTradingStatus.UNAVAILABLE,
                has_intraday_candles=False,
                source="unavailable",
                fetched_at=now,
            )

        status = classify_nasdaq_status(
            price=price,
            has_intraday_candles=has_candles,
            ipo_reference_price=self._ipo_ref,
        )
        return NasdaqSpotSnapshot(
            symbol=self._symbol,
            price=price,
            status=status,
            has_intraday_candles=has_candles,
            source=source,
            fetched_at=now,
        )
