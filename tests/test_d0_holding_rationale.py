"""Saved-signal explanation projection; synthetic inputs only, no networking."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
from realtime_paper_rationale import project_holding_rationale, SYMBOLS


def saved_signal():
    return {
        'id': 'saved-d0', 'strategy': 'D0', 'market_hash': 'saved-market', 'spec_hash': 'saved-spec',
        'day': '2026-10-22', 'confirmed_day': '2026-10-22', 'execution_day': '2026-10-23',
        'data_cutoff': '2026-10-22T15:00:00+08:00', 'market_at': '2026-10-22T15:00:00+08:00',
        'signal_at': '2026-10-22T16:10:00+08:00', 'known_at': '2026-10-22T16:10:00+08:00',
        'received_at': '2026-10-22T16:10:01+08:00', 'eligible_at': '2026-10-23T09:30:00+08:00',
        'version': 'D0-forward-v1', 'source': 'Synthetic saved daily signal',
        'valid': True, 'waiting_reason': None, 'reason': 'Saved allocation explanation',
        'weights': {'sz159915': '0', 'sh512800': '0.4', 'sh518880': '0.6', 'sh511010': '0'},
        'notes': {'sz159915': 'Saved equity gate did not pass', 'sh512800': 'Saved bank gate passed',
                  'sh518880': 'Saved gold gate passed', 'sh511010': 'Saved bond gate did not pass'},
        'dynamic': {symbol: {'eligible': symbol in ('sh512800', 'sh518880'),
                    'momentum20': -0.012, 'momentum60': 0.034, 'volatility20': 0.19,
                    'effective_score': 0.25 if symbol in ('sh512800', 'sh518880') else 0.,
                    'score_ready': True} for symbol in SYMBOLS},
    }


def signal_with_originals():
    signal = saved_signal()
    signal.update(ready={'sz159915': True}, chi_long=False, bank_long=True,
                  weekly_date='2026-10-16', weekly_confirmed='2026-10-16', chi_quote_date='2026-10-22',
                  chi_state={'date': '2026-10-22', 'close_market': 'bear', 'next_risk': 0,
                             'holding_days': 0, 'blocked': False, 'reason': 'Saved defensive reference state'},
                  bank_state={'date': '2026-10-22', 'next_risk': 1, 'holding_days': 4,
                              'reason': 'Continue saved reference holding'})
    signal['features'] = {
        'chi_weekly': {'week_end': '2026-10-16', 'available': '2026-10-16',
                       'k': 42, 'd': 40, 'trix': -.125, 'signal': -.25, 'close': 2.7, 'ma': 2.6},
        'chi_market': {'week_end': '2026-10-16', 'available': '2026-10-16', 'close': 2.7, 'ma': 3.2},
        'bank': {'k': 50, 'd': 45, 'trix': None, 'signal': None, 'ma': None,
                 'volume_ratio': 1.3, 'ready': True, 'entry': False, 'exit': False, 'positive': False},
        'gold': {'quote_date': '2026-10-22', 'value': 312.2, 'ma': 339.8, 'ma_window': 120,
                 'momentum20': -.074, 'ready': True, 'long': False},
        'bond': {'quote_date': '2026-10-22', 'value': 147.9, 'ma': 147.4, 'ma_window': 60,
                 'momentum20': .0037, 'ready': True, 'long': True},
    }
    return signal


def original_gates(signal):
    return {row['symbol']: row['original_gate'] for row in project_holding_rationale(signal)['assets']}


class RationaleProjectionTests(unittest.TestCase):
    def test_saved_facts_are_exposed_without_mutation_or_eligibility_inference(self):
        signal = saved_signal(); before = deepcopy(signal)
        # A positive weight alone must not manufacture an eligibility decision.
        signal['dynamic']['sh512800']['eligible'] = False
        before = deepcopy(signal)
        result = project_holding_rationale(signal)
        self.assertEqual(result['contract_version'], 'd0-holding-logic-v1')
        self.assertEqual(result['reason'], signal['reason'])
        self.assertEqual([a['symbol'] for a in result['assets']], list(SYMBOLS))
        self.assertEqual(result['assets'][1]['target_weight'], 0.4)
        self.assertIs(result['assets'][1]['eligible'], False)
        self.assertEqual(result['assets'][0]['momentum20'], -0.012)
        result['assets'][0]['note'] = 'consumer modified'
        self.assertEqual(signal, before)

    def test_missing_legacy_fields_remain_null(self):
        for signal in (None, [], {}, {'reason': 'Old explanation', 'weights': {'sh518880': '1'}}):
            with self.subTest(signal=signal):
                result = project_holding_rationale(signal)
                self.assertEqual(len(result['assets']), 4)
                self.assertTrue(all(a['eligible'] is None and a['note'] is None
                                    and a['momentum20'] is None and a['score_ready'] is None
                                    for a in result['assets']))
        self.assertIsNone(project_holding_rationale({})['reason'])

    def test_saved_features_dynamic_is_used_only_when_primary_field_is_absent(self):
        signal = saved_signal(); signal['features'] = {'dynamic': signal.pop('dynamic')}
        self.assertTrue(project_holding_rationale(signal)['assets'][2]['eligible'])
        for malformed in (None, [], 'invalid', {}):
            signal['dynamic'] = malformed
            self.assertIsNone(project_holding_rationale(signal)['assets'][2]['eligible'])

    def test_malformed_boolean_numeric_and_text_fields_are_unavailable(self):
        signal = saved_signal()
        signal['reason'] = {'html': '<script>bad</script>'}
        signal['notes']['sz159915'] = ['untrusted object']
        signal['weights']['sz159915'] = True
        signal['dynamic']['sz159915'] = {'eligible': 'false', 'score_ready': 1,
            'momentum20': 'NaN', 'momentum60': float('inf'),
            'volatility20': -1, 'effective_score': {'score': 10}}
        result = project_holding_rationale(signal)
        self.assertIsNone(result['reason'])
        self.assertTrue(all(v is None for k,v in result['assets'][0].items() if k not in ('symbol', 'original_gate')))
        self.assertTrue(all(v is None for v in result['assets'][0]['original_gate']['metrics'].values()))
        json.dumps(result, allow_nan=False)
        for bad in (-0.1, 1.1, '1e1000000', False):
            signal['weights']['sz159915'] = bad
            self.assertIsNone(project_holding_rationale(signal)['assets'][0]['target_weight'])

    def test_raw_text_remains_json_text_and_controls_or_oversize_are_rejected(self):
        signal = saved_signal(); text = '<img src=x onerror="alert(1)"> & saved evidence'
        signal['reason'] = text; signal['notes']['sz159915'] = text
        result = project_holding_rationale(signal)
        self.assertEqual(json.loads(json.dumps(result))['reason'], text)
        self.assertEqual(result['assets'][0]['note'], text)
        for bad in ('\x00hidden', 'x' * 4097, '', '   '):
            signal['reason'] = bad; signal['notes']['sz159915'] = bad
            result = project_holding_rationale(signal)
            self.assertIsNone(result['reason']); self.assertIsNone(result['assets'][0]['note'])


class OriginalGateProjectionTests(unittest.TestCase):
    def test_original_indicators_preserve_units_dates_and_state_without_rejudging(self):
        signal = signal_with_originals(); before = deepcopy(signal)
        result = project_holding_rationale(signal); gates = original_gates(signal)
        self.assertEqual(result['contract_version'], 'd0-holding-logic-v1')
        chi, bank, gold, bond = (gates[s] for s in SYMBOLS)
        self.assertTrue(all(g['contract_version'] == 'd0-original-gate-v1' and
                            g['source'] == 'saved_signal' and g['timing']['status'] == 'confirmed' for g in gates.values()))
        self.assertEqual(chi['metrics']['trix_pct'], -.125)
        self.assertEqual(chi['metrics']['signal_pct'], -.25)
        self.assertEqual(chi['metrics']['weekly_ma'], 2.6)
        self.assertEqual(chi['metrics']['market_ma'], 3.2)
        self.assertEqual(chi['timing']['period_end'], '2026-10-16')
        self.assertFalse(chi['state']['long'])  # Positive relations do not override saved state.
        self.assertFalse(bank['state']['entry'])
        self.assertEqual(bank['state']['next_risk'], 1)
        self.assertEqual(bank['state']['holding_days'], 4)
        self.assertTrue(bank['state']['long'])
        self.assertIsNone(bank['metrics']['trix_pct'])
        self.assertIsNone(bank['timing']['period_end'])  # No invented bank-feature date.
        self.assertEqual(bank['timing']['state_day'], '2026-10-22')
        self.assertEqual(gold['metrics']['value'], 312.2)
        self.assertEqual(gold['metrics']['ma_window'], 120)
        self.assertFalse(gold['state']['long'])
        self.assertEqual(bond['metrics']['ma_window'], 60)
        self.assertTrue(bond['state']['long'])
        chi['metrics']['k'] = 999
        self.assertEqual(signal, before)

    def test_legacy_fields_remain_unknown_without_current_data_or_configuration(self):
        for signal in (None, [], {}, saved_signal()):
            with self.subTest(signal=signal):
                for gate in original_gates(signal).values():
                    self.assertEqual(gate['timing']['status'], 'unknown')
                    self.assertTrue(all(v is None for v in gate['metrics'].values()))
                    self.assertTrue(all(v is None for v in gate['state'].values()))
        signal = signal_with_originals(); signal['features'] = None
        gates = original_gates(signal)
        self.assertTrue(all(v is None for v in gates['sz159915']['metrics'].values()))
        self.assertEqual(gates['sz159915']['state']['next_risk'], 0)
        self.assertTrue(all(v is None for v in gates['sh512800']['metrics'].values()))

    def test_weekly_confirmation_is_causal_and_holiday_availability_is_distinct(self):
        signal = signal_with_originals()
        signal['features']['chi_weekly'].update(week_end='2026-10-15', available='2026-10-19')
        signal.update(weekly_date='2026-10-15', weekly_confirmed='2026-10-19')
        gate = original_gates(signal)['sz159915']
        self.assertEqual(gate['timing']['indicator_status'], 'confirmed')
        self.assertEqual(gate['timing']['period_end'], '2026-10-15')
        self.assertEqual(gate['timing']['available_on'], '2026-10-19')
        for end, available, expected in [('2026-10-16', None, 'unknown'),
                                         ('2026-10-16', '2026-10-23', 'invalid'),
                                         ('2026-10-23', '2026-10-23', 'invalid'),
                                         ('2026-10-20', '2026-10-19', 'invalid'),
                                         ('2026-02-30', '2026-10-19', 'invalid')]:
            with self.subTest(end=end, available=available):
                signal['features']['chi_weekly'].update(week_end=end, available=available)
                signal.update(weekly_date=end, weekly_confirmed=available)
                gate = original_gates(signal)['sz159915']
                self.assertEqual(gate['timing']['indicator_status'], expected)
                self.assertIsNone(gate['metrics']['k'])
                self.assertIsNone(gate['metrics']['trix_pct'])
                self.assertEqual(gate['metrics']['market_ma'], 3.2)
                self.assertEqual(gate['state']['next_risk'], 0)

    def test_bank_and_defense_require_their_own_saved_same_day_provenance(self):
        for bad, expected in [(None, 'unknown'), ('2026-10-21', 'invalid'),
                              ('2026-10-23', 'invalid'), (False, 'invalid'),
                              ('2026-10-22T15:00:00+08:00', 'invalid')]:
            with self.subTest(bad=bad):
                signal = signal_with_originals()
                signal['bank_state']['date'] = bad
                signal['features']['gold']['quote_date'] = bad
                gates = original_gates(signal)
                for symbol in ('sh512800', 'sh518880'):
                    self.assertEqual(gates[symbol]['timing']['status'], expected)
                    self.assertTrue(all(v is None for v in gates[symbol]['metrics'].values()))
                    self.assertTrue(all(v is None for v in gates[symbol]['state'].values()))
                self.assertEqual(gates['sh511010']['timing']['status'], 'confirmed')

    def test_invalid_confirmation_or_conflicting_saved_dates_never_fall_back(self):
        for bad in ('2026-02-30', 20261022, True):
            signal = signal_with_originals(); signal['confirmed_day'] = bad
            for gate in original_gates(signal).values():
                self.assertEqual(gate['timing']['status'], 'invalid')
                self.assertTrue(all(v is None for v in gate['metrics'].values()))
        signal = signal_with_originals(); signal.pop('confirmed_day')
        for gate in original_gates(signal).values():
            self.assertEqual(gate['timing']['status'], 'unknown')
            self.assertTrue(all(v is None for v in gate['metrics'].values()))
        for key in ('weekly_date', 'weekly_confirmed', 'chi_quote_date'):
            signal = signal_with_originals(); signal[key] = '2026-10-23'
            gate = original_gates(signal)['sz159915']
            self.assertEqual(gate['timing']['status'], 'invalid')
            self.assertIsNone(gate['state']['next_risk'] if key == 'chi_quote_date' else gate['metrics']['k'])

    def test_malformed_numbers_booleans_and_text_are_not_coerced(self):
        signal = signal_with_originals()
        signal['features']['chi_weekly'].update(k=True, d=101, trix='NaN', signal=float('inf'), close=[], ma=-1)
        signal['features']['bank'].update(k=-1, d='Infinity', ready='true', entry=0, exit=1, positive={})
        signal['bank_state'].update(next_risk=2, holding_days=1.5, reason=['invalid'])
        signal['features']['gold'].update(value=False, ma='-Infinity', ma_window=True, momentum20={})
        signal['chi_state'].update(close_market='invented', next_risk=-1, holding_days=True, blocked='false', reason='\x00bad')
        signal['ready']['sz159915'] = 1
        signal['chi_long'] = 'false'
        gates = original_gates(signal)
        self.assertTrue(all(gates['sz159915']['metrics'][key] is None
                            for key in ('k', 'd', 'trix_pct', 'signal_pct', 'weekly_close', 'weekly_ma')))
        self.assertTrue(all(v is None for v in gates['sz159915']['state'].values()))
        self.assertTrue(all(gates['sh512800']['state'][key] is None
                            for key in ('ready', 'entry', 'exit', 'positive', 'next_risk', 'holding_days', 'reason')))
        self.assertTrue(all(v is None for v in gates['sh518880']['metrics'].values()))
        json.dumps(gates, allow_nan=False)


class RationaleAdapterTests(unittest.TestCase):
    def test_adapter_uses_saved_signal_and_does_not_write_or_backfill_ledger(self):
        from realtime_paper_engine import PaperLedger
        from server import PaperHttpAdapter
        now = datetime(2026, 10, 23, 10, tzinfo=timezone(timedelta(hours=8)))
        with tempfile.TemporaryDirectory(dir=os.environ.get('ETF_TEST_TMPDIR')) as folder:
            ledger = PaperLedger(Path(folder), now=lambda: now)
            try:
                ledger.create('100000.00', name='Synthetic rationale', idempotency_key='fixture-create')
                ledger.set_signal(signal_with_originals())
                raw = ledger.snapshot(); before = deepcopy(raw)
                adapter = PaperHttpAdapter(SimpleNamespace(now=lambda: now))
                result = adapter.view(raw)
                self.assertEqual(result['accounts'][0]['signal']['rationale']['assets'][2]['target_weight'], 0.6)
                self.assertEqual(result['accounts'][0]['signal']['rationale']['assets'][0]['original_gate']['metrics']['trix_pct'], -.125)
                self.assertEqual(raw, before)
                # Advance presentation time only; saved rationale must not change.
                now += timedelta(hours=1)
                later = adapter.view(raw)
                self.assertEqual(later['accounts'][0]['signal']['rationale'], result['accounts'][0]['signal']['rationale'])
                command = adapter.view(raw, command=True)
                self.assertEqual(command['accounts'][0]['signal']['rationale'], result['accounts'][0]['signal']['rationale'])
                self.assertEqual(ledger.snapshot()['signal'], before['signal'])
                self.assertEqual(ledger.snapshot()['revision'], before['revision'])
                self.assertEqual(ledger.snapshot()['fills'], before['fills'])
            finally:
                ledger.close()

    def test_legacy_signal_without_details_stays_readable_without_enrichment(self):
        from realtime_paper_engine import PaperLedger
        from server import PaperHttpAdapter
        now = datetime(2026, 10, 23, 10, tzinfo=timezone(timedelta(hours=8)))
        with tempfile.TemporaryDirectory(dir=os.environ.get('ETF_TEST_TMPDIR')) as folder:
            ledger = PaperLedger(Path(folder), now=lambda: now)
            try:
                ledger.create('100000.00', name='Synthetic legacy')
                signal = saved_signal(); signal.pop('dynamic'); signal.pop('notes')
                ledger.set_signal(signal)
                adapter = PaperHttpAdapter(SimpleNamespace(now=lambda: now))
                result = adapter.view(ledger.snapshot())['accounts'][0]['signal']['rationale']
                self.assertEqual(result['reason'], signal['reason'])
                self.assertTrue(all(a['eligible'] is None and a['note'] is None for a in result['assets']))
                self.assertNotIn('dynamic', ledger.snapshot()['signal'])
            finally:
                ledger.close()


if __name__ == '__main__':
    unittest.main()
