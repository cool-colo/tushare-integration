# Frozen pre-filter renderer from f7734d7, kept only for PIT equivalence tests.
"""Explicit, source-separated additions to the Tushare v2 scalar contract.

The manifest also records exclusions and unavailable inputs. In particular an
unknown source coverage is never evidence of zero holdings/events/coverage.
"""

from __future__ import annotations

import json
from pathlib import Path


MANIFEST = json.loads((Path(__file__).resolve().parents[2] / "tushare_integration/schema/dws/v2_scalar_extensions.json").read_text(encoding="utf-8"))
SCALAR_SPECS = [item for item in MANIFEST if item["status"] != "excluded"]
FINANCIAL_ADDITIONS = [
    (item["api"], item["field"], item["suffix"], item["name"]) for item in SCALAR_SPECS if "api" in item
]
SUPPLEMENTAL_SPECS = [item for item in SCALAR_SPECS if "api" not in item]
SOURCES = [
    "dwd_index_eod_price",
    "dwd_stock_limit",
    "dwd_security_master",
    "dwd_sw_industry_member",
    "dwd_stock_holder_number",
    "dwd_stock_top_list",
    "dwd_index_weight",
    "dwd_stock_dividend",
    "dwd_stock_research_report",
]
NULL_FLOAT = "CAST(NULL, 'Nullable(Float64)')"
NULL_INT = "CAST(NULL, 'Nullable(Int64)')"
CURRENT = "toDateTime64('9999-12-31 00:00:00', 3)"


def extend_financial_catalog(entries: list[tuple[str, str, str, str]]) -> list[tuple[str, str, str, str]]:
    """Preserve family order, adding only requested offsets in numeric order."""
    groups = {}
    for entry in [*entries, *FINANCIAL_ADDITIONS]:
        prefix = entry[3].removesuffix("_" + entry[2])
        groups.setdefault(prefix, {})[entry[3]] = entry
    kind_order = {"mrq": 0, "ttm": 1, "lyr": 2}
    return [
        entry
        for group in groups.values()
        for entry in sorted(group.values(), key=lambda e: (kind_order[e[2].split("_")[0]], int(e[2].split("_")[1])))
    ]


def _lineage(alias: str = "r") -> str:
    return (
        f"arrayStringConcat(arraySort(groupUniqArray({alias}.source_batch_id)), '|') AS source_batch_id, "
        f"hex(MD5(arrayStringConcat(arraySort(groupUniqArray({alias}.source_record_hash)), '|'))) AS source_record_hash"
    )


def _daily_financial(db: str, table: str, name: str, fields: list[str]) -> str:
    projection = ", ".join("r." + field for field in fields)
    return f"""{name} AS (
    SELECT instrument_id, trade_date, t, report_period, {", ".join(fields)},
           source_batch_id, source_record_hash
    FROM (
        SELECT p.instrument_id AS instrument_id, p.trade_date AS trade_date, p.t, r.event_date AS report_period,
               {projection}, r.source_batch_id, r.source_record_hash,
               row_number() OVER (
                   PARTITION BY p.instrument_id, p.trade_date, r.event_date
                   ORDER BY r.available_trade_date DESC,
                            (r.report_type = '4') DESC, r.f_ann_date DESC,
                            r.update_flag DESC, r.sys_from DESC, r.source_record_hash DESC
               ) AS version_rank
        FROM v2_days p INNER JOIN {db}.{table} r ON p.instrument_id = r.instrument_id
        WHERE r.available_trade_date <= p.t AND r.sys_to = {CURRENT}
          AND r.report_type IN ('1', '4') AND r.ann_date >= r.event_date
          AND r.event_date >= toDate32('2010-01-01')
          AND r.event_date = toLastDayOfMonth(r.event_date)
          AND toMonth(r.event_date) IN (3,6,9,12)
    ) WHERE version_rank = 1
)"""


