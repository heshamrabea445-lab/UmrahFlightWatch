from datetime import date

from app.providers.base import NormalizedFlightDeal
from app.services.deal_scoring import apply_deal_ratings
from app.services.deal_selection import (
    dedupe_deals,
    qualifies_for_strong_alert,
    select_active_deals,
)
from app.services.market_baseline import PriceBaseline


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
    sort_mode: str | None = None,
    airline: str | None = "Saudia",
    baseline_median: int | None = None,
    baseline_has_enough_history: bool | None = None,
) -> NormalizedFlightDeal:
    metadata: dict = {}
    if sort_mode:
        metadata["exact_sort_mode"] = sort_mode
    if baseline_median is not None:
        metadata["baseline_median_cad"] = baseline_median
    if baseline_has_enough_history is not None:
        metadata["baseline_has_enough_history"] = baseline_has_enough_history
    return NormalizedFlightDeal(
        category="one_week",
        origin="YYZ",
        destination="JED",
        depart_date=depart,
        return_date=ret,
        trip_length_days=(ret - depart).days,
        price_cad=price,
        airline=airline,
        stops=stops,
        total_travel_minutes=minutes,
        layover_summary=layover,
        google_flights_link="https://example.com",
        source="fli",
        exact_check_completed=exact,
        deal_score=score,
        metadata=metadata,
    )


def test_dedupe_keeps_best_version_of_same_date_pair_and_price() -> None:
    duplicate_plain = make_deal(score=7.0, exact=False)
    duplicate_exact = make_deal(score=8.5, exact=True)

    deduped = dedupe_deals([duplicate_plain, duplicate_exact])

    assert deduped == [duplicate_exact]


def test_active_deal_selection_returns_cheapest_and_fastest_within_guard() -> None:
    cheap_slow = make_deal(price=700, score=7.0, minutes=34 * 60)
    pricier_fast = make_deal(
        price=940,
        score=9.2,
        depart=date(2026, 9, 12),
        ret=date(2026, 9, 20),
        minutes=14 * 60,
    )

    selected = select_active_deals([cheap_slow, pricier_fast])

    assert selected["cheapest"] == cheap_slow
    assert selected["best_value"] == pricier_fast
    assert set(selected) == {"cheapest", "best_value"}


def test_active_deal_selection_uses_lowest_exact_price_across_search_modes() -> None:
    cheapest_mode = make_deal(
        price=950,
        score=8.0,
        exact=True,
        sort_mode="CHEAPEST",
    )
    top_flights_lower = make_deal(
        price=900,
        score=9.0,
        depart=date(2026, 9, 11),
        ret=date(2026, 9, 18),
        exact=True,
        sort_mode="TOP_FLIGHTS",
    )

    selected = select_active_deals([cheapest_mode, top_flights_lower])

    assert selected["cheapest"] == top_flights_lower


def test_active_deal_selection_prefers_top_flights_for_best_value_with_price_guard() -> None:
    cheapest = make_deal(
        price=850,
        score=8.0,
        exact=True,
        sort_mode="CHEAPEST",
        minutes=30 * 60,
    )
    top_flight = make_deal(
        price=980,
        score=9.2,
        depart=date(2026, 9, 11),
        ret=date(2026, 9, 18),
        exact=True,
        sort_mode="TOP_FLIGHTS",
        minutes=14 * 60,
    )

    selected = select_active_deals([cheapest, top_flight])

    assert selected["cheapest"] == cheapest
    assert selected["best_value"] == top_flight


def test_active_deal_selection_considers_all_exact_modes_for_best_value() -> None:
    cheapest = make_deal(
        price=900,
        score=8.0,
        exact=True,
        sort_mode="CHEAPEST",
        minutes=24 * 60,
    )
    slower_top_flight = make_deal(
        price=920,
        score=8.4,
        exact=True,
        sort_mode="TOP_FLIGHTS",
        minutes=22 * 60,
    )
    faster_cheapest_mode = make_deal(
        price=1020,
        score=9.2,
        exact=True,
        sort_mode="CHEAPEST",
        minutes=14 * 60,
    )

    selected = select_active_deals([cheapest, slower_top_flight, faster_cheapest_mode])

    assert selected["cheapest"] == cheapest
    assert selected["best_value"] == faster_cheapest_mode


def test_active_deal_selection_uses_price_guard_as_the_premium_limit() -> None:
    cheapest = make_deal(
        price=900,
        exact=True,
        sort_mode="CHEAPEST",
        minutes=20 * 60,
    )
    slightly_faster = make_deal(
        price=1200,
        depart=date(2026, 9, 11),
        ret=date(2026, 9, 18),
        exact=True,
        sort_mode="TOP_FLIGHTS",
        minutes=19 * 60,
    )

    selected = select_active_deals([cheapest, slightly_faster])

    assert selected["cheapest"] == cheapest
    assert selected["best_value"] == slightly_faster


