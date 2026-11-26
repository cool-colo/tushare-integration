from __future__ import annotations

import hashlib
import subprocess
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from ricequant_integration.client import RqDataClient
from ricequant_integration.runner import RiceQuantRunner
from ricequant_integration.schema import TABLE_SCHEMAS
from ricequant_integration.settings import DatabaseSettings, RiceQuantSettings
from ricequant_integration.specs import DATASET_SPECS
from ricequant_integration.storage import PublishResult, RiceQuantStorage
from ricequant_integration.transform import (
    fund_holding_frame,
    stock_connect_holding_frame,
)
from tushare_integration.dwd import DWDManager


def test_holding_specs_use_plain_merge_tree_tables_and_explicit_keys():
    connect = DATASET_SPECS["stock_connect_holding_details"]
    fund = DATASET_SPECS["fund_holdings"]

    assert connect.table == "ricequant_stock_connect_holding_detail"
    assert connect.primary_key == (
        "trade_date",
        "order_book_id",
        "participant_number",
    )
    assert fund.table == "ricequant_fund_holding"
    assert "release_date_key" in fund.primary_key
    assert "symbol_key" in fund.primary_key
    assert "ENGINE = MergeTree" in TABLE_SCHEMAS[connect.table].create_sql("default")
    assert "ReplacingMergeTree" not in TABLE_SCHEMAS[fund.table].create_sql("default")


def test_stock_connect_transform_preserves_source_scale_and_identity():
    raw = pd.DataFrame(
        {
            "participant_number": ["A00001"],
            "ccass_name": ["Participant"],
            "shares_holding": [1234.5],
            "holding_ratio": [0.0123],
        },
        index=pd.MultiIndex.from_tuples(
            [("000001.XSHE", pd.Timestamp("2025-01-02"))],
            names=["order_book_id", "date"],
        ),
    )

    frame = stock_connect_holding_frame(raw, date(2025, 1, 2), "batch-a")

    assert frame.loc[0, "trade_date"] == date(2025, 1, 2)
    assert frame.loc[0, "participant_number"] == "A00001"
    assert frame.loc[0, "shares_holding"] == 1234.5
    assert frame.loc[0, "holding_ratio"] == 0.0123
    assert frame.loc[0, "_api_name"] == "get_stock_connect_holding_details"


def test_stock_connect_transform_rejects_missing_source_identity():
    raw = pd.DataFrame(
        {
            "order_book_id": ["600519.XSHG"],
            "date": [pd.Timestamp("2024-06-28")],
            "participant_number": [None],
        }
    )

    with pytest.raises(ValueError, match="missing business key"):
        stock_connect_holding_frame(raw, date(2024, 6, 28), "batch-missing")


def test_fund_transform_preserves_release_date_and_all_asset_classes():
    raw = pd.DataFrame(
        {
            "order_book_id": ["600000.XSHG", "101900.IB"],
            "weight": [0.05, 0.1],
            "shares": [100.0, None],
            "market_value": [1000.0, None],
            "type": ["Stock", "Bond"],
            "category": ["AShare", "GovernmentBond"],
            "symbol": ["浦发银行", "国债"],
            "release_date": [pd.Timestamp("2019-10-22")] * 2,
        },
        index=pd.MultiIndex.from_tuples(
            [("000001", pd.Timestamp("2019-09-30"))] * 2,
            names=["fund_id", "date"],
        ),
    )

    frame = fund_holding_frame(raw, "batch-b")

    assert set(frame["asset_type_key"]) == {"Stock", "Bond"}
    assert set(frame["report_date"]) == {date(2019, 9, 30)}
    assert set(frame["release_date"]) == {date(2019, 10, 22)}
    assert set(frame["release_date_key"]) == {date(2019, 10, 22)}
    assert set(frame["symbol_key"]) == {"浦发银行", "国债"}
    assert frame["weight"].tolist() == [0.05, 0.1]


