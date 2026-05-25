from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.models import ActiveDeal, Base, PriceHistory
from app.jobs.report_jobs import ReportJobService


class FakeTelegramClient:
    def post_weekly_report_sync(self, text: str) -> int | None:
        return None


def make_active_deal(
    *,
    category: str,
    deal_type: str,
    price: int,
    last_seen_at: datetime,
) -> ActiveDeal:
    return ActiveDeal(
        category=category,
        deal_type=deal_type,
        origin="YYZ",
        destination="JED",
        depart_date=date(2026, 6, 3),
        return_date=date(2026, 6, 10),
        trip_length_days=7,
        price_cad=price,
        airline="Etihad Airways",
        stops=2,
        total_travel_minutes=2055,
        google_flights_link="https://example.com",
        source="fli",
        exact_check_completed=True,
        deal_score=8.3,
        active=True,
        first_seen_at=last_seen_at,
        last_seen_at=last_seen_at,
        metadata_json={
            "deal_type": deal_type,
            "fare_label": "Good",
            "flight_quality_label": "Normal",
        },
    )


def make_price_history(
    *,
    category: str,
    price: int,
    checked_at: datetime,
) -> PriceHistory:
    return PriceHistory(
        category=category,
        source="fli",
        origin="YYZ",
        destination="JED",
        depart_date=date(2026, 6, 3),
        return_date=date(2026, 6, 10),
        trip_length_days=7,
        price_cad=price,
        airline="Etihad Airways",
        stops=2,
        total_travel_minutes=2055,
        exact_check_completed=True,
        checked_at=checked_at,
        metadata_json={},
    )


def test_current_report_hides_stale_active_deals() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    now = datetime.now(UTC)
    with session_factory() as session:
        session.add(
            make_active_deal(
                category="one_week",
                deal_type="cheapest",
                price=900,
                last_seen_at=now - timedelta(minutes=30),
            )
        )
        session.add(
            make_active_deal(
                category="two_week",
                deal_type="cheapest",
                price=800,
                last_seen_at=now - timedelta(hours=3),
            )
        )
        session.commit()
    service = ReportJobService(
        session_factory=session_factory,
        telegram_client=FakeTelegramClient(),
        settings=Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            report_max_deal_age_hours=2,
        ),
    )

    report = service.build_current_report_text()

    assert "$900 CAD" in report
    assert "$800 CAD" not in report
    assert "No fresh exact-confirmed deal found." in report
    assert "checked" in report


def test_current_report_market_uses_90_day_history_snapshots() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    now = datetime.now(UTC)
    with session_factory() as session:
        session.add(
            make_active_deal(
                category="one_week",
                deal_type="cheapest",
                price=930,
                last_seen_at=now - timedelta(minutes=30),
            )
        )
        for index, price in enumerate([900, 950, 1000, 1050, 1100] * 4):
            session.add(
                make_price_history(
                    category="one_week",
                    price=price,
                    checked_at=now - timedelta(days=30, minutes=index),
                )
            )
        session.commit()
    service = ReportJobService(
        session_factory=session_factory,
        telegram_client=FakeTelegramClient(),
        settings=Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            report_max_deal_age_hours=2,
            market_min_history_rows=20,
        ),
    )

    report = service.build_current_report_text()

    assert "Market: Good buying window -- 8.5/10" in report
    assert "based on 90-day exact-search history" in report


def test_current_report_market_honors_insufficient_history() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    now = datetime.now(UTC)
    with session_factory() as session:
        session.add(
            make_active_deal(
                category="one_week",
                deal_type="cheapest",
                price=930,
                last_seen_at=now - timedelta(minutes=30),
            )
        )
        session.add(
            make_price_history(
                category="one_week",
                price=900,
                checked_at=now - timedelta(days=30),
            )
        )
        session.commit()
    service = ReportJobService(
        session_factory=session_factory,
        telegram_client=FakeTelegramClient(),
        settings=Settings(
            database_url="postgresql+psycopg://u:p@localhost/db",
            report_max_deal_age_hours=2,
            market_min_history_rows=20,
        ),
    )

    report = service.build_current_report_text()

    assert "Market: Not enough 90-day exact-search history" in report
