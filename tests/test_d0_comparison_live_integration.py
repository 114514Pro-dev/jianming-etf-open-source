"""Offline live-comparison contracts with the real source, ledger and model.

Only temporary SQLite stores and synthetic quotes/markets are used. Source
acceptance is deliberately distinct from ledger acceptance in these cases.
"""
from contextlib import closing
from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import realtime_paper_comparison as comparison
from realtime_paper_comparison_model import replay_reference, estimate_reference_live
from realtime_paper_engine import PaperLedger
from realtime_paper_service import PaperService, ReadOnlyPaperSource, SYMBOLS
from test_d0_comparison_model import SyntheticMarket, NOW, GOLD


class LiveComparisonIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.network = patch('socket.create_connection', side_effect=AssertionError('network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.home = Path(self.folder.name)
        self.received = NOW
        self.clock = NOW - timedelta(seconds=10)
        self.path = self.home / '盘中行情.sqlite3'
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE snapshots(id TEXT PRIMARY KEY,received_at TEXT,payload TEXT)')
            db.execute('CREATE TABLE attempts(id TEXT PRIMARY KEY,attempted_at TEXT,status TEXT)')
        self.source = ReadOnlyPaperSource(self.home, now=lambda: self.clock)
        self.ledger = PaperLedger(self.home, now=lambda: self.clock)
        self.ledger.create('100000.00')
        self.ledger.set_running(True)
        self.signal = dict(id='synthetic-D0-confirmed', strategy='D0', day='2026-10-27',
                           market_hash='synthetic-confirmed-market', spec_hash='synthetic-spec',
                           reason='Synthetic frozen D0 target', history_cutoff='2026-10-27',
                           signal_at='2026-10-27T16:10:00+08:00',
                           received_at='2026-10-27T16:10:00+08:00',
                           data_cutoff='2026-10-27T15:00:00+08:00',
                           eligible_at='2026-10-28T09:30:00+08:00',
                           weights={s: int(s == GOLD) for s in SYMBOLS})
        self.ledger.set_signal(self.signal)
        self.ledger.ingest_batch(self.make_batch(self.clock, volume=10000))
        order = self.ledger.submit(GOLD, 'buy', 100, '13.600',
                                   signal_id=self.signal['id'], client_order_id='synthetic-buy')
        self.assertEqual(order['orders'][-1]['status'], 'pending')
        self.clock = NOW - timedelta(seconds=5)
        self.ledger.ingest_batch(self.make_batch(self.clock, volume=10001))
        self.clock = NOW
        self.batch = self.make_batch(NOW, volume=10002)
        self.write_batch(self.batch)
        self.paper = PaperService(self.home, source=self.source, ledger=self.ledger,
                                  now=lambda: self.clock, start_worker=False)
        self.addCleanup(self.paper.close)
        accepted, reason = self.read_source()
        self.assertEqual(reason, 'ready')
        self.assertIsNotNone(accepted)
        actual = self.ledger.ingest_batch(accepted)
        self.assertEqual(len(actual['fills']), 1)
        self.assertEqual(next(p for p in actual['positions'] if p['symbol'] == GOLD)['qty'], 100)
        self.market = SyntheticMarket()
        self.source._market = self.market
        self.source._signal = deepcopy(self.signal)
        self.source._signal_key = (self.market.latest, self.market.hash)

    def make_batch(self, at, *, volume=10002):
        return dict(schema='simpleetf.intraday.v1', source='Synthetic public quotes',
                    received_at=at.isoformat(), quotes={s: dict(
                        symbol=s, day=at.date().isoformat(),
                        quote_at=(at - timedelta(seconds=1)).isoformat(),
                        price=13.5, previous_close=13., open=13., high=14., low=12.,
                        started=True, volume_lots=volume, amount_cny=volume * 1350)
                        for s in SYMBOLS})

    def write_batch(self, batch, key=None):
        key = key or batch['received_at']
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT OR REPLACE INTO snapshots VALUES (?,?,?)',
                       (key, batch['received_at'], json.dumps(batch, allow_nan=False)))
            db.execute('INSERT OR REPLACE INTO attempts VALUES (?,?,?)',
                       ('success-' + key, batch['received_at'], '成功'))

    def read_source(self):
        # Read the real persisted source batch. Mirror only poll_once's handoff
        # fields, leaving history refresh and automatic order planning out.
        self.source._activity_invalidation = self.source._pending_producer_invalidation
        batch, reason = self.source._batch(self.clock)
        status = 'ready' if batch else ('blocked' if reason == 'quotes_collection_state_invalid' else 'waiting')
        self.paper._source_state = dict(source_status=status, reason=reason,
                                       observation_state=self.source._observation_state,
                                       market_observation=deepcopy(self.source._observed_batch))
        self.paper._last_batch = batch if status == 'ready' else None
        return batch, reason

    def raw_at(self, age=10):
        self.clock = self.received + timedelta(seconds=age)
        self.read_source()
        raw = self.ledger.snapshot()
        raw.update(deepcopy(self.paper._source_state))
        return raw

    def fallback(self, raw):
        return comparison._accepted_repeat_batch(raw, self.clock)

    def assert_relevant_unavailable(self, raw):
        candidate = self.fallback(raw)
        if candidate is not None:
            self.assertNotIn(GOLD, candidate['quotes'])
        self.assertIsNone(comparison._accepted_repeat_batch(raw, self.clock, symbols=[GOLD]))
        self.assertIsNone(comparison._account_live(raw, self.clock))
        self.assertNotEqual(self.model(candidate)['status'], 'available')

    def model(self, batch):
        reference = replay_reference(self.market, '2026-10-23', '2026-10-27', '100000.00')
        self.assertEqual(reference['status'], 'available')
        return estimate_reference_live(reference, self.market, batch, now=self.clock)

    def test_real_accepted_repeat_survives_10_31_and_59_seconds_for_display(self):
        original = self.ledger.snapshot()
        for age in (10, 31, 59):
            with self.subTest(age=age):
                raw = self.raw_at(age)
                self.assertEqual(raw['reason'], 'quote_queue_delay')
                self.assertEqual(raw['observation_state'], 'repeat')
                self.assertEqual(raw['account']['valuation_status'], 'stale')
                self.assertIsNone(self.paper._last_batch)
                batch = self.fallback(raw)
                self.assertEqual(batch, self.batch)
                account = comparison._account_live(raw, self.clock)
                self.assertIsNotNone(account)
                self.assertEqual(account['equity'], raw['account']['equity'])
                self.assertEqual(account['source_at'], self.batch['quotes'][GOLD]['quote_at'])
                live = self.model(batch)
                self.assertEqual(live['status'], 'available')
                self.assertEqual(live['at'], self.batch['received_at'])
                self.assertEqual(live['quote_at'], self.batch['quotes'][GOLD]['quote_at'])
        after = self.ledger.snapshot()
        for field in ('revision', 'orders', 'fills', 'events', 'signal'):
            self.assertEqual(after[field], original[field])
        self.assertTrue(after['account']['running'])

    def test_display_fallback_never_reopens_the_five_second_execution_window(self):
        for age in (10, 31, 59):
            with self.subTest(age=age):
                raw = self.raw_at(age)
                self.assertIsNotNone(self.fallback(raw))
                self.assertFalse(self.ledger._fresh(raw['quotes'][GOLD], self.clock))
                self.assertFalse(self.paper._ready(raw, self.signal, self.batch))
                # Even a ready label cannot relax the independent age check.
                self.paper._source_state['source_status'] = 'ready'
                self.assertFalse(self.paper._ready(raw, self.signal, self.batch))
        result = self.ledger.submit(GOLD, 'buy', 100, '13.600',
                                    signal_id=self.signal['id'], client_order_id='too-old-to-trade')
        self.assertEqual(result['orders'][-1]['status'], 'rejected')
        self.assertEqual(len(result['fills']), 1)

    def test_source_or_receipt_older_than_sixty_seconds_is_unavailable(self):
        for age in (60, 61, 120):  # Source is one second older than receipt.
            with self.subTest(age=age):
                raw = self.raw_at(age)
                self.assertIsNone(self.fallback(raw))
                self.assertIsNone(comparison._account_live(raw, self.clock))
                self.assertNotEqual(self.model(self.batch)['status'], 'available')

    def test_capture_uses_real_ledger_and_safe_repeat_without_rewriting_trading_batch(self):
        raw = self.raw_at(31)
        service = comparison.D0ComparisonService(self.home, self.paper, SimpleNamespace(caches={}),
            now=lambda: self.clock, refresh_enabled=False,
            request=lambda *a, **k: self.fail('comparison requested network'))
        self.addCleanup(service.close)
        captured, market, signal, key, batch = service._capture()
        self.assertEqual(captured['account'], raw['account'])
        self.assertIs(market, self.market)
        self.assertEqual(signal, self.source._signal)
        self.assertEqual(key, self.source._signal_key)
        self.assertEqual(batch, self.batch)
        batch['quotes'][GOLD]['price'] = 999
        self.assertEqual(self.paper._source_state['market_observation'], self.batch)
        self.assertIsNone(self.paper._last_batch)

    def test_new_unaccepted_snapshot_cannot_be_used_as_fallback(self):
        self.clock = NOW + timedelta(seconds=1)
        fresh = self.make_batch(self.clock, volume=10003)
        self.write_batch(fresh)
        accepted, reason = self.read_source()
        self.assertEqual(reason, 'ready')
        self.assertIsNotNone(accepted)
        # Never ingested into the real ledger.
        raw = self.raw_at(20)
        self.assertEqual(raw['observation_state'], 'repeat')
        self.assertIsNone(self.fallback(raw))
        self.assertIsNone(comparison._account_live(raw, self.clock))

    def test_source_acceptance_does_not_hide_actual_ledger_volume_rejection(self):
        self.clock = NOW + timedelta(seconds=1)
        new = self.make_batch(self.clock, volume=10002)
        self.write_batch(new)
        accepted, reason = self.read_source()
        self.assertEqual(reason, 'ready')
        outcome = self.ledger.ingest_batch(accepted)
        self.assertEqual(len(outcome['ingest_errors']), 4)
        self.assertTrue(all('cumulative trade evidence' in e['reason'] for e in outcome['ingest_errors']))
        raw = self.raw_at(20)
        self.assertEqual(raw['quotes'][GOLD]['received_at'], self.batch['received_at'])
        self.assertEqual(raw['observation_state'], 'repeat')
        self.assertIsNone(self.fallback(raw))
        self.assertIsNone(comparison._account_live(raw, self.clock))

    def mixed_acceptance(self, rejected_symbol):
        self.clock = NOW + timedelta(seconds=1)
        new = self.make_batch(self.clock, volume=10003)
        new['quotes'][rejected_symbol].update(volume_lots=10002, amount_cny=10002 * 1350)
        self.write_batch(new)
        accepted, reason = self.read_source()
        self.assertEqual(reason, 'ready')
        outcome = self.ledger.ingest_batch(accepted)
        self.assertEqual([e['symbol'] for e in outcome['ingest_errors']], [rejected_symbol])
        return self.raw_at(20)

    def test_real_unrelated_ledger_rejection_preserves_valid_account_and_model(self):
        raw = self.mixed_acceptance(SYMBOLS[0])
        candidate = self.fallback(raw)
        self.assertEqual(set(candidate['quotes']), set(SYMBOLS) - {SYMBOLS[0]})
        self.assertIsNotNone(comparison._account_live(raw, self.clock))
        self.assertEqual(self.model(candidate)['status'], 'available')

    def test_real_required_ledger_rejection_blocks_account_and_model(self):
        self.assert_relevant_unavailable(self.mixed_acceptance(GOLD))

    def test_missing_new_target_blocks_model_even_when_actual_holding_is_valid(self):
        raw = self.mixed_acceptance(SYMBOLS[0])
        market = SyntheticMarket(weights={'2026-10-27': SYMBOLS[0]})
        reference = replay_reference(market, '2026-10-23', '2026-10-27', '100000.00')
        self.assertGreater(reference['state']['positions'][GOLD]['qty'], 0)
        self.assertEqual(reference['state']['pending']['weights'][SYMBOLS[0]], 1.)
        self.assertIsNotNone(comparison._account_live(raw, self.clock))
        result = estimate_reference_live(reference, market, self.fallback(raw), now=self.clock)
        self.assertNotEqual(result['status'], 'available')

    def test_real_producer_failure_blocks_even_previously_accepted_quotes(self):
        self.clock = NOW + timedelta(seconds=6)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('INSERT INTO attempts VALUES (?,?,?)',
                       ('failed-attempt', self.clock.isoformat(), '失败'))
        raw = self.raw_at(10)
        self.assertNotEqual(raw['reason'], 'quote_queue_delay')
        self.assertIsNone(self.fallback(raw))
        self.assertIsNone(comparison._account_live(raw, self.clock))

    def test_real_invalid_producer_schema_blocks_cached_quotes(self):
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('DROP TABLE attempts')
            db.execute('CREATE VIEW attempts AS SELECT 1 AS unexpected')
        raw = self.raw_at(10)
        self.assertEqual(raw['reason'], 'quotes_collection_state_invalid')
        self.assertIsNone(self.fallback(raw))

    def test_bad_source_states_never_reuse_matching_observation(self):
        raw = self.raw_at(10)
        cases = [dict(source_status='ready'), dict(source_status='blocked'),
                 dict(reason='quotes_stale'), dict(reason='historical_data_revision'),
                 dict(observation_state='new_invalid'), dict(observation_state='repeat_invalid'),
                 dict(observation_state='producer_blocked'), dict(observation_state='new_valid')]
        for changes in cases:
            with self.subTest(changes=changes):
                changed = deepcopy(raw)
                changed.update(changes)
                self.assertIsNone(self.fallback(changed))
                self.assertIsNone(comparison._account_live(changed, self.clock))

    def test_each_observation_identity_and_economic_field_must_match_ledger(self):
        raw = self.raw_at(10)
        changes = dict(symbol=SYMBOLS[0], source='Other source', price=13.6,
                       previous_close=12.9, volume_lots=10003, amount_cny=13502701,
                       quote_at=(NOW - timedelta(seconds=2)).isoformat(),
                       received_at=(NOW - timedelta(seconds=1)).isoformat())
        for field, value in changes.items():
            with self.subTest(field=field):
                changed = deepcopy(raw)
                changed['market_observation']['quotes'][GOLD][field] = value
                self.assert_relevant_unavailable(changed)

    def test_effective_quote_level_receipt_and_source_override_batch_fields(self):
        raw = self.raw_at(10)
        observed = raw['market_observation']
        for q in observed['quotes'].values():
            q.update(received_at=observed['received_at'], source=observed['source'])
        self.assertIsNotNone(self.fallback(raw))
        for field, value in [('source', 'Different batch source'),
                             ('received_at', (NOW - timedelta(seconds=2)).isoformat())]:
            with self.subTest(field=field):
                changed = deepcopy(raw)
                # The effective per-quote value differs even though the
                # top-level batch value still matches the accepted ledger.
                changed['market_observation']['quotes'][GOLD][field] = value
                self.assert_relevant_unavailable(changed)

    def test_incomplete_observation_is_rejected_but_unrelated_unaccepted_quote_is_filtered(self):
        raw = self.raw_at(10)
        changed = deepcopy(raw)
        changed['market_observation']['quotes'].pop(SYMBOLS[0])
        self.assertIsNone(self.fallback(changed))
        for mutation in ('missing', 'different_receipt', 'halted'):
            with self.subTest(mutation=mutation):
                changed = deepcopy(raw)
                if mutation == 'missing':
                    changed['quotes'].pop(SYMBOLS[0])
                elif mutation == 'different_receipt':
                    changed['quotes'][SYMBOLS[0]]['received_at'] = (NOW - timedelta(seconds=2)).isoformat()
                else:
                    changed['quotes'][SYMBOLS[0]]['status'] = 'halted'
                candidate = self.fallback(changed)
                self.assertNotIn(SYMBOLS[0], candidate['quotes'])
                self.assertIn(GOLD, candidate['quotes'])
                self.assertIsNotNone(comparison._account_live(changed, self.clock))
                self.assertEqual(self.model(candidate)['status'], 'available')
                self.assertIsNone(comparison._accepted_repeat_batch(changed, self.clock, symbols=[GOLD, SYMBOLS[0]]))
        changed = deepcopy(raw)
        changed['quotes'].pop(GOLD)
        self.assert_relevant_unavailable(changed)

    def test_halt_unknown_and_corporate_risks_block_fallback(self):
        raw = self.raw_at(10)
        changes = [('status', 'halted'), ('status', 'unknown'),
                   ('suspended', True), ('corporate_actions_known', False),
                   ('corporate_action_pending', True)]
        for field, value in changes:
            with self.subTest(field=field, value=value):
                changed = deepcopy(raw)
                changed['market_observation']['quotes'][GOLD][field] = value
                self.assert_relevant_unavailable(changed)
        for field, value in [('status', 'halted'), ('status', 'unknown'), ('corporate_unknown', True)]:
            with self.subTest(accepted_field=field, value=value):
                changed = deepcopy(raw)
                changed['quotes'][GOLD][field] = value
                self.assert_relevant_unavailable(changed)

    def test_adverse_status_watermark_blocks_even_matching_saved_quote(self):
        raw = self.raw_at(10)
        for status in ('halted', 'unknown'):
            with self.subTest(status=status):
                changed = deepcopy(raw)
                changed.setdefault('status_watermarks', {})[GOLD] = dict(
                    symbol=GOLD, source=self.batch['source'], status=status,
                    quote_at=(NOW + timedelta(seconds=2)).isoformat(),
                    received_at=(NOW + timedelta(seconds=3)).isoformat())
                self.assert_relevant_unavailable(changed)

    def test_future_cross_day_and_lunch_boundary_quotes_are_not_display_current(self):
        raw = self.raw_at(10)
        for stamp in ((self.clock + timedelta(seconds=1)).isoformat(),
                      '2026-10-27T10:00:00+08:00', '2026-10-28T11:29:59+08:00'):
            with self.subTest(stamp=stamp):
                changed = deepcopy(raw)
                for q in changed['quotes'].values():
                    q.update(quote_at=stamp, received_at=stamp)
                changed['market_observation']['received_at'] = stamp
                for q in changed['market_observation']['quotes'].values():
                    q.update(quote_at=stamp)
                self.assertIsNone(self.fallback(changed))
        self.clock = NOW.replace(hour=11, minute=30, second=10)
        stamp = '2026-10-28T11:29:59+08:00'
        changed = deepcopy(raw)
        changed['market_observation']['received_at'] = stamp
        for q in changed['quotes'].values():
            q.update(quote_at=stamp, received_at=stamp)
        for q in changed['market_observation']['quotes'].values():
            q.update(quote_at=stamp)
        self.assertIsNone(self.fallback(changed))

    def test_account_projection_rejects_tampered_equity_position_and_cash(self):
        raw = self.raw_at(10)
        for field in ('equity', 'cash'):
            with self.subTest(account_field=field):
                changed = deepcopy(raw)
                changed['account'][field] = str(Decimal(changed['account'][field]) + 1)
                self.assertIsNone(comparison._account_live(changed, self.clock))
        for field, value in [('price', '13.600'), ('market_value', '1351.00'),
                             ('qty', 101), ('qty', True), ('qty', -100), ('qty', 100.5)]:
            with self.subTest(position_field=field):
                changed = deepcopy(raw)
                next(p for p in changed['positions'] if p['symbol'] == GOLD)[field] = value
                self.assertIsNone(comparison._account_live(changed, self.clock))
        changed = deepcopy(raw)
        changed['positions'].append(deepcopy(next(p for p in changed['positions'] if p['symbol'] == GOLD)))
        self.assertIsNone(comparison._account_live(changed, self.clock))
        raw['response_at'] = (NOW - timedelta(microseconds=500000)).isoformat()
        self.assertIsNone(comparison._account_live(raw, self.clock))

    def test_account_current_path_still_rejects_halt_and_bad_amount(self):
        raw = self.raw_at(1)
        self.assertEqual(raw['account']['valuation_status'], 'current')
        self.assertIsNotNone(comparison._account_live(raw, self.clock))
        for changes in (dict(status='halted'), dict(status='unknown'), dict(corporate_unknown=True)):
            with self.subTest(changes=changes):
                changed = deepcopy(raw)
                changed['quotes'][GOLD].update(changes)
                self.assertIsNone(comparison._account_live(changed, self.clock))
        contradictory = deepcopy(raw)
        next(p for p in contradictory['positions'] if p['symbol'] == GOLD)['valuation_status'] = 'stale'
        self.assertIsNone(comparison._account_live(contradictory, self.clock))
        raw['account']['equity'] = '1.00'
        self.assertIsNone(comparison._account_live(raw, self.clock))

    def test_nonfinite_boolean_and_negative_quote_amounts_cannot_match_accepted_quotes(self):
        raw = self.raw_at(10)
        for field in ('price', 'previous_close', 'volume_lots', 'amount_cny'):
            for value in (True, 'NaN', 'Infinity', -1):
                with self.subTest(field=field, value=value):
                    changed = deepcopy(raw)
                    changed['market_observation']['quotes'][GOLD][field] = value
                    self.assertIsNone(comparison._accepted_repeat_batch(changed, self.clock, symbols=[GOLD]))

    def test_model_still_validates_open_started_and_ohlc_after_fallback(self):
        raw = self.raw_at(10)
        for changes in (dict(open=0), dict(started=False), dict(high=12., low=11.)):
            with self.subTest(changes=changes):
                altered = deepcopy(raw)
                altered['market_observation']['quotes'][GOLD].update(changes)
                candidate = self.fallback(altered)
                if candidate is not None:
                    self.assertNotEqual(self.model(candidate)['status'], 'available')


if __name__ == '__main__':
    unittest.main()
