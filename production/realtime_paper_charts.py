"""Bounded display-only projection of an already computed D0 input cache.

This module never constructs a market, evaluates a strategy, reads a file or
writes a ledger. Historical indicators are confirmed input history, not saved
historical trading decisions. The caller holds the paper service snapshot lock.
"""
import math
from bisect import bisect_left, bisect_right
from datetime import date
from decimal import Decimal, InvalidOperation

from realtime_paper_rationale import SYMBOLS, project_holding_rationale

CONTRACT = 'd0-indicator-history-v1'
SOURCE = 'confirmed_input_history'
MAX_SOURCE_ROWS = 20000
LIMITS = {'weekly': 104, 'daily': 120}
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


def _number(value, field):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        return None
    if isinstance(value, str) and (not value or len(value) > 64):
        return None
    try:
        number = float(Decimal(str(value)))
    except (ValueError, InvalidOperation, OverflowError):
        return None
    if not math.isfinite(number) or abs(number) > 1e100:
        return None
    if field in ('k', 'd') and not 0 <= number <= 100:
        return None
    if field in ('value', 'ma', 'vol') and number < 0:
        return None
    return number


def unavailable(signal, reason='cache_unavailable', status='unavailable'):
    signal = _mapping(signal)
    return dict(contract_version=CONTRACT, source=SOURCE, signal_key=_text(signal.get('id')),
                confirmed_day=_day(signal.get('confirmed_day')), status=status, reason=reason, charts=[])


def _expectations(signal, symbol):
    """Describe only charts whose facts have a saved, date-validated endpoint."""
    asset = next(a for a in project_holding_rationale(signal)['assets'] if a['symbol'] == symbol)
    gate = asset['original_gate']; timing = gate['timing']; metrics = gate['metrics']
    day = _day(signal.get('confirmed_day'))
    if not day:
        raise ValueError('invalid signal date')
    charts = []
    if gate.get('kind') == 'excluded':
        return charts

    def add(key, frequency, unit, basis, fields, values, end, period_end=None):
        if not _day(end) or end > day or (frequency == 'weekly' and (not _day(period_end) or period_end > end)):
            raise LookupError('missing saved chart date')
        charts.append(dict(id=key, frequency=frequency, unit=unit, basis=basis, fields=fields,
                           values=dict(zip(fields, values)), date=end, period_end=period_end))

    if symbol == SYMBOLS[0]:
        if timing['indicator_status'] != 'confirmed' or timing['market_status'] != 'confirmed':
            raise LookupError('missing saved weekly group')
        add('skdj', 'weekly', 'indicator', 'confirmed_weekly_indicator', ('k', 'd'),
            (metrics['k'], metrics['d']), timing['available_on'], timing['period_end'])
        add('trix', 'weekly', 'percent_points', 'confirmed_weekly_indicator', ('trix', 'signal'),
            (metrics['trix_pct'], metrics['signal_pct']), timing['available_on'], timing['period_end'])
        add('trend', 'weekly', 'price', 'weekly_adjusted_close_ma50', ('value', 'ma'),
            (metrics['market_close'], metrics['market_ma']), timing['market_available_on'], timing['market_period_end'])
    elif symbol == SYMBOLS[1]:
        if timing['indicator_status'] != 'confirmed':
            raise LookupError('missing saved bank date')
        add('skdj', 'daily', 'indicator', 'daily_indicator', ('k', 'd'),
            (metrics['k'], metrics['d']), timing['state_day'])
    elif gate.get('kind') == 'bond_weekly':
        if timing['indicator_status'] != 'confirmed':
            raise LookupError('missing saved weekly bond date')
        add('trend', 'weekly', 'index_points', 'total_return_weekly_ma60', ('value', 'ma'),
            (metrics['value'], metrics['ma']), timing['available_on'], timing['period_end'])
        return charts
    else:
        if timing['indicator_status'] != 'confirmed':
            raise LookupError('missing saved defense date')
        window = 120 if symbol == SYMBOLS[2] else 60
        if metrics['ma_window'] != window:
            raise LookupError('different saved moving average')
        add('trend', 'daily', 'index_points', 'total_return_ma' + str(window), ('value', 'ma'),
            (metrics['value'], metrics['ma']), timing['period_end'])
    dynamic = _mapping(signal['dynamic'] if 'dynamic' in signal else _mapping(signal.get('features')).get('dynamic'))
    detail = _mapping(dynamic.get(symbol))
    end = _day(detail.get('quote_date'))
    add('momentum', 'daily', 'ratio', 'dynamic_total_return', ('m20', 'm60'),
        (asset['momentum20'], asset['momentum60']), end)
    add('volatility', 'daily', 'ratio', 'dynamic_total_return', ('vol',), (asset['volatility20'],), end)
    return charts


