"""Pure, bounded display of nominal prices from an already confirmed D0 cache.

No market methods, source reads, model construction or ledger writes occur here.
Daily changes compare unadjusted closes, not total returns or historical exchange
ex-right reference prices. Company actions do not alter that arithmetic. Missing
sessions keep their recorded price but do not assert a one-session change.
"""
from bisect import bisect_left, bisect_right
from datetime import date
from decimal import Decimal, InvalidOperation
import math

from realtime_paper_rationale import SYMBOLS

SOURCE = 'confirmed_daily_history'
BASIS = 'unadjusted_close'
MAX_POINTS = 120
MAX_SOURCE_ROWS = 20000
REASONS = {'cache_unavailable', 'signal_mismatch', 'series_mismatch', 'invalid_history'}


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _day(value):
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        return value if date.fromisoformat(value).isoformat() == value else None
    except ValueError:
        return None


def _text(value):
    return value if isinstance(value, str) and 0 < len(value) <= 128 and all(ord(c) >= 32 for c in value) else None


def _number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    if isinstance(value, str) and (not value or len(value) > 64):
        return None
    try:
        parsed = float(Decimal(str(value)))
    except (ValueError, InvalidOperation, OverflowError):
        return None
    if not math.isfinite(parsed) or abs(parsed) > 1e100 or (positive and parsed <= 0):
        return None
    return parsed


def _same(left, right):
    return left is right if left is None or right is None else math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)


def unavailable(saved_signal, reason='cache_unavailable', status='unavailable'):
    signal = _mapping(saved_signal)
    return dict(status=status, reason=reason, signal_key=_text(signal.get('id')),
                confirmed_day=_day(signal.get('confirmed_day')), basis=BASIS,
                source=SOURCE, points=[], truncated=False)


def project_daily_price_history(history, saved_signal, symbol):
    """Whitelist a source projection at the HTTP boundary; never fill bad data."""
    saved_signal = _mapping(saved_signal)
    try:
        if symbol not in SYMBOLS:
            raise ValueError('unsupported symbol')
        if not isinstance(history, dict):
            return unavailable(saved_signal)
        day = _day(saved_signal.get('confirmed_day'))
        identity = _text(saved_signal.get('id'))
        if (not day or not identity or history.get('signal_key') != identity
                or history.get('confirmed_day') != day or history.get('source') != SOURCE
                or history.get('basis') != BASIS):
            return unavailable(saved_signal, 'signal_mismatch', 'invalid')
        status, reason = history.get('status'), history.get('reason')
        if status in ('unavailable', 'invalid'):
            return unavailable(saved_signal, reason if reason in REASONS else 'invalid_history', status)
        if status != 'available' or reason is not None or type(history.get('truncated')) is not bool:
            raise ValueError('invalid history status')
        rows = history.get('points')
        if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_POINTS:
            raise ValueError('invalid point count')
        points = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError('invalid point')
            when, close = _day(row.get('date')), _number(row.get('close'), positive=True)
            if not when or when > day or close is None or (points and when <= points[-1]['date']):
                raise ValueError('invalid date or price')
            if type(row.get('break_before')) is not bool:
                raise ValueError('invalid gap flag')
            previous_date, previous_close = row.get('previous_date'), row.get('previous_close')
            change = row.get('change_ratio')
            if previous_date is None and previous_close is None:
                if points or history['truncated'] or change is not None:
                    raise ValueError('missing preceding price')
            else:
                previous_date = _day(previous_date)
                previous_close = _number(previous_close, positive=True)
                if not previous_date or previous_date >= when or previous_close is None:
                    raise ValueError('invalid preceding price')
                if points:
                    if previous_date != points[-1]['date'] or not _same(previous_close, points[-1]['close']):
                        raise ValueError('discontinuous preceding price')
                elif not history['truncated']:
                    raise ValueError('unreported truncated history')
                if change is not None:
                    change = _number(change)
                    computed = close / previous_close - 1
                    if change is None or not _same(change, computed) or row['break_before']:
                        raise ValueError('invalid daily change')
                elif not row['break_before']:
                    raise ValueError('missing change without gap')
            points.append(dict(date=when, close=close, previous_close=previous_close,
                               previous_date=previous_date, change_ratio=change,
                               break_before=row['break_before']))
        reference = _number(_mapping(saved_signal.get('reference_prices')).get(symbol), positive=True)
        if reference is None or points[-1]['date'] != day or not _same(points[-1]['close'], reference):
            return unavailable(saved_signal, 'series_mismatch')
        return unavailable(saved_signal) | dict(status='available', reason=None,
                                                points=points, truncated=history['truncated'])
    except (TypeError, ValueError, OverflowError, AttributeError, ArithmeticError):
        return unavailable(saved_signal, 'invalid_history', 'invalid')


