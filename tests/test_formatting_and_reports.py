from datetime import UTC, date, datetime, timedelta

from app.providers.base import NormalizedFlightDeal
from app.services.report_builder import build_strong_alert, build_weekly_report
from app.utils.formatting import escape_telegram_html


def make_deal(
    *,
    deal_type: str = "cheapest",
    price: int = 890,
    score: float = 8.3,
    minutes: int | None = 26 * 60,
    last_seen_at: datetime | None = None,
) -> NormalizedFlightDeal:
    metadata = {
        "deal_type": deal_type,
        "fare_label": "Good",
        "flight_quality_label": "Normal",
    }
    return NormalizedFlightDeal(
        category="one_week",
        origin="YYZ",
        destination="JED",
        depart_date=date(2026, 9, 10),
        return_date=date(2026, 9, 17),
        trip_length_days=7,
        price_cad=price,
        airline="Saudia & Partners",
        stops=2,
        total_travel_minutes=minutes,
        google_flights_link="https://example.com/search?a=1&b=2",
        source="fli",
        exact_check_completed=True,
        deal_score=score,
        last_seen_at=last_seen_at,
        metadata=metadata,
    )


def test_telegram_html_escaping() -> None:
    assert escape_telegram_html("<Saudia & Co>") == "&lt;Saudia &amp; Co&gt;"


def test_weekly_report_hides_unknown_fields_and_merges_same_deal() -> None:
    deal = make_deal()

    report = build_weekly_report(
        {
            "one_week": {"cheapest": deal, "best_value": deal},
            "two_week": {},
            "one_month": {},
        },
        market_label="Good",
        market_score=7.8,
        feedback_form_url="https://forms.example.com",
        generated_at=datetime(2026, 5, 25, 13, 30, tzinfo=UTC),
    )

    assert "\U0001f54b Weekly YYZ &#8594; JED Flight Watch" in report
    assert "May 25, 2026" in report
    assert "Cheapest + Best Overall:" in report
    assert "\U0001f4b8\u23f1\ufe0f Cheapest + Best Overall:" in report
    assert "unknown" not in report.lower()
    assert '<a href="https://example.com/search?a=1&amp;b=2">$890 CAD' in report
    assert "fare Good" in report
    assert "flight Normal" in report
    assert "deal 8.3/10" not in report
    assert "exact-search history" not in report
    assert "Feedback:" not in report
    assert ">Send Feedback</a>" in report


def test_weekly_report_does_not_merge_same_dates_with_different_options() -> None:
    cheapest = make_deal(price=900, minutes=26 * 60)
    faster_best = make_deal(deal_type="best_value", price=1020, score=9.1, minutes=16 * 60)

    report = build_weekly_report(
        {
            "one_week": {"cheapest": cheapest, "best_value": faster_best},
            "two_week": {},
            "one_month": {},
        },
        market_label="Good",
        market_score=7.8,
    )

    assert "Cheapest + Best Overall:" not in report
    assert "\U0001f4b8 Cheapest:" in report
    assert "\u23f1\ufe0f Best Overall:" in report
    assert "$900 CAD" in report
    assert "$1,020 CAD" in report
    assert "26h" in report
    assert "16h" in report


def test_weekly_report_shows_freshness_in_minutes() -> None:
    generated_at = datetime(2026, 5, 23, 20, 0, tzinfo=UTC)
    deal = make_deal(last_seen_at=generated_at - timedelta(minutes=38))

    report = build_weekly_report(
        {"one_week": {"cheapest": deal}, "two_week": {}, "one_month": {}},
        market_label="Good",
        market_score=7.8,
        generated_at=generated_at,
    )

    assert "checked 38 min ago" in report


def test_weekly_report_shows_freshness_in_hours() -> None:
    generated_at = datetime(2026, 5, 23, 20, 0, tzinfo=UTC)
    deal = make_deal(last_seen_at=generated_at - timedelta(hours=2, minutes=15))

    report = build_weekly_report(
        {"one_week": {"cheapest": deal}, "two_week": {}, "one_month": {}},
        market_label="Good",
        market_score=7.8,
        generated_at=generated_at,
    )

    assert "checked 2h ago" in report


def test_weekly_report_omits_freshness_when_last_seen_is_missing() -> None:
    deal = make_deal(last_seen_at=None)

    report = build_weekly_report(
        {"one_week": {"cheapest": deal}, "two_week": {}, "one_month": {}},
        market_label="Good",
        market_score=7.8,
        generated_at=datetime(2026, 5, 23, 20, 0, tzinfo=UTC),
    )

    assert "checked" not in report


def test_weekly_report_uses_fresh_empty_category_copy() -> None:
    report = build_weekly_report(
        {"one_week": {}, "two_week": {}, "one_month": {}},
        market_label="Good",
        market_score=7.8,
    )

    assert "No fresh exact-confirmed deal found." in report
    assert "No current deals." not in report


def test_weekly_report_handles_unknown_market_score() -> None:
    report = build_weekly_report(
        {"one_week": {}, "two_week": {}, "one_month": {}},
        market_label="Not enough market data yet",
        market_score=None,
    )

    assert "Market: Not enough market data yet" in report
    assert "/10" not in report.split("Market:", maxsplit=1)[1]


def test_strong_alert_has_button_url_and_escaped_fields() -> None:
    alert = build_strong_alert(make_deal(score=9.2), alert_type="best_value")

    assert "Best Overall YYZ &#8594; JED Deal" in alert.text
    assert "Saudia &amp; Partners" in alert.text
    assert "Deal score:" not in alert.text
    assert alert.button_text == "View Deal"
    assert alert.button_url == "https://example.com/search?a=1&b=2"
