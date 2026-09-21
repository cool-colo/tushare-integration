from pathlib import Path
import re
import unittest

import yaml


class DailyMarketJobsScriptTest(unittest.TestCase):
    def setUp(self):
        self.root_dir = Path(__file__).resolve().parents[1]
        self.script_path = self.root_dir / "scripts" / "run_daily_market_jobs.sh"
        self.script = self.script_path.read_text(encoding="utf-8")

    def test_security_master_sources_and_dwd_sync_are_scheduled(self):
        self.assertIn('"tushare-job-${UPDATE_TYPE}-index-basic|$IMAGE_DEFAULT|index/basic|full"', self.script)
        self.assertIn('"tushare-job-${UPDATE_TYPE}-future-basic|$IMAGE_DEFAULT|future/basic|full"', self.script)
        self.assertIn('"tushare-dwd-sync-security-master|$DWD_SYNC_IMAGE|dwd_security_master"', self.script)

    def test_all_dwd_schema_tables_are_scheduled(self):
        schema_dir = self.root_dir / "tushare_integration" / "schema" / "dwd"
        expected_tables = {
            yaml.safe_load(path.read_text(encoding="utf-8"))["name"]
            for path in schema_dir.glob("*.yaml")
        }
        scheduled_tables = set(
            re.findall(r'"tushare-dwd-sync-[^"]+\|\$DWD_SYNC_IMAGE\|([^"]+)"', self.script)
        )

        self.assertEqual(expected_tables, scheduled_tables)

    def test_daily_script_uses_shared_runner(self):
        self.assertIn('source "$SCRIPT_DIR/lib/market_job_runner.sh"', self.script)

    def test_stock_factor_wide_v2_is_scheduled_between_wide_and_matrix(self):
        old_wide = self.script.index("dws_stock_factor_wide\"")
        v2_wide = self.script.index("dws_stock_factor_wide_v2\"")
        matrix = self.script.index("dws_stock_factor_wide_matrix\"")
        self.assertLess(old_wide, v2_wide)
        self.assertLess(v2_wide, matrix)

    def test_pre_market_script_runs_price_batch_then_dwd_sync(self):
        script_path = self.root_dir / "scripts" / "run_pre_market_jobs.sh"
        script = script_path.read_text(encoding="utf-8")

        self.assertIn('PRE_JOBS_FILE="${PRE_JOBS_FILE:-$PROJECT_DIR/pre_job.yaml}"', script)
        self.assertIn('source "$SCRIPT_DIR/lib/market_job_runner.sh"', script)
        self.assertIn('"pre/stock-eod-price"', script)
        self.assertIn('"dwd_stock_eod_price"', script)
        self.assertLess(script.index('"pre/stock-eod-price"'), script.index('"dwd_stock_eod_price"'))

    def test_pre_open_script_runs_adj_factor_batch_then_dwd_sync(self):
        script_path = self.root_dir / "scripts" / "run_pre_open_jobs.sh"
        script = script_path.read_text(encoding="utf-8")

        self.assertIn('PRE_OPEN_JOBS_FILE="${PRE_OPEN_JOBS_FILE:-$PROJECT_DIR/pre_open_job.yaml}"', script)
        self.assertIn('source "$SCRIPT_DIR/lib/market_job_runner.sh"', script)
        self.assertIn('"pre/stock-adj-factor"', script)
        self.assertIn('"dwd_stock_adj_factor"', script)
        self.assertLess(script.index('"pre/stock-adj-factor"'), script.index('"dwd_stock_adj_factor"'))
