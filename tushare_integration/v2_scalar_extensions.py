"""Explicit, source-separated additions to the Tushare v2 scalar contract.

The manifest also records exclusions and unavailable inputs. In particular an
unknown source coverage is never evidence of zero holdings/events/coverage.
"""

from __future__ import annotations

import json
from pathlib import Path


MANIFEST = json.loads((Path(__file__).parent / "schema/dws/v2_scalar_extensions.json").read_text(encoding="utf-8"))
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


def _lineage(alias: str = "r", condition: str | None = None) -> str:
    aggregate = "groupUniqArrayIf" if condition else "groupUniqArray"
    predicate = f", {condition}" if condition else ""
    return (
        f"arrayStringConcat(arraySort({aggregate}({alias}.source_batch_id{predicate})), '|') AS source_batch_id, "
        f"hex(MD5(arrayStringConcat(arraySort({aggregate}({alias}.source_record_hash{predicate})), '|'))) AS source_record_hash"
    )


def _financial_versions(db: str, table: str, name: str, field: str, months: str = "3,6,9,12") -> str:
    """Canonical disclosure versions; ASOF supplies the daily visibility bound.

    Keeping NULL inside the selected row is essential: a correction containing
    NULL must not resurrect an older value.
    """
    return f"""{name}_versions AS (
    SELECT instrument_id, event_date AS report_period, available_trade_date,
           {field}, source_batch_id, source_record_hash, toUInt8(1) AS report_exists
    FROM (
        SELECT r.instrument_id, r.event_date, r.available_trade_date,
               r.{field}, r.source_batch_id, r.source_record_hash, row_number() OVER (
            PARTITION BY instrument_id, event_date, available_trade_date
            ORDER BY (report_type = '4') DESC, f_ann_date DESC,
                     update_flag DESC, sys_from DESC, source_record_hash DESC
        ) AS version_rank
        FROM {db}.{table} r
        WHERE sys_to = {CURRENT} AND report_type IN ('1','4') AND ann_date >= event_date
          AND event_date >= toDate32('2010-01-01')
          AND event_date = toLastDayOfMonth(event_date) AND toMonth(event_date) IN ({months})
    ) WHERE version_rank = 1
)"""


def _period_states(name: str, output: str, condition: str = "1") -> str:
    return f"""{output} AS (
    SELECT instrument_id, available_trade_date,
           max(grouped_period) OVER (
               PARTITION BY instrument_id ORDER BY available_trade_date
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ) AS latest_period
    FROM (
        SELECT instrument_id, available_trade_date, max(report_period) AS grouped_period
        FROM {name}_versions WHERE {condition}
        GROUP BY instrument_id, available_trade_date
    )
)"""


