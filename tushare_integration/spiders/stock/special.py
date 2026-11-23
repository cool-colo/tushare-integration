import datetime
import hashlib
import json

import pandas as pd
from scrapy import signals
from twisted.python.failure import Failure

from tushare_integration.cyq_chips_progress import CyqChipsProgressStore
from tushare_integration.items import TushareIntegrationItem
from tushare_integration.spiders.tushare import DailySpider, TSCodeSpider, TushareSpider


class ReportRCSpider(TSCodeSpider):
    # 更新日期不固定，定期用TSCodeSpider更新
    name = "stock/special/report_rc"
    api_name = "report_rc"
    custom_settings = {"TABLE_NAME": "report_rc", "BASIC_TABLE": "stock_basic"}


class CyqPerfSpider(DailySpider):
    name = "stock/special/cyq_perf"
    api_name = "cyq_perf"
    custom_settings = {"TABLE_NAME": "cyq_perf", 'MIN_CAL_DATE': '2018-01-02'}


class CyqChipsSpider(TushareSpider):
    name = "stock/special/cyq_chips"
    api_name = "cyq_chips"
    custom_settings = {
        "TABLE_NAME": "cyq_chips",
        "BASIC_TABLE": "stock_basic",
        "MIN_CAL_DATE": "2018-01-02",
        "BACKFILL_GAPS": False,
        "REQUEST_CHUNK_TRADE_DAYS": 25,
        "MAX_REQUESTS_PER_RUN": 50000,
    }

    PAGE_LIMIT = 6000
    MAX_PAGES_PER_WINDOW = 1000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.window_progress = {}
        self.request_count = 0

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.on_item_scraped, signal=signals.item_scraped)
        return spider

    def create_table(self):
        super().create_table()
        self.get_progress_store().ensure_table(self.db_engine)

    def get_progress_store(self):
        if not hasattr(self, "progress_store"):
            self.progress_store = CyqChipsProgressStore(self.spider_settings)
        return self.progress_store

    def get_page_request(self, params):
        cap = self.get_max_requests_per_run()
        if cap and self.request_count >= cap:
            self.logger.warning("Reached cyq_chips request cap (%s); incomplete windows will be replayed.", cap)
            return None
        self.request_count += 1
        return self.get_scrapy_request(params)

    @staticmethod
    def _format_trade_date(value):
        parsed = DailySpider.parse_date_value(value)
        if parsed is None:
            return None
        return parsed.strftime("%Y-%m-%d")

    def _get_min_trade_date(self, list_date=None):
        min_cal_date = DailySpider.parse_date_value(self.custom_settings.get("MIN_CAL_DATE"))
        parsed_list_date = DailySpider.parse_date_value(list_date)

        if min_cal_date is None:
            return parsed_list_date
        if parsed_list_date is None:
            return min_cal_date
        return max(min_cal_date, parsed_list_date)

    @staticmethod
    def _get_delist_date(delist_date=None):
        parsed_delist_date = DailySpider.parse_date_value(delist_date)
        if parsed_delist_date in (None, datetime.date(1970, 1, 1)):
            return None
        return parsed_delist_date

    def get_missing_trade_dates(self, conn, ts_code: str, list_date=None, delist_date=None):
        db_name = self.spider_settings.database.db_name
        min_trade_date = self._format_trade_date(self._get_min_trade_date(list_date))
        max_trade_date = self._format_trade_date(self._get_delist_date(delist_date))
        delist_condition = f"AND trade_date <= '{max_trade_date}'" if max_trade_date else ""

        # Existing business rows do not prove that all price buckets were fetched.
        # Only successful windows may exclude dates, including empty source windows.
        completed_windows = []
        if not self.custom_settings.get("BACKFILL_GAPS", False):
            completed_windows = self.get_progress_store().get_completed_windows(conn, ts_code)
        exclusions = " OR ".join(
            f"(trade_date >= '{start}' AND trade_date <= '{end}')"
            for start, end in completed_windows
        )
        completed_condition = f"AND NOT ({exclusions})" if exclusions else ""
        return conn.query_df(
            f"""
                SELECT DISTINCT trade_date
                FROM {db_name}.daily
                WHERE ts_code = {CyqChipsProgressStore._quote_string(ts_code)}
                AND trade_date >= '{min_trade_date}'
                {delist_condition}
                {completed_condition}
                ORDER BY trade_date
            """
        )

    def get_request_chunk_trade_days(self) -> int:
        chunk_days = getattr(
            self.spider_settings,
            "cyq_chips_request_chunk_trade_days",
            self.custom_settings.get("REQUEST_CHUNK_TRADE_DAYS", 25),
        )
        return max(1, int(chunk_days or 1))

    def get_max_requests_per_run(self) -> int:
        max_requests = getattr(
            self.spider_settings,
            "cyq_chips_max_requests_per_run",
            self.custom_settings.get("MAX_REQUESTS_PER_RUN", 50000),
        )
        return max(0, int(max_requests or 0))

    def iter_trade_date_ranges(self, trade_dates):
        chunk_days = self.get_request_chunk_trade_days()
        parsed_trade_dates = [DailySpider.parse_date_value(trade_date) for trade_date in trade_dates]
        parsed_trade_dates = [trade_date for trade_date in parsed_trade_dates if trade_date is not None]

        for start_index in range(0, len(parsed_trade_dates), chunk_days):
            chunk = parsed_trade_dates[start_index : start_index + chunk_days]
            if not chunk:
                continue
            yield chunk[0].strftime("%Y%m%d"), chunk[-1].strftime("%Y%m%d")

    def start_requests(self):
        self.pending_windows = self.iter_window_params()
        request = self.next_window_request()
        if request is not None:
            yield request

    def next_window_request(self):
        params = next(getattr(self, "pending_windows", iter(())), None)
        return self.get_page_request(params) if params is not None else None

    def iter_window_params(self):
        conn = self.get_db_engine()
        stock_basic = conn.query_df(
            f"""
                SELECT DISTINCT ts_code, list_date, delist_date
                FROM {self.spider_settings.database.db_name}.{self.custom_settings.get("BASIC_TABLE")}
                WHERE ts_code != ''
                ORDER BY ts_code
            """
        )
        for row in stock_basic.itertuples(index=False):
            trade_dates = self.get_missing_trade_dates(conn, row.ts_code, row.list_date, row.delist_date)
            for start_date, end_date in self.iter_trade_date_ranges(trade_dates["trade_date"]):
                yield {
                    "ts_code": row.ts_code,
                    "start_date": start_date,
                    "end_date": end_date,
                    "limit": self.PAGE_LIMIT,
                    "offset": 0,
                }

    @staticmethod
    def _window_key(params):
        return params["ts_code"], params["start_date"], params["end_date"]

    def _maybe_complete_window(self, key):
        progress = self.window_progress[key]
        if not progress["finished"] or progress["persisted_pages"] != progress["pages"]:
            return
        ts_code, start, end = key
        self.get_progress_store().complete_window(
            self.get_db_engine(),
            ts_code,
            DailySpider.parse_date_value(start),
            DailySpider.parse_date_value(end),
        )
        del self.window_progress[key]
        self.logger.info("Completed and persisted cyq_chips window: %s", key)
        # Finish the current window before spending the run budget on another.
        return self.next_window_request()

    def on_item_scraped(self, item, response, spider):
        # item_scraped fires only after every pipeline has succeeded.
        key = self._window_key(response.meta["params"])
        progress = self.window_progress[key]
        progress["persisted_pages"] += 1
        try:
            request = self._maybe_complete_window(key)
            if request is not None:
                self.crawler.engine.crawl(request)
        except Exception:
            # Exceptions in signal handlers alone do not reach CrawlManager.
            self.crawler.signals.send_catch_log(
                signal=signals.spider_error, failure=Failure(), response=response, spider=self,
            )

    def parse(self, response, **kwargs):
        payload = json.loads(response.text)
        # Parameter errors and malformed success responses are not empty-source evidence.
        if payload.get("code") != 0:
            raise RuntimeError(f"cyq_chips request failed: {payload.get('msg', payload)}")
        if not isinstance(payload.get("data"), dict) or not isinstance(payload["data"].get("items"), list):
            raise RuntimeError("cyq_chips returned malformed data; window is incomplete")
        data = self.parse_response(response, **kwargs)["data"]
        params = dict(response.meta["params"])
        ts_code = params["ts_code"]
        start_date = DailySpider.parse_date_value(params["start_date"])
        end_date = DailySpider.parse_date_value(params["end_date"])
        offset = int(params.get("offset", 0))
        limit = int(params.get("limit", self.PAGE_LIMIT))
        key = self._window_key(params)
        progress = self.window_progress.setdefault(
            key, {"page_hashes": set(), "pages": 0, "persisted_pages": 0, "finished": False}
        )
        if len(data) > limit:
            raise RuntimeError(f"cyq_chips exceeded requested page limit: {key} offset={offset}")
        if data.empty:
            progress["finished"] = True
            request = self._maybe_complete_window(key)
            if request is not None:
                yield request
            return
        if "ts_code" not in data or data["ts_code"].isna().any() or not data["ts_code"].eq(ts_code).all():
            raise RuntimeError(f"cyq_chips returned a different stock code: {key} offset={offset}")
        trade_dates = pd.to_datetime(data["trade_date"], format="mixed", errors="coerce")
        if trade_dates.isna().any():
            raise RuntimeError(f"cyq_chips returned invalid trade_date: {key} offset={offset}")
        if ((trade_dates.dt.date < start_date) | (trade_dates.dt.date > end_date)).any():
            raise RuntimeError(f"cyq_chips returned trade_date outside requested window: {key} offset={offset}")
        if progress["pages"] >= self.MAX_PAGES_PER_WINDOW:
            raise RuntimeError(f"cyq_chips exceeded page safety limit: {key}; window is incomplete")
        page_rows = sorted(json.dumps(row, sort_keys=True, default=str) for row in data.to_dict("records"))
        page_hash = hashlib.sha256("\n".join(page_rows).encode("utf-8")).hexdigest()
        if page_hash in progress["page_hashes"]:
            raise RuntimeError(f"cyq_chips repeated a source page: {key}; the source may be ignoring offset")
        progress["page_hashes"].add(page_hash)
        progress["pages"] += 1
        yield TushareIntegrationItem(data=data)
        params["offset"] = offset + len(data)
        request = self.get_page_request(params)
        if request is not None:
            yield request


