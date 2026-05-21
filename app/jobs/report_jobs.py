from __future__ import annotations

from typing import Any

from sqlalchemy import select

from app.config import Settings
from app.db.locks import release_advisory_lock, try_advisory_lock
from app.db.models import ActiveDeal, Post, PriceHistory
from app.providers.base import NormalizedFlightDeal
from app.services.app_settings import is_paused
from app.services.deal_scoring import calculate_market_rating
from app.services.report_builder import build_weekly_report
from app.services.telegram_client import TelegramClient
from app.utils.dates import ordered_categories, utc_now


class ReportJobService:
    def __init__(
        self,
        *,
        session_factory: Any,
        telegram_client: TelegramClient,
        settings: Settings,
    ) -> None:
        self.session_factory = session_factory
        self.telegram_client = telegram_client
        self.settings = settings

    def post_weekly_report(self, *, respect_pause: bool = True) -> int | None:
        with self.session_factory() as session:
            lock_name = "weekly_report"
            if not try_advisory_lock(session, lock_name):
                return None
            try:
                if respect_pause and is_paused(session):
                    return None
                active = self._active_deals(session)
                historical_deals = [
                    _deal_from_price_history(row)
                    for row in session.execute(
                        select(PriceHistory).where(PriceHistory.archived_at.is_(None))
                    ).scalars()
                ]
                active_deal_list = [deal for deals in active.values() for deal in deals.values()]
                label, score = calculate_market_rating(historical_deals + active_deal_list)
                text = build_weekly_report(
                    active,
                    market_label=label,
                    market_score=score,
                    feedback_form_url=self.settings.feedback_form_url,
                )
                message_id = self.telegram_client.post_weekly_report_sync(text)
                now = utc_now()
                session.add(
                    Post(
                        post_type="weekly_report",
                        telegram_message_id=message_id,
                        category=None,
                        active_deal_id=None,
                        content_text=text,
                        posted_at=now,
                        status="dry_run" if self.settings.dry_run else "posted",
                        metadata_json={"market_label": label, "market_score": score},
                    )
                )
                session.commit()
                return message_id
            finally:
                release_advisory_lock(session, lock_name)

    def build_current_report_text(self) -> str:
        with self.session_factory() as session:
            active = self._active_deals(session)
            label, score = calculate_market_rating(
                [deal for deals in active.values() for deal in deals.values()]
            )
            return build_weekly_report(
                active,
                market_label=label,
                market_score=score,
                feedback_form_url=self.settings.feedback_form_url,
            )

    def _active_deals(self, session: Any) -> dict[str, dict[str, NormalizedFlightDeal]]:
        output: dict[str, dict[str, NormalizedFlightDeal]] = {
            category: {} for category in ordered_categories()
        }
        rows = session.execute(
            select(ActiveDeal).where(ActiveDeal.active.is_(True)).order_by(ActiveDeal.category)
        ).scalars()
        for row in rows:
            output.setdefault(row.category, {})[row.deal_type] = _deal_from_active(row)
        return output


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
        metadata=row.metadata_json or {},
    )


def _deal_from_price_history(row: PriceHistory) -> NormalizedFlightDeal:
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
        source=row.source,
        exact_check_completed=row.exact_check_completed,
        deal_score=row.deal_score,
        metadata=row.metadata_json or {},
    )
