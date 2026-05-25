from datetime import timedelta

from app.config import Settings
from app.scheduler import create_scheduler


class FakeScanService:
    def scan_all_categories(self):
        raise NotImplementedError


class FakeReportService:
    def post_weekly_report(self):
        raise NotImplementedError


class FakeCleanupService:
    def run_cleanup(self):
        raise NotImplementedError


def test_scheduler_uses_hourly_discovery_without_flash_checks() -> None:
    scheduler = create_scheduler(
        settings=Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            discovery_interval_hours=1,
        ),
        scan_service=FakeScanService(),
        report_service=FakeReportService(),
        cleanup_service=FakeCleanupService(),
    )

    jobs = {job.id: job for job in scheduler.get_jobs()}

    assert "scan_one_week" not in jobs
    assert "scan_two_week" not in jobs
    assert "scan_one_month" not in jobs
    assert jobs["discovery_scan"].trigger.interval == timedelta(hours=1)
    assert "flash_check_watchlist" not in jobs
    assert "weekly_report" in jobs
    assert "cleanup" in jobs
