"""Synthetic conditional-K50 gate tests, with no account or network access."""
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path
import json
import random
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
import bank_model
import d0i_bond_ww
from d0_bank_gate import (BANK, CHI, CODES, SCHEMA, BankState,
    ConditionalBankGate, apply_gate, relaxation_gate, step_bank)
from dynamic_allocation import DynamicSignals, config


def shadow(held=False, age=0, next_held=False):
    return dict(risk=float(held), holding_days=age, next_risk=float(next_held),
        reason='synthetic original K40 reference', entry=2. if held else None,
        peak=2.1 if held else None)


def obs(day, *, k=45., d=40., close=1., ma=2., ref=None):
    current = date.fromisoformat(day)
    friday = (current-timedelta(days=(current.weekday()-4) % 7)).isoformat()
    eligible = dict.fromkeys(CODES, False)
    eligible[CODES[2]] = True
    raw = dict(zip(CODES, (3., 4., 2., 1.)))
    return dict(day=day, strategy='D0', ready=dict.fromkeys(CODES, True),
        weights={c: float(eligible[c]) for c in CODES}, cash_weight=0.,
        longs=dict(eligible), bank_long=False,
        dynamic={c: dict(eligible=eligible[c], score=raw[c], effective_score=raw[c] if eligible[c] else 0.,
            momentum20=.02, momentum60=.03, volatility20=.10,
            score_ready=True, quote_date=day) for c in CODES},
        notes=dict.fromkeys(CODES, 'synthetic original note'),
        bank_state=ref or shadow(),
        features=dict(bank=dict(k=k, d=d, ready=True, entry=False, exit=False, positive=False),
            chi_market=dict(close=close, ma=ma, week_end=friday, available=friday)))


def market_for(observations):
    days = sorted(observations)
    prices = {day: dict(open=2.+i*.01, close=2.05+i*.01) for i, day in enumerate(days)}
    return SimpleNamespace(dates=days, bar_dates={BANK: days},
        look={BANK: prices}, inputs=SimpleNamespace(market=SimpleNamespace(
            daily=[dict(date=day, **price) for day, price in prices.items()])))


class TriggerTests(unittest.TestCase):
    def test_strict_confirmed_weekly_ma_comparison(self):
        day = '2026-10-28'
        for close, expected in ((1.999, True), (2., False), (2.001, False)):
            self.assertEqual(relaxation_gate(obs(day, close=close), day)[0], expected)

    def test_dates_and_missing_values_do_not_create_confirmation(self):
        day = '2026-10-28'
        patches = ({'available': None}, {'week_end': None}, {'available': 'bad'},
            {'week_end': '2026-10-30', 'available': '2026-10-30'},
            {'week_end': '2026-10-27', 'available': '2026-10-23'},
            {'close': None}, {'ma': float('nan')})
        for change in patches:
            with self.subTest(change=change):
                original = obs(day)
                original['features']['chi_market'].update(change)
                self.assertFalse(relaxation_gate(original, day)[0])

    def test_short_week_uses_original_known_at_date(self):
        day = '2026-10-12'
        original = obs(day)
        original['features']['chi_market'].update(week_end='2026-10-08', available=day)
        self.assertTrue(relaxation_gate(original, day)[0])
        original['features']['chi_market']['available'] = '2026-10-13'
        self.assertFalse(relaxation_gate(original, day)[0])

    def test_unready_or_stale_any_asset_disables_relaxation(self):
        day = '2026-10-28'
        for code in CODES:
            original = obs(day)
            original['dynamic'][code]['quote_date'] = '2026-10-27'
            self.assertFalse(relaxation_gate(original, day)[0])
        for code in (CHI, BANK):
            for location, key in (('ready', code), ('dynamic', code)):
                original = obs(day)
                if location == 'ready': original[location][key] = False
                else: original[location][key]['score_ready'] = False
                self.assertFalse(relaxation_gate(original, day)[0])

    def test_ineligible_above_ma_and_daily_dip_do_not_trigger(self):
        day = '2026-10-28'
        original = obs(day, close=2.1)
        original['chi_state'] = dict(close=1.0, market_ma=2., next_risk=0.)
        self.assertFalse(original['dynamic'][CHI]['eligible'])
        self.assertFalse(relaxation_gate(original, day)[0])


