#!/usr/bin/env python3
"""Import the Taobao daily broker-forecast Parquet archive into ClickHouse.

The importer preserves every source row. It performs an atomic initial publish,
keeps source-file lineage, and computes a ClickHouse-side content hash without
using that hash to collapse records.
"""

from __future__ import annotations

import argparse
import datetime
import io
import re
import uuid
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd
import yaml

from tushare_integration.db_engine import DatabaseEngineFactory
from tushare_integration.settings import TushareIntegrationSettings


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = Path(
    "/nfs_data/peng.wang/quant/QuantGenesis/risk-manager/brokerage/1d_broker_forecast"
)
DEFAULT_TABLE = "stock_research_report_taobao"
SOURCE_NAME = "taobao_1d_broker_forecast"
BUSINESS_COLUMNS = [
    "code",
    "name",
    "report_date",
    "report_title",
    "report_type",
    "classify",
    "org_name",
    "author_name",
    "quarter",
    "op_rt",
    "op_pr",
    "tp",
    "np",
    "eps",
    "pe",
    "rd",
    "roe",
    "ev_ebitda",
    "rating",
    "max_price",
    "min_price",
    "imp_dg",
    "create_time",
]
REQUIRED_STRING_COLUMNS = [
    "code",
    "name",
    "report_title",
    "classify",
    "org_name",
]
NULLABLE_STRING_COLUMNS = ["report_type", "author_name", "quarter", "rating", "imp_dg"]
NUMERIC_COLUMNS = [
    "op_rt",
    "op_pr",
    "tp",
    "np",
    "eps",
    "pe",
    "rd",
    "roe",
    "ev_ebitda",
    "max_price",
    "min_price",
]
DATE_FILE_RE = re.compile(r"^(\d{8})\.parquet$")


@dataclass(frozen=True)
class SourceFile:
    source_name: str
    file_date: datetime.date
    path: Path
    member_name: str | None = None

    def read(self) -> pd.DataFrame:
        if self.member_name is None:
            return pd.read_parquet(self.path)
        with zipfile.ZipFile(self.path) as archive:
            return pd.read_parquet(io.BytesIO(archive.read(self.member_name)))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--table", default=DEFAULT_TABLE)
    parser.add_argument("--chunk-rows", type=int, default=100_000)
    return parser.parse_args()


def parse_file_date(name: str) -> datetime.date:
    match = DATE_FILE_RE.match(Path(name).name)
    if not match:
        raise ValueError(f"Unexpected source filename: {name}")
    return datetime.datetime.strptime(match.group(1), "%Y%m%d").date()


def discover_source_files(source_dir: Path) -> list[SourceFile]:
    source_files: list[SourceFile] = []
    for archive_path in sorted(source_dir.glob("*.zip")):
        with zipfile.ZipFile(archive_path) as archive:
            for member_name in sorted(name for name in archive.namelist() if name.endswith(".parquet")):
                source_files.append(
                    SourceFile(
                        source_name=f"{archive_path.name}!/{member_name}",
                        file_date=parse_file_date(member_name),
                        path=archive_path,
                        member_name=member_name,
                    )
                )
    for parquet_path in sorted(source_dir.glob("*/*.parquet")):
        source_files.append(
            SourceFile(
                source_name=str(parquet_path.relative_to(source_dir)),
                file_date=parse_file_date(parquet_path.name),
                path=parquet_path,
            )
        )

    dates: dict[datetime.date, str] = {}
    for source_file in source_files:
        if prior_source := dates.get(source_file.file_date):
            raise ValueError(
                f"Duplicate daily files for {source_file.file_date}: "
                f"{prior_source} and {source_file.source_name}"
            )
        dates[source_file.file_date] = source_file.source_name
    if not source_files:
        raise ValueError(f"No Parquet source files found below {source_dir}")
    return source_files