def render_ctes(db: str) -> str:
    """Daily visibility t is the existing v2 available_trade_date (T+1 panel)."""
    ctes = [
        f"""v2_days AS (
    SELECT DISTINCT instrument_id, event_date AS trade_date, available_trade_date AS t
    FROM {db}.dwd_stock_eod_price
    WHERE sys_to = {CURRENT} AND event_date >= toDate32('2010-01-01')
)"""
    ]
    ctes += [
        _daily_financial(db, table, name, fields)
        for table, name, fields in (
            ("dwd_stock_income", "v2_income_reports", ["n_income_attr_p"]),
            ("dwd_stock_balance_sheet", "v2_balance_reports", ["total_hldr_eqy_exc_min_int"]),
            ("dwd_stock_cashflow", "v2_cashflow_reports", ["depr_fa_coga_dpba"]),
        )
    ]
    ctes.append(f"""v2_fiscal AS (
    SELECT r.instrument_id AS instrument_id, r.trade_date AS trade_date, r.t,
           toYear(max(r.report_period)) AS fy0,
           maxIf(toNullable(r.report_period), toMonth(r.report_period) = 12) AS last_annual,
           if(countIf(r.report_period = toDate32(concat(toString(toYear(r.t)-1), '-12-31'))) > 0,
              toYear(r.t), toYear(r.t)-1) AS active_year,
           argMax(tuple(r.n_income_attr_p), r.report_period).1 AS latest_np,
           toMonth(max(r.report_period)) = 12 AS fy0_actual,
           {_lineage()}
    FROM v2_income_reports r GROUP BY r.instrument_id, r.trade_date, r.t
),
v2_book AS (
    SELECT r.instrument_id AS instrument_id, r.trade_date AS trade_date,
           max(r.report_period) AS book_period,
           argMax(tuple(r.total_hldr_eqy_exc_min_int), r.report_period).1 AS book_value,
           {_lineage()}
    FROM v2_balance_reports r GROUP BY r.instrument_id, r.trade_date
),
v2_annual_profit AS (
    SELECT r.instrument_id AS instrument_id, r.trade_date AS trade_date,
           if(count() = 3 AND count(r.n_income_attr_p) = 3,
              sumIf(r.n_income_attr_p, r.n_income_attr_p > 0), {NULL_FLOAT}) AS positive_np_3y,
           {_lineage()}
    FROM v2_income_reports r INNER JOIN v2_fiscal f
      ON r.instrument_id = f.instrument_id AND r.trade_date = f.trade_date
    WHERE toMonth(r.report_period) = 12
      AND r.report_period BETWEEN addYears(f.last_annual, -2) AND f.last_annual
    GROUP BY r.instrument_id, r.trade_date
),
v2_halfyear_ranked AS (
    SELECT instrument_id, trade_date, report_period, depr_fa_coga_dpba,
           source_batch_id, source_record_hash,
           row_number() OVER (PARTITION BY instrument_id, trade_date ORDER BY report_period DESC) AS period_rank
    FROM v2_cashflow_reports WHERE toMonth(report_period) IN (6, 12)
),
v2_halfyear AS (
    SELECT r.instrument_id AS instrument_id, r.trade_date AS trade_date,
           if(toMonth(r.report_period) = 6, r.depr_fa_coga_dpba,
              r.depr_fa_coga_dpba - prev.depr_fa_coga_dpba) AS halfyear_depreciation,
           concat(r.source_batch_id, '|', prev.source_batch_id) AS source_batch_id,
           concat(r.source_record_hash, '|', prev.source_record_hash) AS source_record_hash
    FROM v2_halfyear_ranked r LEFT JOIN v2_cashflow_reports prev
      ON r.instrument_id = prev.instrument_id AND r.trade_date = prev.trade_date
     AND prev.report_period = addDays(toStartOfYear(r.report_period) + INTERVAL 6 MONTH, -1)
    WHERE r.period_rank = 1
)""")
    ctes.append(f"""v2_holder_reports AS (
    SELECT instrument_id, event_date, available_trade_date, holder_num, source_batch_id, source_record_hash
    FROM (
        SELECT instrument_id, event_date, available_trade_date, holder_num, source_batch_id, source_record_hash,
               row_number() OVER (PARTITION BY instrument_id, event_date, available_trade_date
                                  ORDER BY sys_from DESC, source_record_hash DESC) AS version_rank
        FROM {db}.dwd_stock_holder_number
        WHERE event_date = toLastDayOfMonth(event_date) AND toMonth(event_date) IN (3,6,9,12)
          AND ann_date >= event_date
    ) WHERE version_rank = 1
),
v2_holder_slots AS (
    SELECT instrument_id, trade_date, t, report_offset,
           addDays(addMonths(toStartOfQuarter(addDays(t, 1)), -3 * toInt32(report_offset)), -1) AS report_period
    FROM v2_days ARRAY JOIN range(2) AS report_offset
),
v2_holders AS (
    SELECT p.instrument_id AS instrument_id, p.trade_date AS trade_date,
           anyIf(if(r.holder_num > 0, r.holder_num, {NULL_INT}), p.report_offset = 0) AS holder_num_mrq_0,
           anyIf(if(r.holder_num > 0, r.holder_num, {NULL_INT}), p.report_offset = 1) AS holder_num_mrq_1,
           {_lineage()}
    FROM v2_holder_slots p ASOF LEFT JOIN v2_holder_reports r
      ON p.instrument_id = r.instrument_id AND p.report_period = r.event_date AND p.t >= r.available_trade_date
    GROUP BY p.instrument_id, p.trade_date
),
v2_northbound_reports AS (
    SELECT instrument_id, available_trade_date,
           state.1 AS vol, state.2 AS source_batch_id, state.3 AS source_record_hash
    FROM (
        SELECT instrument_id, available_trade_date,
               argMax(tuple(vol, source_batch_id, source_record_hash),
                      tuple(event_date, available_trade_date, sys_from, source_record_hash)) OVER (
                   PARTITION BY instrument_id ORDER BY available_trade_date
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
               ) AS state
    FROM (
        SELECT instrument_id, event_date, available_trade_date, sys_from, vol, source_batch_id, source_record_hash,
               row_number() OVER (PARTITION BY instrument_id, available_trade_date
                                  ORDER BY event_date DESC, sys_from DESC, source_record_hash DESC) AS version_rank
        FROM {db}.dwd_stock_northbound_holding
    ) WHERE version_rank = 1
    )
),
v2_northbound AS (
    SELECT p.instrument_id AS instrument_id, p.trade_date AS trade_date, r.vol AS northbound_hold_shares,
           r.source_batch_id, r.source_record_hash
    FROM v2_days p ASOF LEFT JOIN v2_northbound_reports r
      ON p.instrument_id = r.instrument_id AND p.t >= r.available_trade_date
)""")
    ctes.append(_render_daily_sources(db))
    ctes.append(_render_dividends(db))
    ctes.append(_render_research(db))
    return ",\n".join(ctes)


