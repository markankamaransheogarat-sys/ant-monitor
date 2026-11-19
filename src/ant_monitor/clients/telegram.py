"""Lightweight async Telegram Bot API client."""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)


class TelegramClient:
    """Dispatches formatted HTML messages to Telegram via Bot API `sendMessage`."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        bot_token: str,
        chat_id: str,
        base_url: str = "https://api.telegram.org",
    ) -> None:
        self._client = http_client
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._base_url = base_url.rstrip("/")

    async def send_message(self, text: str) -> bool:
        """Send an HTML message; returns True on success, False on failure without raising."""
        url = f"{self._base_url}/bot{self._bot_token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        try:
            resp = await self._client.post(url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if not data.get("ok", False):
                logger.error("Telegram API returned error payload: %s", data)
                return False
            return True
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            logger.error("Telegram sendMessage failed: %s", exc)
            return False