class ReferenceStateTests(unittest.TestCase):
    def test_k50_boundary_requires_new_cross(self):
        self.assertTrue(step_bank(BankState(), shadow(), True, 50., 49., 40., 40.)['next_eligible'])
        self.assertFalse(step_bank(BankState(), shadow(), True, 50.01, 49., 40., 40.)['next_eligible'])
        self.assertFalse(step_bank(BankState(), shadow(), True, 45., 40., 45., 40.)['next_eligible'])
        self.assertFalse(step_bank(BankState(), shadow(), True, 40., 40., 35., 40.)['next_eligible'])

    def test_next_open_day_one_then_twenty_day_exit_and_lock(self):
        state = BankState()
        enter = step_bank(state, shadow(), True, 45., 40., 35., 40.)
        self.assertEqual(enter['holding_days'], 0)
        self.assertFalse(enter['reference_held'])
        for age in range(1, 21):
            result = step_bank(state, shadow(), True, 48., 45., 45., 40.)
            self.assertEqual(result['holding_days'], age)
            self.assertEqual(result['next_eligible'], age < 20)
        self.assertEqual(result['reason'], 'time_limit_exit')
        blocked = step_bank(state, shadow(), True, 45., 40., 35., 40.)
        self.assertFalse(blocked['next_eligible'])
        self.assertTrue(blocked['blocked'])
        reset = step_bank(state, shadow(), True, 40., 40., 45., 40.)
        self.assertFalse(reset['blocked'])
        self.assertTrue(step_bank(state, shadow(), True, 45., 40., 40., 40.)['next_eligible'])

    def test_exit_checks_precede_entry(self):
        for k, d, reason in ((70., 60., 'high_threshold_exit'), (40., 40., 'dead_cross_or_equal_exit')):
            result = step_bank(BankState(), shadow(True, 3, True), True, k, d, 35., 40.)
            self.assertFalse(result['next_eligible'])
            self.assertEqual(result['reason'], reason)
        result = step_bank(BankState(), shadow(True, 20, True), True, 45., 40., 35., 40.)
        self.assertFalse(result['next_eligible'])
        self.assertEqual(result['reason'], 'time_limit_exit')

    def test_regime_transitions_inherit_then_restore_shadow_clock(self):
        state = BankState()
        result = step_bank(state, shadow(True, 19, True), True, 45., 40., 35., 40.)
        self.assertEqual(result['transition'], 'enter_relaxed')
        self.assertEqual(result['holding_days'], 19)
        self.assertFalse(step_bank(state, shadow(), True, 45., 40., 45., 40.)['next_eligible'])
        original = shadow(True, 4, True)
        result = step_bank(state, original, False, 45., 40., 45., 40.)
        self.assertEqual(result['transition'], 'return_to_original')
        self.assertEqual(result['holding_days'], 4)
        self.assertFalse(result['blocked'])
        self.assertTrue(result['next_eligible'])


