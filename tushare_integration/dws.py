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
STOCK_FACTOR_WIDE_V2_BASE_SQL = (
    ROOT_DIR / "tushare_integration" / "sql" / "dws_stock_factor_wide_v2_base.sql"
)
FACTOR_MAPPING_CSV = DEFAULT_FACTOR_MAPPING_CSV
FACTOR_MAPPING_CSV_CANDIDATES = DEFAULT_FACTOR_MAPPING_CSV_CANDIDATES
DWS_CLICKHOUSE_SEND_RECEIVE_TIMEOUT = 1200
DWS_CLICKHOUSE_QUERY_SETTINGS = {
    "max_query_size": 2 * 1024 * 1024,
    "max_ast_elements": 500000,
}
DWS_TABLE_BUILD_PRIORITY = {
    "dws_stock_financial_indicator_quarter": 0,
    "dws_stock_income_quarter": 0,
    "dws_stock_cashflow_quarter": 0,
    "dws_stock_factor_wide": 10,
    "dws_stock_factor_wide_v2": 11,
    "dws_stock_factor_wide_matrix": 20,
}

STOCK_FACTOR_WIDE_SOURCES = [
    "dwd_stock_eod_price",
    "dwd_stock_adj_factor",
    "dwd_stock_daily_basic",
    "dwd_stock_eod_quote_metrics",
    "dwd_stock_financial_indicator",
    "dws_stock_financial_indicator_quarter",
    "dws_stock_income_quarter",
    "dws_stock_cashflow_quarter",
    "dwd_stock_income",
    "dwd_stock_balance_sheet",
    "dwd_stock_cashflow",
    "dwd_stock_northbound_holding",
    "dwd_stock_margin_trading",
    "dwd_stock_chip_distribution",
]
STOCK_FACTOR_WIDE_MATRIX_SOURCES = ["dws_stock_factor_wide"]
STOCK_FACTOR_WIDE_V2_SOURCES = [
    "dwd_stock_eod_price",
    "dwd_stock_adj_factor",
    "dwd_stock_daily_basic",
    "dwd_stock_eod_quote_metrics",
    "dws_stock_financial_indicator_quarter",
    "dws_stock_income_quarter",
    "dws_stock_cashflow_quarter",
    "dwd_stock_financial_indicator",
    "dwd_stock_income",
    "dwd_stock_balance_sheet",
    "dwd_stock_cashflow",
    "dwd_stock_northbound_holding",
    "dwd_stock_margin_trading",
    "dwd_stock_chip_distribution",
]
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
    "ebit",
    "ebitda",
    "fcfe",
    "fcff",
    "profit_dedt",
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
    "ebit",
    "ebitda",
    "extra_item",
    "fcfe",
    "fcff",
    "profit_dedt",
}
STOCK_INCOME_QUARTER_SOURCE = "dwd_stock_income"
STOCK_INCOME_QUARTER_FIELDS = [
    "ass_invest_income",
    "basic_eps",
    "biz_tax_surchg",
    "diluted_eps",
    "fin_exp",
    "fin_exp_int_exp",
    "fin_exp_int_inc",
    "fv_value_chg_gain",
    "income_tax",
    "int_income",
    "invest_income",
    "n_income",
    "n_income_attr_p",
    "non_oper_exp",
    "non_oper_income",
    "oper_cost",
    "operate_profit",
    "oth_impair_loss_assets",
    "revenue",
    "total_cogs",
    "total_profit",
]
STOCK_INCOME_QUARTER_YTD_DIFF_FIELDS = set(STOCK_INCOME_QUARTER_FIELDS)
STOCK_CASHFLOW_QUARTER_SOURCE = "dwd_stock_cashflow"
STOCK_CASHFLOW_QUARTER_FIELDS = [
    "amort_intang_assets",
    "depr_fa_coga_dpba",
    "eff_fx_flu_cash",
    "lt_amort_deferred_exp",
    "n_cash_flows_fnc_act",
    "n_cashflow_act",
    "n_cashflow_inv_act",
    "n_incr_cash_cash_equ",
    "prov_depr_assets",
]
STOCK_CASHFLOW_QUARTER_YTD_DIFF_FIELDS = set(STOCK_CASHFLOW_QUARTER_FIELDS)
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
    ("fina_indicator", "ebitda", "lyr", "ebitda_lyr"),
    ("fina_indicator", "ebitda", "ttm", "ebitda_ttm"),
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
SUPPLEMENTAL_FINANCIAL_FEATURE_COLUMNS = [
    ('income', 'basic_eps', 'lyr_0', 'basic_eps_lyr_0'),
    ('income', 'basic_eps', 'ttm_0', 'basic_eps_ttm_0'),
    ('income', 'oper_cost', 'lyr_0', 'oper_cost_lyr_0'),
    ('income', 'oper_cost', 'ttm_0', 'oper_cost_ttm_0'),
    ('fina_indicator', 'ebit', 'lyr', 'ebit_lyr'),
    ('fina_indicator', 'ebit', 'ttm', 'ebit_ttm'),
    ('income', 'fv_value_chg_gain', 'lyr_0', 'fv_value_chg_gain_lyr_0'),
    ('income', 'fv_value_chg_gain', 'ttm_0', 'fv_value_chg_gain_ttm_0'),
    ('income', 'fin_exp', 'lyr_0', 'fin_exp_lyr_0'),
    ('income', 'fin_exp', 'ttm_0', 'fin_exp_ttm_0'),
    ('income', 'diluted_eps', 'lyr_0', 'diluted_eps_lyr_0'),
    ('income', 'diluted_eps', 'ttm_0', 'diluted_eps_ttm_0'),
    ('income', 'oth_impair_loss_assets', 'lyr_0', 'oth_impair_loss_assets_lyr_0'),
    ('income', 'oth_impair_loss_assets', 'mrq_0', 'oth_impair_loss_assets_mrq_0'),
    ('income', 'oth_impair_loss_assets', 'ttm_0', 'oth_impair_loss_assets_ttm_0'),
    ('income', 'int_income', 'lyr_0', 'int_income_lyr_0'),
    ('income', 'ass_invest_income', 'lyr_0', 'ass_invest_income_lyr_0'),
    ('income', 'ass_invest_income', 'ttm_0', 'ass_invest_income_ttm_0'),
    ('income', 'invest_income', 'lyr_0', 'invest_income_lyr_0'),
    ('income', 'invest_income', 'ttm_0', 'invest_income_ttm_0'),
    ('income', 'non_oper_exp', 'lyr_0', 'non_oper_exp_lyr_0'),
    ('income', 'non_oper_exp', 'ttm_0', 'non_oper_exp_ttm_0'),
    ('income', 'non_oper_income', 'lyr_0', 'non_oper_income_lyr_0'),
    ('income', 'non_oper_income', 'ttm_0', 'non_oper_income_ttm_0'),
    ('income', 'biz_tax_surchg', 'lyr_0', 'biz_tax_surchg_lyr_0'),
    ('income', 'biz_tax_surchg', 'ttm_0', 'biz_tax_surchg_ttm_0'),
    ('balancesheet', 'acc_exp', 'lyr_0', 'acc_exp_lyr_0'),
    ('balancesheet', 'acc_exp', 'mrq_0', 'acc_exp_mrq_0'),
    ('balancesheet', 'acc_exp', 'ttm_0', 'acc_exp_ttm_0'),
    ('balancesheet', 'acct_payable', 'lyr_0', 'acct_payable_lyr_0'),
    ('balancesheet', 'acct_payable', 'mrq_0', 'acct_payable_mrq_0'),
    ('balancesheet', 'acct_payable', 'ttm_0', 'acct_payable_ttm_0'),
    ('balancesheet', 'accounts_receiv', 'ttm_0', 'accounts_receiv_ttm_0'),
    ('balancesheet', 'adv_receipts', 'lyr_0', 'adv_receipts_lyr_0'),
    ('balancesheet', 'adv_receipts', 'mrq_0', 'adv_receipts_mrq_0'),
    ('balancesheet', 'adv_receipts', 'ttm_0', 'adv_receipts_ttm_0'),
    ('balancesheet', 'notes_receiv', 'lyr_0', 'notes_receiv_lyr_0'),
    ('balancesheet', 'notes_receiv', 'mrq_0', 'notes_receiv_mrq_0'),
    ('balancesheet', 'notes_receiv', 'ttm_0', 'notes_receiv_ttm_0'),
    ('balancesheet', 'bond_payable', 'lyr_0', 'bond_payable_lyr_0'),
    ('balancesheet', 'bond_payable', 'mrq_0', 'bond_payable_mrq_0'),
    ('balancesheet', 'cap_rese', 'lyr_0', 'cap_rese_lyr_0'),
    ('balancesheet', 'cap_rese', 'mrq_0', 'cap_rese_mrq_0'),
    ('balancesheet', 'cap_rese', 'ttm_0', 'cap_rese_ttm_0'),
    ('balancesheet', 'total_cur_assets', 'mrq_0', 'total_cur_assets_mrq_0'),
    ('balancesheet', 'total_cur_liab', 'mrq_0', 'total_cur_liab_mrq_0'),
    ('balancesheet', 'amor_exp', 'lyr_0', 'amor_exp_lyr_0'),
    ('balancesheet', 'amor_exp', 'mrq_0', 'amor_exp_mrq_0'),
    ('balancesheet', 'amor_exp', 'ttm_0', 'amor_exp_ttm_0'),
    ('balancesheet', 'deferred_inc', 'lyr_0', 'deferred_inc_lyr_0'),
    ('balancesheet', 'deferred_inc', 'mrq_0', 'deferred_inc_mrq_0'),
    ('balancesheet', 'deferred_inc', 'ttm_0', 'deferred_inc_ttm_0'),
    ('balancesheet', 'const_materials', 'lyr_0', 'const_materials_lyr_0'),
    ('balancesheet', 'const_materials', 'mrq_0', 'const_materials_mrq_0'),
    ('balancesheet', 'const_materials', 'ttm_0', 'const_materials_ttm_0'),
    ('balancesheet', 'total_hldr_eqy_exc_min_int', 'ttm_1', 'total_hldr_eqy_exc_min_int_ttm_1'),
    ('balancesheet', 'trad_asset', 'lyr_0', 'trad_asset_lyr_0'),
    ('balancesheet', 'trad_asset', 'mrq_0', 'trad_asset_mrq_0'),
    ('balancesheet', 'trad_asset', 'ttm_0', 'trad_asset_ttm_0'),
    ('balancesheet', 'goodwill', 'lyr_0', 'goodwill_lyr_0'),
    ('balancesheet', 'goodwill', 'mrq_0', 'goodwill_mrq_0'),
    ('balancesheet', 'goodwill', 'ttm_0', 'goodwill_ttm_0'),
    ('balancesheet', 'inventories', 'lyr_0', 'inventories_lyr_0'),
    ('balancesheet', 'inventories', 'mrq_0', 'inventories_mrq_0'),
    ('balancesheet', 'inventories', 'ttm_0', 'inventories_ttm_0'),
    ('balancesheet', 'lt_borr', 'lyr_0', 'lt_borr_lyr_0'),
    ('balancesheet', 'lt_borr', 'mrq_0', 'lt_borr_mrq_0'),
    ('balancesheet', 'accounts_receiv', 'lyr_0', 'accounts_receiv_lyr_0'),
    ('balancesheet', 'accounts_receiv', 'mrq_0', 'accounts_receiv_mrq_0'),
    ('balancesheet', 'total_nca', 'lyr_0', 'total_nca_lyr_0'),
    ('balancesheet', 'total_nca', 'mrq_0', 'total_nca_mrq_0'),
    ('balancesheet', 'total_nca', 'ttm_0', 'total_nca_ttm_0'),
    ('balancesheet', 'total_ncl', 'lyr_0', 'total_ncl_lyr_0'),
    ('balancesheet', 'total_ncl', 'mrq_0', 'total_ncl_mrq_0'),
    ('balancesheet', 'total_ncl', 'ttm_0', 'total_ncl_ttm_0'),
    ('balancesheet', 'oth_receiv', 'lyr_0', 'oth_receiv_lyr_0'),
    ('balancesheet', 'oth_receiv', 'mrq_0', 'oth_receiv_mrq_0'),
    ('balancesheet', 'oth_receiv', 'ttm_0', 'oth_receiv_ttm_0'),
    ('balancesheet', 'oth_cur_liab', 'lyr_0', 'oth_cur_liab_lyr_0'),
    ('balancesheet', 'oth_cur_liab', 'mrq_0', 'oth_cur_liab_mrq_0'),
    ('balancesheet', 'oth_cur_liab', 'ttm_0', 'oth_cur_liab_ttm_0'),
    ('balancesheet', 'oth_payable', 'lyr_0', 'oth_payable_lyr_0'),
    ('balancesheet', 'oth_payable', 'mrq_0', 'oth_payable_mrq_0'),
    ('balancesheet', 'oth_payable', 'ttm_0', 'oth_payable_ttm_0'),
    ('balancesheet', 'payroll_payable', 'lyr_0', 'payroll_payable_lyr_0'),
    ('balancesheet', 'payroll_payable', 'mrq_0', 'payroll_payable_mrq_0'),
    ('balancesheet', 'payroll_payable', 'ttm_0', 'payroll_payable_ttm_0'),
    ('balancesheet', 'prepayment', 'lyr_0', 'prepayment_lyr_0'),
    ('balancesheet', 'prepayment', 'mrq_0', 'prepayment_mrq_0'),
    ('balancesheet', 'prepayment', 'ttm_0', 'prepayment_ttm_0'),
    ('balancesheet', 'st_borr', 'lyr_0', 'st_borr_lyr_0'),
    ('balancesheet', 'surplus_rese', 'lyr_0', 'surplus_rese_lyr_0'),
    ('balancesheet', 'surplus_rese', 'mrq_0', 'surplus_rese_mrq_0'),
    ('balancesheet', 'surplus_rese', 'ttm_0', 'surplus_rese_ttm_0'),
    ('balancesheet', 'taxes_payable', 'lyr_0', 'taxes_payable_lyr_0'),
    ('balancesheet', 'taxes_payable', 'mrq_0', 'taxes_payable_mrq_0'),
    ('balancesheet', 'taxes_payable', 'ttm_0', 'taxes_payable_ttm_0'),
    ('balancesheet', 'total_assets', 'mrq_1', 'total_assets_mrq_1'),
    ('balancesheet', 'total_assets', 'ttm_1', 'total_assets_ttm_1'),
    ('balancesheet', 'fix_assets', 'mrq_0', 'fix_assets_mrq_0'),
    ('balancesheet', 'undistr_porfit', 'lyr_0', 'undistr_porfit_lyr_0'),
    ('balancesheet', 'undistr_porfit', 'mrq_0', 'undistr_porfit_mrq_0'),
    ('balancesheet', 'undistr_porfit', 'ttm_0', 'undistr_porfit_ttm_0'),
    ('fina_indicator', 'working_capital', 'lyr', 'working_capital_lyr'),
    ('balancesheet', 'cip', 'lyr_0', 'cip_lyr_0'),
    ('balancesheet', 'cip', 'mrq_0', 'cip_mrq_0'),
    ('balancesheet', 'cip', 'ttm_0', 'cip_ttm_0'),
    ('balancesheet', 'fix_assets_total', 'lyr_0', 'fix_assets_total_lyr_0'),
    ('balancesheet', 'fix_assets_total', 'ttm_0', 'fix_assets_total_ttm_0'),
    ('balancesheet', 'cip_total', 'lyr_0', 'cip_total_lyr_0'),
    ('balancesheet', 'cip_total', 'mrq_0', 'cip_total_mrq_0'),
    ('balancesheet', 'cip_total', 'ttm_0', 'cip_total_ttm_0'),
    ('balancesheet', 'total_hldr_eqy_inc_min_int', 'mrq_0', 'total_hldr_eqy_inc_min_int_mrq_0'),
    ('balancesheet', 'total_hldr_eqy_inc_min_int', 'mrq_1', 'total_hldr_eqy_inc_min_int_mrq_1'),
    ('balancesheet', 'total_hldr_eqy_inc_min_int', 'ttm_1', 'total_hldr_eqy_inc_min_int_ttm_1'),
    ('cashflow', 'lt_amort_deferred_exp', 'ttm_0', 'lt_amort_deferred_exp_ttm_0'),
    ('cashflow', 'lt_amort_deferred_exp', 'mrq_0', 'lt_amort_deferred_exp_mrq_0'),
    ('cashflow', 'eff_fx_flu_cash', 'lyr_0', 'eff_fx_flu_cash_lyr_0'),
    ('cashflow', 'eff_fx_flu_cash', 'ttm_0', 'eff_fx_flu_cash_ttm_0'),
    ('cashflow', 'depr_fa_coga_dpba', 'mrq_0', 'depr_fa_coga_dpba_mrq_0'),
    ('cashflow', 'amort_intang_assets', 'mrq_0', 'amort_intang_assets_mrq_0'),
    ('fina_indicator', 'arturn_days', 'lyr', 'arturn_days_lyr'),
    ('fina_indicator', 'ar_turn', 'lyr', 'ar_turn_lyr'),
    ('fina_indicator', 'ar_turn', 'ttm', 'ar_turn_ttm'),
    ('fina_indicator', 'arturn_days', 'ttm', 'arturn_days_ttm'),
    ('fina_indicator', 'profit_dedt', 'lyr_0', 'profit_dedt_lyr_0'),
    ('fina_indicator', 'profit_dedt', 'ttm_0', 'profit_dedt_ttm_0'),
    ('fina_indicator', 'fcfe', 'lyr_0', 'fcfe_lyr_0'),
    ('fina_indicator', 'fcfe', 'ttm_0', 'fcfe_ttm_0'),
    ('fina_indicator', 'fcff', 'lyr_0', 'fcff_lyr_0'),
    ('fina_indicator', 'fcff', 'ttm_0', 'fcff_ttm_0'),
    ('fina_indicator', 'interestdebt', 'lf', 'interestdebt_lf'),
    ('fina_indicator', 'interestdebt', 'lyr', 'interestdebt_lyr'),
    ('fina_indicator', 'interestdebt', 'ttm', 'interestdebt_ttm'),
    ('fina_indicator', 'inv_turn', 'lyr', 'inv_turn_lyr'),
    ('fina_indicator', 'inv_turn', 'ttm', 'inv_turn_ttm'),
    ('fina_indicator', 'invest_capital', 'lf', 'invest_capital_lf'),
    ('fina_indicator', 'invest_capital', 'lyr', 'invest_capital_lyr'),
    ('fina_indicator', 'invest_capital', 'ttm', 'invest_capital_ttm'),
    ('fina_indicator', 'netdebt', 'lyr', 'netdebt_lyr'),
    ('fina_indicator', 'netdebt', 'ttm', 'netdebt_ttm'),
    ('fina_indicator', 'current_exint', 'lf', 'current_exint_lf'),
    ('fina_indicator', 'current_exint', 'lyr', 'current_exint_lyr'),
    ('fina_indicator', 'current_exint', 'ttm', 'current_exint_ttm'),
    ('fina_indicator', 'noncurrent_exint', 'lf', 'noncurrent_exint_lf'),
    ('fina_indicator', 'noncurrent_exint', 'lyr', 'noncurrent_exint_lyr'),
    ('fina_indicator', 'noncurrent_exint', 'ttm', 'noncurrent_exint_ttm'),
    ('fina_indicator', 'extra_item', 'lyr_0', 'extra_item_lyr_0'),
    ('fina_indicator', 'extra_item', 'ttm_0', 'extra_item_ttm_0'),
    ('fina_indicator', 'turn_days', 'lyr_0', 'turn_days_lyr_0'),
    ('fina_indicator', 'turn_days', 'ttm_0', 'turn_days_ttm_0'),
    ('fina_indicator', 'retained_earnings', 'lf', 'retained_earnings_lf'),
    ('fina_indicator', 'retained_earnings', 'lyr', 'retained_earnings_lyr'),
    ('fina_indicator', 'retained_earnings', 'ttm', 'retained_earnings_ttm'),
    ('fina_indicator', 'assets_turn', 'lyr', 'assets_turn_lyr'),
    ('fina_indicator', 'assets_turn', 'ttm', 'assets_turn_ttm'),
    ('fina_indicator', 'working_capital', 'lf', 'working_capital_lf'),
    ('fina_indicator', 'working_capital', 'ttm', 'working_capital_ttm'),
]
FINANCIAL_FEATURE_COLUMNS.extend(SUPPLEMENTAL_FINANCIAL_FEATURE_COLUMNS)
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
        "quarter_table": "dws_stock_cashflow_quarter",
        "quarter_source_kind": "quarter_dws",
        "sql_alias": "cashflow",
        # Quarter features come from the canonical cumulative-difference DWS
        # table, which is built from report types (1, 4). Types (2, 3) remain
        # useful only as an external reconciliation source.
        "annual_report_types": ("1", "4"),
        "ttm_aggregation": "sum",
    },
    "income": {
        "table": "dwd_stock_income",
        "quarter_table": "dws_stock_income_quarter",
        "quarter_source_kind": "quarter_dws",
        "sql_alias": "income",
        # See cashflow above: production quarter/TTM values use cumulative
        # report types (1, 4), rather than the native single-quarter (2, 3).
        "annual_report_types": ("1", "4"),
        "ttm_aggregation": "sum",
    },
    "fina_indicator": {
        # LYR fields must retain the cumulative/full-year value published in
        # the annual financial-indicator report.  Only MRQ/TTM fields consume
        # the single-quarter values derived in the quarter DWS table.
        "table": "dwd_stock_financial_indicator",
        "source_kind": "raw_versioned_no_report_type",
        "quarter_table": "dws_stock_financial_indicator_quarter",
        "quarter_source_kind": "quarter_dws",
        "sql_alias": "financial_indicator_quarter",
        "ttm_aggregation": {
            "__default__": "avg",
            "ebit": "sum",
            "ebitda": "sum",
            "extra_item": "sum",
            "fcfe": "sum",
            "fcff": "sum",
            "profit_dedt": "sum",
        },
    },
}
FINANCIAL_FEATURE_JOIN_ALIASES = [
    "balance_sheet_quarter_features",
    "balance_sheet_annual_features",
    "cashflow_quarter_features",
    "cashflow_annual_features",
    "income_quarter_features",
    "income_annual_features",
    "financial_indicator_quarter_quarter_features",
    "financial_indicator_quarter_annual_features",
]
DIRECT_EXTRA_FEATURE_COLUMNS = [
    ("daily_basic", "volume_ratio", "volume_ratio"),
    ("income", "assets_impair_loss", "assets_impair_loss"),
    ("income", "int_exp", "int_exp"),
    ("balance_sheet", "div_receiv", "div_receiv"),
    ("balance_sheet", "fa_avail_for_sale", "fa_avail_for_sale"),
    ("balance_sheet", "htm_invest", "htm_invest"),
    ("balance_sheet", "int_receiv", "int_receiv"),
    ("balance_sheet", "intan_assets", "intan_assets"),
    ("balance_sheet", "r_and_d", "r_and_d"),
    ("cashflow", "c_cash_equ_end_period", "c_cash_equ_end_period"),
    ("cashflow", "c_fr_sale_sg", "c_fr_sale_sg"),
    ("cashflow", "c_pay_acq_const_fiolta", "c_pay_acq_const_fiolta"),
]
CALCULATED_FACTOR_COLUMNS = [
    ("ev_lyr", "`total_mv` * 10000 + `interestdebt_lyr` - `money_cap_lyr_0`"),
    ("ev_no_cash_lyr", "`total_mv` * 10000 + `interestdebt_lyr` - `money_cap_lyr_0`"),
    ("ev_no_cash_ttm", "`total_mv` * 10000 + `interestdebt_ttm` - `money_cap_ttm_0`"),
    ("ev_ttm", "`total_mv` * 10000 + `interestdebt_ttm` - `money_cap_ttm_0`"),
]


