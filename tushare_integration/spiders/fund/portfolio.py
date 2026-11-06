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
    MAX_PAGES_PER_FUND = 10000
    FUND_BASIC_PAGE_LIMIT = 15000
    MAX_FUND_BASIC_PAGES_PER_MARKET = 100
    FUND_MARKETS = ("E", "O")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fund_codes = set()
        self.fund_basic_progress = {}
        self.completed_fund_markets = set()
        self.fund_progress = {}

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

    def start_requests(self):
        self.logger.info(
            "fund_portfolio per-fund streaming pagination: page_limit=%s "
            "fund_basic_page_limit=%s max_pages_per_fund=%s code=%s",
            self.PAGE_LIMIT, self.FUND_BASIC_PAGE_LIMIT, self.MAX_PAGES_PER_FUND, __file__,
        )
        # Tushare now enforces ts_code for fund_portfolio. Discover the source
        # universe from fund_basic itself; do not substitute ETF tables or the
        # codes already present in historical holdings, which can omit funds.
        for market in self.FUND_MARKETS:
            yield self.get_fund_basic_request(market=market, offset=0)

    def get_fund_basic_request(self, market: str, offset: int):
        return self.get_scrapy_request(
            params={"market": market, "offset": offset, "limit": self.FUND_BASIC_PAGE_LIMIT},
            api_name="fund_basic",
            fields="ts_code",
            callback=self.parse_fund_basic,
        )

    def parse_fund_basic(self, response, **kwargs):
        page = self.parse_response(response, **kwargs)
        params = dict(response.meta["params"])
        market = params["market"]
        offset = int(params.get("offset", 0))
        data = page["data"]
        progress = self.fund_basic_progress.setdefault(
            market, {"page_hashes": set(), "rows": 0, "pages": 0}
        )

        if len(data) > self.FUND_BASIC_PAGE_LIMIT:
            raise RuntimeError(
                f"fund_basic exceeded requested page limit: market={market} offset={offset} "
                f"rows={len(data)} limit={self.FUND_BASIC_PAGE_LIMIT}"
            )
        if data.empty:
            yield from self.complete_fund_market(market)
            return
        if "ts_code" not in data.columns:
            raise RuntimeError(f"fund_basic response has no ts_code column: market={market} offset={offset}")

        codes = data["ts_code"].astype("string")
        invalid_codes = codes.isna() | codes.str.strip().eq("")
        if invalid_codes.any():
            raise RuntimeError(
                f"fund_basic returned blank ts_code values: market={market} offset={offset} "
                f"rows={int(invalid_codes.sum())}"
            )
        page_codes = codes.str.strip().tolist()
        page_hash = hashlib.sha256("\n".join(sorted(page_codes)).encode("utf-8")).hexdigest()
        if page_hash in progress["page_hashes"]:
            raise RuntimeError(
                f"fund_basic repeated a source page: market={market} offset={offset}; "
                "fund universe may be truncated"
            )
        progress["page_hashes"].add(page_hash)
        progress["pages"] += 1
        progress["rows"] += len(page_codes)
        if progress["pages"] > self.MAX_FUND_BASIC_PAGES_PER_MARKET:
            raise RuntimeError(
                f"fund_basic exceeded page safety limit: market={market} offset={offset} "
                f"max_pages={self.MAX_FUND_BASIC_PAGES_PER_MARKET}; fund universe may be incomplete"
            )

        duplicate_rows = len(page_codes) - len(set(page_codes))
        if duplicate_rows:
            self.logger.warning(
                "Duplicate fund_basic codes in source page: market=%s offset=%s duplicate_rows=%s",
                market, offset, duplicate_rows,
            )
        new_codes = []
        for ts_code in page_codes:
            if ts_code not in self.fund_codes:
                self.fund_codes.add(ts_code)
                new_codes.append(ts_code)
        repeated_codes = len(set(page_codes)) - len(new_codes)
        if repeated_codes:
            self.logger.warning(
                "Fund_basic codes already seen on another page or market: "
                "market=%s offset=%s repeated_codes=%s",
                market, offset, repeated_codes,
            )
        self.logger.info(
            "Collected fund_basic market=%s offset=%s page_rows=%s new_codes=%s total_codes=%s",
            market, offset, len(page_codes), len(new_codes), len(self.fund_codes),
        )

        # Do not treat a short page as terminal: the server can enforce a cap
        # below the requested limit. Only an explicit empty page proves that
        # this market's code universe has completed.
        yield self.get_fund_basic_request(market=market, offset=offset + len(data))

    def complete_fund_market(self, market: str):
        progress = self.fund_basic_progress[market]
        if progress["rows"] == 0:
            raise RuntimeError(f"fund_basic returned no fund codes for market={market}")
        self.completed_fund_markets.add(market)
        self.logger.info("Completed fund_basic market=%s rows=%s", market, progress["rows"])
        if self.completed_fund_markets == set(self.FUND_MARKETS):
            self.logger.info("Completed fund_basic universe total_codes=%s", len(self.fund_codes))
            # Start holdings only after both source markets reach an explicit
            # empty page. A discovery failure must not begin a partial-universe
            # ingestion.
            for ts_code in sorted(self.fund_codes):
                yield self.get_scrapy_request(
                    params={"ts_code": ts_code, "offset": 0, "limit": self.PAGE_LIMIT}
                )

    def parse(self, response, **kwargs):
        page = self.parse_response(response, **kwargs)
        params = dict(response.meta["params"])
        ts_code = params["ts_code"]
        offset = int(params.get("offset", 0))
        progress = self.fund_progress.setdefault(
            ts_code, {"page_hashes": set(), "source_rows": 0, "stored_rows": 0, "pages": 0}
        )
        data = page["data"]
        if data.empty:
            self.logger.info(
                "Completed fund_portfolio ts_code=%s source_rows=%s stored_rows=%s",
                ts_code, progress["source_rows"], progress["stored_rows"],
            )
            del self.fund_progress[ts_code]
            return

        if not data["ts_code"].astype("string").eq(ts_code).all():
            raise RuntimeError(
                f"fund_portfolio returned a different fund code: ts_code={ts_code} offset={offset}"
            )
        end_dates = pd.to_datetime(data["end_date"], format="mixed", errors="coerce")
        if end_dates.isna().any():
            raise RuntimeError(f"fund_portfolio returned invalid end_date: ts_code={ts_code} offset={offset}")
        future_dates = end_dates.dt.date > self.get_request_end_date()
        if future_dates.any():
            raise RuntimeError(f"fund_portfolio returned a future end_date: ts_code={ts_code} offset={offset}")
        if progress["pages"] >= self.MAX_PAGES_PER_FUND:
            raise RuntimeError(
                f"fund_portfolio exceeded page safety limit: ts_code={ts_code} offset={offset} "
                f"max_pages={self.MAX_PAGES_PER_FUND}; fund is incomplete"
            )
        page_rows = sorted(json.dumps(row, sort_keys=True, default=str) for row in data.to_dict("records"))
        page_hash = hashlib.sha256("\n".join(page_rows).encode("utf-8")).hexdigest()
        if page_hash in progress["page_hashes"]:
            # Live Tushare pages can repeat exactly at different offsets yet
            # later offsets contain new rows. Equality does not prove a stall.
            self.logger.warning(
                "Repeated fund_portfolio source page: ts_code=%s offset=%s; continuing to the next offset",
                ts_code, offset,
            )
        progress["page_hashes"].add(page_hash)
        progress["pages"] += 1
        progress["source_rows"] += len(data)

        start_date = pd.to_datetime(self.spider_settings.default_min_cal_date).date()
        eligible_data = data.loc[end_dates.dt.date >= start_date].copy()
        progress["stored_rows"] += len(eligible_data)
        unique_rows = eligible_data.drop_duplicates()
        duplicate_rows = len(eligible_data) - len(unique_rows)
        if duplicate_rows:
            self.logger.warning(
                "Duplicate fund_portfolio source rows: ts_code=%s offset=%s duplicate_rows=%s; raw retains all rows",
                ts_code, offset, duplicate_rows,
            )
        key = self.schema["primary_key"]
        conflicts = unique_rows.duplicated(subset=key, keep=False)
        if conflicts.any():
            self.logger.warning(
                "Conflicting fund_portfolio source payloads: ts_code=%s offset=%s keys=%s; "
                "raw retains variants, ODS latest keeps the last returned row per key; "
                "source revision order is unknown",
                ts_code, offset, len(unique_rows.loc[conflicts, key].drop_duplicates()),
            )
        self.logger.info(
            "Collected fund_portfolio ts_code=%s offset=%s page_rows=%s stored_page_rows=%s "
            "source_rows=%s stored_rows=%s",
            ts_code, offset, len(data), len(eligible_data), progress["source_rows"], progress["stored_rows"],
        )

        # Send eligible rows to the normal storage pipeline immediately. The
        # API is queried for full per-fund history because ts_code is mandatory;
        # preserve the configured historical boundary locally.
        if not eligible_data.empty:
            yield TushareIntegrationItem(data=eligible_data)
        # Follow-up pages stay in Scrapy so timeouts, retries and interruption
        # work normally. Short pages are not assumed to be the last page.
        params["offset"] = offset + len(data)
        yield self.get_scrapy_request(params=params)
