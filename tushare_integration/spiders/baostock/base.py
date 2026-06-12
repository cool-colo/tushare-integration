from __future__ import annotations

import datetime
import logging
import socket
import time
from dataclasses import dataclass
from typing import Any, Callable

import pandas as pd
import scrapy
import yaml

from tushare_integration.db_engine import DatabaseEngineFactory, DBEngine
from tushare_integration.items import TushareIntegrationItem
from tushare_integration.settings import TushareIntegrationSettings
from tushare_integration.spiders.baostock.utils import BAOSTOCK_START_DATE, format_baostock_date, parse_date_value
from tushare_integration.storage import build_latest_schema, build_raw_schema, get_latest_table_name, get_raw_table_name


BAOSTOCK_REQUEST_LOG_TABLE = "baostock_api_request_log"


class BaostockQuotaExceeded(RuntimeError):
    pass


class BaostockRequestFailed(RuntimeError):
    pass


BAOSTOCK_REQUEST_LOG_SCHEMA = {
    "comment": "Baostock API request quota log",
    "primary_key": [],
    "partition_key": ["toYYYYMM(request_date)"],
    "indexes": [{"name": "baostock_api_request_log_idx", "columns": ["request_date", "api_name"]}],
    "columns": [
        {"name": "request_date", "data_type": "date", "comment": "Request date"},
        {"name": "requested_at", "data_type": "datetime", "comment": "Request timestamp"},
        {"name": "source", "data_type": "str", "length": 32, "comment": "Source system"},
        {"name": "api_name", "data_type": "str", "length": 128, "comment": "Baostock API name"},
        {"name": "spider_name", "data_type": "str", "length": 128, "comment": "Spider name"},
        {"name": "batch_id", "data_type": "str", "length": 64, "comment": "Batch id"},
        {"name": "request_count", "data_type": "int", "comment": "Reserved request count"},
    ],
}


@dataclass
class BaostockDailyQuota:
    db_engine: DBEngine
    settings: TushareIntegrationSettings
    spider_name: str
    batch_id: str
    limit: int

    def __post_init__(self):
        self.request_date = datetime.date.today()
        self.used_count = self._load_used_count()

    def _load_used_count(self) -> int:
        if self.limit <= 0:
            return 0
        db_name = self.settings.database.db_name
        data = self.db_engine.query_df(
            f"""
            SELECT coalesce(sum(request_count), 0) AS used_count
            FROM {db_name}.{BAOSTOCK_REQUEST_LOG_TABLE}
            WHERE request_date = '{self.request_date.isoformat()}'
            """
        )
        if data.empty:
            return 0
        return int(data["used_count"].iloc[0] or 0)

    @property
    def remaining(self) -> int | None:
        if self.limit <= 0:
            return None
        return max(0, self.limit - self.used_count)

    def reserve(self, api_name: str) -> None:
        if self.limit <= 0:
            return
        if self.used_count >= self.limit:
            raise BaostockQuotaExceeded(
                f"Baostock daily request limit reached: used={self.used_count}, limit={self.limit}, "
                f"date={self.request_date.isoformat()}"
            )

        now = datetime.datetime.now()
        self.db_engine.insert(
            BAOSTOCK_REQUEST_LOG_TABLE,
            BAOSTOCK_REQUEST_LOG_SCHEMA,
            pd.DataFrame(
                [
                    {
                        "request_date": self.request_date,
                        "requested_at": now,
                        "source": "baostock",
                        "api_name": api_name,
                        "spider_name": self.spider_name,
                        "batch_id": self.batch_id,
                        "request_count": 1,
                    }
                ]
            ),
        )
        self.used_count += 1


