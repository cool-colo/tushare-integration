import datetime
import hashlib
import json

import pandas as pd

from tushare_integration.items import TushareIntegrationItem
from tushare_integration.spiders.tushare import TushareRequestRateLimiter, TushareSpider


class FundPortfolioSpider(TushareSpider):
    name = "fund/portfolio/fund_portfolio"
    api_name = "fund_portfolio"
    PAGE_LIMIT = 8000
    MAX_PAGES_PER_PERIOD = 10000

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.period_progress = {}

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.settings.set("DOWNLOAD_DELAY", spider.get_portfolio_download_delay(), priority="spider")
        return spider

    def get_portfolio_download_delay(self):
        # This endpoint's documented allowance differs from the global tiers.
        frequency = 500 if self.spider_settings.tushare_point >= 8000 else 200
        ratio = self.spider_settings.tushare_rate_limit_ratio
        return max(self.spider_settings.get_download_delay(), 60 / (frequency * ratio))

    def wait_for_rate_limit(self):
        TushareRequestRateLimiter.wait(self.get_portfolio_download_delay())

    def get_request_end_date(self):
        return datetime.date.today()

    def get_all_period(self):
        # Refresh every completed quarter: existing rows do not prove that all
        # funds have disclosed, and old disclosures can subsequently change.
        start_date = pd.to_datetime(self.spider_settings.default_min_cal_date).date()
        end_date = self.get_request_end_date()
        for year in range(start_date.year, end_date.year + 1):
            for month, day in [(3, 31), (6, 30), (9, 30), (12, 31)]:
                period = datetime.date(year, month, day)
                if start_date <= period <= end_date:
                    yield period.strftime("%Y%m%d")

    def start_requests(self):
        self.logger.info(
            "fund_portfolio streaming pagination: page_limit=%s max_pages_per_period=%s code=%s",
            self.PAGE_LIMIT, self.MAX_PAGES_PER_PERIOD, __file__,
        )
        for period in self.get_all_period():
            yield self.get_scrapy_request(params={"period": period, "offset": 0, "limit": self.PAGE_LIMIT})

    def parse(self, response, **kwargs):
        page = self.parse_response(response, **kwargs)
        params = dict(response.meta["params"])
        period = params["period"]
        offset = int(params.get("offset", 0))
        progress = self.period_progress.setdefault(period, {"page_hashes": set(), "rows": 0, "pages": 0})
        data = page["data"]
        if data.empty:
            self.logger.info("Completed fund_portfolio period=%s rows=%s", period, progress["rows"])
            del self.period_progress[period]
            return

        if not pd.to_datetime(data["end_date"], format="mixed", errors="coerce").dt.strftime("%Y%m%d").eq(period).all():
            raise RuntimeError(f"fund_portfolio returned a different report period: period={period} offset={offset}")
        if progress["pages"] >= self.MAX_PAGES_PER_PERIOD:
            raise RuntimeError(
                f"fund_portfolio exceeded page safety limit: period={period} offset={offset} "
                f"max_pages={self.MAX_PAGES_PER_PERIOD}; period is incomplete"
            )
        page_rows = sorted(json.dumps(row, sort_keys=True, default=str) for row in data.to_dict("records"))
        page_hash = hashlib.sha256("\n".join(page_rows).encode("utf-8")).hexdigest()
        if page_hash in progress["page_hashes"]:
            # Live Tushare pages can repeat exactly at different offsets yet
            # later offsets contain new rows. Equality does not prove a stall.
            self.logger.warning(
                "Repeated fund_portfolio source page: period=%s offset=%s; continuing to the next offset",
                period, offset,
            )
        progress["page_hashes"].add(page_hash)
        progress["pages"] += 1
        progress["rows"] += len(data)
        unique_rows = data.drop_duplicates()
        duplicate_rows = len(data) - len(unique_rows)
        if duplicate_rows:
            self.logger.warning(
                "Duplicate fund_portfolio source rows: period=%s offset=%s duplicate_rows=%s; raw retains all rows",
                period, offset, duplicate_rows,
            )
        key = self.schema["primary_key"]
        conflicts = unique_rows.duplicated(subset=key, keep=False)
        if conflicts.any():
            self.logger.warning(
                "Conflicting fund_portfolio source payloads: period=%s offset=%s keys=%s; "
                "raw retains variants, ODS latest keeps the last returned row per key; "
                "source revision order is unknown",
                period, offset, len(unique_rows.loc[conflicts, key].drop_duplicates()),
            )
        self.logger.info(
            "Collected fund_portfolio period=%s offset=%s page_rows=%s total_rows=%s",
            period, offset, len(data), progress["rows"],
        )

        # A quarter can contain millions of rows. Send each page to the normal
        # storage pipeline immediately instead of buffering the whole quarter.
        yield TushareIntegrationItem(data=data)
        # Follow-up pages stay in Scrapy so timeouts, retries and interruption
        # work normally. Short pages are not assumed to be the last page.
        params["offset"] = offset + len(data)
        yield self.get_scrapy_request(params=params)
