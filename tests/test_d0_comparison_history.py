"""Synthetic complete ledger evidence; no production data or service IO."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
from realtime_paper_comparison_history import reconstruct_account_history
from realtime_paper_rationale import SYMBOLS

NOW = datetime.fromisoformat('2026-10-23T16:30:00+08:00')
DAYS = ['2026-10-20', '2026-10-21', '2026-10-22', '2026-10-23']
START = '2026-10-20T10:00:00+08:00'


def money(value):
    return format(Decimal(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP), '.2f')


def fixture(start=START):
    raw = {'account': {'id': 'D0-forward-paper', 'created_at': '2026-10-20T09:00:00+08:00',
                       'initial_capital': '10000.00', 'cash': '10000.00',
                       'resumed_at': start, 'reserved_cash': '0.00'},
           'events': [{'id': 'created', 'type': 'created',
                       'at': '2026-10-20T09:00:00+08:00', 'capital': '10000.00'}],
           'fills': [], 'orders': [],
           'positions': [{'symbol': symbol, 'qty': 0} for symbol in SYMBOLS]}
    if start is not None:
        event(raw, 'started', start)
    return raw


def event(raw, kind, at, **kwargs):
    raw['events'].append({'id': 'event-' + str(len(raw['events'])), 'type': kind,
                          'at': at, **kwargs})


def capital(raw, value, at):
    event(raw, 'capital_changed', at, capital=value)
    raw['account'].update(initial_capital=value, cash=value)


def fill(raw, side='buy', qty=100, price='10.000', fee='5.00',
         at='2026-10-20T10:10:00+08:00', symbol=SYMBOLS[0], event_at=None):
    index = len(raw['fills'])
    order_id, fill_id = 'order-' + str(index), 'fill-' + str(index)
    gross = money(Decimal(price) * qty)
    stamp = datetime.fromisoformat(at)
    times = {'submitted_at': (stamp - timedelta(seconds=3)).isoformat(),
             'eligible_at': (stamp - timedelta(seconds=3)).isoformat(),
             'quote_at': (stamp - timedelta(seconds=1)).isoformat(),
             'received_at': (stamp - timedelta(seconds=1)).isoformat()}
    saved = {'id': fill_id, 'order_id': order_id, 'symbol': symbol,
             'side': side, 'qty': qty, 'price': price, 'gross': gross,
             'fee': fee, 'matched_at': at, **times}
    raw['fills'].append(saved)
    raw['orders'].append({'id': order_id, 'status': 'filled', 'fill_id': fill_id,
                          'symbol': symbol, 'side': side, 'qty': qty,
                          'qty_filled': qty, 'remaining_qty': 0, 'matched_at': at, **times})
    event(raw, 'estimated_fill', event_at or at, order_id=order_id, fill_id=fill_id)
    cash = Decimal(raw['account']['cash'])
    raw['account']['cash'] = money(cash - Decimal(gross) - Decimal(fee)
                                  if side == 'buy' else cash + Decimal(gross) - Decimal(fee))
    row = next(row for row in raw['positions'] if row['symbol'] == symbol)
    row['qty'] += qty if side == 'buy' else -qty
    return saved


def bars():
    return {symbol: {day: {'open': 10, 'close': 10, 'high': 10, 'low': 10}
                     for day in DAYS} for symbol in SYMBOLS}


class ReconstructedAccountHistoryTests(unittest.TestCase):
    def project(self, raw=None, prices=None, sessions=None, now=NOW):
        return reconstruct_account_history(fixture() if raw is None else raw,
                                           bars() if prices is None else prices,
                                           DAYS if sessions is None else sessions, now=now)

    def assertInvalid(self, raw, **kwargs):
        result = self.project(raw, **kwargs)
        self.assertEqual(result['status'], 'invalid', result)
        self.assertEqual(result['segments'], [])
        self.assertIsNone(result['last_state'])
        return result

    def test_cash_only_closes_need_no_prices(self):
        result = self.project(prices={})
        self.assertEqual((result['status'], result['reason']), ('available', None))
        points = result['segments'][0]['points']
        self.assertEqual([point['date'] for point in points], DAYS)
        self.assertEqual([point['equity'] for point in points], ['10000.00'] * 4)
        self.assertEqual([point['break_before'] for point in points], [True, False, False, False])
        self.assertEqual(points[0]['at'], '2026-10-20T15:00:00+08:00')
        self.assertEqual(set(points[0]['positions']), set(SYMBOLS))

    def test_first_started_event_survives_pause_and_resume(self):
        raw = fixture()
        event(raw, 'paused', '2026-10-21T11:00:00+08:00')
        event(raw, 'started', '2026-10-22T11:00:00+08:00')
        raw['account']['resumed_at'] = '2026-10-22T11:00:00+08:00'
        result = self.project(raw)
        self.assertEqual(result['first_started_at'], START)
        self.assertEqual(result['segments'][0]['starts_at'], START)
        self.assertEqual(len(result['segments'][0]['points']), 4)

    def test_creation_and_resumed_at_never_substitute_for_first_start(self):
        raw = fixture(None)
        raw['account']['resumed_at'] = START
        result = self.project(raw)
        self.assertEqual((result['status'], result['reason']), ('unavailable', 'not_started'))
        self.assertIsNone(result['first_started_at'])
        self.assertEqual(result['segments'], [])
        self.assertEqual(result['last_state']['cash'], '10000.00')

    def test_missing_account_is_unavailable(self):
        result = self.project({'account': None})
        self.assertEqual((result['status'], result['reason']), ('unavailable', 'account_not_created'))

    def test_start_after_close_excludes_that_day(self):
        result = self.project(fixture('2026-10-21T15:00:01+08:00'))
        self.assertEqual([p['date'] for p in result['segments'][0]['points']], DAYS[2:])

    def test_start_exactly_at_close_includes_that_day(self):
        result = self.project(fixture('2026-10-21T15:00:00+08:00'))
        self.assertEqual([p['date'] for p in result['segments'][0]['points']], DAYS[1:])

    def test_no_unconfirmed_or_future_close_is_emitted(self):
        now = datetime.fromisoformat('2026-10-23T14:59:59+08:00')
        result = self.project(now=now)
        self.assertEqual([p['date'] for p in result['segments'][0]['points']], DAYS[:3])
        result = self.project(sessions=DAYS[:2])
        self.assertEqual([p['date'] for p in result['segments'][0]['points']], DAYS[:2])

    def test_capital_segments_preserve_empty_same_day_segments(self):
        raw = fixture()
        event(raw, 'paused', '2026-10-20T10:10:00+08:00')
        capital(raw, '20000.00', '2026-10-20T11:00:00+08:00')
        capital(raw, '30000.00', '2026-10-20T15:00:00+08:00')
        result = self.project(raw)
        a, b, c = result['segments']
        self.assertEqual([a['points'], b['points']], [[], []])
        self.assertEqual(a['ends_at'], b['starts_at'])
        self.assertEqual(b['ends_at'], c['starts_at'])
        self.assertEqual(c['points'][0]['equity'], '30000.00')
        self.assertTrue(c['points'][0]['break_before'])
        self.assertEqual(len({s['id'] for s in result['segments']}), 3)
        self.assertEqual([s['id'] for s in result['segments']],
                         [s['id'] for s in self.project(raw, sessions=DAYS[:1])['segments']])

    def test_capital_before_start_keeps_identity_without_prestart_points(self):
        raw = fixture(None)
        capital(raw, '20000.00', '2026-10-20T11:00:00+08:00')
        event(raw, 'started', '2026-10-21T10:00:00+08:00')
        result = self.project(raw)
        self.assertEqual(result['segments'][0]['points'], [])
        self.assertEqual([p['date'] for p in result['segments'][1]['points']], DAYS[1:])
        self.assertEqual(result['segments'][1]['capital'], '20000.00')

    def test_capital_changes_after_any_fill_are_invalid(self):
        raw = fixture()
        fill(raw)
        capital(raw, '20000.00', '2026-10-21T11:00:00+08:00')
        self.assertInvalid(raw)

    def test_buy_fee_and_reserved_cash_are_not_deducted_twice(self):
        raw = fixture()
        fill(raw)
        raw['account']['reserved_cash'] = '100.00'
        result = self.project(raw)
        point = result['segments'][0]['points'][0]
        self.assertEqual((point['cash'], point['equity']), ('8995.00', '9995.00'))
        self.assertEqual(result['last_state']['positions'][SYMBOLS[0]], 100)

    def test_buy_and_sale_reconcile_cash_and_remaining_shares(self):
        raw = fixture()
        fill(raw, qty=300)
        fill(raw, side='sell', qty=100, price='11.000', at='2026-10-21T10:00:00+08:00')
        prices = bars()
        prices[SYMBOLS[0]]['2026-10-21']['close'] = '11.000'
        result = self.project(raw, prices)
        points = result['segments'][0]['points']
        self.assertEqual((points[0]['cash'], points[0]['equity']), ('6995.00', '9995.00'))
        self.assertEqual((points[1]['cash'], points[1]['equity']), ('8090.00', '10290.00'))
        self.assertEqual(result['last_state']['positions'][SYMBOLS[0]], 200)

    def test_zero_fee_and_sell_fee_exceeding_gross_are_valid(self):
        raw = fixture()
        fill(raw, price='.001', fee='0.00', symbol=SYMBOLS[2])
        fill(raw, side='sell', price='.001', fee='5.00', symbol=SYMBOLS[2],
             at='2026-10-20T10:11:00+08:00')
        result = self.project(raw, {})
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['last_state']['cash'], '9995.00')
        self.assertEqual(result['segments'][0]['points'][0]['equity'], '9995.00')

    def test_native_minimum_and_maximum_capital_remain_valid(self):
        for amount in ('0.01', '1000000000.00'):
            with self.subTest(amount=amount):
                raw = fixture()
                raw['account'].update(initial_capital=amount, cash=amount)
                raw['events'][0]['capital'] = amount
                result = self.project(raw, {})
                self.assertEqual(result['status'], 'available')
                self.assertEqual(result['last_state']['cash'], amount)

    def test_same_timestamp_fills_preserve_original_order(self):
        raw = fixture()
        fill(raw, symbol=SYMBOLS[2])
        fill(raw, side='sell', price='11.000', symbol=SYMBOLS[2])
        self.assertEqual(self.project(raw)['last_state']['cash'], '10090.00')
        raw['fills'].reverse()
        raw['events'][-2:] = list(reversed(raw['events'][-2:]))
        self.assertInvalid(raw)

    def test_created_and_estimated_fill_events_may_be_later_than_their_state_time(self):
        raw = fixture()
        raw['events'][0]['at'] = '2026-10-20T09:00:00.001+08:00'
        fill(raw, event_at='2026-10-20T10:10:00.001+08:00')
        self.assertEqual(self.project(raw)['status'], 'available')

    def test_equivalent_aware_timezones_are_supported(self):
        raw = fixture('2026-10-20T02:00:00+00:00')
        result = self.project(raw, now=NOW.astimezone(timezone.utc))
        self.assertEqual(result['first_started_at'], START)
        self.assertEqual(result['segments'][0]['points'][0]['at'], '2026-10-20T15:00:00+08:00')

    def test_last_state_includes_fills_after_last_confirmed_session(self):
        raw = fixture()
        fill(raw, at='2026-10-23T10:00:00+08:00')
        result = self.project(raw, sessions=DAYS[:3])
        self.assertEqual(result['segments'][0]['points'][-1]['equity'], '10000.00')
        self.assertEqual(result['last_state']['cash'], '8995.00')

    def test_missing_held_close_breaks_both_sides_of_the_gap(self):
        raw = fixture()
        fill(raw)
        prices = bars()
        del prices[SYMBOLS[0]]['2026-10-21']
        result = self.project(raw, prices)
        points = result['segments'][0]['points']
        self.assertEqual([p['equity'] for p in points], ['9995.00', None, '9995.00', '9995.00'])
        self.assertEqual([p['break_before'] for p in points], [True, True, True, False])
        self.assertEqual(points[1]['cash'], '8995.00')

    def test_unsafe_close_is_a_gap_and_unused_close_is_irrelevant(self):
        raw = fixture()
        fill(raw)
        for value in ('NaN', 'Infinity', '-1', '0', True, None, '1e99'):
            with self.subTest(value=value):
                prices = bars()
                prices[SYMBOLS[0]][DAYS[1]]['close'] = value
                prices[SYMBOLS[1]][DAYS[0]]['close'] = 'NaN'
                result = self.project(raw, prices)
                self.assertEqual(result['status'], 'available')
                self.assertIsNone(result['segments'][0]['points'][1]['equity'])
                self.assertEqual(result['segments'][0]['points'][0]['equity'], '9995.00')

    def test_cash_mismatch_is_invalid(self):
        raw = fixture()
        fill(raw)
        raw['account']['cash'] = '8994.99'
        self.assertEqual(self.assertInvalid(raw)['reason'], 'reconciliation_failed')

    def test_quantity_mismatch_and_incomplete_positions_are_invalid(self):
        raw = fixture()
        fill(raw)
        for mutate in (lambda x: x['positions'][0].update(qty=0),
                       lambda x: x['positions'].pop(),
                       lambda x: x['positions'].__setitem__(1, deepcopy(x['positions'][0]))):
            with self.subTest(mutate=mutate):
                bad = deepcopy(raw)
                mutate(bad)
                self.assertInvalid(bad)

    def test_missing_fill_cannot_be_hidden_by_final_cash(self):
        raw = fixture()
        fill(raw)
        raw['fills'] = []
        self.assertInvalid(raw)

    def test_duplicate_and_broken_fill_associations_are_invalid(self):
        raw = fixture()
        fill(raw)
        mutations = (
            lambda x: x['fills'].append(deepcopy(x['fills'][0])),
            lambda x: x['orders'].append(deepcopy(x['orders'][0])),
            lambda x: x['events'].append(deepcopy(x['events'][-1])),
            lambda x: x['orders'][0].update(fill_id='other'),
            lambda x: x['events'][-1].update(order_id='other'),
            lambda x: x['events'].pop(),
            lambda x: x['orders'].clear(),
            lambda x: x['orders'][0].update(status='pending'),
            lambda x: x['orders'][0].update(qty_filled=0),
            lambda x: x['orders'][0].update(remaining_qty=100),
            lambda x: x['orders'].append(dict(id='stray-order', status='pending',
                                              fill_id=x['fills'][0]['id'])),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                bad = deepcopy(raw)
                mutate(bad)
                self.assertInvalid(bad)

    def test_out_of_order_and_future_evidence_are_invalid(self):
        raw = fixture()
        fill(raw)
        fill(raw, at='2026-10-21T10:00:00+08:00')
        mutations = (
            lambda x: x['events'].reverse(),
            lambda x: x['fills'].reverse(),
            lambda x: x['fills'][0].update(matched_at='2026-10-20T09:59:59+08:00'),
            lambda x: x['fills'][0].update(matched_at='2026-10-24T10:00:00+08:00'),
            lambda x: x['events'][-1].update(at='2026-10-24T10:00:00+08:00'),
            lambda x: x['events'][0].update(at='2026-10-19T10:00:00+08:00'),
        )
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                bad = deepcopy(raw)
                mutate(bad)
                self.assertInvalid(bad)

    def test_matched_time_cannot_move_a_later_quote_into_an_earlier_close(self):
        raw = fixture()
        fill(raw, at='2026-10-21T10:10:00+08:00')
        raw['fills'][0]['matched_at'] = '2026-10-20T10:10:00+08:00'
        raw['orders'][0]['matched_at'] = '2026-10-20T10:10:00+08:00'
        self.assertInvalid(raw)

    def test_order_and_fill_time_evidence_must_be_present_and_match(self):
        raw = fixture()
        fill(raw)
        for field in ('submitted_at', 'eligible_at', 'quote_at', 'received_at'):
            for collection in ('fills', 'orders'):
                with self.subTest(field=field, collection=collection):
                    bad = deepcopy(raw)
                    del bad[collection][0][field]
                    self.assertInvalid(bad)
                    bad = deepcopy(raw)
                    bad[collection][0][field] = '2026-10-20T10:10:01+08:00'
                    self.assertInvalid(bad)

    def test_bad_numbers_never_produce_a_curve(self):
        raw = fixture()
        fill(raw)
        fields = {'qty': (True, -100, 0, 1, 1000001, 10**30, '100'),
                  'price': (True, 'NaN', 'Infinity', '-1', '0', '10.0001', '1e99', '1' * 81),
                  'gross': (None, '-1.00', '1000.001', '999.00', '1e99'),
                  'fee': (True, '-1.00', 'NaN', '5.001', '1e99')}
        for key, values in fields.items():
            for value in values:
                with self.subTest(key=key, value=value):
                    bad = deepcopy(raw)
                    bad['fills'][0][key] = value
                    self.assertInvalid(bad)
        for key in ('cash', 'initial_capital'):
            for value in (True, '-1.00', 'NaN', '1.001', '1e99'):
                with self.subTest(account=key, value=value):
                    bad = deepcopy(raw)
                    bad['account'][key] = value
                    self.assertInvalid(bad)

    def test_oversell_or_overdraw_is_invalid_even_if_final_state_is_manipulated(self):
        raw = fixture()
        fill(raw, side='sell')
        raw['positions'][0]['qty'] = 0
        self.assertInvalid(raw)
        raw = fixture()
        fill(raw, qty=1000000)
        raw['account']['cash'] = '0.00'
        self.assertInvalid(raw)

    def test_capital_proof_is_mandatory_and_matches_current_capital(self):
        raw = fixture()
        for mutate in (lambda x: x['events'].pop(0),
                       lambda x: x['events'][0].pop('capital'),
                       lambda x: x['events'][0].update(capital='10001.00'),
                       lambda x: x['events'][0].update(capital='1000000000.01')):
            with self.subTest(mutate=mutate):
                bad = deepcopy(raw)
                mutate(bad)
                self.assertInvalid(bad)

    def test_invalid_dates_naive_times_and_inputs_are_invalid(self):
        for sessions in ([DAYS[1], DAYS[0]], [DAYS[0], DAYS[0]], ['2026-02-30'],
                         ['2026-1-01'], ['2026-10-20T15:00'], None):
            with self.subTest(sessions=sessions):
                result = reconstruct_account_history(fixture(), bars(), sessions, now=NOW)
                self.assertEqual(result['status'], 'invalid')
        self.assertEqual(self.project(now=datetime(2026, 10, 23, 16))['status'], 'invalid')
        raw = fixture('2026-10-20T10:00:00')
        self.assertInvalid(raw)

    def test_input_limits_are_enforced(self):
        raw = fixture()
        raw['events'] = [raw['events'][0]] * 100001
        self.assertInvalid(raw)
        raw = fixture()
        raw['fills'] = [{}] * 100001
        self.assertInvalid(raw)
        self.assertEqual(self.project(sessions=[DAYS[0]] * 5001)['status'], 'invalid')

    def test_inputs_unchanged_and_projection_performs_no_io(self):
        raw = fixture()
        fill(raw)
        prices, days = bars(), list(DAYS)
        original = deepcopy((raw, prices, days))
        with patch('builtins.open', side_effect=AssertionError('file IO')), \
                patch('sqlite3.connect', side_effect=AssertionError('ledger IO')), \
                patch('socket.socket', side_effect=AssertionError('network IO')):
            result = reconstruct_account_history(raw, prices, days, now=NOW)
        self.assertEqual(result['status'], 'available')
        self.assertEqual((raw, prices, days), original)
        result['segments'][0]['points'][0]['positions'][SYMBOLS[0]] = 999
        self.assertEqual((raw, prices, days), original)


if __name__ == '__main__':
    unittest.main()
