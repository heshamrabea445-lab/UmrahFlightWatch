from __future__ import annotations

import asyncio
from typing import Any

from sqlalchemy import desc, select
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

from app.config import Settings
from app.db.models import ActiveDeal, Post, Scan
from app.services.app_settings import is_paused, set_setting
from app.services.provider_usage import current_usage
from app.utils.dates import month_key, ordered_categories


def is_authorized_admin(chat_id: int | None, settings: Settings) -> bool:
    return bool(chat_id is not None and settings.telegram_admin_chat_id == str(chat_id))


class TelegramAdminBot:
    def __init__(
        self,
        *,
        settings: Settings,
        session_factory: Any,
        scan_service: Any,
        report_service: Any,
    ) -> None:
        self.settings = settings
        self.session_factory = session_factory
        self.scan_service = scan_service
        self.report_service = report_service
        self.application: Application | None = None

    async def start(self) -> None:
        if not self.settings.telegram_bot_token:
            return
        self.application = Application.builder().token(self.settings.telegram_bot_token).build()
        for command, handler in {
            "status": self.status,
            "usage": self.usage,
            "pause": self.pause,
            "resume": self.resume,
            "scan_now": self.scan_now,
            "post_report": self.post_report,
            "last_deals": self.last_deals,
            "provider": self.provider,
        }.items():
            self.application.add_handler(CommandHandler(command, handler))
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()

    async def stop(self) -> None:
        if self.application is None:
            return
        await self.application.updater.stop()
        await self.application.stop()
        await self.application.shutdown()

    async def status(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_admin(update):
            return
        text = await asyncio.to_thread(self._status_text)
        await update.effective_message.reply_text(text)

    async def usage(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_admin(update):
            return
        text = await asyncio.to_thread(self._usage_text)
        await update.effective_message.reply_text(text)

    async def pause(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_admin(update):
            return
        with self.session_factory() as session:
            set_setting(session, "paused", True)
            session.commit()
        await update.effective_message.reply_text("Paused scheduled scans and channel posting.")

    async def resume(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_admin(update):
            return
        with self.session_factory() as session:
            set_setting(session, "paused", False)
            session.commit()
        await update.effective_message.reply_text("Resumed scheduled work.")

    async def scan_now(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_admin(update):
            return
        category = context.args[0] if context.args else "all"
        if category not in {*ordered_categories(), "all"}:
            await update.effective_message.reply_text(
                "Use /scan_now one_week|two_week|one_month|all"
            )
            return
        await update.effective_message.reply_text(f"Starting manual scan: {category}")
        if category == "all":
            await asyncio.to_thread(self.scan_service.scan_all_categories, respect_pause=False)
        else:
            await asyncio.to_thread(self.scan_service.scan_category, category, respect_pause=False)
        await update.effective_message.reply_text(f"Manual scan finished: {category}")

    async def post_report(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_admin(update):
            return
        await asyncio.to_thread(self.report_service.post_weekly_report, respect_pause=False)
        await update.effective_message.reply_text("Weekly report generated.")

    async def last_deals(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_admin(update):
            return
        text = await asyncio.to_thread(self._last_deals_text)
        await update.effective_message.reply_text(text)

    async def provider(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self._ensure_admin(update):
            return
        text = await asyncio.to_thread(self._provider_text)
        await update.effective_message.reply_text(text)

    async def _ensure_admin(self, update: Update) -> bool:
        chat_id = update.effective_chat.id if update.effective_chat else None
        if is_authorized_admin(chat_id, self.settings):
            return True
        if update.effective_message:
            await update.effective_message.reply_text("Unauthorized.")
        return False

    def _status_text(self) -> str:
        with self.session_factory() as session:
            paused = is_paused(session)
            last_report = session.execute(
                select(Post).where(Post.post_type == "weekly_report").order_by(desc(Post.posted_at))
            ).scalar()
            scans = session.execute(select(Scan).order_by(desc(Scan.started_at)).limit(5)).scalars()
            lines = [
                "Umrah Flight Watch status",
                f"dry_run: {self.settings.dry_run}",
                f"paused: {paused}",
                f"last_report: {last_report.posted_at if last_report else 'none'}",
                "recent_scans:",
            ]
            for scan in scans:
                lines.append(f"- {scan.category}: {scan.status} at {scan.started_at}")
            return "\n".join(lines)

    def _usage_text(self) -> str:
        with self.session_factory() as session:
            usage = current_usage(session, "fli")
            if usage is None:
                return f"fli usage for {month_key()}: 0 calls"
            return (
                f"fli usage for {usage.month_key}\n"
                f"requests: {usage.request_count}\n"
                f"successful: {usage.successful_count}\n"
                f"failed: {usage.failed_count}"
            )

    def _last_deals_text(self) -> str:
        with self.session_factory() as session:
            rows = session.execute(
                select(ActiveDeal)
                .where(ActiveDeal.active.is_(True))
                .order_by(
                    ActiveDeal.category,
                    ActiveDeal.deal_type,
                )
            ).scalars()
            lines = ["Current active deals"]
            for row in rows:
                metadata = row.metadata_json or {}
                lines.append(
                    f"{row.category}/{row.deal_type}: ${row.price_cad} "
                    f"{row.depart_date}->{row.return_date} score={row.deal_score} "
                    f"fare={metadata.get('fare_label', 'n/a')} "
                    f"flight={metadata.get('flight_quality_label', 'n/a')} "
                    f"sort={metadata.get('exact_sort_mode', 'n/a')} "
                    f"last_seen={row.last_seen_at}"
                )
            return "\n".join(lines)

    def _provider_text(self) -> str:
        with self.session_factory() as session:
            last_success = session.execute(
                select(Scan)
                .where(Scan.source == "fli", Scan.status == "success")
                .order_by(desc(Scan.started_at))
            ).scalar()
            last_error = session.execute(
                select(Scan)
                .where(Scan.source == "fli", Scan.status == "failed")
                .order_by(desc(Scan.started_at))
            ).scalar()
            usage = current_usage(session, "fli")
            return (
                "current provider = fli\n"
                f"last successful fli scan: {last_success.started_at if last_success else 'none'}\n"
                f"last fli error: {last_error.error_message if last_error else 'none'}\n"
                f"fli calls this month: {usage.request_count if usage else 0}"
            )
