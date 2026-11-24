"""P&L projection and API replay checks on synthetic account views only."""
from contextlib import closing
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
from realtime_paper_pnl import project_account_pnl
from realtime_paper_rationale import SYMBOLS


def fixture(cash='10000.00', capital='10000.00'):
    return {'account': {'initial_capital': capital, 'cash': cash, 'equity': cash,
                        'valuation_status': 'current'},
        'response_at': '2026-10-23T10:00:00+08:00', 'quotes': {}, 'fills': [],
        'positions': [dict(symbol=s, qty=0, cost='0.00', lots=[], price=None,
                           market_value=None, valuation_status='not_held') for s in SYMBOLS]}


def holding(raw, symbol=SYMBOLS[0], qty=100, cost='1005.00', price='10.000',
            status='current', at='2026-10-23T09:59:58+08:00', lots=None):
    row = next(p for p in raw['positions'] if p['symbol'] == symbol)
    row.update(qty=qty, cost=cost, lots=lots if lots is not None else [{'qty': qty, 'cost': cost}],
               price=price, market_value=None if price is None else
               format((Decimal(price)*qty).quantize(Decimal('.01'), rounding=ROUND_HALF_UP), 'f'),
               valuation_status=status)
    if price is not None:
        raw['quotes'][symbol] = {'price': price, 'quote_at': at}
    held = [p for p in raw['positions'] if p['qty']]
    unknown = any(p['market_value'] is None or p['valuation_status'] == 'unknown' for p in held)
    raw['account']['valuation_status'] = 'unknown' if unknown else 'stale' if any(p['valuation_status'] == 'stale' for p in held) else 'current'
    raw['account']['equity'] = None if unknown else format(Decimal(raw['account']['cash']) + sum(Decimal(p['market_value']) for p in held), '.2f')
    return row


