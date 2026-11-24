"""Pure account P&L from one saved ledger view, never from display quotes.

Remaining lot costs already include buy fees and the ledger's sale allocation.
Cash already includes sale proceeds and fees; reserved cash is part of cash.
This module does not replay trades, price positions, access storage or read time.
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext

from realtime_paper_rationale import SYMBOLS

CENT = Decimal('.01')
RATIO = Decimal('.00000001')
MAX_AMOUNT = Decimal('1e20')


def _number(value, *, positive=False, cents=False):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError('invalid number')
    if isinstance(value, str) and len(value) > 80:
        raise ValueError('oversized number')
    result = Decimal(str(value))
    if not result.is_finite() or result < 0 or result > MAX_AMOUNT or (positive and not result):
        raise ValueError('invalid number')
    if cents and result != result.quantize(CENT):
        raise ValueError('money is not in cents')
    return result


def _quantity(value, positive=False):
    if type(value) is not int or value < (1 if positive else 0) or value > 10**12:
        raise ValueError('invalid quantity')
    return value


def _stamp(value):
    if not isinstance(value, str) or not 19 <= len(value) <= 40:
        return None
    try:
        stamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return stamp if stamp.tzinfo is not None and stamp.utcoffset() is not None else None
    except (ValueError, OverflowError):
        return None


def _format(value, quantum=CENT):
    rounded = value.quantize(quantum, rounding=ROUND_HALF_UP)
    return format(abs(rounded) if not rounded else rounded, 'f')


def project_account_pnl(raw):
    """Project only this view, including for an idempotent command replay."""
    result = dict(contract_version='d0-account-pnl-v1',
        basis='account_equity_and_remaining_cost', status='missing', reason='invalid_account',
        total_pnl=None, return_ratio=None, realized_pnl=None, unrealized_pnl=None,
        fees_paid=None, valuation_at=None, latest_quote_at=None, snapshot_at=None,
        cash_only=False, fees_included=True, frozen_cash_included=True)
    if not isinstance(raw, dict):
        return result
    snapshot = _stamp(raw.get('response_at'))
    if snapshot is not None:
        result['snapshot_at'] = raw['response_at']
    with localcontext() as context:
        context.prec = 60
        try:
            account = raw['account']
            capital = _number(account['initial_capital'], positive=True, cents=True)
            cash = _number(account['cash'], cents=True)
            valuation = account['valuation_status']
            if valuation not in ('current', 'stale', 'unknown'):
                raise ValueError('unknown account valuation')
        except (KeyError, TypeError, ValueError, InvalidOperation, ArithmeticError):
            return result

        reasons = []
        try:
            fills = raw['fills']
            if not isinstance(fills, list) or len(fills) > 100000:
                raise ValueError('invalid fills')
            identifiers = set()
            paid = Decimal(0)
            for fill in fills:
                key = fill['id']
                if not isinstance(key, str) or not key or len(key) > 256 or key in identifiers:
                    raise ValueError('invalid fill identity')
                identifiers.add(key)
                paid += _number(fill['fee'], cents=True)
            result['fees_paid'] = _format(paid)
        except (KeyError, TypeError, ValueError, InvalidOperation, ArithmeticError):
            reasons.append('invalid_fee_evidence')

        try:
            positions = raw['positions']
            if (not isinstance(positions, list) or len(positions) != len(SYMBOLS)
                    or {row['symbol'] for row in positions} != set(SYMBOLS)):
                raise ValueError('incomplete positions')
            cost = Decimal(0)
            held = []
            for row in positions:
                qty = _quantity(row['qty'])
                saved_cost = _number(row['cost'], cents=True)
                lots = row['lots']
                if not isinstance(lots, list) or len(lots) > 100000:
                    raise ValueError('invalid lots')
                lot_qty, lot_cost = 0, Decimal(0)
                for lot in lots:
                    lot_qty += _quantity(lot['qty'], positive=True)
                    lot_cost += _number(lot['cost'], cents=True)
                if lot_qty != qty or lot_cost != saved_cost or (not qty and saved_cost):
                    raise ValueError('remaining lot cost mismatch')
                cost += saved_cost
                if qty:
                    held.append(row)
            result['cash_only'] = not held
            result['realized_pnl'] = _format(cash + cost - capital)
        except (KeyError, TypeError, ValueError, InvalidOperation, ArithmeticError):
            result['reason'] = 'incomplete_cost'
            return result

        try:
            missing = False
            stale = False
            marked = Decimal(0)
            times = []
            for row in held:
                state = row['valuation_status']
                if state not in ('current', 'stale', 'unknown'):
                    raise ValueError('invalid position valuation')
                if state == 'unknown' or row['market_value'] is None or row['price'] is None:
                    missing = True
                    continue
                price = _number(row['price'], positive=True)
                value = _number(row['market_value'], cents=True)
                if value != (price * row['qty']).quantize(CENT, rounding=ROUND_HALF_UP):
                    raise ValueError('position value mismatch')
                marked += value
                stale = stale or state == 'stale'
                quote = raw.get('quotes', {}).get(row['symbol'])
                if not isinstance(quote, dict) or _number(quote.get('price'), positive=True) != price:
                    raise ValueError('valuation quote mismatch')
                source_time = _stamp(quote.get('quote_at'))
                if source_time is None or snapshot is None or source_time > snapshot:
                    reasons.append('missing_quote_time')
                else:
                    times.append((source_time, quote['quote_at']))
            expected_status = 'unknown' if missing else 'stale' if stale else 'current'
            if valuation != expected_status:
                raise ValueError('account valuation status mismatch')
            if held and len(times) == len(held):
                result['valuation_at'] = min(times)[1]
                result['latest_quote_at'] = max(times)[1]
            if missing:
                reasons.insert(0, 'missing_valuation')
            else:
                equity = _number(account['equity'], cents=True)
                if equity != cash + marked:
                    raise ValueError('equity differs from existing holdings')
                result.update(total_pnl=_format(equity-capital),
                    return_ratio=_format((equity-capital)/capital, RATIO),
                    unrealized_pnl=_format(marked-cost))
                if snapshot is None:
                    reasons.append('missing_quote_time')
            result['status'] = 'missing' if reasons else 'stale' if stale else 'fresh'
            result['reason'] = reasons[0] if reasons else None
        except (KeyError, TypeError, ValueError, InvalidOperation, ArithmeticError, AttributeError):
            result['reason'] = 'inconsistent_valuation'
        return result
