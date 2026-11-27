"""Small authenticated ODS/DWD smoke test in a disposable ClickHouse database.

Run inside the RiceQuant image with the repository mounted read-only. No
production table is written; only the database created by this process is dropped.
"""
from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date
import json
from time import monotonic
import uuid

import pandas as pd

from ricequant_integration.client import RqDataClient
from ricequant_integration.runner import RiceQuantRunner
from ricequant_integration.settings import RiceQuantSettings
from ricequant_integration.storage import RiceQuantStorage
from ricequant_integration.transform import dividend_frame
from tushare_integration.db_engine import ClickhouseEngine
from tushare_integration.dwd import DWDManager


class RecordingClient(RqDataClient):
    def __init__(self, token):
        super().__init__(token)
        self.expected = {}

    def stock_dividend_info(self, order_book_ids, start, end):
        raw = super().stock_dividend_info(order_book_ids, start, end)
        frame = dividend_frame(raw, "source-verification")
        for identifier in order_book_ids:
            self.expected[identifier] = frame.loc[frame.order_book_id == identifier]
        return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="ricequant.yaml")
    parser.add_argument("--start", default="2015-01-01")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--instrument", action="append", dest="instruments")
    args = parser.parse_args()
    original = RiceQuantSettings.load(args.config)
    admin = RiceQuantStorage(original.database)
    database = "rq_dividend_verify_" + uuid.uuid4().hex
    instruments = args.instruments or ["000001.XSHE", "600519.XSHG", "000002.XSHE", "000502.XSHE"]
    settings = replace(original, database=replace(original.database, database=database),
                       stock_dividend_batch_size=2)
    admin.client.command(f"CREATE DATABASE `{database}`")
    started = monotonic()
    try:
        client = RecordingClient(settings.token)
        storage = RiceQuantStorage(settings.database)
        counts = []
        quota_before = None
        for _ in range(2):
            runner = RiceQuantRunner(settings, client=client, storage=storage)
            runner.initialize()
            if quota_before is None:
                quota_before = client.quota().bytes_used
            summary = runner.run("backfill", ["stock_dividend_info"],
                                 date.fromisoformat(args.start), date.fromisoformat(args.end),
                                 instruments=instruments)
            if summary.status != "complete":
                raise RuntimeError(f"smoke test stopped: {summary.status}: {summary.message}")
            actual = storage.table_frame("ricequant_stock_dividend_info")
            assert not actual.duplicated(["order_book_id", "effective_date", "sequence_num"]).any()
            for identifier, expected in client.expected.items():
                subset = actual.loc[actual.order_book_id == identifier]
                actual_hashes = sorted(
                    value.decode("ascii") if isinstance(value, bytes) else value
                    for value in subset._record_hash.tolist()
                )
                expected_hashes = sorted(expected._record_hash.tolist())
                assert actual_hashes == expected_hashes, (
                    identifier, len(subset), len(expected), actual_hashes[:1], expected_hashes[:1]
                )
            counts.append(len(actual))
        assert counts[0] == counts[1]

        manager = DWDManager()
        manager.settings = manager.settings.model_copy(update={"database":
            manager.settings.database.model_copy(update={
                "db_name": database, "db_type": "clickhouse", "host": settings.database.host,
                "port": settings.database.port, "user": settings.database.user,
                "password": settings.database.password,
            })})
        manager.db_engine = ClickhouseEngine(manager.settings)
        manager.sync_table("dwd_ricequant_stock_dividend_info", validation_mode="strict")
        dwd = storage.table_frame("dwd_ricequant_stock_dividend_info")
        assert len(dwd) == counts[1]
        assert set(dwd.source) <= {"ricequant"}
        assert dwd.loc[dwd.info_date.isna(), "available_trade_date"].isna().all()
        calendar = storage.table_frame("ricequant_trading_calendar")
        trading_days = sorted(set(calendar.loc[calendar.is_trading_day == 1, "calendar_date"].dt.date))
        calendar_days = set(calendar.calendar_date.dt.date)
        for row in dwd.itertuples(index=False):
            if pd.isna(row.info_date):
                continue
            announcement = row.info_date.date()
            expected = (next((day for day in trading_days if day > announcement), None)
                        if announcement in calendar_days else None)
            actual_date = None if pd.isna(row.available_trade_date) else row.available_trade_date.date()
            assert actual_date == expected
        print(json.dumps({
            "instruments": instruments, "ods_rows": counts[1], "dwd_rows": len(dwd),
            "quota_bytes": max(0, client.quota().bytes_used - quota_before),
            "elapsed_seconds": round(monotonic() - started, 1),
            "checks": "source hashes, repeat download, unique keys, DWD strict validation, next-trading-day availability",
        }, ensure_ascii=False))
    finally:
        # Exact identifier generated and created above; never a production DB.
        admin.client.command(f"DROP DATABASE `{database}` SYNC")
        print(f"Removed disposable verification database: {database}")


if __name__ == "__main__":
    main()
