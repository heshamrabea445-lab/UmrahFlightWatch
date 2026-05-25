from __future__ import annotations

import logging
import time
from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timedelta
from typing import Any

from app.config import Settings
from app.providers.base import ExactSearchMode, NormalizedFlightDeal, ProviderSearchResponse
from app.services.link_builder import DESTINATION, ORIGIN, build_google_flights_link
from app.utils.dates import category_durations
from app.utils.formatting import format_minutes

logger = logging.getLogger(__name__)


class FliProvider:
    source = "fli"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def search_dates_for_category(
        self,
        category: str,
        start_date: date,
        end_date: date,
    ) -> ProviderSearchResponse:
        deals: list[NormalizedFlightDeal] = []
        raw_results: list[dict[str, Any]] = []
        request_count = 0
        successful_count = 0
        failed_count = 0

        for index, duration in enumerate(category_durations(category)):
            if index > 0 and self.settings.fli_request_delay_seconds > 0:
                time.sleep(self.settings.fli_request_delay_seconds)

            duration_started = time.perf_counter()
            result, attempts, error = self._retry_call(
                lambda duration=duration: self._search_dates_duration(
                    start_date,
                    end_date,
                    duration,
                )
            )
            duration_seconds = _elapsed_seconds(duration_started)
            request_count += attempts
            if error:
                failed_count += 1
                logger.error(
                    "fli search_dates failed category=%s duration=%s start_date=%s "
                    "end_date=%s duration_seconds=%s error=%s",
                    category,
                    duration,
                    start_date,
                    end_date,
                    duration_seconds,
                    error,
                )
                continue

            successful_count += 1
            raw_list = result or []
            normalized_for_duration: list[NormalizedFlightDeal] = []
            for raw in raw_list:
                try:
                    normalized_for_duration.append(self.normalize_result(raw, category=category))
                except ValueError as exc:
                    logger.warning("Skipping fli date result that cannot normalize: %s", exc)
            deals.extend(normalized_for_duration)
            cheapest = min(normalized_for_duration, key=lambda item: item.price_cad, default=None)
            raw_results.append(
                {
                    "duration": duration,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "duration_seconds": duration_seconds,
                    "result_count": len(normalized_for_duration),
                    "cheapest_price": cheapest.price_cad if cheapest else None,
                    "cheapest_date_pair": (
                        {
                            "depart_date": cheapest.depart_date.isoformat(),
                            "return_date": cheapest.return_date.isoformat(),
                        }
                        if cheapest
                        else None
                    ),
                    "results": [self._serialize_raw(raw) for raw in raw_list],
                }
            )
            logger.info(
                "fli category scan category=%s duration=%s start_date=%s end_date=%s "
                "duration_seconds=%s results=%s cheapest_price=%s cheapest_date_pair=%s",
                category,
                duration,
                start_date,
                end_date,
                duration_seconds,
                len(normalized_for_duration),
                cheapest.price_cad if cheapest else None,
                (
                    f"{cheapest.depart_date.isoformat()}->{cheapest.return_date.isoformat()}"
                    if cheapest
                    else None
                ),
            )

        return ProviderSearchResponse(
            deals=deals,
            raw_results=raw_results,
            request_count=request_count,
            successful_count=successful_count,
            failed_count=failed_count,
        )

    def search_exact_round_trip(
        self,
        depart_date: date,
        return_date: date,
        *,
        mode: ExactSearchMode = ExactSearchMode.CHEAPEST,
        top_n: int = 1,
    ) -> list[NormalizedFlightDeal]:
        deals, _error = self._search_fli_exact_deals(depart_date, return_date, mode, top_n)
        return deals

    def normalize_result(self, raw_result: Any, **kwargs: Any) -> NormalizedFlightDeal:
        category = kwargs.get("category", "")
        if hasattr(raw_result, "date") and hasattr(raw_result, "price"):
            return self._normalize_date_price(raw_result, category=category)
        return self._normalize_exact_result(raw_result, **kwargs)

    def build_google_flights_link(self, depart_date: date, return_date: date) -> str:
        return build_google_flights_link(depart_date, return_date)

    def _search_fli_exact_deals(
        self,
        depart_date: date,
        return_date: date,
        mode: ExactSearchMode,
        top_n: int,
    ) -> tuple[list[NormalizedFlightDeal], str | None]:
        result, _attempts, error = self._retry_call(
            lambda: self._search_exact(depart_date, return_date, mode, top_n)
        )
        if error or not result:
            logger.warning(
                "fli exact-date confirmation failed depart_date=%s return_date=%s mode=%s error=%s",
                depart_date,
                return_date,
                mode.value,
                error,
            )
            return [], error

        deals: list[NormalizedFlightDeal] = []
        result_limit = max(1, top_n)
        for rank, raw in enumerate(result[:result_limit], start=1):
            try:
                deal = self.normalize_result(
                    raw,
                    depart_date=depart_date,
                    return_date=return_date,
                )
                deal.exact_check_completed = True
                deal.metadata["exact_sort_mode"] = mode.value
                deal.metadata["exact_rank"] = rank
                logger.info(
                    "fli exact-date confirmation succeeded depart_date=%s return_date=%s "
                    "mode=%s rank=%s price=%s",
                    depart_date,
                    return_date,
                    mode.value,
                    rank,
                    deal.price_cad,
                )
                deals.append(deal)
            except ValueError as exc:
                logger.warning("Skipping fli exact result that cannot normalize: %s", exc)
        if not deals:
            return [], "fli exact result did not include a normalizable fare"
        return deals, None

    def _search_dates_duration(
        self,
        start_date: date,
        end_date: date,
        duration: int,
    ) -> list[Any] | None:
        from fli.models import (
            Airport,
            DateSearchFilters,
            FlightSegment,
            PassengerInfo,
            SeatType,
            TripType,
        )
        from fli.search import SearchDates

        filters = DateSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[
                FlightSegment(
                    departure_airport=[[Airport.YYZ, 0]],
                    arrival_airport=[[Airport.JED, 0]],
                    travel_date=start_date.isoformat(),
                ),
                FlightSegment(
                    departure_airport=[[Airport.JED, 0]],
                    arrival_airport=[[Airport.YYZ, 0]],
                    travel_date=(start_date + timedelta(days=duration)).isoformat(),
                ),
            ],
            from_date=start_date.isoformat(),
            to_date=end_date.isoformat(),
            duration=duration,
            seat_type=SeatType.ECONOMY,
        )
        search = SearchDates()
        return search.search(filters)

    def _search_exact(
        self,
        depart_date: date,
        return_date: date,
        mode: ExactSearchMode,
        top_n: int,
    ) -> list[Any] | None:
        from fli.models import (
            Airport,
            FlightSearchFilters,
            FlightSegment,
            PassengerInfo,
            SeatType,
            SortBy,
            TripType,
        )
        from fli.search import SearchFlights

        filters = FlightSearchFilters(
            trip_type=TripType.ROUND_TRIP,
            passenger_info=PassengerInfo(adults=1),
            flight_segments=[
                FlightSegment(
                    departure_airport=[[Airport.YYZ, 0]],
                    arrival_airport=[[Airport.JED, 0]],
                    travel_date=depart_date.isoformat(),
                ),
                FlightSegment(
                    departure_airport=[[Airport.JED, 0]],
                    arrival_airport=[[Airport.YYZ, 0]],
                    travel_date=return_date.isoformat(),
                ),
            ],
            seat_type=SeatType.ECONOMY,
            sort_by=_fli_sort_by(SortBy, mode),
        )
        search = SearchFlights()
        return search.search(filters, top_n=max(1, top_n))

    def _retry_call(self, func: Any) -> tuple[Any, int, str | None]:
        attempts = 0
        last_error: str | None = None
        for attempt in range(self.settings.fli_max_retries + 1):
            attempts = attempt + 1
            try:
                return func(), attempts, None
            except Exception as exc:  # noqa: BLE001 - provider boundary must contain fli errors.
                last_error = str(exc)
                if attempt < self.settings.fli_max_retries:
                    time.sleep(self.settings.fli_request_delay_seconds)
        return None, attempts, last_error

    def _normalize_date_price(self, raw_result: Any, *, category: str) -> NormalizedFlightDeal:
        dates = getattr(raw_result, "date", None)
        if not dates or len(dates) != 2:
            raise ValueError("fli date search result did not include depart and return dates")
        depart_date = _coerce_date(dates[0])
        return_date = _coerce_date(dates[1])
        price = _coerce_price(getattr(raw_result, "price", None))
        return NormalizedFlightDeal(
            category=category,
            origin=ORIGIN,
            destination=DESTINATION,
            depart_date=depart_date,
            return_date=return_date,
            trip_length_days=(return_date - depart_date).days,
            price_cad=price,
            google_flights_link=self.build_google_flights_link(depart_date, return_date),
            source=self.source,
            metadata={
                "raw_currency": getattr(raw_result, "currency", None),
                "result_type": "dates",
            },
        )

    def _normalize_exact_result(self, raw_result: Any, **kwargs: Any) -> NormalizedFlightDeal:
        depart_date = kwargs.get("depart_date")
        return_date = kwargs.get("return_date")
        if depart_date is None or return_date is None:
            raise ValueError("exact fli result normalization requires depart_date and return_date")
        segments = list(raw_result) if isinstance(raw_result, tuple) else [raw_result]
        price = _extract_price(segments)
        if price is None:
            raise ValueError("exact fli result did not include price")

        durations = [getattr(segment, "duration", None) for segment in segments]
        known_durations = [duration for duration in durations if isinstance(duration, int)]
        stops = _sum_optional_int(getattr(segment, "stops", None) for segment in segments)
        return NormalizedFlightDeal(
            category=kwargs.get("category", ""),
            origin=ORIGIN,
            destination=DESTINATION,
            depart_date=depart_date,
            return_date=return_date,
            trip_length_days=(return_date - depart_date).days,
            price_cad=_coerce_price(price),
            airline=_extract_airline(segments),
            stops=stops,
            total_travel_minutes=max(known_durations) if known_durations else None,
            layover_summary=_extract_layover_summary(segments),
            baggage_summary=None,
            google_flights_link=self.build_google_flights_link(depart_date, return_date),
            source=self.source,
            exact_check_completed=True,
            metadata={"result_type": "exact"},
        )

    def _serialize_raw(self, raw: Any) -> Any:
        if hasattr(raw, "model_dump"):
            return raw.model_dump(mode="json")
        if is_dataclass(raw):
            return asdict(raw)
        if isinstance(raw, dict | list | str | int | float | bool | type(None)):
            return raw
        return repr(raw)