def test_fund_transform_distinguishes_same_overseas_ticker_by_source_symbol():
    raw = pd.DataFrame(
        {
            "order_book_id": ["SAN", "SAN"],
            "weight": [0.0033, 0.007],
            "shares": [234.0, 9286.0],
            "market_value": [138852.9, 296198.01],
            "type": ["Stock", "Stock"],
            "category": ["Unknown", "Unknown"],
            "region": ["西班牙", "西班牙"],
            "symbol": ["赛诺菲", "桑坦德"],
            "release_date": [pd.Timestamp("2019-08-24")] * 2,
        },
        index=pd.MultiIndex.from_tuples(
            [("006282", pd.Timestamp("2019-06-30"))] * 2,
            names=["fund_id", "date"],
        ),
    )

    frame = fund_holding_frame(raw, "batch-overseas")

    assert set(frame["symbol_key"]) == {"赛诺菲", "桑坦德"}
    assert not frame.duplicated(
        list(DATASET_SPECS["fund_holdings"].primary_key)
    ).any()


def test_fund_transform_keeps_missing_release_date_pit_invisible_key():
    raw = pd.DataFrame(
        {
            "order_book_id": ["600000.XSHG"],
            "type": ["Stock"],
            "category": ["AShare"],
        },
        index=pd.MultiIndex.from_tuples(
            [("000001", pd.Timestamp("2019-09-30"))],
            names=["fund_id", "date"],
        ),
    )

    frame = fund_holding_frame(raw, "batch-c")

    assert pd.isna(frame.loc[0, "release_date"])
    assert frame.loc[0, "release_date_key"] == date(1970, 1, 1)


def test_fund_transform_rejects_missing_held_asset_identity():
    raw = pd.DataFrame(
        {
            "fund_id": ["000001"],
            "date": [pd.Timestamp("2019-09-30")],
            "order_book_id": [None],
        }
    )

    with pytest.raises(ValueError, match="missing business key"):
        fund_holding_frame(raw, "batch-missing")


def test_client_uses_fund_range_query_not_date_as_pit_cutoff():
    calls: list[tuple] = []

    class Fund:
        @staticmethod
        def all_instruments(**kwargs):
            calls.append(("all", kwargs))
            return pd.DataFrame({"order_book_id": ["000001"]})

        @staticmethod
        def get_holdings(ids, **kwargs):
            calls.append((ids, kwargs))
            return pd.DataFrame()

    client = RqDataClient("token", module=SimpleNamespace(fund=Fund()))
    client.fund_instruments()
    client.fund_holdings(["000001"], date(2019, 1, 1), date(2019, 12, 31))

    assert calls[0] == ("all", {"market": "cn"})
    assert calls[1][1] == {
        "start_date": date(2019, 1, 1),
        "end_date": date(2019, 12, 31),
        "market": "cn",
    }
    assert "date" not in calls[1][1]


def test_ricequant_dwd_sql_keeps_sources_separate_and_applies_pit_rules():
    manager = DWDManager()
    connect_sql = manager.render_sync_sql(
        "dwd_ricequant_stock_connect_holding_detail"
    )
    fund_sql = manager.render_sync_sql("dwd_ricequant_fund_holding")
    fund_schema = manager.build_schema(
        manager.load_spec("dwd_ricequant_fund_holding")
    )

    assert "FROM default.ricequant_stock_connect_holding_detail src" in connect_sql
    assert "addDays(src.trade_date, 1) AS `available_trade_date`" in connect_sql
    assert "'trade_date_plus_one' AS `availability_basis`" in connect_sql
    assert "FROM default.ricequant_fund_holding src" in fund_sql
    assert "FROM default.ricequant_trading_calendar" in fund_sql
    assert "FROM default.trade_cal" not in fund_sql
    assert "calendar_map.next_trade_date" in fund_sql
    available = next(
        column for column in fund_schema["columns"] if column["name"] == "available_trade_date"
    )
    assert available["nullable"] is True
    sorting_columns = fund_schema["indexes"][0]["columns"]
    assert "available_trade_date" not in sorting_columns
    assert {"fund_id", "release_date_key", "held_order_book_id"}.issubset(
        sorting_columns
    )
    columns_by_name = {column["name"]: column for column in fund_schema["columns"]}
    assert all(
        not columns_by_name[column].get("nullable", False)
        for column in sorting_columns
    )


