from __future__ import annotations

import argparse
import fcntl
import json
import logging
import signal
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from types import FrameType
from typing import Any, Iterator

from ricequant_integration.client import RqDataClient
from ricequant_integration.quota import QuotaSnapshot
from ricequant_integration.runner import RiceQuantRunner
from ricequant_integration.settings import RiceQuantSettings
from ricequant_integration.storage import RiceQuantStorage


SHUTDOWN_SIGNALS = (
    signal.SIGINT,
    signal.SIGTERM,
    signal.SIGHUP,
    signal.SIGQUIT,
)


def _shutdown_on_signal(signum: int, _frame: FrameType | None) -> None:
    """Turn process stop signals into normal stack unwinding.

    Ignoring follow-up stop signals protects the ClickHouse lock cleanup from
    an impatient second Ctrl+C. SIGKILL cannot be handled by any process.
    """

    for shutdown_signal in SHUTDOWN_SIGNALS:
        signal.signal(shutdown_signal, signal.SIG_IGN)
    raise SystemExit(128 + signum)


def install_shutdown_signal_handlers() -> None:
    for shutdown_signal in SHUTDOWN_SIGNALS:
        signal.signal(shutdown_signal, _shutdown_on_signal)


@contextmanager
def runner_lock(path: str) -> Iterator[None]:
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                f"another RiceQuant runner is active (lock: {path})"
            ) from exc
        yield


def _date(value: str | None) -> date | None:
    return date.fromisoformat(value) if value else None


def quota_payload(
    snapshot: QuotaSnapshot, min_reserve_bytes: int
) -> dict[str, Any]:
    """Return exact source counters plus convenient display units.

    RQData only exposes the current daily byte limit and bytes used.  Keep the
    exact counters in the output; derived GiB/percentage fields are for operator
    display and must not be used as a replacement for the source values.
    """

    gib = 1024**3
    if snapshot.unlimited:
        return {
            "quota_scope": "daily",
            "unlimited": True,
            "bytes_limit": snapshot.bytes_limit,
            "bytes_used": snapshot.bytes_used,
            "bytes_remaining": None,
            "used_percent": None,
            "limit_gib": None,
            "used_gib": round(snapshot.bytes_used / gib, 4),
            "remaining_gib": None,
            "framework_min_reserve_bytes": min_reserve_bytes,
            "bytes_available_before_min_reserve": None,
        }

    remaining = snapshot.bytes_remaining
    return {
        "quota_scope": "daily",
        "unlimited": False,
        "bytes_limit": snapshot.bytes_limit,
        "bytes_used": snapshot.bytes_used,
        "bytes_remaining": remaining,
        "used_percent": round(snapshot.bytes_used * 100 / snapshot.bytes_limit, 4),
        "limit_gib": round(snapshot.bytes_limit / gib, 4),
        "used_gib": round(snapshot.bytes_used / gib, 4),
        "remaining_gib": round(remaining / gib, 4),
        "framework_min_reserve_bytes": min_reserve_bytes,
        "bytes_available_before_min_reserve": max(
            0, remaining - min_reserve_bytes
        ),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ricequant", description="Independent RQData ingestion runner"
    )
    parser.add_argument("--config", default="ricequant.yaml")
    parser.add_argument("--log-level", default="INFO")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="create RiceQuant final and control tables")
    for name in ("bootstrap", "incremental", "backfill"):
        command = subparsers.add_parser(name)
        command.add_argument("--dataset", action="append", dest="datasets")
        command.add_argument("--instrument", action="append", dest="instruments")
        command.add_argument("--start")
        command.add_argument("--end")
    subparsers.add_parser("status", help="show the latest dataset coverage events")
    subparsers.add_parser("quota", help="show the current RQData daily byte quota")
    return parser


def main(argv: list[str] | None = None) -> int:
    install_shutdown_signal_handlers()
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper()),
        format="%(asctime)s %(levelname)s %(message)s",
    )
    settings = RiceQuantSettings.load(
        args.config, require_token=args.command not in {"init-db", "status"}
    )
    if args.command == "quota":
        client = RqDataClient(settings.token)
        client.initialize()
        print(
            json.dumps(
                quota_payload(client.quota(), settings.quota_min_reserve_bytes),
                ensure_ascii=False,
            )
        )
        return 0
    if args.command == "init-db":
        RiceQuantStorage(settings.database).initialize()
        print("RiceQuant tables initialized")
        return 0
    if args.command == "status":
        storage = RiceQuantStorage(settings.database)
        frame = storage.client.query_df(
            f"""
            SELECT dataset, slice_key,
                   argMax(status, tuple(event_time, event_id)) AS latest_status,
                   argMax(range_end, tuple(event_time, event_id)) AS latest_range_end,
                   argMax(row_count, tuple(event_time, event_id)) AS latest_row_count,
                   max(event_time) AS latest_event_time
            FROM {storage.db}.`ricequant_coverage_event`
            GROUP BY dataset, slice_key
            ORDER BY dataset, latest_event_time DESC
            LIMIT 200
            """
        )
        frame = frame.rename(
            columns={
                "latest_status": "status",
                "latest_range_end": "range_end",
                "latest_row_count": "row_count",
                "latest_event_time": "event_time",
            }
        )
        print(frame.to_json(orient="records", date_format="iso", force_ascii=False))
        return 0

    if args.command == "backfill" and (not args.start or not args.end):
        raise SystemExit("backfill requires --start and --end")
    with runner_lock(settings.lock_file):
        summary = RiceQuantRunner(settings).run(
            mode=args.command,
            datasets=args.datasets,
            start=_date(args.start),
            end=_date(args.end),
            instruments=args.instruments,
        )
    print(json.dumps(summary.__dict__, ensure_ascii=False))
    # quota_paused is an expected, resumable state. Schedulers must not retry it
    # immediately and burn the remaining reserve.
    return 0