def _render_daily_sources(db: str) -> str:
    return f"""v2_benchmark AS (
    SELECT p.instrument_id AS instrument_id, p.trade_date AS trade_date,
           argMax(tuple(r.pct_chg / 100), tuple(r.available_trade_date, r.sys_from, r.source_record_hash)).1 AS bench_ret,
           {_lineage()}
    FROM v2_days p INNER JOIN {db}.dwd_index_eod_price r ON p.trade_date = r.event_date
    WHERE r.source_code = '000985.CSI' AND r.available_trade_date <= p.t
    GROUP BY p.instrument_id, p.trade_date
),
v2_limits AS (
    SELECT p.instrument_id AS instrument_id, p.trade_date AS trade_date,
           argMax(tuple(r.up_limit, r.down_limit), tuple(r.available_trade_date, r.sys_from, r.source_record_hash)) AS prices,
           {_lineage()}
    FROM v2_days p INNER JOIN {db}.dwd_stock_limit r
      ON p.instrument_id = r.instrument_id AND p.trade_date = r.event_date
    WHERE r.available_trade_date <= p.t GROUP BY p.instrument_id, p.trade_date
),
v2_list_dates AS (
    SELECT instrument_id, if(uniqExactIf(list_date, list_date > toDate32('1970-01-01')) = 1,
                            minIf(toNullable(list_date), list_date > toDate32('1970-01-01')),
                            CAST(NULL, 'Nullable(Date32)')) AS list_date,
           {_lineage("r")}
    FROM {db}.dwd_security_master r WHERE instrument_type = 'stock'
    GROUP BY instrument_id
),
v2_top_list AS (
    SELECT p.instrument_id AS instrument_id, p.trade_date AS trade_date, toNullable(toInt64(1)) AS top_list_flag,
           {_lineage()}
    FROM v2_days p INNER JOIN {db}.dwd_stock_top_list r
      ON p.instrument_id = r.instrument_id AND p.trade_date = r.event_date
    WHERE r.available_trade_date <= p.t GROUP BY p.instrument_id, p.trade_date
),
v2_industry AS (
    SELECT p.instrument_id AS instrument_id, p.trade_date AS trade_date,
           if(uniqExact(r.l1_code) = 1, any(toNullable(r.l1_code)), CAST(NULL, 'Nullable(String)')) AS sw_l1_code,
           {_lineage()}
    FROM v2_days p INNER JOIN {db}.dwd_sw_industry_member r ON p.instrument_id = concat('stock:', r.ts_code)
    WHERE r.available_date <= p.t AND p.t < r.end_date
    GROUP BY p.instrument_id, p.trade_date
),
v2_index_snapshots AS (
    SELECT DISTINCT event_date, available_trade_date, toUInt8(1) AS join_key
    FROM {db}.dwd_index_weight WHERE index_code = '000906.SH'
),
v2_index_dates AS (
    SELECT p.t AS t, max(r.event_date) AS snapshot_date
    FROM (SELECT DISTINCT t FROM v2_days) p CROSS JOIN v2_index_snapshots r
    WHERE r.available_trade_date <= p.t
    GROUP BY p.t
),
v2_csi800 AS (
    SELECT p.instrument_id AS instrument_id, p.trade_date AS trade_date,
           if(argMax(tuple(r.weight), tuple(r.available_trade_date, r.sys_from, r.source_record_hash)).1 > 0,
              toNullable(toInt64(1)), {NULL_INT}) AS csi800_member,
           {_lineage()}
    FROM v2_days p INNER JOIN v2_index_dates s ON p.t = s.t
    INNER JOIN {db}.dwd_index_weight r ON p.instrument_id = r.instrument_id AND s.snapshot_date = r.event_date
    WHERE r.index_code = '000906.SH' AND r.available_trade_date <= p.t
    GROUP BY p.instrument_id, p.trade_date
)"""


