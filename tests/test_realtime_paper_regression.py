"""D0 persistence and submitted-order reminder boundaries on synthetic data."""
import copy
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1] / 'production'
sys.path.insert(0, str(ROOT))
from realtime_paper_engine import PaperError, PaperLedger
from realtime_paper_alerts import project_trade_alerts

CN = timezone(timedelta(hours=8))


class LedgerRegressionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('ETF_TEST_TMPDIR'))
        self.home = Path(self.temp.name)
        self.now = datetime(2026, 10, 20, 10, 0, tzinfo=CN)
        self.ledger = PaperLedger(self.home, now=lambda: self.now)

    def tearDown(self):
        self.ledger.close()
        if os.environ.get('ETF_TEST_TMPDIR'):
            self.assertTrue(self.home.resolve().is_relative_to(Path(os.environ['ETF_TEST_TMPDIR']).resolve()))
        self.temp.cleanup()

    def create(self, capital='1000.00', key='create-fixture-account'):
        return self.ledger.create(capital, name='Synthetic D0', idempotency_key=key)

    def test_new_account_is_stopped_and_has_no_orders_or_fills(self):
        view = self.create()
        self.assertIs(view['account']['running'], False)
        self.assertEqual(view['account']['cash'], '1000.00')
        self.assertEqual((view['orders'], view['fills']), ([], []))

    def test_restart_replays_the_original_command_response(self):
        first = self.create()
        self.ledger.close()
        self.now += timedelta(minutes=1)
        self.ledger = PaperLedger(self.home, now=lambda: self.now)
        self.assertEqual(self.create(), first)
        current = self.ledger.snapshot()
        self.assertEqual(current['account']['cash'], '1000.00')
        self.assertEqual((current['orders'], current['fills']), ([], []))

    def test_reusing_a_command_key_cannot_change_its_parameters(self):
        self.create()
        with self.assertRaises(PaperError) as caught:
            self.create('2000.00')
        self.assertEqual(caught.exception.code, 'IDEMPOTENCY_CONFLICT')
        self.assertEqual(self.ledger.snapshot()['account']['cash'], '1000.00')

    def test_running_account_capital_is_locked_and_pause_is_durable(self):
        self.create()
        self.ledger.set_running(True, idempotency_key='start-fixture-account')
        with self.assertRaises(PaperError) as caught:
            self.ledger.configure_capital('2000.00', idempotency_key='capital-fixture-account')
        self.assertEqual(caught.exception.code, 'CAPITAL_LOCKED')
        self.ledger.set_running(False, idempotency_key='pause-fixture-account')
        self.ledger.close()
        self.ledger = PaperLedger(self.home, now=lambda: self.now)
        view = self.ledger.snapshot()
        self.assertIs(view['account']['running'], False)
        self.assertEqual(view['account']['cash'], '1000.00')

    def test_returned_views_cannot_mutate_the_durable_account(self):
        view = self.create()
        view['account']['cash'] = '0.00'
        view['orders'].append({'id': 'not-a-durable-order'})
        current = self.ledger.snapshot()
        self.assertEqual(current['account']['cash'], '1000.00')
        self.assertEqual(current['orders'], [])


