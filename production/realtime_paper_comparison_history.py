"""Pure daily valuation reconstructed from the account's recorded trades.

This is historical-close marking of the complete saved fills, not the ledger's
observed P&L series. It neither changes that series nor reads/writes a ledger.
The caller supplies unadjusted bars and confirmed complete common sessions;
benchmark baselines and live estimates belong to the comparison service.
"""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
import hashlib
import json

from realtime_paper_pnl import CENT, MAX_AMOUNT, _format, _number, _quantity, _stamp
from realtime_paper_rationale import SYMBOLS

TZ = timezone(timedelta(hours=8))
MAX_ITEMS = 100000
MAX_SESSIONS = 5000
MAX_CAPITAL = Decimal('1000000000')
TICK = Decimal('.001')


class _Invalid(ValueError):
    pass


def _identity(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 256:
        raise _Invalid('invalid_history')
    return value


def _time(value):
    parsed = _stamp(value)
    if parsed is None:
        raise _Invalid('invalid_history')
    return parsed.astimezone(TZ)


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    allow_nan=False).encode()).hexdigest()


def _list(value):
    if not isinstance(value, list) or len(value) > MAX_ITEMS:
        raise _Invalid('invalid_history')
    return value


def _sessions(values):
    if not isinstance(values, (list, tuple)) or len(values) > MAX_SESSIONS:
        raise _Invalid('invalid_sessions')
    result, previous = [], None
    for value in values:
        if not isinstance(value, str) or len(value) != 10:
            raise _Invalid('invalid_sessions')
        day = date.fromisoformat(value)
        if day.isoformat() != value or (previous is not None and day <= previous):
            raise _Invalid('invalid_sessions')
        result.append((value, datetime.combine(day, time(15), TZ)))
        previous = day
    return result


def _events(raw, created, now):
    capitals, matches, seen = [], [], set()
    first_start = None
    previous = created
    for index, event in enumerate(_list(raw['events'])):
        key = _identity(event['id'])
        kind = _identity(event['type'])
        at = _time(event['at'])
        if key in seen or not previous <= at <= now:
            raise _Invalid('invalid_history')
        if (index == 0) != (kind == 'created'):
            raise _Invalid('invalid_history')
        seen.add(key)
        previous = at
        if kind in ('created', 'capital_changed'):
            capital = _number(event['capital'], positive=True, cents=True)
            if capital > MAX_CAPITAL or matches:
                raise _Invalid('invalid_history')
            capitals.append((event, at, capital, index))
        elif kind == 'started' and first_start is None:
            first_start = (at, index)
        elif kind == 'estimated_fill':
            matches.append((event, at, index))
    if not capitals:
        raise _Invalid('invalid_history')
    return capitals, matches, first_start


def _fills(raw, matches, capitals, first_start, created, now):
    orders, seen_orders = {}, set()
    for order in _list(raw['orders']):
        key = _identity(order['id'])
        if (key in seen_orders or (order.get('status') != 'filled'
                                  and order.get('fill_id') is not None)):
            raise _Invalid('invalid_history')
        seen_orders.add(key)
        orders[key] = order
    fills = _list(raw['fills'])
    if len(matches) != len(fills):
        raise _Invalid('invalid_history')
    result, seen, filled_orders = [], set(), set()
    previous = created
    for fill, (event, event_at, event_index) in zip(fills, matches):
        key, order_key = _identity(fill['id']), _identity(fill['order_id'])
        at = _time(fill['matched_at'])
        symbol, side = fill['symbol'], fill['side']
        qty = _quantity(fill['qty'], positive=True)
        price = _number(fill['price'], positive=True)
        gross = _number(fill['gross'], positive=True, cents=True)
        fee = _number(fill['fee'], cents=True)
        if (key in seen or order_key in filled_orders or symbol not in SYMBOLS
                or side not in ('buy', 'sell') or qty > 1000000 or qty % 100
                or price != price.quantize(TICK)
                or gross != (price * qty).quantize(CENT, rounding=ROUND_HALF_UP)
                or not previous <= at <= now or at > event_at
                or first_start is None or at < first_start[0]
                or event_index <= first_start[1] or at < capitals[-1][1]
                or event.get('fill_id') != key or event.get('order_id') != order_key):
            raise _Invalid('invalid_history')
        order = orders[order_key]
        times = {field: _time(fill.get(field)) for field in
                 ('submitted_at', 'eligible_at', 'quote_at', 'received_at')}
        if (any(_time(order.get(field)) != stamp for field, stamp in times.items())
                or not created <= times['submitted_at'] <= times['eligible_at'] < at
                or not times['eligible_at'] < times['quote_at'] <= times['received_at'] <= at):
            # Final cash reconciliation alone cannot catch a matched_at moved
            # to the previous session while its actual quote is still later.
            raise _Invalid('invalid_history')
        if (order.get('status') != 'filled' or order.get('fill_id') != key
                or order.get('symbol') != symbol or order.get('side') != side
                or type(order.get('qty')) is not int or order['qty'] != qty
                or type(order.get('qty_filled')) is not int or order['qty_filled'] != qty
                or type(order.get('remaining_qty')) is not int or order['remaining_qty'] != 0
                or _time(order.get('matched_at')) != at):
            raise _Invalid('invalid_history')
        seen.add(key)
        filled_orders.add(order_key)
        previous = at
        result.append((at, symbol, side, qty, gross, fee))
    if {key for key, order in orders.items() if order.get('status') == 'filled'} != filled_orders:
        raise _Invalid('invalid_history')
    return result


