from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

import pandas as pd

from ricequant_integration.specs import DatasetSpec
from ricequant_integration.storage import RiceQuantStorage, quote_string


@dataclass(frozen=True)
class CoverageState:
    dataset: str
    slice_key: str
    status: str
    cursor: dict[str, Any]
    row_count: int
    content_hash: str
    event_time: datetime
    mutable_until: date | None = None


def should_refresh(state: CoverageState | None, as_of: date) -> bool:
    """Return whether a slice is missing, incomplete, or still source-mutable."""
    if state is None or state.status != "complete":
        return True
    return state.mutable_until is not None and as_of <= state.mutable_until


def content_changed(state: CoverageState | None, new_hash: str) -> bool:
    """Avoid creating a new source revision when authoritative content is unchanged."""
    return state is None or state.content_hash != new_hash


class StateStore:
    def __init__(self, storage: RiceQuantStorage, run_id: str):
        self.storage = storage
        self.run_id = run_id

    def run_event(
        self, mode: str, status: str, message: str = "", dataset: str | None = None
    ) -> None:
        self.storage.insert_frame(
            "ricequant_run_event",
            pd.DataFrame(
                [
                    {
                        "event_id": uuid.uuid4().hex,
                        "run_id": self.run_id,
                        "mode": mode,
                        "status": status,
                        "dataset": dataset,
                        "message": message,
                        "event_time": datetime.now(),
                    }
                ]
            ),
        )

    def coverage_event(
        self,
        spec: DatasetSpec,
        slice_key: str,
        status: str,
        *,
        range_start: str | None = None,
        range_end: str | None = None,
        partition_value: str | None = None,
        cursor: dict[str, Any] | None = None,
        row_count: int = 0,
        content_hash: str = "",
        quota_bytes_used: int = 0,
        mutable_until: date | None = None,
        message: str = "",
    ) -> None:
        self.storage.insert_frame(
            "ricequant_coverage_event",
            pd.DataFrame(
                [
                    {
                        "event_id": uuid.uuid4().hex,
                        "run_id": self.run_id,
                        "dataset": spec.name,
                        "time_semantics": spec.time_semantics.value,
                        "slice_key": slice_key,
                        "range_start": range_start,
                        "range_end": range_end,
                        "partition_value": partition_value,
                        "status": status,
                        "cursor_json": json.dumps(
                            cursor or {}, ensure_ascii=False, sort_keys=True
                        ),
                        "row_count": row_count,
                        "content_hash": content_hash,
                        "quota_bytes_used": max(0, quota_bytes_used),
                        "mutable_until": mutable_until,
                        "message": message,
                        "event_time": datetime.now(),
                    }
                ]
            ),
        )

    def latest(self, dataset: str, slice_key: str) -> CoverageState | None:
        frame = self.storage.client.query_df(
            f"""
            SELECT dataset, slice_key,
                   argMax(status, tuple(event_time, event_id)) AS latest_status,
                   argMax(cursor_json, tuple(event_time, event_id)) AS latest_cursor_json,
                   argMax(row_count, tuple(event_time, event_id)) AS latest_row_count,
                   argMax(content_hash, tuple(event_time, event_id)) AS latest_content_hash,
                   argMax(mutable_until, tuple(event_time, event_id)) AS latest_mutable_until,
                   max(event_time) AS latest_event_time
            FROM {self.storage.db}.`ricequant_coverage_event`
            WHERE dataset = {quote_string(dataset)} AND slice_key = {quote_string(slice_key)}
            GROUP BY dataset, slice_key
            """
        )
        if frame.empty:
            return None
        row = frame.iloc[0]
        return CoverageState(
            dataset=str(row["dataset"]),
            slice_key=str(row["slice_key"]),
            status=str(row["latest_status"]),
            cursor=json.loads(row["latest_cursor_json"] or "{}"),
            row_count=int(row["latest_row_count"]),
            content_hash=str(row["latest_content_hash"]),
            event_time=pd.Timestamp(row["latest_event_time"]).to_pydatetime(),
            mutable_until=(
                None
                if pd.isna(row["latest_mutable_until"])
                else pd.Timestamp(row["latest_mutable_until"]).date()
            ),
        )

    def completed_slice_keys(self, dataset: str) -> set[str]:
        frame = self.storage.client.query_df(
            f"""
            SELECT slice_key
            FROM (
                SELECT slice_key,
                       argMax(status, tuple(event_time, event_id)) AS latest_status
                FROM {self.storage.db}.`ricequant_coverage_event`
                WHERE dataset = {quote_string(dataset)}
                GROUP BY slice_key
            ) WHERE latest_status = 'complete'
            """
        )
        return set(frame["slice_key"].astype(str)) if not frame.empty else set()

    def completed_slice_ranges(self, dataset: str) -> dict[str, tuple[date, date]]:
        """Return only authoritative completed bounds for each logical slice.

        A partial-month backfill can share a month-shaped slice key with a
        later full bootstrap. Callers must compare bounds rather than treating
        the key alone as proof that the whole planned interval is complete.
        """
        frame = self.storage.client.query_df(
            f"""
            SELECT slice_key, latest_range_start, latest_range_end
            FROM (
                SELECT slice_key,
                       argMax(status, tuple(event_time, event_id)) AS latest_status,
                       argMax(range_start, tuple(event_time, event_id)) AS latest_range_start,
                       argMax(range_end, tuple(event_time, event_id)) AS latest_range_end
                FROM {self.storage.db}.`ricequant_coverage_event`
                WHERE dataset = {quote_string(dataset)}
                GROUP BY slice_key
            )
            WHERE latest_status = 'complete'
              AND latest_range_start IS NOT NULL
              AND latest_range_end IS NOT NULL
            """
        )
        result: dict[str, tuple[date, date]] = {}
        for _, row in frame.iterrows():
            result[str(row["slice_key"])] = (
                pd.Timestamp(row["latest_range_start"]).date(),
                pd.Timestamp(row["latest_range_end"]).date(),
            )
        return result

    def latest_completed_end(self, dataset: str, slice_prefix: str = "") -> date | None:
        prefix = ""
        if slice_prefix:
            prefix = f" AND slice_key LIKE {quote_string(slice_prefix + '%')}"
        frame = self.storage.client.query_df(
            f"""
            SELECT max(parseDateTimeBestEffortOrNull(latest_range_end)) AS completed_range_end
            FROM (
                SELECT slice_key,
                       argMax(status, tuple(event_time, event_id)) AS latest_status,
                       argMax(range_end, tuple(event_time, event_id)) AS latest_range_end
                FROM {self.storage.db}.`ricequant_coverage_event`
                WHERE dataset = {quote_string(dataset)}{prefix}
                GROUP BY slice_key
            ) WHERE latest_status = 'complete'
            """
        )
        if frame.empty or pd.isna(frame.iloc[0]["completed_range_end"]):
            return None
        return pd.Timestamp(frame.iloc[0]["completed_range_end"]).date()
