from typing import SupportsFloat

from app.providers.base import NormalizedFlightDeal
from app.services.market_baseline import (
    EXCELLENT_MEDIAN_RATIO,
    GOOD_MEDIAN_RATIO,
    HIGH_MEDIAN_RATIO,
    NORMAL_MEDIAN_RATIO,
    PriceBaseline,
)

FARE_SCORE_WEIGHT = 0.4
FLIGHT_QUALITY_SCORE_WEIGHT = 0.6
DEFAULT_SUSPICIOUS_PRICE_AVERAGE_RATIO = 0.20


def is_suspicious_price(
    deal: NormalizedFlightDeal,
    recent_category_average: SupportsFloat | None,
    *,
    average_ratio: float = DEFAULT_SUSPICIOUS_PRICE_AVERAGE_RATIO,
) -> bool:
    average = float(recent_category_average) if recent_category_average is not None else None
    return bool(average and deal.price_cad < average * average_ratio)


def apply_deal_ratings(
    deal: NormalizedFlightDeal,
    *,
    fare_baseline: PriceBaseline | None,
    recent_category_average: SupportsFloat | None,
    min_history_rows: int,
) -> NormalizedFlightDeal:
    fare_score, fare_label, used_fallback = _fare_score_and_label(
        deal.price_cad,
        recent_category_average,
        fare_baseline=fare_baseline,
        min_history_rows=min_history_rows,
    )
    flight_quality_score = calculate_flight_quality_score(deal)
    flight_quality_label = _quality_label(flight_quality_score)
    deal_score = _clamp_score(
        fare_score * FARE_SCORE_WEIGHT + flight_quality_score * FLIGHT_QUALITY_SCORE_WEIGHT
    )
    deal.deal_score = deal_score
    deal.market_label = fare_label
    deal.metadata.update(
        {
            "fare_label": fare_label,
            "fare_uses_static_fallback": used_fallback,
            "flight_quality_label": flight_quality_label,
        }
    )
    if fare_baseline is not None:
        deal.metadata["baseline_has_enough_history"] = fare_baseline.has_enough_history(
            min_history_rows
        )
        if fare_baseline.median is not None:
            deal.metadata["baseline_median_cad"] = int(round(fare_baseline.median))
    return deal


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


def fare_label_for_ratio(ratio: float) -> str:
    if ratio <= EXCELLENT_MEDIAN_RATIO:
        return "Excellent"
    if ratio <= GOOD_MEDIAN_RATIO:
        return "Good"
    if ratio <= NORMAL_MEDIAN_RATIO:
        return "Normal"
    if ratio <= HIGH_MEDIAN_RATIO:
        return "High"
    return "Very High"


def fare_score_for_ratio(ratio: float) -> float:
    if ratio <= EXCELLENT_MEDIAN_RATIO:
        return 10.0
    if ratio <= GOOD_MEDIAN_RATIO:
        return 8.5
    if ratio <= NORMAL_MEDIAN_RATIO:
        return 7.0
    if ratio <= HIGH_MEDIAN_RATIO:
        return 5.5
    return 3.0


def _fare_score_and_label(
    price_cad: int,
    recent_category_average: SupportsFloat | None,
    *,
    fare_baseline: PriceBaseline | None,
    min_history_rows: int,
) -> tuple[float, str, bool]:
    if (
        fare_baseline is not None
        and fare_baseline.has_enough_history(min_history_rows)
        and fare_baseline.median is not None
        and fare_baseline.median > 0
    ):
        ratio = price_cad / fare_baseline.median
        return fare_score_for_ratio(ratio), fare_label_for_ratio(ratio), False
    average = float(recent_category_average) if recent_category_average is not None else None
    if average and average > 0:
        ratio = price_cad / average
        return fare_score_for_ratio(ratio), fare_label_for_ratio(ratio), True
    score, label = _static_price_band(price_cad)
    return score, label, True


def _static_price_band(price_cad: int) -> tuple[float, str]:
    if price_cad <= 900:
        return 9.0, "Good"
    if price_cad <= 1050:
        return 8.0, "Good"
    if price_cad <= 1200:
        return 7.0, "Normal"
    if price_cad <= 1400:
        return 5.5, "High"
    return 3.0, "Very High"


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


def _quality_label(score: float) -> str:
    if score >= 9.0:
        return "Excellent"
    if score >= 8.0:
        return "Good"
    if score >= 6.5:
        return "Normal"
    if score >= 5.0:
        return "Poor"
    return "Very Poor"


def _clamp_score(score: float) -> float:
    return round(max(0.0, min(10.0, score)), 1)
