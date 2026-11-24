"""The real native reference book, driven only by small synthetic markets."""
from copy import deepcopy
from datetime import date, datetime, timezone, timedelta
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
import trade_book as native
from realtime_paper_comparison_model import replay_reference, estimate_reference_live, METHOD, FEES


TZ = timezone(timedelta(hours=8))
NOW = datetime(2026, 10, 28, 10, 0, tzinfo=TZ)
CODES = native.CODES
GOLD = 'sh518880'


class SyntheticMarket:
    def __init__(self, today=False, weights=None):
        self.dates = ['2026-10-23', '2026-10-26', '2026-10-27'] + (['2026-10-28'] if today else [])
        self.latest = self.dates[-1]
        self.hash = 'synthetic-confirmed-market'
        self.inputs = SimpleNamespace(actions={c: {'dividends': []} for c in CODES},
                                      splits={c: {} for c in CODES})
        self.prices = {d: {'open': 10 + i, 'close': 11 + i} for i, d in enumerate(self.dates)}
        self.observations = {d: dict(day=d, weights={c: float(c == GOLD) for c in CODES},
                                   reason='Synthetic original D0 gate', features={}, state='dynamic')
                             for d in self.dates}
        for day, symbol in (weights or {}).items():
            self.observations[day]['weights'] = {c: float(c == symbol) for c in CODES}
        self.called_days = []
        self.on_observation = None

    def at(self, day, opening=False):
        return dict(day=day, market_hash=self.hash,
                    prices={c: self.prices[day]['open' if opening else 'close'] for c in CODES},
                    dates={c: day for c in CODES})

    def observation(self, code, day):
        self.called_days.append(day)
        if self.on_observation:
            self.on_observation(day)
        return self.observations[day]  # Deliberately shared: wrapper must copy.


def batch(now=NOW, price=13.5, opening=13., symbols=CODES):
    return dict(source='Synthetic public quotes', received_at=now.isoformat(),
                quotes={c: dict(symbol=c, day=now.date().isoformat(), quote_at=(now-timedelta(seconds=1)).isoformat(),
                                price=price, open=opening, previous_close=13., started=True)
                        for c in symbols})


