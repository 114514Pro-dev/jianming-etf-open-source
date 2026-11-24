"""Read-only, asynchronous account / actual-index / native-D0 comparison.

The public cache is a derived view.  Capturing a ledger never advances its
source, and no native reference state or transaction evidence is published.
All four series share the account's first valid confirmed close in each
capital segment; later observations retain their own source timestamps.
"""
from collections import OrderedDict
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from functools import partial
import hashlib
import json
import math
import os
from pathlib import Path
import threading
from urllib.request import Request, urlopen

from realtime_paper_comparison_history import reconstruct_account_history
from realtime_paper_comparison_indices import fetch_index_quote
from realtime_paper_comparison_model import (replay_reference, estimate_reference_live,
    model_identity, reference_matches, WW_STRATEGY, METHOD)
from realtime_paper_engine import PaperLedger, TradingCalendar
from realtime_paper_comparison_quotes import DisplayQuoteResolver, source_ready
from realtime_paper_comparison_tail import retain_intraday
from realtime_paper_rationale import SYMBOLS

TZ = timezone(timedelta(hours=8))
CONTRACT = 'd0-performance-comparison-v1'
MAX_POINTS = 5000
INDEX_LINES = {'sh000001': 'market', 'sz399006': 'chinext'}
METHODS = {'account': 'reconstructed_trades_unadjusted_close',
           'market': 'price_index_close', 'chinext': 'price_index_close',
           'd0': METHOD}
BASE_NOTES = ['account_reconstructed_from_fills', 'index_price_excludes_dividends',
              'model_native_fees', 'gaps_not_filled', 'independent_live_times']


def _stamp(value):
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and 19 <= len(value) <= 40:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    else:
        raise ValueError('invalid timestamp')
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError('timezone required')
    return parsed.astimezone(TZ)


def _number(value, *, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError('invalid amount')
    if isinstance(value, str) and len(value) > 80:
        raise ValueError('oversized amount')
    number = Decimal(str(value))
    if not number.is_finite() or number < 0 or number > Decimal('1e20') or (positive and not number):
        raise ValueError('invalid amount')
    return number


def _money(value):
    with localcontext() as context:
        context.prec = 60
        return format(_number(value).quantize(Decimal('.01'), rounding=ROUND_HALF_UP), '.2f')


def _fingerprint(raw):
    """Business evidence only: quotes, view revision and quote marks are absent."""
    account = raw.get('account')
    value = dict(account=None if account is None else {
        key: account.get(key) for key in ('id', 'strategy', 'created_at', 'initial_capital', 'cash')},
        positions=[{key: row.get(key) for key in ('symbol', 'qty')}
                   for row in raw.get('positions', [])],
        signal=raw.get('signal'),
        fills=raw.get('fills', []),
        orders=[order if order.get('status') == 'filled' or order.get('fill_id') is not None
                else {key: order.get(key) for key in ('id', 'status', 'fill_id')}
                for order in raw.get('orders', [])],
        events=[event if event.get('type') in ('created', 'capital_changed', 'started', 'estimated_fill')
                else {key: event.get(key) for key in ('id', 'type', 'at')}
                for event in raw.get('events', [])])
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode('utf-8')).hexdigest()


def _empty(raw, now, status='waiting', reason='comparison_not_ready'):
    account = raw.get('account') if isinstance(raw, dict) else None
    account = account if isinstance(account, dict) else {}
    strategy = account.get('strategy', 'D0')
    identity = model_identity(strategy if strategy in ('D0', WW_STRATEGY) else 'D0')
    methods = {**METHODS, 'd0': identity['method']}
    return dict(contract_version=CONTRACT, status=status, reason=reason,
                strategy=identity['strategy'], model_strategy=identity['strategy'],
                model_label=identity['model_label'],
                account_id=account.get('id'), account_created_at=account.get('created_at'),
                generated_at=now.isoformat(), requested_start_at=None,
                normalization='first_shared_confirmed_close', segments=[],
                series=[dict(id=key, status='unavailable', reason=reason,
                             method=method, as_of=None, points=[])
                        for key, method in methods.items()], notes=list(BASE_NOTES))


