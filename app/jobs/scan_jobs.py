from __future__ import annotations

import hashlib
import json
import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.db.locks import release_advisory_lock, try_advisory_lock
from app.db.models import ActiveDeal, Post, PriceHistory, RawApiResult, Scan
from app.providers.base import FlightProvider, NormalizedFlightDeal
from app.services.app_settings import is_paused
from app.services.deal_scoring import calculate_deal_score
from app.services.deal_selection import (
    dedupe_deals,
    qualifies_for_strong_alert,
    select_active_deals,
)
from app.services.provider_usage import record_provider_usage
from app.services.report_builder import build_strong_alert
from app.services.telegram_client import TelegramClient
from app.utils.dates import local_today, next_three_month_window, utc_now

logger = logging.getLogger(__name__)


class FlightScanService:
    def __init__(
        self,
        *,
        session_factory: Any,
        provider: FlightProvider,
        telegram_client: TelegramClient | Any,
        dry_run: bool,
        settings: Settings | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.telegram_client = telegram_client
        self.dry_run = dry_run
        self.settings = settings or Settings()

    def scan_all_categories(self, *, today: date | None = None, respect_pause: bool = True) -> None:
        for category in ["one_week", "two_week", "one_month"]:
            self.scan_category(category, today=today, respect_pause=respect_pause)

    def scan_category(
        self,
        category: str,
        *,
        today: date | None = None,
        respect_pause: bool = True,
    ) -> int | None:
        with self.session_factory() as session:
            lock_name = f"scan:{category}"
            if not try_advisory_lock(session, lock_name):
                logger.info("Skipping scan because advisory lock is held category=%s", category)
                return None
            try:
                return self._scan_category_with_session(
                    session,
                    category,
                    today=today,
                    respect_pause=respect_pause,
                )
            finally:
                release_advisory_lock(session, lock_name)

    def _scan_category_with_session(
        self,
        session: Session,
        category: str,
        *,
        today: date | None,
        respect_pause: bool,
    ) -> int | None:
        if respect_pause and is_paused(session):
            logger.info("Skipping scheduled scan because app is paused category=%s", category)
            return None

        current_day = today or local_today(self.settings.app_timezone)
        start_date, end_date = next_three_month_window(current_day)
        now = utc_now()
        scan = Scan(
            source=self.provider.source,
            category=category,
            status="running",
            started_at=now,
            request_count=0,
            metadata_json={"start_date": start_date.isoformat(), "end_date": end_date.isoformat()},
        )
        session.add(scan)
        session.flush()
        session.commit()

        try:
            response = self.provider.search_dates_for_category(category, start_date, end_date)
            scan.request_count = response.request_count
            scan.metadata_json = {
                **scan.metadata_json,
                "successful_count": response.successful_count,
                "failed_count": response.failed_count,
            }
            for raw in response.raw_results:
                session.add(
                    RawApiResult(
                        scan_id=scan.id,
                        source=self.provider.source,
                        category=category,
                        request_hash=_request_hash(raw),
                        response_json=raw,
                        created_at=now,
                        expires_at=now + timedelta(days=self.settings.raw_result_retention_days),
                    )
                )
            record_provider_usage(
                session,
                source=self.provider.source,
                request_count=response.request_count,
                successful_count=response.successful_count,
                failed_count=response.failed_count,
            )
            recent_average = self._recent_category_average(session, category)
            deals = self._score_deals(response.deals, recent_average)
            deduped = dedupe_deals(deals)
            selected = select_active_deals(deduped)
            selected = self._exact_check_selected(selected, recent_average)
            deduped = self._merge_exact_results(deduped, selected)
            self._write_price_history(session, deduped, now)
            self._upsert_active_deals(session, category, selected, now)
            self._post_strong_alerts(session, category, selected, recent_average, now)
            scan.status = "success"
            scan.finished_at = utc_now()
            session.commit()
            return scan.id
        except Exception as exc:
            session.rollback()
            with self.session_factory() as error_session:
                scan_row = error_session.get(Scan, scan.id)
                if scan_row:
                    scan_row.status = "failed"
                    scan_row.finished_at = utc_now()
                    scan_row.error_message = str(exc)
                    error_session.commit()
            logger.exception("Category scan failed category=%s", category)
            raise

    def _score_deals(
        self,
        deals: list[NormalizedFlightDeal],
        recent_average: float | None,
    ) -> list[NormalizedFlightDeal]:
        scored: list[NormalizedFlightDeal] = []
        for deal in deals:
            deal.deal_score = calculate_deal_score(deal, recent_average)
            scored.append(deal)
        return scored

    def _exact_check_selected(
        self,
        selected: dict[str, NormalizedFlightDeal | None],
        recent_average: float | None,
    ) -> dict[str, NormalizedFlightDeal | None]:
        confirmed_by_pair: dict[tuple, NormalizedFlightDeal] = {}
        for deal in selected.values():
            if deal is None or deal.date_pair_key() in confirmed_by_pair:
                continue
            exact = self.provider.search_exact_round_trip(deal.depart_date, deal.return_date)
            logger.info(
                "exact-date fli confirmation category=%s depart_date=%s "
                "return_date=%s succeeded=%s",
                deal.category,
                deal.depart_date,
                deal.return_date,
                bool(exact),
            )
            if exact:
                exact.category = deal.category
                exact.deal_score = calculate_deal_score(exact, recent_average)
                confirmed_by_pair[deal.date_pair_key()] = exact

        updated: dict[str, NormalizedFlightDeal | None] = {}
        for deal_type, deal in selected.items():
            if deal is None:
                updated[deal_type] = None
                continue
            updated[deal_type] = confirmed_by_pair.get(deal.date_pair_key(), deal)
        return updated

    def _merge_exact_results(
        self,
        deals: list[NormalizedFlightDeal],
        selected: dict[str, NormalizedFlightDeal | None],
    ) -> list[NormalizedFlightDeal]:
        exact_by_pair = {
            deal.date_pair_key(): deal
            for deal in selected.values()
            if deal is not None and deal.exact_check_completed
        }
        return [exact_by_pair.get(deal.date_pair_key(), deal) for deal in deals]

    def _write_price_history(
        self,
        session: Session,
        deals: list[NormalizedFlightDeal],
        checked_at: Any,
    ) -> None:
        for deal in deals:
            session.add(_price_history_from_deal(deal, checked_at))

    def _upsert_active_deals(
        self,
        session: Session,
        category: str,
        selected: dict[str, NormalizedFlightDeal | None],
        seen_at: Any,
    ) -> None:
        for deal_type, deal in selected.items():
            if deal is None:
                continue
            existing = session.execute(
                select(ActiveDeal).where(
                    ActiveDeal.category == category,
                    ActiveDeal.deal_type == deal_type,
                )
            ).scalar_one_or_none()
            if existing is None:
                session.add(_active_deal_from_deal(deal, deal_type, seen_at))
                continue
            _update_active_deal(existing, deal, seen_at)

    def _post_strong_alerts(
        self,
        session: Session,
        category: str,
        selected: dict[str, NormalizedFlightDeal | None],
        recent_average: float | None,
        posted_at: Any,
    ) -> None:
        if is_paused(session):
            return
        for deal_type in ("cheapest", "best_value"):
            deal = selected.get(deal_type)
            if deal is None:
                continue
            active = session.execute(
                select(ActiveDeal).where(
                    ActiveDeal.category == category,
                    ActiveDeal.deal_type == deal_type,
                )
            ).scalar_one_or_none()
            last_price = active.last_posted_price_cad if active else None
            if not qualifies_for_strong_alert(deal, recent_average, last_price):
                continue
            alert = build_strong_alert(deal, alert_type=deal_type)
            message_id = self.telegram_client.post_strong_alert_sync(
                alert.text,
                alert.button_text,
                alert.button_url,
            )
            post = Post(
                post_type="strong_alert",
                telegram_message_id=message_id,
                category=category,
                active_deal_id=active.id if active else None,
                content_text=alert.text,
                posted_at=posted_at,
                status="dry_run" if self.dry_run else "posted",
                metadata_json={"deal_type": deal_type},
            )
            session.add(post)
            if active:
                active.last_posted_at = posted_at
                active.last_posted_price_cad = deal.price_cad

    def _recent_category_average(self, session: Session, category: str) -> float | None:
        since = utc_now() - timedelta(days=self.settings.price_history_days)
        return session.execute(
            select(func.avg(PriceHistory.price_cad)).where(
                PriceHistory.category == category,
                PriceHistory.checked_at >= since,
                PriceHistory.archived_at.is_(None),
            )
        ).scalar()


def _price_history_from_deal(deal: NormalizedFlightDeal, checked_at: Any) -> PriceHistory:
    return PriceHistory(
        source=deal.source,
        category=deal.category,
        origin=deal.origin,
        destination=deal.destination,
        depart_date=deal.depart_date,
        return_date=deal.return_date,
        trip_length_days=deal.trip_length_days,
        price_cad=deal.price_cad,
        airline=deal.airline,
        stops=deal.stops,
        total_travel_minutes=deal.total_travel_minutes,
        layover_summary=deal.layover_summary,
        baggage_summary=deal.baggage_summary,
        exact_check_completed=deal.exact_check_completed,
        deal_score=deal.deal_score,
        checked_at=checked_at,
        metadata_json=deal.metadata,
    )


def _active_deal_from_deal(deal: NormalizedFlightDeal, deal_type: str, seen_at: Any) -> ActiveDeal:
    return ActiveDeal(
        category=deal.category,
        deal_type=deal_type,
        origin=deal.origin,
        destination=deal.destination,
        depart_date=deal.depart_date,
        return_date=deal.return_date,
        trip_length_days=deal.trip_length_days,
        price_cad=deal.price_cad,
        airline=deal.airline,
        stops=deal.stops,
        total_travel_minutes=deal.total_travel_minutes,
        layover_summary=deal.layover_summary,
        baggage_summary=deal.baggage_summary,
        google_flights_link=deal.google_flights_link,
        source=deal.source,
        exact_check_completed=deal.exact_check_completed,
        deal_score=deal.deal_score,
        market_label=deal.market_label,
        active=True,
        first_seen_at=seen_at,
        last_seen_at=seen_at,
        metadata_json={**deal.metadata, "deal_type": deal_type},
    )


def _update_active_deal(row: ActiveDeal, deal: NormalizedFlightDeal, seen_at: Any) -> None:
    row.origin = deal.origin
    row.destination = deal.destination
    row.depart_date = deal.depart_date
    row.return_date = deal.return_date
    row.trip_length_days = deal.trip_length_days
    row.price_cad = deal.price_cad
    row.airline = deal.airline
    row.stops = deal.stops
    row.total_travel_minutes = deal.total_travel_minutes
    row.layover_summary = deal.layover_summary
    row.baggage_summary = deal.baggage_summary
    row.google_flights_link = deal.google_flights_link
    row.source = deal.source
    row.exact_check_completed = deal.exact_check_completed
    row.deal_score = deal.deal_score
    row.market_label = deal.market_label
    row.active = True
    row.last_seen_at = seen_at
    row.metadata_json = {**deal.metadata, "deal_type": row.deal_type}


def _request_hash(raw: dict[str, Any]) -> str:
    payload = json.dumps(raw, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
