from __future__ import annotations

import datetime
from pathlib import Path

import pandas as pd
import yaml

from tushare_integration.db_engine import DBEngine
from tushare_integration.settings import TushareIntegrationSettings


class CyqChipsProgressStore:
    """Persist only query windows whose pages have all been successfully stored."""

    WINDOWS_TABLE_NAME = "cyq_chips_completed_windows"
    SCHEMA_PATH = Path(__file__).parent / "schema" / "system" / "cyq_chips_completed_windows.yaml"

    def __init__(self, settings: TushareIntegrationSettings):
        self.settings = settings
        with self.SCHEMA_PATH.open("r", encoding="utf-8") as schema_file:
            self.windows_schema = yaml.safe_load(schema_file)

    def ensure_table(self, conn: DBEngine) -> None:
        conn.create_table(self.WINDOWS_TABLE_NAME, self.windows_schema)

    def get_completed_windows(self, conn: DBEngine, ts_code: str) -> list[tuple[datetime.date, datetime.date]]:
        data = conn.query_df(
            f"SELECT DISTINCT start_date, end_date "
            f"FROM {self.settings.database.db_name}.{self.WINDOWS_TABLE_NAME} "
            f"WHERE ts_code = {self._quote_string(ts_code)}"
        )
        result = []
        for row in data.itertuples(index=False):
            start = pd.to_datetime(row.start_date, errors="raise").date()
            end = pd.to_datetime(row.end_date, errors="raise").date()
            if pd.isna(start) or pd.isna(end) or start > end:
                raise ValueError(f"Invalid completed cyq_chips window for {ts_code}: {row}")
            result.append((start, end))
        return result

    def complete_window(self, conn: DBEngine, ts_code: str, start_date, end_date) -> None:
        data = pd.DataFrame([{
            "ts_code": ts_code,
            "start_date": start_date,
            "end_date": end_date,
            "completed_at": datetime.datetime.now(),
        }])
        conn.upsert(self.WINDOWS_TABLE_NAME, self.windows_schema, data)

    @staticmethod
    def _quote_string(value: str) -> str:
        return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"
