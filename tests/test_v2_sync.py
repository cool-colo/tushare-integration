import unittest
from unittest import mock

import inspect

from tushare_integration.commands import dws_app as app, sync_dws_table
from tushare_integration.dws import DWSManager


class V2SyncTest(unittest.TestCase):
    def setUp(self):
        self.manager = DWSManager()
        self.engine = mock.Mock()
        self.manager.db_engine = self.engine
        self.result = {"target": "dws_stock_factor_wide_v2_tmp_unique", "report_path": "unused.json"}

    def run_sync(self, *, exists=True, **kwargs):
        with (
            mock.patch.object(self.manager, "build_v2_candidate", return_value=self.result) as build,
            mock.patch.object(self.manager, "_clickhouse_table_exists", return_value=exists),
            mock.patch.object(self.manager, "_run_post_publish_dqc") as dqc,
            mock.patch("tushare_integration.v2_build.save_report"),
        ):
            self.manager.sync_table("dws_stock_factor_wide_v2", **kwargs)
        return build, dqc

    def test_full_market_once_warn_only_atomic_exchange_retains_old_production(self):
        build, dqc = self.run_sync()
        build.assert_called_once_with(validation_mode="warn_only")
        self.engine.query.assert_called_once_with(
            "EXCHANGE TABLES `default`.`dws_stock_factor_wide_v2` AND `default`.`dws_stock_factor_wide_v2_tmp_unique`")
        dqc.assert_called_once_with("dws_stock_factor_wide_v2", self.engine)

    def test_initial_publication_and_strict_override(self):
        build, _ = self.run_sync(exists=False, validation_mode="strict")
        build.assert_called_once_with(validation_mode="strict")
        self.engine.query.assert_called_once_with(
            "RENAME TABLE `default`.`dws_stock_factor_wide_v2_tmp_unique` TO `default`.`dws_stock_factor_wide_v2`")

    def test_failed_build_leaves_production_and_skips_dqc(self):
        with mock.patch.object(self.manager, "build_v2_candidate", side_effect=RuntimeError("build failed")), mock.patch.object(self.manager, "_run_post_publish_dqc") as dqc:
            with self.assertRaisesRegex(RuntimeError, "build failed"):
                self.manager.sync_table("dws_stock_factor_wide_v2")
        self.engine.query.assert_not_called()
        dqc.assert_not_called()

    def test_exchange_failure_has_no_destructive_fallback(self):
        self.engine.query.side_effect = RuntimeError("EXCHANGE unavailable")
        with self.assertRaisesRegex(RuntimeError, "EXCHANGE unavailable"):
            self.run_sync()
        self.assertEqual(self.engine.query.call_count, 1)
        self.assertEqual(self.result["publication"]["status"], "failed")

    def test_skipping_validation_rejected_before_writes(self):
        for kwargs in ({"skip_validation": True}, {"validation_mode": "skip"}):
            with self.subTest(kwargs=kwargs), mock.patch.object(self.manager, "build_v2_candidate") as build:
                with self.assertRaisesRegex(ValueError, "requires validation"):
                    self.manager.sync_table("dws_stock_factor_wide_v2", **kwargs)
                build.assert_not_called()
        self.engine.query.assert_not_called()

    def test_removed_staged_cli_options(self):
        commands = {command.name for command in app.registered_commands}
        self.assertFalse(commands & {"build-v2", "v2-build-sql", "v2-build-report"})
        self.assertNotIn("v2_qualified_report", inspect.signature(sync_dws_table).parameters)

    def test_other_dws_tables_keep_existing_path(self):
        table = "dws_stock_income_quarter"
        with (
            mock.patch.object(self.manager, "ensure_source_tables"),
            mock.patch.object(self.manager, "ensure_required_functions"),
            mock.patch.object(self.manager, "render_sync_sql", return_value="INSERT original"),
            mock.patch.object(self.manager, "build_v2_candidate") as v2,
            mock.patch("tushare_integration.dws.QualityManager.validate_publish"),
            mock.patch.object(self.manager, "_replace_clickhouse_table_from_tmp") as publish,
            mock.patch.object(self.manager, "_run_post_publish_dqc"),
        ):
            self.manager.sync_table(table, validation_mode="strict")
        v2.assert_not_called()
        publish.assert_called_once_with(table, f"{table}_tmp")
