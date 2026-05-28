from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.locks import release_advisory_lock, try_advisory_lock
from app.db.models import ActiveDeal, Post, PriceHistory, RawApiResult, Scan
from app.providers.base import ExactSearchMode, FlightProvider, NormalizedFlightDeal
from app.services.app_settings import is_paused
from app.services.deal_scoring import apply_deal_ratings
from app.services.deal_selection import (
    dedupe_deals,
    qualifies_for_strong_alert,
    select_active_deals,
)
from app.services.market_baseline import (
    MIN_HISTORY_ROWS,
    PriceBaseline,
    build_cheapest_snapshot_baseline,
)
from app.services.provider_usage import record_provider_usage
from app.services.report_builder import build_strong_alert
from app.services.telegram_client import TelegramClient
from app.utils.dates import local_today, next_three_month_window, ordered_categories, utc_now

logger = logging.getLogger(__name__)

PIPELINE_LOCK = "search_pipeline"
EXACT_SEARCH_TOP_N = 3


@dataclass(frozen=True)
class ScanCategoryResult:
    request_count: int
    successful_count: int
    failed_count: int


@dataclass(frozen=True)
class ExactCheckResult:
    deals: list[NormalizedFlightDeal]
    request_count: int
    successful_count: int
    failed_count: int


@dataclass(frozen=True)
class _PendingAlert:
    category: str
    deal_type: str
    text: str
    button_text: str
    button_url: str
    active_deal_id: int
    price_cad: int


@dataclass
class _CategoryOutcome:
    result: ScanCategoryResult | None = None
    alerts: list[_PendingAlert] = field(default_factory=list)


