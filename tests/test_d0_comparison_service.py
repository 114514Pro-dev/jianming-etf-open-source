"""Comparison contracts over synthetic ledgers and injected, offline data only."""
from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
import json
import math
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from realtime_paper_comparison import D0ComparisonService, _bounded_request
from market_index_benchmark import INDEX_NAMES, SCHEMA
from test_d0_comparison_history import DAYS, NOW, START, bars, capital, event, fill, fixture
from realtime_paper_rationale import SYMBOLS


def close_at(day):
    return day + 'T15:00:00+08:00'


def indexed(snapshot):
    return {item['id']: item for item in snapshot['series']}


class Cache:
    def __init__(self, symbol, days=DAYS):
        self.calls = 0
        self.data = dict(schema=SCHEMA, symbol=symbol, name=INDEX_NAMES[symbol],
                         price_basis='index_price', sessions=list(days),
                         confirmed_through=days[-1], source='synthetic audited index',
                         bars=[dict(date=day, open=100 + i, close=100 + i,
                                    high=100 + i, low=100 + i)
                               for i, day in enumerate(days)])

    def read(self):
        self.calls += 1
        return deepcopy(self.data)


class Paper:
    def __init__(self, raw, prices=None, days=DAYS):
        self.raw = raw
        self._lock = threading.RLock()
        self.ledger = SimpleNamespace(snapshot=self.snapshot)
        self.source = SimpleNamespace(
            _market=SimpleNamespace(dates=list(days), look=bars() if prices is None else prices,
                                    latest=days[-1], hash='synthetic-market-hash'),
            _signal={'confirmed_day': days[-1], 'history_hash': 'synthetic-market-hash'},
            _signal_key=(days[-1], 'synthetic-market-hash'),
            read=Mock(side_effect=AssertionError('comparison must not refresh the trading source')))
        self._source_state = {'source_status': 'ready'}
        self._last_batch = None
        self.writes = 0
        self.start = Mock(side_effect=AssertionError('comparison must not start trading'))
        self.tick = Mock(side_effect=AssertionError('comparison must not tick trading'))

    def snapshot(self):
        return deepcopy(self.raw)


