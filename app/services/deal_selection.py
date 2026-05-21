from app.providers.base import NormalizedFlightDeal
from app.services.deal_scoring import is_suspicious_price

DealSelection = dict[str, NormalizedFlightDeal | None]


def dedupe_deals(deals: list[NormalizedFlightDeal]) -> list[NormalizedFlightDeal]:
    selected: dict[tuple, NormalizedFlightDeal] = {}
    for deal in deals:
        current = selected.get(deal.dedupe_key())
        if current is None or _is_better_duplicate(deal, current):
            selected[deal.dedupe_key()] = deal
    return list(selected.values())


def is_extreme_bad_flight(deal: NormalizedFlightDeal) -> bool:
    if deal.total_travel_minutes is not None and deal.total_travel_minutes > 32 * 60:
        return True
    if deal.stops is not None and deal.stops > 2:
        return True
    if deal.layover_summary and "airport change" in deal.layover_summary.lower():
        return True
    return bool(deal.layover_summary and "unusable" in deal.layover_summary.lower())


def select_active_deals(deals: list[NormalizedFlightDeal]) -> DealSelection:
    if not deals:
        return {"cheapest": None, "best_value": None, "backup": None}

    cheapest_pool = [deal for deal in deals if not is_extreme_bad_flight(deal)] or deals
    cheapest = min(cheapest_pool, key=lambda deal: deal.price_cad)
    ranked = sorted(deals, key=lambda deal: deal.deal_score or 0.0, reverse=True)
    best_value = ranked[0]
    selected_keys = {cheapest.date_pair_key(), best_value.date_pair_key()}
    backup = next((deal for deal in ranked if deal.date_pair_key() not in selected_keys), None)
    return {"cheapest": cheapest, "best_value": best_value, "backup": backup}


def can_repost(last_posted_price_cad: int | None, current_price_cad: int) -> bool:
    return last_posted_price_cad is None or current_price_cad <= last_posted_price_cad - 100


def qualifies_for_strong_alert(
    deal: NormalizedFlightDeal,
    recent_category_average: float | None,
    last_posted_price_cad: int | None,
) -> bool:
    if not deal.exact_check_completed:
        return False
    if not can_repost(last_posted_price_cad, deal.price_cad):
        return False
    if is_suspicious_price(deal, recent_category_average) and not _has_confirmation_detail(deal):
        return False
    score = deal.deal_score or 0.0
    if score >= 9.0:
        return True
    return score >= 8.5 and is_suspicious_price(deal, recent_category_average)


def _is_better_duplicate(candidate: NormalizedFlightDeal, current: NormalizedFlightDeal) -> bool:
    if candidate.exact_check_completed != current.exact_check_completed:
        return candidate.exact_check_completed
    return (candidate.deal_score or 0.0) > (current.deal_score or 0.0)


def _has_confirmation_detail(deal: NormalizedFlightDeal) -> bool:
    return bool(deal.airline or deal.stops is not None or deal.total_travel_minutes is not None)
