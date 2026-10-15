#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把 /nfs_data/quant_data/super_mind/history 下的同花顺(THS)ths_factor 因子历史导入 ClickHouse。

磁盘布局(已核实)::

    TopCategory/SubCategory/FACTOR_CODE/YYYY/FACTOR_CODE-YYYY-MM-DD.csv

每个 CSV 都是统一的长表格式,表头固定为 ``time,code,<FACTOR_CODE>``,一行一只股票一天。
全部为 A 股(.SH/.SZ/.BJ),日频。整库约 571 个因子、148 万个 CSV、224GB。

入库设计(与 SDK 的 ``db__table`` 约定对齐,但数据库名加 ``ths`` 前缀以示来源)::

    数据库 ths_ashare_daily,每个顶层目录一张"长表",表名=SDK 后缀(无表名前缀):
        DailyFreq      -> ths_ashare_daily.daily_freq
        MinFreq        -> ths_ashare_daily.min_freq
        CallAuction    -> ths_ashare_daily.call_auction
        TBTTran        -> ths_ashare_daily.tbt_tran
        TBTOrder       -> ths_ashare_daily.tbt_order
        TickSnapshot   -> ths_ashare_daily.tick_snapshot
        DLTick         -> ths_ashare_daily.dl_tick_snapshot
        TRFM           -> ths_ashare_daily.trfm_model
        RLPV           -> ths_ashare_daily.rl_pv
        RLFundamental  -> ths_ashare_daily.rl_funda
        MLNews         -> ths_ashare_daily.ml_news
        LLMNews        -> ths_ashare_daily.llm_news
        RLSentiment    -> ths_ashare_daily.rl_senti

表结构(所有表一致)::

    trade_date   Date32
    ts_code      LowCardinality(String)
    factor_code  LowCardinality(String)
    sub_category LowCardinality(String)
    value        Nullable(Float64)      -- 部分因子天然为空(如 LLM_NEWS)
    _ingest_time DateTime DEFAULT now()
    ENGINE = ReplacingMergeTree(_ingest_time)
    PARTITION BY toYYYYMM(trade_date)
    ORDER BY (factor_code, ts_code, trade_date)

断点续跑:以 (group, factor, year) 为单位,完成后写入 ths_ashare_daily.load_manifest,
重跑自动跳过已完成单元;ReplacingMergeTree 也保证重复导入幂等(同键最新 _ingest_time 胜出)。

用法(从仓库根目录、quant 环境运行,务必带 -I 隔离当前目录)::

    python -I scripts/import_supermind_history.py --group LLMNews --dry-run   # 只看计划,不写库
    python -I scripts/import_supermind_history.py --group LLMNews             # 小组冒烟
    python -I scripts/import_supermind_history.py --group all                 # 全量(可续跑)
    python -I scripts/import_supermind_history.py --group DailyFreq --since 2024-01-01
