#!/usr/bin/env python3
"""Rebuild share_float with its shareholder-level ClickHouse sorting key.

The source raw table is append-only.  This migration keeps the newest value
seen for every complete business key and preserves the old table as a backup.
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
SCHEMA_PATH = ROOT_DIR / "tushare_integration/schema/stock/market/share_float.yaml"
EXPECTED_SORTING_KEY = "ts_code, ann_date, float_date, holder_name, share_type"


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
        f"WHERE database = '{db_name}' AND name = 'share_float'"
    )
    if table_info.empty:
        raise RuntimeError(f"{db_name}.share_float does not exist")

    current_sorting_key = str(table_info.iloc[0]["sorting_key"])
    print(f"Current sorting key: {current_sorting_key}")
    if current_sorting_key == EXPECTED_SORTING_KEY:
        print("share_float already uses the shareholder-level key; nothing to migrate")
        return
    if not args.execute:
        print("Migration required; rerun with --execute")
        return

    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    staging_table = f"share_float_rebuild_{stamp}"
    backup_table = f"share_float_backup_before_holder_key_{stamp}"
    schema = yaml.safe_load(SCHEMA_PATH.read_text(encoding="utf-8"))

    print(f"Creating {db_name}.{staging_table}")
    db.create_table(staging_table, build_latest_schema(schema))
    db.query(
        f"""
        INSERT INTO {db_name}.{staging_table}
        (
            ts_code, ann_date, float_date, float_share, float_ratio,
            holder_name, share_type, _source, _api_name, _batch_id,
            _ingest_time, _record_hash
        )
        SELECT
            key_ts_code AS ts_code,
            key_ann_date AS ann_date,
            key_float_date AS float_date,
            argMax(value_float_share, tuple(ingest_time, batch_id, record_hash)) AS float_share,
            argMax(value_float_ratio, tuple(ingest_time, batch_id, record_hash)) AS float_ratio,
            key_holder_name AS holder_name,
            key_share_type AS share_type,
            argMax(source, tuple(ingest_time, batch_id, record_hash)) AS _source,
            argMax(api_name, tuple(ingest_time, batch_id, record_hash)) AS _api_name,
            argMax(batch_id, tuple(ingest_time, batch_id, record_hash)) AS _batch_id,
            max(ingest_time) AS _ingest_time,
            argMax(record_hash, tuple(ingest_time, batch_id, record_hash)) AS _record_hash
        FROM
        (
            SELECT
                ifNull(ts_code, '') AS key_ts_code,
                ifNull(ann_date, toDate32('1970-01-01')) AS key_ann_date,
                ifNull(float_date, toDate32('1970-01-01')) AS key_float_date,
                ifNull(float_share, 0.) AS value_float_share,
                ifNull(float_ratio, 0.) AS value_float_ratio,
                ifNull(holder_name, '') AS key_holder_name,
                ifNull(share_type, '') AS key_share_type,
                _source AS source,
                _api_name AS api_name,
                _batch_id AS batch_id,
                _ingest_time AS ingest_time,
                _record_hash AS record_hash
            FROM {db_name}.share_float_raw
        ) AS src
        GROUP BY key_ts_code, key_ann_date, key_float_date, key_holder_name, key_share_type
        """
    )

    validation = db.query_df(
        f"""
        SELECT
            count() AS row_count,
            uniqExact(tuple(ts_code, ann_date, float_date, holder_name, share_type)) AS unique_keys
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

    print(f"Publishing {row_count:,} unique shareholder rows")
    db.query(f"EXCHANGE TABLES {db_name}.share_float AND {db_name}.{staging_table}")
    db.query(f"RENAME TABLE {db_name}.{staging_table} TO {db_name}.{backup_table}")
    print(f"Migration complete; previous table retained as {db_name}.{backup_table}")


if __name__ == "__main__":
    main()
