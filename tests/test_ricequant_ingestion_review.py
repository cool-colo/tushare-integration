from __future__ import annotations

import json
import queue
import threading
from datetime import date, datetime
from types import SimpleNamespace

import pandas as pd
import pytest

from ricequant_integration.quota import QuotaPaused
from ricequant_integration.realtime import Outbox, Subscription
from ricequant_integration.runner import RiceQuantRunner
from ricequant_integration.settings import DatabaseSettings, RiceQuantSettings
from ricequant_integration.state import CoverageState
from ricequant_integration.specs import DATASET_SPECS
from ricequant_integration.storage import PublishResult
from tests.test_ricequant_realtime import bar


class OptionState:
    def __init__(self):
        self.events = []

    def latest(self, dataset, key):
        return next((event for event in reversed(self.events)
                     if event.dataset == dataset and event.slice_key == key), None)

    def coverage_event(self, spec, key, status, **values):
        self.events.append(CoverageState(
            spec.name, key, status, values['cursor'], values.get('row_count', 0),
            values.get('content_hash', ''), datetime.now(),
        ))

    def completed_slice_ranges(self, dataset):
        latest = {event.slice_key: event for event in self.events if event.dataset == dataset}
        return {key: (date.fromisoformat(event.cursor['range_start']),
                      date.fromisoformat(event.cursor['range_end']))
                for key, event in latest.items() if event.status == 'complete'}

    def latest_completed_end(self, dataset, _prefix):
        return max((end for _, end in self.completed_slice_ranges(dataset).values()), default=None)


class OptionStorage:
    def __init__(self):
        self.stages, self.published, self.discarded = {}, {}, []

    def prepare_daily_stage(self, spec, day):
        key = (spec.name, day)
        existed = key in self.stages
        self.stages.setdefault(key, {})
        return key, existed

    def discard_daily_stage(self, spec, day):
        key = (spec.name, day)
        self.discarded.append(key)
        self.stages.pop(key, None)

    def replace_daily_stage_batch(self, spec, stage, ids, frame):
        rows = self.stages[stage]
        for identifier in ids:
            rows.pop(identifier, None)
        for record in frame.to_dict('records'):
            assert record['trading_date'] == stage[1]
            rows[record['order_book_id']] = record

    def publish_daily_stage(self, spec, stage, day):
        rows = self.stages.pop(stage)
        assert set(rows) == {'A', 'B', 'C'}
        self.published[(spec.name, day)] = rows
        return PublishResult(len(rows), 'hash')


def option_runner(dataset):
    state, storage, calls, budget = OptionState(), OptionStorage(), [], [0]
    calendar = [date(2026, 11, day) for day in (9, 10, 11, 12, 13, 16)]

    def download(ids, start, end):
        calls.append((tuple(ids), start, end))
        days = [day for day in calendar if start <= day <= end]
        index = pd.MultiIndex.from_product([ids, pd.to_datetime(days)],
                                          names=['order_book_id', 'trading_date'])
        return pd.DataFrame({'open': [1.0] * len(index),
                             'symbol': ['option'] * len(index)}, index=index)

    client = SimpleNamespace(option_daily=download, option_contract_property=download)
    runner = RiceQuantRunner(
        RiceQuantSettings(DatabaseSettings(host='localhost'), '', option_batch_size=1),
        client=client, storage=storage, today=calendar[-1],
    )
    runner.state = state
    runner._option_month_universe = lambda *_args, **_kwargs: ['A', 'B', 'C']

    def fetch(_dataset, _label, call):
        if not budget[0]:
            raise QuotaPaused('daily quota exhausted')
        budget[0] -= 1
        return call(), 1

    runner._fetch = fetch
    return runner, storage, state, calls, budget, calendar


