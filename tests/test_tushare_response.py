import json
import unittest
from types import SimpleNamespace
from unittest import mock

import pandas as pd

from tushare_integration.settings import TushareIntegrationSettings
from tushare_integration.db_engine import ClickhouseEngine
from tushare_integration.dws import DWS_CLICKHOUSE_SEND_RECEIVE_TIMEOUT, DWSManager
from tushare_integration.manager import CrawlManager
from tushare_integration.spiders.index.quotes import IndexWeightSpider
from tushare_integration.spiders.stock.special import CyqChipsSpider


class DummyResponse:
    def __init__(self, payload, params=None):
        self.text = json.dumps(payload, ensure_ascii=False)
        self.meta = {"params": params or {}}


class DummySpiderSettings(SimpleNamespace):
    tushare_url = "https://api.tushare.pro"
    tushare_token = "token"

    def get_download_delay(self):
        return 0.25


class DummyDB:
    def __init__(self, responses):
        self.responses = responses
        self.queries = []

    def query_df(self, sql):
        self.queries.append(sql)
        return self.responses.pop(0)


class TushareResponseTest(unittest.TestCase):
    def _clickhouse_settings(self):
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
        )

    def test_clickhouse_engine_applies_send_receive_timeout(self):
        settings = self._clickhouse_settings()

        with mock.patch("tushare_integration.db_engine.clickhouse_connect.get_client") as get_client:
            ClickhouseEngine(settings, send_receive_timeout=1200)

        self.assertEqual(get_client.call_args.kwargs["send_receive_timeout"], 1200)

    def test_dws_clickhouse_sync_uses_extended_timeout(self):
        manager = object.__new__(DWSManager)
        manager.settings = self._clickhouse_settings()
        manager.db_engine = None
        db_engine = object()

        with mock.patch("tushare_integration.dws.DatabaseEngineFactory.create", return_value=db_engine) as create:
            self.assertIs(manager.get_db_engine(), db_engine)

        create.assert_called_once_with(
            manager.settings,
            clickhouse_send_receive_timeout=DWS_CLICKHOUSE_SEND_RECEIVE_TIMEOUT,
        )

    def test_dws_stock_factor_wide_uses_asof_financial_join(self):
        manager = object.__new__(DWSManager)
        manager.settings = self._clickhouse_settings()

        sql = manager.render_sync_sql("dws_stock_factor_wide")

        self.assertIn("ASOF LEFT JOIN financial_indicator", sql)
        self.assertIn("price.available_trade_date >= financial_indicator.available_trade_date", sql)
        self.assertIn("PARTITION BY src.instrument_id, src.available_trade_date", sql)
        self.assertNotIn("financial_indicator.available_trade_date <= price.available_trade_date", sql)
        self.assertNotIn("available_trade_date <= price.available_trade_date", sql)
        self.assertNotIn("PARTITION BY price.instrument_id, price.event_date", sql)

    def test_parse_response_treats_common_no_data_message_as_empty_item(self):
        spider = CyqChipsSpider()
        response = DummyResponse(
            {
                "code": -2001,
                "msg": "抱歉，您查询的数据为空，请确认输入参数是否正确",
                "data": None,
            },
            params={"ts_code": "000001.SZ", "trade_date": "20180102"},
        )

        item = spider.parse_response(response)

        self.assertTrue(item["data"].empty)
        self.assertEqual(item["data"].columns.tolist(), ["ts_code", "trade_date", "price", "percent"])

    def test_parse_response_treats_success_without_data_payload_as_empty_item(self):
        spider = CyqChipsSpider()
        response = DummyResponse({"code": 0, "msg": "", "data": None})

        item = spider.parse_response(response)

        self.assertTrue(item["data"].empty)
        self.assertEqual(item["data"].columns.tolist(), ["ts_code", "trade_date", "price", "percent"])

    def test_manager_signal_description_includes_failure_message(self):
        class DummyFailure:
            value = RuntimeError("api failed")

        detail = CrawlManager.describe_signal({"signal": object(), "spider": None, "failure": DummyFailure()})

        self.assertIn("api failed", detail)

    def test_manager_does_not_raise_for_tushare_rate_limit_signal(self):
        class DummyFailure:
            value = RuntimeError("抱歉，您访问接口(cyq_chips)频率超限(200000次/天)")

        manager = object.__new__(CrawlManager)
        manager.signals = [{"signal": object(), "spider": None, "failure": DummyFailure()}]

        manager.raise_for_signal()

    def test_manager_still_raises_for_non_rate_limit_signal(self):
        class DummyFailure:
            value = RuntimeError("api failed")

        manager = object.__new__(CrawlManager)
        manager.signals = [{"signal": object(), "spider": None, "failure": DummyFailure()}]

        with self.assertRaisesRegex(RuntimeError, "api failed"):
            manager.raise_for_signal()

    def test_settings_apply_safety_ratio_to_auto_frequency(self):
        settings = TushareIntegrationSettings(
            tushare_token="token",
            tushare_point=5000,
            feishu_webhook="",
            database={
                "db_type": "clickhouse",
                "host": "localhost",
                "port": 8123,
                "user": "default",
                "password": "",
                "db_name": "default",
            },
        )

        self.assertEqual(settings.get_max_request_frequency(), 500)
        self.assertEqual(settings.get_effective_request_frequency(), 450)
        self.assertAlmostEqual(settings.get_settings()["DOWNLOAD_DELAY"], 60 / 450)

    def test_settings_preserve_manual_frequency_as_effective_frequency(self):
        settings = TushareIntegrationSettings(
            tushare_token="token",
            tushare_point=5000,
            tushare_max_concurrent_requests=400,
            tushare_rate_limit_ratio=0.5,
            feishu_webhook="",
            database={
                "db_type": "clickhouse",
                "host": "localhost",
                "port": 8123,
                "user": "default",
                "password": "",
                "db_name": "default",
            },
        )

        self.assertEqual(settings.get_max_request_frequency(), 400)
        self.assertEqual(settings.get_effective_request_frequency(), 400)
        self.assertAlmostEqual(settings.get_settings()["DOWNLOAD_DELAY"], 0.15)

    def test_request_with_requests_uses_shared_rate_limiter(self):
        spider = CyqChipsSpider()
        spider.spider_settings = DummySpiderSettings()
        response = DummyResponse(
            {
                "code": 0,
                "msg": "",
                "data": {
                    "fields": ["ts_code", "trade_date", "price", "percent"],
                    "items": [],
                },
            }
        )

        with (
            mock.patch("tushare_integration.spiders.tushare.TushareRequestRateLimiter.wait") as wait,
            mock.patch("tushare_integration.spiders.tushare.requests.post", return_value=response),
        ):
            spider.request_with_requests({"ts_code": "000001.SZ"})

        wait.assert_called_once_with(0.25)

    def test_request_with_requests_retries_rate_limit_response(self):
        spider = CyqChipsSpider()
        spider.spider_settings = DummySpiderSettings(retry_times=1, retry_delay=1)
        rate_limited_response = DummyResponse({"code": 40201, "msg": "频率超限", "data": None})
        success_response = DummyResponse(
            {
                "code": 0,
                "msg": "",
                "data": {
                    "fields": ["ts_code", "trade_date", "price", "percent"],
                    "items": [],
                },
            }
        )

        with (
            mock.patch("tushare_integration.spiders.tushare.TushareRequestRateLimiter.wait"),
            mock.patch(
                "tushare_integration.spiders.tushare.requests.post",
                side_effect=[rate_limited_response, success_response],
            ) as post,
            mock.patch("tushare_integration.spiders.tushare.time.sleep") as sleep,
        ):
            spider.request_with_requests({"ts_code": "000001.SZ"})

        self.assertEqual(post.call_count, 2)
        sleep.assert_called_once_with(60)

    def test_cyq_chips_uses_latest_trade_date_by_default(self):
        spider = CyqChipsSpider()
        spider.spider_settings = DummySpiderSettings(database=SimpleNamespace(db_name="default"))
        fake_db = DummyDB(
            [
                pd.DataFrame({"latest_trade_date": [pd.Timestamp("2026-05-08")]}),
                pd.DataFrame({"trade_date": pd.to_datetime(["2026-05-11"])}),
            ]
        )

        trade_dates = spider.get_missing_trade_dates(fake_db, "000565.SZ")

        self.assertEqual(trade_dates["trade_date"].dt.strftime("%Y%m%d").tolist(), ["20260511"])
        self.assertIn("trade_date > '2026-05-08'", fake_db.queries[-1])
        self.assertNotIn("NOT IN", fake_db.queries[-1])

    def test_cyq_chips_can_opt_into_gap_backfill(self):
        spider = CyqChipsSpider()
        spider.spider_settings = DummySpiderSettings(database=SimpleNamespace(db_name="default"))
        spider.custom_settings = spider.custom_settings | {"BACKFILL_GAPS": True}
        fake_db = DummyDB([pd.DataFrame({"trade_date": pd.to_datetime(["2022-05-24"])})])

        trade_dates = spider.get_missing_trade_dates(fake_db, "000565.SZ")

        self.assertEqual(trade_dates["trade_date"].dt.strftime("%Y%m%d").tolist(), ["20220524"])
        self.assertIn("NOT IN", fake_db.queries[-1])

    def test_cyq_chips_primary_key_preserves_price_buckets(self):
        spider = CyqChipsSpider()

        self.assertEqual(spider.schema["primary_key"], ["ts_code", "trade_date", "price"])

    def test_index_weight_parse_schedules_next_page_through_scrapy(self):
        spider = IndexWeightSpider()
        spider.spider_settings = DummySpiderSettings()
        response = DummyResponse(
            {
                "code": 0,
                "msg": "",
                "data": {
                    "fields": ["index_code", "con_code", "trade_date", "weight"],
                    "items": [
                        ["000001.SH", "000001.SZ", "20200101", 1.0],
                        ["000001.SH", "000002.SZ", "20200101", 2.0],
                    ],
                },
            }
        )
        response.meta = {"trade_date": "20200101", "offset": 0, "limit": 2, "index_weight_pages": []}

        outputs = list(spider.parse(response))

        self.assertEqual(len(outputs), 1)
        request = outputs[0]
        body = json.loads(request.body.decode("utf-8"))
        self.assertEqual(body["params"], {"trade_date": "20200101", "offset": 2, "limit": 2})
        self.assertEqual(request.meta["trade_date"], "20200101")
        self.assertEqual(request.meta["offset"], 2)
        self.assertEqual(len(request.meta["index_weight_pages"]), 1)
        self.assertEqual(len(request.meta["index_weight_pages"][0]), 2)

    def test_index_weight_parse_emits_accumulated_pages_when_done(self):
        spider = IndexWeightSpider()
        accumulated = pd.DataFrame(
            [["000001.SH", "000001.SZ", "20200101", 1.0]],
            columns=["index_code", "con_code", "trade_date", "weight"],
        )
        response = DummyResponse(
            {
                "code": 0,
                "msg": "",
                "data": {
                    "fields": ["index_code", "con_code", "trade_date", "weight"],
                    "items": [],
                },
            }
        )
        response.meta = {
            "trade_date": "20200101",
            "offset": 2,
            "limit": 2,
            "index_weight_pages": [accumulated],
        }

        outputs = list(spider.parse(response))

        self.assertEqual(len(outputs), 1)
        self.assertEqual(outputs[0]["data"].to_dict("records"), accumulated.to_dict("records"))


if __name__ == "__main__":
    unittest.main()
