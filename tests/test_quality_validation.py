import json
import unittest
from unittest import mock

import pandas as pd

from tushare_integration.dwd import DWDManager
from tushare_integration.quality import (
    DqcManager,
    QualityManager,
    QualityValidationError,
    ValidationResult,
    _FactorExpressionReferenceEvaluator,
)
from tushare_integration.settings import TushareIntegrationSettings


class DummyDB:
    def __init__(self):
        self.inserts = []
        self.created_tables = []

    def create_table(self, table_name, schema):
        self.created_tables.append(table_name)

    def insert(self, table_name, schema, data):
        self.inserts.append((table_name, data.copy()))

    def query_df(self, sql):
        return pd.DataFrame({"issue_count": [0]})

    def query(self, sql):
        return None


class DqcSqlDB(DummyDB):
    def __init__(self):
        super().__init__()
        self.queries = []

    def query_df(self, sql):
        self.queries.append(sql)
        return pd.DataFrame(
            {
                "issue_count": [0],
                "checked_count": [100],
                "observed_value": [100.0],
            }
        )


class DqcMetricDB(DummyDB):
    def __init__(self):
        super().__init__()
        self.queries = []

    def query_df(self, sql):
        self.queries.append(sql)
        if "uniqExact(instrument_id)" in sql:
            return pd.DataFrame(
                {
                    "trade_date": [pd.Timestamp("2026-05-25").date()],
                    "row_count": [100],
                    "instrument_count": [100],
                    "max_available_trade_date_day": [20000.0],
                    "max_build_time_ts": [1770000000.0],
                }
            )
        return pd.DataFrame()


class DqcFactorCrossCheckDB(DummyDB):
    def __init__(self, actual_value=0.1):
        super().__init__()
        self.queries = []
        self.actual_value = actual_value

    def query_df(self, sql):
        self.queries.append(sql)
        if "actual_value" in sql:
            return pd.DataFrame({"actual_value": [self.actual_value]})
        if "dws_stock_factor_wide_matrix" in sql and "arrayElement" in sql:
            return pd.DataFrame(
                {
                    "instrument_id": ["stock:300119.SZ"],
                    "trade_date": [pd.Timestamp("2026-05-25").date()],
                    "source_code": ["300119.SZ"],
                    "factor_id": ["a158_vsumn30"],
                }
            )
        if "dws_stock_factor_wide" in sql:
            return pd.DataFrame(
                {
                    "trade_date": pd.to_datetime(
                        ["2026-05-20", "2026-05-21", "2026-05-22", "2026-05-25"]
                    ).date,
                    "volume": [10.0, 8.0, 11.0, 7.0],
                }
            )
        return pd.DataFrame()


