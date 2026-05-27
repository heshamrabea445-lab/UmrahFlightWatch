from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.providers.base import NormalizedFlightDeal
from app.utils.dates import CATEGORY_LABELS, ordered_categories, utc_now
from app.utils.formatting import (
    escape_telegram_html,
    format_currency_cad,
    format_date_short,
    format_minutes,
    html_link,
)


@dataclass(frozen=True)
class AlertMessage:
    text: str
    button_text: str
    button_url: str


def build_weekly_report(
    active_deals: dict[str, dict[str, NormalizedFlightDeal]],
    *,
    market_label: str,
    market_score: float | None,
    feedback_form_url: str = "",
    generated_at: datetime | None = None,
) -> str:
    report_time = generated_at or utc_now()
    lines = [
        "\U0001f54b Weekly YYZ &#8594; JED Flight Watch",
        _report_date(report_time),
        "",
    ]
    _append_deal_sections(lines, active_deals, generated_at=report_time)

    if market_score is None:
        lines.append(f"\U0001f4ca Market: {escape_telegram_html(market_label)}")
    else:
        lines.append(
            f"\U0001f4ca Market: {escape_telegram_html(market_label)} -- {market_score:.1f}/10"
        )
    lines.append("")
    lines.append(_PRICE_WARNING)
    if feedback_form_url:
        lines.append(html_link(feedback_form_url, "Send Feedback"))
    return "\n".join(lines).strip()


def build_current_deals_message(
    active_deals: dict[str, dict[str, NormalizedFlightDeal]],
    *,
    generated_at: datetime | None = None,
) -> str:
    report_time = generated_at or utc_now()
    lines = ["\U0001f54b Latest YYZ &#8594; JED Deals", ""]
    _append_deal_sections(lines, active_deals, generated_at=report_time)
    lines.append(_PRICE_WARNING)
    return "\n".join(lines).strip()


def build_strong_alert(deal: NormalizedFlightDeal, alert_type: str) -> AlertMessage:
    title = (
        "\U0001f6a8 Ultra-Cheap YYZ &#8594; JED Deal"
        if alert_type == "cheapest"
        else "\U0001f525 Best Overall YYZ &#8594; JED Deal"
    )
    lines = [title, ""]
    lines.append(f"Price/Dates: {_price_date_link(deal)}")
    lines.append(f"Trip length: {deal.trip_length_days} days")
    _append_optional(lines, "Stops", _format_stops(deal.stops))
    _append_optional(lines, "Airline", deal.airline)
    _append_optional(lines, "Total travel time", format_minutes(deal.total_travel_minutes))
    _append_optional(lines, "Layover", deal.layover_summary)
    _append_optional(lines, "Baggage", deal.baggage_summary)
    return AlertMessage(
        text="\n".join(lines),
        button_text="View Deal",
        button_url=deal.google_flights_link or "",
    )


def _deal_line(label: str, deal: NormalizedFlightDeal, *, generated_at: datetime) -> str:
    display_label = _deal_label(label)
    parts = [
        f"{display_label}: {_price_date_link(deal)}",
        f"{deal.trip_length_days} days",
    ]
    stops = _format_stops(deal.stops)
    if stops:
        parts.append(stops)
    if deal.airline:
        parts.append(escape_telegram_html(deal.airline))
    minutes = format_minutes(deal.total_travel_minutes)
    if minutes:
        parts.append(minutes)
    if deal.layover_summary:
        parts.append(escape_telegram_html(deal.layover_summary))
    if deal.baggage_summary:
        parts.append(escape_telegram_html(deal.baggage_summary))
    fare_label = _metadata_label(deal, "fare_label")
    if fare_label:
        parts.append(f"fare {fare_label}")
    flight_quality_label = _metadata_label(deal, "flight_quality_label")
    if flight_quality_label:
        parts.append(f"flight {flight_quality_label}")
    freshness = _freshness_label(deal, generated_at=generated_at)
    if freshness:
        parts.append(freshness)
    return " -- ".join(parts)


_PRICE_WARNING = (
    "\u26a0\ufe0f Prices can change. Always verify the final price, baggage, "
    "and layovers before booking."
)


def _append_deal_sections(
    lines: list[str],
    active_deals: dict[str, dict[str, NormalizedFlightDeal]],
    *,
    generated_at: datetime,
) -> None:
    for category in ordered_categories():
        lines.append(CATEGORY_LABELS[category])
        category_deals = active_deals.get(category, {})
        cheapest = category_deals.get("cheapest")
        best_value = category_deals.get("best_value")
        if cheapest and best_value and _same_report_option(cheapest, best_value):
            lines.append(_deal_line("Cheapest + Best Overall", cheapest, generated_at=generated_at))
        else:
            if cheapest:
                lines.append(_deal_line("Cheapest", cheapest, generated_at=generated_at))
            if best_value:
                lines.append(_deal_line("Best Overall", best_value, generated_at=generated_at))
        if not cheapest and not best_value:
            lines.append("No fresh exact-confirmed deal found.")
        lines.append("")


def _deal_label(label: str) -> str:
    if label == "Cheapest":
        return "\U0001f4b8 Cheapest"
    if label == "Best Overall":
        return "\u23f1\ufe0f Best Overall"
    if label == "Cheapest + Best Overall":
        return "\U0001f4b8\u23f1\ufe0f Cheapest + Best Overall"
    return label


def _report_date(value: datetime) -> str:
    return f"{value.strftime('%B')} {value.day}, {value.year}"


def _freshness_label(deal: NormalizedFlightDeal, *, generated_at: datetime) -> str | None:
    if deal.last_seen_at is None:
        return None
    last_seen = deal.last_seen_at
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    report_time = generated_at
    if report_time.tzinfo is None:
        report_time = report_time.replace(tzinfo=UTC)
    minutes = max(0, int((report_time - last_seen).total_seconds() // 60))
    if minutes < 60:
        return f"checked {minutes} min ago"
    return f"checked {minutes // 60}h ago"


def _same_report_option(first: NormalizedFlightDeal, second: NormalizedFlightDeal) -> bool:
    return (
        first.date_pair_key() == second.date_pair_key()
        and first.price_cad == second.price_cad
        and first.airline == second.airline
        and first.stops == second.stops
        and first.total_travel_minutes == second.total_travel_minutes
        and first.layover_summary == second.layover_summary
        and first.baggage_summary == second.baggage_summary
    )


def _metadata_label(deal: NormalizedFlightDeal, key: str) -> str | None:
    value = deal.metadata.get(key)
    return escape_telegram_html(str(value)) if value else None


def _price_date_link(deal: NormalizedFlightDeal) -> str:
    label = (
        f"{format_currency_cad(deal.price_cad)} -- "
        f"{format_date_short(deal.depart_date)} -> {format_date_short(deal.return_date)}"
    )
    if not deal.google_flights_link:
        return escape_telegram_html(label)
    return html_link(deal.google_flights_link, label)


def _format_stops(stops: int | None) -> str | None:
    if stops is None:
        return None
    if stops == 0:
        return "nonstop"
    if stops == 1:
        return "1 stop"
    return f"{stops} stops"


def _append_optional(lines: list[str], label: str, value: str | None) -> None:
    if value:
        lines.append(f"{label}: {escape_telegram_html(value)}")
