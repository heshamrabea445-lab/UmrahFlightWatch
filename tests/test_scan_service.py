from datetime import date

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import ActiveDeal, Base, PriceHistory
from app.jobs.scan_jobs import FlightScanService
from app.providers.base import NormalizedFlightDeal, ProviderSearchResponse


class FakeProvider:
    source = "fli"

    def __init__(self) -> None:
        self.exact_calls = 0

    def search_dates_for_category(self, category: str, start_date: date, end_date: date):
        deal = NormalizedFlightDeal(
            category=category,
            origin="YYZ",
            destination="JED",
            depart_date=date(2026, 9, 10),
            return_date=date(2026, 9, 17),
            trip_length_days=7,
            price_cad=890,
            stops=1,
            total_travel_minutes=18 * 60,
            google_flights_link="https://example.com",
            source="fli",
        )
        return ProviderSearchResponse(
            deals=[deal],
            raw_results=[{"duration": 7, "results": [{"price": 890}]}],
            request_count=1,
        )

    def search_exact_round_trip(self, depart_date: date, return_date: date):
        self.exact_calls += 1
        return NormalizedFlightDeal(
            category="one_week",
            origin="YYZ",
            destination="JED",
            depart_date=depart_date,
            return_date=return_date,
            trip_length_days=(return_date - depart_date).days,
            price_cad=880,
            airline="Saudia",
            stops=1,
            total_travel_minutes=17 * 60,
            google_flights_link="https://example.com",
            source="fli",
            exact_check_completed=True,
        )

    def normalize_result(self, raw_result, **kwargs):  # pragma: no cover - protocol shim
        raise NotImplementedError

    def build_google_flights_link(self, depart_date: date, return_date: date) -> str:
        return "https://example.com"


class FakeTelegramClient:
    def __init__(self) -> None:
        self.strong_alerts: list[str] = []

    def post_strong_alert_sync(self, text: str, button_text: str, button_url: str) -> int | None:
        self.strong_alerts.append(text)
        return None


def test_scan_flow_writes_history_and_active_deals_without_posting_weak_deal() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    provider = FakeProvider()
    telegram = FakeTelegramClient()
    service = FlightScanService(
        session_factory=session_factory,
        provider=provider,
        telegram_client=telegram,
        dry_run=True,
    )

    service.scan_category("one_week", today=date(2026, 5, 20), respect_pause=False)

    with session_factory() as session:
        assert session.query(PriceHistory).count() == 1
        history = session.query(PriceHistory).one()
        assert history.price_cad == 880
        assert history.exact_check_completed
        assert session.query(ActiveDeal).count() == 2
    assert provider.exact_calls == 1
    assert telegram.strong_alerts == []
