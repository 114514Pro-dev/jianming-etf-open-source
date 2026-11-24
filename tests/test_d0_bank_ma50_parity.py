"""Read-only production-seed integration checks for the D0-only bank gate."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

PRODUCTION = Path(__file__).resolve().parents[1] / 'production'
sys.path.insert(0, str(PRODUCTION))
import bank_model as model
import d0i_bond_ww as ww
from trade_book import Market


def without_hash(observation):
    result = deepcopy(observation)
    result.pop('market_hash', None)
    return result


class D0BankGateProductionParityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.block_network = patch('socket.socket.connect', side_effect=AssertionError('Offline seed test'))
        cls.block_network.start()
        cls.addClassCleanup(cls.block_network.stop)
        cls.pair = json.loads((PRODUCTION / '初始行情.json').read_text(encoding='utf-8-sig'))
        cls.market = Market(data=cls.pair)
        cls.days = [d for d in cls.market.dates if d >= '2018-01-02']

    def test_legacy_d0_weights_and_qualifications_remain_shared_with_other_dynamic_modes(self):
        for day in self.days:
            legacy = model.legacy_d0_observation(self.market, day)
            for code in ('D5', 'DW'):
                observation = self.market.observation(code, day)
                self.assertEqual(observation['weights'], legacy['weights'], (code, day))
                self.assertEqual(observation['dynamic'], legacy['dynamic'], (code, day))
                self.assertEqual(observation['bank_state'], legacy['bank_state'], (code, day))

    def test_d0_targets_change_only_inside_confirmed_bear_regime(self):
        changed = 0
        for day in self.days:
            observation = self.market.observation('D0', day)
            legacy = model.legacy_d0_observation(self.market, day)
            gate = observation['bank_gate']
            self.assertEqual(gate['schema'], 'd0.bank-ma50-k50.v1')
            self.assertEqual(gate['entry_k_limit'], 50 if gate['relaxed'] else 40)
            if gate['relaxed']:
                self.assertLess(gate['weekly_close'], gate['ma'])
                self.assertLessEqual(gate['week_end'], gate['available'])
                self.assertLessEqual(gate['available'], day)
            else:
                self.assertEqual(observation['weights'], legacy['weights'], day)
            changed += observation['weights'] != legacy['weights']
        self.assertGreater(changed, 0, 'Seed integration never exercises the new allocation')

    def test_ww_uses_legacy_stock_eligibility(self):
        for day in self.days:
            result = ww.observation(self.market, day)
            legacy = model.legacy_d0_observation(self.market, day)
            self.assertEqual(result['original_weights'], legacy['weights'], day)
            for symbol in ww.STOCKS:
                self.assertEqual(result['dynamic'][symbol], legacy['dynamic'][symbol], (day, symbol))
        self.assertEqual(ww.spec()['original_stock_spec'], model.legacy_d0_spec())
        self.assertNotEqual(model.spec('D0'), model.legacy_d0_spec())

    def test_arbitrary_call_order_and_mutation_do_not_change_outputs(self):
        sample = self.days[::37]
        expected = {day: without_hash(self.market.observation('D0', day)) for day in sample}
        for day in reversed(sample):
            result = self.market.observation('D0', day)
            self.assertEqual(without_hash(result), expected[day])
            result['weights']['sh512800'] = -1
            result['bank_gate']['holding_days'] = -1
            self.assertEqual(without_hash(self.market.observation('D0', day)), expected[day])

    def test_truncated_wednesday_does_not_change_prior_signals(self):
        cutoff = '2024-12-25'
        short = deepcopy(self.pair)
        for part in short.values():
            part['asof'] = cutoff
            for symbol in part['bars']:
                part['bars'][symbol] = [r for r in part['bars'][symbol] if r['date'] <= cutoff]
            for symbol in part['split_adjustments']:
                part['split_adjustments'][symbol] = {d: x for d, x in part['split_adjustments'][symbol].items() if d <= cutoff}
        truncated = Market(data=short)
        for day in truncated.dates:
            self.assertEqual(without_hash(truncated.observation('D0', day)),
                             without_hash(self.market.observation('D0', day)), day)


if __name__ == '__main__':
    unittest.main()
