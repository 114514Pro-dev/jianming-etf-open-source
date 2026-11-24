"""Bounded, read-only chart samples from the public quote producer's database.

This reader is independent of paper-account locks and trading acceptance. It
does not collect quotes, construct LiveStore, change a schema or write a ledger.
Keep one reader for the service lifetime; call snapshot only after releasing the
paper snapshot lock. Coverage is always recorded samples, never a complete tape.
"""
from copy import deepcopy
from bisect import bisect_left
from datetime import datetime, timedelta, timezone
import json
import math
from pathlib import Path
import sqlite3
from threading import Lock
import time

from realtime_paper_rationale import SYMBOLS

CN = timezone(timedelta(hours=8))
MAX_ROWS = 2048
MAX_POINTS = 600
MAX_PAYLOAD_BYTES = 64 * 1024
MAX_READ_BYTES = 8 * 1024 * 1024
REFRESH_SECONDS = 30
READ_SECONDS = 1.0
SQL_TIMEOUT = .15
GAP_SECONDS = 90


def _stamp(value):
    if not isinstance(value, str) or not 19 <= len(value) <= 40:
        return None
    try:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return None
        return stamp.astimezone(CN)
    except (ValueError, OverflowError):
        return None


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and 0 < number < 1e100 else None
    except (ValueError, OverflowError):
        return None


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON field')
        result[key] = value
    return result


def _history(status='unavailable', reason='no_samples', day=None, truncated=False, points=None):
    return dict(status=status, reason=reason, session_day=day,
                source='recorded_public_quotes', coverage='recorded_samples_only',
                truncated=bool(truncated), points=points or [])


def _empty(reason, status='unavailable'):
    return {symbol: _history(status, reason) for symbol in SYMBOLS}


def _asset():
    return dict(day=None, samples={}, invalid=False, truncated=False, force_break=False)


def _new_state(identity):
    return dict(identity=identity, cursors={}, assets={s: _asset() for s in SYMBOLS},
                failures=[], attempts_known=False, attempts_invalid=False, truncated=False)


