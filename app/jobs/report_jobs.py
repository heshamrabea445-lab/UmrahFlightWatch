from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.locks import release_advisory_lock, try_advisory_lock
from app.db.models import ActiveDeal, Post, PriceHistory
from app.providers.base import NormalizedFlightDeal
from app.services.app_settings import is_paused
from app.services.market_baseline import (
    MIN_HISTORY_ROWS,
    MarketRating,
    calculate_market_rating,
    cheapest_snapshot_prices_by_category,
)
from app.services.report_builder import build_weekly_report
from app.services.telegram_client import TelegramClient
from app.utils.dates import ordered_categories, utc_now

WEEKLY_REPORT_LOCK = "weekly_report"


class ReportJobService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        telegram_client: TelegramClient,
        settings: Settings,
    ) -> None:
        self.session_factory = session_factory
        self.telegram_client = telegram_client
        self.settings = settings

    def post_weekly_report(self, *, respect_pause: bool = True) -> int | None:
        with self.session_factory() as session:
            if not try_advisory_lock(session, WEEKLY_REPORT_LOCK):
                return None
            try:
                if respect_pause and is_paused(session):
                    return None
                now = utc_now()
                fresh_since = now - timedelta(hours=self.settings.report_max_deal_age_hours)
                active = self._active_deals(session, fresh_since=fresh_since)
                market = self._market_rating(session, active, now=now, fresh_since=fresh_since)
                text = build_weekly_report(
                    active,
                    market_label=market.label,
                    market_score=market.score,
                    market_baseline_days=self.settings.market_baseline_days,
                    feedback_form_url=self.settings.feedback_form_url,
                    generated_at=now,
                )
                message_id = self.telegram_client.post_weekly_report(text)
                session.add(
                    Post(
                        post_type="weekly_report",
                        telegram_message_id=message_id,
                        category=None,
                        active_deal_id=None,
                        content_text=text,
                        posted_at=now,
                        status="dry_run" if self.settings.dry_run else "posted",
                        metadata_json={
                            "market_label": market.label,
                            "market_score": market.score,
                        },
                    )
                )
                session.commit()
                return message_id
            finally:
                release_advisory_lock(session, WEEKLY_REPORT_LOCK)

    def build_current_report_text(self) -> str:
        with self.session_factory() as session:
            now = utc_now()
            fresh_since = now - timedelta(hours=self.settings.report_max_deal_age_hours)
            active = self._active_deals(session, fresh_since=fresh_since)
            market = self._market_rating(session, active, now=now, fresh_since=fresh_since)
            return build_weekly_report(
                active,
                market_label=market.label,
                market_score=market.score,
                market_baseline_days=self.settings.market_baseline_days,
                feedback_form_url=self.settings.feedback_form_url,
                generated_at=now,
            )

    def _active_deals(
        self,
        session: Session,
        *,
        fresh_since: datetime,
    ) -> dict[str, dict[str, NormalizedFlightDeal]]:
        output: dict[str, dict[str, NormalizedFlightDeal]] = {
            category: {} for category in ordered_categories()
        }
        rows = session.execute(
            select(ActiveDeal)
            .where(
                ActiveDeal.active.is_(True),
                ActiveDeal.last_seen_at >= fresh_since,
            )
            .order_by(ActiveDeal.category)
        ).scalars()
        for row in rows:
            output.setdefault(row.category, {})[row.deal_type] = _deal_from_active(row)
        return output

    def _market_rating(
        self,
        session: Session,
        active: dict[str, dict[str, NormalizedFlightDeal]],
        *,
        now: datetime,
        fresh_since: datetime,
    ) -> MarketRating:
        current_cheapest_prices = {
            category: deals["cheapest"].price_cad
            for category, deals in active.items()
            if deals.get("cheapest") is not None
        }
        baseline_since = now - timedelta(days=self.settings.market_baseline_days)
        rows = session.execute(
            select(PriceHistory).where(
                PriceHistory.checked_at >= baseline_since,
                PriceHistory.checked_at < fresh_since,
                PriceHistory.exact_check_completed.is_(True),
                PriceHistory.archived_at.is_(None),
            )
        ).scalars()
        snapshot_prices = cheapest_snapshot_prices_by_category(rows)
        return calculate_market_rating(
            current_cheapest_prices,
            snapshot_prices,
            baseline_days=self.settings.market_baseline_days,
            min_history_rows=MIN_HISTORY_ROWS,
        )


def _deal_from_active(row: ActiveDeal) -> NormalizedFlightDeal:
    return NormalizedFlightDeal(
        category=row.category,
        origin=row.origin,
        destination=row.destination,
        depart_date=row.depart_date,
        return_date=row.return_date,
        trip_length_days=row.trip_length_days,
        price_cad=row.price_cad,
        airline=row.airline,
        stops=row.stops,
        total_travel_minutes=row.total_travel_minutes,
        layover_summary=row.layover_summary,
        baggage_summary=row.baggage_summary,
        google_flights_link=row.google_flights_link,
        source=row.source,
        exact_check_completed=row.exact_check_completed,
        deal_score=row.deal_score,
        market_label=row.market_label,
        metadata={**(row.metadata_json or {}), "last_seen_at": row.last_seen_at.isoformat()},
    )
