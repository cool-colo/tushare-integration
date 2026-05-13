from __future__ import annotations

import argparse
import os
import sys
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

ROOT_DIR = Path(__file__).resolve().parent.parent
os.chdir(ROOT_DIR)
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from tushare_integration.db_engine import DatabaseEngineFactory
from tushare_integration.dwd import DWDManager
from tushare_integration.settings import TushareIntegrationSettings
from tushare_integration.storage import build_latest_schema


SCHEMA_DIR = ROOT_DIR / "tushare_integration" / "schema"
DEFAULT_OUTPUT = ROOT_DIR / "docs" / "downloaded_tables_report.txt"
DEFAULT_STATS_MD_OUTPUT = ROOT_DIR / "docs" / "downloaded_tables_report_stats.md"
DEFAULT_STATS_TXT_OUTPUT = ROOT_DIR / "docs" / "downloaded_tables_report_stats.txt"
INTERNAL_TABLES = {"tushare_integration_log"}

LAYER_ORDER = ["DWS汇总层", "DWD标准层", "源表/同步表"]
TOPIC_ORDER = ["股票", "指数/板块", "期货", "沪深港通", "两融/转融通", "日历/市场", "概念题材", "研报/预测", "其他"]
ROW_BUCKETS = [
    (">= 1,000万行", 10_000_000, None),
    ("100万 - 1,000万行", 1_000_000, 10_000_000),
    ("10万 - 100万行", 100_000, 1_000_000),
    ("< 10万行", 0, 100_000),
]

HSGT_TABLES = {"ccass_hold", "ccass_hold_detail", "ggt_daily", "ggt_top10", "hk_hold", "hs_const", "hsgt_top10"}
MARGIN_TABLES = {"margin", "margin_detail", "margin_secs", "slb_len", "slb_len_mm", "slb_sec", "slb_sec_detail"}
CALENDAR_TABLES = {"dwd_trade_calendar", "trade_cal", "sz_daily_info"}
CONCEPT_TABLES = {"concept", "concept_detail", "dc_concept"}
RESEARCH_TABLES = {"broker_recommend", "report_rc"}
OTHER_TABLES = {"block_trade", "dwd_security_master"}
INDEX_TABLES = {
    "dc_index",
    "index_basic",
    "index_daily",
    "index_dailybasic",
    "index_global",
    "index_monthly",
    "index_weekly",
    "index_weight",
    "tdx_index",
}
STOCK_TABLES = {
    "adj_factor",
    "bak_basic",
    "bak_daily",
    "balancesheet",
    "cashflow",
    "cyq_chips",
    "cyq_chips_backup_before_price_key",
    "cyq_perf",
    "daily",
    "daily_basic",
    "daily_info",
    "disclosure_date",
    "dividend",
    "express",
    "fina_audit",
    "fina_indicator",
    "fina_mainbz",
    "forecast",
    "income",
    "monthly",
    "namechange",
    "new_share",
    "pledge_detail",
    "pledge_stat",
    "repurchase",
    "share_float",
    "stk_alert",
    "stk_factor",
    "stk_high_shock",
    "stk_holdernumber",
    "stk_holdertrade",
    "stk_limit",
    "stk_managers",
    "stk_mins",
    "stk_rewards",
    "stk_shock",
    "stk_surv",
    "suspend_d",
    "top10_floatholders",
    "top10_holders",
    "top_inst",
    "top_list",
    "weekly",
}


@dataclass
class TableDoc:
    name: str
    comment: str
    columns: list[dict[str, Any]]
    row_count: int
    schema_source: str
    sample: pd.DataFrame | None = None


def load_settings(config_path: Path) -> TushareIntegrationSettings:
    with open(config_path, "r", encoding="utf-8") as f:
        return TushareIntegrationSettings.model_validate(yaml.safe_load(f.read()))


def load_yaml(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f.read())


