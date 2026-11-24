"""Durable minute observations, distinct from the existing daily observations.

The caller owns the ledger transaction/savepoint. Reads return today's points
only, so old retained days are never copied into command results or HTTP views.
"""
from datetime import time
from decimal import Decimal, InvalidOperation, localcontext
import json

from realtime_paper_pnl import _format
from realtime_paper_pnl_history import (_day, _identity, _money, _revision,
    _segments, _time, HEX, RATIO)

TABLE = 'paper_pnl_intraday'
META = 'paper_pnl_intraday_meta'
SCHEMA = 'd0-account-pnl-intraday-store-v1'
LIMIT = 1500
DAYS = 5
SECONDS = 60


def _empty(account_key=None):
    return {'schema': SCHEMA, 'account_key': account_key, 'truncated': False,
            'available_dates': [], 'last_observed_at': None,
            'last_ledger_revision': None, 'points': []}


def read_intraday(db, raw):
    key, _, now, _ = _identity(raw)
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN (?,?)", (TABLE, META))}
    if not tables:
        return _empty(key)
    if tables != {TABLE, META}:
        raise ValueError('incomplete intraday schema')
    count, size = db.execute('SELECT COUNT(*),COALESCE(MAX(length(CAST(data AS BLOB))),0) FROM paper_pnl_intraday WHERE account_key=?', (key,)).fetchone()
    if count > LIMIT or size > 4096:
        raise ValueError('oversized intraday history')
    result = _empty(key)
    result['available_dates'] = [r[0] for r in db.execute('SELECT DISTINCT day FROM paper_pnl_intraday WHERE account_key=? ORDER BY day', (key,))]
    if len(result['available_dates']) > DAYS:
        raise ValueError('oversized intraday dates')
    latest = db.execute('SELECT observed_at,ledger_revision FROM paper_pnl_intraday WHERE account_key=? ORDER BY observed_at DESC,ledger_revision DESC LIMIT 1', (key,)).fetchone()
    if latest:
        result.update(last_observed_at=latest[0], last_ledger_revision=str(latest[1]))
    for segment, day, minute, observed, revision, payload in db.execute('SELECT segment_id,day,minute,observed_at,ledger_revision,data FROM paper_pnl_intraday WHERE account_key=? AND day=? ORDER BY observed_at,ledger_revision,segment_id', (key, now.date().isoformat())):
        point = json.loads(payload)
        if ((point.get('segment_id'), point.get('date'), point.get('observed_at'), point.get('ledger_revision')) != (segment, day, observed, str(revision))
                or _time(observed).replace(second=0, microsecond=0).isoformat() != minute):
            raise ValueError('intraday index mismatch')
        result['points'].append(point)
    meta = db.execute('SELECT truncated FROM paper_pnl_intraday_meta WHERE account_key=?', (key,)).fetchone()
    if (count and meta is None) or (meta is not None and meta[0] not in (0, 1)):
        raise ValueError('invalid intraday metadata')
    result['truncated'] = bool(meta and meta[0])
    return result


def create_tables(db):
    db.execute('CREATE TABLE IF NOT EXISTS paper_pnl_intraday(account_key TEXT NOT NULL,segment_id TEXT NOT NULL,day TEXT NOT NULL,minute TEXT NOT NULL,observed_at TEXT NOT NULL,ledger_revision INTEGER NOT NULL,data TEXT NOT NULL,PRIMARY KEY(account_key,segment_id,minute))')
    db.execute('CREATE TABLE IF NOT EXISTS paper_pnl_intraday_meta(account_key TEXT PRIMARY KEY,truncated INTEGER NOT NULL DEFAULT 0)')