@pytest.mark.parametrize('dataset', ['option_daily', 'option_contract_property'])
def test_option_quota_resume_finishes_frozen_interval_before_growing_dates(dataset):
    runner, storage, state, calls, budget, days = option_runner(dataset)
    for count, quota in [(2, 1), (3, 1), (4, 1), (5, 2)]:
        budget[0] = quota
        with pytest.raises(QuotaPaused):
            runner._sync_option_series(dataset, 'incremental', days[:count], None, None)
        if count == 2:
            discarded = list(storage.discarded)
        if count == 3:
            assert storage.discarded == discarded
            assert not storage.published
        if count == 4:
            assert set(day for _, day in storage.published) == set(days[:2])
    budget[0] = 10
    runner._sync_option_series(dataset, 'incremental', days, None, None)
    assert calls == [
        ((identifier,), days[0], days[1]) for identifier in 'ABC'
    ] + [
        ((identifier,), days[2], days[3]) for identifier in 'ABC'
    ] + [
        ((identifier,), days[4], days[5]) for identifier in 'ABC'
    ]
    assert set(day for _, day in storage.published) == set(days)
    assert not storage.stages
    assert state.latest(dataset, '2026-11').status == 'complete'


@pytest.mark.parametrize('dataset', ['option_daily', 'option_contract_property'])
def test_option_resume_restarts_frozen_interval_when_a_daily_stage_is_missing(dataset):
    runner, storage, _state, calls, budget, days = option_runner(dataset)
    budget[0] = 1
    with pytest.raises(QuotaPaused):
        runner._sync_option_series(dataset, 'incremental', days[:2], None, None)
    del storage.stages[(dataset, days[0])]
    budget[0] = 10
    runner._sync_option_series(dataset, 'incremental', days[:3], None, None)
    assert calls[:4] == [((identifier,), days[0], days[1]) for identifier in 'AABC']
    assert set(day for _, day in storage.published) == set(days[:3])


def test_option_resume_preserves_cursor_when_partial_status_moves_incremental_start_backwards():
    runner, _storage, state, calls, budget, days = option_runner('option_daily')
    days.extend([date(2026, 11, day) for day in (17, 18, 19)])
    state.coverage_event(DATASET_SPECS['option_daily'], '2026-11', 'complete', cursor={
        'range_start': str(days[0]), 'range_end': '2026-11-17',
    })
    budget[0] = 1
    with pytest.raises(QuotaPaused):
        runner._sync_option_series('option_daily', 'incremental', days[:-1], None, None)
    assert calls == [(('A',), date(2026, 11, 11), date(2026, 11, 18))]
    budget[0] = 10
    runner._sync_option_series('option_daily', 'incremental', days, None, None)
    assert calls[:3] == [((identifier,), date(2026, 11, 11), date(2026, 11, 18))
                         for identifier in 'ABC']
    assert calls[3:] == [((identifier,), days[-1], days[-1]) for identifier in 'ABC']


def test_supervisor_warns_when_current_connection_confirms_only_a_subset(tmp_path, monkeypatch, caplog):
    import ricequant_integration.realtime as module

    stop, clock = threading.Event(), [0]

    class Storage:
        def __init__(self, *_args, **_kwargs):
            pass
        def initialize(self):
            pass
        def insert(self, events, **_kwargs):
            if clock[0] > 140:
                stop.set()
        def retain_partitions(self, _keep):
            return None
        def close(self):
            pass

    class Source:
        def __init__(self, _token):
            self.rq = SimpleNamespace()
        def initialize(self):
            pass

    class Session:
        def __init__(self, *_args, **_kwargs):
            self.ready = threading.Event()
            self.error, self.rejected = None, 0
        @property
        def confirmed_count(self):
            # Initially fully acknowledged; after internal reconnect only one.
            return 2 if clock[0] < 70 else 1
        def start(self):
            self.ready.set()
        def close(self):
            pass

    class FastQueue(queue.Queue):
        def get(self, block=True, timeout=None):
            return super().get(block=False)

    def monotonic():
        clock[0] += 10
        return clock[0]

    monkeypatch.setattr(module, 'RealtimeStorage', Storage)
    monkeypatch.setattr(module, 'RqDataClient', Source)
    monkeypatch.setattr(module, 'Subscription', Session)
    monkeypatch.setattr(module, 'stock_universe', lambda *_args: {'000001.XSHE', '600000.XSHG'})
    monkeypatch.setattr(module.queue, 'Queue', FastQueue)
    monkeypatch.setattr(module.time, 'monotonic', monotonic)
    settings = RiceQuantSettings(DatabaseSettings(host='localhost'), 'test-token')
    args = module.build_parser().parse_args(['--state-dir', str(tmp_path), '--flush-seconds', '1'])
    module.run(settings, args, stop)
    assert 'Server has confirmed 1/2 subscriptions' in caplog.text