def _render_financial_panels(db: str) -> str:
    sources = [
        _financial_versions(db, "dwd_stock_income", "v2_income", "n_income_attr_p"),
        _financial_versions(db, "dwd_stock_balance_sheet", "v2_balance", "total_hldr_eqy_exc_min_int"),
        _financial_versions(db, "dwd_stock_cashflow", "v2_cashflow", "depr_fa_coga_dpba", "6,12"),
        _period_states("v2_income", "v2_income_period_states"),
        _period_states("v2_income", "v2_annual_period_states", "toMonth(report_period)=12"),
        _period_states("v2_balance", "v2_balance_period_states"),
        _period_states("v2_cashflow", "v2_halfyear_period_states"),
    ]
    sources.append(f"""v2_income_latest_states AS (
    SELECT s.instrument_id AS instrument_id,s.available_trade_date AS available_trade_date,
           r.report_period AS report_period,r.n_income_attr_p AS n_income_attr_p,
           r.source_batch_id AS source_batch_id,r.source_record_hash AS source_record_hash
    FROM v2_income_period_states s ASOF LEFT JOIN v2_income_versions r
      ON s.instrument_id=r.instrument_id AND s.latest_period=r.report_period
     AND s.available_trade_date>=r.available_trade_date
    WHERE r.report_exists=1
),
v2_fiscal_states AS (
    SELECT p.instrument_id AS instrument_id,p.available_trade_date AS available_trade_date,
           toUInt8(1) AS has_fiscal,p.report_period AS latest_report_period,
           toYear(p.report_period) AS fy0,
           if(a.report_exists=1,toNullable(a.report_period),CAST(NULL,'Nullable(Date32)')) AS last_annual,
           p.n_income_attr_p AS latest_np,toMonth(p.report_period)=12 AS fy0_actual,
           concat(p.source_batch_id,'|',a.source_batch_id) AS source_batch_id,
           hex(MD5(concat(p.source_record_hash,'|',a.source_record_hash))) AS source_record_hash
    FROM v2_income_latest_states p ASOF LEFT JOIN v2_annual_period_states s
      ON p.instrument_id=s.instrument_id AND p.available_trade_date>=s.available_trade_date
    ASOF LEFT JOIN v2_income_versions a
      ON p.instrument_id=a.instrument_id AND s.latest_period=a.report_period
     AND p.available_trade_date>=a.available_trade_date
),
v2_fiscal AS (
    SELECT p.instrument_id AS instrument_id,p.trade_date AS trade_date,p.t AS t,
           f.has_fiscal AS has_fiscal,f.latest_report_period AS latest_report_period,
           f.fy0 AS fy0,f.last_annual AS last_annual,f.latest_np AS latest_np,f.fy0_actual AS fy0_actual,
           if(prev.report_exists=1,toInt32(toYear(p.t)),toInt32(toYear(p.t))-1) AS active_year,
           concat(f.source_batch_id,'|',prev.source_batch_id) AS source_batch_id,
           hex(MD5(concat(f.source_record_hash,'|',prev.source_record_hash))) AS source_record_hash
    FROM v2_days p ASOF LEFT JOIN v2_fiscal_states f
      ON p.instrument_id=f.instrument_id AND p.t>=f.available_trade_date
    ASOF LEFT JOIN v2_income_versions prev
      ON p.instrument_id=prev.instrument_id
     AND prev.report_period=toDate32(concat(toString(toYear(p.t)-1),'-12-31'))
     AND p.t>=prev.available_trade_date
    WHERE f.has_fiscal=1
),
v2_annual_profit_states AS (
    SELECT r.instrument_id AS instrument_id,r.available_trade_date AS available_trade_date,
           if(count()=3 AND count(a.n_income_attr_p)=3,
              sumIf(a.n_income_attr_p,a.n_income_attr_p>0),{NULL_FLOAT}) AS positive_np_3y,
           toUInt8(1) AS has_annual_profit,
           {_lineage("a")}
    FROM (
        SELECT instrument_id,available_trade_date,last_annual,
               addYears(assumeNotNull(last_annual),-toInt32(i)) AS report_period
        FROM v2_fiscal_states ARRAY JOIN range(3) AS i
        WHERE last_annual IS NOT NULL
    ) r ASOF LEFT JOIN v2_income_versions a
      ON r.instrument_id=a.instrument_id AND r.report_period=a.report_period
     AND r.available_trade_date>=a.available_trade_date
    WHERE a.report_exists=1
    GROUP BY r.instrument_id,r.available_trade_date
),
v2_annual_profit AS (
    SELECT p.instrument_id AS instrument_id,p.trade_date AS trade_date,
           a.positive_np_3y AS positive_np_3y,a.source_batch_id AS source_batch_id,
           a.source_record_hash AS source_record_hash
    FROM v2_days p ASOF LEFT JOIN v2_annual_profit_states a
      ON p.instrument_id=a.instrument_id AND p.t>=a.available_trade_date
    WHERE a.has_annual_profit=1
),
v2_book_states AS (
    SELECT s.instrument_id AS instrument_id,s.available_trade_date AS available_trade_date,
           toUInt8(1) AS has_book,r.report_period AS book_period,
           r.total_hldr_eqy_exc_min_int AS book_value,
           r.source_batch_id AS source_batch_id,r.source_record_hash AS source_record_hash
    FROM v2_balance_period_states s ASOF LEFT JOIN v2_balance_versions r
      ON s.instrument_id=r.instrument_id AND s.latest_period=r.report_period
     AND s.available_trade_date>=r.available_trade_date
    WHERE r.report_exists=1
),
v2_book AS (
    SELECT p.instrument_id AS instrument_id,p.trade_date AS trade_date,
           b.has_book AS has_book,b.book_period AS book_period,b.book_value AS book_value,
           b.source_batch_id AS source_batch_id,b.source_record_hash AS source_record_hash
    FROM v2_days p ASOF LEFT JOIN v2_book_states b
      ON p.instrument_id=b.instrument_id AND p.t>=b.available_trade_date
    WHERE b.has_book=1
),
v2_halfyear_states AS (
    SELECT s.instrument_id AS instrument_id,s.available_trade_date AS available_trade_date,
           if(toMonth(r.report_period)=6,r.depr_fa_coga_dpba,
              r.depr_fa_coga_dpba-prev.depr_fa_coga_dpba) AS halfyear_depreciation,
           toUInt8(1) AS has_halfyear,
           concat(r.source_batch_id,'|',prev.source_batch_id) AS source_batch_id,
           concat(r.source_record_hash,'|',prev.source_record_hash) AS source_record_hash
    FROM v2_halfyear_period_states s ASOF LEFT JOIN v2_cashflow_versions r
      ON s.instrument_id=r.instrument_id AND s.latest_period=r.report_period
     AND s.available_trade_date>=r.available_trade_date
    ASOF LEFT JOIN v2_cashflow_versions prev
      ON s.instrument_id=prev.instrument_id
     AND prev.report_period=addDays(toStartOfYear(r.report_period)+INTERVAL 6 MONTH,-1)
     AND s.available_trade_date>=prev.available_trade_date
    WHERE r.report_exists=1
),
v2_halfyear AS (
    SELECT p.instrument_id AS instrument_id,p.trade_date AS trade_date,
           h.halfyear_depreciation AS halfyear_depreciation,
           h.source_batch_id AS source_batch_id,h.source_record_hash AS source_record_hash
    FROM v2_days p ASOF LEFT JOIN v2_halfyear_states h
      ON p.instrument_id=h.instrument_id AND p.t>=h.available_trade_date
    WHERE h.has_halfyear=1
)""")
    return ",\n".join(sources)