def _render_dividends(db: str) -> str:
    return f"""v2_dividend_events AS (
    SELECT instrument_id, trade_date, t, end_date, ex_date, div_proc, cash_div_tax, base_share,
           source_batch_id, source_record_hash
    FROM (
        SELECT p.instrument_id AS instrument_id, p.trade_date AS trade_date, p.t, r.end_date, r.ex_date, r.div_proc, r.cash_div_tax, r.base_share,
               r.source_batch_id, r.source_record_hash,
               row_number() OVER (
                   PARTITION BY p.instrument_id, p.trade_date, r.end_date, r.ex_date
                   ORDER BY r.available_trade_date DESC, r.sys_from DESC, r.source_record_hash DESC
               ) AS version_rank
        FROM v2_days p INNER JOIN {db}.dwd_stock_dividend r ON p.instrument_id = r.instrument_id
        WHERE r.available_trade_date <= p.t AND r.ex_date <= p.t
          AND r.ex_date > toDate32('1970-01-01')
          AND r.imp_ann_date > toDate32('1970-01-01') AND r.imp_ann_date < p.t
    ) WHERE version_rank = 1
),
v2_dividend_12m AS (
    SELECT r.instrument_id AS instrument_id, r.trade_date AS trade_date,
           if(countIf(r.cash_div_tax IS NULL OR r.base_share IS NULL OR r.base_share <= 0) = 0,
              sum(r.cash_div_tax * r.base_share * 10000), {NULL_FLOAT}) AS implemented_cash_dividend_12m_cny,
           {_lineage()}
    FROM v2_dividend_events r
    WHERE r.div_proc = '实施' AND (r.cash_div_tax > 0 OR r.cash_div_tax IS NULL)
      AND r.ex_date > subtractMonths(r.t, 12)
    GROUP BY r.instrument_id, r.trade_date
),
v2_retention AS (
    SELECT r.instrument_id AS instrument_id, r.trade_date AS trade_date,
           if(countIf(r.cash_div_tax IS NULL OR r.base_share IS NULL OR r.base_share <= 0) = 0
                  AND any(a.positive_np_3y) > 0,
              greatest(0., least(1., 1 - sum(r.cash_div_tax * r.base_share * 10000) / any(a.positive_np_3y))),
              {NULL_FLOAT}) AS retention_ratio,
           {_lineage()}
    FROM v2_dividend_events r INNER JOIN v2_fiscal f
      ON r.instrument_id = f.instrument_id AND r.trade_date = f.trade_date
    INNER JOIN v2_annual_profit a ON r.instrument_id = a.instrument_id AND r.trade_date = a.trade_date
    WHERE r.div_proc = '实施' AND (r.cash_div_tax > 0 OR r.cash_div_tax IS NULL)
      AND toYear(r.ex_date) BETWEEN toYear(f.last_annual)-2 AND toYear(f.last_annual)
    GROUP BY r.instrument_id, r.trade_date
)"""