class StkFactorSpider(DailySpider):
    name = "stock/special/stk_factor"
    api_name = "stk_factor"
    custom_settings = {"TABLE_NAME": "stk_factor", "MIN_CAL_DATE": "1990-12-19"}


class CCASSHoldSpider(DailySpider):
    name = "stock/special/ccass_hold"
    api_name = "ccass_hold"
    custom_settings = {"TABLE_NAME": "ccass_hold", "MIN_CAL_DATE": "2020-11-11"}


class CCASSHoldDetailSpider(DailySpider):
    name = "stock/special/ccass_hold_detail"
    api_name = "ccass_hold_detail"
    custom_settings = {"TABLE_NAME": "ccass_hold_detail", "MIN_CAL_DATE": "2016-12-05"}


class HKHoldSpider(DailySpider):
    name = "stock/special/hk_hold"
    api_name = "hk_hold"
    custom_settings = {"TABLE_NAME": "hk_hold", 'MIN_CAL_DATE': '2016-06-29'}


class StkSurvSpider(TSCodeSpider):
    name = "stock/special/stk_surv"
    api_name = "stk_surv"
    custom_settings = {"TABLE_NAME": "stk_surv", "BASIC_TABLE": "stock_basic"}


class BrokerRecommend(TushareSpider):
    name = "stock/special/broker_recommend"
    api_name = "broker_recommend"
    custom_settings = {"TABLE_NAME": "broker_recommend"}

    def start_requests(self):
        # 生成从202003到现在的月份列表
        month_list = []
        for year in range(2020, datetime.datetime.now().year + 1):
            for month in range(1, 13):
                yield self.get_scrapy_request({"month": f"{year}{month:02d}"})


class StkFactorPro(DailySpider):
    name = "stock/special/stk_factor_pro"
    api_name = "stk_factor_pro"
    custom_settings = {"TABLE_NAME": "stk_factor_pro", "MIN_CAL_DATE": "2010-01-01"}
