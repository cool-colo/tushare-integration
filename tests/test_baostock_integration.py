import datetime
import sys
import types
import unittest
from unittest import mock

import pandas as pd

from tushare_integration.dwd import DWDManager
from tushare_integration.manager import CrawlManager
from tushare_integration.quality import CrossSourceQualityManager
from tushare_integration.settings import TushareIntegrationSettings
from tushare_integration.spiders.baostock.base import (
    BaostockClient,
    BaostockCodeListMixin,
    BaostockDailyQuota,
    BaostockQuotaExceeded,
    BaostockRequestFailed,
)
from tushare_integration.spiders.baostock.index import BaostockIndexDailySpider
from tushare_integration.spiders.baostock.stock import (
    BaostockStockDailySpider,
    BaostockStockFinancialIndicatorSpider,
    BaostockStockProfitSpider,
    BaostockTradeDatesSpider,
)
from tushare_integration.spiders.baostock.utils import baostock_exchange, normalize_baostock_code


class DummyCodeListDB:
    def __init__(self, data):
        self.data = data
        self.queries = []

    def query_df(self, sql):
        self.queries.append(sql)
        return self.data.copy()


class DummyDependencyDB:
    def __init__(self, row_counts):
        if isinstance(row_counts, dict):
            self.row_counts = row_counts
        else:
            self.row_counts = {"1": row_counts}
        self.queries = []

    def query_df(self, sql):
        self.queries.append(sql)
        return pd.DataFrame(
            [
                {"type": code_type, "row_count": row_count}
                for code_type, row_count in self.row_counts.items()
                if f"'{code_type}'" in sql
            ]
        )


class DummyQuotaDB:
    def __init__(self, used_count=0):
        self.used_count = used_count
        self.inserts = []

    def query_df(self, sql):
        return pd.DataFrame({"used_count": [self.used_count]})

    def insert(self, table_name, schema, data):
        self.inserts.append((table_name, data.copy()))
        self.used_count += int(data["request_count"].sum())


class DummyDailyRangeDB:
    def __init__(
        self,
        latest_by_code,
        missing_dates_by_code=None,
        code_rows=None,
        existing_stat_dates_by_code=None,
    ):
        self.latest_by_code = latest_by_code
        self.missing_dates_by_code = missing_dates_by_code or {}
        self.code_rows = code_rows
        self.existing_stat_dates_by_code = existing_stat_dates_by_code or {}
        self.queries = []

    def query_df(self, sql):
        self.queries.append(sql)
        if "FROM default.baostock_stock_basic" in sql:
            if self.code_rows is None:
                return pd.DataFrame(columns=["code", "type", "outDate"])
            return self.code_rows.copy()
        if "FROM default.baostock_trade_dates" in sql:
            for code, missing_dates in self.missing_dates_by_code.items():
                if f"`code` = '{code}'" in sql:
                    return pd.DataFrame({"calendar_date": pd.to_datetime(missing_dates)})
            return pd.DataFrame(columns=["calendar_date"])
        if "FROM default.trade_cal" in sql:
            raise AssertionError("Baostock daily range must not use Tushare trade_cal")
        if "SELECT DISTINCT `statDate`" in sql:
            for code, stat_dates in self.existing_stat_dates_by_code.items():
                if f"`code` = '{code}'" in sql:
                    return pd.DataFrame({"statDate": pd.to_datetime(stat_dates)})
            return pd.DataFrame(columns=["statDate"])
        for code, latest_date in self.latest_by_code.items():
            if f"`code` = '{code}'" in sql:
                return pd.DataFrame({"row_count": [1], "latest_date": [latest_date]})
        return pd.DataFrame({"row_count": [0], "latest_date": [None]})


class DummyTradeDatesDB:
    def __init__(self, row_count, latest_date):
        self.row_count = row_count
        self.latest_date = latest_date
        self.queries = []

    def query_df(self, sql):
        self.queries.append(sql)
        return pd.DataFrame({"row_count": [self.row_count], "latest_date": [self.latest_date]})


class DummyTradeDatesClient:
    def __init__(self):
        self.calls = []

    def query(self, method_name, **params):
        self.calls.append((method_name, params))
        return pd.DataFrame(
            [
                {
                    "calendar_date": params["start_date"],
                    "is_trading_day": "1",
                }
            ]
        )