@pytest.mark.parametrize('fail_after_first_batch', [False, True])
def test_refresh_accepts_bars_while_subscribe_is_in_progress(tmp_path, fail_after_first_batch):
    delivered, consumed, stop = threading.Event(), threading.Event(), threading.Event()
    incoming, messages = queue.Queue(), queue.Queue()
    new_stocks = {'301999.XSHE', '600000.XSHG'}

    class Client:
        info = {}

        def __init__(self):
            self.fail_once = fail_after_first_batch

        def subscribe(self, channels):
            if channels == ['bar_301999.XSHE']:
                incoming.put(bar(order_book_id='301999.XSHE', channel=channels[0]).payload)
                assert consumed.wait(2), 'reader did not process the concurrent feed'
                if self.fail_once:
                    self.fail_once = False
                    raise ConnectionError('second subscription batch not sent')

        def unsubscribe(self, channels):
            pass

        def listen(self):
            while not stop.is_set():
                try:
                    message = incoming.get(timeout=0.05)
                except queue.Empty:
                    continue
                yield message
                delivered.set()
                consumed.set()

        def close(self):
            stop.set()

    subscription = Subscription(SimpleNamespace(LiveMarketDataClient=Client),
                                {'000001.XSHE'}, messages, 1)
    subscription.start()
    assert subscription.ready.wait(2)
    try:
        if fail_after_first_batch:
            with pytest.raises(ConnectionError):
                subscription.refresh(new_stocks)
        else:
            subscription.refresh(new_stocks)
        assert delivered.wait(2)
        event = messages.get(timeout=1)
        assert event.payload['order_book_id'] == '301999.XSHE'
        outbox = Outbox(tmp_path / 'spool.sqlite3', 'db/table', 10)
        try:
            outbox.append([event])
            assert outbox.peek(1) == [event]
        finally:
            outbox.close()
        if fail_after_first_batch:
            # Retry must still send the additions which may only partially exist.
            subscription.refresh(new_stocks)
        assert subscription.order_book_ids == new_stocks
        assert subscription.rejected == 0
    finally:
        subscription.close()


def test_sdk_internal_reconnect_counts_only_current_connection_acknowledgments(monkeypatch):
    import rqdatac
    import rqdatac.services.live_md_client as sdk
    import websockets.sync.client
    from websockets.exceptions import ConnectionClosedError

    stocks = {'000001.XSHE', '600000.XSHG'}
    channels = {f'bar_{stock}' for stock in stocks}
    feed = bar().payload

    class Socket:
        def __init__(self, replies):
            self.replies = iter([{'action': 'auth_reply', 'success': True}, *replies])

        def send(self, payload):
            pass

        def recv(self, **kwargs):
            reply = next(self.replies)
            if isinstance(reply, Exception):
                raise reply
            return json.dumps(reply).encode()

        def close(self):
            pass

    sockets = iter([
        Socket([{'action': 'subscribe_reply', 'subscribed': sorted(channels)}, feed,
                ConnectionClosedError(None, None)]),
        Socket([{'action': 'subscribe_reply', 'subscribed': ['bar_000001.XSHE']}, feed]),
    ])
    monkeypatch.setattr(sdk, 'get_client', lambda: SimpleNamespace(execute=lambda _: 'test-token'))
    monkeypatch.setattr(sdk, 'instruments', lambda _: True)
    monkeypatch.setattr(websockets.sync.client, 'connect', lambda *_args, **_kwargs: next(sockets))
    monkeypatch.setattr(sdk.time, 'sleep', lambda _: None)
    advance = threading.Event()
    listen = sdk.LiveMarketDataClient.listen

    def gated_listen(client):
        for index, message in enumerate(listen(client)):
            yield message
            if index == 0:
                assert advance.wait(2)
            else:
                subscription.closed.wait(2)

    monkeypatch.setattr(sdk.LiveMarketDataClient, 'listen', gated_listen)
    messages = queue.Queue()
    subscription = Subscription(rqdatac, stocks, messages, 200)
    subscription.start()
    try:
        assert messages.get(timeout=2).payload == feed
        assert subscription.confirmed_count == 2
        advance.set()
        assert messages.get(timeout=2).payload == feed
        assert subscription.confirmed_count == 1
        assert subscription.error is None
    finally:
        advance.set()
        subscription.close()
