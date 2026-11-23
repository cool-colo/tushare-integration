import datetime
import json
import unittest
from types import SimpleNamespace
from unittest import mock

import pandas as pd
from scrapy import signals
from scrapy.http import TextResponse

from tushare_integration.spiders.stock.special import CyqChipsSpider
from tushare_integration.cyq_chips_progress import CyqChipsProgressStore


class CyqChipsPaginationTest(unittest.TestCase):
    def setUp(self):
        self.spider = CyqChipsSpider()
        self.spider.spider_settings = SimpleNamespace(
            tushare_url="https://api.tushare.pro",
            tushare_token="token",
            database=SimpleNamespace(db_name="default", db_type="clickhouse"),
        )
        self.spider.db_engine = mock.Mock()
        self.settings_store = mock.Mock()
        self.spider.progress_store = self.settings_store

    @staticmethod
    def row(ts_code="000001.SZ", trade_date="20261105", price=10.0):
        return [ts_code, trade_date, price, 1.0]

    def response(self, rows, *, offset=0, start_date="20261105", end_date="20261105"):
        params = {
            "ts_code": "000001.SZ",
            "start_date": start_date,
            "end_date": end_date,
            "limit": self.spider.PAGE_LIMIT,
            "offset": offset,
        }
        request = self.spider.get_scrapy_request(params)
        return TextResponse(
            url=request.url,
            request=request,
            body=json.dumps(
                {
                    "code": 0,
                    "data": {
                        "fields": ["ts_code", "trade_date", "price", "percent"],
                        "items": rows,
                    },
                }
            ).encode(),
            encoding="utf-8",
        )

    def start_one_window(self):
        self.settings_store.complete_window.reset_mock()

    def test_full_6000_row_page_requests_next_offset(self):
        self.start_one_window()
        outputs = list(self.spider.parse(self.response([self.row()] * 6000)))

        self.assertEqual(len(outputs), 2)
        next_params = json.loads(outputs[1].body)["params"]
        self.assertEqual(next_params["offset"], 6000)
        self.assertEqual(next_params["limit"], 6000)

    def test_short_page_still_requests_explicit_terminal_empty_page(self):
        self.start_one_window()
        outputs = list(self.spider.parse(self.response([self.row()])))

        self.assertEqual(len(outputs), 2)
        self.assertEqual(json.loads(outputs[1].body)["params"]["offset"], 1)

    def test_repeated_page_raises_instead_of_looping_forever(self):
        self.start_one_window()
        list(self.spider.parse(self.response([self.row()], offset=0)))

        with self.assertRaisesRegex(RuntimeError, "ignoring offset"):
            list(self.spider.parse(self.response([self.row()], offset=1)))

    def test_different_stock_code_is_rejected(self):
        self.start_one_window()
        with self.assertRaisesRegex(RuntimeError, "different stock code"):
            list(self.spider.parse(self.response([self.row(ts_code="000002.SZ")])))

    def test_trade_date_outside_requested_window_is_rejected(self):
        self.start_one_window()
        with self.assertRaisesRegex(RuntimeError, "outside requested window"):
            list(self.spider.parse(self.response([self.row(trade_date="20261104")])))

    def test_entire_empty_window_records_only_its_own_range(self):
        self.start_one_window()
        self.assertEqual(list(self.spider.parse(self.response([]))), [])

        self.settings_store.complete_window.assert_called_once_with(
            self.spider.db_engine,
            "000001.SZ",
            datetime.date(2026, 11, 5),
            datetime.date(2026, 11, 5),
        )

    def test_terminal_page_without_pipeline_success_does_not_complete_window(self):
        self.start_one_window()
        list(self.spider.parse(self.response([self.row()], offset=0)))
        self.assertEqual(list(self.spider.parse(self.response([], offset=1))), [])

        self.settings_store.complete_window.assert_not_called()

    def test_parameter_error_never_records_empty_completion(self):
        response = self.response([])
        response = response.replace(body=json.dumps({"code": -2001, "msg": "查询数据失败，请确认参数"}).encode())
        with self.assertRaisesRegex(RuntimeError, "request failed"):
            list(self.spider.parse(response))
        self.settings_store.complete_window.assert_not_called()

    def test_malformed_success_never_records_empty_completion(self):
        for payload in ({"code": 0}, {"code": 0, "data": None}, {"code": 0, "data": {"items": None}}):
            with self.subTest(payload=payload):
                response = self.response([]).replace(body=json.dumps(payload).encode())
                with self.assertRaisesRegex(RuntimeError, "malformed"):
                    list(self.spider.parse(response))
        self.settings_store.complete_window.assert_not_called()

    def test_completion_waits_for_pipeline_success_even_after_terminal_page(self):
        first_response = self.response([self.row()])
        item = list(self.spider.parse(first_response))[0]
        list(self.spider.parse(self.response([], offset=1)))
        self.settings_store.complete_window.assert_not_called()
        self.spider.on_item_scraped(item, first_response, self.spider)
        self.settings_store.complete_window.assert_called_once()
        self.assertEqual(self.spider.window_progress, {})

    def test_partial_page_restart_replays_date_despite_existing_business_rows(self):
        first_response = self.response([self.row()])
        item = list(self.spider.parse(first_response))[0]
        self.spider.on_item_scraped(item, first_response, self.spider)
        # The second page fails: no completed range exists, even though page one was persisted.
        self.settings_store.complete_window.assert_not_called()
        self.settings_store.get_completed_windows.return_value = []
        self.spider.db_engine.query_df.return_value = pd.DataFrame({"trade_date": [pd.Timestamp("2026-11-05")]})
        dates = self.spider.get_missing_trade_dates(self.spider.db_engine, "000001.SZ")
        sql = self.spider.db_engine.query_df.call_args.args[0]
        self.assertNotIn("max(trade_date)", sql)
        self.assertNotIn("trade_date > ", sql)
        self.assertEqual(len(dates), 1)

    def test_later_empty_window_does_not_skip_earlier_failed_window(self):
        self.settings_store.get_completed_windows.return_value = [
            (datetime.date(2026, 11, 6), datetime.date(2026, 11, 6)),
        ]
        self.spider.db_engine.query_df.return_value = pd.DataFrame({"trade_date": [pd.Timestamp("2026-11-05")]})
        dates = self.spider.get_missing_trade_dates(self.spider.db_engine, "000001.SZ")
        sql = self.spider.db_engine.query_df.call_args.args[0]
        self.assertIn("AND NOT ((trade_date >= '2026-11-06' AND trade_date <= '2026-11-06'))", sql)
        self.assertEqual(dates["trade_date"].dt.strftime("%Y%m%d").tolist(), ["20261105"])

    def test_request_cap_counts_followup_pages(self):
        self.spider.spider_settings.cyq_chips_max_requests_per_run = 2
        self.spider.get_page_request({"ts_code": "000001.SZ"})
        first = list(self.spider.parse(self.response([self.row()])))
        self.assertEqual(len(first), 2)
        second = list(self.spider.parse(self.response([self.row(price=11)], offset=1)))
        self.assertEqual(len(second), 1)
        self.assertEqual(self.spider.request_count, 2)
        self.settings_store.complete_window.assert_not_called()

    def test_null_stock_code_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "different stock code"):
            list(self.spider.parse(self.response([self.row(ts_code=None)])))

    def test_next_window_is_scheduled_only_after_pipeline_and_terminal_page(self):
        self.spider.pending_windows = iter([{
            "ts_code": "000001.SZ", "start_date": "20261106", "end_date": "20261106", "offset": 0,
        }])
        self.spider.crawler = mock.Mock()
        response = self.response([self.row()])
        item = list(self.spider.parse(response))[0]
        self.assertEqual(list(self.spider.parse(self.response([], offset=1))), [])
        self.spider.crawler.engine.crawl.assert_not_called()
        self.spider.on_item_scraped(item, response, self.spider)
        self.spider.crawler.engine.crawl.assert_called_once()
        request = self.spider.crawler.engine.crawl.call_args.args[0]
        self.assertEqual(json.loads(request.body)["params"]["start_date"], "20261106")

    def test_pipeline_success_before_terminal_also_completes_window(self):
        response = self.response([self.row()])
        item = list(self.spider.parse(response))[0]
        self.spider.on_item_scraped(item, response, self.spider)
        self.settings_store.complete_window.assert_not_called()
        list(self.spider.parse(self.response([], offset=1)))
        self.settings_store.complete_window.assert_called_once()

    def test_checkpoint_failure_is_reported_as_spider_error(self):
        self.spider.crawler = mock.Mock()
        response = self.response([self.row()])
        item = list(self.spider.parse(response))[0]
        list(self.spider.parse(self.response([], offset=1)))
        self.settings_store.complete_window.side_effect = RuntimeError("checkpoint write failed")
        self.spider.on_item_scraped(item, response, self.spider)
        call = self.spider.crawler.signals.send_catch_log.call_args.kwargs
        self.assertEqual(call["signal"], signals.spider_error)
        self.assertIn("checkpoint write failed", call["failure"].getErrorMessage())
        self.assertTrue(self.spider.window_progress)


