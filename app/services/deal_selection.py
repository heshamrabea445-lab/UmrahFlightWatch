from typing import SupportsFloat

from app.providers.base import NormalizedFlightDeal
from app.services.deal_scoring import DEFAULT_SUSPICIOUS_PRICE_AVERAGE_RATIO, is_suspicious_price

DealSelection = dict[str, NormalizedFlightDeal | None]
DEFAULT_BEST_VALUE_MAX_PRICE_PREMIUM_CAD = 300
DEFAULT_BEST_VALUE_MAX_PRICE_PREMIUM_RATIO = 1.25
DEFAULT_FLASH_ALERT_MEDIAN_RATIO = 0.70
DEFAULT_FLASH_ALERT_ABSOLUTE_FALLBACK_CAD = 750
REPOST_PRICE_DROP_CAD = 100
UNKNOWN_DURATION_MINUTES = 10**9
PREFERRED_BEST_VALUE_SORT_MODE = "TOP_FLIGHTS"


def dedupe_deals(deals: list[NormalizedFlightDeal]) -> list[NormalizedFlightDeal]:
    selected: dict[tuple, NormalizedFlightDeal] = {}
    for deal in deals:
        current = selected.get(deal.dedupe_key())
        if current is None or _is_better_duplicate(deal, current):
            selected[deal.dedupe_key()] = deal
    return list(selected.values())


def select_active_deals(
    deals: list[NormalizedFlightDeal],
    *,
    best_value_max_price_premium_cad: int = DEFAULT_BEST_VALUE_MAX_PRICE_PREMIUM_CAD,
    best_value_max_price_premium_ratio: float = DEFAULT_BEST_VALUE_MAX_PRICE_PREMIUM_RATIO,
) -> DealSelection:
    """Pick the Cheapest (lowest price) and Best Overall (fastest within price guard).

    Best Overall is intentionally NOT scored by `deal_score`: it picks the shortest total
    travel time among deals whose price stays within the guard, breaking ties toward the
    provider's `TOP_FLIGHTS` ranking and then toward a lower price.
    """
    if not deals:
        return {"cheapest": None, "best_value": None}

    exact_deals = [deal for deal in deals if deal.exact_check_completed] or deals
    cheapest = min(exact_deals, key=_cheapest_price_key)

    guarded = [
        deal
        for deal in exact_deals
        if _passes_best_value_price_guard(
            deal,
            cheapest,
            max_price_premium_cad=best_value_max_price_premium_cad,
            max_price_premium_ratio=best_value_max_price_premium_ratio,
        )
    ] or [cheapest]
    best_value = min(guarded, key=_best_value_sort_key)

    return {"cheapest": cheapest, "best_value": best_value}


def can_repost(last_posted_price_cad: int | None, current_price_cad: int) -> bool:
    return (
        last_posted_price_cad is None
        or current_price_cad <= last_posted_price_cad - REPOST_PRICE_DROP_CAD
    )


def qualifies_for_strong_alert(
    deal: NormalizedFlightDeal,
    recent_category_average: SupportsFloat | None,
    last_posted_price_cad: int | None,
    *,
    flash_alert_median_ratio: float = DEFAULT_FLASH_ALERT_MEDIAN_RATIO,
    flash_alert_absolute_fallback_cad: int = DEFAULT_FLASH_ALERT_ABSOLUTE_FALLBACK_CAD,
    suspicious_price_average_ratio: float = DEFAULT_SUSPICIOUS_PRICE_AVERAGE_RATIO,
) -> bool:
    if not deal.exact_check_completed:
        return False
    if not can_repost(last_posted_price_cad, deal.price_cad):
        return False
    if is_suspicious_price(
        deal,
        recent_category_average,
        average_ratio=suspicious_price_average_ratio,
    ) and not _has_confirmation_detail(deal):
        return False
    baseline_median = _metadata_float(deal, "baseline_median_cad")
    if (
        _metadata_bool(deal, "baseline_has_enough_history")
        and baseline_median is not None
        and baseline_median > 0
    ):
        return deal.price_cad <= baseline_median * flash_alert_median_ratio
    return deal.price_cad <= flash_alert_absolute_fallback_cad


def _is_better_duplicate(candidate: NormalizedFlightDeal, current: NormalizedFlightDeal) -> bool:
    if candidate.exact_check_completed != current.exact_check_completed:
        return candidate.exact_check_completed
    return _duration(candidate) < _duration(current)


def _has_confirmation_detail(deal: NormalizedFlightDeal) -> bool:
    return bool(deal.airline or deal.stops is not None or deal.total_travel_minutes is not None)


def _exact_sort_mode(deal: NormalizedFlightDeal) -> str | None:
    raw = deal.metadata.get("exact_sort_mode")
    return str(raw).upper() if raw else None


def _passes_best_value_price_guard(
    deal: NormalizedFlightDeal,
    cheapest: NormalizedFlightDeal,
    *,
    max_price_premium_cad: int,
    max_price_premium_ratio: float,
) -> bool:
    return (
        deal.price_cad <= cheapest.price_cad + max_price_premium_cad
        or deal.price_cad <= cheapest.price_cad * max_price_premium_ratio
    )


def _metadata_float(deal: NormalizedFlightDeal, key: str) -> float | None:
    value = deal.metadata.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _metadata_bool(deal: NormalizedFlightDeal, key: str) -> bool:
    value = deal.metadata.get(key)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() == "true"
    return False


def _duration(deal: NormalizedFlightDeal) -> int:
    return (
        deal.total_travel_minutes
        if deal.total_travel_minutes is not None
        else UNKNOWN_DURATION_MINUTES
    )


def _best_value_sort_key(deal: NormalizedFlightDeal) -> tuple[int, int, int]:
    not_preferred_sort = 0 if _exact_sort_mode(deal) == PREFERRED_BEST_VALUE_SORT_MODE else 1
    return (_duration(deal), not_preferred_sort, deal.price_cad)


def _cheapest_price_key(deal: NormalizedFlightDeal) -> tuple[int, int]:
    prefer_cheapest_mode = 0 if _exact_sort_mode(deal) == "CHEAPEST" else 1
    return deal.price_cad, prefer_cheapest_mode
