from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from threading import Lock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.models import ActiveDeal, Base, PriceHistory, ProviderUsage, Scan
from app.jobs.scan_jobs import (
    FlightScanService,
    _provider_safe_scan_day,
    select_discovery_candidates,
)
from app.providers.base import ExactSearchMode, NormalizedFlightDeal, ProviderSearchResponse


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

    def search_exact_round_trip(
        self,
        depart_date: date,
        return_date: date,
        *,
        mode: ExactSearchMode = ExactSearchMode.CHEAPEST,
        top_n: int = 1,
    ):
        self.exact_calls += 1
        return [
            NormalizedFlightDeal(
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
                metadata={"exact_sort_mode": mode.value, "exact_rank": 1},
            )
        ]


def test_provider_safe_scan_day_uses_provider_day_when_local_day_is_behind() -> None:
    assert _provider_safe_scan_day(
        date(2026, 5, 27),
        provider_day=date(2026, 5, 28),
    ) == date(2026, 5, 28)


def test_provider_safe_scan_day_keeps_later_local_day() -> None:
    assert _provider_safe_scan_day(
        date(2026, 5, 29),
        provider_day=date(2026, 5, 28),
    ) == date(2026, 5, 29)


class ExactPriceProvider(FakeProvider):
    def __init__(
        self,
        price: int,
        *,
        minutes: int = 17 * 60,
        airline: str | None = "Saudia",
        stops: int | None = 1,
    ) -> None:
        super().__init__()
        self.price = price
        self.minutes = minutes
        self.airline = airline
        self.stops = stops

    def search_exact_round_trip(
        self,
        depart_date: date,
        return_date: date,
        *,
        mode: ExactSearchMode = ExactSearchMode.CHEAPEST,
        top_n: int = 1,
    ):
        self.exact_calls += 1
        return [
            NormalizedFlightDeal(
                category="one_week",
                origin="YYZ",
                destination="JED",
                depart_date=depart_date,
                return_date=return_date,
                trip_length_days=(return_date - depart_date).days,
                price_cad=self.price,
                airline=self.airline,
                stops=self.stops,
                total_travel_minutes=self.minutes,
                google_flights_link="https://example.com",
                source="fli",
                exact_check_completed=True,
                metadata={"exact_sort_mode": mode.value, "exact_rank": 1},
            )
        ]


class TopFlightProvider(FakeProvider):
    def search_exact_round_trip(
        self,
        depart_date: date,
        return_date: date,
        *,
        mode: ExactSearchMode = ExactSearchMode.CHEAPEST,
        top_n: int = 1,
    ):
        self.exact_calls += 1
        price = 850 if mode == ExactSearchMode.CHEAPEST else 950
        stops = 2 if mode == ExactSearchMode.CHEAPEST else 0
        minutes = 30 * 60 if mode == ExactSearchMode.CHEAPEST else 14 * 60
        return [
            NormalizedFlightDeal(
                category="one_week",
                origin="YYZ",
                destination="JED",
                depart_date=depart_date,
                return_date=return_date,
                trip_length_days=(return_date - depart_date).days,
                price_cad=price,
                airline="Saudia",
                stops=stops,
                total_travel_minutes=minutes,
                google_flights_link="https://example.com",
                source="fli",
                exact_check_completed=True,
                metadata={"exact_sort_mode": mode.value, "exact_rank": 1},
            )
        ]


class OverpricedTopFlightProvider(FakeProvider):
    def search_exact_round_trip(
        self,
        depart_date: date,
        return_date: date,
        *,
        mode: ExactSearchMode = ExactSearchMode.CHEAPEST,
        top_n: int = 1,
    ):
        self.exact_calls += 1
        price = 850 if mode == ExactSearchMode.CHEAPEST else 1400
        return [
            NormalizedFlightDeal(
                category="one_week",
                origin="YYZ",
                destination="JED",
                depart_date=depart_date,
                return_date=return_date,
                trip_length_days=(return_date - depart_date).days,
                price_cad=price,
                airline="Saudia",
                stops=0,
                total_travel_minutes=14 * 60,
                google_flights_link="https://example.com",
                source="fli",
                exact_check_completed=True,
                metadata={"exact_sort_mode": mode.value, "exact_rank": 1},
            )
        ]


