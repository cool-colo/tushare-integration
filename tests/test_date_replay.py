import datetime
import json
from types import SimpleNamespace
from unittest import mock

import pytest
import scrapy
from scrapy.http import TextResponse
from scrapy.settings import Settings
from typer.testing import CliRunner

from tushare_integration import commands
from tushare_integration.manager import CrawlManager
from tushare_integration.pipelines import (
    TransformDTypePipeline,
    TushareIntegrationDataPipeline,
    TushareIntegrationFillNAPipeline,
)
from tushare_integration.replay import (
    PAGINATED_REPLAY_PAGE_SIZES,
    REPLAY_RESPONSE_ROW_LIMITS,
    build_date_replay_plan,
    make_date_replay_spider,
)


def replay_spider(ts_code=None, days=None, spider_name='stock/quotes/adj_factor'):
    plan = build_date_replay_plan(spider_name, days or ['2026-10-26'], ts_code)
    spider = make_date_replay_spider(plan)()
    spider.spider_settings = SimpleNamespace(tushare_url='https://example.test', tushare_token='test-token')
    spider.crawler = SimpleNamespace(stats=mock.Mock())
    return plan, spider


def response(rows, params=None, fields=None, **extra_data):
    request = scrapy.Request('https://example.test', meta={'params': params or {'trade_date': '20261026'}})
    payload = {
        'code': 0,
        'data': {'fields': fields or ['ts_code', 'trade_date', 'adj_factor'], 'items': rows} | extra_data,
    }
    return TextResponse(request.url, request=request, body=json.dumps(payload).encode(), encoding='utf-8')


def test_dry_run_normalizes_deduplicates_dates_without_starting_a_crawl():
    with mock.patch.object(commands, 'CrawlManager') as manager:
        result = CliRunner().invoke(commands.crawl_app, [
            'replay', 'stock/quotes/adj_factor', '--trade-date', '20261026',
            '--trade-date', '2026-10-23', '--trade-date', '2026-10-26', '--dry-run',
        ])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        'spider': 'stock/quotes/adj_factor', 'api_name': 'adj_factor',
        'raw_table': 'adj_factor_raw', 'latest_table': 'adj_factor',
        'requests': [
            {'trade_date': '20261023', 'limit': 1000, 'offset': 0},
            {'trade_date': '20261026', 'limit': 1000, 'offset': 0},
        ], 'dry_run': True,
    }
    manager.assert_not_called()


def test_cli_passes_single_security_to_the_replay_manager():
    with mock.patch.object(commands, 'CrawlManager') as manager:
        manager.return_value.run_date_replay.return_value = {'completed_dates': 1}
        result = CliRunner().invoke(commands.crawl_app, [
            'replay', 'stock/quotes/adj_factor', '--trade-date', '20261026', '--ts-code', '688585.sh',
        ])
    assert result.exit_code == 0, result.output
    plan = manager.return_value.run_date_replay.call_args.args[0]
    assert plan.request_params() == [{'trade_date': '20261026', 'ts_code': '688585.SH'}]


@pytest.mark.parametrize('arguments', [
    ['stock/quotes/adj_factor', '--trade-date', '2026-02-30'],
    ['stock/quotes/adj_factor', '--trade-date', '2026-1-2'],
    ['stock/quotes/adj_factor', '--trade-date', '2099-01-01'],
    ['stock/quotes/adj_factor', '--trade-date', '20261026', '--ts-code', ''],
    ['stock/quotes/adj_factor', '--trade-date', '20261026', '--ts-code', 'bad code'],
    ['stock/quotes/adj_.*', '--trade-date', '20261026'],
    ['stock/basic/stock_basic', '--trade-date', '20261026'],
    ['index/quotes/index_daily', '--trade-date', '20261026'],
    ['stock/quotes/adj_factor'],
])
def test_invalid_replays_fail_before_creating_a_manager(arguments):
    with mock.patch.object(commands, 'CrawlManager') as manager:
        result = CliRunner().invoke(commands.crawl_app, ['replay', *arguments])
    assert result.exit_code == 2, result.output
    manager.assert_not_called()


