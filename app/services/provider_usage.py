from datetime import datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as postgres_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
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
    if _record_provider_usage_with_upsert(
        session,
        source=source,
        month_key_value=key,
        request_count=request_count,
        successful_count=successful_count,
        failed_count=failed_count,
        updated_at=now,
    ):
        return

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


def _record_provider_usage_with_upsert(
    session: Session,
    *,
    source: str,
    month_key_value: str,
    request_count: int,
    successful_count: int,
    failed_count: int,
    updated_at: datetime,
) -> bool:
    bind = session.get_bind()
    dialect_name = bind.dialect.name if bind is not None else ""
    insert_factory = {
        "postgresql": postgres_insert,
        "sqlite": sqlite_insert,
    }.get(dialect_name)
    if insert_factory is None:
        return False

    table = ProviderUsage.__table__
    insert_statement = insert_factory(table).values(
        source=source,
        month_key=month_key_value,
        request_count=request_count,
        successful_count=successful_count,
        failed_count=failed_count,
        updated_at=updated_at,
    )
    session.execute(
        insert_statement.on_conflict_do_update(
            index_elements=[table.c.source, table.c.month_key],
            set_={
                "request_count": table.c.request_count + request_count,
                "successful_count": table.c.successful_count + successful_count,
                "failed_count": table.c.failed_count + failed_count,
                "updated_at": updated_at,
            },
        )
    )
    return True


def current_usage(session: Session, source: str) -> ProviderUsage | None:
    return session.execute(
        select(ProviderUsage).where(
            ProviderUsage.source == source,
            ProviderUsage.month_key == month_key(),
        )
    ).scalar_one_or_none()
