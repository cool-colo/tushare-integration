from __future__ import annotations

from dataclasses import dataclass

from ricequant_integration.financial_fields import FINANCIAL_FIELDS_BY_DATASET


@dataclass(frozen=True)
class TableSchema:
    name: str
    columns_sql: str
    partition_by: str
    order_by: tuple[str, ...]

    def create_sql(self, database: str) -> str:
        order = ", ".join(self.order_by)
        return f"""
        CREATE TABLE IF NOT EXISTS `{database}`.`{self.name}` (
            {self.columns_sql}
        ) ENGINE = MergeTree
        PARTITION BY {self.partition_by}
        ORDER BY ({order})
        """


METADATA_COLUMNS = """
    `_source` LowCardinality(String),
    `_api_name` LowCardinality(String),
    `_batch_id` String,
    `_ingest_time` DateTime64(6, 'Asia/Shanghai'),
    `_record_hash` FixedString(32)
"""


def _financial_columns(dataset: str) -> str:
    value_columns = ",\n".join(
        f"            `{field}` Nullable(Float64)"
        for field in FINANCIAL_FIELDS_BY_DATASET[dataset]
    )
    return f"""
            `order_book_id` String,
            `report_period` Date32,
            `quarter` LowCardinality(String),
            `source_version_id` FixedString(32),
            `info_date` Nullable(Date32),
            `if_adjusted` Nullable(UInt8),
            `rice_create_tm` Nullable(DateTime64(6, 'Asia/Shanghai')),
            `query_date` Date32,
            `observed_at` DateTime64(6, 'Asia/Shanghai'),
            `statements` LowCardinality(String),
{value_columns},
            {METADATA_COLUMNS}
    """


