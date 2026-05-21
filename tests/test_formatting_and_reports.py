from datetime import date

from app.providers.base import NormalizedFlightDeal
from app.services.report_builder import build_strong_alert, build_weekly_report
from app.utils.formatting import escape_telegram_html


def make_deal(
    *,
    deal_type: str = "cheapest",
    price: int = 890,
    score: float = 8.3,
) -> NormalizedFlightDeal:
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
        total_travel_minutes=26 * 60,
        google_flights_link="https://example.com/search?a=1&b=2",
        source="fli",
        exact_check_completed=True,
        deal_score=score,
        metadata={"deal_type": deal_type},
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
    )

    assert "Weekly YYZ &rarr; JED Report" in report
    assert "Cheapest + Best Value:" in report
    assert "unknown" not in report.lower()
    assert '<a href="https://example.com/search?a=1&amp;b=2">$890 CAD' in report
    assert "Feedback:" in report


def test_strong_alert_has_button_url_and_escaped_fields() -> None:
    alert = build_strong_alert(make_deal(score=9.2), alert_type="best_value")

    assert "Best-Value YYZ &rarr; JED Deal" in alert.text
    assert "Saudia &amp; Partners" in alert.text
    assert alert.button_text == "View Deal"
    assert alert.button_url == "https://example.com/search?a=1&b=2"
