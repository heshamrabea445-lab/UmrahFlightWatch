from __future__ import annotations

from dataclasses import dataclass

from app.providers.base import NormalizedFlightDeal
from app.utils.dates import CATEGORY_LABELS, ordered_categories
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
    market_score: float,
    feedback_form_url: str = "",
) -> str:
    lines = ["Weekly YYZ &rarr; JED Report", ""]
    for category in ordered_categories():
        lines.append(CATEGORY_LABELS[category])
        category_deals = active_deals.get(category, {})
        cheapest = category_deals.get("cheapest")
        best_value = category_deals.get("best_value")
        if cheapest and best_value and cheapest.date_pair_key() == best_value.date_pair_key():
            lines.append(_deal_line("Cheapest + Best Value", cheapest))
        else:
            if cheapest:
                lines.append(_deal_line("Cheapest", cheapest))
            if best_value:
                lines.append(_deal_line("Best Value", best_value))
        if not cheapest and not best_value:
            lines.append("No current deals.")
        lines.append("")

    lines.append(f"Market: {escape_telegram_html(market_label)} -- {market_score:.1f}/10")
    lines.append("")
    lines.append(
        "Note: Prices can change. Always verify the final price, baggage, "
        "and layovers before booking."
    )
    if feedback_form_url:
        lines.append(f"Feedback: {html_link(feedback_form_url, 'Send a fare tip')}")
    return "\n".join(lines).strip()


def build_strong_alert(deal: NormalizedFlightDeal, alert_type: str) -> AlertMessage:
    title = (
        "\U0001f6a8 Ultra-Cheap YYZ &rarr; JED Deal"
        if alert_type == "cheapest"
        else "\U0001f525 Best-Value YYZ &rarr; JED Deal"
    )
    lines = [title, ""]
    lines.append(f"Price/Dates: {_price_date_link(deal)}")
    lines.append(f"Trip length: {deal.trip_length_days} days")
    _append_optional(lines, "Stops", _format_stops(deal.stops))
    _append_optional(lines, "Airline", deal.airline)
    _append_optional(lines, "Total travel time", format_minutes(deal.total_travel_minutes))
    _append_optional(lines, "Layover", deal.layover_summary)
    _append_optional(lines, "Baggage", deal.baggage_summary)
    if deal.deal_score is not None:
        lines.append(f"Deal score: {deal.deal_score:.1f}/10")
    return AlertMessage(
        text="\n".join(lines),
        button_text="View Deal",
        button_url=deal.google_flights_link or "",
    )


def _deal_line(label: str, deal: NormalizedFlightDeal) -> str:
    parts = [
        f"{label}: {_price_date_link(deal)}",
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
    if deal.deal_score is not None:
        parts.append(f"{deal.deal_score:.1f}/10")
    return " -- ".join(parts)


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