class CyqChipsProgressStoreTest(unittest.TestCase):
    def setUp(self):
        self.store = CyqChipsProgressStore(SimpleNamespace(database=SimpleNamespace(db_name="default")))

    def test_reads_exact_completed_ranges(self):
        conn = mock.Mock()
        conn.query_df.return_value = pd.DataFrame({
            "start_date": [pd.Timestamp("2026-11-05")],
            "end_date": [pd.Timestamp("2026-11-06")],
        })
        self.assertEqual(self.store.get_completed_windows(conn, "000001.SZ"), [
            (datetime.date(2026, 11, 5), datetime.date(2026, 11, 6)),
        ])
        self.assertIn("default.cyq_chips_completed_windows", conn.query_df.call_args.args[0])

    def test_invalid_completed_range_fails_instead_of_skipping_dates(self):
        conn = mock.Mock()
        conn.query_df.return_value = pd.DataFrame({
            "start_date": [pd.Timestamp("2026-11-06")],
            "end_date": [pd.Timestamp("2026-11-05")],
        })
        with self.assertRaisesRegex(ValueError, "Invalid completed"):
            self.store.get_completed_windows(conn, "000001.SZ")

    def test_checkpoint_keeps_stock_and_inclusive_date_bounds(self):
        conn = mock.Mock()
        start, end = datetime.date(2026, 11, 5), datetime.date(2026, 11, 6)
        self.store.complete_window(conn, "000001.SZ", start, end)
        table, schema, data = conn.upsert.call_args.args
        self.assertEqual(table, "cyq_chips_completed_windows")
        self.assertEqual(schema["primary_key"], ["ts_code", "start_date", "end_date"])
        self.assertEqual(data["ts_code"].iloc[0], "000001.SZ")
        self.assertEqual(data["start_date"].iloc[0], start)
        self.assertEqual(data["end_date"].iloc[0], end)


if __name__ == "__main__":
    unittest.main()