def test_explicit_historical_dates_bypass_existing_data_and_calendar_queries():
    _, spider = replay_spider(days=['2024-06-25', '2026-10-26'])
    with mock.patch.object(spider, 'get_db_engine', side_effect=AssertionError('Must not query date coverage')):
        requests = list(spider.start_requests())
    assert [json.loads(r.body)['params'] for r in requests] == [
        {'trade_date': '20240625', 'limit': 1000, 'offset': 0},
        {'trade_date': '20261026', 'limit': 1000, 'offset': 0},
    ]
    assert all(r.meta['api_name'] == 'adj_factor' for r in requests)


def test_replay_requests_can_limit_to_one_security():
    _, spider = replay_spider('688585.SH')
    request = next(spider.start_requests())
    assert json.loads(request.body)['params'] == {'trade_date': '20261026', 'ts_code': '688585.SH'}


@pytest.mark.parametrize('rows,options,message', [
    ([], {}, 'no data'),
    ([['688585.SH', '20261026', 1.0243]], {'has_more': True}, 'truncated'),
    ([['688585.SH', '20261027', 1.0243]], {}, 'trade dates'),
    ([['688585.SH', None, 1.0243]], {}, 'trade dates'),
    ([['688585.SH', 'invalid', 1.0243]], {}, 'trade dates'),
    ([['688585.SH', '20261026']], {'fields': ['ts_code', 'trade_date']}, 'missing fields'),
    ([[None, '20261026', 1.0243]], {}, 'missing ts_code'),
    ([[' ', '20261026', 1.0243]], {}, 'missing ts_code'),
    ([['688585.SH', '20261026', 1.0243]] * 2, {}, 'duplicate'),
    ([['688585.SH', '20261026', 1.0243], ['688585.SH', '2026-10-26', 1.0243]], {}, 'duplicate'),
    ([['688585.SH', '20261026', None]], {}, 'adj_factor'),
    ([['688585.SH', '20261026', 0]], {}, 'adj_factor'),
    ([['688585.SH', '20261026', -1]], {}, 'adj_factor'),
    ([['688585.SH', '20261026', 'NaN']], {}, 'adj_factor'),
    ([['688585.SH', '20261026', 'Infinity']], {}, 'adj_factor'),
])
def test_bad_responses_are_rejected_before_any_pipeline_writes(rows, options, message):
    _, spider = replay_spider()
    with pytest.raises(RuntimeError, match=message):
        spider.parse_response(response(rows, **options))
    spider.crawler.stats.inc_value.assert_not_called()


def test_single_security_replay_rejects_a_different_security():
    _, spider = replay_spider('688585.SH')
    with pytest.raises(RuntimeError, match='unexpected ts_code'):
        spider.parse_response(response([['300584.SZ', '20261026', 1.5825]],
                                      params={'trade_date': '20261026', 'ts_code': '688585.SH'}))


def schema_response(spider, count, *, start=0, params=None):
    fields = [column['name'] for column in spider.schema['columns']]
    rows = [
        [f'{index:06d}.SH' if field == 'ts_code' else '20261026' if field == 'trade_date' else 1
         for field in fields]
        for index in range(start, start + count)
    ]
    return response(rows, fields=fields, params=params)


@pytest.mark.parametrize('spider_name,api_name', [
    ('stock/quotes/daily', 'daily'),
    ('stock/quotes/daily_basic', 'daily_basic'),
    ('fund/quotes/fund_daily', 'fund_daily'),
    ('stock/quotes/stk_limit', 'stk_limit'),
])
def test_full_market_response_at_documented_limit_is_rejected_without_has_more(spider_name, api_name):
    _, spider = replay_spider(spider_name=spider_name)
    capped = schema_response(spider, REPLAY_RESPONSE_ROW_LIMITS[api_name])
    assert 'has_more' not in json.loads(capped.text)['data']
    with pytest.raises(RuntimeError, match=f'{api_name} row limit'):
        spider.parse(capped)
    spider.crawler.stats.inc_value.assert_not_called()


def test_uncapped_endpoint_accepts_below_limit_but_rejects_above_limit(monkeypatch):
    monkeypatch.setitem(REPLAY_RESPONSE_ROW_LIMITS, 'daily', 3)
    _, spider = replay_spider(spider_name='stock/quotes/daily')
    assert len(spider.parse(schema_response(spider, 2))['data']) == 2
    with pytest.raises(RuntimeError, match='row limit'):
        spider.parse(schema_response(spider, 4))


