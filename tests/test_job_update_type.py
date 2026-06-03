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
