"""Long-running RQData 1-minute subscription, with a durable ClickHouse outbox."""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import queue
import re
import signal
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import clickhouse_connect
import pandas as pd

from ricequant_integration.client import RqDataClient
from ricequant_integration.commands import runner_lock
from ricequant_integration.settings import DatabaseSettings, RiceQuantSettings


SHANGHAI = ZoneInfo("Asia/Shanghai")
LOG = logging.getLogger(__name__)
DEFAULT_TABLE = "ricequant_stock_minute_realtime"
CSI2000 = "932000.INDX"
INDEX_TABLE = "ricequant_index_minute_realtime"
VALUE_FIELDS = ("open", "high", "low", "close", "volume", "total_turnover", "num_trades")
COLUMN_TYPES = {
    "trade_date": "Date",
    "order_book_id": "String",
    "datetime": "DateTime64(3, 'Asia/Shanghai')",
    **{field: "Nullable(Float64)" for field in VALUE_FIELDS},
    "source_datetime": "String",
    "source_trading_date": "UInt32",
    "received_at": "DateTime64(6, 'Asia/Shanghai')",
    "event_id": "String",
    "record_hash": "FixedString(64)",
    "payload_json": "String",
    "source": "LowCardinality(String)",
    "api_name": "LowCardinality(String)",
}
COLUMNS = tuple(COLUMN_TYPES)


def validate_scope(scope: str) -> None:
    if scope not in {"stock", "csi2000"}:
        raise ValueError(f"unsupported realtime scope: {scope!r}")


def resolve_args(args: argparse.Namespace) -> None:
    validate_scope(args.scope)
    if args.table is None:
        args.table = INDEX_TABLE if args.scope == "csi2000" else DEFAULT_TABLE
    if args.state_dir is None:
        args.state_dir = "data/ricequant-realtime-csi2000" if args.scope == "csi2000" else "data/ricequant-realtime"
    if ((args.scope == "csi2000" and args.table == DEFAULT_TABLE)
            or (args.scope == "stock" and args.table == INDEX_TABLE)):
        raise ValueError("stock and index subscriptions must use separate realtime tables")