class BaostockClient:
    def __init__(
        self,
        socket_timeout_seconds: int = 20,
        quota: BaostockDailyQuota | None = None,
        retry_attempts: int = 3,
        retry_delay_seconds: float = 1.0,
    ):
        try:
            import baostock as bs
        except ImportError as exc:
            raise RuntimeError("Baostock spiders require the optional dependency: pip install baostock") from exc
        self.bs = bs
        self.logged_in = False
        self.socket_timeout_seconds = socket_timeout_seconds
        self.quota = quota
        self.retry_attempts = max(1, int(retry_attempts or 1))
        self.retry_delay_seconds = max(0.0, float(retry_delay_seconds or 0.0))

    def _run_with_socket_timeout(self, func, *args, **kwargs):
        previous_timeout = socket.getdefaulttimeout()
        socket.setdefaulttimeout(self.socket_timeout_seconds)
        try:
            return func(*args, **kwargs)
        finally:
            socket.setdefaulttimeout(previous_timeout)

    def login(self):
        if self.logged_in:
            return
        result = self._run_with_socket_timeout(self.bs.login)
        if getattr(result, "error_code", "0") != "0":
            endpoint = self._endpoint_description()
            raise RuntimeError(
                f"Baostock login failed at {endpoint}: {getattr(result, 'error_msg', '')}. "
                "Check outbound TCP access to the Baostock service."
            )
        self.logged_in = True

    def logout(self):
        if self.logged_in:
            self.bs.logout()
            self.logged_in = False

    def reset_connection(self):
        try:
            self.logout()
        except Exception as exc:
            logging.warning("Failed to logout Baostock client after request error: %s", exc)
            self.logged_in = False

    @staticmethod
    def result_to_dataframe(result) -> pd.DataFrame:
        if getattr(result, "error_code", "0") != "0":
            raise RuntimeError(f"Baostock query failed: {getattr(result, 'error_msg', '')}")

        rows = []
        while result.next():
            rows.append(result.get_row_data())
        return pd.DataFrame(rows, columns=result.fields)

    def query(self, method_name: str, **params) -> pd.DataFrame:
        method = getattr(self.bs, method_name)
        last_exc: Exception | None = None

        for attempt in range(1, self.retry_attempts + 1):
            try:
                self.login()
                if self.quota is not None:
                    self.quota.reserve(method_name)
                logging.info(
                    "Requesting Baostock %s with params: %s attempt=%s/%s",
                    method_name,
                    params,
                    attempt,
                    self.retry_attempts,
                )
                return self.result_to_dataframe(self._run_with_socket_timeout(method, **params))
            except BaostockQuotaExceeded:
                raise
            except Exception as exc:
                last_exc = exc
                self.reset_connection()
                if attempt >= self.retry_attempts:
                    break
                logging.warning(
                    "Retrying Baostock %s after attempt %s/%s failed: %s",
                    method_name,
                    attempt,
                    self.retry_attempts,
                    exc,
                )
                delay_seconds = self.retry_delay_seconds * attempt
                if delay_seconds > 0:
                    time.sleep(delay_seconds)

        raise BaostockRequestFailed(
            f"Baostock {method_name} failed after {self.retry_attempts} attempts: {last_exc}"
        ) from last_exc

    def _endpoint_description(self) -> str:
        try:
            constants = self.bs.login.__globals__["cons"]
            return f"{constants.BAOSTOCK_SERVER_IP}:{constants.BAOSTOCK_SERVER_PORT}"
        except Exception:
            return "Baostock socket endpoint"