def _render_research(db: str) -> str:
    return f"""v2_research_visible AS (
    SELECT instrument_id, trade_date, t, report_date, forecast_period_end, org_name,
           eps, np, min_price, max_price, available_trade_date, create_time, source_batch_id, source_record_hash
    FROM (
        SELECT p.instrument_id AS instrument_id, p.trade_date AS trade_date, p.t, r.report_date, r.forecast_period_end, r.org_name,
               r.eps, r.np, r.min_price, r.max_price, r.available_trade_date, r.create_time,
               r.source_batch_id, r.source_record_hash,
               row_number() OVER (
                   PARTITION BY p.instrument_id, p.trade_date, r.report_date, r.org_name,
                                r.report_title, r.author_name, r.quarter, r.report_type, r.classify
                   ORDER BY r.available_trade_date DESC, r.create_time DESC, r.sys_from DESC, r.source_record_hash DESC
               ) AS version_rank
        FROM v2_days p INNER JOIN {db}.dwd_stock_research_report r ON p.instrument_id = r.instrument_id
        WHERE r.available_trade_date <= p.t AND r.report_date <= p.t
          AND r.org_name IS NOT NULL AND trimBoth(r.org_name) != ''
    ) WHERE version_rank = 1
),
v2_org_forecasts AS (
    SELECT instrument_id, trade_date, t, org_name, forecast_year,
           report_date, np, eps, source_batch_id, source_record_hash
    FROM (
        SELECT instrument_id, trade_date, t, org_name, toYear(forecast_period_end) AS forecast_year,
               report_date, np, eps, source_batch_id, source_record_hash,
               row_number() OVER (
                   PARTITION BY instrument_id, trade_date, org_name, forecast_period_end
                   ORDER BY report_date DESC, available_trade_date DESC, create_time DESC, source_record_hash DESC
               ) AS org_rank
        FROM v2_research_visible
        WHERE toMonth(forecast_period_end) = 12 AND toDayOfMonth(forecast_period_end) = 31
    ) WHERE org_rank = 1
),
v2_year_forecasts AS (
    SELECT r.instrument_id AS instrument_id, r.trade_date AS trade_date, r.forecast_year,
           avgOrNullIf(r.np, isFinite(r.np)) * 10000 AS np_mean,
           {_lineage()}
    FROM v2_org_forecasts r GROUP BY r.instrument_id, r.trade_date, r.forecast_year
),
v2_active_forecasts AS (
    SELECT r.instrument_id AS instrument_id, r.trade_date AS trade_date,
           if(countIf(r.forecast_year = f.active_year AND r.report_date > subtractDays(r.t,180) AND isFinite(r.np)) >= 3,
              avgOrNullIf(r.np, r.forecast_year = f.active_year AND r.report_date > subtractDays(r.t,180) AND isFinite(r.np)) * 10000,
              {NULL_FLOAT}) AS analyst_np_mean_active_180d_cny,
           avgOrNullIf(r.eps, r.forecast_year = f.active_year AND r.report_date > subtractDays(r.t,90) AND isFinite(r.eps)) AS analyst_eps_mean_active_90d,
           if(countIf(r.forecast_year = toYear(r.t) AND r.report_date > subtractDays(r.t,90) AND isFinite(r.eps)) >= 5
                  AND abs(avgOrNullIf(r.eps, r.forecast_year = toYear(r.t) AND r.report_date > subtractDays(r.t,90) AND isFinite(r.eps))) >= 0.05,
              stddevSampIf(r.eps, r.forecast_year = toYear(r.t) AND r.report_date > subtractDays(r.t,90) AND isFinite(r.eps)) /
                  abs(avgOrNullIf(r.eps, r.forecast_year = toYear(r.t) AND r.report_date > subtractDays(r.t,90) AND isFinite(r.eps))),
              {NULL_FLOAT}) AS analyst_eps_dispersion_active_90d,
           if(countIf(r.forecast_year = toYear(r.t) AND r.report_date > subtractDays(r.t,91) AND isFinite(r.eps)) >= 5
                  AND abs(avgOrNullIf(r.eps, r.forecast_year = toYear(r.t) AND r.report_date > subtractDays(r.t,91) AND isFinite(r.eps))) >= 0.05,
              stddevSampIf(r.eps, r.forecast_year = toYear(r.t) AND r.report_date > subtractDays(r.t,91) AND isFinite(r.eps)) /
                  abs(avgOrNullIf(r.eps, r.forecast_year = toYear(r.t) AND r.report_date > subtractDays(r.t,91) AND isFinite(r.eps))),
              {NULL_FLOAT}) AS analyst_eps_dispersion_active_91d,
           {_lineage()}
    FROM v2_org_forecasts r LEFT JOIN v2_fiscal f
      ON r.instrument_id = f.instrument_id AND r.trade_date = f.trade_date
    GROUP BY r.instrument_id, r.trade_date
),
v2_research_counts AS (
    SELECT r.instrument_id AS instrument_id, r.trade_date AS trade_date,
           toNullable(toInt64(uniqExact(r.org_name))) AS analyst_org_coverage_90d,
           toNullable(toInt64(uniqExactIf(tuple(r.org_name, toYear(r.forecast_period_end)),
                     r.forecast_period_end IS NOT NULL AND (r.np IS NOT NULL OR r.eps IS NOT NULL)))) AS analyst_org_year_pair_count_90d,
           {_lineage()}
    FROM v2_research_visible r WHERE r.report_date > subtractDays(r.t,90)
    GROUP BY r.instrument_id, r.trade_date
),
v2_target_orgs AS (
    SELECT instrument_id, trade_date, org_name,
           argMax((min_price+max_price)/2, tuple(report_date, available_trade_date, create_time, source_record_hash)) AS target_price
    FROM v2_research_visible
    WHERE report_date > subtractDays(t,90) AND 0 < min_price AND min_price <= max_price
      AND isFinite(min_price) AND isFinite(max_price)
    GROUP BY instrument_id, trade_date, org_name
),
v2_target_prices AS (
    SELECT instrument_id, trade_date, avgOrNull(target_price) AS analyst_target_price_mean_90d
    FROM v2_target_orgs GROUP BY instrument_id, trade_date
),
v2_book_years AS (
    SELECT b.instrument_id AS instrument_id, b.trade_date AS trade_date, b.book_value,
           toUInt16(toYear(b.book_period) + year_offset) AS forecast_year,
           dateDiff('day', greatest(addDays(b.book_period,1), toDate32(concat(toString(toYear(b.book_period)+year_offset),'-01-01'))),
                          toDate32(concat(toString(toYear(b.book_period)+year_offset+1),'-01-01'))) /
           dateDiff('day', toDate32(concat(toString(toYear(b.book_period)+year_offset),'-01-01')),
                          toDate32(concat(toString(toYear(b.book_period)+year_offset+1),'-01-01'))) AS year_weight
    FROM v2_book b INNER JOIN v2_fiscal f ON b.instrument_id = f.instrument_id AND b.trade_date = f.trade_date
    ARRAY JOIN range(toUInt32(greatest(0, toInt32(f.fy0)+2-toInt32(toYear(b.book_period))))) AS year_offset
),
v2_book_forecast AS (
    SELECT b.instrument_id AS instrument_id, b.trade_date AS trade_date,
           if(countIf(b.year_weight > 0 AND y.np_mean IS NULL) = 0,
              any(b.book_value) + any(r.retention_ratio) * sumIf(y.np_mean * b.year_weight, b.year_weight > 0),
              {NULL_FLOAT}) AS analyst_bv_consensus_fy1,
           {_lineage("y")}
    FROM v2_book_years b LEFT JOIN v2_year_forecasts y
      ON b.instrument_id = y.instrument_id AND b.trade_date = y.trade_date AND b.forecast_year = y.forecast_year
    LEFT JOIN v2_retention r ON b.instrument_id = r.instrument_id AND b.trade_date = r.trade_date
    GROUP BY b.instrument_id, b.trade_date
)"""