TABLE_SCHEMAS: dict[str, TableSchema] = {
    "ricequant_trading_calendar": TableSchema(
        name="ricequant_trading_calendar",
        columns_sql=f"""
            `calendar_date` Date32,
            `is_trading_day` UInt8,
            {METADATA_COLUMNS}
        """,
        partition_by="toYear(calendar_date)",
        order_by=("calendar_date",),
    ),
    "ricequant_instrument": TableSchema(
        name="ricequant_instrument",
        columns_sql=f"""
            `snapshot_date` Date32,
            `order_book_id` String,
            `symbol` Nullable(String),
            `abbrev_symbol` Nullable(String),
            `type` Nullable(String),
            `exchange` Nullable(String),
            `listed_date` Nullable(Date32),
            `de_listed_date` Nullable(Date32),
            `status` Nullable(String),
            {METADATA_COLUMNS}
        """,
        partition_by="toYYYYMMDD(snapshot_date)",
        order_by=("snapshot_date", "order_book_id"),
    ),
    "ricequant_option_instrument": TableSchema(
        name="ricequant_option_instrument",
        columns_sql=f"""
            `observation_date` Date32,
            `observed_at` DateTime64(6, 'Asia/Shanghai'),
            `snapshot_date` Date32,
            `order_book_id` String,
            `symbol` Nullable(String),
            `abbrev_symbol` Nullable(String),
            `type` Nullable(String),
            `exchange` Nullable(String),
            `listed_date` Nullable(Date32),
            `de_listed_date` Nullable(Date32),
            `status` Nullable(String),
            `underlying_symbol` Nullable(String),
            `underlying_order_book_id` Nullable(String),
            `option_type` Nullable(String),
            `maturity_date` Nullable(Date32),
            `strike_price` Nullable(Float64),
            `contract_multiplier` Nullable(Float64),
            {METADATA_COLUMNS}
        """,
        partition_by="tuple(observation_date, snapshot_date)",
        order_by=("observation_date", "snapshot_date", "order_book_id"),
    ),
    "ricequant_option_contract_property": TableSchema(
        name="ricequant_option_contract_property",
        columns_sql=f"""
            `trading_date` Date32,
            `order_book_id` String,
            `product_name` Nullable(String),
            `symbol` Nullable(String),
            `contract_multiplier` Nullable(Float64),
            `strike_price` Nullable(Float64),
            {METADATA_COLUMNS}
        """,
        partition_by="trading_date",
        order_by=("trading_date", "order_book_id"),
    ),
    "ricequant_option_daily": TableSchema(
        name="ricequant_option_daily",
        columns_sql=f"""
            `trading_date` Date32,
            `order_book_id` String,
            `open` Nullable(Float64),
            `high` Nullable(Float64),
            `low` Nullable(Float64),
            `close` Nullable(Float64),
            `prev_close` Nullable(Float64),
            `volume` Nullable(Float64),
            `total_turnover` Nullable(Float64),
            `open_interest` Nullable(Float64),
            `strike_price` Nullable(Float64),
            `contract_multiplier` Nullable(Float64),
            `prev_settlement` Nullable(Float64),
            `settlement` Nullable(Float64),
            `limit_up` Nullable(Float64),
            `limit_down` Nullable(Float64),
            `day_session_open` Nullable(Float64),
            {METADATA_COLUMNS}
        """,
        partition_by="trading_date",
        order_by=("trading_date", "order_book_id"),
    ),
    "ricequant_index_daily": TableSchema(
        name="ricequant_index_daily",
        columns_sql=f"""
            `order_book_id` String,
            `trading_date` Date32,
            `open` Nullable(Float64),
            `high` Nullable(Float64),
            `low` Nullable(Float64),
            `close` Nullable(Float64),
            `prev_close` Nullable(Float64),
            `volume` Nullable(Float64),
            `total_turnover` Nullable(Float64),
            `num_trades` Nullable(Float64),
            {METADATA_COLUMNS}
        """,
        partition_by="tuple(order_book_id, toYYYYMM(trading_date))",
        order_by=("order_book_id", "trading_date"),
    ),
    "ricequant_index_component": TableSchema(
        name="ricequant_index_component",
        columns_sql=f"""
            `index_id` String,
            `trading_date` Date32,
            `component_id` String,
            {METADATA_COLUMNS}
        """,
        partition_by="tuple(index_id, toYYYYMM(trading_date))",
        order_by=("index_id", "trading_date", "component_id"),
    ),
    "ricequant_index_weight": TableSchema(
        name="ricequant_index_weight",
        columns_sql=f"""
            `index_id` String,
            `snapshot_date` Date32,
            `component_id` String,
            `weight` Nullable(Float64),
            {METADATA_COLUMNS}
        """,
        partition_by="tuple(index_id, toYYYYMM(snapshot_date))",
        order_by=("index_id", "snapshot_date", "component_id"),
    ),
    "ricequant_index_weight_ex": TableSchema(
        name="ricequant_index_weight_ex",
        columns_sql=f"""
            `index_id` String,
            `trading_date` Date32,
            `component_id` String,
            `weight` Nullable(Float64),
            {METADATA_COLUMNS}
        """,
        partition_by="tuple(index_id, toYYYYMM(trading_date))",
        order_by=("index_id", "trading_date", "component_id"),
    ),
    "ricequant_stock_daily": TableSchema(
        name="ricequant_stock_daily",
        columns_sql=f"""
            `trading_date` Date32,
            `order_book_id` String,
            `open` Nullable(Float64),
            `high` Nullable(Float64),
            `low` Nullable(Float64),
            `close` Nullable(Float64),
            `prev_close` Nullable(Float64),
            `volume` Nullable(Float64),
            `total_turnover` Nullable(Float64),
            `num_trades` Nullable(Float64),
            `limit_up` Nullable(Float64),
            `limit_down` Nullable(Float64),
            {METADATA_COLUMNS}
        """,
        partition_by="trading_date",
        order_by=("trading_date", "order_book_id"),
    ),
    "ricequant_stock_minute": TableSchema(
        name="ricequant_stock_minute",
        columns_sql=f"""
            `trading_date` Date32,
            `order_book_id` String,
            `datetime` DateTime64(0, 'Asia/Shanghai'),
            `open` Nullable(Float64),
            `high` Nullable(Float64),
            `low` Nullable(Float64),
            `close` Nullable(Float64),
            `volume` Nullable(Float64),
            `total_turnover` Nullable(Float64),
            `num_trades` Nullable(Float64),
            {METADATA_COLUMNS}
        """,
        partition_by="trading_date",
        order_by=("trading_date", "order_book_id", "datetime"),
    ),
    "ricequant_stock_ex_factor": TableSchema(
        name="ricequant_stock_ex_factor",
        columns_sql=f"""
            `order_book_id` String,
            `ex_date` Date32,
            `announcement_date` Nullable(Date32),
            `ex_end_date` Nullable(Date32),
            `ex_factor` Nullable(Float64),
            `ex_cum_factor` Nullable(Float64),
            `rice_create_tm` Nullable(DateTime64(6, 'Asia/Shanghai')),
            {METADATA_COLUMNS}
        """,
        partition_by="order_book_id",
        order_by=("order_book_id", "ex_date"),
    ),
    "ricequant_stock_split": TableSchema(
        name="ricequant_stock_split",
        columns_sql=f"""
            `order_book_id` String,
            `ex_dividend_date` Date32,
            `book_closure_date` Nullable(Date32),
            `payable_date` Nullable(Date32),
            `split_coefficient_from` Nullable(Float64),
            `split_coefficient_to` Nullable(Float64),
            `cum_factor` Nullable(Float64),
            `rice_create_tm` Nullable(DateTime64(6, 'Asia/Shanghai')),
            {METADATA_COLUMNS}
        """,
        partition_by="order_book_id",
        order_by=("order_book_id", "ex_dividend_date"),
    ),
    "ricequant_stock_dividend_info": TableSchema(
        name="ricequant_stock_dividend_info",
        columns_sql=f"""
            `order_book_id` String,
            `effective_date` Date32,
            `sequence_num` Int64,
            `info_date` Nullable(Date32),
            `ex_dividend_date` Nullable(Date32),
            `dividend_bonus_share` Nullable(Float64),
            `dividend_transferred_share` Nullable(Float64),
            `dividend_cash_before_tax` Nullable(Float64),
            `dividend_type` Nullable(String),
            `special_dividend` Nullable(UInt8),
            `event_procedure` Nullable(String),
            `dividend_base` Nullable(Float64),
            `proposal_announcement_date` Nullable(Date32),
            `if_dividend` Nullable(String),
            `period` Nullable(String),
            `payable_date` Nullable(Date32),
            `rice_create_tm` Nullable(DateTime64(6, 'Asia/Shanghai')),
            {METADATA_COLUMNS}
        """,
        partition_by="order_book_id",
        order_by=("order_book_id", "effective_date", "sequence_num"),
    ),
    "ricequant_stock_connect_holding_detail": TableSchema(
        name="ricequant_stock_connect_holding_detail",
        columns_sql=f"""
            `trade_date` Date32,
            `order_book_id` String,
            `participant_number` String,
            `ccass_name` Nullable(String),
            `shares_holding` Nullable(Float64),
            `holding_ratio` Nullable(Float64),
            {METADATA_COLUMNS}
        """,
        partition_by="trade_date",
        order_by=("trade_date", "order_book_id", "participant_number"),
    ),
    "ricequant_fund_holding": TableSchema(
        name="ricequant_fund_holding",
        columns_sql=f"""
            `fund_id` String,
            `report_date` Date32,
            `release_date` Nullable(Date32),
            `release_date_key` Date32,
            `held_order_book_id` String,
            `weight` Nullable(Float64),
            `shares` Nullable(Float64),
            `market_value` Nullable(Float64),
            `symbol` Nullable(String),
            `symbol_key` String,
            `asset_type` Nullable(String),
            `asset_type_key` String,
            `category` Nullable(String),
            `category_key` String,
            `region` Nullable(String),
            `region_key` String,
            {METADATA_COLUMNS}
        """,
        partition_by="toYYYYMM(report_date)",
        order_by=(
            "fund_id",
            "report_date",
            "release_date_key",
            "held_order_book_id",
            "asset_type_key",
            "category_key",
            "region_key",
            "symbol_key",
        ),
    ),
    "ricequant_income_statement": TableSchema(
        name="ricequant_income_statement",
        columns_sql=_financial_columns("financial_income"),
        partition_by="order_book_id",
        order_by=("order_book_id", "report_period", "source_version_id"),
    ),
    "ricequant_balance_sheet": TableSchema(
        name="ricequant_balance_sheet",
        columns_sql=_financial_columns("financial_balance"),
        partition_by="order_book_id",
        order_by=("order_book_id", "report_period", "source_version_id"),
    ),
    "ricequant_cashflow_statement": TableSchema(
        name="ricequant_cashflow_statement",
        columns_sql=_financial_columns("financial_cashflow"),
        partition_by="order_book_id",
        order_by=("order_book_id", "report_period", "source_version_id"),
    ),
    "ricequant_financial_metric": TableSchema(
        name="ricequant_financial_metric",
        columns_sql=_financial_columns("financial_metric"),
        partition_by="order_book_id",
        order_by=("order_book_id", "report_period", "source_version_id"),
    ),
    "ricequant_concept_catalog": TableSchema(
        name="ricequant_concept_catalog",
        columns_sql=f"""
            `concept_name` String,
            `inclusion_date` Date32,
            {METADATA_COLUMNS}
        """,
        partition_by="toYear(inclusion_date)",
        order_by=("concept_name", "inclusion_date"),
    ),
    "ricequant_concept_member": TableSchema(
        name="ricequant_concept_member",
        columns_sql=f"""
            `concept_name` String,
            `order_book_id` String,
            `inclusion_date` Date32,
            {METADATA_COLUMNS}
        """,
        partition_by="toYear(inclusion_date)",
        order_by=("concept_name", "order_book_id", "inclusion_date"),
    ),
    "ricequant_concept_snapshot": TableSchema(
        name="ricequant_concept_snapshot",
        columns_sql=f"""
            `observation_date` Date32,
            `observed_at` DateTime64(6, 'Asia/Shanghai'),
            `snapshot_date` Date32,
            `concept_name` String,
            `order_book_id` String,
            {METADATA_COLUMNS}
        """,
        partition_by="tuple(observation_date, snapshot_date)",
        order_by=(
            "observation_date",
            "snapshot_date",
            "concept_name",
            "order_book_id",
        ),
    ),
    "ricequant_industry_mapping": TableSchema(
        name="ricequant_industry_mapping",
        columns_sql=f"""
            `snapshot_date` Date32,
            `source_name` LowCardinality(String),
            `first_industry_code` String,
            `first_industry_name` String,
            `second_industry_code` String,
            `second_industry_name` String,
            `third_industry_code` String,
            `third_industry_name` String,
            {METADATA_COLUMNS}
        """,
        partition_by="snapshot_date",
        order_by=(
            "snapshot_date",
            "source_name",
            "first_industry_code",
            "second_industry_code",
            "third_industry_code",
        ),
    ),
    "ricequant_industry_member": TableSchema(
        name="ricequant_industry_member",
        columns_sql=f"""
            `source_name` LowCardinality(String),
            `industry_level` UInt8,
            `industry_code` String,
            `industry_name` String,
            `order_book_id` String,
            `start_date` Date32,
            `cancel_date` Nullable(Date32),
            {METADATA_COLUMNS}
        """,
        partition_by="toYear(start_date)",
        order_by=(
            "source_name",
            "industry_level",
            "industry_code",
            "order_book_id",
            "start_date",
        ),
    ),
    "ricequant_industry_snapshot": TableSchema(
        name="ricequant_industry_snapshot",
        columns_sql=f"""
            `observation_date` Date32,
            `observed_at` DateTime64(6, 'Asia/Shanghai'),
            `snapshot_date` Date32,
            `source_name` LowCardinality(String),
            `industry_level` UInt8,
            `order_book_id` String,
            `industry_code` String,
            `industry_name` String,
            {METADATA_COLUMNS}
        """,
        partition_by="tuple(observation_date, snapshot_date)",
        order_by=(
            "observation_date",
            "snapshot_date",
            "source_name",
            "industry_level",
            "order_book_id",
        ),
    ),
    "ricequant_sector_snapshot": TableSchema(
        name="ricequant_sector_snapshot",
        columns_sql=f"""
            `observation_date` Date32,
            `observed_at` DateTime64(6, 'Asia/Shanghai'),
            `sector_code` String,
            `sector_name` String,
            `order_book_id` String,
            {METADATA_COLUMNS}
        """,
        partition_by="observation_date",
        order_by=("observation_date", "sector_code", "order_book_id"),
    ),
    "ricequant_stock_tick": TableSchema(
        name="ricequant_stock_tick",
        columns_sql=f"""
            `trading_date` Date32,
            `order_book_id` String,
            `datetime` DateTime64(9, 'Asia/Shanghai'),
            `tick_sequence` UInt32,
            `last` Nullable(Float64),
            `open` Nullable(Float64),
            `high` Nullable(Float64),
            `low` Nullable(Float64),
            `prev_close` Nullable(Float64),
            `volume` Nullable(Float64),
            `total_turnover` Nullable(Float64),
            `num_trades` Nullable(Float64),
            `limit_up` Nullable(Float64),
            `limit_down` Nullable(Float64),
            `change_rate` Nullable(Float64),
            `a1` Nullable(Float64), `a1_v` Nullable(Float64),
            `a2` Nullable(Float64), `a2_v` Nullable(Float64),
            `a3` Nullable(Float64), `a3_v` Nullable(Float64),
            `a4` Nullable(Float64), `a4_v` Nullable(Float64),
            `a5` Nullable(Float64), `a5_v` Nullable(Float64),
            `b1` Nullable(Float64), `b1_v` Nullable(Float64),
            `b2` Nullable(Float64), `b2_v` Nullable(Float64),
            `b3` Nullable(Float64), `b3_v` Nullable(Float64),
            `b4` Nullable(Float64), `b4_v` Nullable(Float64),
            `b5` Nullable(Float64), `b5_v` Nullable(Float64),
            {METADATA_COLUMNS}
        """,
        partition_by="trading_date",
        order_by=("trading_date", "order_book_id", "datetime", "tick_sequence"),
    ),
}


