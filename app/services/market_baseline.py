from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from statistics import mean
from typing import Any

EXCELLENT_MEDIAN_RATIO = 0.85
GOOD_MEDIAN_RATIO = 0.95
NORMAL_MEDIAN_RATIO = 1.06
HIGH_MEDIAN_RATIO = 1.20


@dataclass(frozen=True)
class PriceBaseline:
    baseline_days: int
    sample_size: int
    average: float | None
    median: float | None
    p10: float | None
    p25: float | None
    p75: float | None
    p90: float | None

    def has_enough_history(self, min_history_rows: int) -> bool:
        return self.sample_size >= min_history_rows

    def metadata(self, *, min_history_rows: int) -> dict[str, Any]:
        return {
            "baseline_days": self.baseline_days,
            "baseline_sample_size": self.sample_size,
            "baseline_has_enough_history": self.has_enough_history(min_history_rows),
            "baseline_average_cad": _round_or_none(self.average),
            "baseline_median_cad": _round_or_none(self.median),
            "baseline_p10_cad": _round_or_none(self.p10),
            "baseline_p25_cad": _round_or_none(self.p25),
            "baseline_p75_cad": _round_or_none(self.p75),
            "baseline_p90_cad": _round_or_none(self.p90),
        }


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
    values = sorted(int(price) for price in prices)
    if not values:
        return PriceBaseline(
            baseline_days=baseline_days,
            sample_size=0,
            average=None,
            median=None,
            p10=None,
            p25=None,
            p75=None,
            p90=None,
        )
    return PriceBaseline(
        baseline_days=baseline_days,
        sample_size=len(values),
        average=mean(values),
        median=_percentile(values, 0.50),
        p10=_percentile(values, 0.10),
        p25=_percentile(values, 0.25),
        p75=_percentile(values, 0.75),
        p90=_percentile(values, 0.90),
    )


def cheapest_snapshot_prices_by_category(rows: Iterable[Any]) -> dict[str, list[int]]:
    cheapest_by_scan: dict[tuple[str, datetime], int] = {}
    for row in rows:
        key = (row.category, row.checked_at)
        current = cheapest_by_scan.get(key)
        if current is None or row.price_cad < current:
            cheapest_by_scan[key] = row.price_cad

    output: dict[str, list[int]] = {}
    for category, _checked_at in cheapest_by_scan:
        output.setdefault(category, [])
    for (category, _checked_at), price in cheapest_by_scan.items():
        output[category].append(price)
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
    if price_cad <= baseline.median * EXCELLENT_MEDIAN_RATIO:
        return 10.0
    if price_cad <= baseline.median * GOOD_MEDIAN_RATIO:
        return 8.5
    if price_cad <= baseline.median * NORMAL_MEDIAN_RATIO:
        return 7.0
    if price_cad <= baseline.median * HIGH_MEDIAN_RATIO:
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
    category_metadata: dict[str, Any] = {}

    for category, current_price in current_cheapest_prices.items():
        baseline = build_price_baseline(
            snapshot_prices_by_category.get(category, []),
            baseline_days=baseline_days,
        )
        category_metadata[category] = {
            **baseline.metadata(min_history_rows=min_history_rows),
            "current_cheapest_cad": current_price,
        }
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
                "categories": category_metadata,
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
            "categories": category_metadata,
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


def _percentile(values: list[int], percentile: float) -> float:
    if len(values) == 1:
        return float(values[0])
    position = (len(values) - 1) * percentile
    lower_index = int(position)
    upper_index = min(lower_index + 1, len(values) - 1)
    fraction = position - lower_index
    return round(values[lower_index] + (values[upper_index] - values[lower_index]) * fraction, 6)


def _round_or_none(value: float | None) -> int | None:
    return int(round(value)) if value is not None else None