def _point(segment, at, equity, phase, *, source_at=None, observed_at=None, break_before=False,
           cash_only=False):
    stamp = _stamp(at)
    amount, ratio = None, None
    if equity is not None:
        amount = _money(equity)
        with localcontext() as context:
            context.prec = 60
            ratio = float(Decimal(amount) / _number(segment['baseline_equity'], positive=True) - 1)
        if not math.isfinite(ratio):
            raise ValueError('invalid ratio')
    return dict(key=segment['id'] + ':' + phase + ':' + stamp.isoformat(),
                at=stamp.isoformat(), date=stamp.date().isoformat(), segment_id=segment['id'],
                equity=amount, return_ratio=ratio, phase=phase,
                source_at=_stamp(source_at).isoformat() if source_at else None,
                observed_at=_stamp(observed_at).isoformat() if observed_at else None,
                cash_only=bool(cash_only is True and source_at is None and phase == 'intraday_estimate'),
                break_before=bool(break_before or amount is None))


def _append(line, point):
    previous = line['points'][-1] if line['points'] else None
    point['break_before'] = bool(point['break_before'] or previous is None
                                 or previous['equity'] is None
                                 or previous['segment_id'] != point['segment_id'])
    line['points'].append(point)
    if point['equity'] is not None:
        line.update(status='available', reason=None,
                    as_of=point['source_at'] or point['at'])


def _index_bars(snapshot, symbol, now):
    """Consume an audited cache defensively without repairing missing days."""
    if not isinstance(snapshot, dict):
        raise ValueError('invalid index cache')
    if snapshot.get('symbol', symbol) != symbol or snapshot.get('price_basis', 'index_price') != 'index_price':
        raise ValueError('invalid index identity')
    through = snapshot.get('confirmed_through')
    if not isinstance(through, str):
        raise ValueError('missing index cutoff')
    result, previous = {}, None
    rows = snapshot.get('bars')
    if not isinstance(rows, list) or len(rows) > 100000:
        raise ValueError('invalid index rows')
    sessions = snapshot.get('sessions')
    if not isinstance(sessions, list) or sessions != sorted(set(sessions)):
        raise ValueError('invalid index sessions')
    for row in rows:
        day = row['date']
        closed_at = _stamp(day + 'T15:00:00+08:00')
        if previous is not None and day <= previous:
            raise ValueError('duplicate index day')
        previous = day
        if day in sessions and day <= through and closed_at <= now:
            result[day] = _number(row['close'], positive=True)
    return result


def _anchor(segment):
    starts, ends = segment['starts_at'], segment['ends_at']
    if starts is None or (ends is not None and _stamp(ends) <= _stamp(starts)):
        return None
    first = next((p for p in segment['points'] if p['equity'] is not None
                  and _stamp(p['at']) >= _stamp(starts)
                  and (ends is None or _stamp(p['at']) < _stamp(ends))), None)
    # A legitimately exhausted account cannot supply a percentage denominator.
    return first if first is not None and _number(first['equity']) > 0 else None


