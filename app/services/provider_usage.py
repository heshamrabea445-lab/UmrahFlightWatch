from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ProviderUsage
from app.utils.dates import month_key, utc_now


def record_provider_usage(
    session: Session,
    *,
    source: str,
    request_count: int,
    successful_count: int,
    failed_count: int,
) -> None:
    key = month_key()
    now = utc_now()
    usage = session.execute(
        select(ProviderUsage).where(
            ProviderUsage.source == source,
            ProviderUsage.month_key == key,
        )
    ).scalar_one_or_none()
    if usage is None:
        session.add(
            ProviderUsage(
                source=source,
                month_key=key,
                request_count=request_count,
                successful_count=successful_count,
                failed_count=failed_count,
                updated_at=now,
            )
        )
        return
    usage.request_count += request_count
    usage.successful_count += successful_count
    usage.failed_count += failed_count
    usage.updated_at = now


def current_usage(session: Session, source: str) -> ProviderUsage | None:
    return session.execute(
        select(ProviderUsage).where(
            ProviderUsage.source == source,
            ProviderUsage.month_key == month_key(),
        )
    ).scalar_one_or_none()
