from __future__ import annotations

import csv
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from tushare_integration.db_engine import DatabaseEngineFactory
from tushare_integration.dwd import FAR_FUTURE_TS_SQL, MIN_LAYER_TRADE_DATE_SQL
from tushare_integration.factor_mapping import (
    DEFAULT_FACTOR_MAPPING_CSV,
    FACTOR_MAPPING_CSV_CANDIDATES as DEFAULT_FACTOR_MAPPING_CSV_CANDIDATES,
    resolve_factor_mapping_csv,
)
from tushare_integration.quality import DqcManager, QualityManager, ValidationMode
from tushare_integration.settings import TushareIntegrationSettings


ROOT_DIR = Path(__file__).resolve().parent.parent
DWS_SCHEMA_DIR = ROOT_DIR / "tushare_integration" / "schema" / "dws"
FACTOR_MAPPING_CSV = DEFAULT_FACTOR_MAPPING_CSV
FACTOR_MAPPING_CSV_CANDIDATES = DEFAULT_FACTOR_MAPPING_CSV_CANDIDATES
DWS_CLICKHOUSE_SEND_RECEIVE_TIMEOUT = 1200

STOCK_FACTOR_WIDE_SOURCES = [
    "dwd_stock_eod_price",
    "dwd_stock_adj_factor",
    "dwd_stock_daily_basic",
    "dwd_stock_eod_quote_metrics",
    "dwd_stock_financial_indicator",
    "dwd_stock_income",
    "dwd_stock_balance_sheet",
    "dwd_stock_cashflow",
    "dwd_stock_northbound_holding",
    "dwd_stock_margin_trading",
    "dwd_stock_chip_distribution",
]
STOCK_FACTOR_WIDE_MATRIX_SOURCES = ["dws_stock_factor_wide"]
STOCK_FACTOR_WIDE_MATRIX_UDF = "dws_stock_factor_rows"
STOCK_FACTOR_WIDE_MATRIX_PREFIX_COLUMNS = [
    "trade_date",
    "event_date",
    "available_trade_date",
    "source_batch_id",
    "source_record_hash",
]
STOCK_FACTOR_WIDE_MATRIX_EXCLUDED_FIELDS = {
    "build_time",
}
STOCK_FACTOR_WIDE_MATRIX_ALIASES = {
    "volume": "`vol`",
    "vwap": "`avg_price`",
    "turnover": "coalesce(`turnover_rate_f`, `turn_over`)",
}
STOCK_FINANCIAL_INDICATOR_QUARTER_SOURCE = "dwd_stock_financial_indicator"
STOCK_FINANCIAL_INDICATOR_QUARTER_FIELDS = [
    "arturn_days",
    "ar_turn",
    "fcfe",
    "fcff",
    "interestdebt",
    "inv_turn",
    "invest_capital",
    "netdebt",
    "current_exint",
    "noncurrent_exint",
    "extra_item",
    "turn_days",
    "retained_earnings",
    "assets_turn",
    "working_capital",
]
STOCK_FINANCIAL_INDICATOR_QUARTER_YTD_DIFF_FIELDS = {
    "extra_item",
    "fcfe",
    "fcff",
}
FINANCIAL_FEATURE_COLUMNS = [
    ("balancesheet", "bond_payable", "ttm_0", "bond_payable_ttm_0"),
    ("balancesheet", "bond_payable", "ttm_1", "bond_payable_ttm_1"),
    ("balancesheet", "fix_assets", "lyr_0", "fix_assets_lyr_0"),
    ("balancesheet", "fix_assets", "lyr_1", "fix_assets_lyr_1"),
    ("balancesheet", "fix_assets", "ttm_0", "fix_assets_ttm_0"),
    ("balancesheet", "fix_assets", "ttm_1", "fix_assets_ttm_1"),
    ("balancesheet", "lt_borr", "ttm_0", "lt_borr_ttm_0"),
    ("balancesheet", "lt_borr", "ttm_1", "lt_borr_ttm_1"),
    ("balancesheet", "money_cap", "lyr_0", "money_cap_lyr_0"),
    ("balancesheet", "money_cap", "lyr_1", "money_cap_lyr_1"),
    ("balancesheet", "money_cap", "mrq_0", "money_cap_mrq_0"),
    ("balancesheet", "money_cap", "ttm_0", "money_cap_ttm_0"),
    ("balancesheet", "money_cap", "ttm_1", "money_cap_ttm_1"),
    ("balancesheet", "non_cur_liab_due_1y", "lyr_0", "non_cur_liab_due_1y_lyr_0"),
    ("balancesheet", "non_cur_liab_due_1y", "lyr_1", "non_cur_liab_due_1y_lyr_1"),
    ("balancesheet", "non_cur_liab_due_1y", "ttm_0", "non_cur_liab_due_1y_ttm_0"),
    ("balancesheet", "non_cur_liab_due_1y", "ttm_1", "non_cur_liab_due_1y_ttm_1"),
    ("balancesheet", "notes_payable", "lyr_0", "notes_payable_lyr_0"),
    ("balancesheet", "notes_payable", "lyr_1", "notes_payable_lyr_1"),
    ("balancesheet", "notes_payable", "ttm_0", "notes_payable_ttm_0"),
    ("balancesheet", "notes_payable", "ttm_1", "notes_payable_ttm_1"),
    ("balancesheet", "st_borr", "ttm_0", "st_borr_ttm_0"),
    ("balancesheet", "st_borr", "ttm_1", "st_borr_ttm_1"),
    ("balancesheet", "total_assets", "lyr_0", "total_assets_lyr_0"),
    ("balancesheet", "total_assets", "lyr_1", "total_assets_lyr_1"),
    ("balancesheet", "total_assets", "mrq_0", "total_assets_mrq_0"),
    ("balancesheet", "total_assets", "mrq_4", "total_assets_mrq_4"),
    ("balancesheet", "total_assets", "ttm_0", "total_assets_ttm_0"),
    ("balancesheet", "total_assets", "ttm_4", "total_assets_ttm_4"),
    ("balancesheet", "total_cur_assets", "lyr_0", "total_cur_assets_lyr_0"),
    ("balancesheet", "total_cur_assets", "lyr_1", "total_cur_assets_lyr_1"),
    ("balancesheet", "total_cur_assets", "ttm_0", "total_cur_assets_ttm_0"),
    ("balancesheet", "total_cur_assets", "ttm_1", "total_cur_assets_ttm_1"),
    ("balancesheet", "total_cur_liab", "lyr_0", "total_cur_liab_lyr_0"),
    ("balancesheet", "total_cur_liab", "lyr_1", "total_cur_liab_lyr_1"),
    ("balancesheet", "total_cur_liab", "ttm_0", "total_cur_liab_ttm_0"),
    ("balancesheet", "total_cur_liab", "ttm_1", "total_cur_liab_ttm_1"),
    ("balancesheet", "total_hldr_eqy_exc_min_int", "lyr_0", "total_hldr_eqy_exc_min_int_lyr_0"),
    ("balancesheet", "total_hldr_eqy_exc_min_int", "lyr_1", "total_hldr_eqy_exc_min_int_lyr_1"),
    ("balancesheet", "total_hldr_eqy_exc_min_int", "mrq_0", "total_hldr_eqy_exc_min_int_mrq_0"),
    ("balancesheet", "total_hldr_eqy_exc_min_int", "mrq_4", "total_hldr_eqy_exc_min_int_mrq_4"),
    ("balancesheet", "total_hldr_eqy_exc_min_int", "ttm_0", "total_hldr_eqy_exc_min_int_ttm_0"),
    ("balancesheet", "total_hldr_eqy_exc_min_int", "ttm_4", "total_hldr_eqy_exc_min_int_ttm_4"),
    ("balancesheet", "total_hldr_eqy_inc_min_int", "lyr_0", "total_hldr_eqy_inc_min_int_lyr_0"),
    ("balancesheet", "total_hldr_eqy_inc_min_int", "lyr_1", "total_hldr_eqy_inc_min_int_lyr_1"),
    ("balancesheet", "total_hldr_eqy_inc_min_int", "ttm_0", "total_hldr_eqy_inc_min_int_ttm_0"),
    ("balancesheet", "total_hldr_eqy_inc_min_int", "ttm_4", "total_hldr_eqy_inc_min_int_ttm_4"),
    ("balancesheet", "total_liab", "lyr_0", "total_liab_lyr_0"),
    ("balancesheet", "total_liab", "mrq_0", "total_liab_mrq_0"),
    ("balancesheet", "total_liab", "ttm_0", "total_liab_ttm_0"),
    ("cashflow", "amort_intang_assets", "lyr_0", "amort_intang_assets_lyr_0"),
    ("cashflow", "amort_intang_assets", "ttm_0", "amort_intang_assets_ttm_0"),
    ("cashflow", "depr_fa_coga_dpba", "lyr_0", "depr_fa_coga_dpba_lyr_0"),
    ("cashflow", "depr_fa_coga_dpba", "ttm_0", "depr_fa_coga_dpba_ttm_0"),
    ("cashflow", "n_cash_flows_fnc_act", "lyr_0", "n_cash_flows_fnc_act_lyr_0"),
    ("cashflow", "n_cash_flows_fnc_act", "lyr_1", "n_cash_flows_fnc_act_lyr_1"),
    ("cashflow", "n_cash_flows_fnc_act", "ttm_0", "n_cash_flows_fnc_act_ttm_0"),
    ("cashflow", "n_cash_flows_fnc_act", "ttm_4", "n_cash_flows_fnc_act_ttm_4"),
    ("cashflow", "n_cashflow_act", "lyr_0", "n_cashflow_act_lyr_0"),
    ("cashflow", "n_cashflow_act", "lyr_1", "n_cashflow_act_lyr_1"),
    ("cashflow", "n_cashflow_act", "ttm_0", "n_cashflow_act_ttm_0"),
    ("cashflow", "n_cashflow_act", "ttm_4", "n_cashflow_act_ttm_4"),
    ("cashflow", "n_cashflow_inv_act", "lyr_0", "n_cashflow_inv_act_lyr_0"),
    ("cashflow", "n_cashflow_inv_act", "lyr_1", "n_cashflow_inv_act_lyr_1"),
    ("cashflow", "n_cashflow_inv_act", "ttm_0", "n_cashflow_inv_act_ttm_0"),
    ("cashflow", "n_cashflow_inv_act", "ttm_4", "n_cashflow_inv_act_ttm_4"),
    ("cashflow", "n_incr_cash_cash_equ", "lyr_0", "n_incr_cash_cash_equ_lyr_0"),
    ("cashflow", "n_incr_cash_cash_equ", "lyr_1", "n_incr_cash_cash_equ_lyr_1"),
    ("cashflow", "n_incr_cash_cash_equ", "ttm_0", "n_incr_cash_cash_equ_ttm_0"),
    ("cashflow", "n_incr_cash_cash_equ", "ttm_4", "n_incr_cash_cash_equ_ttm_4"),
    ("cashflow", "prov_depr_assets", "lyr_0", "prov_depr_assets_lyr_0"),
    ("cashflow", "prov_depr_assets", "ttm_0", "prov_depr_assets_ttm_0"),
    ("income", "ebitda", "lyr", "ebitda_lyr"),
    ("income", "ebitda", "ttm", "ebitda_ttm"),
    ("income", "fin_exp_int_exp", "lyr_0", "fin_exp_int_exp_lyr_0"),
    ("income", "fin_exp_int_exp", "ttm_0", "fin_exp_int_exp_ttm_0"),
    ("income", "fin_exp_int_inc", "lyr_0", "fin_exp_int_inc_lyr_0"),
    ("income", "fin_exp_int_inc", "ttm_0", "fin_exp_int_inc_ttm_0"),
    ("income", "income_tax", "lyr_0", "income_tax_lyr_0"),
    ("income", "income_tax", "ttm_0", "income_tax_ttm_0"),
    ("income", "int_income", "ttm_0", "int_income_ttm_0"),
    ("income", "n_income", "lyr_0", "n_income_lyr_0"),
    ("income", "n_income", "lyr_1", "n_income_lyr_1"),
    ("income", "n_income", "ttm_0", "n_income_ttm_0"),
    ("income", "n_income", "ttm_1", "n_income_ttm_1"),
    ("income", "n_income", "ttm_4", "n_income_ttm_4"),
    ("income", "n_income_attr_p", "lyr_0", "n_income_attr_p_lyr_0"),
    ("income", "n_income_attr_p", "lyr_1", "n_income_attr_p_lyr_1"),
    ("income", "n_income_attr_p", "ttm_0", "n_income_attr_p_ttm_0"),
    ("income", "n_income_attr_p", "ttm_4", "n_income_attr_p_ttm_4"),
    ("income", "operate_profit", "lyr_0", "operate_profit_lyr_0"),
    ("income", "operate_profit", "lyr_1", "operate_profit_lyr_1"),
    ("income", "operate_profit", "ttm_0", "operate_profit_ttm_0"),
    ("income", "operate_profit", "ttm_4", "operate_profit_ttm_4"),
    ("income", "revenue", "lyr_0", "revenue_lyr_0"),
    ("income", "revenue", "lyr_1", "revenue_lyr_1"),
    ("income", "revenue", "ttm_0", "revenue_ttm_0"),
    ("income", "revenue", "ttm_4", "revenue_ttm_4"),
    ("income", "total_cogs", "lyr_0", "total_cogs_lyr_0"),
    ("income", "total_cogs", "lyr_1", "total_cogs_lyr_1"),
    ("income", "total_cogs", "ttm_0", "total_cogs_ttm_0"),
    ("income", "total_cogs", "ttm_4", "total_cogs_ttm_4"),
    ("income", "total_profit", "lyr_0", "total_profit_lyr_0"),
    ("income", "total_profit", "lyr_1", "total_profit_lyr_1"),
    ("income", "total_profit", "ttm_0", "total_profit_ttm_0"),
    ("income", "total_profit", "ttm_4", "total_profit_ttm_4"),
]
FINANCIAL_FEATURE_SOURCE_CONFIG = {
    "balancesheet": {
        "table": "dwd_stock_balance_sheet",
        "sql_alias": "balance_sheet",
        "quarter_report_types": ("1", "4"),
        "annual_report_types": ("1", "4"),
        "ttm_aggregation": "avg",
    },
    "cashflow": {
        "table": "dwd_stock_cashflow",
        "sql_alias": "cashflow",
        "quarter_report_types": ("2", "3"),
        "annual_report_types": ("1", "4"),
        "ttm_aggregation": "sum",
    },
    "income": {
        "table": "dwd_stock_income",
        "sql_alias": "income",
        "quarter_report_types": ("2", "3"),
        "annual_report_types": ("1", "4"),
        "ttm_aggregation": "sum",
    },
}
FINANCIAL_FEATURE_JOIN_ALIASES = [
    "balance_sheet_quarter_features",
    "balance_sheet_annual_features",
    "cashflow_quarter_features",
    "cashflow_annual_features",
    "income_quarter_features",
    "income_annual_features",
]


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f.read())