def test_unknown_full_market_policy_fails_before_starting_a_crawl():
    with mock.patch.object(commands, 'CrawlManager') as manager:
        result = CliRunner().invoke(commands.crawl_app, [
            'replay', 'stock/special/cyq_perf', '--trade-date', '20261026',
        ])
    assert result.exit_code == 2
    assert 'completeness' in result.output
    manager.assert_not_called()
    with pytest.raises(ValueError, match='no full-market replay completeness policy'):
        build_date_replay_plan('stock/special/cyq_perf', ['20261026'])


def test_unknown_row_limit_can_still_replay_exactly_one_security_date():
    plan, spider = replay_spider('688585.SH', spider_name='stock/special/cyq_perf')
    assert plan.page_size is None
    assert plan.request_params() == [{'trade_date': '20261026', 'ts_code': '688585.SH'}]
    rows = [[
        '688585.SH' if c['name'] == 'ts_code' else '20261026' if c['name'] == 'trade_date' else 1
        for c in spider.schema['columns']
    ]]
    item = spider.parse(response(rows, fields=[c['name'] for c in spider.schema['columns']],
                                 params=plan.request_params()[0]))
    assert len(item['data']) == 1


@pytest.mark.parametrize('api_name,spider_name', [
    ('adj_factor', 'stock/quotes/adj_factor'),
    ('fund_adj', 'fund/quotes/fund_adj'),
    ('stk_factor', 'stock/special/stk_factor'),
])
def test_full_pages_without_has_more_are_buffered_until_a_terminal_empty_page(monkeypatch, api_name, spider_name):
    monkeypatch.setitem(PAGINATED_REPLAY_PAGE_SIZES, api_name, 2)
    plan, spider = replay_spider(spider_name=spider_name)
    params = plan.request_params()[0]
    assert params == {'trade_date': '20261026', 'limit': 2, 'offset': 0}
    next_page = spider.parse(schema_response(spider, 2, params=params))
    assert isinstance(next_page, scrapy.Request)
    assert next_page.meta['params']['offset'] == 2
    spider.crawler.stats.inc_value.assert_not_called()
    next_page = spider.parse(schema_response(spider, 2, start=2, params=next_page.meta['params']))
    assert isinstance(next_page, scrapy.Request)
    assert next_page.meta['params']['offset'] == 4
    spider.crawler.stats.inc_value.assert_not_called()
    completed = spider.parse(schema_response(spider, 0, params=next_page.meta['params']))
    assert completed['data']['ts_code'].tolist() == [f'{i:06d}.SH' for i in range(4)]
    spider.crawler.stats.inc_value.assert_called_once_with('replay/rows_received', 4)
    assert not spider.replay_pages


def test_short_continuation_completes_all_rows_in_one_pipeline_item(monkeypatch):
    monkeypatch.setitem(PAGINATED_REPLAY_PAGE_SIZES, 'adj_factor', 2)
    plan, spider = replay_spider()
    next_page = spider.parse(schema_response(spider, 2, params=plan.request_params()[0]))
    completed = spider.parse(schema_response(spider, 1, start=2, params=next_page.meta['params']))
    assert len(completed['data']) == 3
    spider.crawler.stats.inc_value.assert_called_once_with('replay/rows_received', 3)


def test_flagged_full_page_is_continued_but_flagged_short_page_cannot_complete_date(monkeypatch):
    monkeypatch.setitem(PAGINATED_REPLAY_PAGE_SIZES, 'adj_factor', 2)
    plan, spider = replay_spider()
    next_page = spider.parse(response(
        [['000000.SH', '20261026', 1], ['000001.SH', '20261026', 1]],
        params=plan.request_params()[0], has_more=True,
    ))
    assert isinstance(next_page, scrapy.Request)
    with pytest.raises(RuntimeError, match='truncated'):
        spider.parse(response([['000002.SH', '20261026', 1]], params=next_page.meta['params'], has_more=True))
    spider.crawler.stats.inc_value.assert_not_called()


