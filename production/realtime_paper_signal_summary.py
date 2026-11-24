"""Read-only D0 signal/plan explanation from one saved account snapshot.

This module never calculates a strategy, sizes an order or reads/writes storage.
Directions describe the frozen plan's remaining quantity, not permission to trade.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import json

from realtime_paper_rationale import SYMBOLS, project_holding_rationale
from realtime_paper_engine import TradingCalendar

CONTRACT_VERSION = 'd0-signal-summary-v1'
STRATEGIES = frozenset(('D0', 'D0I-BOND-WW'))
CN = timezone(timedelta(hours=8))
TERMINAL = {'cancelled', 'rejected', 'expired'}


def _mapping(value):
    return value if type(value) is dict else {}


def _identifier(value):
    return value if type(value) is str and 0 < len(value) <= 4096 and not any(ord(c) < 32 for c in value) else None


def _integer(value, maximum=10**12):
    return type(value) is int and 0 <= value <= maximum


def _decimal(value, maximum=Decimal('1e100')):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)) or len(str(value)) > 128:
        return None
    try:
        number = Decimal(str(value))
        return number if number.is_finite() and 0 <= number <= maximum else None
    except (InvalidOperation, ValueError):
        return None


def _moment(value):
    try:
        if type(value) is str:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            return None
        return value.astimezone(CN)
    except (ValueError, TypeError, OverflowError):
        return None


def _day(value):
    try:
        return date.fromisoformat(value) if type(value) is str and len(value) == 10 else None
    except ValueError:
        return None


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


def _signal_valid(signal, now):
    if (type(signal.get('strategy')) is not str or signal.get('strategy') not in STRATEGIES
            or signal.get('valid') is not True or _identifier(signal.get('id')) is None):
        return False
    weights = _mapping(signal.get('weights'))
    numbers = [_decimal(weights.get(symbol), Decimal(1)) for symbol in SYMBOLS]
    if set(weights) != set(SYMBOLS) or any(number is None for number in numbers) or sum(numbers) > 1:
        return False
    if signal.get('strategy') == 'D0I-BOND-WW' and (numbers[2] != 0 or numbers[3] > 0 and sum(numbers[:2]) > 0):
        return False
    times = [_moment(signal.get(key)) for key in ('data_cutoff', 'signal_at', 'known_at', 'received_at', 'eligible_at')]
    if now is None or any(value is None for value in times):
        return False
    cutoff, at, known, received, eligible = times
    confirmed, execution = _day(signal.get('confirmed_day')), _day(signal.get('execution_day'))
    if signal.get('strategy') == 'D0I-BOND-WW' and numbers[3] > 0:
        weekly = _mapping(signal.get('ww_bond'))
        end, available, quote = (_day(weekly.get(key)) for key in ('week_end', 'available', 'current_quote_date'))
        if (None in (end, available, quote, confirmed) or not end <= available <= confirmed or quote != confirmed
                or any(weekly.get(key) is not True for key in ('weekly_ready', 'weekly_indicator_gate',
                    'current_score_ready', 'current_data_usable', 'indicator_effective'))):
            return False
    return (cutoff <= at <= known <= received <= now and cutoff <= eligible
            and confirmed == cutoff.date() and signal.get('day') == signal.get('confirmed_day')
            and execution == eligible.date() and confirmed < execution)


def _plan_status(plan, account, signal, now):
    if not plan:
        return 'missing'
    if (_identifier(plan.get('id')) is None or _identifier(plan.get('signal_id')) is None
            or not _integer(plan.get('generation')) or _day(plan.get('session_day')) is None):
        return 'invalid'
    if (plan['signal_id'] != signal['id'] or plan['generation'] != account.get('activation_generation')
            or plan['session_day'] != now.date().isoformat()):
        return 'historical'
    expected = _hash({'signal': signal['id'], 'day': plan['session_day'], 'generation': plan['generation']})
    targets = _mapping(plan.get('targets'))
    created, resumed = _moment(plan.get('created_at')), _moment(account.get('resumed_at'))
    received, eligible = _moment(signal.get('received_at')), _moment(signal.get('eligible_at'))
    if (plan['id'] != expected or set(targets) != set(SYMBOLS)
            or any(not _integer(qty) or qty % 100 for qty in targets.values())
            or created is None or resumed is None or not received <= created <= now
            or not resumed <= created or created.date() != now.date() or created < eligible):
        return 'invalid'
    return 'current'


def _positions(raw):
    rows = raw.get('positions')
    if type(rows) is not list or len(rows) != len(SYMBOLS):
        return None
    result = {}
    for row in rows:
        row = _mapping(row)
        symbol = row.get('symbol')
        if (symbol not in SYMBOLS or symbol in result or not _integer(row.get('qty'))
                or not _integer(row.get('available_qty')) or row['available_qty'] > row['qty']):
            return None
        result[symbol] = row
    return result


def _orders(raw, account, signal, plan, now):
    """Validate current-plan orders; an active old order makes action uncertain."""
    rows = raw.get('orders')
    if type(rows) is not list:
        return None
    result, ids, clients = [], set(), set()
    for candidate in rows:
        row = _mapping(candidate)
        current = row.get('signal_id') == signal['id'] and row.get('plan_id') == plan['id']
        if not current:
            if row.get('status') == 'pending':
                return None
            continue
        if (row.get('symbol') not in SYMBOLS or row.get('side') not in ('buy', 'sell')
                or type(row.get('status')) is not str or row.get('status') not in TERMINAL | {'pending', 'filled'}
                or any(_identifier(row.get(k)) is None for k in ('id', 'client_order_id', 'intent_id'))
                or row['id'] in ids or row['client_order_id'] in clients
                or ('account_id' in row and row['account_id'] != account['id'])
                or not _integer(row.get('qty'), 1000000) or not row['qty'] or row['qty'] % 100
                or not _integer(row.get('remaining_qty')) or not _integer(row.get('qty_filled'))
                or _decimal(row.get('limit_price')) in (None, Decimal(0))):
            return None
        ids.add(row['id']); clients.add(row['client_order_id'])
        signal_at, submitted, eligible, expires = [_moment(row.get(k)) for k in ('signal_at', 'submitted_at', 'eligible_at', 'expires_at')]
        if (any(value is None for value in (signal_at, submitted, eligible, expires))
                or signal_at != _moment(signal['signal_at'])
                or not _moment(plan['created_at']) <= submitted <= now
                or submitted.date() != now.date() or expires.date() != now.date()
                or not submitted <= eligible < expires or eligible < _moment(signal['eligible_at'])):
            return None
        status = row['status']
        if status == 'pending':
            if row['remaining_qty'] != row['qty'] or row['qty_filled'] != 0 or row.get('terminal_at') is not None:
                return None
        else:
            terminal = _moment(row.get('terminal_at'))
            if terminal is None or not submitted <= terminal <= now or row['remaining_qty'] != 0:
                return None
            if row['qty_filled'] != (row['qty'] if status == 'filled' else 0):
                return None
        result.append(row)
    return result


def _terminal_intent(orders, signal, plan, symbol, side):
    """Mirror only the saved intent ID chain, never run the order planner."""
    identity = {'signal': signal['id'], 'day': plan['session_day'], 'generation': plan['generation'], 'symbol': symbol, 'side': side}
    clients = {row['client_order_id']: row for row in orders}
    for child in range(len(orders) + 1):
        row = clients.get(_hash(dict(identity, child=child)))
        if child == 0 and row is None:
            row = clients.get(_hash(identity))
        if row is None:
            return None
        if row['status'] != 'filled':
            return row if row['status'] in TERMINAL else None
    return None


def _latest_fill(raw, signal, plan, now):
    rows = raw.get('fills')
    if type(rows) is not list or now is None:
        return None
    source_orders = raw.get('orders')
    if type(source_orders) is not list:
        return None
    orders = {}
    for order in source_orders:
        order = _mapping(order)
        if _identifier(order.get('id')) is None or order['id'] in orders:
            return None
        orders[order['id']] = order
    ids, candidates = set(), []
    for row in rows:
        row = _mapping(row)
        at = _moment(row.get('matched_at'))
        if (_identifier(row.get('id')) is None or row['id'] in ids
                or any(_identifier(row.get(k)) is None for k in ('order_id', 'signal_id', 'plan_id'))
                or row.get('symbol') not in SYMBOLS or row.get('side') not in ('buy', 'sell')
                or not _integer(row.get('qty'), 1000000) or not row['qty']
                or _decimal(row.get('price')) in (None, Decimal(0)) or at is None or at > now):
            return None
        order = orders.get(row['order_id'], {})
        if (order.get('status') != 'filled' or order.get('fill_id') != row['id']
                or order.get('qty_filled') != row['qty'] or order.get('remaining_qty') != 0
                or any(row.get(key) != order.get(key) for key in ('signal_id', 'plan_id', 'symbol', 'side', 'qty', 'signal_at', 'submitted_at', 'eligible_at', 'matched_at', 'quote_at', 'received_at'))):
            return None
        submitted, eligible, quote, received = [_moment(row.get(key)) for key in ('submitted_at', 'eligible_at', 'quote_at', 'received_at')]
        if any(value is None for value in (submitted, eligible, quote, received)) or not submitted <= eligible <= quote <= received <= at:
            return None
        ids.add(row['id']); candidates.append((at, row))
    if not candidates:
        return None
    _, row = max(candidates, key=lambda item: (item[0], item[1]['id']))
    return {**{key: row[key] for key in ('id', 'order_id', 'signal_id', 'plan_id', 'symbol', 'side', 'matched_at')},
            'quantity': row['qty'], 'price': format(_decimal(row['price']), 'f'),
            'current_signal': row['signal_id'] == signal.get('id'),
            'current_plan': row['plan_id'] == plan.get('id') and row['signal_id'] == signal.get('id')}


def project_signal_summary(raw, *, now, source_status, observer_status, command=False):
    raw = _mapping(raw); account = _mapping(raw.get('account')); signal = _mapping(raw.get('signal')); plan = _mapping(raw.get('plan'))
    moment = _moment(now)
    result = {'contract_version': CONTRACT_VERSION, 'account_id': _identifier(account.get('id')),
              'generated_at': moment.isoformat() if moment else None, 'signal_id': _identifier(signal.get('id')),
              'plan_id': _identifier(plan.get('id')), 'signal_status': 'missing', 'plan_status': 'missing',
              'reference_status': 'unavailable', 'action': 'wait', 'execution_status': 'waiting', 'reason_code': 'no_signal',
              **{key: None for key in ('confirmed_day', 'execution_day', 'eligible_at', 'signal_at', 'known_at', 'data_cutoff', 'plan_created_at', 'saved_reason')},
              'assets': [], 'latest_fill': _latest_fill(raw, signal, plan, moment), 'is_trade_instruction': False}
    positions = _positions(raw)
    rationale = project_holding_rationale(signal)
    details = {row['symbol']: row for row in rationale['assets']}
    signal_valid = _signal_valid(signal, moment)
    for symbol in SYMBOLS:
        detail = details[symbol]; position = positions.get(symbol) if positions is not None else None
        weight = _decimal(_mapping(signal.get('weights')).get(symbol), Decimal(1)) if signal_valid else None
        result['assets'].append({'symbol': symbol, 'target_weight': format(weight, 'f') if weight is not None else None,
            'actual_quantity': position['qty'] if position else None, 'target_quantity': None, 'difference_quantity': None,
            'action': 'wait', 'progress': 'no_plan', 'reason_code': 'no_plan', 'pending_quantity': 0,
            'pending_side': None, 'terminal_status': None, 'order_ids': [],
            'trigger': {key: detail[key] for key in ('eligible', 'score_ready', 'effective_score', 'note')}})
    if not signal_valid:
        if result['latest_fill']:
            result['latest_fill'].update(current_signal=False, current_plan=False)
        if signal:
            result.update(signal_status='invalid', reference_status='invalid', execution_status='needs_review', reason_code='invalid_signal')
        return result
    result.update(signal_status='confirmed', saved_reason=rationale['reason'],
                  **{key: signal[key] for key in ('confirmed_day', 'execution_day', 'eligible_at', 'signal_at', 'known_at', 'data_cutoff')})
    if (type(account.get('strategy')) is not str or account.get('strategy') not in STRATEGIES
            or account.get('strategy') != signal.get('strategy')
            or result['account_id'] is None or type(account.get('running')) is not bool
            or not _integer(account.get('activation_generation')) or moment is None):
        result.update(reference_status='invalid', execution_status='needs_review', reason_code='unknown_account')
        return result
    plan_status = _plan_status(plan, account, signal, moment)
    result['plan_status'] = plan_status
    if result['latest_fill'] and plan_status != 'current':
        result['latest_fill']['current_plan'] = False
    if plan_status != 'current':
        result.update(reference_status='saved' if plan_status != 'invalid' else 'invalid',
                      execution_status='needs_review' if plan_status == 'invalid' else 'stopped' if not account['running'] else 'waiting',
                      reason_code={'missing': 'no_plan', 'historical': 'old_plan', 'invalid': 'invalid_plan'}[plan_status])
        for asset in result['assets']:
            asset.update(progress='needs_review' if plan_status == 'invalid' else 'no_plan', reason_code=result['reason_code'])
        return result
    result['plan_created_at'] = plan['created_at']
    orders = _orders(raw, account, signal, plan, moment)
    if positions is None or orders is None:
        result.update(reference_status='invalid', execution_status='needs_review', reason_code='invalid_positions' if positions is None else 'invalid_orders')
        for asset in result['assets']:
            asset.update(progress='needs_review', reason_code=result['reason_code'])
        return result
    sells_pending = any(order['side'] == 'sell' and order['status'] == 'pending' and moment < _moment(order['expires_at']) for order in orders)
    for asset in result['assets']:
        symbol = asset['symbol']; target = plan['targets'][symbol]; actual = positions[symbol]['qty']; gap = target - actual
        action = 'buy' if gap > 0 else 'sell' if gap < 0 else 'hold' if actual else 'cash'
        asset.update(target_quantity=target, difference_quantity=gap, action=action,
                     progress='target_reached' if not gap else 'awaiting_submission', reason_code='target_reached' if not gap else 'awaiting_submission')
        pending = [order for order in orders if order['symbol'] == symbol and order['status'] == 'pending']
        terminal = _terminal_intent(orders, signal, plan, symbol, action) if gap else None
        if pending:
            if len(pending) != 1 or pending[0]['side'] != action or pending[0]['remaining_qty'] > abs(gap):
                asset.update(action='wait', progress='needs_review', reason_code='invalid_orders')
            else:
                order = pending[0]; asset.update(order_ids=[order['id']])
                if moment >= _moment(order['expires_at']):
                    asset.update(progress='terminal_order', reason_code='terminal_order', terminal_status='expired')
                else:
                    asset.update(progress='pending_order', reason_code='pending_order', pending_quantity=order['remaining_qty'], pending_side=order['side'])
        elif terminal:
            asset.update(progress='terminal_order', reason_code='terminal_order', terminal_status=terminal['status'], order_ids=[terminal['id']])
        elif action == 'buy' and sells_pending:
            asset.update(progress='waiting_sell', reason_code='waiting_sell')
        elif action == 'sell' and positions[symbol]['available_qty'] < min(100, -gap):
            asset.update(progress='sellable_limited', reason_code='sellable_limited')
    actions = {asset['action'] for asset in result['assets']}
    result['action'] = 'wait' if 'wait' in actions else 'rebalance' if {'buy', 'sell'} <= actions else 'buy' if 'buy' in actions else 'sell' if 'sell' in actions else 'hold' if 'hold' in actions else 'cash'
    reason = ('invalid_orders' if 'wait' in actions else 'command_snapshot' if command is not False
              else 'account_stopped' if not account['running'] else 'before_eligible' if moment < _moment(signal['eligible_at'])
              else 'outside_session' if not TradingCalendar().is_continuous(moment)
              else 'source_not_ready' if source_status != 'ready' else 'observer_not_running' if observer_status != 'running' else 'ready')
    result.update(reason_code=reason, reference_status='current' if reason == 'ready' else 'invalid' if reason == 'invalid_orders' else 'saved',
                  execution_status='ready' if reason == 'ready' else 'stopped' if reason == 'account_stopped' else 'needs_review' if reason == 'invalid_orders' else 'waiting')
    return result