def project_comparison(raw, history, indices, references, *, now):
    """Pure projection of verified evidence; references' private state is ignored."""
    result = _empty(raw, now, history['status'], history.get('reason'))
    result.update(account_id=history.get('account_id'), account_created_at=history.get('created_at'),
                  requested_start_at=history.get('first_started_at'))
    if history['status'] != 'available':
        return result
    lines = {line['id']: line for line in result['series']}
    for line in lines.values():
        line['reason'] = 'waiting_first_confirmed_close'
    for source_segment in history['segments']:
        starts, ends = source_segment['starts_at'], source_segment['ends_at']
        if starts is None or (ends is not None and _stamp(ends) <= _stamp(starts)):
            continue
        anchor = _anchor(source_segment)
        segment = dict(id=source_segment['id'], starts_at=starts, ends_at=ends,
                       baseline_at=anchor['at'] if anchor else None,
                       baseline_equity=_money(anchor['equity']) if anchor else None,
                       capital=source_segment['capital'])
        result['segments'].append(segment)
        if anchor is None:
            if any(p['equity'] is not None and _number(p['equity']) == 0
                   for p in source_segment['points']):
                result['notes'].append('zero_baseline')
            continue
        if _stamp(starts).date() == _stamp(anchor['at']).date() and _stamp(starts).hour >= 15:
            result['notes'].append('first_partial_day_excluded')
        elif _stamp(starts).date() < _stamp(anchor['at']).date():
            result['notes'].append('first_partial_day_excluded')
        points = [p for p in source_segment['points'] if p['at'] >= anchor['at']]
        for p in points:
            _append(lines['account'], _point(segment, p['at'], p['equity'], 'reconstructed_close',
                                           source_at=p['at'], break_before=p['break_before']))
        for symbol, name in INDEX_LINES.items():
            bars = indices.get(symbol, {})
            base = bars.get(anchor['date'])
            if base is None:
                result['notes'].append('index_segments_unavailable')
                if lines[name]['status'] != 'available':
                    lines[name]['reason'] = 'index_anchor_missing'
                continue
            for p in points:
                price = bars.get(p['date'])
                with localcontext() as context:
                    context.prec = 60
                    amount = None if price is None else Decimal(segment['baseline_equity']) * price / base
                _append(lines[name], _point(segment, p['at'], amount, 'index_close',
                                           source_at=p['at'] if price is not None else None,
                                           break_before=p['date'] == anchor['date']))
        reference = references.get(segment['id'], {})
        if (reference.get('status') != 'available'
                or not reference_matches(reference, result['strategy'])):
            result['notes'].append('model_segments_unavailable')
            if lines['d0']['status'] != 'available':
                lines['d0']['reason'] = 'model_unavailable'
            continue
        model_days = {p['date']: p for p in reference.get('points', [])}
        for p in points:
            native = model_days.get(p['date'], {})
            amount = None if native.get('stale_assets') else native.get('equity')
            _append(lines['d0'], _point(segment, p['at'], amount, 'model_close',
                                       source_at=p['at'] if amount is not None else None,
                                       break_before=bool(native.get('break_before'))))
    if any(s['baseline_at'] for s in result['segments']):
        result.update(status='available', reason=None)
    else:
        result.update(status='unavailable' if 'zero_baseline' in result['notes'] else 'waiting',
                      reason='zero_baseline' if 'zero_baseline' in result['notes'] else 'waiting_first_confirmed_close')
        if result['reason'] == 'zero_baseline':
            for line in lines.values():
                line['reason'] = 'zero_baseline'
    if any(s['baseline_at'] is None for s in result['segments']):
        result['notes'].append('segments_waiting')
    result['notes'] = list(dict.fromkeys(result['notes']))
    return result


def _fresh(source, received, now):
    source, received = _stamp(source), _stamp(received)
    return (source.date() == now.date() == received.date()
            and 0 <= (now - source).total_seconds() <= 60
            and source <= received <= now
            and (now - received).total_seconds() <= 60)


def _accepted_quote_usable(raw, symbol, now):
    """Value accepted marks without reusing the five-second execution gate."""
    quote = raw.get('quotes', {}).get(symbol, {})
    if (quote.get('symbol') != symbol or quote.get('status') not in ('normal', 'unverified')
            or not isinstance(quote.get('source'), str) or not 1 <= len(quote['source']) <= 128
            or quote.get('corporate_unknown') is True):
        return False
    water = raw.get('status_watermarks', {}).get(symbol)
    if water is not None and water.get('status') not in ('normal', 'unverified'):
        return False
    if not _fresh(quote.get('quote_at'), quote.get('received_at'), now):
        return False
    calendar = TradingCalendar()
    segment = calendar.segment(now)
    return (segment is not None
            and calendar.segment(_stamp(quote['quote_at'])) == segment
            and calendar.segment(_stamp(quote['received_at'])) == segment)


