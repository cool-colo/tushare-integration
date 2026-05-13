import unittest

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
