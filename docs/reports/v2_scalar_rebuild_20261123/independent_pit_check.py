"""Independent Python recomputation from real DWD records, without v2 SQL helpers."""

import argparse
import bisect
import calendar
import datetime as dt
import json
import math
from collections import defaultdict, Counter
from pathlib import Path
import clickhouse_connect
from tushare_integration.dws import DWSManager

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--latest-tax-only", action="store_true")
args = parser.parse_args()
s = DWSManager().settings.database
c = clickhouse_connect.get_client(
    host=s.host,
    port=s.port,
    username=s.user,
    password=s.password,
    database=s.db_name,
    send_receive_timeout=600,
)
DB = "v2_scalar_rebuild_20261123"
NEW = f"{DB}.dws_stock_factor_wide_v2_available_20261123"
where = """WHERE cityHash64(instrument_id)%50=0
OR source_code IN ('000001.SZ','000004.SZ','000928.SZ','002594.SZ','300750.SZ','600036.SH','600519.SH','601318.SH','688981.SH','688001.SH')
OR deferred_income_tax_ttm_0 IS NOT NULL"""
output = "available_independent_pit.json"
if args.latest_tax_only:
    NEW = f"{DB}.dws_stock_factor_wide_v2_available_20261123"
    where = "WHERE deferred_income_tax_ttm_0 IS NOT NULL"
    output = "available_tax_independent_pit.json"
ART = Path("docs/reports/v2_scalar_rebuild_20261123")
settings = {"max_threads": 4, "max_memory_usage": 8589934592, "max_execution_time": 600}
fields = [
    "accounts_pay_mrq_0",
    "total_share_mrq_0",
    "accounts_receiv_bill_mrq_9",
    "rd_exp_mrq_0",
    "rd_exp_ttm_0",
    "rd_exp_lyr_0",
    "basic_eps_lyr_10",
    "deferred_income_tax_ttm_0",
    "holder_num_mrq_0",
    "holder_num_mrq_1",
    "bench_ret",
    "northbound_hold_shares",
]


def get(sql):
    return list(c.query(sql, settings=settings).named_results())


panel = get(
    f"SELECT instrument_id,trade_date,available_trade_date,{','.join(fields)} FROM {NEW} {where} ORDER BY instrument_id,trade_date"
)
assert panel
instruments = ",".join(
    "'" + v + "'" for v in sorted({r["instrument_id"] for r in panel})
)
sources = {}
for table, values in [
    (
        "dwd_stock_balance_sheet",
        ["accounts_pay", "total_share", "accounts_receiv_bill"],
    ),
    ("dwd_stock_income", ["rd_exp", "basic_eps"]),
    ("dwd_stock_cashflow", ["decr_def_inc_tax_assets", "incr_def_inc_tax_liab"]),
]:
    rows = get(
        f"SELECT instrument_id,event_date,available_trade_date,report_type,f_ann_date,update_flag,sys_from,source_record_hash,{','.join(values)} FROM {s.db_name}.{table} WHERE instrument_id IN ({instruments}) AND sys_to=toDateTime64('9999-12-31 00:00:00',3) AND report_type IN ('1','4') AND ann_date>=event_date"
    )
    groups = defaultdict(list)
    for r in rows:
        groups[(r["instrument_id"], r["event_date"])].append(r)
    for key, rs in groups.items():
        rs.sort(
            key=lambda r: (
                r["available_trade_date"],
                r["report_type"] == "4",
                r["f_ann_date"] or dt.date.min,
                r["update_flag"] if r["update_flag"] is not None else -1,
                r["sys_from"],
                r["source_record_hash"],
            )
        )
    sources[table] = {
        key: ([r["available_trade_date"] for r in rs], rs) for key, rs in groups.items()
    }
    print(table, len(rows), flush=True)


def report(table, instrument, period, t):
    ds, rs = sources[table].get((instrument, period), ([], []))
    idx = bisect.bisect_right(ds, t) - 1
    return rs[idx] if idx >= 0 else None


def qshift(period, offset):
    n = period.year * 12 + period.month - 1 + offset * 3
    y, month = divmod(n, 12)
    month += 1
    return dt.date(y, month, calendar.monthrange(y, month)[1])


def value(r, name):
    return r[name] if r else None


def quarter(table, instrument, period, t, field):
    if period < dt.date(2010, 1, 1):
        return False, None
    r = report(table, instrument, period, t)
    if r is None:
        return False, None

    def ytd(row):
        if field == "deferred_income_tax":
            a = value(row, "decr_def_inc_tax_assets")
            b = value(row, "incr_def_inc_tax_liab")
            return a + b if a is not None and b is not None else None
        return value(row, field)

    curr = ytd(r)
    if period.month == 3:
        return True, curr
    prev = ytd(report(table, instrument, qshift(period, -1), t))
    return True, curr - prev if curr is not None and prev is not None else None


holders = defaultdict(list)
for r in get(
    f"SELECT instrument_id,event_date,available_trade_date,holder_num,sys_from,source_record_hash FROM {DB}.dwd_stock_holder_number_rebuilt WHERE instrument_id IN ({instruments})"
):
    holders[(r["instrument_id"], r["event_date"])].append(r)
for rs in holders.values():
    rs.sort(
        key=lambda r: (
            r["available_trade_date"],
            r["sys_from"],
            r["source_record_hash"],
        )
    )