def build_schema_index() -> dict[str, dict[str, Any]]:
    schema_index: dict[str, dict[str, Any]] = {}

    for path in sorted(SCHEMA_DIR.glob("**/*.yaml")):
        relative_path = path.relative_to(SCHEMA_DIR)
        if relative_path.parts[0] in {"dwd", "template"}:
            continue

        schema = load_yaml(path)
        table_name = schema.get("name")
        if not table_name or "columns" not in schema:
            continue

        # Latest tables are the business table plus system metadata columns.
        schema_index.setdefault(
            table_name,
            {
                "comment": schema.get("comment", ""),
                "columns": build_latest_schema(schema)["columns"],
                "schema_source": str(relative_path),
            },
        )

    dwd_manager = DWDManager()
    for table_name in dwd_manager.list_tables():
        spec = dwd_manager.load_spec(table_name)
        schema = dwd_manager.build_schema(spec)
        schema_index[table_name] = {
            "comment": schema.get("comment") or spec.get("comment", ""),
            "columns": schema.get("columns", []),
            "schema_source": f"dwd/{table_name}.yaml",
        }

    return schema_index


def quote_identifier(identifier: str) -> str:
    return f"`{identifier.replace('`', '``')}`"


def sql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def query_table_names(db_engine, settings: TushareIntegrationSettings) -> list[str]:
    db_name = settings.database.db_name
    if settings.database.db_type == "clickhouse":
        sql = f"""
            SELECT name
            FROM system.tables
            WHERE database = currentDatabase()
              AND NOT endsWith(name, '_raw')
            ORDER BY name
        """
    else:
        sql = f"""
            SELECT table_name AS name
            FROM information_schema.tables
            WHERE table_schema = {sql_string(db_name)}
              AND table_name NOT LIKE '%\\_raw'
            ORDER BY table_name
        """

    table_names = db_engine.query_df(sql)["name"].tolist()
    return [table_name for table_name in table_names if table_name not in INTERNAL_TABLES]


def count_rows(db_engine, settings: TushareIntegrationSettings, table_name: str) -> int:
    db_name = settings.database.db_name
    count_expr = "count()" if settings.database.db_type == "clickhouse" else "count(*)"
    sql = f"SELECT {count_expr} AS row_count FROM {quote_identifier(db_name)}.{quote_identifier(table_name)}"
    result = db_engine.query_df(sql)
    if result.empty:
        return 0
    return int(result.iloc[0]["row_count"])


def query_fallback_table_doc(db_engine, settings: TushareIntegrationSettings, table_name: str) -> dict[str, Any]:
    db_name = settings.database.db_name
    if settings.database.db_type == "clickhouse":
        columns_sql = f"""
            SELECT name, comment
            FROM system.columns
            WHERE database = currentDatabase()
              AND table = {sql_string(table_name)}
            ORDER BY position
        """
    else:
        columns_sql = f"""
            SELECT column_name AS name, column_comment AS comment
            FROM information_schema.columns
            WHERE table_schema = {sql_string(db_name)}
              AND table_name = {sql_string(table_name)}
            ORDER BY ordinal_position
        """

    columns_df = db_engine.query_df(columns_sql)
    return {
        "comment": "未在本地 schema 中匹配到表说明",
        "columns": columns_df.fillna("").to_dict("records"),
        "schema_source": "database metadata",
    }


def query_sample(
    db_engine,
    settings: TushareIntegrationSettings,
    table_name: str,
    sample_size: int,
) -> pd.DataFrame | None:
    if sample_size <= 0:
        return None

    db_name = settings.database.db_name
    sql = f"SELECT * FROM {quote_identifier(db_name)}.{quote_identifier(table_name)} LIMIT {sample_size}"
    return db_engine.query_df(sql)


def table_layer_sort_key(table_doc: TableDoc) -> tuple[int, str]:
    schema_source = table_doc.schema_source.replace("\\", "/")
    if table_doc.name.startswith("dws_") or schema_source.startswith("dws/"):
        layer_rank = 0
    elif table_doc.name.startswith("dwd_") or schema_source.startswith("dwd/"):
        layer_rank = 1
    else:
        layer_rank = 2
    return layer_rank, table_doc.name


def collect_table_docs(
    config_path: Path,
    include_empty: bool,
    sample_size: int,
) -> tuple[TushareIntegrationSettings, list[TableDoc]]:
    settings = load_settings(config_path)
    db_engine = DatabaseEngineFactory.create(settings)
    schema_index = build_schema_index()
    table_docs: list[TableDoc] = []

    for table_name in query_table_names(db_engine, settings):
        row_count = count_rows(db_engine, settings, table_name)
        if row_count == 0 and not include_empty:
            continue

        schema_doc = schema_index.get(table_name)
        if schema_doc is None:
            schema_doc = query_fallback_table_doc(db_engine, settings, table_name)

        table_docs.append(
            TableDoc(
                name=table_name,
                comment=schema_doc.get("comment", ""),
                columns=schema_doc.get("columns", []),
                row_count=row_count,
                schema_source=schema_doc.get("schema_source", ""),
                sample=query_sample(db_engine, settings, table_name, sample_size),
            )
        )

    table_docs.sort(key=table_layer_sort_key)
    return settings, table_docs