# Every joined CTE is unique on (instrument_id, trade_date), except list_dates
# which is unique by instrument. This prevents fan-out of the stock-day panel.
JOINED = {
    "v2_benchmark": "bm",
    "v2_limits": "lim",
    "v2_list_dates": "listing",
    "v2_top_list": "top",
    "v2_industry": "sw",
    "v2_csi800": "idx",
    "v2_holders": "holders",
    "v2_northbound": "nb",
    "v2_halfyear": "hy",
    "v2_dividend_12m": "div12",
    "v2_active_forecasts": "active",
    "v2_research_counts": "coverage",
    "v2_target_prices": "target",
    "v2_fiscal": "fiscal",
    "v2_book": "book",
    "v2_annual_profit": "annual",
    "v2_retention": "retention",
    "v2_book_forecast": "bv",
}
NO_LINEAGE = {"target"}


def render_joins() -> str:
    result = []
    for cte, alias in JOINED.items():
        condition = f"price.instrument_id = {alias}.instrument_id"
        if alias != "listing":
            condition += f" AND price.trade_date = {alias}.trade_date"
        result.append(f"LEFT JOIN {cte} {alias} ON {condition}")
    for offset in range(4):
        result.append(
            f"LEFT JOIN v2_year_forecasts fy{offset} ON price.instrument_id = fy{offset}.instrument_id "
            f"AND price.trade_date = fy{offset}.trade_date AND fy{offset}.forecast_year = fiscal.fy0 + {offset}"
        )
    for offset, alias in [(0, "cy"), (1, "ny")]:
        result.append(
            f"LEFT JOIN v2_year_forecasts {alias} ON price.instrument_id = {alias}.instrument_id "
            f"AND price.trade_date = {alias}.trade_date AND {alias}.forecast_year = toYear(price.available_trade_date) + {offset}"
        )
    return "\n".join(result)


