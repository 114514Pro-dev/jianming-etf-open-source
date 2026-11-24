"""Saved D0 intent explanation: causal associations and no execution side effects."""
from copy import deepcopy
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from contextlib import closing
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
from realtime_paper_signal_summary import project_signal_summary, _hash, SYMBOLS

NOW = datetime(2026, 10, 28, 10, 0, tzinfo=timezone(timedelta(hours=8)))


def fixture():
    signal = dict(id='saved-signal', strategy='D0', valid=True, day='2026-10-27', confirmed_day='2026-10-27',
        execution_day='2026-10-28', data_cutoff='2026-10-27T15:00:00+08:00',
        signal_at='2026-10-27T16:11:00+08:00', known_at='2026-10-27T16:11:00+08:00',
        received_at='2026-10-27T16:11:00+08:00', eligible_at='2026-10-28T09:30:00+08:00',
        weights={symbol: '1' if symbol == SYMBOLS[3] else '0' for symbol in SYMBOLS}, reason='保存的配置依据',
        notes={symbol: '保存的资产判断' for symbol in SYMBOLS}, dynamic={symbol: {'eligible': symbol == SYMBOLS[3],
        'score_ready': True, 'effective_score': 1.2 if symbol == SYMBOLS[3] else 0} for symbol in SYMBOLS})
    plan = dict(signal_id=signal['id'], session_day='2026-10-28', generation=1,
                created_at='2026-10-28T09:31:00+08:00', targets={symbol: 5600 if symbol == SYMBOLS[3] else 0 for symbol in SYMBOLS})
    plan['id'] = _hash(dict(signal=signal['id'], day=plan['session_day'], generation=1))
    return dict(account={'id': 'D0-forward-paper', 'strategy': 'D0', 'running': True,
                'activation_generation': 1, 'resumed_at': '2026-10-28T09:30:00+08:00'},
                signal=signal, plan=plan, orders=[], fills=[], positions=[dict(symbol=symbol,
                    qty=5600 if symbol == SYMBOLS[3] else 0, available_qty=5600 if symbol == SYMBOLS[3] else 0) for symbol in SYMBOLS])


def add_order(raw, symbol=SYMBOLS[3], side='buy', status='pending', qty=100, child=0):
    plan, signal = raw['plan'], raw['signal']
    client = _hash(dict(signal=signal['id'], day=plan['session_day'], generation=plan['generation'], symbol=symbol, side=side, child=child))
    row = dict(id='order-'+str(len(raw['orders'])), symbol=symbol, side=side, status=status,
               signal_id=signal['id'], plan_id=plan['id'], client_order_id=client, intent_id=client,
               qty=qty, remaining_qty=qty if status == 'pending' else 0, qty_filled=qty if status == 'filled' else 0,
               limit_price='141.000', signal_at=signal['signal_at'], submitted_at='2026-10-28T09:32:00+08:00',
               eligible_at='2026-10-28T09:32:00+08:00', expires_at='2026-10-28T14:57:00+08:00',
               terminal_at=None if status == 'pending' else '2026-10-28T09:45:00+08:00')
    raw['orders'].append(row)
    return row


def add_fill(raw, **kwargs):
    order = add_order(raw, status='filled', **kwargs)
    fill = {}
    fill.update({key: order[key] for key in ('plan_id', 'signal_id', 'symbol', 'side', 'qty', 'signal_at', 'submitted_at', 'eligible_at')})
    fill.update(id='fill-'+order['id'], order_id=order['id'], price='140.999', matched_at='2026-10-28T09:45:00+08:00',
                quote_at='2026-10-28T09:44:57+08:00', received_at='2026-10-28T09:44:59+08:00')
    order['fill_id'] = fill['id']; order.update({key: fill[key] for key in ('matched_at', 'quote_at', 'received_at')}); raw['fills'].append(fill)
    return fill


def project(raw, **kwargs):
    return project_signal_summary(raw, now=kwargs.pop('now', NOW), source_status=kwargs.pop('source_status', 'ready'),
                                  observer_status=kwargs.pop('observer_status', 'running'), **kwargs)


