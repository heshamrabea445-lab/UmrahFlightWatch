import zlib

from sqlalchemy import func, select
from sqlalchemy.orm import Session


def advisory_lock_key(name: str) -> int:
    return zlib.crc32(name.encode("utf-8"))


def try_advisory_lock(session: Session, name: str) -> bool:
    if session.bind and session.bind.dialect.name != "postgresql":
        return True
    result = session.execute(
        select(func.pg_try_advisory_xact_lock(advisory_lock_key(name)))
    ).scalar()
    return bool(result)


def release_advisory_lock(session: Session, name: str) -> None:
    # Transaction-level advisory locks are released automatically on commit,
    # rollback, or session close. Keep this function for existing call sites.
    return