class TopFlightFailureProvider(FakeProvider):
    def search_exact_round_trip(
        self,
        depart_date: date,
        return_date: date,
        *,
        mode: ExactSearchMode = ExactSearchMode.CHEAPEST,
        top_n: int = 1,
    ):
        if mode == ExactSearchMode.TOP_FLIGHTS:
            self.exact_calls += 1
            return []
        return super().search_exact_round_trip(
            depart_date,
            return_date,
            mode=mode,
            top_n=top_n,
        )


class FakeTelegramClient:
    def __init__(self) -> None:
        self.strong_alerts: list[str] = []

    def post_strong_alert(self, text: str, button_text: str, button_url: str) -> int | None:
        self.strong_alerts.append(text)
        return None


def make_calendar_deal(
    price: int,
    depart_day: int,
    *,
    category: str = "one_week",
) -> NormalizedFlightDeal:
    return NormalizedFlightDeal(
        category=category,
        origin="YYZ",
        destination="JED",
        depart_date=date(2026, 9, depart_day),
        return_date=date(2026, 9, depart_day + 7),
        trip_length_days=7,
        price_cad=price,
        google_flights_link="https://example.com",
        source="fli",
    )


class ManyDealProvider:
    source = "fli"

    def __init__(self) -> None:
        self.exact_calls: list[tuple[date, date, ExactSearchMode]] = []
        self._lock = Lock()

    def search_dates_for_category(self, category: str, start_date: date, end_date: date):
        deals = [
            make_calendar_deal(1000 + index, index + 1, category=category) for index in range(20)
        ]
        return ProviderSearchResponse(
            deals=deals,
            raw_results=[{"duration": 7, "results": [{"price": deal.price_cad} for deal in deals]}],
            request_count=1,
        )

    def search_exact_round_trip(
        self,
        depart_date: date,
        return_date: date,
        *,
        mode: ExactSearchMode = ExactSearchMode.CHEAPEST,
        top_n: int = 1,
    ):
        with self._lock:
            self.exact_calls.append((depart_date, return_date, mode))
        price = 900 + depart_date.day
        if mode == ExactSearchMode.TOP_FLIGHTS:
            price += 25
        return [
            NormalizedFlightDeal(
                category="one_week",
                origin="YYZ",
                destination="JED",
                depart_date=depart_date,
                return_date=return_date,
                trip_length_days=(return_date - depart_date).days,
                price_cad=price,
                airline="Saudia",
                stops=1 if mode == ExactSearchMode.CHEAPEST else 0,
                total_travel_minutes=17 * 60 if mode == ExactSearchMode.CHEAPEST else 14 * 60,
                google_flights_link="https://example.com",
                source="fli",
                exact_check_completed=True,
                metadata={"exact_sort_mode": mode.value, "exact_rank": 1},
            )
        ]


class FailingCategoryProvider(ManyDealProvider):
    def search_dates_for_category(self, category: str, start_date: date, end_date: date):
        if category == "two_week":
            raise RuntimeError("two_week provider failure")
        return super().search_dates_for_category(category, start_date, end_date)


class ExactRaisingProvider(ManyDealProvider):
    def search_exact_round_trip(
        self,
        depart_date: date,
        return_date: date,
        *,
        mode: ExactSearchMode = ExactSearchMode.CHEAPEST,
        top_n: int = 1,
    ):
        if mode == ExactSearchMode.TOP_FLIGHTS:
            with self._lock:
                self.exact_calls.append((depart_date, return_date, mode))
            raise RuntimeError("top flights exact failure")
        return super().search_exact_round_trip(
            depart_date,
            return_date,
            mode=mode,
            top_n=top_n,
        )