class SignalSummaryTests(unittest.TestCase):
    def test_real_saved_target_hold_independent_of_price_weight_drift(self):
        raw = fixture(); raw['account']['equity'] = '1'; raw['account']['cash'] = '99999'
        raw['positions'][3].update(price='1234', market_value='999999')
        result = project(raw)
        self.assertEqual((result['action'], result['execution_status']), ('hold', 'ready'))
        self.assertEqual(result['assets'][3]['difference_quantity'], 0)
        self.assertEqual(result['assets'][3]['trigger']['note'], '保存的资产判断')
        self.assertFalse(result['is_trade_instruction'])

    def test_no_plan_does_not_infer_buy_from_positive_weight(self):
        raw = fixture(); raw['plan'] = None; raw['positions'][3].update(qty=0, available_qty=0)
        result = project(raw)
        self.assertEqual((result['action'], result['reason_code']), ('wait', 'no_plan'))
        self.assertEqual(result['assets'][3]['target_weight'], '1')
        self.assertIsNone(result['assets'][3]['target_quantity'])

    def test_buy_sell_rebalance_cash_use_frozen_share_difference(self):
        for expected, change in [('buy', lambda r: r['plan']['targets'].update({SYMBOLS[3]: 5700})),
                                 ('sell', lambda r: r['plan']['targets'].update({SYMBOLS[3]: 5500})),
                                 ('rebalance', lambda r: r['plan']['targets'].update({SYMBOLS[0]: 100, SYMBOLS[3]: 5500})),
                                 ('cash', lambda r: (r['plan']['targets'].update({SYMBOLS[3]: 0}), r['positions'][3].update(qty=0, available_qty=0)))]:
            with self.subTest(action=expected):
                raw = fixture(); change(raw); self.assertEqual(project(raw)['action'], expected)

    def test_lunch_keeps_hold_and_saved_targets_but_execution_waits(self):
        result = project(fixture(), now=NOW.replace(hour=12), source_status='waiting')
        self.assertEqual((result['action'], result['execution_status'], result['reference_status'], result['reason_code']),
                         ('hold', 'waiting', 'saved', 'outside_session'))
        self.assertEqual(result['assets'][3]['target_quantity'], 5600)

    def test_paused_keeps_plan_direction_without_executable_claim(self):
        raw = fixture(); raw['account']['running'] = False; raw['plan']['targets'][SYMBOLS[3]] = 5700
        result = project(raw)
        self.assertEqual((result['action'], result['execution_status'], result['reference_status']), ('buy', 'stopped', 'saved'))

    def test_source_wait_and_observer_error_keep_direction_as_saved(self):
        for kw, reason in [({'source_status': 'waiting'}, 'source_not_ready'), ({'observer_status': 'error'}, 'observer_not_running')]:
            result = project(fixture(), **kw)
            self.assertEqual((result['action'], result['execution_status'], result['reference_status'], result['reason_code']), ('hold', 'waiting', 'saved', reason))

    def test_weekend_or_uncovered_calendar_never_advertises_execution_ready(self):
        for moment in (NOW.replace(day=31), NOW.replace(year=2027, month=1, day=4)):
            raw = fixture(); raw['plan'].update(session_day=moment.date().isoformat(), created_at=moment.replace(hour=9, minute=31).isoformat())
            raw['account']['resumed_at'] = moment.replace(hour=9, minute=30).isoformat()
            raw['plan']['id'] = _hash(dict(signal=raw['signal']['id'], day=raw['plan']['session_day'], generation=1))
            result = project(raw, now=moment)
            self.assertEqual((result['action'], result['execution_status'], result['reason_code']), ('hold', 'waiting', 'outside_session'))

    def test_command_response_never_claims_current_execution(self):
        result = project(fixture(), command=True)
        self.assertEqual((result['reference_status'], result['reason_code']), ('saved', 'command_snapshot'))

    def test_old_day_generation_or_signal_plan_is_not_a_new_action(self):
        for key, value in [('session_day', '2026-10-27'), ('generation', 0), ('signal_id', 'prior')]:
            with self.subTest(key=key):
                raw = fixture(); raw['plan'][key] = value; result = project(raw)
                self.assertEqual((result['action'], result['plan_status']), ('wait', 'historical'))
                self.assertEqual(result['assets'][3]['target_weight'], '1')
                self.assertIsNone(result['assets'][3]['target_quantity'])

    def test_invalid_plan_hash_targets_or_causal_time_fails_closed(self):
        changes = [lambda r: r['plan'].update(id='wrong'), lambda r: r['plan']['targets'].update({SYMBOLS[3]: 5601}),
                   lambda r: r['plan']['targets'].pop(SYMBOLS[0]), lambda r: r['plan'].update(created_at='2026-10-28T10:01:00+08:00'),
                   lambda r: r['account'].update(resumed_at='2026-10-28T09:35:00+08:00')]
        for change in changes:
            raw = fixture(); change(raw); result = project(raw)
            self.assertEqual((result['action'], result['reason_code']), ('wait', 'invalid_plan'))

    def test_invalid_signal_times_dates_weights_or_strategy_never_infer(self):
        changes = [lambda r: r['signal'].update(known_at='2026-10-29T10:00:00+08:00'),
                   lambda r: r['signal'].update(confirmed_day='2026-10-28'),
                   lambda r: r['signal'].update(signal_at='2026-10-27T16:11:00'),
                   lambda r: r['signal']['weights'].update({SYMBOLS[0]: 'NaN'}),
                   lambda r: r['signal'].update(strategy='D1'), lambda r: r['signal'].update(valid=False)]
        for change in changes:
            raw = fixture(); change(raw); result = project(raw)
            self.assertEqual((result['signal_status'], result['action']), ('invalid', 'wait'))
            self.assertTrue(all(a['target_weight'] is None for a in result['assets']))

    def test_missing_or_duplicate_positions_do_not_become_zero(self):
        for change in [lambda r: r['positions'].pop(), lambda r: r['positions'].append(r['positions'][0]),
                       lambda r: r['positions'][3].update(qty=True), lambda r: r['positions'][3].update(available_qty=6000)]:
            raw = fixture(); change(raw); result = project(raw)
            self.assertEqual(result['reason_code'], 'invalid_positions')
            self.assertTrue(all(a['actual_quantity'] is None for a in result['assets']))

    def test_pending_order_is_not_a_fill(self):
        raw = fixture(); raw['plan']['targets'][SYMBOLS[3]] = 5700; add_order(raw)
        result = project(raw); asset = result['assets'][3]
        self.assertEqual((asset['action'], asset['progress'], asset['pending_quantity']), ('buy', 'pending_order', 100))
        self.assertIsNone(result['latest_fill'])

    def test_pending_direction_quantity_or_duplicate_conflict_is_not_ready(self):
        for change in [lambda r, o: o.update(side='sell'), lambda r, o: o.update(qty=200, remaining_qty=200),
                       lambda r, o: r['orders'].append(deepcopy(o)), lambda r, o: o.update(submitted_at='2026-10-28T10:01:00+08:00')]:
            raw = fixture(); raw['plan']['targets'][SYMBOLS[3]] = 5700; order = add_order(raw); change(raw, order)
            result = project(raw)
            self.assertEqual((result['action'], result['execution_status']), ('wait', 'needs_review'))

    def test_old_active_order_blocks_current_plan_readiness(self):
        raw = fixture(); order = add_order(raw, side='sell'); order['plan_id'] = 'old-plan'
        self.assertEqual(project(raw)['reason_code'], 'invalid_orders')

    def test_terminal_unfilled_intent_does_not_claim_automatic_retry(self):
        for status in ('cancelled', 'rejected', 'expired'):
            with self.subTest(status=status):
                raw = fixture(); raw['plan']['targets'][SYMBOLS[3]] = 5700; add_order(raw, status=status)
                asset = project(raw)['assets'][3]
                self.assertEqual((asset['action'], asset['progress'], asset['terminal_status'], asset['pending_quantity']), ('buy', 'terminal_order', status, 0))

    def test_legacy_terminal_intent_id_is_recognized(self):
        raw = fixture(); raw['plan']['targets'][SYMBOLS[3]] = 5700; row = add_order(raw, status='cancelled')
        row['client_order_id'] = _hash(dict(signal=raw['signal']['id'], day=raw['plan']['session_day'], generation=1, symbol=SYMBOLS[3], side='buy'))
        self.assertEqual(project(raw)['assets'][3]['progress'], 'terminal_order')

    def test_filled_first_child_then_terminal_second_child_blocks_retry(self):
        raw = fixture(); raw['plan']['targets'][SYMBOLS[3]] = 5800
        add_order(raw, status='filled', child=0); add_order(raw, status='rejected', child=1)
        self.assertEqual(project(raw)['assets'][3]['terminal_status'], 'rejected')

    def test_buy_waits_for_actual_pending_sell(self):
        raw = fixture(); raw['plan']['targets'].update({SYMBOLS[0]: 100, SYMBOLS[3]: 5500}); add_order(raw, side='sell')
        result = project(raw)
        self.assertEqual(result['action'], 'rebalance')
        self.assertEqual(result['assets'][0]['progress'], 'waiting_sell')

    def test_sell_locked_quantity_is_not_invented_as_submitted(self):
        raw = fixture(); raw['plan']['targets'][SYMBOLS[3]] = 5500; raw['positions'][3]['available_qty'] = 0
        asset = project(raw)['assets'][3]
        self.assertEqual((asset['action'], asset['progress'], asset['pending_quantity']), ('sell', 'sellable_limited', 0))

    def test_expired_pending_snapshot_not_shown_as_open_execution(self):
        raw = fixture(); raw['plan']['targets'][SYMBOLS[3]] = 5700; add_order(raw)
        result = project(raw, now=NOW.replace(hour=15)); asset = result['assets'][3]
        self.assertEqual((asset['progress'], asset['terminal_status'], asset['pending_quantity']), ('terminal_order', 'expired', 0))
        self.assertEqual(result['execution_status'], 'waiting')

    def test_latest_fill_requires_saved_order_association_and_causal_times(self):
        raw = fixture(); fill = add_fill(raw)
        self.assertEqual(project(raw)['latest_fill']['id'], fill['id'])
        for key, value in [('plan_id', 'wrong'), ('matched_at', '2026-10-29T09:45:00+08:00'), ('qty', 200), ('received_at', '2026-10-28T09:46:00+08:00')]:
            bad = deepcopy(raw); bad['fills'][0][key] = value
            self.assertIsNone(project(bad)['latest_fill'])

    def test_fill_cannot_contradict_order_execution_fields(self):
        raw = fixture(); add_fill(raw)
        for key, value in [('matched_at', '2026-10-28T09:46:00+08:00'), ('quote_at', '2026-10-28T09:44:58+08:00'),
                           ('qty_filled', 0), ('remaining_qty', 100)]:
            bad = deepcopy(raw); bad['orders'][0][key] = value
            self.assertIsNone(project(bad)['latest_fill'])

    def test_malformed_order_status_is_data_not_an_exception(self):
        raw = fixture(); raw['plan']['targets'][SYMBOLS[3]] = 5700; add_order(raw)['status'] = []
        self.assertEqual(project(raw)['reason_code'], 'invalid_orders')

    def test_latest_fill_from_old_signal_is_labelled_historical(self):
        raw = fixture(); fill = add_fill(raw); fill['signal_id'] = raw['orders'][0]['signal_id'] = 'old-signal'
        fill['plan_id'] = raw['orders'][0]['plan_id'] = 'old-plan'
        latest = project(raw)['latest_fill']
        self.assertFalse(latest['current_signal']); self.assertFalse(latest['current_plan'])

    def test_saved_previous_day_plan_fill_is_not_current_plan(self):
        raw = fixture(); add_fill(raw)
        result = project(raw, now=NOW + timedelta(days=1))
        self.assertEqual(result['plan_status'], 'historical')
        self.assertFalse(result['latest_fill']['current_plan'])

    def test_trigger_is_saved_not_inferred_from_target_or_market(self):
        raw = fixture(); raw['signal'].pop('notes'); raw['signal'].pop('dynamic')
        result = project(raw)
        self.assertEqual(result['assets'][3]['target_weight'], '1')
        self.assertEqual(result['assets'][3]['trigger'], dict(eligible=None, score_ready=None, effective_score=None, note=None))

    def test_projection_is_detached_deterministic_and_does_no_io(self):
        raw = fixture(); before = deepcopy(raw)
        with patch('builtins.open', side_effect=AssertionError('no IO')), patch('sqlite3.connect', side_effect=AssertionError('no database')):
            first = project(raw); second = project(raw)
        self.assertEqual(first, second); self.assertEqual(raw, before)
        first['assets'][3]['trigger']['note'] = 'changed'; self.assertEqual(raw, before)
        json.dumps(second, allow_nan=False)

    def test_empty_input_is_unavailable_not_zero_signal(self):
        for raw in (None, [], {}, {'signal': []}):
            result = project(raw)
            self.assertEqual((result['action'], result['signal_status']), ('wait', 'missing'))
            self.assertIsNone(result['assets'][0]['target_quantity'])


