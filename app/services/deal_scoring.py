from typing import SupportsFloat

from app.providers.base import NormalizedFlightDeal
from app.services.market_baseline import PriceBaseline, median_ratio_score_for_price

FARE_SCORE_WEIGHT = 0.25
FLIGHT_QUALITY_SCORE_WEIGHT = 0.65
CONFIDENCE_SCORE_WEIGHT = 0.10
DEFAULT_SUSPICIOUS_PRICE_AVERAGE_RATIO = 0.20


def score_label(score: float) -> str:
    if score >= 9.0:
        return "Excellent"
    if score >= 8.0:
        return "Good"
    if score >= 6.5:
        return "Normal"
    if score >= 5.0:
        return "High"
    return "Very High"


def quality_label(score: float) -> str:
    if score >= 9.0:
        return "Excellent"
    if score >= 8.0:
        return "Good"
    if score >= 6.5:
        return "Normal"
    if score >= 5.0:
        return "Poor"
    return "Very Poor"


def is_suspicious_price(
    deal: NormalizedFlightDeal,
    recent_category_average: SupportsFloat | None,
    *,
    average_ratio: float = DEFAULT_SUSPICIOUS_PRICE_AVERAGE_RATIO,
) -> bool:
    average = _coerce_average(recent_category_average)
    return bool(average and deal.price_cad < average * average_ratio)


def calculate_deal_score(
    deal: NormalizedFlightDeal,
    recent_category_average: SupportsFloat | None,
    *,
    fare_baseline: PriceBaseline | None = None,
    min_history_rows: int = 20,
) -> float:
    fare_score, _fare_label, _fallback = calculate_fare_score(
        deal.price_cad,
        recent_category_average,
        fare_baseline=fare_baseline,
        min_history_rows=min_history_rows,
    )
    flight_quality_score = calculate_flight_quality_score(deal)
    confidence_score = calculate_confidence_score(deal)
    return _combined_deal_score(fare_score, flight_quality_score, confidence_score)


def apply_deal_ratings(
    deal: NormalizedFlightDeal,
    *,
    fare_baseline: PriceBaseline | None,
    recent_category_average: SupportsFloat | None,
    min_history_rows: int,
) -> NormalizedFlightDeal:
    fare_score, fare_label, used_fallback = calculate_fare_score(
        deal.price_cad,
        recent_category_average,
        fare_baseline=fare_baseline,
        min_history_rows=min_history_rows,
    )
    flight_quality_score = calculate_flight_quality_score(deal)
    flight_quality_label = quality_label(flight_quality_score)
    confidence_score = calculate_confidence_score(deal)
    deal_score = _combined_deal_score(fare_score, flight_quality_score, confidence_score)
    deal.deal_score = deal_score
    deal.market_label = fare_label
    baseline_metadata = (
        fare_baseline.metadata(min_history_rows=min_history_rows) if fare_baseline else {}
    )
    deal.metadata.update(
        {
            **baseline_metadata,
            "fare_score": fare_score,
            "fare_label": fare_label,
            "fare_uses_static_fallback": used_fallback,
            "flight_quality_score": flight_quality_score,
            "flight_quality_label": flight_quality_label,
            "confidence_score": confidence_score,
            "deal_score": deal_score,
        }
    )
    return deal


def calculate_fare_score(
    price_cad: int,
    recent_category_average: SupportsFloat | None,
    *,
    fare_baseline: PriceBaseline | None = None,
    min_history_rows: int = 20,
) -> tuple[float, str, bool]:
    if fare_baseline and fare_baseline.has_enough_history(min_history_rows):
        score = _baseline_price_score(price_cad, fare_baseline)
        return score, score_label(score), False
    score = _price_score(price_cad, recent_category_average)
    return score, score_label(score), True


