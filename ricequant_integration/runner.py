from __future__ import annotations

import calendar
import logging
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from time import monotonic
from typing import Callable, Iterable, TypeVar
from zoneinfo import ZoneInfo

import pandas as pd

from ricequant_integration.client import RqDataClient
from ricequant_integration.financial_fields import FINANCIAL_FIELDS_BY_DATASET
from ricequant_integration.planner import (
    DateSlice,
    daily_slices,
    incremental_start,
    month_end_trading_dates,
    month_slices,
    quarter_end_on_or_after,
    quarter_end_on_or_before,
    quarter_label,
)
from ricequant_integration.progress import ProgressReporter
from ricequant_integration.quota import QuotaGuard, QuotaPaused
from ricequant_integration.settings import RiceQuantSettings
from ricequant_integration.specs import DATASET_SPECS, INDEX_WEIGHTS_EX_INDEXES
from ricequant_integration.state import StateStore
from ricequant_integration.storage import RiceQuantStorage, quote_string
from ricequant_integration.transform import (
    add_metadata,
    concept_catalog_frame,
    concept_member_frame,
    concept_snapshot_frame,
    conform,
    citics_industry_snapshot_frame,
    ex_factor_frame,
    financial_statement_frame,
    industry_mapping_frame,
    industry_member_frame,
    index_components_frame,
    index_daily_frame,
    index_weights_ex_frame,
    index_weights_frame,
    instruments_frame,
    sector_snapshot_frame,
    shenwan_industry_snapshot_frame,
    split_frame,
    stock_daily_frame,
    stock_minute_frame,
    tick_frame,
)


LOGGER = logging.getLogger(__name__)
T = TypeVar("T")


DEFAULT_ESTIMATES = {
    "trading_calendar": 2 * 1024 * 1024,
    "instruments": 4 * 1024 * 1024,
    "index_daily": 2 * 1024 * 1024,
    "index_components": 8 * 1024 * 1024,
    "index_weights": 4 * 1024 * 1024,
    "index_weights_ex": 8 * 1024 * 1024,
    "stock_daily": 4 * 1024 * 1024,
    "stock_minute": 32 * 1024 * 1024,
    "stock_ex_factor": 8 * 1024 * 1024,
    "stock_split": 4 * 1024 * 1024,
    "financial_income": 32 * 1024 * 1024,
    "financial_balance": 64 * 1024 * 1024,
    "financial_cashflow": 32 * 1024 * 1024,
    "financial_metric": 16 * 1024 * 1024,
    "concept_catalog": 2 * 1024 * 1024,
    "concept_members": 8 * 1024 * 1024,
    "concept_snapshot": 2 * 1024 * 1024,
    "industry_mapping": 2 * 1024 * 1024,
    "industry_members": 2 * 1024 * 1024,
    "industry_snapshot": 4 * 1024 * 1024,
    "sector_snapshot": 2 * 1024 * 1024,
    "tick": 16 * 1024 * 1024,
}

SECTOR_NAMES = {
    "ConsumerDiscretionary": "非必需消费品",
    "ConsumerStaples": "必需消费品",
    "Energy": "能源",
    "Financials": "金融",
    "HealthCare": "医疗保健",
    "Industrials": "工业",
    "InformationTechnology": "信息技术",
    "Materials": "原材料",
    "TelecommunicationServices": "电信服务",
    "Utilities": "公共服务",
}

FINANCIAL_DATASETS = tuple(FINANCIAL_FIELDS_BY_DATASET)


@dataclass(frozen=True)
class RunSummary:
    run_id: str
    status: str
    message: str