class ProjectionAndCacheTests(unittest.TestCase):
    def fixture(self):
        days = ['2026-10-19', '2026-10-20', '2026-10-21', '2026-10-22', '2026-10-23']
        observations = {d: obs(d) for d in days}
        observations[days[0]] = obs(days[0], k=35., d=40.)
        observations[days[-1]] = obs(days[-1], close=2.1)
        return days, observations

    def test_raw_bank_score_and_current_state_projection(self):
        days, observations = self.fixture()
        gate = ConditionalBankGate(market_for(observations), lambda day: deepcopy(observations[day]))
        before = deepcopy(observations)
        entry = apply_gate(deepcopy(observations[days[1]]), gate.get(days[1]))
        self.assertEqual(entry['weights'][BANK], 4/6)
        self.assertEqual(entry['weights'][CODES[2]], 2/6)
        self.assertEqual(entry['dynamic'][BANK]['effective_score'], 4.)
        self.assertTrue(entry['features']['bank']['entry'])
        self.assertEqual(entry['bank_state']['next_risk'], 1.)
        self.assertEqual(entry['bank_state']['holding_days'], 0)
        self.assertEqual(entry['bank_gate']['schema'], SCHEMA)
        self.assertEqual(entry['bank_gate']['entry_k_limit'], 50)
        holding = apply_gate(deepcopy(observations[days[2]]), gate.get(days[2]))
        self.assertEqual(holding['bank_state']['holding_days'], 1)
        self.assertEqual(holding['bank_state']['entry'], 2.02)
        self.assertFalse(holding['features']['bank']['entry'])
        self.assertEqual(observations, before)

    def test_inactive_restores_original_target_and_reference(self):
        days, observations = self.fixture()
        gate = ConditionalBankGate(market_for(observations), lambda day: deepcopy(observations[day]))
        result = apply_gate(deepcopy(observations[days[-1]]), gate.get(days[-1]))
        self.assertEqual(result['weights'], observations[days[-1]]['weights'])
        self.assertEqual(result['bank_state'], observations[days[-1]]['bank_state'])
        self.assertEqual(result['features']['bank'], observations[days[-1]]['features']['bank'])
        self.assertEqual(result['bank_gate']['entry_k_limit'], 40)
        self.assertEqual(result['bank_gate']['transition'], 'return_to_original')

    def test_random_query_order_same_results_and_single_scan(self):
        days, observations = self.fixture()
        getter = Mock(side_effect=lambda day: deepcopy(observations[day]))
        gate = ConditionalBankGate(market_for(observations), getter)
        sequential = {day: gate.get(day) for day in days}
        self.assertEqual(getter.call_count, len(days))
        query = days * 4
        random.Random(50).shuffle(query)
        for day in query:
            self.assertEqual(gate.get(day), sequential[day])
        self.assertEqual(getter.call_count, len(days))
        reverse_getter = Mock(side_effect=lambda day: deepcopy(observations[day]))
        reverse = ConditionalBankGate(market_for(observations), reverse_getter)
        for day in reversed(days):
            self.assertEqual(reverse.get(day), sequential[day])
        self.assertEqual(reverse_getter.call_count, len(days))

    def test_prefix_and_returned_evidence_mutation_isolation(self):
        days, observations = self.fixture()
        full = ConditionalBankGate(market_for(observations), lambda day: deepcopy(observations[day]))
        full.get(days[-1])
        shorter = {d: observations[d] for d in days[:3]}
        short = ConditionalBankGate(market_for(shorter), lambda day: deepcopy(shorter[day]))
        for day in shorter:
            self.assertEqual(full.get(day), short.get(day))
        changed = full.get(days[1])
        changed['evidence']['quote_dates'][BANK] = 'future'
        changed['bank_state']['next_risk'] = 0.
        self.assertNotEqual(full.get(days[1]), changed)

    def test_missing_bank_bar_disables_and_resets_to_original(self):
        days, observations = self.fixture()
        market = market_for(observations)
        market.bar_dates[BANK] = [d for d in days if d != days[2]]
        del market.look[BANK][days[2]]
        gate = ConditionalBankGate(market, lambda day: deepcopy(observations[day]))
        result = gate.get(days[2])
        self.assertFalse(result['evidence']['active'])
        self.assertIn('bank_no_bar', result['evidence']['gate_reasons'])
        self.assertEqual(result['bank_state'], observations[days[2]]['bank_state'])

    def test_reference_entry_and_peak_keep_shadow_split_adjusted_units(self):
        days = ['2025-07-03', '2025-07-04', '2025-07-07', '2025-07-08']
        observations = {day: obs(day) for day in days}
        observations[days[0]] = obs(days[0], k=35., d=40.)
        market = market_for(observations)
        # A 2-for-1 split halves executable prices; the original indicator and
        # reference engine multiplies later bars by the cumulative ratio.
        market.look[BANK][days[2]] = dict(open=1.1, close=1.2)
        market.look[BANK][days[3]] = dict(open=1.2, close=1.3)
        market.inputs.market.daily[2] = dict(date=days[2], open=2.2, close=2.4)
        market.inputs.market.daily[3] = dict(date=days[3], open=2.4, close=2.6)
        gate = ConditionalBankGate(market, lambda day: deepcopy(observations[day]))
        on_split = gate.get(days[2])
        self.assertEqual(on_split['bank_state']['entry'], 2.2)
        self.assertEqual(on_split['bank_state']['peak'], 2.4)
        later = gate.get(days[3])
        self.assertEqual(later['bank_state']['entry'], 2.2)
        self.assertEqual(later['bank_state']['peak'], 2.6)
        # An inherited pre-split shadow position stays in the identical unit.
        inherited = deepcopy(observations)
        inherited[days[0]] = obs(days[0], ref=shadow(True, 3, True))
        carried = ConditionalBankGate(market, lambda day: deepcopy(inherited[day]))
        record = carried.get(days[3])
        self.assertEqual(record['bank_state']['entry'], 2.)
        self.assertEqual(record['bank_state']['peak'], 2.6)


