from __future__ import annotations

import os
import warnings
import logging
from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from ricequant_integration.client import RqDataClient
from ricequant_integration.commands import build_parser, quota_payload
from ricequant_integration.financial_fields import (
    BALANCE_SHEET_FIELDS,
    CASHFLOW_STATEMENT_FIELDS,
    FINANCIAL_FIELDS_BY_DATASET,
    FINANCIAL_METRIC_FIELDS,
    INCOME_STATEMENT_FIELDS,
)
from ricequant_integration.planner import (
    DateSlice,
    incremental_start,
    month_slices,
    quarter_end_on_or_after,
    quarter_end_on_or_before,
    quarter_label,
    report_periods_to_rescan,
)
from ricequant_integration.progress import ProgressReporter
from ricequant_integration.quota import QuotaGuard, QuotaPaused, QuotaSnapshot
from ricequant_integration.runner import RiceQuantRunner
from ricequant_integration.schema import TABLE_SCHEMAS
from ricequant_integration.settings import DatabaseSettings, RiceQuantSettings
from ricequant_integration.specs import (
    DATASET_SPECS,
    INDEX_WEIGHTS_EX_INDEXES,
    TimeSemantics,
)
from ricequant_integration.state import (
    CoverageState,
    StateStore,
    content_changed,
    should_refresh,
)
from ricequant_integration.storage import dataframe_hash
from ricequant_integration.transform import (
    concept_catalog_frame,
    concept_member_frame,
    concept_snapshot_frame,
    ex_factor_frame,
    financial_version_key,
    financial_statement_frame,
    industry_mapping_frame,
    index_weights_ex_frame,
    instruments_frame,
    split_frame,
    sector_snapshot_frame,
    stock_daily_frame,
    stock_minute_frame,
    tick_frame,
)


def test_all_final_tables_are_plain_mergetree_and_have_explicit_keys():
    for spec in DATASET_SPECS.values():
        ddl = TABLE_SCHEMAS[spec.table].create_sql("default")
        assert "ENGINE = MergeTree" in ddl
        assert "ReplacingMergeTree" not in ddl
        assert spec.primary_key


def test_quota_guard_stops_at_larger_of_floor_and_estimate():
    guard = QuotaGuard(min_reserve_bytes=256, estimate_multiplier=1.5)
    guard.check(QuotaSnapshot(1000, 500), estimated_next_slice_bytes=100)
    with pytest.raises(QuotaPaused):
        guard.check(QuotaSnapshot(1000, 744), estimated_next_slice_bytes=100)
    with pytest.raises(QuotaPaused):
        guard.check(QuotaSnapshot(1000, 699), estimated_next_slice_bytes=201)
    guard.check(QuotaSnapshot(0, 999999), estimated_next_slice_bytes=10**12)


def test_quota_command_reports_exact_and_operator_friendly_values():
    args = build_parser().parse_args(["quota"])
    assert args.command == "quota"

    payload = quota_payload(QuotaSnapshot(5 * 1024**3, 1024**3), 256 * 1024**2)
    assert payload == {
        "quota_scope": "daily",
        "unlimited": False,
        "bytes_limit": 5 * 1024**3,
        "bytes_used": 1024**3,
        "bytes_remaining": 4 * 1024**3,
        "used_percent": 20.0,
        "limit_gib": 5.0,
        "used_gib": 1.0,
        "remaining_gib": 4.0,
        "framework_min_reserve_bytes": 256 * 1024**2,
        "bytes_available_before_min_reserve": 4 * 1024**3 - 256 * 1024**2,
    }


def test_ingestion_cli_accepts_explicit_factor_instruments():
    args = build_parser().parse_args(
        [
            "bootstrap",
            "--dataset",
            "stock_ex_factor",
            "--instrument",
            "000001.XSHE",
            "--instrument",
            "600000.XSHG",
        ]
    )
    assert args.instruments == ["000001.XSHE", "600000.XSHG"]