class FlightScanService:
    def __init__(
        self,
        *,
        session_factory: sessionmaker[Session],
        provider: FlightProvider,
        telegram_client: TelegramClient,
        dry_run: bool,
        settings: Settings | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.provider = provider
        self.telegram_client = telegram_client
        self.dry_run = dry_run
        self.settings = settings or Settings()

    def scan_all_categories(self, *, today: date | None = None, respect_pause: bool = True) -> None:
        categories = ordered_categories()
        started = time.perf_counter()

        with self.session_factory() as gate_session:
            if respect_pause and is_paused(gate_session):
                logger.info("Skipping discovery because app is paused")
                return
            if not try_advisory_lock(gate_session, PIPELINE_LOCK):
                logger.info("Skipping discovery because search pipeline lock is held")
                return
            try:
                outcomes, failures = self._run_discovery_workers(categories, today=today)
                self._safe_record_discovery_provider_usage(
                    gate_session,
                    (outcome.result for outcome in outcomes.values() if outcome.result),
                )
            finally:
                release_advisory_lock(gate_session, PIPELINE_LOCK)

        self._send_pending_alerts(
            alert for outcome in outcomes.values() for alert in outcome.alerts
        )

        total_seconds = _elapsed_seconds(started)
        logger.info(
            "discovery scan finished categories=%s failed_categories=%s total_seconds=%s",
            ",".join(categories),
            ",".join(failures) if failures else "none",
            total_seconds,
        )
        if failures:
            error_summary = "; ".join(
                f"{category}: {error}" for category, error in failures.items()
            )
            raise RuntimeError(f"Discovery scan failed categories: {error_summary}")

    def scan_category(
        self,
        category: str,
        *,
        today: date | None = None,
        respect_pause: bool = True,
    ) -> ScanCategoryResult | None:
        outcome = _CategoryOutcome()
        with self.session_factory() as session:
            if respect_pause and is_paused(session):
                logger.info("Skipping scan because app is paused category=%s", category)
                return None
            if not try_advisory_lock(session, PIPELINE_LOCK):
                logger.info(
                    "Skipping scan because search pipeline lock is held category=%s",
                    category,
                )
                return None
            try:
                outcome = self._scan_category_in_new_session(category, today=today)
                if outcome.result is not None:
                    self._safe_record_discovery_provider_usage(session, [outcome.result])
            finally:
                release_advisory_lock(session, PIPELINE_LOCK)

        self._send_pending_alerts(outcome.alerts)
        return outcome.result

    def _run_discovery_workers(
        self,
        categories: list[str],
        *,
        today: date | None,
    ) -> tuple[dict[str, _CategoryOutcome], dict[str, BaseException]]:
        worker_count = max(
            1,
            min(self.settings.discovery_category_workers, len(categories)),
        )
        outcomes: dict[str, _CategoryOutcome] = {}
        failures: dict[str, BaseException] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_by_category = {
                executor.submit(
                    self._scan_category_in_new_session,
                    category,
                    today=today,
                ): category
                for category in categories
            }
            for future in concurrent.futures.as_completed(future_by_category):
                category = future_by_category[future]
                try:
                    outcomes[category] = future.result()
                except Exception as exc:  # noqa: BLE001 - collect category failures after join.
                    failures[category] = exc
                    logger.exception("Discovery category worker failed category=%s", category)
        return outcomes, failures

    def _scan_category_in_new_session(
        self,
        category: str,
        *,
        today: date | None,
    ) -> _CategoryOutcome:
        with self.session_factory() as session:
            return self._scan_category(session, category, today=today)

    def _safe_record_discovery_provider_usage(
        self,
        session: Session,
        results: Iterable[ScanCategoryResult],
    ) -> None:
        try:
            self._record_discovery_provider_usage(session, results)
            session.commit()
        except Exception:  # noqa: BLE001 - usage accounting must not fail discovery.
            session.rollback()
            logger.exception("Provider usage update failed after discovery scan")

    def _record_discovery_provider_usage(
        self,
        session: Session,
        results: Iterable[ScanCategoryResult],
    ) -> None:
        totals = list(results)
        request_count = sum(result.request_count for result in totals)
        successful_count = sum(result.successful_count for result in totals)
        failed_count = sum(result.failed_count for result in totals)
        if request_count == 0 and successful_count == 0 and failed_count == 0:
            return
        record_provider_usage(
            session,
            source=self.provider.source,
            request_count=request_count,
            successful_count=successful_count,
            failed_count=failed_count,
        )

    def _exact_search_modes(self) -> list[ExactSearchMode]:
        return [ExactSearchMode.CHEAPEST, ExactSearchMode.TOP_FLIGHTS]

    def _scan_category(
        self,
        session: Session,
        category: str,
        *,
        today: date | None,
    ) -> _CategoryOutcome:
        category_started = time.perf_counter()
        current_day = today or _provider_safe_scan_day(local_today(self.settings.app_timezone))
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
        session.commit()

        try:
            calendar_started = time.perf_counter()
            response = self.provider.search_dates_for_category(category, start_date, end_date)
            calendar_seconds = _elapsed_seconds(calendar_started)
            scan.request_count = response.request_count
            scan.metadata_json = {
                **scan.metadata_json,
                "successful_count": response.successful_count,
                "failed_count": response.failed_count,
                "calendar_seconds": calendar_seconds,
                "calendar_deal_count": len(response.deals),
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
            fare_baseline = self._category_fare_baseline(session, category, before=now)
            recent_average = fare_baseline.average
            scored = self._score_deals(response.deals, fare_baseline)
            candidates = select_discovery_candidates(
                scored,
                self.settings.discovery_candidates_per_category,
            )
            exact_started = time.perf_counter()
            exact_result = self._exact_check_candidates(candidates, fare_baseline)
            exact_seconds = _elapsed_seconds(exact_started)
            exact_candidates = dedupe_deals(exact_result.deals)
            self._write_price_history(session, exact_candidates, now)
            selected = select_active_deals(exact_candidates)
            self._upsert_active_deals(session, category, selected, now)
            session.flush()
            pending_alerts = self._collect_pending_alerts(
                session,
                category,
                selected,
                recent_average,
            )
            total_seconds = _elapsed_seconds(category_started)
            scan.metadata_json = {
                **scan.metadata_json,
                "candidate_count": len(candidates),
                "exact_seconds": exact_seconds,
                "exact_request_count": exact_result.request_count,
                "exact_success_count": exact_result.successful_count,
                "exact_failed_count": exact_result.failed_count,
                "exact_result_count": len(exact_result.deals),
                "exact_deduped_count": len(exact_candidates),
                "total_seconds": total_seconds,
            }
            scan.request_count = response.request_count + exact_result.request_count
            scan.status = "success"
            scan.finished_at = utc_now()
            session.commit()
            logger.info(
                "discovery category finished category=%s calendar_seconds=%s "
                "exact_seconds=%s total_seconds=%s calendar_deal_count=%s "
                "candidate_count=%s exact_success_count=%s",
                category,
                calendar_seconds,
                exact_seconds,
                total_seconds,
                len(response.deals),
                len(candidates),
                exact_result.successful_count,
            )
            return _CategoryOutcome(
                result=ScanCategoryResult(
                    request_count=response.request_count + exact_result.request_count,
                    successful_count=response.successful_count + exact_result.successful_count,
                    failed_count=response.failed_count + exact_result.failed_count,
                ),
                alerts=pending_alerts,
            )
        except Exception as exc:
            session.rollback()
            scan_row = session.get(Scan, scan.id)
            if scan_row is not None:
                scan_row.status = "failed"
                scan_row.finished_at = utc_now()
                scan_row.error_message = str(exc)
                scan_row.metadata_json = {
                    **(scan_row.metadata_json or {}),
                    "total_seconds": _elapsed_seconds(category_started),
                }
                session.commit()
            logger.exception("Category scan failed category=%s", category)
            raise

    def _score_deals(
        self,
        deals: list[NormalizedFlightDeal],
        fare_baseline: PriceBaseline,
    ) -> list[NormalizedFlightDeal]:
        for deal in deals:
            apply_deal_ratings(
                deal,
                fare_baseline=fare_baseline,
                recent_category_average=fare_baseline.average,
                min_history_rows=MIN_HISTORY_ROWS,
            )
        return deals

    def _exact_check_candidates(
        self,
        candidates: list[NormalizedFlightDeal],
        fare_baseline: PriceBaseline,
    ) -> ExactCheckResult:
        exact_deals: list[NormalizedFlightDeal] = []
        modes = self._exact_search_modes()
        request_count = 0
        successful_count = 0
        failed_count = 0
        first_call = True
        for candidate in candidates:
            for mode in modes:
                if not first_call and self.settings.exact_search_delay_seconds > 0:
                    time.sleep(self.settings.exact_search_delay_seconds)
                first_call = False
                request_count += 1
                try:
                    found = self.provider.search_exact_round_trip(
                        candidate.depart_date,
                        candidate.return_date,
                        mode=mode,
                        top_n=EXACT_SEARCH_TOP_N,
                    )
                except Exception:  # noqa: BLE001 - one failure must not fail discovery.
                    failed_count += 1
                    logger.exception(
                        "exact-date confirmation raised category=%s depart_date=%s "
                        "return_date=%s mode=%s",
                        candidate.category,
                        candidate.depart_date,
                        candidate.return_date,
                        mode.value,
                    )
                    continue
                if found:
                    successful_count += 1
                else:
                    failed_count += 1
                logger.info(
                    "exact-date confirmation category=%s depart_date=%s return_date=%s "
                    "mode=%s succeeded=%s result_count=%s",
                    candidate.category,
                    candidate.depart_date,
                    candidate.return_date,
                    mode.value,
                    bool(found),
                    len(found),
                )
                for exact in found:
                    exact.category = candidate.category
                    exact.metadata.setdefault("exact_sort_mode", mode.value)
                    apply_deal_ratings(
                        exact,
                        fare_baseline=fare_baseline,
                        recent_category_average=fare_baseline.average,
                        min_history_rows=MIN_HISTORY_ROWS,
                    )
                    exact_deals.append(exact)
        return ExactCheckResult(
            deals=exact_deals,
            request_count=request_count,
            successful_count=successful_count,
            failed_count=failed_count,
        )

    def _write_price_history(
        self,
        session: Session,
        deals: list[NormalizedFlightDeal],
        checked_at: datetime,
    ) -> None:
        for deal in deals:
            session.add(_price_history_from_deal(deal, checked_at))

    def _upsert_active_deals(
        self,
        session: Session,
        category: str,
        selected: dict[str, NormalizedFlightDeal | None],
        seen_at: datetime,
    ) -> None:
        selected_types = {deal_type for deal_type, deal in selected.items() if deal is not None}
        for stale in session.execute(
            select(ActiveDeal).where(
                ActiveDeal.category == category,
                ActiveDeal.deal_type.not_in(selected_types or {"__none__"}),
            )
        ).scalars():
            stale.active = False

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

    def _collect_pending_alerts(
        self,
        session: Session,
        category: str,
        selected: dict[str, NormalizedFlightDeal | None],
        recent_average: float | None,
    ) -> list[_PendingAlert]:
        pending: list[_PendingAlert] = []
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
            if active is None:
                continue
            if not qualifies_for_strong_alert(
                deal,
                recent_average,
                active.last_posted_price_cad,
            ):
                continue
            alert = build_strong_alert(deal, alert_type=deal_type)
            pending.append(
                _PendingAlert(
                    category=category,
                    deal_type=deal_type,
                    text=alert.text,
                    button_text=alert.button_text,
                    button_url=alert.button_url,
                    active_deal_id=active.id,
                    price_cad=deal.price_cad,
                )
            )
        return pending

    def _send_pending_alerts(self, alerts: Iterable[_PendingAlert]) -> None:
        pending_list = list(alerts)
        if not pending_list:
            return
        sent: list[tuple[_PendingAlert, int | None]] = []
        for alert in pending_list:
            try:
                message_id = self.telegram_client.post_strong_alert(
                    alert.text,
                    alert.button_text,
                    alert.button_url,
                )
            except Exception:  # noqa: BLE001 - one failed post must not block the rest.
                logger.exception(
                    "Strong alert post failed category=%s deal_type=%s",
                    alert.category,
                    alert.deal_type,
                )
                continue
            sent.append((alert, message_id))
        if not sent:
            return
        posted_at = utc_now()
        with self.session_factory() as session:
            for alert, message_id in sent:
                session.add(
                    Post(
                        post_type="strong_alert",
                        telegram_message_id=message_id,
                        category=alert.category,
                        active_deal_id=alert.active_deal_id,
                        content_text=alert.text,
                        posted_at=posted_at,
                        status="dry_run" if self.dry_run else "posted",
                        metadata_json={"deal_type": alert.deal_type},
                    )
                )
                active = session.get(ActiveDeal, alert.active_deal_id)
                if active is not None:
                    active.last_posted_at = posted_at
                    active.last_posted_price_cad = alert.price_cad
            session.commit()

    def _category_fare_baseline(
        self,
        session: Session,
        category: str,
        *,
        before: datetime,
    ) -> PriceBaseline:
        since = utc_now() - timedelta(days=self.settings.market_baseline_days)
        rows = session.execute(
            select(PriceHistory).where(
                PriceHistory.category == category,
                PriceHistory.checked_at >= since,
                PriceHistory.checked_at < before,
                PriceHistory.exact_check_completed.is_(True),
                PriceHistory.archived_at.is_(None),
            )
        ).scalars()
        return build_cheapest_snapshot_baseline(
            rows,
            category=category,
            baseline_days=self.settings.market_baseline_days,
        )


def _price_history_from_deal(deal: NormalizedFlightDeal, checked_at: datetime) -> PriceHistory:
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
        metadata_json=_essential_metadata(deal),
    )


def _active_deal_from_deal(
    deal: NormalizedFlightDeal,
    deal_type: str,
    seen_at: datetime,
) -> ActiveDeal:
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
        metadata_json={**_essential_metadata(deal), "deal_type": deal_type},
    )


