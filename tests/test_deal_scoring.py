from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from types import SimpleNamespace

from app.providers.base import NormalizedFlightDeal
from app.services.deal_scoring import (
    apply_deal_ratings,
    calculate_flight_quality_score,
    is_suspicious_price,
    score_label,
)
from app.services.market_baseline import (
    PriceBaseline,
    build_cheapest_snapshot_baseline,
    build_price_baseline,
    calculate_market_rating,
)


def make_deal(
    price: int,
    *,
    score: float | None = None,
    stops: int | None = 1,
    minutes: int | None = 19 * 60,
    layover: str | None = None,
) -> NormalizedFlightDeal:
    return NormalizedFlightDeal(
        category="two_week",
        origin="YYZ",
        destination="JED",
        depart_date=date(2026, 9, 10),
        return_date=date(2026, 9, 24),
        trip_length_days=14,
        price_cad=price,
        stops=stops,
        total_travel_minutes=minutes,
        layover_summary=layover,
        source="fli",
        exact_check_completed=True,
        deal_score=score,
    )


def rated_deal_score(
    deal: NormalizedFlightDeal,
    *,
    recent_category_average: float | None,
) -> float:
    apply_deal_ratings(
        deal,
        fare_baseline=None,
        recent_category_average=recent_category_average,
        min_history_rows=20,
    )
    assert deal.deal_score is not None
    return deal.deal_score


def test_suspicious_price_detection_uses_category_average_ratio_only() -> None:
    assert not is_suspicious_price(make_deal(499), recent_category_average=1200)
    assert not is_suspicious_price(make_deal(475), recent_category_average=None)
    assert is_suspicious_price(make_deal(230), recent_category_average=1200)
    assert not is_suspicious_price(make_deal(250), recent_category_average=1200)


def test_suspicious_price_detection_accepts_decimal_average() -> None:
    assert is_suspicious_price(make_deal(230), recent_category_average=Decimal("1200"))


def test_deal_score_rewards_prices_below_recent_average() -> None:
    cheap = rated_deal_score(make_deal(850), recent_category_average=1200)
    expensive = rated_deal_score(make_deal(1450), recent_category_average=1200)

    assert cheap > expensive
    assert 0 <= expensive <= 10
    assert 0 <= cheap <= 10


def test_deal_score_prefers_much_shorter_trip_when_price_is_reasonable() -> None:
    cheap_slow = rated_deal_score(
        make_deal(800, minutes=24 * 60),
        recent_category_average=1200,
    )
    faster_reasonable = rated_deal_score(
        make_deal(1000, minutes=14 * 60),
        recent_category_average=1200,
    )

    assert faster_reasonable > cheap_slow


def test_score_label_thresholds_match_product_language() -> None:
    assert score_label(9.0) == "Excellent"
    assert score_label(8.5) == "Good"
    assert score_label(7.0) == "Normal"
    assert score_label(5.5) == "High"
    assert score_label(4.9) == "Very High"


def test_price_baseline_calculates_percentiles_without_outlier_dominating() -> None:
    baseline = build_price_baseline(
        [900, 950, 1000, 1050, 1100, 1150, 1200, 1250, 1300, 3000],
        baseline_days=90,
    )

    assert baseline.average == 1290
    assert baseline.median == 1125
    assert baseline.p10 == 945
    assert baseline.p25 == 1012.5
    assert baseline.p75 == 1237.5
    assert baseline.p90 == 1470


def test_cheapest_snapshot_baseline_collapses_multiple_exact_rows_per_scan() -> None:
    checked_at = datetime(2026, 5, 24, 12, 0, tzinfo=UTC)
    rows = [
        SimpleNamespace(category="one_week", checked_at=checked_at, price_cad=1500),
        SimpleNamespace(category="one_week", checked_at=checked_at, price_cad=1400),
        SimpleNamespace(
            category="one_week",
            checked_at=checked_at + timedelta(hours=1),
            price_cad=1300,
        ),
        SimpleNamespace(category="two_week", checked_at=checked_at, price_cad=900),
    ]

    baseline = build_cheapest_snapshot_baseline(
        rows,
        category="one_week",
        baseline_days=90,
    )

    assert baseline.sample_size == 2
    assert baseline.average == 1350
    assert baseline.median == 1350