class DummyBaostockResult:
    def __init__(self, error_code="0", error_msg="", fields=None, rows=None):
        self.error_code = error_code
        self.error_msg = error_msg
        self.fields = fields or []
        self.rows = rows or []
        self.index = 0

    def next(self):
        if self.index >= len(self.rows):
            return False
        self.index += 1
        return True

    def get_row_data(self):
        return self.rows[self.index - 1]


class DummyBaostockModule(types.SimpleNamespace):
    def __init__(self, fail_times=0):
        super().__init__()
        self.fail_times = fail_times
        self.query_calls = 0
        self.logout_calls = 0

    def login(self):
        return DummyBaostockResult()

    def logout(self):
        self.logout_calls += 1

    def query_history_k_data_plus(self, **params):
        self.query_calls += 1
        if self.query_calls <= self.fail_times:
            return DummyBaostockResult(error_code="1", error_msg="网络接收错误。")
        return DummyBaostockResult(fields=["code"], rows=[[params["code"]]])


class BaostockIntegrationTest(unittest.TestCase):
    def _settings(self):
        return TushareIntegrationSettings(
            tushare_token="token",
            feishu_webhook="",
            database={
                "db_type": "clickhouse",
                "host": "localhost",
                "port": 8123,
                "user": "default",
                "password": "",
                "db_name": "default",
            },
            quality={"mode": "warn_only", "create_result_tables": False},
        )

    def test_baostock_code_normalization_supports_cn_exchanges(self):
        self.assertEqual(normalize_baostock_code("sh.600000"), "600000.SH")
        self.assertEqual(normalize_baostock_code("sz.000001"), "000001.SZ")
        self.assertEqual(normalize_baostock_code("bj.430047"), "430047.BJ")
        self.assertEqual(baostock_exchange("bj.430047"), "BJ")

    def test_baostock_item_padding_preserves_schema_shape(self):
        spider = BaostockStockDailySpider()
        item = spider.item_from_dataframe(
            pd.DataFrame(
                [
                    {
                        "date": "2026-05-25",
                        "code": "sh.600000",
                        "open": "10.0",
                        "high": "11.0",
                        "low": "9.9",
                        "close": "10.5",
                    }
                ]
            )
        )

        self.assertIsNotNone(item)
        self.assertIn("adjustflag", item["data"].columns)
        self.assertIn("isST", item["data"].columns)
        self.assertEqual(item["data"]["code"].iloc[0], "sh.600000")

    def test_dwd_discovery_recurses_and_renders_mapped_baostock_sql(self):
        manager = DWDManager()

        self.assertIn("dwd_baostock_stock_eod_price", manager.list_tables())
        sql = manager.render_sync_sql("dwd_baostock_stock_eod_price")
        schema = manager.build_schema(manager.load_spec("dwd_baostock_stock_daily_basic"))
        column_names = {column["name"] for column in schema["columns"]}

        self.assertIn("FROM default.baostock_stock_daily_raw src", sql)
        self.assertIn("FROM default.baostock_trade_dates c", sql)
        self.assertNotIn("FROM default.trade_cal c", sql)
        self.assertIn("src.`date` >= toDate32('2015-01-01')", sql)
        self.assertIn("src.`adjustflag` = '3'", sql)
        self.assertIn("AS `pre_close`", sql)
        self.assertIn("AS `vol`", sql)
        self.assertIn("concat('stock:'", sql)
        self.assertIn("pcf_ncf_ttm", column_names)
        self.assertIn("is_st", column_names)
        required_tables = manager.get_required_source_tables(manager.load_spec("dwd_baostock_stock_eod_price"))
        self.assertIn("baostock_trade_dates", required_tables)
        self.assertNotIn("trade_cal", required_tables)

    def test_baostock_financial_pit_uses_publication_date_then_period_fallback(self):
        sql = DWDManager().render_sync_sql("dwd_baostock_stock_income")

        self.assertIn("FROM default.baostock_trade_dates c", sql)
        self.assertNotIn("FROM default.trade_cal c", sql)
        self.assertIn("src.`statDate` >= toDate32('2015-01-01')", sql)
        self.assertIn("PARTITION BY src.`code`, src.`statDate`", sql)
        self.assertIn("nullIf(src.pubDate, toDate32('1970-01-01')) AS `ann_date`", sql)
        self.assertIn(
            "coalesce(calendar_map.next_trade_date, nullIf(src.pubDate, toDate32('1970-01-01')), src.statDate)",
            sql,
        )

    def test_baostock_daily_depends_on_baostock_trade_dates(self):
        dependencies = CrawlManager.get_dependencies(["baostock/stock/daily"])

        self.assertIn("baostock/stock/trade_dates", dependencies)
        self.assertNotIn("stock/basic/trade_cal", dependencies)

    def test_baostock_basic_dependency_skips_when_local_basic_has_rows(self):
        manager = CrawlManager.__new__(CrawlManager)
        manager.settings = self._settings()
        manager._dependency_db_engine = DummyDependencyDB(2)

        spiders = manager.get_all_spiders(["baostock/stock/balance"])

        self.assertEqual(spiders, ["baostock/stock/balance"])
        self.assertIn("baostock_stock_basic FINAL", manager._dependency_db_engine.queries[0])
        self.assertIn("WHERE `type` IN ('1')", manager._dependency_db_engine.queries[0])

    def test_baostock_basic_dependency_runs_when_local_basic_is_empty(self):
        manager = CrawlManager.__new__(CrawlManager)
        manager.settings = self._settings()
        manager._dependency_db_engine = DummyDependencyDB(0)

        spiders = manager.get_all_spiders(["baostock/stock/balance"])

        self.assertEqual(spiders, ["baostock/stock/basic", "baostock/stock/balance"])

    def test_baostock_index_daily_basic_dependency_requires_local_index_rows(self):
        manager = CrawlManager.__new__(CrawlManager)
        manager.settings = self._settings()
        manager._dependency_db_engine = DummyDependencyDB({"1": 2, "2": 0})

        spiders = manager.get_all_spiders(["baostock/index/daily"])

        self.assertIn("baostock/stock/basic", spiders)
        self.assertIn("WHERE `type` IN ('2')", manager._dependency_db_engine.queries[0])

    def test_baostock_index_daily_basic_dependency_skips_when_local_index_rows_exist(self):
        manager = CrawlManager.__new__(CrawlManager)
        manager.settings = self._settings()
        manager._dependency_db_engine = DummyDependencyDB({"2": 3})

        spiders = manager.get_all_spiders(["baostock/index/daily"])

        self.assertNotIn("baostock/stock/basic", spiders)
        self.assertIn("baostock/stock/trade_dates", spiders)

    def test_baostock_mixed_basic_dependency_requires_stock_and_index_rows(self):
        manager = CrawlManager.__new__(CrawlManager)
        manager.settings = self._settings()
        manager._dependency_db_engine = DummyDependencyDB({"1": 2, "2": 0})

        spiders = manager.get_all_spiders(["baostock/stock/daily", "baostock/index/daily"])

        self.assertIn("baostock/stock/basic", spiders)
        self.assertIn("WHERE `type` IN ('1', '2')", manager._dependency_db_engine.queries[0])

    def test_baostock_trade_dates_queries_only_missing_tail_range(self):
        today = datetime.date.today()
        spider = BaostockTradeDatesSpider()
        spider.spider_settings = self._settings()
        spider.db_engine = DummyTradeDatesDB(1, today - datetime.timedelta(days=2))
        client = DummyTradeDatesClient()
        spider.client = client

        items = list(spider.parse_baostock(None))

        self.assertEqual(len(items), 1)
        self.assertEqual(client.calls[0][0], "query_trade_dates")
        self.assertEqual(client.calls[0][1]["start_date"], (today - datetime.timedelta(days=1)).isoformat())
        self.assertEqual(client.calls[0][1]["end_date"], today.isoformat())
        self.assertTrue(any("max(`calendar_date`)" in query for query in spider.db_engine.queries))

    def test_baostock_trade_dates_skips_query_when_local_calendar_is_current(self):
        today = datetime.date.today()
        spider = BaostockTradeDatesSpider()
        spider.spider_settings = self._settings()
        spider.db_engine = DummyTradeDatesDB(1, today)
        client = DummyTradeDatesClient()
        spider.client = client

        items = list(spider.parse_baostock(None))

        self.assertEqual(items, [])
        self.assertEqual(client.calls, [])

    def test_cross_source_rules_use_generic_metadata_and_comparable_fields(self):
        manager = CrossSourceQualityManager(settings=self._settings())

        schemas = manager._metadata_table_schemas()
        rules = {rule.rule_id: rule for rule in manager.build_rules("stock_eod_price", "2026-05-25")}

        self.assertIn("dq_cross_source_run", schemas)
        self.assertIn("dq_cross_source_result", schemas)
        self.assertIn("dq_cross_source_diff", schemas)
        self.assertIn("dq_source_quality_metric", schemas)
        self.assertIn("stock_eod_price_baostock_unadjusted", rules)
        self.assertIn("dwd_stock_eod_price", rules["stock_eod_price_close_diff"].issue_count_sql)
        self.assertIn("dwd_baostock_stock_eod_price", rules["stock_eod_price_close_diff"].issue_count_sql)
        self.assertIn("abs(toFloat64(t.close) - toFloat64(b.close))", rules["stock_eod_price_close_diff"].issue_count_sql)

    def test_baostock_daily_quota_reserves_and_blocks_at_limit(self):
        db = DummyQuotaDB(used_count=49999)
        quota = BaostockDailyQuota(
            db_engine=db,
            settings=self._settings(),
            spider_name="baostock/stock/daily",
            batch_id="batch",
            limit=50000,
        )

        quota.reserve("query_history_k_data_plus")

        self.assertEqual(quota.used_count, 50000)
        self.assertEqual(db.inserts[0][0], "baostock_api_request_log")
        self.assertEqual(db.inserts[0][1]["api_name"].iloc[0], "query_history_k_data_plus")
        with self.assertRaises(BaostockQuotaExceeded):
            quota.reserve("query_history_k_data_plus")

    def test_baostock_client_retries_transient_query_errors(self):
        fake_baostock = DummyBaostockModule(fail_times=2)
        original_module = sys.modules.get("baostock")
        sys.modules["baostock"] = fake_baostock
        try:
            client = BaostockClient(retry_attempts=3, retry_delay_seconds=0.5)

            with mock.patch("tushare_integration.spiders.baostock.base.time.sleep") as sleep:
                data = client.query("query_history_k_data_plus", code="sh.600000")
        finally:
            if original_module is None:
                sys.modules.pop("baostock", None)
            else:
                sys.modules["baostock"] = original_module

        self.assertEqual(fake_baostock.query_calls, 3)
        self.assertEqual(fake_baostock.logout_calls, 2)
        self.assertEqual(data["code"].tolist(), ["sh.600000"])
        self.assertEqual([call.args[0] for call in sleep.call_args_list], [0.5, 1.0])

    def test_baostock_client_raises_request_failed_after_retries(self):
        fake_baostock = DummyBaostockModule(fail_times=3)
        original_module = sys.modules.get("baostock")
        sys.modules["baostock"] = fake_baostock
        try:
            client = BaostockClient(retry_attempts=3, retry_delay_seconds=0)

            with self.assertRaises(BaostockRequestFailed):
                client.query("query_history_k_data_plus", code="sh.600000")
        finally:
            if original_module is None:
                sys.modules.pop("baostock", None)
            else:
                sys.modules["baostock"] = original_module

        self.assertEqual(fake_baostock.query_calls, 3)

    def test_baostock_code_list_prefers_local_basic_table(self):
        settings = self._settings()

        class DummyCodeListSpider(BaostockCodeListMixin):
            name = "baostock/stock/daily"
            code_type = "1"

            def __init__(self):
                self.spider_settings = settings
                self.db = DummyCodeListDB(pd.DataFrame({"code": ["sh.600000", "sz.000001"]}))

            def get_db_engine(self):
                return self.db

            def get_client(self):
                raise AssertionError("Baostock API should not be called when local codes exist")

        spider = DummyCodeListSpider()

        self.assertEqual(spider.load_codes(), ["sh.600000", "sz.000001"])
        self.assertIn("baostock_stock_basic FINAL", spider.db.queries[0])

    def test_baostock_stock_daily_code_list_filters_stock_type(self):
        spider = BaostockStockDailySpider()
        spider.spider_settings = self._settings()
        spider.db_engine = DummyCodeListDB(
            pd.DataFrame(
                {
                    "code": ["sh.000001", "sh.600000", "sz.399001"],
                    "type": ["2", "1", "2"],
                    "outDate": ["1970-01-01", "2020-05-15", "1970-01-01"],
                }
            )
        )

        self.assertEqual(spider.load_codes(), ["sh.600000"])
        self.assertIn("WHERE `type` = '1'", spider.db_engine.queries[0])

    def test_baostock_index_daily_code_list_filters_index_type(self):
        spider = BaostockIndexDailySpider()
        spider.spider_settings = self._settings()
        spider.db_engine = DummyCodeListDB(
            pd.DataFrame(
                {
                    "code": ["sh.000001", "sh.600000", "sz.399001"],
                    "type": ["2", "1", "2"],
                }
            )
        )

        self.assertEqual(spider.load_codes(), ["sh.000001", "sz.399001"])
        self.assertIn("WHERE `type` = '2'", spider.db_engine.queries[0])

    def test_baostock_daily_range_uses_per_code_latest_date(self):
        spider = BaostockStockDailySpider()
        spider.spider_settings = self._settings()
        spider.db_engine = DummyDailyRangeDB({"sh.600000": datetime.date(2026, 6, 1)})

        known_start_date, _ = spider.get_request_date_range("sh.600000")
        new_start_date, _ = spider.get_request_date_range("sz.000001")

        self.assertEqual(known_start_date, "2026-05-25")
        self.assertEqual(new_start_date, "2015-01-01")
        self.assertTrue(any("WHERE `code` = 'sh.600000'" in query for query in spider.db_engine.queries))
        self.assertTrue(any("WHERE `code` = 'sz.000001'" in query for query in spider.db_engine.queries))

    def test_baostock_daily_iter_code_frames_streams_missing_dates(self):
        spider = BaostockStockDailySpider()
        spider.spider_settings = self._settings()
        spider.db_engine = DummyDailyRangeDB(
            {"sh.600000": datetime.date(2026, 6, 1)},
            {"sh.600000": ["2026-05-28", "2026-05-29", "2026-06-02"]},
        )
        calls = []

        def query_func(code, start_date, end_date):
            calls.append((code, start_date, end_date))
            return pd.DataFrame([{"date": start_date, "code": code, "close": "1.0"}])

        frames = list(spider.iter_code_frames(query_func, ["sh.600000", "sz.000001"]))

        self.assertEqual(len(frames), 2)
        self.assertEqual(calls[0], ("sh.600000", "2026-05-28", "2026-06-02"))
        self.assertEqual(calls[1][0:2], ("sz.000001", "2015-01-01"))

    def test_baostock_daily_iter_code_frames_skips_failed_request_and_continues(self):
        spider = BaostockStockDailySpider()
        spider.spider_settings = self._settings()
        spider.db_engine = DummyDailyRangeDB({}, code_rows=pd.DataFrame(columns=["code", "type", "outDate"]))
        calls = []

        def query_func(code, start_date, end_date):
            calls.append((code, start_date, end_date))
            if code == "sh.600000":
                raise BaostockRequestFailed("Baostock query_history_k_data_plus failed after 3 attempts")
            return pd.DataFrame([{"date": start_date, "code": code, "close": "1.0"}])

        frames = list(spider.iter_code_frames(query_func, ["sh.600000", "sz.000001"]))

        self.assertEqual(len(frames), 1)
        self.assertEqual(calls[0][0], "sh.600000")
        self.assertEqual(calls[1][0], "sz.000001")

    def test_baostock_stock_daily_caps_request_range_at_delist_date(self):
        spider = BaostockStockDailySpider()
        spider.spider_settings = self._settings()
        spider.db_engine = DummyDailyRangeDB(
            {},
            code_rows=pd.DataFrame(
                {
                    "code": ["sh.600000", "sh.000001"],
                    "type": ["1", "2"],
                    "outDate": ["2020-05-15", "1970-01-01"],
                }
            ),
        )
        calls = []

        def query_func(code, start_date, end_date):
            calls.append((code, start_date, end_date))
            return pd.DataFrame([{"date": start_date, "code": code, "close": "1.0"}])

        frames = list(spider.iter_code_frames(query_func, spider.load_codes()))

        self.assertEqual(len(frames), 1)
        self.assertEqual(calls, [("sh.600000", "2015-01-01", "2020-05-15")])

    def test_baostock_financial_quarters_stop_after_delist_date(self):
        spider = BaostockStockProfitSpider()
        spider.spider_settings = self._settings()
        spider.db_engine = DummyDailyRangeDB(
            {},
            code_rows=pd.DataFrame(
                {
                    "code": ["sh.600005"],
                    "type": ["1"],
                    "outDate": ["2017-08-16"],
                }
            ),
        )

        quarters = list(spider.iter_code_year_quarters("sh.600005"))

        self.assertEqual(quarters[-1], (2017, 2))
        self.assertNotIn((2020, 3), quarters)

    def test_baostock_financial_quarters_skip_existing_stat_dates(self):
        spider = BaostockStockProfitSpider()
        spider.spider_settings = self._settings()
        spider.db_engine = DummyDailyRangeDB(
            {},
            code_rows=pd.DataFrame(
                {
                    "code": ["sh.600005"],
                    "type": ["1"],
                    "ipoDate": ["2015-01-01"],
                    "outDate": ["2017-08-16"],
                }
            ),
            existing_stat_dates_by_code={
                "sh.600005": ["2015-03-31", "2015-06-30", "2017-06-30"],
            },
        )

        quarters = list(spider.iter_code_year_quarters("sh.600005"))

        self.assertNotIn((2015, 1), quarters)
        self.assertNotIn((2015, 2), quarters)
        self.assertNotIn((2017, 2), quarters)
        self.assertIn((2015, 3), quarters)

    def test_baostock_financial_quarters_skip_pre_ipo_and_future_quarters(self):
        today = datetime.date.today()
        spider = BaostockStockProfitSpider()
        spider.spider_settings = self._settings()
        spider.db_engine = DummyDailyRangeDB(
            {},
            code_rows=pd.DataFrame(
                {
                    "code": ["sh.600005"],
                    "type": ["1"],
                    "ipoDate": ["2020-05-15"],
                    "outDate": ["1970-01-01"],
                }
            ),
        )

        quarters = list(spider.iter_code_year_quarters("sh.600005"))

        self.assertEqual(quarters[0], (2020, 2))
        self.assertTrue(
            all(BaostockStockProfitSpider.quarter_end_date(year, quarter) <= today for year, quarter in quarters)
        )

    def test_baostock_financial_parse_does_not_request_after_delist_date(self):
        spider = BaostockStockProfitSpider()
        spider.spider_settings = self._settings()
        spider.db_engine = DummyDailyRangeDB(
            {},
            code_rows=pd.DataFrame(
                {
                    "code": ["sh.600005"],
                    "type": ["1"],
                    "outDate": ["2017-08-16"],
                }
            ),
        )
        calls = []

        def query_financial(code, year, quarter):
            calls.append((code, year, quarter))
            return pd.DataFrame(
                [
                    {
                        "code": code,
                        "pubDate": f"{year}-01-01",
                        "statDate": f"{year}-{quarter * 3:02d}-01",
                    }
                ]
            )

        spider.query_financial = query_financial

        list(spider.parse_baostock(None))

        self.assertEqual(calls[-1], ("sh.600005", 2017, 2))
        self.assertNotIn(("sh.600005", 2020, 3), calls)

    def test_baostock_financial_indicator_quarters_stop_after_delist_date(self):
        spider = BaostockStockFinancialIndicatorSpider()
        spider.spider_settings = self._settings()
        spider.db_engine = DummyDailyRangeDB(
            {},
            code_rows=pd.DataFrame(
                {
                    "code": ["sh.600005"],
                    "type": ["1"],
                    "outDate": ["2017-08-16"],
                }
            ),
        )

        quarters = list(spider.iter_code_year_quarters("sh.600005"))

        self.assertEqual(quarters[-1], (2017, 2))
        self.assertNotIn((2020, 3), quarters)

    def test_baostock_daily_iter_code_frames_skips_existing_lookback_dates(self):
        spider = BaostockStockDailySpider()
        spider.spider_settings = self._settings()
        spider.db_engine = DummyDailyRangeDB({"sh.600000": datetime.date(2026, 6, 10)})
        calls = []

        def query_func(code, start_date, end_date):
            calls.append((code, start_date, end_date))
            return pd.DataFrame([{"date": start_date, "code": code, "close": "1.0"}])

        frames = list(spider.iter_code_frames(query_func, ["sh.600000"]))

        self.assertEqual(frames, [])
        self.assertEqual(calls, [])
        self.assertTrue(any("calendar_date NOT IN" in query for query in spider.db_engine.queries))
        self.assertTrue(any("baostock_trade_dates" in query for query in spider.db_engine.queries))
        self.assertFalse(any("trade_cal" in query for query in spider.db_engine.queries))


if __name__ == "__main__":
    unittest.main()
