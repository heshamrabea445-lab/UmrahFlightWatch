from datetime import date

import pytest

from app.utils.dates import category_durations, next_three_month_window


def test_category_durations_are_fixed_ranges() -> None:
    assert category_durations("one_week") == [5, 6, 7, 8, 9, 10]
    assert category_durations("two_week") == [12, 13, 14, 15, 16, 17]
    assert category_durations("one_month") == [25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35]


def test_unknown_category_is_rejected() -> None:
    with pytest.raises(ValueError, match="Unknown trip category"):
        category_durations("weekend")


def test_next_three_month_window_uses_calendar_months() -> None:
    start, end = next_three_month_window(date(2026, 5, 20))

    assert start == date(2026, 5, 20)
    assert end == date(2026, 8, 20)


def test_next_three_month_window_clamps_month_end() -> None:
    start, end = next_three_month_window(date(2026, 11, 30))

    assert start == date(2026, 11, 30)
    assert end == date(2027, 2, 28)
