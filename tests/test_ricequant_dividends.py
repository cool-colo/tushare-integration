from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest

from ricequant_integration.client import RqDataClient
from ricequant_integration.commands import build_parser
from ricequant_integration.quota import QuotaPaused, QuotaSnapshot
from ricequant_integration.runner import RiceQuantRunner
from ricequant_integration.schema import TABLE_SCHEMAS
from ricequant_integration.settings import DatabaseSettings, RiceQuantSettings
from ricequant_integration.specs import DATASET_SPECS
from ricequant_integration.storage import PublishResult, dataframe_hash
from ricequant_integration.transform import DIVIDEND_COLUMNS, dividend_frame
from tushare_integration.db_engine import ClickhouseEngine
from tushare_integration.dwd import DWDManager
from tushare_integration.quality import QualityManager


def source_row(identifier="000001.XSHE", **overrides):
    return {
        "order_book_id": identifier, "effective_date": "2024-06-30",
        "sequence_num": 1, "info_date": "2024-09-26",
        "ex_dividend_date": "2024-10-10", "dividend_cash_before_tax": 2.46,
        "special_dividend": False, "proposal_announcement_date": "2024-08-16",
        "event_procedure": "方案实施", "dividend_base": 19405918198.0,
        "if_dividend": "是", "rice_create_tm": "2026-02-02 12:26:09",
        **overrides,
    }


@pytest.mark.parametrize("index", [None, ["effective_date"], ["order_book_id", "effective_date"]])
def test_transform_shapes_units_and_source_dates(index):
    raw = pd.DataFrame([source_row()])
    if index:
        raw = raw.set_index(index)
    frame = dividend_frame(raw, "batch")
    assert list(frame) == DIVIDEND_COLUMNS
    row = frame.iloc[0]
    assert row.effective_date == date(2024, 6, 30)
    assert row.info_date == date(2024, 9, 26)
    assert row.proposal_announcement_date == date(2024, 8, 16)
    assert row.dividend_cash_before_tax == 2.46
    assert pd.isna(row.dividend_bonus_share)
    assert row.event_procedure == "方案实施"
    assert row.dividend_base == 19405918198.0
    assert str(row.rice_create_tm.tz) == "Asia/Shanghai"
    assert row.rice_create_tm.hour == 12
    assert row["_api_name"] == "get_dividend_info"


def test_empty_missing_disclosure_and_no_dividend_remain_explicit():
    assert list(dividend_frame(pd.DataFrame(), "batch")) == DIVIDEND_COLUMNS
    frame = dividend_frame(pd.DataFrame([source_row(
        info_date=None, ex_dividend_date=None, special_dividend=None,
        dividend_cash_before_tax=None, if_dividend="否", event_procedure="预案",
    )]), "batch")
    assert len(frame) == 1
    assert pd.isna(frame.iloc[0].info_date)
    assert pd.isna(frame.iloc[0].special_dividend)
    assert pd.isna(frame.iloc[0].dividend_cash_before_tax)
    assert frame.iloc[0].if_dividend == "否"


def test_sequences_preserved_identical_duplicates_collapsed_and_hash_stable():
    rows = [source_row(), source_row(sequence_num=2, dividend_cash_before_tax=1.0), source_row()]
    one = dividend_frame(pd.DataFrame(rows), "first")
    two = dividend_frame(pd.DataFrame(list(reversed(rows))), "second")
    assert len(one) == 2
    assert set(one.sequence_num) == {1, 2}
    assert dataframe_hash(one, DATASET_SPECS["stock_dividend_info"].primary_key) == dataframe_hash(
        two, DATASET_SPECS["stock_dividend_info"].primary_key
    )


@pytest.mark.parametrize("overrides, message", [
    ({"sequence_num": None}, "missing business key"),
    ({"sequence_num": 1.5}, "must be an integer"),
    ({"effective_date": "not-a-date"}, ""),
    ({"order_book_id": ""}, "empty order_book_id"),
    ({"new_source_field": 1}, "unmapped fields"),
    ({"special_dividend": "false"}, "must be boolean"),
    ({"dividend_cash_before_tax": float("inf")}, "non-finite"),
])
def test_invalid_source_is_not_published(overrides, message):
    with pytest.raises(ValueError, match=message):
        dividend_frame(pd.DataFrame([source_row(**overrides)]), "batch")


