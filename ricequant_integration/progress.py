from __future__ import annotations

import logging
from dataclasses import dataclass
from time import monotonic
from typing import Callable


@dataclass
class DatasetProgress:
    started_at: float
    last_heartbeat_at: float
    api_calls: int = 0
    response_rows: int = 0
    quota_bytes: int = 0
    failures: int = 0
    active_slice: str = ""


class ProgressReporter:
    """Framework-level progress for every quota-accounted source request.

    Dataset adapters receive this automatically by routing source calls through
    ``RiceQuantRunner._fetch``. Domain progress, such as a Tick universe
    percentage, can be logged in addition to this common baseline.
    """

    def __init__(
        self,
        logger: logging.Logger,
        run_id: str,
        *,
        heartbeat_seconds: float = 60.0,
        heartbeat_calls: int = 250,
        clock: Callable[[], float] = monotonic,
    ):
        self.logger = logger
        self.run_id = run_id
        self.heartbeat_seconds = heartbeat_seconds
        self.heartbeat_calls = heartbeat_calls
        self.clock = clock
        self._datasets: dict[str, DatasetProgress] = {}

    def fetch_started(self, dataset: str, slice_key: str) -> None:
        now = self.clock()
        progress = self._datasets.get(dataset)
        if progress is None:
            progress = DatasetProgress(now, now, active_slice=slice_key)
            self._datasets[dataset] = progress
            self.logger.info(
                "dataset_fetch_started run_id=%s dataset=%s first_slice=%s",
                self.run_id,
                dataset,
                slice_key,
            )
        progress.active_slice = slice_key
        if self.logger.isEnabledFor(logging.DEBUG):
            self.logger.debug(
                "api_call_started run_id=%s dataset=%s slice=%s call=%d",
                self.run_id,
                dataset,
                slice_key,
                progress.api_calls + 1,
            )

    def fetch_completed(
        self, dataset: str, slice_key: str, *, rows: int, quota_bytes: int
    ) -> None:
        now = self.clock()
        progress = self._datasets[dataset]
        progress.api_calls += 1
        progress.response_rows += max(0, rows)
        progress.quota_bytes += max(0, quota_bytes)
        progress.active_slice = slice_key
        due_by_calls = (
            self.heartbeat_calls > 0 and progress.api_calls % self.heartbeat_calls == 0
        )
        due_by_time = now - progress.last_heartbeat_at >= self.heartbeat_seconds
        if due_by_calls or due_by_time:
            self.logger.info(
                "dataset_heartbeat run_id=%s dataset=%s api_calls=%d "
                "response_rows=%d quota_bytes=%d last_slice=%s "
                "elapsed_seconds=%.1f",
                self.run_id,
                dataset,
                progress.api_calls,
                progress.response_rows,
                progress.quota_bytes,
                slice_key,
                now - progress.started_at,
            )
            progress.last_heartbeat_at = now

    def fetch_failed(self, dataset: str, slice_key: str, exc: Exception) -> None:
        now = self.clock()
        progress = self._datasets.get(dataset)
        if progress is None:
            progress = DatasetProgress(now, now, active_slice=slice_key)
            self._datasets[dataset] = progress
        progress.failures += 1
        progress.active_slice = slice_key
        self.logger.warning(
            "api_call_failed run_id=%s dataset=%s slice=%s error_type=%s error=%s",
            self.run_id,
            dataset,
            slice_key,
            type(exc).__name__,
            exc,
        )

    def fetch_paused(self, dataset: str, slice_key: str, reason: Exception) -> None:
        progress = self._datasets[dataset]
        progress.active_slice = slice_key
        self.logger.warning(
            "api_call_paused run_id=%s dataset=%s slice=%s reason=%s",
            self.run_id,
            dataset,
            slice_key,
            reason,
        )

    def finish(self, status: str) -> None:
        now = self.clock()
        for dataset, progress in self._datasets.items():
            self.logger.info(
                "dataset_fetch_summary run_id=%s dataset=%s status=%s "
                "api_calls=%d response_rows=%d quota_bytes=%d failures=%d "
                "last_slice=%s elapsed_seconds=%.1f",
                self.run_id,
                dataset,
                status,
                progress.api_calls,
                progress.response_rows,
                progress.quota_bytes,
                progress.failures,
                progress.active_slice,
                now - progress.started_at,
            )
