from dataclasses import dataclass
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import jinja2
import pandas as pd

from tushare_integration.dws import DWSManager
from tushare_integration.v2_build import execute_build


@dataclass
class Validation:
    mode: str = "warn_only"
    status: str = "PASS"


class V2CandidateTest(unittest.TestCase):
    def setUp(self):
        self.manager = DWSManager()
        self.engine = mock.Mock()
        self.manager.db_engine = self.engine
        self.engine.templates = {"create": jinja2.Template("CREATE TABLE IF NOT EXISTS {{ db_name }}.{{ table_name }} (id Int64) ENGINE=Memory")}
        self.engine.query_df.side_effect = lambda sql: pd.DataFrame([
            {"only_candidate": 0, "only_price": 0} if "AS only_candidate" in sql else {"rows": 2, "keys": 2}
        ])
        self.patches = [
            mock.patch.object(self.manager, "_clickhouse_table_exists", return_value=False),
            mock.patch.object(self.manager, "ensure_source_tables"),
            mock.patch.object(self.manager, "render_sync_sql", return_value="INSERT INTO candidate SELECT 1"),
            mock.patch("tushare_integration.v2_build.source_inventory", return_value={"parts": []}),
            mock.patch("tushare_integration.v2_build.collect_query_metrics", return_value=[]),
            mock.patch("tushare_integration.v2_build.QualityManager.validate_publish", return_value=Validation()),
        ]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_isolated_full_market_creates_once_inserts_once_never_publishes(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = execute_build(self.manager, report_path=Path(tmp)/"report.json")
            report = json.loads((Path(tmp)/"report.json").read_text())
        self.assertEqual(report["status"], "validated")
        self.assertTrue(result["target"].startswith("dws_stock_factor_wide_v2_tmp_"))
        self.assertIsNone(report["publication"])
        self.assertEqual(self.engine.query.call_count, 2)
        self.assertTrue(self.engine.query.call_args_list[0].args[0].startswith("CREATE TABLE default."))
        self.assertEqual(self.engine.query.call_args_list[1].args[0], "INSERT INTO candidate SELECT 1")
        self.manager.render_sync_sql.assert_called_once_with("dws_stock_factor_wide_v2", target_table_name=result["target"], instrument_ids=None)

    def test_existing_and_reserved_targets_do_not_write(self):
        for target in ("dws_stock_factor_wide_v2", "dws_stock_factor_wide_v2_tmp", "v2_stage_old_price", "bad;name"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                execute_build(self.manager, target)
        with mock.patch.object(self.manager, "_clickhouse_table_exists", return_value=True), self.assertRaisesRegex(ValueError, "already exists"):
            execute_build(self.manager, "existing_candidate")
        self.engine.query.assert_not_called()

    def test_failed_insert_preserves_candidate_and_report(self):
        self.engine.query.side_effect = [None, RuntimeError("memory limit")]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/"report.json"
            with self.assertRaisesRegex(RuntimeError, "memory limit"):
                execute_build(self.manager, "candidate", report_path=path)
            report = json.loads(path.read_text())
        self.assertEqual(report["status"], "failed")
        self.assertEqual(self.engine.query.call_count, 2)

    def test_source_change_stops_publication_and_preserves_candidate(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch("tushare_integration.v2_build.source_inventory", side_effect=[{"parts": [1]}, {"parts": [2]}]):
            path = Path(tmp)/"report.json"
            with self.assertRaisesRegex(RuntimeError, "Source inventory changed"):
                execute_build(self.manager, "candidate", report_path=path)
            report = json.loads(path.read_text())
        self.assertFalse(report["sources_unchanged"])
        self.assertEqual(self.engine.query.call_count, 2)