def test_active_deal_selection_prefers_much_faster_two_week_trip_after_scoring() -> None:
    baseline = PriceBaseline(
        baseline_days=90,
        sample_size=20,
        average=1500,
        median=1360,
    )
    slow_excellent_fare = make_deal(
        ret=date(2026, 9, 24),
        price=1290,
        exact=True,
        sort_mode="CHEAPEST",
        airline="Etihad Airways",
        stops=2,
        minutes=(31 * 60) + 15,
    )
    faster_reasonable_premium = make_deal(
        ret=date(2026, 9, 24),
        price=1440,
        exact=True,
        sort_mode="TOP_FLIGHTS",
        airline="Etihad Airways",
        stops=1,
        minutes=(19 * 60) + 30,
        layover="3h 15m in AUH",
    )
    for deal in (slow_excellent_fare, faster_reasonable_premium):
        apply_deal_ratings(
            deal,
            fare_baseline=baseline,
            recent_category_average=baseline.average,
            min_history_rows=20,
        )

    selected = select_active_deals([slow_excellent_fare, faster_reasonable_premium])

    assert selected["cheapest"] == slow_excellent_fare
    assert selected["best_value"] == faster_reasonable_premium


def test_active_deal_selection_blocks_overpriced_top_flights_best_value() -> None:
    cheapest = make_deal(
        price=850,
        score=8.5,
        exact=True,
        sort_mode="CHEAPEST",
    )
    overpriced = make_deal(
        price=1400,
        score=9.8,
        depart=date(2026, 9, 11),
        ret=date(2026, 9, 18),
        exact=True,
        sort_mode="TOP_FLIGHTS",
    )

    selected = select_active_deals([cheapest, overpriced])

    assert selected["best_value"] == cheapest


def test_strong_alert_uses_70_percent_of_90_day_median() -> None:
    alerting_deal = make_deal(
        price=900,
        exact=True,
        score=6.0,
        baseline_median=1400,
        baseline_has_enough_history=True,
    )
    non_alerting_deal = make_deal(
        price=1000,
        exact=True,
        score=9.5,
        baseline_median=1400,
        baseline_has_enough_history=True,
    )

    assert qualifies_for_strong_alert(alerting_deal, 1400, None)
    assert not qualifies_for_strong_alert(non_alerting_deal, 1400, None)


def test_strong_alert_uses_unified_cheapest_snapshot_median_threshold() -> None:
    alerting_deal = make_deal(
        price=900,
        exact=True,
        baseline_median=1290,
        baseline_has_enough_history=True,
    )
    non_alerting_deal = make_deal(
        price=950,
        exact=True,
        baseline_median=1290,
        baseline_has_enough_history=True,
    )

    assert qualifies_for_strong_alert(alerting_deal, 1290, None)
    assert not qualifies_for_strong_alert(non_alerting_deal, 1290, None)


def test_strong_alert_uses_absolute_fallback_when_baseline_history_is_insufficient() -> None:
    alerting_deal = make_deal(
        price=749,
        exact=True,
        score=4.0,
        baseline_median=1400,
        baseline_has_enough_history=False,
    )
    non_alerting_deal = make_deal(
        price=800,
        exact=True,
        score=9.5,
        baseline_median=1400,
        baseline_has_enough_history=False,
    )

    assert qualifies_for_strong_alert(alerting_deal, 1400, None)
    assert not qualifies_for_strong_alert(non_alerting_deal, 1400, None)


def test_strong_alert_suspicious_price_guard_requires_confirmation_detail() -> None:
    suspicious_without_detail = make_deal(
        price=230,
        exact=True,
        score=9.9,
        airline=None,
        stops=None,
        minutes=None,
        baseline_median=1400,
        baseline_has_enough_history=True,
    )
    suspicious_with_detail = make_deal(
        price=230,
        exact=True,
        score=1.0,
        airline="Saudia",
        stops=None,
        minutes=None,
        baseline_median=1400,
        baseline_has_enough_history=True,
    )

    assert not qualifies_for_strong_alert(suspicious_without_detail, 1200, None)
    assert qualifies_for_strong_alert(suspicious_with_detail, 1200, None)


def test_strong_alert_repost_rule_still_requires_100_cad_drop() -> None:
    deal = make_deal(
        price=900,
        exact=True,
        baseline_median=1400,
        baseline_has_enough_history=True,
    )

    assert not qualifies_for_strong_alert(deal, 1400, 950)
    assert qualifies_for_strong_alert(deal, 1400, 1000)
