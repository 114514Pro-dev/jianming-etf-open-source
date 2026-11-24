"""Synthetic D0 history and quote isolation; no production data or networking."""
from copy import deepcopy
from contextlib import closing
from datetime import datetime, timedelta
import json
import os
import sqlite3
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
from realtime_paper_history import AcceptedHistory, HistoryContinuityError, digest
from realtime_paper_service import ReadOnlyPaperSource, PaperService, SYMBOLS, TZ
from realtime_paper_engine import PaperLedger


def daily(days=('2026-10-20',)):
    return {group: {'bars': {symbol: [dict(date=day, open=10., close=10., high=10., low=10.,
                    volume_lots=1000., amount_cny=1000000.) for day in days] for symbol in SYMBOLS},
                    'corporate_actions': {}, 'split_adjustments': {}}
            for group in ('chi', 'bank')}


class SyntheticMarket:
    def __init__(self, data):
        self.data = data

    def observation(self, code, day):
        return {'weights': {'sh518880': 1}, 'reason': 'Synthetic confirmed D0'}

    def at(self, day):
        return {'dates': {s: day for s in SYMBOLS}, 'prices': {s: 10 for s in SYMBOLS}}


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('ETF_TEST_TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.clock = datetime(2026, 10, 21, 10, tzinfo=TZ)
        self.old = daily()
        self.original_path = self.publish(self.old)
        self.previous = dict(history_cutoff='2026-10-20',
                             history_hash=ReadOnlyPaperSource._history_hash(self.old, '2026-10-20'))
        self.new = daily(('2026-10-20', '2026-10-21', '2026-10-22'))
        self.new['chi']['bars']['sz159915'][0]['volume_lots'] = 2000.
        self.archive = self.new_archive()

    def publish(self, data):
        identity = digest(data)
        path = self.home / '行情快照' / (identity + '.json')
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(data), encoding='utf8')
        (self.home / '设置.json').write_text(json.dumps({'market': identity}), encoding='utf8')
        return path

    def new_archive(self):
        return AcceptedHistory(self.home, ReadOnlyPaperSource._history_hash,
                               ReadOnlyPaperSource._truncate, deepcopy, digest)

    def reconcile(self, data=None):
        data = self.new if data is None else data
        return self.archive.reconcile(data, self.previous, digest(data))

    def test_exact_old_hash_anchor_and_complete_old_rows_survive(self):
        before = self.original_path.read_bytes()
        output, evidence = self.reconcile()
        self.assertEqual(output['chi']['bars']['sz159915'][0], self.old['chi']['bars']['sz159915'][0])
        self.assertEqual(output['chi']['bars']['sz159915'][1:], self.new['chi']['bars']['sz159915'][1:])
        meta = self.archive.commit(output, '2026-10-22', digest(self.new), evidence, self.clock.isoformat())
        self.assertTrue(meta['retained'])
        self.assertEqual(self.original_path.read_bytes(), before)
        self.assertEqual(evidence['changes'][0]['rows'][0]['observed']['volume_lots'], 2000.)

    def test_checkpoint_recovers_next_session_and_process_restart(self):
        output, evidence = self.reconcile()
        self.archive.commit(output, '2026-10-22', digest(self.new), evidence, self.clock.isoformat())
        previous = dict(history_cutoff='2026-10-22', history_hash=ReadOnlyPaperSource._history_hash(output, '2026-10-22'))
        later = deepcopy(self.new)
        for group in later.values():
            for rows in group['bars'].values():
                rows.append(dict(rows[-1], date='2026-10-23'))
        result, _ = self.new_archive().reconcile(later, previous, digest(later))
        self.assertEqual(ReadOnlyPaperSource._history_hash(result, '2026-10-22'), previous['history_hash'])
        self.assertEqual(result['chi']['bars']['sz159915'][-1]['date'], '2026-10-23')

    def test_missing_or_tampered_original_snapshot_never_authorizes(self):
        self.original_path.write_text(json.dumps(self.new), encoding='utf8')
        with self.assertRaisesRegex(HistoryContinuityError, 'baseline_missing'):
            self.reconcile()

    def test_unverified_source_cannot_recover(self):
        for reference in (None, 'a'*64):
            with self.subTest(reference=reference), self.assertRaises(HistoryContinuityError):
                self.archive.reconcile(self.new, self.previous, reference)

    def test_missing_inserted_or_duplicate_history_stays_blocked(self):
        for kind in ('missing', 'inserted', 'duplicate'):
            value = deepcopy(self.new)
            rows = value['chi']['bars']['sz159915']
            if kind == 'missing':
                rows.pop(0)
            elif kind == 'inserted':
                rows.insert(0, dict(rows[0], date='2026-10-19'))
            else:
                rows.insert(0, deepcopy(rows[0]))
            with self.subTest(kind=kind), self.assertRaisesRegex(HistoryContinuityError, 'continuity_gap'):
                self.reconcile(value)

    def test_company_actions_and_adjustment_changes_stay_blocked(self):
        for key in ('corporate_actions', 'split_adjustments', 'attack_symbol'):
            value = deepcopy(self.new); value['bank'][key] = {'changed': True}
            with self.subTest(key=key), self.assertRaisesRegex(HistoryContinuityError, 'corporate_action'):
                self.reconcile(value)

    def test_same_hash_metadata_change_is_blocked_by_checkpoint(self):
        self.archive.commit(self.old, '2026-10-20', digest(self.old), None, self.clock.isoformat())
        changed = deepcopy(self.old)
        changed['chi']['split_adjustments'] = {'sh518880': {'2026-10-20': 2.0}}
        self.assertEqual(ReadOnlyPaperSource._history_hash(changed, '2026-10-20'),
                         self.previous['history_hash'])
        self.publish(changed)
        for reference in (digest(changed), None):
            with self.subTest(reference=reference), self.assertRaisesRegex(
                    HistoryContinuityError, 'corporate_action_review_required'):
                self.new_archive().reconcile(changed, self.previous, reference)
        with self.assertRaisesRegex(HistoryContinuityError, 'corporate_action_review_required'):
            self.archive.commit(changed, '2026-10-20', digest(changed), None, self.clock.isoformat())

    def test_same_hash_migration_rejects_ambiguous_metadata(self):
        changed = deepcopy(self.old)
        changed['chi']['split_adjustments'] = {'sh518880': {'2026-10-20': 2.0}}
        self.publish(changed)
        self.assertEqual(ReadOnlyPaperSource._history_hash(changed, '2026-10-20'),
                         self.previous['history_hash'])
        # Whichever matching file is newest, neither metadata set is proven.
        for data in (changed, self.old):
            with self.subTest(data=data['chi']['split_adjustments']), self.assertRaisesRegex(
                    HistoryContinuityError, 'corporate_action_review_required'):
                self.new_archive().reconcile(data, self.previous, digest(data))

    def test_normal_same_hash_migration_is_cached_and_can_append(self):
        later = daily(('2026-10-20', '2026-10-21', '2026-10-22'))
        self.publish(later)
        with patch.object(self.archive, 'validate', wraps=deepcopy) as validate:
            output, evidence = self.archive.reconcile(later, self.previous, digest(later))
            count = validate.call_count
            self.assertGreater(count, 0)
            self.assertEqual(output, later)
            self.assertIsNone(evidence)
            self.archive.reconcile(later, self.previous, digest(later))
            self.assertEqual(validate.call_count, count)
        self.archive.commit(output, '2026-10-22', digest(later), evidence, self.clock.isoformat())
        following = dict(history_cutoff='2026-10-22',
                         history_hash=ReadOnlyPaperSource._history_hash(later, '2026-10-22'))
        with patch.object(Path, 'glob', side_effect=AssertionError('checkpoint must not scan archive')):
            result, evidence = self.new_archive().reconcile(later, following, digest(later))
        self.assertEqual(result, later)
        self.assertIsNone(evidence)

    def test_ambiguous_migration_error_does_not_repeat_scan(self):
        changed = deepcopy(self.old)
        changed['chi']['split_adjustments'] = {'changed': True}
        self.publish(changed)
        with self.assertRaisesRegex(HistoryContinuityError, 'corporate_action_review_required'):
            self.archive.reconcile(changed, self.previous, digest(changed))
        with patch.object(Path, 'glob', side_effect=AssertionError('unchanged archive must not rescan')):
            with self.assertRaisesRegex(HistoryContinuityError, 'corporate_action_review_required'):
                self.archive.reconcile(changed, self.previous, digest(changed))

    def test_initial_and_unchanged_seed_data_remain_supported(self):
        for previous in ({}, self.previous):
            output, evidence = self.new_archive().reconcile(self.old, previous, None)
            self.assertEqual(output, self.old)
            self.assertIsNone(evidence)
        with self.assertRaisesRegex(HistoryContinuityError, 'historical_data_revision'):
            self.archive.reconcile(self.old, self.previous, 'a' * 64)

    def test_migration_scan_limit_does_not_assume_unseen_metadata(self):
        for index in range(256):
            value = deepcopy(self.old)
            value['chi']['published_at'] = index
            self.publish(value)
        with self.assertRaisesRegex(HistoryContinuityError, 'history_baseline_missing'):
            self.archive.reconcile(self.old, self.previous, digest(self.old))

    def test_audit_write_failure_cannot_publish_checkpoint(self):
        output, evidence = self.reconcile()
        with patch('realtime_paper_history.durable_json', side_effect=OSError('synthetic full disk')):
            with self.assertRaises(OSError):
                self.archive.commit(output, '2026-10-22', digest(self.new), evidence, self.clock.isoformat())
        self.assertFalse(self.archive.folder.exists())

    def test_corrupted_checkpoint_is_not_rebuilt_or_reset(self):
        output, evidence = self.reconcile()
        self.archive.commit(output, '2026-10-22', digest(self.new), evidence, self.clock.isoformat())
        path = next((self.archive.folder / 'checkpoints').glob('*.json'))
        value = json.loads(path.read_text()); value['data']['chi']['bars']['sz159915'][0]['close'] = 99
        path.write_text(json.dumps(value), encoding='utf8'); damaged = path.read_bytes()
        previous = dict(history_cutoff='2026-10-22', history_hash=ReadOnlyPaperSource._history_hash(output, '2026-10-22'))
        with self.assertRaisesRegex(HistoryContinuityError, 'checkpoint_invalid'):
            self.new_archive().reconcile(self.new, previous, digest(self.new))
        self.assertEqual(path.read_bytes(), damaged)

    def source(self):
        return ReadOnlyPaperSource(self.home, now=lambda: self.clock, market_factory=SyntheticMarket,
                    spec_factory=lambda _: {'synthetic': True}, validator=deepcopy, digester=digest)

    def quote(self, sequence=0):
        self.clock += timedelta(seconds=2)
        batch = dict(source='synthetic public quote', received_at=self.clock.isoformat(),
            quotes={s: dict(symbol=s, price=10., previous_close=10., quote_at=self.clock.isoformat(),
                            volume_lots=1000 + sequence*100, amount_cny=1000000 + sequence*100000)
                    for s in SYMBOLS})
        with closing(sqlite3.connect(self.home / '盘中行情.sqlite3')) as connection:
            connection.execute('CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY, received_at TEXT, payload TEXT)')
            connection.execute('INSERT INTO snapshots VALUES(?,?,?)', (digest(batch), batch['received_at'], json.dumps(batch)))
            connection.commit()
        return batch

    def test_service_recovery_preserves_fills_running_and_replay(self):
        ledger = PaperLedger(self.home / 'ledger', now=lambda: self.clock)
        service = PaperService(self.home, source=self.source(), ledger=ledger, now=lambda: self.clock, start_worker=False)
        self.addCleanup(service.close)
        service.create('100000.00', idempotency_key='isolated-create')
        service.set_running(True, idempotency_key='isolated-start')
        for sequence in range(4):
            self.quote(sequence); service.poll_once()
        before = service.snapshot()
        self.assertEqual(len(before['fills']), 1)
        self.publish(self.new)
        self.clock = datetime(2026, 10, 23, 10, tzinfo=TZ)
        self.quote(5); after = service.poll_once()
        self.assertEqual(after['source_status'], 'ready')
        self.assertEqual(after['signal']['confirmed_day'], '2026-10-22')
        self.assertEqual(after['fills'], before['fills'])
        self.assertEqual(after['orders'][:len(before['orders'])], before['orders'])
        for key in ('id', 'initial_capital', 'running', 'resumed_at', 'activation_generation', 'fees'):
            self.assertEqual(after['account'][key], before['account'][key])
        repeated = service.poll_once()
        self.assertEqual(repeated['fills'], after['fills'])
        self.assertEqual(repeated['orders'], after['orders'])
        service.source = self.source()
        restarted = service.poll_once()
        self.assertEqual(restarted['source_status'], 'ready')
        self.assertEqual(restarted['fills'], before['fills'])

    def test_blocked_source_exposes_new_quote_without_accepting_it(self):
        ledger = PaperLedger(self.home / 'ledger', now=lambda: self.clock)
        service = PaperService(self.home, source=self.source(), ledger=ledger, now=lambda: self.clock, start_worker=False)
        self.addCleanup(service.close)
        service.create('100000.00')
        self.quote(0); old = service.poll_once()
        value = deepcopy(self.new); value['bank']['corporate_actions'] = {'review': True}
        self.publish(value); self.clock = datetime(2026, 10, 23, 10, tzinfo=TZ)
        batch = self.quote(1); blocked = service.poll_once()
        self.assertEqual(blocked['reason'], 'corporate_action_review_required')
        self.assertEqual(blocked['quotes'], old['quotes'])
        self.assertEqual(blocked['market_observation'], batch)
        self.assertEqual(blocked['orders'], [])
        self.assertFalse(blocked['account']['running'])
        from server import PaperHttpAdapter
        view = PaperHttpAdapter(service).snapshot()
        self.assertEqual(len(view['market_quotes']), 4)
        self.assertTrue(all(q['display_only'] and q['fresh'] for q in view['market_quotes']))
        self.assertTrue(all(q['quote_at'].startswith('2026-10-21') for q in view['quotes']))
        self.assertEqual(view['accounts'][0]['execution_state'], 'stopped')
        self.assertEqual(PaperHttpAdapter(service).view(blocked, command=True)['market_quotes'], [])

    def test_failed_checkpoint_keeps_signal_and_orders_unchanged(self):
        source = self.source(); self.quote(0)
        previous = source.read()['signal']
        self.publish(self.new); self.clock = datetime(2026, 10, 23, 10, tzinfo=TZ); self.quote(1)
        with patch('realtime_paper_history.durable_json', side_effect=OSError('synthetic full disk')):
            blocked = source.read(previous)
        self.assertEqual(blocked['reason'], 'history_checkpoint_write_failed')
        self.assertIsNone(blocked['signal'])
        self.assertIsNone(blocked['batch'])

    def test_calendar_failure_still_returns_quote_observation(self):
        source = self.source(); batch = self.quote(0)
        with patch.object(source, '_expected', side_effect=ValueError('calendar unavailable')):
            result = source.read()
        self.assertEqual(result['source_status'], 'blocked')
        self.assertEqual(result['observed_batch'], batch)


if __name__ == '__main__':
    unittest.main()
