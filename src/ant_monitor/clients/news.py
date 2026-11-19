"""Google News RSS client with recency filtering and SHA-256 deduplication."""

from __future__ import annotations

import calendar
import hashlib
import logging
from collections import deque
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse, urlunparse

import feedparser
import httpx

from ant_monitor.models import NewsItem

logger = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    """Strip whitespace and fragments so identical URLs hash consistently."""
    cleaned = url.strip()
    if not cleaned:
        return ""
    parsed = urlparse(cleaned)
    return urlunparse(
        (
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path,
            "",
            parsed.query,
            "",
        )
    )


def compute_news_hash(title: str, link: str) -> str:
    """Compute stable SHA-256 deduplication key preferring canonical URL, falling back to title."""
    canonical = normalize_url(link) or " ".join(title.lower().split())
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _parse_entry_time(entry: dict) -> datetime | None:
    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if struct is None:
        return None
    try:
        timestamp = calendar.timegm(struct)
    except (TypeError, ValueError, OverflowError):
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


class NewsFeedClient:
    """Fetches recent Anthropic IPO / ANT stock headlines and deduplicates across cycles."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        rss_url: str,
        window_minutes: int = 30,
        max_items: int = 2,
        max_seen_cache: int = 2000,
    ) -> None:
        self._client = http_client
        self._rss_url = rss_url
        self._window = timedelta(minutes=window_minutes)
        self._max_items = max_items
        self._max_seen = max_seen_cache
        self._seen_order: deque[str] = deque()
        self._seen_set: set[str] = set()

    def _remember(self, digest: str) -> None:
        if digest in self._seen_set:
            return
        if len(self._seen_order) >= self._max_seen:
            evicted = self._seen_order.popleft()
            self._seen_set.discard(evicted)
        self._seen_order.append(digest)
        self._seen_set.add(digest)

    def parse_feed(
        self, xml_payload: str, now: datetime | None = None
    ) -> tuple[NewsItem, ...]:
        """Parse RSS XML payload and return unseen items published within the recency window."""
        ref_now = now or datetime.now(timezone.utc)
        cutoff = ref_now - self._window
        parsed = feedparser.parse(xml_payload)

        candidates: list[NewsItem] = []
        batch_hashes: set[str] = set()

        for entry in parsed.entries:
            title = " ".join(str(entry.get("title", "")).split())
            link = str(entry.get("link", "")).strip()
            if not title:
                continue

            published_at = _parse_entry_time(entry)
            if published_at is not None and published_at < cutoff:
                continue

            digest = compute_news_hash(title, link)
            if digest in self._seen_set or digest in batch_hashes:
                continue
            batch_hashes.add(digest)
            candidates.append(
                NewsItem(
                    title=title,
                    link=link,
                    published_at=published_at,
                    content_hash=digest,
                )
            )

        candidates.sort(
            key=lambda item: (
                item.published_at or datetime.min.replace(tzinfo=timezone.utc)
            ),
            reverse=True,
        )
        selected = tuple(candidates[: self._max_items])
        for item in selected:
            self._remember(item.content_hash)
        return selected

    async def fetch_recent_news(
        self, now: datetime | None = None
    ) -> tuple[NewsItem, ...]:
        """Download RSS feed with strict timeout; return empty tuple on network errors."""
        try:
            resp = await self._client.get(
                self._rss_url,
                headers={"User-Agent": "ANT-Monitor/0.1 (+https://github.com)"},
                follow_redirects=True,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("RSS fetch failed: %s", exc)
            return ()

        return self.parse_feed(resp.text, now=now)