V2_FINANCIAL_FEATURE_FAMILIES = [
    ("balancesheet", "bond_payable", "bond_payable", ("mrq", "ttm", "lyr")),
    ("balancesheet", "fix_assets", "fix_assets", ("mrq", "ttm", "lyr")),
    ("balancesheet", "lt_borr", "lt_borr", ("mrq", "ttm", "lyr")),
    ("balancesheet", "money_cap", "money_cap", ("mrq", "ttm", "lyr")),
    ("balancesheet", "non_cur_liab_due_1y", "non_cur_liab_due_1y", ("ttm", "lyr")),
    ("balancesheet", "notes_payable", "notes_payable", ("ttm", "lyr")),
    ("balancesheet", "st_borr", "st_borr", ("ttm", "lyr")),
    ("balancesheet", "total_assets", "total_assets", ("mrq", "ttm", "lyr")),
    ("balancesheet", "total_cur_assets", "total_cur_assets", ("mrq", "ttm", "lyr")),
    ("balancesheet", "total_cur_liab", "total_cur_liab", ("mrq", "ttm", "lyr")),
    ("balancesheet", "total_hldr_eqy_exc_min_int", "total_hldr_eqy_exc_min_int", ("mrq", "ttm", "lyr")),
    ("balancesheet", "total_hldr_eqy_inc_min_int", "total_hldr_eqy_inc_min_int", ("mrq", "ttm", "lyr")),
    ("balancesheet", "total_liab", "total_liab", ("mrq", "ttm", "lyr")),
    ("cashflow", "amort_intang_assets", "amort_intang_assets", ("mrq", "ttm", "lyr")),
    ("cashflow", "depr_fa_coga_dpba", "depr_fa_coga_dpba", ("mrq", "ttm", "lyr")),
    ("cashflow", "n_cash_flows_fnc_act", "n_cash_flows_fnc_act", ("ttm", "lyr")),
    ("cashflow", "n_cashflow_act", "n_cashflow_act", ("ttm", "lyr")),
    ("cashflow", "n_cashflow_inv_act", "n_cashflow_inv_act", ("ttm", "lyr")),
    ("cashflow", "n_incr_cash_cash_equ", "n_incr_cash_cash_equ", ("ttm", "lyr")),
    ("cashflow", "prov_depr_assets", "prov_depr_assets", ("ttm", "lyr")),
    ("fina_indicator", "ebitda", "ebitda", ("ttm", "lyr")),
    ("income", "fin_exp_int_exp", "fin_exp_int_exp", ("ttm", "lyr")),
    ("income", "fin_exp_int_inc", "fin_exp_int_inc", ("ttm", "lyr")),
    ("income", "income_tax", "income_tax", ("ttm", "lyr")),
    ("income", "int_income", "int_income", ("ttm", "lyr")),
    ("income", "n_income", "n_income", ("ttm", "lyr")),
    ("income", "n_income_attr_p", "n_income_attr_p", ("ttm", "lyr")),
    ("income", "operate_profit", "operate_profit", ("ttm", "lyr")),
    ("income", "revenue", "revenue", ("ttm", "lyr")),
    ("income", "total_cogs", "total_cogs", ("ttm", "lyr")),
    ("income", "total_profit", "total_profit", ("ttm", "lyr")),
    ("income", "basic_eps", "basic_eps", ("ttm", "lyr")),
    ("income", "oper_cost", "oper_cost", ("ttm", "lyr")),
    ("fina_indicator", "ebit", "ebit", ("ttm", "lyr")),
    ("income", "fv_value_chg_gain", "fv_value_chg_gain", ("ttm", "lyr")),
    ("income", "fin_exp", "fin_exp", ("ttm", "lyr")),
    ("income", "diluted_eps", "diluted_eps", ("ttm", "lyr")),
    ("income", "oth_impair_loss_assets", "oth_impair_loss_assets", ("mrq", "ttm", "lyr")),
    ("income", "ass_invest_income", "ass_invest_income", ("ttm", "lyr")),
    ("income", "invest_income", "invest_income", ("ttm", "lyr")),
    ("income", "non_oper_exp", "non_oper_exp", ("ttm", "lyr")),
    ("income", "non_oper_income", "non_oper_income", ("ttm", "lyr")),
    ("income", "biz_tax_surchg", "biz_tax_surchg", ("ttm", "lyr")),
    ("balancesheet", "acc_exp", "acc_exp", ("mrq", "ttm", "lyr")),
    ("balancesheet", "acct_payable", "acct_payable", ("mrq", "ttm", "lyr")),
    ("balancesheet", "accounts_receiv", "accounts_receiv", ("mrq", "ttm", "lyr")),
    ("balancesheet", "adv_receipts", "adv_receipts", ("mrq", "ttm", "lyr")),
    ("balancesheet", "notes_receiv", "notes_receiv", ("mrq", "ttm", "lyr")),
    ("balancesheet", "cap_rese", "cap_rese", ("mrq", "ttm", "lyr")),
    ("balancesheet", "amor_exp", "amor_exp", ("mrq", "ttm", "lyr")),
    ("balancesheet", "deferred_inc", "deferred_inc", ("mrq", "ttm", "lyr")),
    ("balancesheet", "const_materials", "const_materials", ("mrq", "ttm", "lyr")),
    ("balancesheet", "trad_asset", "trad_asset", ("mrq", "ttm", "lyr")),
    ("balancesheet", "goodwill", "goodwill", ("mrq", "ttm", "lyr")),
    ("balancesheet", "inventories", "inventories", ("mrq", "ttm", "lyr")),
    ("balancesheet", "total_nca", "total_nca", ("mrq", "ttm", "lyr")),
    ("balancesheet", "total_ncl", "total_ncl", ("mrq", "ttm", "lyr")),
    ("balancesheet", "oth_receiv", "oth_receiv", ("mrq", "ttm", "lyr")),
    ("balancesheet", "oth_cur_liab", "oth_cur_liab", ("mrq", "ttm", "lyr")),
    ("balancesheet", "oth_payable", "oth_payable", ("mrq", "ttm", "lyr")),
    ("balancesheet", "payroll_payable", "payroll_payable", ("mrq", "ttm", "lyr")),
    ("balancesheet", "prepayment", "prepayment", ("mrq", "ttm", "lyr")),
    ("balancesheet", "surplus_rese", "surplus_rese", ("mrq", "ttm", "lyr")),
    ("balancesheet", "taxes_payable", "taxes_payable", ("mrq", "ttm", "lyr")),
    ("balancesheet", "undistr_porfit", "undistr_porfit", ("mrq", "ttm", "lyr")),
    ("fina_indicator", "working_capital", "working_capital", ("mrq", "ttm", "lyr")),
    ("balancesheet", "cip", "cip", ("mrq", "ttm", "lyr")),
    ("balancesheet", "fix_assets_total", "fix_assets_total", ("ttm", "lyr")),
    ("balancesheet", "cip_total", "cip_total", ("mrq", "ttm", "lyr")),
    ("cashflow", "lt_amort_deferred_exp", "lt_amort_deferred_exp", ("mrq", "ttm")),
    ("cashflow", "eff_fx_flu_cash", "eff_fx_flu_cash", ("ttm", "lyr")),
    ("fina_indicator", "arturn_days", "arturn_days", ("ttm", "lyr")),
    ("fina_indicator", "ar_turn", "ar_turn", ("ttm", "lyr")),
    ("fina_indicator", "profit_dedt", "profit_dedt", ("ttm", "lyr")),
    ("fina_indicator", "fcfe", "fcfe", ("ttm", "lyr")),
    ("fina_indicator", "fcff", "fcff", ("ttm", "lyr")),
    ("fina_indicator", "interestdebt", "interestdebt", ("mrq", "ttm", "lyr")),
    ("fina_indicator", "inv_turn", "inv_turn", ("ttm", "lyr")),
    ("fina_indicator", "invest_capital", "invest_capital", ("mrq", "ttm", "lyr")),
    ("fina_indicator", "netdebt", "netdebt", ("ttm", "lyr")),
    ("fina_indicator", "current_exint", "current_exint", ("mrq", "ttm", "lyr")),
    ("fina_indicator", "noncurrent_exint", "noncurrent_exint", ("mrq", "ttm", "lyr")),
    ("fina_indicator", "extra_item", "extra_item", ("ttm", "lyr")),
    ("fina_indicator", "turn_days", "turn_days", ("ttm", "lyr")),
    ("fina_indicator", "retained_earnings", "retained_earnings", ("mrq", "ttm", "lyr")),
    ("fina_indicator", "assets_turn", "assets_turn", ("ttm", "lyr")),
]