def write_intraday(db, account_key, point, stored, calendar):
    now = _time(point['observed_at'])
    # Cash-only accounts still have daily observations outside market hours;
    # the intraday curve records only actual market-session observations.
    if calendar.segment(now) is None:
        return
    point = dict(point)
    earlier = next((p for p in stored.get('points', []) if p['date'] == point['date'] and p['segment_id'] == point['segment_id']), None)
    point['first_base'] = (dict(earlier['first_base']) if earlier else
                          {k: point[k] for k in ('observed_at', 'cumulative_pnl')})
    minute = now.replace(second=0, microsecond=0).isoformat()
    serialized = json.dumps(point, sort_keys=True, separators=(',', ':'), allow_nan=False)
    db.execute('INSERT INTO paper_pnl_intraday VALUES(?,?,?,?,?,?,?) ON CONFLICT(account_key,segment_id,minute) DO UPDATE SET observed_at=excluded.observed_at,ledger_revision=excluded.ledger_revision,data=excluded.data',
               (account_key, point['segment_id'], point['date'], minute, point['observed_at'], int(point['ledger_revision']), serialized))
    db.execute('INSERT OR IGNORE INTO paper_pnl_intraday_meta(account_key,truncated) VALUES(?,0)', (account_key,))
    dates = [r[0] for r in db.execute('SELECT DISTINCT day FROM paper_pnl_intraday WHERE account_key=? ORDER BY day DESC', (account_key,))]
    if len(dates) > DAYS:
        db.execute('DELETE FROM paper_pnl_intraday WHERE account_key=? AND day<?', (account_key, dates[DAYS-1]))
        db.execute('UPDATE paper_pnl_intraday_meta SET truncated=1 WHERE account_key=?', (account_key,))
    count = db.execute('SELECT COUNT(*) FROM paper_pnl_intraday').fetchone()[0]
    if count > LIMIT:
        dropped = db.execute('SELECT rowid,account_key FROM paper_pnl_intraday ORDER BY observed_at,ledger_revision LIMIT ?', (count-LIMIT,)).fetchall()
        for rowid, key in dropped:
            db.execute('DELETE FROM paper_pnl_intraday WHERE rowid=?', (rowid,))
            db.execute('UPDATE paper_pnl_intraday_meta SET truncated=1 WHERE account_key=?', (key,))


def update_intraday(db, raw, daily, candidate, calendar):
    """Isolate this optional series from the established daily observation."""
    started = False
    try:
        db.execute('SAVEPOINT paper_pnl_minute_observation')
        started = True
        create_tables(db)
        stored = read_intraday(db, raw)
        projected = project_intraday({**raw, '_pnl_history': {**daily, 'intraday': stored}}, calendar=calendar)
        if projected['reason'] in ('invalid_history', 'history_unavailable'):
            raise ValueError('intraday history inconsistent with ledger')
        if candidate is not None:
            write_intraday(db, candidate[0], candidate[1], stored, calendar)
        result = read_intraday(db, raw)
        db.execute('RELEASE SAVEPOINT paper_pnl_minute_observation')
        return result
    except Exception:
        if not db.in_transaction:
            raise
        if started:
            db.execute('ROLLBACK TO SAVEPOINT paper_pnl_minute_observation')
            db.execute('RELEASE SAVEPOINT paper_pnl_minute_observation')
        return {'error': 'history_unavailable'}


