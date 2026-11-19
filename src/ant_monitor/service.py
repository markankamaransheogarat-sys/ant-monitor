"""Async daemon orchestration with drift-free scheduling and rotating file logging."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from typing import Awaitable, Callable

import httpx

from ant_monitor.alerts import evaluate_urgent_alerts
from ant_monitor.clients.binance import BinanceFuturesClient
from ant_monitor.clients.nasdaq import NasdaqSpotClient
from ant_monitor.clients.news import NewsFeedClient
from ant_monitor.clients.telegram import TelegramClient
from ant_monitor.config import MonitorConfig
from ant_monitor.formatter import format_scheduled_report, format_urgent_alert
from ant_monitor.models import (
    AlertTrackerState,
    BinanceFuturesSnapshot,
    MarketSnapshot,
    NasdaqSpotSnapshot,
    NewsItem,
)

logger = logging.getLogger(__name__)


def configure_logging(log_file: str, level: str = "INFO") -> None:
    """Configure root logging to stdout and a size-rotated `monitor.log` file."""
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    for handler in list(root.handlers):
        root.removeHandler(handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)


async def _wait_until(
    deadline: float,
    stop_event: asyncio.Event,
    clock: Callable[[], float],
) -> bool:
    """Sleep until `deadline` unless `stop_event` is set. Returns False if stopped."""
    delay = deadline - clock()
    if delay <= 0:
        return not stop_event.is_set()
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=delay)
        return False
    except TimeoutError:
        return True


class AntMonitorService:
    """Coordinates scheduled 5-minute summaries and rapid 30-60s alert polling."""

    def __init__(
        self,
        config: MonitorConfig,
        binance_client: BinanceFuturesClient,
        nasdaq_client: NasdaqSpotClient,
        news_client: NewsFeedClient,
        telegram_client: TelegramClient | None,
        dry_run: bool = False,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._config = config
        self._binance = binance_client
        self._nasdaq = nasdaq_client
        self._news = news_client
        self._telegram = telegram_client
        self._dry_run = dry_run
        self._clock = clock or (lambda: asyncio.get_running_loop().time())
        self._alert_state = AlertTrackerState()

    async def collect_snapshot(self, include_news: bool = True) -> MarketSnapshot:
        """Fetch enabled market and news sources concurrently without propagating exceptions."""
        binance_coro = self._binance.fetch_snapshot()
        nasdaq_coro = self._nasdaq.fetch_snapshot()

        if include_news:
            results = await asyncio.gather(
                binance_coro,
                nasdaq_coro,
                self._news.fetch_recent_news(),
                return_exceptions=True,
            )
            b_res, n_res, news_res = results
        else:
            b_res, n_res = await asyncio.gather(
                binance_coro,
                nasdaq_coro,
                return_exceptions=True,
            )
            news_res = ()

        binance_snap: BinanceFuturesSnapshot | None = (
            None if isinstance(b_res, BaseException) else b_res
        )
        if isinstance(b_res, BaseException):
            logger.error("Unexpected Binance client exception: %s", b_res)

        nasdaq_snap: NasdaqSpotSnapshot | None = (
            None if isinstance(n_res, BaseException) else n_res
        )
        if isinstance(n_res, BaseException):
            logger.error("Unexpected Nasdaq client exception: %s", n_res)

        news_items: tuple[NewsItem, ...] = (
            () if isinstance(news_res, BaseException) else news_res
        )
        if isinstance(news_res, BaseException):
            logger.error("Unexpected News client exception: %s", news_res)

        return MarketSnapshot(
            timestamp=datetime.now(timezone.utc),
            binance=binance_snap,
            nasdaq=nasdaq_snap,
            news=news_items,
        )

    async def _dispatch(self, text: str) -> bool:
        if self._dry_run or self._telegram is None:
            print(text)
            print("-" * 40)
            return True
        return await self._telegram.send_message(text)

    async def run_scheduled_cycle(self) -> MarketSnapshot:
        """Collect all sources, send the formatted summary, and check urgent triggers."""
        snapshot = await self.collect_snapshot(include_news=True)
        await self._dispatch(format_scheduled_report(snapshot, self._config))
        await self._emit_alerts(snapshot)
        return snapshot

    async def run_alert_cycle(self) -> MarketSnapshot:
        """Poll fast price/spot endpoints and dispatch urgent alerts if triggered."""
        snapshot = await self.collect_snapshot(include_news=False)
        await self._emit_alerts(snapshot)
        return snapshot

    async def _emit_alerts(self, snapshot: MarketSnapshot) -> None:
        events = evaluate_urgent_alerts(
            snapshot=snapshot,
            config=self._config,
            state=self._alert_state,
            now_mono=self._clock(),
        )
        for event in events:
            logger.warning(
                "Triggering urgent alert [%s]: %s", event.kind.value, event.title
            )
            await self._dispatch(format_urgent_alert(event))

    async def _run_periodic_loop(
        self,
        interval_seconds: int,
        callback: Callable[[], Awaitable[object]],
        stop_event: asyncio.Event,
        initial_delay: float,
    ) -> None:
        deadline = self._clock() + initial_delay
        while not stop_event.is_set():
            if not await _wait_until(deadline, stop_event, self._clock):
                break
            try:
                await callback()
            except Exception as exc:
                logger.exception("Unhandled error inside periodic task: %s", exc)
            deadline += interval_seconds
            now = self._clock()
            if deadline < now:
                missed = int((now - deadline) // interval_seconds) + 1
                deadline += missed * interval_seconds

    async def run(self, stop_event: asyncio.Event | None = None) -> None:
        """Send an immediate startup report and then run drift-free periodic loops."""
        stopper = stop_event or asyncio.Event()
        logger.info(
            "Starting ANT Monitor (poll=%ss, alert=%ss, dry_run=%s)",
            self._config.poll_interval_seconds,
            self._config.alert_interval_seconds,
            self._dry_run,
        )

        # Immediate startup report (criteria: first message within 5s of startup)
        await self.run_scheduled_cycle()

        await asyncio.gather(
            self._run_periodic_loop(
                interval_seconds=self._config.poll_interval_seconds,
                callback=self.run_scheduled_cycle,
                stop_event=stopper,
                initial_delay=float(self._config.poll_interval_seconds),
            ),
            self._run_periodic_loop(
                interval_seconds=self._config.alert_interval_seconds,
                callback=self.run_alert_cycle,
                stop_event=stopper,
                initial_delay=float(self._config.alert_interval_seconds),
            ),
        )


async def run_from_config(
    config: MonitorConfig,
    once: bool = False,
    dry_run: bool = False,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Instantiate HTTP clients and run either a single check or the background daemon."""
    config.validate(require_telegram=not dry_run)
    timeout = httpx.Timeout(config.http_timeout_seconds)
    proxy = config.proxy_url or None

    async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as http_client:
        binance_client = BinanceFuturesClient(http_client, symbol=config.binance_symbol)
        nasdaq_client = NasdaqSpotClient(
            http_client=http_client,
            symbol=config.nasdaq_symbol,
            ipo_reference_price=config.ipo_reference_price,
            timeout_seconds=config.http_timeout_seconds,
            finnhub_api_key=config.finnhub_api_key,
            polygon_api_key=config.polygon_api_key,
        )
        news_client = NewsFeedClient(
            http_client=http_client,
            rss_url=config.news_rss_url,
            window_minutes=config.news_window_minutes,
            max_items=config.news_max_items,
        )
        telegram_client = (
            None
            if dry_run
            else TelegramClient(
                http_client=http_client,
                bot_token=config.telegram_bot_token,
                chat_id=config.telegram_chat_id,
            )
        )
        service = AntMonitorService(
            config=config,
            binance_client=binance_client,
            nasdaq_client=nasdaq_client,
            news_client=news_client,
            telegram_client=telegram_client,
            dry_run=dry_run,
        )
        if once:
            await service.run_scheduled_cycle()
            return
        await service.run(stop_event=stop_event)