def extract_daily_price_histories(saved_signal, cached_signal, signal_key, market):
    """Read scalar cached attributes only; return independent four-asset views."""
    saved_signal = _mapping(saved_signal)
    def all_unavailable(reason='cache_unavailable', status='unavailable'):
        return {symbol: unavailable(saved_signal, reason, status) for symbol in SYMBOLS}
    if not isinstance(cached_signal, dict) or market is None:
        return all_unavailable()
    fields = ('id', 'history_hash', 'spec_hash', 'confirmed_day')
    expected_key = (saved_signal.get('confirmed_day'), saved_signal.get('history_hash'))
    if saved_signal.get('strategy') == 'D0I-BOND-WW':
        expected_key += ('D0I-BOND-WW',)
    if (any(not _text(saved_signal.get(key)) or saved_signal.get(key) != cached_signal.get(key) for key in fields)
            or not _day(saved_signal.get('confirmed_day'))
            or signal_key != expected_key
            or saved_signal.get('strategy', 'D0') != cached_signal.get('strategy', 'D0')
            or any(s.get('history_cutoff', s.get('confirmed_day')) != s.get('confirmed_day') for s in (saved_signal, cached_signal))):
        return all_unavailable('signal_mismatch', 'invalid')
    day = saved_signal['confirmed_day']
    inputs = getattr(market, 'inputs', None)
    bars = getattr(inputs, 'bars', None)
    sessions = getattr(market, 'dates', None)
    if not isinstance(bars, dict) or sessions is None:
        return all_unavailable()
    if (not isinstance(sessions, list) or not 1 <= len(sessions) <= MAX_SOURCE_ROWS
            or any(not _day(value) for value in sessions) or sessions != sorted(set(sessions)) or day not in sessions):
        return all_unavailable('invalid_history', 'invalid')
    session_set = set(sessions)
    results = {}
    for symbol in SYMBOLS:
        try:
            rows = bars.get(symbol)
            if rows is None:
                results[symbol] = unavailable(saved_signal)
                continue
            if not isinstance(rows, list) or not 1 <= len(rows) <= MAX_SOURCE_ROWS:
                raise ValueError('invalid cached price series')
            selected = []; previous_day = None
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError('invalid cached price row')
                when = _day(row.get('date'))
                if not when or (previous_day and when <= previous_day):
                    raise ValueError('invalid cached dates')
                previous_day = when
                if when > day or when < sessions[0]:
                    continue
                close = _number(row.get('close'), positive=True)
                if close is None or when not in session_set:
                    raise ValueError('invalid cached nominal price')
                selected.append((when, close))
            if not selected:
                results[symbol] = unavailable(saved_signal, 'series_mismatch')
                continue
            points = []; previous = None
            for when, close in selected:
                gap = False; change = None
                if previous:
                    prior_day, prior_close = previous
                    gap = bisect_right(sessions, prior_day) < bisect_left(sessions, when)
                    if not gap:
                        change = close / prior_close - 1
                        if _number(change) is None:
                            raise ValueError('invalid derived change')
                points.append(dict(date=when, close=close,
                                   previous_close=previous[1] if previous else None,
                                   previous_date=previous[0] if previous else None,
                                   change_ratio=change, break_before=gap))
                previous = when, close
            history = unavailable(saved_signal) | dict(status='available', reason=None,
                points=points[-MAX_POINTS:], truncated=len(points) > MAX_POINTS)
            results[symbol] = project_daily_price_history(history, saved_signal, symbol)
        except (TypeError, ValueError, OverflowError, AttributeError, ArithmeticError):
            results[symbol] = unavailable(saved_signal, 'invalid_history', 'invalid')
    return results
