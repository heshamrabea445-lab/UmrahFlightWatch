import calendar
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

CATEGORY_LABELS: dict[str, str] = {
    "one_week": "1-Week Trips",
    "two_week": "2-Week Trips",
    "one_month": "1-Month Trips",
}

_CATEGORY_DURATIONS: dict[str, list[int]] = {
    "one_week": list(range(5, 11)),
    "two_week": list(range(12, 18)),
    "one_month": list(range(25, 36)),
}


def category_durations(category: str) -> list[int]:
    try:
        return _CATEGORY_DURATIONS[category].copy()
    except KeyError as exc:
        raise ValueError(f"Unknown trip category: {category}") from exc


def ordered_categories() -> list[str]:
    return ["one_week", "two_week", "one_month"]


def add_calendar_months(value: date, months: int) -> date:
    month_index = value.month - 1 + months
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def next_three_month_window(today: date) -> tuple[date, date]:
    return today, add_calendar_months(today, 3)


def local_today(timezone_name: str) -> date:
    return datetime.now(ZoneInfo(timezone_name)).date()


def utc_now() -> datetime:
    return datetime.now(UTC)


def month_key(value: datetime | None = None) -> str:
    current = value or utc_now()
    return current.strftime("%Y-%m")
