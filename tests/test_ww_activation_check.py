"""The deployment evidence reader is independent of application writers."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import sqlite3
from contextlib import closing
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ww_activation', ROOT / 'scripts/check_ww_activation.py')
activation = importlib.util.module_from_spec(spec); spec.loader.exec_module(activation)


class ActivationEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.state = {'revision': 3, 'account': {'id': 'D0-forward-paper', 'strategy': 'D0',
            'name': 'PRIVATE ACCOUNT NAME', 'initial_capital': '123456.78', 'cash': '98765.43',
            'running': True, 'created_at': '2026-10-01T12:00:00+08:00'},
            'fills': [{'id': 'old-fill', 'quantity': 100, 'price': '12.345'}],
            'positions': {'sh511010': [{'qty': 100, 'price': '12.345'}]}, 'orders': [],
            'quotes': {'old': 'cached'}, 'signal': None, 'plan': None}
        self.save('D0', self.state)
        (self.root / 'web/settings.json').write_text(json.dumps({'auto_refresh': True,
            'auto_simulate': False, 'paused_accounts': []}), encoding='utf-8')
        # Invalid credential content would fail if the checker tried to parse it.
        (self.root / 'web/auth.json').write_text('DO NOT READ AUTH', encoding='utf-8')

    def tearDown(self): self.temp.cleanup()

    def save(self, code, state):
        target = self.root / activation.DBS[code]; target.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(target)) as db:
            db.execute('CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY,data TEXT)')
            db.execute('INSERT OR REPLACE INTO ledger VALUES(1,?)', (json.dumps(state),)); db.commit()

    def ww_empty(self): self.save('D0I-BOND-WW', {'account': None, 'fills': [], 'positions': {}, 'orders': []})

    def test_new_empty_ww_and_normal_restart_changes_pass_without_private_values(self):
        before = activation.capture(self.root)
        self.ww_empty()
        after_state = deepcopy(self.state); after_state.update(revision=8, quotes={'new': 'cached'},
            signal={'new': 'signal'}, plan={'new': 'plan'}, observations={})
        self.save('D0', after_state)
        value = activation.compare(before, activation.capture(self.root, require_ww=True))
        self.assertEqual(value['status'], 'passed')
        text = json.dumps(value)
        for secret in ('PRIVATE ACCOUNT NAME', '123456.78', '98765.43', '12.345', 'old-fill'):
            self.assertNotIn(secret, text)

    def test_appended_fill_requires_review_but_old_history_corruption_fails(self):
        before = activation.capture(self.root); self.ww_empty()
        changed = deepcopy(self.state); changed['fills'].append({'id': 'new-fill'})
        changed['positions'] = {}
        self.save('D0', changed)
        self.assertEqual(activation.compare(before, activation.capture(self.root))['status'], 'review_required')
        changed['fills'][0]['quantity'] = 200; self.save('D0', changed)
        self.assertEqual(activation.compare(before, activation.capture(self.root))['status'], 'failed')

    def test_legacy_missing_d0_strategy_is_the_same_identity_as_explicit_d0(self):
        legacy = deepcopy(self.state); del legacy['account']['strategy']
        self.save('D0', legacy)
        path = self.root / activation.DBS['D0']; raw = path.read_bytes()
        before = activation.capture(self.root)
        self.assertEqual(before['ledgers']['D0']['strategy'], 'D0')
        self.assertEqual(path.read_bytes(), raw)
        self.ww_empty(); self.save('D0', self.state)
        after = activation.capture(self.root, require_ww=True)
        self.assertEqual(before['ledgers']['D0']['account_core_hash'], after['ledgers']['D0']['account_core_hash'])
        self.assertEqual(activation.compare(before, after)['status'], 'passed')

    def test_missing_strategy_is_not_a_default_for_ww_or_an_explicit_bad_d0_value(self):
        for invalid in (None, '', 'D0I-BOND-WW'):
            changed = deepcopy(self.state); changed['account']['strategy'] = invalid
            self.save('D0', changed)
            with self.assertRaises(ValueError): activation.capture(self.root)
        self.save('D0', self.state)
        changed = deepcopy(self.state); del changed['account']['strategy']
        changed['account']['id'] = 'D0I-BOND-WW-forward-paper'
        self.save('D0I-BOND-WW', changed)
        with self.assertRaises(ValueError): activation.capture(self.root)

    def test_worker_auto_pause_requires_review_and_order_expiry_is_not_data_loss(self):
        before = activation.capture(self.root); self.ww_empty()
        changed = deepcopy(self.state); changed['account']['running'] = False
        self.save('D0', changed)
        value = activation.compare(before, activation.capture(self.root))
        self.assertEqual(value['status'], 'review_required')
        self.assertTrue(all(check['passed'] for check in value['checks']))
        self.assertIn('D0:running_state_changed', value['runtime_changes'])
        changed = deepcopy(self.state); changed['orders'] = [{'status': 'pending'}]
        self.save('D0', changed); before = activation.capture(self.root)
        changed['orders'] = [{'status': 'expired'}]; changed['revision'] += 1
        self.save('D0', changed)
        self.assertEqual(activation.compare(before, activation.capture(self.root))['status'], 'passed')

    def test_cash_change_without_new_fills_is_not_silently_accepted(self):
        before = activation.capture(self.root); self.ww_empty()
        changed = deepcopy(self.state); changed['account']['cash'] = '0.00'
        self.save('D0', changed)
        result = activation.compare(before, activation.capture(self.root))
        self.assertEqual(result['status'], 'failed')
        self.assertIn({'check': 'D0:cash_preserved_without_new_fills', 'passed': False}, result['checks'])
        changed['fills'].append({'id': 'new-fill'})
        self.save('D0', changed)
        self.assertEqual(activation.compare(before, activation.capture(self.root))['status'], 'review_required')

    def test_ww_automatic_creation_and_automation_changes_fail(self):
        before = activation.capture(self.root); self.ww_empty()
        changed = deepcopy(self.state); changed['account']['id'] = 'D0I-BOND-WW-forward-paper'
        changed['account']['strategy'] = 'D0I-BOND-WW'; changed['account']['running'] = False
        changed.update(fills=[], positions={})
        self.save('D0I-BOND-WW', changed)
        self.assertEqual(activation.compare(before, activation.capture(self.root))['status'], 'failed')
        self.ww_empty()
        (self.root / 'web/settings.json').write_text('{"auto_refresh":false}', encoding='utf-8')
        self.assertEqual(activation.compare(before, activation.capture(self.root))['status'], 'failed')

    def test_baseline_is_exclusive_outside_data_and_ledger_reads_leave_bytes_unchanged(self):
        path = self.root / activation.DBS['D0']; before = path.read_bytes()
        snapshot = activation.capture(self.root)
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaises(ValueError): activation.write_baseline(self.root / 'inside.json', snapshot, self.root)
        with tempfile.TemporaryDirectory() as destination:
            target = Path(destination) / 'baseline.json'
            activation.write_baseline(target, snapshot, self.root)
            with self.assertRaises(FileExistsError): activation.write_baseline(target, snapshot, self.root)
            self.assertNotIn('PRIVATE ACCOUNT NAME', target.read_text())


if __name__ == '__main__': unittest.main()