def test_unlimited_quota_does_not_report_fake_remaining_capacity():
    payload = quota_payload(QuotaSnapshot(0, 123), 256)
    assert payload["unlimited"] is True
    assert payload["bytes_remaining"] is None
    assert payload["bytes_available_before_min_reserve"] is None


def test_framework_progress_is_automatic_for_every_dataset_fetch(caplog):
    now = [100.0]
    reporter = ProgressReporter(
        logging.getLogger("test.ricequant.progress"),
        "run-id",
        heartbeat_seconds=60,
        heartbeat_calls=2,
        clock=lambda: now[0],
    )
    with caplog.at_level(logging.INFO, logger="test.ricequant.progress"):
        reporter.fetch_started("future_dataset", "slice-1")
        reporter.fetch_completed("future_dataset", "slice-1", rows=10, quota_bytes=100)
        now[0] += 1
        reporter.fetch_started("future_dataset", "slice-2")
        reporter.fetch_completed("future_dataset", "slice-2", rows=20, quota_bytes=200)
        reporter.finish("complete")

    messages = [record.getMessage() for record in caplog.records]
    assert any("dataset_fetch_started" in message for message in messages)
    assert any("dataset_heartbeat" in message for message in messages)
    summary = next(
        message for message in messages if "dataset_fetch_summary" in message
    )
    assert "api_calls=2" in summary
    assert "response_rows=30" in summary
    assert "quota_bytes=300" in summary


def test_month_slices_are_bounded_for_on_demand_backfill():
    slices = list(month_slices(date(2025, 1, 20), date(2025, 3, 5), prefix="x:"))
    assert [(item.start, item.end, item.slice_key) for item in slices] == [
        (date(2025, 1, 20), date(2025, 1, 31), "x:2025-01"),
        (date(2025, 2, 1), date(2025, 2, 28), "x:2025-02"),
        (date(2025, 3, 1), date(2025, 3, 5), "x:2025-03"),
    ]


def test_partial_month_coverage_does_not_skip_full_bootstrap_slice():
    planned = DateSlice(date(2026, 10, 1), date(2026, 10, 31), "index:2026-10")
    assert not RiceQuantRunner._completed_slice_covers(
        {"index:2026-10": (date(2026, 10, 27), date(2026, 10, 28))}, planned
    )
    assert RiceQuantRunner._completed_slice_covers(
        {"index:2026-10": (date(2026, 10, 1), date(2026, 10, 31))}, planned
    )


def test_incremental_start_uses_manifest_end_and_bounded_rescan():
    assert incremental_start(date(2025, 5, 10), date(2025, 1, 1)) == date(2025, 5, 11)
    assert incremental_start(
        date(2025, 5, 10), date(2025, 1, 1), rescan_days=7
    ) == date(2025, 5, 4)


def test_tick_key_preserves_multiple_ticks_at_same_timestamp_and_is_replay_stable():
    raw = pd.DataFrame(
        {"last": [10.0, 10.1, 10.2], "volume": [1, 2, 3]},
        index=pd.DatetimeIndex(
            [
                "2025-01-02 09:30:00.000001",
                "2025-01-02 09:30:00.000001",
                "2025-01-02 09:30:00.000002",
            ],
            name="datetime",
        ),
    )
    first = tick_frame(raw, "000001.XSHE", date(2025, 1, 2), "batch-a")
    second = tick_frame(raw, "000001.XSHE", date(2025, 1, 2), "batch-b")
    assert first["tick_sequence"].tolist() == [0, 1, 0]
    key = ["trading_date", "order_book_id", "datetime", "tick_sequence"]
    assert not first.duplicated(key).any()
    assert first[key].equals(second[key])
    assert dataframe_hash(first, key) == dataframe_hash(second, key)


