from datetime import date

from app.providers.base import NormalizedFlightDeal
from app.services.deal_scoring import (
    calculate_deal_score,
    calculate_market_rating,
    is_suspicious_price,
    score_label,
)


def make_deal(price: int, *, score: float | None = None) -> NormalizedFlightDeal:
    return NormalizedFlightDeal(
        category="two_week",
        origin="YYZ",
        destination="JED",
        depart_date=date(2026, 9, 10),
        return_date=date(2026, 9, 24),
        trip_length_days=14,
        price_cad=price,
        stops=1,
        total_travel_minutes=19 * 60,
        source="fli",
        deal_score=score,
    )


def test_suspicious_price_detection_uses_floor_and_average_drop() -> None:
    assert is_suspicious_price(make_deal(499), recent_category_average=1200)
    assert is_suspicious_price(make_deal(475), recent_category_average=None)
    assert is_suspicious_price(make_deal(700), recent_category_average=1800)
    assert not is_suspicious_price(make_deal(850), recent_category_average=1200)


def test_deal_score_rewards_prices_below_recent_average() -> None:
    cheap = calculate_deal_score(make_deal(850), recent_category_average=1200)
    expensive = calculate_deal_score(make_deal(1450), recent_category_average=1200)

    assert cheap > expensive
    assert 0 <= expensive <= 10
    assert 0 <= cheap <= 10


def test_score_label_thresholds_match_product_language() -> None:
    assert score_label(9.0) == "Excellent"
    assert score_label(8.5) == "Good"
    assert score_label(7.0) == "Normal"
    assert score_label(5.5) == "High"
    assert score_label(4.9) == "Very High"


def test_market_rating_uses_available_deals() -> None:
    label, score = calculate_market_rating([make_deal(850, score=9.0), make_deal(1100, score=8.0)])

    assert label == "Good"
    assert score == 8.5