def _accepted_repeat_batch(raw, now, *, symbols=None):
    """Only recover an aged, previously accepted batch for display valuation.

    Source readiness is a trading gate. Its accepted repeat can outlive the
    five-second queue limit, but source acceptance alone does not prove that
    the ledger accepted each quote. Keep only individually matched rows: the
    native estimator still requires every instrument it actually holds or
    targets, while an unrelated unaccepted quote cannot hide a valid mark.
    """
    if (raw.get('source_status') != 'waiting' or raw.get('reason') != 'quote_queue_delay'
            or raw.get('observation_state') != 'repeat'):
        return None
    try:
        batch = raw.get('market_observation')
        if not isinstance(batch, dict) or not isinstance(batch.get('quotes'), dict):
            return None
        rows = PaperLedger._raw_quotes(batch)
        if len(rows) != len(SYMBOLS) or {row.get('symbol') for row in rows} != set(SYMBOLS):
            return None
        matched = {}
        for row in rows:
            symbol = row['symbol']
            accepted = raw.get('quotes', {}).get(symbol, {})
            try:
                if (not _accepted_quote_usable(raw, symbol, now)
                        or PaperLedger._raw_status(row) != accepted['status']
                        or row.get('source') != accepted.get('source')
                        or _stamp(row.get('quote_at')) != _stamp(accepted['quote_at'])
                        or _stamp(row.get('received_at', batch.get('received_at')))
                            != _stamp(accepted['received_at'])
                        or not _fresh(row['quote_at'], batch.get('received_at'), now)):
                    continue
                if any(_number(row.get(field), positive=field in ('price', 'previous_close'))
                       != _number(accepted.get(field))
                       for field in ('price', 'previous_close', 'volume_lots', 'amount_cny')):
                    continue
            except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation, ArithmeticError):
                continue
            matched[symbol] = batch['quotes'][symbol]
        if not matched or (symbols is not None and not set(symbols).issubset(matched)):
            return None
        return {**deepcopy(batch), 'quotes': deepcopy(matched)}
    except (ValueError, TypeError, KeyError, AttributeError, InvalidOperation, ArithmeticError):
        return None


def _account_live(raw, now, *, display_batch=None):
    account = raw['account']
    cash = _number(account['cash'])
    held = [p for p in raw['positions'] if p['qty']]
    if (any(isinstance(p['qty'], bool) or not isinstance(p['qty'], int) or p['qty'] <= 0 for p in held)
            or len({p['symbol'] for p in held}) != len(held)):
        return None
    if not held:
        if _money(cash) != _money(account.get('equity')):
            return None
        return dict(equity=_money(cash), at=now.isoformat(), source_at=None,
                    observed_at=now.isoformat(), cash_only=True)
    status = account.get('valuation_status')
    if status not in ('current', 'stale'):
        return None
    if display_batch is not None and not source_ready(raw):
        return None
    if (status == 'stale' and display_batch is None
            and _accepted_repeat_batch(raw, now, symbols=[p['symbol'] for p in held]) is None):
        return None
    observed = raw.get('response_at')
    if TradingCalendar().segment(_stamp(observed)) != TradingCalendar().segment(now):
        return None
    stamps, receipts = [], []
    display = ({row['symbol']: row for row in PaperLedger._raw_quotes(display_batch)}
               if display_batch is not None else None)
    for p in held:
        if (p.get('valuation_status') not in ('current', 'stale')
                or (status == 'current' and p.get('valuation_status') != 'current')):
            return None
        accepted = raw.get('quotes', {}).get(p['symbol'], {})
        quote = accepted
        checked = raw
        if display is not None:
            if p['symbol'] not in display:
                return None
            quote = deepcopy(display.get(p['symbol'], {}))
            quote.setdefault('received_at', display_batch.get('received_at'))
            quote['status'] = PaperLedger._raw_status(quote)
            if (_number(quote.get('price'), positive=True) != _number(accepted.get('price'), positive=True)
                    or quote.get('source') != accepted.get('source')):
                return None
            checked = {**raw, 'quotes': {p['symbol']: quote}}
        if not _accepted_quote_usable(checked, p['symbol'], now):
            return None
        if (not _fresh(quote.get('quote_at'), observed, now)
                or _stamp(quote['received_at']) > _stamp(observed)):
            return None
        price = _number(quote.get('price'), positive=True)
        if price != _number(p.get('price'), positive=True):
            return None
        value = _money(price * p['qty'])
        if value != _money(p.get('market_value')):
            return None
        cash += Decimal(value)
        stamps.append(_stamp(quote['quote_at']))
        receipts.append(_stamp(quote['received_at']))
    if _money(cash) != _money(account.get('equity')):
        return None
    return dict(equity=_money(cash), at=_stamp(observed).isoformat(),
                source_at=min(stamps).isoformat(),
                observed_at=(max(receipts) if display is not None else _stamp(observed)).isoformat(),
                cash_only=False)