def test_index_weights_ex_preserves_daily_source_weight_and_key():
    raw = pd.DataFrame(
        {"weight": [0.00484, 0.00098, 0.00490]},
        index=pd.MultiIndex.from_tuples(
            [
                (date(2026, 10, 27), "000001.XSHE"),
                (date(2026, 10, 27), "000002.XSHE"),
                (date(2026, 10, 28), "000001.XSHE"),
            ],
            names=["date", "order_book_id"],
        ),
    )
    frame = index_weights_ex_frame(raw, "000300.XSHG", "batch-a")
    assert frame[["trading_date", "component_id", "weight"]].to_dict("records") == [
        {
            "trading_date": date(2026, 10, 27),
            "component_id": "000001.XSHE",
            "weight": 0.00484,
        },
        {
            "trading_date": date(2026, 10, 27),
            "component_id": "000002.XSHE",
            "weight": 0.00098,
        },
        {
            "trading_date": date(2026, 10, 28),
            "component_id": "000001.XSHE",
            "weight": 0.00490,
        },
    ]
    assert frame["_api_name"].unique().tolist() == ["index_weights_ex"]


def test_index_weights_ex_uses_source_supported_indexes_and_2015_start():
    settings = RiceQuantSettings(
        database=DatabaseSettings(host="localhost"),
        token="",
        indexes=("399006.XSHE",),
        history_start_date="1990-01-01",
    )
    runner = object.__new__(RiceQuantRunner)
    runner.settings = settings
    assert runner._dataset_index_ids("index_weights_ex") == INDEX_WEIGHTS_EX_INDEXES
    assert "399006.XSHE" not in INDEX_WEIGHTS_EX_INDEXES
    assert runner._dataset_history_start("index_weights_ex") == date(2015, 1, 1)
    assert runner._dataset_history_start("index_daily") == date(1990, 1, 1)
    assert runner._dataset_history_start("stock_daily") == date(2015, 1, 1)
    assert runner._dataset_history_start("stock_minute") == date(2020, 1, 1)
    assert runner._resolve_datasets(["index_weights_ex"]) == [
        "trading_calendar",
        "index_weights_ex",
    ]
    assert runner._resolve_datasets(["stock_minute"]) == [
        "trading_calendar",
        "instruments",
        "stock_minute",
    ]
    assert runner._dataset_history_start("financial_income") == date(2015, 1, 1)
    assert runner._resolve_datasets(["financial_income"]) == [
        "instruments",
        "financial_income",
    ]


def test_stock_daily_and_minute_preserve_unadjusted_source_values_and_keys():
    daily_raw = pd.DataFrame(
        {
            "open": [10.0, 20.0],
            "close": [10.5, 19.5],
            "volume": [100.0, 200.0],
            "total_turnover": [1050.0, 3900.0],
        },
        index=pd.MultiIndex.from_tuples(
            [
                ("000001.XSHE", date(2025, 1, 2)),
                ("600000.XSHG", date(2025, 1, 2)),
            ],
            names=["order_book_id", "date"],
        ),
    )
    daily = stock_daily_frame(daily_raw, date(2025, 1, 2), "batch-a")
    assert daily[["trading_date", "order_book_id", "close"]].to_dict(
        "records"
    ) == [
        {
            "trading_date": date(2025, 1, 2),
            "order_book_id": "000001.XSHE",
            "close": 10.5,
        },
        {
            "trading_date": date(2025, 1, 2),
            "order_book_id": "600000.XSHG",
            "close": 19.5,
        },
    ]

    minute_raw = pd.DataFrame(
        {"open": [10.0, 10.1], "close": [10.1, 10.2], "volume": [10, 20]},
        index=pd.MultiIndex.from_tuples(
            [
                ("000001.XSHE", pd.Timestamp("2025-01-02 09:31:00")),
                ("000001.XSHE", pd.Timestamp("2025-01-02 09:32:00")),
            ],
            names=["order_book_id", "datetime"],
        ),
    )
    minute = stock_minute_frame(minute_raw, date(2025, 1, 2), "batch-b")
    assert minute["trading_date"].unique().tolist() == [date(2025, 1, 2)]
    assert minute["datetime"].tolist() == [
        pd.Timestamp("2025-01-02 09:31:00", tz="Asia/Shanghai"),
        pd.Timestamp("2025-01-02 09:32:00", tz="Asia/Shanghai"),
    ]
    assert not minute.duplicated(
        ["trading_date", "order_book_id", "datetime"]
    ).any()