bench = defaultdict(list)
for r in get(
    f"SELECT event_date,available_trade_date,pct_chg,sys_from,source_record_hash FROM {s.db_name}.dwd_index_eod_price WHERE source_code='000985.CSI'"
):
    bench[r["event_date"]].append(r)
for rs in bench.values():
    rs.sort(
        key=lambda r: (
            r["available_trade_date"],
            r["sys_from"],
            r["source_record_hash"],
        )
    )
nb = defaultdict(list)
for r in get(
    f"SELECT instrument_id,event_date,available_trade_date,vol,sys_from,source_record_hash FROM {s.db_name}.dwd_stock_northbound_holding WHERE instrument_id IN ({instruments})"
):
    nb[r["instrument_id"]].append(r)
for rs in nb.values():
    rs.sort(
        key=lambda r: (
            r["event_date"],
            r["available_trade_date"],
            r["sys_from"],
            r["source_record_hash"],
        ),
        reverse=True,
    )
counts = Counter()
nonnull = Counter()
diffs = []
max_abs = defaultdict(float)
for p in panel:
    i = p["instrument_id"]
    t = p["available_trade_date"]
    nextday = t + dt.timedelta(days=1)
    end = dt.date(nextday.year, ((nextday.month - 1) // 3) * 3 + 1, 1) - dt.timedelta(
        days=1
    )
    expected = {}
    for name, field, offset in [
        ("accounts_pay_mrq_0", "accounts_pay", 0),
        ("total_share_mrq_0", "total_share", 0),
        ("accounts_receiv_bill_mrq_9", "accounts_receiv_bill", 9),
    ]:
        expected[name] = value(
            report("dwd_stock_balance_sheet", i, qshift(end, -offset), t), field
        )
    expected["rd_exp_mrq_0"] = quarter("dwd_stock_income", i, end, t, "rd_exp")[1]
    for name, table, field in [
        ("rd_exp_ttm_0", "dwd_stock_income", "rd_exp"),
        ("deferred_income_tax_ttm_0", "dwd_stock_cashflow", "deferred_income_tax"),
    ]:
        slots = [quarter(table, i, qshift(end, -j), t, field) for j in range(4)]
        vals = [v for exists, v in slots if v is not None]
        expected[name] = (
            sum(vals) / len(vals) * 4
            if all(exists for exists, v in slots) and vals
            else None
        )
    for name, field, offset in [
        ("rd_exp_lyr_0", "rd_exp", 0),
        ("basic_eps_lyr_10", "basic_eps", 10),
    ]:
        expected[name] = value(
            report(
                "dwd_stock_income", i, dt.date(nextday.year - 1 - offset, 12, 31), t
            ),
            field,
        )
    for offset in (0, 1):
        rs = holders.get((i, qshift(end, -offset)), [])
        r = next((r for r in reversed(rs) if r["available_trade_date"] <= t), None)
        v = value(r, "holder_num")
        expected[f"holder_num_mrq_{offset}"] = v if v is not None and v > 0 else None
    r = next(
        (r for r in reversed(bench[p["trade_date"]]) if r["available_trade_date"] <= t),
        None,
    )
    v = value(r, "pct_chg")
    expected["bench_ret"] = v / 100 if v is not None else None
    r = next((r for r in nb[i] if r["available_trade_date"] <= t), None)
    expected["northbound_hold_shares"] = value(r, "vol")
    for f in fields:
        actual = p[f]
        want = expected[f]
        counts[f] += 1
        nonnull[f] += want is not None
        same = (actual is None and want is None) or (
            actual is not None
            and want is not None
            and math.isclose(actual, want, rel_tol=1e-12, abs_tol=1e-8)
        )
        if actual is not None and want is not None:
            max_abs[f] = max(max_abs[f], abs(actual - want))
        if not same:
            diffs.append(
                {
                    "instrument_id": i,
                    "trade_date": str(p["trade_date"]),
                    "t": str(t),
                    "field": f,
                    "expected": want,
                    "actual": actual,
                }
            )
result = {
    "rows": len(panel),
    "stocks": sorted({p['instrument_id'] for p in panel}),
    "selection": where,
    "candidate": NEW,
    "checks": sum(counts.values()),
    "field_checks": dict(counts),
    "source_nonnull": dict(nonnull),
    "mismatch_count": len(diffs),
    "mismatches_by_field": dict(Counter(r["field"] for r in diffs)),
    "mismatches": diffs[:50],
    "max_absolute_difference": dict(max_abs),
    "float_relative_tolerance": 1e-12,
    "float_absolute_tolerance": 1e-8,
}
if any(p["deferred_income_tax_ttm_0"] is not None for p in panel):
    result["tax_values"] = [
        {
            key: str(p[key]) if isinstance(p[key], dt.date) else p[key]
            for key in (
                "instrument_id",
                "trade_date",
                "available_trade_date",
                "deferred_income_tax_ttm_0",
            )
        }
        for p in panel
        if p["deferred_income_tax_ttm_0"] is not None
    ]
(ART / output).write_text(json.dumps(result, ensure_ascii=False, indent=2))
print(json.dumps(result, ensure_ascii=False), flush=True)
if diffs:
    raise SystemExit(1)
