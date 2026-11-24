"""Pure descriptions of saved D0 indicators, never strategy or trade decisions.

Pair movement describes the interval between two saved observations. It does
not date a crossing within that interval, forecast a crossing, or infer an
entry/exit from line positions. Every current endpoint is reprojected from the
saved signal, and optional history goes through the existing chart boundary.
"""
import math
from datetime import date

from realtime_paper_charts import project_indicator_history
from realtime_paper_rationale import SYMBOLS, project_holding_rationale


CONTRACT_VERSION = 'd0-indicator-commentary-v1'


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _day(value):
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return value if date.fromisoformat(value).isoformat() == value else None
    except ValueError:
        return None


def _identifier(value):
    return value if isinstance(value, str) and 0 < len(value) <= 128 and all(ord(c) >= 32 for c in value) else None


def _position(left, right):
    if left is None or right is None:
        return 'unavailable'
    return 'above' if left > right else 'below' if left < right else 'equal'


def _movement(left, right, previous):
    if previous is None or left is None or right is None:
        return 'unknown'
    before, current = previous['left'] - previous['right'], left - right
    if not math.isfinite(before) or not math.isfinite(current):
        return 'unknown'
    if before <= 0 < current:
        return 'cross_up'
    if before >= 0 > current:
        return 'cross_down'
    if current == before:
        return 'unchanged'
    if current < 0:
        return 'converging_up' if current > before else 'widening_below'
    if current > 0:
        return 'converging_down' if current < before else 'widening_above'
    # Equality is a position, not a completed strict crossing or an unchanged
    # gap. The UI can state that the lines meet without predicting direction.
    return 'unknown'


def _previous(history, key, frequency, period_end, available_on, left, right):
    if history.get('status') != 'available' or left is None or right is None:
        return None
    chart = next((item for item in history['charts'] if item['id'] == key), None)
    if not chart or len(chart['points']) < 2:
        return None
    previous, current = chart['points'][-2:]
    if current['break_before']:
        return None
    names = ('k', 'd') if key == 'skdj' else ('trix', 'signal')
    before_left, before_right = (previous['values'][name] for name in names)
    if before_left is None or before_right is None:
        return None
    current_period = current.get('period_end', current['date'])
    before_period = previous.get('period_end', previous['date'])
    if (current['date'] != available_on or current_period != period_end
            or before_period >= current_period or previous['date'] >= current['date']
            or any(current['values'][name] is None or not math.isclose(current['values'][name], value,
                       rel_tol=1e-12, abs_tol=1e-12) for name, value in zip(names, (left, right)))):
        return None
    return dict(period_end=before_period, available_on=previous['date'],
                left=before_left, right=before_right)


def project_indicator_commentary(signal, asset):
    """Return bounded factual states using only the caller's saved snapshot.

    Only the asset's symbol and optional historical contract are consumed.
    Its metrics, state and targets cannot override the original saved signal.
    Missing provenance suppresses that group's conclusions independently.
    """
    signal, asset = _mapping(signal), _mapping(asset)
    symbol = asset.get('symbol') if isinstance(asset.get('symbol'), str) and asset['symbol'] in SYMBOLS else None
    signal_key, confirmed = _identifier(signal.get('id')), _day(signal.get('confirmed_day'))
    result = dict(contract_version=CONTRACT_VERSION, source='saved_signal', signal_key=signal_key,
                  confirmed_day=confirmed, symbol=symbol, pairs=[], trend=None,
                  momentum=dict.fromkeys(('momentum20', 'momentum60', 'volatility20', 'effective_score', 'score_ready')),
                  state=dict.fromkeys(('ready', 'long', 'eligible', 'target_weight', 'entry', 'exit', 'holding_days',
                                       'next_risk', 'close_market', 'blocked')))
    if symbol is None or signal_key is None or confirmed is None:
        return result
    saved = next(row for row in project_holding_rationale(signal)['assets'] if row['symbol'] == symbol)
    gate = saved['original_gate']; timing, metrics, state = gate['timing'], gate['metrics'], gate['state']
    if symbol == SYMBOLS[1]:
        result['bank_rule'] = gate['bank_rule']
    history = project_indicator_history(asset.get('indicator_history'), signal, symbol)

    def group_dates(group):
        if timing[group + '_status'] != 'confirmed':
            return None, None
        if group == 'market':
            return timing['market_period_end'], timing['market_available_on']
        if symbol == SYMBOLS[1]:
            return timing['state_day'], timing['state_day']
        return timing['period_end'], timing['available_on'] if symbol == SYMBOLS[0] else timing['period_end']

    if symbol in SYMBOLS[:2]:
        frequency = 'weekly' if symbol == SYMBOLS[0] else 'daily'
        period_end, available_on = group_dates('indicator')
        for key, names in [('skdj', ('k', 'd'))] + ([('trix', ('trix_pct', 'signal_pct'))] if symbol == SYMBOLS[0] else []):
            left, right = (metrics.get(name) for name in names)
            previous = _previous(history, key, frequency, period_end, available_on, left, right)
            result['pairs'].append(dict(id=key, frequency=frequency, period_end=period_end,
                available_on=available_on, left=left, right=right, position=_position(left, right),
                movement=_movement(left, right, previous), previous=previous))
    if gate['kind'] == 'excluded':
        result['state'].update(eligible=False, long=False, target_weight=saved['target_weight'])
        result['allocation_mode'] = 'excluded'
        return result
    if symbol != SYMBOLS[1]:
        weekly_bond = gate['kind'] == 'bond_weekly'
        weekly = symbol == SYMBOLS[0] or weekly_bond
        window = 50 if weekly else 120 if symbol == SYMBOLS[2] else 60
        if weekly_bond:
            window = 60
        period_end, available_on = group_dates('market' if symbol == SYMBOLS[0] else 'indicator')
        if weekly_bond:
            available_on = timing['available_on'] if timing['indicator_status'] == 'confirmed' else None
        valid_window = symbol == SYMBOLS[0] or metrics.get('ma_window') == window
        value, ma = (metrics.get(key) for key in (('market_close', 'market_ma') if symbol == SYMBOLS[0] else ('value', 'ma')))
        if not valid_window:
            value = ma = None
        # Positive values are needed to interpret a price/index relative to a
        # moving average. Zero or negative prices are not a usable trend pair.
        value = value if value is not None and value > 0 else None
        ma = ma if ma is not None and ma > 0 else None
        result['trend'] = dict(frequency='weekly' if weekly else 'daily', period_end=period_end,
            available_on=available_on, window=window if valid_window and period_end else None,
            value=value, ma=ma, position=_position(value, ma),
            momentum20=None if symbol == SYMBOLS[0] else metrics.get('momentum20'))
        if weekly_bond:
            result['trend']['momentum_unit'] = 'weeks'
            result['allocation_mode'] = 'weekly_bond_fallback'
    dynamic = _mapping(signal['dynamic'] if 'dynamic' in signal else _mapping(signal.get('features')).get('dynamic'))
    detail = _mapping(dynamic.get(symbol))
    dynamic_dated = _day(detail.get('quote_date')) == confirmed
    if dynamic_dated:
        result['momentum'] = {key: saved[key] for key in result['momentum']}
        result['state']['eligible'] = saved['eligible']
    if gate['kind'] == 'bond_weekly' and timing['status'] == 'confirmed':
        result['state']['eligible'] = saved['eligible']
    for key in ('ready', 'long', 'entry', 'exit', 'holding_days', 'next_risk', 'close_market', 'blocked'):
        result['state'][key] = state.get(key)
    result['state']['target_weight'] = saved['target_weight']
    return result
