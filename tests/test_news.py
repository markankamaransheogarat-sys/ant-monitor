"""Tests for RSS news parsing, recency filtering, and SHA-256 deduplication."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import httpx
import pytest

from ant_monitor.clients.news import NewsFeedClient


def _build_rss(items: list[tuple[str, str, datetime]]) -> str:
    entries = []
    for title, link, pub in items:
        entries.append(
            f"<item><title>{title}</title><link>{link}</link>"
            f"<pubDate>{format_datetime(pub)}</pubDate></item>"
        )
    return f"<?xml version='1.0' encoding='UTF-8'?><rss version='2.0'><channel>{''.join(entries)}</channel></rss>"


def test_news_filters_old_items_and_deduplicates() -> None:
    now = datetime(2026, 11, 19, 16, 50, tzinfo=timezone.utc)
    rss = _build_rss(
        [
            ("Old news", "https://example.com/old", now - timedelta(minutes=45)),
            ("Fresh 1", "https://example.com/a#frag1", now - timedelta(minutes=5)),
            (
                "Fresh 1 duplicate",
                "https://example.com/a#frag2",
                now - timedelta(minutes=3),
            ),
            ("Fresh 2", "https://example.com/b", now - timedelta(minutes=2)),
            ("Fresh 3", "https://example.com/c", now - timedelta(minutes=1)),
        ]
    )

    client = NewsFeedClient(
        http_client=httpx.AsyncClient(),
        rss_url="https://news.google.com/rss",
        window_minutes=30,
        max_items=2,
    )

    first_batch = client.parse_feed(rss, now=now)
    assert [i.title for i in first_batch] == ["Fresh 3", "Fresh 2"]

    # Second pass on same feed yields only the remaining unseen item ("Fresh 1")
    second_batch = client.parse_feed(rss, now=now + timedelta(minutes=1))
    assert [i.title for i in second_batch] == ["Fresh 1"]

    # Third pass yields empty tuple
    assert client.parse_feed(rss, now=now + timedelta(minutes=2)) == ()


@pytest.mark.asyncio
async def test_news_fetch_returns_empty_on_http_error() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(504))
    ) as http_client:
        client = NewsFeedClient(http_client, rss_url="https://news.google.com/rss")
        assert await client.fetch_recent_news() == ()