class QualityValidationTest(unittest.TestCase):
    def _settings(self, quality=None):
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
            quality=quality or {"mode": "warn_only", "create_result_tables": False},
        )

    def test_skip_mode_records_bypass_without_running_rules(self):
        db = DummyDB()
        manager = QualityManager(settings=self._settings(), db_engine=db)

        with mock.patch.object(manager, "run_rules") as run_rules:
            run = manager.validate_publish(
                layer="dwd",
                table_name="dwd_stock_eod_price",
                target_table_name="dwd_stock_eod_price_tmp",
                stage="pre_dwd_publish",
                skip_validation=True,
            )

        run_rules.assert_not_called()
        self.assertEqual(run.mode, "skip")
        self.assertEqual(run.status, "SKIPPED")
        self.assertEqual(db.inserts[0][0], "dq_validation_run")

    def test_warn_only_records_failures_but_does_not_raise(self):
        db = DummyDB()
        manager = QualityManager(settings=self._settings(), db_engine=db)
        failure = ValidationResult(
            rule_id="market_ohlc_consistency",
            severity="BLOCKER",
            status="FAIL",
            issue_count=2,
            description="bad ohlc",
        )

        with mock.patch.object(manager, "run_rules", return_value=[failure]):
            run = manager.validate_publish(
                layer="dwd",
                table_name="dwd_stock_eod_price",
                target_table_name="dwd_stock_eod_price_tmp",
                stage="pre_dwd_publish",
                mode="warn_only",
            )

        self.assertEqual(run.status, "FAIL")
        self.assertFalse(run.should_block)
        self.assertEqual(db.inserts[1][0], "dq_validation_result")

    def test_strict_blocks_on_blocker_failure(self):
        db = DummyDB()
        manager = QualityManager(settings=self._settings(), db_engine=db)
        failure = ValidationResult(
            rule_id="dwd_single_open_version",
            severity="BLOCKER",
            status="FAIL",
            issue_count=1,
            description="duplicate open version",
        )

        with mock.patch.object(manager, "run_rules", return_value=[failure]):
            with self.assertRaises(QualityValidationError):
                manager.validate_publish(
                    layer="dwd",
                    table_name="dwd_stock_eod_price",
                    target_table_name="dwd_stock_eod_price_tmp",
                    stage="pre_dwd_publish",
                    mode="strict",
                )

    def test_table_mode_overrides_global_mode(self):
        manager = QualityManager(
            settings=self._settings(
                {
                    "mode": "strict",
                    "table_modes": {"dwd_stock_financial_indicator": "skip"},
                    "create_result_tables": False,
                }
            ),
            db_engine=DummyDB(),
        )

        self.assertEqual(manager.resolve_mode("dwd", "dwd_stock_financial_indicator"), "skip")
        self.assertEqual(manager.resolve_mode("dwd", "dwd_stock_eod_price"), "strict")

    def test_dwd_market_rules_include_business_checks(self):
        manager = QualityManager(settings=self._settings(), db_engine=DummyDB())

        rule_ids = {
            rule.rule_id
            for rule in manager.list_rules(
                layer="dwd",
                table_name="dwd_stock_eod_price",
                target_table_name="dwd_stock_eod_price_tmp",
            )
        }

        self.assertIn("market_ohlc_consistency", rule_ids)
        self.assertIn("market_positive_prices_when_traded", rule_ids)
        self.assertIn("dwd_single_open_version", rule_ids)

    def test_checked_count_sql_uses_trade_date_scope(self):
        manager = QualityManager(settings=self._settings(), db_engine=DummyDB())

        dwd_sql = manager.checked_count_sql(
            layer="dwd",
            table_name="dwd_stock_eod_price",
            target_table_name="dwd_stock_eod_price_tmp",
        )
        dws_sql = manager.checked_count_sql(
            layer="dws",
            table_name="dws_stock_factor_wide",
            target_table_name="dws_stock_factor_wide_tmp",
        )
        ods_sql = manager.checked_count_sql(layer="ods", table_name="daily", target_table_name="daily")

        self.assertIn("event_date >= toDate32('2010-01-01')", dwd_sql)
        self.assertIn("trade_date >= toDate32('2010-01-01')", dws_sql)
        self.assertNotIn("2010-01-01", ods_sql)

    def test_market_ohlc_consistency_only_checks_active_price_rows(self):
        manager = QualityManager(settings=self._settings(), db_engine=DummyDB())

        rules = {
            rule.rule_id: rule
            for rule in manager.list_rules(
                layer="dwd",
                table_name="dwd_future_eod_price",
                target_table_name="dwd_future_eod_price_tmp",
            )
        }

        self.assertIn("vol > 0 OR open > 0 OR high > 0 OR low > 0", rules["market_ohlc_consistency"].issue_count_sql)
        self.assertIn("high < low OR high < open OR high < close", rules["market_ohlc_consistency"].issue_count_sql)

    def test_dwd_trade_rules_are_limited_to_rows_since_2010(self):
        manager = QualityManager(settings=self._settings(), db_engine=DummyDB())

        rules = {
            rule.rule_id: rule
            for rule in manager.list_rules(
                layer="dwd",
                table_name="dwd_stock_eod_price",
                target_table_name="dwd_stock_eod_price_tmp",
            )
        }

        self.assertIn("event_date >= toDate32('2010-01-01')", rules["row_count_nonzero"].issue_count_sql)
        self.assertIn("event_date >= toDate32('2010-01-01')", rules["dwd_single_open_version"].issue_count_sql)
        self.assertIn("event_date >= toDate32('2010-01-01')", rules["market_ohlc_consistency"].issue_count_sql)
        self.assertNotIn("2010-01-01", rules["required_columns_exist"].issue_count_sql)

    def test_dws_trade_rules_are_limited_to_trade_dates_since_2010(self):
        manager = QualityManager(settings=self._settings(), db_engine=DummyDB())

        rules = {
            rule.rule_id: rule
            for rule in manager.list_rules(
                layer="dws",
                table_name="dws_stock_factor_wide",
                target_table_name="dws_stock_factor_wide_tmp",
            )
        }

        self.assertIn("trade_date >= toDate32('2010-01-01')", rules["row_count_nonzero"].issue_count_sql)
        self.assertIn("trade_date >= toDate32('2010-01-01')", rules["dws_factor_wide_unique_key"].issue_count_sql)
        self.assertIn("trade_date >= toDate32('2010-01-01')", rules["dws_factor_wide_ohlc"].issue_count_sql)

    def test_non_trade_dwd_rules_are_not_date_limited(self):
        manager = QualityManager(settings=self._settings(), db_engine=DummyDB())

        rules = {
            rule.rule_id: rule
            for rule in manager.list_rules(
                layer="dwd",
                table_name="dwd_stock_income",
                target_table_name="dwd_stock_income_tmp",
            )
        }

        self.assertNotIn("2010-01-01", rules["financial_no_placeholder_dates"].issue_count_sql)

    def test_dwd_open_version_rule_uses_source_business_key(self):
        manager = QualityManager(settings=self._settings(), db_engine=DummyDB())

        income_rules = {
            rule.rule_id: rule
            for rule in manager.list_rules(
                layer="dwd",
                table_name="dwd_stock_income",
                target_table_name="dwd_stock_income_tmp",
            )
        }
        calendar_rules = {
            rule.rule_id: rule
            for rule in manager.list_rules(
                layer="dwd",
                table_name="dwd_trade_calendar",
                target_table_name="dwd_trade_calendar_tmp",
            )
        }

        self.assertIn("report_type", income_rules["dwd_single_open_version"].issue_count_sql)
        self.assertIn("update_flag", income_rules["dwd_single_open_version"].issue_count_sql)
        self.assertIn(
            "GROUP BY ts_code, ann_date, f_ann_date, end_date, report_type, update_flag",
            income_rules["dwd_single_open_version"].issue_count_sql,
        )
        self.assertIn(
            "ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING",
            income_rules["dwd_no_overlapping_versions"].issue_count_sql,
        )
        self.assertIn("GROUP BY cal_date, exchange", calendar_rules["dwd_single_open_version"].issue_count_sql)
        self.assertNotIn("GROUP BY event_date", calendar_rules["dwd_single_open_version"].issue_count_sql)

    def test_dwd_version_sql_uses_full_window_frame(self):
        sql = DWDManager().render_sync_sql("dwd_stock_income")

        self.assertIn("ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING", sql)

    def test_dwd_trade_date_source_rows_are_limited_since_2010(self):
        price_sql = DWDManager().render_sync_sql("dwd_stock_eod_price")
        income_sql = DWDManager().render_sync_sql("dwd_stock_income")

        self.assertIn("src.`trade_date` >= toDate32('2010-01-01')", price_sql)
        self.assertNotIn("src.`trade_date` >= toDate32('2010-01-01')", income_sql)

    def test_dqc_metadata_uses_generic_result_tables(self):
        manager = DqcManager(settings=self._settings(), db_engine=DummyDB())

        schemas = manager._metadata_table_schemas()

        self.assertIn("dq_dqc_run", schemas)
        self.assertIn("dq_dqc_metric", schemas)
        self.assertIn("layer", [column["name"] for column in schemas["dq_dqc_run"]["columns"]])
        self.assertIn("suite_name", [column["name"] for column in schemas["dq_dqc_result"]["columns"]])
        self.assertIn("issue_rate", [column["name"] for column in schemas["dq_dqc_result"]["columns"]])

    def test_dqc_suite_resolution_is_generic(self):
        manager = DqcManager(settings=self._settings(), db_engine=DummyDB())

        self.assertEqual(manager.resolve_suite("dws", None), "stock_factor_panel")
        self.assertEqual(
            manager.resolve_tables("dws", "stock_factor_panel"),
            ["dws_stock_factor_wide", "dws_stock_factor_wide_matrix"],
        )

    def test_dqc_skip_records_bypass_without_running_suite(self):
        db = DummyDB()
        manager = DqcManager(
            settings=self._settings({"dqc_mode": "skip", "dqc_create_result_tables": False}),
            db_engine=db,
        )

        run = manager.run(layer="dws", suite_name="stock_factor_panel", table_name="dws_stock_factor_wide")

        self.assertEqual(run.status, "SKIPPED")
        self.assertEqual(db.inserts[0][0], "dq_dqc_run")

    def test_dqc_result_insert_includes_run_id(self):
        db = DummyDB()
        manager = DqcManager(settings=self._settings({"dqc_create_result_tables": False}), db_engine=db)

        with mock.patch.object(
            manager,
            "_run_dws_stock_factor_panel",
            return_value=(
                [
                    manager._dqc_result(
                        domain="factor",
                        suite_name="stock_factor_panel",
                        table_name="dws_stock_factor_wide",
                        rule_id="demo_rule",
                        check_layer="semantic",
                        check_type="demo",
                        severity="BLOCKER",
                        issue_count=0,
                        checked_count=100,
                    )
                ],
                [],
                [],
                [],
            ),
        ):
            run = manager.run(layer="dws", suite_name="stock_factor_panel", table_name="dws_stock_factor_wide")

        result_insert = next(data for table_name, data in db.inserts if table_name == "dq_dqc_result")
        self.assertEqual(result_insert["run_id"].iloc[0], run.run_id)
        self.assertEqual(result_insert["issue_rate"].iloc[0], 0.0)

    def test_dqc_result_computes_issue_rate(self):
        manager = DqcManager(settings=self._settings(), db_engine=DummyDB())

        result = manager._dqc_result(
            domain="factor",
            suite_name="stock_factor_panel",
            table_name="dws_stock_factor_wide",
            rule_id="demo_rule",
            check_layer="semantic",
            check_type="demo",
            severity="WARN",
            issue_count=5,
            checked_count=100,
        )
        zero_checked_result = manager._dqc_result(
            domain="factor",
            suite_name="stock_factor_panel",
            table_name="dws_stock_factor_wide",
            rule_id="demo_rule_zero",
            check_layer="semantic",
            check_type="demo",
            severity="WARN",
            issue_count=0,
            checked_count=0,
        )

        self.assertEqual(result.issue_rate, 0.05)
        self.assertIsNone(zero_checked_result.issue_rate)

    def test_dqc_wide_semantic_sql_contains_expected_rules(self):
        db = DqcSqlDB()
        manager = DqcManager(settings=self._settings(), db_engine=db)

        manager._dws_table_results(
            domain="factor",
            suite_name="stock_factor_panel",
            table_name="dws_stock_factor_wide",
            as_of_date=pd.Timestamp("2026-05-26").date(),
        )
        rendered_sql = "\n".join(db.queries)

        self.assertIn("dwd_trade_calendar", rendered_sql)
        self.assertIn("high < low OR high < open OR high < close", rendered_sql)
        self.assertIn("countIf(available_trade_date < trade_date) AS issue_count", rendered_sql)
        self.assertIn("count() AS checked_count", rendered_sql)
        self.assertIn("available_trade_date < trade_date", rendered_sql)

    def test_dqc_matrix_semantic_sql_contains_factor_checks(self):
        db = DqcSqlDB()
        manager = DqcManager(settings=self._settings(), db_engine=db)

        manager._dws_table_results(
            domain="factor",
            suite_name="stock_factor_panel",
            table_name="dws_stock_factor_wide_matrix",
            as_of_date=pd.Timestamp("2026-05-26").date(),
        )
        rendered_sql = "\n".join(db.queries)

        self.assertIn("factor_count !=", rendered_sql)
        self.assertIn("countIf(factor_count !=", rendered_sql)
        self.assertIn("qb_rsi_14 < 0 OR qb_rsi_14 > 100", rendered_sql)
        self.assertIn("source_table != 'dws_stock_factor_wide'", rendered_sql)
        self.assertIn("JSONExtractKeys", rendered_sql)
        self.assertIn("ifNull(JSONExtractRaw(ifNull(factor_errors_json, '{}'), 'errors'), '{}')", rendered_sql)
        self.assertNotIn("factor_errors_json NOT IN", rendered_sql)

    def test_dqc_numeric_finite_check_batches_wide_tables(self):
        db = DqcSqlDB()
        manager = DqcManager(settings=self._settings(), db_engine=db)

        manager._dws_numeric_finite_result(
            domain="factor",
            suite_name="stock_factor_panel",
            table_name="dws_stock_factor_wide_matrix",
            qualified="default.dws_stock_factor_wide_matrix",
            target_trade_date_sql="toDate32('2026-05-25')",
            numeric_columns=[f"factor_{index}" for index in range(181)],
        )

        self.assertEqual(len(db.queries), 3)
        self.assertLessEqual(max(query.count("countIf(") for query in db.queries), 80)

    def test_dqc_column_stats_batches_wide_tables(self):
        db = DqcMetricDB()
        manager = DqcManager(settings=self._settings(), db_engine=db)

        with mock.patch.object(
            manager,
            "_dws_numeric_columns",
            return_value=[f"factor_{index}" for index in range(95)],
        ):
            manager._dws_table_metrics(
                domain="factor",
                suite_name="stock_factor_panel",
                table_name="dws_stock_factor_wide_matrix",
                as_of_date=pd.Timestamp("2026-05-25").date(),
            )

        stats_queries = [query for query in db.queries if "UNION ALL" in query]
        self.assertEqual(len(stats_queries), 3)
        self.assertLessEqual(max(query.count("UNION ALL") for query in stats_queries), 39)

    def test_factor_reference_evaluator_recomputes_vsumn30(self):
        evaluator = _FactorExpressionReferenceEvaluator(
            "Sum(Greater(Ref($volume, 1)-$volume, 0), 30)/(Sum(Abs($volume-Ref($volume, 1)), 30)+1e-12)"
        )

        value = evaluator.evaluate(
            [
                {"volume": 10.0},
                {"volume": 8.0},
                {"volume": 11.0},
                {"volume": 7.0},
            ]
        )

        self.assertAlmostEqual(value, 6.0 / 9.0)

    def test_dqc_factor_business_cross_validation_records_mismatch_sample(self):
        db = DqcFactorCrossCheckDB()
        manager = DqcManager(
            settings=self._settings(
                {
                    "dqc_create_result_tables": False,
                    "dqc_factor_cross_check_samples": 1,
                    "dqc_factor_cross_check_history_rows": 30,
                }
            ),
            db_engine=db,
        )
        mapping = [
            {
                "factor_id": "a158_vsumn30",
                "factor_name": "Alpha158_成交量下跌占比30日",
                "expression": (
                    "Sum(Greater(Ref($volume, 1)-$volume, 0), 30)"
                    "/(Sum(Abs($volume-Ref($volume, 1)), 30)+1e-12)"
                ),
            }
        ]

        with mock.patch.object(manager, "_supported_factor_mapping", return_value=(mapping, 0)):
            results, samples = manager._dws_factor_business_cross_validation(
                domain="factor",
                suite_name="stock_factor_panel",
                as_of_date=pd.Timestamp("2026-05-25").date(),
            )

        cross_check = next(result for result in results if result.rule_id == "dqc_factor_business_cross_validation")
        self.assertEqual(cross_check.checked_count, 1)
        self.assertEqual(cross_check.issue_count, 1)
        self.assertEqual(cross_check.status, "FAIL")
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].entity_name, "a158_vsumn30")
        self.assertEqual(samples[0].sample_type, "factor_cross_check_failed")
        payload = json.loads(samples[0].sample_json)
        self.assertEqual(payload["actual_value"], 0.1)
        self.assertAlmostEqual(payload["expected_value"], 6.0 / 9.0)
        self.assertIn("factor_mapping_readable", cross_check.message)
        self.assertTrue(any("`vol` AS `volume`" in query for query in db.queries))

    def test_dqc_factor_business_cross_validation_records_passed_sample(self):
        db = DqcFactorCrossCheckDB(actual_value=6.0 / 9.0)
        manager = DqcManager(
            settings=self._settings(
                {
                    "dqc_create_result_tables": False,
                    "dqc_factor_cross_check_samples": 1,
                    "dqc_factor_cross_check_history_rows": 30,
                }
            ),
            db_engine=db,
        )
        mapping = [
            {
                "factor_id": "a158_vsumn30",
                "factor_name": "Alpha158_成交量下跌占比30日",
                "expression": (
                    "Sum(Greater(Ref($volume, 1)-$volume, 0), 30)"
                    "/(Sum(Abs($volume-Ref($volume, 1)), 30)+1e-12)"
                ),
            }
        ]

        with mock.patch.object(manager, "_supported_factor_mapping", return_value=(mapping, 0)):
            results, samples = manager._dws_factor_business_cross_validation(
                domain="factor",
                suite_name="stock_factor_panel",
                as_of_date=pd.Timestamp("2026-05-25").date(),
            )

        cross_check = next(result for result in results if result.rule_id == "dqc_factor_business_cross_validation")
        self.assertEqual(cross_check.checked_count, 1)
        self.assertEqual(cross_check.issue_count, 0)
        self.assertEqual(cross_check.status, "PASS")
        self.assertEqual(len(samples), 1)
        self.assertEqual(samples[0].sample_type, "factor_cross_check_passed")
        payload = json.loads(samples[0].sample_json)
        self.assertAlmostEqual(payload["actual_value"], 6.0 / 9.0)
        self.assertAlmostEqual(payload["expected_value"], 6.0 / 9.0)

    def test_dwd_dividend_sql_uses_source_key_and_announcement_visibility(self):
        sql = DWDManager().render_sync_sql("dwd_stock_dividend")
        availability_expr = (
            "coalesce(src.imp_ann_date, src.ann_date, src.record_date, "
            "src.ex_date, src.pay_date, src.div_listdate, src.end_date)"
        )

        self.assertIn("FROM default.dividend_raw src", sql)
        self.assertIn("PARTITION BY src.`ts_code`, src.`end_date`, src.`ann_date`, src.`div_proc`", sql)
        self.assertIn("lagInFrame(src._record_hash)", sql)
        self.assertIn(availability_expr, sql)
        self.assertIn("coalesce(calendar_map.next_trade_date, src.imp_ann_date", sql)

    def test_dwd_dc_concept_sql_uses_theme_trade_key_and_no_instrument(self):
        manager = DWDManager()
        schema = manager.build_schema(manager.load_spec("dwd_dc_concept"))
        sql = manager.render_sync_sql("dwd_dc_concept")

        columns = {column["name"]: column for column in schema["columns"]}
        column_names = set(columns)
        self.assertNotIn("instrument_id", column_names)
        self.assertNotIn("nullable", columns["theme_code"])
        self.assertNotIn("nullable", columns["trade_date"])
        self.assertIn("FROM default.dc_concept_raw src", sql)
        self.assertIn("PARTITION BY src.`theme_code`, src.`trade_date`", sql)
        self.assertIn("lagInFrame(src._record_hash)", sql)
        self.assertIn("coalesce(calendar_map.next_trade_date, src.trade_date)", sql)

    def test_dwd_dc_concept_cons_sql_uses_stock_theme_trade_key(self):
        manager = DWDManager()
        schema = manager.build_schema(manager.load_spec("dwd_dc_concept_cons"))
        columns = {column["name"]: column for column in schema["columns"]}
        sql = manager.render_sync_sql("dwd_dc_concept_cons")

        self.assertNotIn("nullable", columns["ts_code"])
        self.assertNotIn("nullable", columns["theme_code"])
        self.assertNotIn("nullable", columns["trade_date"])
        self.assertIn("FROM default.dc_concept_cons_raw src", sql)
        self.assertIn("concat('stock:', src.ts_code) AS `instrument_id`", sql)
        self.assertIn("PARTITION BY src.`ts_code`, src.`trade_date`, src.`theme_code`", sql)
        self.assertIn("lagInFrame(src._record_hash)", sql)

    def test_dwd_dc_index_sql_uses_board_trade_key_and_no_instrument(self):
        manager = DWDManager()
        schema = manager.build_schema(manager.load_spec("dwd_dc_index"))
        sql = manager.render_sync_sql("dwd_dc_index")

        columns = {column["name"]: column for column in schema["columns"]}
        column_names = set(columns)
        self.assertNotIn("instrument_id", column_names)
        self.assertNotIn("nullable", columns["ts_code"])
        self.assertNotIn("nullable", columns["trade_date"])
        self.assertIn("FROM default.dc_index_raw src", sql)
        self.assertIn("PARTITION BY src.`ts_code`, src.`trade_date`", sql)
        self.assertIn("lagInFrame(src._record_hash)", sql)
        self.assertIn("coalesce(calendar_map.next_trade_date, src.trade_date)", sql)

    def test_dwd_dc_member_sql_uses_stock_board_trade_key(self):
        manager = DWDManager()
        schema = manager.build_schema(manager.load_spec("dwd_dc_member"))
        columns = {column["name"]: column for column in schema["columns"]}
        sql = manager.render_sync_sql("dwd_dc_member")

        self.assertNotIn("nullable", columns["trade_date"])
        self.assertNotIn("nullable", columns["ts_code"])
        self.assertNotIn("nullable", columns["con_code"])
        self.assertIn("FROM default.dc_member_raw src", sql)
        self.assertIn("concat('stock:', src.con_code) AS `instrument_id`", sql)
        self.assertIn("PARTITION BY src.`trade_date`, src.`ts_code`, src.`con_code`", sql)
        self.assertIn("lagInFrame(src._record_hash)", sql)

    def test_dwd_index_weight_sql_uses_index_stock_trade_key(self):
        manager = DWDManager()
        schema = manager.build_schema(manager.load_spec("dwd_index_weight"))
        columns = {column["name"]: column for column in schema["columns"]}
        sql = manager.render_sync_sql("dwd_index_weight")

        self.assertNotIn("nullable", columns["index_code"])
        self.assertNotIn("nullable", columns["con_code"])
        self.assertNotIn("nullable", columns["trade_date"])
        self.assertIn("FROM default.index_weight_raw src", sql)
        self.assertIn("concat('stock:', src.con_code) AS `instrument_id`", sql)
        self.assertIn("PARTITION BY src.`index_code`, src.`con_code`, src.`trade_date`", sql)
        self.assertIn("src.`trade_date` >= toDate32('2010-01-01')", sql)
        self.assertIn("coalesce(calendar_map.next_trade_date, src.trade_date)", sql)

    def test_dwd_index_weight_quality_rules_include_domain_checks(self):
        manager = QualityManager(settings=self._settings(), db_engine=DummyDB())

        rules = {
            rule.rule_id: rule
            for rule in manager.list_rules(
                layer="dwd",
                table_name="dwd_index_weight",
                target_table_name="dwd_index_weight_tmp",
            )
        }

        self.assertIn("index_weight_percent_range", rules)
        self.assertIn("index_weight_available_not_before_event", rules)
        self.assertIn("weight < 0 OR weight > 100", rules["index_weight_percent_range"].issue_count_sql)
        self.assertIn("event_date >= toDate32('2010-01-01')", rules["index_weight_percent_range"].issue_count_sql)

    def test_dwd_dividend_quality_rules_include_pit_and_domain_checks(self):
        manager = QualityManager(settings=self._settings(), db_engine=DummyDB())

        rules = {
            rule.rule_id: rule
            for rule in manager.list_rules(
                layer="dwd",
                table_name="dwd_stock_dividend",
                target_table_name="dwd_stock_dividend_tmp",
            )
        }

        self.assertIn("financial_no_placeholder_dates", rules)
        self.assertIn("dividend_nonnegative_values", rules)
        self.assertIn("dividend_action_dates_not_before_announcement", rules)
        self.assertIn(
            "GROUP BY ts_code, end_date, ann_date, div_proc",
            rules["dwd_single_open_version"].issue_count_sql,
        )
        self.assertIn("cash_div_tax < 0", rules["dividend_nonnegative_values"].issue_count_sql)


if __name__ == "__main__":
    unittest.main()