def _update_active_deal(
    row: ActiveDeal,
    deal: NormalizedFlightDeal,
    seen_at: datetime,
) -> None:
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
    row.metadata_json = {**_essential_metadata(deal), "deal_type": row.deal_type}


_ESSENTIAL_METADATA_KEYS = (
    "fare_label",
    "flight_quality_label",
    "exact_sort_mode",
    "baseline_median_cad",
    "baseline_has_enough_history",
)


def _essential_metadata(deal: NormalizedFlightDeal) -> dict[str, Any]:
    return {key: deal.metadata[key] for key in _ESSENTIAL_METADATA_KEYS if key in deal.metadata}


def select_discovery_candidates(
    deals: list[NormalizedFlightDeal],
    limit: int,
) -> list[NormalizedFlightDeal]:
    if limit <= 0:
        return []
    best_by_pair: dict[tuple[str, str, date, date, int], NormalizedFlightDeal] = {}
    for deal in deals:
        current = best_by_pair.get(deal.date_pair_key())
        if current is None or deal.price_cad < current.price_cad:
            best_by_pair[deal.date_pair_key()] = deal
    return sorted(best_by_pair.values(), key=lambda deal: (deal.price_cad, deal.depart_date))[
        :limit
    ]


def _elapsed_seconds(started_at: float) -> float:
    return round(time.perf_counter() - started_at, 3)


def _provider_safe_scan_day(local_day: date, provider_day: date | None = None) -> date:
    return max(local_day, provider_day or date.today())


def _request_hash(raw: dict[str, Any]) -> str:
    payload = json.dumps(raw, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
