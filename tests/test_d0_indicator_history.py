"""Synthetic cached indicators only: no market construction, IO or trading."""
from copy import deepcopy
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
from realtime_paper_charts import (extract_indicator_histories, project_indicator_history,
                                    SYMBOLS, MAX_SOURCE_ROWS)
from realtime_paper_service import ReadOnlyPaperSource, PaperService


def fixture():
    day = '2026-10-23'
    weekly = {
        '2026-10-09': dict(week_end='2026-10-08', available='2026-10-09', k=30, d=40, trix=-.3, signal=-.2, close=2.3, ma=2.4),
        '2026-10-16': dict(week_end='2026-10-16', available='2026-10-16', k=35, d=38, trix=-.2, signal=-.3, close=2.5, ma=2.6),
        day: dict(week_end=day, available=day, k=42, d=40, trix=-.125, signal=-.25, close=2.7, ma=2.6),
    }
    weekly50 = deepcopy(weekly)
    for row in weekly50.values():
        row['ma'] = 3.2
    dates = ['2026-10-19', '2026-10-21', day]
    bank = [dict(k=40 + i, d=30 + i, trix=None, signal=None, ma=None) for i in range(3)]
    defense = {symbol: {d: dict(quote_date=d, value=100 + i, ma=101, ma_window=window,
                momentum20=-.01, ready=True, long=False) for i, d in enumerate(dates)}
               for symbol, window in ((SYMBOLS[2], 120), (SYMBOLS[3], 60))}
    stats = {symbol: {d: dict(quote_date=d, momentum20=-.01 + i * .001,
                 momentum60=.034, volatility20=.19, score=99, score_ready=True)
              for i, d in enumerate(dates)} for symbol in SYMBOLS}
    signal = dict(id='saved-id', history_hash='saved-history', spec_hash='saved-spec', confirmed_day=day,
                  history_cutoff=day, weekly_date=day, weekly_confirmed=day, chi_quote_date=day,
                  chi_state={'date': day}, bank_state={'date': day},
                  features=dict(chi_weekly=deepcopy(weekly[day]), chi_market=deepcopy(weekly50[day]),
                    bank=deepcopy(bank[-1]), gold=deepcopy(defense[SYMBOLS[2]][day]), bond=deepcopy(defense[SYMBOLS[3]][day])),
                  dynamic={s: deepcopy(stats[s][day]) | dict(eligible=False, effective_score=0.) for s in SYMBOLS})
    market = SimpleNamespace(dates=dates, signals=SimpleNamespace(
        staged=SimpleNamespace(weekly=weekly, weekly50=weekly50, defense=defense),
        dynamic=SimpleNamespace(stats=stats), bank_features=bank, bank_index=dict(zip(dates, range(3)))))
    source = ReadOnlyPaperSource.__new__(ReadOnlyPaperSource)
    source._signal = deepcopy(signal)
    source._signal_key = (day, signal['history_hash'])
    source._market = market
    source.read = Mock(side_effect=AssertionError('chart must not read source'))
    return signal, source


def chart(histories, symbol, key):
    return next(c for c in histories[symbol]['charts'] if c['id'] == key)