def supplemental_expressions() -> dict[str, str]:
    expressions = {
        "bench_ret": "bm.bench_ret",
        "up_limit": "lim.prices.1",
        "down_limit": "lim.prices.2",
        "list_date": "if(listing.list_date <= price.trade_date, listing.list_date, CAST(NULL, 'Nullable(Date32)'))",
        "top_list_flag": "top.top_list_flag",
        "sw_l1_code": "sw.sw_l1_code",
        "csi800_member": "idx.csi800_member",
        "holder_num_mrq_0": "holders.holder_num_mrq_0",
        "holder_num_mrq_1": "holders.holder_num_mrq_1",
        "northbound_hold_shares": "nb.northbound_hold_shares",
        "halfyear_depreciation": "hy.halfyear_depreciation",
        "implemented_cash_dividend_12m_cny": "div12.implemented_cash_dividend_12m_cny",
        "analyst_np_consensus_fy0": "if(fiscal.fy0_actual, fiscal.latest_np, fy0.np_mean)",
        "analyst_bv_consensus_fy1": "bv.analyst_bv_consensus_fy1",
        "analyst_target_price_mean_90d": "target.analyst_target_price_mean_90d",
    }
    for i in range(1, 4):
        expressions[f"analyst_np_consensus_fy{i}"] = f"fy{i}.np_mean"
    w = "dateDiff('day', toStartOfYear(price.available_trade_date), price.available_trade_date) / dateDiff('day', toStartOfYear(price.available_trade_date), addYears(toStartOfYear(price.available_trade_date),1))"
    ntm = f"((1-({w}))*cy.np_mean + ({w})*ny.np_mean)"
    expressions["analyst_forward_pe_12m"] = f"if({ntm} > 0, price.total_mv * 10000 / {ntm}, {NULL_FLOAT})"
    for name in [
        "analyst_np_mean_active_180d_cny",
        "analyst_eps_mean_active_90d",
        "analyst_eps_dispersion_active_90d",
        "analyst_eps_dispersion_active_91d",
    ]:
        expressions[name] = "active." + name
    for name in ["analyst_org_coverage_90d", "analyst_org_year_pair_count_90d"]:
        expressions[name] = "coverage." + name
    for item in SUPPLEMENTAL_SPECS:
        if item["status"] == "placeholder":
            typ = {"str": "String", "int": "Int64", "float": "Float64"}[item["data_type"]]
            expressions[item["name"]] = f"CAST(NULL, 'Nullable({typ})')"
    return expressions


