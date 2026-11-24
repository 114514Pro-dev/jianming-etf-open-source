"""Independent price-index comparison; reads never fetch or mutate accounts.

The curves are normalized observations of actual indices, not pretend ETF
holdings. Tencent daily bars are refreshed only by the background service.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from decimal import DecimalException
import json
import math
import os
from pathlib import Path
import threading

from account_benchmark import (
    _account_daily, _calendar, _complete, _day, _fetch_daily,
    _money, _now, _number, _request,
)

SCHEMA = 'account.benchmark.price-index.v1'
INDICES = (
    ('sz399006', '创业板指数（399006）'),
    ('sh000001', '上证指数（000001）'),
)
INDEX_NAMES = dict(INDICES)
# Tencent's 创业板 daily history omits the real session 2014-10-08.
# Publish only a complete supported period; older accounts are unavailable
# rather than silently moving their start date or filling that missing bar.
HISTORY_START = '2015-01-01'
METHOD = ('按账户同一本金，将实际价格指数从账户起始日开盘点位归一化，'
          '逐日按收盘点位计算对照资产；不计交易费用、滑点或现金分红。'
          '该曲线是价格指数对标，不是可直接买卖的基金资产或含分红的全收益指数。'
          '账户与指数只比较共同已确认日终，缺失日线或账户日终不填补。')


def unavailable_index(symbol, message='指数行情暂不可用，账户资产曲线仍可查看。'):
    return dict(status='unavailable', symbol=symbol, name=INDEX_NAMES[symbol],
                price_basis='index_price', methodology=METHOD, message=message,
                notes=[], account_curve=[], benchmark_curve=[])


def _validate_snapshot(snapshot, symbol):
    if symbol not in INDEX_NAMES:
        raise ValueError('未知的大盘指数代码。')
    if not isinstance(snapshot, dict) or snapshot.get('schema') != SCHEMA:
        raise ValueError('独立指数行情尚未就绪。')
    if snapshot.get('symbol') != symbol or snapshot.get('name') != INDEX_NAMES[symbol]:
        raise ValueError('指数身份与指定基准不匹配。')
    if snapshot.get('price_basis') != 'index_price':
        raise ValueError('基准不是实际价格指数口径。')
    rows = snapshot.get('bars')
    sessions = snapshot.get('sessions')
    if not isinstance(rows, list) or not rows:
        raise ValueError('指数日线为空。')
    if not isinstance(sessions, list) or not sessions or sessions != sorted(set(sessions)):
        raise ValueError('缺少经过校验的指数交易日历。')
    for day in sessions:
        _day(day)
    last = None
    for row in rows:
        day = _day(row['date'])
        if last and day <= last:
            raise ValueError('指数日线重复或未按日期排序。')
        last = day
        opened, closed, high, low = [_number(row[key], positive=True)
                                     for key in ('open', 'close', 'high', 'low')]
        if low > min(opened, closed) or high < max(opened, closed) or low > high:
            raise ValueError('指数日线高低点位不一致。')
    if [row['date'] for row in rows] != sessions:
        raise ValueError('指数日线与已核实交易日历存在缺口。')
    through = _day(snapshot['confirmed_through'])
    if rows[-1]['date'] != through:
        raise ValueError('指数日线与确认截止日不一致。')
    known_sessions, _, _ = _calendar()
    expected = {day for day in known_sessions if rows[0]['date'] <= day <= through}
    if expected - set(sessions):
        raise ValueError('指数缓存缺少已验证交易日，不能删去日历来掩盖日线缺口。')
    if any(day.startswith('2026-') and day not in known_sessions for day in sessions):
        raise ValueError('指数缓存日期与2026官方交易日历不一致。')
    return snapshot


def build_index_benchmark(detail, snapshot, symbol, *, now=None):
    """Pure calculation: starting OPEN and daily CLOSE share account capital."""
    result = unavailable_index(symbol)
    try:
        now = _now(now)
        _validate_snapshot(snapshot, symbol)
        start, cutoff, capital, account = _account_daily(detail, now)
        bars = {row['date']: row for row in snapshot['bars']
                if _complete(row['date'], now)}
        if not bars:
            raise ValueError('指数尚无已确认日线。')
        benchmark_cutoff = max(bars)
        end = min(max(account), benchmark_cutoff)
        if start > end or start not in bars:
            raise ValueError('指数行情未覆盖账户起始日，不能缩短起点或重设本金。')
        days = [day for day in snapshot['sessions'] if start <= day <= end]
        if not days or days[0] != start or days[-1] != end:
            raise ValueError('比较边界不在已验证指数交易日历中。')
        missing_market = [day for day in days if day not in bars]
        missing_account = [day for day in days if day not in account]
        if missing_market or missing_account:
            label, missing = ('指数日线', missing_market) if missing_market else ('账户日终', missing_account)
            raise ValueError(label + '缺少：' + '、'.join(missing[:5]) + '；未填补缺失收益。')
        day_set = set(days)
        if any(start <= day <= end and day not in day_set for day in account):
            raise ValueError('账户记录与指数交易日历不一致。')
        reference = _number(bars[start]['open'], positive=True)
        curve = [dict(date=day, equity=_money(_number(
            capital * _number(bars[day]['close'], positive=True) / reference))) for day in days]
        last_account, last_benchmark = account[end], curve[-1]['equity']
        returns = (last_account / capital - 1, last_benchmark / capital - 1,
                   (last_account - last_benchmark) / capital)
        if not all(math.isfinite(value) for value in returns):
            raise ValueError('收益计算超出有效数字范围。')
        source = deepcopy(snapshot.get('source') or {})
        source.update(fetched_at=snapshot.get('fetched_at'), confirmed_through=benchmark_cutoff,
                      price_basis='index_price', normalization='start_day_open', dividends='excluded_price_index')
        notes = ['对照资产 = 账户初始本金 × 当日指数收盘点位 ÷ 起始日指数开盘点位。',
                 '指数涨跌采用实际价格指数，不包含成分股现金分红，也不模拟买卖交易。',
                 '账户曲线沿用现有模拟记录；超额收益为两者同区间累计收益之差，单位为百分点。']
        if end != cutoff[:10]:
            notes.append('原账户截止' + cutoff + '，本对照仅比较至共同已确认日终' + end + '；后续点未用旧价填补。')
        if len(cutoff) > 10 or any(len(str(row.get('date', row.get('datetime', '')))) > 10
                                   for row in detail.get('curve', [])):
            notes.append('小时策略只取15:00日终资产；盘中点及未完成收盘日不与全天收盘点位混比。')
        if source.get('cache_status') == 'bundled_seed_fallback':
            notes.append('本地指数缓存不可读，暂用已核验内置行情；仅显示内置行情覆盖的共同日终。')
        elif source.get('cache_status') == 'bundled_seed':
            notes.append('指数使用随版本交付的已核验行情，后台独立更新后切换到新缓存。')
        result.pop('message', None)
        result.update(status='ok', capital=capital, start=start, end=end,
                      account_cutoff=cutoff, benchmark_cutoff=benchmark_cutoff,
                      account_equity=last_account, benchmark_equity=last_benchmark,
                      account_return=returns[0], benchmark_return=returns[1], excess_return=returns[2],
                      excess_amount=_money(last_account - last_benchmark),
                      account_curve=[dict(date=day, equity=account[day]) for day in days],
                      benchmark_curve=curve, reference_open=reference, source=source,
                      notes=notes, settlement='normalized_price_index')
    except (ValueError, TypeError, KeyError, IndexError, OverflowError, DecimalException) as exc:
        result['message'] = str(exc) or '指数对照资料不足。'
    return result


def _identity_checked_request(symbol, request):
    """Check the provider's instrument code and index type before parsing bars."""
    def checked(url):
        raw = request(url)
        text = raw.decode('utf-8-sig').strip()
        if not text.startswith('{') and '=' in text:
            text = text.split('=', 1)[1].rstrip(';')
        payload = json.loads(text)
        node = payload.get('data', {}).get(symbol, {})
        quote = node.get('qt', {}).get(symbol)
        if (payload.get('code') != 0 or not isinstance(quote, list) or len(quote) < 3
                or str(quote[2]) != symbol[2:] or 'ZS' not in quote):
            raise ValueError('腾讯指数代码或指数类型无法核实：' + symbol + '。')
        if not isinstance(node.get('day'), list):
            raise ValueError('腾讯未返回实际指数日线，不能以复权基金行情替代。')
        return raw
    return checked


