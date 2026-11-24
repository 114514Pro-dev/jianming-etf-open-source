"""Read-only explanation of the D0 signal already saved in the paper ledger.

No price lookup, strategy calculation, eligibility inference or ledger writes
belong here. Unknown legacy fields remain unavailable rather than being rebuilt
from today's market or from the account's current holdings.
"""
import math
from datetime import date
from decimal import Decimal, InvalidOperation


SYMBOLS = ('sz159915', 'sh512800', 'sh518880', 'sh511010')
CONTRACT_VERSION = 'd0-holding-logic-v1'
ORIGINAL_CONTRACT_VERSION = 'd0-original-gate-v1'
WEEKLY_BOND_STRATEGY = 'D0I-BOND-WW'
WEEKLY_BOND_CONTRACT_VERSION = 'd0i-bond-weekly-v1'
BANK_RULE_CONTRACT_VERSION = 'd0-bank-entry-rule-v1'
BANK_RULE_SIGNAL_VERSION = 'D0-forward-bank-ma50-v1'
BANK_GATE_SCHEMA = 'd0.bank-ma50-k50.v1'


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _text(value):
    # Plain JSON text, never HTML. The client renders it with textContent.
    if (not isinstance(value, str) or not value.strip() or len(value) > 4096
            or any(ord(char) < 32 and char not in '\t\r\n' for char in value)):
        return None
    return value


