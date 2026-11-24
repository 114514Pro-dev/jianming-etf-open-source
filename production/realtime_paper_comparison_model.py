"""Isolated native D0 reference replay and a frozen-signal live valuation.

Only disposable reference databases are written. The caller supplies an already
accepted market; this module neither loads a user's account nor fetches data.
Today's quote may value yesterday's plan, but never becomes a new close signal.
"""
from copy import deepcopy
from datetime import date, datetime, time, timezone, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import json
import hashlib
import math
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace

import trade_book as native
from suite_book import SuiteBook
from realtime_paper_engine import TradingCalendar


TZ = timezone(timedelta(hours=8))
METHOD = 'native_d0_bank_ma50_k50_next_open'
WW_STRATEGY = 'D0I-BOND-WW'
WW_METHOD = 'native_d0i_bond_ww_next_open'
MAX_DAYS = 5000
FEES = {'commission': native.RATE, 'minimum_commission': 5, 'slippage': native.SLIP}


def model_identity(strategy='D0'):
    """A reference's public identity is independent of its execution adapter."""
    if strategy == 'D0':
        return dict(strategy='D0', method=METHOD, model_label='D0模型组合')
    if strategy != WW_STRATEGY:
        raise ValueError('unsupported reference strategy')
    from d0i_bond_ww import spec
    specification = spec()
    fingerprint = hashlib.sha256(json.dumps(specification, sort_keys=True, ensure_ascii=False,
        separators=(',', ':')).encode('utf-8')).hexdigest()
    return dict(strategy=strategy, method=WW_METHOD,
                model_label='D0I-BOND-WW 周线择债模型', spec_hash=fingerprint)


def reference_matches(reference, strategy='D0'):
    """Never value or publish an original-D0 reference under the WW label."""
    identity = model_identity(strategy)
    if reference.get('method') != identity['method']:
        return False
    if strategy == 'D0':
        return reference.get('strategy', 'D0') == 'D0'
    return (reference.get('strategy') == strategy
            and reference.get('spec_hash') == identity['spec_hash'])


def _money(value):
    if isinstance(value, bool):
        raise ValueError('invalid amount')
    try:
        value = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError('invalid amount') from None
    if not value.is_finite() or abs(value) > Decimal('1e12'):
        raise ValueError('invalid amount')
    return format(value.quantize(Decimal('.01'), rounding=ROUND_HALF_UP), '.2f')


