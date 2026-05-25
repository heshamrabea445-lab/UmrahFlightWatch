from __future__ import annotations

import concurrent.futures
import hashlib
import json
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

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
from app.services.market_baseline import PriceBaseline, build_cheapest_snapshot_baseline
from app.services.provider_usage import record_provider_usage
from app.services.report_builder import build_strong_alert
from app.services.telegram_client import TelegramClient
from app.utils.dates import local_today, next_three_month_window, ordered_categories, utc_now

logger = logging.getLogger(__name__)


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


class FlightScanService:
    def __init__(
        self,
        *,
        session_factory: Any,
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
        failures: dict[str, BaseException] = {}
        results: dict[str, ScanCategoryResult] = {}
        with self.session_factory() as session:
            if respect_pause and is_paused(session):
                logger.info("Skipping discovery because app is paused")
                return
            if not try_advisory_lock(session, "search_pipeline"):
                logger.info("Skipping discovery because search pipeline lock is held")
                return
            try:
                results, failures = self._run_discovery_workers(categories, today=today)
                self._safe_record_discovery_provider_usage(session, results.values())
            finally:
                release_advisory_lock(session, "search_pipeline")
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

    def _run_discovery_workers(
        self,
        categories: list[str],
        *,
        today: date | None,
    ) -> tuple[dict[str, ScanCategoryResult], dict[str, BaseException]]:
        worker_count = max(
            1,
            min(self.settings.discovery_category_workers, len(categories)),
        )
        results: dict[str, ScanCategoryResult] = {}
        failures: dict[str, BaseException] = {}
        with concurrent.futures.ThreadPoolExecutor(max_workers=worker_count) as executor:
            future_by_category = {
                executor.submit(
                    self._scan_category_worker,
                    category,
                    today=today,
                ): category
                for category in categories
            }
            for future in concurrent.futures.as_completed(future_by_category):
                category = future_by_category[future]
                try:
                    result = future.result()
                    if result is not None:
                        results[category] = result
                except Exception as exc:  # noqa: BLE001 - collect category failures after join.
                    failures[category] = exc
                    logger.exception("Discovery category worker failed category=%s", category)
        return results, failures

    def _scan_category_worker(
        self,
        category: str,
        *,
        today: date | None,
    ) -> ScanCategoryResult | None:
        with self.session_factory() as session:
            lock_name = f"scan:{category}"
            if not try_advisory_lock(session, lock_name):
                logger.info(
                    "Skipping discovery because category lock is held category=%s", category
                )
                return None
            try:
                return self._scan_category_with_session(
                    session,
                    category,
                    today=today,
                    respect_pause=False,
                )
            finally:
                release_advisory_lock(session, lock_name)

    def scan_category(
        self,
        category: str,
        *,
        today: date | None = None,
        respect_pause: bool = True,
    ) -> ScanCategoryResult | None:
        with self.session_factory() as session:
            if not try_advisory_lock(session, "search_pipeline"):
                logger.info(
                    "Skipping scan because search pipeline lock is held category=%s",
                    category,
                )
                return None
            lock_name = f"scan:{category}"
            if not try_advisory_lock(session, lock_name):
                logger.info("Skipping scan because advisory lock is held category=%s", category)
                release_advisory_lock(session, "search_pipeline")
                return None
            try:
                result = self._scan_category_with_session(
                    session,
                    category,
                    today=today,
                    respect_pause=respect_pause,
                )
                if result is not None:
                    self._safe_record_discovery_provider_usage(session, [result])
                return result
            finally:
                release_advisory_lock(session, lock_name)
                release_advisory_lock(session, "search_pipeline")

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
        modes = [ExactSearchMode.CHEAPEST]
        best_mode = ExactSearchMode(self.settings.best_value_exact_sort.upper())
        if best_mode not in modes:
            modes.append(best_mode)
        return modes

    def _scan_category_with_session(
        self,
        session: Session,
        category: str,
        *,
        today: date | None,
        respect_pause: bool,
    ) -> ScanCategoryResult | None:
        if respect_pause and is_paused(session):
            logger.info("Skipping scheduled scan because app is paused category=%s", category)
            return None

        category_started = time.perf_counter()
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
            deals = self._score_deals(response.deals, fare_baseline)
            candidates = select_discovery_candidates(
                deals,
                self.settings.discovery_candidates_per_category,
            )
            exact_started = time.perf_counter()
            exact_result = self._exact_check_candidates(candidates, fare_baseline)
            exact_seconds = _elapsed_seconds(exact_started)
            exact_candidates = dedupe_deals(exact_result.deals)
            self._write_price_history(session, exact_candidates, now)
            selected = select_active_deals(
                exact_candidates,
                best_value_exact_sort=self.settings.best_value_exact_sort,
                best_value_max_price_premium_cad=(self.settings.best_value_max_price_premium_cad),
                best_value_max_price_premium_ratio=(
                    self.settings.best_value_max_price_premium_ratio
                ),
            )
            self._upsert_active_deals(session, category, selected, now)
            self._post_strong_alerts(session, category, selected, recent_average, now)
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
            return ScanCategoryResult(
                request_count=response.request_count + exact_result.request_count,
                successful_count=response.successful_count + exact_result.successful_count,
                failed_count=response.failed_count + exact_result.failed_count,
            )
        except Exception as exc:
            session.rollback()
            with self.session_factory() as error_session:
                scan_row = error_session.get(Scan, scan.id)
                if scan_row:
                    scan_row.status = "failed"
                    scan_row.finished_at = utc_now()
                    scan_row.error_message = str(exc)
                    scan_row.metadata_json = {
                        **(scan_row.metadata_json or {}),
                        "total_seconds": _elapsed_seconds(category_started),
                    }
                    error_session.commit()
            logger.exception("Category scan failed category=%s", category)
            raise

    def _score_deals(
        self,
        deals: list[NormalizedFlightDeal],
        fare_baseline: PriceBaseline,
    ) -> list[NormalizedFlightDeal]:
        scored: list[NormalizedFlightDeal] = []
        for deal in deals:
            apply_deal_ratings(
                deal,
                fare_baseline=fare_baseline,
                recent_category_average=fare_baseline.average,
                min_history_rows=self.settings.market_min_history_rows,
            )
            scored.append(deal)
        return scored

    def _exact_check_candidates(
        self,
        candidates: list[NormalizedFlightDeal],
        fare_baseline: PriceBaseline,
    ) -> ExactCheckResult:
        exact_candidates: list[NormalizedFlightDeal] = []
        requests = [
            (candidate, candidate_rank, mode)
            for candidate_rank, candidate in enumerate(candidates, start=1)
            for mode in self._exact_search_modes()
        ]
        successful_count = 0
        failed_count = 0
        for index, (candidate, candidate_rank, mode) in enumerate(requests):
            if index > 0 and self.settings.exact_search_delay_seconds > 0:
                time.sleep(self.settings.exact_search_delay_seconds)
            try:
                exact_deals = self.provider.search_exact_round_trip(
                    candidate.depart_date,
                    candidate.return_date,
                    mode=mode,
                    top_n=self.settings.exact_search_top_n,
                )
            except Exception:  # noqa: BLE001 - one exact-date failure should not fail discovery.
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
            if exact_deals:
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
                bool(exact_deals),
                len(exact_deals),
            )
            for exact in exact_deals:
                exact.category = candidate.category
                exact.metadata["calendar_price_cad"] = candidate.price_cad
                exact.metadata["calendar_candidate_rank"] = candidate_rank
                exact.metadata.setdefault("exact_sort_mode", mode.value)
                apply_deal_ratings(
                    exact,
                    fare_baseline=fare_baseline,
                    recent_category_average=fare_baseline.average,
                    min_history_rows=self.settings.market_min_history_rows,
                )
                exact_candidates.append(exact)
        return ExactCheckResult(
            deals=exact_candidates,
            request_count=len(requests),
            successful_count=successful_count,
            failed_count=failed_count,
        )

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
            if not qualifies_for_strong_alert(
                deal,
                recent_average,
                last_price,
                flash_alert_median_ratio=self.settings.flash_alert_median_ratio,
                flash_alert_absolute_fallback_cad=(self.settings.flash_alert_absolute_fallback_cad),
                suspicious_price_average_ratio=self.settings.suspicious_price_average_ratio,
            ):
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

    def _category_fare_baseline(
        self,
        session: Session,
        category: str,
        *,
        before: Any,
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


def _elapsed_seconds(started_at: float) -> float:
    return round(time.perf_counter() - started_at, 3)


def _request_hash(raw: dict[str, Any]) -> str:
    payload = json.dumps(raw, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