def test_conflicting_key_fails_without_arbitrary_selection():
    with pytest.raises(ValueError, match="conflicting get_dividend_info"):
        dividend_frame(pd.DataFrame([source_row(), source_row(dividend_cash_before_tax=3.0)]), "batch")


def test_missing_sequence_column_is_not_synthesized():
    with pytest.raises(ValueError, match="lacks"):
        dividend_frame(pd.DataFrame([source_row()]).drop(columns="sequence_num"), "batch")


def test_client_uses_effective_date_bounds_and_all_instruments_without_date():
    calls = []
    module = SimpleNamespace(
        get_dividend_info=lambda *args, **kwargs: calls.append((args, kwargs)),
        all_instruments=lambda **kwargs: calls.append(((), kwargs)),
    )
    client = RqDataClient("token", module)
    assert client.stock_dividend_info(["000001.XSHE"], date(2015, 1, 1), date(2026, 1, 1)).empty
    client.dividend_instruments()
    assert calls[0] == ((["000001.XSHE"],), {
        "start_date": date(2015, 1, 1), "end_date": date(2026, 1, 1), "market": "cn",
    })
    assert calls[1][1] == {"type": "CS", "market": "cn"}


class MemoryState:
    def __init__(self):
        self.events = []

    def latest(self, dataset, key):
        return next((SimpleNamespace(status=e["status"], cursor=deepcopy(e.get("cursor", {})))
                     for e in reversed(self.events) if e["key"] == key), None)

    def completed_slice_ranges(self, dataset):
        latest = {e["key"]: e for e in self.events}
        return {key: (date.fromisoformat(e["range_start"]), date.fromisoformat(e["range_end"]))
                for key, e in latest.items() if e["status"] == "complete"}

    def coverage_event(self, spec, key, status, **kwargs):
        self.events.append(deepcopy(dict(key=key, status=status, **kwargs)))

    def run_event(self, *args, **kwargs):
        pass


class MemoryStorage:
    def __init__(self):
        self.frames = {}
        self.publications = []
        self.observations = []
        self.fail_identifier = None

    def estimate_bytes(self, dataset, fallback):
        return 1

    def record_quota_observation(self, *args):
        self.observations.append(args)

    def distributed_runner_lock(self, run_id):
        return nullcontext()

    def publish_partition(self, spec, partition, frame, *, replace_range):
        identifier = partition.strip("'")
        if identifier == self.fail_identifier:
            raise RuntimeError("publication interrupted")
        old = self.frames.get(identifier, frame.iloc[:0])
        column, lower, upper = replace_range
        keep = old.loc[~old[column].between(lower, upper)]
        result = (frame.copy() if keep.empty else keep.copy() if frame.empty
                  else pd.concat([keep, frame], ignore_index=True))
        assert not result.duplicated(list(spec.primary_key)).any()
        self.frames[identifier] = result
        self.publications.append((identifier, replace_range))
        return PublishResult(len(result), dataframe_hash(result, spec.primary_key))


class Source:
    def __init__(self):
        self.calls = []
        self.universe_calls = 0
        self.rows = [source_row("000001.XSHE"), source_row("600000.XSHG")]
        self.pause_after = None

    def quota(self):
        return QuotaSnapshot(0, 0)

    def dividend_instruments(self):
        self.universe_calls += 1
        return pd.DataFrame({"order_book_id": ["600000.XSHG", "000001.XSHE", "900901.XSHG", "200001.XSHE"],
                             "de_listed_date": ["2020-01-01", None, None, None]})

    def stock_dividend_info(self, ids, lower, upper):
        if self.pause_after is not None and len(self.calls) >= self.pause_after:
            raise QuotaPaused("test quota exhausted")
        self.calls.append((ids, lower, upper))
        return pd.DataFrame([row for row in self.rows if row["order_book_id"] in ids
                             and lower <= date.fromisoformat(row["effective_date"]) <= upper])


def make_runner(today=date(2026, 11, 26), state=None, source=None, storage=None, batch_size=1):
    runner = RiceQuantRunner(
        RiceQuantSettings(database=DatabaseSettings("localhost"), token="token",
                          stock_dividend_batch_size=batch_size),
        client=source or Source(), storage=storage or MemoryStorage(), today=today,
    )
    runner.state = state or MemoryState()
    runner.calendars = []
    runner.initialize = lambda: None

    def sync_calendar(lower, upper):
        runner.calendars.append((lower, upper))
        return []

    runner._sync_calendar = sync_calendar
    return runner


