import datetime
import json
import unittest
from types import SimpleNamespace
from unittest import mock

import pandas as pd

from tushare_integration.settings import TushareIntegrationSettings
from tushare_integration.db_engine import ClickhouseEngine
from tushare_integration.dwd import DWDManager
from tushare_integration.dws import (
    DWS_CLICKHOUSE_SEND_RECEIVE_TIMEOUT,
    DWSManager,
    FINANCIAL_FEATURE_COLUMNS,
    STOCK_FINANCIAL_INDICATOR_QUARTER_FIELDS,
    STOCK_FINANCIAL_INDICATOR_QUARTER_SOURCE,
)
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
        self.assertIn("AND event_date >= toDate32('2010-01-01')", sql)

    def test_dws_stock_factor_wide_includes_pit_adj_factor(self):
        manager = object.__new__(DWSManager)
        manager.settings = self._clickhouse_settings()

        sql = manager.render_sync_sql("dws_stock_factor_wide")
        spec = manager.load_spec("dws_stock_factor_wide")
        column_names = [column["name"] for column in spec["schema"]["columns"]]

        self.assertIn("adj_factor", column_names)
        self.assertIn("dwd_stock_adj_factor", manager.get_required_source_tables(spec))
        self.assertIn("FROM default.dwd_stock_adj_factor", sql)
        self.assertIn("LEFT JOIN adj_factor", sql)
        self.assertIn("adj_factor.event_date = price.event_date", sql)
        self.assertIn("coalesce(adj_factor.available_trade_date, price.available_trade_date)", sql)
        self.assertIn("adj_factor.adj_factor AS adj_factor", sql)
        self.assertIn("|', coalesce(adj_factor.source_batch_id, '')", sql)
        self.assertIn("|', coalesce(adj_factor.source_record_hash, '')", sql)
        self.assertNotIn("ASOF LEFT JOIN adj_factor", sql)

    def test_financial_source_and_dwd_schemas_include_requested_factor_fields(self):
        manager = object.__new__(DWDManager)
        requested_fields_by_table = {
            "dwd_stock_income": {
                "total_revenue",
                "revenue",
                "n_income",
                "n_income_attr_p",
                "compr_inc_attr_p",
                "compr_inc_attr_m_s",
                "oper_cost",
                "total_profit",
                "ebit",
                "ebitda",
                "admin_exp",
                "sell_exp",
                "fin_exp",
                "income_tax",
                "total_opcost",
            },
            "dwd_stock_balance_sheet": {
                "total_assets",
                "total_liab",
                "total_cur_liab",
                "total_cur_assets",
                "money_cap",
                "total_hldr_eqy_exc_min_int",
            },
            "dwd_stock_cashflow": {
                "c_inf_fr_operate_a",
                "st_cash_out_act",
                "stot_out_inv_act",
                "stot_inflows_inv_act",
                "stot_cash_in_fnc_act",
                "stot_cashout_fnc_act",
            },
            "dwd_stock_financial_indicator": {
                "assets_turn",
                "inv_turn",
                "ar_turn",
            },
        }

        for table_name, requested_fields in requested_fields_by_table.items():
            spec = manager.load_spec(table_name)
            dwd_schema = manager.build_schema(spec)
            dwd_columns = {column["name"] for column in dwd_schema["columns"]}

            self.assertTrue(
                requested_fields.issubset(dwd_columns),
                f"{table_name} missing {sorted(requested_fields - dwd_columns)}",
            )

    def test_dws_stock_factor_wide_includes_financial_statement_sources(self):
        manager = object.__new__(DWSManager)
        manager.settings = self._clickhouse_settings()

        sql = manager.render_sync_sql("dws_stock_factor_wide")
        spec = manager.load_spec("dws_stock_factor_wide")
        column_names = {column["name"] for column in spec["schema"]["columns"]}
        requested_columns = {
            "assets_turn",
            "inv_turn",
            "ar_turn",
            "total_revenue",
            "revenue",
            "n_income",
            "n_income_attr_p",
            "compr_inc_attr_p",
            "compr_inc_attr_m_s",
            "oper_cost",
            "total_profit",
            "ebit",
            "ebitda",
            "admin_exp",
            "sell_exp",
            "fin_exp",
            "income_tax",
            "total_opcost",
            "total_assets",
            "total_liab",
            "total_cur_liab",
            "total_cur_assets",
            "money_cap",
            "total_hldr_eqy_exc_min_int",
            "c_inf_fr_operate_a",
            "st_cash_out_act",
            "stot_out_inv_act",
            "stot_inflows_inv_act",
            "stot_cash_in_fnc_act",
            "stot_cashout_fnc_act",
        }

        self.assertTrue(requested_columns.issubset(column_names))
        self.assertIn("dwd_stock_income", manager.get_required_source_tables(spec))
        self.assertIn("dwd_stock_balance_sheet", manager.get_required_source_tables(spec))
        self.assertIn("dwd_stock_cashflow", manager.get_required_source_tables(spec))
        self.assertIn("FROM default.dwd_stock_income", sql)
        self.assertIn("FROM default.dwd_stock_balance_sheet", sql)
        self.assertIn("FROM default.dwd_stock_cashflow", sql)
        self.assertIn("ASOF LEFT JOIN income", sql)
        self.assertIn("ASOF LEFT JOIN balance_sheet", sql)
        self.assertIn("ASOF LEFT JOIN cashflow", sql)
        self.assertIn("price.available_trade_date >= income.available_trade_date", sql)
        self.assertIn("price.available_trade_date >= balance_sheet.available_trade_date", sql)
        self.assertIn("price.available_trade_date >= cashflow.available_trade_date", sql)
        self.assertIn("income.total_revenue AS total_revenue", sql)
        self.assertIn("balance_sheet.total_assets AS total_assets", sql)
        self.assertIn("cashflow.c_inf_fr_operate_a AS c_inf_fr_operate_a", sql)
        self.assertIn("|', coalesce(income.source_batch_id, '')", sql)
        self.assertIn("|', coalesce(balance_sheet.source_record_hash, '')", sql)
        self.assertIn("|', coalesce(cashflow.source_record_hash, '')", sql)

    def test_dws_stock_factor_wide_includes_single_quarter_financial_features(self):
        manager = object.__new__(DWSManager)
        manager.settings = self._clickhouse_settings()

        sql = manager.render_sync_sql("dws_stock_factor_wide")
        spec = manager.load_spec("dws_stock_factor_wide")
        column_names = {column["name"] for column in spec["schema"]["columns"]}
        feature_columns = {column for _, _, _, column in FINANCIAL_FEATURE_COLUMNS}
        requested_columns = {
            "revenue_ttm_0",
            "revenue_ttm_4",
            "n_income_lyr_1",
            "money_cap_mrq_0",
            "total_assets_mrq_4",
            "ebitda_ttm",
            "ebitda_lyr",
        }

        self.assertEqual(len(feature_columns), 106)
        self.assertTrue(feature_columns.issubset(column_names))
        self.assertTrue(requested_columns.issubset(column_names))
        self.assertIn("income_quarter_features", sql)
        self.assertIn("cashflow_quarter_features", sql)
        self.assertIn("balance_sheet_quarter_features", sql)
        self.assertIn("ASOF LEFT JOIN income_quarter_features", sql)
        self.assertIn("ASOF LEFT JOIN balance_sheet_annual_features", sql)
        self.assertIn("income_quarter_features.`revenue_ttm_0` AS `revenue_ttm_0`", sql)
        self.assertIn("income_annual_features.`n_income_lyr_1` AS `n_income_lyr_1`", sql)
        self.assertIn("balance_sheet_quarter_features.`money_cap_mrq_0` AS `money_cap_mrq_0`", sql)
        self.assertIn(
            "sumIf(`revenue`, report_offset >= 0 AND report_offset < 4)",
            sql,
        )
        self.assertIn(
            "avgIf(`total_assets`, report_offset >= 0 AND report_offset < 4)",
            sql,
        )
        self.assertIn("income_quarter_features.`ebitda_ttm` AS `ebitda_ttm`", sql)
        self.assertIn("income_annual_features.`ebitda_lyr` AS `ebitda_lyr`", sql)
        self.assertIn("|', coalesce(income_quarter_features.source_batch_id, '')", sql)
        self.assertIn("|', coalesce(cashflow_annual_features.source_record_hash, '')", sql)

    def test_dws_stock_financial_indicator_quarter_table_derives_requested_fields(self):
        manager = object.__new__(DWSManager)
        manager.settings = self._clickhouse_settings()

        sql = manager.render_sync_sql("dws_stock_financial_indicator_quarter")
        spec = manager.load_spec("dws_stock_financial_indicator_quarter")
        column_names = {column["name"] for column in spec["schema"]["columns"]}
        comments = {column["name"]: column["comment"] for column in spec["schema"]["columns"]}

        self.assertTrue(set(STOCK_FINANCIAL_INDICATOR_QUARTER_FIELDS).issubset(column_names))
        self.assertNotIn("profit_dedt", column_names)
        self.assertEqual(manager.get_required_source_tables(spec), [STOCK_FINANCIAL_INDICATOR_QUARTER_SOURCE])
        self.assertIn("FROM default.dwd_stock_financial_indicator src", sql)
        self.assertIn("toMonth(src.event_date) IN (3, 6, 9, 12)", sql)
        self.assertIn("AND toQuarter(curr.event_date) != 1", sql)
        self.assertIn("prev.event_date = addMonths(curr.event_date, -3)", sql)
        self.assertIn("`extra_item` - `prev_extra_item`", sql)
        self.assertIn("`fcfe` - `prev_fcfe`", sql)
        self.assertIn("`fcff` - `prev_fcff`", sql)
        self.assertIn("toQuarter(event_date) = 1", sql)
        self.assertIn("curr.`ar_turn` AS `ar_turn`", sql)
        self.assertIn("当期累计值减上一季度累计值", comments["extra_item"])
        self.assertIn("存量指标不做差分", comments["interestdebt"])
        self.assertIn("不可由累计值差分单季化", comments["ar_turn"])

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

    def test_parse_response_treats_generic_tushare_query_failure_as_empty_item(self):
        spider = CyqChipsSpider()
        response = DummyResponse(
            {
                "code": 50101,
                "msg": "查询数据失败，请确认参数！可以反馈管理员协助您排查问题",
                "data": None,
            },
            params={"ts_code": "832317.BJ", "trade_date": "20180102"},
        )

        item = spider.parse_response(response)

        self.assertTrue(item["data"].empty)
        self.assertEqual(item["data"].columns.tolist(), ["ts_code", "trade_date", "price", "percent"])

    def test_parse_response_still_raises_for_parameter_validation_errors(self):
        spider = CyqChipsSpider()
        response = DummyResponse(
            {
                "code": 50101,
                "msg": "参数校验失败, ts_code,trade_date至少输入一个参数",
                "data": None,
            }
        )

        with self.assertRaisesRegex(RuntimeError, "参数校验失败"):
            spider.parse_response(response)

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

    def test_cyq_chips_bounds_missing_dates_to_listing_window(self):
        spider = CyqChipsSpider()
        spider.spider_settings = DummySpiderSettings(database=SimpleNamespace(db_name="default"))
        fake_db = DummyDB(
            [
                pd.DataFrame({"latest_trade_date": [pd.NaT]}),
                pd.DataFrame({"trade_date": pd.to_datetime(["2021-12-15"])}),
            ]
        )

        trade_dates = spider.get_missing_trade_dates(
            fake_db,
            "832317.BJ",
            list_date=pd.Timestamp("2020-07-27"),
            delist_date=pd.Timestamp("2022-04-26"),
        )

        self.assertEqual(trade_dates["trade_date"].dt.strftime("%Y%m%d").tolist(), ["20211215"])
        self.assertIn("trade_date >= '2020-07-27'", fake_db.queries[-1])
        self.assertIn("trade_date <= '2022-04-26'", fake_db.queries[-1])

    def test_cyq_chips_start_requests_uses_current_stock_code(self):
        spider = CyqChipsSpider()
        spider.spider_settings = DummySpiderSettings(database=SimpleNamespace(db_name="default"))
        fake_db = DummyDB(
            [
                pd.DataFrame(
                    {
                        "ts_code": ["000001.SZ"],
                        "list_date": [pd.Timestamp("1991-04-03")],
                        "delist_date": [pd.NaT],
                    }
                ),
                pd.DataFrame({"latest_trade_date": [pd.Timestamp("2026-05-08")]}),
                pd.DataFrame({"trade_date": pd.to_datetime(["2026-05-11"])}),
            ]
        )

        with mock.patch.object(spider, "get_db_engine", return_value=fake_db):
            requests = list(spider.start_requests())

        request_params = [json.loads(request.body.decode("utf-8"))["params"] for request in requests]
        self.assertEqual(
            request_params,
            [{"ts_code": "000001.SZ", "start_date": "20260511", "end_date": "20260511"}],
        )

    def test_cyq_chips_chunks_trade_dates_into_range_requests(self):
        spider = CyqChipsSpider()
        spider.spider_settings = DummySpiderSettings(
            database=SimpleNamespace(db_name="default"),
            cyq_chips_request_chunk_trade_days=2,
        )
        fake_db = DummyDB(
            [
                pd.DataFrame(
                    {
                        "ts_code": ["000001.SZ"],
                        "list_date": [pd.Timestamp("1991-04-03")],
                        "delist_date": [pd.NaT],
                    }
                ),
                pd.DataFrame({"latest_trade_date": [pd.Timestamp("2026-05-08")]}),
                pd.DataFrame(
                    {"trade_date": pd.to_datetime(["2026-05-11", "2026-05-12", "2026-05-13"])}
                ),
            ]
        )

        with mock.patch.object(spider, "get_db_engine", return_value=fake_db):
            requests = list(spider.start_requests())

        request_params = [json.loads(request.body.decode("utf-8"))["params"] for request in requests]
        self.assertEqual(
            request_params,
            [
                {"ts_code": "000001.SZ", "start_date": "20260511", "end_date": "20260512"},
                {"ts_code": "000001.SZ", "start_date": "20260513", "end_date": "20260513"},
            ],
        )

    def test_cyq_chips_respects_per_run_request_cap(self):
        spider = CyqChipsSpider()
        spider.spider_settings = DummySpiderSettings(
            database=SimpleNamespace(db_name="default"),
            cyq_chips_request_chunk_trade_days=1,
            cyq_chips_max_requests_per_run=1,
        )
        fake_db = DummyDB(
            [
                pd.DataFrame(
                    {
                        "ts_code": ["000001.SZ"],
                        "list_date": [pd.Timestamp("1991-04-03")],
                        "delist_date": [pd.NaT],
                    }
                ),
                pd.DataFrame({"latest_trade_date": [pd.Timestamp("2026-05-08")]}),
                pd.DataFrame({"trade_date": pd.to_datetime(["2026-05-11", "2026-05-12"])}),
            ]
        )

        with mock.patch.object(spider, "get_db_engine", return_value=fake_db):
            requests = list(spider.start_requests())

        request_params = [json.loads(request.body.decode("utf-8"))["params"] for request in requests]
        self.assertEqual(
            request_params,
            [{"ts_code": "000001.SZ", "start_date": "20260511", "end_date": "20260511"}],
        )

    def test_cyq_chips_primary_key_preserves_price_buckets(self):
        spider = CyqChipsSpider()

        self.assertEqual(spider.schema["primary_key"], ["ts_code", "trade_date", "price"])

    def test_index_weight_start_requests_uses_documented_monthly_index_code_params(self):
        spider = IndexWeightSpider()
        spider.spider_settings = DummySpiderSettings(database=SimpleNamespace(db_name="default"))
        fake_db = DummyDB(
            [
                pd.DataFrame({"row_count": [0], "latest_trade_date": [pd.NaT]}),
                pd.DataFrame(
                    {
                        "ts_code": ["399300.SZ"],
                        "base_date": [pd.to_datetime("2004-12-31")],
                        "list_date": [pd.to_datetime("2015-04-16")],
                        "exp_date": [pd.to_datetime("1970-01-01")],
                    }
                ),
            ]
        )

        with mock.patch.object(spider, "get_db_engine", return_value=fake_db):
            with mock.patch.object(spider, "get_request_end_date", return_value=datetime.date(2015, 5, 31)):
                requests = list(spider.start_requests())

        self.assertEqual(len(requests), 2)
        request_params = [json.loads(request.body.decode("utf-8"))["params"] for request in requests]
        self.assertEqual(
            request_params,
            [
                {"index_code": "399300.SZ", "start_date": "20150401", "end_date": "20150430"},
                {"index_code": "399300.SZ", "start_date": "20150501", "end_date": "20150531"},
            ],
        )
        self.assertNotIn("offset", request_params[0])
        self.assertNotIn("limit", request_params[0])

    def test_index_weight_parse_returns_current_response_data_without_pagination(self):
        spider = IndexWeightSpider()
        response = DummyResponse(
            {
                "code": 0,
                "msg": "",
                "data": {
                    "fields": ["index_code", "con_code", "trade_date", "weight"],
                    "items": [
                        ["399300.SZ", "000001.SZ", "20200101", 1.0],
                        ["399300.SZ", "000002.SZ", "20200101", 2.0],
                    ],
                },
            }
        )

        item = spider.parse(response)

        self.assertEqual(
            item["data"].to_dict("records"),
            [
                {"index_code": "399300.SZ", "con_code": "000001.SZ", "trade_date": "20200101", "weight": 1.0},
                {"index_code": "399300.SZ", "con_code": "000002.SZ", "trade_date": "20200101", "weight": 2.0},
            ],
        )


if __name__ == "__main__":
    unittest.main()
