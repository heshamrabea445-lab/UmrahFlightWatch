from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Protocol


class ExactSearchMode(StrEnum):
    CHEAPEST = "CHEAPEST"
    TOP_FLIGHTS = "TOP_FLIGHTS"


@dataclass
class NormalizedFlightDeal:
    category: str
    origin: str
    destination: str
    depart_date: date
    return_date: date
    trip_length_days: int
    price_cad: int
    source: str
    airline: str | None = None
    stops: int | None = None
    total_travel_minutes: int | None = None
    layover_summary: str | None = None
    baggage_summary: str | None = None
    google_flights_link: str | None = None
    exact_check_completed: bool = False
    deal_score: float | None = None
    market_label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def dedupe_key(self) -> tuple[str, str, date, date, int, int]:
        return (
            self.origin,
            self.destination,
            self.depart_date,
            self.return_date,
            self.trip_length_days,
            self.price_cad,
        )

    def date_pair_key(self) -> tuple[str, str, date, date, int]:
        return (
            self.origin,
            self.destination,
            self.depart_date,
            self.return_date,
            self.trip_length_days,
        )


@dataclass
class ProviderSearchResponse:
    deals: list[NormalizedFlightDeal]
    raw_results: list[dict[str, Any]] = field(default_factory=list)
    request_count: int = 0
    successful_count: int = 0
    failed_count: int = 0
    error_messages: list[str] = field(default_factory=list)


class FlightProvider(Protocol):
    source: str

    def search_dates_for_category(
        self,
        category: str,
        start_date: date,
        end_date: date,
    ) -> ProviderSearchResponse:
        raise NotImplementedError

    def search_exact_round_trip(
        self,
        depart_date: date,
        return_date: date,
        *,
        mode: ExactSearchMode = ExactSearchMode.CHEAPEST,
        top_n: int = 1,
    ) -> list[NormalizedFlightDeal]:
        raise NotImplementedError

    def normalize_result(self, raw_result: Any, **kwargs: Any) -> NormalizedFlightDeal:
        raise NotImplementedError

    def build_google_flights_link(self, depart_date: date, return_date: date) -> str:
        raise NotImplementedError
