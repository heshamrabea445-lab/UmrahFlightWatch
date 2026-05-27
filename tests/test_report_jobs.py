from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import Settings
from app.db.models import ActiveDeal, Base, PriceHistory
from app.jobs.report_jobs import ReportJobService


class FakeTelegramClient:
    def __init__(self) -> None:
        self.weekly_reply_markups: list[dict[str, object] | None] = []

    def post_weekly_report(
        self,
        text: str,
        *,
        reply_markup: dict[str, object] | None = None,
    ) -> int | None:
        self.weekly_reply_markups.append(reply_markup)
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


def test_current_deals_hides_stale_active_deals() -> None:
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
            _env_file=None,
            database_url="postgresql+psycopg://u:p@localhost/db",
            report_max_deal_age_hours=2,
        ),
    )

    report = service.build_current_deals_text()

    assert "Latest YYZ &#8594; JED Deals" in report
    assert "$900 CAD" in report
    assert "$800 CAD" not in report
    assert "No fresh exact-confirmed deal found." in report
    assert "checked" in report
    assert "Market:" not in report
    assert "Send Feedback" not in report


def test_current_deals_omits_market_even_with_history() -> None:
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
            _env_file=None,
            database_url="postgresql+psycopg://u:p@localhost/db",
            report_max_deal_age_hours=2,
        ),
    )

    report = service.build_current_deals_text()

    assert "$930 CAD" in report
    assert "Market:" not in report
    assert "exact-search history" not in report


def test_current_deals_omits_market_when_history_is_insufficient() -> None:
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
            _env_file=None,
            database_url="postgresql+psycopg://u:p@localhost/db",
            report_max_deal_age_hours=2,
        ),
    )

    report = service.build_current_deals_text()

    assert "$930 CAD" in report
    assert "Market:" not in report


def test_weekly_report_adds_current_deals_button_when_bot_username_is_set() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    telegram = FakeTelegramClient()
    service = ReportJobService(
        session_factory=session_factory,
        telegram_client=telegram,
        settings=Settings(
            _env_file=None,
            database_url="postgresql+psycopg://u:p@localhost/db",
            telegram_bot_username="@UmrahFlightWatchBot",
        ),
    )

    service.post_weekly_report(respect_pause=False)

    assert telegram.weekly_reply_markups == [
        {
            "inline_keyboard": [
                [
                    {
                        "text": "Get Latest Deals",
                        "url": "https://t.me/UmrahFlightWatchBot?start=current_deals",
                    }
                ]
            ]
        }
    ]


def test_weekly_report_omits_current_deals_button_when_bot_username_is_blank() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine)
    telegram = FakeTelegramClient()
    service = ReportJobService(
        session_factory=session_factory,
        telegram_client=telegram,
        settings=Settings(_env_file=None, database_url="postgresql+psycopg://u:p@localhost/db"),
    )

    service.post_weekly_report(respect_pause=False)

    assert telegram.weekly_reply_markups == [None]
