from statistics import mean

from app.providers.base import NormalizedFlightDeal


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


def is_suspicious_price(
    deal: NormalizedFlightDeal,
    recent_category_average: float | None,
) -> bool:
    if deal.price_cad < 500:
        return True
    return bool(recent_category_average and deal.price_cad < recent_category_average * 0.40)


def calculate_deal_score(
    deal: NormalizedFlightDeal,
    recent_category_average: float | None,
) -> float:
    price_score = _price_score(deal.price_cad, recent_category_average)
    quality_score = _quality_score(deal)
    return round(max(0.0, min(10.0, price_score * 0.70 + quality_score * 0.30)), 1)


def calculate_market_rating(deals: list[NormalizedFlightDeal]) -> tuple[str, float]:
    scores = [deal.deal_score for deal in deals if deal.deal_score is not None]
    if not scores:
        return "Very High", 0.0
    market_score = round(mean(sorted(scores, reverse=True)[:6]), 1)
    return score_label(market_score), market_score


def _price_score(price_cad: int, recent_average: float | None) -> float:
    if recent_average and recent_average > 0:
        ratio = price_cad / recent_average
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


def _quality_score(deal: NormalizedFlightDeal) -> float:
    parts: list[float] = []
    if deal.stops is not None:
        if deal.stops == 0:
            parts.append(10.0)
        elif deal.stops == 1:
            parts.append(8.5)
        elif deal.stops == 2:
            parts.append(6.5)
        else:
            parts.append(3.0)

    if deal.total_travel_minutes is not None:
        hours = deal.total_travel_minutes / 60
        if hours <= 18:
            parts.append(9.0)
        elif hours <= 24:
            parts.append(7.5)
        elif hours <= 32:
            parts.append(5.5)
        else:
            parts.append(2.0)

    if deal.layover_summary:
        summary = deal.layover_summary.lower()
        if "airport change" in summary:
            parts.append(2.0)
        elif "overnight" in summary:
            parts.append(5.0)
        else:
            parts.append(7.0)

    if deal.baggage_summary and "carry-on only" in deal.baggage_summary.lower():
        parts.append(6.5)

    return round(mean(parts), 1) if parts else 7.0
