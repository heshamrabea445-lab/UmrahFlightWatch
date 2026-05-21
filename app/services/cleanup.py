from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db.models import PriceHistory, RawApiResult
from app.utils.dates import utc_now


def cleanup_old_data(
    session: Session,
    *,
    price_history_days: int,
    raw_result_retention_days: int,
) -> dict[str, int]:
    now = utc_now()
    raw_delete = session.execute(delete(RawApiResult).where(RawApiResult.expires_at <= now))
    archive_before = now - timedelta(days=price_history_days)
    rows = session.execute(
        select(PriceHistory).where(
            PriceHistory.checked_at < archive_before,
            PriceHistory.archived_at.is_(None),
        )
    ).scalars()
    archived = 0
    for row in rows:
        row.archived_at = now
        archived += 1

    raw_floor = now - timedelta(days=raw_result_retention_days * 2)
    session.execute(delete(RawApiResult).where(RawApiResult.created_at < raw_floor))
    return {"raw_deleted": raw_delete.rowcount or 0, "history_archived": archived}
