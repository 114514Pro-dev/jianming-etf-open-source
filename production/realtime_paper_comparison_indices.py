"""Independent, identity-checked index observations for D0 comparisons.

These are display observations of actual price indices, never execution quotes
for the four ETF instruments. Parsing is pure; fetching is explicit, injectable
and belongs on the comparison worker. Old provider timestamps remain old.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import math
import re
from urllib.parse import urlencode

from account_benchmark import _request


TZ = timezone(timedelta(hours=8))
INDEX_NAMES = {
    'sh000001': '上证指数（000001）',
    'sz399006': '创业板指数（399006）',
}
MAX_RESPONSE_BYTES = 1024 * 1024
SOURCE = '腾讯实际指数报价'
# Tencent's qt schema puts the security type at zero-based position 61.
# Both public sh000001 and sz399006 fqkline responses were checked against
# this position; a matching string in a name or another field proves nothing.
QT_INSTRUMENT_TYPE_INDEX = 61


def _symbol(symbol):
    if not isinstance(symbol, str) or symbol not in INDEX_NAMES:
        raise ValueError('不支持的指数报价代码。')
    return symbol


def _received(value):
    if isinstance(value, str):
        if not 1 <= len(value) <= 64:
            raise ValueError('指数报价接收时间无效。')
        try:
            value = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError('指数报价接收时间无效。') from exc
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError('指数报价接收时间须含时区。')
    return value.astimezone(TZ)


def _positive(value):
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError('指数报价点位无效。')
    if isinstance(value, str) and (not value or len(value) > 64):
        raise ValueError('指数报价点位无效。')
    try:
        number = Decimal(str(value))
        if not number.is_finite() or not 0 < number <= Decimal('1e100'):
            raise ValueError('指数报价点位无效。')
        result = float(number)
        if not math.isfinite(result) or result <= 0:
            raise ValueError('指数报价点位无效。')
        return result
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError('指数报价点位无效。') from exc


def parse_index_quote(payload, symbol, *, received_at):
    """Validate actual index identity and return scalar display facts only.

    The Tencent ``qt`` array carries its instrument code at slot 2 and its
    security type at slot 61. Only ``ZS`` in that fixed type slot is accepted.
    A configured label cannot substitute for either piece of source evidence.
    Freshness and session eligibility are deliberately left to the caller;
    this function does not replace a stale quote time with its receipt time.
    """
    symbol = _symbol(symbol)
    received = _received(received_at)
    if not isinstance(payload, dict) or type(payload.get('code')) is not int or payload['code'] != 0:
        raise ValueError('指数报价响应状态无效。')
    data = payload.get('data')
    node = data.get(symbol) if isinstance(data, dict) else None
    quotes = node.get('qt') if isinstance(node, dict) else None
    fields = quotes.get(symbol) if isinstance(quotes, dict) else None
    if (not isinstance(fields, list) or not QT_INSTRUMENT_TYPE_INDEX < len(fields) <= 512
            or type(fields[2]) not in (str, int) or str(fields[2]) != symbol[2:]
            or type(fields[QT_INSTRUMENT_TYPE_INDEX]) is not str
            or fields[QT_INSTRUMENT_TYPE_INDEX] != 'ZS'
            or not isinstance(node.get('day'), list)):
        raise ValueError('指数代码、ZS类型或实际指数日线身份无法核实。')
    stamp = fields[30]
    if not isinstance(stamp, str) or not re.fullmatch(r'[0-9]{14}', stamp):
        raise ValueError('指数报价源时间无效。')
    try:
        quoted = datetime.strptime(stamp, '%Y%m%d%H%M%S').replace(tzinfo=TZ)
    except ValueError as exc:
        raise ValueError('指数报价源时间无效。') from exc
    if quoted > received + timedelta(seconds=5):
        raise ValueError('指数报价源时间在接收时间之后。')
    price, previous, opening, high, low = [_positive(fields[index]) for index in (3, 4, 5, 33, 34)]
    if low > min(opening, price) or max(opening, price) > high:
        raise ValueError('指数报价开高低现价不一致。')
    return {
        'symbol': symbol, 'name': INDEX_NAMES[symbol], 'price': price,
        'previous_close': previous, 'open': opening, 'quote_at': quoted.isoformat(),
        'received_at': received.isoformat(), 'source': SOURCE, 'instrument_type': 'ZS',
    }


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('指数报价JSON包含重复键。')
        result[key] = value
    return result


def _invalid_constant(_value):
    raise ValueError('指数报价JSON包含非有限数值。')


def fetch_index_quote(symbol, *, now=None, request=None):
    """Fetch one bounded observation with the existing Tencent request path.

    ``request(url)`` is injected in tests. The normal request helper retains the
    application's existing HTTPS timeout and its independent transport bound;
    this layer additionally refuses responses above one MiB before decoding.
    """
    symbol = _symbol(symbol)
    # Capture the real receipt instant after transport, rather than treating
    # the beginning of a slow request as the quote's receipt time.
    received = _received(now) if now is not None else None
    url = ('https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?' +
           urlencode({'param': f'{symbol},day,,,1,', '_var': 'd0_comparison_quote'}))
    raw = (request or _request)(url)
    if not isinstance(raw, (bytes, bytearray)) or not 0 < len(raw) <= MAX_RESPONSE_BYTES:
        raise ValueError('指数报价响应大小或类型无效。')
    if received is None:
        received = datetime.now(TZ)
    try:
        text = bytes(raw).decode('utf-8-sig').strip()
        if not text.startswith('{'):
            wrapped = re.fullmatch(r'(?:var\s+)?[A-Za-z_$][A-Za-z0-9_$]*\s*=\s*(\{.*\})\s*;?', text, re.DOTALL)
            if not wrapped:
                raise ValueError('指数报价响应不是JSON。')
            text = wrapped.group(1)
        payload = json.loads(text, object_pairs_hook=_unique_object,
                             parse_float=Decimal, parse_constant=_invalid_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('指数报价JSON无法解析。') from exc
    return parse_index_quote(payload, symbol, received_at=received)