def make_file_session_factory(path: Path):
    engine = create_engine(
        f"sqlite+pysqlite:///{path}",
        connect_args={"check_same_thread": False, "timeout": 30},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def seed_price_history(
    session_factory,
    prices: list[int],
    *,
    category: str = "one_week",
) -> None:
    checked_at = datetime.now(UTC) - timedelta(days=1)
    with session_factory() as session:
        for index, price in enumerate(prices):
            session.add(
                PriceHistory(
                    source="fli",
                    category=category,
                    origin="YYZ",
                    destination="JED",
                    depart_date=date(2026, 9, 1),
                    return_date=date(2026, 9, 8),
                    trip_length_days=7,
                    price_cad=price,
                    exact_check_completed=True,
                    checked_at=checked_at - timedelta(hours=index),
                    metadata_json={},
                )
            )
        session.commit()


def seed_price_history_snapshots(
    session_factory,
    prices_by_scan: list[list[int]],
    *,
    category: str = "one_week",
) -> datetime:
    checked_at = datetime.now(UTC) - timedelta(days=1)
    with session_factory() as session:
        for scan_index, prices in enumerate(prices_by_scan):
            scan_checked_at = checked_at - timedelta(hours=scan_index)
            for price in prices:
                session.add(
                    PriceHistory(
                        source="fli",
                        category=category,
                        origin="YYZ",
                        destination="JED",
                        depart_date=date(2026, 9, 1),
                        return_date=date(2026, 9, 8),
                        trip_length_days=7,
                        price_cad=price,
                        exact_check_completed=True,
                        checked_at=scan_checked_at,
                        metadata_json={},
                    )
                )
        session.commit()
    return checked_at


def test_select_discovery_candidates_keeps_top_unique_prices() -> None:
    deals = [make_calendar_deal(1200, 1), make_calendar_deal(900, 2)]
    duplicate = make_calendar_deal(850, 2)
    deals.append(duplicate)

    selected = select_discovery_candidates(deals, 2)

    assert [deal.price_cad for deal in selected] == [850, 1200]
    assert len({deal.date_pair_key() for deal in selected}) == 2


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
    assert provider.exact_calls == 2
    assert telegram.strong_alerts == []


def test_scan_flow_alerts_from_baseline_median_without_requiring_high_deal_score() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    seed_price_history(session_factory, [1400] * 20)
    provider = ExactPriceProvider(900, minutes=40 * 60)
    telegram = FakeTelegramClient()
    service = FlightScanService(
        session_factory=session_factory,
        provider=provider,
        telegram_client=telegram,
        dry_run=True,
        settings=Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            exact_search_delay_seconds=0,
        ),
    )

    service.scan_category("one_week", today=date(2026, 5, 20), respect_pause=False)

    with session_factory() as session:
        cheapest = session.query(ActiveDeal).filter_by(deal_type="cheapest").one()
        assert cheapest.price_cad == 900
        assert cheapest.deal_score is not None
        assert cheapest.deal_score < 9.0
        assert cheapest.metadata_json["baseline_median_cad"] == 1400
    assert len(telegram.strong_alerts) == 2


def test_category_fare_baseline_uses_cheapest_snapshot_per_scan() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    before = seed_price_history_snapshots(session_factory, [[1500, 1000]] * 20)
    service = FlightScanService(
        session_factory=session_factory,
        provider=FakeProvider(),
        telegram_client=FakeTelegramClient(),
        dry_run=True,
    )

    with session_factory() as session:
        baseline = service._category_fare_baseline(
            session,
            "one_week",
            before=before + timedelta(minutes=1),
        )

    assert baseline.sample_size == 20
    assert baseline.median == 1000


def test_scan_flow_uses_top_flights_for_best_overall_when_reasonably_priced() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    service = FlightScanService(
        session_factory=session_factory,
        provider=TopFlightProvider(),
        telegram_client=FakeTelegramClient(),
        dry_run=True,
        settings=Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            exact_search_delay_seconds=0,
        ),
    )

    service.scan_category("one_week", today=date(2026, 5, 20), respect_pause=False)

    with session_factory() as session:
        best = session.query(ActiveDeal).filter_by(deal_type="best_value").one()
        cheapest = session.query(ActiveDeal).filter_by(deal_type="cheapest").one()
        assert cheapest.price_cad == 850
        assert best.price_cad == 950
        assert best.metadata_json["exact_sort_mode"] == "TOP_FLIGHTS"
        assert best.metadata_json["flight_quality_label"] == "Excellent"