def _model_live_blocked(raw):
    """An old accepted market cannot authorize new trades during review."""
    reason = raw.get('reason')
    return isinstance(reason, str) and (
        reason.startswith('history_') or reason in {
            'historical_data_revision', 'corporate_action_review_required',
            'holdings_history_unverified', 'calendar_unavailable'})


def _bounded_request(url):
    """A separate, bounded index transport, never the trading-source request."""
    request = Request(url, headers={'User-Agent': 'Mozilla/5.0 D0Comparison'})
    with urlopen(request, timeout=5) as response:
        payload = response.read(1024 * 1024 + 1)
    if len(payload) > 1024 * 1024:
        raise ValueError('oversized index response')
    return payload


class D0ComparisonService:
    def __init__(self, folder, paper, indices, *, now=None, refresh_enabled=None, interval=30,
                 quote_fetcher=None, model_runner=None, live_model_runner=None, request=None, strategy='D0'):
        self.identity = model_identity(strategy)
        self.strategy = strategy
        self.folder = Path(folder)
        self.paper, self.indices, self.now = paper, indices, now
        self.interval = max(0.1, float(interval))
        self.quote_fetcher = quote_fetcher or fetch_index_quote
        self.model_runner = model_runner or partial(replay_reference, strategy=strategy)
        self.live_model_runner = live_model_runner or partial(estimate_reference_live, strategy=strategy)
        self.request = request or _bounded_request
        self.halt, self.wake = threading.Event(), threading.Event()
        self._cache_lock, self._refresh_lock = threading.Lock(), threading.Lock()
        self._cache, self._business_key = None, None
        self._models = OrderedDict()
        self._display_quotes = DisplayQuoteResolver(getattr(paper.source, 'home', self.folder))
        self._tail_identity = None
        if refresh_enabled is None:
            refresh_enabled = os.environ.get('ETF_WEB_INDEX_BENCHMARK_REFRESH',
                                            os.environ.get('ETF_WEB_BENCHMARK_REFRESH', '1')) == '1'
        self.refresh_enabled = bool(refresh_enabled)
        self.thread = None
        if self.refresh_enabled:
            self.thread = threading.Thread(target=self._worker, name='d0-performance-comparison', daemon=True)
            self.thread.start()

    def _now(self):
        value = self.now() if callable(self.now) else self.now
        return _stamp(value) if value is not None else datetime.now(TZ)

    def _capture(self):
        # A production source refresh can already own this lock. The derived
        # worker must remain stoppable while waiting for that unrelated work.
        lock = self.paper._lock
        while not lock.acquire(timeout=0.1):
            if self.halt.is_set():
                raise InterruptedError('comparison stopped')
        try:
            raw = deepcopy(self.paper.ledger.snapshot())
            raw.update(deepcopy(getattr(self.paper, '_source_state', {})))
            source = self.paper.source
            market = getattr(source, '_market', None)
            signal = deepcopy(getattr(source, '_signal', None))
            key = deepcopy(getattr(source, '_signal_key', None))
            batch = deepcopy(getattr(self.paper, '_last_batch', None))
            if batch is None:
                batch = _accepted_repeat_batch(raw, self._now())
        finally:
            lock.release()
        return raw, market, signal, key, batch

    def _publish(self, raw, result):
        result.update(strategy=self.strategy, model_strategy=self.strategy,
                      model_label=self.identity['model_label'])
        for line in result['series']:
            if line['id'] == 'd0':
                line.update(strategy=self.strategy, method=self.identity['method'],
                            label=self.identity['model_label'])
        result['generated_at'] = self._now().isoformat()
        for line in result['series']:
            if len(line['points']) > MAX_POINTS:
                # Retain every segment's first point; remove only later points
                # and break the visible interval where a close was omitted.
                excess = len(line['points']) - MAX_POINTS
                segments, kept, removed_previous = set(), [], False
                for point in line['points']:
                    first = point['segment_id'] not in segments
                    segments.add(point['segment_id'])
                    if excess and not first:
                        excess -= 1
                        removed_previous = True
                        continue
                    if removed_previous:
                        point['break_before'] = True
                        removed_previous = False
                    kept.append(point)
                line['points'] = kept
                last = next((p for p in reversed(kept) if p['equity'] is not None), None)
                line['as_of'] = (last['source_at'] or last['at']) if last else None
                if 'history_truncated' not in result['notes']:
                    result['notes'].append('history_truncated')
        try:
            business_key = _fingerprint(raw)
        except (ValueError, TypeError, KeyError, AttributeError):
            business_key = None
        with self._cache_lock:
            self._cache, self._business_key = deepcopy(result), business_key
        return deepcopy(result)

    def refresh(self, fetch_live=None):
        """Explicit/background refresh. No account lock is held during work or IO."""
        if fetch_live is None:
            fetch_live = self.refresh_enabled
        while not self._refresh_lock.acquire(timeout=0.1):
            if self.halt.is_set():
                raise InterruptedError('comparison stopped')
        try:
            raw, market, signal, key, batch = self._capture()
            now = self._now()
            if raw.get('account') is None:
                return self._publish(raw, _empty(raw, now, 'unavailable', 'account_not_created'))
            if raw['account'].get('strategy', 'D0') != self.strategy:
                return self._publish(raw, _empty(raw, now, 'unavailable', 'account_mismatch'))
            if market is None:
                return self._publish(raw, _empty(raw, now, 'waiting', 'market_cache_unavailable'))
            signal_map = signal if isinstance(signal, dict) else {}
            expected_key = ((market.latest, signal_map.get('history_hash'), self.strategy)
                            if self.strategy != 'D0'
                            else (market.latest, signal_map.get('history_hash')))
            if (not isinstance(signal, dict) or signal.get('confirmed_day') != market.latest
                    or signal.get('strategy', 'D0') != self.strategy or key != expected_key):
                return self._publish(raw, _empty(raw, now, 'waiting', 'signal_cache_mismatch'))
            saved_spec = (raw.get('signal') or {}).get('spec_hash')
            if saved_spec and signal.get('spec_hash') and saved_spec != signal['spec_hash']:
                return self._publish(raw, _empty(raw, now, 'waiting', 'spec_mismatch'))
            if self.strategy != 'D0' and signal.get('spec_hash') != self.identity['spec_hash']:
                return self._publish(raw, _empty(raw, now, 'waiting', 'spec_mismatch'))
            history = reconstruct_account_history(raw, market.look, market.dates, now=now)
            if history['status'] != 'available':
                return self._publish(raw, project_comparison(raw, history, {}, {}, now=now))
            index_bars = {}
            for symbol in INDEX_LINES:
                try:
                    index_bars[symbol] = _index_bars(self.indices.caches[symbol].read(), symbol, now)
                except Exception:
                    index_bars[symbol] = {}
            references = {}
            for segment in history['segments']:
                if self.halt.is_set():
                    break
                points = segment['points']
                anchor = _anchor(segment)
                if anchor is None:
                    continue
                cache_key = (self.strategy, market.hash, signal.get('spec_hash'), segment['id'],
                             anchor['date'], points[-1]['date'], anchor['equity'])
                reference = self._models.get(cache_key)
                if reference is None:
                    try:
                        reference = self.model_runner(market, anchor['date'], points[-1]['date'],
                                                      anchor['equity'], directory=None, stop=self.halt)
                    except Exception:
                        reference = {'status': 'unavailable', 'reason': 'model_unavailable'}
                    if not isinstance(reference, dict):
                        reference = {'status': 'unavailable', 'reason': 'model_unavailable'}
                    if (reference.get('status') == 'available'
                            and not reference_matches(reference, self.strategy)):
                        reference = {'status': 'unavailable', 'reason': 'model_identity_mismatch'}
                    # An interrupted result must be retried on a later refresh.
                    if not self.halt.is_set() and reference.get('status') == 'available':
                        self._models[cache_key] = reference
                        while len(self._models) > 16:
                            self._models.popitem(last=False)
                else:
                    self._models.move_to_end(cache_key)
                references[segment['id']] = reference
            result = project_comparison(raw, history, index_bars, references, now=now)
            identity = (self.strategy, _fingerprint(raw), market.hash, json.dumps(signal, sort_keys=True),
                        json.dumps(key, sort_keys=True), json.dumps(raw.get('signal'), sort_keys=True))
            if fetch_live and result['status'] == 'available' and not self.halt.is_set():
                self._live(result, raw, market, batch, references, index_bars)
                with self._cache_lock:
                    previous = deepcopy(self._cache)
                result = retain_intraday(result, previous, now=self._now(),
                                         same_identity=identity == self._tail_identity)
                for line in result['series']:
                    if line['points'] and line['points'][-1].get('retained') is True:
                        line['live_status'] = 'retained'
            self._tail_identity = identity
            return self._publish(raw, result)
        finally:
            self._refresh_lock.release()

    def _live(self, result, raw, market, batch, references, index_bars):
        segment = result['segments'][-1] if result['segments'] else None
        if not segment or not segment['baseline_at'] or segment['ends_at'] is not None:
            return
        lines = {line['id']: line for line in result['series']}
        # Resolve complete raw observations outside the paper lock. A silent
        # quote is display evidence only; the ledger and trading batch stay as-is.
        verified = self._display_quotes.resolve(raw, now=self._now()) if 'market_observation' in raw else None
        if 'market_observation' in raw:
            batch = verified
        unavailable_reason = ('market_closed' if TradingCalendar().segment(self._now()) is None
                              else 'source_unavailable' if not source_ready(raw)
                              else 'quote_not_verified')
        for name in ('account', 'd0'):
            lines[name].update(live_status='unavailable', live_reason=unavailable_reason)

        def append(name, live):
            if not live:
                return False
            point = _point(segment, live['at'], live['equity'], 'intraday_estimate',
                           source_at=live.get('source_at'), observed_at=live.get('observed_at'),
                           cash_only=name in ('account', 'd0') and live.get('cash_only') is True)
            previous = lines[name]['points'][-1] if lines[name]['points'] else None
            if (lines[name]['status'] != 'available' or previous is None
                    or previous['segment_id'] != segment['id']
                    or _stamp(point['at']) <= _stamp(previous['at'])
                    or (point['source_at'] is not None
                        and _stamp(point['source_at']) <= _stamp(previous['at']))
                    or _stamp(point['at']) < _stamp(segment['baseline_at'])):
                return False
            _append(lines[name], point)
            if name in ('account', 'd0'):
                lines[name].update(live_status='available', live_reason=None)
            return True

        try:
            if ('market_observation' not in raw or verified is not None
                    or not any(p.get('qty') for p in raw.get('positions', []))):
                append('account', _account_live(raw, self._now(), display_batch=verified))
        except (ValueError, TypeError, KeyError, InvalidOperation, ArithmeticError):
            pass
        reference = references.get(segment['id'])
        if (reference and reference.get('status') == 'available'
                and reference_matches(reference, self.strategy)
                and not self.halt.is_set() and not _model_live_blocked(raw)):
            try:
                live = self.live_model_runner(reference, market, batch, now=self._now(), directory=None)
                if live.get('status') != 'available' and unavailable_reason == 'quote_not_verified':
                    lines['d0']['live_reason'] = (live.get('reason') if live.get('reason') in {
                        'quotes_stale', 'quotes_unavailable', 'quotes_invalid', 'invalid_reference',
                        'calendar_unavailable', 'live_model_unavailable'} else 'model_unavailable')
                current = self._now()
                source, received = live.get('quote_at'), live.get('at')
                if (live.get('status') == 'available' and _stamp(received) <= current
                        and _stamp(received).date() == current.date()
                        and (current - _stamp(received)).total_seconds() <= 60
                        and (source is None or _fresh(source, received, current))):
                    latest = live.get('latest_quote_at')
                    if latest is None or (_fresh(latest, received, current)
                                          and (source is None or _stamp(source) <= _stamp(latest))):
                        append('d0', dict(at=received, equity=live['equity'],
                                          source_at=source, observed_at=received,
                                          cash_only=live.get('cash_only') is True))
            except Exception:
                lines['d0']['live_reason'] = 'model_unavailable'
                pass
        for symbol, name in INDEX_LINES.items():
            if self.halt.is_set():
                break
            base = index_bars.get(symbol, {}).get(segment['baseline_at'][:10])
            if base is None:
                continue
            try:
                quote = self.quote_fetcher(symbol, request=self.request)
                current = self._now()  # Receipt belongs to the completed request.
                if (quote.get('symbol') != symbol or quote.get('instrument_type') != 'ZS'
                        or not _fresh(quote.get('quote_at'), quote.get('received_at'), current)):
                    continue
                with localcontext() as context:
                    context.prec = 60
                    equity = Decimal(segment['baseline_equity']) * _number(quote['price'], positive=True) / base
                append(name, dict(at=quote['received_at'], equity=equity,
                                  source_at=quote['quote_at'], observed_at=quote['received_at']))
            except Exception:
                continue

    def snapshot(self, account_id):
        """A fast cache read with a fresh account-evidence check; never does IO."""
        with self.paper._lock:
            raw = deepcopy(self.paper.ledger.snapshot())
        now = self._now()
        actual_id = (raw.get('account') or {}).get('id')
        if actual_id != account_id or (raw.get('account') or {}).get('strategy', 'D0') != self.strategy:
            result = _empty({}, now, 'unavailable', 'account_mismatch')
            result.update(strategy=self.strategy, model_strategy=self.strategy,
                          model_label=self.identity['model_label'])
            for line in result['series']:
                if line['id'] == 'd0':
                    line.update(method=self.identity['method'], strategy=self.strategy,
                                label=self.identity['model_label'])
            return result
        try:
            business_key = _fingerprint(raw)
        except (ValueError, TypeError, KeyError, AttributeError):
            business_key = None
        with self._cache_lock:
            if self._cache is not None and business_key is not None and business_key == self._business_key:
                return deepcopy(self._cache)
            cached = self._cache is not None
        self.wake.set()
        result = _empty(raw, now, 'waiting', 'account_changed' if cached else 'comparison_not_ready')
        for line in result['series']:
            if line['id'] == 'd0':
                line.update(strategy=self.strategy, label=self.identity['model_label'])
        return result

    def _worker(self):
        while not self.halt.is_set():
            self.wake.clear()
            try:
                self.refresh(fetch_live=True)
            except Exception:
                # A malformed cache must not terminate subsequent refreshes.
                pass
            if not self.halt.is_set():
                self.wake.wait(self.interval)

    def close(self):
        self.halt.set()
        self.wake.set()
        thread = self.thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=15)
            if not thread.is_alive():
                self.thread = None
