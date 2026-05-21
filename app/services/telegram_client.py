from __future__ import annotations

import asyncio
import logging

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

from app.config import Settings

logger = logging.getLogger(__name__)


class TelegramClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._bot: Bot | None = None

    @property
    def bot(self) -> Bot:
        if not self.settings.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required when DRY_RUN=false")
        if self._bot is None:
            self._bot = Bot(self.settings.telegram_bot_token)
        return self._bot

    async def post_channel_message(
        self,
        text: str,
        *,
        button_text: str | None = None,
        button_url: str | None = None,
    ) -> int | None:
        if self.settings.dry_run:
            logger.info("DRY_RUN Telegram channel message:\n%s", text)
            if button_text and button_url:
                logger.info("DRY_RUN Telegram button: %s -> %s", button_text, button_url)
            return None
        if not self.settings.telegram_channel_id:
            raise RuntimeError("TELEGRAM_CHANNEL_ID is required when DRY_RUN=false")
        reply_markup = None
        if button_text and button_url:
            reply_markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton(text=button_text, url=button_url)]]
            )
        message = await self.bot.send_message(
            chat_id=self.settings.telegram_channel_id,
            text=text,
            parse_mode="HTML",
            disable_web_page_preview=False,
            reply_markup=reply_markup,
        )
        return message.message_id

    async def post_weekly_report(self, text: str) -> int | None:
        return await self.post_channel_message(text)

    async def post_strong_alert(
        self,
        text: str,
        *,
        button_text: str,
        button_url: str,
    ) -> int | None:
        return await self.post_channel_message(
            text,
            button_text=button_text,
            button_url=button_url,
        )

    def post_weekly_report_sync(self, text: str) -> int | None:
        return _run_sync(self.post_weekly_report(text))

    def post_strong_alert_sync(
        self,
        text: str,
        button_text: str,
        button_url: str,
    ) -> int | None:
        return _run_sync(
            self.post_strong_alert(text, button_text=button_text, button_url=button_url)
        )


def _run_sync(coro: object) -> int | None:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)  # type: ignore[arg-type]
    result: list[int | None] = []

    def runner() -> None:
        result.append(asyncio.run(coro))  # type: ignore[arg-type]

    import threading

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    return result[0] if result else None