def project_intraday(raw, *, calendar=None):
    result = {'contract_version': 'd0-account-pnl-intraday-v1', 'basis': 'minute_last_observation',
              'status': 'unavailable', 'reason': 'no_recorded_valuations_today', 'date': None,
              'sampling_seconds': SECONDS, 'retention_days': DAYS, 'retention_limit': LIMIT,
              'truncated': False, 'available_dates': [], 'last_recorded_at': None,
              'latest_recorded_at': None, 'current_segment': None, 'points': []}
    try:
        if not isinstance(raw, dict) or not raw.get('account'):
            return result
        key, segment, now, revision = _identity(raw)
        result.update(date=now.date().isoformat(), current_segment=segment)
        envelope = raw.get('_pnl_history')
        if envelope is None:
            return result
        if not isinstance(envelope, dict):
            raise ValueError('invalid parent history')
        if envelope.get('error'):
            result['reason'] = 'history_unavailable'
            return result
        stored = envelope.get('intraday')
        if stored is None:  # Old saved command results remain replayable.
            return result
        if isinstance(stored, dict) and stored.get('error') == 'history_unavailable':
            result['reason'] = 'history_unavailable'
            return result
        if (not isinstance(stored, dict) or stored.get('schema') != SCHEMA
                or stored.get('account_key') != key or type(stored.get('truncated')) is not bool
                or not isinstance(stored.get('points'), list) or len(stored['points']) > LIMIT
                or not isinstance(stored.get('available_dates'), list) or len(stored['available_dates']) > DAYS):
            raise ValueError('invalid intraday envelope')
        if calendar is None:
            from realtime_paper_engine import TradingCalendar
            calendar = TradingCalendar()
        dates = stored['available_dates']
        if sorted(set(dates)) != dates or any(_day(d) > now.date() or calendar.is_session(_day(d)) is not True for d in dates):
            raise ValueError('invalid retained dates')
        latest, latest_revision = stored['last_observed_at'], stored['last_ledger_revision']
        if dates:
            if _time(latest) > now or _time(latest).date().isoformat() != dates[-1] or _revision(latest_revision) > revision:
                raise ValueError('intraday history ahead of ledger')
        elif latest is not None or latest_revision is not None or stored['points']:
            raise ValueError('unexpected empty history metadata')
        if bool(stored['points']) != (now.date().isoformat() in dates):
            raise ValueError('missing current intraday observations')
        segments = _segments(raw, key, now)
        previous, seen, bases = None, set(), {}
        daily_points = envelope.get('points', [])
        with localcontext() as context:
            context.prec = 60
            for point in stored['points']:
                day, observed, identifier = _day(point['date']), _time(point['observed_at']), point['segment_id']
                minute = observed.replace(second=0, microsecond=0).isoformat()
                point_revision = _revision(point['ledger_revision'])
                if (not isinstance(identifier, str) or not HEX.fullmatch(identifier)
                        or identifier not in segments or point['initial_capital'] != segments[identifier]['capital']
                        or observed < segments[identifier]['at'] or day != now.date() or day != observed.date()
                        or calendar.segment(observed) is None or observed > now or point_revision > revision
                        or (identifier, minute) in seen
                        or (previous and (observed < _time(previous['observed_at']) or point_revision < int(previous['ledger_revision'])))):
                    raise ValueError('invalid intraday identity/order')
                seen.add((identifier, minute))
                capital = _money(point['initial_capital'], positive=True)
                cumulative = _money(point['cumulative_pnl'])
                if (_money(point['equity'], nonnegative=True)-capital != cumulative
                        or not isinstance(point['return_ratio'], str) or not RATIO.fullmatch(point['return_ratio'])
                        or point['return_ratio'] != _format(cumulative/capital, Decimal('.00000001'))
                        or type(point['cash_only']) is not bool):
                    raise ValueError('invalid intraday valuation')
                if point['cash_only']:
                    if point['valuation_at'] is not None or point['latest_quote_at'] is not None:
                        raise ValueError('cash observation has quotes')
                else:
                    oldest, newest = _time(point['valuation_at']), _time(point['latest_quote_at'])
                    if (not oldest <= newest <= observed or oldest.date() != day or newest.date() != day
                            or (observed-oldest).total_seconds() > 60 or calendar.segment(oldest) != calendar.segment(observed)):
                        raise ValueError('invalid intraday quote times')
                base = point['daily_base']
                if base is None:
                    if point['daily_pnl'] is not None:
                        raise ValueError('daily pnl without baseline')
                    base_date = None
                else:
                    base_date = base['date']
                    if (base['segment_id'] != identifier or calendar.next_session(_day(base_date)) != day
                            or _money(point['daily_pnl']) != cumulative-_money(base['cumulative_pnl'])):
                        raise ValueError('invalid intraday daily baseline')
                    matching = [p for p in daily_points if p['date'] == base_date and p['segment_id'] == identifier]
                    if matching and matching[-1]['cumulative_pnl'] != base['cumulative_pnl']:
                        raise ValueError('intraday baseline differs from daily history')
                first = point['first_base']
                first_at, first_pnl = _time(first['observed_at']), _money(first['cumulative_pnl'])
                if (first_at.date() != day or not segments[identifier]['at'] <= first_at <= observed
                        or calendar.segment(first_at) is None
                        or (first_at == observed and first_pnl != cumulative)
                        or (identifier in bases and bases[identifier] != (first, base))):
                    raise ValueError('invalid first observation baseline')
                bases[identifier] = (first, base)
                connected = bool(previous and previous['segment_id'] == identifier
                                 and calendar.segment(_time(previous['observed_at'])) == calendar.segment(observed)
                                 and (observed-_time(previous['observed_at'])).total_seconds() <= 120)
                public = {k: point[k] for k in ('date', 'segment_id', 'initial_capital', 'equity',
                    'cumulative_pnl', 'daily_pnl', 'return_ratio', 'observed_at', 'valuation_at',
                    'latest_quote_at', 'cash_only', 'ledger_revision')}
                public.update(daily_base_date=base_date, break_before=not connected,
                              record_type='minute_last_observation',
                              phase='intraday_estimate' if now.time().replace(tzinfo=None) < time(15) else 'last_recorded',
                              since_first_observation_pnl=_format(cumulative-first_pnl),
                              first_observed_at=first['observed_at'], first_observation_cumulative_pnl=first['cumulative_pnl'])
                result['points'].append(public)
                previous = point
        if previous and (previous['observed_at'], previous['ledger_revision']) != (latest, latest_revision):
            raise ValueError('intraday latest metadata mismatch')
        result.update(truncated=stored['truncated'], available_dates=dates, latest_recorded_at=latest)
        if result['points']:
            result.update(status='available', reason=None, last_recorded_at=result['points'][-1]['observed_at'])
        return result
    except (KeyError, TypeError, ValueError, InvalidOperation, ArithmeticError, AttributeError):
        result.update(status='unavailable', reason='invalid_history', points=[], available_dates=[],
                      last_recorded_at=None, latest_recorded_at=None, truncated=False)
        return result