class PnlProjectionTests(unittest.TestCase):
    def test_empty_cash_account_is_zero_without_quote_requirements(self):
        result = project_account_pnl(fixture())
        self.assertEqual(result['contract_version'], 'd0-account-pnl-v1')
        self.assertEqual(result['status'], 'fresh')
        self.assertTrue(result['cash_only'])
        for field in ('total_pnl', 'realized_pnl', 'unrealized_pnl', 'fees_paid'):
            self.assertEqual(result[field], '0.00')
        self.assertEqual(result['return_ratio'], '0.00000000')
        self.assertIsNone(result['valuation_at'])
        self.assertIsNone(result['latest_quote_at'])

    def test_buy_fee_is_in_cost_and_never_deducted_twice(self):
        raw = fixture('8995.00'); holding(raw)
        raw['fills'] = [{'id': 'buy-1', 'fee': '5.00'}]
        result = project_account_pnl(raw)
        self.assertEqual(result['total_pnl'], '-5.00')
        self.assertEqual(result['return_ratio'], '-0.00050000')
        self.assertEqual(result['realized_pnl'], '0.00')
        self.assertEqual(result['unrealized_pnl'], '-5.00')
        self.assertEqual(result['fees_paid'], '5.00')
        self.assertTrue(result['fees_included'])

    def test_partial_sale_uses_saved_remaining_cost_rounding(self):
        # Buy 300 for 3000+5; sell 100 for 1100-5. The ledger retained 2003.33.
        raw = fixture('8090.00'); holding(raw, qty=200, cost='2003.33', price='11.000')
        raw['fills'] = [{'id': 'buy', 'fee': '5.00'}, {'id': 'sell', 'fee': '5.00'}]
        result = project_account_pnl(raw)
        self.assertEqual(result['total_pnl'], '290.00')
        self.assertEqual(result['realized_pnl'], '93.33')
        self.assertEqual(result['unrealized_pnl'], '196.67')
        self.assertEqual(result['fees_paid'], '10.00')

    def test_sale_across_lots_keeps_ledger_cent_allocation(self):
        # Buy 200 for 405, then 300 for 905; sell 250 for 1000-5.
        # FIFO leaves 250 of the second lot at 754.17, already rounded by engine.
        raw = fixture('9685.00'); holding(raw, qty=250, cost='754.17', price='4.000')
        raw['fills'] = [{'id': key, 'fee': '5.00'} for key in ('buy-a', 'buy-b', 'sell')]
        result = project_account_pnl(raw)
        self.assertEqual((result['total_pnl'], result['realized_pnl'], result['unrealized_pnl']),
                         ('685.00', '439.17', '245.83'))
        self.assertEqual(result['fees_paid'], '15.00')

    def test_fully_closed_positions_keep_realized_result_and_paid_fees(self):
        raw = fixture('10090.00')
        raw['fills'] = [{'id': 'buy', 'fee': '5.00'}, {'id': 'sell', 'fee': '5.00'}]
        result = project_account_pnl(raw)
        self.assertEqual((result['total_pnl'], result['realized_pnl'], result['unrealized_pnl']),
                         ('90.00', '90.00', '0.00'))
        self.assertTrue(result['cash_only'])
        self.assertEqual(result['status'], 'fresh')
        self.assertIsNone(result['valuation_at'])

    def test_multiple_assets_use_oldest_held_quote_and_keep_stale_values(self):
        raw = fixture('7990.00')
        holding(raw, cost='1005.00', price='11.000', at='2026-10-23T09:59:59+08:00')
        holding(raw, SYMBOLS[2], qty=100, cost='1005.00', price='9.000', status='stale',
                at='2026-10-22T14:55:54+08:00')
        raw['quotes'][SYMBOLS[3]] = {'price': '1', 'quote_at': '2000-01-01T00:00:00+08:00'}
        result = project_account_pnl(raw)
        self.assertEqual(result['status'], 'stale')
        self.assertEqual(result['total_pnl'], '-10.00')
        self.assertEqual(result['realized_pnl'], '0.00')
        self.assertEqual(result['unrealized_pnl'], '-10.00')
        self.assertEqual(result['valuation_at'], '2026-10-22T14:55:54+08:00')
        self.assertEqual(result['latest_quote_at'], '2026-10-23T09:59:59+08:00')

    def test_missing_held_price_keeps_realized_but_never_zero_fills_unknown_pnl(self):
        raw = fixture('8995.00'); holding(raw, price=None, status='unknown')
        raw['fills'] = [{'id': 'buy', 'fee': '5.00'}]
        result = project_account_pnl(raw)
        self.assertEqual((result['status'], result['reason']), ('missing', 'missing_valuation'))
        for field in ('total_pnl', 'unrealized_pnl', 'return_ratio', 'valuation_at'):
            self.assertIsNone(result[field])
        self.assertEqual(result['realized_pnl'], '0.00')
        self.assertEqual(result['fees_paid'], '5.00')

    def test_frozen_cash_and_frozen_quantity_are_not_additional_costs(self):
        raw = fixture('8995.00'); row = holding(raw)
        before = project_account_pnl(raw)
        raw['account'].update(reserved_cash='500.00', available_cash='8495.00')
        row.update(reserved_qty=100, available_qty=0, settled_qty=100)
        raw['orders'] = [{'reserved_cash': '500.00', 'reserved_qty': 100}]
        self.assertEqual(project_account_pnl(raw), before)
        self.assertTrue(before['frozen_cash_included'])

    def test_display_quotes_and_external_values_never_reprice_the_account(self):
        raw = fixture('8995.00'); holding(raw)
        before = project_account_pnl(raw)
        raw['market_observation'] = {'quotes': {s: {'price': '999999'} for s in SYMBOLS}}
        raw['market_quotes'] = [{'symbol': s, 'price': '999999'} for s in SYMBOLS]
        self.assertEqual(project_account_pnl(raw), before)

    def test_remaining_lot_cost_or_quantity_mismatch_is_not_reconstructed(self):
        for change in ({'cost': '-1'}, {'cost': 'NaN'}, {'cost': '1e1000'},
                       {'cost': None}, {'cost': '1005.001'}, {'lots': []},
                       {'lots': [{'qty': 99, 'cost': '1005.00'}]},
                       {'lots': [{'qty': 100, 'cost': '1004.99'}]}):
            with self.subTest(change=change):
                raw = fixture('8995.00'); holding(raw).update(change)
                result = project_account_pnl(raw)
                self.assertEqual((result['status'], result['reason']), ('missing', 'incomplete_cost'))
                for field in ('total_pnl', 'realized_pnl', 'unrealized_pnl', 'return_ratio'):
                    self.assertIsNone(result[field])
        for mutate in (lambda r: r['positions'].pop(), lambda r: r['positions'].append(r['positions'][0])):
            raw = fixture(); mutate(raw)
            self.assertEqual(project_account_pnl(raw)['reason'], 'incomplete_cost')

    def test_bad_account_and_inconsistent_existing_valuation_fail_closed(self):
        for value in (None, True, '-1', 'NaN', 'Infinity', '1e1000', '10000.001'):
            raw = fixture(); raw['account']['initial_capital'] = value
            self.assertEqual(project_account_pnl(raw)['reason'], 'invalid_account')
        for target, key, value in (('account', 'equity', '10000.00'),
                                   ('account', 'valuation_status', 'stale'),
                                   ('position', 'market_value', '999.00'),
                                   ('quote', 'price', '9')):
            raw = fixture('8995.00'); row = holding(raw)
            {'account': raw['account'], 'position': row, 'quote': raw['quotes'][SYMBOLS[0]]}[target][key] = value
            result = project_account_pnl(raw)
            self.assertEqual(result['status'], 'missing')
            self.assertEqual(result['reason'], 'inconsistent_valuation')
            self.assertIsNone(result['total_pnl'])
        self.assertEqual(project_account_pnl(None)['status'], 'missing')

    def test_missing_or_future_time_never_claims_freshness(self):
        for value in (None, '2026-10-23T09:59:58', '2026-10-23T10:01:00+08:00'):
            raw = fixture('8995.00'); holding(raw, at=value)
            result = project_account_pnl(raw)
            self.assertEqual(result['status'], 'missing')
            self.assertEqual(result['reason'], 'missing_quote_time')
            self.assertIsNone(result['valuation_at'])
            self.assertEqual(result['total_pnl'], '-5.00')

    def test_fee_evidence_is_distinct_and_not_silently_deduplicated(self):
        for fills in (None, [{'id': 'bad', 'fee': '-5'}], [{'id': 'bad', 'fee': 'NaN'}],
                      [{'id': 'same', 'fee': '5.00'}, {'id': 'same', 'fee': '5.00'}]):
            raw = fixture('8995.00'); holding(raw); raw['fills'] = fills
            result = project_account_pnl(raw)
            self.assertEqual(result['status'], 'missing')
            self.assertEqual(result['reason'], 'invalid_fee_evidence')
            self.assertIsNone(result['fees_paid'])
            self.assertEqual(result['total_pnl'], '-5.00')

    def test_pure_projection_never_changes_input_or_reads_files_or_database(self):
        raw = fixture('8995.00'); holding(raw)
        original = deepcopy(raw)
        with patch('builtins.open', side_effect=AssertionError('no files')), \
             patch('sqlite3.connect', side_effect=AssertionError('no database')):
            result = project_account_pnl(raw)
        self.assertEqual(raw, original)
        self.assertEqual(Decimal(result['realized_pnl'])+Decimal(result['unrealized_pnl']), Decimal(result['total_pnl']))
        result['total_pnl'] = '0.00'
        self.assertEqual(project_account_pnl(raw)['total_pnl'], '-5.00')
        json.dumps(result, allow_nan=False)