def test_adjustment_factor_and_split_are_kept_as_independent_source_data():
    factor_raw = pd.DataFrame(
        {
            "order_book_id": ["000001.XSHE"],
            "announcement_date": [pd.Timestamp("2025-06-11")],
            "ex_end_date": [pd.NaT],
            "ex_factor": [1.02],
            "ex_cum_factor": [150.0],
            "rice_create_tm": [pd.Timestamp("2025-06-10 18:00:00")],
        },
        index=pd.DatetimeIndex(["2025-06-12"], name="ex_date"),
    )
    factor = ex_factor_frame(factor_raw, "batch-a")
    assert factor.loc[0, "ex_date"] == date(2025, 6, 12)
    assert factor.loc[0, "ex_cum_factor"] == 150.0
    assert factor.loc[0, "_api_name"] == "get_ex_factor"

    split_raw = pd.DataFrame(
        {
            "order_book_id": ["000001.XSHE"],
            "book_closure_date": [pd.Timestamp("2025-06-11")],
            "split_coefficient_from": [10],
            "split_coefficient_to": [12],
            "cum_factor": [1.2],
        },
        index=pd.DatetimeIndex(["2025-06-12"], name="ex_dividend_date"),
    )
    split = split_frame(split_raw, "batch-b")
    assert split.loc[0, "ex_dividend_date"] == date(2025, 6, 12)
    assert split.loc[0, "cum_factor"] == 1.2
    assert split.loc[0, "_api_name"] == "get_split"


def test_split_key_preserves_multiple_source_events_on_the_same_ex_date():
    raw = pd.DataFrame(
        {
            "order_book_id": ["000058.XSHE", "000058.XSHE"],
            "book_closure_date": [
                pd.Timestamp("2006-06-12"),
                pd.Timestamp("2006-06-13"),
            ],
            "payable_date": [
                pd.Timestamp("2006-06-14"),
                pd.Timestamp("2006-06-14"),
            ],
            "split_coefficient_from": [10.0, 10.0],
            "split_coefficient_to": [14.6445, 10.8077],
            "cum_factor": [2.8191066259, 3.0468058681],
            "rice_create_tm": [
                pd.Timestamp("2019-07-16 11:20:11"),
                pd.Timestamp("2023-06-12 08:46:04"),
            ],
        },
        index=pd.DatetimeIndex(
            ["2006-06-14", "2006-06-14"], name="ex_dividend_date"
        ),
    )

    split = split_frame(raw, "batch-duplicate-date")

    assert split.duplicated(
        ["order_book_id", "ex_dividend_date"], keep=False
    ).all()
    assert not split.duplicated(list(DATASET_SPECS["stock_split"].primary_key)).any()


def test_concept_and_industry_transforms_keep_source_lineage_separate():
    catalog = concept_catalog_frame(
        pd.Series(
            ["低空经济", "机器人"],
            index=pd.DatetimeIndex(["2024-01-02", "2024-01-03"], name="date"),
        ),
        "batch-a",
    )
    assert catalog["concept_name"].tolist() == ["低空经济", "机器人"]

    members_raw = pd.DataFrame(
        {"order_book_id": ["000001.XSHE"], "inclusion_date": ["2024-01-02"]},
        index=pd.Index(["低空经济"], name="concept"),
    )
    members = concept_member_frame(members_raw, "batch-b")
    assert members[["concept_name", "order_book_id"]].iloc[0].tolist() == [
        "低空经济",
        "000001.XSHE",
    ]

    mapping = industry_mapping_frame(
        pd.DataFrame(
            {
                "first_industry_code": ["40"],
                "first_industry_name": ["银行"],
                "second_industry_code": ["4020"],
                "second_industry_name": ["股份制银行"],
                "third_industry_code": ["402010"],
                "third_industry_name": ["股份制银行III"],
            }
        ),
        date(2025, 1, 2),
        "citics_2019",
        "batch-c",
    )
    assert mapping.loc[0, "source_name"] == "citics_2019"
    assert mapping.loc[0, "_api_name"] == "get_industry_mapping"