class RiceQuantRunner:
    def __init__(
        self,
        settings: RiceQuantSettings,
        *,
        client: RqDataClient | None = None,
        storage: RiceQuantStorage | None = None,
        today: date | None = None,
    ):
        self.settings = settings
        self.client = client or RqDataClient(settings.token)
        self.storage = storage or RiceQuantStorage(settings.database)
        self.today = today or self._completed_data_date(
            datetime.now(ZoneInfo("Asia/Shanghai")), settings.daily_data_ready_time
        )
        self.run_id = f"rq-{datetime.now():%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"
        self.state = StateStore(self.storage, self.run_id)
        self.progress = ProgressReporter(LOGGER, self.run_id)
        self.guard = QuotaGuard(
            settings.quota_min_reserve_bytes, settings.quota_estimate_multiplier
        )
        self.requested_order_book_ids: tuple[str, ...] = ()

    @staticmethod
    def _completed_data_date(as_of: datetime, ready_time: str) -> date:
        hour, minute = (int(part) for part in ready_time.split(":", maxsplit=1))
        if (as_of.hour, as_of.minute) < (hour, minute):
            return as_of.date() - timedelta(days=1)
        return as_of.date()

    def initialize(self) -> None:
        LOGGER.info(
            "initializing run_id=%s database=%s@%s:%s",
            self.run_id,
            self.settings.database.database,
            self.settings.database.host,
            self.settings.database.port,
        )
        self.storage.initialize()
        self.client.initialize()

    def run(
        self,
        mode: str,
        datasets: Iterable[str] | None = None,
        start: date | None = None,
        end: date | None = None,
        instruments: Iterable[str] | None = None,
    ) -> RunSummary:
        self.requested_order_book_ids = tuple(
            sorted({str(value) for value in (instruments or ())})
        )
        selected = self._resolve_datasets(datasets)
        if self.requested_order_book_ids and {
            "stock_daily",
            "stock_minute",
            "tick",
        }.intersection(selected):
            raise ValueError(
                "--instrument is supported for stock_ex_factor/stock_split only; "
                "partial-universe bar partitions are not publishable as all-market data"
            )
        run_started = monotonic()
        LOGGER.info(
            "run_started run_id=%s mode=%s datasets=%s requested_start=%s "
            "requested_end=%s data_through=%s",
            self.run_id,
            mode,
            ",".join(selected),
            start or "auto",
            end or "auto",
            self.today,
        )
        self.initialize()
        with self.storage.distributed_runner_lock(self.run_id):
            self.state.run_event(
                mode, "started", message=f"datasets={','.join(selected)}"
            )
            try:
                trading_dates: list[date] = []
                if "trading_calendar" in selected:
                    calendar_start = self._calendar_start(mode, selected, start)
                    calendar_end = min(end or self.today, self.today)
                    trading_dates = self._sync_calendar(calendar_start, calendar_end)
                instrument_consumers = {
                    "tick",
                    "stock_daily",
                    "stock_minute",
                    "stock_ex_factor",
                    "stock_split",
                    "industry_snapshot",
                    *FINANCIAL_DATASETS,
                }
                if (
                    "instruments" in selected
                    and not instrument_consumers.intersection(selected)
                    and trading_dates
                ):
                    self._sync_instruments(trading_dates[-1])
                if "index_daily" in selected:
                    self._sync_index_daily(mode, trading_dates, start, end)
                if "index_components" in selected:
                    self._sync_index_components(mode, trading_dates, start, end)
                if "index_weights" in selected:
                    self._sync_index_weights(mode, trading_dates, start, end)
                if "index_weights_ex" in selected:
                    self._sync_index_weights_ex(mode, trading_dates, start, end)
                if "stock_daily" in selected:
                    self._sync_stock_bars(
                        "stock_daily", mode, trading_dates, start, end
                    )
                if "stock_minute" in selected:
                    self._sync_stock_bars(
                        "stock_minute", mode, trading_dates, start, end
                    )
                if "stock_ex_factor" in selected:
                    self._sync_stock_factors(
                        "stock_ex_factor", mode, trading_dates, start, end
                    )
                if "stock_split" in selected:
                    self._sync_stock_factors(
                        "stock_split", mode, trading_dates, start, end
                    )
                for dataset in FINANCIAL_DATASETS:
                    if dataset in selected:
                        self._sync_financials(dataset, mode, start, end)
                if "concept_catalog" in selected:
                    self._sync_concept_catalog(mode, start, end)
                if "concept_members" in selected:
                    self._sync_concept_members(mode, start, end)
                if "concept_snapshot" in selected:
                    self._sync_concept_snapshot(mode, trading_dates, start, end)
                if "industry_mapping" in selected:
                    self._sync_industry_mapping(trading_dates, end)
                if "industry_members" in selected:
                    self._sync_industry_members(mode, start, end)
                if "industry_snapshot" in selected:
                    self._sync_industry_snapshot(mode, trading_dates, start, end)
                if "sector_snapshot" in selected:
                    self._sync_sector_snapshot(mode, trading_dates, end)
                if "tick" in selected:
                    self._sync_tick(mode, trading_dates, start, end)
            except QuotaPaused as exc:
                self.progress.finish("quota_paused")
                LOGGER.warning(
                    "run_quota_paused run_id=%s elapsed_seconds=%.1f reason=%s",
                    self.run_id,
                    monotonic() - run_started,
                    exc,
                )
                self.state.run_event(mode, "quota_paused", message=str(exc))
                return RunSummary(self.run_id, "quota_paused", str(exc))
            except Exception as exc:
                self.progress.finish("failed")
                LOGGER.exception(
                    "run_failed run_id=%s elapsed_seconds=%.1f",
                    self.run_id,
                    monotonic() - run_started,
                )
                self.state.run_event(
                    mode, "failed", message=f"{type(exc).__name__}: {exc}"
                )
                raise
            self.state.run_event(mode, "complete")
            self.progress.finish("complete")
            LOGGER.info(
                "run_complete run_id=%s mode=%s elapsed_seconds=%.1f",
                self.run_id,
                mode,
                monotonic() - run_started,
            )
            return RunSummary(self.run_id, "complete", "all selected datasets complete")

    def _calendar_start(
        self, mode: str, selected: list[str], requested_start: date | None
    ) -> date:
        if requested_start:
            return requested_start
        selected_starts = [
            self._dataset_history_start(dataset)
            for dataset in selected
            if dataset not in {"trading_calendar", "instruments"}
        ]
        history_start = min(
            selected_starts,
            default=date.fromisoformat(self.settings.history_start_date),
        )
        if mode in {"bootstrap", "backfill"}:
            return history_start
        completed_ends: list[date] = []
        for dataset in selected:
            if dataset in {"trading_calendar", "instruments"}:
                continue
            if dataset.startswith("index_"):
                completed_ends.extend(
                    value
                    for index_id in self._dataset_index_ids(dataset)
                    if (
                        value := self.state.latest_completed_end(
                            dataset, f"{index_id}:"
                        )
                    )
                    is not None
                )
            elif (value := self.state.latest_completed_end(dataset)) is not None:
                completed_ends.append(value)
        if not completed_ends:
            return max(
                history_start,
                self.today
                - timedelta(days=max(62, self.settings.tick_lookback_calendar_days)),
            )
        # Use the least advanced dataset so a quota-created backlog is never
        # hidden by another dataset which has already reached today.
        rescan_days = max(DATASET_SPECS[name].mutable_days for name in selected)
        return max(history_start, min(completed_ends) - timedelta(days=rescan_days))

    def _dataset_history_start(self, dataset: str) -> date:
        if dataset == "index_weights_ex":
            return date.fromisoformat(self.settings.index_weights_ex_start_date)
        if dataset == "stock_daily":
            return date.fromisoformat(self.settings.stock_daily_start_date)
        if dataset == "stock_minute":
            return date.fromisoformat(self.settings.stock_minute_start_date)
        if dataset in {"stock_ex_factor", "stock_split"}:
            return date.fromisoformat(self.settings.factor_start_date)
        if dataset in FINANCIAL_DATASETS:
            return date.fromisoformat(self.settings.financial_start_date)
        if dataset in {
            "concept_snapshot",
            "industry_snapshot",
            "sector_snapshot",
        }:
            return self.today - timedelta(
                days=self.settings.classification_lookback_calendar_days - 1
            )
        if dataset.startswith("concept_"):
            return date.fromisoformat(self.settings.concept_start_date)
        return date.fromisoformat(self.settings.history_start_date)

    def _dataset_index_ids(self, dataset: str) -> tuple[str, ...]:
        if dataset == "index_weights_ex":
            return INDEX_WEIGHTS_EX_INDEXES
        return self.settings.indexes

    @staticmethod
    def _completed_slice_covers(
        completed: dict[str, tuple[date, date]], planned: DateSlice
    ) -> bool:
        bounds = completed.get(planned.slice_key)
        return bool(bounds and bounds[0] <= planned.start and bounds[1] >= planned.end)

    @staticmethod
    def _batches(values: list[str], size: int) -> Iterable[list[str]]:
        for position in range(0, len(values), size):
            yield values[position : position + size]

    def _resolve_datasets(self, datasets: Iterable[str] | None) -> list[str]:
        requested = set(
            datasets
            or (
                "index_daily",
                "index_components",
                "index_weights",
                "index_weights_ex",
                "tick",
            )
        )
        unknown = requested - DATASET_SPECS.keys()
        if unknown:
            raise ValueError(f"unknown RiceQuant datasets: {sorted(unknown)}")
        financial_only = bool(requested) and requested <= set(FINANCIAL_DATASETS)
        if requested - {"trading_calendar"} and not financial_only:
            requested.add("trading_calendar")
        pending_dependencies = list(requested)
        while pending_dependencies:
            name = pending_dependencies.pop()
            for dependency in DATASET_SPECS[name].dependencies:
                if dependency not in requested:
                    requested.add(dependency)
                    pending_dependencies.append(dependency)
        # Financials use the instrument universe but their report-period
        # bounds do not depend on exchange trading dates.
        if financial_only:
            requested.discard("trading_calendar")
        order = [
            "trading_calendar",
            "instruments",
            "index_daily",
            "index_components",
            "index_weights",
            "index_weights_ex",
            "stock_daily",
            "stock_minute",
            "stock_ex_factor",
            "stock_split",
            "financial_income",
            "financial_balance",
            "financial_cashflow",
            "financial_metric",
            "concept_catalog",
            "concept_members",
            "concept_snapshot",
            "industry_mapping",
            "industry_members",
            "industry_snapshot",
            "sector_snapshot",
            "tick",
        ]
        return [name for name in order if name in requested]

    def _fetch(
        self, dataset: str, slice_key: str, operation: Callable[[], T]
    ) -> tuple[T, int]:
        self.progress.fetch_started(dataset, slice_key)
        try:
            before = self.client.quota()
            estimate = self.storage.estimate_bytes(dataset, DEFAULT_ESTIMATES[dataset])
            self.guard.check(before, estimate, f"{dataset}:{slice_key}")
            result = operation()
            after = self.client.quota()
            consumed = max(0, after.bytes_used - before.bytes_used)
            row_count = len(result) if hasattr(result, "__len__") else 0
            self.storage.record_quota_observation(
                dataset, slice_key, consumed, row_count
            )
        except QuotaPaused as exc:
            self.progress.fetch_paused(dataset, slice_key, exc)
            raise
        except Exception as exc:
            self.progress.fetch_failed(dataset, slice_key, exc)
            raise
        self.progress.fetch_completed(
            dataset, slice_key, rows=row_count, quota_bytes=consumed
        )
        return result, consumed

    def _sync_calendar(self, start: date, end: date) -> list[date]:
        spec = DATASET_SPECS["trading_calendar"]
        started = monotonic()
        LOGGER.info("dataset_started dataset=%s range=%s..%s", spec.name, start, end)
        trading_dates, consumed = self._fetch(
            spec.name, f"{start}:{end}", lambda: self.client.trading_dates(start, end)
        )
        trading_set = set(trading_dates)
        for year in range(start.year, end.year + 1):
            part_start = max(start, date(year, 1, 1))
            part_end = min(end, date(year, 12, 31))
            values = pd.date_range(part_start, part_end, freq="D").date
            frame = pd.DataFrame(
                {
                    "calendar_date": values,
                    "is_trading_day": [
                        1 if value in trading_set else 0 for value in values
                    ],
                }
            )
            frame = conform(
                add_metadata(frame, "get_trading_dates", self.run_id),
                [
                    "calendar_date",
                    "is_trading_day",
                    "_source",
                    "_api_name",
                    "_batch_id",
                    "_ingest_time",
                    "_record_hash",
                ],
            )
            result = self.storage.publish_partition(
                spec,
                str(year),
                frame,
                replace_range=("calendar_date", part_start, part_end),
            )
            self.state.coverage_event(
                spec,
                f"{year}",
                "complete",
                range_start=str(part_start),
                range_end=str(part_end),
                partition_value=str(year),
                row_count=result.row_count,
                content_hash=result.content_hash,
                quota_bytes_used=consumed,
            )
        LOGGER.info(
            "dataset_complete dataset=%s calendar_days=%d trading_days=%d "
            "quota_bytes=%d elapsed_seconds=%.1f",
            spec.name,
            (end - start).days + 1,
            len(trading_dates),
            consumed,
            monotonic() - started,
        )
        return trading_dates

    def _date_bounds(
        self,
        mode: str,
        trading_dates: list[date],
        start: date | None,
        end: date | None,
        dataset: str,
        prefix: str,
    ) -> tuple[date, date] | None:
        if not trading_dates:
            return None
        upper = min(end or trading_dates[-1], trading_dates[-1])
        if start:
            lower = start
        elif mode in {"bootstrap", "backfill"}:
            lower = self._dataset_history_start(dataset)
        else:
            last = self.state.latest_completed_end(dataset, prefix)
            rescan_days = DATASET_SPECS[dataset].mutable_days
            lower = incremental_start(last, trading_dates[0], rescan_days=rescan_days)
        return (lower, upper) if lower <= upper else None

    def _sync_index_daily(
        self, mode: str, trading_dates: list[date], start: date | None, end: date | None
    ) -> None:
        spec = DATASET_SPECS["index_daily"]
        dataset_started = monotonic()
        LOGGER.info(
            "dataset_started dataset=%s indexes=%d mode=%s",
            spec.name,
            len(self.settings.indexes),
            mode,
        )
        complete = self.state.completed_slice_ranges(spec.name)
        for index_id in self.settings.indexes:
            bounds = self._date_bounds(
                mode, trading_dates, start, end, spec.name, f"{index_id}:"
            )
            if not bounds:
                continue
            slices = list(
                month_slices(*bounds, prefix=f"{index_id}:")
                if mode in {"bootstrap", "backfill"}
                else daily_slices(
                    (
                        value
                        for value in trading_dates
                        if bounds[0] <= value <= bounds[1]
                    ),
                    prefix=f"{index_id}:",
                )
            )
            pending = [
                slice_
                for slice_ in slices
                if not (
                    mode == "bootstrap"
                    and self._completed_slice_covers(complete, slice_)
                )
            ]
            index_started = monotonic()
            total_rows = 0
            total_quota = 0
            LOGGER.info(
                "index_started dataset=%s index=%s range=%s..%s slices=%d skipped=%d",
                spec.name,
                index_id,
                bounds[0],
                bounds[1],
                len(pending),
                len(slices) - len(pending),
            )
            for position, slice_ in enumerate(pending, start=1):
                raw, consumed = self._fetch(
                    spec.name,
                    slice_.slice_key,
                    lambda i=index_id, s=slice_: self.client.index_daily(
                        i, s.start, s.end
                    ),
                )
                frame = index_daily_frame(raw, index_id, self.run_id)
                partition = f"({quote_string(index_id)}, {slice_.start:%Y%m})"
                result = self.storage.publish_partition(
                    spec,
                    partition,
                    frame,
                    replace_range=("trading_date", slice_.start, slice_.end),
                )
                self.state.coverage_event(
                    spec,
                    slice_.slice_key,
                    "complete",
                    range_start=str(slice_.start),
                    range_end=str(slice_.end),
                    partition_value=partition,
                    row_count=result.row_count,
                    content_hash=result.content_hash,
                    quota_bytes_used=consumed,
                    mutable_until=slice_.end + timedelta(days=spec.mutable_days),
                )
                total_rows += result.row_count
                total_quota += consumed
                if position == 1 or position % 50 == 0 or position == len(pending):
                    LOGGER.info(
                        "index_progress dataset=%s index=%s completed=%d/%d "
                        "slice=%s rows=%d elapsed_seconds=%.1f",
                        spec.name,
                        index_id,
                        position,
                        len(pending),
                        slice_.slice_key,
                        total_rows,
                        monotonic() - index_started,
                    )
            LOGGER.info(
                "index_complete dataset=%s index=%s slices=%d rows=%d "
                "quota_bytes=%d elapsed_seconds=%.1f",
                spec.name,
                index_id,
                len(pending),
                total_rows,
                total_quota,
                monotonic() - index_started,
            )
        LOGGER.info(
            "dataset_complete dataset=%s elapsed_seconds=%.1f",
            spec.name,
            monotonic() - dataset_started,
        )

    def _sync_index_components(
        self, mode: str, trading_dates: list[date], start: date | None, end: date | None
    ) -> None:
        spec = DATASET_SPECS["index_components"]
        dataset_started = monotonic()
        LOGGER.info(
            "dataset_started dataset=%s indexes=%d mode=%s",
            spec.name,
            len(self.settings.indexes),
            mode,
        )
        complete = self.state.completed_slice_ranges(spec.name)
        for index_id in self.settings.indexes:
            bounds = self._date_bounds(
                mode, trading_dates, start, end, spec.name, f"{index_id}:"
            )
            if not bounds:
                continue
            slices = list(
                month_slices(*bounds, prefix=f"{index_id}:")
                if mode in {"bootstrap", "backfill"}
                else daily_slices(
                    (
                        value
                        for value in trading_dates
                        if bounds[0] <= value <= bounds[1]
                    ),
                    prefix=f"{index_id}:",
                )
            )
            pending = [
                slice_
                for slice_ in slices
                if not (
                    mode == "bootstrap"
                    and self._completed_slice_covers(complete, slice_)
                )
            ]
            index_started = monotonic()
            total_rows = 0
            total_quota = 0
            LOGGER.info(
                "index_started dataset=%s index=%s range=%s..%s slices=%d skipped=%d",
                spec.name,
                index_id,
                bounds[0],
                bounds[1],
                len(pending),
                len(slices) - len(pending),
            )
            for position, slice_ in enumerate(pending, start=1):
                raw, consumed = self._fetch(
                    spec.name,
                    slice_.slice_key,
                    lambda i=index_id, s=slice_: self.client.index_components(
                        i, s.start, s.end
                    ),
                )
                frame = index_components_frame(raw, index_id, self.run_id, slice_.start)
                partition = f"({quote_string(index_id)}, {slice_.start:%Y%m})"
                result = self.storage.publish_partition(
                    spec,
                    partition,
                    frame,
                    replace_range=("trading_date", slice_.start, slice_.end),
                )
                self.state.coverage_event(
                    spec,
                    slice_.slice_key,
                    "complete",
                    range_start=str(slice_.start),
                    range_end=str(slice_.end),
                    partition_value=partition,
                    row_count=result.row_count,
                    content_hash=result.content_hash,
                    quota_bytes_used=consumed,
                    mutable_until=slice_.end + timedelta(days=spec.mutable_days),
                )
                total_rows += result.row_count
                total_quota += consumed
                if position == 1 or position % 50 == 0 or position == len(pending):
                    LOGGER.info(
                        "index_progress dataset=%s index=%s completed=%d/%d "
                        "slice=%s rows=%d elapsed_seconds=%.1f",
                        spec.name,
                        index_id,
                        position,
                        len(pending),
                        slice_.slice_key,
                        total_rows,
                        monotonic() - index_started,
                    )
            LOGGER.info(
                "index_complete dataset=%s index=%s slices=%d rows=%d "
                "quota_bytes=%d elapsed_seconds=%.1f",
                spec.name,
                index_id,
                len(pending),
                total_rows,
                total_quota,
                monotonic() - index_started,
            )
        LOGGER.info(
            "dataset_complete dataset=%s elapsed_seconds=%.1f",
            spec.name,
            monotonic() - dataset_started,
        )

    def _sync_index_weights(
        self, mode: str, trading_dates: list[date], start: date | None, end: date | None
    ) -> None:
        spec = DATASET_SPECS["index_weights"]
        dataset_started = monotonic()
        LOGGER.info(
            "dataset_started dataset=%s indexes=%d mode=%s",
            spec.name,
            len(self.settings.indexes),
            mode,
        )
        complete = self.state.completed_slice_ranges(spec.name)
        for index_id in self.settings.indexes:
            bounds = self._date_bounds(
                mode, trading_dates, start, end, spec.name, f"{index_id}:"
            )
            if not bounds:
                continue
            eligible = [
                value for value in trading_dates if bounds[0] <= value <= bounds[1]
            ]
            # RQData documents index weights as monthly data. Only closed
            # calendar months get a canonical snapshot, avoiding a new copy on
            # every trading day of the current month.
            snapshots = [
                value
                for value in month_end_trading_dates(eligible)
                if (value.year, value.month) < (bounds[1].year, bounds[1].month)
                or bounds[1].day
                == calendar.monthrange(bounds[1].year, bounds[1].month)[1]
            ]
            slices = list(daily_slices(snapshots, prefix=f"{index_id}:"))
            pending = [
                slice_
                for slice_ in slices
                if not (
                    mode == "bootstrap"
                    and self._completed_slice_covers(complete, slice_)
                )
            ]
            index_started = monotonic()
            total_rows = 0
            total_quota = 0
            LOGGER.info(
                "index_started dataset=%s index=%s range=%s..%s slices=%d skipped=%d",
                spec.name,
                index_id,
                bounds[0],
                bounds[1],
                len(pending),
                len(slices) - len(pending),
            )
            for position, slice_ in enumerate(pending, start=1):
                raw, consumed = self._fetch(
                    spec.name,
                    slice_.slice_key,
                    lambda i=index_id, d=slice_.start: self.client.index_weights(i, d),
                )
                frame = index_weights_frame(raw, index_id, self.run_id, slice_.start)
                partition = f"({quote_string(index_id)}, {slice_.start:%Y%m})"
                result = self.storage.publish_partition(
                    spec,
                    partition,
                    frame,
                    replace_keys=("index_id", "snapshot_date"),
                    replace_values=(index_id, slice_.start),
                )
                self.state.coverage_event(
                    spec,
                    slice_.slice_key,
                    "complete",
                    range_start=str(slice_.start),
                    range_end=str(slice_.end),
                    partition_value=partition,
                    row_count=result.row_count,
                    content_hash=result.content_hash,
                    quota_bytes_used=consumed,
                    mutable_until=slice_.end + timedelta(days=spec.mutable_days),
                )
                total_rows += result.row_count
                total_quota += consumed
                if position == 1 or position % 50 == 0 or position == len(pending):
                    LOGGER.info(
                        "index_progress dataset=%s index=%s completed=%d/%d "
                        "slice=%s rows=%d elapsed_seconds=%.1f",
                        spec.name,
                        index_id,
                        position,
                        len(pending),
                        slice_.slice_key,
                        total_rows,
                        monotonic() - index_started,
                    )
            LOGGER.info(
                "index_complete dataset=%s index=%s slices=%d rows=%d "
                "quota_bytes=%d elapsed_seconds=%.1f",
                spec.name,
                index_id,
                len(pending),
                total_rows,
                total_quota,
                monotonic() - index_started,
            )
        LOGGER.info(
            "dataset_complete dataset=%s elapsed_seconds=%.1f",
            spec.name,
            monotonic() - dataset_started,
        )

    def _sync_index_weights_ex(
        self, mode: str, trading_dates: list[date], start: date | None, end: date | None
    ) -> None:
        spec = DATASET_SPECS["index_weights_ex"]
        index_ids = INDEX_WEIGHTS_EX_INDEXES
        dataset_started = monotonic()
        LOGGER.info(
            "dataset_started dataset=%s indexes=%d mode=%s",
            spec.name,
            len(index_ids),
            mode,
        )
        complete = self.state.completed_slice_ranges(spec.name)
        for index_id in index_ids:
            bounds = self._date_bounds(
                mode, trading_dates, start, end, spec.name, f"{index_id}:"
            )
            if not bounds:
                continue
            slices = list(
                month_slices(*bounds, prefix=f"{index_id}:")
                if mode in {"bootstrap", "backfill"}
                else daily_slices(
                    (
                        value
                        for value in trading_dates
                        if bounds[0] <= value <= bounds[1]
                    ),
                    prefix=f"{index_id}:",
                )
            )
            pending = [
                slice_
                for slice_ in slices
                if not (
                    mode == "bootstrap"
                    and self._completed_slice_covers(complete, slice_)
                )
            ]
            index_started = monotonic()
            total_rows = 0
            total_quota = 0
            LOGGER.info(
                "index_started dataset=%s index=%s range=%s..%s slices=%d skipped=%d",
                spec.name,
                index_id,
                bounds[0],
                bounds[1],
                len(pending),
                len(slices) - len(pending),
            )
            for position, slice_ in enumerate(pending, start=1):
                raw, consumed = self._fetch(
                    spec.name,
                    slice_.slice_key,
                    lambda i=index_id, s=slice_: self.client.index_weights_ex(
                        i, s.start, s.end
                    ),
                )
                frame = index_weights_ex_frame(raw, index_id, self.run_id)
                partition = f"({quote_string(index_id)}, {slice_.start:%Y%m})"
                result = self.storage.publish_partition(
                    spec,
                    partition,
                    frame,
                    replace_range=("trading_date", slice_.start, slice_.end),
                )
                self.state.coverage_event(
                    spec,
                    slice_.slice_key,
                    "complete",
                    range_start=str(slice_.start),
                    range_end=str(slice_.end),
                    partition_value=partition,
                    row_count=result.row_count,
                    content_hash=result.content_hash,
                    quota_bytes_used=consumed,
                    mutable_until=slice_.end + timedelta(days=spec.mutable_days),
                )
                total_rows += result.row_count
                total_quota += consumed
                if position == 1 or position % 25 == 0 or position == len(pending):
                    LOGGER.info(
                        "index_progress dataset=%s index=%s completed=%d/%d "
                        "slice=%s rows=%d elapsed_seconds=%.1f",
                        spec.name,
                        index_id,
                        position,
                        len(pending),
                        slice_.slice_key,
                        total_rows,
                        monotonic() - index_started,
                    )
            LOGGER.info(
                "index_complete dataset=%s index=%s slices=%d rows=%d "
                "quota_bytes=%d elapsed_seconds=%.1f",
                spec.name,
                index_id,
                len(pending),
                total_rows,
                total_quota,
                monotonic() - index_started,
            )
        LOGGER.info(
            "dataset_complete dataset=%s elapsed_seconds=%.1f",
            spec.name,
            monotonic() - dataset_started,
        )

    def _sync_concept_catalog(
        self, mode: str, start: date | None, end: date | None
    ) -> None:
        spec = DATASET_SPECS["concept_catalog"]
        lower = start or self._dataset_history_start(spec.name)
        upper = min(end or self.today, self.today)
        complete = self.state.completed_slice_ranges(spec.name)
        years = list(range(lower.year, upper.year + 1))
        pending_years = [
            year
            for year in years
            if not (
                mode == "bootstrap"
                and self._completed_slice_covers(
                    complete,
                    DateSlice(
                        max(lower, date(year, 1, 1)),
                        min(upper, date(year, 12, 31)),
                        str(year),
                    ),
                )
            )
        ]
        if not pending_years:
            LOGGER.info("dataset_complete dataset=%s reason=all_slices_complete", spec.name)
            return
        fetch_start = max(lower, date(min(pending_years), 1, 1))
        fetch_end = min(upper, date(max(pending_years), 12, 31))
        raw, consumed = self._fetch(
            spec.name,
            f"{fetch_start}:{fetch_end}",
            lambda: self.client.concept_catalog(fetch_start, fetch_end),
        )
        frame = concept_catalog_frame(raw, self.run_id)
        for year in pending_years:
            part_start = max(lower, date(year, 1, 1))
            part_end = min(upper, date(year, 12, 31))
            part = frame[
                frame["inclusion_date"].map(
                    lambda value, y=year: bool(value) and value.year == y
                )
            ].copy()
            result = self.storage.publish_partition(
                spec,
                str(year),
                part,
                replace_range=("inclusion_date", part_start, part_end),
            )
            self.state.coverage_event(
                spec,
                str(year),
                "complete",
                range_start=str(part_start),
                range_end=str(part_end),
                partition_value=str(year),
                row_count=result.row_count,
                content_hash=result.content_hash,
                quota_bytes_used=consumed // max(1, len(pending_years)),
            )
        LOGGER.info(
            "dataset_complete dataset=%s concepts=%d years=%d quota_bytes=%d",
            spec.name,
            len(frame),
            len(pending_years),
            consumed,
        )

    def _sync_concept_members(
        self, mode: str, start: date | None, end: date | None
    ) -> None:
        spec = DATASET_SPECS["concept_members"]
        lower = start or self._dataset_history_start(spec.name)
        upper = min(end or self.today, self.today)
        catalog = self.storage.client.query_df(
            f"SELECT DISTINCT concept_name FROM {self.storage.db}.`ricequant_concept_catalog` "
            f"WHERE inclusion_date <= toDate({quote_string(str(upper))}) ORDER BY concept_name"
        )
        concepts = catalog["concept_name"].astype(str).tolist() if not catalog.empty else []
        frames: list[pd.DataFrame] = []
        total_quota = 0
        batches = list(self._batches(concepts, 100))
        for position, batch in enumerate(batches, start=1):
            raw, consumed = self._fetch(
                spec.name,
                f"{lower}:{upper}:{position}",
                lambda values=batch: self.client.concept_members(values, lower, upper),
            )
            frames.append(concept_member_frame(raw, self.run_id))
            total_quota += consumed
            LOGGER.info(
                "concept_progress dataset=%s batch=%d/%d concepts=%d quota_bytes=%d",
                spec.name,
                position,
                len(batches),
                min(position * 100, len(concepts)),
                total_quota,
            )
        frame = (
            pd.concat(frames, ignore_index=True)
            if frames
            else concept_member_frame(pd.DataFrame(), self.run_id)
        )
        frame = frame.drop_duplicates(list(spec.primary_key))
        for year in range(lower.year, upper.year + 1):
            part_start = max(lower, date(year, 1, 1))
            part_end = min(upper, date(year, 12, 31))
            part = frame[
                frame["inclusion_date"].map(
                    lambda value, y=year: bool(value) and value.year == y
                )
            ].copy()
            result = self.storage.publish_partition(
                spec,
                str(year),
                part,
                replace_range=("inclusion_date", part_start, part_end),
            )
            self.state.coverage_event(
                spec,
                str(year),
                "complete",
                range_start=str(part_start),
                range_end=str(part_end),
                partition_value=str(year),
                row_count=result.row_count,
                content_hash=result.content_hash,
                quota_bytes_used=total_quota
                // max(1, upper.year - lower.year + 1),
            )
        LOGGER.info(
            "dataset_complete dataset=%s concepts=%d memberships=%d quota_bytes=%d",
            spec.name,
            len(concepts),
            len(frame),
            total_quota,
        )

    def _sync_concept_snapshot(
        self,
        mode: str,
        trading_dates: list[date],
        start: date | None,
        end: date | None,
    ) -> None:
        if not trading_dates:
            return
        spec = DATASET_SPECS["concept_snapshot"]
        if start:
            snapshot_dates = [
                value
                for value in trading_dates
                if start <= value <= min(end or trading_dates[-1], trading_dates[-1])
            ]
        else:
            upper = min(end or trading_dates[-1], trading_dates[-1])
            lower = upper - timedelta(
                days=self.settings.classification_lookback_calendar_days - 1
            )
            snapshot_dates = [value for value in trading_dates if lower <= value <= upper]
        observation_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        for snapshot_date in snapshot_dates:
            slice_key = f"{observation_date}:{snapshot_date}"
            latest = self.state.latest(spec.name, slice_key)
            if latest and latest.status == "complete" and mode != "backfill":
                continue
            concepts, catalog_quota = self._fetch(
                spec.name,
                f"{snapshot_date}:catalog",
                lambda value=snapshot_date: self.client.concept_names(value),
            )
            frames: list[pd.DataFrame] = []
            total_quota = catalog_quota
            concepts = sorted({str(value) for value in concepts})
            for position, concept_name in enumerate(concepts, start=1):
                members, consumed = self._fetch(
                    spec.name,
                    f"{snapshot_date}:{concept_name}",
                    lambda name=concept_name, value=snapshot_date: self.client.concept_snapshot(
                        name, value
                    ),
                )
                frames.append(
                    concept_snapshot_frame(
                        members,
                        concept_name,
                        snapshot_date,
                        observation_date,
                        datetime.now(ZoneInfo("Asia/Shanghai")),
                        self.run_id,
                    )
                )
                total_quota += consumed
                if position == 1 or position % 100 == 0 or position == len(concepts):
                    LOGGER.info(
                        "snapshot_progress dataset=%s date=%s concepts=%d/%d rows=%d quota_bytes=%d",
                        spec.name,
                        snapshot_date,
                        position,
                        len(concepts),
                        sum(len(value) for value in frames),
                        total_quota,
                    )
            frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            if not frame.empty:
                # A snapshot is published atomically, so its PIT availability time
                # must also be atomic.  Per-request timestamps would let downstream
                # PIT joins observe a partially assembled classification snapshot.
                frame["observed_at"] = datetime.now(ZoneInfo("Asia/Shanghai"))
                frame = frame.drop_duplicates(list(spec.primary_key))
            partition = (
                f"tuple(toDate({quote_string(str(observation_date))}), "
                f"toDate({quote_string(str(snapshot_date))}))"
            )
            result = self.storage.publish_partition(spec, partition, frame)
            self.state.coverage_event(
                spec,
                slice_key,
                "complete",
                range_start=slice_key,
                range_end=slice_key,
                partition_value=partition,
                row_count=result.row_count,
                content_hash=result.content_hash,
                quota_bytes_used=total_quota,
            )

    def _sync_industry_mapping(
        self, trading_dates: list[date], end: date | None
    ) -> None:
        if not trading_dates:
            return
        spec = DATASET_SPECS["industry_mapping"]
        snapshot_date = min(end or trading_dates[-1], trading_dates[-1])
        slice_key = str(snapshot_date)
        latest = self.state.latest(spec.name, slice_key)
        if latest and latest.status == "complete":
            return
        raw, consumed = self._fetch(
            spec.name,
            f"citics_2019:{snapshot_date}",
            lambda: self.client.industry_mapping(snapshot_date),
        )
        frame = industry_mapping_frame(
            raw, snapshot_date, "citics_2019", self.run_id
        )
        result = self.storage.publish_partition(
            spec, quote_string(slice_key), frame
        )
        self.state.coverage_event(
            spec,
            slice_key,
            "complete",
            range_start=slice_key,
            range_end=slice_key,
            partition_value=quote_string(slice_key),
            row_count=result.row_count,
            content_hash=result.content_hash,
            quota_bytes_used=consumed,
        )

    def _sync_industry_members(
        self, mode: str, start: date | None, end: date | None
    ) -> None:
        spec = DATASET_SPECS["industry_members"]
        lower = start or date(2019, 1, 1)
        upper = min(end or self.today, self.today)
        mapping = self.storage.client.query_df(
            f"SELECT * FROM {self.storage.db}.`ricequant_industry_mapping` "
            "WHERE snapshot_date = (SELECT max(snapshot_date) FROM "
            f"{self.storage.db}.`ricequant_industry_mapping`)"
        )
        definitions: list[tuple[int, str, str]] = []
        for level, prefix in ((1, "first"), (2, "second"), (3, "third")):
            code_column = f"{prefix}_industry_code"
            name_column = f"{prefix}_industry_name"
            if code_column in mapping:
                values = mapping[[code_column, name_column]].drop_duplicates()
                definitions.extend(
                    (level, str(row[code_column]), str(row[name_column]))
                    for _, row in values.iterrows()
                    if str(row[code_column])
                )
        frames: list[pd.DataFrame] = []
        total_quota = 0
        for position, (level, code, name) in enumerate(definitions, start=1):
            raw, consumed = self._fetch(
                spec.name,
                f"citics_2019:{level}:{code}",
                lambda c=code, value=level: self.client.industry_changes(c, value),
            )
            frames.append(
                industry_member_frame(
                    raw, "citics_2019", level, code, name, self.run_id
                )
            )
            total_quota += consumed
            if position == 1 or position % 50 == 0 or position == len(definitions):
                LOGGER.info(
                    "industry_progress dataset=%s industries=%d/%d quota_bytes=%d",
                    spec.name,
                    position,
                    len(definitions),
                    total_quota,
                )
        frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if not frame.empty:
            frame = frame.drop_duplicates(list(spec.primary_key))
        for year in range(lower.year, upper.year + 1):
            part_start = max(lower, date(year, 1, 1))
            part_end = min(upper, date(year, 12, 31))
            part = frame[
                frame["start_date"].map(
                    lambda value, y=year: bool(value) and value.year == y
                )
            ].copy() if not frame.empty else frame.copy()
            result = self.storage.publish_partition(
                spec,
                str(year),
                part,
                replace_range=("start_date", part_start, part_end),
            )
            self.state.coverage_event(
                spec,
                str(year),
                "complete",
                range_start=str(part_start),
                range_end=str(part_end),
                partition_value=str(year),
                row_count=result.row_count,
                content_hash=result.content_hash,
                quota_bytes_used=total_quota
                // max(1, upper.year - lower.year + 1),
            )

    def _sync_industry_snapshot(
        self,
        mode: str,
        trading_dates: list[date],
        start: date | None,
        end: date | None,
    ) -> None:
        if not trading_dates:
            return
        spec = DATASET_SPECS["industry_snapshot"]
        if start:
            snapshot_dates = [
                value
                for value in trading_dates
                if start <= value <= min(end or trading_dates[-1], trading_dates[-1])
            ]
        else:
            upper = min(end or trading_dates[-1], trading_dates[-1])
            lower = upper - timedelta(
                days=self.settings.classification_lookback_calendar_days - 1
            )
            snapshot_dates = [value for value in trading_dates if lower <= value <= upper]
        observation_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        for snapshot_date in snapshot_dates:
            slice_key = f"{observation_date}:{snapshot_date}"
            latest = self.state.latest(spec.name, slice_key)
            if latest and latest.status == "complete" and mode != "backfill":
                continue
            instruments = self._sync_instruments(snapshot_date)
            universe = self._active_order_book_ids(instruments, snapshot_date)
            frames: list[pd.DataFrame] = []
            total_quota = 0
            batches = list(self._batches(universe, self.settings.stock_daily_batch_size))
            for position, batch in enumerate(batches, start=1):
                raw, consumed = self._fetch(
                    spec.name,
                    f"citics_2019:{snapshot_date}:{position}",
                    lambda ids=batch: self.client.citics_industries(ids, snapshot_date),
                )
                frames.append(
                    citics_industry_snapshot_frame(
                        raw,
                        snapshot_date,
                        observation_date,
                        datetime.now(ZoneInfo("Asia/Shanghai")),
                        self.run_id,
                    )
                )
                total_quota += consumed
                for level in (1, 2, 3):
                    raw, consumed = self._fetch(
                        spec.name,
                        f"shenwan:{level}:{snapshot_date}:{position}",
                        lambda ids=batch, value=level: self.client.shenwan_industries(
                            ids, snapshot_date, value
                        ),
                    )
                    frames.append(
                        shenwan_industry_snapshot_frame(
                            raw,
                            snapshot_date,
                            observation_date,
                            datetime.now(ZoneInfo("Asia/Shanghai")),
                            level,
                            self.run_id,
                        )
                    )
                    total_quota += consumed
                LOGGER.info(
                    "snapshot_progress dataset=%s date=%s batches=%d/%d quota_bytes=%d",
                    spec.name,
                    snapshot_date,
                    position,
                    len(batches),
                    total_quota,
                )
            frame = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            if not frame.empty:
                frame["observed_at"] = datetime.now(ZoneInfo("Asia/Shanghai"))
                frame = frame.drop_duplicates(list(spec.primary_key))
            partition = (
                f"tuple(toDate({quote_string(str(observation_date))}), "
                f"toDate({quote_string(str(snapshot_date))}))"
            )
            result = self.storage.publish_partition(spec, partition, frame)
            self.state.coverage_event(
                spec,
                slice_key,
                "complete",
                range_start=slice_key,
                range_end=slice_key,
                partition_value=partition,
                row_count=result.row_count,
                content_hash=result.content_hash,
                quota_bytes_used=total_quota,
            )

    def _sync_sector_snapshot(
        self, mode: str, trading_dates: list[date], end: date | None
    ) -> None:
        if not trading_dates:
            return
        spec = DATASET_SPECS["sector_snapshot"]
        latest_trading_date = trading_dates[-1]
        if end and end < latest_trading_date:
            raise ValueError(
                "RQData sector() has no historical date parameter; historical sector snapshots cannot be backfilled"
            )
        observation_date = datetime.now(ZoneInfo("Asia/Shanghai")).date()
        slice_key = str(observation_date)
        latest = self.state.latest(spec.name, slice_key)
        if latest and latest.status == "complete" and mode != "backfill":
            return
        frames: list[pd.DataFrame] = []
        total_quota = 0
        for code, name in SECTOR_NAMES.items():
            members, consumed = self._fetch(
                spec.name,
                f"{observation_date}:{code}",
                lambda value=code: self.client.sector_members(value),
            )
            frames.append(
                sector_snapshot_frame(
                    members,
                    code,
                    name,
                    observation_date,
                    datetime.now(ZoneInfo("Asia/Shanghai")),
                    self.run_id,
                )
            )
            total_quota += consumed
        frame = pd.concat(frames, ignore_index=True).drop_duplicates(
            list(spec.primary_key)
        )
        frame["observed_at"] = datetime.now(ZoneInfo("Asia/Shanghai"))
        result = self.storage.publish_partition(
            spec, quote_string(slice_key), frame
        )
        self.state.coverage_event(
            spec,
            slice_key,
            "complete",
            range_start=slice_key,
            range_end=slice_key,
            partition_value=quote_string(slice_key),
            row_count=result.row_count,
            content_hash=result.content_hash,
            quota_bytes_used=total_quota,
        )

    def _sync_stock_bars(
        self,
        dataset: str,
        mode: str,
        trading_dates: list[date],
        start: date | None,
        end: date | None,
    ) -> None:
        spec = DATASET_SPECS[dataset]
        bounds = self._date_bounds(mode, trading_dates, start, end, dataset, "")
        if not bounds:
            return
        slices = list(
            daily_slices(
                value for value in trading_dates if bounds[0] <= value <= bounds[1]
            )
        )
        batch_size = (
            self.settings.stock_daily_batch_size
            if dataset == "stock_daily"
            else self.settings.stock_minute_batch_size
        )
        dataset_started = monotonic()
        LOGGER.info(
            "dataset_started dataset=%s mode=%s range=%s..%s trading_days=%d batch_size=%d",
            dataset,
            mode,
            bounds[0],
            bounds[1],
            len(slices),
            batch_size,
        )
        for day_position, slice_ in enumerate(slices, start=1):
            latest = self.state.latest(dataset, slice_.slice_key)
            if mode == "bootstrap" and latest and latest.status == "complete":
                LOGGER.info(
                    "bar_day_skipped dataset=%s date=%s day=%d/%d reason=complete",
                    dataset,
                    slice_.start,
                    day_position,
                    len(slices),
                )
                continue
            day_started = monotonic()
            instruments = self._sync_instruments(slice_.start)
            universe = self._active_order_book_ids(instruments, slice_.start)
            stage, stage_existed = self.storage.prepare_daily_stage(
                spec, slice_.start
            )
            last_id = (
                str((latest.cursor if latest else {}).get("last_order_book_id", ""))
                if stage_existed and latest and latest.status != "complete"
                else ""
            )
            pending = [value for value in universe if value > last_id]
            batches = list(self._batches(pending, batch_size))
            processed_total = len(universe) - len(pending)
            downloaded_rows = 0
            quota_bytes = 0
            LOGGER.info(
                "bar_day_started dataset=%s date=%s day=%d/%d universe=%d resumed=%d pending=%d batches=%d",
                dataset,
                slice_.start,
                day_position,
                len(slices),
                len(universe),
                processed_total,
                len(pending),
                len(batches),
            )
            for batch_position, order_book_ids in enumerate(batches, start=1):
                try:
                    if dataset == "stock_daily":
                        raw, consumed = self._fetch(
                            dataset,
                            f"{slice_.slice_key}:{order_book_ids[0]}-{order_book_ids[-1]}",
                            lambda ids=order_book_ids, d=slice_.start: self.client.stock_daily(
                                ids, d
                            ),
                        )
                        frame = stock_daily_frame(raw, slice_.start, self.run_id)
                    else:
                        raw, consumed = self._fetch(
                            dataset,
                            f"{slice_.slice_key}:{order_book_ids[0]}-{order_book_ids[-1]}",
                            lambda ids=order_book_ids, d=slice_.start: self.client.stock_minute(
                                ids, d
                            ),
                        )
                        frame = stock_minute_frame(raw, slice_.start, self.run_id)
                except QuotaPaused:
                    self.state.coverage_event(
                        spec,
                        slice_.slice_key,
                        "quota_paused",
                        range_start=str(slice_.start),
                        range_end=str(slice_.end),
                        partition_value=str(slice_.start),
                        cursor={
                            "last_order_book_id": last_id,
                            "universe_size": len(universe),
                        },
                        message="resume the same trading day on the next quota day",
                    )
                    LOGGER.warning(
                        "bar_day_quota_paused dataset=%s date=%s processed=%d/%d last=%s rows=%d elapsed_seconds=%.1f",
                        dataset,
                        slice_.start,
                        processed_total,
                        len(universe),
                        last_id or "none",
                        downloaded_rows,
                        monotonic() - day_started,
                    )
                    raise
                self.storage.replace_daily_stage_batch(
                    spec, stage, order_book_ids, frame
                )
                last_id = order_book_ids[-1]
                processed_total += len(order_book_ids)
                downloaded_rows += len(frame)
                quota_bytes += consumed
                self.state.coverage_event(
                    spec,
                    slice_.slice_key,
                    "partial",
                    range_start=str(slice_.start),
                    range_end=str(slice_.end),
                    partition_value=str(slice_.start),
                    cursor={
                        "last_order_book_id": last_id,
                        "universe_size": len(universe),
                    },
                )
                if (
                    batch_position == 1
                    or batch_position % 5 == 0
                    or batch_position == len(batches)
                ):
                    LOGGER.info(
                        "bar_day_progress dataset=%s date=%s batch=%d/%d processed=%d/%d percent=%.1f last=%s rows=%d quota_bytes=%d elapsed_seconds=%.1f",
                        dataset,
                        slice_.start,
                        batch_position,
                        len(batches),
                        processed_total,
                        len(universe),
                        100.0 * processed_total / max(1, len(universe)),
                        last_id,
                        downloaded_rows,
                        quota_bytes,
                        monotonic() - day_started,
                    )
            result = self.storage.publish_daily_stage(spec, stage, slice_.start)
            self.state.coverage_event(
                spec,
                slice_.slice_key,
                "complete",
                range_start=str(slice_.start),
                range_end=str(slice_.end),
                partition_value=str(slice_.start),
                cursor={"last_order_book_id": last_id, "universe_size": len(universe)},
                row_count=result.row_count,
                content_hash=result.content_hash,
                quota_bytes_used=quota_bytes,
                mutable_until=slice_.end + timedelta(days=spec.mutable_days),
            )
            LOGGER.info(
                "bar_day_complete dataset=%s date=%s day=%d/%d rows=%d quota_bytes=%d elapsed_seconds=%.1f",
                dataset,
                slice_.start,
                day_position,
                len(slices),
                result.row_count,
                quota_bytes,
                monotonic() - day_started,
            )
        LOGGER.info(
            "dataset_complete dataset=%s trading_days=%d elapsed_seconds=%.1f",
            dataset,
            len(slices),
            monotonic() - dataset_started,
        )

    def _known_order_book_ids(self, snapshot_date: date) -> list[str]:
        if self.requested_order_book_ids:
            return list(self.requested_order_book_ids)
        latest = self._sync_instruments(snapshot_date)
        identifiers = set(self._active_order_book_ids(latest, snapshot_date))
        historical = self.storage.client.query_df(
            f"SELECT DISTINCT order_book_id FROM {self.storage.db}.`ricequant_instrument`"
        )
        if not historical.empty:
            identifiers.update(historical["order_book_id"].dropna().astype(str))
        return sorted(identifiers)

    def _sync_stock_factors(
        self,
        dataset: str,
        mode: str,
        trading_dates: list[date],
        start: date | None,
        end: date | None,
    ) -> None:
        if not trading_dates:
            return
        spec = DATASET_SPECS[dataset]
        upper = min(end or trading_dates[-1], trading_dates[-1])
        if start:
            lower = start
        elif mode in {"bootstrap", "backfill"}:
            lower = self._dataset_history_start(dataset)
        else:
            lower = max(
                self._dataset_history_start(dataset),
                upper - timedelta(days=spec.mutable_days),
            )
        identifiers = self._known_order_book_ids(trading_dates[-1])
        complete = self.state.completed_slice_ranges(dataset)
        pending = []
        planned: dict[str, DateSlice] = {}
        for identifier in identifiers:
            slice_key = f"{identifier}:{lower}:{upper}"
            slice_ = DateSlice(lower, upper, slice_key)
            planned[identifier] = slice_
            if not (
                mode == "bootstrap"
                and self._completed_slice_covers(complete, slice_)
            ):
                pending.append(identifier)
        dataset_started = monotonic()
        batch_size = self.settings.stock_daily_batch_size
        batches = list(self._batches(pending, batch_size))
        LOGGER.info(
            "dataset_started dataset=%s mode=%s range=%s..%s instruments=%d skipped=%d batches=%d",
            dataset,
            mode,
            lower,
            upper,
            len(pending),
            len(identifiers) - len(pending),
            len(batches),
        )
        for batch_position, batch in enumerate(batches, start=1):
            if dataset == "stock_ex_factor":
                raw, consumed = self._fetch(
                    dataset,
                    f"{lower}:{upper}:{batch[0]}-{batch[-1]}",
                    lambda ids=batch: self.client.ex_factors(ids, lower, upper),
                )
                transformed = ex_factor_frame(raw, self.run_id)
                date_column = "ex_date"
            else:
                raw, consumed = self._fetch(
                    dataset,
                    f"{lower}:{upper}:{batch[0]}-{batch[-1]}",
                    lambda ids=batch: self.client.splits(ids, lower, upper),
                )
                transformed = split_frame(raw, self.run_id)
                date_column = "ex_dividend_date"
            unexpected = set(transformed["order_book_id"].astype(str)) - set(batch)
            if unexpected:
                raise ValueError(
                    f"{dataset} returned unexpected instruments: {sorted(unexpected)[:5]}"
                )
            per_instrument_quota = consumed // max(1, len(batch))
            for identifier in batch:
                frame = transformed[
                    transformed["order_book_id"].astype(str) == identifier
                ].copy()
                result = self.storage.publish_partition(
                    spec,
                    quote_string(identifier),
                    frame,
                    replace_range=(date_column, lower, upper),
                )
                slice_ = planned[identifier]
                self.state.coverage_event(
                    spec,
                    slice_.slice_key,
                    "complete",
                    range_start=str(lower),
                    range_end=str(upper),
                    partition_value=quote_string(identifier),
                    row_count=result.row_count,
                    content_hash=result.content_hash,
                    quota_bytes_used=per_instrument_quota,
                    mutable_until=upper + timedelta(days=spec.mutable_days),
                )
            LOGGER.info(
                "factor_progress dataset=%s batch=%d/%d instruments=%d/%d rows=%d quota_bytes=%d elapsed_seconds=%.1f",
                dataset,
                batch_position,
                len(batches),
                min(batch_position * batch_size, len(pending)),
                len(pending),
                len(transformed),
                consumed,
                monotonic() - dataset_started,
            )
        LOGGER.info(
            "dataset_complete dataset=%s instruments=%d elapsed_seconds=%.1f",
            dataset,
            len(pending),
            monotonic() - dataset_started,
        )

    def _sync_financials(
        self,
        dataset: str,
        mode: str,
        start: date | None,
        end: date | None,
    ) -> None:
        """Fetch one independent PIT field group and publish per instrument."""

        spec = DATASET_SPECS[dataset]
        history_start = date.fromisoformat(self.settings.financial_start_date)
        upper = quarter_end_on_or_before(min(end or self.today, self.today))
        if start:
            lower = quarter_end_on_or_after(max(start, history_start))
        elif mode in {"bootstrap", "backfill"}:
            lower = quarter_end_on_or_after(history_start)
        else:
            lower = quarter_end_on_or_after(
                max(
                    history_start,
                    upper - timedelta(days=self.settings.financial_rescan_days),
                )
            )
        if lower > upper:
            LOGGER.info(
                "dataset_complete dataset=%s reason=no_completed_report_period range=%s..%s",
                dataset,
                lower,
                upper,
            )
            return

        query_date = self.today
        start_quarter = quarter_label(lower)
        end_quarter = quarter_label(upper)
        fields = FINANCIAL_FIELDS_BY_DATASET[dataset]
        identifiers = self._known_order_book_ids(query_date)
        complete = self.state.completed_slice_ranges(dataset)
        pending: list[str] = []
        planned: dict[str, DateSlice] = {}
        for identifier in identifiers:
            slice_key = f"{identifier}:{lower}:{upper}"
            slice_ = DateSlice(lower, upper, slice_key)
            planned[identifier] = slice_
            if not (
                mode == "bootstrap"
                and self._completed_slice_covers(complete, slice_)
            ):
                pending.append(identifier)

        dataset_started = monotonic()
        batches = list(self._batches(pending, self.settings.financial_batch_size))
        LOGGER.info(
            "dataset_started dataset=%s mode=%s periods=%s..%s query_date=%s "
            "fields=%d instruments=%d skipped=%d batches=%d statements=all",
            dataset,
            mode,
            start_quarter,
            end_quarter,
            query_date,
            len(fields),
            len(pending),
            len(identifiers) - len(pending),
            len(batches),
        )
        for batch_position, batch in enumerate(batches, start=1):
            raw, consumed = self._fetch(
                dataset,
                f"{start_quarter}:{end_quarter}:{batch[0]}-{batch[-1]}",
                lambda ids=batch: self.client.pit_financials(
                    ids,
                    fields,
                    start_quarter,
                    end_quarter,
                    query_date,
                ),
            )
            observed_at = datetime.now(ZoneInfo("Asia/Shanghai"))
            transformed = financial_statement_frame(
                raw,
                fields,
                query_date,
                observed_at,
                self.run_id,
            )
            returned_ids = (
                set(transformed["order_book_id"].astype(str))
                if not transformed.empty
                else set()
            )
            unexpected = returned_ids - set(batch)
            if unexpected:
                raise ValueError(
                    f"{dataset} returned unexpected instruments: {sorted(unexpected)[:5]}"
                )
            returned_periods = (
                set(transformed["report_period"].dropna())
                if not transformed.empty
                else set()
            )
            out_of_range = {
                value for value in returned_periods if value < lower or value > upper
            }
            if out_of_range:
                raise ValueError(
                    f"{dataset} returned report periods outside request: "
                    f"{sorted(out_of_range)[:5]}"
                )

            per_instrument_quota = consumed // max(1, len(batch))
            published_rows = 0
            for identifier in batch:
                frame = transformed[
                    transformed["order_book_id"].astype(str) == identifier
                ].copy()
                result = self.storage.publish_partition(
                    spec,
                    quote_string(identifier),
                    frame,
                    replace_range=("report_period", lower, upper),
                )
                slice_ = planned[identifier]
                self.state.coverage_event(
                    spec,
                    slice_.slice_key,
                    "complete",
                    range_start=str(lower),
                    range_end=str(upper),
                    partition_value=quote_string(identifier),
                    row_count=len(frame),
                    content_hash=result.content_hash,
                    quota_bytes_used=per_instrument_quota,
                    mutable_until=upper
                    + timedelta(days=self.settings.financial_rescan_days),
                    message=f"query_date={query_date};statements=all",
                )
                published_rows += len(frame)
            LOGGER.info(
                "financial_progress dataset=%s batch=%d/%d instruments=%d/%d "
                "rows=%d quota_bytes=%d elapsed_seconds=%.1f",
                dataset,
                batch_position,
                len(batches),
                min(
                    batch_position * self.settings.financial_batch_size,
                    len(pending),
                ),
                len(pending),
                published_rows,
                consumed,
                monotonic() - dataset_started,
            )
        LOGGER.info(
            "dataset_complete dataset=%s periods=%s..%s instruments=%d "
            "elapsed_seconds=%.1f",
            dataset,
            start_quarter,
            end_quarter,
            len(pending),
            monotonic() - dataset_started,
        )

    def _sync_instruments(self, trading_date: date) -> pd.DataFrame:
        spec = DATASET_SPECS["instruments"]
        slice_key = str(trading_date)
        latest = self.state.latest(spec.name, slice_key)
        where = f"snapshot_date = toDate({quote_string(slice_key)})"
        if latest and latest.status == "complete":
            frame = self.storage.table_frame(spec.table, where)
            LOGGER.info(
                "snapshot_reused dataset=%s date=%s rows=%d",
                spec.name,
                trading_date,
                len(frame),
            )
            return frame
        started = monotonic()
        LOGGER.info("snapshot_started dataset=%s date=%s", spec.name, trading_date)
        raw, consumed = self._fetch(
            spec.name, slice_key, lambda: self.client.instruments(trading_date)
        )
        frame = instruments_frame(raw, trading_date, self.run_id)
        partition = f"{trading_date:%Y%m%d}"
        result = self.storage.publish_partition(spec, partition, frame)
        self.state.coverage_event(
            spec,
            slice_key,
            "complete",
            range_start=slice_key,
            range_end=slice_key,
            partition_value=partition,
            row_count=result.row_count,
            content_hash=result.content_hash,
            quota_bytes_used=consumed,
        )
        LOGGER.info(
            "snapshot_complete dataset=%s date=%s rows=%d quota_bytes=%d "
            "elapsed_seconds=%.1f",
            spec.name,
            trading_date,
            result.row_count,
            consumed,
            monotonic() - started,
        )
        return frame

    def _sync_tick(
        self, mode: str, trading_dates: list[date], start: date | None, end: date | None
    ) -> None:
        spec = DATASET_SPECS["tick"]
        dataset_started = monotonic()
        upper = (
            min(end or self.today, trading_dates[-1]) if trading_dates else self.today
        )
        if start:
            lower = start
        elif mode in {"bootstrap", "backfill"}:
            lower = upper - timedelta(days=self.settings.tick_lookback_calendar_days)
        else:
            last = self.state.latest_completed_end(spec.name)
            lower = incremental_start(
                last,
                upper
                - timedelta(days=max(62, self.settings.tick_lookback_calendar_days)),
            )
        slices = list(
            daily_slices(value for value in trading_dates if lower <= value <= upper)
        )
        LOGGER.info(
            "dataset_started dataset=%s mode=%s range=%s..%s trading_days=%d",
            spec.name,
            mode,
            lower,
            upper,
            len(slices),
        )
        for day_position, slice_ in enumerate(slices, start=1):
            latest = self.state.latest(spec.name, slice_.slice_key)
            if latest and latest.status == "complete":
                LOGGER.info(
                    "tick_day_skipped date=%s day=%d/%d reason=complete",
                    slice_.start,
                    day_position,
                    len(slices),
                )
                continue
            day_started = monotonic()
            instruments = self._sync_instruments(slice_.start)
            universe = self._active_order_book_ids(instruments, slice_.start)
            stage = self.storage.prepare_tick_day(slice_.start)
            last_id = str(
                (latest.cursor if latest else {}).get("last_order_book_id", "")
            )
            pending = [value for value in universe if value > last_id]
            processed_since_checkpoint = 0
            processed_since_log = 0
            processed_total = len(universe) - len(pending)
            downloaded_rows = 0
            quota_bytes = 0
            LOGGER.info(
                "tick_day_started date=%s day=%d/%d universe=%d resumed=%d pending=%d",
                slice_.start,
                day_position,
                len(slices),
                len(universe),
                processed_total,
                len(pending),
            )
            for order_book_id in pending:
                try:
                    raw, consumed = self._fetch(
                        spec.name,
                        f"{slice_.slice_key}:{order_book_id}",
                        lambda i=order_book_id, d=slice_.start: self.client.tick(i, d),
                    )
                except QuotaPaused:
                    self.state.coverage_event(
                        spec,
                        slice_.slice_key,
                        "quota_paused",
                        range_start=str(slice_.start),
                        range_end=str(slice_.end),
                        partition_value=str(slice_.start),
                        cursor={
                            "last_order_book_id": last_id,
                            "universe_size": len(universe),
                        },
                        message="resume the same trading day on the next quota day",
                    )
                    LOGGER.warning(
                        "tick_day_quota_paused date=%s processed=%d/%d last=%s "
                        "downloaded_rows=%d elapsed_seconds=%.1f",
                        slice_.start,
                        processed_total,
                        len(universe),
                        last_id or "none",
                        downloaded_rows,
                        monotonic() - day_started,
                    )
                    raise
                frame = tick_frame(raw, order_book_id, slice_.start, self.run_id)
                self.storage.replace_tick_instrument(stage, order_book_id, frame)
                last_id = order_book_id
                processed_since_checkpoint += 1
                processed_since_log += 1
                processed_total += 1
                downloaded_rows += len(frame)
                quota_bytes += consumed
                if processed_since_checkpoint >= 25:
                    self.state.coverage_event(
                        spec,
                        slice_.slice_key,
                        "partial",
                        range_start=str(slice_.start),
                        range_end=str(slice_.end),
                        partition_value=str(slice_.start),
                        cursor={
                            "last_order_book_id": last_id,
                            "universe_size": len(universe),
                        },
                    )
                    processed_since_checkpoint = 0
                if processed_since_log >= 100 or processed_total == len(universe):
                    LOGGER.info(
                        "tick_day_progress date=%s processed=%d/%d percent=%.1f "
                        "last=%s downloaded_rows=%d quota_bytes=%d "
                        "elapsed_seconds=%.1f",
                        slice_.start,
                        processed_total,
                        len(universe),
                        100.0 * processed_total / max(1, len(universe)),
                        last_id,
                        downloaded_rows,
                        quota_bytes,
                        monotonic() - day_started,
                    )
                    processed_since_log = 0
            result = self.storage.publish_tick_day(stage, slice_.start)
            self.state.coverage_event(
                spec,
                slice_.slice_key,
                "complete",
                range_start=str(slice_.start),
                range_end=str(slice_.end),
                partition_value=str(slice_.start),
                cursor={"last_order_book_id": last_id, "universe_size": len(universe)},
                row_count=result.row_count,
                content_hash=result.content_hash,
            )
            LOGGER.info(
                "tick_day_complete date=%s day=%d/%d rows=%d quota_bytes=%d "
                "elapsed_seconds=%.1f",
                slice_.start,
                day_position,
                len(slices),
                result.row_count,
                quota_bytes,
                monotonic() - day_started,
            )
        LOGGER.info(
            "dataset_complete dataset=%s trading_days=%d elapsed_seconds=%.1f",
            spec.name,
            len(slices),
            monotonic() - dataset_started,
        )

    @staticmethod
    def _active_order_book_ids(frame: pd.DataFrame, trading_date: date) -> list[str]:
        if frame.empty:
            return []
        active = frame.copy()
        # Fresh API frames contain Python ``date`` objects, while Date32
        # columns read back from ClickHouse are pandas ``datetime64[ns]``.
        # Normalize both paths at this boundary so snapshot reuse has exactly
        # the same universe semantics as a newly downloaded snapshot.
        comparison_date = pd.Timestamp(trading_date)
        if "listed_date" in active:
            listed_date = pd.to_datetime(active["listed_date"], errors="coerce")
            active = active[
                listed_date.isna() | (listed_date <= comparison_date)
            ]
        if "de_listed_date" in active:
            de_listed_date = pd.to_datetime(
                active["de_listed_date"], errors="coerce"
            )
            active = active[
                de_listed_date.isna() | (de_listed_date >= comparison_date)
            ]
        return sorted(active["order_book_id"].dropna().astype(str).unique().tolist())
