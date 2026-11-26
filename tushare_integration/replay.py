"""Explicit date re-ingestion through the existing daily-spider pipelines."""

import datetime
import json
import math
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

import pandas as pd
from scrapy.settings import Settings
from scrapy.spiderloader import SpiderLoader

from tushare_integration.spiders.tushare import DailySpider, TushareSpider


# Only opt in APIs with an established replay completeness policy. Do not
# infer a row limit for another endpoint from its schema or spider base class.
# fund_adj documents offset/limit (doc_id=199); stk_factor documents pagination
# (doc_id=296). adj_factor's offset/limit behavior was checked against the API;
# its documentation (doc_id=28) does not publish a default response limit.
PAGINATED_REPLAY_PAGE_SIZES = {'adj_factor': 1000, 'fund_adj': 2000, 'stk_factor': 10000}
# Documented single-response limits: doc_id=27, 32, 127, and 183 respectively.
REPLAY_RESPONSE_ROW_LIMITS = {'daily': 6000, 'daily_basic': 6000, 'fund_daily': 5000, 'stk_limit': 5800}
MAX_REPLAY_PAGES_PER_DATE = 100


@dataclass(frozen=True)
class DateReplayPlan:
    spider_class: type[DailySpider]
    trade_dates: tuple[str, ...]
    ts_code: str | None

    @property
    def page_size(self) -> int | None:
        if self.ts_code is not None:
            return None
        return PAGINATED_REPLAY_PAGE_SIZES.get(self.spider_class().get_api_name())

    def request_params(self) -> list[dict[str, str | int]]:
        date_field = self.spider_class.custom_settings.get('TRADE_DATE_FIELD', 'trade_date')
        paging = {'limit': self.page_size, 'offset': 0} if self.page_size is not None else {}
        return [
            {date_field: day.replace('-', '')} | ({'ts_code': self.ts_code} if self.ts_code is not None else {})
            | paging
            for day in self.trade_dates
        ]

    def describe(self) -> dict:
        spider = self.spider_class()
        return {
            'spider': spider.name,
            'api_name': spider.get_api_name(),
            'raw_table': spider.get_raw_table_name(),
            'latest_table': spider.get_latest_table_name(),
            'requests': self.request_params(),
        }


def build_date_replay_plan(spider_name: str, trade_dates: list[str], ts_code: str | None = None) -> DateReplayPlan:
    dates = set()
    for value in trade_dates:
        if re.fullmatch(r'\d{8}', value):
            value = f'{value[:4]}-{value[4:6]}-{value[6:]}'
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            raise ValueError('trade dates must use YYYY-MM-DD or YYYYMMDD')
        try:
            day = datetime.date.fromisoformat(value)
        except ValueError as error:
            raise ValueError(f'Invalid trade date: {value}') from error
        if day > datetime.datetime.now(ZoneInfo('Asia/Shanghai')).date():
            raise ValueError(f'Cannot replay a future trade date: {value}')
        dates.add(day.isoformat())
    if not dates:
        raise ValueError('Provide at least one --trade-date')

    loader = SpiderLoader.from_settings(Settings({'SPIDER_MODULES': ['tushare_integration.spiders']}))
    try:
        spider_class = loader.load(spider_name)
    except KeyError as error:
        raise ValueError(f'Unknown spider: {spider_name}; provide its exact name') from error
    if (
        not issubclass(spider_class, DailySpider)
        or spider_class.start_requests is not DailySpider.start_requests
        or spider_class.parse_response is not TushareSpider.parse_response
        or spider_class.parse is not TushareSpider.parse
    ):
        raise ValueError(f'{spider_name} does not use the standard daily request/response flow')

    spider = spider_class()
    if ts_code is not None:
        ts_code = ts_code.strip().upper()
        if not re.fullmatch(r'[A-Z0-9-]+\.[A-Z0-9]+', ts_code):
            raise ValueError('Invalid --ts-code; expected a code such as 688585.SH')
        if 'ts_code' not in {c['name'] for c in spider.schema['columns']}:
            raise ValueError(f'{spider_name} has no ts_code field')
        date_field = spider.get_trade_date_field()
        if set(spider.schema.get('primary_key', [])) != {'ts_code', date_field}:
            raise ValueError(f'{spider_name} does not have a single-row security/date replay policy')
    elif spider.get_api_name() not in PAGINATED_REPLAY_PAGE_SIZES | REPLAY_RESPONSE_ROW_LIMITS:
        raise ValueError(
            f'{spider_name} has no full-market replay completeness policy; '
            'use --ts-code for a single-row security/date endpoint'
        )
    return DateReplayPlan(spider_class, tuple(sorted(dates)), ts_code)


