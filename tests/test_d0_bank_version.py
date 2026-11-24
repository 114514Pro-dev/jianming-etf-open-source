"""D0 version transition on disposable synthetic accounts, never user ledgers."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
import bank_model as model
import trade_book as native
from automation import AutoBook
from suite_book import SuiteBook


CODES = native.CODES
CHI, BANK, GOLD, BOND = CODES
DAYS = ['2026-10-23', '2026-10-26', '2026-10-27']


def weights(symbol):
    return {code: float(code == symbol) for code in CODES}


class SyntheticMarket:
    provisional = False
    dates = DAYS
    latest = DAYS[-1]
    hash = 'synthetic-d0-rule-transition'

    def __init__(self):
        self.inputs = SimpleNamespace(actions={c: {'dividends': []} for c in CODES},
                                      splits={c: {} for c in CODES})
        self.targets = {DAYS[0]: GOLD, DAYS[1]: GOLD, DAYS[2]: GOLD}
        self.fail = False

    def at(self, day, opening=False):
        return dict(day=day, market_hash=self.hash, prices={c: 10. for c in CODES},
                    dates={c: day for c in CODES})

    def observation(self, code, day):
        if self.fail:
            raise ValueError('synthetic unavailable signal')
        return dict(day=day, strategy=code, weights=weights(self.targets[day]),
                    reason='Synthetic confirmed target', features={}, state='dynamic')


class D0VersionTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.market = SyntheticMarket()
        self.book = SuiteBook(self.folder.name)

    def database(self):
        with self.book.connection() as con:
            return tuple(con.execute('SELECT * FROM accounts').fetchall()), tuple(con.execute('SELECT * FROM events ORDER BY rowid').fetchall())

    def write_state(self, state):
        native.validate(state)
        with self.book.connection() as con:
            con.execute('UPDATE accounts SET payload=? WHERE id=?',
                        (json.dumps(state, ensure_ascii=False), state['id']))

    def legacy_account(self, *, execution='auto', strategy='D0'):
        options = dict(execution=execution) if isinstance(self.book, SuiteBook) else {}
        created = self.book.create('Synthetic preserved history', 100000, DAYS[0], self.market,
                                   strategy=strategy, **options)
        # Establish genuine prior fills and curves using a disposable native book.
        state = self.book.advance(created['id'], self.market, DAYS[1])
        state['auto'].update(spec_hash=model.digest(model.legacy_d0_spec()),
                             evaluated=DAYS[1], watch=True,
                             last_observation=dict(day=DAYS[1], reason='Saved legacy evidence'))
        state['pending'] = dict(id='synthetic-old-order', day=DAYS[1],
                                weights=weights(BANK), reasons=['Saved legacy target'])
        self.write_state(state)
        return deepcopy(state)

    def test_get_export_and_watched_preserve_saved_version_and_database(self):
        old = self.legacy_account()
        before = self.database()
        self.assertEqual(self.book.get(old['id']), old)
        self.assertEqual(self.book.watched(), old)
        exported = self.book.export(old['id'])
        self.assertEqual(exported['account'], old)
        self.assertEqual(self.database(), before)

    def test_same_close_upgrade_preserves_economics_history_and_preferences(self):
        old = self.legacy_account()
        prior_events = list(reversed(self.book.events(old['id'])))
        self.market.targets[DAYS[1]] = BOND
        current = self.book.advance(old['id'], self.market, DAYS[1])
        for field in ('cash', 'positions', 'realized', 'dividends', 'fees', 'receivables',
                      'entitlements', 'processed', 'curve', 'last_target', 'day', 'start', 'initial'):
            self.assertEqual(current[field], old[field], field)
        self.assertTrue(current['auto']['watch'])
        self.assertEqual(current['auto'].get('execution', 'auto'), 'auto')
        self.assertEqual(current['auto']['spec_hash'], model.digest(model.spec('D0')))
        self.assertEqual(current['pending']['weights'], weights(BOND))
        self.assertEqual(current['pending']['day'], DAYS[1])
        events = list(reversed(self.book.events(old['id'])))
        self.assertEqual(events[:len(prior_events)], prior_events)
        self.assertEqual(sum(e['kind'] == '更新D0策略版本' for e in events), 1)
        self.book.advance(old['id'], self.market, DAYS[1])
        self.assertEqual(self.book.events(old['id']), list(reversed(events)))

    def test_direct_next_day_advance_cannot_execute_legacy_pending_target(self):
        old = self.legacy_account()
        self.market.targets[DAYS[1]] = BOND
        self.market.targets[DAYS[2]] = BOND
        current = self.book.advance(old['id'], self.market, DAYS[2])
        self.assertEqual(current['positions'][BANK]['qty'], 0)
        self.assertGreater(current['positions'][BOND]['qty'], 0)
        self.assertEqual(current['curve'][:len(old['curve'])], old['curve'])
        fills = [e['data'] for e in self.book.events(old['id']) if e['kind'] == '策略成交']
        self.assertFalse(any(f['symbol'] == BANK for f in fills))
        bond_fill = next(f for f in fills if f['symbol'] == BOND)
        self.assertEqual(bond_fill['signal_day'], DAYS[1])
        self.assertEqual(bond_fill['day'], DAYS[2])

    def test_review_evidence_retains_actual_version_transition(self):
        from suite_analysis import evidence
        old = self.legacy_account()
        self.market.targets[DAYS[1]] = BOND
        self.book.advance(old['id'], self.market, DAYS[2])
        transition = next(e for e in self.book.events(old['id']) if e['kind'] == '更新D0策略版本')
        self.market.data = {'chi': {}, 'bank': {}}
        with patch('suite_analysis.total_return_series', return_value=[]):
            # The version node remains visible even when it predates the
            # selected return window, so current rules are not applied to old fills.
            selected = evidence(self.book, old['id'], self.market, DAYS[2], DAYS[2])
            prior = evidence(self.book, old['id'], self.market, DAYS[0], DAYS[0])
        self.assertEqual(selected['packet']['strategy_changes'], [transition])
        self.assertEqual(transition['data']['previous_spec_hash'], old['auto']['spec_hash'])
        self.assertEqual(transition['data']['current_spec_hash'], model.digest(model.spec('D0')))
        self.assertEqual(prior['packet']['strategy_changes'], [])

    def test_failed_new_signal_rolls_back_version_and_cancellation_together(self):
        old = self.legacy_account()
        before = self.database()
        self.market.fail = True
        with self.assertRaisesRegex(ValueError, 'unavailable signal'):
            self.book.advance(old['id'], self.market, DAYS[2])
        self.assertEqual(self.database(), before)
        self.assertEqual(self.book.get(old['id']), old)

    def test_manual_rehearsal_order_is_preserved_on_signal_upgrade(self):
        old = self.legacy_account(execution='paper')
        self.market.targets[DAYS[1]] = BOND
        current = self.book.advance(old['id'], self.market, DAYS[1])
        self.assertEqual(current['pending'], old['pending'])
        self.assertEqual(current['positions'], old['positions'])
        self.assertEqual(current['auto']['execution'], 'paper')
        self.assertEqual(current['auto']['spec_hash'], model.digest(model.spec('D0')))
        self.assertEqual(current['auto']['last_observation']['weights'], weights(BOND))

    def test_legacy_backup_import_preserves_original_and_defers_upgrade(self):
        old = self.legacy_account()
        payload = self.book.export(old['id'])
        copied = self.book.import_copy(payload)
        self.assertNotEqual(copied['id'], old['id'])
        self.assertEqual(self.book.get(old['id']), old)
        for field in ('positions', 'cash', 'curve', 'fees', 'dividends', 'realized'):
            self.assertEqual(copied[field], old[field])
        self.assertEqual(copied['auto']['spec_hash'], old['auto']['spec_hash'])
        self.assertFalse(copied['auto']['watch'])
        self.assertIsNone(copied['pending'])
        advanced = self.book.advance(copied['id'], self.market, DAYS[1])
        self.assertEqual(advanced['auto']['spec_hash'], model.digest(model.spec('D0')))

    def test_unknown_hash_and_legacy_hash_on_other_strategy_remain_rejected(self):
        old = self.legacy_account()
        payload = self.book.export(old['id'])
        for strategy, fingerprint in [('D0', 'unrecognized-spec'), ('D5', old['auto']['spec_hash'])]:
            with self.subTest(strategy=strategy):
                invalid = deepcopy(old)
                invalid['auto'].update(strategy=strategy, spec_hash=fingerprint)
                self.write_state(invalid)
                with self.assertRaisesRegex(ValueError, '策略版本不匹配'):
                    self.book.get(old['id'])
                backup = deepcopy(payload)
                backup['account'] = invalid
                backup['sha256'] = native.digest({k: v for k, v in backup.items() if k != 'sha256'})
                with self.assertRaisesRegex(ValueError, '策略版本不匹配'):
                    self.book.import_copy(backup)

    def test_current_other_strategy_does_not_migrate(self):
        created = self.book.create('D5 unchanged', 100000, DAYS[0], self.market, strategy='D5')
        first = self.book.advance(created['id'], self.market, DAYS[0])
        self.assertEqual(first['auto']['spec_hash'], model.digest(model.spec('D5')))
        self.assertFalse(any(e['kind'] == '更新D0策略版本' for e in self.book.events(created['id'])))

    def test_plain_autobook_preserves_prior_same_day_close_event(self):
        self.book = AutoBook(self.folder.name)
        old = self.legacy_account()
        with self.book.connection() as con:
            legacy_key = model.digest(dict(account=old['id'], day=DAYS[1], kind='close'))
            self.book.event(con, old, '收盘分析', dict(reason='Legacy fixed event ID'), legacy_key)
        # The previously created current-version event is synthetic setup, not a
        # real legacy row. Remove only that fixture event before the transition.
        current_key = model.digest(dict(account=old['id'], day=DAYS[1], kind='close',
                                        spec_hash=model.digest(model.spec('D0'))))
        with self.book.connection() as con:
            con.execute('DELETE FROM events WHERE id=?', (current_key,))
        self.market.targets[DAYS[1]] = BOND
        current = self.book.advance(old['id'], self.market, DAYS[1])
        self.assertEqual(current['pending']['weights'], weights(BOND))
        self.assertIn(legacy_key, [event['id'] for event in self.book.events(old['id'])])


if __name__ == '__main__':
    unittest.main()