def test_snapshots_separate_source_as_of_date_from_observation_time_for_pit():
    observed_at = datetime(2026, 11, 5, 18, 0)
    concept = concept_snapshot_frame(
        ["000001.XSHE"],
        "深港通",
        date(2026, 11, 3),
        date(2026, 11, 5),
        observed_at,
        "batch-a",
    )
    assert concept.loc[0, "snapshot_date"] == date(2026, 11, 3)
    assert concept.loc[0, "observation_date"] == date(2026, 11, 5)
    assert concept.loc[0, "observed_at"] == observed_at

    sector = sector_snapshot_frame(
        ["000001.XSHE"],
        "Financials",
        "金融",
        date(2026, 11, 5),
        observed_at,
        "batch-b",
    )
    assert "snapshot_date" not in sector.columns
    assert sector.loc[0, "observation_date"] == date(2026, 11, 5)
    assert DATASET_SPECS["sector_snapshot"].primary_key[0] == "observation_date"


def test_tick_rejects_a_source_trading_date_mismatch():
    raw = pd.DataFrame(
        {"trading_date": [date(2025, 1, 3)], "last": [10.0]},
        index=pd.DatetimeIndex(["2025-01-03 09:30:00"], name="datetime"),
    )
    with pytest.raises(ValueError, match="do not match requested"):
        tick_frame(raw, "000001.XSHE", date(2025, 1, 2), "batch-a")


def test_instrument_dates_parse_iso_values_without_inference_warning():
    raw = pd.DataFrame(
        {
            "order_book_id": ["000001.XSHE", "000002.XSHE"],
            "listed_date": ["1991-04-03", date(1992, 1, 31)],
            "de_listed_date": [None, "2025-06-30"],
        }
    )
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = instruments_frame(raw, date(2025, 1, 2), "batch-a")
    assert result["listed_date"].tolist() == [date(1991, 4, 3), date(1992, 1, 31)]
    assert result["de_listed_date"].tolist()[1] == date(2025, 6, 30)


def test_financial_time_semantics_do_not_require_a_trading_date():
    for dataset in FINANCIAL_FIELDS_BY_DATASET:
        spec = DATASET_SPECS[dataset]
        assert spec.time_semantics is TimeSemantics.REPORT_PERIOD
        assert "trading_date" not in spec.primary_key
        assert spec.primary_key == (
            "order_book_id",
            "report_period",
            "source_version_id",
        )
    revision_a = financial_version_key(
        "000001.XSHE",
        "2025q1",
        date(2025, 4, 20),
        0,
        datetime(2025, 4, 19, 20),
    )
    revision_b = financial_version_key(
        "000001.XSHE",
        "2025q1",
        date(2025, 4, 22),
        0,
        datetime(2025, 4, 21, 20),
    )
    assert revision_a != revision_b


def test_financial_field_groups_match_rqdatac_381_and_do_not_overlap():
    assert [
        len(INCOME_STATEMENT_FIELDS),
        len(BALANCE_SHEET_FIELDS),
        len(CASHFLOW_STATEMENT_FIELDS),
        len(FINANCIAL_METRIC_FIELDS),
    ] == [94, 194, 74, 32]
    groups = [set(value) for value in FINANCIAL_FIELDS_BY_DATASET.values()]
    assert len(set().union(*groups)) == 394
    for position, left in enumerate(groups):
        for right in groups[position + 1 :]:
            assert left.isdisjoint(right)


