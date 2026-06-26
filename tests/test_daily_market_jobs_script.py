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