def normalize_frame(
    frame: pd.DataFrame,
    source_file: SourceFile,
    ingest_time: datetime.datetime,
    batch_id: str,
) -> pd.DataFrame:
    if list(frame.columns) != BUSINESS_COLUMNS:
        raise ValueError(
            f"Unexpected columns in {source_file.source_name}: "
            f"expected={BUSINESS_COLUMNS}, actual={list(frame.columns)}"
        )

    normalized = frame.copy()
    for column in REQUIRED_STRING_COLUMNS:
        if normalized[column].isna().any():
            raise ValueError(f"Required column {column} is null in {source_file.source_name}")
        normalized[column] = normalized[column].astype(str)
    for column in NULLABLE_STRING_COLUMNS:
        normalized[column] = normalized[column].map(lambda value: None if pd.isna(value) else str(value))

    report_dates = pd.to_datetime(normalized["report_date"], format="%Y%m%d", errors="coerce")
    if report_dates.isna().any():
        raise ValueError(f"Invalid report_date in {source_file.source_name}")
    if not (report_dates.dt.date == source_file.file_date).all():
        raise ValueError(f"report_date differs from filename date in {source_file.source_name}")
    normalized["report_date"] = report_dates.dt.date

    create_times = pd.to_datetime(
        normalized["create_time"], format="%Y-%m-%d %H:%M:%S", errors="coerce"
    )
    if create_times.isna().any():
        raise ValueError(f"Invalid create_time in {source_file.source_name}")
    normalized["create_time"] = create_times

    for column in NUMERIC_COLUMNS:
        values = pd.to_numeric(normalized[column], errors="coerce")
        if np.isinf(values.to_numpy(dtype=float, na_value=np.nan)).any():
            raise ValueError(f"Infinite numeric value in {source_file.source_name}.{column}")
        normalized[column] = values.astype(object).where(values.notna(), None)

    normalized["file_date"] = source_file.file_date
    normalized["_source"] = SOURCE_NAME
    normalized["_source_file"] = source_file.source_name
    normalized["_batch_id"] = batch_id
    normalized["_ingest_time"] = ingest_time
    return normalized


