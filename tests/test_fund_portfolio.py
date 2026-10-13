import datetime
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from scrapy.settings import Settings
from scrapy.http import TextResponse

from tushare_integration.dwd import DWDManager
from tushare_integration.pipelines import (
    TushareIntegrationDataPipeline,
    TushareIntegrationFillNAPipeline,
    TransformDTypePipeline,
)
from tushare_integration.quality import QualityManager
from tushare_integration.settings import TushareIntegrationSettings
from tushare_integration.spiders.fund.portfolio import FundPortfolioSpider


class FundPortfolioTest(unittest.TestCase):
    def setUp(self):
        self.spider = FundPortfolioSpider()
        self.spider.spider_settings = SimpleNamespace(
            tushare_url="https://api.tushare.pro",
            tushare_token="token",
            default_min_cal_date="2024-01-01",
            tushare_point=5000,
            tushare_rate_limit_ratio=0.9,
            get_download_delay=lambda: 60 / 450,
        )
        self.fields = self.spider.load_fields().split(",")

    def row(self, fund="001753.OF", ann_date="20240823", symbol="603019.SH", mkv=3130994.46):
        return [fund, ann_date, "20240630", symbol, mkv, 68258.0, 4.37, None]

    def response(self, rows, offset=0):
        request = self.spider.get_scrapy_request({"period": "20240630", "offset": offset, "limit": 2})
        return TextResponse(
            url=request.url,
            request=request,
            body=json.dumps({"code": 0, "data": {"fields": self.fields, "items": rows}}).encode(),
            encoding="utf-8",
        )

    def test_collects_completed_quarters_including_weekend_report_dates(self):
        with mock.patch.object(self.spider, "get_request_end_date", return_value=datetime.date(2024, 7, 2)):
            requests = list(self.spider.start_requests())
        self.assertEqual(
            [json.loads(request.body)["params"] for request in requests],
            [
                {"period": "20240331", "offset": 0, "limit": 8000},
                {"period": "20240630", "offset": 0, "limit": 8000},
            ],
        )
        self.spider.spider_settings.default_min_cal_date = "2024-04-01"
        with mock.patch.object(self.spider, "get_request_end_date", return_value=datetime.date(2024, 7, 2)):
            self.assertEqual(list(self.spider.get_all_period()), ["20240630"])

    def test_pages_are_emitted_immediately_and_short_pages_continue_until_empty(self):
        outputs = self.spider.parse(self.response([self.row()]))
        # Receiving the item must not fetch the next page or collect the quarter.
        with mock.patch.object(self.spider, "request_with_requests") as blocking_fetch:
            item = next(outputs)
            self.assertEqual(item["data"]["mkv"].tolist(), [3130994.46])
            request = next(outputs)
        blocking_fetch.assert_not_called()
        self.assertEqual(json.loads(request.body)["params"], {"period": "20240630", "offset": 1, "limit": 2})
        later_disclosure = self.row(ann_date="20240901", mkv=3131994.46)
        other_fund = self.row(fund="000001.OF")
        item, request = list(self.spider.parse(self.response([later_disclosure, other_fund], offset=1)))
        self.assertEqual(item["data"]["ann_date"].tolist(), ["20240901", "20240823"])
        self.assertEqual(item["data"]["ts_code"].tolist(), ["001753.OF", "000001.OF"])
        self.assertEqual(json.loads(request.body)["params"], {"period": "20240630", "offset": 3, "limit": 2})
        self.assertEqual(list(self.spider.parse(self.response([], offset=3))), [])
        self.assertNotIn("20240630", self.spider.period_progress)

    def test_repeated_source_page_continues_to_later_rows_even_when_order_changes(self):
        rows = [self.row(), self.row(symbol="600845.SH")]
        list(self.spider.parse(self.response(rows)))
        with self.assertLogs(self.spider.name, level="WARNING") as logs:
            item, request = list(self.spider.parse(self.response(rows[::-1], offset=2)))
        self.assertEqual(len(item["data"]), 2)
        self.assertIn("Repeated fund_portfolio source page", logs.output[0])
        self.assertEqual(json.loads(request.body)["params"]["offset"], 4)
        item, request = list(self.spider.parse(self.response([self.row(symbol="600000.SH")], offset=4)))
        self.assertEqual(item["data"]["symbol"].tolist(), ["600000.SH"])
        self.assertEqual(list(self.spider.parse(self.response([], offset=5))), [])

    def test_endless_nonempty_pages_fail_at_safety_limit_without_claiming_completion(self):
        self.spider.MAX_PAGES_PER_PERIOD = 2
        list(self.spider.parse(self.response([self.row()], offset=0)))
        list(self.spider.parse(self.response([self.row()], offset=1)))
        with self.assertRaisesRegex(RuntimeError, "page safety limit.*period is incomplete"):
            list(self.spider.parse(self.response([self.row()], offset=2)))

    def test_terminal_empty_page_can_complete_at_safety_limit(self):
        self.spider.MAX_PAGES_PER_PERIOD = 1
        list(self.spider.parse(self.response([self.row()])))
        self.assertEqual(list(self.spider.parse(self.response([], offset=1))), [])

    def test_duplicate_and_conflicting_payloads_are_logged_and_preserved(self):
        original = self.row()
        correction = self.row(mkv=3131994.46)
        with self.assertLogs(self.spider.name, level="WARNING") as logs:
            item, request = list(self.spider.parse(self.response([original, original, correction])))
        self.assertEqual(item["data"]["mkv"].tolist(), [3130994.46, 3130994.46, 3131994.46])
        self.assertEqual(json.loads(request.body)["params"]["offset"], 3)
        self.assertTrue(any("duplicate_rows=1" in message for message in logs.output))
        self.assertTrue(any("Conflicting fund_portfolio source payloads" in message for message in logs.output))

    def test_later_page_error_fails_without_discarding_previously_emitted_page(self):
        item, request = list(self.spider.parse(self.response([self.row()])))
        response = TextResponse(
            url=request.url, request=request,
            body=json.dumps({"code": 40203, "msg": "rate limit"}).encode(), encoding="utf-8",
        )
        with self.assertRaisesRegex(RuntimeError, "rate limit"):
            list(self.spider.parse(response))
        self.assertEqual(len(item["data"]), 1)

    def test_unexpected_report_period_fails_before_emitting_rows(self):
        row = self.row()
        row[2] = "20240331"
        with self.assertRaisesRegex(RuntimeError, "different report period"):
            list(self.spider.parse(self.response([row])))

    def test_progress_keeps_hashes_and_counts_without_accumulating_dataframes(self):
        for offset in range(20):
            list(self.spider.parse(self.response([self.row(symbol=f"{offset:06d}.SZ")], offset=offset)))
        progress = self.spider.period_progress["20240630"]
        self.assertEqual(progress["rows"], 20)
        self.assertEqual(len(progress["page_hashes"]), 20)
        self.assertEqual(set(progress), {"rows", "pages", "page_hashes"})

    def test_storage_receives_each_page_before_followup_request_is_emitted(self):
        self.spider.settings = Settings({"BATCH_ID": "stream-check"})
        fill = TushareIntegrationFillNAPipeline(settings=self.settings())
        transform = TransformDTypePipeline(settings=self.settings())
        fill.schema = transform.schema = self.spider.schema
        db = mock.Mock()
        with mock.patch("tushare_integration.pipelines.DatabaseEngineFactory.create", return_value=db):
            storage = TushareIntegrationDataPipeline(settings=self.settings())
            storage.open_spider(self.spider)
        for offset in [0, 1]:
            outputs = self.spider.parse(self.response([self.row(symbol=f"{offset:06d}.SZ")], offset=offset))
            item = next(outputs)
            storage.process_item(transform.process_item(fill.process_item(item, self.spider), self.spider), self.spider)
            self.assertEqual(db.insert.call_count, offset + 1)
            self.assertEqual(db.upsert.call_count, offset + 1)
            self.assertEqual(db.insert.call_args.args[0], "fund_portfolio_raw")
            self.assertEqual(db.upsert.call_args.args[0], "fund_portfolio")
            self.assertEqual(len(db.insert.call_args.kwargs["data"]), 1)
            next(outputs)

    def test_empty_quarter_does_not_request_more_pages(self):
        with mock.patch.object(self.spider, "request_with_requests") as fetch:
            self.assertEqual(list(self.spider.parse(self.response([]))), [])
        fetch.assert_not_called()

    def test_rate_limit_uses_endpoint_allowance_and_slower_user_settings(self):
        self.assertAlmostEqual(self.spider.get_portfolio_download_delay(), 60 / 180)
        self.spider.spider_settings.tushare_point = 8000
        self.assertAlmostEqual(self.spider.get_portfolio_download_delay(), 60 / 450)
        self.spider.spider_settings.get_download_delay = lambda: 1.0
        self.assertEqual(self.spider.get_portfolio_download_delay(), 1.0)

    def test_pipeline_preserves_null_measures_source_units_and_float_precision(self):
        item = self.spider.parse_response(self.response([self.row(), self.row(mkv=None)]))
        fill = TushareIntegrationFillNAPipeline(settings=None)
        transform = TransformDTypePipeline(settings=None)
        fill.schema = self.spider.schema
        transform.schema = self.spider.schema
        item = transform.process_item(fill.process_item(item, self.spider), self.spider)
        for data in (item["raw_data"], item["latest_data"]):
            self.assertEqual(data["mkv"].iloc[0], 3130994.46)
            self.assertEqual(data["amount"].iloc[0], 68258.0)
            self.assertEqual(data["stk_mkv_ratio"].iloc[0], 4.37)
            self.assertIsNone(data["mkv"].iloc[1])
            self.assertIsNone(data["stk_float_ratio"].iloc[0])
            self.assertEqual(data["end_date"].iloc[0], datetime.date(2024, 6, 30))

    def test_nonnullable_pipeline_columns_still_receive_defaults(self):
        item = self.spider.parse_response(self.response([self.row(fund=None, ann_date=None)]))
        fill = TushareIntegrationFillNAPipeline(settings=None)
        transform = TransformDTypePipeline(settings=None)
        fill.schema = self.spider.schema
        transform.schema = self.spider.schema
        item = transform.process_item(fill.process_item(item, self.spider), self.spider)
        self.assertEqual(item["latest_data"]["ts_code"].iloc[0], "")
        self.assertEqual(item["latest_data"]["ann_date"].iloc[0], datetime.date(1970, 1, 1))
        self.assertIsNone(item["raw_data"]["ts_code"].iloc[0])
        self.assertIsNone(item["raw_data"]["ann_date"].iloc[0])

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

    def test_dwd_preserves_fund_stock_and_disclosure_identity_and_raw_nulls(self):
        manager = DWDManager.__new__(DWDManager)
        manager.settings = self.settings()
        spec = manager.load_spec("dwd_fund_portfolio")
        columns = {column["name"]: column for column in manager.build_schema(spec)["columns"]}
        sql = manager.render_sync_sql("dwd_fund_portfolio")
        self.assertEqual(manager.get_required_source_tables(spec), ["fund_portfolio_raw", "trade_cal"])
        for key in ("ts_code", "ann_date", "end_date", "symbol"):
            self.assertFalse(columns[key].get("nullable", False))
        for measure in ("mkv", "amount", "stk_mkv_ratio", "stk_float_ratio"):
            self.assertTrue(columns[measure]["nullable"])
            self.assertNotIn("default", columns[measure])
        self.assertIn("FROM default.fund_portfolio_raw src", sql)
        self.assertIn("PARTITION BY `ts_code`, `ann_date`, `end_date`, `symbol`", sql)
        self.assertIn("concat('stock:', src.symbol) AS `instrument_id`", sql)
        self.assertIn("concat('fund:', src.ts_code) AS `fund_id`", sql)
        self.assertIn("src.end_date AS `event_date`", sql)
        self.assertIn("src.ann_date AS _calendar_lookup_date", sql)
        self.assertIn("throwIf(isNull(calendar_map.next_trade_date)", sql)
        self.assertIn("Missing SSE next trading day for fund announcement", sql)
        self.assertNotIn("coalesce(", sql)

    def test_quality_checks_disclosure_dates_values_lineage_and_full_business_key(self):
        manager = QualityManager(settings=self.settings(), db_engine=mock.Mock())
        rules = {
            rule.rule_id: rule
            for rule in manager.build_rules("dwd", "dwd_fund_portfolio", "dwd_fund_portfolio_tmp")
        }
        for rule_id in (
            "dwd_pit_dates_not_null", "dwd_lineage_not_empty", "fund_portfolio_report_dates",
            "fund_portfolio_strict_next_trade_visibility", "fund_portfolio_nonnegative_finite_measures",
        ):
            self.assertEqual(rules[rule_id].severity, "BLOCKER")
        self.assertIn("GROUP BY ts_code, ann_date, end_date, symbol", rules["dwd_single_open_version"].issue_count_sql)
        self.assertIn("end_date > ann_date", rules["fund_portfolio_report_dates"].issue_count_sql)
        self.assertIn(
            "available_trade_date <= ann_date", rules["fund_portfolio_strict_next_trade_visibility"].issue_count_sql
        )
        self.assertIn("NOT isFinite(mkv)", rules["fund_portfolio_nonnegative_finite_measures"].issue_count_sql)


if __name__ == "__main__":
    unittest.main()