def test_repeated_offset_or_overlapping_page_never_publishes_a_partial_date(monkeypatch):
    monkeypatch.setitem(PAGINATED_REPLAY_PAGE_SIZES, 'adj_factor', 2)
    plan, spider = replay_spider()
    next_page = spider.parse(schema_response(spider, 2, params=plan.request_params()[0]))
    # A repeated first page also uses a different date representation; keys
    # must be compared after date normalization, not as raw strings.
    repeated = response([['000000.SH', '2026-10-26', 1], ['000001.SH', '2026-10-26', 1]],
                        params=next_page.meta['params'])
    with pytest.raises(RuntimeError, match='repeated business keys'):
        spider.parse(repeated)
    spider.crawler.stats.inc_value.assert_not_called()


def test_ignored_page_limit_is_rejected_before_writing(monkeypatch):
    monkeypatch.setitem(PAGINATED_REPLAY_PAGE_SIZES, 'adj_factor', 2)
    plan, spider = replay_spider()
    with pytest.raises(RuntimeError, match='exceeded the requested page limit'):
        spider.parse(schema_response(spider, 3, params=plan.request_params()[0]))
    spider.crawler.stats.inc_value.assert_not_called()


def test_unexpected_pagination_offset_is_rejected_without_completing_the_date(monkeypatch):
    monkeypatch.setitem(PAGINATED_REPLAY_PAGE_SIZES, 'adj_factor', 2)
    plan, spider = replay_spider()
    next_page = spider.parse(schema_response(spider, 2, params=plan.request_params()[0]))
    with pytest.raises(RuntimeError, match='unexpected offset'):
        spider.parse(schema_response(spider, 1, start=2, params=next_page.meta['params'] | {'offset': 3}))
    spider.crawler.stats.inc_value.assert_not_called()


def test_exceeding_page_safety_limit_leaves_date_unwritten(monkeypatch):
    monkeypatch.setitem(PAGINATED_REPLAY_PAGE_SIZES, 'adj_factor', 2)
    monkeypatch.setattr('tushare_integration.replay.MAX_REPLAY_PAGES_PER_DATE', 1)
    plan, spider = replay_spider()
    next_page = spider.parse(schema_response(spider, 2, params=plan.request_params()[0]))
    with pytest.raises(RuntimeError, match='safety limit'):
        spider.parse(schema_response(spider, 1, start=2, params=next_page.meta['params']))
    spider.crawler.stats.inc_value.assert_not_called()


def test_failed_continuation_cannot_be_mistaken_for_a_successful_empty_final_page(monkeypatch):
    monkeypatch.setitem(PAGINATED_REPLAY_PAGE_SIZES, 'adj_factor', 2)
    plan, spider = replay_spider()
    next_page = spider.parse(schema_response(spider, 2, params=plan.request_params()[0]))
    failed = TextResponse(next_page.url, request=next_page, encoding='utf-8',
                          body=json.dumps({'code': -1, 'msg': '查询数据失败，请确认参数', 'data': None}).encode())
    with pytest.raises(RuntimeError, match='continuation failed'):
        spider.parse(failed)
    spider.crawler.stats.inc_value.assert_not_called()


def test_dates_can_be_paginated_independently_when_responses_interleave(monkeypatch):
    monkeypatch.setitem(PAGINATED_REPLAY_PAGE_SIZES, 'adj_factor', 2)
    plan, spider = replay_spider(days=['2026-10-23', '2026-10-26'])
    first, second = plan.request_params()
    first_response = response([['000000.SH', '20261023', 1], ['000001.SH', '20261023', 1]], params=first)
    continuation = spider.parse(first_response)
    second_complete = spider.parse(schema_response(spider, 1, params=second))
    assert len(second_complete['data']) == 1
    first_complete = spider.parse(response([], params=continuation.meta['params']))
    assert first_complete['data']['trade_date'].tolist() == ['20261023', '20261023']
    assert not spider.replay_pages