"""

import argparse
import glob
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import yaml

# 保证能 import 仓库内模块(脚本位于 scripts/ 下)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import clickhouse_connect  # noqa: E402

DB_NAME = "ths_ashare_daily"
DEFAULT_ROOT = "/nfs_data/quant_data/super_mind/history"

# 磁盘顶层目录 -> ClickHouse 表名(= SDK 的 __ 后缀)
GROUP_TABLE = {
    "DailyFreq": "daily_freq",
    "MinFreq": "min_freq",
    "CallAuction": "call_auction",
    "TBTTran": "tbt_tran",
    "TBTOrder": "tbt_order",
    "TickSnapshot": "tick_snapshot",
    "DLTick": "dl_tick_snapshot",
    "TRFM": "trfm_model",
    "RLPV": "rl_pv",
    "RLFundamental": "rl_funda",
    "MLNews": "ml_news",
    "LLMNews": "llm_news",
    "RLSentiment": "rl_senti",
}

TABLE_DDL = """
CREATE TABLE IF NOT EXISTS {db}.{table}
(
    trade_date   Date32,
    ts_code      LowCardinality(String),
    factor_code  LowCardinality(String),
    sub_category LowCardinality(String),
    value        Nullable(Float64),
    _ingest_time DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(_ingest_time)
PARTITION BY toYYYYMM(trade_date)
ORDER BY (factor_code, ts_code, trade_date)
"""

MANIFEST_DDL = """
CREATE TABLE IF NOT EXISTS {db}.load_manifest
(
    `group`     LowCardinality(String),
    `table`     LowCardinality(String),
    factor_code LowCardinality(String),
    `year`      UInt16,
    files       UInt32,
    rows        UInt64,
    done_at     DateTime DEFAULT now()
)
ENGINE = ReplacingMergeTree(done_at)
ORDER BY (`group`, factor_code, `year`)
"""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("supermind")


def load_client():
    """按仓库约定从 config.yaml 的 database 块创建 clickhouse-connect client。"""
    config_path = os.path.join(REPO_ROOT, "config.yaml")
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    db = cfg["database"]
    return clickhouse_connect.get_client(
        host=db["host"],
        port=int(db["port"]),
        username=db["user"],
        password=db.get("password", "") or "",
        apply_server_timezone=True,
        # 不设 database:所有 SQL/insert 均用全限定名 ths_ashare_daily.<table>
    )


def ensure_schema(client, table):
    client.command(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}")
    client.command(TABLE_DDL.format(db=DB_NAME, table=table))
    client.command(MANIFEST_DDL.format(db=DB_NAME))


def done_units(client, group):
    """返回该 group 下已完成的 (factor_code, year) 集合。"""
    try:
        df = client.query_df(
            f"SELECT factor_code, year FROM {DB_NAME}.load_manifest "
            f"WHERE `group` = {_q(group)}"
        )
    except Exception:
        return set()
    return {(r.factor_code, int(r.year)) for r in df.itertuples(index=False)}


def _q(s: str) -> str:
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"


def read_factor_year(csv_paths, factor_code, sub_category):
    """读取一个因子某一年的所有日 CSV,拼成目标 DataFrame。"""
    frames = []
    for p in csv_paths:
        # 第 3 列列名就是 factor_code;统一重命名,空串 -> NaN -> Nullable(Float64)
        df = pd.read_csv(p, dtype={"time": str, "code": str})
        if df.shape[1] != 3:
            raise ValueError(f"unexpected columns in {p}: {list(df.columns)}")
        df.columns = ["trade_date", "ts_code", "value"]
        df["value"] = pd.to_numeric(df["value"], errors="coerce")
        frames.append(df)
    if not frames:
        return None
    out = pd.concat(frames, ignore_index=True)
    out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.date
    out["factor_code"] = factor_code
    out["sub_category"] = sub_category
    return out[["trade_date", "ts_code", "factor_code", "sub_category", "value"]]


def iter_units(root, group, since, until):
    """产出 (factor_code, sub_category, year, [csv_paths]) 单元,按 (因子, 年) 分批。"""
    group_dir = os.path.join(root, group)
    for sub in sorted(os.listdir(group_dir)):
        sub_dir = os.path.join(group_dir, sub)
        if not os.path.isdir(sub_dir):
            continue
        for factor in sorted(os.listdir(sub_dir)):
            factor_dir = os.path.join(sub_dir, factor)
            if not os.path.isdir(factor_dir):
                continue
            for year in sorted(os.listdir(factor_dir)):
                year_dir = os.path.join(factor_dir, year)
                if not (os.path.isdir(year_dir) and year.isdigit()):
                    continue
                paths = sorted(glob.glob(os.path.join(year_dir, "*.csv")))
                if since or until:
                    paths = [p for p in paths if _date_ok(p, since, until)]
                if paths:
                    yield factor, sub, int(year), paths


def _date_ok(path, since, until):
    # 文件名形如 FACTOR-YYYY-MM-DD.csv,取末尾日期判断
    base = os.path.basename(path)[:-4]
    d = base.rsplit("-", 3)
    if len(d) < 4:
        return True
    datestr = "-".join(d[-3:])
    if since and datestr < since:
        return False
    if until and datestr > until:
        return False
    return True


def process_group(client, root, group, args):
    table = GROUP_TABLE[group]
    if not args.dry_run:
        ensure_schema(client, table)
    skip = set() if (args.dry_run or args.since or args.until) else done_units(client, group)

    units = list(iter_units(root, group, args.since, args.until))
    pending = [u for u in units if (u[0], u[2]) not in skip]
    log.info(
        "[%s -> %s.%s] %d 个 (因子,年) 单元, 跳过已完成 %d, 待处理 %d",
        group, DB_NAME, table, len(units), len(units) - len(pending), len(pending),
    )
    if args.dry_run:
        total_files = sum(len(u[3]) for u in pending)
        log.info("[dry-run] 将读取 %d 个 CSV,写入 %s.%s", total_files, DB_NAME, table)
        return 0

    total_rows = 0

    def _one(unit):
        factor, sub, year, paths = unit
        df = read_factor_year(paths, factor, sub)
        if df is None or df.empty:
            return factor, year, len(paths), 0
        return factor, year, len(paths), df, sub

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = {pool.submit(_one, u): u for u in pending}
        for fut in as_completed(futs):
            res = fut.result()
            if len(res) == 4:  # 空单元
                factor, year, nfiles, _ = res
                nrows = 0
            else:
                factor, year, nfiles, df, sub = res
                client.insert_df(f"{DB_NAME}.{table}", df)
                nrows = len(df)
                total_rows += nrows
                client.insert(
                    f"{DB_NAME}.load_manifest",
                    [[group, table, factor, year, nfiles, nrows]],
                    column_names=["group", "table", "factor_code", "year", "files", "rows"],
                )
            log.info("  %-20s %d: %d files, %d rows", factor, year, nfiles, nrows)
    log.info("[%s] 完成,共写入 %d 行", group, total_rows)
    return total_rows


def main():
    ap = argparse.ArgumentParser(description="Import super_mind THS factor history into ClickHouse")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="历史数据根目录")
    ap.add_argument("--group", required=True, help="顶层目录名,或 all 表示全部")
    ap.add_argument("--since", default=None, help="仅导入 >= 该日期(YYYY-MM-DD)的文件")
    ap.add_argument("--until", default=None, help="仅导入 <= 该日期(YYYY-MM-DD)的文件")
    ap.add_argument("--workers", type=int, default=4, help="并行读取/插入的线程数")
    ap.add_argument("--dry-run", action="store_true", help="只统计计划,不建表不写库")
    args = ap.parse_args()

    if args.group == "all":
        groups = list(GROUP_TABLE)
    elif args.group in GROUP_TABLE:
        groups = [args.group]
    else:
        ap.error(f"未知 group: {args.group};可选: {', '.join(GROUP_TABLE)} 或 all")

    client = None if args.dry_run else load_client()
    if args.dry_run:
        # dry-run 也需要一个 client 来创建?不需要;但 done_units 跳过。
        client = _NullClient()

    t0 = time.time()
    grand = 0
    for g in groups:
        grand += process_group(client, args.root, g, args)
    log.info("全部完成:%d 行,用时 %.1fs", grand, time.time() - t0)


class _NullClient:
    """dry-run 占位,query_df 返回空以跳过 manifest 查询。"""

    def query_df(self, *a, **k):
        return pd.DataFrame(columns=["factor_code", "year"])


if __name__ == "__main__":
    main()