class BaostockSpider(scrapy.Spider):
    name: str
    api_name: str = ""
    custom_settings: dict[str, Any] = {}

    schema: dict = {}
    latest_schema: dict = {}
    raw_schema: dict = {}
    spider_settings: TushareIntegrationSettings
    db_engine: DBEngine

    def __init__(self, name=None, **kwargs):
        super().__init__(name, **kwargs)
        self.schema = self.get_schema()
        self.latest_schema = build_latest_schema(self.schema)
        self.raw_schema = build_raw_schema(self.schema)
        self.client: BaostockClient | None = None
        self.quota: BaostockDailyQuota | None = None

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        spider.spider_settings = TushareIntegrationSettings.model_validate(
            yaml.safe_load(open("config.yaml", "r", encoding="utf-8").read())
        )
        spider.create_table()
        return spider

    def closed(self, reason):
        if self.client is not None:
            self.client.logout()

    def create_table(self):
        self.db_engine = DatabaseEngineFactory.create(self.spider_settings)
        self.db_engine.create_table(self.get_latest_table_name(), self.latest_schema)
        self.db_engine.create_table(self.get_raw_table_name(), self.raw_schema)
        self.db_engine.create_table(BAOSTOCK_REQUEST_LOG_TABLE, BAOSTOCK_REQUEST_LOG_SCHEMA)

    def get_schema(self):
        with open(f"tushare_integration/schema/{self.get_schema_name()}.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f.read())

    def get_schema_name(self) -> str:
        return self.custom_settings.get("SCHEMA_NAME", self.name)

    def get_source_name(self) -> str:
        return "baostock"

    def get_api_name(self) -> str:
        return self.api_name or self.name.split("/")[-1]

    def get_latest_table_name(self) -> str:
        return get_latest_table_name(self.custom_settings.get("TABLE_NAME", self.name.split("/")[-1]))

    def get_raw_table_name(self) -> str:
        return get_raw_table_name(self.get_latest_table_name())

    def get_table_name(self) -> str:
        return self.get_latest_table_name()

    def get_db_engine(self):
        return self.db_engine

    def get_local_request(self, callback):
        return scrapy.Request(url=f"data:,{self.name}", callback=callback, dont_filter=True)

    def get_client(self) -> BaostockClient:
        if self.client is None:
            timeout_seconds = getattr(self.spider_settings, "baostock_socket_timeout_seconds", 20)
            retry_attempts = getattr(self.spider_settings, "baostock_request_retry_attempts", 3)
            retry_delay_seconds = getattr(self.spider_settings, "baostock_request_retry_delay_seconds", 1.0)
            daily_limit = getattr(self.spider_settings, "baostock_daily_request_limit", 50000)
            batch_id = self.settings.get("BATCH_ID", "") if hasattr(self, "settings") else ""
            self.quota = BaostockDailyQuota(
                db_engine=self.get_db_engine(),
                settings=self.spider_settings,
                spider_name=self.name,
                batch_id=batch_id,
                limit=int(daily_limit or 0),
            )
            self.client = BaostockClient(
                socket_timeout_seconds=timeout_seconds,
                quota=self.quota,
                retry_attempts=retry_attempts,
                retry_delay_seconds=retry_delay_seconds,
            )
        return self.client

    def get_start_date(self) -> datetime.date:
        settings_value = getattr(self.spider_settings, "baostock_start_date", None)
        parsed = parse_date_value(self.custom_settings.get("MIN_CAL_DATE", settings_value))
        return parsed or BAOSTOCK_START_DATE

    def get_backfill_days(self) -> int:
        backfill_days = self.custom_settings.get(
            "BACKFILL_DAYS",
            getattr(self.spider_settings, "baostock_incremental_backfill_days", 0),
        )
        return max(0, int(backfill_days or 0))

    def get_incremental_start_date(
        self,
        date_field: str,
        table_name: str | None = None,
        where_clause: str = "",
    ) -> datetime.date:
        min_date = self.get_start_date()
        row_count, latest_date = self.get_incremental_date_state(date_field, table_name, where_clause)
        if row_count == 0:
            return min_date
        if latest_date is None:
            return min_date
        return max(min_date, latest_date - datetime.timedelta(days=self.get_backfill_days()))

    def get_incremental_date_state(
        self,
        date_field: str,
        table_name: str | None = None,
        where_clause: str = "",
    ) -> tuple[int, datetime.date | None]:
        conn = self.get_db_engine()
        db_name = self.spider_settings.database.db_name
        table_name = table_name or self.get_table_name()

        latest_data = conn.query_df(
            f"""
                SELECT count() AS row_count, max(`{date_field}`) AS latest_date
                FROM {db_name}.{table_name}
                {where_clause}
                """
        )
        if latest_data.empty:
            return 0, None
        row_count = int(latest_data["row_count"].iloc[0] or 0)
        latest_date = parse_date_value(latest_data["latest_date"].iloc[0])
        return row_count, latest_date

    @staticmethod
    def merge_frames(frames: list[pd.DataFrame]) -> pd.DataFrame:
        frames = [frame for frame in frames if frame is not None and not frame.empty]
        if not frames:
            return pd.DataFrame()
        return pd.concat(frames, ignore_index=True)

    def item_from_dataframe(self, data: pd.DataFrame) -> TushareIntegrationItem | None:
        if data is None or data.empty:
            return None
        data = data.copy()
        schema_columns = [column["name"] for column in self.schema["columns"]]
        for column in schema_columns:
            if column not in data.columns:
                data[column] = None
        data = data[schema_columns]
        return TushareIntegrationItem(data=data)


class BaostockDirectSpider(BaostockSpider):
    query_method: str
    query_params: dict[str, Any] = {}

    def start_requests(self):
        yield self.get_local_request(self.parse_baostock)

    def parse_baostock(self, response):
        try:
            item = self.item_from_dataframe(self.get_client().query(self.query_method, **self.query_params))
        except (BaostockQuotaExceeded, BaostockRequestFailed) as exc:
            logging.warning("Skipping %s because %s", self.name, exc)
            return
        if item is not None:
            yield item


class BaostockCodeListMixin:
    code_type: str = "1"
    code_list_fields: tuple[str, ...] = ("code",)

    def get_code_list_fields(self) -> tuple[str, ...]:
        return self.code_list_fields

    def get_code_list_select_fields(self) -> tuple[str, ...]:
        fields = ["code", "type"]
        for field in self.get_code_list_fields():
            if field not in fields:
                fields.append(field)
        return tuple(fields)

    def filter_code_rows(self, data: pd.DataFrame) -> pd.DataFrame:
        if data.empty:
            return data
        data = data.copy()
        if "type" in data.columns:
            data = data[data["type"].astype(str) == self.code_type]
        if "code" not in data.columns:
            return pd.DataFrame()
        data = data[data["code"].notna() & (data["code"].astype(str) != "")]
        return data

    def cache_code_rows(self, data: pd.DataFrame) -> None:
        self._baostock_code_rows = data.copy()

    def get_cached_code_rows(self) -> pd.DataFrame | None:
        return getattr(self, "_baostock_code_rows", None)

    def get_code_lifecycle_date(self, code: str | None, field_name: str) -> datetime.date | None:
        if not code:
            return None

        code_rows = self.get_cached_code_rows()
        if code_rows is None:
            try:
                self.load_codes_from_local_basic()
                code_rows = self.get_cached_code_rows()
            except Exception as exc:
                logging.warning("Failed to load Baostock stock lifecycle for %s: %s", self.name, exc)
                return None

        if code_rows is None or code_rows.empty or field_name not in code_rows.columns:
            return None
        matched = code_rows[code_rows["code"].astype(str) == code]
        if matched.empty:
            return None

        lifecycle_date = parse_date_value(matched[field_name].iloc[0])
        if lifecycle_date is None or lifecycle_date <= datetime.date(1970, 1, 1):
            return None
        return lifecycle_date

    def get_code_ipo_date(self, code: str | None) -> datetime.date | None:
        return self.get_code_lifecycle_date(code, "ipoDate")

    def get_code_delist_date(self, code: str | None) -> datetime.date | None:
        return self.get_code_lifecycle_date(code, "outDate")

    def load_codes_from_local_basic(self) -> list[str]:
        db_name = self.spider_settings.database.db_name
        table_expr = f"{db_name}.baostock_stock_basic"
        if self.spider_settings.database.db_type == "clickhouse":
            table_expr = f"{table_expr} FINAL"
        select_fields = ", ".join(f"`{field}`" for field in self.get_code_list_select_fields())

        data = self.get_db_engine().query_df(
            f"""
            SELECT DISTINCT {select_fields}
            FROM {table_expr}
            WHERE `type` = '{self.code_type}'
              AND code != ''
            ORDER BY code
            """
        )
        data = self.filter_code_rows(data)
        self.cache_code_rows(data)
        if data.empty or "code" not in data.columns:
            return []
        return data["code"].dropna().astype(str).tolist()

    def load_codes(self) -> list[str]:
        try:
            codes = self.load_codes_from_local_basic()
            if codes:
                logging.info("Loaded %s Baostock codes from local baostock_stock_basic", len(codes))
                return codes
        except Exception as exc:
            logging.warning("Failed to load Baostock code list from local table; falling back to API: %s", exc)

        try:
            df = self.get_client().query("query_stock_basic")
        except (BaostockQuotaExceeded, BaostockRequestFailed) as exc:
            logging.warning("Skipping code-list load for %s because %s", self.name, exc)
            return []
        if df.empty:
            return []
        df = self.filter_code_rows(df)
        self.cache_code_rows(df)
        if df.empty or "code" not in df.columns:
            return []
        return sorted(df["code"].dropna().astype(str).unique().tolist())


class BaostockDailyRangeMixin:
    date_field = "date"

    def get_end_date(self) -> datetime.date:
        return datetime.date.today()

    def get_code_request_end_date(self, code: str | None = None) -> datetime.date:
        return self.get_end_date()

    @staticmethod
    def escape_sql_literal(value: str) -> str:
        return value.replace("'", "''")

    def get_code_where_clause(self, code: str | None) -> str:
        if not code:
            return ""
        return f"WHERE `code` = '{self.escape_sql_literal(code)}'"

    def get_code_filter_condition(self, code: str | None) -> str:
        if not code:
            return ""
        return f"AND `code` = '{self.escape_sql_literal(code)}'"

    def get_calendar_table_name(self) -> str:
        return "baostock_trade_dates"

    @staticmethod
    def compact_missing_dates_to_ranges(dates: list[datetime.date | None]) -> list[tuple[str, str]]:
        valid_dates = sorted({date for date in dates if date is not None})
        if not valid_dates:
            return []
        return [(format_baostock_date(valid_dates[0]), format_baostock_date(valid_dates[-1]))]

    def get_request_date_range(self, code: str | None = None) -> tuple[str, str]:
        start_date = self.get_incremental_start_date(
            self.date_field,
            where_clause=self.get_code_where_clause(code),
        )
        end_date = self.get_code_request_end_date(code)
        return format_baostock_date(start_date), format_baostock_date(end_date)

    def get_missing_request_date_ranges(self, code: str | None = None) -> list[tuple[str, str]]:
        row_count, latest_date = self.get_incremental_date_state(
            self.date_field,
            where_clause=self.get_code_where_clause(code),
        )
        min_date = self.get_start_date()
        end_date = self.get_code_request_end_date(code)
        if end_date < min_date:
            return []
        if row_count == 0 or latest_date is None:
            return [(format_baostock_date(min_date), format_baostock_date(end_date))]

        start_date = max(min_date, latest_date - datetime.timedelta(days=self.get_backfill_days()))
        if start_date > end_date:
            return []
        db_name = self.spider_settings.database.db_name
        table_name = self.get_table_name()
        calendar_table_name = self.get_calendar_table_name()

        try:
            missing_dates = self.get_db_engine().query_df(
                f"""
                    SELECT DISTINCT calendar_date
                    FROM {db_name}.{calendar_table_name}
                    WHERE calendar_date NOT IN (
                        SELECT `{self.date_field}` FROM {db_name}.{table_name}
                        WHERE `{self.date_field}` >= '{format_baostock_date(start_date)}'
                        {self.get_code_filter_condition(code)}
                    )
                      AND is_trading_day = 1
                      AND calendar_date >= '{format_baostock_date(start_date)}'
                      AND calendar_date <= '{format_baostock_date(end_date)}'
                    ORDER BY calendar_date
                    """
            )
        except Exception as exc:
            logging.warning(
                "Failed to load Baostock trade calendar for %s; falling back to Baostock range request: %s",
                self.name,
                exc,
            )
            return [(format_baostock_date(start_date), format_baostock_date(end_date))]

        if missing_dates.empty or "calendar_date" not in missing_dates.columns:
            return []
        dates = [parse_date_value(value) for value in missing_dates["calendar_date"]]
        return self.compact_missing_dates_to_ranges(dates)

    def iter_code_frames(
        self,
        query_func: Callable[[str, str, str], pd.DataFrame],
        codes: list[str],
    ):
        for code in codes:
            for start_date, end_date in self.get_missing_request_date_ranges(code):
                try:
                    frame = query_func(code, start_date, end_date)
                except BaostockQuotaExceeded as exc:
                    logging.warning("Stopping %s because %s", self.name, exc)
                    return
                except BaostockRequestFailed as exc:
                    logging.warning(
                        "Skipping Baostock request for %s code=%s start_date=%s end_date=%s because %s",
                        self.name,
                        code,
                        start_date,
                        end_date,
                        exc,
                    )
                    continue
                if frame is not None and not frame.empty:
                    yield frame

    def query_by_codes(
        self,
        query_func: Callable[[str, str, str], pd.DataFrame],
        codes: list[str],
    ) -> pd.DataFrame:
        return self.merge_frames(list(self.iter_code_frames(query_func, codes)))