def _same(actual, expected):
    if actual is None or expected is None:
        return actual is expected
    # JSON/Decimal projection can change representation, never indicator units.
    return math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12)


def project_indicator_history(history, saved_signal, symbol):
    """Sanitize the display contract and reject identity or endpoint mismatch.

    This is also the HTTP boundary for synthetic/custom paper sources. Unknown
    properties are discarded; each applicable chart must occur exactly once.
    """
    saved_signal = _mapping(saved_signal)
    try:
        if symbol not in SYMBOLS:
            raise ValueError('unsupported symbol')
        if not isinstance(history, dict):
            return unavailable(saved_signal)
        if (history.get('contract_version') != CONTRACT or history.get('source') != SOURCE
                or history.get('signal_key') != _text(saved_signal.get('id'))
                or history.get('confirmed_day') != _day(saved_signal.get('confirmed_day'))
                or not _text(saved_signal.get('id')) or not _day(saved_signal.get('confirmed_day'))):
            return unavailable(saved_signal, 'signal_mismatch', 'invalid')
        status = history.get('status')
        if status in ('unavailable', 'invalid'):
            reason = history.get('reason')
            return unavailable(saved_signal, reason if reason in REASONS else 'invalid_history', status)
        if status != 'available' or history.get('reason') is not None:
            raise ValueError('invalid status')
        expected = _expectations(saved_signal, symbol)
        charts = history.get('charts')
        if not isinstance(charts, list) or len(charts) != len(expected):
            raise ValueError('invalid chart count')
        by_id = {}
        for chart in charts:
            if not isinstance(chart, dict) or not isinstance(chart.get('id'), str) or chart['id'] in by_id:
                raise ValueError('invalid or duplicate chart')
            by_id[chart['id']] = chart
        output = []
        for spec in expected:
            chart = by_id.get(spec['id'])
            if not chart or any(chart.get(k) != spec[k] for k in ('frequency', 'unit', 'basis')):
                raise ValueError('invalid chart metadata')
            rows = chart.get('points')
            if not isinstance(rows, list) or not 1 <= len(rows) <= LIMITS[spec['frequency']]:
                raise ValueError('invalid point count')
            points = []; previous = None; previous_period = None
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError('invalid point')
                day, available = _day(row.get('date')), _day(row.get('available_on'))
                if not day or day != available or day > saved_signal['confirmed_day'] or (previous and day <= previous):
                    raise ValueError('invalid point date')
                previous = day
                if not isinstance(row.get('values'), dict) or not isinstance(row.get('break_before'), bool):
                    raise ValueError('invalid point values')
                point = dict(date=day, available_on=available, values={
                    field: _number(row['values'].get(field), field) for field in spec['fields']},
                    break_before=row['break_before'])
                if spec['frequency'] == 'weekly':
                    period = _day(row.get('period_end'))
                    if not period or period > available or (previous_period and period <= previous_period):
                        raise ValueError('invalid weekly period')
                    previous_period = period
                    point['period_end'] = period
                points.append(point)
            last = points[-1]
            if (last['date'] != spec['date'] or last.get('period_end') != spec['period_end']
                    or any(not _same(last['values'][field], spec['values'][field]) for field in spec['fields'])):
                return unavailable(saved_signal, 'series_mismatch')
            output.append({key: spec[key] for key in ('id', 'frequency', 'unit', 'basis')} | {'points': points})
        return unavailable(saved_signal) | dict(status='available', reason=None, charts=output)
    except LookupError:
        return unavailable(saved_signal, 'series_mismatch')
    except (TypeError, ValueError, OverflowError, AttributeError, ArithmeticError):
        return unavailable(saved_signal, 'invalid_history', 'invalid')


def _dated_rows(mapping, day, *, weekly=False, quoted=False):
    if not isinstance(mapping, dict) or len(mapping) > MAX_SOURCE_ROWS:
        raise ValueError('invalid cache series')
    rows = []
    for key, row in mapping.items():
        if not _day(key) or not isinstance(row, dict):
            raise ValueError('invalid cache row')
        if key > day:
            continue
        if weekly and (row.get('available') != key or not _day(row.get('week_end')) or row['week_end'] > key):
            raise ValueError('invalid weekly cache date')
        if quoted and row.get('quote_date') != key:
            raise ValueError('invalid daily cache date')
        rows.append((key, row))
    return sorted(rows)


