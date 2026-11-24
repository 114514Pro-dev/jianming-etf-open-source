"""Saved conditional-bank rule explanations, including legacy/WW isolation."""
from copy import deepcopy
import unittest

from test_d0_holding_rationale import signal_with_originals, original_gates
from realtime_paper_commentary import project_indicator_commentary
from realtime_paper_rationale import BANK_RULE_SIGNAL_VERSION


def conditional_signal(active=True):
    signal = signal_with_originals()
    signal['version'] = BANK_RULE_SIGNAL_VERSION
    signal['bank_gate'] = dict(schema='d0.bank-ma50-k50.v1', day=signal['confirmed_day'],
        active=active, relaxed=active, entry_k_limit=50 if active else 40,
        weekly_close=2.7 if active else 3.2, ma=3.2,
        week_end='2026-10-16', available='2026-10-16',
        gate_reasons=[] if active else ['chi_weekly_close_not_below_50week_ma'])
    return signal


def bank_rule(signal):
    return original_gates(signal)['sh512800']['bank_rule']


class BankRuleProjectionTests(unittest.TestCase):
    def test_saved_active_and_inactive_thresholds_and_evidence(self):
        for active, limit in ((True, 50), (False, 40)):
            with self.subTest(active=active):
                signal = conditional_signal(active); before = deepcopy(signal)
                rule = bank_rule(signal)
                self.assertEqual((rule['mode'], rule['status']), ('conditional', 'confirmed'))
                self.assertEqual(rule['entry_k_limit'], limit)
                self.assertIs(rule['active'], active)
                self.assertEqual(rule['weekly_status'], 'confirmed')
                self.assertEqual(rule['week_end'], '2026-10-16')
                self.assertEqual(rule['weekly_close'], signal['bank_gate']['weekly_close'])
                self.assertEqual(signal, before)

    def test_old_signals_never_acquire_new_rules_from_injected_gate(self):
        signal = conditional_signal()
        for version in ('D0-forward-v1', None):
            signal['version'] = version
            rule = bank_rule(signal)
            self.assertEqual((rule['mode'], rule['status'], rule['entry_k_limit']), ('legacy', 'legacy', 40))
            self.assertIsNone(rule['weekly_close'])

    def test_weekly_bond_strategy_stays_legacy_even_with_new_version_and_gate(self):
        signal = conditional_signal(); signal['strategy'] = 'D0I-BOND-WW'
        rule = bank_rule(signal)
        self.assertEqual((rule['mode'], rule['entry_k_limit']), ('legacy', 40))
        self.assertIs(rule['active'], False)

    def test_missing_new_evidence_does_not_fall_back_to_40(self):
        for missing in (None, {}, [], 'invalid'):
            signal = conditional_signal(); signal['bank_gate'] = missing
            rule = bank_rule(signal)
            self.assertEqual(rule['status'], 'unknown')
            self.assertIsNone(rule['entry_k_limit'])
            self.assertIsNone(rule['active'])

    def test_conflicting_active_evidence_is_unknown_instead_of_displaying_50(self):
        for key, value in [('schema', 'other'), ('day', '2026-10-21'), ('day', '2026-10-23'),
                ('active', 1), ('relaxed', False), ('entry_k_limit', 40), ('entry_k_limit', True),
                ('week_end', '2026-10-23'), ('available', '2026-10-23'),
                ('week_end', '2026-10-17'), ('weekly_close', 3.2), ('weekly_close', float('nan')),
                ('ma', None), ('ma', 0), ('gate_reasons', ['unready'])]:
            with self.subTest(key=key, value=value):
                signal = conditional_signal(); signal['bank_gate'][key] = value
                rule = bank_rule(signal)
                self.assertEqual(rule['status'], 'invalid')
                self.assertIsNone(rule['entry_k_limit'])
                self.assertIsNone(rule['weekly_close'])

    def test_bank_state_date_is_required_for_new_evidence(self):
        signal = conditional_signal(); signal['bank_state'].pop('date')
        self.assertIsNone(bank_rule(signal)['entry_k_limit'])

    def test_inactive_warmup_keeps_saved_40_without_fabricating_weekly_values(self):
        signal = conditional_signal(False)
        signal['bank_gate'].update(week_end=None, available=None, weekly_close=None, ma=None,
                                   gate_reasons=['chi_50week_values_unready'])
        rule = bank_rule(signal)
        self.assertEqual((rule['status'], rule['entry_k_limit'], rule['weekly_status']),
                         ('confirmed', 40, 'unknown'))
        self.assertIsNone(rule['weekly_close'])

    def test_commentary_reprojects_rule_and_ignores_forged_asset(self):
        signal = conditional_signal()
        asset = dict(symbol='sh512800', bank_rule=dict(entry_k_limit=40),
                     original_gate=dict(bank_rule=dict(entry_k_limit=40)))
        commentary = project_indicator_commentary(signal, asset)
        self.assertEqual(commentary['bank_rule'], bank_rule(signal))
        self.assertEqual(commentary['bank_rule']['entry_k_limit'], 50)


if __name__ == '__main__':
    unittest.main()
