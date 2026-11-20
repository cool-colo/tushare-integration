from __future__ import annotations

import logging
import os
import queue
import threading
import uuid
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from ricequant_integration.realtime import (
    CSI2000, DEFAULT_TABLE, INDEX_TABLE, SHANGHAI, BarEvent, Outbox, RealtimeStorage, SecretFilter, Subscription,
    build_parser, identifier, load_env_file, resolve_args, retry_delay, run, stock_universe,
)
from ricequant_integration.commands import runner_lock
from ricequant_integration.settings import DatabaseSettings, RiceQuantSettings


def bar(day: date = date(2026, 11, 12), **changes) -> BarEvent:
    payload = {
        "action": "feed", "channel": "bar_000001.XSHE", "order_book_id": "000001.XSHE",
        "datetime": int(day.strftime("%Y%m%d") + "093100"),
        "trading_date": int(day.strftime("%Y%m%d")),
        "open": 10.01, "high": 10.03, "low": 10.0, "close": 10.02,
        "volume": 12345, "total_turnover": 123456.78, "num_trades": 12,
    }
    payload.update(changes)
    return BarEvent(uuid.uuid4().hex, datetime(2026, 11, 12, 16, tzinfo=SHANGHAI), payload)


def index_bar(**changes) -> BarEvent:
    event = bar(order_book_id=CSI2000, channel=f"bar_{CSI2000}", **changes)
    return BarEvent(event.event_id, event.received_at, event.payload, "csi2000")


def test_csi2000_preserves_source_values_missing_fields_and_scope():
    event = index_bar(close=None, volume=0, total_turnover=None, num_trades=None, last=999)
    row = event.row()
    assert row[1] == CSI2000
    assert row[6:10] == [None, 0.0, None, None]
    assert row[10:12] == ["20261112093100", 20261112]
    assert row[-2:] == ["ricequant", "LiveMarketDataClient/bar_1m"]
    assert index_bar().row()[8] == 123456.78


@pytest.mark.parametrize("changes", [
    {"order_book_id": "000300.XSHG", "channel": "bar_000300.XSHG"},
    {"order_book_id": "000001.XSHE", "channel": "bar_000001.XSHE"},
    {"channel": f"tick_{CSI2000}"}, {"channel": f"bar_{CSI2000}_3m"},
    {"datetime": 20261112093101}, {"trading_date": 20261111}, {"high": 9},
    {"total_turnover": float("inf")}, {"volume": -1},
])
def test_csi2000_rejects_other_assets_channels_and_invalid_bars(changes):
    # Build directly because some cases replace the configured ID/channel.
    payload = dict(index_bar().payload, **changes)
    with pytest.raises(ValueError):
        BarEvent(uuid.uuid4().hex, bar().received_at, payload, "csi2000").row()
    with pytest.raises(ValueError):
        bar(order_book_id=CSI2000, channel=f"bar_{CSI2000}").row()


def test_csi2000_outbox_recovery_keeps_scope_and_rejects_stock_events(tmp_path):
    path = tmp_path / "index.sqlite3"
    event = index_bar(close=None)
    spool = Outbox(path, "db/index_table", 10, scope="csi2000")
    with pytest.raises(ValueError, match="scope"):
        spool.append([event, bar()])
    assert spool.size == 0
    spool.append([event])
    assert spool.peek(10) == [event]
    token = spool.batch_token
    spool.close()
    with pytest.raises(ValueError, match="scope"):
        Outbox(path, "db/index_table", 10)
    recovered = Outbox(path, "db/index_table", 10, scope="csi2000")
    assert recovered.peek(10) == [event]
    assert recovered.batch_token == token
    recovered.acknowledge([event.event_id])
    assert recovered.size == 0
    recovered.close()


