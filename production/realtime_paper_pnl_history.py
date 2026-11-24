"""Bounded, derived account observations in the ledger's existing transaction.

These are the last *observed* fresh valuations of each trading day, never a
reconstruction or an official close. Intraday observations use separate tables.
The HTTP projection is pure and never consults current storage or the clock.
"""
from datetime import date, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import re

from realtime_paper_pnl import project_account_pnl, _stamp, _format

TZ = timezone(timedelta(hours=8))
LIMIT = 366
SCHEMA = 'd0-account-pnl-history-store-v1'
TABLE = 'paper_pnl_daily'
META = 'paper_pnl_history_meta'
HEX = re.compile(r'^[a-f0-9]{64}$')
MONEY = re.compile(r'^-?(?:0|[1-9][0-9]{0,20})\.[0-9]{2}$')
RATIO = re.compile(r'^-?(?:0|[1-9][0-9]{0,20})\.[0-9]{8}$')


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()


def _time(value):
    value = _stamp(value)
    if value is None:
        raise ValueError('invalid observation time')
    return value.astimezone(TZ)


def _day(value):
    if not isinstance(value, str) or len(value) != 10:
        raise ValueError('invalid day')
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('invalid day')
    return parsed


def _revision(value):
    if not isinstance(value, str) or not re.fullmatch(r'0|[1-9][0-9]{0,18}', value):
        raise ValueError('invalid revision')
    result = int(value)
    if result > 2**63-1:
        raise ValueError('invalid revision')
    return result


def _money(value, *, positive=False, nonnegative=False):
    if not isinstance(value, str) or not MONEY.fullmatch(value):
        raise ValueError('invalid money')
    number = Decimal(value)
    if abs(number) > Decimal('1e20') or (positive and number <= 0) or (nonnegative and number < 0):
        raise ValueError('invalid money')
    return number


def _segments(raw, account_key, now):
    events = raw['events']
    if not isinstance(events, list) or len(events) > 100000:
        raise ValueError('invalid capital evidence')
    relevant = [e for e in events if isinstance(e, dict) and e.get('type') in ('created', 'capital_changed')]
    if not relevant or relevant[0]['type'] != 'created':
        raise ValueError('missing capital evidence')
    segments, seen = {}, set()
    previous = _time(raw['account']['created_at'])
    for index, event in enumerate(relevant):
        key, stamp, capital = event.get('id'), _time(event.get('at')), event.get('capital')
        if (not isinstance(key, str) or not 1 <= len(key) <= 256 or key in seen
                or not previous <= stamp <= now or (index and event['type'] != 'capital_changed')):
            raise ValueError('invalid capital evidence')
        _money(capital, positive=True)
        seen.add(key); previous = stamp
        identifier = _hash({'account_key': account_key, 'capital': capital,
                            'event_id': key, 'event_at': event['at']})
        segments[identifier] = {'capital': capital, 'at': stamp}
    return segments


def _identity(raw):
    account = raw['account']
    key, created = account['id'], account['created_at']
    if not isinstance(key, str) or not 1 <= len(key) <= 256:
        raise ValueError('invalid account identity')
    now = _time(raw['response_at'])
    if _time(created) > now:
        raise ValueError('account is in the future')
    capital = account['initial_capital']
    _money(capital, positive=True)
    account_key = _hash({'id': key, 'created_at': created})
    segments = _segments(raw, account_key, now)
    segment = next(reversed(segments))
    if segments[segment]['capital'] != capital:
        raise ValueError('capital differs from last event')
    return account_key, segment, now, _revision(raw['revision'])


def _empty(account_key=None):
    return {'schema': SCHEMA, 'account_key': account_key, 'truncated': False, 'points': []}


