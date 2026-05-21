from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AppSetting
from app.utils.dates import utc_now


def get_setting(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(AppSetting, key)
    if row is None:
        return default
    return row.value_json.get("value", default)


def set_setting(session: Session, key: str, value: Any) -> None:
    row = session.get(AppSetting, key)
    now = utc_now()
    if row is None:
        session.add(AppSetting(key=key, value_json={"value": value}, updated_at=now))
        return
    row.value_json = {"value": value}
    row.updated_at = now


def is_paused(session: Session) -> bool:
    return bool(get_setting(session, "paused", False))
