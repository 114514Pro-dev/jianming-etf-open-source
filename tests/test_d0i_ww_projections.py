"""Saved WW evidence is distinct from original D0 daily defense evidence."""
from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
from realtime_paper_rationale import project_holding_rationale, SYMBOLS
from realtime_paper_commentary import project_indicator_commentary
from realtime_paper_signal_summary import project_signal_summary
from test_d0_holding_rationale import signal_with_originals
from test_realtime_signal_summary import fixture, NOW


def weekly(day='2026-10-22'):
    return dict(week_end='2026-10-16', available='2026-10-16', weeks=180,
        sma60weeks=140., momentum20weeks=.024, value=143., weekly_ready=True,
        weekly_indicator_gate=True, current_score_ready=True, current_quote_date=day,
        current_data_usable=True, indicator_effective=True)


def saved_ww():
    signal = signal_with_originals()
    signal.update(strategy='D0I-BOND-WW', ww_bond=weekly(),
                  weights=dict(zip(SYMBOLS, (0, 0, 0, 1))))
    # These daily fields deliberately conflict. They must not govern WW.
    signal['features']['bond'].update(value=95, ma=100, momentum20=-.1, long=False)
    signal['dynamic']['sh511010'].update(quote_date=signal['confirmed_day'], eligible=False)
    return signal


class WeeklyProjectionTests(unittest.TestCase):
    def test_bond_gate_uses_saved_week_units_not_old_daily_filter(self):
        signal = saved_ww(); before = deepcopy(signal)
        result = project_holding_rationale(signal)
        self.assertEqual(result['strategy'], 'D0I-BOND-WW')
        bond = result['assets'][3]
        self.assertEqual(bond['original_gate']['kind'], 'bond_weekly')
        self.assertEqual(bond['original_gate']['metrics']['ma_unit'], 'weeks')
        self.assertEqual(bond['original_gate']['metrics']['value'], 143.)
        self.assertEqual(bond['original_gate']['metrics']['momentum20'], .024)
        self.assertIs(bond['eligible'], True)
        self.assertIsNone(bond['effective_score'])
        self.assertIsNone(bond['momentum20'])
        self.assertEqual(signal, before)

    def test_gold_is_excluded_and_does_not_describe_daily_gold_trend(self):
        signal = saved_ww()
        asset = project_holding_rationale(signal)['assets'][2]
        self.assertFalse(asset['eligible'])
        self.assertEqual(asset['original_gate']['kind'], 'excluded')
        result = project_indicator_commentary(signal, asset)
        self.assertEqual(result['allocation_mode'], 'excluded')
        self.assertIsNone(result['trend'])
        self.assertEqual(result['pairs'], [])

    def test_commentary_shows_60_week_trend_and_20_week_momentum(self):
        signal = saved_ww()
        asset = project_holding_rationale(signal)['assets'][3]
        result = project_indicator_commentary(signal, asset)
        self.assertEqual(result['trend']['frequency'], 'weekly')
        self.assertEqual(result['trend']['window'], 60)
        self.assertEqual(result['trend']['momentum_unit'], 'weeks')
        self.assertEqual(result['trend']['momentum20'], .024)
        self.assertEqual(result['trend']['available_on'], '2026-10-16')
        self.assertTrue(result['state']['eligible'])

    def test_missing_future_or_stale_weekly_evidence_is_not_rebuilt(self):
        for change in (lambda s: s.pop('ww_bond'),
                       lambda s: s['ww_bond'].update(available='2026-10-23'),
                       lambda s: s['ww_bond'].update(current_quote_date='2026-10-21')):
            with self.subTest(change=change):
                signal = saved_ww(); change(signal)
                bond = project_holding_rationale(signal)['assets'][3]
                self.assertIsNone(bond['eligible'])
                self.assertNotEqual(bond['original_gate']['timing']['status'], 'confirmed')

    def test_d0_projection_contract_is_unchanged(self):
        result = project_holding_rationale(signal_with_originals())
        self.assertNotIn('strategy', result)
        self.assertNotIn('weekly_gate', result)
        self.assertEqual(result['assets'][3]['original_gate']['kind'], 'defense_daily')
        self.assertIs(result['assets'][3]['original_gate']['state']['long'], True)


class WeeklySummaryTests(unittest.TestCase):
    def raw(self):
        raw = fixture()
        raw['account'].update(id='D0I-BOND-WW-forward-paper', strategy='D0I-BOND-WW')
        raw['signal'].update(strategy='D0I-BOND-WW', ww_bond=weekly('2026-10-27'))
        return raw

    def project(self, raw):
        return project_signal_summary(raw, now=NOW, source_status='ready', observer_status='running')

    def test_matching_ww_saved_plan_projects_normally(self):
        result = self.project(self.raw())
        self.assertEqual((result['action'], result['execution_status']), ('hold', 'ready'))

    def test_cross_account_strategy_or_invalid_fallback_is_not_actionable(self):
        for change in (lambda r: r['account'].update(strategy='D0'),
                       lambda r: r['account'].update(strategy={'unknown': 'strategy'}),
                       lambda r: r['signal'].update(strategy=['D0I-BOND-WW']),
                       lambda r: r['signal'].pop('ww_bond'),
                       lambda r: r['signal']['ww_bond'].update(available='2026-10-28'),
                       lambda r: r['signal']['weights'].update(sh518880='0.1', sh511010='0.9')):
            raw = self.raw(); change(raw)
            result = self.project(raw)
            self.assertEqual(result['action'], 'wait')
            self.assertEqual(result['execution_status'], 'needs_review')


if __name__ == '__main__':
    unittest.main()