class LegacyIsolationTests(unittest.TestCase):
    def test_legacy_spec_matches_previous_dynamic_schema_and_ww(self):
        old = bank_model.legacy_d0_spec()
        new = bank_model.spec('D0')
        self.assertEqual(old['schema'], 'etfsuite.dynamic.v1')
        self.assertNotIn('bank_gate', old)
        self.assertEqual(new['schema'], 'etfsuite.dynamic.v2')
        self.assertEqual(new['bank_gate']['relaxed_entry_k_limit'], 50)
        self.assertEqual(new['signal_rules'], old['signal_rules'])
        self.assertEqual(d0i_bond_ww.spec()['original_stock_spec'], old)
        for code in ('D5', 'DW'):
            self.assertEqual(config(code), config(code, legacy=True))
            self.assertNotIn('bank_gate', bank_model.spec(code))

    def test_explicit_legacy_observation_bypasses_public_d0(self):
        expected = {'legacy': True}
        market = SimpleNamespace(signals=SimpleNamespace(legacy_d0_observation=Mock(return_value=expected)),
            observation=Mock(side_effect=AssertionError('new D0 must not be called')))
        self.assertIs(bank_model.legacy_d0_observation(market, '2026-10-28'), expected)
        market.signals.legacy_d0_observation.assert_called_once_with('2026-10-28')

    def test_other_dynamic_modes_never_construct_k50_cache(self):
        dynamic = DynamicSignals.__new__(DynamicSignals)
        dynamic.legacy_observation = Mock(return_value={'unchanged': True})
        for code in ('D5', 'DW'):
            self.assertEqual(dynamic.observation(code, '2026-10-28'), {'unchanged': True})
        self.assertFalse(hasattr(dynamic, '_conditional_bank'))


class NativeCopyIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from trade_book import Market
        path = Path(__file__).resolve().parents[1] / 'production' / '初始行情.json'
        cls.market = Market(data=json.loads(path.read_text(encoding='utf-8-sig')))

    def test_warmed_native_market_deepcopy_rebinds_engine_and_lock(self):
        market = self.market
        expected = market.observation('D0', market.latest)
        copied = deepcopy(market)
        old_gate = market.signals.dynamic._conditional_bank
        new_gate = copied.signals.dynamic._conditional_bank
        self.assertIsNot(old_gate, new_gate)
        self.assertIsNot(old_gate.lock, new_gate.lock)
        self.assertIs(new_gate.market, copied)
        self.assertIs(new_gate.original_observation.__self__, copied.signals.dynamic)
        self.assertEqual(copied.observation('D0', copied.latest), expected)
        # Mutating the copied engine is observed by its bound callback only.
        day = copied.latest
        copied.signals.dynamic.stats[BANK][day]['score'] += 1.
        self.assertNotEqual(new_gate.original_observation(day)['dynamic'][BANK]['score'],
            old_gate.original_observation(day)['dynamic'][BANK]['score'])
        new_gate.cache[day]['evidence']['gate_reasons'].append('copy-only')
        self.assertNotIn('copy-only', old_gate.cache[day]['evidence']['gate_reasons'])
        self.assertEqual(market.observation('D0', day), expected)

    def test_reference_replay_after_latest_signal_remains_available(self):
        from realtime_paper_comparison_model import replay_reference
        market = self.market
        expected = market.observation('D0', market.latest)
        with tempfile.TemporaryDirectory(prefix='d0-k50-copy-test-') as directory:
            result = replay_reference(market, market.dates[-3], market.latest, '100000', directory=directory)
        self.assertEqual(result['status'], 'available', result.get('reason'))
        self.assertEqual([p['date'] for p in result['points']], market.dates[-3:])
        self.assertEqual(market.observation('D0', market.latest), expected)


if __name__ == '__main__':
    unittest.main()