def test_incremental_rechecks_all_history_delisted_stocks_and_source_revision():
    runner = make_runner()
    runner._sync_stock_dividends("incremental", None, None)
    assert runner.client.calls[0][1:] == (date(2015, 1, 1), runner.today)
    assert set(runner.storage.frames) == {"000001.XSHE", "600000.XSHG"}
    runner.client.rows[0]["dividend_cash_before_tax"] = 3.0
    runner._sync_stock_dividends("incremental", None, None)
    assert len(runner.client.calls) == 4
    assert runner.storage.frames["000001.XSHE"].iloc[0].dividend_cash_before_tax == 3.0
    assert runner.calendars[0][1] == runner.today + timedelta(days=14)


def test_partial_backfill_and_empty_response_preserve_unrequested_rows():
    runner = make_runner()
    runner.requested_order_book_ids = ("000001.XSHE",)
    runner.client.rows = [source_row(), source_row(effective_date="2024-12-31")]
    runner._sync_stock_dividends("backfill", date(2015, 1, 1), date(2025, 1, 1))
    runner.client.rows = []
    runner._sync_stock_dividends("backfill", date(2024, 6, 1), date(2024, 6, 30))
    frame = runner.storage.frames["000001.XSHE"]
    assert frame.effective_date.tolist() == [date(2024, 12, 31)]


def test_quota_pause_resumes_unfinished_stocks_before_extending_end_and_universe():
    one = make_runner()
    one.client.pause_after = 1
    with pytest.raises(QuotaPaused):
        one._sync_stock_dividends("incremental", None, None)
    assert list(one.storage.frames) == ["000001.XSHE"]
    old_end = one.today
    one.client.pause_after = None
    two = make_runner(today=old_end + timedelta(days=1), state=one.state,
                      source=one.client, storage=one.storage)
    two._sync_stock_dividends("incremental", None, None)
    calls = two.client.calls
    assert calls[1] == (["600000.XSHG"], date(2015, 1, 1), old_end)
    assert calls[2][0] == ["000001.XSHE"]
    assert calls[2][2] == two.today
    assert two.client.universe_calls == 2  # reuse saved list, then resolve new cycle
    cycles = [e for e in two.state.events if e["key"].startswith("refresh:") and e["status"] == "complete"]
    assert [e["range_end"] for e in cycles] == [str(old_end), str(two.today)]


def test_crash_during_batch_publication_resumes_after_last_published_instrument():
    runner = make_runner(batch_size=2)
    runner.storage.fail_identifier = "600000.XSHG"
    with pytest.raises(RuntimeError, match="publication interrupted"):
        runner._sync_stock_dividends("backfill", date(2015, 1, 1), date(2026, 11, 26))
    runner.storage.fail_identifier = None
    runner._sync_stock_dividends("backfill", date(2015, 1, 1), date(2026, 11, 26))
    assert runner.client.calls[-1][0] == ["600000.XSHG"]
    assert len(runner.storage.frames["000001.XSHE"]) == 1


def test_bootstrap_can_skip_complete_bounds_but_backfill_and_incremental_refresh():
    runner = make_runner()
    runner._sync_stock_dividends("bootstrap", None, None)
    runner._sync_stock_dividends("bootstrap", None, None)
    assert len(runner.client.calls) == 2
    runner._sync_stock_dividends("backfill", None, None)
    runner._sync_stock_dividends("incremental", None, None)
    assert len(runner.client.calls) == 6


def test_bootstrap_resume_skips_previously_completed_stock_after_cursor():
    runner = make_runner()
    lower, upper = date(2015, 1, 1), runner.today
    complete_stock = "000002.XSHE"
    spec = DATASET_SPECS["stock_dividend_info"]
    runner.state.coverage_event(
        spec, f"{complete_stock}:{lower}:{upper}", "complete",
        range_start=str(lower), range_end=str(upper),
    )
    runner.requested_order_book_ids = ("000001.XSHE", complete_stock, "600000.XSHG")
    runner.client.pause_after = 1
    with pytest.raises(QuotaPaused):
        runner._sync_stock_dividends("bootstrap", None, None)

    runner.client.pause_after = None
    runner._sync_stock_dividends("bootstrap", None, None)

    assert runner.client.calls == [
        (["000001.XSHE"], lower, upper),
        (["600000.XSHG"], lower, upper),
    ]
    assert runner.state.events[-1]["status"] == "complete"


