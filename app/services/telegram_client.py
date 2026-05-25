from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings

logger = logging.getLogger(__name__)


class TelegramClient:
    """Sync HTTP client for outbound channel posts.

    Inbound admin commands use python-telegram-bot in `app/admin/telegram_admin.py`;
    this client only does fire-and-forget POSTs from scheduler threads.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def post_weekly_report(self, text: str) -> int | None:
        return self._send_message(text)

    def post_strong_alert(self, text: str, button_text: str, button_url: str) -> int | None:
        reply_markup = (
            {"inline_keyboard": [[{"text": button_text, "url": button_url}]]}
            if button_text and button_url
            else None
        )
        return self._send_message(text, reply_markup=reply_markup)

    def _send_message(
        self,
        text: str,
        *,
        reply_markup: dict[str, Any] | None = None,
    ) -> int | None:
        if self.settings.dry_run:
            logger.info("DRY_RUN Telegram message:\n%s", text)
            if reply_markup:
                logger.info("DRY_RUN Telegram reply_markup: %s", reply_markup)
            return None
        if not self.settings.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required when DRY_RUN=false")
        if not self.settings.telegram_channel_id:
            raise RuntimeError("TELEGRAM_CHANNEL_ID is required when DRY_RUN=false")

        payload: dict[str, Any] = {
            "chat_id": self.settings.telegram_channel_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        url = f"https://api.telegram.org/bot{self.settings.telegram_bot_token}/sendMessage"
        response = httpx.post(url, json=payload, timeout=30.0)
        response.raise_for_status()
        return response.json().get("result", {}).get("message_id")