def reminder_fixture():
    signal = {'id': 'signal-1', 'strategy': 'D0', 'valid': True,
        'data_cutoff': '2026-10-20T09:31:00+08:00',
        'signal_at': '2026-10-20T09:31:01+08:00',
        'known_at': '2026-10-20T09:31:02+08:00',
        'received_at': '2026-10-20T09:31:03+08:00',
        'eligible_at': '2026-10-20T09:31:05+08:00', 'execution_day': '2026-10-20'}
    account = {'id': 'account-1', 'strategy': 'D0', 'running': True,
        'activation_generation': 1, 'resumed_at': '2026-10-20T09:30:00+08:00'}
    plan = {'id': 'plan-1', 'signal_id': 'signal-1', 'generation': 1,
        'created_at': '2026-10-20T09:32:00+08:00', 'session_day': '2026-10-20'}
    order = {'id': 'order-1', 'account_id': 'account-1', 'signal_id': 'signal-1',
        'plan_id': 'plan-1', 'intent_id': 'intent-1', 'symbol': 'sz159915',
        'side': 'buy', 'qty': 100, 'limit_price': '1.200', 'status': 'pending',
        'remaining_qty': 100, 'qty_filled': 0, 'terminal_at': None,
        'signal_at': signal['signal_at'], 'submitted_at': '2026-10-20T09:33:00+08:00',
        'eligible_at': '2026-10-20T09:34:00+08:00', 'expires_at': '2026-10-20T14:57:00+08:00'}
    event = {'id': 'event-1', 'type': 'submitted', 'account_id': 'account-1',
        'order_id': 'order-1', 'at': '2026-10-20T09:33:01+08:00'}
    return {'account': account, 'signal': signal, 'plan': plan, 'orders': [order], 'events': [event]}


class ReminderRegressionTests(unittest.TestCase):
    def project(self, raw, **options):
        return project_trade_alerts(raw, now='2026-10-20T10:00:00+08:00',
            source_status=options.get('source', 'ready'), observer_status='running',
            command=options.get('command', False))

    def test_valid_submission_is_a_readonly_in_app_reference(self):
        raw = reminder_fixture()
        original = copy.deepcopy(raw)
        view = self.project(raw)
        self.assertEqual(len(view['items']), 1)
        self.assertEqual(view['items'][0]['reference_status'], 'current_reference')
        self.assertIs(view['items'][0]['is_trade_instruction'], False)
        self.assertEqual(view['email_status'], 'not_integrated')
        view['items'][0]['quantity'] = 999
        self.assertEqual(raw, original)

    def test_plans_and_fill_events_do_not_create_submission_reminders(self):
        raw = reminder_fixture()
        raw['events'] = []
        self.assertEqual(self.project(raw)['items'], [])
        raw['events'] = [{'id': 'fill-1', 'type': 'estimated_fill', 'order_id': 'order-1'}]
        self.assertEqual(self.project(raw)['items'], [])

    def test_rejected_or_foreign_account_orders_are_excluded(self):
        for field, value in [('status', 'rejected'), ('account_id', 'other-account')]:
            with self.subTest(field=field):
                raw = reminder_fixture()
                raw['orders'][0][field] = value
                self.assertEqual(self.project(raw)['items'], [])

    def test_identical_replayed_event_does_not_duplicate_the_reminder(self):
        raw = reminder_fixture()
        first = self.project(raw)['items'][0]
        raw['events'].append(copy.deepcopy(raw['events'][0]))
        items = self.project(raw)['items']
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['id'], first['id'])
        self.assertEqual(items[0]['reference_status'], 'current_reference')

    def test_conflicting_submissions_cannot_become_a_current_reference(self):
        raw = reminder_fixture()
        other = copy.deepcopy(raw['events'][0]); other['id'] = 'event-2'
        raw['events'].append(other)
        item = self.project(raw)['items'][0]
        self.assertEqual(item['reference_status'], 'needs_review')
        self.assertEqual(item['reason_code'], 'ambiguous_submission')

    def test_paused_accounts_and_command_snapshots_are_historical(self):
        raw = reminder_fixture(); raw['account']['running'] = False
        self.assertEqual(self.project(raw)['items'][0]['reason_code'], 'account_stopped')
        raw = reminder_fixture()
        self.assertEqual(self.project(raw, command=True)['items'][0]['reason_code'], 'command_snapshot')

    def test_missing_source_and_naive_times_never_produce_current_reference(self):
        raw = reminder_fixture()
        self.assertEqual(self.project(raw, source='unavailable')['items'][0]['reason_code'], 'source_not_ready')
        raw['orders'][0]['submitted_at'] = '2026-10-20T09:33:00'
        self.assertEqual(self.project(raw)['items'][0]['reason_code'], 'invalid_timestamp')


if __name__ == '__main__':
    unittest.main()