def test_valid_source_revision_appends_raw_and_upserts_latest_through_existing_pipelines():
    _, spider = replay_spider()
    spider.settings = Settings({'BATCH_ID': 'new-replay-batch'})
    item = spider.parse(response([['688585.SH', '20261026', 1.0243]]))
    settings = SimpleNamespace(batch_id='new-replay-batch')
    for pipeline_class in [TushareIntegrationFillNAPipeline, TransformDTypePipeline]:
        pipeline = pipeline_class(settings)
        pipeline.open_spider(spider)
        item = pipeline.process_item(item, spider)

    db = mock.Mock()
    with mock.patch('tushare_integration.pipelines.DatabaseEngineFactory.create', return_value=db):
        writer = TushareIntegrationDataPipeline(settings)
    writer.open_spider(spider)
    writer.process_item(item, spider)

    db.insert.assert_called_once()
    db.upsert.assert_called_once()
    raw = db.insert.call_args.kwargs['data'].iloc[0]
    latest = db.upsert.call_args.kwargs['data'].iloc[0]
    assert db.insert.call_args.args[0] == 'adj_factor_raw'
    assert db.upsert.call_args.args[0] == 'adj_factor'
    assert raw['adj_factor'] == latest['adj_factor'] == 1.0243
    assert raw['trade_date'] == datetime.date(2026, 10, 26)
    assert raw['_batch_id'] == 'new-replay-batch'
    assert raw['_ingest_time'].date() == datetime.datetime.now(datetime.timezone.utc).date()
    assert raw['_ingest_time'].utcoffset() == datetime.timedelta(0)
    assert json.loads(raw['_raw_json'])['adj_factor'] == 1.0243
    assert raw['_record_hash'] == latest['_record_hash']
    assert all(call[0] in {'insert', 'upsert'} for call in db.method_calls)


def test_ingest_timestamp_keeps_the_actual_instant_on_a_beijing_time_host():
    from zoneinfo import ZoneInfo

    class FrozenDatetime(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            instant = cls(2026, 11, 26, 12, 40, 42, 544000, tzinfo=datetime.timezone.utc)
            if tz is None:
                return instant.astimezone(ZoneInfo('Asia/Shanghai')).replace(tzinfo=None)
            return instant.astimezone(tz)

    _, spider = replay_spider()
    spider.settings = Settings({'BATCH_ID': 'utc-replay-batch'})
    item = spider.parse(response([['688585.SH', '20261026', 1.0239]]))
    settings = SimpleNamespace(batch_id='utc-replay-batch')
    for pipeline_class in [TushareIntegrationFillNAPipeline, TransformDTypePipeline]:
        pipeline = pipeline_class(settings)
        pipeline.open_spider(spider)
        item = pipeline.process_item(item, spider)
    db = mock.Mock()
    with mock.patch('tushare_integration.pipelines.DatabaseEngineFactory.create', return_value=db):
        writer = TushareIntegrationDataPipeline(settings)
    writer.open_spider(spider)
    with mock.patch('tushare_integration.pipelines.datetime.datetime', FrozenDatetime):
        writer.process_item(item, spider)

    raw = db.insert.call_args.kwargs['data'].iloc[0]
    latest = db.upsert.call_args.kwargs['data'].iloc[0]
    expected = datetime.datetime(2026, 11, 26, 12, 40, 42, 544000, tzinfo=datetime.timezone.utc)
    assert raw['_ingest_time'] == latest['_ingest_time'] == expected
    assert raw['_ingest_time'].timestamp() == expected.timestamp()


def replay_manager(completed):
    manager = object.__new__(CrawlManager)
    manager.process = mock.Mock()
    manager.batch_id = 'replay-batch'
    manager.signals = []
    manager.critical_errors = []
    manager.process.create_crawler.return_value.stats.get_stats.return_value = {
        'item_scraped_count': completed, 'replay/rows_received': completed * 5580,
    }
    return manager


def test_manager_replays_only_the_target_and_returns_write_counts():
    plan, _ = replay_spider(days=['2026-10-23', '2026-10-26'])
    manager = replay_manager(2)
    with mock.patch.object(manager, 'get_all_spiders', side_effect=AssertionError('No dependencies')):
        result = manager.run_date_replay(plan)
    manager.process.start.assert_called_once()
    assert result['completed_dates'] == 2
    assert result['rows_received'] == 11160
    assert result['batch_id'] == 'replay-batch'


@pytest.mark.parametrize('completed', [0, 1])
def test_manager_fails_if_http_or_pipeline_errors_leave_a_date_unwritten(completed):
    plan, _ = replay_spider(days=['2026-10-23', '2026-10-26'])
    manager = replay_manager(completed)
    with pytest.raises(RuntimeError, match='Replay incomplete'):
        manager.run_date_replay(plan)