def render_ctes(db: str) -> str:
    """Daily visibility t is the existing v2 available_trade_date (T+1 panel)."""
    ctes = [
        f"""v2_days AS (
    SELECT DISTINCT instrument_id, event_date AS trade_date, available_trade_date AS t
    FROM {db}.dwd_stock_eod_price
    WHERE sys_to = {CURRENT} AND event_date >= toDate32('2010-01-01')
)"""
    ]
    ctes.append(_render_financial_panels(db))
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
    SELECT p.t AS t, r.snapshot_date
    FROM (SELECT DISTINCT t,toUInt8(1) AS join_key FROM v2_days) p
    ASOF LEFT JOIN (
        SELECT toUInt8(1) AS join_key, available_trade_date,
               max(event_date) OVER (ORDER BY available_trade_date
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS snapshot_date,
               toUInt8(1) AS snapshot_exists
        FROM (SELECT available_trade_date,max(event_date) AS event_date
              FROM v2_index_snapshots GROUP BY available_trade_date)
    ) r ON p.join_key=r.join_key AND p.t>=r.available_trade_date
    WHERE r.snapshot_exists=1
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
    return f"""v2_dividend_year_slots AS (
    SELECT p.instrument_id AS instrument_id,p.trade_date AS trade_date,p.t AS t,f.last_annual,ex_year
    FROM v2_days p ASOF LEFT JOIN v2_fiscal_states f
      ON p.instrument_id=f.instrument_id AND p.t>=f.available_trade_date
    ARRAY JOIN arrayDistinct(arrayConcat(
        [toInt32(toYear(subtractMonths(p.t,12))),toInt32(toYear(p.t))],
        if(f.has_fiscal=1 AND isNotNull(f.last_annual),
           arrayMap(i -> toInt32(toYear(assumeNotNull(f.last_annual)))-toInt32(i),range(3)),
           CAST([], 'Array(Int32)'))
    )) AS ex_year
),
v2_dividend_events AS (
    SELECT instrument_id, trade_date, t, end_date, ex_date, div_proc, cash_div_tax, base_share,
           source_batch_id, source_record_hash
    FROM (
        SELECT p.instrument_id AS instrument_id, p.trade_date AS trade_date, p.t AS t, r.end_date, r.ex_date, r.div_proc, r.cash_div_tax, r.base_share,
               r.source_batch_id, r.source_record_hash,
               row_number() OVER (
                   PARTITION BY p.instrument_id, p.trade_date, r.end_date, r.ex_date
                   ORDER BY r.available_trade_date DESC, r.sys_from DESC, r.source_record_hash DESC
               ) AS version_rank
        FROM v2_dividend_year_slots p INNER JOIN {db}.dwd_stock_dividend r
          ON p.instrument_id=r.instrument_id AND p.ex_year=toInt32(toYear(r.ex_date))
        WHERE r.available_trade_date <= p.t AND r.ex_date <= p.t
          AND r.ex_date > toDate32('1970-01-01')
          AND r.imp_ann_date > toDate32('1970-01-01') AND r.imp_ann_date < p.t
          AND (r.ex_date>subtractMonths(p.t,12)
               OR toYear(r.ex_date) BETWEEN toYear(p.last_annual)-2 AND toYear(p.last_annual))
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
    FROM v2_dividend_events r ASOF LEFT JOIN v2_fiscal_states f
      ON r.instrument_id=f.instrument_id AND r.t>=f.available_trade_date
    ASOF LEFT JOIN v2_annual_profit_states a
      ON r.instrument_id=a.instrument_id AND r.t>=a.available_trade_date
    WHERE r.div_proc = '实施' AND (r.cash_div_tax > 0 OR r.cash_div_tax IS NULL)
      AND toYear(r.ex_date) BETWEEN toYear(f.last_annual)-2 AND toYear(f.last_annual)
    GROUP BY r.instrument_id, r.trade_date
)"""


def _render_research(db: str) -> str:
    return f"""v2_research_versions AS (
    SELECT instrument_id,report_date,org_name,report_title,author_name,quarter,report_type,classify,
           available_trade_date,create_time,sys_from,forecast_period_end,np,eps,min_price,max_price,
           source_batch_id,source_record_hash FROM (
        SELECT instrument_id,report_date,org_name,report_title,author_name,quarter,report_type,classify,
               available_trade_date,create_time,sys_from,forecast_period_end,np,eps,min_price,max_price,
               source_batch_id,source_record_hash,row_number() OVER (
            PARTITION BY instrument_id,report_date,org_name,report_title,author_name,
                         quarter,report_type,classify,available_trade_date
            ORDER BY create_time DESC,sys_from DESC,source_record_hash DESC
        ) AS source_version_rank
        FROM {db}.dwd_stock_research_report r
        WHERE org_name IS NOT NULL AND trimBoth(org_name)!=''
    ) WHERE source_version_rank=1
),
v2_research_months AS (
    SELECT instrument_id,trade_date,t,
           toUInt32(toYear(subtractDays(t,89))*12+toMonth(subtractDays(t,89))+month_offset) AS report_month
    FROM v2_days
    ARRAY JOIN range(toUInt32(dateDiff('month',subtractDays(t,89),t)+1)) AS month_offset
),
v2_research_visible AS (
    SELECT instrument_id, trade_date, t, report_date, forecast_period_end, org_name,
           eps, np, min_price, max_price, available_trade_date, create_time, source_batch_id, source_record_hash
    FROM (
        SELECT p.instrument_id AS instrument_id, p.trade_date AS trade_date, p.t AS t, r.report_date, r.forecast_period_end, r.org_name,
               r.eps, r.np, r.min_price, r.max_price, r.available_trade_date, r.create_time,
               r.source_batch_id, r.source_record_hash,
               row_number() OVER (
                   PARTITION BY p.instrument_id, p.trade_date, r.report_date, r.org_name,
                                r.report_title, r.author_name, r.quarter, r.report_type, r.classify
                   ORDER BY r.available_trade_date DESC, r.create_time DESC, r.sys_from DESC, r.source_record_hash DESC
               ) AS version_rank
        FROM v2_research_months p INNER JOIN v2_research_versions r
          ON p.instrument_id=r.instrument_id
         AND p.report_month=toUInt32(toYear(r.report_date)*12+toMonth(r.report_date))
        WHERE r.available_trade_date <= p.t AND r.report_date <= p.t
          AND r.report_date>subtractDays(p.t,90)
    ) WHERE version_rank = 1
),
v2_org_updates AS (
    SELECT instrument_id,org_name,toYear(forecast_period_end) AS forecast_year,
           greatest(available_trade_date,report_date) AS visible_date,
           argMax(tuple(np,eps,report_date,source_batch_id,source_record_hash),
                  tuple(report_date,available_trade_date,create_time,source_record_hash)) AS value,
           max(tuple(report_date,available_trade_date,create_time,source_record_hash)) AS selection_key
    FROM v2_research_versions
    WHERE toMonth(forecast_period_end)=12 AND toDayOfMonth(forecast_period_end)=31
    GROUP BY instrument_id,org_name,forecast_year,visible_date
),
v2_org_states AS (
    SELECT instrument_id,org_name,forecast_year,visible_date,toUInt8(1) AS forecast_exists,
           argMax(value,selection_key) OVER (
               PARTITION BY instrument_id,org_name,forecast_year ORDER BY visible_date
               ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
           ) AS state
    FROM v2_org_updates
),
v2_forecast_year_slots AS (
    SELECT p.instrument_id AS instrument_id,p.trade_date AS trade_date,p.t AS t,
           if(prev.report_exists=1,toInt32(toYear(p.t)),toInt32(toYear(p.t))-1) AS active_year,forecast_year,
           (f.has_fiscal=1 AND forecast_year BETWEEN f.fy0 AND f.fy0+3)
             OR forecast_year BETWEEN toYear(p.t) AND toYear(p.t)+1
             OR (f.has_fiscal=1 AND b.has_book=1
                 AND forecast_year BETWEEN toYear(addDays(b.book_period,1)) AND f.fy0+1) AS long_horizon_needed
    FROM v2_days p ASOF LEFT JOIN v2_fiscal_states f
      ON p.instrument_id=f.instrument_id AND p.t>=f.available_trade_date
    ASOF LEFT JOIN v2_book_states b ON p.instrument_id=b.instrument_id AND p.t>=b.available_trade_date
    ASOF LEFT JOIN v2_income_versions prev ON p.instrument_id=prev.instrument_id
      AND prev.report_period=toDate32(concat(toString(toYear(p.t)-1),'-12-31')) AND p.t>=prev.available_trade_date
    ARRAY JOIN arrayDistinct(arrayConcat(
        [toInt32(toYear(p.t)),toInt32(toYear(p.t))+1],
        if(f.has_fiscal=1,arrayConcat(arrayMap(i -> toInt32(f.fy0)+toInt32(i),range(4)),[if(prev.report_exists=1,toInt32(toYear(p.t)),toInt32(toYear(p.t))-1)]),CAST([],'Array(Int32)')),
        if(f.has_fiscal=1 AND b.has_book=1,
           arrayMap(i -> toInt32(toYear(addDays(b.book_period,1)))+toInt32(i),
                    range(toUInt32(greatest(0,toInt32(f.fy0)+2-toInt32(toYear(addDays(b.book_period,1))))))),
           CAST([],'Array(Int32)'))
    )) AS forecast_year
),
v2_org_forecasts AS (
    SELECT p.instrument_id AS instrument_id,p.trade_date AS trade_date,p.t AS t,
           o.org_name AS org_name,p.forecast_year AS forecast_year,
           p.active_year AS active_year,p.long_horizon_needed AS long_horizon_needed,
           r.state.1 AS np,r.state.2 AS eps,r.state.3 AS report_date,
           r.state.4 AS source_batch_id,r.state.5 AS source_record_hash
    FROM v2_forecast_year_slots p INNER JOIN (
        SELECT DISTINCT instrument_id,org_name,forecast_year FROM v2_org_updates
    ) o ON p.instrument_id=o.instrument_id AND p.forecast_year=o.forecast_year
    ASOF LEFT JOIN v2_org_states r
      ON p.instrument_id=r.instrument_id AND p.forecast_year=r.forecast_year
     AND o.org_name=r.org_name AND p.t>=r.visible_date
    WHERE r.forecast_exists=1 AND (
        p.long_horizon_needed
        OR (p.forecast_year=p.active_year AND r.state.3>subtractDays(p.t,180))
        OR (p.forecast_year=toYear(p.t) AND r.state.3>subtractDays(p.t,91))
    )
),
v2_year_forecasts AS (
    SELECT r.instrument_id AS instrument_id, r.trade_date AS trade_date, r.forecast_year,
           avgOrNullIf(r.np, isFinite(r.np)) * 10000 AS np_mean,
           {_lineage()}
    FROM v2_org_forecasts r WHERE r.long_horizon_needed
    GROUP BY r.instrument_id, r.trade_date, r.forecast_year
),
v2_active_forecasts AS (
    SELECT r.instrument_id AS instrument_id, r.trade_date AS trade_date,
           if(countIf(r.forecast_year = r.active_year AND r.report_date > subtractDays(r.t,180) AND isFinite(r.np)) >= 3,
              avgOrNullIf(r.np, r.forecast_year = r.active_year AND r.report_date > subtractDays(r.t,180) AND isFinite(r.np)) * 10000,
              {NULL_FLOAT}) AS analyst_np_mean_active_180d_cny,
           avgOrNullIf(r.eps, r.forecast_year = r.active_year AND r.report_date > subtractDays(r.t,90) AND isFinite(r.eps)) AS analyst_eps_mean_active_90d,
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
    FROM v2_org_forecasts r
    WHERE (r.forecast_year=r.active_year AND r.report_date>subtractDays(r.t,180))
       OR (r.forecast_year=toYear(r.t) AND r.report_date>subtractDays(r.t,91))
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
           argMax(tuple((min_price+max_price)/2,source_batch_id,source_record_hash),
                  tuple(report_date,available_trade_date,create_time,source_record_hash)) AS selected
    FROM v2_research_visible
    WHERE report_date > subtractDays(t,90) AND 0 < min_price AND min_price <= max_price
      AND isFinite(min_price) AND isFinite(max_price)
    GROUP BY instrument_id, trade_date, org_name
),
v2_target_prices AS (
    SELECT instrument_id, trade_date, avgOrNull(r.target_price) AS analyst_target_price_mean_90d,
           {_lineage()}
    FROM (SELECT instrument_id,trade_date,selected.1 AS target_price,
                 selected.2 AS source_batch_id,selected.3 AS source_record_hash FROM v2_target_orgs) r
    GROUP BY instrument_id, trade_date
),
v2_book_years AS (
    SELECT p.instrument_id AS instrument_id, p.trade_date AS trade_date, b.book_value AS book_value,
           toUInt16(toYear(b.book_period) + year_offset) AS forecast_year,
           dateDiff('day', greatest(addDays(b.book_period,1), toDate32(concat(toString(toYear(b.book_period)+year_offset),'-01-01'))),
                          toDate32(concat(toString(toYear(b.book_period)+year_offset+1),'-01-01'))) /
           dateDiff('day', toDate32(concat(toString(toYear(b.book_period)+year_offset),'-01-01')),
                          toDate32(concat(toString(toYear(b.book_period)+year_offset+1),'-01-01'))) AS year_weight
    FROM v2_days p ASOF LEFT JOIN v2_book_states b ON p.instrument_id=b.instrument_id AND p.t>=b.available_trade_date
    ASOF LEFT JOIN v2_fiscal_states f ON p.instrument_id=f.instrument_id AND p.t>=f.available_trade_date
    ARRAY JOIN range(toUInt32(if(b.has_book=1 AND f.has_fiscal=1,
        greatest(0,toInt32(f.fy0)+2-toInt32(toYear(b.book_period))),0))) AS year_offset
    WHERE b.has_book=1 AND f.has_fiscal=1
),
v2_book_forecast AS (
    SELECT b.instrument_id AS instrument_id, b.trade_date AS trade_date,
           if(countIf(b.year_weight > 0 AND y.np_mean IS NULL) = 0,
              any(b.book_value) + any(r.retention_ratio) * sumIf(y.np_mean * b.year_weight, b.year_weight > 0),
              {NULL_FLOAT}) AS analyst_bv_consensus_fy1,
           {_lineage("y", "b.year_weight > 0")}
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
NO_LINEAGE: set[str] = set()


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
    """Resolve the small supplemental panel before joining the financial
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