STATE_DDL = """
CREATE TABLE IF NOT EXISTS `{database}`.`ricequant_coverage_event` (
    `event_id` String,
    `run_id` String,
    `dataset` LowCardinality(String),
    `time_semantics` LowCardinality(String),
    `slice_key` String,
    `range_start` Nullable(String),
    `range_end` Nullable(String),
    `partition_value` Nullable(String),
    `status` LowCardinality(String),
    `cursor_json` String,
    `row_count` UInt64,
    `content_hash` String,
    `quota_bytes_used` UInt64,
    `mutable_until` Nullable(Date32),
    `message` String,
    `event_time` DateTime64(6, 'Asia/Shanghai')
) ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (dataset, slice_key, event_time, event_id)
"""


RUN_DDL = """
CREATE TABLE IF NOT EXISTS `{database}`.`ricequant_run_event` (
    `event_id` String,
    `run_id` String,
    `mode` LowCardinality(String),
    `status` LowCardinality(String),
    `dataset` Nullable(String),
    `message` String,
    `event_time` DateTime64(6, 'Asia/Shanghai')
) ENGINE = MergeTree
PARTITION BY toYYYYMM(event_time)
ORDER BY (run_id, event_time, event_id)
"""


ESTIMATE_DDL = """
CREATE TABLE IF NOT EXISTS `{database}`.`ricequant_quota_observation` (
    `event_id` String,
    `dataset` LowCardinality(String),
    `slice_key` String,
    `bytes_used` UInt64,
    `row_count` UInt64,
    `observed_at` DateTime64(6, 'Asia/Shanghai')
) ENGINE = MergeTree
PARTITION BY toYYYYMM(observed_at)
ORDER BY (dataset, observed_at, event_id)
"""