def read_history(db, raw):
    """Read using the caller's already-open snapshot; never create tables here."""
    if not raw.get('account'):
        return _empty()
    account_key, _, _, _ = _identity(raw)
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?)", (TABLE, META))}
    if not tables:
        return _empty(account_key)
    if tables != {TABLE, META}:
        raise ValueError('incomplete history schema')
    count, size = db.execute('SELECT COUNT(*),COALESCE(MAX(length(CAST(data AS BLOB))),0) FROM paper_pnl_daily WHERE account_key=?', (account_key,)).fetchone()
    if count > LIMIT or size > 4096:
        raise ValueError('oversized history')
    points = []
    for segment, day, observed, revision, payload in db.execute('SELECT segment_id,day,observed_at,ledger_revision,data FROM paper_pnl_daily WHERE account_key=? ORDER BY day,observed_at,ledger_revision', (account_key,)):
        point = json.loads(payload)
        if (point.get('segment_id'), point.get('date'), point.get('observed_at'), point.get('ledger_revision')) != (segment, day, observed, str(revision)):
            raise ValueError('history index mismatch')
        points.append(point)
    meta = db.execute('SELECT truncated FROM paper_pnl_history_meta WHERE account_key=?', (account_key,)).fetchone()
    if (count and meta is None) or (meta is not None and meta[0] not in (0, 1)):
        raise ValueError('invalid history metadata')
    result = {'schema': SCHEMA, 'account_key': account_key, 'truncated': bool(meta and meta[0]), 'points': points}
    from realtime_paper_pnl_intraday import read_intraday
    try:
        result['intraday'] = read_intraday(db, raw)
    except Exception:
        result['intraday'] = {'error': 'history_unavailable'}
    return result


def _candidate(raw, calendar):
    account_key, segment, now, revision = _identity(raw)
    if calendar.is_session(now.date()) is not True:
        return None
    pnl = project_account_pnl(raw)
    if pnl['status'] != 'fresh':
        return None
    # Do not move future trade proceeds or positions backwards on a clock reset.
    for fill in raw['fills']:
        if _time(fill.get('matched_at')) > now:
            raise ValueError('future fill')
    if not pnl['cash_only']:
        if calendar.segment(now) is None:
            return None
        for position in raw['positions']:
            if not position['qty']:
                continue
            quote = raw['quotes'][position['symbol']]
            at, received = _time(quote.get('quote_at')), _time(quote.get('received_at'))
            if (not at <= received <= now or at.date() != now.date() or received.date() != now.date()
                    or (now-at).total_seconds() > 60 or (now-received).total_seconds() > 5
                    or (received-at).total_seconds() > 60
                    or calendar.segment(at) != calendar.segment(now)
                    or calendar.segment(received) != calendar.segment(now)):
                return None
    point = {'date': now.date().isoformat(), 'segment_id': segment,
             'initial_capital': raw['account']['initial_capital'], 'equity': raw['account']['equity'],
             'cumulative_pnl': pnl['total_pnl'], 'return_ratio': pnl['return_ratio'],
             'observed_at': now.isoformat(), 'valuation_at': pnl['valuation_at'],
             'latest_quote_at': pnl['latest_quote_at'], 'cash_only': pnl['cash_only'],
             'ledger_revision': str(revision), 'daily_pnl': None, 'daily_base': None}
    return account_key, point


