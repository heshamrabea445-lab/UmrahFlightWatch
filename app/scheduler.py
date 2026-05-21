from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.config import Settings
from app.jobs.cleanup_jobs import CleanupJobService
from app.jobs.report_jobs import ReportJobService
from app.jobs.scan_jobs import FlightScanService


def create_scheduler(
    *,
    settings: Settings,
    scan_service: FlightScanService,
    report_service: ReportJobService,
    cleanup_service: CleanupJobService,
) -> BackgroundScheduler:
    timezone = ZoneInfo(settings.app_timezone)
    scheduler = BackgroundScheduler(timezone=timezone)
    scheduler.add_job(
        scan_service.scan_category,
        CronTrigger(day_of_week="mon-sun", hour=9, minute=0, timezone=timezone),
        args=["one_week"],
        id="scan_one_week",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        scan_service.scan_category,
        CronTrigger(day_of_week="mon-sun", hour=14, minute=0, timezone=timezone),
        args=["two_week"],
        id="scan_two_week",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        scan_service.scan_category,
        CronTrigger(day_of_week="mon-sun", hour=20, minute=0, timezone=timezone),
        args=["one_month"],
        id="scan_one_month",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        report_service.post_weekly_report,
        CronTrigger(day_of_week="fri", hour=13, minute=30, timezone=timezone),
        id="weekly_report",
        replace_existing=True,
        max_instances=1,
    )
    scheduler.add_job(
        cleanup_service.run_cleanup,
        CronTrigger(day_of_week="mon-sun", hour=3, minute=15, timezone=timezone),
        id="cleanup",
        replace_existing=True,
        max_instances=1,
    )
    return scheduler
