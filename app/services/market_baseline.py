from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from statistics import mean, median
from typing import Any

EXCELLENT_MEDIAN_RATIO = 0.85
GOOD_MEDIAN_RATIO = 0.95
NORMAL_MEDIAN_RATIO = 1.06
HIGH_MEDIAN_RATIO = 1.20
MIN_HISTORY_ROWS = 20


@dataclass(frozen=True)
class PriceBaseline:
    baseline_days: int
    sample_size: int
    average: float | None
    median: float | None

    def has_enough_history(self, min_history_rows: int) -> bool:
        return self.sample_size >= min_history_rows


@dataclass(frozen=True)
class MarketRating:
    label: str
    score: float | None
    metadata: dict[str, Any]


def build_price_baseline(
    prices: Iterable[int],
    *,
    baseline_days: int,
) -> PriceBaseline:
    values = [int(price) for price in prices]
    if not values:
        return PriceBaseline(
            baseline_days=baseline_days,
            sample_size=0,
            average=None,
            median=None,
        )
    return PriceBaseline(
        baseline_days=baseline_days,
        sample_size=len(values),
        average=mean(values),
        median=float(median(values)),
    )


def cheapest_snapshot_prices_by_category(rows: Iterable[Any]) -> dict[str, list[int]]:
    cheapest_by_scan: dict[tuple[str, datetime], int] = {}
    for row in rows:
        key = (row.category, row.checked_at)
        current = cheapest_by_scan.get(key)
        if current is None or row.price_cad < current:
            cheapest_by_scan[key] = row.price_cad

    output: dict[str, list[int]] = {}
    for (category, _checked_at), price in cheapest_by_scan.items():
        output.setdefault(category, []).append(price)
    return output


def build_cheapest_snapshot_baseline(
    rows: Iterable[Any],
    *,
    category: str,
    baseline_days: int,
) -> PriceBaseline:
    prices_by_category = cheapest_snapshot_prices_by_category(rows)
    return build_price_baseline(
        prices_by_category.get(category, []),
        baseline_days=baseline_days,
    )


def median_ratio_score_for_price(price_cad: int, baseline: PriceBaseline) -> float:
    if baseline.median is None or baseline.median <= 0:
        return 3.0
    ratio = price_cad / baseline.median
    if ratio <= EXCELLENT_MEDIAN_RATIO:
        return 10.0
    if ratio <= GOOD_MEDIAN_RATIO:
        return 8.5
    if ratio <= NORMAL_MEDIAN_RATIO:
        return 7.0
    if ratio <= HIGH_MEDIAN_RATIO:
        return 5.5
    return 3.0


def calculate_market_rating(
    current_cheapest_prices: Mapping[str, int],
    snapshot_prices_by_category: Mapping[str, list[int]],
    *,
    baseline_days: int,
    min_history_rows: int,
) -> MarketRating:
    category_scores: dict[str, float] = {}

    for category, current_price in current_cheapest_prices.items():
        baseline = build_price_baseline(
            snapshot_prices_by_category.get(category, []),
            baseline_days=baseline_days,
        )
        if not baseline.has_enough_history(min_history_rows):
            continue
        category_scores[category] = median_ratio_score_for_price(current_price, baseline)

    if not category_scores:
        return MarketRating(
            label="Not enough 90-day exact-search history",
            score=None,
            metadata={
                "baseline_days": baseline_days,
                "min_history_rows": min_history_rows,
                "category_scores": category_scores,
            },
        )

    score = round(mean(category_scores.values()), 1)
    return MarketRating(
        label=market_label(score),
        score=score,
        metadata={
            "baseline_days": baseline_days,
            "min_history_rows": min_history_rows,
            "category_scores": category_scores,
        },
    )


def market_label(score: float) -> str:
    if score >= 9.0:
        return "Excellent buying window"
    if score >= 8.0:
        return "Good buying window"
    if score >= 6.5:
        return "Normal market"
    if score >= 5.0:
        return "Expensive market"
    return "Very expensive market"
