"""Fixed equity-priority / completed-week Treasury gate used by WW paper accounts.

This module only evaluates a supplied immutable market. It performs no IO and
does not create accounts, fetch quotes or execute trades. The original D0 stock
qualifications and relative scores remain the authoritative stock inputs.
"""
from bisect import bisect_right
from copy import deepcopy
from datetime import date
import math
import statistics
from decimal import Decimal, ROUND_FLOOR

CODE = 'D0I-BOND-WW'
NAME = '双股择时 周线择债'
STOCKS = ('sz159915', 'sh512800')
GOLD, BOND = 'sh518880', 'sh511010'
SYMBOLS = (*STOCKS, GOLD, BOND)


def spec():
    from bank_model import legacy_d0_spec
    return dict(id=CODE, name=NAME, schema='d0i.bond-ww.v1',
        original_stock_spec=legacy_d0_spec(), stock_allocation='eligible_original_d0_scores_normalized',
        gold='excluded', bond_fallback='only_when_both_stocks_ineligible',
        bond=dict(price='point_in_time_total_return', ma_weeks=60, momentum_weeks=20,
                  above_ma=True, positive_momentum=True, completed_weeks_only=True,
                  confirmation='friday_close_or_next_observed_week_first_close',
                  current_quality='score_ready_and_same_day_quote'),
        no_eligible='cash', execution='confirmed_close_then_next_executable_session',
        weekly_trend='frozen_between_confirmed_weeks')


def completed_weeks(rows):
    groups = []
    for row in rows:
        key = date.fromisoformat(row['date']).isocalendar()[:2]
        if not groups or groups[-1][0] != key:
            groups.append((key, []))
        groups[-1][1].append(row)
    result = []
    for index, (_, group) in enumerate(groups):
        if index == 0 and date.fromisoformat(group[0]['date']).weekday() != 0:
            continue
        last = group[-1]
        if date.fromisoformat(last['date']).weekday() == 4:
            available = last['date']
        elif index + 1 < len(groups):
            available = groups[index + 1][1][0]['date']
        else:
            continue
        result.append(dict(week_end=last['date'], available=available,
                           value=last['value'], close=last['close']))
    return result


def weekly_features(rows):
    values, result = [], []
    for week in completed_weeks(rows):
        values.append(week['value'])
        mean = statistics.mean(values[-60:]) if len(values) >= 60 else None
        momentum = values[-1] / values[-21] - 1 if len(values) >= 21 else None
        ready = len(values) >= 60
        result.append(dict(**week, weeks=len(values), sma60weeks=mean,
            momentum20weeks=momentum, weekly_ready=ready,
            weekly_indicator_gate=bool(ready and values[-1] > mean and momentum > 0)))
    return result


def _cache(market):
    cached = getattr(market, '_d0i_ww_weekly_cache', None)
    if cached is None:
        from etf_forecast import total_return_series
        rows = total_return_series({**market.data['chi'], 'attack_symbol': BOND}, market.latest)
        features = weekly_features(rows)
        cached = dict(features=features, availability=[point['available'] for point in features])
        market._d0i_ww_weekly_cache = cached
    return cached


def observation(market, day):
    """Return a fresh WW observation derived from the supplied D0 observation."""
    from bank_model import legacy_d0_observation
    original = legacy_d0_observation(market, day)
    result = deepcopy(original)
    weights = original['weights']
    if (set(weights) != set(SYMBOLS) or any(not math.isfinite(w) or w < 0 for w in weights.values())
            or sum(weights.values()) > 1.000001):
        raise ValueError('invalid original D0 weights')
    cache = _cache(market)
    index = bisect_right(cache['availability'], day) - 1
    feature = cache['features'][index] if index >= 0 else {}
    current = original['dynamic'][BOND]
    quality = bool(current['score_ready'] and current['quote_date'] == day)
    weekly = dict(week_end=feature.get('week_end'), available=feature.get('available'),
        weeks=feature.get('weeks'), value=feature.get('value'), close=feature.get('close'),
        sma60weeks=feature.get('sma60weeks'), momentum20weeks=feature.get('momentum20weeks'),
        weekly_ready=bool(feature.get('weekly_ready')),
        weekly_indicator_gate=bool(feature.get('weekly_indicator_gate')),
        current_score_ready=bool(current['score_ready']), current_quote_date=current['quote_date'],
        current_data_usable=quality,
        indicator_effective=bool(feature.get('weekly_indicator_gate') and quality))
    stock_sum = math.fsum(weights[c] for c in STOCKS)
    target = {c: weights[c] / stock_sum if c in STOCKS and stock_sum > 0 else 0.0 for c in SYMBOLS}
    if all(target[c] > 0 for c in STOCKS):
        # Conserve the full stock budget through JSON/Decimal serialization.
        # Fifteen decimals differ from binary score ratios by <1e-15 and avoid
        # an apparent 100.000000000000006% target at the strict paper boundary.
        first = Decimal(str(target[STOCKS[0]])).quantize(Decimal('0.000000000000001'), rounding=ROUND_FLOOR)
        target[STOCKS[0]], target[STOCKS[1]] = float(first), float(Decimal(1) - first)
    if stock_sum == 0 and weekly['indicator_effective']:
        target[BOND] = 1.0
    result.update(strategy=CODE, weights=target, cash_weight=max(0., 1 - sum(target.values())),
        state='equity_priority_weekly_bond', original_weights=deepcopy(weights), ww_bond=weekly,
        allocation_rule='合格股票按原D0评分归一；双不合格时国债60周均线/20周动量通过才持国债，否则现金；黄金不参与')
    result['longs'][GOLD] = False
    result['longs'][BOND] = weekly['indicator_effective']
    result['dynamic'][GOLD].update(eligible=False, effective_score=0.)
    result['dynamic'][BOND].update(eligible=weekly['indicator_effective'],
        effective_score=result['dynamic'][BOND].get('score', 0.) if weekly['indicator_effective'] else 0.)
    result['features']['dynamic'] = deepcopy(result['dynamic'])
    result['notes'][GOLD] = '本策略排除黄金，目标0%。'
    result['notes'][BOND] = ('国债已完成周60周均线与20周动量资格通过' if weekly['indicator_effective']
                            else '国债周资格未通过或当前数据未就绪，防守预算留现金')
    if stock_sum > 0:
        note = '股票资格通过，按原D0股票相对评分归一分配；国债暂不占用股票预算。'
    elif target[BOND] > 0:
        note = '两股均未通过原D0资格，国债已完成周60周均线和20周动量资格通过，国债目标100%。'
    else:
        note = '两股均未通过原D0资格，国债周资格未通过或数据未就绪，目标现金。'
    result['reason'] = note + ' 黄金不参与；银行日线SKDJ与创业板周线SKDJ/TRIX原资格保持不变。'
    return result