@pytest.mark.parametrize("bounded_end", [False, True])
def test_run_fetches_one_dividend_calendar_without_extending_other_datasets(bounded_end):
    runner = make_runner()
    start = date(2015, 1, 1)
    end = runner.today - timedelta(days=2) if bounded_end else None
    horizon = runner.today + timedelta(days=14)
    market_dates = []

    def trading_dates(lower, upper):
        runner.calendars.append((lower, upper))
        return sorted({end or runner.today, runner.today, horizon})

    runner.client.trading_dates = trading_dates
    runner._sync_calendar = RiceQuantRunner._sync_calendar.__get__(runner)
    runner._sync_index_daily = lambda mode, dates, start, end: market_dates.extend(dates)

    result = runner.run("incremental", ["stock_dividend_info", "index_daily"], start, end)

    assert result.status == "complete"
    assert runner.calendars == [(start, horizon)]
    assert market_dates == [end or runner.today]
    calendar_frame = runner.storage.frames[str(horizon.year)]
    assert calendar_frame.loc[calendar_frame.calendar_date == horizon, "is_trading_day"].item() == 1


@pytest.mark.parametrize("dividend_watermark", [None, date(2020, 1, 1)])
def test_incremental_index_requests_match_when_mixed_with_dividends(dividend_watermark):
    def run_indexes(datasets):
        runner = make_runner()
        runner.settings = replace(runner.settings, indexes=("000300.XSHG",))
        first_incremental_day = runner.today - timedelta(days=62)
        future = runner.today + timedelta(days=14)
        source_dates = (
            date(1990, 1, 2), date(2015, 1, 5), first_incremental_day, runner.today, future,
        )
        index_calls = []

        def latest_completed_end(dataset, prefix=""):
            return dividend_watermark if dataset == "stock_dividend_info" else None

        def sync_calendar(lower, upper):
            runner.calendars.append((lower, upper))
            return [day for day in source_dates if lower <= day <= upper]

        def index_daily(index_id, lower, upper):
            index_calls.append((index_id, lower, upper))
            return pd.DataFrame()

        runner.state.latest_completed_end = latest_completed_end
        runner._sync_calendar = sync_calendar
        runner.client.index_daily = index_daily
        assert runner.run("incremental", datasets).status == "complete"
        return runner.calendars, index_calls

    solo_calendars, solo_index_calls = run_indexes(["index_daily"])
    mixed_calendars, mixed_index_calls = run_indexes(["index_daily", "stock_dividend_info"])

    assert solo_calendars == [(date(2026, 9, 25), date(2026, 11, 26))]
    assert mixed_index_calls == solo_index_calls == [
        ("000300.XSHG", date(2026, 9, 25), date(2026, 9, 25)),
        ("000300.XSHG", date(2026, 11, 26), date(2026, 11, 26)),
    ]
    assert mixed_calendars == [(date(2015, 1, 1), date(2026, 12, 10))]


def test_run_dividend_calendar_includes_earlier_saved_range_start():
    runner = make_runner()
    runner.client.pause_after = 1
    assert runner.run("incremental", ["stock_dividend_info"]).status == "quota_paused"

    runner.calendars.clear()
    runner.client.pause_after = None
    runner.settings = replace(runner.settings, stock_dividend_start_date="2016-01-01")
    result = runner.run("incremental", ["stock_dividend_info"])

    assert result.status == "complete"
    assert runner.calendars == [(date(2015, 1, 1), runner.today + timedelta(days=14))]
    assert runner.client.calls[1] == (["600000.XSHG"], date(2015, 1, 1), runner.today)
    assert runner.client.calls[2][1] == date(2016, 1, 1)


def test_quota_guard_pauses_before_api_with_durable_cycle_cursor():
    runner = make_runner()
    runner.requested_order_book_ids = ("000001.XSHE",)
    runner.client.quota = lambda: QuotaSnapshot(1000, 999)
    with pytest.raises(QuotaPaused):
        runner._sync_stock_dividends("incremental", None, None)
    assert not runner.client.calls
    assert not runner.storage.publications
    assert runner.state.events[-1]["status"] == "partial"
    assert runner.state.events[-1]["cursor"]["last_instrument"] == ""


