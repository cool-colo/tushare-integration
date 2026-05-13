import unittest
from unittest import mock

import pandas as pd

from tushare_integration.quality import QualityManager, QualityValidationError, ValidationResult
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


if __name__ == "__main__":
    unittest.main()