def _day(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError('invalid day')
    if date.fromisoformat(value).isoformat() != value:
        raise ValueError('invalid day')
    return value


def _stamp(value):
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('timestamp timezone required')
    return parsed.astimezone(TZ)


def _positive(value):
    if isinstance(value, bool):
        raise ValueError('invalid quote price')
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError('invalid quote price') from None
    if not math.isfinite(number) or not 0 < number <= 1e12:
        raise ValueError('invalid quote price')
    return number


def _cancelled(stop):
    return bool(stop is not None and stop.is_set())


def _temporary(directory):
    # Always create a new child and let TemporaryDirectory remove only that
    # generated child. An existing native or paper account folder is never used.
    if directory is None:
        return tempfile.TemporaryDirectory(prefix='d0-reference-')
    parent = Path(directory)
    if parent.is_symlink():
        raise ValueError('reference directory must not be a symlink')
    parent.mkdir(parents=True, exist_ok=True)
    return tempfile.TemporaryDirectory(prefix='d0-reference-', dir=parent)


class _MarketView:
    """Protect cached market values from mutations by the native book."""
    provisional = False

    def __init__(self, market, strategy='D0'):
        self._market = market
        self.strategy = strategy
        self.dates = list(market.dates)
        self.latest = market.latest
        self.hash = market.hash
        # The book reads only these inputs. Copy them rather than retaining a
        # writable reference to the accepted market's corporate-action cache.
        self.inputs = SimpleNamespace(actions=deepcopy(market.inputs.actions),
                                      splits=deepcopy(market.inputs.splits))

    def at(self, day, opening=False):
        return deepcopy(self._market.at(day, opening))

    def observation(self, code, day):
        if self.strategy == WW_STRATEGY:
            if code != 'D0':
                raise ValueError('unexpected native reference adapter strategy')
            from d0i_bond_ww import observation
            result = deepcopy(observation(self._market, day))
            # Only this disposable SuiteBook uses D0 as the execution mode.
            # Public results retain the WW code, specification and method.
            result['strategy'] = 'D0'
            return result
        return deepcopy(self._market.observation(code, day))


def replay_reference(market, anchor_day, end_day, capital, *, directory=None, stop=None, strategy='D0'):
    """Start with cash at an accepted close, then use native next-open D0 rules."""
    result = dict(status='unavailable', reason='invalid_inputs', points=[], state=None,
                  method=METHOD, fees=deepcopy(FEES), source_cutoff=None)
    try:
        result.update(model_identity(strategy))
        anchor_day, end_day = _day(anchor_day), _day(end_day)
        amount = Decimal(_money(capital))
        raw_amount = Decimal(str(capital))
        if raw_amount < 1000:
            result['reason'] = 'capital_below_model_minimum'
            return result
        if raw_amount > Decimal('1e9'):
            return result
        view = _MarketView(market, strategy)
        dates = view.dates
        if (len(dates) > 50000 or dates != sorted(set(dates))
                or any(_day(day) != day for day in dates)
                or anchor_day not in dates or end_day not in dates
                or not anchor_day <= end_day <= _day(view.latest)):
            return result
        days = [day for day in dates if anchor_day <= day <= end_day]
        if len(days) > MAX_DAYS:
            result['reason'] = 'range_too_large'
            return result
        if _cancelled(stop):
            result['reason'] = 'cancelled'
            return result
        # Signals lazily install staged/dynamic caches on their Market. Keep
        # that initialization private as well as copying observation results.
        # This copy happens once per confirmed replay, never per live quote.
        view = _MarketView(deepcopy(market), strategy)
        with _temporary(directory) as folder:
            book = SuiteBook(folder=folder)
            state = book.create(result['model_label'], float(amount), anchor_day, view, strategy='D0')
            # The anchor is cash. This close creates the first pending target;
            # no trade is backdated to the anchor day's open.
            stale_by_day = {}
            for day in days:
                if _cancelled(stop):
                    result['reason'] = 'cancelled'
                    return result
                state = book.advance(state['id'], view, day)
                if _cancelled(stop):
                    result['reason'] = 'cancelled'
                    return result
                quote = view.at(day)
                stale_by_day[day] = [symbol for symbol in native.CODES
                                     if state['positions'][symbol]['qty'] and quote['dates'].get(symbol) != day]
            points = []
            previous_stale = False
            for point in state['curve']:
                day = _day(point['day'])
                if not anchor_day <= day <= end_day:
                    raise ValueError('unexpected curve date')
                # Native valuation can carry a suspended asset's previous
                # close. Preserve that fact instead of joining a fresh line.
                stale = stale_by_day[day]
                points.append(dict(date=day, at=day+'T15:00:00+08:00', equity=_money(point['equity']),
                                   break_before=bool(stale or previous_stale), stale_assets=stale))
                previous_stale = bool(stale)
            if ([point['date'] for point in points] != days or not points
                    or points[0]['equity'] != _money(amount)):
                raise ValueError('incomplete reference curve')
            result.update(status='available', reason=None, points=points,
                          state=deepcopy(state), source_cutoff=end_day)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, OSError, sqlite3.Error):
        result.update(status='unavailable', reason='model_replay_unavailable', points=[], state=None)
    return result


class _LiveMarketView(_MarketView):
    def __init__(self, market, day, quotes, strategy='D0'):
        super().__init__(market, strategy)
        self.day, self.quotes = day, deepcopy(quotes)
        self.dates.append(day)
        self.latest = day

    def at(self, day, opening=False):
        if day != self.day:
            return super().at(day, opening)
        return dict(day=day, market_hash=self.hash,
                    prices={symbol: self.quotes.get(symbol, {}).get('open' if opening else 'price')
                            for symbol in native.CODES},
                    dates={symbol: day if symbol in self.quotes else None for symbol in native.CODES})

    def observation(self, code, day):
        if day == self.day:
            raise ValueError('unconfirmed day must never generate a signal')
        return super().observation(code, day)