class ReferenceModelTests(unittest.TestCase):
    def replay(self, market=None, end='2026-10-27', capital='100000.00', **kwargs):
        return replay_reference(market or SyntheticMarket(), '2026-10-23', end, capital, **kwargs)

    def test_anchor_is_cash_and_first_trade_uses_the_following_open(self):
        market = SyntheticMarket()
        result = self.replay(market, end='2026-10-23')
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['points'][0]['equity'], '100000.00')
        self.assertEqual(result['state']['fees'], 0)
        self.assertTrue(all(p['qty'] == 0 for p in result['state']['positions'].values()))
        self.assertEqual(result['state']['pending']['day'], '2026-10-23')
        later = self.replay(market, end='2026-10-26')
        self.assertEqual(later['status'], 'available')
        self.assertGreater(later['state']['positions'][GOLD]['qty'], 0)
        self.assertGreater(later['state']['fees'], 0)
        self.assertEqual([p['date'] for p in later['points']], ['2026-10-23', '2026-10-26'])

    def test_live_uses_yesterdays_frozen_target_without_today_observation(self):
        market = SyntheticMarket()
        reference = self.replay(market)
        original = deepcopy(reference)
        called = list(market.called_days)
        market.on_observation = lambda day: self.fail('live requested a close signal: '+day)
        result = estimate_reference_live(reference, market, batch(), now=NOW)
        self.assertEqual(result['status'], 'available')
        self.assertEqual(market.called_days, called)
        self.assertEqual(reference, original)
        self.assertEqual(result['quote_at'], (NOW-timedelta(seconds=1)).isoformat())
        self.assertEqual(result['at'], NOW.isoformat())
        self.assertNotIn('state', result)
        self.assertNotIn('points', result)

    def test_live_matches_later_confirmed_day_equity_before_its_new_signal(self):
        old = SyntheticMarket()
        reference = self.replay(old)
        live = estimate_reference_live(reference, old, batch(), now=NOW)
        complete = SyntheticMarket(today=True, weights={'2026-10-28': CODES[1]})
        complete.prices['2026-10-28'] = dict(open=13., close=13.5)
        official = self.replay(complete, end='2026-10-28')
        self.assertEqual(live['status'], 'available')
        self.assertEqual(official['status'], 'available')
        self.assertEqual(live['equity'], official['points'][-1]['equity'])
        self.assertEqual(reference['state']['day'], '2026-10-27')
        self.assertEqual(official['state']['auto']['evaluated'], '2026-10-28')

    def test_t1_release_and_next_open_rotation_use_native_rules(self):
        rotations = {'2026-10-23': CODES[0], '2026-10-26': CODES[1], '2026-10-27': GOLD}
        old = SyntheticMarket(weights=rotations)
        reference = self.replay(old)
        self.assertGreater(reference['state']['positions'][CODES[1]]['qty'], 0)
        self.assertIn('2026-10-27', reference['state']['positions'][CODES[1]]['locked'])
        live = estimate_reference_live(reference, old, batch(), now=NOW)
        complete = SyntheticMarket(today=True, weights=rotations)
        complete.prices['2026-10-28'] = dict(open=13., close=13.5)
        official = self.replay(complete, end='2026-10-28')
        self.assertEqual(live['status'], 'available')
        self.assertEqual(live['equity'], official['points'][-1]['equity'])
        self.assertEqual(official['state']['positions'][CODES[1]]['qty'], 0)

    def test_native_corporate_actions_and_dividend_value_are_preserved(self):
        old, complete = SyntheticMarket(), SyntheticMarket(today=True)
        dividend = dict(record='2026-10-27', ex='2026-10-28', pay='2026-10-28', cash_per_share=.1)
        for market in (old, complete):
            market.inputs.splits[GOLD]['2026-10-28'] = dict(ratio=2., rounding='floor')
            market.inputs.actions[GOLD]['dividends'] = [deepcopy(dividend)]
        reference = self.replay(old)
        live = estimate_reference_live(reference, old, batch(price=6.75, opening=6.5), now=NOW)
        complete.prices['2026-10-28'] = dict(open=6.5, close=6.75)
        official = self.replay(complete, end='2026-10-28')
        self.assertEqual(live['status'], 'available')
        self.assertEqual(live['equity'], official['points'][-1]['equity'])
        self.assertGreater(official['state']['dividends'], 0)

    def test_cash_reference_needs_no_market_quote(self):
        market = SyntheticMarket(weights={day: None for day in SyntheticMarket().dates})
        reference = self.replay(market)
        result = estimate_reference_live(reference, market, None, now=NOW)
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['equity'], '100000.00')
        self.assertTrue(result['cash_only'])
        self.assertIsNone(result['quote_at'])

    def test_bad_stale_future_and_mixed_day_quotes_are_rejected(self):
        market = SyntheticMarket(); reference = self.replay(market)
        mutations = [lambda b: b.update(source=''),
                     lambda b: b.update(received_at=(NOW-timedelta(seconds=61)).isoformat()),
                     lambda b: b.update(received_at=(NOW+timedelta(seconds=1)).isoformat()),
                     lambda b: b['quotes'][GOLD].update(quote_at=(NOW+timedelta(seconds=1)).isoformat()),
                     lambda b: b['quotes'][GOLD].update(day='2026-10-27'),
                     lambda b: b['quotes'][GOLD].update(symbol=CODES[0]),
                     lambda b: b['quotes'][GOLD].update(started=False),
                     lambda b: b['quotes'][GOLD].update(open=0),
                     lambda b: b['quotes'][GOLD].update(price=float('nan')),
                     lambda b: b['quotes'][GOLD].update(open=True),
                     lambda b: b['quotes'][GOLD].update(previous_close=-1),
                     lambda b: b['quotes'][GOLD].update(low=14, high=15),
                     lambda b: b['quotes'][GOLD].update(high=14),
                     lambda b: b['quotes'].pop(GOLD)]
        for change in mutations:
            quote = batch(); change(quote)
            with self.subTest(change=repr(change)):
                result = estimate_reference_live(reference, market, quote, now=NOW)
                self.assertEqual(result['status'], 'unavailable')
                self.assertIsNone(result['equity'])
                self.assertIsNone(result['at'])

    def test_quote_time_must_be_an_observed_trading_period(self):
        market = SyntheticMarket(); reference = self.replay(market)
        for hour, minute in ((8, 0), (12, 0), (16, 0)):
            moment = NOW.replace(hour=hour, minute=minute)
            self.assertEqual(estimate_reference_live(reference, market, batch(moment), now=moment)['status'], 'unavailable')

    def test_missing_calendar_and_skipped_confirmed_sessions_do_not_project(self):
        market = SyntheticMarket(); reference = self.replay(market)
        for moment in (NOW.replace(day=29), NOW.replace(month=12, day=31),
                       NOW.replace(year=2027, month=1, day=1)):
            self.assertEqual(estimate_reference_live(reference, market, batch(moment), now=moment)['status'], 'unavailable')

    def test_reference_must_remain_at_the_current_confirmed_cutoff(self):
        market = SyntheticMarket(); reference = self.replay(market)
        for mutate in (lambda r: r.update(method='other'), lambda r: r.update(source_cutoff='2026-10-26'),
                       lambda r: r['state']['auto'].update(evaluated=None),
                       lambda r: r['state']['pending'].update(day='2026-10-28')):
            changed = deepcopy(reference); mutate(changed)
            self.assertEqual(estimate_reference_live(changed, market, batch(), now=NOW)['status'], 'unavailable')

    def test_explicit_temporary_children_do_not_touch_other_accounts(self):
        with tempfile.TemporaryDirectory() as root:
            sentinel = Path(root)/'existing-account.sqlite3';sentinel.write_bytes(b'preserve')
            with patch('trade_book.home', side_effect=AssertionError('no default account folder')):
                reference = self.replay(directory=root)
                live = estimate_reference_live(reference, SyntheticMarket(), batch(), now=NOW, directory=root)
            self.assertEqual(reference['status'], 'available')
            self.assertEqual(live['status'], 'available')
            self.assertEqual(sentinel.read_bytes(), b'preserve')
            self.assertEqual([p.name for p in Path(root).iterdir()], ['existing-account.sqlite3'])

    def test_market_values_and_fee_globals_are_not_modified(self):
        market = SyntheticMarket(); before = deepcopy((market.prices, market.observations, market.inputs, market.dates))
        fees = (native.RATE, native.SLIP, deepcopy(FEES))
        with patch('socket.create_connection', side_effect=AssertionError('no network')):
            reference = self.replay(market)
            quote = batch(); original_quote = deepcopy(quote)
            live = estimate_reference_live(reference, market, quote, now=NOW)
        self.assertEqual(live['status'], 'available')
        self.assertEqual((market.prices, market.observations, market.inputs, market.dates), before)
        self.assertEqual(quote, original_quote)
        self.assertEqual((native.RATE, native.SLIP, FEES), fees)
        live['fees']['commission'] = 99
        self.assertEqual(FEES['commission'], .0003)

    def test_replay_does_not_initialize_caches_on_the_supplied_market(self):
        class LazyMarket(SyntheticMarket):
            def observation(self, code, day):
                self.signal_cache = day
                return super().observation(code, day)
        market = LazyMarket()
        result = self.replay(market)
        self.assertEqual(result['status'], 'available')
        self.assertFalse(hasattr(market, 'signal_cache'))
        self.assertEqual(market.called_days, [])

    def test_minimum_capital_bad_ranges_and_cancellation_are_bounded(self):
        self.assertEqual(self.replay(capital='999.99')['reason'], 'capital_below_model_minimum')
        self.assertEqual(self.replay(capital='999.999')['reason'], 'capital_below_model_minimum')
        for value in (True, 'NaN', '-1', float('inf'), '1000000000.001'):
            self.assertEqual(self.replay(capital=value)['status'], 'unavailable')
        event = threading.Event();event.set()
        self.assertEqual(self.replay(stop=event)['reason'], 'cancelled')
        event.clear();market = SyntheticMarket();market.on_observation = lambda day: event.set()
        self.assertEqual(self.replay(market, end='2026-10-23', stop=event)['reason'], 'cancelled')
        self.assertEqual(replay_reference(SyntheticMarket(), '2026-10-26', '2026-10-23', 100000)['status'], 'unavailable')
        long = SyntheticMarket()
        long.dates = [(date(2012, 1, 4)+timedelta(days=i)).isoformat() for i in range(5001)]
        long.latest = long.dates[-1]
        self.assertEqual(replay_reference(long, long.dates[0], long.latest, 100000)['reason'], 'range_too_large')

    def test_closed_old_marks_are_explicit_breaks_not_fresh_prices(self):
        market = SyntheticMarket()
        actual = market.at
        def at(day, opening=False):
            quote = actual(day, opening)
            if day == '2026-10-27':
                quote['dates'][GOLD] = '2026-10-26'
            return quote
        market.at = at
        result = self.replay(market)
        self.assertEqual(result['status'], 'available')
        self.assertTrue(result['points'][-1]['break_before'])
        self.assertEqual(result['points'][-1]['stale_assets'], [GOLD])


if __name__ == '__main__':
    unittest.main()
