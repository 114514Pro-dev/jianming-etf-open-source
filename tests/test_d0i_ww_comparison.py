"""WW reference identity and accounting stay separate from the original D0."""
from copy import deepcopy
from datetime import timedelta
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from realtime_paper_comparison_model import (
    replay_reference, estimate_reference_live, model_identity, reference_matches,
    METHOD, WW_STRATEGY, WW_METHOD)
from realtime_paper_comparison import D0ComparisonService
from realtime_paper_comparison_tail import retain_intraday
from test_d0_comparison_model import SyntheticMarket, NOW, batch, CODES, GOLD
from test_d0_comparison_service import Paper, Cache, indexed, close_at
from test_d0_comparison_history import fixture, DAYS, NOW as HISTORY_NOW
from test_d0_comparison_tail import fixture as tail_fixture, lines, NOW as TAIL_NOW

BANK = 'sh512800'


def ww_observation(market, day):
    return dict(day=day, strategy=WW_STRATEGY, weights={c: float(c == BANK) for c in CODES},
                reason='Synthetic verified WW target', features={}, state='weekly_bond_fallback')


class WWReferenceTests(unittest.TestCase):
    def test_native_execution_receives_ww_targets_and_retains_external_identity(self):
        market = SyntheticMarket()
        before = deepcopy(market.observations)
        original = replay_reference(market, market.dates[0], market.latest, '100000.00')
        with patch('d0i_bond_ww.observation', side_effect=ww_observation) as provider:
            improved = replay_reference(market, market.dates[0], market.latest, '100000.00', strategy=WW_STRATEGY)
        self.assertEqual((original['status'], improved['status']), ('available', 'available'))
        self.assertGreater(original['state']['positions'][GOLD]['qty'], 0)
        self.assertEqual(improved['state']['positions'][GOLD]['qty'], 0)
        self.assertGreater(improved['state']['positions'][BANK]['qty'], 0)
        self.assertEqual(improved['points'][0]['equity'], '100000.00')
        self.assertEqual(improved['strategy'], WW_STRATEGY)
        self.assertEqual(improved['method'], WW_METHOD)
        self.assertEqual(improved['spec_hash'], model_identity(WW_STRATEGY)['spec_hash'])
        self.assertTrue(reference_matches(improved, WW_STRATEGY))
        self.assertFalse(reference_matches(improved, 'D0'))
        self.assertEqual(market.observations, before)
        self.assertTrue(provider.called)
        self.assertTrue(all(call.args[1] <= market.latest for call in provider.call_args_list))

    def test_live_ww_uses_only_saved_plan_and_rejects_cross_strategy_reference(self):
        market = SyntheticMarket()
        with patch('d0i_bond_ww.observation', side_effect=ww_observation):
            improved = replay_reference(market, market.dates[0], market.latest, '100000.00', strategy=WW_STRATEGY)
        original = replay_reference(market, market.dates[0], market.latest, '100000.00')
        before = deepcopy(improved)
        with patch('d0i_bond_ww.observation', side_effect=AssertionError('unconfirmed strategy calculation')):
            live = estimate_reference_live(improved, market, batch(), now=NOW, strategy=WW_STRATEGY)
        self.assertEqual(live['status'], 'available')
        self.assertEqual(live['strategy'], WW_STRATEGY)
        self.assertEqual(improved, before)
        self.assertEqual(estimate_reference_live(original, market, batch(), now=NOW,
                                               strategy=WW_STRATEGY)['status'], 'unavailable')
        self.assertEqual(estimate_reference_live(improved, market, batch(), now=NOW)['status'], 'unavailable')
        changed = deepcopy(improved)
        changed['spec_hash'] = 'bad-version'
        self.assertEqual(estimate_reference_live(changed, market, batch(), now=NOW,
                                               strategy=WW_STRATEGY)['status'], 'unavailable')

    def test_retained_original_tail_is_not_reused_for_ww(self):
        current, previous = tail_fixture(), tail_fixture(True)
        current['strategy'], previous['strategy'] = WW_STRATEGY, 'D0'
        value = retain_intraday(current, previous, now=TAIL_NOW, same_identity=True)
        self.assertEqual(len(lines(value)['d0']['points']), 1)
        self.assertEqual(len(lines(value)['account']['points']), 1)


class WWComparisonServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.identity = model_identity(WW_STRATEGY)
        self.raw = fixture()
        self.raw['account'].update(id='D0I-BOND-WW-forward-paper', strategy=WW_STRATEGY)
        self.paper = Paper(self.raw)
        signal = self.paper.source._signal
        signal.update(strategy=WW_STRATEGY, spec_hash=self.identity['spec_hash'])
        self.paper.source._signal_key = (DAYS[-1], signal['history_hash'], WW_STRATEGY)
        self.indices = SimpleNamespace(caches={s: Cache(s) for s in ('sh000001', 'sz399006')})
        self.calls = []

    def model(self, market, anchor, end, amount, **kwargs):
        self.calls.append((anchor, end, amount))
        return dict(self.identity, status='available', reason=None,
                    points=[dict(date=d, at=close_at(d), equity=str(amount), break_before=d == anchor)
                            for d in DAYS if anchor <= d <= end],
                    state={'private_adapter': 'must not escape'}, source_cutoff=end)

    def service(self, **kwargs):
        options = dict(strategy=WW_STRATEGY, now=HISTORY_NOW, refresh_enabled=False,
                       model_runner=self.model, live_model_runner=lambda *a, **k: dict(status='unavailable'))
        options.update(kwargs)
        service = D0ComparisonService(self.temp.name, self.paper, self.indices, **options)
        self.addCleanup(service.close)
        return service

    def test_public_model_label_method_and_cache_are_ww(self):
        service = self.service()
        value = service.refresh(fetch_live=False)
        self.assertEqual(value['status'], 'available')
        self.assertEqual(value['strategy'], WW_STRATEGY)
        model = indexed(value)['d0']
        self.assertEqual(model['status'], 'available')
        self.assertEqual((model['method'], model['strategy']), (WW_METHOD, WW_STRATEGY))
        self.assertIn('周线择债', model['label'])
        self.assertNotIn('private_adapter', str(value))
        self.assertTrue(all(key[0] == WW_STRATEGY for key in service._models))
        self.assertEqual(service.snapshot(self.raw['account']['id']), value)
        self.assertEqual(service.snapshot('D0-forward-paper')['reason'], 'account_mismatch')
        self.assertEqual(service.snapshot('D0-forward-paper')['strategy'], WW_STRATEGY)

    def test_original_model_cannot_be_relabelled_as_ww(self):
        def original(*args, **kwargs):
            value = self.model(*args, **kwargs)
            value.update(strategy='D0', method=METHOD)
            return value
        service = self.service(model_runner=original)
        result = service.refresh(fetch_live=False)
        self.assertEqual(indexed(result)['d0']['status'], 'unavailable')
        self.assertEqual(indexed(result)['d0']['points'], [])
        self.assertEqual(service._models, {})

    def test_wrong_account_or_source_identity_never_generates_a_reference(self):
        for mutate in (lambda: self.raw['account'].update(strategy='D0'),
                       lambda: self.paper.source._signal.update(strategy='D0'),
                       lambda: setattr(self.paper.source, '_signal_key', (DAYS[-1], 'synthetic-market-hash')),
                       lambda: self.paper.source._signal.update(spec_hash='other-parameters')):
            with self.subTest(mutation=mutate):
                self.setUp()
                mutate()
                result = self.service().refresh(fetch_live=False)
                self.assertIn(result['reason'], ('account_mismatch', 'signal_cache_mismatch', 'spec_mismatch'))
                self.assertEqual(self.calls, [])

    def test_unknown_strategy_fails_before_a_worker_is_created(self):
        with self.assertRaises(ValueError):
            self.service(strategy='UNKNOWN')


if __name__ == '__main__':
    unittest.main()