def update_and_read_history(db, raw, calendar):
    """Optional derived write inside a savepoint; caller still owns the commit.

    If SQLite has aborted the outer transaction, propagate the error: claiming
    the business operation committed would be incorrect in that situation.
    """
    if not db.in_transaction:
        raise ValueError('caller must own the ledger transaction')
    if not raw.get('account'):
        return _empty()
    started = False
    try:
        db.execute('SAVEPOINT paper_pnl_observation')
        started = True
        db.execute('CREATE TABLE IF NOT EXISTS paper_pnl_daily(account_key TEXT NOT NULL,segment_id TEXT NOT NULL,day TEXT NOT NULL,observed_at TEXT NOT NULL,ledger_revision INTEGER NOT NULL,data TEXT NOT NULL,PRIMARY KEY(account_key,segment_id,day))')
        db.execute('CREATE TABLE IF NOT EXISTS paper_pnl_history_meta(account_key TEXT PRIMARY KEY,truncated INTEGER NOT NULL DEFAULT 0)')
        existing = read_history(db, raw)
        projection = project_account_pnl_history({**raw, '_pnl_history': existing}, calendar=calendar)
        if projection['reason'] == 'invalid_history':
            raise ValueError('history ahead of or inconsistent with ledger')
        candidate = _candidate(raw, calendar)
        if candidate is not None:
            account_key, point = candidate
            previous = existing['points'][-1] if existing['points'] else None
            if previous is not None:
                if (int(point['ledger_revision']) < int(previous['ledger_revision'])
                        or _time(point['observed_at']) < _time(previous['observed_at'])):
                    raise ValueError('observation moved backwards')
                # Repeated observation identity cannot carry different money.
                if (point['ledger_revision'], point['observed_at']) == (previous['ledger_revision'], previous['observed_at']):
                    for key in ('segment_id', 'initial_capital', 'equity', 'cumulative_pnl', 'return_ratio', 'valuation_at', 'latest_quote_at', 'cash_only'):
                        if point[key] != previous[key]:
                            raise ValueError('conflicting observation identity')
                prior_day = next((p for p in reversed(existing['points']) if p['date'] < point['date']), None)
                if (prior_day is not None and prior_day['segment_id'] == point['segment_id']
                        and calendar.next_session(_day(prior_day['date'])) == _day(point['date'])):
                    point['daily_base'] = {k: prior_day[k] for k in ('date', 'segment_id', 'cumulative_pnl')}
                elif previous['date'] == point['date'] and previous['segment_id'] == point['segment_id']:
                    # A retained first day can still carry its original baseline.
                    point['daily_base'] = previous['daily_base']
            if point['daily_base'] is not None:
                point['daily_pnl'] = _format(Decimal(point['cumulative_pnl'])-Decimal(point['daily_base']['cumulative_pnl']))
            serialized = json.dumps(point, sort_keys=True, separators=(',', ':'), allow_nan=False)
            db.execute('INSERT INTO paper_pnl_daily VALUES(?,?,?,?,?,?) ON CONFLICT(account_key,segment_id,day) DO UPDATE SET observed_at=excluded.observed_at,ledger_revision=excluded.ledger_revision,data=excluded.data',
                       (account_key, point['segment_id'], point['date'], point['observed_at'], int(point['ledger_revision']), serialized))
            db.execute('INSERT OR IGNORE INTO paper_pnl_history_meta(account_key,truncated) VALUES(?,0)', (account_key,))
            count = db.execute('SELECT COUNT(*) FROM paper_pnl_daily').fetchone()[0]
            if count > LIMIT:
                dropped = db.execute('SELECT rowid,account_key FROM paper_pnl_daily ORDER BY day,observed_at,ledger_revision LIMIT ?', (count-LIMIT,)).fetchall()
                for rowid, dropped_account in dropped:
                    db.execute('DELETE FROM paper_pnl_daily WHERE rowid=?', (rowid,))
                    db.execute('UPDATE paper_pnl_history_meta SET truncated=1 WHERE account_key=?', (dropped_account,))
        from realtime_paper_pnl_intraday import update_intraday
        intraday = update_intraday(db, raw, existing, candidate, calendar)
        result = read_history(db, raw)
        result['intraday'] = intraday
        db.execute('RELEASE SAVEPOINT paper_pnl_observation')
        return result
    except Exception:
        if not db.in_transaction:
            raise
        if started:
            db.execute('ROLLBACK TO SAVEPOINT paper_pnl_observation')
            db.execute('RELEASE SAVEPOINT paper_pnl_observation')
        return {'error': 'history_unavailable'}