class PnlApiTests(unittest.TestCase):
    def test_get_is_durable_readonly_and_command_replay_uses_its_saved_snapshot(self):
        from realtime_paper_engine import PaperLedger
        from realtime_paper_service import PaperService
        from server import PaperHttpAdapter
        now = [datetime(2026, 10, 23, 10, tzinfo=timezone(timedelta(hours=8)))]
        with tempfile.TemporaryDirectory(dir=os.environ.get('ETF_TEST_TMPDIR')) as folder:
            ledger = PaperLedger(folder, now=lambda: now[0])
            created = ledger.create('10000.00', name='Synthetic P&L')
            service = PaperService(folder, ledger=ledger, source=Mock(strategy='D0'), now=lambda: now[0], start_worker=False)
            service.intraday_charts.snapshot = Mock(return_value={})
            def durable():
                with closing(sqlite3.connect(ledger.path.resolve().as_uri()+'?mode=ro', uri=True)) as con:
                    return con.execute('SELECT data FROM ledger WHERE id=1').fetchone()[0]
            try:
                before = durable()
                shown = PaperHttpAdapter(service).snapshot()
                self.assertEqual(shown['accounts'][0]['pnl']['total_pnl'], '0.00')
                self.assertEqual(durable(), before)
                first = PaperHttpAdapter(service).configure_capital(created['account']['id'], '11000.00', 'pnl-capital')
                stored = durable()
                service.intraday_charts.snapshot = Mock(side_effect=AssertionError('no external chart read'))
                now[0] += timedelta(days=1)
                again = PaperHttpAdapter(service).configure_capital(created['account']['id'], '11000.00', 'pnl-capital')
                self.assertEqual(again, first)
                self.assertEqual(durable(), stored)
                self.assertEqual(again['accounts'][0]['pnl']['snapshot_at'], first['generated_at'])
                service.intraday_charts.snapshot.assert_not_called()
            finally:
                service.close(); ledger.close()


if __name__ == '__main__':
    unittest.main()
