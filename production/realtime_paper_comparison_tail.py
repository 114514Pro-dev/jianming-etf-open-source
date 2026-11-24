"""Retain a recorded comparison estimate without renewing its evidence."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import math

TZ = timezone(timedelta(hours=8))
RETAINED_LINES = frozenset(('account', 'd0'))


def _stamp(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('timezone required')
    return parsed.astimezone(TZ)


def _last_history(points):
    return next((point for point in reversed(points)
                 if point.get('phase') != 'intraday_estimate'), None)


def _history_identity(point):
    if not isinstance(point, dict):
        return None
    return tuple(point.get(field) for field in
                 ('phase', 'at', 'equity', 'source_at', 'segment_id', 'break_before'))


def _valid_recorded_point(point, segment, history, now):
    if (point.get('segment_id') != segment['id']
            or point.get('phase') != 'intraday_estimate'
            or point.get('date') != now.date().isoformat()):
        return False
    at = _stamp(point['at'])
    observed = _stamp(point['observed_at'])
    source = _stamp(point['source_at']) if point.get('source_at') is not None else None
    if (at.date() != now.date() or observed.date() != now.date()
            or not observed <= at <= now
            or at <= _stamp(history['at']) or at < _stamp(segment['baseline_at'])):
        return False
    if source is None:
        if point.get('cash_only') is not True:
            return False
    elif (source.date() != now.date() or not source <= observed
          or source <= _stamp(history['at']) or source < _stamp(segment['baseline_at'])):
        return False
    if isinstance(point.get('equity'), bool) or isinstance(point.get('return_ratio'), bool):
        return False
    equity, baseline = Decimal(str(point['equity'])), Decimal(str(segment['baseline_equity']))
    ratio = float(point['return_ratio'])
    return (equity.is_finite() and equity >= 0 and baseline.is_finite() and baseline > 0
            and math.isfinite(ratio) and math.isclose(ratio, float(equity / baseline - 1),
                                                    rel_tol=1e-10, abs_tol=1e-10))


def retain_intraday(result, previous, *, now, same_identity):
    """Return a copy with eligible account/model observations kept verbatim.

    The caller must establish the same business, signal and model identities.
    These are historical observations, not a substitute for current quotes:
    source, receipt and record timestamps are never advanced, including after
    a producer failure, a session boundary or freshness expiry.
    """
    result = deepcopy(result)
    if same_identity is not True or not isinstance(previous, dict):
        return result
    try:
        now = _stamp(now)
        if (result.get('status') != 'available' or previous.get('status') != 'available'
                or not result.get('account_id') or result['account_id'] != previous.get('account_id')
                or result.get('contract_version') != previous.get('contract_version')
                or result.get('strategy', 'D0') != previous.get('strategy', 'D0')
                or result.get('normalization') != previous.get('normalization')):
            return result
        segment, old_segment = result['segments'][-1], previous['segments'][-1]
        fields = ('id', 'starts_at', 'ends_at', 'baseline_at', 'baseline_equity', 'capital')
        if (not segment.get('id') or not segment.get('baseline_at')
                or segment.get('ends_at') is not None or old_segment.get('ends_at') is not None
                or any(segment.get(key) != old_segment.get(key) for key in fields)):
            return result
        old_lines = {}
        for line in previous['series']:
            if line['id'] in old_lines:
                return result
            old_lines[line['id']] = line
        if len({line['id'] for line in result['series']}) != len(result['series']):
            return result
        for line in result['series']:
            if line['id'] not in RETAINED_LINES:
                continue
            old = old_lines.get(line['id'])
            if (not old or line.get('status') != 'available' or old.get('status') != 'available'
                    or not line.get('method') or line['method'] != old.get('method')):
                continue
            points, old_points = line['points'], old['points']
            if any(point.get('phase') == 'intraday_estimate'
                   and point.get('segment_id') == segment['id'] for point in points):
                continue
            history, old_history = _last_history(points), _last_history(old_points)
            if (history is None or history.get('segment_id') != segment['id']
                    or _history_identity(history) != _history_identity(old_history)):
                continue
            point = next((p for p in reversed(old_points)
                          if p.get('phase') == 'intraday_estimate'
                          and p.get('segment_id') == segment['id']), None)
            if point is None:
                continue
            try:
                if not _valid_recorded_point(point, segment, history, now):
                    continue
            except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation, ArithmeticError):
                continue
            kept = deepcopy(point)
            kept.update(retained=True, retained_reason='waiting_verified_quote')
            points.append(kept)
            line['as_of'] = kept.get('source_at') or kept['at']
        return result
    except (ValueError, TypeError, KeyError, IndexError, AttributeError, InvalidOperation, ArithmeticError):
        return result