def _build_v2_financial_feature_columns() -> list[tuple[str, str, str, str]]:
    expanded: list[tuple[str, str, str, str]] = []
    for api, field, prefix, kinds in V2_FINANCIAL_FEATURE_FAMILIES:
        for kind, max_index in (("mrq", 8), ("ttm", 8), ("lyr", 4)):
            if kind not in kinds:
                continue
            for index in range(max_index + 1):
                suffix = f"{kind}_{index}"
                expanded.append((api, field, suffix, f"{prefix}_{suffix}"))
    return expanded


V2_FINANCIAL_FEATURE_COLUMNS = _build_v2_financial_feature_columns()
V2_FINANCIAL_FEATURE_SOURCE_CONFIG = {
    "balancesheet": {
        "table": "dwd_stock_balance_sheet",
        "sql_alias": "balance_sheet",
        "quarter_report_types": ("1", "4"),
        "annual_report_types": ("1", "4"),
        "ttm_aggregation": "avg",
    },
    "cashflow": {
        "table": "dwd_stock_cashflow",
        "quarter_table": "dws_stock_cashflow_quarter",
        "quarter_source_kind": "quarter_dws",
        "sql_alias": "cashflow",
        "annual_report_types": ("1", "4"),
        "ttm_aggregation": "sum",
    },
    "income": {
        "table": "dwd_stock_income",
        "quarter_table": "dws_stock_income_quarter",
        "quarter_source_kind": "quarter_dws",
        "sql_alias": "income",
        "annual_report_types": ("1", "4"),
        "ttm_aggregation": "sum",
    },
    "fina_indicator": {
        "table": "dwd_stock_financial_indicator",
        "source_kind": "raw_versioned_no_report_type",
        "quarter_table": "dws_stock_financial_indicator_quarter",
        "quarter_source_kind": "quarter_dws",
        "sql_alias": "financial_indicator_quarter",
        "ttm_aggregation": {
            "__default__": "avg",
            "ebit": "sum",
            "ebitda": "sum",
            "extra_item": "sum",
            "fcfe": "sum",
            "fcff": "sum",
            "profit_dedt": "sum",
        },
    },
}
V2_FINANCIAL_FEATURE_JOIN_ALIASES = [
    "balance_sheet_quarter_features",
    "balance_sheet_annual_features",
    "cashflow_quarter_features",
    "cashflow_annual_features",
    "income_quarter_features",
    "income_annual_features",
    "financial_indicator_quarter_quarter_features",
    "financial_indicator_quarter_annual_features",
]
V2_CALCULATED_FACTOR_COLUMNS = [
    *[
        (
            f"ev_ttm_{index}",
            f"`total_mv` * 10000 + `interestdebt_ttm_{index}` - `money_cap_ttm_{index}`",
        )
        for index in range(9)
    ],
    *[
        (
            f"ev_lyr_{index}",
            f"`total_mv` * 10000 + `interestdebt_lyr_{index}` - `money_cap_lyr_{index}`",
        )
        for index in range(5)
    ],
    *[
        (
            f"ev_no_cash_ttm_{index}",
            f"`total_mv` * 10000 + `interestdebt_ttm_{index}` - `money_cap_ttm_{index}`",
        )
        for index in range(9)
    ],
    *[
        (
            f"ev_no_cash_lyr_{index}",
            f"`total_mv` * 10000 + `interestdebt_lyr_{index}` - `money_cap_lyr_{index}`",
        )
        for index in range(5)
    ],
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
                clickhouse_query_settings=(
                    DWS_CLICKHOUSE_QUERY_SETTINGS
                    if self.settings.database.db_type == "clickhouse"
                    else None
                ),
            )
        return self.db_engine

    def list_tables(self) -> list[str]:
        table_names = []
        for path in sorted(DWS_SCHEMA_DIR.glob("*.yaml")):
            spec = _load_yaml(path)
            table_names.append(spec["name"])
        return sorted(table_names, key=lambda name: (DWS_TABLE_BUILD_PRIORITY.get(name, 100), name))

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
    def _financial_feature_ttm_aggregation(api: str, field: str) -> str:
        return DWSManager._financial_feature_ttm_aggregation_from(
            FINANCIAL_FEATURE_SOURCE_CONFIG,
            api,
            field,
        )

    @staticmethod
    def _financial_feature_ttm_aggregation_from(
        source_config: dict[str, dict[str, Any]],
        api: str,
        field: str,
    ) -> str:
        aggregation = source_config[api]["ttm_aggregation"]
        if isinstance(aggregation, dict):
            return aggregation.get(field, aggregation.get("__default__", "sum"))
        return aggregation

    @staticmethod
    def _financial_feature_source_config(api: str, feature_group: str) -> dict[str, Any]:
        config = dict(FINANCIAL_FEATURE_SOURCE_CONFIG[api])
        if feature_group == "quarter" and "quarter_table" in config:
            config["table"] = config["quarter_table"]
            config["source_kind"] = config.get("quarter_source_kind", "quarter_dws")
        return config

    @staticmethod
    def _sql_in(values: tuple[str, ...]) -> str:
        return ", ".join([_sql_string_literal(value) for value in values])

    @staticmethod
    def _financial_feature_entries(api: str, feature_group: str) -> list[tuple[str, str, str, str]]:
        return DWSManager._financial_feature_entries_from(
            FINANCIAL_FEATURE_COLUMNS,
            api,
            feature_group,
        )

    @staticmethod
    def _financial_feature_entries_from(
        catalog: list[tuple[str, str, str, str]],
        api: str,
        feature_group: str,
    ) -> list[tuple[str, str, str, str]]:
        entries = []
        for entry in catalog:
            entry_api, _, suffix, _ = entry
            if entry_api != api:
                continue
            kind = DWSManager._financial_feature_kind(suffix)
            if feature_group == "annual" and kind == "lyr":
                entries.append(entry)
            if feature_group == "quarter" and kind in {"lf", "mrq", "ttm"}:
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
        source_configs: dict[str, dict[str, Any]] | None = None,
    ) -> str:
        if source_configs is None:
            config = self._financial_feature_source_config(api, feature_group)
        else:
            config = dict(source_configs[api])
            if feature_group == "quarter" and "quarter_table" in config:
                config["table"] = config["quarter_table"]
                config["source_kind"] = config.get("quarter_source_kind", "quarter_dws")
        cte_prefix = config["sql_alias"]
        cte_name = f"{cte_prefix}_{feature_group}_reports"

        def source_projection(ordering_columns: list[str]) -> str:
            if source_configs is None:
                return "src.*"
            columns = [
                "instrument_id",
                "event_date",
                "available_trade_date",
                "source_batch_id",
                "source_record_hash",
                *ordering_columns,
                *fields,
            ]
            columns = list(dict.fromkeys(columns))
            return ",\n            ".join(f"src.`{column}`" for column in columns)

        if config.get("source_kind") == "quarter_dws":
            period_filter = (
                "AND toMonth(src.event_date) = 12"
                if feature_group == "annual"
                else "AND toMonth(src.event_date) IN (3, 6, 9, 12)"
            )
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
            {source_projection(['build_time'])},
            row_number() OVER (
                PARTITION BY src.instrument_id, src.event_date, src.available_trade_date
                ORDER BY
                    src.build_time DESC,
                    src.source_record_hash DESC
            ) AS report_rank
        FROM {db_name}.{config['table']} src
        WHERE src.event_date >= {MIN_LAYER_TRADE_DATE_SQL}
          {period_filter}
    ) src
    WHERE report_rank = 1
)"""
        if config.get("source_kind") == "raw_versioned_no_report_type":
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
            {source_projection(['update_flag', 'sys_from'])},
            row_number() OVER (
                PARTITION BY src.instrument_id, src.event_date, src.available_trade_date
                ORDER BY
                    src.update_flag DESC,
                    src.sys_from DESC,
                    src.source_record_hash DESC
            ) AS report_rank
        FROM {db_name}.{config['table']} src
        WHERE src.sys_to = {FAR_FUTURE_TS_SQL}
          AND toMonth(src.event_date) = 12
    ) src
    WHERE report_rank = 1
)"""
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
            {source_projection(['report_type', 'f_ann_date', 'update_flag', 'sys_from'])},
            row_number() OVER (
                PARTITION BY src.instrument_id, src.event_date, src.available_trade_date
                ORDER BY
                    multiIf(src.report_type IN ('3', '4'), 2, src.report_type IN ('2', '1'), 1, 0) DESC,
                    src.f_ann_date DESC,
                    src.update_flag DESC,
                    src.sys_from DESC,
                    src.source_record_hash DESC
            ) AS report_rank
        FROM {db_name}.{config['table']} src
        WHERE src.sys_to = {FAR_FUTURE_TS_SQL}
          AND src.report_type IN ({self._sql_in(report_types)})
          -- An announcement before its own report period is structurally
          -- impossible. Keep the raw DWD row for audit, but do not let a
          -- vendor metadata error enter canonical LYR/MRQ features.
          AND src.ann_date >= src.event_date
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
                aggregate = "sumIf" if self._financial_feature_ttm_aggregation(api, field) == "sum" else "avgIf"
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

    def _render_financial_feature_cte_v2(
        self,
        db_name: str,
        api: str,
        feature_group: str,
        entries: list[tuple[str, str, str, str]],
    ) -> str:
        """Render fixed calendar-period slots anchored to every wide-table state date."""

        config = V2_FINANCIAL_FEATURE_SOURCE_CONFIG[api]
        cte_prefix = config["sql_alias"]
        report_cte = f"{cte_prefix}_{feature_group}_reports"
        dates_cte = f"{cte_prefix}_{feature_group}_dates"
        expected_cte = f"{cte_prefix}_{feature_group}_expected"
        selected_cte = f"{cte_prefix}_{feature_group}_selected"
        features_cte = f"{cte_prefix}_{feature_group}_features"
        fields = self._financial_feature_fields(entries)
        max_offset = max(
            self._financial_feature_offset(suffix)
            + (3 if self._financial_feature_kind(suffix) == "ttm" else 0)
            for _, _, suffix, _ in entries
        )
        joined_field_select = ",\n        ".join([f"r.`{field}` AS `{field}`" for field in fields])
        if joined_field_select:
            joined_field_select = ",\n        " + joined_field_select

        if feature_group == "annual":
            expected_period_sql = (
                "addYears(toDate(concat(toString(toYear(addDays(available_trade_date, 1)) - 1), "
                "'-12-31')), -toInt32(report_offset))"
            )
        else:
            expected_period_sql = (
                "addDays(addMonths(toStartOfQuarter(addDays(available_trade_date, 1)), "
                "-3 * toInt32(report_offset)), -1)"
            )
        boundary_period_sql = expected_period_sql.replace(
            "available_trade_date",
            "p.available_trade_date",
        ).replace("report_offset", "0")

        feature_exprs = []
        for _, field, suffix, column in entries:
            kind = self._financial_feature_kind(suffix)
            offset = self._financial_feature_offset(suffix)
            if kind == "ttm":
                condition = f"report_offset >= {offset} AND report_offset < {offset + 4}"
                non_null_count = f"countIf({condition} AND `{field}` IS NOT NULL)"
                value_sum = f"sumIf(ifNull(`{field}`, 0.0), {condition})"
                multiplier = (
                    " * 4"
                    if self._financial_feature_ttm_aggregation_from(
                        V2_FINANCIAL_FEATURE_SOURCE_CONFIG,
                        api,
                        field,
                    )
                    == "sum"
                    else ""
                )
                feature_exprs.append(
                    f"if(countIf({condition} AND report_exists = 1) = 4 AND {non_null_count} > 0, "
                    f"{value_sum} / {non_null_count}{multiplier}, "
                    f"CAST(NULL, 'Nullable(Float64)')) AS `{column}`"
                )
            else:
                feature_exprs.append(
                    f"anyIf(`{field}`, report_offset = {offset} AND report_exists = 1) AS `{column}`"
                )
        feature_select = ",\n        ".join(feature_exprs)

        return f"""
{dates_cte} AS (
    SELECT
        instrument_id,
        available_trade_date
    FROM {report_cte}
    UNION DISTINCT
    SELECT
        p.instrument_id,
        min(p.available_trade_date) AS available_trade_date
    FROM {db_name}.dwd_stock_eod_price p
    WHERE p.sys_to = {FAR_FUTURE_TS_SQL}
      AND p.event_date >= {MIN_LAYER_TRADE_DATE_SQL}
    GROUP BY
        p.instrument_id,
        {boundary_period_sql}
),
{expected_cte} AS (
    SELECT
        instrument_id,
        available_trade_date,
        report_offset,
        {expected_period_sql} AS report_period
    FROM {dates_cte}
    ARRAY JOIN range({max_offset + 1}) AS report_offset
),
{selected_cte} AS (
    SELECT
        e.instrument_id AS instrument_id,
        e.available_trade_date AS available_trade_date,
        e.report_offset AS report_offset,
        e.report_period AS report_period,
        if(r.source_record_hash != '', 1, 0) AS report_exists,
        r.source_batch_id AS source_batch_id,
        r.source_record_hash AS source_record_hash{joined_field_select}
    FROM {expected_cte} e
    ASOF LEFT JOIN {report_cte} r
        ON e.instrument_id = r.instrument_id
       AND e.report_period = r.report_period
       AND e.available_trade_date >= r.available_trade_date
),
{features_cte} AS (
    SELECT
        instrument_id,
        available_trade_date,
        arrayStringConcat(
            arrayDistinct(groupArrayIf(source_batch_id, report_exists = 1 AND source_batch_id != '')),
            '|'
        ) AS source_batch_id,
        lower(hex(MD5(arrayStringConcat(
            arrayDistinct(groupArrayIf(source_record_hash, report_exists = 1 AND source_record_hash != '')),
            '|'
        )))) AS source_record_hash,
        {feature_select}
    FROM {selected_cte}
    GROUP BY
        instrument_id,
        available_trade_date
)"""

    def _render_financial_feature_ctes(self, db_name: str) -> str:
        ctes = []
        for api in ("balancesheet", "cashflow", "income", "fina_indicator"):
            for feature_group in ("quarter", "annual"):
                entries = self._financial_feature_entries(api, feature_group)
                if not entries:
                    continue
                fields = self._financial_feature_fields(entries)
                ctes.append(self._render_financial_report_cte(db_name, api, feature_group, fields))
                ctes.append(self._render_financial_feature_cte(api, feature_group, entries))
        return ",\n".join(ctes)

    def _render_financial_feature_ctes_v2(self, db_name: str) -> str:
        ctes = []
        for api in ("balancesheet", "cashflow", "income", "fina_indicator"):
            for feature_group in ("quarter", "annual"):
                entries = self._financial_feature_entries_from(
                    V2_FINANCIAL_FEATURE_COLUMNS,
                    api,
                    feature_group,
                )
                if not entries:
                    continue
                fields = self._financial_feature_fields(entries)
                ctes.append(
                    self._render_financial_report_cte(
                        db_name,
                        api,
                        feature_group,
                        fields,
                        source_configs=V2_FINANCIAL_FEATURE_SOURCE_CONFIG,
                    )
                )
                ctes.append(
                    self._render_financial_feature_cte_v2(
                        db_name,
                        api,
                        feature_group,
                        entries,
                    )
                )
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

    def _render_direct_extra_feature_wide_selects(self) -> str:
        return ",\n        ".join(
            [f"{alias}.`{field}` AS `{column}`" for alias, field, column in DIRECT_EXTRA_FEATURE_COLUMNS]
        )

    def _render_direct_extra_feature_output_columns(self) -> str:
        return ",\n    ".join([f"`{column}`" for _, _, column in DIRECT_EXTRA_FEATURE_COLUMNS])

    def _render_calculated_factor_output_columns(self) -> str:
        return ",\n    ".join(
            [f"{expression} AS `{column}`" for column, expression in CALCULATED_FACTOR_COLUMNS]
        )

    def _render_financial_feature_joins(self, aliases: list[str] | None = None) -> str:
        joins = []
        for alias in aliases or FINANCIAL_FEATURE_JOIN_ALIASES:
            joins.append(
                f"""    ASOF LEFT JOIN {alias}
        ON price.instrument_id = {alias}.instrument_id
       AND price.available_trade_date >= {alias}.available_trade_date"""
            )
        return "\n".join(joins)

    def _render_financial_feature_lineage_concat(
        self,
        column: str,
        aliases: list[str] | None = None,
    ) -> str:
        return "".join(
            [
                f",\n            '|', coalesce({alias}.{column}, '')"
                for alias in aliases or FINANCIAL_FEATURE_JOIN_ALIASES
            ]
        )

    @staticmethod
    def _render_latest_consolidated_statement_cte(
        db_name: str,
        cte_name: str,
        table_name: str,
        fields: list[str],
    ) -> str:
        """Render a PIT state stream for the latest normal consolidated report.

        A late correction to an old report period must not replace a newer
        report merely because the correction has a later disclosure date.  We
        therefore resolve versions inside each report period first, and only
        then choose the greatest report period visible at each state date.
        Direct wide-table fields intentionally use report_type=1 only; adjusted
        comparative reports (type 4) remain available to LYR/TTM processing.
        """

        report_versions_cte = f"{cte_name}_report_versions"
        state_dates_cte = f"{cte_name}_state_dates"
        field_select = ",\n        ".join([f"r.`{field}` AS `{field}`" for field in fields])
        output_field_select = ",\n        ".join([f"`{field}`" for field in fields])
        return f"""
{report_versions_cte} AS (
    SELECT *
    FROM (
        SELECT
            src.*,
            row_number() OVER (
                PARTITION BY src.instrument_id, src.event_date, src.available_trade_date
                ORDER BY
                    src.f_ann_date DESC,
                    src.update_flag DESC,
                    src.sys_from DESC,
                    src.source_record_hash DESC
            ) AS version_rank
        FROM {db_name}.{table_name} src
        WHERE src.sys_to = {FAR_FUTURE_TS_SQL}
          AND src.report_type = '1'
          -- Preserve malformed source rows in DWD for audit, while excluding
          -- impossible announcement dates from the canonical direct join.
          AND src.ann_date >= src.event_date
    ) src
    WHERE version_rank = 1
),
{state_dates_cte} AS (
    SELECT DISTINCT
        instrument_id,
        available_trade_date
    FROM {report_versions_cte}
),
{cte_name} AS (
    SELECT
        instrument_id,
        event_date,
        available_trade_date,
        source_batch_id,
        source_record_hash,
        {output_field_select}
    FROM (
        SELECT
            d.instrument_id AS instrument_id,
            r.event_date AS event_date,
            d.available_trade_date AS available_trade_date,
            r.source_batch_id AS source_batch_id,
            r.source_record_hash AS source_record_hash,
            {field_select},
            row_number() OVER (
                PARTITION BY d.instrument_id, d.available_trade_date
                ORDER BY
                    r.event_date DESC,
                    r.available_trade_date DESC,
                    r.f_ann_date DESC,
                    r.update_flag DESC,
                    r.sys_from DESC,
                    r.source_record_hash DESC
            ) AS state_rank
        FROM {state_dates_cte} d
        INNER JOIN {report_versions_cte} r
            ON r.instrument_id = d.instrument_id
        -- ClickHouse only permits the range predicate in ASOF JOIN ON clauses.
        -- Keep this as an equi-join and apply PIT visibility as a row filter.
        WHERE r.available_trade_date <= d.available_trade_date
    ) ranked
    WHERE state_rank = 1
)"""

    def _render_stock_factor_wide_sync_sql(self, target_table_name: str) -> str:
        db_name = self.settings.database.db_name
        source_table_sql = ",".join(STOCK_FACTOR_WIDE_SOURCES)
        financial_feature_ctes = self._render_financial_feature_ctes(db_name)
        financial_feature_available_trade_dates = self._render_financial_feature_available_trade_dates()
        financial_feature_wide_selects = self._render_financial_feature_wide_selects()
        financial_feature_output_columns = self._render_financial_feature_output_columns()
        direct_extra_feature_wide_selects = self._render_direct_extra_feature_wide_selects()
        direct_extra_feature_output_columns = self._render_direct_extra_feature_output_columns()
        calculated_factor_output_columns = self._render_calculated_factor_output_columns()
        financial_feature_joins = self._render_financial_feature_joins()
        financial_feature_source_batch_id_concat = self._render_financial_feature_lineage_concat("source_batch_id")
        financial_feature_source_record_hash_concat = self._render_financial_feature_lineage_concat("source_record_hash")
        direct_statement_ctes = ",\n".join(
            [
                self._render_latest_consolidated_statement_cte(
                    db_name,
                    "income",
                    "dwd_stock_income",
                    [
                        "total_revenue",
                        "revenue",
                        "n_income",
                        "n_income_attr_p",
                        "compr_inc_attr_p",
                        "compr_inc_attr_m_s",
                        "oper_cost",
                        "total_profit",
                        "ebit",
                        "ebitda",
                        "admin_exp",
                        "sell_exp",
                        "fin_exp",
                        "income_tax",
                        "total_opcost",
                        "assets_impair_loss",
                        "int_exp",
                    ],
                ),
                self._render_latest_consolidated_statement_cte(
                    db_name,
                    "balance_sheet",
                    "dwd_stock_balance_sheet",
                    [
                        "total_assets",
                        "total_liab",
                        "total_cur_liab",
                        "total_cur_assets",
                        "money_cap",
                        "total_hldr_eqy_exc_min_int",
                        "div_receiv",
                        "fa_avail_for_sale",
                        "htm_invest",
                        "int_receiv",
                        "intan_assets",
                        "r_and_d",
                    ],
                ),
                self._render_latest_consolidated_statement_cte(
                    db_name,
                    "cashflow",
                    "dwd_stock_cashflow",
                    [
                        "c_inf_fr_operate_a",
                        "st_cash_out_act",
                        "stot_out_inv_act",
                        "stot_inflows_inv_act",
                        "stot_cash_in_fnc_act",
                        "stot_cashout_fnc_act",
                        "c_cash_equ_end_period",
                        "c_fr_sale_sg",
                        "c_pay_acq_const_fiolta",
                    ],
                ),
            ]
        )
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
financial_indicator_report_versions AS (
    SELECT *
    FROM (
        SELECT
            src.*,
            row_number() OVER (
                PARTITION BY src.instrument_id, src.event_date, src.available_trade_date
                ORDER BY
                    src.update_flag DESC,
                    src.sys_from DESC,
                    src.source_record_hash DESC
            ) AS version_rank
        FROM {db_name}.dwd_stock_financial_indicator src
        WHERE src.sys_to = {FAR_FUTURE_TS_SQL}
    ) src
    WHERE version_rank = 1
),
financial_indicator_state_dates AS (
    SELECT DISTINCT
        instrument_id,
        available_trade_date
    FROM financial_indicator_report_versions
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
        ar_turn,
        ebit,
        ebitda
    FROM (
        SELECT
            d.instrument_id AS instrument_id,
            src.event_date AS event_date,
            d.available_trade_date AS available_trade_date,
            src.source_batch_id AS source_batch_id,
            src.source_record_hash AS source_record_hash,
            src.roe AS roe,
            src.roa AS roa,
            src.roic AS roic,
            src.grossprofit_margin AS grossprofit_margin,
            src.netprofit_margin AS netprofit_margin,
            src.or_yoy AS or_yoy,
            src.netprofit_yoy AS netprofit_yoy,
            src.op_yoy AS op_yoy,
            src.basic_eps_yoy AS basic_eps_yoy,
            src.q_roe AS q_roe,
            src.q_gsprofit_margin AS q_gsprofit_margin,
            src.q_netprofit_yoy AS q_netprofit_yoy,
            src.q_sales_yoy AS q_sales_yoy,
            src.ocf_to_or AS ocf_to_or,
            src.ocf_to_profit AS ocf_to_profit,
            src.debt_to_assets AS debt_to_assets,
            src.current_ratio AS current_ratio,
            src.eps AS eps,
            src.bps AS bps,
            src.ocfps AS ocfps,
            src.rd_exp AS rd_exp,
            src.assets_turn AS assets_turn,
            src.inv_turn AS inv_turn,
            src.ar_turn AS ar_turn,
            src.ebit AS ebit,
            src.ebitda AS ebitda,
            row_number() OVER (
                PARTITION BY d.instrument_id, d.available_trade_date
                ORDER BY
                    src.event_date DESC,
                    src.available_trade_date DESC,
                    src.update_flag DESC,
                    src.sys_from DESC,
                    src.source_record_hash DESC
            ) AS financial_rank
        FROM financial_indicator_state_dates d
        INNER JOIN financial_indicator_report_versions src
            ON src.instrument_id = d.instrument_id
        WHERE src.available_trade_date <= d.available_trade_date
    ) src
    WHERE financial_rank = 1
),
{direct_statement_ctes},
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
        daily_basic.volume_ratio AS vol_ratio,
        daily_basic.turnover_rate AS turn_over,
        (price.high - price.low) / nullIf(price.pre_close, 0) * 100 AS swing,
        price.amount * 10 / nullIf(price.vol, 0) AS avg_price,
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
        financial_indicator.ebit AS ebit,
        financial_indicator.ebitda AS ebitda,
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
        {direct_extra_feature_wide_selects},
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
    {direct_extra_feature_output_columns},
    {calculated_factor_output_columns},
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

    def _render_stock_factor_wide_v2_sync_sql(
        self,
        target_table_name: str,
    ) -> str:
        db_name = self.settings.database.db_name
        base_sql = STOCK_FACTOR_WIDE_V2_BASE_SQL.read_text(encoding="utf-8").replace(
            "{db_name}",
            db_name,
        )
        v2_spec = self.load_spec("dws_stock_factor_wide_v2")
        v2_financial_columns = {column for _, _, _, column in V2_FINANCIAL_FEATURE_COLUMNS}
        v2_calculated_columns = {column for column, _ in V2_CALCULATED_FACTOR_COLUMNS}
        base_columns = [
            column["name"]
            for column in v2_spec["schema"]["columns"]
            if column["name"] not in v2_financial_columns
            and column["name"] not in v2_calculated_columns
        ]

        financial_feature_ctes = self._render_financial_feature_ctes_v2(db_name)
        financial_feature_joins = self._render_financial_feature_joins(
            V2_FINANCIAL_FEATURE_JOIN_ALIASES
        )
        batch_lineage = self._render_financial_feature_lineage_concat(
            "source_batch_id",
            V2_FINANCIAL_FEATURE_JOIN_ALIASES,
        )
        hash_lineage = self._render_financial_feature_lineage_concat(
            "source_record_hash",
            V2_FINANCIAL_FEATURE_JOIN_ALIASES,
        )
        source_table_sql = ",".join(STOCK_FACTOR_WIDE_V2_SOURCES)

        candidate_selects = []
        for column in base_columns:
            if column == "build_time":
                candidate_selects.append("now64(3) AS `build_time`")
            elif column == "source":
                candidate_selects.append("'derived' AS `source`")
            elif column == "source_table":
                candidate_selects.append(f"'{source_table_sql}' AS `source_table`")
            elif column == "source_batch_id":
                candidate_selects.append(
                    "concat(price.source_batch_id"
                    f"{batch_lineage}\n        ) AS `source_batch_id`"
                )
            elif column == "source_record_hash":
                candidate_selects.append(
                    "lower(hex(MD5(concat(price.source_record_hash"
                    f"{hash_lineage}\n        )))) AS `source_record_hash`"
                )
            else:
                candidate_selects.append(f"price.`{column}` AS `{column}`")

        for api, _, suffix, column in V2_FINANCIAL_FEATURE_COLUMNS:
            feature_group = "annual" if self._financial_feature_kind(suffix) == "lyr" else "quarter"
            alias = f"{V2_FINANCIAL_FEATURE_SOURCE_CONFIG[api]['sql_alias']}_{feature_group}_features"
            candidate_selects.append(f"{alias}.`{column}` AS `{column}`")
        candidate_select_sql = ",\n        ".join(candidate_selects)

        calculated = dict(V2_CALCULATED_FACTOR_COLUMNS)
        candidate_columns = set(base_columns) | {
            column for _, _, _, column in V2_FINANCIAL_FEATURE_COLUMNS
        }
        output_selects = []
        for column_spec in v2_spec["schema"]["columns"]:
            column = column_spec["name"]
            if column in calculated:
                output_selects.append(f"{calculated[column]} AS `{column}`")
            elif column in candidate_columns:
                output_selects.append(f"`{column}`")
            else:
                raise ValueError(f"No v2 stock factor expression for schema column {column}")
        output_select_sql = ",\n    ".join(output_selects)

        return f"""
INSERT INTO {db_name}.{target_table_name}
WITH
price AS (
    {base_sql}
),
{financial_feature_ctes},
wide_candidates AS (
    SELECT
        {candidate_select_sql}
    FROM price
{financial_feature_joins}
)
SELECT
    {output_select_sql}
FROM wide_candidates
SETTINGS max_insert_threads = 4
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
    def _stock_cumulative_quarter_value_expr(field: str, ytd_diff_fields: set[str]) -> str:
        if field not in ytd_diff_fields:
            return f"`{field}`"

        return (
            f"if(toQuarter(event_date) = 1, `{field}`, "
            f"if(coalesce(prev_instrument_id, '') = '' OR `{field}` IS NULL OR `prev_{field}` IS NULL, "
            f"CAST(NULL, 'Nullable(Float64)'), `{field}` - `prev_{field}`))"
        )

    def _render_stock_cumulative_quarter_sync_sql(
        self,
        target_table_name: str,
        source_table: str,
        fields: list[str],
        ytd_diff_fields: set[str],
        report_types: tuple[str, ...] | None = None,
    ) -> str:
        db_name = self.settings.database.db_name
        curr_selects = ",\n        ".join([f"curr.`{field}` AS `{field}`" for field in fields])
        report_field_selects = ",\n        ".join([f"`{field}`" for field in fields])
        candidate_field_selects = ",\n        ".join([f"r.`{field}` AS `{field}`" for field in fields])
        prev_selects = ",\n        ".join(
            [
                f"prev.`{field}` AS `prev_{field}`"
                for field in sorted(ytd_diff_fields)
            ]
        )
        value_selects = ",\n    ".join(
            [
                f"{self._stock_cumulative_quarter_value_expr(field, ytd_diff_fields)} AS `{field}`"
                for field in fields
            ]
        )
        if report_types:
            report_type_filter = f"AND src.report_type IN ({self._sql_in(report_types)})"
            announcement_validity_filter = "AND src.ann_date >= src.event_date"
            report_version_columns = "report_type,\n        f_ann_date,"
            report_rank_order = (
                "multiIf(src.report_type = '4', 2, src.report_type = '1', 1, 0) DESC,\n"
                "                    src.f_ann_date DESC,\n"
                "                    src.update_flag DESC,\n"
                "                    src.sys_from DESC,\n"
                "                    src.source_record_hash DESC"
            )
            current_rank_order = (
                "r.available_trade_date DESC,\n"
                "                    multiIf(r.report_type = '4', 2, r.report_type = '1', 1, 0) DESC,\n"
                "                    r.f_ann_date DESC,\n"
                "                    r.update_flag DESC,\n"
                "                    r.sys_from DESC,\n"
                "                    r.source_record_hash DESC"
            )
        else:
            report_type_filter = ""
            announcement_validity_filter = ""
            report_version_columns = ""
            # fina_indicator has no report_type/f_ann_date.  update_flag is a
            # deterministic tie-breaker only; its ann_date still defines when
            # the source version becomes market-visible.
            report_rank_order = (
                "src.update_flag DESC,\n"
                "                    src.sys_from DESC,\n"
                "                    src.source_record_hash DESC"
            )
            current_rank_order = (
                "r.available_trade_date DESC,\n"
                "                    r.update_flag DESC,\n"
                "                    r.sys_from DESC,\n"
                "                    r.source_record_hash DESC"
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
        update_flag,
        sys_from,
        {report_version_columns}
        {report_field_selects}
    FROM (
        SELECT
            src.*,
            row_number() OVER (
                PARTITION BY src.instrument_id, src.event_date, src.available_trade_date
                ORDER BY
                    {report_rank_order}
            ) AS report_rank
        FROM {db_name}.{source_table} src
        WHERE src.sys_to = {FAR_FUTURE_TS_SQL}
          AND src.event_date >= {MIN_LAYER_TRADE_DATE_SQL}
          AND toMonth(src.event_date) IN (3, 6, 9, 12)
          {report_type_filter}
          {announcement_validity_filter}
    ) src
    WHERE report_rank = 1
),
report_changes AS (
    SELECT DISTINCT
        instrument_id,
        available_trade_date AS state_available_trade_date,
        event_date AS affected_event_date
    FROM reports
),
affected_quarters AS (
    -- A cumulative revision changes its own quarter and, except for Q4, the
    -- following quarter whose delta subtracts this cumulative value.
    SELECT
        instrument_id,
        state_available_trade_date,
        affected_event_date
    FROM report_changes
    UNION DISTINCT
    SELECT
        change.instrument_id,
        change.state_available_trade_date,
        toLastDayOfMonth(addMonths(change.affected_event_date, 3)) AS affected_event_date
    FROM report_changes AS change
    -- Qualify the input column: ClickHouse otherwise expands the SELECT alias
    -- in WHERE, tests the *next* quarter, and reverses the intended Q3/Q4 edge.
    WHERE toQuarter(change.affected_event_date) != 4
),
current_candidates AS (
    SELECT
        a.state_available_trade_date AS state_available_trade_date,
        r.instrument_id AS instrument_id,
        r.instrument_type AS instrument_type,
        r.exchange AS exchange,
        r.source_code AS source_code,
        r.event_date AS event_date,
        r.available_trade_date AS report_available_trade_date,
        r.source_batch_id AS source_batch_id,
        r.source_record_hash AS source_record_hash,
        {candidate_field_selects},
        row_number() OVER (
            PARTITION BY a.instrument_id, a.affected_event_date, a.state_available_trade_date
            ORDER BY
                {current_rank_order}
        ) AS current_rank
    FROM affected_quarters a
    INNER JOIN reports r
        ON r.instrument_id = a.instrument_id
       AND r.event_date = a.affected_event_date
    WHERE r.available_trade_date <= a.state_available_trade_date
),
current_reports AS (
    SELECT
        *,
        if(
            toQuarter(event_date) = 1,
            toDate32('1970-01-01'),
            toLastDayOfMonth(addMonths(event_date, -3))
        ) AS previous_event_date
    FROM current_candidates
    WHERE current_rank = 1
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
        curr.state_available_trade_date AS available_trade_date,
        curr.source_batch_id AS source_batch_id,
        curr.source_record_hash AS source_record_hash,
        prev.instrument_id AS prev_instrument_id,
        prev.source_batch_id AS prev_source_batch_id,
        prev.source_record_hash AS prev_source_record_hash,
        {curr_selects},
        {prev_selects}
    FROM current_reports curr
    -- reports is unique per report period and availability date. ASOF therefore
    -- returns the latest previous-quarter version visible at this state date.
    -- Q1 uses an impossible report period so it keeps an empty previous side.
    ASOF LEFT JOIN reports prev
        ON prev.instrument_id = curr.instrument_id
       AND prev.event_date = curr.previous_event_date
       AND curr.state_available_trade_date >= prev.available_trade_date
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
"""

    def _render_stock_financial_indicator_quarter_sync_sql(self, target_table_name: str) -> str:
        return self._render_stock_cumulative_quarter_sync_sql(
            target_table_name,
            STOCK_FINANCIAL_INDICATOR_QUARTER_SOURCE,
            STOCK_FINANCIAL_INDICATOR_QUARTER_FIELDS,
            STOCK_FINANCIAL_INDICATOR_QUARTER_YTD_DIFF_FIELDS,
        )

    def _render_stock_income_quarter_sync_sql(self, target_table_name: str) -> str:
        return self._render_stock_cumulative_quarter_sync_sql(
            target_table_name,
            STOCK_INCOME_QUARTER_SOURCE,
            STOCK_INCOME_QUARTER_FIELDS,
            STOCK_INCOME_QUARTER_YTD_DIFF_FIELDS,
            report_types=("1", "4"),
        )

    def _render_stock_cashflow_quarter_sync_sql(self, target_table_name: str) -> str:
        return self._render_stock_cumulative_quarter_sync_sql(
            target_table_name,
            STOCK_CASHFLOW_QUARTER_SOURCE,
            STOCK_CASHFLOW_QUARTER_FIELDS,
            STOCK_CASHFLOW_QUARTER_YTD_DIFF_FIELDS,
            report_types=("1", "4"),
        )

    def render_sync_sql(
        self,
        table_name: str,
        target_table_name: str | None = None,
    ) -> str:
        spec = self.load_spec(table_name)
        target_table_name = target_table_name or spec["name"]
        if spec.get("builder") == "stock_factor_wide":
            return self._render_stock_factor_wide_sync_sql(target_table_name)
        if spec.get("builder") == "stock_factor_wide_v2":
            return self._render_stock_factor_wide_v2_sync_sql(target_table_name)
        if spec.get("builder") == "stock_factor_wide_matrix":
            return self._render_stock_factor_wide_matrix_sync_sql(target_table_name)
        if spec.get("builder") == "stock_financial_indicator_quarter":
            return self._render_stock_financial_indicator_quarter_sync_sql(target_table_name)
        if spec.get("builder") == "stock_income_quarter":
            return self._render_stock_income_quarter_sync_sql(target_table_name)
        if spec.get("builder") == "stock_cashflow_quarter":
            return self._render_stock_cashflow_quarter_sync_sql(target_table_name)
        raise ValueError(f"Unsupported DWS builder for {table_name}: {spec.get('builder')}")

    def get_required_source_tables(self, spec: dict[str, Any]) -> list[str]:
        if spec.get("builder") == "stock_factor_wide":
            return STOCK_FACTOR_WIDE_SOURCES
        if spec.get("builder") == "stock_factor_wide_v2":
            return STOCK_FACTOR_WIDE_V2_SOURCES
        if spec.get("builder") == "stock_factor_wide_matrix":
            return STOCK_FACTOR_WIDE_MATRIX_SOURCES
        if spec.get("builder") == "stock_financial_indicator_quarter":
            return [STOCK_FINANCIAL_INDICATOR_QUARTER_SOURCE]
        if spec.get("builder") == "stock_income_quarter":
            return [STOCK_INCOME_QUARTER_SOURCE]
        if spec.get("builder") == "stock_cashflow_quarter":
            return [STOCK_CASHFLOW_QUARTER_SOURCE]
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
        if table_name not in {
            "dws_stock_factor_wide",
            "dws_stock_factor_wide_v2",
            "dws_stock_factor_wide_matrix",
        }:
            return

        dqc_table_name = None if table_name == "dws_stock_factor_wide_matrix" else table_name
        DqcManager(settings=self.settings, db_engine=db_engine).run(
            layer="dws",
            suite_name="stock_factor_panel",
            table_name=dqc_table_name,
        )