class IntradayChartReader:
    def __init__(self, home, *, clock=None):
        # Construction deliberately performs no filesystem or database IO.
        self.path = Path(home) / '盘中行情.sqlite3'
        self._clock = clock or time.monotonic
        self._lock = Lock()
        self._next_due = float('-inf')
        self._cache = _empty('cache_unavailable')
        self._observed_at = None
        self._state = None

    def snapshot(self, now):
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            return _empty('invalid_time', 'invalid')
        now = now.astimezone(CN)
        if self._clock() < self._next_due:
            return self._deliver(now)
        if not self._lock.acquire(blocking=False):
            return _empty('reader_busy')
        try:
            if self._clock() >= self._next_due:
                try:
                    state = self._read(now)
                    cache = self._project(state)
                    self._state, self._cache, self._observed_at = state, cache, now
                except FileNotFoundError:
                    self._state = None
                    self._cache = _empty('quotes_missing')
                except Exception:
                    # A display failure must never fail the account GET or retain
                    # an apparently successful refresh. Retry after the TTL.
                    self._cache = _empty('read_failed')
                self._next_due = self._clock() + REFRESH_SECONDS
            return self._deliver(now)
        finally:
            self._lock.release()

    def _deliver(self, now):
        # A clock rollback must not expose samples that are now in the future.
        if self._observed_at is not None and now < self._observed_at:
            return _empty('clock_regressed', 'invalid')
        return deepcopy(self._cache)

    @staticmethod
    def _identity(path):
        stat = path.stat()
        return stat.st_dev, stat.st_ino

    @staticmethod
    def _table(con, name):
        row = con.execute('SELECT type FROM sqlite_master WHERE name=?', (name,)).fetchone()
        if row and row[0] != 'table':
            raise ValueError('chart source must be a table')
        return bool(row)

    @staticmethod
    def _metadata(con, table, where='', args=(), order='DESC', limit=MAX_ROWS + 1):
        # Names and query fragments are internal constants, never request input.
        date_field = 'received_at' if table == 'snapshots' else 'attempted_at'
        tail = ('length(CAST(payload AS BLOB))' if table == 'snapshots' else
                'CASE WHEN length(CAST(status AS BLOB)) <= 32 THEN status END')
        query = (f'SELECT rowid, CASE WHEN length(CAST(id AS BLOB)) <= 128 THEN id END, '
                 f'CASE WHEN length(CAST({date_field} AS BLOB)) <= 64 THEN {date_field} END, '
                 f'{tail} FROM {table} {where} ORDER BY rowid {order} LIMIT ?')
        return con.execute(query, (*args, limit)).fetchall()

    def _read(self, now):
        identity = self._identity(self.path)
        deadline = time.monotonic() + READ_SECONDS
        con = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', timeout=SQL_TIMEOUT, uri=True)
        try:
            con.execute('PRAGMA query_only=ON')
            con.execute('PRAGMA trusted_schema=OFF')
            con.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
            con.execute('BEGIN')
            if not self._table(con, 'snapshots'):
                raise ValueError('missing snapshots table')
            attempts_known = self._table(con, 'attempts')
            tables = ['snapshots'] + (['attempts'] if attempts_known else [])
            state = self._state
            reset = state is None or state['identity'] != identity or state['attempts_known'] != attempts_known
            if not reset:
                for table in tables:
                    anchor = state['cursors'].get(table)
                    newest = self._metadata(con, table, limit=1)
                    if anchor and (not newest or newest[0][0] < anchor[0] or
                                   self._metadata(con, table, 'WHERE rowid=?', (anchor[0],), limit=1) != [anchor]):
                        reset = True
                        break
            rows = {}
            if not reset:
                for table in tables:
                    anchor = state['cursors'].get(table)
                    rows[table] = self._metadata(con, table, 'WHERE rowid>?', (anchor[0] if anchor else 0,), order='ASC')
                    if len(rows[table]) > MAX_ROWS:
                        reset = True
                        break
            state = _new_state(identity) if reset else deepcopy(state)
            state['attempts_known'] = attempts_known
            if reset:
                rows = {table: self._metadata(con, table) for table in tables}
            for table, records in rows.items():
                if len(records) > MAX_ROWS:
                    state['truncated'] = True
                # On a reset retain the newest tail. Incremental overflow always
                # resets first, so a skipped interval cannot join old points.
                records = sorted(records[:MAX_ROWS], key=lambda row: row[0])
                rows[table] = records
                if records:
                    state['cursors'][table] = records[-1]

            budget = MAX_READ_BYTES
            wanted = []
            dropped = False
            for row in reversed(rows['snapshots']):
                size = row[3]
                if not isinstance(size, int) or size <= 0 or size > MAX_PAYLOAD_BYTES:
                    dropped = True
                elif size > budget:
                    dropped = True
                    state['truncated'] = True
                else:
                    budget -= size
                    wanted.append(row[0])
            # Byte sizes are checked before materializing TEXT in Python. Fetch
            # in small parameter batches to support conservative SQLite limits.
            payloads = {}
            for offset in range(0, len(wanted), 400):
                keys = wanted[offset:offset + 400]
                marks = ','.join('?' for _ in keys)
                for rowid, payload in con.execute(f'SELECT rowid,payload FROM snapshots WHERE rowid IN ({marks})', keys):
                    payloads[rowid] = payload
                if time.monotonic() > deadline:
                    raise TimeoutError('bounded quote read expired')
            if self._identity(self.path) != identity:
                raise ValueError('quote database replaced during read')
        finally:
            con.close()
        # Release SQLite's read transaction before JSON parsing, copying and
        # chart work so the existing producer is not held up by display CPU.
        self._attempts(state, rows.get('attempts', []), now)
        for rowid, _, received, _ in rows['snapshots']:
            if rowid in payloads:
                self._batch(state, payloads[rowid], received, now)
            if time.monotonic() > deadline:
                raise TimeoutError('bounded quote parse expired')
        if dropped:
            for asset in state['assets'].values():
                asset['invalid'] = asset['force_break'] = True
        return state

    @staticmethod
    def _attempts(state, rows, now):
        failures = set(state['failures'])
        for _, identifier, attempted_at, status in rows:
            if status == '日线失败':
                continue
            stamp = _stamp(attempted_at)
            if not isinstance(identifier, str) or not identifier or stamp is None or stamp > now or status not in ('成功', '失败'):
                state['attempts_invalid'] = True
            elif status == '失败':
                failures.add(stamp)
        if len(failures) > MAX_ROWS:
            state['truncated'] = state['attempts_invalid'] = True
        state['failures'] = sorted(failures)[-MAX_ROWS:]

    @staticmethod
    def _batch(state, payload, received_at, now):
        try:
            batch = json.loads(payload, object_pairs_hook=_object)
            received = _stamp(received_at)
            if (not isinstance(batch, dict) or received is None or received > now or
                    _stamp(batch.get('received_at')) != received or not isinstance(batch.get('quotes'), dict)):
                raise ValueError('invalid snapshot')
        except (ValueError, TypeError, RecursionError):
            for asset in state['assets'].values():
                asset['invalid'] = asset['force_break'] = True
            return
        for symbol, asset in state['assets'].items():
            quote = batch['quotes'].get(symbol)
            stamp = _stamp(quote.get('quote_at')) if isinstance(quote, dict) else None
            if stamp is None or stamp > now or stamp > received:
                asset['invalid'] = asset['force_break'] = True
                continue
            day = stamp.date().isoformat()
            if asset['day'] is not None and day < asset['day']:
                continue
            if day != asset['day']:
                asset.clear()
                asset.update(_asset())
                asset['day'] = day
            price, previous = _number(quote.get('price')), _number(quote.get('previous_close'))
            valid = (price is not None and previous is not None and quote.get('symbol', symbol) == symbol
                     and quote.get('day', day) == day)
            change = price / previous - 1 if valid else None
            if change is None or not math.isfinite(change):
                asset['samples'][stamp] = None
                asset['invalid'] = True
                continue
            point = dict(at=stamp.isoformat(), received_at=received.isoformat(), price=price,
                         previous_close=previous, change_ratio=change, break_before=False)
            if stamp in asset['samples']:
                previous_point = asset['samples'][stamp]
                if previous_point is None:
                    continue  # A conflicted timestamp remains a gap.
                if (previous_point['price'], previous_point['previous_close']) != (price, previous):
                    asset['samples'][stamp] = None
                    asset['invalid'] = True
                elif received < _stamp(previous_point['received_at']):
                    asset['samples'][stamp] = point
            else:
                asset['samples'][stamp] = point
        for asset in state['assets'].values():
            if len(asset['samples']) > MAX_POINTS:
                asset['samples'] = dict(sorted(asset['samples'].items())[-MAX_POINTS:])
                asset['truncated'] = True

    @staticmethod
    def _project(state):
        result = {}
        for symbol, asset in state['assets'].items():
            points, previous, gap = [], None, False
            uncertain = not state['attempts_known'] or state['attempts_invalid'] or asset['force_break']
            for stamp, saved in sorted(asset['samples'].items()):
                if saved is None:
                    gap = True
                    continue
                point = dict(saved)
                if previous is not None:
                    prior_at = _stamp(previous['at'])
                    prior_received = _stamp(previous['received_at'])
                    received = _stamp(point['received_at'])
                    lunch = prior_at.hour < 12 <= stamp.hour
                    failures = state['failures']
                    at_index = bisect_left(failures, prior_at)
                    received_index = bisect_left(failures, prior_received)
                    failed = ((at_index < len(failures) and failures[at_index] <= stamp) or
                              (received_index < len(failures) and failures[received_index] <= received))
                    point['break_before'] = bool(gap or uncertain or lunch or failed or
                        (stamp - prior_at).total_seconds() > GAP_SECONDS or
                        point['previous_close'] != previous['previous_close'])
                points.append(point)
                previous, gap = point, False
            truncated = state['truncated'] or asset['truncated']
            if not points:
                result[symbol] = _history('invalid' if asset['invalid'] else 'unavailable',
                    'invalid_samples' if asset['invalid'] else 'no_samples', asset['day'], truncated)
                continue
            reason = None
            if asset['invalid']:
                reason = 'invalid_samples'
            elif not state['attempts_known'] or state['attempts_invalid']:
                reason = 'collection_state_unavailable'
            elif state['failures'] and state['failures'][-1] >= min(_stamp(points[-1]['at']), _stamp(points[-1]['received_at'])):
                reason = 'collection_failed'
            result[symbol] = _history('available', reason, asset['day'], truncated, points)
        return result