class D0ComparisonServiceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.raw = fixture()
        self.paper = Paper(self.raw)
        self.indices = SimpleNamespace(caches={s: Cache(s) for s in INDEX_NAMES})
        self.model_calls = []
        self.quote_calls = []
        self.clock = NOW

    def model(self, market, anchor, end, amount, *, directory=None, stop=None):
        self.assertFalse(self.paper._lock._is_owned(), 'model ran under the trading lock')
        self.model_calls.append((anchor, end, str(amount)))
        points = [dict(date=day, at=close_at(day),
                       equity=format(Decimal(str(amount)) * (Decimal(1) + Decimal(i) / 100), '.2f'),
                       break_before=i == 0)
                  for i, day in enumerate(d for d in market.dates if anchor <= d <= end)]
        return dict(status='available', reason=None, points=points,
                    state={'private_model_secret': 'must-never-reach-client'},
                    fees={'commission': .0003, 'minimum_commission': 5, 'slippage': .0002},
                    source_cutoff=end, method='native_d0_bank_ma50_k50_next_open')

    def quote(self, symbol, *, request=None, now=None):
        self.assertFalse(self.paper._lock._is_owned(), 'network ran under the trading lock')
        self.quote_calls.append(symbol)
        return dict(symbol=symbol, name=INDEX_NAMES[symbol], price=110, previous_close=103,
                    open=103, quote_at=self.clock.isoformat(), received_at=self.clock.isoformat(),
                    source='synthetic actual index', instrument_type='ZS')

    def service(self, **kwargs):
        options = dict(now=lambda: self.clock, refresh_enabled=False,
                       model_runner=self.model, quote_fetcher=self.quote,
                       live_model_runner=lambda *a, **k: dict(status='unavailable', reason='test_no_live'))
        options.update(kwargs)
        result = D0ComparisonService(self.folder.name, self.paper, self.indices, **options)
        self.addCleanup(result.close)
        return result

    def history(self, **kwargs):
        return self.service(**kwargs).refresh(fetch_live=False)

    def test_pre_upgrade_d0_reference_is_not_published_or_cached(self):
        def old_model(*args, **kwargs):
            result = self.model(*args, **kwargs)
            result['method'] = 'native_d0_next_open'
            return result
        service = self.service(model_runner=old_model)
        result = service.refresh(fetch_live=False)
        line = indexed(result)['d0']
        self.assertNotEqual(line['status'], 'available')
        self.assertEqual(line['points'], [])
        self.assertFalse(service._models)

    def test_four_lines_share_first_confirmed_close_and_first_start(self):
        fill(self.raw)
        self.paper.source._market.look[SYMBOLS[0]][DAYS[1]]['close'] = 11
        result = self.history()
        self.assertEqual((result['contract_version'], result['status']),
                         ('d0-performance-comparison-v1', 'available'))
        self.assertEqual(result['normalization'], 'first_shared_confirmed_close')
        self.assertEqual(result['requested_start_at'], START)
        self.assertEqual(result['account_created_at'], self.raw['account']['created_at'])
        self.assertEqual(result['segments'][0]['baseline_equity'], '9995.00')
        self.assertEqual(result['segments'][0]['baseline_at'], close_at(DAYS[0]))
        lines = indexed(result)
        self.assertEqual(set(lines), {'account', 'market', 'chinext', 'd0'})
        for line in lines.values():
            self.assertEqual(line['status'], 'available', line)
            first = line['points'][0]
            self.assertEqual((first['at'], first['equity'], first['return_ratio']),
                             (close_at(DAYS[0]), '9995.00', 0))
        actual = lines['account']['points']
        self.assertEqual(actual[1]['equity'], '10095.00')
        self.assertAlmostEqual(actual[1]['return_ratio'], 100 / 9995, places=7)
        self.assertEqual(actual[1]['phase'], 'reconstructed_close')
        self.assertIn('reconstruct', lines['account']['method'].lower())

    def test_late_start_waits_for_next_close_and_never_uses_created_time(self):
        self.raw = fixture('2026-10-20T15:00:01+08:00')
        self.paper.raw = self.raw
        result = self.history()
        self.assertEqual(result['segments'][0]['baseline_at'], close_at(DAYS[1]))
        for line in result['series']:
            self.assertEqual(line['points'][0]['date'], DAYS[1])
            self.assertEqual(line['points'][0]['return_ratio'], 0)

    def test_not_started_is_explicit_and_does_not_make_reference(self):
        self.paper.raw = fixture(None)
        result = self.history()
        self.assertIn(result['status'], ('unavailable', 'waiting'))
        self.assertEqual(result['reason'], 'not_started')
        self.assertEqual(self.model_calls, [])
        self.assertTrue(all(not s['points'] for s in result['series']))

    def test_start_after_latest_close_waits_without_baseline(self):
        self.paper.raw = fixture('2026-10-23T15:01:00+08:00')
        result = self.history()
        self.assertEqual(result['status'], 'waiting')
        self.assertIsNone(result['segments'][0]['baseline_at'])
        self.assertEqual(self.model_calls, [])

    def test_history_does_not_read_source_or_trade(self):
        before = deepcopy(self.raw)
        self.history()
        self.paper.source.read.assert_not_called()
        self.paper.start.assert_not_called()
        self.paper.tick.assert_not_called()
        self.assertEqual(self.quote_calls, [])
        self.assertEqual(self.raw, before)

    def test_absent_cached_market_does_not_construct_or_refresh_one(self):
        self.paper.source._market = None
        result = self.history()
        self.assertIn(result['status'], ('unavailable', 'waiting'))
        self.assertTrue(result['reason'])
        self.assertEqual(self.model_calls, [])
        self.paper.source.read.assert_not_called()

    def test_cash_reconciliation_failure_has_no_usable_curve(self):
        fill(self.raw)
        self.raw['account']['cash'] = '9999.00'
        result = self.history()
        self.assertEqual(result['status'], 'invalid')
        self.assertTrue(all(not s['points'] for s in result['series']))
        self.assertEqual(self.model_calls, [])

    def test_zero_equity_at_first_close_is_explicitly_non_comparable(self):
        # A valid fully closed account may have spent its last proceeds on fees.
        self.raw['account'].update(initial_capital='1005.00', cash='1005.00')
        self.raw['events'][0]['capital'] = '1005.00'
        fill(self.raw)
        fill(self.raw, side='sell', price='0.050', at='2026-10-20T12:00:00+08:00')
        result = self.history()
        self.assertIn(result['status'], ('waiting', 'unavailable', 'invalid'))
        self.assertTrue(result['reason'])
        self.assertTrue(all(not s['points'] for s in result['series']))
        self.assertEqual(self.model_calls, [])

    def test_capital_changes_keep_all_segments_and_reset_at_each_close(self):
        capital(self.raw, '20000.00', '2026-10-21T10:00:00+08:00')
        result = self.history()
        self.assertEqual(len(result['segments']), 2)
        self.assertEqual([s['baseline_at'] for s in result['segments']],
                         [close_at(DAYS[0]), close_at(DAYS[1])])
        self.assertEqual([s['baseline_equity'] for s in result['segments']], ['10000.00', '20000.00'])
        for line in result['series']:
            for segment in result['segments']:
                first = next(p for p in line['points'] if p['segment_id'] == segment['id'])
                self.assertEqual((first['return_ratio'], first['equity']),
                                 (0, segment['baseline_equity']))
                self.assertTrue(first['break_before'])

    def test_missing_index_anchor_is_independent_and_never_shifts_start(self):
        cache = self.indices.caches['sh000001']
        cache.data['bars'] = cache.data['bars'][1:]
        cache.data['sessions'] = cache.data['sessions'][1:]
        result = self.history()
        lines = indexed(result)
        self.assertEqual(result['status'], 'available')
        self.assertEqual(lines['market']['status'], 'unavailable')
        self.assertEqual(lines['market']['points'], [])
        self.assertEqual(lines['chinext']['status'], 'available')
        self.assertEqual(lines['account']['points'][0]['at'], close_at(DAYS[0]))

    def test_account_missing_close_is_null_and_recovery_breaks_line(self):
        fill(self.raw)
        del self.paper.source._market.look[SYMBOLS[0]][DAYS[1]]
        result = self.history()
        points = indexed(result)['account']['points']
        missing = next(p for p in points if p['date'] == DAYS[1])
        self.assertIsNone(missing['equity'])
        self.assertIsNone(missing['return_ratio'])
        self.assertTrue(missing['break_before'])
        self.assertTrue(next(p for p in points if p['date'] == DAYS[2])['break_before'])

    def test_index_missing_middle_close_is_not_carried_forward(self):
        cache = self.indices.caches['sz399006']
        cache.data['bars'] = [r for r in cache.data['bars'] if r['date'] != DAYS[1]]
        result = self.history()
        line = indexed(result)['chinext']
        self.assertEqual(line['status'], 'available')
        missing = next(p for p in line['points'] if p['date'] == DAYS[1])
        self.assertIsNone(missing['equity'])
        self.assertIsNone(missing['return_ratio'])
        self.assertTrue(missing['break_before'])
        recovered = next(p for p in line['points'] if p['date'] == DAYS[2])
        self.assertTrue(recovered['break_before'])
        self.assertAlmostEqual(recovered['return_ratio'], .02)

    def test_model_stale_asset_closes_are_gaps(self):
        def model(*args, **kwargs):
            result = self.model(*args, **kwargs)
            result['points'][1]['stale_assets'] = [SYMBOLS[0]]
            return result
        points = indexed(self.history(model_runner=model))['d0']['points']
        self.assertIsNone(points[1]['equity'])
        self.assertIsNone(points[1]['return_ratio'])
        self.assertTrue(points[1]['break_before'])
        self.assertTrue(points[2]['break_before'])

    def test_native_model_state_and_raw_ledger_never_reach_public_contract(self):
        result = self.history()
        public = json.dumps(result, allow_nan=False)
        self.assertNotIn('private_model_secret', public)
        self.assertNotIn('must-never-reach-client', public)
        self.assertNotIn('"fills"', public)
        self.assertNotIn('"orders"', public)
        self.assertNotIn(self.folder.name, public)
        for line in result['series']:
            self.assertLessEqual(len(line['points']), 5000)
            for p in line['points']:
                if p['return_ratio'] is not None:
                    self.assertTrue(math.isfinite(p['return_ratio']))

    def test_snapshot_is_copy_and_never_reads_indices_replays_or_fetches(self):
        service = self.service()
        service.refresh(fetch_live=False)
        model_count = len(self.model_calls)
        cache_counts = [c.calls for c in self.indices.caches.values()]
        first = service.snapshot('D0-forward-paper')
        first['series'][0]['points'].clear()
        second = service.snapshot('D0-forward-paper')
        self.assertEqual(second['status'], 'available')
        self.assertTrue(second['series'][0]['points'])
        self.assertEqual(len(self.model_calls), model_count)
        self.assertEqual([c.calls for c in self.indices.caches.values()], cache_counts)
        self.assertEqual(self.quote_calls, [])
        self.paper.source.read.assert_not_called()

    def test_snapshot_rejects_changed_business_evidence(self):
        service = self.service()
        service.refresh(fetch_live=False)
        fill(self.raw, at='2026-10-23T16:00:00+08:00')
        result = service.snapshot('D0-forward-paper')
        self.assertEqual((result['status'], result['reason']), ('waiting', 'account_changed'))

    def test_snapshot_rejects_new_future_event_and_nonfilled_duplicate_order(self):
        def future_event(raw):
            event(raw, 'paused', '2026-10-24T10:00:00+08:00')
        def duplicate_order(raw):
            raw['orders'].append(dict(id=raw['orders'][0]['id'], status='pending', fill_id=None))
        for mutate in (future_event, duplicate_order):
            with self.subTest(evidence=mutate.__name__):
                self.raw = fixture()
                fill(self.raw)
                self.paper = Paper(self.raw)
                service = self.service()
                service.refresh(fetch_live=False)
                mutate(self.raw)
                result = service.snapshot('D0-forward-paper')
                self.assertEqual((result['status'], result['reason']), ('waiting', 'account_changed'))

    def test_fingerprint_covers_inactive_event_and_unfilled_order_identity(self):
        for kind, key, value in [('event', 'id', 'changed-event'),
                                 ('event', 'type', 'other_notice'),
                                 ('event', 'at', '2026-10-22T12:00:01+08:00'),
                                 ('order', 'id', 'changed-order'),
                                 ('order', 'status', 'cancelled'),
                                 ('order', 'fill_id', 'invalid-fill-link')]:
            with self.subTest(kind=kind, key=key):
                self.raw = fixture()
                event(self.raw, 'paused', '2026-10-22T12:00:00+08:00')
                self.raw['orders'].append(dict(id='pending-order', status='pending', fill_id=None))
                self.paper = Paper(self.raw)
                service = self.service()
                service.refresh(fetch_live=False)
                row = self.raw['events'][-1] if kind == 'event' else self.raw['orders'][-1]
                row[key] = value
                result = service.snapshot('D0-forward-paper')
                self.assertEqual((result['status'], result['reason']), ('waiting', 'account_changed'))

    def test_snapshot_ignores_quote_price_and_revision_changes(self):
        service = self.service()
        service.refresh(fetch_live=False)
        self.raw.update(revision=999, response_at='2026-10-23T16:30:01+08:00',
                        quotes={SYMBOLS[0]: {'price': '999', 'quote_at': NOW.isoformat()}})
        self.raw['account'].update(revision=999, equity='999999.00')
        result = service.snapshot('D0-forward-paper')
        self.assertEqual(result['status'], 'available')

    def test_business_fingerprint_covers_each_material_field_family(self):
        def cash(raw):
            raw['account']['cash'] = '1.00'
        def quantity(raw):
            raw['positions'][0]['qty'] += 1
        def fee(raw):
            raw['fills'][0]['fee'] = '6.00'
        def capital_event(raw):
            raw['events'][0]['capital'] = '10001.00'
        def order(raw):
            raw['orders'][0]['qty_filled'] += 1
        for mutate in (cash, quantity, fee, capital_event, order):
            with self.subTest(field=mutate.__name__):
                self.raw = fixture()
                fill(self.raw)
                self.paper = Paper(self.raw)
                service = self.service()
                service.refresh(fetch_live=False)
                mutate(self.raw)
                result = service.snapshot('D0-forward-paper')
                self.assertEqual((result['status'], result['reason']),
                                 ('waiting', 'account_changed'))

    def test_repeated_historical_refresh_uses_model_cache(self):
        service = self.service()
        service.refresh(fetch_live=False)
        expected = len(self.model_calls)
        service.refresh(fetch_live=False)
        self.assertEqual(len(self.model_calls), expected)

    def test_signal_cache_mismatch_degrades_without_new_source_read(self):
        self.paper.source._signal_key = (DAYS[0], 'old-hash')
        result = self.history()
        self.assertNotEqual(result['status'], 'available')
        self.assertEqual(self.model_calls, [])
        self.paper.source.read.assert_not_called()

    def test_paused_ledger_old_signal_allows_new_valid_market_reference(self):
        self.raw['signal'] = {'id': 'old-signal', 'confirmed_day': DAYS[0]}
        event(self.raw, 'paused', '2026-10-21T10:00:00+08:00')
        result = self.history()
        self.assertEqual(result['status'], 'available')
        self.assertEqual(indexed(result)['d0']['status'], 'available')

    def test_disabled_environment_never_creates_worker(self):
        with patch.dict(os.environ, {'ETF_WEB_INDEX_BENCHMARK_REFRESH': '0',
                                     'ETF_WEB_BENCHMARK_REFRESH': '0'}):
            service = self.service(refresh_enabled=None)
        self.assertIsNone(service.thread)
        self.assertEqual(self.model_calls, [])
        self.assertEqual(self.quote_calls, [])
        started = time.monotonic()
        service.close()
        self.assertLess(time.monotonic() - started, 1)

    def test_close_interrupts_waiting_worker(self):
        service = self.service(refresh_enabled=True, interval=60)
        started = time.monotonic()
        service.close()
        self.assertLess(time.monotonic() - started, 3)
        self.assertTrue(service.thread is None or not service.thread.is_alive())

    def test_close_passes_stop_to_inflight_model(self):
        entered = threading.Event()
        stopped = threading.Event()
        def model(*args, stop=None, **kwargs):
            entered.set()
            if stop is not None and stop.wait(3):
                stopped.set()
            return dict(status='unavailable', reason='test_stopped', points=[])
        service = self.service(refresh_enabled=True, interval=60, model_runner=model)
        self.assertTrue(entered.wait(2), 'background model was never scheduled')
        started = time.monotonic()
        service.close()
        self.assertLess(time.monotonic() - started, 2)
        self.assertTrue(stopped.is_set())
        self.assertTrue(service.thread is None or not service.thread.is_alive())

    def test_close_cancels_capture_wait_without_releasing_business_lock(self):
        attempted = threading.Event()
        owner = threading.get_ident()
        class ObservedLock:
            def __init__(self):
                self.inner = threading.RLock()
            def acquire(self, *args, **kwargs):
                if threading.get_ident() != owner:
                    attempted.set()
                return self.inner.acquire(*args, **kwargs)
            def release(self):
                self.inner.release()
            def _is_owned(self):
                return self.inner._is_owned()
            def __enter__(self):
                self.acquire()
                return self
            def __exit__(self, *args):
                self.release()
        self.paper._lock = ObservedLock()
        # Keep the real business lock held until after close has returned.
        with self.paper._lock:
            service = self.service(refresh_enabled=True, interval=60)
            self.assertTrue(attempted.wait(1), 'worker did not begin capturing the account')
            started = time.monotonic()
            service.close()
            self.assertLess(time.monotonic() - started, 1)
            self.assertTrue(service.thread is None or not service.thread.is_alive())
            self.assertEqual(self.model_calls, [])

    def live_fixture(self, *, fresh=True):
        self.clock = datetime.fromisoformat('2026-10-23T14:00:00+08:00')
        self.paper.source._market.dates = DAYS[:3]
        self.paper.source._market.latest = DAYS[2]
        self.paper.source._signal['confirmed_day'] = DAYS[2]
        self.paper.source._signal_key = (DAYS[2], 'synthetic-market-hash')
        fill(self.raw)
        self.raw['response_at'] = self.clock.isoformat()
        source_at = (self.clock - timedelta(seconds=10 if fresh else 90)).isoformat()
        self.raw['quotes'] = {SYMBOLS[0]: {'symbol': SYMBOLS[0], 'price': '11.000', 'status': 'unverified',
                                         'source': 'synthetic ETF',
                                         'quote_at': source_at, 'received_at': self.clock.isoformat()}}
        self.raw['account'].update(equity='10095.00', valuation_status='current' if fresh else 'stale')
        for row in self.raw['positions']:
            row.update(cost='1005.00' if row['qty'] else '0.00',
                       lots=[{'qty': 100, 'cost': '1005.00'}] if row['qty'] else [],
                       price='11.000' if row['qty'] else None,
                       market_value='1100.00' if row['qty'] else None,
                       valuation_status=('current' if fresh else 'stale') if row['qty'] else 'not_held')
        self.paper._last_batch = dict(source='synthetic ETF', received_at=self.clock.isoformat(),
                                     quotes=deepcopy(self.raw['quotes']))
        for cache in self.indices.caches.values():
            cache.data.update(bars=cache.data['bars'][:3], sessions=DAYS[:3], confirmed_through=DAYS[2])
        return source_at

    def test_stale_actual_quote_does_not_become_current_estimate(self):
        self.live_fixture(fresh=False)
        result = self.service().refresh(fetch_live=True)
        points = indexed(result)['account']['points']
        self.assertFalse(any(p['phase'] == 'intraday_estimate' for p in points))
        self.assertEqual(points[-1]['at'], close_at(DAYS[2]))

    def test_refresh_retains_verified_tails_and_replaces_them_on_recovery(self):
        self.live_fixture()
        available = [True]
        def model_live(*args, **kwargs):
            return (dict(status='available', equity='10050.00', at=self.clock.isoformat(),
                         quote_at=(self.clock-timedelta(seconds=1)).isoformat(), cash_only=False)
                    if available[0] else dict(status='unavailable', reason='quotes_unavailable'))
        service = self.service(live_model_runner=model_live)
        first = indexed(service.refresh(fetch_live=True))
        saved = {name: deepcopy(first[name]['points'][-1]) for name in ('account', 'd0')}
        self.clock += timedelta(seconds=10)
        available[0] = False
        self.paper._source_state = dict(source_status='blocked', reason='quotes_collection_failed',
                                       observation_state='producer_blocked', market_observation=None)
        for delay in (0, 120):
            self.clock += timedelta(seconds=delay)
            result = indexed(service.refresh(fetch_live=True))
            for name in saved:
                point = result[name]['points'][-1]
                self.assertIs(point['retained'], True)
                self.assertEqual({k: v for k, v in point.items() if k not in ('retained', 'retained_reason')}, saved[name])
                self.assertEqual(result[name]['live_status'], 'retained')
                self.assertEqual(result[name]['live_reason'], 'source_unavailable')
                self.assertEqual(sum(p['phase'] == 'intraday_estimate' for p in result[name]['points']), 1)
            self.assertEqual(result['market']['points'][-1]['at'], self.clock.isoformat())
        available[0] = True
        self.paper._source_state = dict(source_status='ready')
        self.raw['response_at'] = self.clock.isoformat()
        self.raw['quotes'][SYMBOLS[0]].update(quote_at=(self.clock-timedelta(seconds=1)).isoformat(),
                                              received_at=self.clock.isoformat())
        recovered = indexed(service.refresh(fetch_live=True))
        for name in saved:
            self.assertNotIn('retained', recovered[name]['points'][-1])
            self.assertEqual(recovered[name]['live_status'], 'available')

    def test_refresh_signal_change_does_not_restore_previous_model_or_account_tail(self):
        self.live_fixture()
        runner = Mock(return_value=dict(status='available', equity='10050.00', at=self.clock.isoformat(),
                                       quote_at=self.clock.isoformat(), cash_only=False))
        service = self.service(live_model_runner=runner)
        service.refresh(fetch_live=True)
        self.clock += timedelta(seconds=10)
        self.paper.source._signal['id'] = 'new-confirmed-identity'
        self.paper._source_state = dict(source_status='blocked', reason='quotes_collection_failed',
                                       observation_state='producer_blocked', market_observation=None)
        runner.return_value = dict(status='unavailable', reason='quotes_unavailable')
        result = indexed(service.refresh(fetch_live=True))
        for name in ('account', 'd0'):
            self.assertFalse(any(p['phase'] == 'intraday_estimate' for p in result[name]['points']))

    def test_refresh_new_business_event_does_not_restore_previous_tail(self):
        self.live_fixture()
        runner = Mock(return_value=dict(status='available', equity='10050.00', at=self.clock.isoformat(),
                                       quote_at=self.clock.isoformat(), cash_only=False))
        service = self.service(live_model_runner=runner)
        service.refresh(fetch_live=True)
        self.clock += timedelta(seconds=10)
        self.raw['events'].append(dict(id='new-control-observation', type='observer_control', at=self.clock.isoformat()))
        self.paper._source_state = dict(source_status='blocked', reason='quotes_collection_failed',
                                       observation_state='producer_blocked', market_observation=None)
        runner.return_value = dict(status='unavailable', reason='quotes_unavailable')
        result = indexed(service.refresh(fetch_live=True))
        for name in ('account', 'd0'):
            self.assertFalse(any(p['phase'] == 'intraday_estimate' for p in result[name]['points']))

    def test_snapshot_rejects_changed_saved_signal_before_next_worker_refresh(self):
        fill(self.raw)
        service = self.service()
        service.refresh(fetch_live=False)
        self.assertEqual(service.snapshot(self.raw['account']['id'])['status'], 'available')
        self.raw['signal'] = dict(id='new-confirmed-signal', history_cutoff=DAYS[-1], spec_hash='new-spec')
        result = service.snapshot(self.raw['account']['id'])
        self.assertEqual(result['status'], 'waiting')
        self.assertEqual(result['reason'], 'account_changed')

    def test_history_review_prevents_only_reference_live_from_old_market(self):
        self.live_fixture()
        for reason in ('historical_data_revision', 'history_baseline_review',
                       'history_continuity_review_required', 'corporate_action_review_required',
                       'holdings_history_unverified'):
            with self.subTest(reason=reason):
                self.paper._source_state = dict(source_status='blocked', reason=reason)
                runner = Mock(return_value=dict(status='available', reason=None, equity='10050.00',
                                               at=self.clock.isoformat(), quote_at=self.clock.isoformat(),
                                               latest_quote_at=self.clock.isoformat(), cash_only=False))
                result = self.service(live_model_runner=runner).refresh(fetch_live=True)
                lines = indexed(result)
                self.assertEqual(lines['d0']['points'][-1]['phase'], 'model_close')
                runner.assert_not_called()
                for name in ('account', 'market', 'chinext'):
                    self.assertEqual(lines[name]['points'][-1]['phase'], 'intraday_estimate')

    def test_cash_only_live_account_and_explicit_native_cash_are_identified(self):
        self.live_fixture()
        self.raw = fixture()
        self.raw['account']['equity'] = self.raw['account']['cash']
        self.paper.raw = self.raw
        runner = lambda *a, **k: dict(status='available', reason=None, equity='10000.00',
                                    at=self.clock.isoformat(), quote_at=None,
                                    latest_quote_at=None, cash_only=True)
        lines = indexed(self.service(live_model_runner=runner).refresh(fetch_live=True))
        for name in ('account', 'd0'):
            point = lines[name]['points'][-1]
            self.assertEqual(point['phase'], 'intraday_estimate')
            self.assertIs(point['cash_only'], True)
            self.assertIsNone(point['source_at'])
        for name in ('market', 'chinext'):
            point = lines[name]['points'][-1]
            self.assertEqual(point['phase'], 'intraday_estimate')
            self.assertIs(point['cash_only'], False)

    def test_live_account_holdings_and_priced_model_are_not_cash_only(self):
        source_at = self.live_fixture()
        runner = lambda *a, **k: dict(status='available', reason=None, equity='10050.00',
                                    at=self.clock.isoformat(), quote_at=source_at,
                                    latest_quote_at=source_at, cash_only=False)
        result = self.service(live_model_runner=runner).refresh(fetch_live=True)
        for line in result['series']:
            point = line['points'][-1]
            self.assertEqual(point['phase'], 'intraday_estimate')
            self.assertIs(point['cash_only'], False)

    def test_unstamped_model_without_explicit_cash_status_is_never_called_cash_only(self):
        self.live_fixture()
        for flag in ('missing', False):
            with self.subTest(cash_only=flag):
                def runner(*a, **k):
                    result = dict(status='available', reason=None, equity='10050.00',
                                  at=self.clock.isoformat(), quote_at=None, latest_quote_at=None)
                    if flag != 'missing':
                        result['cash_only'] = flag
                    return result
                result = self.service(live_model_runner=runner).refresh(fetch_live=True)
                live = [p for p in indexed(result)['d0']['points'] if p['phase'] == 'intraday_estimate']
                if live:
                    self.assertIs(live[-1].get('cash_only'), False)

    def test_independent_live_source_times_are_preserved(self):
        account_at = self.live_fixture()
        model_at = (self.clock - timedelta(seconds=20)).isoformat()
        market_at = (self.clock - timedelta(seconds=30)).isoformat()
        chinext_at = (self.clock - timedelta(seconds=40)).isoformat()
        def quote(symbol, **kwargs):
            result = self.quote(symbol, **kwargs)
            result['quote_at'] = market_at if symbol == 'sh000001' else chinext_at
            return result
        def model_live(*args, **kwargs):
            self.assertFalse(self.paper._lock._is_owned())
            return dict(status='available', reason=None, equity='10050.00',
                        at=self.clock.isoformat(), quote_at=model_at,
                        latest_quote_at=model_at, phase='intraday_estimate')
        result = self.service(quote_fetcher=quote, live_model_runner=model_live).refresh(fetch_live=True)
        lines = indexed(result)
        for name, stamp in [('account', account_at), ('market', market_at),
                            ('chinext', chinext_at), ('d0', model_at)]:
            point = lines[name]['points'][-1]
            self.assertEqual(point['phase'], 'intraday_estimate', (name, point))
            self.assertEqual(point['source_at'], stamp)
            self.assertEqual(point['observed_at'], self.clock.isoformat())
        self.assertNotIn('excess', json.dumps(result).lower())

    def test_one_index_live_failure_keeps_other_and_historical_points(self):
        self.live_fixture()
        def quote(symbol, **kwargs):
            if symbol == 'sh000001':
                raise OSError('synthetic transport unavailable')
            return self.quote(symbol, **kwargs)
        result = self.service(quote_fetcher=quote).refresh(fetch_live=True)
        lines = indexed(result)
        self.assertEqual(lines['market']['status'], 'available')
        self.assertEqual(lines['market']['points'][-1]['phase'], 'index_close')
        self.assertEqual(lines['chinext']['points'][-1]['phase'], 'intraday_estimate')

    def test_old_index_quote_is_not_freshened_to_receipt_time(self):
        self.live_fixture()
        def quote(symbol, **kwargs):
            result = self.quote(symbol, **kwargs)
            result['quote_at'] = (self.clock - timedelta(seconds=61)).isoformat()
            return result
        result = self.service(quote_fetcher=quote).refresh(fetch_live=True)
        for name in ('market', 'chinext'):
            self.assertEqual(indexed(result)[name]['points'][-1]['phase'], 'index_close')

    def test_future_and_wrong_identity_index_quotes_are_not_appended(self):
        self.live_fixture()
        def future(result):
            result['quote_at'] = (self.clock + timedelta(seconds=1)).isoformat()
        def wrong_symbol(result):
            result['symbol'] = 'sh510300'
        def wrong_type(result):
            result['instrument_type'] = 'ETF'
        for corrupt in (future, wrong_symbol, wrong_type):
            with self.subTest(kind=corrupt.__name__):
                def quote(symbol, **kwargs):
                    result = self.quote(symbol, **kwargs)
                    corrupt(result)
                    return result
                result = self.service(quote_fetcher=quote).refresh(fetch_live=True)
                for name in ('market', 'chinext'):
                    self.assertEqual(indexed(result)[name]['points'][-1]['phase'], 'index_close')

    def test_quote_before_confirmed_close_received_after_it_is_not_new_live_value(self):
        self.live_fixture()
        self.clock = datetime.fromisoformat('2026-10-23T15:00:15+08:00')
        source_at = '2026-10-23T14:59:59+08:00'
        self.paper.source._market.dates = DAYS
        self.paper.source._market.latest = DAYS[-1]
        self.paper.source._signal['confirmed_day'] = DAYS[-1]
        self.paper.source._signal_key = (DAYS[-1], 'synthetic-market-hash')
        self.indices = SimpleNamespace(caches={s: Cache(s) for s in INDEX_NAMES})
        self.raw['response_at'] = self.clock.isoformat()
        self.raw['quotes'][SYMBOLS[0]].update(quote_at=source_at, received_at=self.clock.isoformat())
        def quote(symbol, **kwargs):
            result = self.quote(symbol, **kwargs)
            result['quote_at'] = source_at
            return result
        def model_live(*args, **kwargs):
            return dict(status='available', reason=None, equity='10050.00',
                        at=self.clock.isoformat(), quote_at=source_at,
                        latest_quote_at=source_at, phase='intraday_estimate')
        result = self.service(quote_fetcher=quote, live_model_runner=model_live).refresh(fetch_live=True)
        for line in result['series']:
            self.assertNotEqual(line['points'][-1]['phase'], 'intraday_estimate', line)
            self.assertEqual(line['points'][-1]['at'], close_at(DAYS[-1]))

    def test_default_transport_uses_five_second_timeout_and_bounded_actual_read(self):
        limit = 1024 * 1024
        for count in (10, limit, limit + 1):
            with self.subTest(bytes=count), patch('realtime_paper_comparison.urlopen') as open_url:
                response = open_url.return_value.__enter__.return_value
                response.read.return_value = b'x' * count
                if count > limit:
                    with self.assertRaises(ValueError):
                        _bounded_request('https://synthetic.invalid/index')
                else:
                    self.assertEqual(len(_bounded_request('https://synthetic.invalid/index')), count)
                self.assertEqual(open_url.call_args.kwargs['timeout'], 5)
                response.read.assert_called_once_with(limit + 1)


if __name__ == '__main__':
    unittest.main()