class AdapterOptionalProjectionTests(unittest.TestCase):
    def test_adapter_wiring_is_additive_and_failure_isolated(self):
        from realtime_paper_engine import PaperLedger
        from server import PaperHttpAdapter
        with tempfile.TemporaryDirectory(dir=os.environ.get('ETF_TEST_TMPDIR')) as folder:
            ledger = PaperLedger(folder, now=lambda: NOW)
            ledger.create('10000.00', name='Synthetic signal summary')
            adapter = PaperHttpAdapter(SimpleNamespace(now=lambda: NOW))
            raw = ledger.snapshot(); before = deepcopy(raw)
            def durable():
                with closing(sqlite3.connect(ledger.path.resolve().as_uri()+'?mode=ro', uri=True)) as db:
                    return db.execute('SELECT data FROM ledger WHERE id=1').fetchone()[0]
            saved = durable(); shown = adapter.view(raw)
            self.assertEqual(shown['accounts'][0]['signal_summary']['signal_status'], 'missing')
            with patch('server.project_signal_summary', side_effect=ValueError('synthetic optional failure')), self.assertLogs('etfweb', level='ERROR'):
                fallback = adapter.view(raw)
            self.assertIsNone(fallback['accounts'][0]['signal_summary'])
            shown['accounts'][0]['signal_summary'] = None
            self.assertEqual(fallback, shown); self.assertEqual(raw, before); self.assertEqual(durable(), saved)
            ledger.close()


if __name__ == '__main__':
    unittest.main()