def calculated_expressions() -> dict[str, str]:
    return {f"diluted_weighted_share_mrq_{i}": f"total_share_mrq_{i}" for i in (0, 4)}


def lineage_concat(column: str) -> str:
    aliases = [alias for alias in JOINED.values() if alias not in NO_LINEAGE] + ["fy0", "fy1", "fy2", "fy3", "cy", "ny"]
    return "".join(f", '|', ifNull({alias}.{column}, '')" for alias in aliases)


def render_features_cte(db: str) -> str:
    """Resolve the small supplemental panel before joining the 1,782 financial
    columns. Keeping these join trees separate bounds analyzer/optimizer work.
    """
    selects = ",\n        ".join(f"{expr} AS `{name}`" for name, expr in supplemental_expressions().items())
    return f"""v2_extension_mv AS (
    SELECT instrument_id, event_date, available_trade_date,
           argMax(tuple(total_mv), tuple(sys_from, source_record_hash)).1 AS total_mv
    FROM {db}.dwd_stock_daily_basic
    GROUP BY instrument_id, event_date, available_trade_date
),
v2_extra_features AS (
    SELECT price.instrument_id AS instrument_id, price.trade_date AS trade_date,
           {selects},
           concat(''{lineage_concat("source_batch_id")}) AS source_batch_id,
           hex(MD5(concat(''{lineage_concat("source_record_hash")}))) AS source_record_hash
    FROM (
        SELECT p.instrument_id AS instrument_id, p.trade_date AS trade_date,
               p.t AS available_trade_date, mv.total_mv AS total_mv
        FROM v2_days p ASOF LEFT JOIN v2_extension_mv mv
          ON p.instrument_id = mv.instrument_id AND p.trade_date = mv.event_date AND p.t >= mv.available_trade_date
    ) price
    {render_joins()}
)"""