def _completed_calendar(now):
    sessions, calendar_through, calendar_hash = _calendar()
    if now.date().isoformat() > calendar_through:
        raise ValueError('交易日历已经过期，请先更新官方交易日历。')
    expected = [day for day in sessions if HISTORY_START <= day <= calendar_through and _complete(day, now)]
    if not expected:
        raise ValueError('当前时间之前没有已验证交易日。')
    return sessions, calendar_hash, expected


def _audited_today(snapshot, now, end):
    """Only an actual successful, nonfuture full-history audit can be reused."""
    if not snapshot or snapshot.get('source', {}).get('history_audit') != 'full_ohlc_no_revisions':
        return False
    try:
        raw = snapshot.get('fetched_at')
        if not isinstance(raw, str):
            return False
        stamp = datetime.fromisoformat(raw)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            return False
        stamp = _now(stamp)
        through = snapshot['confirmed_through']
        return (stamp <= now and stamp.date() == now.date() and through >= end
                and _complete(through, stamp) and _complete(through, now))
    except (ValueError, TypeError, KeyError, OverflowError):
        return False


def fetch_index_snapshot(symbol, previous=None, *, now=None, request=None):
    """Audit the complete history; reject gaps, identity errors and revisions.

    Past observed calendar omissions are recovered from actual index sessions.
    Current official-calendar sessions must match exactly. Every published old
    session remains mandatory, and every historical OHLC value is rechecked.
    """
    if symbol not in INDEX_NAMES:
        raise ValueError('未知的大盘指数代码。')
    now = _now(now)
    sessions, calendar_hash, expected = _completed_calendar(now)
    end = expected[-1]
    old = _validate_snapshot(previous, symbol) if previous else None
    checked = _identity_checked_request(symbol, request or _request)
    incoming, receipts = _fetch_daily(symbol, HISTORY_START, end, checked)
    mandatory = set(expected).union((old or {}).get('sessions', []))
    missing = sorted(mandatory - set(incoming))
    if missing:
        raise ValueError('指数日线缺口：' + '、'.join(missing[:5]) + '；未发布不完整更新。')
    # The packaged calendar carries exchange holiday notices for 2026. Its
    # preceding observation history may omit sessions, so allow recovered days.
    if any(day.startswith('2026-') and day not in sessions for day in incoming):
        raise ValueError('指数日期与2026官方交易日历不一致。')
    if old:
        for point in old['bars']:
            if incoming.get(point['date']) != point:
                raise ValueError('数据源修改了已保存历史指数点位，缓存保留原版等待核验。')
    snapshot = dict(schema=SCHEMA, symbol=symbol, name=INDEX_NAMES[symbol],
                    price_basis='index_price', bars=sorted(incoming.values(), key=lambda row: row['date']),
                    sessions=sorted(incoming), confirmed_through=end,
                    fetched_at=now.isoformat(timespec='seconds'),
                    source=dict(price='腾讯实际指数日线', identity_symbol=symbol,
                                identity_code=symbol[2:], instrument_type='ZS',
                                history_start=HISTORY_START,
                                history_coverage='2015年起完整日线；更早账户起点不重设、不填补缺失点位',
                                calendar='实际指数历史交易日期与包内2026官方交易日历交叉校验',
                                calendar_sha256=calendar_hash, history_audit='full_ohlc_no_revisions',
                                requests=receipts))
    return _validate_snapshot(snapshot, symbol)