def test_financial_transform_preserves_all_source_and_observation_times():
    raw = pd.DataFrame(
        {
            "info_date": [pd.Timestamp("2025-03-15")],
            "if_adjusted": [0],
            "rice_create_tm": [pd.Timestamp("2025-03-14 20:11:51")],
            "revenue": [1.25e9],
        },
        index=pd.MultiIndex.from_tuples(
            [("000001.XSHE", "2024q4")],
            names=["order_book_id", "quarter"],
        ),
    )
    observed_at = datetime(2026, 11, 10, 10, 0)
    frame = financial_statement_frame(
        raw,
        ("revenue",),
        date(2026, 11, 10),
        observed_at,
        "batch-a",
    )
    assert frame.loc[0, "report_period"] == date(2024, 12, 31)
    assert frame.loc[0, "info_date"] == date(2025, 3, 15)
    assert str(frame.loc[0, "rice_create_tm"].tz) == "Asia/Shanghai"
    assert frame.loc[0, "query_date"] == date(2026, 11, 10)
    assert frame.loc[0, "observed_at"] == observed_at
    assert frame.loc[0, "statements"] == "all"
    assert len(frame.loc[0, "source_version_id"]) == 32


def test_financial_quarter_bounds_do_not_use_a_trading_calendar():
    assert quarter_end_on_or_before(date(2025, 1, 1)) == date(2024, 12, 31)
    assert quarter_end_on_or_before(date(2025, 6, 30)) == date(2025, 6, 30)
    assert quarter_end_on_or_after(date(2025, 4, 1)) == date(2025, 6, 30)
    assert quarter_label(date(2025, 9, 30)) == "2025q3"


def test_financial_runner_publishes_one_authoritative_report_period_range():
    calls = []

    class Client:
        def pit_financials(
            self, order_book_ids, fields, start_quarter, end_quarter, query_date
        ):
            calls.append(
                (
                    order_book_ids,
                    fields,
                    start_quarter,
                    end_quarter,
                    query_date,
                )
            )
            values = {field: [1.0] for field in fields}
            values.update(
                {
                    "info_date": [pd.Timestamp("2025-03-15")],
                    "if_adjusted": [0],
                    "rice_create_tm": [pd.Timestamp("2025-03-14 20:11:51")],
                }
            )
            return pd.DataFrame(
                values,
                index=pd.MultiIndex.from_tuples(
                    [("000001.XSHE", "2024q4")],
                    names=["order_book_id", "quarter"],
                ),
            )

    class Storage:
        published = []

        def publish_partition(self, spec, partition, frame, **kwargs):
            self.published.append((spec.name, partition, frame.copy(), kwargs))
            return SimpleNamespace(row_count=len(frame), content_hash="hash")

    class State:
        events = []

        @staticmethod
        def completed_slice_ranges(dataset):
            return {}

        def coverage_event(self, spec, slice_key, status, **kwargs):
            self.events.append((spec.name, slice_key, status, kwargs))

    runner = object.__new__(RiceQuantRunner)
    runner.settings = RiceQuantSettings(
        database=DatabaseSettings(host="localhost"),
        token="",
        financial_start_date="2015-01-01",
        financial_batch_size=20,
        financial_rescan_days=1100,
    )
    runner.today = date(2026, 11, 9)
    runner.run_id = "run-id"
    runner.client = Client()
    runner.storage = Storage()
    runner.state = State()
    runner.requested_order_book_ids = ("000001.XSHE",)
    runner._known_order_book_ids = lambda _: ["000001.XSHE"]
    runner._fetch = lambda dataset, slice_key, operation: (operation(), 100)

    runner._sync_financials(
        "financial_metric",
        "backfill",
        date(2024, 10, 1),
        date(2024, 12, 31),
    )

    assert calls[0][2:] == ("2024q4", "2024q4", date(2026, 11, 9))
    assert len(calls[0][1]) == 32
    _, partition, frame, publish_kwargs = runner.storage.published[0]
    assert partition == "'000001.XSHE'"
    assert publish_kwargs["replace_range"] == (
        "report_period",
        date(2024, 12, 31),
        date(2024, 12, 31),
    )
    assert frame["statements"].unique().tolist() == ["all"]
    assert runner.state.events[0][2] == "complete"