def _number(value, *, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    if isinstance(value, str) and (not value or len(value) > 64):
        return None
    try:
        decimal = Decimal(str(value))
        if (not decimal.is_finite() or (minimum is not None and decimal < minimum)
                or (maximum is not None and decimal > maximum)):
            return None
        number = float(decimal)
        return number if math.isfinite(number) else None
    except (InvalidOperation, ValueError, OverflowError):
        return None


def _boolean(value):
    return value if isinstance(value, bool) else None


def _integer(value, *, minimum=0):
    number = _number(value, minimum=minimum, maximum=1000000)
    return int(number) if number is not None and number.is_integer() else None


def _date(value):
    if value is None:
        return None, 'unknown'
    if not isinstance(value, str) or len(value) != 10:
        return None, 'invalid'
    try:
        parsed = date.fromisoformat(value)
        return (value, 'confirmed') if parsed.isoformat() == value else (None, 'invalid')
    except ValueError:
        return None, 'invalid'


def _time_status(values, confirmed, *, weekly=False):
    """Validate saved dates, without manufacturing a date from today's clock."""
    parsed = [_date(value) for value in values]
    day, day_status = _date(confirmed)
    if day_status == 'invalid' or any(status == 'invalid' for _, status in parsed):
        return 'invalid'
    if day and any(value and value > day for value, _ in parsed):
        return 'invalid'
    if weekly and all(value for value, _ in parsed) and parsed[0][0] > parsed[1][0]:
        return 'invalid'
    if day_status != 'confirmed' or any(status != 'confirmed' for _, status in parsed):
        return 'unknown'
    if not weekly and parsed[0][0] != day:
        return 'invalid'
    return 'confirmed'


def _gated(values, status):
    return values if status == 'confirmed' else dict.fromkeys(values)


def _bank_entry_rule(original, state_status):
    """Describe this saved signal's rule version without upgrading old history."""
    legacy = (original.get('strategy') == WEEKLY_BOND_STRATEGY or
              original.get('version') != BANK_RULE_SIGNAL_VERSION)
    result = dict(contract_version=BANK_RULE_CONTRACT_VERSION,
                  source='saved_signal', mode='legacy' if legacy else 'conditional',
                  status='legacy' if legacy else 'unknown',
                  entry_k_limit=40 if legacy else None, active=False if legacy else None,
                  day=_date(original.get('confirmed_day'))[0], weekly_status='unknown',
                  weekly_close=None, ma=None, week_end=None, available=None)
    if legacy:
        return result
    saved = _mapping(original.get('bank_gate'))
    if not saved:
        return result
    confirmed = original.get('confirmed_day')
    daily_status = _time_status([saved.get('day')], confirmed)
    weekly_status = _time_status([saved.get('week_end'), saved.get('available')], confirmed, weekly=True)
    active, relaxed = _boolean(saved.get('active')), _boolean(saved.get('relaxed'))
    limit = _number(saved.get('entry_k_limit'))
    close, ma = _number(saved.get('weekly_close'), minimum=0), _number(saved.get('ma'), minimum=0)
    reasons = saved.get('gate_reasons')
    valid = (saved.get('schema') == BANK_GATE_SCHEMA and daily_status == 'confirmed'
             and state_status == 'confirmed' and active is not None and active == relaxed
             and limit == (50 if active else 40) and isinstance(reasons, list)
             and all(_text(reason) is not None for reason in reasons))
    # Active evidence must contain the actual confirmed weekly trigger. An
    # inactive snapshot may legitimately have no weekly values during warmup.
    if active:
        valid = (valid and not reasons and weekly_status == 'confirmed'
                 and close is not None and ma is not None and 0 < close < ma)
    if not valid:
        result['status'] = 'invalid'
        return result
    result.update(status='confirmed', entry_k_limit=int(limit), active=active)
    weekly_usable = weekly_status == 'confirmed' and close is not None and ma is not None and close > 0 and ma > 0
    result['weekly_status'] = weekly_status if weekly_usable or weekly_status != 'confirmed' else 'unknown'
    if weekly_usable:
        result.update(weekly_close=close, ma=ma, week_end=_date(saved.get('week_end'))[0],
                      available=_date(saved.get('available'))[0])
    return result


def _original_gate(original, symbol):
    """Expose original-strategy facts already stored alongside this D0 signal.

    Dates gate each independent group. A current quote, today's configuration,
    or another group's date must never backfill missing historical evidence.
    TRIX values are already percentage points in the saved strategy features.
    """
    features = _mapping(original.get('features'))
    confirmed = original.get('confirmed_day')
    timing = dict(status='unknown', indicator_status='unknown', market_status=None,
                  state_status='unknown', confirmed_day=_date(confirmed)[0],
                  period_end=None, available_on=None, market_period_end=None,
                  market_available_on=None, state_day=None)
    if symbol == 'sz159915':
        kind = 'chi_weekly'
        indicator, market, saved = (_mapping(features.get('chi_weekly')),
                                    _mapping(features.get('chi_market')),
                                    _mapping(original.get('chi_state')))
        timing.update(indicator_status=_time_status([indicator.get('week_end'), indicator.get('available')], confirmed, weekly=True),
                      market_status=_time_status([market.get('week_end'), market.get('available')], confirmed, weekly=True),
                      state_status=_time_status([saved.get('date')], confirmed),
                      period_end=_date(indicator.get('week_end'))[0], available_on=_date(indicator.get('available'))[0],
                      market_period_end=_date(market.get('week_end'))[0], market_available_on=_date(market.get('available'))[0],
                      state_day=_date(saved.get('date'))[0])
        for field, value, group in [('weekly_date', indicator.get('week_end'), 'indicator_status'),
                                    ('weekly_confirmed', indicator.get('available'), 'indicator_status'),
                                    ('chi_quote_date', saved.get('date'), 'state_status')]:
            if field in original and original[field] != value:
                timing[group] = 'invalid'
        metrics = _gated(dict(k=_number(indicator.get('k'), minimum=0, maximum=100),
                             d=_number(indicator.get('d'), minimum=0, maximum=100),
                             trix_pct=_number(indicator.get('trix')), signal_pct=_number(indicator.get('signal')),
                             weekly_close=_number(indicator.get('close'), minimum=0),
                             weekly_ma=_number(indicator.get('ma'), minimum=0)), timing['indicator_status'])
        metrics.update(_gated(dict(market_close=_number(market.get('close'), minimum=0),
                                   market_ma=_number(market.get('ma'), minimum=0)), timing['market_status']))
        state = _gated(dict(ready=_boolean(_mapping(original.get('ready')).get(symbol)),
                            long=_boolean(original.get('chi_long')),
                            close_market=saved.get('close_market') if saved.get('close_market') in ('bull', 'bear', 'warmup') else None,
                            next_risk=_number(saved.get('next_risk'), minimum=0, maximum=1),
                            holding_days=_integer(saved.get('holding_days')), blocked=_boolean(saved.get('blocked')),
                            reason=_text(saved.get('reason'))), timing['state_status'])
    elif symbol == 'sh512800':
        kind = 'bank_daily'
        indicator, saved = _mapping(features.get('bank')), _mapping(original.get('bank_state'))
        # Bank features carry no independent date. The same signal's saved
        # bank state supplies the only supported daily provenance.
        status = _time_status([saved.get('date')], confirmed)
        timing.update(indicator_status=status, state_status=status, state_day=_date(saved.get('date'))[0])
        metrics = _gated(dict(k=_number(indicator.get('k'), minimum=0, maximum=100),
                             d=_number(indicator.get('d'), minimum=0, maximum=100),
                             trix_pct=_number(indicator.get('trix')), signal_pct=_number(indicator.get('signal')),
                             ma=_number(indicator.get('ma'), minimum=0),
                             volume_ratio=_number(indicator.get('volume_ratio'), minimum=0)), status)
        state = _gated(dict(ready=_boolean(indicator.get('ready')), long=_boolean(original.get('bank_long')),
                            entry=_boolean(indicator.get('entry')), exit=_boolean(indicator.get('exit')),
                            positive=_boolean(indicator.get('positive')),
                            next_risk=_number(saved.get('next_risk'), minimum=0, maximum=1),
                            holding_days=_integer(saved.get('holding_days')), reason=_text(saved.get('reason'))), status)
    else:
        kind = 'defense_daily'
        indicator = _mapping(features.get('gold' if symbol == 'sh518880' else 'bond'))
        status = _time_status([indicator.get('quote_date')], confirmed)
        timing.update(indicator_status=status, state_status=status, period_end=_date(indicator.get('quote_date'))[0])
        metrics = _gated(dict(value=_number(indicator.get('value'), minimum=0), ma=_number(indicator.get('ma'), minimum=0),
                             ma_window=_integer(indicator.get('ma_window'), minimum=1),
                             momentum20=_number(indicator.get('momentum20'))), status)
        state = _gated(dict(ready=_boolean(indicator.get('ready')), long=_boolean(indicator.get('long'))), status)
    statuses = [timing[key] for key in ('indicator_status', 'market_status', 'state_status') if timing[key] is not None]
    timing['status'] = 'invalid' if 'invalid' in statuses else 'unknown' if 'unknown' in statuses else 'confirmed'
    result = dict(contract_version=ORIGINAL_CONTRACT_VERSION, source='saved_signal', kind=kind,
                  metrics=metrics, state=state, timing=timing)
    if symbol == 'sh512800':
        result['bank_rule'] = _bank_entry_rule(original, timing['state_status'])
    return result


def _weekly_bond_gate(original):
    """Project the saved weekly fallback, never recalculate it from daily data."""
    saved = _mapping(original.get('ww_bond'))
    confirmed = original.get('confirmed_day')
    indicator_status = _time_status([saved.get('week_end'), saved.get('available')], confirmed, weekly=True)
    state_status = _time_status([saved.get('current_quote_date')], confirmed)
    statuses = (indicator_status, state_status)
    status = 'invalid' if 'invalid' in statuses else 'unknown' if 'unknown' in statuses else 'confirmed'
    timing = dict(status=status, indicator_status=indicator_status, market_status=None,
                  state_status=state_status, confirmed_day=_date(confirmed)[0],
                  period_end=_date(saved.get('week_end'))[0], available_on=_date(saved.get('available'))[0],
                  market_period_end=None, market_available_on=None,
                  state_day=_date(saved.get('current_quote_date'))[0])
    metrics = _gated(dict(value=_number(saved.get('value'), minimum=0),
        ma=_number(saved.get('sma60weeks'), minimum=0),
        momentum20=_number(saved.get('momentum20weeks')),
        ma_window=60, weeks=_integer(saved.get('weeks'), minimum=0)), indicator_status)
    metrics.update(ma_unit='weeks', momentum_unit='weeks')
    state = _gated(dict(ready=_boolean(saved.get('weekly_ready')),
                         long=_boolean(saved.get('weekly_indicator_gate'))), indicator_status)
    state.update(_gated(dict(current_score_ready=_boolean(saved.get('current_score_ready')),
        current_data_usable=_boolean(saved.get('current_data_usable'))), state_status))
    state['eligible'] = _boolean(saved.get('indicator_effective')) if status == 'confirmed' else None
    return dict(contract_version=ORIGINAL_CONTRACT_VERSION, source='saved_signal', kind='bond_weekly',
                metrics=metrics, state=state, timing=timing)


def _excluded_gold_gate(original):
    confirmed, state = _date(original.get('confirmed_day'))
    status = 'confirmed' if state == 'confirmed' else state
    return dict(contract_version=ORIGINAL_CONTRACT_VERSION, source='saved_signal', kind='excluded',
        metrics={}, state=dict(ready=None, long=False),
        timing=dict(status=status, indicator_status=status, market_status=None,
            state_status=status, confirmed_day=confirmed, period_end=None, available_on=None,
            market_period_end=None, market_available_on=None, state_day=confirmed))


def project_holding_rationale(signal):
    """Project saved facts into a bounded JSON contract; never modify the input."""
    original = _mapping(signal)
    weights = _mapping(original.get('weights'))
    notes = _mapping(original.get('notes'))
    # Native signals store dynamic both at top level and under features. A
    # malformed primary value must not silently fall through to another copy.
    dynamic = _mapping(original['dynamic'] if 'dynamic' in original else
                       _mapping(original.get('features')).get('dynamic'))
    assets = []
    for symbol in SYMBOLS:
        detail = _mapping(dynamic.get(symbol))
        assets.append({
            'symbol': symbol,
            'target_weight': _number(weights.get(symbol), minimum=0, maximum=1),
            'eligible': detail.get('eligible') if isinstance(detail.get('eligible'), bool) else None,
            'note': _text(notes.get(symbol)),
            'momentum20': _number(detail.get('momentum20')),
            'momentum60': _number(detail.get('momentum60')),
            'volatility20': _number(detail.get('volatility20'), minimum=0),
            'effective_score': _number(detail.get('effective_score'), minimum=0),
            'score_ready': detail.get('score_ready') if isinstance(detail.get('score_ready'), bool) else None,
            'original_gate': _original_gate(original, symbol),
        })
    result = {'contract_version': CONTRACT_VERSION, 'reason': _text(original.get('reason')), 'assets': assets}
    if original.get('strategy') == WEEKLY_BOND_STRATEGY:
        result['strategy'] = WEEKLY_BOND_STRATEGY
        gold, bond = assets[2], assets[3]
        gold.update(eligible=False, note='本策略不配置黄金。', allocation_mode='excluded',
                    original_gate=_excluded_gold_gate(original))
        gate = _weekly_bond_gate(original)
        bond.update(eligible=gate['state']['eligible'], allocation_mode='weekly_bond_fallback',
                    original_gate=gate)
        # A 100% fallback budget is not allocated from the original daily bond
        # score. Its daily score readiness remains a separate saved quality gate.
        for asset in (gold, bond):
            for key in ('momentum20', 'momentum60', 'volatility20', 'effective_score'):
                asset[key] = None
        result['weekly_gate'] = {**gate, 'contract_version': WEEKLY_BOND_CONTRACT_VERSION}
    return result
