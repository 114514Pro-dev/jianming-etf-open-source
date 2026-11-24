"""A rule change invalidates targets/reference values without rewriting history."""
from copy import deepcopy
import unittest

import test_d0_history_continuation as history_fixture
from test_d0_comparison_model import SyntheticMarket, batch, NOW
from realtime_paper_comparison_model import (
    replay_reference, estimate_reference_live, reference_matches, METHOD,
)


class SignalVersionTests(unittest.TestCase):
    setUp = history_fixture.HistoryTests.setUp
    publish = history_fixture.HistoryTests.publish
    new_archive = history_fixture.HistoryTests.new_archive
    source = history_fixture.HistoryTests.source
    quote = history_fixture.HistoryTests.quote

    def test_same_day_spec_change_rebuilds_signal_without_changing_history(self):
        source = self.source()
        specification = {'rule': 'original40'}
        source.spec_factory = lambda _: deepcopy(specification)
        self.quote(0)
        first = source.read()['signal']
        self.assertIsNotNone(first)
        key = source._signal_key
        history = self.original_path.read_bytes()
        specification['rule'] = 'conditional50'
        second = source.read(first)['signal']
        self.assertIsNotNone(second)
        self.assertEqual(source._signal_key, key)
        self.assertNotEqual(first['spec_hash'], second['spec_hash'])
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(first['history_hash'], second['history_hash'])
        self.assertEqual(second['version'], 'D0-forward-bank-ma50-v1')
        self.assertEqual(self.original_path.read_bytes(), history)
        self.assertEqual(source.read(second)['signal'], second)


class ModelVersionTests(unittest.TestCase):
    def test_legacy_model_cannot_be_valued_as_the_current_d0(self):
        market = SyntheticMarket()
        current = replay_reference(market, market.dates[0], market.latest, '100000.00')
        self.assertEqual(current['status'], 'available')
        self.assertEqual(current['method'], METHOD)
        self.assertTrue(reference_matches(current))
        legacy = deepcopy(current)
        legacy['method'] = 'native_d0_next_open'
        self.assertFalse(reference_matches(legacy))
        self.assertEqual(estimate_reference_live(legacy, market, batch(), now=NOW)['status'], 'unavailable')
        self.assertEqual(estimate_reference_live(current, market, batch(), now=NOW)['status'], 'available')


if __name__ == '__main__':
    unittest.main()