def test_recent_report_period_planner_is_independent_of_exchange_calendar():
    periods = report_periods_to_rescan(date(2025, 8, 1), mutable_days=550)
    assert date(2025, 6, 30) in periods
    assert date(2025, 3, 31) in periods
    assert all(value.day in {30, 31} for value in periods)


def test_mutable_financial_slice_rechecks_empty_or_unchanged_responses():
    state = CoverageState(
        dataset="financial_example",
        slice_key="2025-03-31",
        status="complete",
        cursor={},
        row_count=0,
        content_hash="same",
        event_time=datetime(2025, 4, 1),
        mutable_until=date(2026, 9, 30),
    )
    assert should_refresh(state, date(2025, 8, 1))
    assert not content_changed(state, "same")
    assert content_changed(state, "revised")
    assert not should_refresh(state, date(2026, 10, 1))


def test_latest_coverage_query_avoids_clickhouse_aggregate_alias_collision():
    class Client:
        sql = ""

        def query_df(self, sql):
            self.sql = sql
            return pd.DataFrame(
                [
                    {
                        "dataset": "tick",
                        "slice_key": "2025-01-02",
                        "latest_status": "partial",
                        "latest_cursor_json": '{"last_order_book_id":"000001.XSHE"}',
                        "latest_row_count": 1,
                        "latest_content_hash": "hash",
                        "latest_mutable_until": None,
                        "latest_event_time": datetime(2025, 1, 2, 18),
                    }
                ]
            )

    class Storage:
        db = "`default`"
        client = Client()

    state = StateStore(Storage(), "run-id").latest("tick", "2025-01-02")
    assert state is not None
    assert state.status == "partial"
    assert state.cursor == {"last_order_book_id": "000001.XSHE"}
    assert "max(event_time) AS latest_event_time" in Storage.client.sql
    assert "max(event_time) AS event_time" not in Storage.client.sql


def test_active_universe_honours_listing_lifecycle():
    frame = pd.DataFrame(
        [
            {
                "order_book_id": "A",
                "listed_date": date(2020, 1, 1),
                "de_listed_date": None,
            },
            {
                "order_book_id": "B",
                "listed_date": date(2025, 2, 1),
                "de_listed_date": None,
            },
            {
                "order_book_id": "C",
                "listed_date": date(2020, 1, 1),
                "de_listed_date": date(2025, 1, 1),
            },
        ]
    )
    assert RiceQuantRunner._active_order_book_ids(frame, date(2025, 1, 2)) == ["A"]


def test_active_universe_accepts_clickhouse_datetime64_dates():
    frame = pd.DataFrame(
        {
            "order_book_id": ["A", "B", "C", "D"],
            "listed_date": pd.to_datetime(
                ["2020-01-01", "2025-01-03", "2020-01-01", None]
            ),
            "de_listed_date": pd.to_datetime(
                [None, None, "2025-01-01", "2025-01-02"]
            ),
        }
    )

    assert RiceQuantRunner._active_order_book_ids(
        frame, date(2025, 1, 2)
    ) == ["A", "D"]


def test_current_trading_day_is_not_planned_before_ready_time():
    assert RiceQuantRunner._completed_data_date(
        datetime(2025, 1, 2, 17, 59), "18:00"
    ) == date(2025, 1, 1)
    assert RiceQuantRunner._completed_data_date(
        datetime(2025, 1, 2, 18, 0), "18:00"
    ) == date(2025, 1, 2)


