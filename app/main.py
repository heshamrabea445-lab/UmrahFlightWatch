from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.admin.telegram_admin import TelegramAdminBot
from app.config import get_settings
from app.db.session import create_session_factory
from app.jobs.cleanup_jobs import CleanupJobService
from app.jobs.report_jobs import ReportJobService
from app.jobs.scan_jobs import FlightScanService
from app.providers.fli_provider import FliProvider
from app.scheduler import create_scheduler
from app.services.telegram_client import TelegramClient
from app.utils.logging import configure_logging


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging(settings.log_level)
    session_factory = create_session_factory(settings.database_url)
    provider = FliProvider(settings=settings)
    telegram_client = TelegramClient(settings=settings)
    scan_service = FlightScanService(
        session_factory=session_factory,
        provider=provider,
        telegram_client=telegram_client,
        dry_run=settings.dry_run,
        settings=settings,
    )
    report_service = ReportJobService(
        session_factory=session_factory,
        telegram_client=telegram_client,
        settings=settings,
    )
    cleanup_service = CleanupJobService(session_factory=session_factory, settings=settings)
    scheduler = create_scheduler(
        settings=settings,
        scan_service=scan_service,
        report_service=report_service,
        cleanup_service=cleanup_service,
    )
    admin_bot = TelegramAdminBot(
        settings=settings,
        session_factory=session_factory,
        scan_service=scan_service,
        report_service=report_service,
    )
    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.scan_service = scan_service
    app.state.report_service = report_service
    scheduler.start()
    await admin_bot.start()
    try:
        yield
    finally:
        await admin_bot.stop()
        scheduler.shutdown(wait=False)
        session_factory.kw["bind"].dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Umrah Flight Watch", lifespan=lifespan)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "provider": "fli"}

    @app.get("/")
    def root() -> dict[str, str]:
        return {"name": "Umrah Flight Watch"}

    return app


app = create_app()
