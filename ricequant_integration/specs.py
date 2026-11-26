from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class TimeSemantics(StrEnum):
    TRADING_DATE = "trading_date"
    CALENDAR_DATE = "calendar_date"
    REPORT_PERIOD = "report_period"
    SOURCE_UPDATE_TIME = "source_update_time"
    SNAPSHOT = "snapshot"
    EFFECTIVE_DATE = "effective_date"


@dataclass(frozen=True)
class DatasetSpec:
    name: str
    table: str
    time_semantics: TimeSemantics
    primary_key: tuple[str, ...]
    partition_expression: str
    cadence: Literal["daily", "monthly", "snapshot", "on_demand"]
    mutable_days: int = 0
    dependencies: tuple[str, ...] = ()


DATASET_SPECS: dict[str, DatasetSpec] = {
    "trading_calendar": DatasetSpec(
        name="trading_calendar",
        table="ricequant_trading_calendar",
        time_semantics=TimeSemantics.CALENDAR_DATE,
        primary_key=("calendar_date",),
        partition_expression="toYear(calendar_date)",
        cadence="daily",
    ),
    "instruments": DatasetSpec(
        name="instruments",
        table="ricequant_instrument",
        time_semantics=TimeSemantics.SNAPSHOT,
        primary_key=("snapshot_date", "order_book_id"),
        partition_expression="toYYYYMMDD(snapshot_date)",
        cadence="snapshot",
        dependencies=("trading_calendar",),
    ),
    "option_instruments": DatasetSpec(
        name="option_instruments",
        table="ricequant_option_instrument",
        time_semantics=TimeSemantics.SNAPSHOT,
        primary_key=("observation_date", "snapshot_date", "order_book_id"),
        partition_expression="tuple(observation_date, snapshot_date)",
        cadence="snapshot",
        dependencies=("trading_calendar",),
    ),
    "option_contract_property": DatasetSpec(
        name="option_contract_property",
        table="ricequant_option_contract_property",
        time_semantics=TimeSemantics.TRADING_DATE,
        primary_key=("trading_date", "order_book_id"),
        partition_expression="trading_date",
        cadence="daily",
        mutable_days=7,
        dependencies=("trading_calendar", "option_instruments"),
    ),
    "option_daily": DatasetSpec(
        name="option_daily",
        table="ricequant_option_daily",
        time_semantics=TimeSemantics.TRADING_DATE,
        primary_key=("trading_date", "order_book_id"),
        partition_expression="trading_date",
        cadence="daily",
        mutable_days=7,
        dependencies=("trading_calendar", "option_instruments"),
    ),
    "index_daily": DatasetSpec(
        name="index_daily",
        table="ricequant_index_daily",
        time_semantics=TimeSemantics.TRADING_DATE,
        primary_key=("order_book_id", "trading_date"),
        partition_expression="tuple(order_book_id, toYYYYMM(trading_date))",
        cadence="daily",
        mutable_days=7,
        dependencies=("trading_calendar",),
    ),
    "index_components": DatasetSpec(
        name="index_components",
        table="ricequant_index_component",
        time_semantics=TimeSemantics.TRADING_DATE,
        primary_key=("index_id", "trading_date", "component_id"),
        partition_expression="tuple(index_id, toYYYYMM(trading_date))",
        cadence="daily",
        mutable_days=7,
        dependencies=("trading_calendar",),
    ),
    "index_weights": DatasetSpec(
        name="index_weights",
        table="ricequant_index_weight",
        time_semantics=TimeSemantics.SNAPSHOT,
        primary_key=("index_id", "snapshot_date", "component_id"),
        partition_expression="tuple(index_id, toYYYYMM(snapshot_date))",
        cadence="monthly",
        mutable_days=62,
        dependencies=("trading_calendar",),
    ),
    "index_weights_ex": DatasetSpec(
        name="index_weights_ex",
        table="ricequant_index_weight_ex",
        time_semantics=TimeSemantics.TRADING_DATE,
        primary_key=("index_id", "trading_date", "component_id"),
        partition_expression="tuple(index_id, toYYYYMM(trading_date))",
        cadence="daily",
        mutable_days=7,
        dependencies=("trading_calendar",),
    ),
    "stock_daily": DatasetSpec(
        name="stock_daily",
        table="ricequant_stock_daily",
        time_semantics=TimeSemantics.TRADING_DATE,
        primary_key=("trading_date", "order_book_id"),
        partition_expression="trading_date",
        cadence="daily",
        mutable_days=7,
        dependencies=("trading_calendar", "instruments"),
    ),
    "stock_minute": DatasetSpec(
        name="stock_minute",
        table="ricequant_stock_minute",
        time_semantics=TimeSemantics.TRADING_DATE,
        primary_key=("trading_date", "order_book_id", "datetime"),
        partition_expression="trading_date",
        cadence="daily",
        mutable_days=3,
        dependencies=("trading_calendar", "instruments"),
    ),
    "stock_ex_factor": DatasetSpec(
        name="stock_ex_factor",
        table="ricequant_stock_ex_factor",
        time_semantics=TimeSemantics.EFFECTIVE_DATE,
        primary_key=("order_book_id", "ex_date"),
        partition_expression="order_book_id",
        cadence="daily",
        mutable_days=550,
        dependencies=("instruments",),
    ),
    "stock_split": DatasetSpec(
        name="stock_split",
        table="ricequant_stock_split",
        time_semantics=TimeSemantics.EFFECTIVE_DATE,
        # RQData can return multiple genuine corporate-action rows for the
        # same instrument and ex-dividend date.  The book-closure date
        # distinguishes those source events (for example 000058.XSHE on
        # 2006-06-14), so collapsing at date granularity would lose data.
        primary_key=("order_book_id", "ex_dividend_date", "book_closure_date"),
        partition_expression="order_book_id",
        cadence="daily",
        mutable_days=550,
        dependencies=("instruments",),
    ),
    "stock_connect_holding_details": DatasetSpec(
        name="stock_connect_holding_details",
        table="ricequant_stock_connect_holding_detail",
        time_semantics=TimeSemantics.TRADING_DATE,
        primary_key=("trade_date", "order_book_id", "participant_number"),
        partition_expression="trade_date",
        cadence="daily",
        mutable_days=7,
        dependencies=("trading_calendar", "instruments"),
    ),
    "fund_holdings": DatasetSpec(
        name="fund_holdings",
        table="ricequant_fund_holding",
        time_semantics=TimeSemantics.REPORT_PERIOD,
        primary_key=(
            "fund_id",
            "report_date",
            "release_date_key",
            "held_order_book_id",
            "asset_type_key",
            "category_key",
            "region_key",
        ),
        partition_expression="toYYYYMM(report_date)",
        cadence="monthly",
        mutable_days=550,
        dependencies=("trading_calendar",),
    ),
    "financial_income": DatasetSpec(
        name="financial_income",
        table="ricequant_income_statement",
        time_semantics=TimeSemantics.REPORT_PERIOD,
        primary_key=("order_book_id", "report_period", "source_version_id"),
        partition_expression="order_book_id",
        cadence="on_demand",
        mutable_days=1100,
        dependencies=("instruments",),
    ),
    "financial_balance": DatasetSpec(
        name="financial_balance",
        table="ricequant_balance_sheet",
        time_semantics=TimeSemantics.REPORT_PERIOD,
        primary_key=("order_book_id", "report_period", "source_version_id"),
        partition_expression="order_book_id",
        cadence="on_demand",
        mutable_days=1100,
        dependencies=("instruments",),
    ),
    "financial_cashflow": DatasetSpec(
        name="financial_cashflow",
        table="ricequant_cashflow_statement",
        time_semantics=TimeSemantics.REPORT_PERIOD,
        primary_key=("order_book_id", "report_period", "source_version_id"),
        partition_expression="order_book_id",
        cadence="on_demand",
        mutable_days=1100,
        dependencies=("instruments",),
    ),
    "financial_metric": DatasetSpec(
        name="financial_metric",
        table="ricequant_financial_metric",
        time_semantics=TimeSemantics.REPORT_PERIOD,
        primary_key=("order_book_id", "report_period", "source_version_id"),
        partition_expression="order_book_id",
        cadence="on_demand",
        mutable_days=1100,
        dependencies=("instruments",),
    ),
    "concept_catalog": DatasetSpec(
        name="concept_catalog",
        table="ricequant_concept_catalog",
        time_semantics=TimeSemantics.EFFECTIVE_DATE,
        primary_key=("concept_name", "inclusion_date"),
        partition_expression="toYear(inclusion_date)",
        cadence="daily",
        mutable_days=30,
    ),
    "concept_members": DatasetSpec(
        name="concept_members",
        table="ricequant_concept_member",
        time_semantics=TimeSemantics.EFFECTIVE_DATE,
        primary_key=("concept_name", "order_book_id", "inclusion_date"),
        partition_expression="toYear(inclusion_date)",
        cadence="daily",
        mutable_days=30,
        dependencies=("concept_catalog",),
    ),
    "concept_snapshot": DatasetSpec(
        name="concept_snapshot",
        table="ricequant_concept_snapshot",
        time_semantics=TimeSemantics.SNAPSHOT,
        primary_key=(
            "observation_date",
            "snapshot_date",
            "concept_name",
            "order_book_id",
        ),
        partition_expression="tuple(observation_date, snapshot_date)",
        cadence="snapshot",
    ),
    "industry_mapping": DatasetSpec(
        name="industry_mapping",
        table="ricequant_industry_mapping",
        time_semantics=TimeSemantics.SNAPSHOT,
        primary_key=(
            "snapshot_date",
            "source_name",
            "first_industry_code",
            "second_industry_code",
            "third_industry_code",
        ),
        partition_expression="snapshot_date",
        cadence="snapshot",
    ),
    "industry_members": DatasetSpec(
        name="industry_members",
        table="ricequant_industry_member",
        time_semantics=TimeSemantics.EFFECTIVE_DATE,
        primary_key=(
            "source_name",
            "industry_level",
            "industry_code",
            "order_book_id",
            "start_date",
        ),
        partition_expression="toYear(start_date)",
        cadence="daily",
        mutable_days=30,
        dependencies=("industry_mapping",),
    ),
    "industry_snapshot": DatasetSpec(
        name="industry_snapshot",
        table="ricequant_industry_snapshot",
        time_semantics=TimeSemantics.SNAPSHOT,
        primary_key=(
            "observation_date",
            "snapshot_date",
            "source_name",
            "industry_level",
            "order_book_id",
        ),
        partition_expression="tuple(observation_date, snapshot_date)",
        cadence="snapshot",
        dependencies=("instruments",),
    ),
    "sector_snapshot": DatasetSpec(
        name="sector_snapshot",
        table="ricequant_sector_snapshot",
        time_semantics=TimeSemantics.SNAPSHOT,
        primary_key=("observation_date", "sector_code", "order_book_id"),
        partition_expression="observation_date",
        cadence="snapshot",
    ),
    "tick": DatasetSpec(
        name="tick",
        table="ricequant_stock_tick",
        time_semantics=TimeSemantics.TRADING_DATE,
        primary_key=("trading_date", "order_book_id", "datetime", "tick_sequence"),
        partition_expression="trading_date",
        cadence="daily",
        dependencies=("trading_calendar", "instruments"),
    ),
}


DEFAULT_INDEXES: tuple[str, ...] = (
    "000016.XSHG",  # SSE 50
    "000300.XSHG",  # CSI 300
    "000510.XSHG",  # CSI A500
    "000905.XSHG",  # CSI 500
    "000906.XSHG",  # CSI 800
    "000852.XSHG",  # CSI 1000
    "932000.INDX",  # CSI 2000
    "000688.XSHG",  # STAR 50
    "000922.XSHG",  # CSI Dividend
    "399006.XSHE",  # ChiNext
)


# rqdatac.index_weights_ex requires one index per call and rejects identifiers
# outside this official source-supported set. This is deliberately independent
# of the user-configured ``indexes`` selection used by the other index APIs.
INDEX_WEIGHTS_EX_INDEXES: tuple[str, ...] = (
    "000016.XSHG",  # SSE 50
    "000300.XSHG",  # CSI 300
    "000510.XSHG",  # CSI A500
    "000905.XSHG",  # CSI 500
    "000906.XSHG",  # CSI 800
    "000852.XSHG",  # CSI 1000
    "932000.INDX",  # CSI 2000
    "000688.XSHG",  # STAR 50
    "000922.XSHG",  # CSI Dividend
)