def _positions(raw):
    rows = raw['positions']
    if not isinstance(rows, list) or len(rows) != len(SYMBOLS):
        raise _Invalid('invalid_history')
    result = {}
    for row in rows:
        symbol = row['symbol']
        if symbol not in SYMBOLS or symbol in result:
            raise _Invalid('invalid_history')
        result[symbol] = _quantity(row['qty'])
    return result


def _equity(cash, positions, bars, day):
    equity = cash
    try:
        for symbol, qty in positions.items():
            if qty:
                price = _number(bars[symbol][day]['close'], positive=True)
                equity += (price * qty).quantize(CENT, rounding=ROUND_HALF_UP)
                if equity > MAX_AMOUNT:
                    return None
        return _format(equity)
    except (KeyError, TypeError, ValueError, InvalidOperation, ArithmeticError):
        # A missing or unsafe historical mark breaks the line; never fill it
        # with a current quote or the preceding session's price.
        return None


def reconstruct_account_history(raw, bars, sessions, *, now):
    """Reconstruct daily closes from complete saved transactions, without IO.

    Events, fills and filled orders must agree, and replayed cash/quantities
    must equal the supplied final snapshot before any history is returned.
    The original fill order resolves equal timestamps. Reserved cash is still
    account cash. Missing held-asset closes yield null equity and a line break.
    Invalid evidence returns no curve or unverified final state.
    """
    result = dict(status='invalid', reason='invalid_history', account_id=None,
                  created_at=None, first_started_at=None, segments=[], last_state=None)
    with localcontext() as context:
        context.prec = 60
        try:
            if (not isinstance(now, datetime) or now.tzinfo is None
                    or now.utcoffset() is None or not isinstance(raw, dict)):
                raise _Invalid('invalid_history')
            now = now.astimezone(TZ)
            if raw.get('account') is None:
                result.update(status='unavailable', reason='account_not_created')
                return result
            if not isinstance(bars, dict):
                raise _Invalid('invalid_history')
            closes = _sessions(sessions)
            account = raw['account']
            account_id = _identity(account['id'])
            created = _time(account['created_at'])
            if created > now:
                raise _Invalid('invalid_history')
            result.update(account_id=account_id, created_at=created.isoformat())
            capital = _number(account['initial_capital'], positive=True, cents=True)
            final_cash = _number(account['cash'], cents=True)
            expected_positions = _positions(raw)
            capitals, matches, first_start = _events(raw, created, now)
            if capital != capitals[-1][2]:
                raise _Invalid('reconciliation_failed')
            fills = _fills(raw, matches, capitals, first_start, created, now)
            if first_start is not None:
                result['first_started_at'] = first_start[0].isoformat()

            account_key = _hash({'id': account_id, 'created_at': account['created_at']})
            segments = []
            for index, (event, at, amount, _) in enumerate(capitals):
                segments.append(dict(
                    id=_hash({'account_key': account_key, 'capital': _format(amount),
                              'event_id': event['id'], 'event_at': event['at']}),
                    capital=_format(amount),
                    starts_at=max(first_start[0], at).isoformat() if first_start else None,
                    ends_at=capitals[index + 1][1].isoformat() if index + 1 < len(capitals) else None,
                    points=[]))

            cash, positions = Decimal(0), {symbol: 0 for symbol in SYMBOLS}
            capital_index, fill_index, active_segment = 0, 0, None

            def advance(until):
                nonlocal cash, capital_index, fill_index, active_segment
                # The native account permits changing capital only before any
                # fill. _events/_fills above establish this ordering first.
                while capital_index < len(capitals) and capitals[capital_index][1] <= until:
                    cash = capitals[capital_index][2]
                    active_segment = capital_index
                    capital_index += 1
                while fill_index < len(fills) and fills[fill_index][0] <= until:
                    _, symbol, side, qty, gross, fee = fills[fill_index]
                    if side == 'buy':
                        cash -= gross + fee
                        positions[symbol] += qty
                    else:
                        cash += gross - fee
                        positions[symbol] -= qty
                    _number(cash, cents=True)
                    _quantity(positions[symbol])
                    fill_index += 1

            if first_start is not None:
                for day, at in closes:
                    if at > now:
                        break
                    advance(at)
                    if at < first_start[0] or active_segment is None:
                        continue
                    segment = segments[active_segment]
                    equity = _equity(cash, positions, bars, day)
                    previous = segment['points'][-1] if segment['points'] else None
                    segment['points'].append(dict(
                        date=day, at=at.isoformat(), equity=equity, cash=_format(cash),
                        positions=dict(positions), break_before=(
                            equity is None or previous is None or previous['equity'] is None)))
            advance(now)
            if cash != final_cash or positions != expected_positions:
                raise _Invalid('reconciliation_failed')
            result['last_state'] = {'cash': _format(cash), 'positions': dict(positions)}
            if first_start is None:
                result.update(status='unavailable', reason='not_started')
            else:
                result.update(status='available', reason=None, segments=segments)
            return result
        except _Invalid as exc:
            result['reason'] = str(exc)
        except (KeyError, TypeError, ValueError, InvalidOperation, ArithmeticError, AttributeError):
            pass
    result.update(status='invalid', segments=[], last_state=None)
    return result