def identifier(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise ValueError(f"invalid SQL identifier: {value!r}")
    return f"`{value}`"


def is_hs_a_stock(order_book_id: str) -> bool:
    # Applied only to the source's CS universe; exclude B shares and Beijing.
    return bool(re.fullmatch(r"(?:(?:00|30)\d{4}\.XSHE|(?:60|68)\d{4}\.XSHG)", order_book_id))


def stock_universe(rq: Any, today: date) -> set[str]:
    # bypass the SDK's three-hour instrument-list cache on each daily refresh
    frame = rq.all_instruments(type="CS", date=today, market="cn", cached=False)
    if not isinstance(frame, pd.DataFrame) or "order_book_id" not in frame:
        raise ValueError("all_instruments(CS) did not return an instrument list")
    result = {str(value) for value in frame["order_book_id"] if is_hs_a_stock(str(value))}
    if not result:
        raise ValueError("refusing to replace the subscription with an empty stock universe")
    return result


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("bar numeric field must be a number or null")
    result = float(value)
    if math.isnan(result):
        return None
    if not math.isfinite(result):
        raise ValueError("bar numeric field cannot be infinite")
    return result


@dataclass(frozen=True)
class BarEvent:
    event_id: str
    received_at: datetime
    payload: dict[str, Any]
    scope: str = "stock"

    def row(self) -> list[Any]:
        msg = self.payload
        obid = msg.get("order_book_id")
        validate_scope(self.scope)
        if not isinstance(obid, str) or (obid != CSI2000 if self.scope == "csi2000" else not is_hs_a_stock(obid)):
            raise ValueError(f"bar instrument is outside the {self.scope} subscription scope")
        if msg.get("action") != "feed" or msg.get("channel") != f"bar_{obid}":
            raise ValueError("expected the native 1-minute bar channel")
        raw_dt = msg.get("datetime")
        # SDK 3.8.1 native bars use YYYYMMDDHHMMSS; retain source representation.
        text = str(raw_dt)
        if not re.fullmatch(r"\d{14}|\d{17}", text):
            raise ValueError("invalid source bar datetime")
        source_dt = datetime.strptime(text[:14], "%Y%m%d%H%M%S").replace(tzinfo=SHANGHAI)
        if len(text) == 17:
            source_dt = source_dt.replace(microsecond=int(text[14:]) * 1000)
        if source_dt.second or source_dt.microsecond:
            raise ValueError("bar datetime is not aligned to a minute")
        trading_date = msg.get("trading_date")
        if isinstance(trading_date, bool) or not re.fullmatch(r"\d{8}", str(trading_date)):
            raise ValueError("missing or invalid source trading_date")
        day = datetime.strptime(str(trading_date), "%Y%m%d").date()
        if day != source_dt.date() or day > self.received_at.astimezone(SHANGHAI).date():
            raise ValueError("bar source datetime/trading_date disagree or are in the future")
        values = [_number(msg.get(field)) for field in VALUE_FIELDS]
        prices = dict(zip(VALUE_FIELDS, values))
        if prices["high"] is not None and prices["low"] is not None and prices["high"] < prices["low"]:
            raise ValueError("bar high is below low")
        if any(prices[field] is not None and prices[field] < 0 for field in VALUE_FIELDS):
            raise ValueError("bar price, volume, turnover or trade count is negative")
        for field in ("open", "close"):
            value = prices[field]
            if value is not None and ((prices["high"] is not None and value > prices["high"])
                                      or (prices["low"] is not None and value < prices["low"])):
                raise ValueError("bar open/close is outside its high/low range")
        payload = json.dumps(msg, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        return [day, obid, source_dt, *values, text, int(trading_date), self.received_at,
                self.event_id, digest, payload, "ricequant", "LiveMarketDataClient/bar_1m"]


class Outbox:
    """Bounded SQLite WAL queue. An event keeps its ID across ambiguous retries."""

    def __init__(self, path: Path, target: str, max_rows: int, *, scope: str = "stock"):
        validate_scope(scope)
        self.scope = scope
        path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=FULL")
        self.connection.execute("CREATE TABLE IF NOT EXISTS target (name TEXT NOT NULL)")
        names = self.connection.execute("SELECT name FROM target").fetchall()
        if names and names != [(target,)]:
            self.connection.close()
            raise ValueError("outbox belongs to a different ClickHouse target; use a separate state directory")
        if not names:
            self.connection.execute("INSERT INTO target VALUES (?)", (target,))
        # An old outbox without scope metadata belongs to the stock collector.
        # Never reinterpret queued stock events as index events on restart.
        self.connection.execute("CREATE TABLE IF NOT EXISTS subscription_scope (name TEXT NOT NULL)")
        scopes = self.connection.execute("SELECT name FROM subscription_scope").fetchall()
        if (scopes and scopes != [(scope,)]) or (not scopes and names and scope != "stock"):
            self.connection.close()
            raise ValueError("outbox belongs to a different subscription scope; use a separate state directory")
        if not scopes:
            self.connection.execute("INSERT INTO subscription_scope VALUES (?)", (scope,))
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS events (event_id TEXT PRIMARY KEY, trade_date TEXT NOT NULL, "
            "received_at TEXT NOT NULL, payload TEXT NOT NULL)"
        )
        self.connection.execute("CREATE TABLE IF NOT EXISTS active_batch (event_id TEXT PRIMARY KEY)")
        self.connection.execute("CREATE TABLE IF NOT EXISTS batch_metadata (token TEXT NOT NULL)")
        self.connection.commit()
        self.max_rows = max_rows
        self.size = int(self.connection.execute("SELECT count(*) FROM events").fetchone()[0])

    def append(self, events: list[BarEvent]) -> None:
        if any(event.scope != self.scope for event in events):
            raise ValueError("event scope does not match durable outbox scope")
        if self.size + len(events) > self.max_rows:
            raise BufferError("durable outbox is full")
        rows = [(e.event_id, str(e.row()[0]), e.received_at.isoformat(),
                 json.dumps(e.payload, separators=(",", ":"), ensure_ascii=False)) for e in events]
        with self.connection:
            self.connection.executemany("INSERT INTO events VALUES (?, ?, ?, ?)", rows)
        self.size += len(rows)

    def peek(self, limit: int) -> list[BarEvent]:
        # Freeze the in-flight batch durably. New arrivals must not change its
        # ClickHouse deduplication token after a timeout or process restart.
        with self.connection:
            if not self.connection.execute("SELECT 1 FROM active_batch LIMIT 1").fetchone():
                self.connection.execute("DELETE FROM batch_metadata")
                self.connection.execute(
                    "INSERT INTO active_batch SELECT event_id FROM events ORDER BY rowid LIMIT ?", (limit,)
                )
            if not self.connection.execute("SELECT 1 FROM batch_metadata LIMIT 1").fetchone():
                ids = self.connection.execute(
                    "SELECT e.event_id FROM events AS e JOIN active_batch AS b ON e.event_id = b.event_id ORDER BY e.rowid"
                ).fetchall()
                if ids:
                    token = hashlib.sha256("\n".join(row[0] for row in ids).encode()).hexdigest()
                    self.connection.execute("INSERT INTO batch_metadata VALUES (?)", (token,))
        rows = self.connection.execute(
            "SELECT e.event_id, e.received_at, e.payload FROM events AS e "
            "JOIN active_batch AS b ON e.event_id = b.event_id ORDER BY e.rowid"
        ).fetchall()
        return [BarEvent(eid, datetime.fromisoformat(received), json.loads(payload), self.scope)
                for eid, received, payload in rows]

    @property
    def batch_token(self) -> str | None:
        value = self.connection.execute("SELECT token FROM batch_metadata LIMIT 1").fetchone()
        return value[0] if value else None

    def acknowledge(self, event_ids: list[str]) -> None:
        with self.connection:
            self.connection.executemany("DELETE FROM events WHERE event_id = ?", [(eid,) for eid in event_ids])
            self.connection.executemany("DELETE FROM active_batch WHERE event_id = ?", [(eid,) for eid in event_ids])
        self.size -= len(event_ids)

    def discard_before(self, cutoff: date) -> int:
        with self.connection:
            cursor = self.connection.execute("DELETE FROM events WHERE trade_date < ?", (str(cutoff),))
            self.connection.execute("DELETE FROM active_batch WHERE event_id NOT IN (SELECT event_id FROM events)")
        self.size -= cursor.rowcount
        return cursor.rowcount

    def close(self) -> None:
        self.connection.close()


class RealtimeStorage:
    def __init__(self, settings: DatabaseSettings, table: str, client: Any = None, *, scope: str = "stock"):
        validate_scope(scope)
        self.scope = scope
        self.database, self.table = settings.database, table
        self.qualified = f"{identifier(self.database)}.{identifier(table)}"
        self.client = client if client is not None else clickhouse_connect.get_client(
            host=settings.host, port=settings.port, username=settings.user,
            password=settings.password, database=settings.database, secure=settings.secure,
            connect_timeout=10, send_receive_timeout=30,
        )

    def initialize(self) -> None:
        columns = ",\n".join(f"{identifier(name)} {kind}" for name, kind in COLUMN_TYPES.items())
        self.client.command(
            f"CREATE TABLE IF NOT EXISTS {self.qualified} ({columns}, "
            "INDEX minute_minmax datetime TYPE minmax GRANULARITY 1) ENGINE = MergeTree "
            "PARTITION BY trade_date ORDER BY (trade_date, order_book_id, datetime, event_id) "
            "SETTINGS non_replicated_deduplication_window = 10000 "
            f"COMMENT 'ricequant-realtime-scope:{self.scope}'"
        )
        parameters = {"db": self.database, "table": self.table}
        structure = self.client.query(
            "SELECT engine, partition_key, sorting_key, create_table_query, comment FROM system.tables "
            "WHERE database = {db:String} AND name = {table:String}", parameters=parameters,
        ).first_row
        actual = dict(self.client.query(
            "SELECT name, type FROM system.columns WHERE database = {db:String} AND table = {table:String}",
            parameters=parameters,
        ).result_rows)
        if (actual != COLUMN_TYPES or structure[0] != "MergeTree" or structure[1] != "trade_date"
                or structure[2] != "trade_date, order_book_id, datetime, event_id"
                or "non_replicated_deduplication_window = 10000" not in structure[3]):
            raise ValueError("existing realtime table has an incompatible schema, engine or partition key")
        expected_comment = f"ricequant-realtime-scope:{self.scope}"
        if structure[4] != expected_comment and not (self.scope == "stock" and structure[4] == ""):
            raise ValueError("existing realtime table belongs to a different subscription scope")
        # Preserve stream revisions in the table; expose one whole latest observation
        # per minute without Nullable argMax skipping or background deduplication.
        fields = [name for name in COLUMNS if name not in {"trade_date", "order_book_id", "datetime"}]
        selected = ", ".join(f"tupleElement(latest, {i}) AS {identifier(name)}"
                             for i, name in enumerate(fields, 1))
        values = ", ".join(identifier(name) for name in fields)
        self.client.command(
            f"CREATE VIEW IF NOT EXISTS {identifier(self.database)}.{identifier(self.table + '_latest')} AS "
            f"SELECT trade_date, order_book_id, datetime, {selected} FROM ("
            f"SELECT trade_date, order_book_id, datetime, argMax(tuple({values}), "
            f"tuple(received_at, event_id)) AS latest FROM {self.qualified} "
            "GROUP BY trade_date, order_book_id, datetime)"
        )

    def insert(self, events: list[BarEvent], *, deduplication_token: str | None = None) -> int:
        if not events:
            return 0
        if any(event.scope != self.scope for event in events):
            raise ValueError("event scope does not match realtime table scope")
        # A lost HTTP response may mean ClickHouse already committed the insert.
        # Read event IDs before replaying the durable batch; only one writer is allowed.
        existing = {row[0] for row in self.client.query(
            f"SELECT event_id FROM {self.qualified} WHERE trade_date IN {{days:Array(Date)}} "
            "AND datetime BETWEEN toDateTime({start:String}, 'Asia/Shanghai') "
            "AND toDateTime({end:String}, 'Asia/Shanghai') AND event_id IN {ids:Array(String)}",
            parameters={"ids": [event.event_id for event in events],
                        "days": sorted({event.row()[0] for event in events}),
                        "start": min(event.row()[2] for event in events).strftime("%Y-%m-%d %H:%M:%S"),
                        "end": max(event.row()[2] for event in events).strftime("%Y-%m-%d %H:%M:%S")},
        ).result_rows}
        rows = [event.row() for event in events if event.event_id not in existing]
        if rows:
            token = deduplication_token or hashlib.sha256("\n".join(event.event_id for event in events).encode()).hexdigest()
            self.client.insert(self.qualified, rows, column_names=list(COLUMNS), settings={
                "insert_deduplicate": 1, "insert_deduplication_token": token,
            })
        return len(rows)

    def retain_partitions(self, keep: int) -> date | None:
        if keep < 1:
            raise ValueError("keep-partitions must be positive")
        partitions = self.client.query(
            "SELECT partition_id, any(partition) FROM system.parts WHERE active "
            "AND database = {db:String} AND table = {table:String} "
            "GROUP BY partition_id ORDER BY any(partition) DESC",
            parameters={"db": self.database, "table": self.table},
        ).result_rows
        # Validate every partition before allowing any destructive DDL.
        validated = []
        for partition_id, value in partitions:
            day = date.fromisoformat(str(value).strip("'"))
            if not re.fullmatch(r"[A-Za-z0-9_-]+", str(partition_id)):
                raise ValueError("unexpected partition ID")
            validated.append((str(partition_id), day))
        for partition_id, day in validated[keep:]:
            self.client.command(f"ALTER TABLE {self.qualified} DROP PARTITION ID '{partition_id}'")
            LOG.info("Dropped old realtime partition trade_date=%s", day)
        return validated[keep - 1][1] if len(validated) >= keep else None

    def close(self) -> None:
        self.client.close()


def connection_scoped_client(rq: Any) -> Any:
    """Keep rqdatac 3.8.1's server ACKs scoped to one WebSocket connection."""

    class ConnectionScopedClient(rq.LiveMarketDataClient):
        def _init_websocket_client(self):
            # The SDK otherwise unions subscribe_reply into ACKs from old
            # connections. Clear before connecting, including failed retries.
            self._subscribed.clear()
            super()._init_websocket_client()

    return ConnectionScopedClient()


class Subscription:
    """Supervised SDK reader: exceptions are delivered to the owning main loop."""

    def __init__(self, rq: Any, order_book_ids: set[str], messages: queue.Queue, batch_size: int,
                 *, scope: str = "stock"):
        validate_scope(scope)
        self.scope = scope
        self._validate_universe(order_book_ids)
        self.rq, self.order_book_ids, self.messages, self.batch_size = rq, set(order_book_ids), messages, batch_size
        self._accepted_ids = frozenset(order_book_ids)
        self.closed = threading.Event()
        self.ready = threading.Event()
        self.client = None
        self.error: Exception | None = None
        self.rejected = 0
        self.thread = threading.Thread(target=self._run, name="ricequant-minute-reader", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def _validate_universe(self, order_book_ids: set[str]) -> None:
        valid = (order_book_ids == {CSI2000} if self.scope == "csi2000"
                 else bool(order_book_ids) and all(is_hs_a_stock(obid) for obid in order_book_ids))
        if not valid:
            raise ValueError(f"instruments are outside the {self.scope} subscription scope")

    def _change(self, method: Callable[[list[str]], None], order_book_ids: set[str]) -> None:
        channels = [f"bar_{obid}" for obid in sorted(order_book_ids)]
        for start in range(0, len(channels), self.batch_size):
            method(channels[start:start + self.batch_size])

    def refresh(self, order_book_ids: set[str]) -> None:
        self._validate_universe(order_book_ids)
        if not self.ready.is_set() or self.error is not None:
            return
        removed, added = self._accepted_ids - order_book_ids, order_book_ids - self.order_book_ids
        # Publish an immutable reader snapshot before sending any changes. Keep
        # the union if a batch fails: already subscribed additions may still feed,
        # while self.order_book_ids stays unchanged so a later refresh retries all changes.
        self._accepted_ids = self._accepted_ids | order_book_ids
        self._change(self.client.unsubscribe, removed)
        self._change(self.client.subscribe, added)
        self.order_book_ids = set(order_book_ids)
        self._accepted_ids = frozenset(order_book_ids)
        LOG.info("Refreshed subscriptions scope=%s total=%d added=%d removed=%d",
                 self.scope, len(order_book_ids), len(added), len(removed))

    @property
    def confirmed_count(self) -> int:
        # SDK 3.8.1 updates _subscribed from server subscribe_reply, while the
        # public subscriptions property only reports what the user requested.
        if self.client is None:
            return 0
        confirmed = self.client._subscribed
        return sum(f"bar_{obid}" in confirmed for obid in self.order_book_ids)

    def _run(self) -> None:
        try:
            self.client = connection_scoped_client(self.rq)
            if self.closed.is_set():
                return
            info = self.client.info
            if isinstance(info, dict) and (info.get("error") or info.get("action") == "error"
                                          or info.get("success") is False):
                raise PermissionError("live market data authentication rejected")
            self._change(self.client.subscribe, self.order_book_ids)
            self.ready.set()
            for message in self.client.listen():
                if self.closed.is_set():
                    break
                if message.get("order_book_id") not in self._accepted_ids:
                    continue
                event = BarEvent(uuid.uuid4().hex, datetime.now(SHANGHAI), message, self.scope)
                try:
                    event.row()
                except (ValueError, TypeError, OverflowError) as exc:
                    self.rejected += 1
                    if self.rejected <= 5 or self.rejected % 100 == 0:
                        LOG.error("Rejected invalid native minute bar count=%d reason=%s", self.rejected, exc)
                    continue
                while not self.closed.is_set():
                    try:
                        self.messages.put(event, timeout=0.5)
                        break
                    except queue.Full:
                        continue
            if not self.closed.is_set():
                raise ConnectionError("market data listener ended unexpectedly")
        except Exception as exc:
            self.error = exc
        finally:
            if self.client is not None:
                self.client.close()

    def close(self) -> None:
        self.closed.set()
        if self.client is not None:
            self.client.close()
        self.thread.join(timeout=5)


def retry_delay(error: Exception, now: datetime, failures: int) -> float:
    if type(error).__name__ == "QuotaExceeded":
        next_day = now.astimezone(SHANGHAI).date() + timedelta(days=1)
        reset = datetime.combine(next_day, datetime.min.time(), SHANGHAI) + timedelta(minutes=1)
        return max(1, (reset - now).total_seconds())
    return min(300, 5 * 2 ** min(failures - 1, 6))


def run(settings: RiceQuantSettings, args: argparse.Namespace, stop: threading.Event) -> None:
    resolve_args(args)
    state = Path(args.state_dir)
    state.mkdir(parents=True, exist_ok=True)
    storage = RealtimeStorage(settings.database, args.table, scope=args.scope)
    outbox = None
    subscription = None
    messages: queue.Queue[BarEvent] = queue.Queue(maxsize=args.queue_rows)
    pending: list[BarEvent] = []
    # Deliberately separate from settings.lock_file and the historical runner's
    # ClickHouse ricequant_runtime_lock. Streaming must not block downloads.
    with runner_lock(str(state / "writer.lock")):
        try:
            storage.initialize()
            if args.create_table:
                return
            target = f"{settings.database.host}:{settings.database.port}/{settings.database.database}/{args.table}"
            outbox = Outbox(state / "outbox.sqlite3", target, args.max_spool_rows, scope=args.scope)
            source = RqDataClient(settings.token)
            source.initialize()
            order_book_ids = ({CSI2000} if args.scope == "csi2000"
                              else stock_universe(source.rq, datetime.now(SHANGHAI).date()))
            refreshed = datetime.now(SHANGHAI).date()
            subscription = Subscription(source.rq, order_book_ids, messages, args.subscribe_batch_size, scope=args.scope)
            subscription.start()
            LOG.info("Started native minute subscription scope=%s requested=%d recovered_outbox=%d",
                     args.scope, len(order_book_ids), outbox.size)
            next_flush = next_cleanup = next_heartbeat = time.monotonic()
            next_source_retry = next_universe_retry = 0.0
            failures = 0
            ack_deadline = time.monotonic() + 60
            cutoff = None
            while not stop.is_set():
                clock = time.monotonic()
                now = datetime.now(SHANGHAI)
                if subscription is not None and subscription.error is not None:
                    error = subscription.error
                    subscription.close()
                    subscription = None
                    failures += 1
                    delay = retry_delay(error, now, failures)
                    next_source_retry = clock + delay
                    LOG.error("Subscription stopped error_type=%s retry_in_seconds=%.0f; a disconnect may leave a data gap",
                              type(error).__name__, delay)
                if subscription is None and clock >= next_source_retry:
                    subscription = Subscription(source.rq, order_book_ids, messages, args.subscribe_batch_size, scope=args.scope)
                    subscription.start()
                    ack_deadline = clock + 60
                if subscription is not None and subscription.ready.is_set():
                    if subscription.confirmed_count == len(order_book_ids):
                        failures = 0
                    elif clock >= ack_deadline:
                        LOG.error("Server has confirmed %d/%d subscriptions; check license subscription limit and permissions",
                                  subscription.confirmed_count, len(order_book_ids))
                        # Do not treat the SDK's requested-channel list as proof of coverage.
                        ack_deadline = clock + 60
                    if (args.scope == "stock" and now.date() != refreshed and now.hour >= 7
                            and clock >= next_universe_retry):
                        try:
                            updated = stock_universe(source.rq, now.date())
                            subscription.refresh(updated)
                            order_book_ids, refreshed = updated, now.date()
                            ack_deadline = clock + 60
                        except Exception as exc:
                            next_universe_retry = clock + 300
                            LOG.error("Daily instrument refresh failed error_type=%s; retrying in 300 seconds", type(exc).__name__)
                # Keep durable backlog bounded. When full, backpressure the reader
                # instead of dropping events or allocating unbounded memory.
                capacity = min(args.batch_rows, args.max_spool_rows - outbox.size)
                if capacity > 0:
                    try:
                        pending.append(messages.get(timeout=0.2))
                    except queue.Empty:
                        pass
                    while len(pending) < capacity:
                        try:
                            pending.append(messages.get_nowait())
                        except queue.Empty:
                            break
                    if pending:
                        if cutoff is not None:
                            stale = sum(event.row()[0] < cutoff for event in pending)
                            if stale:
                                LOG.warning("Discarded %d late bars outside retained partitions cutoff=%s", stale, cutoff)
                            pending = [event for event in pending if event.row()[0] >= cutoff]
                        outbox.append(pending)
                        pending.clear()
                else:
                    stop.wait(0.2)
                if clock >= next_flush:
                    try:
                        batch = outbox.peek(args.batch_rows)
                        storage.insert(batch, deduplication_token=outbox.batch_token)
                        outbox.acknowledge([event.event_id for event in batch])
                        next_flush = clock + (0 if outbox.size else args.flush_seconds)
                    except Exception as exc:
                        next_flush = clock + args.retry_seconds
                        LOG.error("ClickHouse write failed error_type=%s durable_pending=%d; batch retained for retry",
                                  type(exc).__name__, outbox.size)
                if clock >= next_cleanup:
                    try:
                        cutoff = storage.retain_partitions(args.keep_partitions)
                        if cutoff is not None:
                            discarded = outbox.discard_before(cutoff)
                            if discarded:
                                LOG.warning("Removed %d queued bars outside retained partitions", discarded)
                        next_cleanup = clock + args.cleanup_seconds
                    except Exception as exc:
                        next_cleanup = clock + args.retry_seconds
                        LOG.error("Partition cleanup failed error_type=%s; retry scheduled", type(exc).__name__)
                if clock >= next_heartbeat:
                    LOG.info("Heartbeat scope=%s instruments=%d confirmed=%d memory_queue=%d durable_pending=%d rejected=%d",
                             args.scope, len(order_book_ids), subscription.confirmed_count if subscription else 0,
                             messages.qsize(), outbox.size, subscription.rejected if subscription else 0)
                    if outbox.size >= args.max_spool_rows:
                        LOG.error("Durable outbox full; reader is backpressured, prolonged outage may cause a market-data gap")
                    next_heartbeat = clock + 60
        finally:
            if subscription is not None:
                subscription.close()
            if outbox is not None:
                # Drain received events on a normal signal; replay on next start.
                while not messages.empty() and outbox.size < args.max_spool_rows:
                    capacity = min(args.batch_rows, args.max_spool_rows - outbox.size)
                    tail = []
                    while len(tail) < capacity:
                        try:
                            tail.append(messages.get_nowait())
                        except queue.Empty:
                            break
                    if tail:
                        outbox.append(tail)
                if pending and outbox.size + len(pending) <= args.max_spool_rows:
                    outbox.append(pending)
                if not messages.empty():
                    LOG.error("Shutdown with a full outbox: %d in-memory events could not be persisted", messages.qsize())
                LOG.info("Stopped; durable_pending=%d will replay on the next start", outbox.size)
                outbox.close()
            storage.close()


def load_env_file(path: str | None) -> None:
    if path is None:
        return
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        key, separator, value = text.partition("=")
        if not separator or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise ValueError("env file must contain Docker-style KEY=value entries")
        os.environ.setdefault(key, value)


class SecretFilter(logging.Filter):
    def __init__(self, secrets: list[str]):
        super().__init__()
        self.secrets = [value for value in secrets if value]

    def filter(self, record: logging.LogRecord) -> bool:
        text = record.getMessage()
        for secret in self.secrets:
            text = text.replace(secret, "[REDACTED]")
        record.msg, record.args = text, ()
        return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="ricequant.yaml")
    parser.add_argument("--env-file", help="Docker-style env file; existing environment variables take precedence")
    parser.add_argument("--scope", choices=("stock", "csi2000"), default="stock",
                        help="stock: all Shanghai/Shenzhen A-shares; csi2000: only bar_932000.INDX (no ticks)")
    parser.add_argument("--table", help="default: ricequant_stock_minute_realtime; csi2000: ricequant_index_minute_realtime")
    parser.add_argument("--state-dir", help="default: data/ricequant-realtime; csi2000: data/ricequant-realtime-csi2000")
    parser.add_argument("--log-dir", default="logs")
    parser.add_argument("--create-table", action="store_true", help="create/validate the table and latest view, then exit")
    parser.add_argument("--keep-partitions", type=int, default=7)
    parser.add_argument("--batch-rows", type=int, default=1000)
    parser.add_argument("--subscribe-batch-size", type=int, default=200)
    parser.add_argument("--queue-rows", type=int, default=50_000)
    parser.add_argument("--max-spool-rows", type=int, default=2_000_000)
    parser.add_argument("--flush-seconds", type=float, default=2)
    parser.add_argument("--cleanup-seconds", type=float, default=60)
    parser.add_argument("--retry-seconds", type=float, default=10)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        resolve_args(args)
    except ValueError as exc:
        parser.error(str(exc))
    for name in ("keep_partitions", "batch_rows", "subscribe_batch_size", "queue_rows", "max_spool_rows",
                 "flush_seconds", "cleanup_seconds", "retry_seconds"):
        value = getattr(args, name)
        if value <= 0 or not math.isfinite(value):
            parser.error(f"--{name.replace('_', '-')} must be finite and positive")
    load_env_file(args.env_file)
    settings = RiceQuantSettings.load(args.config, require_token=not args.create_table)
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    handlers = [logging.StreamHandler(), TimedRotatingFileHandler(
        log_dir / ("ricequant-realtime-csi2000.log" if args.scope == "csi2000" else "ricequant-realtime.log"),
        when="midnight", backupCount=7, encoding="utf-8")]
    for handler in handlers:
        handler.addFilter(SecretFilter([settings.token, settings.database.password]))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", handlers=handlers)
    logging.captureWarnings(True)
    stop = threading.Event()
    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, lambda _signum, _frame: stop.set())
    try:
        run(settings, args, stop)
    except Exception as exc:
        LOG.error("Realtime collector failed error_type=%s: %s", type(exc).__name__, exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
