import json
import unittest
from types import SimpleNamespace
from unittest import mock

import pandas as pd

from tushare_integration.dwd import DWDManager
from tushare_integration.quality import QualityManager
from tushare_integration.settings import TushareIntegrationSettings
from tushare_integration.spiders.fund.basic import EtfBasicSpider, EtfIndexSpider
from tushare_integration.spiders.fund.quotes import EtfLimitSpider, FundAdjSpider, FundDailySpider


class DummyDB:
    def __init__(self, responses):
        self.responses = list(responses)
        self.queries = []

    def query_df(self, sql):
        self.queries.append(sql)
        return self.responses.pop(0)


class EtfSpiderTest(unittest.TestCase):
    @staticmethod
    def _settings(backfill_days=0, default_min_cal_date="2010-01-01"):
        return SimpleNamespace(
            tushare_url="https://api.tushare.pro",
            tushare_token="token",
            incremental_backfill_days=backfill_days,
            default_min_cal_date=default_min_cal_date,
            database=SimpleNamespace(db_name="default"),
        )

    @staticmethod
    def _request_body(request):
        return json.loads(request.body.decode("utf-8"))

    def test_fund_daily_spider_builds_trade_date_requests(self):
        spider = FundDailySpider()
        spider.spider_settings = self._settings(backfill_days=7)
        spider.db_engine = DummyDB(
            [
                pd.DataFrame({"row_count": [10], "latest_trade_date": [pd.Timestamp("2026-05-08")]}),
                pd.DataFrame({"cal_date": pd.to_datetime(["2026-05-11"])}),
            ]
        )

        requests = list(spider.start_requests())

        self.assertEqual(
            [self._request_body(request)["params"] for request in requests],
            [{"trade_date": "20260511"}],
        )
        self.assertEqual(self._request_body(requests[0])["api_name"], "fund_daily")
        # fund_daily 的 _raw 审计表名由 TABLE_NAME 决定
        self.assertEqual(spider.get_table_name(), "fund_daily")

    def test_etf_limit_spider_uses_min_cal_date_floor_for_empty_table(self):
        spider = EtfLimitSpider()
        spider.spider_settings = self._settings(default_min_cal_date="2010-01-01")
        spider.db_engine = DummyDB(
            [
                pd.DataFrame({"row_count": [0], "latest_trade_date": [pd.NaT]}),
                pd.DataFrame({"cal_date": pd.to_datetime(["2004-01-05"])}),
            ]
        )

        requests = list(spider.start_requests())

        self.assertEqual(
            [self._request_body(request)["params"] for request in requests],
            [{"trade_date": "20040105"}],
        )
        self.assertEqual(self._request_body(requests[0])["api_name"], "etf_limit")
        # custom_settings 的 MIN_CAL_DATE 把回填下限锁在 ETF 上市之初 2004 年
        self.assertIn("cal_date >= '2004-01-01'", spider.db_engine.queries[-1])

    def test_fund_adj_spider_api_and_table(self):
        spider = FundAdjSpider()
        self.assertEqual(spider.api_name, "fund_adj")
        self.assertEqual(spider.custom_settings["TABLE_NAME"], "fund_adj")
        self.assertEqual(spider.custom_settings["MIN_CAL_DATE"], "2004-01-01")

    def test_etf_basic_spider_requests_both_exchanges(self):
        spider = EtfBasicSpider()
        spider.spider_settings = self._settings()

        requests = list(spider.start_requests())

        self.assertEqual(
            [self._request_body(request)["params"] for request in requests],
            [{"exchange": "SH"}, {"exchange": "SZ"}],
        )
        self.assertEqual(self._request_body(requests[0])["api_name"], "etf_basic")

    def test_etf_index_spider_single_full_fetch(self):
        spider = EtfIndexSpider()
        spider.spider_settings = self._settings()

        requests = list(spider.start_requests())

        self.assertEqual([self._request_body(request)["params"] for request in requests], [{}])
        self.assertEqual(self._request_body(requests[0])["api_name"], "etf_index")

    def test_schema_fields_match_api_defaults(self):
        self.assertEqual(
            EtfBasicSpider().load_fields().split(","),
            [
                "ts_code", "csname", "extname", "cname", "index_code", "index_name",
                "setup_date", "list_date", "list_status", "exchange", "mgr_name",
                "custod_name", "mgt_fee", "etf_type",
            ],
        )
        self.assertIn("adj_factor", FundAdjSpider().load_fields().split(","))
        self.assertEqual(
            EtfLimitSpider().load_fields().split(","),
            ["trade_date", "ts_code", "pre_close", "up_limit", "down_limit"],
        )