def test_changing_explicit_bounds_creates_new_cycle_not_mixed_completion():
    runner = make_runner()
    runner.client.pause_after = 1
    with pytest.raises(QuotaPaused):
        runner._sync_stock_dividends("backfill", date(2015, 1, 1), date(2025, 1, 1))
    runner.client.pause_after = None
    runner._sync_stock_dividends("backfill", date(2015, 1, 1), date(2025, 6, 1))
    assert runner.client.calls[1][0] == ["000001.XSHE"]
    assert runner.client.calls[1][2] == date(2025, 6, 1)
    cursors = [e for e in runner.state.events if e["key"].startswith("refresh:")]
    assert len(set(e["key"] for e in cursors)) == 2


def test_out_of_range_and_unexpected_instrument_never_replace_existing_data():
    runner = make_runner()
    runner.client.stock_dividend_info = lambda *args: pd.DataFrame([source_row("OTHER")])
    with pytest.raises(ValueError, match="unexpected instruments"):
        runner._sync_stock_dividends("backfill", None, None)
    assert not runner.storage.publications
    runner.client.stock_dividend_info = lambda *args: pd.DataFrame([source_row(effective_date="2000-01-01")])
    with pytest.raises(ValueError, match="outside effective_date"):
        runner._sync_stock_dividends("backfill", None, None)
    assert not runner.storage.publications


def test_schema_dwd_source_separation_nullable_availability_and_pit_limits():
    spec = DATASET_SPECS["stock_dividend_info"]
    assert spec.primary_key == ("order_book_id", "effective_date", "sequence_num")
    assert "ENGINE = MergeTree" in TABLE_SCHEMAS[spec.table].create_sql("default")
    manager = DWDManager()
    dwd = manager.load_spec("dwd_ricequant_stock_dividend_info")
    schema = manager.build_schema(dwd)
    # Validate all types against the real engine, not only SQL text.
    for column in schema["columns"]:
        ClickhouseEngine.column_type_sql(column)
    available = next(column for column in schema["columns"] if column["name"] == "available_trade_date")
    assert available["nullable"] is True
    sql = manager.render_sync_sql(dwd["name"])
    assert "FROM default.ricequant_stock_dividend_info src" in sql
    assert "FROM default.ricequant_trading_calendar" in sql
    assert "src.info_date AS _calendar_lookup_date" in sql
    assert "calendar_map.calendar_date = src._calendar_lookup_date" in sql
    assert "'source_current_disclosure_dated'" in sql
    assert "info_date_next_trade_day" in sql
    assert "src.effective_date AS `event_date`" in sql
    assert "coalesce(" not in dwd["available_trade_date_expr"].lower()
    assert "proposal_announcement_date" not in dwd["available_trade_date_expr"]
    assert "rice_create_tm" not in dwd["available_trade_date_expr"]


def test_independent_settings_cli_and_historical_calendar(tmp_path):
    config = tmp_path / "ricequant.yaml"
    config.write_text("stock_dividend_start_date: '2016-01-01'\nstock_dividend_batch_size: 7\n")
    settings = RiceQuantSettings.load(config, require_token=False)
    assert settings.stock_dividend_start_date == "2016-01-01"
    assert settings.stock_dividend_batch_size == 7
    runner = make_runner()
    selected = runner._resolve_datasets(["stock_dividend_info"])
    assert selected == ["trading_calendar", "instruments", "stock_dividend_info"]
    assert runner._calendar_start("incremental", selected, None) == date(2015, 1, 1)
    args = build_parser().parse_args(["backfill", "--dataset", "stock_dividend_info", "--instrument", "000001.XSHE"])
    assert args.instruments == ["000001.XSHE"]


def test_disclosure_quality_rule_uses_info_date_and_preserves_fund_default():
    manager = QualityManager()
    def disclosure_rule(table):
        return next(rule.issue_count_sql for rule in manager.build_rules("dwd", table, table)
                    if rule.rule_id == "dwd_partial_unknown_disclosure_labelled")
    dividend = disclosure_rule("dwd_ricequant_stock_dividend_info")
    assert "info_date IS NULL" in dividend
    assert "missing_info_date" in dividend
    assert "info_date_next_trade_day" in dividend
    assert "release_date" not in dividend
    fund = disclosure_rule("dwd_ricequant_fund_holding")
    assert "release_date IS NULL" in fund
    assert "missing_release_date" in fund
    assert "release_date_next_trade_day" in fund
    assert "info_date" not in fund