def test_daily_publish_uses_the_table_partition_date_column():
    class Result:
        def __init__(self, value):
            self.first_row = (value,)

    class Client:
        def __init__(self):
            self.queries = []

        def query(self, sql):
            self.queries.append(sql)
            return Result(0)

    storage = object.__new__(RiceQuantStorage)
    storage.database = "default"
    storage.client = Client()
    storage._validate_non_null = lambda *_: None
    storage._validate_unique = lambda *_: None
    spec = DATASET_SPECS["stock_connect_holding_details"]

    with pytest.raises(ValueError, match="refusing to publish empty"):
        storage.publish_daily_stage(spec, "stage", date(2024, 6, 28))

    assert any("WHERE `trade_date` !=" in sql for sql in storage.client.queries)


def test_storage_migrates_fund_final_and_resumable_stages_with_symbol_key():
    class Result:
        result_rows = [
            ("ricequant_fund_holding",),
            ("ricequant_fund_holding_stage_2019_06",),
        ]

    class Client:
        def __init__(self):
            self.commands = []

        def query(self, _sql):
            return Result()

        def command(self, sql):
            self.commands.append(sql)

    storage = object.__new__(RiceQuantStorage)
    storage.database = "default"
    storage.client = Client()

    storage._migrate_fund_holding_symbol_key()

    assert len(storage.client.commands) == 2
    assert all("ADD COLUMN IF NOT EXISTS `symbol_key`" in sql for sql in storage.client.commands)
    assert any("stage_2019_06" in sql for sql in storage.client.commands)


def test_stock_connect_can_atomically_publish_a_legitimate_empty_day():
    class Result:
        first_row = (0,)

    class Client:
        def __init__(self):
            self.commands = []

        def query(self, _sql):
            return Result()

        def command(self, sql):
            self.commands.append(sql)

    storage = object.__new__(RiceQuantStorage)
    storage.database = "default"
    storage.client = Client()
    storage._validate_non_null = lambda *_: None
    storage._validate_unique = lambda *_: None
    spec = DATASET_SPECS["stock_connect_holding_details"]

    result = storage.publish_daily_stage(
        spec, "stage", date(2025, 1, 2), allow_empty=True
    )

    assert result.row_count == 0
    assert any("DROP PARTITION '2025-01-02'" in sql for sql in storage.client.commands)
    assert storage.client.commands[-1] == "DROP TABLE `default`.`stage`"


class FundHoldingState:
    def __init__(self, latest=None):
        self.latest_state = latest
        self.events = []

    def latest(self, _dataset, _slice_key):
        return self.latest_state

    def completed_slice_ranges(self, _dataset):
        return {}

    def coverage_event(self, _spec, slice_key, status, **values):
        self.events.append((slice_key, status, values))


class FundHoldingStorage:
    def __init__(self, staged=False):
        self.stages = {"2019-09": {"A"}} if staged else {}
        self.discarded = []
        self.replaced = []
        self.published = []

    def prepare_partition_stage(self, _spec, suffix):
        existed = suffix in self.stages
        self.stages.setdefault(suffix, set())
        return suffix, existed

    def discard_partition_stage(self, _spec, suffix):
        self.discarded.append(suffix)
        self.stages.pop(suffix, None)

    def replace_partition_stage_batch(
        self, _spec, stage, _key_column, requested_values, _frame
    ):
        self.replaced.extend(requested_values)
        self.stages[stage].update(requested_values)

    def publish_partition_stage(self, _spec, stage, partition, allow_empty=True):
        assert allow_empty is True
        self.published.append((stage, partition, set(self.stages.pop(stage))))
        return PublishResult(0, "hash")