class MarketIndexCache:
    """Per-index disk cache: network and writes are explicit refresh only."""
    def __init__(self, folder, symbol, seed=None):
        if symbol not in INDEX_NAMES:
            raise ValueError('未知的大盘指数代码。')
        self.symbol = symbol
        self.path = Path(folder) / (symbol + '.json')
        self.seed = (Path(seed) if seed is not None else
                     Path(__file__).resolve().parent / 'data/market_index_benchmark' / (symbol + '.json'))
        self._refresh_lock = threading.Lock()
        self.last_error = None

    def read(self):
        try:
            result = _validate_snapshot(json.loads(self.path.read_text(encoding='utf8')), self.symbol)
            result.setdefault('source', {})['cache_status'] = 'local_cache'
            return result
        except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError):
            try:
                result = _validate_snapshot(json.loads(self.seed.read_text(encoding='utf8')), self.symbol)
                result.setdefault('source', {})['cache_status'] = ('bundled_seed_fallback'
                                                                  if self.path.exists() else 'bundled_seed')
                return result
            except (OSError, ValueError, TypeError, KeyError, IndexError, OverflowError):
                return None

    def refresh(self, *, now=None, request=None):
        if not self._refresh_lock.acquire(blocking=False):
            return dict(status='updating', symbol=self.symbol)
        try:
            now = _now(now)
            previous = self.read()
            _, _, expected = _completed_calendar(now)
            if self.last_error is None and _audited_today(previous, now, expected[-1]):
                return dict(status='ok', symbol=self.symbol, confirmed_through=previous['confirmed_through'],
                            fetched_at=previous['fetched_at'])
            snapshot = fetch_index_snapshot(self.symbol, previous, now=now, request=request)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            target = self.path.with_suffix('.tmp')
            with target.open('w', encoding='utf8') as output:
                json.dump(snapshot, output, ensure_ascii=False, allow_nan=False)
                output.flush()
                os.fsync(output.fileno())
            os.replace(target, self.path)
            self.last_error = None
            return dict(status='ok', symbol=self.symbol, confirmed_through=snapshot['confirmed_through'],
                        fetched_at=snapshot['fetched_at'])
        except Exception as exc:
            self.last_error = str(exc)
            return dict(status='unavailable', symbol=self.symbol, message=str(exc))
        finally:
            self._refresh_lock.release()
