from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd

from ricequant_integration.client import RqDataClient
from ricequant_integration.runner import RiceQuantRunner
from ricequant_integration.schema import TABLE_SCHEMAS
from ricequant_integration.settings import DatabaseSettings, RiceQuantSettings
from ricequant_integration.specs import DATASET_SPECS
from ricequant_integration.transform import (
    option_contract_property_frame,
    option_daily_frame,
    option_instruments_frame,
)


def test_option_specs_use_independent_plain_mergetree_tables_and_keys():
    expected = {
        "option_instruments": (
            "ricequant_option_instrument",
            ("observation_date", "snapshot_date", "order_book_id"),
        ),
        "option_contract_property": (
            "ricequant_option_contract_property",
            ("trading_date", "order_book_id"),
        ),
        "option_daily": (
            "ricequant_option_daily",
            ("trading_date", "order_book_id"),
        ),
    }
    for dataset, (table, key) in expected.items():
        spec = DATASET_SPECS[dataset]
        assert spec.table == table
        assert spec.primary_key == key
        ddl = TABLE_SCHEMAS[table].create_sql("default")
        assert "ENGINE = MergeTree" in ddl
        assert "ReplacingMergeTree" not in ddl


def test_option_history_defaults_start_in_2019():
    settings = RiceQuantSettings(
        database=DatabaseSettings(host="localhost"), token=""
    )
    runner = object.__new__(RiceQuantRunner)
    runner.settings = settings
    for dataset in (
        "option_instruments",
        "option_contract_property",
        "option_daily",
    ):
        assert runner._dataset_history_start(dataset) == date(2019, 1, 1)


def test_option_instrument_transform_preserves_source_and_observation_times():
    raw = pd.DataFrame(
        {
            "order_book_id": ["10000001"],
            "symbol": ["50ETF购1月2500"],
            "listed_date": ["2018-12-20"],
            "de_listed_date": ["2019-01-23"],
            "maturity_date": ["2019-01-23"],
            "underlying_symbol": ["510050.XSHG"],
            "underlying_order_book_id": ["510050.XSHG"],
            "option_type": ["C"],
            "strike_price": [2.5],
            "contract_multiplier": [10000],
        }
    )
    observed_at = datetime(2026, 11, 17, 18, 30)
    frame = option_instruments_frame(
        raw,
        date(2019, 1, 2),
        date(2026, 11, 17),
        observed_at,
        "batch-a",
    )
    assert frame.loc[0, "snapshot_date"] == date(2019, 1, 2)
    assert frame.loc[0, "observation_date"] == date(2026, 11, 17)
    assert frame.loc[0, "observed_at"] == observed_at
    assert frame.loc[0, "type"] == "Option"
    assert frame.loc[0, "maturity_date"] == date(2019, 1, 23)
    assert frame.loc[0, "contract_multiplier"] == 10000


def test_option_property_and_daily_transforms_keep_one_row_per_contract_day():
    index = pd.MultiIndex.from_tuples(
        [("10000001", pd.Timestamp("2019-01-02"))],
        names=["order_book_id", "trading_date"],
    )
    property_frame = option_contract_property_frame(
        pd.DataFrame(
            {
                "product_name": ["510050C1901M02500"],
                "symbol": ["50ETF购1月2500"],
                "contract_multiplier": [10000],
                "strike_price": [2.5],
            },
            index=index,
        ),
        "batch-a",
    )
    daily_frame = option_daily_frame(
        pd.DataFrame(
            {
                "open": [0.1],
                "high": [0.12],
                "low": [0.08],
                "close": [0.11],
                "volume": [100],
                "open_interest": [1000],
                "settlement": [0.105],
            },
            index=index,
        ),
        "batch-b",
    )
    assert property_frame.loc[0, "trading_date"] == date(2019, 1, 2)
    assert property_frame.loc[0, "_api_name"] == "options.get_contract_property"
    assert daily_frame.loc[0, "trading_date"] == date(2019, 1, 2)
    assert daily_frame.loc[0, "open_interest"] == 1000
    assert daily_frame.loc[0, "_api_name"] == "get_price"


def test_option_client_calls_official_contract_property_and_unadjusted_daily_apis():
    calls = []

    class Options:
        @staticmethod
        def get_contract_property(order_book_ids, **kwargs):
            calls.append(("property", order_book_ids, kwargs))
            return pd.DataFrame()

    class Module:
        options = Options()

        @staticmethod
        def all_instruments(**kwargs):
            calls.append(("instruments", None, kwargs))
            return pd.DataFrame()

        @staticmethod
        def get_price(order_book_ids, **kwargs):
            calls.append(("daily", order_book_ids, kwargs))
            return pd.DataFrame()

    client = RqDataClient("token", module=Module())
    client.option_instruments(date(2019, 1, 2))
    client.option_contract_property(
        ["10000001"], date(2019, 1, 2), date(2019, 1, 31)
    )
    client.option_daily(["10000001"], date(2019, 1, 2), date(2019, 1, 31))

    assert calls[0] == (
        "instruments",
        None,
        {"type": "Option", "date": date(2019, 1, 2), "market": "cn"},
    )
    assert calls[1][2]["fields"] == [
        "product_name",
        "symbol",
        "contract_multiplier",
        "strike_price",
    ]
    assert calls[2][2]["frequency"] == "1d"
    assert calls[2][2]["adjust_type"] == "none"
    assert "open_interest" in calls[2][2]["fields"]


def test_option_property_universe_only_selects_exchange_etf_underlyings():
    class Client:
        @staticmethod
        def query_df(_sql):
            return pd.DataFrame(
                {
                    "order_book_id": ["ETF", "INDEX", "COMMODITY"],
                    "underlying_symbol": [
                        "510050.XSHG",
                        "IF",
                        "CU",
                    ],
                }
            )

    runner = object.__new__(RiceQuantRunner)
    runner.storage = SimpleNamespace(client=Client(), db="`default`")
    assert runner._option_month_universe(
        date(2019, 1, 1), date(2019, 1, 31), etf_only=True
    ) == ["ETF"]
    assert runner._option_month_universe(
        date(2019, 1, 1), date(2019, 1, 31), etf_only=False
    ) == ["COMMODITY", "ETF", "INDEX"]
