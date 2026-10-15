#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
解析《【字典】因子对外字典》xlsx 的 A 股 sheet,构建因子元数据表 ths_ashare_daily.factor_catalog。

字典 A 股 sheet 的结构:
  - 顶部为"数据类别 -> SDK表名"汇总(SDK 表名形如 ashare_daily__daily_freq)。
  - 其后为分组明细表,每组一个小标题行,接表头
    `二级分类, 数据字段名(=factor_code), 英文全称, 中文全称, 入库日期, 中文介绍`,再接若干因子行。

本脚本只用标准库解析 xlsx(zip + XML),不依赖 openpyxl。它把每个 factor_code 落到对应
ClickHouse 表(ths_ashare_daily.<SDK后缀>),并记录 SDK 的完整 db__table 产品名,供 SDK 增量
路径做 product -> 表的映射。

同时与磁盘实际存在的 factor_code 做交叉核对:报告"磁盘有但字典无"与"字典有但磁盘无"。

用法::
    python -I scripts/supermind_factor_catalog.py \
        --xlsx docs/other/【字典】因子对外字典20260908.xlsx \
        --root /nfs_data/quant_data/super_mind/history
    python -I scripts/supermind_factor_catalog.py --xlsx ... --dry-run   # 只解析打印,不写库
"""

import argparse
import os
import re
import sys
import zipfile
import xml.etree.ElementTree as ET

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

import clickhouse_connect  # noqa: E402

DB_NAME = "ths_ashare_daily"
M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

# 磁盘顶层目录 -> 表名,与 import_supermind_history.py 保持一致
GROUP_TABLE = {
    "DailyFreq": "daily_freq", "MinFreq": "min_freq", "CallAuction": "call_auction",
    "TBTTran": "tbt_tran", "TBTOrder": "tbt_order", "TickSnapshot": "tick_snapshot",
    "DLTick": "dl_tick_snapshot", "TRFM": "trfm_model", "RLPV": "rl_pv",
    "RLFundamental": "rl_funda", "MLNews": "ml_news", "LLMNews": "llm_news",
    "RLSentiment": "rl_senti",
}

CATALOG_DDL = """
CREATE TABLE IF NOT EXISTS {db}.factor_catalog
(
    ch_table     LowCardinality(String),
    sdk_product  LowCardinality(String),
    sub_category LowCardinality(String),
    factor_code  String,
    name_en      String,
    name_cn      String,
    intro        String,
    since        String
)
ENGINE = ReplacingMergeTree
ORDER BY (ch_table, factor_code)
""".format(db=DB_NAME)


def _cidx(ref):
    s = re.match(r"[A-Z]+", ref).group()
    n = 0
    for ch in s:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_sheet(zf, path):
    sst = []
    with zf.open("xl/sharedStrings.xml") as f:
        for si in ET.parse(f).getroot().findall("m:si", NS):
            sst.append("".join(e.text or "" for e in si.iter(M + "t")))
    rows = []
    with zf.open(path) as f:
        root = ET.parse(f).getroot()
    for r in root.iter(M + "row"):
        cells = {}
        for c in r.findall("m:c", NS):
            v = c.find("m:v", NS)
            isv = c.find("m:is", NS)
            if v is not None:
                val = sst[int(v.text)] if c.get("t") == "s" else v.text
            elif isv is not None:
                val = "".join(e.text or "" for e in isv.iter(M + "t"))
            else:
                val = ""
            cells[_cidx(c.get("r"))] = val
        mx = max(cells) if cells else -1
        rows.append([cells.get(i, "") for i in range(mx + 1)])
    return rows


def parse_catalog(rows):
    """从 A 股 sheet 明细区解析因子行。返回 list[dict]。"""
    # 明细表头:二级分类 / 数据字段名 / 英文全称 / 中文全称 / 入库日期 / 中文介绍
    records = []
    for r in rows:
        if len(r) < 2:
            continue
        code = (r[1] or "").strip()
        # factor_code 形如大写字母/数字/下划线组合(OB_CA1_CBOS、DAY_PVC_AMPV、RL_DAY_ALPHA1 ...)
        if not re.fullmatch(r"[A-Z0-9_]{3,}", code):
            continue
        records.append({
            "sub_category": (r[0] or "").strip(),
            "factor_code": code,
            "name_en": (r[2] or "").strip() if len(r) > 2 else "",
            "name_cn": (r[3] or "").strip() if len(r) > 3 else "",
            "since": (r[4] or "").strip() if len(r) > 4 else "",
            "intro": (r[5] or "").strip() if len(r) > 5 else "",
        })
    return records


def disk_factor_tables(root):
    """返回 {factor_code: (ch_table, sub_category)},来自磁盘实际目录。"""
    out = {}
    for group, table in GROUP_TABLE.items():
        gdir = os.path.join(root, group)
        if not os.path.isdir(gdir):
            continue
        for sub in os.listdir(gdir):
            sdir = os.path.join(gdir, sub)
            if not os.path.isdir(sdir):
                continue
            for factor in os.listdir(sdir):
                if os.path.isdir(os.path.join(sdir, factor)):
                    out[factor] = (table, sub)
    return out


def load_client():
    with open(os.path.join(REPO_ROOT, "config.yaml"), encoding="utf-8") as f:
        db = yaml.safe_load(f)["database"]
    return clickhouse_connect.get_client(
        host=db["host"], port=int(db["port"]), username=db["user"],
        password=db.get("password", "") or "", apply_server_timezone=True,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--xlsx", required=True, help="因子对外字典 xlsx 路径")
    ap.add_argument("--root", default="/nfs_data/quant_data/super_mind/history")
    ap.add_argument("--sheet", default="xl/worksheets/sheet1.xml", help="A 股 sheet 的内部路径")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with zipfile.ZipFile(args.xlsx) as zf:
        rows = read_sheet(zf, args.sheet)
    dict_records = parse_catalog(rows)
    dict_codes = {r["factor_code"] for r in dict_records}
    print(f"字典解析到 {len(dict_records)} 条因子记录,{len(dict_codes)} 个唯一 factor_code")

    disk = disk_factor_tables(args.root)
    disk_codes = set(disk)
    print(f"磁盘实际 {len(disk_codes)} 个 factor_code")

    only_disk = sorted(disk_codes - dict_codes)
    only_dict = sorted(dict_codes - disk_codes)
    print(f"磁盘有但字典无: {len(only_disk)}  {only_disk[:20]}")
    print(f"字典有但磁盘无: {len(only_dict)}  {only_dict[:20]}")

    # 以磁盘为准落 ch_table / sub_category(字典的二级分类更细,但表归属以磁盘为权威),
    # 字典补充 en/cn/intro/since;sdk_product = ashare_daily__<table>
    final = []
    for code, (table, sub) in sorted(disk.items()):
        meta = next((r for r in dict_records if r["factor_code"] == code), {})
        final.append([
            table, f"ashare_daily__{table}", sub, code,
            meta.get("name_en", ""), meta.get("name_cn", ""),
            meta.get("intro", ""), meta.get("since", ""),
        ])

    if args.dry_run:
        print(f"[dry-run] 将写入 {len(final)} 行到 {DB_NAME}.factor_catalog;样例:")
        for row in final[:5]:
            print("  ", row[:4], "|", row[5][:20])
        return

    client = load_client()
    client.command(f"CREATE DATABASE IF NOT EXISTS {DB_NAME}")
    client.command(CATALOG_DDL)
    client.command(f"TRUNCATE TABLE {DB_NAME}.factor_catalog")
    client.insert(
        f"{DB_NAME}.factor_catalog", final,
        column_names=["ch_table", "sdk_product", "sub_category", "factor_code",
                      "name_en", "name_cn", "intro", "since"],
    )
    print(f"已写入 {len(final)} 行到 {DB_NAME}.factor_catalog")


if __name__ == "__main__":
    main()