def _elapsed_seconds(started_at: float) -> float:
    return round(time.perf_counter() - started_at, 3)


def _fli_sort_by(sort_by_type: Any, mode: ExactSearchMode) -> Any:
    return sort_by_type[mode.value]


def _coerce_date(value: Any) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return datetime.strptime(value, "%Y-%m-%d").date()
    raise ValueError(f"Cannot parse date value: {value!r}")


def _coerce_price(value: Any) -> int:
    if value is None:
        raise ValueError("Missing flight price")
    return int(round(float(value)))


def _extract_price(segments: list[Any]) -> Any:
    for segment in reversed(segments):
        price = getattr(segment, "price", None)
        if price is not None:
            return price
    return None


def _sum_optional_int(values: Any) -> int | None:
    total = 0
    found = False
    for value in values:
        if value is None:
            continue
        total += int(value)
        found = True
    return total if found else None


def _extract_airline(segments: list[Any]) -> str | None:
    for segment in segments:
        primary = getattr(segment, "primary_airline_name", None)
        if primary:
            return str(primary)
    for segment in segments:
        for leg in getattr(segment, "legs", []) or []:
            airline = getattr(leg, "airline", None)
            name = getattr(airline, "value", None) or getattr(airline, "name", None)
            if name:
                return str(name).removeprefix("_")
    return None


def _extract_layover_summary(segments: list[Any]) -> str | None:
    summaries: list[str] = []
    for segment in segments:
        for layover in getattr(segment, "layovers", None) or []:
            airport = getattr(getattr(layover, "airport", None), "name", None)
            duration = format_minutes(getattr(layover, "duration", None))
            parts = [part for part in [duration, f"in {airport}" if airport else None] if part]
            if getattr(layover, "overnight", False):
                parts.append("overnight")
            if getattr(layover, "change_of_airport", False):
                parts.append("airport change")
            if parts:
                summaries.append(" ".join(parts))
    return "; ".join(summaries) if summaries else None