class EtfDwdTest(unittest.TestCase):
    @staticmethod
    def settings():
        return TushareIntegrationSettings(
            tushare_token="token",
            feishu_webhook="",
            database={
                "db_type": "clickhouse", "host": "localhost", "port": 8123,
                "user": "default", "password": "", "db_name": "default",
            },
            quality={"mode": "strict", "create_result_tables": False},
        )

    def _manager(self):
        manager = DWDManager.__new__(DWDManager)
        manager.settings = self.settings()
        return manager

    def test_etf_price_adj_limit_use_fund_prefix_and_pit_columns(self):
        manager = self._manager()
        cases = {
            "dwd_etf_eod_price": "fund_daily_raw",
            "dwd_etf_adj_factor": "fund_adj_raw",
            "dwd_etf_limit": "etf_limit_raw",
        }
        for table, source_table in cases.items():
            spec = manager.load_spec(table)
            sql = manager.render_sync_sql(table)
            columns = {column["name"] for column in manager.build_schema(spec)["columns"]}
            self.assertIn(f"FROM default.{source_table} src", sql)
            self.assertIn("concat('fund:', src.ts_code) AS `instrument_id`", sql)
            self.assertIn("src.trade_date AS `event_date`", sql)
            self.assertIn("coalesce(calendar_map.next_trade_date, src.trade_date)", sql)
            self.assertEqual(manager.get_required_source_tables(spec), sorted([source_table, "trade_cal"]))
            for pit_column in ("instrument_id", "event_date", "available_trade_date", "sys_from", "sys_to"):
                self.assertIn(pit_column, columns)

    def test_etf_basic_reference_table_keyed_on_ingest_time(self):
        manager = self._manager()
        spec = manager.load_spec("dwd_etf_basic")
        sql = manager.render_sync_sql("dwd_etf_basic")
        self.assertIn("FROM default.etf_basic_raw raw", sql)
        self.assertIn("concat('fund:', raw.ts_code) AS `instrument_id`", sql)
        self.assertIn("toDate(raw._ingest_time) AS `event_date`", sql)
        self.assertEqual(manager.get_required_source_tables(spec), sorted(["etf_basic_raw", "trade_cal"]))

    def test_etf_index_reference_table_uses_index_prefix(self):
        manager = self._manager()
        sql = manager.render_sync_sql("dwd_etf_index")
        self.assertIn("FROM default.etf_index_raw raw", sql)
        self.assertIn("concat('index:', raw.ts_code) AS `instrument_id`", sql)

    def test_security_master_unions_etf_basic(self):
        manager = self._manager()
        spec = manager.load_spec("dwd_security_master")
        sql = manager.render_sync_sql("dwd_security_master")
        self.assertIn("FROM default.etf_basic_raw src", sql)
        self.assertIn("'fund' AS instrument_type", sql)
        self.assertIn("concat('fund:', src.ts_code) AS instrument_id", sql)
        self.assertIn("'etf_basic_raw' AS source_table", sql)
        self.assertIn("etf_basic_raw", manager.get_required_source_tables(spec))


class EtfQualityTest(unittest.TestCase):
    @staticmethod
    def settings():
        return TushareIntegrationSettings(
            tushare_token="token",
            feishu_webhook="",
            database={
                "db_type": "clickhouse", "host": "localhost", "port": 8123,
                "user": "default", "password": "", "db_name": "default",
            },
            quality={"mode": "strict", "create_result_tables": False},
        )

    def _rules(self, table):
        manager = QualityManager(settings=self.settings(), db_engine=mock.Mock())
        return {rule.rule_id: rule for rule in manager.build_rules("dwd", table, f"{table}_tmp")}

    def test_etf_eod_price_reuses_market_price_rules(self):
        rules = self._rules("dwd_etf_eod_price")
        self.assertIn("market_ohlc_consistency", rules)

    def test_etf_adj_factor_requires_positive_factor(self):
        rules = self._rules("dwd_etf_adj_factor")
        self.assertIn("adj_factor_positive", rules)
        self.assertIn("adj_factor <= 0", rules["adj_factor_positive"].issue_count_sql)

    def test_etf_limit_reuses_stock_limit_rules(self):
        rules = self._rules("dwd_etf_limit")
        self.assertIn("stock_limit_positive_prices", rules)


if __name__ == "__main__":
    unittest.main()