def calculate_flight_quality_score(deal: NormalizedFlightDeal) -> float:
    weighted_parts: list[tuple[float, float]] = []
    duration_score = _duration_score(deal.total_travel_minutes)
    if duration_score is not None:
        weighted_parts.append((duration_score, 0.90))

    layover_score = _layover_score(deal.layover_summary)
    if layover_score is not None:
        weighted_parts.append((layover_score, 0.075))

    baggage_score = _baggage_score(deal.baggage_summary)
    if baggage_score is not None:
        weighted_parts.append((baggage_score, 0.025))

    if not weighted_parts:
        return 7.0
    total_weight = sum(weight for _score, weight in weighted_parts)
    return _clamp_score(sum(score * weight for score, weight in weighted_parts) / total_weight)


def calculate_confidence_score(deal: NormalizedFlightDeal) -> float:
    score = 8.0 if deal.exact_check_completed else 3.0
    if deal.airline:
        score += 0.5
    if deal.stops is not None:
        score += 0.5
    if deal.total_travel_minutes is not None:
        score += 0.5

    calendar_price = _coerce_optional_float(deal.metadata.get("calendar_price_cad"))
    if calendar_price and calendar_price > 0:
        difference_ratio = abs(deal.price_cad - calendar_price) / calendar_price
        if difference_ratio <= 0.10:
            score += 0.5
        elif difference_ratio <= 0.25:
            score += 0.2
        elif difference_ratio >= 0.50:
            score -= 1.0

    if deal.price_cad < 500 and not (deal.airline or deal.stops is not None):
        score -= 2.0
    return _clamp_score(score)


def _price_score(price_cad: int, recent_average: SupportsFloat | None) -> float:
    average = _coerce_average(recent_average)
    if average and average > 0:
        ratio = price_cad / average
        if ratio <= 0.70:
            return 10.0
        if ratio <= 0.80:
            return 9.0
        if ratio <= 0.90:
            return 8.0
        if ratio <= 1.00:
            return 7.0
        if ratio <= 1.15:
            return 5.5
        if ratio <= 1.30:
            return 4.0
        return 2.0

    if price_cad <= 900:
        return 9.0
    if price_cad <= 1050:
        return 8.0
    if price_cad <= 1200:
        return 7.0
    if price_cad <= 1400:
        return 5.5
    if price_cad <= 1600:
        return 4.0
    return 2.5


def _baseline_price_score(price_cad: int, baseline: PriceBaseline) -> float:
    return median_ratio_score_for_price(price_cad, baseline)


def _coerce_average(recent_average: SupportsFloat | None) -> float | None:
    return float(recent_average) if recent_average is not None else None


def _coerce_optional_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _duration_score(total_travel_minutes: int | None) -> float | None:
    if total_travel_minutes is None:
        return None
    hours = total_travel_minutes / 60
    if hours <= 14:
        return 10.0
    if hours <= 16:
        return 9.5
    if hours <= 20:
        return 9.0
    if hours <= 24:
        return 8.0
    if hours <= 28:
        return 6.0
    if hours <= 32:
        return 4.5
    return 2.0


def _layover_score(layover_summary: str | None) -> float | None:
    if not layover_summary:
        return None
    summary = layover_summary.lower()
    if "airport change" in summary or "unusable" in summary:
        return 2.0
    if "overnight" in summary:
        return 5.0
    return 7.0


def _baggage_score(baggage_summary: str | None) -> float | None:
    if not baggage_summary:
        return None
    if "carry-on only" in baggage_summary.lower():
        return 6.5
    return 8.0


def _clamp_score(score: float) -> float:
    return round(max(0.0, min(10.0, score)), 1)


def _combined_deal_score(
    fare_score: float,
    flight_quality_score: float,
    confidence_score: float,
) -> float:
    return _clamp_score(
        fare_score * FARE_SCORE_WEIGHT
        + flight_quality_score * FLIGHT_QUALITY_SCORE_WEIGHT
        + confidence_score * CONFIDENCE_SCORE_WEIGHT
    )
