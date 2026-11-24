"""Nominal cached price projection tests; synthetic data, no live sources."""
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
from realtime_paper_price_history import (extract_daily_price_histories,
    project_daily_price_history, SYMBOLS, MAX_SOURCE_ROWS)


def fixture(dates=None, closes=None):
    dates = dates or ['2026-10-16', '2026-10-19', '2026-10-20', '2026-10-21', '2026-10-22', '2026-10-23']
    closes = closes or [10, 11, 9.9, 9.9, 10.2, 10.5]
    signal = dict(id='saved-id', history_hash='saved-history', spec_hash='saved-spec',
                  confirmed_day=dates[-1], history_cutoff=dates[-1],
                  reference_prices={s: str(closes[-1]) for s in SYMBOLS})
    inputs = SimpleNamespace(
        bars={s: [dict(date=d, close=p) for d, p in zip(dates, closes)] for s in SYMBOLS},
        actions={s: dict(dividends=[], splits=[]) for s in SYMBOLS},
        splits={s: {} for s in SYMBOLS})
    market = SimpleNamespace(dates=list(dates), inputs=inputs)
    return signal, deepcopy(signal), (signal['confirmed_day'], signal['history_hash']), market


def extract(data):
    return extract_daily_price_histories(*data)


class DailyPriceHistoryTests(unittest.TestCase):
    def test_nominal_prices_signed_ratios_weekend_spacing_and_purity(self):
        data = fixture(); before = deepcopy(data)
        for name in ('at', 'observation', 'read'):
            setattr(data[-1], name, Mock(side_effect=AssertionError('no market calls')))
        with patch('builtins.open', side_effect=AssertionError('no IO')), patch('sqlite3.connect', side_effect=AssertionError('no DB')):
            result = extract(data)
        for history in result.values():
            self.assertEqual(history['status'], 'available')
            self.assertEqual(history['basis'], 'unadjusted_close')
            self.assertFalse(history['truncated'])
            points = history['points']
            self.assertIsNone(points[0]['change_ratio'])
            self.assertEqual(points[1]['previous_date'], '2026-10-16')
            self.assertFalse(points[1]['break_before'])
            self.assertAlmostEqual(points[1]['change_ratio'], .1)
            self.assertAlmostEqual(points[2]['change_ratio'], -.1)
            self.assertEqual(points[3]['change_ratio'], 0)
            self.assertEqual(points[-1]['close'], 10.5)
        self.assertEqual(data[:3], before[:3])
        self.assertEqual(data[-1].inputs, before[-1].inputs)
        self.assertEqual(data[-1].dates, before[-1].dates)
        for name in ('at', 'observation', 'read'):
            getattr(data[-1], name).assert_not_called()
        json.dumps(result, allow_nan=False)

    def test_saved_cache_identity_and_key_required(self):
        for field in ('id', 'history_hash', 'spec_hash', 'confirmed_day', 'history_cutoff'):
            data = fixture(); data[0][field] = 'different'
            self.assertTrue(all(h['reason'] == 'signal_mismatch' for h in extract(data).values()), field)
        data = fixture()
        self.assertTrue(all(h['reason'] == 'signal_mismatch' for h in extract_daily_price_histories(data[0], data[1], ('wrong', 'saved-history'), data[3]).values()))
        for cached, market in ((None, data[3]), (data[1], None)):
            self.assertTrue(all(h['reason'] == 'cache_unavailable' for h in extract_daily_price_histories(data[0], cached, data[2], market).values()))

    def test_saved_endpoint_must_match_and_other_assets_stay_available(self):
        for value in ('999', None, True, 'NaN'):
            data = fixture(); data[0]['reference_prices'][SYMBOLS[0]] = value
            result = extract(data)
            self.assertEqual(result[SYMBOLS[0]]['reason'], 'series_mismatch')
            self.assertEqual(result[SYMBOLS[1]]['status'], 'available')
        data = fixture(); data[3].inputs.bars[SYMBOLS[0]].pop()
        self.assertEqual(extract(data)[SYMBOLS[0]]['reason'], 'series_mismatch')

    def test_known_missing_session_retains_price_but_suppresses_multiday_change(self):
        data = fixture(); data[3].inputs.bars[SYMBOLS[0]].pop(2)
        points = extract(data)[SYMBOLS[0]]['points']
        after = next(p for p in points if p['date'] == '2026-10-21')
        self.assertTrue(after['break_before'])
        self.assertIsNone(after['change_ratio'])
        self.assertEqual(after['close'], 9.9)
        self.assertEqual(after['previous_date'], '2026-10-19')
        self.assertFalse(points[-1]['break_before'])

    def test_nominal_close_changes_include_split_and_ex_date_price_changes(self):
        data = fixture(); inputs = data[3].inputs; symbol = SYMBOLS[0]
        inputs.actions[symbol] = dict(dividends=[dict(record='2026-10-20', ex='2026-10-21', pay='2026-10-23', cash_per_share=.1)],
                                     splits=[dict(date='2026-10-16', ratio=2)])
        inputs.splits[symbol] = {'2026-10-19': dict(effective='2026-10-19', ratio=2)}
        points = {p['date']: p for p in extract(data)[symbol]['points']}
        for when in ('2026-10-19', '2026-10-20', '2026-10-21', '2026-10-23'):
            point = points[when]
            self.assertFalse(point['break_before'])
            self.assertAlmostEqual(point['change_ratio'], point['close']/point['previous_close']-1)

    def test_missing_or_uncertain_event_metadata_cannot_suppress_nominal_price_change(self):
        for mutate in (lambda i,s: i.actions.pop(s), lambda i,s: i.splits.pop(s),
                       lambda i,s: i.actions[s].update(dividends=[{'ex': 'bad'}]),
                       lambda i,s: i.splits[s].update({'2026-10-19': {'effective': '2026-10-20', 'ratio': 2}})):
            data = fixture(); mutate(data[3].inputs, SYMBOLS[0])
            history = extract(data)[SYMBOLS[0]]
            self.assertEqual(history['status'], 'available')
            self.assertTrue(all(p['change_ratio'] is not None and not p['break_before'] for p in history['points'][1:]))
            self.assertEqual(history['points'][-1]['close'], 10.5)

    def test_120_point_window_keeps_prior_close_before_crop(self):
        days = []; current = date(2026, 1, 1)
        while len(days) < 125:
            if current.weekday() < 5: days.append(current.isoformat())
            current += timedelta(days=1)
        data = fixture(days, [100+i for i in range(125)])
        history = extract(data)[SYMBOLS[0]]
        self.assertEqual(len(history['points']), 120)
        self.assertTrue(history['truncated'])
        first = history['points'][0]
        self.assertEqual(first['date'], days[5]); self.assertEqual(first['previous_date'], days[4])
        self.assertEqual(first['previous_close'], 104)
        self.assertAlmostEqual(first['change_ratio'], 105/104-1)

    def test_future_bars_excluded_and_incorrect_calendar_rejected(self):
        data = fixture()
        for rows in data[3].inputs.bars.values(): rows.append(dict(date='2026-10-26', close=999))
        result = extract(data)
        self.assertTrue(all(h['points'][-1]['date'] == '2026-10-23' for h in result.values()))
        for bad in (None, [], ['not-a-date'], ['2026-10-23', '2026-10-16']):
            data = fixture(); data[3].dates = bad
            self.assertTrue(all(h['status'] != 'available' for h in extract(data).values()))

    def test_bad_prices_dates_and_oversize_source_fail_without_zero_fill(self):
        for bad in (None, True, 0, -1, float('inf'), 'NaN', '1e200'):
            data = fixture(); data[3].inputs.bars[SYMBOLS[0]][2]['close'] = bad
            h = extract(data)[SYMBOLS[0]]
            self.assertEqual(h['status'], 'invalid'); self.assertEqual(h['points'], [])
        data = fixture(); data[3].inputs.bars[SYMBOLS[0]][2]['date'] = '2026-10-19'
        self.assertEqual(extract(data)[SYMBOLS[0]]['status'], 'invalid')
        data = fixture(); data[3].inputs.bars[SYMBOLS[0]] = [{}] * (MAX_SOURCE_ROWS+1)
        self.assertEqual(extract(data)[SYMBOLS[0]]['status'], 'invalid')

    def test_http_projection_whitelists_and_rejects_tampering(self):
        data = fixture(); symbol = SYMBOLS[0]; good = extract(data)[symbol]
        unknown = deepcopy(good); unknown['private'] = 'secret'; unknown['points'][0]['private'] = 'secret'
        self.assertEqual(project_daily_price_history(unknown, data[0], symbol), good)
        changes = [lambda h: h.update(signal_key='old'), lambda h: h.update(source='another'),
                   lambda h: h.update(truncated='yes'), lambda h: h.update(points=h['points']*30),
                   lambda h: h['points'][1].update(change_ratio=10),
                   lambda h: h['points'][1].update(change_ratio='NaN'),
                   lambda h: h['points'][1].update(previous_close=999),
                   lambda h: h['points'][1].update(previous_date='2026-10-15'),
                   lambda h: h['points'][1].update(break_before=True),
                   lambda h: h['points'][-1].update(date='2026-10-26')]
        for mutate in changes:
            h = deepcopy(good); mutate(h)
            self.assertNotEqual(project_daily_price_history(h, data[0], symbol)['status'], 'available')
        h = deepcopy(good); h.update(status='invalid', reason='private arbitrary text')
        self.assertNotIn('private arbitrary text', json.dumps(project_daily_price_history(h, data[0], symbol)))


if __name__ == '__main__':
    unittest.main()
