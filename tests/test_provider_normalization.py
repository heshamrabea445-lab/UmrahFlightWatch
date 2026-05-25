from datetime import date, datetime
from enum import Enum
from types import SimpleNamespace

from app.config import Settings
from app.providers.base import ExactSearchMode
from app.providers.fli_provider import FliProvider, _fli_sort_by


def test_fli_date_price_normalization_handles_calendar_result() -> None:
    provider = FliProvider(settings=Settings(database_url="postgresql+psycopg://u:p@localhost/db"))
    raw = SimpleNamespace(
        date=(datetime(2026, 9, 10), datetime(2026, 9, 17)),
        price=890.49,
        currency="CAD",
    )

    deal = provider.normalize_calendar_result(raw, category="one_week")

    assert deal.origin == "YYZ"
    assert deal.destination == "JED"
    assert deal.depart_date.isoformat() == "2026-09-10"
    assert deal.return_date.isoformat() == "2026-09-17"
    assert deal.trip_length_days == 7
    assert deal.price_cad == 890
    assert deal.airline is None


def test_fli_exact_result_normalization_uses_available_fields_without_crashing() -> None:
    provider = FliProvider(settings=Settings(database_url="postgresql+psycopg://u:p@localhost/db"))
    leg = SimpleNamespace(
        airline=SimpleNamespace(name="_SV"),
        departure_airport=SimpleNamespace(name="YYZ"),
        arrival_airport=SimpleNamespace(name="JED"),
    )
    raw = SimpleNamespace(
        legs=[leg],
        price=950,
        currency="CAD",
        duration=18 * 60 + 40,
        stops=1,
        layovers=None,
        primary_airline_name="Saudia",
    )

    deal = provider.normalize_exact_result(
        raw,
        category="two_week",
        depart_date=datetime(2026, 9, 12).date(),
        return_date=datetime(2026, 9, 27).date(),
    )

    assert deal.price_cad == 950
    assert deal.airline == "Saudia"
    assert deal.stops == 1
    assert deal.total_travel_minutes == 1120
    assert deal.layover_summary is None


def test_fli_exact_sort_mode_maps_to_provider_enum() -> None:
    class SortByStub(Enum):
        CHEAPEST = "cheapest-sort"
        TOP_FLIGHTS = "top-flights-sort"

    assert _fli_sort_by(SortByStub, ExactSearchMode.CHEAPEST) == SortByStub.CHEAPEST
    assert _fli_sort_by(SortByStub, ExactSearchMode.TOP_FLIGHTS) == SortByStub.TOP_FLIGHTS


def test_fli_exact_search_returns_ranked_results_with_metadata() -> None:
    provider = FliProvider(settings=Settings(database_url="postgresql+psycopg://u:p@localhost/db"))
    raw_results = [
        SimpleNamespace(
            legs=[],
            price=950,
            currency="CAD",
            duration=18 * 60,
            stops=1,
            layovers=None,
            primary_airline_name="Saudia",
        ),
        SimpleNamespace(
            legs=[],
            price=990,
            currency="CAD",
            duration=14 * 60,
            stops=0,
            layovers=None,
            primary_airline_name="Saudia",
        ),
    ]
    provider._search_exact = lambda depart, ret, mode, top_n: raw_results

    deals, error = provider._search_fli_exact_deals(
        date(2026, 9, 12),
        date(2026, 9, 27),
        ExactSearchMode.TOP_FLIGHTS,
        2,
    )

    assert error is None
    assert [deal.price_cad for deal in deals] == [950, 990]
    assert deals[0].metadata["exact_sort_mode"] == "TOP_FLIGHTS"
    assert deals[0].metadata["exact_rank"] == 1
    assert deals[1].metadata["exact_rank"] == 2