def _sql_string_literal(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def _load_factor_ids() -> list[str]:
    mapping_csv = resolve_factor_mapping_csv(require_exists=True)
    with open(mapping_csv, "r", encoding="utf-8") as f:
        rows = csv.DictReader(f)
        factor_ids = []
        seen = set()
        for row in rows:
            factor_id = row["factor_id"].strip()
            if factor_id and factor_id not in seen:
                seen.add(factor_id)
                factor_ids.append(factor_id)
        return factor_ids


class DWSManager:
    def __init__(self):
        self.settings = TushareIntegrationSettings.model_validate(
            yaml.safe_load(open("config.yaml", "r", encoding="utf-8").read())
        )
        self.db_engine = None

    def get_db_engine(self):
        if self.db_engine is None:
            clickhouse_timeout = (
                DWS_CLICKHOUSE_SEND_RECEIVE_TIMEOUT
                if self.settings.database.db_type == "clickhouse"
                else None
            )
            self.db_engine = DatabaseEngineFactory.create(
                self.settings,
                clickhouse_send_receive_timeout=clickhouse_timeout,
            )
        return self.db_engine

    def list_tables(self) -> list[str]:
        table_names = []
        for path in sorted(DWS_SCHEMA_DIR.glob("*.yaml")):
            spec = _load_yaml(path)
            table_names.append(spec["name"])
        return table_names

    def load_spec(self, table_name: str) -> dict[str, Any]:
        for path in DWS_SCHEMA_DIR.glob("*.yaml"):
            spec = _load_yaml(path)
            if spec["name"] == table_name:
                return spec
        raise ValueError(f"DWS table {table_name} not found")

    def build_schema(self, spec: dict[str, Any]) -> dict[str, Any]:
        return deepcopy(spec["schema"])

    @staticmethod
    def _financial_feature_kind(suffix: str) -> str:
        return suffix.split("_", 1)[0]

    @staticmethod
    def _financial_feature_offset(suffix: str) -> int:
        parts = suffix.split("_", 1)
        return int(parts[1]) if len(parts) == 2 else 0

    @staticmethod
    def _sql_in(values: tuple[str, ...]) -> str:
        return ", ".join([_sql_string_literal(value) for value in values])

    @staticmethod
    def _financial_feature_entries(api: str, feature_group: str) -> list[tuple[str, str, str, str]]:
        entries = []
        for entry in FINANCIAL_FEATURE_COLUMNS:
            entry_api, _, suffix, _ = entry
            if entry_api != api:
                continue
            kind = DWSManager._financial_feature_kind(suffix)
            if feature_group == "annual" and kind == "lyr":
                entries.append(entry)
            if feature_group == "quarter" and kind in {"mrq", "ttm"}:
                entries.append(entry)
        return entries

    @staticmethod
    def _financial_feature_fields(entries: list[tuple[str, str, str, str]]) -> list[str]:
        return sorted({field for _, field, _, _ in entries})

    @staticmethod
    def _financial_feature_column_names() -> list[str]:
        return [column for _, _, _, column in FINANCIAL_FEATURE_COLUMNS]

    def _render_financial_report_cte(
        self,
        db_name: str,
        api: str,
        feature_group: str,
        fields: list[str],
    ) -> str:
        config = FINANCIAL_FEATURE_SOURCE_CONFIG[api]
        cte_prefix = config["sql_alias"]
        cte_name = f"{cte_prefix}_{feature_group}_reports"
        report_types = (
            config["annual_report_types"] if feature_group == "annual" else config["quarter_report_types"]
        )
        annual_filter = "AND (src.end_type = '4' OR toMonth(src.event_date) = 12)" if feature_group == "annual" else ""
        field_select = ",\n        ".join([f"`{field}`" for field in fields])
        if field_select:
            field_select = ",\n        " + field_select

        return f"""
{cte_name} AS (
    SELECT
        instrument_id,
        event_date AS report_period,
        available_trade_date,
        source_batch_id,
        source_record_hash{field_select}
    FROM (
        SELECT
            src.*,
            row_number() OVER (
                PARTITION BY src.instrument_id, src.event_date, src.available_trade_date
                ORDER BY
                    multiIf(src.report_type IN ('3', '4'), 2, src.report_type IN ('2', '1'), 1, 0) DESC,
                    src.sys_from DESC,
                    src.source_record_hash DESC
            ) AS report_rank
        FROM {db_name}.{config['table']} src
        WHERE src.sys_to = {FAR_FUTURE_TS_SQL}
          AND src.report_type IN ({self._sql_in(report_types)})
          {annual_filter}
    ) src
    WHERE report_rank = 1
)"""

    def _render_financial_feature_cte(
        self,
        api: str,
        feature_group: str,
        entries: list[tuple[str, str, str, str]],
    ) -> str:
        config = FINANCIAL_FEATURE_SOURCE_CONFIG[api]
        cte_prefix = config["sql_alias"]
        report_cte = f"{cte_prefix}_{feature_group}_reports"
        dates_cte = f"{cte_prefix}_{feature_group}_dates"
        asof_cte = f"{cte_prefix}_{feature_group}_asof"
        latest_cte = f"{cte_prefix}_{feature_group}_latest"
        ordered_cte = f"{cte_prefix}_{feature_group}_ordered"
        features_cte = f"{cte_prefix}_{feature_group}_features"
        fields = self._financial_feature_fields(entries)
        max_offset = max(
            self._financial_feature_offset(suffix) + (3 if self._financial_feature_kind(suffix) == "ttm" else 0)
            for _, _, suffix, _ in entries
        )
        joined_field_select = ",\n        ".join([f"r.`{field}` AS `{field}`" for field in fields])
        if joined_field_select:
            joined_field_select = ",\n        " + joined_field_select

        feature_exprs = []
        for _, field, suffix, column in entries:
            kind = self._financial_feature_kind(suffix)
            offset = self._financial_feature_offset(suffix)
            if kind == "ttm":
                condition = f"report_offset >= {offset} AND report_offset < {offset + 4}"
                aggregate = "sumIf" if config["ttm_aggregation"] == "sum" else "avgIf"
                feature_exprs.append(
                    f"if(countIf({condition} AND `{field}` IS NOT NULL) = 4, "
                    f"{aggregate}(`{field}`, {condition}), CAST(NULL, 'Nullable(Float64)')) AS `{column}`"
                )
            else:
                feature_exprs.append(f"anyIf(`{field}`, report_offset = {offset}) AS `{column}`")
        feature_select = ",\n        ".join(feature_exprs)

        return f"""
{dates_cte} AS (
    SELECT DISTINCT
        instrument_id,
        available_trade_date
    FROM {report_cte}
),
{asof_cte} AS (
    SELECT
        d.instrument_id AS instrument_id,
        d.available_trade_date AS available_trade_date,
        r.report_period AS report_period,
        r.available_trade_date AS report_available_trade_date,
        r.source_batch_id AS source_batch_id,
        r.source_record_hash AS source_record_hash{joined_field_select},
        row_number() OVER (
            PARTITION BY d.instrument_id, d.available_trade_date, r.report_period
            ORDER BY
                r.available_trade_date DESC,
                r.source_record_hash DESC
        ) AS revision_rank
    FROM {dates_cte} d
    INNER JOIN {report_cte} r
        ON r.instrument_id = d.instrument_id
    WHERE r.available_trade_date <= d.available_trade_date
),
{latest_cte} AS (
    SELECT *
    FROM {asof_cte}
    WHERE revision_rank = 1
),
{ordered_cte} AS (
    SELECT
        *,
        row_number() OVER (
            PARTITION BY instrument_id, available_trade_date
            ORDER BY report_period DESC
        ) - 1 AS report_offset
    FROM {latest_cte}
),
{features_cte} AS (
    SELECT
        instrument_id,
        available_trade_date,
        arrayStringConcat(
            arrayDistinct(groupArrayIf(source_batch_id, report_offset <= {max_offset} AND source_batch_id != '')),
            '|'
        ) AS source_batch_id,
        lower(hex(MD5(arrayStringConcat(
            arrayDistinct(groupArrayIf(source_record_hash, report_offset <= {max_offset} AND source_record_hash != '')),
            '|'
        )))) AS source_record_hash,
        {feature_select}
    FROM {ordered_cte}
    WHERE report_offset <= {max_offset}
    GROUP BY
        instrument_id,
        available_trade_date
)"""

    def _render_financial_feature_ctes(self, db_name: str) -> str:
        ctes = []
        for api in ("balancesheet", "cashflow", "income"):
            for feature_group in ("quarter", "annual"):
                entries = self._financial_feature_entries(api, feature_group)
                if not entries:
                    continue
                fields = self._financial_feature_fields(entries)
                ctes.append(self._render_financial_report_cte(db_name, api, feature_group, fields))
                ctes.append(self._render_financial_feature_cte(api, feature_group, entries))
        return ",\n".join(ctes)

    def _render_financial_feature_available_trade_dates(self) -> str:
        return "".join(
            [
                f",\n            coalesce({alias}.available_trade_date, price.available_trade_date)"
                for alias in FINANCIAL_FEATURE_JOIN_ALIASES
            ]
        )

    def _render_financial_feature_wide_selects(self) -> str:
        select_items = []
        for api, _, suffix, column in FINANCIAL_FEATURE_COLUMNS:
            feature_group = (
                "annual" if self._financial_feature_kind(suffix) == "lyr" else "quarter"
            )
            alias = f"{FINANCIAL_FEATURE_SOURCE_CONFIG[api]['sql_alias']}_{feature_group}_features"
            select_items.append(f"{alias}.`{column}` AS `{column}`")
        return ",\n        ".join(select_items)

    def _render_financial_feature_output_columns(self) -> str:
        return ",\n    ".join([f"`{column}`" for column in self._financial_feature_column_names()])

    def _render_financial_feature_joins(self) -> str:
        joins = []
        for alias in FINANCIAL_FEATURE_JOIN_ALIASES:
            joins.append(
                f"""    ASOF LEFT JOIN {alias}
        ON price.instrument_id = {alias}.instrument_id
       AND price.available_trade_date >= {alias}.available_trade_date"""
            )
        return "\n".join(joins)

    def _render_financial_feature_lineage_concat(self, column: str) -> str:
        return "".join(
            [
                f",\n            '|', coalesce({alias}.{column}, '')"
                for alias in FINANCIAL_FEATURE_JOIN_ALIASES
            ]
        )

    def _render_stock_factor_wide_sync_sql(self, target_table_name: str) -> str:
        db_name = self.settings.database.db_name
        source_table_sql = ",".join(STOCK_FACTOR_WIDE_SOURCES)
        financial_feature_ctes = self._render_financial_feature_ctes(db_name)
        financial_feature_available_trade_dates = self._render_financial_feature_available_trade_dates()
        financial_feature_wide_selects = self._render_financial_feature_wide_selects()
        financial_feature_output_columns = self._render_financial_feature_output_columns()
        financial_feature_joins = self._render_financial_feature_joins()
        financial_feature_source_batch_id_concat = self._render_financial_feature_lineage_concat("source_batch_id")
        financial_feature_source_record_hash_concat = self._render_financial_feature_lineage_concat("source_record_hash")
        return f"""
INSERT INTO {db_name}.{target_table_name}
WITH
price AS (
    SELECT *
    FROM {db_name}.dwd_stock_eod_price
    WHERE sys_to = {FAR_FUTURE_TS_SQL}
      AND event_date >= {MIN_LAYER_TRADE_DATE_SQL}
),
daily_basic AS (
    SELECT *
    FROM {db_name}.dwd_stock_daily_basic
    WHERE sys_to = {FAR_FUTURE_TS_SQL}
      AND event_date >= {MIN_LAYER_TRADE_DATE_SQL}
),
adj_factor AS (
    SELECT *
    FROM {db_name}.dwd_stock_adj_factor
    WHERE sys_to = {FAR_FUTURE_TS_SQL}
      AND event_date >= {MIN_LAYER_TRADE_DATE_SQL}
),
quote_metrics AS (
    SELECT *
    FROM {db_name}.dwd_stock_eod_quote_metrics
    WHERE sys_to = {FAR_FUTURE_TS_SQL}
      AND event_date >= {MIN_LAYER_TRADE_DATE_SQL}
),
financial_indicator AS (
    SELECT
        instrument_id,
        event_date,
        available_trade_date,
        source_batch_id,
        source_record_hash,
        roe,
        roa,
        roic,
        grossprofit_margin,
        netprofit_margin,
        or_yoy,
        netprofit_yoy,
        op_yoy,
        basic_eps_yoy,
        q_roe,
        q_gsprofit_margin,
        q_netprofit_yoy,
        q_sales_yoy,
        ocf_to_or,
        ocf_to_profit,
        debt_to_assets,
        current_ratio,
        eps,
        bps,
        ocfps,
        rd_exp,
        assets_turn,
        inv_turn,
        ar_turn
    FROM (
        SELECT
            src.*,
            row_number() OVER (
                PARTITION BY src.instrument_id, src.available_trade_date
                ORDER BY
                    src.event_date DESC,
                    src.sys_from DESC,
                    src.source_record_hash DESC
            ) AS financial_rank
        FROM {db_name}.dwd_stock_financial_indicator src
        WHERE src.sys_to = {FAR_FUTURE_TS_SQL}
    ) src
    WHERE financial_rank = 1
),
income AS (
    SELECT
        instrument_id,
        event_date,
        available_trade_date,
        source_batch_id,
        source_record_hash,
        total_revenue,
        revenue,
        n_income,
        n_income_attr_p,
        compr_inc_attr_p,
        compr_inc_attr_m_s,
        oper_cost,
        total_profit,
        ebit,
        ebitda,
        admin_exp,
        sell_exp,
        fin_exp,
        income_tax,
        total_opcost
    FROM (
        SELECT
            src.*,
            row_number() OVER (
                PARTITION BY src.instrument_id, src.available_trade_date
                ORDER BY
                    src.event_date DESC,
                    src.sys_from DESC,
                    src.source_record_hash DESC
            ) AS income_rank
        FROM {db_name}.dwd_stock_income src
        WHERE src.sys_to = {FAR_FUTURE_TS_SQL}
    ) src
    WHERE income_rank = 1
),
balance_sheet AS (
    SELECT
        instrument_id,
        event_date,
        available_trade_date,
        source_batch_id,
        source_record_hash,
        total_assets,
        total_liab,
        total_cur_liab,
        total_cur_assets,
        money_cap,
        total_hldr_eqy_exc_min_int
    FROM (
        SELECT
            src.*,
            row_number() OVER (
                PARTITION BY src.instrument_id, src.available_trade_date
                ORDER BY
                    src.event_date DESC,
                    src.sys_from DESC,
                    src.source_record_hash DESC
            ) AS balance_sheet_rank
        FROM {db_name}.dwd_stock_balance_sheet src
        WHERE src.sys_to = {FAR_FUTURE_TS_SQL}
    ) src
    WHERE balance_sheet_rank = 1
),
cashflow AS (
    SELECT
        instrument_id,
        event_date,
        available_trade_date,
        source_batch_id,
        source_record_hash,
        c_inf_fr_operate_a,
        st_cash_out_act,
        stot_out_inv_act,
        stot_inflows_inv_act,
        stot_cash_in_fnc_act,
        stot_cashout_fnc_act
    FROM (
        SELECT
            src.*,
            row_number() OVER (
                PARTITION BY src.instrument_id, src.available_trade_date
                ORDER BY
                    src.event_date DESC,
                    src.sys_from DESC,
                    src.source_record_hash DESC
            ) AS cashflow_rank
        FROM {db_name}.dwd_stock_cashflow src
        WHERE src.sys_to = {FAR_FUTURE_TS_SQL}
    ) src
    WHERE cashflow_rank = 1
),
{financial_feature_ctes},
northbound_holding AS (
    SELECT *
    FROM {db_name}.dwd_stock_northbound_holding
    WHERE sys_to = {FAR_FUTURE_TS_SQL}
      AND event_date >= {MIN_LAYER_TRADE_DATE_SQL}
),
margin_trading AS (
    SELECT *
    FROM {db_name}.dwd_stock_margin_trading
    WHERE sys_to = {FAR_FUTURE_TS_SQL}
      AND event_date >= {MIN_LAYER_TRADE_DATE_SQL}
),
chip_distribution AS (
    SELECT *
    FROM {db_name}.dwd_stock_chip_distribution
    WHERE sys_to = {FAR_FUTURE_TS_SQL}
      AND event_date >= {MIN_LAYER_TRADE_DATE_SQL}
),
wide_candidates AS (
    SELECT
        price.instrument_id AS instrument_id,
        price.instrument_type AS instrument_type,
        price.exchange AS exchange,
        price.source_code AS source_code,
        price.event_date AS event_date,
        price.event_date AS trade_date,
        greatest(
            price.available_trade_date,
            coalesce(adj_factor.available_trade_date, price.available_trade_date),
            coalesce(daily_basic.available_trade_date, price.available_trade_date),
            coalesce(quote_metrics.available_trade_date, price.available_trade_date),
            coalesce(financial_indicator.available_trade_date, price.available_trade_date),
            coalesce(income.available_trade_date, price.available_trade_date),
            coalesce(balance_sheet.available_trade_date, price.available_trade_date),
            coalesce(cashflow.available_trade_date, price.available_trade_date)
            {financial_feature_available_trade_dates},
            coalesce(northbound_holding.available_trade_date, price.available_trade_date),
            coalesce(margin_trading.available_trade_date, price.available_trade_date),
            coalesce(chip_distribution.available_trade_date, price.available_trade_date)
        ) AS available_trade_date,
        price.open AS open,
        price.high AS high,
        price.low AS low,
        price.close AS close,
        price.pre_close AS pre_close,
        price.pct_chg AS pct_chg,
        price.vol AS vol,
        price.amount AS amount,
        adj_factor.adj_factor AS adj_factor,
        quote_metrics.buying AS buying,
        quote_metrics.selling AS selling,
        quote_metrics.vol_ratio AS vol_ratio,
        quote_metrics.turn_over AS turn_over,
        quote_metrics.swing AS swing,
        quote_metrics.avg_price AS avg_price,
        quote_metrics.strength AS strength,
        quote_metrics.activity AS activity,
        quote_metrics.avg_turnover AS avg_turnover,
        quote_metrics.attack AS attack,
        daily_basic.pe_ttm AS pe_ttm,
        daily_basic.pb AS pb,
        daily_basic.ps_ttm AS ps_ttm,
        daily_basic.dv_ttm AS dv_ttm,
        daily_basic.turnover_rate_f AS turnover_rate_f,
        daily_basic.volume_ratio AS volume_ratio_db,
        daily_basic.circ_mv AS circ_mv,
        daily_basic.total_mv AS total_mv,
        daily_basic.total_share AS total_share,
        daily_basic.float_share AS float_share,
        daily_basic.free_share AS free_share,
        financial_indicator.roe AS roe,
        financial_indicator.roa AS roa,
        financial_indicator.roic AS roic,
        financial_indicator.grossprofit_margin AS grossprofit_margin,
        financial_indicator.netprofit_margin AS netprofit_margin,
        financial_indicator.or_yoy AS or_yoy,
        financial_indicator.netprofit_yoy AS netprofit_yoy,
        financial_indicator.op_yoy AS op_yoy,
        financial_indicator.basic_eps_yoy AS basic_eps_yoy,
        financial_indicator.q_roe AS q_roe,
        financial_indicator.q_gsprofit_margin AS q_gsprofit_margin,
        financial_indicator.q_netprofit_yoy AS q_netprofit_yoy,
        financial_indicator.q_sales_yoy AS q_sales_yoy,
        financial_indicator.ocf_to_or AS ocf_to_or,
        financial_indicator.ocf_to_profit AS ocf_to_profit,
        financial_indicator.debt_to_assets AS debt_to_assets,
        financial_indicator.current_ratio AS current_ratio,
        financial_indicator.eps AS eps,
        financial_indicator.bps AS bps,
        financial_indicator.ocfps AS ocfps,
        financial_indicator.rd_exp AS rd_exp,
        financial_indicator.assets_turn AS assets_turn,
        financial_indicator.inv_turn AS inv_turn,
        financial_indicator.ar_turn AS ar_turn,
        income.total_revenue AS total_revenue,
        income.revenue AS revenue,
        income.n_income AS n_income,
        income.n_income_attr_p AS n_income_attr_p,
        income.compr_inc_attr_p AS compr_inc_attr_p,
        income.compr_inc_attr_m_s AS compr_inc_attr_m_s,
        income.oper_cost AS oper_cost,
        income.total_profit AS total_profit,
        income.ebit AS ebit,
        income.ebitda AS ebitda,
        income.admin_exp AS admin_exp,
        income.sell_exp AS sell_exp,
        income.fin_exp AS fin_exp,
        income.income_tax AS income_tax,
        income.total_opcost AS total_opcost,
        balance_sheet.total_assets AS total_assets,
        balance_sheet.total_liab AS total_liab,
        balance_sheet.total_cur_liab AS total_cur_liab,
        balance_sheet.total_cur_assets AS total_cur_assets,
        balance_sheet.money_cap AS money_cap,
        balance_sheet.total_hldr_eqy_exc_min_int AS total_hldr_eqy_exc_min_int,
        cashflow.c_inf_fr_operate_a AS c_inf_fr_operate_a,
        cashflow.st_cash_out_act AS st_cash_out_act,
        cashflow.stot_out_inv_act AS stot_out_inv_act,
        cashflow.stot_inflows_inv_act AS stot_inflows_inv_act,
        cashflow.stot_cash_in_fnc_act AS stot_cash_in_fnc_act,
        cashflow.stot_cashout_fnc_act AS stot_cashout_fnc_act,
        {financial_feature_wide_selects},
        northbound_holding.vol AS hk_hold_vol,
        northbound_holding.ratio AS hk_hold_ratio,
        margin_trading.rzye AS rzye,
        margin_trading.rzmre AS rzmre,
        margin_trading.rzche AS rzche,
        margin_trading.rqye AS rqye,
        margin_trading.rqyl AS rqyl,
        margin_trading.rqmcl AS rqmcl,
        chip_distribution.winner_rate AS winner_rate,
        chip_distribution.cost_5pct AS cost_5pct,
        chip_distribution.cost_50pct AS cost_50pct,
        chip_distribution.cost_95pct AS cost_95pct,
        chip_distribution.weight_avg AS weight_avg_cost,
        now64(3) AS build_time,
        'derived' AS source,
        '{source_table_sql}' AS source_table,
        concat(
            price.source_batch_id,
            '|', coalesce(adj_factor.source_batch_id, ''),
            '|', coalesce(daily_basic.source_batch_id, ''),
            '|', coalesce(quote_metrics.source_batch_id, ''),
            '|', coalesce(financial_indicator.source_batch_id, ''),
            '|', coalesce(income.source_batch_id, ''),
            '|', coalesce(balance_sheet.source_batch_id, ''),
            '|', coalesce(cashflow.source_batch_id, '')
            {financial_feature_source_batch_id_concat},
            '|', coalesce(northbound_holding.source_batch_id, ''),
            '|', coalesce(margin_trading.source_batch_id, ''),
            '|', coalesce(chip_distribution.source_batch_id, '')
        ) AS source_batch_id,
        lower(hex(MD5(concat(
            price.source_record_hash,
            '|', coalesce(adj_factor.source_record_hash, ''),
            '|', coalesce(daily_basic.source_record_hash, ''),
            '|', coalesce(quote_metrics.source_record_hash, ''),
            '|', coalesce(financial_indicator.source_record_hash, ''),
            '|', coalesce(income.source_record_hash, ''),
            '|', coalesce(balance_sheet.source_record_hash, ''),
            '|', coalesce(cashflow.source_record_hash, '')
            {financial_feature_source_record_hash_concat},
            '|', coalesce(northbound_holding.source_record_hash, ''),
            '|', coalesce(margin_trading.source_record_hash, ''),
            '|', coalesce(chip_distribution.source_record_hash, '')
        )))) AS source_record_hash
    FROM price
    LEFT JOIN adj_factor
        ON adj_factor.instrument_id = price.instrument_id
       AND adj_factor.event_date = price.event_date
    LEFT JOIN daily_basic
        ON daily_basic.instrument_id = price.instrument_id
       AND daily_basic.event_date = price.event_date
    LEFT JOIN quote_metrics
        ON quote_metrics.instrument_id = price.instrument_id
       AND quote_metrics.event_date = price.event_date
    ASOF LEFT JOIN financial_indicator
        ON price.instrument_id = financial_indicator.instrument_id
       AND price.available_trade_date >= financial_indicator.available_trade_date
    ASOF LEFT JOIN income
        ON price.instrument_id = income.instrument_id
       AND price.available_trade_date >= income.available_trade_date
    ASOF LEFT JOIN balance_sheet
        ON price.instrument_id = balance_sheet.instrument_id
       AND price.available_trade_date >= balance_sheet.available_trade_date
    ASOF LEFT JOIN cashflow
        ON price.instrument_id = cashflow.instrument_id
       AND price.available_trade_date >= cashflow.available_trade_date
{financial_feature_joins}
    LEFT JOIN northbound_holding
        ON northbound_holding.instrument_id = price.instrument_id
       AND northbound_holding.event_date = price.event_date
    LEFT JOIN margin_trading
        ON margin_trading.instrument_id = price.instrument_id
       AND margin_trading.event_date = price.event_date
    LEFT JOIN chip_distribution
        ON chip_distribution.instrument_id = price.instrument_id
       AND chip_distribution.event_date = price.event_date
)
SELECT
    instrument_id,
    instrument_type,
    exchange,
    source_code,
    event_date,
    trade_date,
    available_trade_date,
    open,
    high,
    low,
    close,
    pre_close,
    pct_chg,
    vol,
    amount,
    adj_factor,
    buying,
    selling,
    vol_ratio,
    turn_over,
    swing,
    avg_price,
    strength,
    activity,
    avg_turnover,
    attack,
    pe_ttm,
    pb,
    ps_ttm,
    dv_ttm,
    turnover_rate_f,
    volume_ratio_db,
    circ_mv,
    total_mv,
    total_share,
    float_share,
    free_share,
    roe,
    roa,
    roic,
    grossprofit_margin,
    netprofit_margin,
    or_yoy,
    netprofit_yoy,
    op_yoy,
    basic_eps_yoy,
    q_roe,
    q_gsprofit_margin,
    q_netprofit_yoy,
    q_sales_yoy,
    ocf_to_or,
    ocf_to_profit,
    debt_to_assets,
    current_ratio,
    eps,
    bps,
    ocfps,
    rd_exp,
    assets_turn,
    inv_turn,
    ar_turn,
    total_revenue,
    revenue,
    n_income,
    n_income_attr_p,
    compr_inc_attr_p,
    compr_inc_attr_m_s,
    oper_cost,
    total_profit,
    ebit,
    ebitda,
    admin_exp,
    sell_exp,
    fin_exp,
    income_tax,
    total_opcost,
    total_assets,
    total_liab,
    total_cur_liab,
    total_cur_assets,
    money_cap,
    total_hldr_eqy_exc_min_int,
    c_inf_fr_operate_a,
    st_cash_out_act,
    stot_out_inv_act,
    stot_inflows_inv_act,
    stot_cash_in_fnc_act,
    stot_cashout_fnc_act,
    {financial_feature_output_columns},
    hk_hold_vol,
    hk_hold_ratio,
    rzye,
    rzmre,
    rzche,
    rqye,
    rqyl,
    rqmcl,
    winner_rate,
    cost_5pct,
    cost_50pct,
    cost_95pct,
    weight_avg_cost,
    build_time,
    source,
    source_table,
    source_batch_id,
    source_record_hash
FROM wide_candidates
"""

    def _stock_factor_matrix_source_fields(self) -> list[tuple[str, str]]:
        wide_spec = self.load_spec("dws_stock_factor_wide")
        source_columns = wide_spec["schema"]["columns"]
        numeric_fields = [
            column["name"]
            for column in source_columns
            if column.get("data_type") in {"float", "number", "int"}
            and column["name"] not in STOCK_FACTOR_WIDE_MATRIX_EXCLUDED_FIELDS
        ]
        field_exprs: dict[str, str] = {field_name: f"`{field_name}`" for field_name in numeric_fields}
        for alias, expression in STOCK_FACTOR_WIDE_MATRIX_ALIASES.items():
            field_exprs.setdefault(alias, expression)
        return sorted(field_exprs.items())

    def _render_stock_factor_wide_matrix_sync_sql(self, target_table_name: str) -> str:
        db_name = self.settings.database.db_name
        source_table = STOCK_FACTOR_WIDE_MATRIX_SOURCES[0]
        fields = self._stock_factor_matrix_source_fields()
        factor_ids = _load_factor_ids()
        field_names_json = _sql_string_literal(json.dumps([name for name, _ in fields], ensure_ascii=False))
        row_tuple_values = ",\n                ".join(
            [f"`{column}`" for column in STOCK_FACTOR_WIDE_MATRIX_PREFIX_COLUMNS]
            + [expression for _, expression in fields]
        )
        factor_select_sql = ",\n    ".join(
            [
                "toFloat64OrNull("
                f"JSONExtractRaw(factor_values_json, 'values', {_sql_string_literal(factor_id)})"
                f") AS `{factor_id}`"
                for factor_id in factor_ids
            ]
        )
        return f"""
INSERT INTO {db_name}.{target_table_name}
WITH
panel AS (
    SELECT
        instrument_id,
        anyLast(instrument_type) AS instrument_type,
        anyLast(exchange) AS exchange,
        anyLast(source_code) AS source_code,
        arraySort(
            row -> tupleElement(row, 1),
            groupArray(tuple(
                {row_tuple_values}
            ))
        ) AS rows
    FROM {db_name}.{source_table}
    WHERE trade_date >= {MIN_LAYER_TRADE_DATE_SQL}
    GROUP BY instrument_id
),
factorized AS (
    SELECT
        instrument_id,
        instrument_type,
        exchange,
        source_code,
        arrayJoin({STOCK_FACTOR_WIDE_MATRIX_UDF}({field_names_json}, toJSONString(rows))) AS factor_row
    FROM panel
),
factor_rows AS (
    SELECT
        instrument_id,
        instrument_type,
        exchange,
        source_code,
        tupleElement(factor_row, 1) AS event_date,
        tupleElement(factor_row, 2) AS trade_date,
        tupleElement(factor_row, 3) AS available_trade_date,
        tupleElement(factor_row, 4) AS factor_values_json,
        tupleElement(factor_row, 5) AS factor_errors_json,
        tupleElement(factor_row, 6) AS factor_count,
        tupleElement(factor_row, 7) AS source_batch_id,
        tupleElement(factor_row, 8) AS source_record_hash
    FROM factorized
)
SELECT
    instrument_id,
    instrument_type,
    exchange,
    source_code,
    event_date,
    trade_date,
    available_trade_date,
    {factor_select_sql},
    factor_errors_json,
    factor_count,
    now64(3) AS build_time,
    'python_udf' AS source,
    '{source_table}' AS source_table,
    source_batch_id,
    source_record_hash
FROM factor_rows
"""

    @staticmethod
    def _stock_financial_indicator_quarter_value_expr(field: str) -> str:
        if field not in STOCK_FINANCIAL_INDICATOR_QUARTER_YTD_DIFF_FIELDS:
            return f"`{field}`"

        return (
            f"if(toQuarter(event_date) = 1, `{field}`, "
            f"if(coalesce(prev_instrument_id, '') = '' OR `{field}` IS NULL OR `prev_{field}` IS NULL, "
            f"CAST(NULL, 'Nullable(Float64)'), `{field}` - `prev_{field}`))"
        )

    def _render_stock_financial_indicator_quarter_sync_sql(self, target_table_name: str) -> str:
        db_name = self.settings.database.db_name
        source_table = STOCK_FINANCIAL_INDICATOR_QUARTER_SOURCE
        field_selects = ",\n        ".join([f"`{field}`" for field in STOCK_FINANCIAL_INDICATOR_QUARTER_FIELDS])
        curr_selects = ",\n        ".join([f"curr.`{field}` AS `{field}`" for field in STOCK_FINANCIAL_INDICATOR_QUARTER_FIELDS])
        prev_selects = ",\n        ".join(
            [
                f"prev.`{field}` AS `prev_{field}`"
                for field in sorted(STOCK_FINANCIAL_INDICATOR_QUARTER_YTD_DIFF_FIELDS)
            ]
        )
        value_selects = ",\n    ".join(
            [
                f"{self._stock_financial_indicator_quarter_value_expr(field)} AS `{field}`"
                for field in STOCK_FINANCIAL_INDICATOR_QUARTER_FIELDS
            ]
        )

        return f"""
INSERT INTO {db_name}.{target_table_name}
WITH
reports AS (
    SELECT
        instrument_id,
        instrument_type,
        exchange,
        source_code,
        event_date,
        available_trade_date,
        source_batch_id,
        source_record_hash,
        {field_selects}
    FROM (
        SELECT
            src.*,
            row_number() OVER (
                PARTITION BY src.instrument_id, src.event_date, src.available_trade_date
                ORDER BY
                    src.sys_from DESC,
                    src.source_record_hash DESC
            ) AS report_rank
        FROM {db_name}.{source_table} src
        WHERE src.sys_to = {FAR_FUTURE_TS_SQL}
          AND src.event_date >= {MIN_LAYER_TRADE_DATE_SQL}
          AND toMonth(src.event_date) IN (3, 6, 9, 12)
    ) src
    WHERE report_rank = 1
),
quarter_candidates AS (
    SELECT
        curr.instrument_id AS instrument_id,
        curr.instrument_type AS instrument_type,
        curr.exchange AS exchange,
        curr.source_code AS source_code,
        curr.event_date AS event_date,
        toUInt16(toYear(curr.event_date)) AS fiscal_year,
        toUInt8(toQuarter(curr.event_date)) AS fiscal_quarter,
        curr.available_trade_date AS available_trade_date,
        curr.source_batch_id AS source_batch_id,
        curr.source_record_hash AS source_record_hash,
        prev.instrument_id AS prev_instrument_id,
        prev.source_batch_id AS prev_source_batch_id,
        prev.source_record_hash AS prev_source_record_hash,
        {curr_selects},
        {prev_selects},
        row_number() OVER (
            PARTITION BY curr.instrument_id, curr.event_date, curr.available_trade_date
            ORDER BY
                prev.available_trade_date DESC,
                prev.source_record_hash DESC
        ) AS prev_rank
    FROM reports curr
    LEFT JOIN reports prev
        ON prev.instrument_id = curr.instrument_id
       AND toQuarter(curr.event_date) != 1
       AND prev.event_date = addMonths(curr.event_date, -3)
       AND prev.available_trade_date <= curr.available_trade_date
)
SELECT
    instrument_id,
    instrument_type,
    exchange,
    source_code,
    event_date,
    fiscal_year,
    fiscal_quarter,
    available_trade_date,
    {value_selects},
    now64(3) AS build_time,
    'derived' AS source,
    '{source_table}' AS source_table,
    concat(source_batch_id, '|', coalesce(prev_source_batch_id, '')) AS source_batch_id,
    lower(hex(MD5(concat(
        source_record_hash,
        '|',
        coalesce(prev_source_record_hash, '')
    )))) AS source_record_hash
FROM quarter_candidates
WHERE prev_rank = 1
"""

    def render_sync_sql(self, table_name: str, target_table_name: str | None = None) -> str:
        spec = self.load_spec(table_name)
        target_table_name = target_table_name or spec["name"]
        if spec.get("builder") == "stock_factor_wide":
            return self._render_stock_factor_wide_sync_sql(target_table_name)
        if spec.get("builder") == "stock_factor_wide_matrix":
            return self._render_stock_factor_wide_matrix_sync_sql(target_table_name)
        if spec.get("builder") == "stock_financial_indicator_quarter":
            return self._render_stock_financial_indicator_quarter_sync_sql(target_table_name)
        raise ValueError(f"Unsupported DWS builder for {table_name}: {spec.get('builder')}")

    def get_required_source_tables(self, spec: dict[str, Any]) -> list[str]:
        if spec.get("builder") == "stock_factor_wide":
            return STOCK_FACTOR_WIDE_SOURCES
        if spec.get("builder") == "stock_factor_wide_matrix":
            return STOCK_FACTOR_WIDE_MATRIX_SOURCES
        if spec.get("builder") == "stock_financial_indicator_quarter":
            return [STOCK_FINANCIAL_INDICATOR_QUARTER_SOURCE]
        return []

    def ensure_source_tables(self, spec: dict[str, Any]) -> None:
        db_name = self.settings.database.db_name
        required_tables = self.get_required_source_tables(spec)
        source_table_list = ", ".join([f"'{table_name}'" for table_name in required_tables])
        existing_tables = self.get_db_engine().query_df(
            f"""
            SELECT name
            FROM system.tables
            WHERE database = '{db_name}'
              AND name IN ({source_table_list})
            """
        )["name"].tolist()

        missing_tables = sorted(set(required_tables) - set(existing_tables))
        if missing_tables:
            raise ValueError(
                f"Missing source tables for {spec['name']}: {', '.join(missing_tables)}. "
                "Sync the corresponding upstream tables first."
            )

    def ensure_required_functions(self, spec: dict[str, Any]) -> None:
        if self.settings.database.db_type != "clickhouse":
            return
        if spec.get("builder") != "stock_factor_wide_matrix":
            return
        result = self.get_db_engine().query_df(
            f"""
            SELECT count() AS function_count
            FROM system.functions
            WHERE name = '{STOCK_FACTOR_WIDE_MATRIX_UDF}'
              AND origin = 'ExecutableUserDefined'
            """
        )
        if int(result["function_count"].iloc[0]) <= 0:
            raise ValueError(
                f"Missing ClickHouse executable UDF {STOCK_FACTOR_WIDE_MATRIX_UDF}. "
                "Install deploy/clickhouse/user_scripts/dws_stock_factor_rows.py under user_scripts_path "
                "and deploy/clickhouse/user_defined_functions/dws_stock_factor_rows.xml under "
                "user_defined_executable_functions_config, then reload ClickHouse functions."
            )

    def create_table(self, table_name: str) -> None:
        spec = self.load_spec(table_name)
        self.get_db_engine().create_table(spec["name"], self.build_schema(spec))

    def _clickhouse_table_exists(self, table_name: str) -> bool:
        db_name = self.settings.database.db_name
        result = self.get_db_engine().query_df(
            f"""
            SELECT count() AS table_count
            FROM system.tables
            WHERE database = '{db_name}'
              AND name = '{table_name}'
            """
        )
        return int(result["table_count"].iloc[0]) > 0

    def _replace_clickhouse_table_from_tmp(self, target_table: str, tmp_table: str) -> None:
        db_name = self.settings.database.db_name
        db_engine = self.get_db_engine()
        qualified_target = f"{db_name}.{target_table}"
        qualified_tmp = f"{db_name}.{tmp_table}"

        if not self._clickhouse_table_exists(target_table):
            db_engine.query(f"RENAME TABLE {qualified_tmp} TO {qualified_target}")
            return

        try:
            db_engine.query(f"EXCHANGE TABLES {qualified_target} AND {qualified_tmp}")
        except Exception:
            db_engine.query(f"DROP TABLE IF EXISTS {qualified_target}")
            db_engine.query(f"RENAME TABLE {qualified_tmp} TO {qualified_target}")
        else:
            db_engine.query(f"DROP TABLE IF EXISTS {qualified_tmp}")

    def sync_table(
        self,
        table_name: str,
        validation_mode: ValidationMode | None = None,
        skip_validation: bool = False,
    ) -> None:
        spec = self.load_spec(table_name)
        self.ensure_source_tables(spec)
        self.ensure_required_functions(spec)
        target_table = spec["name"]
        tmp_table = f"{target_table}_tmp"
        schema = self.build_schema(spec)
        tmp_schema = deepcopy(schema)
        tmp_schema["comment"] = f"{schema['comment']} TMP"

        db_name = self.settings.database.db_name
        db_engine = self.get_db_engine()
        db_engine.query(f"DROP TABLE IF EXISTS {db_name}.{tmp_table}")
        db_engine.create_table(tmp_table, tmp_schema)
        db_engine.query(self.render_sync_sql(table_name, target_table_name=tmp_table))

        QualityManager(settings=self.settings, db_engine=db_engine).validate_publish(
            layer="dws",
            table_name=target_table,
            target_table_name=tmp_table,
            stage="pre_dws_publish",
            mode=validation_mode,
            skip_validation=skip_validation,
        )

        if self.settings.database.db_type == "clickhouse":
            self._replace_clickhouse_table_from_tmp(target_table, tmp_table)
            self._run_post_publish_dqc(target_table, db_engine)
            return

        db_engine.create_table(target_table, schema)
        db_engine.query(f"TRUNCATE TABLE {db_name}.{target_table}")
        db_engine.query(f"INSERT INTO {db_name}.{target_table} SELECT * FROM {db_name}.{tmp_table}")
        db_engine.query(f"DROP TABLE IF EXISTS {db_name}.{tmp_table}")
        self._run_post_publish_dqc(target_table, db_engine)

    def sync_all(
        self,
        validation_mode: ValidationMode | None = None,
        skip_validation: bool = False,
    ) -> None:
        for table_name in self.list_tables():
            self.sync_table(table_name, validation_mode=validation_mode, skip_validation=skip_validation)

    def _run_post_publish_dqc(self, table_name: str, db_engine) -> None:
        if table_name not in {"dws_stock_factor_wide", "dws_stock_factor_wide_matrix"}:
            return

        dqc_table_name = None if table_name == "dws_stock_factor_wide_matrix" else table_name
        DqcManager(settings=self.settings, db_engine=db_engine).run(
            layer="dws",
            suite_name="stock_factor_panel",
            table_name=dqc_table_name,
        )