def fund_holding_runner(latest=None, staged=False, today=date(2026, 11, 26)):
    calls = []

    class Client:
        @staticmethod
        def fund_instruments():
            return pd.DataFrame({"order_book_id": ["A", "B"]})

        @staticmethod
        def fund_holdings(ids, start, end):
            calls.append((tuple(ids), start, end))
            return pd.DataFrame()

    storage = FundHoldingStorage(staged=staged)
    state = FundHoldingState(latest=latest)
    runner = RiceQuantRunner(
        RiceQuantSettings(
            DatabaseSettings(host="localhost"), "", fund_holding_batch_size=1
        ),
        client=Client(),
        storage=storage,
        today=today,
    )
    runner.state = state
    runner._fetch = lambda _dataset, _label, call: (call(), 0)
    return runner, storage, state, calls


def fund_universe_hash():
    return hashlib.md5(b"A\nB", usedforsecurity=False).hexdigest()


def test_fund_partial_month_backfill_refreshes_complete_historical_month():
    runner, storage, state, calls = fund_holding_runner()

    runner._sync_fund_holdings(
        "backfill", date(2019, 9, 15), date(2019, 9, 15)
    )

    assert calls == [
        (("A",), date(2019, 9, 1), date(2019, 9, 30)),
        (("B",), date(2019, 9, 1), date(2019, 9, 30)),
    ]
    complete = next(values for _, status, values in state.events if status == "complete")
    assert complete["range_start"] == "2019-09-01"
    assert complete["range_end"] == "2019-09-30"
    assert storage.published[0][1] == "201909"


def test_fund_current_month_refresh_never_queries_future_dates():
    runner, _, state, calls = fund_holding_runner(today=date(2019, 9, 15))

    runner._sync_fund_holdings(
        "backfill", date(2019, 9, 1), date(2019, 9, 10)
    )

    assert calls == [
        (("A",), date(2019, 9, 1), date(2019, 9, 15)),
        (("B",), date(2019, 9, 1), date(2019, 9, 15)),
    ]
    complete = next(values for _, status, values in state.events if status == "complete")
    assert complete["range_end"] == "2019-09-15"


def test_fund_resume_restarts_stage_when_saved_interval_is_shorter():
    latest = SimpleNamespace(
        status="partial",
        cursor={
            "last_fund_id": "A",
            "universe_hash": fund_universe_hash(),
            "range_start": "2019-09-01",
            "range_end": "2019-09-15",
        },
    )
    runner, storage, _, calls = fund_holding_runner(latest=latest, staged=True)

    runner._sync_fund_holdings(
        "backfill", date(2019, 9, 1), date(2019, 9, 30)
    )

    assert storage.discarded == ["2019-09"]
    assert [ids for ids, _, _ in calls] == [("A",), ("B",)]
    assert storage.published[0][2] == {"A", "B"}


def test_fund_resume_keeps_stage_only_when_interval_and_universe_match():
    latest = SimpleNamespace(
        status="quota_paused",
        cursor={
            "last_fund_id": "A",
            "universe_hash": fund_universe_hash(),
            "range_start": "2019-09-01",
            "range_end": "2019-09-30",
        },
    )
    runner, storage, _, calls = fund_holding_runner(latest=latest, staged=True)

    runner._sync_fund_holdings(
        "backfill", date(2019, 9, 15), date(2019, 9, 15)
    )

    assert storage.discarded == []
    assert [ids for ids, _, _ in calls] == [("B",)]
    assert storage.published[0][2] == {"A", "B"}


def test_ricequant_dwd_script_has_valid_shell_syntax_and_both_tables():
    script = Path(__file__).resolve().parents[1] / "scripts" / "run_ricequant_dwd.sh"
    result = subprocess.run(
        ["bash", "-n", str(script)], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
    text = script.read_text(encoding="utf-8")
    assert "dwd_ricequant_stock_connect_holding_detail" in text
    assert "dwd_ricequant_fund_holding" in text