def project_account_pnl_history(raw, *, calendar=None):
    """Validate and project only the historical evidence attached to this view."""
    from realtime_paper_pnl_intraday import project_intraday
    result = {'contract_version': 'd0-account-pnl-history-v1', 'source': 'recorded_account_valuation',
              'basis': 'daily_last_observation', 'status': 'unavailable', 'reason': 'no_recorded_valuations',
              'current_segment': None, 'retention_limit': LIMIT, 'truncated': False,
              'recorded_from': None, 'last_recorded_at': None, 'points': [],
              'intraday': project_intraday(raw, calendar=calendar)}
    if not isinstance(raw, dict):
        return result
    stored = raw.get('_pnl_history')
    if stored is None:
        return result
    if isinstance(stored, dict) and stored.get('error') == 'history_unavailable':
        result['reason'] = 'history_unavailable'
        return result
    try:
        if not raw.get('account') and stored == _empty():
            return result
        account_key, segment, now, revision = _identity(raw)
        segments = _segments(raw, account_key, now)
        result['current_segment'] = segment
        if (not isinstance(stored, dict) or stored.get('schema') != SCHEMA
                or stored.get('account_key') != account_key or type(stored.get('truncated')) is not bool
                or not isinstance(stored.get('points'), list) or len(stored['points']) > LIMIT):
            raise ValueError('invalid history envelope')
        if calendar is None:
            from realtime_paper_engine import TradingCalendar
            calendar = TradingCalendar()
        previous, seen = None, set()
        with localcontext() as context:
            context.prec = 60
            for point in stored['points']:
                day = _day(point['date'])
                observed = _time(point['observed_at'])
                point_revision = _revision(point['ledger_revision'])
                identifier = point['segment_id']
                if not isinstance(identifier, str) or not HEX.fullmatch(identifier):
                    raise ValueError('invalid segment')
                if (identifier not in segments or point['initial_capital'] != segments[identifier]['capital']
                        or observed < segments[identifier]['at']):
                    raise ValueError('observation differs from capital evidence')
                if ((identifier, point['date']) in seen or calendar.is_session(day) is not True
                        or day != observed.date() or observed > now or point_revision > revision
                        or (previous is not None and (observed < _time(previous['observed_at'])
                             or point_revision < int(previous['ledger_revision'])))):
                    raise ValueError('invalid observation order')
                seen.add((identifier, point['date']))
                capital = _money(point['initial_capital'], positive=True)
                equity = _money(point['equity'], nonnegative=True)
                cumulative = _money(point['cumulative_pnl'])
                if equity-capital != cumulative or not isinstance(point['return_ratio'], str) or not RATIO.fullmatch(point['return_ratio']) or point['return_ratio'] != _format(cumulative/capital, Decimal('.00000001')):
                    raise ValueError('inconsistent observation money')
                if type(point['cash_only']) is not bool:
                    raise ValueError('invalid cash state')
                if point['cash_only']:
                    if point['valuation_at'] is not None or point['latest_quote_at'] is not None:
                        raise ValueError('cash account has quote times')
                else:
                    oldest, latest = _time(point['valuation_at']), _time(point['latest_quote_at'])
                    if not oldest <= latest <= observed or oldest.date() != day or latest.date() != day or (observed-oldest).total_seconds() > 60 or calendar.segment(observed) is None or calendar.segment(oldest) != calendar.segment(observed):
                        raise ValueError('invalid held observation times')
                base = point['daily_base']
                if base is None:
                    if point['daily_pnl'] is not None:
                        raise ValueError('daily change without baseline')
                    base_date = None
                else:
                    base_date = base['date']
                    if (base['segment_id'] != identifier or calendar.next_session(_day(base_date)) != day
                            or _money(point['daily_pnl']) != cumulative-_money(base['cumulative_pnl'])):
                        raise ValueError('invalid daily baseline')
                    if previous is not None and previous['date'] < point['date']:
                        if (previous['date'], previous['segment_id'], previous['cumulative_pnl']) != (base_date, identifier, base['cumulative_pnl']):
                            raise ValueError('daily baseline differs from recorded prior day')
                connected = (previous is not None and previous['segment_id'] == identifier
                             and base_date == previous['date'])
                public = {k: point[k] for k in ('date', 'segment_id', 'initial_capital', 'equity',
                    'cumulative_pnl', 'daily_pnl', 'return_ratio', 'observed_at', 'valuation_at',
                    'latest_quote_at', 'cash_only', 'ledger_revision')}
                public.update(daily_base_date=base_date, break_before=not connected,
                              record_type='daily_last_observation',
                              phase='intraday_estimate' if day == now.date() and now.time().replace(tzinfo=None) < time(15) else 'last_recorded')
                result['points'].append(public)
                previous = point
        result['truncated'] = stored['truncated']
        if result['points']:
            result.update(status='available', reason=None, recorded_from=result['points'][0]['date'],
                          last_recorded_at=result['points'][-1]['observed_at'])
        return result
    except (KeyError, TypeError, ValueError, InvalidOperation, ArithmeticError, AttributeError):
        result.update(status='unavailable', reason='invalid_history', points=[], recorded_from=None,
                      last_recorded_at=None, truncated=False)
        return result