def test_scan_flow_blocks_overpriced_top_flight_best_overall() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    service = FlightScanService(
        session_factory=session_factory,
        provider=OverpricedTopFlightProvider(),
        telegram_client=FakeTelegramClient(),
        dry_run=True,
        settings=Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            exact_search_delay_seconds=0,
        ),
    )

    service.scan_category("one_week", today=date(2026, 5, 20), respect_pause=False)

    with session_factory() as session:
        best = session.query(ActiveDeal).filter_by(deal_type="best_value").one()
        assert best.price_cad == 850
        assert best.metadata_json["exact_sort_mode"] == "CHEAPEST"


def test_top_flights_exact_failure_does_not_fail_category_scan() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    service = FlightScanService(
        session_factory=session_factory,
        provider=TopFlightFailureProvider(),
        telegram_client=FakeTelegramClient(),
        dry_run=True,
        settings=Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            exact_search_delay_seconds=0,
        ),
    )

    service.scan_category("one_week", today=date(2026, 5, 20), respect_pause=False)

    with session_factory() as session:
        scan = session.query(Scan).one()
        assert scan.status == "success"
        assert scan.metadata_json["exact_failed_count"] == 1
        assert session.query(PriceHistory).count() == 1


def test_discovery_exact_checks_configured_top_candidates() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    provider = ManyDealProvider()
    service = FlightScanService(
        session_factory=session_factory,
        provider=provider,
        telegram_client=FakeTelegramClient(),
        dry_run=True,
        settings=Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            discovery_candidates_per_category=10,
            exact_search_delay_seconds=0,
        ),
    )

    service.scan_category("one_week", today=date(2026, 5, 20), respect_pause=False)

    with session_factory() as session:
        assert session.query(PriceHistory).count() == 20
        assert session.query(ActiveDeal).filter_by(active=True).count() == 2
    assert len(provider.exact_calls) == 20


def test_scan_all_categories_runs_each_category_with_own_scan_row(tmp_path: Path) -> None:
    session_factory = make_file_session_factory(tmp_path / "scan_all.db")
    provider = ManyDealProvider()
    service = FlightScanService(
        session_factory=session_factory,
        provider=provider,
        telegram_client=FakeTelegramClient(),
        dry_run=True,
        settings=Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            discovery_candidates_per_category=10,
            discovery_category_workers=3,
            exact_search_delay_seconds=0,
        ),
    )

    service.scan_all_categories(today=date(2026, 5, 20), respect_pause=False)

    with session_factory() as session:
        scans = session.query(Scan).all()
        assert {scan.category for scan in scans} == {"one_week", "two_week", "one_month"}
        assert {scan.status for scan in scans} == {"success"}
        assert session.query(PriceHistory).count() == 60
        assert session.query(ActiveDeal).filter_by(active=True).count() == 6
        usage = session.query(ProviderUsage).one()
        assert usage.request_count == 63
        for scan in scans:
            assert scan.metadata_json["candidate_count"] == 10
            assert scan.metadata_json["exact_request_count"] == 20
            assert scan.metadata_json["exact_success_count"] == 20
            assert scan.metadata_json["exact_deduped_count"] == 20
            assert "calendar_seconds" in scan.metadata_json
            assert "exact_seconds" in scan.metadata_json
            assert "total_seconds" in scan.metadata_json
    assert len(provider.exact_calls) == 60


def test_scan_all_categories_raises_after_other_categories_finish(tmp_path: Path) -> None:
    session_factory = make_file_session_factory(tmp_path / "scan_all_failure.db")
    provider = FailingCategoryProvider()
    service = FlightScanService(
        session_factory=session_factory,
        provider=provider,
        telegram_client=FakeTelegramClient(),
        dry_run=True,
        settings=Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            discovery_candidates_per_category=10,
            discovery_category_workers=3,
            exact_search_delay_seconds=0,
        ),
    )

    with pytest.raises(RuntimeError, match="two_week"):
        service.scan_all_categories(today=date(2026, 5, 20), respect_pause=False)

    with session_factory() as session:
        scans = {scan.category: scan for scan in session.query(Scan).all()}
        assert scans["one_week"].status == "success"
        assert scans["two_week"].status == "failed"
        assert scans["one_month"].status == "success"
        assert session.query(PriceHistory).count() == 40
        assert session.query(ActiveDeal).filter_by(active=True).count() == 4
