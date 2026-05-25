from typing import SupportsFloat

from app.providers.base import NormalizedFlightDeal
from app.services.deal_scoring import is_suspicious_price

DealSelection = dict[str, NormalizedFlightDeal | None]
DEFAULT_BEST_VALUE_MAX_PRICE_PREMIUM_CAD = 300
DEFAULT_BEST_VALUE_MAX_PRICE_PREMIUM_RATIO = 1.25
DEFAULT_FLASH_ALERT_MEDIAN_RATIO = 0.70
DEFAULT_FLASH_ALERT_ABSOLUTE_FALLBACK_CAD = 750
DEFAULT_SUSPICIOUS_PRICE_AVERAGE_RATIO = 0.20
BEST_VALUE_PROVIDER_SORT_BONUS = 0.1


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
    best_value_exact_sort: str = "TOP_FLIGHTS",
    best_value_max_price_premium_cad: int = DEFAULT_BEST_VALUE_MAX_PRICE_PREMIUM_CAD,
    best_value_max_price_premium_ratio: float = DEFAULT_BEST_VALUE_MAX_PRICE_PREMIUM_RATIO,
) -> DealSelection:
    if not deals:
        return {"cheapest": None, "best_value": None, "backup": None}

    best_value_sort = best_value_exact_sort.upper()
    exact_deals = [deal for deal in deals if deal.exact_check_completed] or deals
    cheapest = min(exact_deals, key=_cheapest_price_key)

    guarded_best_pool = [
        deal
        for deal in exact_deals
        if _passes_best_value_price_guard(
            deal,
            cheapest,
            max_price_premium_cad=best_value_max_price_premium_cad,
            max_price_premium_ratio=best_value_max_price_premium_ratio,
        )
    ] or [cheapest]
    best_value = max(guarded_best_pool, key=lambda deal: _best_value_score(deal, best_value_sort))

    selected_keys = {cheapest.date_pair_key(), best_value.date_pair_key()}
    ranked = sorted(exact_deals, key=_deal_score, reverse=True)
    backup = next((deal for deal in ranked if deal.date_pair_key() not in selected_keys), None)
    return {"cheapest": cheapest, "best_value": best_value, "backup": backup}


def can_repost(last_posted_price_cad: int | None, current_price_cad: int) -> bool:
    return last_posted_price_cad is None or current_price_cad <= last_posted_price_cad - 100


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
    suspicious = is_suspicious_price(
        deal,
        recent_category_average,
        average_ratio=suspicious_price_average_ratio,
    )
    if suspicious and not _has_confirmation_detail(deal):
        return False
    baseline_median = _metadata_score(deal, "baseline_median_cad")
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
    return (candidate.deal_score or 0.0) > (current.deal_score or 0.0)


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
    if deal.price_cad <= cheapest.price_cad + max_price_premium_cad:
        return True
    if deal.price_cad <= cheapest.price_cad * max_price_premium_ratio:
        return True
    cheapest_quality = _metadata_score(cheapest, "flight_quality_score")
    deal_quality = _metadata_score(deal, "flight_quality_score")
    return bool(
        cheapest_quality is not None
        and deal_quality is not None
        and cheapest_quality <= 6.0
        and deal_quality >= cheapest_quality + 2.0
    )


def _metadata_score(deal: NormalizedFlightDeal, key: str) -> float | None:
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


def _deal_score(deal: NormalizedFlightDeal) -> float:
    return deal.deal_score or 0.0


def _best_value_score(deal: NormalizedFlightDeal, preferred_sort: str) -> float:
    score = _deal_score(deal)
    if _exact_sort_mode(deal) == preferred_sort:
        score += BEST_VALUE_PROVIDER_SORT_BONUS
    return score


def _cheapest_price_key(deal: NormalizedFlightDeal) -> tuple[int, int]:
    prefer_cheapest_mode = 0 if _exact_sort_mode(deal) == "CHEAPEST" else 1
    return deal.price_cad, prefer_cheapest_mode