def iter_chunks(
    source_files: list[SourceFile],
    ingest_time: datetime.datetime,
    batch_id: str,
    chunk_rows: int,
) -> Iterator[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    row_count = 0
    for index, source_file in enumerate(source_files, start=1):
        frame = normalize_frame(source_file.read(), source_file, ingest_time, batch_id)
        frames.append(frame)
        row_count += len(frame)
        if row_count >= chunk_rows:
            yield pd.concat(frames, ignore_index=True)
            frames = []
            row_count = 0
        if index % 250 == 0:
            print(f"Read {index:,}/{len(source_files):,} source files", flush=True)
    if frames:
        yield pd.concat(frames, ignore_index=True)


def quote_identifier(value: str) -> str:
    return "`" + value.replace("`", "``") + "`"


def table_ddl(db_name: str, table_name: str) -> str:
    qualified = f"{quote_identifier(db_name)}.{quote_identifier(table_name)}"
    hash_tuple = ", ".join(quote_identifier(column) for column in BUSINESS_COLUMNS)
    return f"""
CREATE TABLE {qualified}
(
    `code` String COMMENT '源侧股票代码',
    `name` String COMMENT '股票名称',
    `report_date` Date32 COMMENT '研报日期',
    `report_title` String COMMENT '报告标题',
    `report_type` Nullable(String) COMMENT '报告类型',
    `classify` String COMMENT '报告分类',
    `org_name` String COMMENT '机构名称',
    `author_name` Nullable(String) COMMENT '作者',
    `quarter` Nullable(String) COMMENT '预测报告期',
    `op_rt` Nullable(Float64) COMMENT '预测营业收入，源文件数值',
    `op_pr` Nullable(Float64) COMMENT '预测营业利润，源文件数值',
    `tp` Nullable(Float64) COMMENT '预测利润总额，源文件数值',
    `np` Nullable(Float64) COMMENT '预测净利润，源文件数值',
    `eps` Nullable(Float64) COMMENT '预测每股收益，源文件数值',
    `pe` Nullable(Float64) COMMENT '预测市盈率，源文件数值',
    `rd` Nullable(Float64) COMMENT '预测股息率，源文件数值',
    `roe` Nullable(Float64) COMMENT '预测净资产收益率，源文件数值',
    `ev_ebitda` Nullable(Float64) COMMENT '预测EV/EBITDA，源文件数值',
    `rating` Nullable(String) COMMENT '卖方评级',
    `max_price` Nullable(Float64) COMMENT '预测最高目标价，源文件数值',
    `min_price` Nullable(Float64) COMMENT '预测最低目标价，源文件数值',
    `imp_dg` Nullable(String) COMMENT '机构关注度',
    `create_time` DateTime64(3) COMMENT '源数据更新时间',
    `file_date` Date32 COMMENT 'Parquet文件日期',
    `_source` LowCardinality(String) COMMENT '数据来源',
    `_source_file` String COMMENT '源归档及文件名',
    `_batch_id` String COMMENT '导入批次ID',
    `_ingest_time` DateTime64(3) COMMENT '导入时间',
    `_record_hash` FixedString(32) MATERIALIZED lower(hex(MD5(toJSONString(tuple({hash_tuple}))))) COMMENT '业务字段内容哈希'
)
ENGINE = MergeTree
PARTITION BY toYear(report_date)
ORDER BY (report_date, code, create_time, _record_hash)
SETTINGS index_granularity = 8192
"""


def main() -> None:
    args = parse_args()
    if args.chunk_rows <= 0:
        raise ValueError("--chunk-rows must be positive")

    source_files = discover_source_files(args.source_dir)
    settings = TushareIntegrationSettings.model_validate(
        yaml.safe_load((ROOT_DIR / "config.yaml").read_text(encoding="utf-8"))
    )
    if settings.database.db_type != "clickhouse":
        raise RuntimeError("This importer currently supports ClickHouse only")

    db = DatabaseEngineFactory.create(settings, clickhouse_send_receive_timeout=1200)
    db_name = settings.database.db_name
    existing = db.query_df(
        "SELECT count() AS table_count FROM system.tables "
        f"WHERE database = '{db_name}' AND name = '{args.table}'"
    )
    if int(existing["table_count"].iloc[0]) > 0:
        raise RuntimeError(f"Refusing to overwrite existing table {db_name}.{args.table}")

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    staging_table = f"{args.table}_import_{stamp}"
    batch_id = f"taobao_import_{stamp}_{uuid.uuid4().hex[:8]}"
    ingest_time = datetime.datetime.now()
    print(
        f"Importing {len(source_files):,} files into {db_name}.{staging_table}; "
        f"batch_id={batch_id}",
        flush=True,
    )
    db.query(table_ddl(db_name, staging_table))

    inserted_rows = 0
    try:
        for chunk_index, chunk in enumerate(
            iter_chunks(source_files, ingest_time, batch_id, args.chunk_rows), start=1
        ):
            db.insert(staging_table, schema={}, data=chunk)
            inserted_rows += len(chunk)
            print(f"Inserted chunk {chunk_index}: total_rows={inserted_rows:,}", flush=True)

        validation = db.query_df(
            f"""
            SELECT
                count() AS row_count,
                uniqExact(_source_file) AS source_files,
                countIf(file_date != report_date) AS file_date_mismatches,
                min(report_date) AS min_report_date,
                max(report_date) AS max_report_date
            FROM {quote_identifier(db_name)}.{quote_identifier(staging_table)}
            """
        ).iloc[0]
        row_count = int(validation["row_count"])
        source_file_count = int(validation["source_files"])
        mismatch_count = int(validation["file_date_mismatches"])
        if row_count != inserted_rows or source_file_count != len(source_files) or mismatch_count:
            raise RuntimeError(
                "Import validation failed: "
                f"inserted_rows={inserted_rows}, stored_rows={row_count}, "
                f"expected_files={len(source_files)}, stored_files={source_file_count}, "
                f"file_date_mismatches={mismatch_count}"
            )

        db.query(
            f"RENAME TABLE {quote_identifier(db_name)}.{quote_identifier(staging_table)} "
            f"TO {quote_identifier(db_name)}.{quote_identifier(args.table)}"
        )
    except Exception:
        print(f"Import failed; staging table retained as {db_name}.{staging_table}", flush=True)
        raise

    print(
        f"Published {db_name}.{args.table}: rows={inserted_rows:,}, "
        f"files={len(source_files):,}, dates={validation['min_report_date']}..{validation['max_report_date']}",
        flush=True,
    )


if __name__ == "__main__":
    main()