def test_legacy_stock_outbox_is_preserved_and_cannot_be_reinterpreted_as_index(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    event = bar()
    spool = Outbox(path, "db/table", 10)
    spool.append([event])
    spool.connection.execute("DROP TABLE subscription_scope")
    spool.connection.commit()
    spool.close()
    with pytest.raises(ValueError, match="scope"):
        Outbox(path, "db/table", 10, scope="csi2000")
    recovered = Outbox(path, "db/table", 10)
    assert recovered.peek(10) == [event]
    recovered.close()


def test_storage_rejects_wrong_scope_before_querying_clickhouse():
    class NoQueries:
        def query(self, *_args, **_kwargs):
            pytest.fail("wrong-scope events must be rejected before ClickHouse queries")
    index = RealtimeStorage(DatabaseSettings(host="localhost"), INDEX_TABLE, NoQueries(), scope="csi2000")
    stock = RealtimeStorage(DatabaseSettings(host="localhost"), DEFAULT_TABLE, NoQueries())
    with pytest.raises(ValueError, match="scope"):
        index.insert([index_bar(), bar()])
    with pytest.raises(ValueError, match="scope"):
        stock.insert([index_bar()])


def test_csi2000_reader_requests_one_minute_channel_and_filters_other_messages():
    commands = []
    source_event = index_bar(close=None)
    class Client:
        info = {}
        _subscribed = {f"bar_{CSI2000}", "bar_000001.XSHE"}
        def subscribe(self, channels):
            commands.append(channels)
        def listen(self):
            return iter([bar().payload, dict(source_event.payload, order_book_id="000300.XSHG"),
                         dict(source_event.payload, channel=f"tick_{CSI2000}"), source_event.payload])
        def close(self):
            pass
    messages = queue.Queue()
    subscription = Subscription(SimpleNamespace(LiveMarketDataClient=Client), {CSI2000}, messages, 200, scope="csi2000")
    subscription.start()
    subscription.thread.join(timeout=2)
    assert not subscription.thread.is_alive()
    assert commands == [[f"bar_{CSI2000}"]]
    assert subscription.confirmed_count == 1
    assert subscription.rejected == 1  # the requested ID on a tick channel
    event = messages.get_nowait()
    assert event.scope == "csi2000" and event.payload == source_event.payload
    assert event.row()[6] is None
    assert messages.empty()
    with pytest.raises(ValueError, match="scope"):
        subscription.refresh({CSI2000, "000300.XSHG"})
    assert commands == [[f"bar_{CSI2000}"]]


def test_csi2000_defaults_are_isolated_and_builtin_tables_cannot_be_crossed():
    stock = build_parser().parse_args([])
    index = build_parser().parse_args(["--scope", "csi2000"])
    resolve_args(stock)
    resolve_args(index)
    assert stock.table == DEFAULT_TABLE and index.table == INDEX_TABLE
    assert stock.state_dir != index.state_dir
    for scope, table in [("stock", INDEX_TABLE), ("csi2000", DEFAULT_TABLE)]:
        args = build_parser().parse_args(["--scope", scope, "--table", table])
        with pytest.raises(ValueError, match="separate"):
            resolve_args(args)


def test_csi2000_create_table_does_not_initialize_rqdata(tmp_path, monkeypatch):
    import ricequant_integration.realtime as module
    initialized = []
    class Storage:
        def __init__(self, _settings, table, *, scope):
            initialized.append((table, scope))
        def initialize(self):
            pass
        def close(self):
            pass
    def no_rqdata(*_args, **_kwargs):
        pytest.fail("create-table must not initialize or subscribe to RQData")
    monkeypatch.setattr(module, "RealtimeStorage", Storage)
    monkeypatch.setattr(module, "RqDataClient", no_rqdata)
    settings = RiceQuantSettings(DatabaseSettings(host="localhost"), "")
    args = build_parser().parse_args(["--scope", "csi2000", "--create-table", "--state-dir", str(tmp_path)])
    run(settings, args, threading.Event())
    assert initialized == [(INDEX_TABLE, "csi2000")]
    assert not (tmp_path / "outbox.sqlite3").exists()


def test_source_time_units_zero_and_null_are_preserved():
    event = bar(volume=0, close=None, total_turnover=0, num_trades=float("nan"))
    row = event.row()
    assert row[:3] == [date(2026, 11, 12), "000001.XSHE", datetime(2026, 11, 12, 9, 31, tzinfo=SHANGHAI)]
    assert row[6:10] == [None, 0.0, 0.0, None]
    assert row[10:12] == ["20261112093100", 20261112]
    assert row[12] == event.received_at
    assert bar().row()[8] == 123456.78
    # No substitution from tick's last price for a missing minute close.
    assert bar(close=None, last=99).row()[6] is None


@pytest.mark.parametrize("changes", [
    {"trading_date": None}, {"trading_date": 20261111}, {"datetime": 20261112093101},
    {"datetime": 20261112093100001}, {"channel": "tick_000001.XSHE"},
    {"order_book_id": "200001.XSHE", "channel": "bar_200001.XSHE"},
    {"volume": -1}, {"volume": "100"}, {"close": float("inf")}, {"high": 9}, {"close": 99},
])
def test_rejects_invalid_or_mismatched_financial_messages(changes):
    with pytest.raises(ValueError):
        bar(**changes).row()


def test_a_share_universe_excludes_b_beijing_and_other_assets_and_refreshes_source():
    calls = []
    def all_instruments(**kwargs):
        calls.append(kwargs)
        return pd.DataFrame({"order_book_id": [
            "000001.XSHE", "301999.XSHE", "600000.XSHG", "688001.XSHG",
            "900901.XSHG", "200001.XSHE", "920001.XBSE", "510300.XSHG",
        ]})
    result = stock_universe(SimpleNamespace(all_instruments=all_instruments), date(2026, 11, 12))
    assert result == {"000001.XSHE", "301999.XSHE", "600000.XSHG", "688001.XSHG"}
    assert calls == [{"type": "CS", "date": date(2026, 11, 12), "market": "cn", "cached": False}]
    with pytest.raises(ValueError):
        stock_universe(SimpleNamespace(all_instruments=lambda **_: pd.DataFrame()), date.today())


def test_durable_outbox_replays_original_ids_time_and_payload_and_is_bounded(tmp_path):
    path = tmp_path / "spool.sqlite3"
    first, second = bar(), bar(close=None)
    spool = Outbox(path, "db/table", 2)
    spool.append([first, second])
    with pytest.raises(BufferError):
        spool.append([bar()])
    spool.close()
    recovered = Outbox(path, "db/table", 2)
    assert recovered.peek(10) == [first, second]
    recovered.acknowledge([first.event_id])
    assert recovered.size == 1
    recovered.close()
    with pytest.raises(ValueError, match="different ClickHouse target"):
        Outbox(path, "other/table", 2)


def test_outbox_drops_only_events_older_than_actual_retained_cutoff(tmp_path):
    spool = Outbox(tmp_path / "spool.sqlite3", "db/table", 10)
    spool.append([bar(date(2026, 9, 25)), bar(date(2026, 10, 9))])
    assert spool.discard_before(date(2026, 10, 9)) == 1
    assert spool.size == 1
    assert spool.peek(10)[0].row()[0] == date(2026, 10, 9)
    spool.close()


def test_inflight_batch_remains_identical_when_more_events_arrive_and_across_restart(tmp_path):
    path = tmp_path / "spool.sqlite3"
    first, second = bar(), bar()
    spool = Outbox(path, "db/table", 10)
    spool.append([first])
    assert spool.peek(1000) == [first]
    spool.append([second])
    assert spool.peek(1000) == [first]
    spool.close()
    recovered = Outbox(path, "db/table", 10)
    assert recovered.peek(1000) == [first]
    recovered.acknowledge([first.event_id])
    assert recovered.peek(1000) == [second]
    recovered.close()


def test_inflight_token_survives_retention_removing_only_old_events(tmp_path):
    spool = Outbox(tmp_path / "spool.sqlite3", "db/table", 10)
    old, current = bar(date(2026, 9, 25)), bar(date(2026, 10, 9))
    spool.append([old, current])
    assert spool.peek(1000) == [old, current]
    token = spool.batch_token
    assert token
    spool.discard_before(date(2026, 10, 9))
    assert spool.peek(1000) == [current]
    assert spool.batch_token == token
    spool.close()


class PartitionClient:
    def __init__(self, rows):
        self.rows, self.commands = rows, []
    def query(self, sql, parameters=None):
        assert "WHERE active" in sql
        assert parameters == {"db": "default", "table": "test_realtime"}
        return SimpleNamespace(result_rows=self.rows)
    def command(self, sql):
        self.commands.append(sql)


def test_retention_keeps_seven_actual_partitions_across_a_long_holiday():
    days = ["2026-10-12", "2026-10-09", "2026-09-30", "2026-09-29", "2026-09-28",
            "2026-09-25", "2026-09-24", "2026-09-23", "2026-09-22"]
    client = PartitionClient([(day.replace("-", ""), day) for day in days])
    storage = RealtimeStorage(DatabaseSettings(host="localhost"), "test_realtime", client)
    assert storage.retain_partitions(7) == date(2026, 9, 24)
    assert client.commands == [
        "ALTER TABLE `default`.`test_realtime` DROP PARTITION ID '20260923'",
        "ALTER TABLE `default`.`test_realtime` DROP PARTITION ID '20260922'",
    ]


def test_retention_validates_all_partitions_before_deleting_anything():
    client = PartitionClient([("20261012", "2026-10-12"), ("bad';DROP TABLE x", "2026-09-23")])
    storage = RealtimeStorage(DatabaseSettings(host="localhost"), "test_realtime", client)
    with pytest.raises(ValueError):
        storage.retain_partitions(1)
    assert client.commands == []
    with pytest.raises(ValueError):
        identifier("realtime; DROP TABLE x")


def test_subscription_refresh_adds_new_listings_and_removes_delistings_without_tick_channels():
    commands = []
    client = SimpleNamespace(
        subscribe=lambda channels: commands.append(("subscribe", channels)),
        unsubscribe=lambda channels: commands.append(("unsubscribe", channels)),
        _subscribed={"bar_000001.XSHE"},
    )
    subscription = Subscription(None, {"000001.XSHE", "600000.XSHG"}, queue.Queue(), 200)
    subscription.client = client
    subscription.ready.set()
    assert subscription.confirmed_count == 1
    subscription.refresh({"000001.XSHE", "301999.XSHE"})
    assert commands == [("unsubscribe", ["bar_600000.XSHG"]), ("subscribe", ["bar_301999.XSHE"])]
    assert subscription.order_book_ids == {"000001.XSHE", "301999.XSHE"}


def test_reader_exceptions_reach_supervisor_and_connection_closes():
    class FailedClient:
        info = {}
        closed = False
        def subscribe(self, channels):
            pass
        def listen(self):
            raise ConnectionError("disconnected")
        def close(self):
            self.closed = True
    subscription = Subscription(SimpleNamespace(LiveMarketDataClient=FailedClient),
                                {"000001.XSHE"}, queue.Queue(), 200)
    subscription.start()
    subscription.thread.join(timeout=2)
    assert isinstance(subscription.error, ConnectionError)
    assert subscription.client.closed


def test_normally_ended_reader_is_restarted_instead_of_silently_stalling():
    class Client:
        info = {}
        def subscribe(self, channels):
            pass
        def listen(self):
            return iter([])
        def close(self):
            pass
    subscription = Subscription(SimpleNamespace(LiveMarketDataClient=Client),
                                {"000001.XSHE"}, queue.Queue(), 200)
    subscription.start()
    subscription.thread.join(timeout=2)
    assert isinstance(subscription.error, ConnectionError)


def test_realtime_start_does_not_conflict_with_held_download_lock(tmp_path, monkeypatch):
    import ricequant_integration.realtime as module
    initialized = []
    class FakeStorage:
        def __init__(self, *_, **_kwargs):
            pass
        def initialize(self):
            initialized.append(True)
        def close(self):
            pass
    monkeypatch.setattr(module, "RealtimeStorage", FakeStorage)
    download_lock = str(tmp_path / "download.lock")
    settings = RiceQuantSettings(DatabaseSettings(host="localhost"), "", lock_file=download_lock)
    args = build_parser().parse_args(["--create-table", "--state-dir", str(tmp_path / "realtime")])
    with runner_lock(download_lock):
        run(settings, args, threading.Event())
    assert initialized == [True]
    assert (tmp_path / "realtime" / "writer.lock").exists()


@pytest.mark.parametrize("scope", ["stock", "csi2000"])
def test_supervisor_retries_reader_and_clickhouse_and_persists_received_events(tmp_path, monkeypatch, scope):
    import ricequant_integration.realtime as module
    stop = threading.Event()
    clock = [0.0]
    sessions = []
    writes = []
    targets = []
    inserts = [0]
    class FakeStorage:
        def __init__(self, _settings, table, **kwargs):
            targets.append((table, kwargs["scope"]))
        def initialize(self):
            pass
        def insert(self, events, **_kwargs):
            inserts[0] += 1
            if inserts[0] == 1:
                raise ConnectionError("database temporarily unavailable")
            writes.extend(event.event_id for event in events)
            if inserts[0] == 10:
                stop.set()
        def retain_partitions(self, _keep):
            return None
        def close(self):
            pass
    class FakeSource:
        def __init__(self, _token):
            def all_instruments(**_kwargs):
                assert scope == "stock", "CSI 2000 must not request the stock universe"
                return pd.DataFrame({"order_book_id": ["000001.XSHE"]})
            self.rq = SimpleNamespace(all_instruments=all_instruments)
        def initialize(self):
            pass
    class FakeSubscription:
        def __init__(self, _rq, ids, messages, _batch_size, **kwargs):
            assert kwargs["scope"] == scope
            assert ids == ({CSI2000} if scope == "csi2000" else {"000001.XSHE"})
            self.messages = messages
            self.error = None
            self.ready = threading.Event()
            self.confirmed_count, self.rejected = 1, 0
            self.event = index_bar() if scope == "csi2000" else bar()
            sessions.append(self)
        def start(self):
            self.ready.set()
            self.messages.put(self.event)
            if len(sessions) == 1:
                self.error = ConnectionError("reader stopped")
        def close(self):
            pass
    class FastQueue(queue.Queue):
        def get(self, block=True, timeout=None):
            return super().get(block=False)
    def monotonic():
        clock[0] += 1
        return clock[0]
    monkeypatch.setattr(module, "RealtimeStorage", FakeStorage)
    monkeypatch.setattr(module, "RqDataClient", FakeSource)
    monkeypatch.setattr(module, "Subscription", FakeSubscription)
    monkeypatch.setattr(module.time, "monotonic", monotonic)
    monkeypatch.setattr(module.queue, "Queue", FastQueue)
    settings = RiceQuantSettings(DatabaseSettings(host="localhost"), "test-token")
    args = build_parser().parse_args(["--scope", scope, "--state-dir", str(tmp_path),
                                     "--retry-seconds", "1", "--flush-seconds", "1"])
    run(settings, args, stop)
    assert len(sessions) == 2
    assert writes == [session.event.event_id for session in sessions]
    assert targets == [(INDEX_TABLE if scope == "csi2000" else DEFAULT_TABLE, scope)]
    recovered = Outbox(tmp_path / "outbox.sqlite3", "localhost:8123/default/" + args.table,
                       args.max_spool_rows, scope=scope)
    assert recovered.size == 0
    recovered.close()


def test_quota_exhaustion_waits_for_shanghai_next_day_and_network_errors_back_off():
    QuotaExceeded = type("QuotaExceeded", (Exception,), {})
    now = datetime(2026, 11, 12, 23, 59, tzinfo=SHANGHAI)
    assert retry_delay(QuotaExceeded(), now, 1) == 120
    assert retry_delay(ConnectionError(), now, 1) == 5
    assert retry_delay(ConnectionError(), now, 100) == 300


def test_env_file_is_not_executed_and_existing_environment_has_precedence(tmp_path, monkeypatch):
    path = tmp_path / "credentials.env"
    path.write_text("# comment\nRQDATA_TOKEN=opaque-$token-$(no_execution)\nDB_HOST=from-file\n")
    monkeypatch.delenv("RQDATA_TOKEN", raising=False)
    monkeypatch.setenv("DB_HOST", "existing")
    load_env_file(str(path))
    assert os.environ["RQDATA_TOKEN"] == "opaque-$token-$(no_execution)"
    assert os.environ["DB_HOST"] == "existing"


def test_logging_redacts_credentials():
    record = logging.LogRecord("test", logging.ERROR, "", 0, "error with %s", ("secret-token",), None)
    SecretFilter(["secret-token"]).filter(record)
    assert record.getMessage() == "error with [REDACTED]"


@pytest.fixture
def live_storage(request):
    if os.environ.get("RICEQUANT_TEST_CLICKHOUSE") != "1":
        pytest.skip("set RICEQUANT_TEST_CLICKHOUSE=1 to validate temporary tables on project ClickHouse")
    settings = RiceQuantSettings.load(require_token=False).database
    table = "test_ricequant_realtime_" + uuid.uuid4().hex
    storage = RealtimeStorage(settings, table, scope=getattr(request, "param", "stock"))
    try:
        storage.initialize()
        yield storage
    finally:
        storage.client.command(f"DROP VIEW IF EXISTS `{settings.database}`.`{table}_latest`")
        storage.client.command(f"DROP TABLE IF EXISTS `{settings.database}`.`{table}`")
        storage.close()


@pytest.mark.parametrize("live_storage", ["csi2000"], indirect=True)
def test_clickhouse_csi2000_writes_retry_and_latest_null_in_separate_table(live_storage):
    storage = live_storage
    original = index_bar()
    assert storage.insert([original]) == 1
    assert storage.insert([original]) == 0
    event = index_bar(close=None, total_turnover=None, num_trades=None)
    revised = BarEvent(event.event_id, original.received_at + timedelta(seconds=1), event.payload, "csi2000")
    assert storage.insert([revised]) == 1
    rows = storage.client.query(
        f"SELECT order_book_id, close, total_turnover, num_trades, event_id "
        f"FROM `{storage.database}`.`{storage.table}_latest`"
    ).result_rows
    assert rows == [(CSI2000, None, None, None, revised.event_id)]
    assert storage.client.query(f"SELECT count() FROM {storage.qualified}").first_row[0] == 2
    with pytest.raises(ValueError, match="scope"):
        storage.insert([bar()])
    # Even a custom table name cannot be reused by a stock collector.
    other_scope = RealtimeStorage(RiceQuantSettings.load(require_token=False).database,
                                  storage.table, storage.client)
    with pytest.raises(ValueError, match="scope"):
        other_scope.initialize()


def test_clickhouse_ambiguous_insert_retry_does_not_duplicate_and_latest_keeps_null(live_storage):
    storage = live_storage
    original = bar()
    insert = storage.client.insert
    def ambiguous_insert(*args, **kwargs):
        insert(*args, **kwargs)
        raise ConnectionError("HTTP response lost after server commit")
    storage.client.insert = ambiguous_insert
    with pytest.raises(ConnectionError):
        storage.insert([original])
    storage.client.insert = insert
    assert storage.insert([original]) == 0
    revised = bar(close=None)
    revised = BarEvent(revised.event_id, original.received_at + timedelta(seconds=1), revised.payload)
    assert storage.insert([revised]) == 1
    assert storage.client.query(f"SELECT count() FROM {storage.qualified}").first_row[0] == 2
    latest = storage.client.query(f"SELECT close, event_id FROM `{storage.database}`.`{storage.table}_latest`").first_row
    assert latest == (None, revised.event_id)


def test_clickhouse_deduplication_token_handles_retry_even_when_lookup_misses_commit(live_storage):
    storage = live_storage
    event = bar()
    assert storage.insert([event]) == 1
    query = storage.client.query
    def stale_lookup(sql, **kwargs):
        if sql.startswith("SELECT event_id"):
            return SimpleNamespace(result_rows=[])
        return query(sql, **kwargs)
    storage.client.query = stale_lookup
    storage.insert([event])
    storage.client.query = query
    assert query(f"SELECT count() FROM {storage.qualified}").first_row[0] == 1


def test_clickhouse_real_date_partitions_are_reduced_to_seven(live_storage):
    storage = live_storage
    # Calendar gaps are intentional: retention counts existing partitions.
    days = [date(2026, 10, 12), date(2026, 10, 9), date(2026, 9, 30), date(2026, 9, 29),
            date(2026, 9, 28), date(2026, 9, 25), date(2026, 9, 24), date(2026, 9, 23)]
    storage.insert([bar(day) for day in days])
    assert storage.retain_partitions(7) == date(2026, 9, 24)
    result = storage.client.query(f"SELECT DISTINCT trade_date FROM {storage.qualified} ORDER BY trade_date DESC").result_rows
    assert [row[0] for row in result] == days[:7]
