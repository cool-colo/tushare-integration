import json
import unittest
from unittest import mock
from types import SimpleNamespace

import pandas as pd

from tushare_integration.spiders.index.quotes import IndexDailySpider, IndexWeightSpider, get_incremental_priority_codes
from tushare_integration.spiders.stock.market import DCIndexSpider
from tushare_integration.spiders.stock.quotes import StockDailySpider


class DummyDB:
    def __init__(self, responses):
        self.responses = list(responses)
        self.queries = []

    def query_df(self, sql):
        self.queries.append(sql)
        return self.responses.pop(0)


class IncrementalPolicyTest(unittest.TestCase):
    @staticmethod
    def _settings(backfill_days=0, default_min_cal_date="2010-01-01", index_priority_codes=None):
        return SimpleNamespace(
            tushare_url="https://api.tushare.pro",
            tushare_token="token",
            incremental_backfill_days=backfill_days,
            index_priority_codes=index_priority_codes or [],
            default_min_cal_date=default_min_cal_date,
            database=SimpleNamespace(db_name="default"),
        )

    @staticmethod
    def _request_params(request):
        return json.loads(request.body.decode("utf-8"))["params"]

    def test_daily_spider_uses_latest_date_with_configured_backfill_window(self):
        spider = StockDailySpider()
        spider.spider_settings = self._settings(backfill_days=7)
        spider.db_engine = DummyDB(
            [
                pd.DataFrame({"row_count": [10], "latest_trade_date": [pd.Timestamp("2026-05-08")]}),
                pd.DataFrame({"cal_date": pd.to_datetime(["2026-05-11"])}),
            ]
        )

        requests = list(spider.start_requests())

        self.assertEqual([self._request_params(request) for request in requests], [{"trade_date": "20260511"}])
        self.assertTrue(any("cal_date >= '2026-05-01'" in query for query in spider.db_engine.queries))
        self.assertNotIn("1970-01-01", spider.db_engine.queries[-1])

    def test_empty_daily_table_uses_configured_default_when_min_cal_date_missing(self):
        spider = StockDailySpider()
        spider.custom_settings = {"TABLE_NAME": "daily"}
        spider.spider_settings = self._settings(default_min_cal_date="2024-01-01")
        spider.db_engine = DummyDB(
            [
                pd.DataFrame({"row_count": [0], "latest_trade_date": [pd.NaT]}),
                pd.DataFrame({"cal_date": pd.to_datetime(["2024-01-02"])}),
            ]
        )

        requests = list(spider.start_requests())

        self.assertEqual([self._request_params(request) for request in requests], [{"trade_date": "20240102"}])
        self.assertIn("cal_date >= '2024-01-01'", spider.db_engine.queries[-1])
        self.assertNotIn("1970-01-01", spider.db_engine.queries[-1])

    def test_index_daily_uses_daily_ts_code_trade_date_incremental_requests(self):
        spider = IndexDailySpider()
        spider.spider_settings = self._settings(backfill_days=7)
        spider.db_engine = DummyDB(
            [
                pd.DataFrame({"row_count": [10], "latest_trade_date": [pd.Timestamp("2026-05-08")]}),
                pd.DataFrame({"cal_date": pd.to_datetime(["2026-05-11"])}),
                pd.DataFrame(
                    {
                        "ts_code": ["000001.SH", "000002.SH"],
                        "base_date": [pd.Timestamp("1990-12-19"), pd.Timestamp("2026-05-12")],
                        "list_date": [pd.Timestamp("1991-07-15"), pd.Timestamp("2026-05-12")],
                        "exp_date": [pd.Timestamp("1970-01-01"), pd.Timestamp("1970-01-01")],
                    }
                ),
                pd.DataFrame({"ts_code": ["000002.SH"], "trade_date": pd.to_datetime(["2026-05-11"])}),
            ]
        )

        with mock.patch.object(spider, "get_request_end_date", return_value=pd.Timestamp("2026-05-11").date()):
            requests = list(spider.start_requests())

        self.assertEqual(
            [self._request_params(request) for request in requests],
            [{"ts_code": "000001.SH", "trade_date": "20260511"}],
        )
        self.assertTrue(any("cal_date >= '2026-05-01'" in query for query in spider.db_engine.queries))
        self.assertTrue(any("market IN ('CSI', 'SSE', 'SZSE')" in query for query in spider.db_engine.queries))

    def test_daily_type_spider_uses_dimension_high_watermark_not_full_history(self):
        spider = DCIndexSpider()
        spider.spider_settings = self._settings(backfill_days=7)
        spider.db_engine = DummyDB(
            [
                pd.DataFrame({"row_count": [100], "latest_trade_date": [pd.Timestamp("2026-05-11")]}),
                pd.DataFrame({"row_count": [100], "latest_trade_date": [pd.Timestamp("2026-05-11")]}),
                pd.DataFrame({"row_count": [100], "latest_trade_date": [pd.Timestamp("2026-05-11")]}),
                pd.DataFrame(columns=["trade_date", "idx_type"]),
                pd.DataFrame({"cal_date": pd.to_datetime(["2026-05-05"])}),
            ]
        )

        requests = list(spider.start_requests())

        self.assertEqual(
            [self._request_params(request) for request in requests],
            [
                {"trade_date": "20260505", "idx_type": "行业板块"},
                {"trade_date": "20260505", "idx_type": "概念板块"},
                {"trade_date": "20260505", "idx_type": "地域板块"},
            ],
        )
        self.assertIn("cal_date >= '2026-05-04'", spider.db_engine.queries[-1])
        self.assertNotIn("1990-12-19", "\n".join(spider.db_engine.queries))

    def test_index_incremental_priority_codes_and_empty_default(self):
        spider = IndexDailySpider(job_update_type="incremental")
        spider.spider_settings = self._settings()
        self.assertIsNone(get_incremental_priority_codes(spider))
        spider.spider_settings.index_priority_codes = [" 000300.SH ", "000300.SH"]
        self.assertEqual(get_incremental_priority_codes(spider), ["000300.SH"])
        spider.spider_settings.index_priority_codes = ["invalid"]
        with self.assertRaisesRegex(ValueError, "Invalid index_priority_codes"):
            get_incremental_priority_codes(spider)

    def test_index_daily_incremental_filters_universe(self):
        spider = IndexDailySpider(job_update_type="incremental")
        spider.spider_settings = self._settings(index_priority_codes=["000300.SH"])
        spider.db_engine = DummyDB([
            pd.DataFrame({"row_count": [10], "latest_trade_date": [pd.Timestamp("2026-05-08")]}),
            pd.DataFrame({"cal_date": pd.to_datetime(["2026-05-11"])}),
            pd.DataFrame({"ts_code": ["000300.SH", "000001.SH"], "list_date": pd.to_datetime(["2005-04-08"] * 2)}),
            pd.DataFrame(columns=["ts_code", "trade_date"]),
        ])
        with mock.patch.object(spider, "get_request_end_date", return_value=pd.Timestamp("2026-05-11").date()):
            requests = list(spider.start_requests())
        self.assertEqual([self._request_params(r) for r in requests], [{"ts_code": "000300.SH", "trade_date": "20260511"}])

    def test_index_daily_full_repairs_old_nonpriority_gap(self):
        spider = IndexDailySpider(job_update_type="full")
        spider.spider_settings = self._settings(index_priority_codes=["000300.SH"])
        spider.custom_settings = spider.custom_settings | {"MIN_CAL_DATE": "2026-05-01"}
        # The core index already has the latest date, but another index has an older gap.
        spider.db_engine = DummyDB([
            pd.DataFrame({"cal_date": pd.to_datetime(["2026-05-04", "2026-05-11"])}),
            pd.DataFrame({"ts_code": ["000300.SH", "000001.SH"], "list_date": pd.to_datetime(["2005-04-08"] * 2)}),
            pd.DataFrame({"ts_code": ["000300.SH", "000300.SH", "000001.SH"],
                          "trade_date": pd.to_datetime(["2026-05-04", "2026-05-11", "2026-05-11"])}),
        ])
        with mock.patch.object(spider, "get_request_end_date", return_value=pd.Timestamp("2026-05-11").date()):
            requests = list(spider.start_requests())
        self.assertEqual([self._request_params(r) for r in requests], [{"ts_code": "000001.SH", "trade_date": "20260504"}])
        self.assertIn("cal_date >= '2026-05-01'", spider.db_engine.queries[0])
        self.assertFalse(any("max(" in sql for sql in spider.db_engine.queries))

    def test_index_weight_full_replays_older_months_for_all_codes(self):
        spider = IndexWeightSpider(job_update_type="full")
        spider.spider_settings = self._settings(index_priority_codes=["000300.SH"])
        spider.custom_settings = spider.custom_settings | {"MIN_CAL_DATE": "2026-09-01"}
        spider.db_engine = DummyDB([
            pd.DataFrame({"ts_code": ["000300.SH", "000001.SH"], "list_date": pd.to_datetime(["2005-04-08"] * 2)}),
        ])
        with mock.patch.object(spider, "get_request_end_date", return_value=pd.Timestamp("2026-11-05").date()):
            requests = list(spider.start_requests())
        params = [self._request_params(r) for r in requests]
        self.assertEqual(len(params), 6)
        self.assertIn({"index_code": "000001.SH", "start_date": "20260901", "end_date": "20260930"}, params)
        self.assertFalse(any("max(" in sql for sql in spider.db_engine.queries))

    def test_index_weight_incremental_uses_priority_universe(self):
        spider = IndexWeightSpider(job_update_type="incremental")
        spider.spider_settings = self._settings(index_priority_codes=["000300.SH"])
        spider.db_engine = DummyDB([
            pd.DataFrame({"row_count": [10], "latest_trade_date": [pd.Timestamp("2026-10-30")]}),
            pd.DataFrame({"ts_code": ["000300.SH", "000001.SH"], "list_date": pd.to_datetime(["2005-04-08"] * 2)}),
        ])
        with mock.patch.object(spider, "get_request_end_date", return_value=pd.Timestamp("2026-11-05").date()):
            requests = list(spider.start_requests())
        params = [self._request_params(r) for r in requests]
        self.assertEqual({p["index_code"] for p in params}, {"000300.SH"})
        self.assertEqual(len(params), 2)


if __name__ == "__main__":
    unittest.main()