def test_apply_deal_ratings_uses_90_day_baseline_metadata() -> None:
    baseline = build_price_baseline(
        [900, 950, 1000, 1050, 1100, 1150, 1200, 1250, 1300, 1350] * 2,
        baseline_days=90,
    )
    deal = make_deal(900, stops=0, minutes=14 * 60)

    apply_deal_ratings(
        deal,
        fare_baseline=baseline,
        recent_category_average=baseline.average,
        min_history_rows=20,
    )

    assert deal.metadata["fare_label"] == "Excellent"
    assert deal.metadata["flight_quality_label"] == "Excellent"
    assert deal.metadata["baseline_sample_size"] == 20
    assert deal.deal_score and deal.deal_score >= 9


def test_fare_rating_uses_median_ratio_bands_not_raw_percentiles() -> None:
    one_week_baseline = PriceBaseline(
        baseline_days=90,
        sample_size=20,
        average=1435,
        median=1440,
        p10=1412,
        p25=1412,
        p75=1440,
        p90=1490,
    )
    one_week_deal = make_deal(1412)

    apply_deal_ratings(
        one_week_deal,
        fare_baseline=one_week_baseline,
        recent_category_average=one_week_baseline.average,
        min_history_rows=20,
    )

    assert one_week_deal.metadata["fare_label"] == "Normal"


def test_fare_rating_treats_small_premium_over_median_as_normal() -> None:
    two_week_baseline = PriceBaseline(
        baseline_days=90,
        sample_size=20,
        average=1311,
        median=1290,
        p10=1290,
        p25=1290,
        p75=1290,
        p90=1362,
    )
    normal_deal = make_deal(1362)
    very_high_deal = make_deal(1590)

    for deal in (normal_deal, very_high_deal):
        apply_deal_ratings(
            deal,
            fare_baseline=two_week_baseline,
            recent_category_average=two_week_baseline.average,
            min_history_rows=20,
        )

    assert normal_deal.metadata["fare_label"] == "Normal"
    assert very_high_deal.metadata["fare_label"] == "Very High"


def test_apply_deal_ratings_marks_static_fallback_when_history_is_small() -> None:
    baseline = build_price_baseline([900, 950], baseline_days=90)
    deal = make_deal(900)

    apply_deal_ratings(
        deal,
        fare_baseline=baseline,
        recent_category_average=1200,
        min_history_rows=20,
    )

    assert deal.metadata["fare_uses_static_fallback"]
    assert not deal.metadata["baseline_has_enough_history"]


def test_flight_quality_scores_bad_layovers_lower() -> None:
    good = calculate_flight_quality_score(make_deal(950, stops=0, minutes=14 * 60))
    bad = calculate_flight_quality_score(
        make_deal(950, stops=2, minutes=34 * 60, layover="airport change")
    )

    assert good > bad
    assert bad < 5


def test_flight_quality_prefers_shorter_trip_over_fewer_stops() -> None:
    shorter_with_more_stops = calculate_flight_quality_score(
        make_deal(950, stops=2, minutes=15 * 60)
    )
    longer_nonstop = calculate_flight_quality_score(make_deal(950, stops=0, minutes=17 * 60))

    assert shorter_with_more_stops > longer_nonstop


def test_flight_quality_does_not_penalize_stop_count_when_duration_matches() -> None:
    nonstop = calculate_flight_quality_score(make_deal(950, stops=0, minutes=17 * 60))
    two_stop = calculate_flight_quality_score(make_deal(950, stops=2, minutes=17 * 60))

    assert nonstop == two_stop


def test_flight_quality_uses_neutral_score_when_quality_fields_missing() -> None:
    assert calculate_flight_quality_score(make_deal(950, stops=None, minutes=None)) == 7.0


def test_market_rating_uses_historical_snapshots_not_deal_scores() -> None:
    rating = calculate_market_rating(
        {"two_week": 930},
        {"two_week": [900, 950, 1000, 1050, 1100] * 4},
        baseline_days=90,
        min_history_rows=20,
    )

    assert rating.label == "Good buying window"
    assert rating.score == 8.5


def test_market_rating_uses_same_median_ratio_bands_as_fare_rating() -> None:
    rating = calculate_market_rating(
        {"two_week": 1060},
        {"two_week": [900, 950, 1000, 1050, 1100] * 4},
        baseline_days=90,
        min_history_rows=20,
    )

    assert rating.label == "Normal market"
    assert rating.score == 7.0


def test_market_rating_requires_enough_history() -> None:
    rating = calculate_market_rating(
        {"two_week": 930},
        {"two_week": [900, 950]},
        baseline_days=90,
        min_history_rows=20,
    )

    assert rating.label == "Not enough 90-day exact-search history"
    assert rating.score is None
