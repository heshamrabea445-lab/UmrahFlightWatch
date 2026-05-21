from datetime import datetime
from types import SimpleNamespace

from app.config import Settings
from app.providers.fli_provider import FliProvider


def test_fli_date_price_normalization_handles_calendar_result() -> None:
    provider = FliProvider(settings=Settings(database_url="postgresql+psycopg://u:p@localhost/db"))
    raw = SimpleNamespace(
        date=(datetime(2026, 9, 10), datetime(2026, 9, 17)),
        price=890.49,
        currency="CAD",
    )

    deal = provider.normalize_result(raw, category="one_week")

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

    deal = provider.normalize_result(
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
