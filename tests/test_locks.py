from __future__ import annotations

from typing import Any

from sqlalchemy.dialects import postgresql

from app.db.locks import release_advisory_lock, try_advisory_lock


class _Result:
    def __init__(self, value: bool) -> None:
        self.value = value

    def scalar(self) -> bool:
        return self.value


class _Dialect:
    def __init__(self, name: str) -> None:
        self.name = name


class _Bind:
    def __init__(self, dialect_name: str) -> None:
        self.dialect = _Dialect(dialect_name)


class _Session:
    def __init__(self, dialect_name: str = "postgresql", result: bool = True) -> None:
        self.bind = _Bind(dialect_name)
        self.result = result
        self.executed: list[Any] = []

    def execute(self, statement: Any) -> _Result:
        self.executed.append(statement)
        return _Result(self.result)


def test_postgres_lock_uses_transaction_scoped_advisory_lock() -> None:
    session = _Session()

    assert try_advisory_lock(session, "search_pipeline") is True

    compiled = str(session.executed[0].compile(dialect=postgresql.dialect()))
    assert "pg_try_advisory_xact_lock" in compiled
    assert "pg_try_advisory_lock" not in compiled


def test_non_postgres_lock_is_noop_success() -> None:
    session = _Session(dialect_name="sqlite")

    assert try_advisory_lock(session, "search_pipeline") is True

    assert session.executed == []


def test_release_advisory_lock_is_noop_for_transaction_locks() -> None:
    session = _Session()

    release_advisory_lock(session, "search_pipeline")

    assert session.executed == []