def format_number(value: int) -> str:
    return f"{value:,}"


def normalize_comment(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    return text if text else "无字段说明"


def build_database_label(settings: TushareIntegrationSettings) -> str:
    return (
        f"{settings.database.db_type}://{settings.database.host}:{settings.database.port}/"
        f"{settings.database.db_name}"
    )


def build_scope(include_empty: bool) -> str:
    empty_scope = "包含 0 行空表" if include_empty else "排除 0 行空表"
    return f"数据库中实际存在、表名不以 _raw 结尾、排除内部日志表、{empty_scope}的数据表"


def format_percent(value: int, total: int) -> str:
    if total == 0:
        return "0.00%"
    return f"{value / total * 100:.2f}%"


def truncate_text(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[: max_chars - 1] + "…"


def table_layer(table_doc: TableDoc) -> str:
    schema_source = table_doc.schema_source.replace("\\", "/")
    if table_doc.name.startswith("dws_") or schema_source.startswith("dws/"):
        return "DWS汇总层"
    if table_doc.name.startswith("dwd_") or schema_source.startswith("dwd/"):
        return "DWD标准层"
    return "源表/同步表"


def table_topic(table_doc: TableDoc) -> str:
    table_name = table_doc.name
    if table_name.startswith(("dws_stock_", "dwd_stock_", "stock_")) or table_name in STOCK_TABLES:
        return "股票"
    if table_name.startswith("dwd_index_") or table_name in INDEX_TABLES:
        return "指数/板块"
    if table_name.startswith("dwd_future_") or table_name.startswith("fut_"):
        return "期货"
    if table_name in CALENDAR_TABLES:
        return "日历/市场"
    if table_name in HSGT_TABLES:
        return "沪深港通"
    if table_name in MARGIN_TABLES:
        return "两融/转融通"
    if table_name in CONCEPT_TABLES:
        return "概念题材"
    if table_name in RESEARCH_TABLES:
        return "研报/预测"
    if table_name in OTHER_TABLES:
        return "其他"
    if table_doc.schema_source.replace("\\", "/").startswith("stock/"):
        return "股票"
    return "其他"


def schema_label(table_doc: TableDoc) -> str:
    schema_source = table_doc.schema_source.replace("\\", "/")
    if schema_source == "database metadata":
        return "未匹配"
    if schema_source.startswith("dwd/"):
        return "DWD YAML"
    if schema_source.startswith("dws/"):
        return "DWS YAML"
    return "本地schema"


def is_local_schema_matched(table_doc: TableDoc) -> bool:
    return table_doc.schema_source.replace("\\", "/") != "database metadata"


def aggregate_by_label(table_docs: list[TableDoc], labels: list[str], label_func) -> list[dict[str, Any]]:
    grouped: dict[str, list[TableDoc]] = defaultdict(list)
    for table_doc in table_docs:
        grouped[label_func(table_doc)].append(table_doc)

    rows: list[dict[str, Any]] = []
    for label in labels:
        docs = grouped.get(label, [])
        if not docs:
            continue
        row_count = sum(table_doc.row_count for table_doc in docs)
        column_count = sum(len(table_doc.columns) for table_doc in docs)
        max_table = max(docs, key=lambda table_doc: table_doc.row_count)
        rows.append(
            {
                "label": label,
                "table_count": len(docs),
                "row_count": row_count,
                "column_count": column_count,
                "avg_columns": column_count / len(docs),
                "max_table": max_table.name,
            }
        )
    return rows


def aggregate_row_buckets(table_docs: list[TableDoc]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for label, min_rows, max_rows in ROW_BUCKETS:
        docs = [
            table_doc
            for table_doc in table_docs
            if table_doc.row_count >= min_rows and (max_rows is None or table_doc.row_count < max_rows)
        ]
        rows.append(
            {
                "label": label,
                "table_count": len(docs),
                "row_count": sum(table_doc.row_count for table_doc in docs),
            }
        )
    return rows


def markdown_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    def escape(value: Any) -> str:
        return str(value).replace("|", "\\|")

    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(escape(value) for value in row) + " |")
    return lines


def display_width(value: Any) -> int:
    text = str(value)
    width = 0
    for char in text:
        width += 2 if unicodedata.east_asian_width(char) in {"F", "W"} else 1
    return width


def pad_display(value: Any, width: int, align: str = "left") -> str:
    text = str(value)
    padding = max(width - display_width(text), 0)
    if align == "right":
        return " " * padding + text
    if align == "center":
        left = padding // 2
        return " " * left + text + " " * (padding - left)
    return text + " " * padding


def text_table(headers: list[str], rows: list[list[Any]], aligns: list[str] | None = None) -> list[str]:
    text_rows = [[str(value) for value in row] for row in rows]
    widths = [
        max([display_width(headers[index])] + [display_width(row[index]) for row in text_rows])
        for index in range(len(headers))
    ]
    aligns = aligns or ["left"] * len(headers)

    def border(left: str, middle: str, right: str) -> str:
        return left + middle.join("─" * (width + 2) for width in widths) + right

    def row_line(row: list[str], row_aligns: list[str]) -> str:
        cells = [
            f" {pad_display(value, widths[index], row_aligns[index])} "
            for index, value in enumerate(row)
        ]
        return "│" + "│".join(cells) + "│"

    lines = [border("┌", "┬", "┐")]
    lines.append(row_line(headers, ["center"] * len(headers)))
    lines.append(border("├", "┼", "┤"))
    for row in text_rows:
        lines.append(row_line(row, aligns))
    lines.append(border("└", "┴", "┘"))
    return lines


def build_stats_sections(table_docs: list[TableDoc]) -> dict[str, Any]:
    total_rows = sum(table_doc.row_count for table_doc in table_docs)
    total_columns = sum(len(table_doc.columns) for table_doc in table_docs)
    max_row_table = max(table_docs, key=lambda table_doc: table_doc.row_count) if table_docs else None
    max_column_table = max(table_docs, key=lambda table_doc: len(table_doc.columns)) if table_docs else None
    matched_count = sum(1 for table_doc in table_docs if is_local_schema_matched(table_doc))
    top_tables = sorted(table_docs, key=lambda table_doc: table_doc.row_count, reverse=True)[:15]
    unmatched_tables = [table_doc for table_doc in table_docs if not is_local_schema_matched(table_doc)]

    return {
        "total_rows": total_rows,
        "total_columns": total_columns,
        "avg_rows": int(total_rows / len(table_docs)) if table_docs else 0,
        "avg_columns": total_columns / len(table_docs) if table_docs else 0,
        "max_row_table": max_row_table,
        "max_column_table": max_column_table,
        "matched_count": matched_count,
        "layer_rows": aggregate_by_label(table_docs, LAYER_ORDER, table_layer),
        "topic_rows": aggregate_by_label(table_docs, TOPIC_ORDER, table_topic),
        "bucket_rows": aggregate_row_buckets(table_docs),
        "top_tables": top_tables,
        "unmatched_tables": unmatched_tables,
    }


def format_sample(sample: pd.DataFrame) -> list[str]:
    if sample.empty:
        return ["    无样例数据"]

    display_sample = sample.copy()
    for column in display_sample.columns:
        display_sample[column] = display_sample[column].map(lambda value: str(value)[:80] if value is not None else "")

    table_text = display_sample.to_string(index=False, max_colwidth=80)
    return [f"    {line}" for line in table_text.splitlines()]


def render_report(
    settings: TushareIntegrationSettings,
    table_docs: list[TableDoc],
    include_types: bool,
    include_empty: bool,
    generated_at: str,
) -> str:
    total_rows = sum(table_doc.row_count for table_doc in table_docs)

    lines = [
        "已下载数据表清单（非 RAW 表）",
        "============================================================",
        f"生成时间：{generated_at}",
        f"数据库：{build_database_label(settings)}",
        f"统计范围：{build_scope(include_empty)}",
        f"表数量：{len(table_docs)} 张",
        f"总数据量：{format_number(total_rows)} 行",
        "",
        "一、表清单总览",
        "------------------------------------------------------------",
    ]

    for index, table_doc in enumerate(table_docs, start=1):
        lines.append(
            f"{index:02d}. {table_doc.name}｜{table_doc.comment or '无表说明'}｜"
            f"{format_number(table_doc.row_count)} 行"
        )

    lines.extend(
        [
            "",
            "二、字段明细",
            "============================================================",
        ]
    )

    for index, table_doc in enumerate(table_docs, start=1):
        lines.extend(
            [
                "",
                "------------------------------------------------------------",
                f"{index:02d}. {table_doc.name}",
                f"表说明：{table_doc.comment or '无表说明'}",
                f"数据量：{format_number(table_doc.row_count)} 行",
                f"字段数量：{len(table_doc.columns)} 个",
                f"结构来源：{table_doc.schema_source}",
                "字段清单：",
            ]
        )

        if not table_doc.columns:
            lines.append("    无字段信息")
        else:
            for column_index, column in enumerate(table_doc.columns, start=1):
                column_name = column.get("name", "")
                column_comment = normalize_comment(column.get("comment", ""))
                if include_types and column.get("data_type"):
                    lines.append(
                        f"    {column_index:02d}. {column_name}（{column.get('data_type')}）：{column_comment}"
                    )
                else:
                    lines.append(f"    {column_index:02d}. {column_name}：{column_comment}")

        if table_doc.sample is not None:
            lines.append("样例数据：")
            lines.extend(format_sample(table_doc.sample))

    lines.append("")
    return "\n".join(lines)


def render_stats_markdown(
    settings: TushareIntegrationSettings,
    table_docs: list[TableDoc],
    include_empty: bool,
    generated_at: str,
    source_path: Path,
    output_path: Path,
) -> str:
    stats = build_stats_sections(table_docs)
    total_rows = stats["total_rows"]
    max_row_table = stats["max_row_table"]
    max_column_table = stats["max_column_table"]

    basic_rows = [
        ["生成时间", generated_at],
        ["数据库", build_database_label(settings)],
        ["统计范围", build_scope(include_empty)],
        ["表数量", f"{len(table_docs)} 张"],
        ["总数据量", f"{format_number(total_rows)} 行"],
        ["字段总数", f"{format_number(stats['total_columns'])} 个"],
        ["平均每表行数", f"{format_number(stats['avg_rows'])} 行"],
        ["平均每表字段数", f"{stats['avg_columns']:.1f} 个"],
        [
            "最大数据表",
            f"{max_row_table.name}（{format_number(max_row_table.row_count)} 行）" if max_row_table else "无",
        ],
        [
            "字段最多表",
            f"{max_column_table.name}（{format_number(len(max_column_table.columns))} 个字段）"
            if max_column_table
            else "无",
        ],
        ["已匹配本地schema", f"{stats['matched_count']} 张"],
        ["未匹配本地schema", f"{len(table_docs) - stats['matched_count']} 张"],
    ]

    lines = [
        "# 已下载数据表统计概览",
        "",
        f"- **来源文件**：{source_path.name}",
        f"- **输出文件**：{output_path.name}",
        "- **说明**：本文件与明细清单由同一次数据库扫描生成。",
        "",
        "## 一、基础信息",
        "",
    ]
    lines.extend(markdown_table(["指标", "数值"], basic_rows))

    layer_rows = [
        [
            row["label"],
            row["table_count"],
            format_number(row["row_count"]),
            format_percent(row["row_count"], total_rows),
            format_number(row["column_count"]),
            f"{row['avg_columns']:.1f}",
        ]
        for row in stats["layer_rows"]
    ]
    lines.extend(["", "## 二、分层统计", ""])
    lines.extend(markdown_table(["层级", "表数", "行数", "占比", "字段数", "平均字段"], layer_rows))

    topic_rows = [
        [
            row["label"],
            row["table_count"],
            format_number(row["row_count"]),
            format_percent(row["row_count"], total_rows),
            row["max_table"],
        ]
        for row in stats["topic_rows"]
    ]
    lines.extend(["", "## 三、主题统计", ""])
    lines.extend(markdown_table(["主题", "表数", "行数", "占比", "最大表"], topic_rows))

    bucket_rows = [
        [
            row["label"],
            row["table_count"],
            format_number(row["row_count"]),
            format_percent(row["row_count"], total_rows),
        ]
        for row in stats["bucket_rows"]
    ]
    lines.extend(["", "## 四、数据量区间", ""])
    lines.extend(markdown_table(["区间", "表数", "行数", "占比"], bucket_rows))

    top_rows = [
        [
            index,
            table_doc.name,
            truncate_text(table_doc.comment or "无表说明", 18),
            format_number(table_doc.row_count),
            format_percent(table_doc.row_count, total_rows),
            len(table_doc.columns),
        ]
        for index, table_doc in enumerate(stats["top_tables"], start=1)
    ]
    lines.extend(["", "## 五、Top 15 数据量", ""])
    lines.extend(markdown_table(["排名", "表名", "说明", "行数", "占比", "字段"], top_rows))

    table_rows = [
        [
            index,
            table_doc.name,
            table_layer(table_doc),
            table_topic(table_doc),
            format_number(table_doc.row_count),
            format_percent(table_doc.row_count, total_rows),
            len(table_doc.columns),
            schema_label(table_doc),
        ]
        for index, table_doc in enumerate(table_docs, start=1)
    ]
    lines.extend(["", "## 六、完整表清单", ""])
    lines.extend(markdown_table(["序号", "表名", "层级", "主题", "行数", "占比", "字段", "Schema"], table_rows))

    unmatched_rows = [
        [table_doc.name, format_number(table_doc.row_count), len(table_doc.columns), table_doc.comment or "无表说明"]
        for table_doc in stats["unmatched_tables"]
    ]
    if unmatched_rows:
        lines.extend(["", "## 七、未匹配本地 schema 的表", ""])
        lines.extend(markdown_table(["表名", "行数", "字段", "说明"], unmatched_rows))

    lines.append("")
    return "\n".join(lines)


def render_stats_text(
    settings: TushareIntegrationSettings,
    table_docs: list[TableDoc],
    include_empty: bool,
    generated_at: str,
    source_path: Path,
    output_path: Path,
) -> str:
    stats = build_stats_sections(table_docs)
    total_rows = stats["total_rows"]
    max_row_table = stats["max_row_table"]
    max_column_table = stats["max_column_table"]

    basic_rows = [
        ["生成时间", generated_at],
        ["数据库", build_database_label(settings)],
        ["统计范围", build_scope(include_empty)],
        ["表数量", f"{len(table_docs)} 张"],
        ["总数据量", f"{format_number(total_rows)} 行"],
        ["字段总数", f"{format_number(stats['total_columns'])} 个"],
        ["平均每表行数", f"{format_number(stats['avg_rows'])} 行"],
        ["平均每表字段数", f"{stats['avg_columns']:.1f} 个"],
        [
            "最大数据表",
            f"{max_row_table.name}（{format_number(max_row_table.row_count)} 行）" if max_row_table else "无",
        ],
        [
            "字段最多表",
            f"{max_column_table.name}（{format_number(len(max_column_table.columns))} 个字段）"
            if max_column_table
            else "无",
        ],
        ["已匹配本地schema", f"{stats['matched_count']} 张"],
        ["未匹配本地schema", f"{len(table_docs) - stats['matched_count']} 张"],
    ]

    lines = [
        "已下载数据表统计概览",
        "========================================================================",
        f"来源文件：{source_path.name}",
        f"输出文件：{output_path.name}",
        "说明：本文件与明细清单由同一次数据库扫描生成。",
        "",
        "一、基础信息",
        "------------------------------------------------------------------------",
    ]
    lines.extend(text_table(["指标", "数值"], basic_rows))

    layer_rows = [
        [
            row["label"],
            row["table_count"],
            format_number(row["row_count"]),
            format_percent(row["row_count"], total_rows),
            format_number(row["column_count"]),
            f"{row['avg_columns']:.1f}",
        ]
        for row in stats["layer_rows"]
    ]
    lines.extend(["", "二、分层统计", "------------------------------------------------------------------------"])
    lines.extend(
        text_table(
            ["层级", "表数", "行数", "占比", "字段数", "平均字段"],
            layer_rows,
            ["left", "right", "right", "right", "right", "right"],
        )
    )

    topic_rows = [
        [
            row["label"],
            row["table_count"],
            format_number(row["row_count"]),
            format_percent(row["row_count"], total_rows),
            row["max_table"],
        ]
        for row in stats["topic_rows"]
    ]
    lines.extend(["", "三、主题统计", "------------------------------------------------------------------------"])
    lines.extend(
        text_table(
            ["主题", "表数", "行数", "占比", "最大表"],
            topic_rows,
            ["left", "right", "right", "right", "left"],
        )
    )

    bucket_rows = [
        [
            row["label"],
            row["table_count"],
            format_number(row["row_count"]),
            format_percent(row["row_count"], total_rows),
        ]
        for row in stats["bucket_rows"]
    ]
    lines.extend(["", "四、数据量区间", "------------------------------------------------------------------------"])
    lines.extend(text_table(["区间", "表数", "行数", "占比"], bucket_rows, ["left", "right", "right", "right"]))

    top_rows = [
        [
            index,
            table_doc.name,
            truncate_text(table_doc.comment or "无表说明", 18),
            format_number(table_doc.row_count),
            format_percent(table_doc.row_count, total_rows),
            len(table_doc.columns),
        ]
        for index, table_doc in enumerate(stats["top_tables"], start=1)
    ]
    lines.extend(["", "五、Top 15 数据量", "------------------------------------------------------------------------"])
    lines.extend(
        text_table(
            ["排名", "表名", "说明", "行数", "占比", "字段"],
            top_rows,
            ["right", "left", "left", "right", "right", "right"],
        )
    )

    table_rows = [
        [
            index,
            table_doc.name,
            table_layer(table_doc),
            table_topic(table_doc),
            format_number(table_doc.row_count),
            format_percent(table_doc.row_count, total_rows),
            len(table_doc.columns),
            schema_label(table_doc),
        ]
        for index, table_doc in enumerate(table_docs, start=1)
    ]
    lines.extend(["", "六、完整表清单", "------------------------------------------------------------------------"])
    lines.extend(
        text_table(
            ["序号", "表名", "层级", "主题", "行数", "占比", "字段", "Schema"],
            table_rows,
            ["right", "left", "left", "left", "right", "right", "right", "left"],
        )
    )

    unmatched_rows = [
        [table_doc.name, format_number(table_doc.row_count), len(table_doc.columns), table_doc.comment or "无表说明"]
        for table_doc in stats["unmatched_tables"]
    ]
    if unmatched_rows:
        lines.extend(
            [
                "",
                "七、未匹配本地 schema 的表",
                "------------------------------------------------------------------------",
            ]
        )
        lines.extend(text_table(["表名", "行数", "字段", "说明"], unmatched_rows, ["left", "right", "right", "left"]))

    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成已下载数据表清单纯文本文档")
    parser.add_argument("--config", default=str(ROOT_DIR / "config.yaml"), help="配置文件路径")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出 txt 文件路径")
    parser.add_argument("--stats-md-output", default=str(DEFAULT_STATS_MD_OUTPUT), help="统计概览 markdown 文件路径")
    parser.add_argument("--stats-txt-output", default=str(DEFAULT_STATS_TXT_OUTPUT), help="统计概览 txt 文件路径")
    parser.add_argument("--include-empty", action="store_true", help="包含 0 行空表")
    parser.add_argument("--include-types", action="store_true", help="字段清单中包含字段类型")
    parser.add_argument("--sample-size", type=int, default=0, help="每张表输出的样例数据行数，默认不输出")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).resolve()
    output_path = Path(args.output).resolve()
    stats_md_output_path = Path(args.stats_md_output).resolve()
    stats_txt_output_path = Path(args.stats_txt_output).resolve()

    settings, table_docs = collect_table_docs(
        config_path=config_path,
        include_empty=args.include_empty,
        sample_size=args.sample_size,
    )
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    report = render_report(
        settings,
        table_docs,
        include_types=args.include_types,
        include_empty=args.include_empty,
        generated_at=generated_at,
    )
    stats_md_report = render_stats_markdown(
        settings,
        table_docs,
        include_empty=args.include_empty,
        generated_at=generated_at,
        source_path=output_path,
        output_path=stats_md_output_path,
    )
    stats_txt_report = render_stats_text(
        settings,
        table_docs,
        include_empty=args.include_empty,
        generated_at=generated_at,
        source_path=output_path,
        output_path=stats_txt_output_path,
    )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    stats_md_output_path.parent.mkdir(parents=True, exist_ok=True)
    stats_md_output_path.write_text(stats_md_report, encoding="utf-8")
    stats_txt_output_path.parent.mkdir(parents=True, exist_ok=True)
    stats_txt_output_path.write_text(stats_txt_report, encoding="utf-8")
    print(f"文档已生成：{output_path}")
    print(f"统计 Markdown 已生成：{stats_md_output_path}")
    print(f"统计 TXT 已生成：{stats_txt_output_path}")
    print(f"表数量：{len(table_docs)}")


if __name__ == "__main__":
    main()
