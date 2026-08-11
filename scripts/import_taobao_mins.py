#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
把 /oss_data/zichao.wang/quant_data 下的分钟K线 CSV 导入 ClickHouse 表 stk_mins_taobao。

数据布局:<freq>_按年汇总/<year>_<freq>/<code>_<year>.csv
  例如 1分钟_按年汇总/2024_1min/sh600000_2024.csv
CSV(UTF-8 BOM,中文表头):
  时间,代码,名称,开盘价,收盘价,最高价,最低价,成交量,成交额,涨幅,振幅

只保留 OHLCV + 成交额,丢弃 名称/涨幅/振幅;代码从 sh600000 规范化为 600000.SH;
额外写入一列 freq(1min/5min/...)。表用 ReplacingMergeTree,按 (freq, toYYYYMM(trade_time)) 分区。

用法(从仓库根目录、quant 环境运行):
  python scripts/import_taobao_mins.py --create-table          # 仅建表
  python scripts/import_taobao_mins.py --freq 1min --dry-run   # 只统计,不写库
  python scripts/import_taobao_mins.py --freq 1min --years 2000
  python scripts/import_taobao_mins.py --freq 1min             # 全量(支持断点续跑)
"""

import argparse
import glob
import json
import logging
import os
import sys
import time

import pandas as pd
import yaml

# 保证能 import 仓库内模块(脚本位于 scripts/ 下)
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from tushare_integration.db_engine import DatabaseEngineFactory  # noqa: E402
from tushare_integration.settings import TushareIntegrationSettings  # noqa: E402

TABLE_NAME = "stk_mins_taobao"

# freq -> 年汇总目录中文前缀
FREQ_DIR_PREFIX = {
    "1min": "1分钟",
    "5min": "5分钟",
    "15min": "15分钟",
    "30min": "30分钟",
    "60min": "60分钟",
}

# 源 CSV 中文列 -> 目标列名(只取用到的列)
COLUMN_MAP = {
    "时间": "trade_time",
    "代码": "ts_code",
    "开盘价": "open",
    "最高价": "high",
    "最低价": "low",
    "收盘价": "close",
    "成交量": "vol",
    "成交额": "amount",
}

# 目标表列顺序(与 insert_df 的 DataFrame 列一致)
TARGET_COLUMNS = ["ts_code", "freq", "trade_time", "open", "high", "low", "close", "vol", "amount"]

CREATE_TABLE_DDL = f"""
CREATE TABLE IF NOT EXISTS {{db_name}}.{TABLE_NAME}
(
    `ts_code`    LowCardinality(String) COMMENT '股票代码,如600000.SH',
    `freq`       LowCardinality(String) COMMENT '频率:1min/5min/15min/30min/60min',
    `trade_time` DateTime               COMMENT '交易时间(秒级,分钟对齐)',
    `open`       Float64                COMMENT '开盘价',
    `high`       Float64                COMMENT '最高价',
    `low`        Float64                COMMENT '最低价',
    `close`      Float64                COMMENT '收盘价',
    `vol`        Int64                  COMMENT '成交量(股)',
    `amount`     Int64                  COMMENT '成交额(元)'
)
ENGINE = ReplacingMergeTree
PARTITION BY (freq, toYYYYMM(trade_time))
ORDER BY (ts_code, freq, trade_time)
SETTINGS index_granularity = 8192
"""

logger = logging.getLogger("import_taobao_mins")


def build_engine():
    """按仓库约定从 config.yaml 载入设置并创建 ClickhouseEngine。"""
    config_path = os.path.join(REPO_ROOT, "config.yaml")
    with open(config_path, "r", encoding="utf-8") as f:
        settings = TushareIntegrationSettings.model_validate(yaml.safe_load(f))
    engine = DatabaseEngineFactory.create(settings)
    return engine, settings


def create_table(engine, settings):
    ddl = CREATE_TABLE_DDL.format(db_name=settings.database.db_name)
    engine.client.query(ddl)
    logger.info("已确保表 %s.%s 存在", settings.database.db_name, TABLE_NAME)


def normalize_ts_code(raw: str):
    """sh600000 -> 600000.SH;sz000001 -> 000001.SZ。未知前缀返回 None。"""
    if not isinstance(raw, str):
        return None
    s = raw.strip().lower()
    if s.startswith("sh"):
        return s[2:] + ".SH"
    if s.startswith("sz"):
        return s[2:] + ".SZ"
    if s.startswith("bj"):  # 北交所,以防出现
        return s[2:] + ".BJ"
    return None


def resolve_year_dirs(base_dir: str, freq: str, years):
    """返回该频率下需要处理的 <year>_<freq> 目录列表(已排序)。"""
    prefix = FREQ_DIR_PREFIX[freq]
    summary_dir = os.path.join(base_dir, f"{prefix}_按年汇总")
    if not os.path.isdir(summary_dir):
        raise FileNotFoundError(f"未找到年汇总目录: {summary_dir}")

    all_dirs = sorted(
        d for d in glob.glob(os.path.join(summary_dir, f"*_{freq}")) if os.path.isdir(d)
    )
    if years is None:
        return all_dirs

    wanted = set(years)
    picked = []
    for d in all_dirs:
        # 目录名形如 2024_1min
        name = os.path.basename(d)
        year_str = name.split("_", 1)[0]
        if year_str.isdigit() and int(year_str) in wanted:
            picked.append(d)
    return picked


def parse_years(years_arg):
    """'2024' 或 '2020-2024' -> set(int);None -> None。"""
    if not years_arg:
        return None
    if "-" in years_arg:
        a, b = years_arg.split("-", 1)
        return set(range(int(a), int(b) + 1))
    return {int(years_arg)}


def list_csv_files(year_dirs):
    files = []
    for d in year_dirs:
        files.extend(sorted(glob.glob(os.path.join(d, "*.csv"))))
    return files


def load_state(state_file):
    if state_file and os.path.exists(state_file):
        try:
            with open(state_file, "r", encoding="utf-8") as f:
                return set(json.load(f).get("done", []))
        except Exception:  # noqa: BLE001
            logger.warning("state 文件损坏,忽略: %s", state_file)
    return set()


def save_state(state_file, done_set):
    if not state_file:
        return
    tmp = state_file + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"done": sorted(done_set)}, f)
    os.replace(tmp, state_file)


def process_file(path: str, freq: str):
    """读单个 CSV -> 规范化后的 DataFrame(列顺序 = TARGET_COLUMNS)。坏文件返回空 DataFrame。"""
    try:
        df = pd.read_csv(
            path,
            encoding="utf-8-sig",
            usecols=list(COLUMN_MAP.keys()),
        )
    except ValueError:
        # 列不匹配等,退回全量读取再筛列
        df = pd.read_csv(path, encoding="utf-8-sig")
        missing = [c for c in COLUMN_MAP if c not in df.columns]
        if missing:
            logger.warning("跳过(缺列 %s): %s", missing, path)
            return pd.DataFrame(columns=TARGET_COLUMNS)
        df = df[list(COLUMN_MAP.keys())]
    except Exception as e:  # noqa: BLE001
        logger.warning("跳过(读取失败 %s): %s", e, path)
        return pd.DataFrame(columns=TARGET_COLUMNS)

    df = df.rename(columns=COLUMN_MAP)

    # ts_code 规范化
    df["ts_code"] = df["ts_code"].map(normalize_ts_code)
    bad = df["ts_code"].isna()
    if bad.any():
        logger.warning("文件 %s 有 %d 行代码无法规范化,已丢弃", path, int(bad.sum()))
        df = df[~bad]
    if df.empty:
        return pd.DataFrame(columns=TARGET_COLUMNS)

    # 类型转换
    # 时间列可能混用两种格式(同一文件内也会切换):
    #   "2026-01-05 09:30:00"(带秒、连字符)与 "2026/06/04 09:30"(斜杠、无秒)。
    # 不指定 format 让 pandas 逐值推断,遇到斜杠格式会误判为 NaT 被丢弃,
    # 故先用两种显式格式各解析一遍,再取非空结果合并。
    raw_time = df["trade_time"].astype("string").str.strip()
    t1 = pd.to_datetime(raw_time, format="%Y-%m-%d %H:%M:%S", errors="coerce")
    t2 = pd.to_datetime(raw_time, format="%Y/%m/%d %H:%M", errors="coerce")
    df["trade_time"] = t1.fillna(t2)
    # 兜底:两种显式格式都失败的,再用宽松推断补一次(极少数其它写法)
    still_na = df["trade_time"].isna()
    if still_na.any():
        df.loc[still_na, "trade_time"] = pd.to_datetime(
            raw_time[still_na], errors="coerce", format="mixed"
        )
    for col in ("open", "high", "low", "close"):
        df[col] = pd.to_numeric(df[col], errors="coerce").astype("float64")
    for col in ("vol", "amount"):
        df[col] = pd.to_numeric(df[col], errors="coerce")

    # 丢弃时间/量额无法解析的坏行
    before = len(df)
    df = df.dropna(subset=["trade_time", "vol", "amount"])
    if len(df) < before:
        logger.warning("文件 %s 丢弃 %d 行(时间或量额无法解析)", path, before - len(df))

    df[["vol", "amount"]] = df[["vol", "amount"]].astype("int64")
    df["freq"] = freq

    return df[TARGET_COLUMNS]


def main():
    parser = argparse.ArgumentParser(description="导入淘宝分钟K线到 ClickHouse stk_mins_taobao")
    parser.add_argument("--freq", default="1min", choices=list(FREQ_DIR_PREFIX.keys()))
    parser.add_argument("--base-dir", default="/oss_data/zichao.wang/quant_data")
    parser.add_argument("--years", default=None, help="如 2024 或 2020-2024;默认全部年份")
    parser.add_argument("--batch-size", type=int, default=200000, help="每批 insert 的行数")
    parser.add_argument("--state-file", default=None, help="断点续跑状态文件;默认 scripts/.taobao_mins_import_state.<freq>.json")
    parser.add_argument("--dry-run", action="store_true", help="只统计文件数/预估行数,不写库")
    parser.add_argument("--create-table", action="store_true", help="仅建表后退出")
    parser.add_argument("--log-every", type=int, default=200, help="每处理多少文件打印一次进度")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    engine, settings = build_engine()

    if args.create_table:
        create_table(engine, settings)
        return

    years = parse_years(args.years)
    year_dirs = resolve_year_dirs(args.base_dir, args.freq, years)
    files = list_csv_files(year_dirs)
    logger.info("频率=%s 年份目录=%d 个,CSV 文件=%d 个", args.freq, len(year_dirs), len(files))

    if args.dry_run:
        # 抽样估算平均行数(避免全量 wc)
        sample = files[:: max(1, len(files) // 20)][:20] if files else []
        sample_rows = 0
        for p in sample:
            try:
                # 减一行表头
                with open(p, "rb") as f:
                    sample_rows += sum(1 for _ in f) - 1
            except Exception:  # noqa: BLE001
                pass
        avg = (sample_rows / len(sample)) if sample else 0
        logger.info("抽样 %d 文件,平均约 %.0f 行/文件,预估总行数约 %.2f 亿",
                    len(sample), avg, avg * len(files) / 1e8)
        return

    # 建表(幂等)
    create_table(engine, settings)

    state_file = args.state_file or os.path.join(
        REPO_ROOT, "scripts", f".taobao_mins_import_state.{args.freq}.json"
    )
    done = load_state(state_file)
    if done:
        logger.info("续跑:已完成 %d 个文件,将跳过", len(done))

    t0 = time.time()
    total_rows = 0
    processed = 0
    buffer = []
    buffer_rows = 0

    def flush():
        nonlocal buffer, buffer_rows, total_rows
        if not buffer:
            return
        batch = pd.concat(buffer, ignore_index=True)
        engine.client.insert_df(TABLE_NAME, batch)
        total_rows += len(batch)
        buffer = []
        buffer_rows = 0

    pending = [p for p in files if p not in done]
    logger.info("待处理文件 %d 个", len(pending))

    for i, path in enumerate(pending, 1):
        df = process_file(path, args.freq)
        if not df.empty:
            buffer.append(df)
            buffer_rows += len(df)
        if buffer_rows >= args.batch_size:
            flush()

        done.add(path)
        processed += 1

        if processed % args.log_every == 0:
            flush()  # flush 后再存 state,保证已 insert 才标记完成
            save_state(state_file, done)
            elapsed = time.time() - t0
            rate = processed / elapsed if elapsed else 0
            remain = (len(pending) - processed) / rate if rate else 0
            logger.info(
                "进度 %d/%d 文件 | 已写 %d 行 | %.1f 文件/s | 预估剩余 %.1f 分钟 | 当前 %s",
                processed, len(pending), total_rows, rate, remain / 60, os.path.basename(path),
            )

    # 收尾
    flush()
    save_state(state_file, done)

    elapsed = time.time() - t0
    logger.info("完成:处理 %d 文件,写入 %d 行,耗时 %.1f 分钟", processed, total_rows, elapsed / 60)

    # 核对
    res = engine.client.query(
        f"SELECT count(), min(trade_time), max(trade_time) FROM {TABLE_NAME} WHERE freq = %(f)s",
        parameters={"f": args.freq},
    )
    logger.info("表内 freq=%s: count/min/max = %s", args.freq, res.result_rows)


if __name__ == "__main__":
    main()
