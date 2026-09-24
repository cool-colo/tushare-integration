#!/usr/bin/env python3
"""Rebuild report_rc with a key that preserves every source report row.

The append-only raw table is the source of truth. For each complete report
identity, this migration keeps the most recently ingested values and retains
the previous latest table as a timestamped backup.
"""

from __future__ import annotations

import argparse
import datetime
from pathlib import Path

import yaml

from tushare_integration.db_engine import DatabaseEngineFactory
from tushare_integration.settings import TushareIntegrationSettings
from tushare_integration.storage import build_latest_schema


ROOT_DIR = Path(__file__).resolve().parent.parent
SCHEMA_PATH = ROOT_DIR / "tushare_integration/schema/stock/special/report_rc.yaml"
EXPECTED_SORTING_KEY = (
    "ts_code, report_date, org_name, report_title, author_name, quarter, "
    "report_type, classify, create_time"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Perform the migration. Without this flag only the current table definition is inspected.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = yaml.safe_load((ROOT_DIR / "config.yaml").read_text(encoding="utf-8"))
    settings = TushareIntegrationSettings.model_validate(config)
    if settings.database.db_type != "clickhouse":
        raise RuntimeError("This migration currently supports ClickHouse only")

    db = DatabaseEngineFactory.create(settings, clickhouse_send_receive_timeout=1200)
    db_name = settings.database.db_name
    table_info = db.query_df(
        "SELECT sorting_key FROM system.tables "
        f"WHERE database = '{db_name}' AND name = 'report_rc'"
    )
    if table_info.empty:
        raise RuntimeError(f"{db_name}.report_rc does not exist")

    current_sorting_key = str(table_info.iloc[0]["sorting_key"])
    print(f"Current sorting key: {current_sorting_key}")
    if current_sorting_key == EXPECTED_SORTING_KEY:
        print("report_rc already uses the complete row-level key; nothing to migrate")
        return
    if not args.execute:
        print("Migration required; rerun with --execute")
        return

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    staging_table = f"report_rc_rebuild_{stamp}"
    backup_table = f"report_rc_backup_before_row_key_{stamp}"
    schema = yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))

    print(f"Creating {db_name}.{staging_table}")
    db.create_table(staging_table, build_latest_schema(schema))
    db.query(
        f"""
        INSERT INTO {db_name}.{staging_table}
        (
            ts_code, name, report_date, report_title, report_type, classify,
            org_name, author_name, quarter, op_rt, op_pr, tp, np, eps, pe,
            rd, roe, ev_ebitda, rating, max_price, min_price, imp_dg,
            create_time, _source, _api_name, _batch_id, _ingest_time,
            _record_hash
        )
        SELECT
            key_ts_code AS ts_code,
            argMax(name, recency) AS name,
            key_report_date AS report_date,
            key_report_title AS report_title,
            key_report_type AS report_type,
            key_classify AS classify,
            key_org_name AS org_name,
            key_author_name AS author_name,
            key_quarter AS quarter,
            argMax(op_rt, recency) AS op_rt,
            argMax(op_pr, recency) AS op_pr,
            argMax(tp, recency) AS tp,
            argMax(np, recency) AS np,
            argMax(eps, recency) AS eps,
            argMax(pe, recency) AS pe,
            argMax(rd, recency) AS rd,
            argMax(roe, recency) AS roe,
            argMax(ev_ebitda, recency) AS ev_ebitda,
            argMax(rating, recency) AS rating,
            argMax(max_price, recency) AS max_price,
            argMax(min_price, recency) AS min_price,
            argMax(imp_dg, recency) AS imp_dg,
            key_create_time AS create_time,
            argMax(source, recency) AS _source,
            argMax(api_name, recency) AS _api_name,
            argMax(batch_id, recency) AS _batch_id,
            max(ingest_time) AS _ingest_time,
            argMax(record_hash, recency) AS _record_hash
        FROM
        (
            SELECT
                ifNull(ts_code, '') AS key_ts_code,
                ifNull(name, '') AS name,
                ifNull(report_date, toDate32('1970-01-01')) AS key_report_date,
                ifNull(report_title, '') AS key_report_title,
                ifNull(report_type, '') AS key_report_type,
                ifNull(classify, '') AS key_classify,
                ifNull(org_name, '') AS key_org_name,
                ifNull(author_name, '') AS key_author_name,
                ifNull(quarter, '') AS key_quarter,
                ifNull(op_rt, 0.) AS op_rt,
                ifNull(op_pr, 0.) AS op_pr,
                ifNull(tp, 0.) AS tp,
                ifNull(np, 0.) AS np,
                ifNull(eps, 0.) AS eps,
                ifNull(pe, 0.) AS pe,
                ifNull(rd, 0.) AS rd,
                ifNull(roe, 0.) AS roe,
                ifNull(ev_ebitda, 0.) AS ev_ebitda,
                ifNull(rating, '') AS rating,
                ifNull(max_price, 0.) AS max_price,
                ifNull(min_price, 0.) AS min_price,
                ifNull(imp_dg, '') AS imp_dg,
                ifNull(create_time, toDateTime64('1970-01-01 00:00:00', 3)) AS key_create_time,
                _source AS source,
                _api_name AS api_name,
                _batch_id AS batch_id,
                _ingest_time AS ingest_time,
                _record_hash AS record_hash,
                tuple(_ingest_time, _batch_id, _record_hash) AS recency
            FROM {db_name}.report_rc_raw
        ) AS src
        GROUP BY
            key_ts_code, key_report_date, key_org_name, key_report_title,
            key_author_name, key_quarter, key_report_type, key_classify,
            key_create_time
        """
    )

    validation = db.query_df(
        f"""
        SELECT
            count() AS row_count,
            uniqExact(tuple(
                ts_code, report_date, org_name, report_title, author_name,
                quarter, report_type, classify, create_time
            )) AS unique_keys
        FROM {db_name}.{staging_table}
        """
    ).iloc[0]
    row_count = int(validation["row_count"])
    unique_keys = int(validation["unique_keys"])
    if row_count == 0 or unique_keys != row_count:
        raise RuntimeError(
            f"Refusing to publish invalid rebuild: row_count={row_count}, unique_keys={unique_keys}; "
            f"staging table retained as {staging_table}"
        )

    print(f"Publishing {row_count:,} unique report forecast rows")
    db.query(f"EXCHANGE TABLES {db_name}.report_rc AND {db_name}.{staging_table}")
    db.query(f"RENAME TABLE {db_name}.{staging_table} TO {db_name}.{backup_table}")
    print(f"Migration complete; previous table retained as {db_name}.{backup_table}")


if __name__ == "__main__":
    main()