class IndicatorHistoryTests(unittest.TestCase):
    def test_cache_projection_is_pure_and_preserves_negative_units_and_true_dates(self):
        signal, source = fixture()
        before = deepcopy((signal, source._signal, source._market))
        histories = source.indicator_history(signal)
        self.assertTrue(all(h['status'] == 'available' for h in histories.values()))
        trix = chart(histories, SYMBOLS[0], 'trix')
        self.assertEqual(trix['points'][-1]['values'], {'trix': -.125, 'signal': -.25})
        self.assertEqual(trix['points'][0]['date'], '2026-10-09')
        self.assertEqual(trix['points'][0]['period_end'], '2026-10-08')
        self.assertEqual(chart(histories, SYMBOLS[0], 'trend')['points'][-1]['values']['ma'], 3.2)
        self.assertEqual([p['date'] for p in chart(histories, SYMBOLS[1], 'skdj')['points']],
                         ['2026-10-19', '2026-10-21', '2026-10-23'])
        self.assertEqual({c['id'] for c in histories[SYMBOLS[1]]['charts']}, {'skdj', 'momentum', 'volatility'})
        self.assertNotIn('score', json.dumps(histories))
        self.assertEqual((signal, source._signal, source._market), before)
        source.read.assert_not_called()
        json.dumps(histories, allow_nan=False)

    def test_missing_cache_does_not_attempt_source_io_or_strategy_construction(self):
        signal, source = fixture()
        for attr in ('_signal', '_market'):
            old = getattr(source, attr); setattr(source, attr, None)
            with patch('builtins.open', side_effect=AssertionError('no IO')):
                results = source.indicator_history(signal)
            self.assertTrue(all(h['reason'] == 'cache_unavailable' for h in results.values()))
            setattr(source, attr, old)
        source.read.assert_not_called()

    def test_all_identity_components_and_cache_key_are_required(self):
        signal, source = fixture()
        for field in ('id', 'history_hash', 'spec_hash', 'confirmed_day', 'history_cutoff'):
            changed = deepcopy(signal); changed[field] = 'wrong'
            self.assertTrue(all(h['reason'] == 'signal_mismatch' for h in source.indicator_history(changed).values()), field)
        source._signal_key = ('2026-10-22', signal['history_hash'])
        self.assertTrue(all(h['reason'] == 'signal_mismatch' for h in source.indicator_history(signal).values()))

    def test_full_market_digest_is_not_confused_with_accepted_history_hash(self):
        signal, source = fixture(); source._market.hash = 'different-full-market-digest'
        self.assertTrue(all(h['status'] == 'available' for h in source.indicator_history(signal).values()))

    def test_cache_endpoint_must_match_saved_numbers_including_missing_saved_values(self):
        for value in (999, None, True, 'NaN'):
            signal, source = fixture(); signal['features']['chi_weekly']['trix'] = value
            result = source.indicator_history(signal)
            self.assertEqual(result[SYMBOLS[0]]['reason'], 'series_mismatch')
            self.assertEqual(result[SYMBOLS[2]]['status'], 'available')

    def test_independent_weekly_endpoint_dates_must_match(self):
        signal, source = fixture()
        signal['features']['chi_market'].update(available='2026-10-16', week_end='2026-10-16')
        self.assertEqual(source.indicator_history(signal)[SYMBOLS[0]]['reason'], 'series_mismatch')

    def test_missing_saved_dynamic_date_is_not_replaced_by_confirmed_day(self):
        signal, source = fixture(); signal['dynamic'][SYMBOLS[0]].pop('quote_date')
        self.assertEqual(source.indicator_history(signal)[SYMBOLS[0]]['reason'], 'series_mismatch')

    def test_future_cached_points_are_excluded_without_repeating_weekly_values(self):
        signal, source = fixture(); staged = source._market.signals.staged
        staged.weekly['2026-10-30'] = dict(available='2026-10-30', week_end='2026-10-30', k=99, d=99)
        stats = source._market.signals.dynamic.stats[SYMBOLS[0]]
        stats['2026-10-26'] = dict(quote_date='2026-10-26', momentum20=9)
        results = source.indicator_history(signal)
        self.assertEqual(len(chart(results, SYMBOLS[0], 'skdj')['points']), 3)
        self.assertTrue(all(p['date'] <= signal['confirmed_day'] for h in results.values() for c in h['charts'] for p in c['points']))

    def test_windows_crop_completed_indicators_only(self):
        signal, source = fixture(); legacy = source._market.signals
        endpoint = date.fromisoformat(signal['confirmed_day'])
        for n in range(1, 220):
            day = (endpoint - timedelta(days=7*n)).isoformat()
            legacy.staged.weekly[day] = dict(available=day, week_end=day, k=12, d=13, trix=-.2, signal=-.1)
            legacy.staged.weekly50[day] = dict(available=day, week_end=day, close=2, ma=3)
            for symbol in SYMBOLS:
                daily = (endpoint - timedelta(days=n)).isoformat()
                legacy.dynamic.stats[symbol].setdefault(daily, dict(quote_date=daily, momentum20=.1, momentum60=.2, volatility20=.3))
        result = source.indicator_history(signal)
        self.assertEqual(len(chart(result, SYMBOLS[0], 'skdj')['points']), 104)
        self.assertEqual(len(chart(result, SYMBOLS[0], 'momentum')['points']), 120)
        self.assertEqual(chart(result, SYMBOLS[0], 'skdj')['points'][-1]['values']['k'], 42)

    def test_bank_index_is_used_and_invalid_or_duplicate_indices_rejected(self):
        signal, source = fixture(); legacy = source._market.signals
        legacy.bank_features.reverse()
        legacy.bank_index = {d: 2-i for d, i in legacy.bank_index.items()}
        self.assertEqual(chart(source.indicator_history(signal), SYMBOLS[1], 'skdj')['points'][-1]['values']['k'], 42)
        legacy.bank_index['2026-10-20'] = legacy.bank_index['2026-10-19']
        self.assertEqual(source.indicator_history(signal)[SYMBOLS[1]]['status'], 'invalid')

    def test_input_series_size_is_bounded(self):
        signal, source = fixture()
        source._market.signals.staged.weekly = {str(i): {} for i in range(MAX_SOURCE_ROWS + 1)}
        self.assertEqual(source.indicator_history(signal)[SYMBOLS[0]]['reason'], 'invalid_history')

    def test_known_missing_trading_session_breaks_daily_line_without_filling_or_recomputing(self):
        signal, source = fixture()
        source._market.dates = ['2026-10-19', '2026-10-20', '2026-10-21', '2026-10-23']
        result = source.indicator_history(signal)
        points = chart(result, SYMBOLS[0], 'momentum')['points']
        self.assertEqual([p['date'] for p in points], ['2026-10-19', '2026-10-21', '2026-10-23'])
        self.assertEqual([p['break_before'] for p in points], [False, True, False])
        self.assertTrue(all(not p['break_before'] for p in chart(result, SYMBOLS[0], 'skdj')['points']))
        source.read.assert_not_called()

    def test_weekends_and_holidays_do_not_create_synthetic_gaps(self):
        signal, source = fixture()
        result = source.indicator_history(signal)
        self.assertTrue(all(not p['break_before'] for h in result.values() for c in h['charts'] for p in c['points']))

    def test_invalid_cached_session_order_is_rejected(self):
        signal, source = fixture(); source._market.dates.reverse()
        self.assertTrue(all(h['reason'] == 'invalid_history' for h in source.indicator_history(signal).values()))

    def test_nonfinite_boolean_and_missing_values_become_null_gaps(self):
        signal, source = fixture(); history = source.indicator_history(signal)[SYMBOLS[0]]
        history['charts'][0]['points'][1]['values'] = {'k': 'NaN', 'd': True}
        history['charts'][0]['points'][1]['break_before'] = True
        result = project_indicator_history(history, signal, SYMBOLS[0])
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['charts'][0]['points'][1]['values'], {'k': None, 'd': None})
        self.assertTrue(result['charts'][0]['points'][1]['break_before'])
        json.dumps(result, allow_nan=False)

    def test_http_projection_rejects_future_duplicate_malformed_and_excess_points(self):
        signal, source = fixture(); history = source.indicator_history(signal)[SYMBOLS[0]]
        mutations = [lambda h: h['charts'][0]['points'][0].update(date='2026-99-99'),
                     lambda h: h['charts'][0]['points'][-1].update(date='2026-10-30', available_on='2026-10-30'),
                     lambda h: h['charts'][0]['points'].append(deepcopy(h['charts'][0]['points'][-1])),
                     lambda h: h['charts'].append(deepcopy(h['charts'][0])),
                     lambda h: h['charts'][0].update(points=h['charts'][0]['points'] * 40),
                     lambda h: h['charts'][0]['points'][0].update(break_before=1),
                     lambda h: h['charts'][0]['points'][0].update(period_end='2026-10-30'),
                     lambda h: h['charts'][0]['points'][1].update(period_end='2026-10-08'),
                     lambda h: h['charts'][0].update(basis='invented')]
        for mutate in mutations:
            changed = deepcopy(history); mutate(changed)
            self.assertEqual(project_indicator_history(changed, signal, SYMBOLS[0])['status'], 'invalid')

    def test_http_projection_identity_and_endpoint_fail_closed_without_mutation(self):
        signal, source = fixture(); history = source.indicator_history(signal)[SYMBOLS[0]]
        for field in ('signal_key', 'confirmed_day'):
            changed = deepcopy(history); changed[field] = 'another'
            self.assertEqual(project_indicator_history(changed, signal, SYMBOLS[0])['reason'], 'signal_mismatch')
        history['charts'][0]['points'][-1]['values']['k'] = 99
        before = deepcopy(history)
        self.assertEqual(project_indicator_history(history, signal, SYMBOLS[0])['reason'], 'series_mismatch')
        self.assertEqual(history, before)

    def test_single_point_stays_single_and_unknown_keys_are_removed(self):
        signal, source = fixture(); history = source.indicator_history(signal)[SYMBOLS[0]]
        history['untrusted'] = 'drop'
        for item in history['charts']:
            item['points'] = item['points'][-1:]
            item['points'][0]['values']['effective_score'] = 123
        result = project_indicator_history(history, signal, SYMBOLS[0])
        self.assertEqual(result['status'], 'available')
        self.assertEqual(len(result['charts'][0]['points']), 1)
        self.assertNotIn('untrusted', result)
        self.assertNotIn('effective_score', result['charts'][0]['points'][0]['values'])

    def test_snapshot_adds_only_readonly_context_and_chart_failure_does_not_break_account(self):
        signal, source = fixture()
        service = PaperService.__new__(PaperService)
        raw = dict(signal=signal, revision='7', account={'id': 'synthetic'})
        service.ledger = SimpleNamespace(snapshot=Mock(return_value=raw))
        service.source = source; service._lock = threading.RLock(); service._source_state = {}; service._plans = 0
        before = deepcopy(raw)
        snapshot = service.snapshot()
        self.assertEqual(snapshot['indicator_histories'][SYMBOLS[0]]['status'], 'available')
        self.assertEqual(raw, before)
        source.indicator_history = Mock(side_effect=RuntimeError('synthetic optional chart failure'))
        degraded = service.snapshot()
        self.assertEqual(degraded['account'], raw['account'])
        self.assertEqual(degraded['indicator_histories'][SYMBOLS[0]]['reason'], 'invalid_history')
        source.read.assert_not_called()

    def test_real_http_adapter_sanitizes_get_and_ignores_chart_context_for_commands(self):
        from realtime_paper_engine import PaperLedger
        from server import PaperHttpAdapter
        signal, source = fixture()
        day = signal['confirmed_day']
        signal.update(strategy='D0', day=day, market_hash='synthetic-market', reason='Synthetic saved rationale',
            signal_at=day+'T16:10:00+08:00', known_at=day+'T16:10:00+08:00', received_at=day+'T16:10:01+08:00',
            data_cutoff=day+'T15:00:00+08:00', market_at=day+'T15:00:00+08:00', eligible_at='2026-10-26T09:30:00+08:00',
            execution_day='2026-10-26', version='D0-forward-v1', source='Synthetic fixture', valid=True,
            waiting_reason=None, weights={s: '0' for s in SYMBOLS})
        now = datetime(2026, 10, 24, 10, tzinfo=timezone(timedelta(hours=8)))
        with tempfile.TemporaryDirectory(dir=os.environ.get('ETF_TEST_TMPDIR')) as folder:
            ledger = PaperLedger(Path(folder), now=lambda: now)
            try:
                ledger.create('100000.00', name='Synthetic indicator history')
                ledger.set_signal(signal)
                raw = ledger.snapshot(); durable = deepcopy(raw)
                raw['indicator_histories'] = source.indicator_history(signal)
                before = deepcopy(raw)
                adapter = PaperHttpAdapter(SimpleNamespace(now=lambda: now))
                output = adapter.view(raw)
                assets = output['accounts'][0]['signal']['rationale']['assets']
                self.assertTrue(all(a['indicator_history']['status'] == 'available' for a in assets))
                self.assertEqual(raw, before)
                self.assertEqual(adapter.view(raw, command=True), adapter.view(durable, command=True))
                raw['indicator_histories'][SYMBOLS[0]]['signal_key'] = 'another-signal'
                rejected = adapter.view(raw)['accounts'][0]['signal']['rationale']['assets'][0]['indicator_history']
                self.assertEqual(rejected['reason'], 'signal_mismatch')
                self.assertEqual(ledger.snapshot(), durable)
            finally:
                ledger.close()


if __name__ == '__main__':
    unittest.main()