class _FrozenSignalBook(SuiteBook):
    def __init__(self, folder, frozen_day):
        self._frozen_day = frozen_day
        super().__init__(folder=folder)

    def evaluate(self, con, state, market):
        if state['day'] != self._frozen_day:
            return super().evaluate(con, state, market)


def estimate_reference_live(reference, market, batch, *, now, directory=None, strategy='D0'):
    """Execute only the previous confirmed target at today's observed open.

    This returns one temporary valuation, never a newly confirmed model curve
    or a user-account order. Quote timestamps remain provider timestamps.
    """
    result = dict(status='unavailable', reason='invalid_reference', equity=None, at=None,
                  quote_at=None, latest_quote_at=None, phase='intraday_estimate',
                  cash_only=False, fees=deepcopy(FEES))
    try:
        result.update(model_identity(strategy))
        moment = _stamp(now)
        today = moment.date().isoformat()
        state = deepcopy(reference['state'])
        calendar = TradingCalendar()
        if (reference.get('status') != 'available' or not reference_matches(reference, strategy)
                or reference.get('source_cutoff') != market.latest or state['day'] != market.latest
                or not state['day'] < today or state['auto'].get('strategy') != 'D0'
                or state['auto'].get('evaluated') != state['day']):
            return result
        if (calendar.is_session(today) is not True
                or calendar.next_session(state['day']) != moment.date()):
            result['reason'] = 'calendar_unavailable'
            return result
        pending = state.get('pending')
        if pending and _day(pending['day']) > state['day']:
            return result
        weights = pending['weights'] if pending else dict.fromkeys(native.CODES, 0.)
        relevant = [symbol for symbol in native.CODES
                    if state['positions'][symbol]['qty'] > 0 or weights[symbol] > 0]
        quotes, stamps = {}, []
        if relevant:
            if not isinstance(batch, dict) or not isinstance(batch.get('source'), str) or not batch['source']:
                result['reason'] = 'quotes_unavailable'
                return result
            received = _stamp(batch['received_at'])
            if not 0 <= (moment-received).total_seconds() <= 60:
                result['reason'] = 'quotes_stale'
                return result
            for symbol in relevant:
                raw = batch['quotes'][symbol]
                stamp = _stamp(raw['quote_at'])
                clock = stamp.timetz().replace(tzinfo=None)
                if (raw.get('symbol') != symbol or raw.get('day') != today or stamp.date() != moment.date()
                        or raw.get('started') is not True or not stamp <= received <= moment
                        or not 0 <= (moment-stamp).total_seconds() <= 60
                        or not (time(9, 30) <= clock <= time(11, 30) or time(13) <= clock <= time(15))):
                    result['reason'] = 'quotes_invalid'
                    return result
                quotes[symbol] = dict(price=_positive(raw['price']), open=_positive(raw['open']))
                if raw.get('high') is not None or raw.get('low') is not None:
                    high, low = _positive(raw['high']), _positive(raw['low'])
                    if not low <= min(quotes[symbol].values()) <= max(quotes[symbol].values()) <= high:
                        result['reason'] = 'quotes_invalid'
                        return result
                _positive(raw['previous_close'])
                stamps.append(stamp)
        else:
            received = moment
            result['cash_only'] = True
        view = _LiveMarketView(market, today, quotes, strategy)
        with _temporary(directory) as folder:
            book = _FrozenSignalBook(folder, today)
            with book.connection() as con:
                con.execute('INSERT INTO accounts VALUES (?,?,?,?)',
                            (state['id'], state['name'], state['revision'], json.dumps(state, allow_nan=False)))
            live = book.advance(state['id'], view, today)
            if live['auto']['evaluated'] != state['day']:
                raise ValueError('today generated a close signal')
            equity = native.value(live, view.at(today))['equity']
            result.update(status='available', reason=None, equity=_money(equity),
                          at=received.isoformat(), quote_at=min(stamps).isoformat() if stamps else None,
                          latest_quote_at=max(stamps).isoformat() if stamps else None)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, OSError, sqlite3.Error):
        result.update(status='unavailable', reason='live_model_unavailable', equity=None, at=None,
                      quote_at=None, latest_quote_at=None)
    return result
