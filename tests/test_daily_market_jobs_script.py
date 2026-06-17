from pathlib import Path
import unittest


class DailyMarketJobsScriptTest(unittest.TestCase):
    def test_security_master_sources_and_dwd_sync_are_scheduled(self):
        script_path = Path(__file__).resolve().parents[1] / "scripts" / "run_daily_market_jobs.sh"
        script = script_path.read_text(encoding="utf-8")

        self.assertIn('"tushare-job-${UPDATE_TYPE}-index-basic|$IMAGE_DEFAULT|index/basic|full"', script)
        self.assertIn('"tushare-job-${UPDATE_TYPE}-future-basic|$IMAGE_DEFAULT|future/basic|full"', script)
        self.assertIn('"tushare-dwd-sync-security-master|$DWD_SYNC_IMAGE|dwd_security_master"', script)