def extract_indicator_histories(saved_signal, cached_signal, signal_key, market):
    """Extract cached scalar series only; never invoke any method on market."""
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
    legacy = getattr(market, 'signals', None)
    staged, dynamic = getattr(legacy, 'staged', None), getattr(legacy, 'dynamic', None)
    if legacy is None or staged is None or dynamic is None:
        return all_unavailable()
    sessions = getattr(market, 'dates', None)
    if (not isinstance(sessions, list) or len(sessions) > MAX_SOURCE_ROWS
            or any(not _day(value) for value in sessions) or sessions != sorted(set(sessions))):
        return all_unavailable('invalid_history', 'invalid')
    results = {}
    for symbol in SYMBOLS:
        try:
            specs = _expectations(saved_signal, symbol)
            if symbol == SYMBOLS[0]:
                primary = _dated_rows(getattr(staged, 'weekly', None), day, weekly=True)
                trend = _dated_rows(getattr(staged, 'weekly50', None), day, weekly=True)
            elif symbol == SYMBOLS[1]:
                index, features = getattr(legacy, 'bank_index', None), getattr(legacy, 'bank_features', None)
                if not isinstance(index, dict) or len(index) > MAX_SOURCE_ROWS or not isinstance(features, list) or len(features) > MAX_SOURCE_ROWS:
                    raise ValueError('invalid bank cache')
                primary = []; seen = set()
                for key, ix in index.items():
                    if not _day(key) or isinstance(ix, bool) or not isinstance(ix, int) or not 0 <= ix < len(features) or ix in seen:
                        raise ValueError('invalid bank cache index')
                    seen.add(ix)
                    if key <= day:
                        if not isinstance(features[ix], dict):
                            raise ValueError('invalid bank feature')
                        primary.append((key, features[ix]))
                primary.sort()
                trend = []
            elif symbol == SYMBOLS[3] and saved_signal.get('strategy') == 'D0I-BOND-WW':
                primary = []
                weekly_cache = _mapping(getattr(market, '_d0i_ww_weekly_cache', None))
                feature_rows = weekly_cache.get('features')
                if not isinstance(feature_rows, list) or len(feature_rows) > MAX_SOURCE_ROWS:
                    raise ValueError('invalid weekly bond cache')
                trend = [(row['available'], dict(value=row['value'], ma=row['sma60weeks'], week_end=row['week_end']))
                         for row in feature_rows if row['available'] <= day]
            else:
                primary = []
                trend = _dated_rows(_mapping(getattr(staged, 'defense', None)).get(symbol), day, quoted=True)
            stats = _dated_rows(_mapping(getattr(dynamic, 'stats', None)).get(symbol), day, quoted=True)
            charts = []
            for spec in specs:
                key = spec['id']
                rows = stats if key in ('momentum', 'volatility') else trend if key == 'trend' else primary
                source_fields = {'skdj': ('k', 'd'), 'trix': ('trix', 'signal'),
                    'trend': ('close' if symbol == SYMBOLS[0] else 'value', 'ma'),
                    'momentum': ('momentum20', 'momentum60'), 'volatility': ('volatility20',)}[key]
                points = []; previous_day = None
                for point_day, row in rows[-LIMITS[spec['frequency']]:]:
                    # A known market session missing from this asset's cache
                    # (e.g. a recorded suspension) must not be bridged. Normal
                    # weekends/holidays have no session in this cached calendar.
                    gap = bool(spec['frequency'] == 'daily' and previous_day
                               and bisect_right(sessions, previous_day) < bisect_left(sessions, point_day))
                    point = dict(date=point_day, available_on=point_day, values={
                        field: _number(row.get(source_field), field) for field, source_field in zip(spec['fields'], source_fields)},
                        break_before=gap)
                    if spec['frequency'] == 'weekly':
                        point['period_end'] = row['week_end']
                    points.append(point)
                    previous_day = point_day
                charts.append({key: spec[key] for key in ('id', 'frequency', 'unit', 'basis')} | {'points': points})
            raw = unavailable(saved_signal) | dict(status='available', reason=None, charts=charts)
            results[symbol] = project_indicator_history(raw, saved_signal, symbol)
        except LookupError:
            results[symbol] = unavailable(saved_signal, 'series_mismatch')
        except (TypeError, ValueError, OverflowError, AttributeError, ArithmeticError):
            results[symbol] = unavailable(saved_signal, 'invalid_history', 'invalid')
    return results
