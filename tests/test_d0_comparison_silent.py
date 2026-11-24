"""Strict silent-quote valuation using real temporary source/ledger evidence.

Every account and quote originates from the offline integration fixture. The
resolver must preserve the latest public observation's real timestamps without
changing accepted trading quotes or inventing missing opening-price evidence.
"""
from contextlib import closing
from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import test_d0_comparison_live_integration as fixtures
from realtime_paper_comparison_quotes import DisplayQuoteResolver


class SilentComparisonTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.LiveComparisonIntegrationTests()
        self.addCleanup(self.f.doCleanups)
        self.f.setUp()

    def resolver(self):
        return DisplayQuoteResolver(self.f.home)

    def current_raw(self):
        raw = self.f.ledger.snapshot()
        raw.update(deepcopy(self.f.paper._source_state))
        return raw

    def silent(self, *, after=90, wait=10):
        self.f.clock = fixtures.NOW + timedelta(seconds=after)
        observed = self.f.make_batch(self.f.clock, volume=10002)
        self.f.write_batch(observed)
        batch, reason = self.f.read_source()
        self.assertEqual(reason, 'ready')
        outcome = self.f.ledger.ingest_batch(batch)
        self.assertEqual(len(outcome['ingest_errors']), len(fixtures.SYMBOLS))
        self.assertTrue(all('cumulative trade evidence' in e['reason'] for e in outcome['ingest_errors']))
        raw = self.f.raw_at(after + wait)
        self.assertEqual(raw['quotes'][fixtures.GOLD]['quote_at'], self.f.batch['quotes'][fixtures.GOLD]['quote_at'])
        return raw, observed

    def resolve(self, resolver, raw):
        return resolver.resolve(raw, now=self.f.clock)

    def assert_missing(self, result, symbol=fixtures.GOLD):
        self.assertTrue(result is None or symbol not in result['quotes'])

    def assert_observed(self, result, observed, symbol=fixtures.GOLD):
        self.assertIsNotNone(result)
        self.assertIn(symbol, result['quotes'])
        self.assertEqual(result['source'], observed['source'])
        self.assertEqual(result['received_at'], observed['received_at'])
        for key in ('quote_at', 'day', 'price', 'previous_close', 'open', 'high', 'low',
                    'started', 'volume_lots', 'amount_cny'):
            self.assertEqual(result['quotes'][symbol][key], observed['quotes'][symbol][key])

    def remove_old_archive(self):
        with closing(sqlite3.connect(self.f.path)) as db, db:
            db.execute('DELETE FROM snapshots WHERE received_at=?', (self.f.batch['received_at'],))

    def test_direct_accepted_complete_batch_preserves_provider_payload(self):
        raw = self.current_raw()
        before = deepcopy(raw)
        result = self.resolve(self.resolver(), raw)
        self.assert_observed(result, self.f.batch)
        self.assertEqual(raw, before)
        result['quotes'][fixtures.GOLD]['open'] = 999
        self.assertEqual(raw, before)

    def test_cold_archive_recovers_old_witness_for_fresh_silent_quote(self):
        raw, observed = self.silent()
        self.assertGreater((self.f.clock - fixtures.NOW).total_seconds(), 60)
        self.assertEqual(raw['account']['valuation_status'], 'stale')
        self.assertIsNone(self.f.paper._last_batch)
        before = deepcopy(raw)
        result = self.resolve(self.resolver(), raw)
        self.assert_observed(result, observed)
        self.assertEqual(raw, before)
        model = self.f.model(result)
        self.assertEqual(model['status'], 'available')
        self.assertEqual(model['at'], observed['received_at'])
        self.assertEqual(model['quote_at'], observed['quotes'][fixtures.GOLD]['quote_at'])
        self.assertFalse(self.f.ledger._fresh(raw['quotes'][fixtures.GOLD], self.f.clock))
        self.assertFalse(self.f.paper._ready(raw, self.f.signal, result))

    def test_warmed_cache_retains_original_complete_witness_without_archive(self):
        resolver = self.resolver()
        self.assert_observed(self.resolve(resolver, self.current_raw()), self.f.batch)
        self.remove_old_archive()
        raw, observed = self.silent(after=120)
        self.assert_observed(self.resolve(resolver, raw), observed)

    def test_silent_valuation_does_not_mutate_account_trades_or_accepted_quotes(self):
        raw, observed = self.silent()
        original = self.f.ledger.snapshot()
        resolver = self.resolver()
        result = self.resolve(resolver, raw)
        self.assert_observed(result, observed)
        self.assertEqual(self.f.model(result)['status'], 'available')
        after = self.f.ledger.snapshot()
        for field in ('revision', 'account', 'positions', 'orders', 'fills', 'events', 'signal', 'quotes'):
            self.assertEqual(after[field], original[field])
        self.assertTrue(after['account']['running'])

    def test_account_uses_verified_latest_observation_while_ledger_stays_stale(self):
        raw, observed = self.silent()
        original = deepcopy(raw)
        result = self.resolve(self.resolver(), raw)
        account = fixtures.comparison._account_live(raw, self.f.clock, display_batch=result)
        self.assertIsNotNone(account)
        self.assertEqual(account['equity'], raw['account']['equity'])
        self.assertEqual(account['source_at'], observed['quotes'][fixtures.GOLD]['quote_at'])
        self.assertEqual(account['at'], raw['response_at'])
        self.assertFalse(account.get('cash_only', False))
        self.assertEqual(raw, original)
        self.assertEqual(raw['account']['valuation_status'], 'stale')
        self.assertEqual(raw['quotes'][fixtures.GOLD]['received_at'], self.f.batch['received_at'])
        self.assertIsNone(fixtures.comparison._account_live(raw, self.f.clock))

    def test_multiple_silent_rounds_keep_account_and_model_visible_without_new_trade_evidence(self):
        resolver = self.resolver()
        self.assertIsNotNone(self.resolve(resolver, self.current_raw()))
        original = self.f.ledger.snapshot()
        previous_quote = self.f.batch['quotes'][fixtures.GOLD]['quote_at']
        for elapsed in (90, 120, 180, 300):
            with self.subTest(elapsed=elapsed):
                raw, observed = self.silent(after=elapsed)
                result = self.resolve(resolver, raw)
                self.assert_observed(result, observed)
                account = fixtures.comparison._account_live(raw, self.f.clock, display_batch=result)
                self.assertIsNotNone(account)
                self.assertEqual(account['equity'], original['account']['equity'])
                self.assertEqual(account['source_at'], observed['quotes'][fixtures.GOLD]['quote_at'])
                self.assertGreater(account['source_at'], previous_quote)
                previous_quote = account['source_at']
                model = self.f.model(result)
                self.assertEqual(model['status'], 'available')
                self.assertEqual(model['quote_at'], account['source_at'])
                self.assertEqual(model['at'], observed['received_at'])
                self.assertEqual(raw['quotes'], original['quotes'])
                self.assertEqual(raw['fills'], original['fills'])
                self.assertEqual(raw['orders'], original['orders'])
                self.assertTrue(raw['account']['running'])
                self.assertFalse(self.f.paper._ready(raw, self.f.signal, result))
                self.assertFalse(self.f.ledger._fresh(raw['quotes'][fixtures.GOLD], self.f.clock))

    def test_relevant_rejection_or_inconsistent_account_cannot_be_hidden_by_display_batch(self):
        raw, _ = self.silent()
        resolver = self.resolver()
        result = self.resolve(resolver, raw)
        for kind in ('missing_required', 'account_equity', 'position_price', 'position_quantity'):
            with self.subTest(kind=kind):
                changed, display = deepcopy(raw), deepcopy(result)
                if kind == 'missing_required':
                    display['quotes'].pop(fixtures.GOLD)
                elif kind == 'account_equity':
                    changed['account']['equity'] = '1.00'
                elif kind == 'position_price':
                    next(p for p in changed['positions'] if p['symbol'] == fixtures.GOLD)['price'] = '14.000'
                else:
                    next(p for p in changed['positions'] if p['symbol'] == fixtures.GOLD)['qty'] = True
                self.assertIsNone(fixtures.comparison._account_live(changed, self.f.clock, display_batch=display))

    def test_same_silent_quote_works_in_ready_and_repeat_waiting_states(self):
        raw, observed = self.silent(wait=0)
        self.assertEqual(raw['source_status'], 'ready')
        self.assert_observed(self.resolve(self.resolver(), raw), observed)
        repeated = self.f.raw_at(92)
        self.assertEqual(repeated['source_status'], 'ready')
        self.assertEqual(repeated['observation_state'], 'repeat')
        self.assert_observed(self.resolve(self.resolver(), repeated), observed)
        waiting = self.f.raw_at(100)
        self.assertEqual(waiting['reason'], 'quote_queue_delay')
        self.assert_observed(self.resolve(self.resolver(), waiting), observed)

    def test_silent_latest_observation_still_expires_after_sixty_seconds(self):
        raw, observed = self.silent(wait=59)
        self.assert_observed(self.resolve(self.resolver(), raw), observed)
        for elapsed in (60, 61, 120):
            with self.subTest(elapsed=elapsed):
                stale = self.f.raw_at(90 + elapsed)
                self.assert_missing(self.resolve(self.resolver(), stale))

    def test_changed_price_previous_close_and_cumulative_activity_are_not_silent(self):
        raw, _ = self.silent()
        for field, value in (('price', 13.6), ('previous_close', 12.9),
                             ('volume_lots', 10003), ('volume_lots', 10001),
                             ('amount_cny', 10002 * 1350 + 1), ('amount_cny', 10002 * 1350 - 1)):
            with self.subTest(field=field, value=value):
                changed = deepcopy(raw)
                changed['market_observation']['quotes'][fixtures.GOLD][field] = value
                result = self.resolve(self.resolver(), changed)
                self.assert_missing(result)
                self.assertNotEqual(self.f.model(result)['status'], 'available')

    def test_new_open_high_low_or_started_cannot_replace_original_witness(self):
        raw, _ = self.silent()
        for field, value in (('open', 12.5), ('high', 14.1), ('low', 11.9), ('started', False)):
            with self.subTest(field=field):
                changed = deepcopy(raw)
                changed['market_observation']['quotes'][fixtures.GOLD][field] = value
                self.assert_missing(self.resolve(self.resolver(), changed))

    def test_source_day_and_symbol_identity_cannot_change(self):
        raw, _ = self.silent()
        for field, value in (('source', 'Different source'), ('day', '2026-10-27'),
                             ('symbol', fixtures.SYMBOLS[0])):
            with self.subTest(field=field):
                changed = deepcopy(raw)
                changed['market_observation']['quotes'][fixtures.GOLD][field] = value
                self.assert_missing(self.resolve(self.resolver(), changed))
        raw['market_observation']['source'] = 'Different batch source'
        self.assert_missing(self.resolve(self.resolver(), raw))

    def test_negative_boolean_nonfinite_and_missing_activity_are_rejected(self):
        raw, _ = self.silent()
        for field in ('price', 'previous_close', 'open', 'high', 'low', 'volume_lots', 'amount_cny'):
            for value in (-1, True, 'NaN', 'Infinity', None):
                with self.subTest(field=field, value=value):
                    changed = deepcopy(raw)
                    changed['market_observation']['quotes'][fixtures.GOLD][field] = value
                    self.assert_missing(self.resolve(self.resolver(), changed))

    def test_backward_future_or_cross_session_timestamps_are_rejected(self):
        raw, _ = self.silent(after=30)
        for stamp in ((fixtures.NOW - timedelta(seconds=2)).isoformat(),
                      (self.f.clock + timedelta(seconds=1)).isoformat(),
                      '2026-10-27T10:00:00+08:00'):
            with self.subTest(stamp=stamp):
                changed = deepcopy(raw)
                changed['market_observation']['quotes'][fixtures.GOLD]['quote_at'] = stamp
                self.assert_missing(self.resolve(self.resolver(), changed))
        raw['market_observation']['received_at'] = (fixtures.NOW - timedelta(seconds=2)).isoformat()
        self.assert_missing(self.resolve(self.resolver(), raw))

    def test_current_observation_cannot_cross_lunch_or_next_day(self):
        raw, _ = self.silent()
        self.f.clock = fixtures.NOW.replace(hour=11, minute=30, second=10)
        for q in raw['market_observation']['quotes'].values():
            q['quote_at'] = '2026-10-28T11:29:59+08:00'
        raw['market_observation']['received_at'] = '2026-10-28T11:30:00+08:00'
        self.assert_missing(self.resolve(self.resolver(), raw))
        self.f.clock = fixtures.NOW + timedelta(days=1)
        for q in raw['market_observation']['quotes'].values():
            q.update(day=self.f.clock.date().isoformat(),
                     quote_at=(self.f.clock - timedelta(seconds=1)).isoformat())
        raw['market_observation']['received_at'] = self.f.clock.isoformat()
        self.assert_missing(self.resolve(self.resolver(), raw))

    def test_adverse_current_accepted_or_watermark_status_blocks_relevant_symbol(self):
        raw, _ = self.silent()
        for collection in ('current', 'accepted', 'watermark'):
            for status in ('halted', 'unknown'):
                with self.subTest(collection=collection, status=status):
                    changed = deepcopy(raw)
                    if collection == 'current':
                        changed['market_observation']['quotes'][fixtures.GOLD]['status'] = status
                    elif collection == 'accepted':
                        changed['quotes'][fixtures.GOLD]['status'] = status
                    else:
                        changed.setdefault('status_watermarks', {})[fixtures.GOLD] = dict(
                            symbol=fixtures.GOLD, source=self.f.batch['source'], status=status,
                            quote_at=(fixtures.NOW + timedelta(seconds=80)).isoformat(),
                            received_at=(fixtures.NOW + timedelta(seconds=81)).isoformat())
                    self.assert_missing(self.resolve(self.resolver(), changed))
        for field, value in (('suspended', True), ('corporate_actions_known', False),
                             ('corporate_action_pending', True)):
            with self.subTest(field=field):
                changed = deepcopy(raw)
                changed['market_observation']['quotes'][fixtures.GOLD][field] = value
                self.assert_missing(self.resolve(self.resolver(), changed))
        raw['quotes'][fixtures.GOLD]['corporate_unknown'] = True
        self.assert_missing(self.resolve(self.resolver(), raw))

    def test_rejected_unrelated_symbol_does_not_hide_valid_required_model_quote(self):
        raw, observed = self.silent()
        raw['market_observation']['quotes'][fixtures.SYMBOLS[0]]['price'] = 13.6
        result = self.resolve(self.resolver(), raw)
        self.assert_missing(result, fixtures.SYMBOLS[0])
        self.assert_observed(result, observed)
        self.assertEqual(self.f.model(result)['status'], 'available')
        self.assertIsNotNone(fixtures.comparison._account_live(raw, self.f.clock, display_batch=result))

    def test_history_or_producer_blocked_state_does_not_reuse_warmed_cache(self):
        resolver = self.resolver()
        self.assertIsNotNone(self.resolve(resolver, self.current_raw()))
        raw, _ = self.silent()
        cases = [dict(source_status='blocked', reason='historical_data_revision'),
                 dict(source_status='blocked', reason='history_continuity_review_required'),
                 dict(source_status='blocked', reason='corporate_action_review_required'),
                 dict(source_status='blocked', reason='quotes_collection_state_invalid'),
                 dict(source_status='waiting', reason='quote_precedes_collection_failure'),
                 dict(observation_state='producer_blocked'), dict(observation_state='new_invalid'),
                 dict(observation_state='repeat_invalid')]
        for changes in cases:
            with self.subTest(changes=changes):
                changed = deepcopy(raw)
                changed.update(changes)
                self.assert_missing(self.resolve(resolver, changed))

    def test_ready_source_with_nonready_reason_is_rejected(self):
        raw = self.current_raw()
        self.assertEqual(raw['source_status'], 'ready')
        self.assertEqual(raw['reason'], 'ready')
        self.assert_observed(self.resolve(self.resolver(), raw), self.f.batch)
        for reason in (None, '', 'quote_queue_delay', 'historical_data_revision',
                       'quotes_collection_failed', 'source_read_failed'):
            with self.subTest(reason=reason):
                changed = deepcopy(raw)
                changed['reason'] = reason
                self.assert_missing(self.resolve(self.resolver(), changed))

    def test_current_receipt_override_must_equal_batch_but_archive_uses_effective_receipt(self):
        self.remove_old_archive()
        witness = deepcopy(self.f.batch)
        witness['received_at'] = (fixtures.NOW - timedelta(microseconds=500000)).isoformat()
        witness['source'] = 'Outer archive source overridden by each quote'
        for quote in witness['quotes'].values():
            quote['received_at'] = self.f.batch['received_at']
            quote['source'] = self.f.batch['source']
        with closing(sqlite3.connect(self.f.path)) as db, db:
            db.execute('INSERT INTO snapshots VALUES (?,?,?)',
                       ('effective-original-receipt', witness['received_at'], json.dumps(witness)))
        raw, observed = self.silent()
        matching = deepcopy(raw)
        matching['market_observation']['quotes'][fixtures.GOLD]['received_at'] = observed['received_at']
        result = self.resolve(self.resolver(), matching)
        self.assert_observed(result, observed)
        self.assertEqual(self.f.model(result)['status'], 'available')
        for delta in (-.5, .5):
            with self.subTest(delta=delta):
                changed = deepcopy(matching)
                changed['market_observation']['quotes'][fixtures.GOLD]['received_at'] = (
                    fixtures.NOW + timedelta(seconds=90 + delta)).isoformat()
                result = self.resolve(self.resolver(), changed)
                self.assert_missing(result)
                self.assert_observed(result, observed, fixtures.SYMBOLS[0])

    def test_real_producer_failure_blocks_an_otherwise_matching_silent_quote(self):
        raw, _ = self.silent()
        self.f.clock = fixtures.NOW + timedelta(seconds=101)
        with closing(sqlite3.connect(self.f.path)) as db, db:
            db.execute('INSERT INTO attempts VALUES (?,?,?)',
                       ('synthetic-producer-failure', self.f.clock.isoformat(), '失败'))
        blocked = self.f.raw_at(102)
        self.assertNotEqual(blocked['reason'], 'quote_queue_delay')
        self.assert_missing(self.resolve(self.resolver(), blocked))

    def test_cold_missing_original_archive_never_guesses_opening_fields(self):
        self.remove_old_archive()
        raw, _ = self.silent()
        self.assert_missing(self.resolve(self.resolver(), raw))

    def test_cold_missing_database_fails_closed(self):
        raw, _ = self.silent()
        self.f.path.unlink()
        self.assert_missing(self.resolve(self.resolver(), raw))

    def test_cold_ambiguous_original_opening_payload_is_rejected(self):
        ambiguous = deepcopy(self.f.batch)
        ambiguous['quotes'][fixtures.GOLD]['open'] = 12.5
        with closing(sqlite3.connect(self.f.path)) as db, db:
            db.execute('INSERT INTO snapshots VALUES (?,?,?)',
                       ('same-accepted-identity-different-open', ambiguous['received_at'], json.dumps(ambiguous)))
        raw, observed = self.silent()
        result = self.resolve(self.resolver(), raw)
        self.assert_missing(result)
        # The ambiguity belongs to GOLD; unrelated rows have identical evidence.
        if result is not None:
            self.assert_observed(result, observed, fixtures.SYMBOLS[0])

    def test_direct_same_ledger_identity_does_not_bypass_archived_ohlc_conflict(self):
        raw = self.current_raw()
        ambiguous = deepcopy(self.f.batch)
        ambiguous['quotes'][fixtures.GOLD]['open'] = 12.5
        with closing(sqlite3.connect(self.f.path)) as db, db:
            db.execute('INSERT INTO snapshots VALUES (?,?,?)',
                       ('direct-key-conflicting-complete-payload', ambiguous['received_at'], json.dumps(ambiguous)))
        result = self.resolve(self.resolver(), raw)
        self.assert_missing(result)
        self.assertNotEqual(self.f.model(result)['status'], 'available')

    def test_direct_same_ledger_identity_cannot_invent_or_replace_opening_evidence(self):
        raw = self.current_raw()
        for field, value in (('open', 12.5), ('high', 14.1), ('low', 11.9)):
            with self.subTest(field=field):
                changed = deepcopy(raw)
                changed['market_observation']['quotes'][fixtures.GOLD][field] = value
                self.assert_missing(self.resolve(self.resolver(), changed))
        self.remove_old_archive()
        self.assert_missing(self.resolve(self.resolver(), raw))

    def test_rejected_current_payload_cannot_poison_witness_cache(self):
        raw = self.current_raw()
        resolver = self.resolver()
        self.assert_observed(self.resolve(resolver, raw), self.f.batch)
        changed = deepcopy(raw)
        changed['market_observation']['quotes'][fixtures.GOLD]['open'] = 12.5
        self.assert_missing(self.resolve(resolver, changed))
        self.assert_observed(self.resolve(resolver, raw), self.f.batch)

    def test_archive_read_does_not_change_any_record(self):
        raw, observed = self.silent()
        with closing(sqlite3.connect(self.f.path)) as db:
            before = db.execute('SELECT rowid,id,received_at,payload FROM snapshots ORDER BY rowid').fetchall()
            attempts = db.execute('SELECT rowid,id,attempted_at,status FROM attempts ORDER BY rowid').fetchall()
        self.assert_observed(self.resolve(self.resolver(), raw), observed)
        with closing(sqlite3.connect(self.f.path)) as db:
            self.assertEqual(db.execute('SELECT rowid,id,received_at,payload FROM snapshots ORDER BY rowid').fetchall(), before)
            self.assertEqual(db.execute('SELECT rowid,id,attempted_at,status FROM attempts ORDER BY rowid').fetchall(), attempts)


if __name__ == '__main__':
    unittest.main()
