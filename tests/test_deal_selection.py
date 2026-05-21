from datetime import date

from app.providers.base import NormalizedFlightDeal
from app.services.deal_selection import (
    dedupe_deals,
    is_extreme_bad_flight,
    select_active_deals,
)


def make_deal(
    *,
    depart: date = date(2026, 9, 10),
    ret: date = date(2026, 9, 17),
    price: int = 900,
    score: float = 8.0,
    stops: int | None = 1,
    minutes: int | None = 18 * 60,
    layover: str | None = None,
    exact: bool = False,
) -> NormalizedFlightDeal:
    return NormalizedFlightDeal(
        category="one_week",
        origin="YYZ",
        destination="JED",
        depart_date=depart,
        return_date=ret,
        trip_length_days=(ret - depart).days,
        price_cad=price,
        airline="Saudia",
        stops=stops,
        total_travel_minutes=minutes,
        layover_summary=layover,
        google_flights_link="https://example.com",
        source="fli",
        exact_check_completed=exact,
        deal_score=score,
    )


def test_dedupe_keeps_best_version_of_same_date_pair_and_price() -> None:
    duplicate_plain = make_deal(score=7.0, exact=False)
    duplicate_exact = make_deal(score=8.5, exact=True)

    deduped = dedupe_deals([duplicate_plain, duplicate_exact])

    assert deduped == [duplicate_exact]


def test_extreme_bad_flight_filter_uses_available_fields_only() -> None:
    assert is_extreme_bad_flight(make_deal(minutes=33 * 60))
    assert is_extreme_bad_flight(make_deal(stops=3))
    assert is_extreme_bad_flight(make_deal(layover="Airport change in New York"))
    assert not is_extreme_bad_flight(make_deal(stops=None, minutes=None, layover=None))


def test_active_deal_selection_uses_cheapest_best_value_and_backup() -> None:
    cheap_bad = make_deal(price=700, score=7.0, minutes=34 * 60)
    cheapest = make_deal(price=820, score=8.1, depart=date(2026, 9, 11), ret=date(2026, 9, 18))
    best = make_deal(price=940, score=9.2, depart=date(2026, 9, 12), ret=date(2026, 9, 20))
    backup = make_deal(price=910, score=8.8, depart=date(2026, 9, 13), ret=date(2026, 9, 21))

    selected = select_active_deals([cheap_bad, cheapest, best, backup])

    assert selected["cheapest"] == cheapest
    assert selected["best_value"] == best
    assert selected["backup"] == backup