def test_quota_adapter_reads_official_bytes_fields():
    class User:
        @staticmethod
        def get_quota():
            return {"bytes_limit": 5000, "bytes_used": 1234}

    class Module:
        user = User()

    client = RqDataClient("rqdata://token", module=Module())
    assert client.quota() == QuotaSnapshot(5000, 1234)


def test_rqdata_client_wraps_opaque_license_and_initializes_from_environment(
    monkeypatch,
):
    calls = []

    class Module:
        @staticmethod
        def init(**kwargs):
            calls.append(kwargs)

    monkeypatch.delenv("RQDATAC_CONF", raising=False)
    client = RqDataClient("issued-license", module=Module())
    client.initialize()
    assert calls == [{"use_zstd": True}]
    assert (
        os.environ["RQDATAC_CONF"]
        == "rqdata://license:issued-license@rqdatad-pro.ricequant.com:16011"
    )


@pytest.mark.parametrize(
    "uri",
    [
        "rqdata://license:issued-license@rqdatad-pro.ricequant.com:16011",
        "tcp://license:issued-license@rqdatad-pro.ricequant.com:16011",
    ],
)
def test_rqdata_client_preserves_preconfigured_connection_uri(monkeypatch, uri):
    class Module:
        @staticmethod
        def init(**kwargs):
            assert kwargs == {"use_zstd": True}

    monkeypatch.delenv("RQDATAC_CONF", raising=False)
    RqDataClient(uri, module=Module()).initialize()
    assert os.environ["RQDATAC_CONF"] == uri


def test_rqdata_client_calls_index_weights_ex_with_cn_date_range():
    calls = []

    class Module:
        @staticmethod
        def index_weights_ex(index_id, **kwargs):
            calls.append((index_id, kwargs))
            return pd.DataFrame()

    client = RqDataClient("token", module=Module())
    client.index_weights_ex("000300.XSHG", date(2026, 10, 1), date(2026, 10, 31))
    assert calls == [
        (
            "000300.XSHG",
            {
                "start_date": date(2026, 10, 1),
                "end_date": date(2026, 10, 31),
                "market": "cn",
            },
        )
    ]


def test_stock_bar_client_requests_unadjusted_non_synthetic_bars():
    calls = []

    class Module:
        @staticmethod
        def get_price(order_book_ids, **kwargs):
            calls.append((order_book_ids, kwargs))
            return pd.DataFrame()

    client = RqDataClient("token", module=Module())
    identifiers = ["000001.XSHE", "600000.XSHG"]
    client.stock_daily(identifiers, date(2025, 1, 2))
    client.stock_minute(identifiers, date(2025, 1, 2))

    assert [value[1]["frequency"] for value in calls] == ["1d", "1m"]
    for returned_ids, kwargs in calls:
        assert returned_ids == identifiers
        assert kwargs["adjust_type"] == "none"
        assert kwargs["skip_suspended"] is True
        assert kwargs["start_date"] == date(2025, 1, 2)
        assert kwargs["end_date"] == date(2025, 1, 2)


def test_financial_client_requests_all_disclosure_versions_and_exact_fields():
    calls = []

    class Module:
        @staticmethod
        def get_pit_financials_ex(**kwargs):
            calls.append(kwargs)
            return pd.DataFrame()

    client = RqDataClient("token", module=Module())
    client.pit_financials(
        ["000001.XSHE"],
        ("revenue", "net_profit"),
        "2024q1",
        "2024q4",
        date(2026, 11, 10),
    )
    assert calls == [
        {
            "order_book_ids": ["000001.XSHE"],
            "fields": ["revenue", "net_profit"],
            "start_quarter": "2024q1",
            "end_quarter": "2024q4",
            "date": date(2026, 11, 10),
            "statements": "all",
            "market": "cn",
        }
    ]
