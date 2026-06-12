from pathlib import Path
import unittest

import yaml

from tushare_integration.manager import CrawlManager


class JobUpdateTypeTest(unittest.TestCase):
    def test_update_type_aliases(self):
        self.assertEqual(CrawlManager.normalize_update_type("daily"), "incremental")
        self.assertEqual(CrawlManager.normalize_update_type("incremental"), "incremental")
        self.assertEqual(CrawlManager.normalize_update_type("fully"), "full")
        self.assertEqual(CrawlManager.normalize_update_type("full"), "full")
        self.assertIsNone(CrawlManager.normalize_update_type(None))

    def test_filter_job_spiders_by_update_type_defaults_to_incremental(self):
        job = {
            "name": "stock/example",
            "spiders": [
                {"name": "stock/example/daily_spider"},
                {"name": "stock/example/full_spider", "update_type": "full"},
                {"name": "stock/example/both_spider", "update_types": ["incremental", "full"]},
                {"name": "stock/example/disabled_spider", "enabled": False},
            ],
        }

        self.assertEqual(
            [spider["name"] for spider in CrawlManager.filter_job_spiders_by_update_type(job, None)],
            [
                "stock/example/daily_spider",
                "stock/example/full_spider",
                "stock/example/both_spider",
            ],
        )
        self.assertEqual(
            [spider["name"] for spider in CrawlManager.filter_job_spiders_by_update_type(job, "incremental")],
            [
                "stock/example/daily_spider",
                "stock/example/both_spider",
            ],
        )
        self.assertEqual(
            [spider["name"] for spider in CrawlManager.filter_job_spiders_by_update_type(job, "full")],
            [
                "stock/example/full_spider",
                "stock/example/both_spider",
            ],
        )

    def test_stock_market_job_skips_disabled_legacy_apis(self):
        jobs_path = Path(__file__).resolve().parents[1] / "jobs.yaml"
        jobs = yaml.safe_load(jobs_path.read_text(encoding="utf-8"))
        stock_market_job = next(job for job in jobs["cronjob"] if job["name"] == "stock/market")

        full_spiders = [
            spider["name"]
            for spider in CrawlManager.filter_job_spiders_by_update_type(stock_market_job, "full")
        ]
        incremental_spiders = [
            spider["name"]
            for spider in CrawlManager.filter_job_spiders_by_update_type(stock_market_job, "incremental")
        ]

        self.assertNotIn("stock/market/concept", full_spiders)
        self.assertNotIn("stock/market/concept_detail", full_spiders)
        self.assertNotIn("stock/market/stk_account_old", full_spiders)
        self.assertNotIn("stock/market/concept", incremental_spiders)
        self.assertNotIn("stock/market/concept_detail", incremental_spiders)
        self.assertIn("stock/market/dc_concept", incremental_spiders)
        self.assertIn("stock/market/dc_concept_cons", incremental_spiders)

    def test_stock_quotes_job_skips_disabled_legacy_apis(self):
        jobs_path = Path(__file__).resolve().parents[1] / "jobs.yaml"
        jobs = yaml.safe_load(jobs_path.read_text(encoding="utf-8"))
        stock_quotes_job = next(job for job in jobs["cronjob"] if job["name"] == "stock/quotes")

        all_spiders = [
            spider["name"]
            for spider in CrawlManager.filter_job_spiders_by_update_type(stock_quotes_job, None)
        ]
        full_spiders = [
            spider["name"]
            for spider in CrawlManager.filter_job_spiders_by_update_type(stock_quotes_job, "full")
        ]

        self.assertNotIn("stock/quotes/ggt_monthly", all_spiders)
        self.assertNotIn("stock/quotes/ggt_monthly", full_spiders)

    def test_filter_job_spiders_rejects_unknown_update_type(self):
        with self.assertRaisesRegex(ValueError, "Unsupported update_type"):
            CrawlManager.normalize_update_type("nightly")

    def test_index_daily_job_is_incremental(self):
        jobs_path = Path(__file__).resolve().parents[1] / "jobs.yaml"
        jobs = yaml.safe_load(jobs_path.read_text(encoding="utf-8"))
        index_quotes_job = next(job for job in jobs["cronjob"] if job["name"] == "index/quotes")

        incremental_spiders = [
            spider["name"]
            for spider in CrawlManager.filter_job_spiders_by_update_type(index_quotes_job, "incremental")
        ]
        full_spiders = [
            spider["name"]
            for spider in CrawlManager.filter_job_spiders_by_update_type(index_quotes_job, "full")
        ]

        self.assertIn("index/quotes/index_daily", incremental_spiders)
        self.assertNotIn("index/quotes/index_daily", full_spiders)

    def test_baostock_financial_job_supports_incremental(self):
        jobs_path = Path(__file__).resolve().parents[1] / "jobs.yaml"
        jobs = yaml.safe_load(jobs_path.read_text(encoding="utf-8"))
        baostock_financial_job = next(job for job in jobs["cronjob"] if job["name"] == "baostock/stock/financial")

        incremental_spiders = [
            spider["name"]
            for spider in CrawlManager.filter_job_spiders_by_update_type(baostock_financial_job, "incremental")
        ]
        full_spiders = [
            spider["name"]
            for spider in CrawlManager.filter_job_spiders_by_update_type(baostock_financial_job, "full")
        ]

        expected_spiders = {
            "baostock/stock/balance",
            "baostock/stock/profit",
            "baostock/stock/cash_flow",
            "baostock/stock/operation",
            "baostock/stock/growth",
            "baostock/stock/debt",
            "baostock/stock/dupont",
            "baostock/stock/financial_indicator",
            "baostock/stock/express",
        }
        self.assertTrue(expected_spiders.issubset(set(incremental_spiders)))
        self.assertTrue(expected_spiders.issubset(set(full_spiders)))