def make_date_replay_spider(plan: DateReplayPlan) -> type[DailySpider]:
    page_size = plan.page_size
    api_name = plan.spider_class().get_api_name()

    class DateReplaySpider(plan.spider_class):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.replay_pages = {}

        def start_requests(self):
            # Explicit dates bypass the high-watermark and already-ingested-date query.
            for params in plan.request_params():
                yield self.get_scrapy_request(params=params)

        def parse_response(self, response, **kwargs):
            payload = json.loads(response.text)
            source_data = payload.get('data') or {}
            if source_data.get('has_more') or payload.get('has_more'):
                # A flagged full page is expected when this endpoint is paged.
                # A flagged short page does not establish exhaustion and must
                # never be published as a complete date.
                if page_size is None or len(source_data.get('items') or []) != page_size:
                    raise RuntimeError('Replay response is truncated; no rows from this response were written')
            if (
                page_size is not None
                and response.meta['params'].get('offset', 0) > 0
                and payload.get('code') != 0
            ):
                raise RuntimeError('Replay continuation failed; date remains unwritten')
            item = super().parse_response(response, **kwargs)
            data = item['data']
            params = response.meta['params']
            if data.empty:
                if page_size is not None and params.get('offset', 0) > 0:
                    return item  # An empty continuation proves the last full page ended the date.
                raise RuntimeError('Replay returned no data; existing records were retained')
            if page_size is not None:
                if len(data) > page_size:
                    raise RuntimeError('Replay response exceeded the requested page limit; pagination may be ignored')
            elif plan.ts_code is None:
                row_limit = REPLAY_RESPONSE_ROW_LIMITS.get(api_name)
                if row_limit is None:
                    raise RuntimeError('Replay endpoint has no full-market completeness policy')
                if len(data) >= row_limit:
                    raise RuntimeError(
                        f'Replay response reached the {api_name} row limit ({row_limit}); '
                        'completeness cannot be established. No rows were written; use --ts-code.'
                    )
            required = {c['name'] for c in self.schema['columns']}
            missing = required - set(data.columns)
            if missing:
                raise RuntimeError(f'Replay response is missing fields: {sorted(missing)}')

            date_field = self.get_trade_date_field()
            requested = params[date_field]
            dates = pd.to_datetime(data[date_field], format='mixed', errors='coerce').dt.strftime('%Y%m%d')
            if not dates.eq(requested).all():
                raise RuntimeError('Replay response contains missing or unexpected trade dates')
            if 'ts_code' in data.columns:
                codes = data['ts_code']
                if codes.isna().any() or codes.astype(str).str.strip().eq('').any():
                    raise RuntimeError('Replay response contains missing ts_code values')
                if plan.ts_code is not None and not codes.eq(plan.ts_code).all():
                    raise RuntimeError('Replay response contains an unexpected ts_code')
            keys = self.schema.get('primary_key', [])
            if keys:
                business_keys = data[keys].copy()
                if date_field in keys:
                    business_keys[date_field] = dates
                if business_keys.duplicated().any():
                    raise RuntimeError('Replay response contains duplicate business keys')
            if 'adj_factor' in data.columns:
                factors = pd.to_numeric(data['adj_factor'], errors='coerce')
                if not factors.map(lambda value: math.isfinite(value) and value > 0).all():
                    raise RuntimeError('Replay response contains a missing, non-finite or non-positive adj_factor')
            return item

        def parse(self, response, **kwargs):
            item = self.parse_response(response, **kwargs)
            data = item['data']
            if page_size is None:
                self.crawler.stats.inc_value('replay/rows_received', len(data))
                return item

            params = response.meta['params']
            day = params[self.get_trade_date_field()]
            offset = params.get('offset', 0)
            state = self.replay_pages.setdefault(day, {'frames': [], 'keys': set(), 'offset': 0, 'pages': 0})
            if offset != state['offset'] or (offset == 0 and state['pages']):
                raise RuntimeError('Replay pagination returned an unexpected offset; date remains unwritten')
            if state['pages'] >= MAX_REPLAY_PAGES_PER_DATE:
                raise RuntimeError('Replay pagination exceeded its safety limit; date remains unwritten')
            state['pages'] += 1
            if not data.empty:
                business_keys = data[self.schema['primary_key']].copy()
                date_field = self.get_trade_date_field()
                business_keys[date_field] = pd.to_datetime(
                    business_keys[date_field], format='mixed'
                ).dt.strftime('%Y%m%d')
                keys = set(business_keys.itertuples(index=False, name=None))
                if state['keys'] & keys:
                    raise RuntimeError(
                        'Replay pagination repeated business keys; offset may be ignored. Date remains unwritten'
                    )
                state['keys'].update(keys)
                state['frames'].append(data)
                state['offset'] += len(data)
            if len(data) == page_size:
                return self.get_scrapy_request(params=params | {'offset': state['offset']})

            # Publish exactly one item only after the date's final short/empty
            # page. An HTTP/parse failure on any page leaves that date unwritten.
            item['data'] = pd.concat(state['frames'], ignore_index=True)
            del self.replay_pages[day]
            self.crawler.stats.inc_value('replay/rows_received', len(item['data']))
            return item

    return DateReplaySpider
