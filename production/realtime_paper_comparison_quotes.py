"""Read-only quote witnesses for display valuation, never execution evidence."""
from collections import OrderedDict
from copy import deepcopy
from decimal import Decimal
import json
from pathlib import Path
import sqlite3
import time

from realtime_paper_engine import PaperLedger, TradingCalendar, dt
from realtime_paper_rationale import SYMBOLS

ECONOMIC = ('price', 'previous_close', 'volume_lots', 'amount_cny')
COMPLETE = ECONOMIC + ('open', 'high', 'low')


def _amount(value, positive=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError('invalid quote amount')
    if isinstance(value, str) and len(value) > 80:
        raise ValueError('oversized quote amount')
    number = Decimal(str(value))
    if not number.is_finite() or number < 0 or number > Decimal('1e20') or (positive and not number):
        raise ValueError('invalid quote amount')
    return number


def source_ready(raw):
    status, reason, observation = (raw.get(k) for k in ('source_status', 'reason', 'observation_state'))
    return ((status == 'ready' and reason == 'ready' and observation in ('new_valid', 'repeat'))
            or (status == 'waiting' and reason == 'quote_queue_delay' and observation == 'repeat'))


def _row(batch, symbol):
    row = deepcopy(batch['quotes'][symbol])
    if not isinstance(row, dict) or row.get('symbol', symbol) != symbol:
        raise ValueError('wrong quote identity')
    row.setdefault('symbol', symbol)
    row.setdefault('source', batch.get('source'))
    row.setdefault('received_at', batch.get('received_at'))
    if not isinstance(row['source'], str) or not 1 <= len(row['source']) <= 128:
        raise ValueError('invalid source')
    quote, received = dt(row['quote_at']), dt(row['received_at'])
    if quote > received or row.get('day') != quote.date().isoformat() or row.get('started') is not True:
        raise ValueError('invalid quote day')
    if PaperLedger._raw_status(row) not in ('normal', 'unverified'):
        raise ValueError('adverse status')
    values = {k: _amount(row.get(k), k not in ('volume_lots', 'amount_cny')) for k in COMPLETE}
    if not values['low'] <= min(values['price'], values['open']) <= max(values['price'], values['open']) <= values['high']:
        raise ValueError('invalid price range')
    return row


def _key(row, *, ledger=False):
    status = row.get('status') if ledger else PaperLedger._raw_status(row)
    if status not in ('normal', 'unverified') or row.get('corporate_unknown') is True:
        raise ValueError('adverse accepted quote')
    return (row['symbol'], row['source'], dt(row['quote_at']), dt(row['received_at']), status,
            *(_amount(row[k], k in ('price', 'previous_close')) for k in ECONOMIC))


def _signature(row):
    return (row['symbol'], row['source'], row['day'], row['started'], PaperLedger._raw_status(row),
            *(_amount(row[k], k not in ('volume_lots', 'amount_cny')) for k in COMPLETE))


class DisplayQuoteResolver:
    """Re-use provenance, not timestamps, for strictly unchanged observations.

    The ledger intentionally rejects packets without new trade activity. A
    fresh public observation can still value unchanged holdings when every
    economic field agrees with a complete, previously accepted raw packet.
    """
    def __init__(self, folder):
        self.path = Path(folder) / '盘中行情.sqlite3'
        self.witnesses = OrderedDict()

    def _remember(self, key, row):
        self.witnesses[key] = deepcopy(row)
        self.witnesses.move_to_end(key)
        while len(self.witnesses) > 64:
            self.witnesses.popitem(last=False)

    def _restore(self, wanted):
        """A bounded read outside the account lock; never creates a database."""
        if not wanted or not self.path.is_file():
            return {}
        deadline = time.monotonic() + .2
        found, conflicts = {}, set()
        connection = None
        try:
            connection = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=.1)
            connection.execute('PRAGMA query_only=ON')
            connection.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            # rowid tail avoids a full unindexed received_at sort. Limit both
            # row count and payload size before materializing JSON in Python.
            rows = connection.execute('SELECT received_at, CASE WHEN length(payload)<=65536 THEN payload END '
                                      'FROM snapshots ORDER BY rowid DESC LIMIT 1024')
            for receipt, payload in rows:
                if time.monotonic() >= deadline:
                    return {}  # An incomplete scan cannot establish uniqueness.
                if payload is None:
                    if any(dt(receipt) == key[3] for key in wanted):
                        return {}
                    continue
                try:
                    batch = json.loads(payload)
                    if batch.get('received_at') != receipt:
                        continue
                    batch_receipt = dt(receipt)
                    for key in wanted:
                        try:
                            candidate = batch.get('quotes', {}).get(key[0], {})
                            candidate_receipt = (dt(candidate['received_at']) if 'received_at' in candidate
                                                 else batch_receipt)
                            # Most archive rows are unrelated receipts. Avoid
                            # OHLC/Decimal validation until identity can match.
                            if (candidate_receipt != key[3]
                                    or candidate.get('source', batch.get('source')) != key[1]
                                    or dt(candidate.get('quote_at')) != key[2]):
                                continue
                            row = _row(batch, key[0])
                            if _key(row) != key:
                                continue
                            if key in found and _signature(found[key]) != _signature(row):
                                conflicts.add(key)
                            else:
                                found[key] = row
                        except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError):
                            continue
                except (ValueError, TypeError, AttributeError):
                    if any(dt(receipt) == key[3] for key in wanted):
                        return {}
                    continue
        except (OSError, sqlite3.Error, ValueError, TypeError, AttributeError):
            return {}
        finally:
            if connection is not None:
                connection.close()
        return {key: value for key, value in found.items() if key not in conflicts}

    def resolve(self, raw, *, now):
        now, calendar = dt(now), TradingCalendar()
        if not source_ready(raw) or calendar.segment(now) is None:
            return None
        observed = raw.get('market_observation')
        if not isinstance(observed, dict) or not isinstance(observed.get('quotes'), dict):
            return None
        try:
            received = dt(observed['received_at'])
            if not 0 <= (now - received).total_seconds() <= 60:
                return None
        except (ValueError, TypeError, KeyError, AttributeError):
            return None
        candidates, wanted = {}, set()
        for symbol in SYMBOLS:
            try:
                accepted = raw['quotes'][symbol]
                key = _key(accepted, ledger=True)
                water = raw.get('status_watermarks', {}).get(symbol)
                if water is not None and water.get('status') not in ('normal', 'unverified'):
                    continue
                current = _row(observed, symbol)
                quote, receipt = dt(current['quote_at']), dt(current['received_at'])
                segment = calendar.segment(now)
                if (key[2].date() != now.date() or key[3].date() != now.date()
                        or not key[2] <= quote <= receipt <= now or receipt < key[3]
                        or receipt != received  # Native valuation uses the batch receipt.
                        or not quote <= received <= now
                        or not 0 <= (now - quote).total_seconds() <= 60
                        or not 0 <= (now - receipt).total_seconds() <= 60
                        or calendar.segment(quote) != segment or calendar.segment(receipt) != segment
                        or calendar.segment(received) != segment):
                    continue
                if key not in self.witnesses:
                    # Ledger identity omits OHLC. Even an exact current key
                    # needs an unambiguous original complete archive witness.
                    wanted.add(key)
                candidates[symbol] = (key, current)
            except (ValueError, TypeError, KeyError, AttributeError, ArithmeticError):
                continue
        for key, witness in self._restore(wanted).items():
            self._remember(key, witness)
        quotes = {}
        for symbol, (key, current) in candidates.items():
            witness = self.witnesses.get(key)
            if witness is not None and _signature(witness) == _signature(current):
                # Preserve the new, actually observed timestamps and OHLC.
                quotes[symbol] = deepcopy(observed['quotes'][symbol])
        return {**deepcopy(observed), 'quotes': quotes} if quotes else None
