"""Pure indicator descriptions on synthetic saved signals and chart contracts."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'production'))
from realtime_paper_commentary import project_indicator_commentary
from realtime_paper_rationale import SYMBOLS, project_holding_rationale


def fixture(symbol=SYMBOLS[0]):
    day = '2026-10-23'
    signal = dict(id='synthetic-saved-signal', confirmed_day=day,
        weekly_date=day, weekly_confirmed=day, chi_quote_date=day,
        ready={SYMBOLS[0]: True}, chi_long=False, bank_long=True,
        chi_state=dict(date=day, close_market='bear', next_risk=0, holding_days=0, blocked=False),
        bank_state=dict(date=day, next_risk=1, holding_days=4),
        weights=dict(zip(SYMBOLS, (0, .4, .6, 0))),
        features=dict(chi_weekly=dict(week_end=day, available=day, k=42, d=40, trix=-.125, signal=-.25),
            chi_market=dict(week_end=day, available=day, close=2.7, ma=3.2),
            bank=dict(k=42, d=40, ready=True, entry=False, exit=False),
            gold=dict(quote_date=day, value=102, ma=101, ma_window=120, momentum20=.03, ready=True, long=True),
            bond=dict(quote_date=day, value=100, ma=101, ma_window=60, momentum20=-.02, ready=True, long=False)),
        dynamic={s: dict(quote_date=day, momentum20=.03, momentum60=.06, volatility20=.12,
            effective_score=.8, score_ready=True, eligible=s in SYMBOLS[1:3]) for s in SYMBOLS})
    asset = asset_for(signal, symbol)
    return signal, asset


def asset_for(signal, symbol):
    asset = next(row for row in project_holding_rationale(signal)['assets'] if row['symbol'] == symbol)
    gate = asset['original_gate']; metrics = gate['metrics']; day = signal['confirmed_day']
    charts = []

    def add(key, frequency, unit, basis, current, previous):
        earlier = '2026-10-16' if frequency == 'weekly' else '2026-10-22'
        points = [dict(date=earlier, available_on=earlier, values=previous, break_before=False),
                  dict(date=day, available_on=day, values=current, break_before=False)]
        if frequency == 'weekly':
            for point in points:
                point['period_end'] = point['date']
        charts.append(dict(id=key, frequency=frequency, unit=unit, basis=basis, points=points))

    if symbol in SYMBOLS[:2]:
        weekly = symbol == SYMBOLS[0]
        add('skdj', 'weekly' if weekly else 'daily', 'indicator',
            'confirmed_weekly_indicator' if weekly else 'daily_indicator',
            dict(k=metrics['k'], d=metrics['d']), dict(k=35, d=38))
        if weekly:
            add('trix', 'weekly', 'percent_points', 'confirmed_weekly_indicator',
                dict(trix=metrics['trix_pct'], signal=metrics['signal_pct']), dict(trix=-.3, signal=-.2))
            add('trend', 'weekly', 'price', 'weekly_adjusted_close_ma50',
                dict(value=metrics['market_close'], ma=metrics['market_ma']), dict(value=2.5, ma=3.1))
    else:
        window = 120 if symbol == SYMBOLS[2] else 60
        add('trend', 'daily', 'index_points', 'total_return_ma'+str(window),
            dict(value=metrics['value'], ma=metrics['ma']), dict(value=100, ma=101))
    add('momentum', 'daily', 'ratio', 'dynamic_total_return',
        dict(m20=asset['momentum20'], m60=asset['momentum60']), dict(m20=.01, m60=.02))
    add('volatility', 'daily', 'ratio', 'dynamic_total_return', dict(vol=asset['volatility20']), dict(vol=.15))
    asset['indicator_history'] = dict(contract_version='d0-indicator-history-v1', source='confirmed_input_history',
        signal_key=signal['id'], confirmed_day=day, status='available', reason=None, charts=charts)
    return asset


def pair_chart(asset, key='skdj'):
    return next(row for row in asset['indicator_history']['charts'] if row['id'] == key)


def pair(result, key='skdj'):
    return next(row for row in result['pairs'] if row['id'] == key)


def with_pair(left, right, previous_left, previous_right, *, symbol=SYMBOLS[0], key='skdj'):
    signal, _ = fixture(symbol)
    group = signal['features']['chi_weekly' if symbol == SYMBOLS[0] else 'bank']
    keys = ('k', 'd') if key == 'skdj' else ('trix', 'signal')
    group.update(zip(keys, (left, right)))
    asset = asset_for(signal, symbol)
    pair_chart(asset, key)['points'][0]['values'] = dict(zip(keys, (previous_left, previous_right)))
    return signal, asset


class IndicatorCommentaryTests(unittest.TestCase):
    def test_all_four_asset_contracts_use_saved_current_values_and_states(self):
        for index, symbol in enumerate(SYMBOLS):
            with self.subTest(symbol=symbol):
                signal, asset = fixture(symbol)
                result = project_indicator_commentary(signal, asset)
                self.assertEqual(result['contract_version'], 'd0-indicator-commentary-v1')
                self.assertEqual(result['source'], 'saved_signal')
                self.assertEqual(result['signal_key'], signal['id'])
                self.assertEqual(result['confirmed_day'], signal['confirmed_day'])
                self.assertEqual(result['symbol'], symbol)
                self.assertEqual(len(result['pairs']), (2, 1, 0, 0)[index])
                self.assertEqual(result['trend']['window'] if result['trend'] else None, (50, None, 120, 60)[index])
                self.assertEqual(result['state']['target_weight'], (0, .4, .6, 0)[index])
                self.assertEqual(result['momentum']['momentum20'], .03)
                self.assertIs(result['momentum']['score_ready'], True)
                self.assertIs(result['state']['eligible'], symbol in SYMBOLS[1:3])
        signal, asset = fixture(SYMBOLS[1])
        result = project_indicator_commentary(signal, asset)
        self.assertIs(result['state']['entry'], False)
        self.assertIs(result['state']['long'], True)
        self.assertEqual(result['state']['holding_days'], 4)

    def test_current_above_and_crossing_are_distinct(self):
        for values, expected in [((42, 40, 35, 38), 'cross_up'), ((35, 38, 42, 40), 'cross_down'),
                                 ((42, 40, 43, 40), 'converging_down'), ((42, 40, 41, 40), 'widening_above')]:
            with self.subTest(values=values):
                signal, asset = with_pair(*values)
                result = pair(project_indicator_commentary(signal, asset))
                self.assertEqual(result['movement'], expected)
                self.assertEqual(result['previous']['available_on'], '2026-10-16')

    def test_daily_crosses_use_daily_dates(self):
        for values, expected in [((42, 40, 35, 38), 'cross_up'), ((35, 38, 42, 40), 'cross_down')]:
            signal, asset = with_pair(*values, symbol=SYMBOLS[1])
            result = pair(project_indicator_commentary(signal, asset))
            self.assertEqual(result['movement'], expected)
            self.assertEqual(result['frequency'], 'daily')
            self.assertEqual(result['previous']['period_end'], '2026-10-22')

    def test_below_convergence_and_widening_need_no_arbitrary_threshold(self):
        for values, expected in [((39, 40, 35, 38), 'converging_up'), ((35, 40, 38, 40), 'widening_below'),
                                 ((37, 40, 35, 38), 'unchanged')]:
            signal, asset = with_pair(*values)
            result = pair(project_indicator_commentary(signal, asset))
            self.assertEqual(result['position'], 'below')
            self.assertEqual(result['movement'], expected)

    def test_equality_is_not_a_strict_cross_or_falsely_unchanged(self):
        for before, expected in [((35, 38), 'unknown'), ((42, 42), 'unchanged')]:
            signal, asset = with_pair(40, 40, *before)
            result = pair(project_indicator_commentary(signal, asset))
            self.assertEqual(result['position'], 'equal')
            self.assertEqual(result['movement'], expected)
        signal, asset = with_pair(41, 40, 40, 40)
        self.assertEqual(pair(project_indicator_commentary(signal, asset))['movement'], 'cross_up')

    def test_trix_keeps_signed_percentage_point_units(self):
        for values, expected in [((-.125, -.25, -.3, -.2), 'cross_up'), ((-.3, -.2, .1, .05), 'cross_down'),
                                 ((.1, .05, -.1, -.05), 'cross_up')]:
            signal, asset = with_pair(*values, key='trix')
            result = pair(project_indicator_commentary(signal, asset), 'trix')
            self.assertEqual(result['left'], values[0])
            self.assertEqual(result['right'], values[1])
            self.assertEqual(result['movement'], expected)

    def test_forged_asset_metrics_state_and_weight_are_ignored(self):
        signal, asset = fixture(SYMBOLS[1])
        asset.update(original_gate={'metrics': {'k': 99, 'd': 0}, 'state': {'entry': True}},
                     target_weight=1, eligible=True, momentum20=99, effective_score=99)
        result = project_indicator_commentary(signal, asset)
        self.assertEqual(pair(result)['left'], 42)
        self.assertIs(result['state']['entry'], False)
        self.assertEqual(result['state']['target_weight'], .4)
        self.assertEqual(result['momentum']['effective_score'], .8)

    def test_missing_history_only_suppresses_interval_movement(self):
        signal, asset = fixture(); asset.pop('indicator_history')
        result = pair(project_indicator_commentary(signal, asset))
        self.assertEqual(result['position'], 'above')
        self.assertEqual(result['movement'], 'unknown')
        self.assertIsNone(result['previous'])

    def test_one_point_history_cannot_establish_crossing(self):
        signal, asset = fixture(); pair_chart(asset)['points'].pop(0)
        self.assertEqual(pair(project_indicator_commentary(signal, asset))['movement'], 'unknown')

    def test_missing_previous_values_do_not_skip_to_an_older_point(self):
        signal, asset = fixture(); points = pair_chart(asset)['points']
        older = deepcopy(points[0]); older.update(date='2026-10-09', available_on='2026-10-09', period_end='2026-10-09')
        points.insert(0, older); points[1]['values']['k'] = None
        result = pair(project_indicator_commentary(signal, asset))
        self.assertEqual(result['movement'], 'unknown')
        self.assertIsNone(result['previous'])

    def test_current_missing_value_is_unavailable_without_using_older_values(self):
        signal, asset = fixture(); signal['features']['chi_weekly']['k'] = None
        asset = asset_for(signal, SYMBOLS[0])
        result = pair(project_indicator_commentary(signal, asset))
        self.assertIsNone(result['left'])
        self.assertEqual(result['position'], 'unavailable')
        self.assertEqual(result['movement'], 'unknown')

    def test_daily_and_explicit_weekly_gaps_disable_interval_events(self):
        for symbol in SYMBOLS[:2]:
            signal, asset = fixture(symbol); pair_chart(asset)['points'][-1]['break_before'] = True
            result = pair(project_indicator_commentary(signal, asset))
            self.assertEqual(result['position'], 'above')
            self.assertEqual(result['movement'], 'unknown')

    def test_missing_week_is_an_interval_description_without_claiming_adjacency(self):
        signal, asset = fixture(); point = pair_chart(asset)['points'][0]
        point.update(date='2026-10-02', available_on='2026-10-02', period_end='2026-10-02')
        result = pair(project_indicator_commentary(signal, asset))
        self.assertEqual(result['movement'], 'cross_up')
        self.assertEqual(result['previous']['period_end'], '2026-10-02')
        self.assertEqual(result['period_end'], '2026-10-23')
        self.assertNotIn('adjacent', result)

    def test_invalid_history_identity_dates_units_and_endpoint_cannot_create_events(self):
        mutations = [lambda h: h.update(signal_key='other'), lambda h: h.update(confirmed_day='2026-10-24'),
            lambda h: h['charts'][0].update(unit='ratio'),
            lambda h: h['charts'][0]['points'][-1]['values'].update(k=99),
            lambda h: h['charts'][0]['points'][-1].update(date='2026-10-30', available_on='2026-10-30'),
            lambda h: h['charts'][0]['points'][0].update(period_end='2026-10-24'),
            lambda h: h['charts'].append(deepcopy(h['charts'][0]))]
        for mutate in mutations:
            signal, asset = fixture(); mutate(asset['indicator_history'])
            result = pair(project_indicator_commentary(signal, asset))
            self.assertEqual(result['position'], 'above')
            self.assertEqual(result['movement'], 'unknown')

    def test_future_or_missing_current_weekly_dates_suppress_only_that_group(self):
        for change in ({'available': '2026-10-30'}, {'week_end': None}, {'week_end': '2026-02-30'}):
            signal, asset = fixture(); signal['features']['chi_weekly'].update(change)
            result = project_indicator_commentary(signal, asset)
            self.assertTrue(all(row['position'] == 'unavailable' for row in result['pairs']))
            self.assertEqual(result['trend']['position'], 'below')
            self.assertIs(result['state']['ready'], True)

    def test_invalid_market_dates_leave_pair_and_state_facts_independent(self):
        signal, asset = fixture(); signal['features']['chi_market']['available'] = '2026-10-30'
        result = project_indicator_commentary(signal, asset)
        self.assertEqual(result['trend']['position'], 'unavailable')
        self.assertEqual(pair(result)['position'], 'above')
        self.assertIs(result['state']['long'], False)

    def test_invalid_state_date_does_not_borrow_indicator_or_signal_date(self):
        signal, asset = fixture(); signal['chi_state']['date'] = None
        result = project_indicator_commentary(signal, asset)
        self.assertIsNone(result['state']['long'])
        self.assertIsNone(result['state']['holding_days'])
        self.assertEqual(pair(result)['position'], 'above')
        signal, asset = fixture(SYMBOLS[1]); signal['bank_state']['date'] = None
        result = project_indicator_commentary(signal, asset)
        self.assertEqual(pair(result)['position'], 'unavailable')
        self.assertIsNone(result['state']['entry'])

    def test_defense_missing_wrong_or_invalid_window_has_no_trend_conclusion(self):
        for symbol, group in ((SYMBOLS[2], 'gold'), (SYMBOLS[3], 'bond')):
            for window in (None, 50, True, 'NaN'):
                signal, asset = fixture(symbol); signal['features'][group]['ma_window'] = window
                result = project_indicator_commentary(signal, asset)
                self.assertEqual(result['trend']['position'], 'unavailable')
                self.assertIsNone(result['trend']['window'])
                self.assertIsNone(result['trend']['value'])

    def test_defense_dates_do_not_borrow_dynamic_dates(self):
        signal, asset = fixture(SYMBOLS[2]); signal['features']['gold']['quote_date'] = '2026-10-22'
        result = project_indicator_commentary(signal, asset)
        self.assertEqual(result['trend']['position'], 'unavailable')
        self.assertIsNone(result['state']['long'])
        self.assertEqual(result['momentum']['momentum20'], .03)

    def test_defense_screening_momentum_remains_distinct_from_dynamic_momentum(self):
        for symbol, group in ((SYMBOLS[2], 'gold'), (SYMBOLS[3], 'bond')):
            signal, asset = fixture(symbol)
            signal['features'][group]['momentum20'] = -.012
            signal['dynamic'][symbol]['momentum20'] = .03
            result = project_indicator_commentary(signal, asset)
            self.assertEqual(result['trend']['momentum20'], -.012)
            self.assertEqual(result['momentum']['momentum20'], .03)
            signal['features'][group].pop('momentum20')
            result = project_indicator_commentary(signal, asset)
            self.assertIsNone(result['trend']['momentum20'])
            self.assertEqual(result['momentum']['momentum20'], .03)

    def test_dynamic_dates_are_required_for_momentum_and_eligibility(self):
        for value in (None, '2026-10-22', '2026-10-30', '2026-02-30'):
            signal, asset = fixture(); signal['dynamic'][SYMBOLS[0]]['quote_date'] = value
            result = project_indicator_commentary(signal, asset)
            self.assertTrue(all(value is None for value in result['momentum'].values()))
            self.assertIsNone(result['state']['eligible'])
            self.assertEqual(result['state']['target_weight'], 0)
            self.assertEqual(pair(result)['position'], 'above')

    def test_reference_risk_protection_and_market_state_need_their_own_valid_date(self):
        signal, asset = fixture()
        signal['chi_state'].update(next_risk=.5, blocked=True, close_market='bull')
        result = project_indicator_commentary(signal, asset)
        self.assertEqual(result['state']['next_risk'], .5)
        self.assertIs(result['state']['blocked'], True)
        self.assertEqual(result['state']['close_market'], 'bull')
        signal['chi_state']['date'] = '2026-10-22'
        result = project_indicator_commentary(signal, asset)
        for key in ('next_risk', 'blocked', 'close_market'):
            self.assertIsNone(result['state'][key])

    def test_bank_existing_long_does_not_need_a_new_low_entry_signal(self):
        signal, asset = fixture(SYMBOLS[1])
        result = project_indicator_commentary(signal, asset)
        self.assertGreater(pair(result)['left'], 40)
        self.assertIs(result['state']['entry'], False)
        self.assertIs(result['state']['long'], True)
        self.assertIs(result['state']['eligible'], True)

    def test_chinext_below_lines_do_not_override_saved_continuing_full_position(self):
        signal, _ = fixture()
        signal['features']['chi_weekly'].update(k=30, d=40, trix=-.3, signal=-.2)
        signal.update(chi_long=True)
        signal['chi_state'].update(next_risk=1., close_market='bull', blocked=False)
        signal['dynamic'][SYMBOLS[0]]['eligible'] = True
        result = project_indicator_commentary(signal, asset_for(signal, SYMBOLS[0]))
        self.assertTrue(all(p['position'] == 'below' for p in result['pairs']))
        self.assertEqual(result['state']['next_risk'], 1.)
        self.assertIs(result['state']['blocked'], False)
        self.assertIs(result['state']['long'], True)
        self.assertIs(result['state']['eligible'], True)

    def test_nonfinite_booleans_and_malformed_values_are_null_and_json_safe(self):
        for value in (float('nan'), float('inf'), float('-inf'), True, 'NaN', 'Infinity'):
            signal, asset = fixture(); signal['features']['chi_weekly']['k'] = value
            signal['dynamic'][SYMBOLS[0]].update(momentum20=value, volatility20=value, effective_score=value)
            result = project_indicator_commentary(signal, asset)
            self.assertIsNone(pair(result)['left'])
            self.assertIsNone(result['momentum']['momentum20'])
            self.assertIsNone(result['momentum']['volatility20'])
            self.assertIsNone(result['momentum']['effective_score'])
            json.dumps(result, allow_nan=False)

    def test_zero_or_negative_trend_values_do_not_produce_trend_positions(self):
        for value in (0, -1):
            signal, asset = fixture(SYMBOLS[2]); signal['features']['gold']['value'] = value
            result = project_indicator_commentary(signal, asset)
            self.assertEqual(result['trend']['position'], 'unavailable')

    def test_missing_identity_unsupported_symbol_and_malformed_inputs_are_safe(self):
        for signal, asset in ((None, None), ({}, {}), ([], []),
                              ({'id': 'x', 'confirmed_day': 'bad'}, {'symbol': SYMBOLS[0]}),
                              ({'id': 'x', 'confirmed_day': '2026-10-23'}, {'symbol': 'other'})):
            result = project_indicator_commentary(signal, asset)
            self.assertEqual(result['pairs'], [])
            self.assertIsNone(result['trend'])
            self.assertTrue(all(value is None for value in result['momentum'].values()))
            json.dumps(result, allow_nan=False)

    def test_projection_is_pure_without_io_or_strategy_evaluation(self):
        signal, asset = fixture(); original = deepcopy((signal, asset))
        with patch('builtins.open', side_effect=AssertionError('no IO')):
            result = project_indicator_commentary(signal, asset)
        self.assertEqual((signal, asset), original)
        result['pairs'][0]['left'] = 99
        result['pairs'][0]['previous']['left'] = 99
        self.assertEqual((signal, asset), original)


if __name__ == '__main__':
    unittest.main()
