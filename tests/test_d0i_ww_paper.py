"""Synthetic WW budget, completed-week causality and isolated paper persistence."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
import d0i_bond_ww as ww
from realtime_paper_engine import PaperLedger
from realtime_paper_service import PaperService, ReadOnlyPaperSource
from realtime_paper_history import AcceptedHistory

CN = timezone(timedelta(hours=8))


def observation(weights=None):
    weights = weights or dict(zip(ww.SYMBOLS, (0., 0., .5, .5)))
    return dict(weights=weights, longs={c: True for c in ww.SYMBOLS},
        dynamic={c: dict(score=2., eligible=True, effective_score=2., score_ready=True,
                        quote_date='2026-10-30') for c in ww.SYMBOLS},
        features={}, notes={c: 'synthetic' for c in ww.SYMBOLS}, reason='synthetic')


class SyntheticMarket:
    def __init__(self, raw=None, gate=True):
        self.raw = raw or observation()
        self._d0i_ww_weekly_cache = dict(availability=['2026-10-23'], features=[dict(
            week_end='2026-10-23', available='2026-10-23', value=160., close=145.,
            weeks=70, sma60weeks=150., momentum20weeks=.02, weekly_ready=True,
            weekly_indicator_gate=gate)])
    def observation(self, code, day):
        assert code == 'D0'
        return self.raw


class WeeklyGateTests(unittest.TestCase):
    def test_weekly_warmup_is_sixty_and_momentum_is_twenty_weeks(self):
        origin = date(2025, 1, 6)
        rows = [dict(date=(origin+timedelta(weeks=i, days=d)).isoformat(), value=100+i,
                     close=100+i) for i in range(61) for d in range(5)]
        result = ww.weekly_features(rows)
        self.assertFalse(result[58]['weekly_ready'])
        self.assertTrue(result[59]['weekly_ready'])
        self.assertEqual(result[59]['sma60weeks'], sum(range(100, 160))/60)
        self.assertAlmostEqual(result[59]['momentum20weeks'], 159/139-1)
        self.assertTrue(result[59]['weekly_indicator_gate'])

    def test_short_week_requires_next_observed_week_first_close(self):
        rows = [dict(date=d, value=100., close=100.) for d in
                ('2026-09-21', '2026-09-22', '2026-09-23', '2026-09-24')]
        self.assertEqual(ww.completed_weeks(rows), [])
        longer = rows + [dict(date='2026-09-28', value=101., close=101.)]
        self.assertEqual(ww.completed_weeks(longer)[0]['week_end'], '2026-09-24')
        self.assertEqual(ww.completed_weeks(longer)[0]['available'], '2026-09-28')

    def test_stock_priority_exact_budget_gold_exclusion_and_original_immutable(self):
        raw = observation(dict(zip(ww.SYMBOLS, (.1, .2, .3, .4))))
        before = deepcopy(raw)
        result = ww.observation(SyntheticMarket(raw), '2026-10-30')
        self.assertAlmostEqual(result['weights'][ww.STOCKS[0]], 1/3, places=14)
        self.assertEqual(sum(Decimal(str(x)) for x in result['weights'].values()), 1)
        self.assertEqual(result['weights'][ww.GOLD], 0)
        self.assertEqual(result['weights'][ww.BOND], 0)
        self.assertEqual(raw, before)

    def test_fallback_requires_weekly_gate_and_current_quality(self):
        market = SyntheticMarket()
        self.assertEqual(ww.observation(market, '2026-10-30')['weights'][ww.BOND], 1)
        market.raw['dynamic'][ww.BOND]['quote_date'] = '2026-10-29'
        result = ww.observation(market, '2026-10-30')
        self.assertEqual(sum(result['weights'].values()), 0)
        self.assertTrue(result['ww_bond']['weekly_indicator_gate'])
        self.assertFalse(result['ww_bond']['indicator_effective'])
        self.assertEqual(sum(ww.observation(SyntheticMarket(gate=False), '2026-10-30')['weights'].values()), 0)


class IsolationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=os.environ.get('ETF_TEST_TMPDIR'))
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.now = datetime(2026, 10, 30, 10, tzinfo=CN)

    def signal(self, strategy):
        return dict(id='same-input-id', strategy=strategy, valid=True, market_hash='public-hash',
            spec_hash='specific-hash', reason='synthetic confirmed signal', day='2026-10-29',
            market_at='2026-10-29T15:00:00+08:00', data_cutoff='2026-10-29T15:00:00+08:00',
            signal_at='2026-10-29T16:11:00+08:00', known_at='2026-10-29T16:11:00+08:00',
            received_at='2026-10-29T16:11:00+08:00', eligible_at='2026-10-30T09:30:00+08:00',
            weights={ww.BOND: 1}, reference_prices={ww.BOND: 140})

    def test_two_ledgers_default_stopped_commands_and_accounts_isolated(self):
        original = PaperLedger(self.home/'original', now=lambda:self.now)
        candidate = PaperLedger(self.home/'ww', now=lambda:self.now, strategy=ww.CODE)
        old = original.create('1000', idempotency_key='same-create-key')
        new = candidate.create('2000', idempotency_key='same-create-key')
        self.assertEqual(old['account']['id'], 'D0-forward-paper')
        self.assertEqual(new['account']['id'], 'D0I-BOND-WW-forward-paper')
        self.assertFalse(new['account']['running'])
        self.assertEqual(new['orders'], [])
        candidate.set_running(True)
        self.assertFalse(original.snapshot()['account']['running'])
        self.assertEqual(original.snapshot()['account']['cash'], '1000.00')
        candidate.set_running(False)
        restarted = PaperLedger(self.home/'ww', now=lambda:self.now, strategy=ww.CODE)
        self.assertEqual(restarted.create('2000', idempotency_key='same-create-key'), new)
        with self.assertRaisesRegex(ValueError, 'strategy'):
            PaperLedger(self.home/'ww', now=lambda:self.now)

    def test_wrong_strategy_signal_and_gold_target_rejected_without_mutating(self):
        ledger = PaperLedger(self.home/'ww', now=lambda:self.now, strategy=ww.CODE)
        ledger.create('100000')
        before = ledger.snapshot()
        with self.assertRaises(ValueError):
            ledger.set_signal(self.signal('D0'))
        self.assertEqual(ledger.snapshot(), before)
        bad = self.signal(ww.CODE); bad['weights']={ww.GOLD: 1}
        with self.assertRaisesRegex(ValueError, 'gold'):
            ledger.set_signal(bad)
        self.assertEqual(ledger.snapshot(), before)
        ledger.set_signal(self.signal(ww.CODE))
        self.assertEqual(ledger.snapshot()['signal']['strategy'], ww.CODE)

    def test_service_rejects_mismatched_source_or_ledger(self):
        ledger = PaperLedger(self.home/'ww', now=lambda:self.now, strategy=ww.CODE)
        with self.assertRaisesRegex(ValueError, 'ledger strategy'):
            PaperService(self.home, ledger=ledger, start_worker=False)
        source = ReadOnlyPaperSource(self.home, strategy='D0')
        with self.assertRaisesRegex(ValueError, 'source strategy'):
            PaperService(self.home, source=source, ledger=ledger, strategy=ww.CODE, start_worker=False)

    def test_wrong_signal_from_source_never_enters_ledger(self):
        class WrongSource:
            def read(inner, previous_signal=None):
                return dict(signal=self.signal('D0'), source_status='ready')
        ledger = PaperLedger(self.home/'ww', now=lambda:self.now, strategy=ww.CODE)
        service = PaperService(self.home, source=WrongSource(), ledger=ledger, now=lambda:self.now,
                               strategy=ww.CODE, start_worker=False)
        result = service.poll_once()
        self.assertIsNone(result['signal'])
        self.assertEqual(result['reason'], 'signal_strategy_mismatch')
        self.assertEqual(result['orders'], [])

    def test_ww_reminder_identity_and_label_do_not_accept_original_d0_signal(self):
        from test_realtime_paper_regression import reminder_fixture
        from realtime_paper_alerts import project_trade_alerts
        raw = reminder_fixture()
        raw['account']['strategy'] = raw['signal']['strategy'] = ww.CODE
        options = dict(now='2026-10-20T10:00:00+08:00', source_status='ready', observer_status='running', command=False)
        result = project_trade_alerts(raw, **options)
        self.assertEqual(result['items'][0]['reference_status'], 'current_reference')
        self.assertIn(ww.CODE, result['items'][0]['label'])
        raw['signal']['strategy'] = 'D0'
        self.assertEqual(project_trade_alerts(raw, **options)['items'][0]['reference_status'], 'needs_review')

    def test_native_sources_share_public_inputs_but_keep_strategy_and_checkpoints_distinct(self):
        from bank_model import digest
        from realtime_paper_rationale import project_holding_rationale
        seed = json.loads((Path(__file__).resolve().parents[1]/'production/初始行情.json').read_text(encoding='utf-8-sig'))
        identity = digest(seed)
        folder = self.home/'行情快照'; folder.mkdir()
        (folder/(identity+'.json')).write_text(json.dumps(seed), encoding='utf-8')
        (self.home/'设置.json').write_text(json.dumps(dict(market=identity)), encoding='utf-8')
        moment = datetime(2026, 9, 14, 10, tzinfo=CN)
        sources = [ReadOnlyPaperSource(self.home, now=lambda:moment, strategy=c) for c in ('D0', ww.CODE)]
        signals = []
        for source in sources:
            with patch.object(source, '_batch', return_value=(None, 'quotes_missing')):
                result = source.read()
            self.assertIsNotNone(result['signal'], result.get('reason'))
            signal = result['signal']; signals.append(signal)
            self.assertEqual(signal['confirmed_day'], '2026-09-11')
            self.assertEqual(signal['strategy'], source.strategy)
            self.assertEqual(len(source._signal_key), 2 if source.strategy == 'D0' else 3)
        self.assertNotEqual(signals[0]['spec_hash'], signals[1]['spec_hash'])
        self.assertNotEqual(signals[0]['id'], signals[1]['id'])
        self.assertEqual(signals[0]['history_hash'], signals[1]['history_hash'])
        self.assertNotEqual(sources[0]._history_archive.folder, sources[1]._history_archive.folder)
        candidate = sources[1]
        rationale = project_holding_rationale(signals[1])
        self.assertEqual(rationale['assets'][3]['original_gate']['kind'], 'bond_weekly')
        charts = candidate.indicator_history(signals[1])
        self.assertEqual(charts[ww.BOND]['status'], 'available')
        self.assertEqual(charts[ww.BOND]['charts'][0]['frequency'], 'weekly')
        self.assertEqual(charts[ww.BOND]['charts'][0]['basis'], 'total_return_weekly_ma60')
        self.assertEqual(charts[ww.GOLD]['charts'], [])
        self.assertTrue(all(z['status']=='available' for z in candidate.daily_price_history(signals[1]).values()))


if __name__ == '__main__':
    unittest.main()
