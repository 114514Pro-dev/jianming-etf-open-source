"""Read-only account versus cash-dividend ETF buy-and-hold comparison.

``build_account_benchmark`` never reads an account file and never uses network.
``BenchmarkCache.refresh`` belongs on an independent background worker; GET
handlers may call ``read`` without waiting for its network requests.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from hashlib import sha256
from html.parser import HTMLParser
from pathlib import Path
import json
import math
import os
import re
import threading
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TZ = timezone(timedelta(hours=8))
SYMBOL = 'sh510050'
NAME = '上证50ETF（510050）'
SCHEMA = 'account.benchmark.market.v1'
HISTORY_START = '2013-01-01'
COMMISSION = .0003
MINIMUM_COMMISSION = 5.
SLIPPAGE = .0002
LOT = 100
METHOD = ('同账户本金，从账户起始日开盘一次买入上证50ETF（510050）；'
          '采用未复权成交价，佣金万分之三且最低5元、买入滑点万分之二、100份整数手；'
          '现金分红在除息日计应收、支付日转现金，保留现金不再投资、不计利息；'
          '期末按收盘市值计价，不虚构卖出。账户与基准仅在共同已确认日终比较。')


def _day(value):
    text = str(value)
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', text):
        raise ValueError('日期格式错误。')
    return date.fromisoformat(text).isoformat()


def _number(value, *, positive=False):
    if isinstance(value, bool):
        raise ValueError('金额或价格不是有效数字。')
    result = float(value)
    if not math.isfinite(result) or result < 0 or (positive and result <= 0):
        raise ValueError('金额或价格不是有效数字。')
    return result


def _money(value):
    return float(Decimal(str(value)).quantize(Decimal('.01'), rounding=ROUND_HALF_UP))


def _now(value=None):
    value = value or datetime.now(TZ)
    if value.tzinfo is None:
        raise ValueError('确认时间必须带时区。')
    return value.astimezone(TZ)


def _complete(day, now):
    return datetime.combine(date.fromisoformat(day), time(15, 1), TZ) <= now


def _validate_snapshot(snapshot):
    if not isinstance(snapshot, dict) or snapshot.get('schema') != SCHEMA:
        raise ValueError('大盘ETF独立行情尚未就绪。')
    if snapshot.get('symbol') != SYMBOL or snapshot.get('price_basis') != 'unadjusted':
        raise ValueError('基准代码或未复权价格口径不匹配。')
    rows = snapshot.get('bars')
    if not isinstance(rows, list) or not rows:
        raise ValueError('大盘ETF日线为空。')
    last = None
    for row in rows:
        day = _day(row['date'])
        if last and day <= last:
            raise ValueError('大盘ETF日线重复或未按日期排序。')
        last = day
        for key in ('open', 'close', 'high', 'low'):
            _number(row[key], positive=True)
        if row['low'] > min(row['open'], row['close']) or row['high'] < max(row['open'], row['close']):
            raise ValueError('大盘ETF日线高低价不一致。')
    actions = snapshot.get('corporate_actions')
    if not isinstance(actions, dict) or not isinstance(actions.get('dividends'), list) or not isinstance(actions.get('splits'), list):
        raise ValueError('缺少已核实分红与折算记录，不能以零分红代替。')
    seen = set()
    for event in actions['dividends']:
        record, ex, pay = (_day(event[k]) for k in ('record', 'ex', 'pay'))
        if not record < ex <= pay or ex in seen:
            raise ValueError('分红登记、除息、支付日期异常或重复。')
        _number(event['cash_per_share'], positive=True)
        seen.add(ex)
    for event in actions['splits']:
        _day(event['date'])
        _number(event['ratio'], positive=True)
    _day(snapshot['confirmed_through'])
    if rows[-1]['date'] > snapshot['confirmed_through']:
        raise ValueError('日线超出确认范围。')
    if not snapshot.get('actions_verified'):
        raise ValueError('分红资料未完成验证。')
    return snapshot


def _account_daily(detail, now):
    """Date-only points mean close; intraday points must be exactly 15:00."""
    summary = detail.get('summary') or {}
    start = _day(str(summary['start'])[:10])
    cutoff = str(summary['day'])
    cutoff_day = _day(cutoff[:10])
    cutoff_bound = datetime.fromisoformat(cutoff) if len(cutoff) > 10 else None
    if cutoff_bound is not None and cutoff_bound.tzinfo is not None:
        cutoff_bound = cutoff_bound.astimezone(TZ)
        cutoff_day = cutoff_bound.date().isoformat()
    capital = _number(summary['capital'], positive=True)
    points = {}
    for row in detail.get('curve') or []:
        raw = str(row.get('date', row.get('day', row.get('datetime', ''))))
        day = _day(raw[:10])
        if len(raw) > 10:
            stamp = datetime.fromisoformat(raw)
            if stamp.tzinfo is not None:
                stamp = stamp.astimezone(TZ)
                day = stamp.date().isoformat()
            if stamp.time().replace(tzinfo=None) != time(15):
                continue
        if not start <= day <= cutoff_day or not _complete(day, now):
            continue
        # A summary timestamp before close cannot authorize a same-day close.
        if cutoff_bound is not None and day == cutoff_day:
            if cutoff_bound.time().replace(tzinfo=None) < time(15):
                continue
        equity = _number(row['equity'])
        if day in points and abs(points[day] - equity) > .005:
            raise ValueError('账户同一日终出现不一致资产记录。')
        points[day] = equity
    if not points or start not in points:
        raise ValueError('尚无从账户起始日开始的完整日终记录，暂不能同区间比较。')
    return start, cutoff, capital, points


def build_account_benchmark(detail, snapshot, *, now=None):
    """Return flat UI data; invalid/missing evidence produces no fake returns."""
    result = dict(status='unavailable', symbol=SYMBOL, name=NAME,
                  methodology=METHOD, notes=[], account_curve=[], benchmark_curve=[])
    try:
        now = _now(now)
        _validate_snapshot(snapshot)
        start, cutoff, capital, account = _account_daily(detail, now)
        bars = {r['date']: r for r in snapshot['bars']
                if _complete(r['date'], now) and r['date'] <= snapshot['confirmed_through']}
        if not bars:
            raise ValueError('大盘ETF尚无已确认日线。')
        benchmark_cutoff = max(bars)
        end = min(max(account), benchmark_cutoff)
        if start > end or start not in bars:
            raise ValueError('基准行情未覆盖账户起始日，不能缩短起点或重设本金。')
        sessions = snapshot.get('sessions')
        if not isinstance(sessions, list) or not sessions or sessions != sorted(set(sessions)):
            raise ValueError('缺少经过校验的交易日历，不能忽略日线缺口。')
        days = [d for d in sessions if start <= d <= end]
        if not days or days[0] != start or days[-1] != end:
            raise ValueError('比较边界不在已验证交易日历中。')
        missing_market = [d for d in days if d not in bars]
        missing_account = [d for d in days if d not in account]
        if missing_market or missing_account:
            label, missing = ('基准日线', missing_market) if missing_market else ('账户日终', missing_account)
            raise ValueError(label + '缺少：' + '、'.join(missing[:5]) + '；未填补缺失收益。')
        unexpected = [d for d in account if start <= d <= end and d not in set(days)]
        if unexpected:
            raise ValueError('账户记录与交易日历不一致。')
        for event in snapshot['corporate_actions']['splits']:
            if start <= event['date'] <= end:
                raise ValueError('区间内有份额折算，需核实公告及取整规则后才能比较。')
        price = round(bars[start]['open'] * (1 + SLIPPAGE), 8)
        qty = max(0, int(capital / price) // LOT * LOT)
        def cost(q):
            gross = _money(q * price)
            fee = _money(max(MINIMUM_COMMISSION, gross * COMMISSION)) if q else 0.
            return gross, fee
        gross, fee = cost(qty)
        while qty and gross + fee > capital:
            qty -= LOT
            gross, fee = cost(qty)
        cash = _money(capital - gross - fee)
        dividends = [e for e in snapshot['corporate_actions']['dividends'] if start <= e['record'] and e['ex'] <= end]
        curve = []
        for day in days:
            # Fixed holdings make the date entitlement explicit. Never accrue
            # an event whose record date preceded the initial purchase.
            paid = sum(_money(qty * e['cash_per_share']) for e in dividends if e['pay'] <= day)
            receivable = sum(_money(qty * e['cash_per_share']) for e in dividends if e['ex'] <= day < e['pay'])
            equity = _money(cash + paid + receivable + qty * bars[day]['close'])
            curve.append(dict(date=day, equity=equity))
        last_account, last_benchmark = account[end], curve[-1]['equity']
        source = deepcopy(snapshot.get('source') or {})
        source.update(fetched_at=snapshot.get('fetched_at'), confirmed_through=benchmark_cutoff,
                      price_basis='unadjusted', dividend_policy='cash_not_reinvested')
        notes = ['账户曲线来自现有真实模拟记录，未重算策略、未改动账户或成交。',
                 '未复权价格加现金分红；基金费用已反映在净值与市场价中，不额外重复扣管理费。',
                 '超额收益为账户累计收益率减去基准累计收益率，以百分点展示，并非保证未来超额。']
        if end != cutoff[:10]:
            notes.append('原账户截止' + cutoff + '，本对照仅比较至共同已确认日终' + end + '；后续点未用旧价填补。')
        if len(cutoff) > 10 or any(len(str(r.get('date', r.get('datetime', '')))) > 10 for r in detail.get('curve', [])):
            notes.append('小时策略只取15:00日终资产；盘中点及未完成收盘日不与全天收盘价混比。')
        if qty == 0:
            notes.append('本金不足买入一手并支付费用，基准保持现金，收益为真实零持仓结果。')
        if source.get('cache_status') == 'bundled_seed_fallback':
            notes.append('本地基准缓存不可读，暂用已核验内置行情；仅显示内置行情覆盖的共同日终。')
        elif source.get('cache_status') == 'bundled_seed':
            notes.append('基准使用随版本交付的已核验行情，后台独立更新后切换到新缓存。')
        group = detail.get('group', detail.get('summary', {}).get('group'))
        if group in ('nasdaq', 'hangseng', 'hangtech'):
            notes.append('海外账户与境内上证50ETF的市场风险不同；原账户收益及分红处理沿用原引擎，此处仅增加基准。')
        result.update(status='ok', capital=capital, start=start, end=end,
                      account_cutoff=cutoff, benchmark_cutoff=benchmark_cutoff,
                      account_equity=last_account, benchmark_equity=last_benchmark,
                      account_return=last_account/capital-1, benchmark_return=last_benchmark/capital-1,
                      excess_return=(last_account-last_benchmark)/capital,
                      excess_amount=_money(last_account-last_benchmark),
                      account_curve=[dict(date=d, equity=account[d]) for d in days],
                      benchmark_curve=curve, source=source, notes=notes,
                      purchase=dict(date=start, reference=bars[start]['open'], price=price,
                                    shares=qty, gross=gross, fee=fee, remaining_cash=cash),
                      settlement='market_value_no_terminal_sale')
    except (ValueError, TypeError, KeyError, IndexError, OverflowError) as exc:
        result['message'] = str(exc) or '大盘ETF对照资料不足。'
    return result


class _TableRows(HTMLParser):
    def __init__(self):
        super().__init__(); self.rows = []; self.row = None; self.cell = None
    def handle_starttag(self, tag, attrs):
        if tag == 'tr': self.row = []
        if tag in ('td', 'th') and self.row is not None: self.cell = []
    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
    def handle_endtag(self, tag):
        if tag in ('td', 'th') and self.cell is not None:
            self.row.append(''.join(self.cell).strip()); self.cell = None
        if tag == 'tr' and self.row is not None:
            self.rows.append(self.row); self.row = None


def parse_actions(html):
    if '分红送配详情' not in html or '拆分详情' not in html or '510050' not in html:
        raise ValueError('上证50ETF分红页面结构或身份无法确认。')
    parser = _TableRows(); parser.feed(html)
    dividends, splits = [], []
    for row in parser.rows:
        if len(row) == 5 and re.fullmatch(r'\d{4}-\d{2}-\d{2}', row[1]):
            match = re.fullmatch(r'每10份派现金([\d.]+)元', row[3])
            if not match:
                raise ValueError('现金分红单位无法确认。')
            dividends.append(dict(record=_day(row[1]), ex=_day(row[2]), pay=_day(row[4]),
                                  cash_per_share=float(Decimal(match[1])/10)))
        if len(row) == 4 and re.fullmatch(r'\d{4}-\d{2}-\d{2}', row[1]):
            ratio = re.fullmatch(r'1\s*[:：]\s*([\d.]+)', row[3])
            if not ratio:
                raise ValueError('份额折算比例无法确认。')
            splits.append(dict(date=_day(row[1]), ratio=_number(ratio[1], positive=True), type=row[2]))
    # This fund has a documented dividend history; an empty parsed list is an
    # upstream format failure, not permission to manufacture a zero return.
    if not dividends:
        raise ValueError('上证50ETF历史分红为空，不能按无分红继续。')
    return dict(dividends=sorted(dividends, key=lambda e:e['ex']), splits=splits)


def verify_official_dividends(html, actions):
    """Fund manager table independently verifies every record/pay/amount."""
    if not re.search(r'<input\b[^>]*name=[\"\']fundcode[\"\'][^>]*value=[\"\']510050[\"\']', html, re.I):
        raise ValueError('基金管理人分红页的ETF身份无法确认。')
    if not all(label in html for label in ('权益登记日', '每份分红', '分红发放日')):
        raise ValueError('基金管理人分红表结构无法确认。')
    parser = _TableRows(); parser.feed(html); official = {}
    for row in parser.rows:
        if len(row) == 4 and re.fullmatch(r'\d{4}-\d{2}-\d{2}', row[1]):
            key = (_day(row[1]), _day(row[3]))
            if key in official:
                raise ValueError('基金管理人分红日期重复。')
            official[key] = _number(row[2], positive=True)
    supplied = {(e['record'], e['pay']): e['cash_per_share'] for e in actions['dividends']}
    if not official or set(official) != set(supplied) or any(abs(amount-supplied[key]) > 1e-10 for key,amount in official.items()):
        raise ValueError('分红日期或金额与基金管理人官方历史表不一致，未发布新缓存。')
    return len(official)


def _request(url):
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': '*/*'})
    with urlopen(req, timeout=20) as response:
        raw = response.read(3_000_001)
    if len(raw) > 3_000_000:
        raise ValueError('基准行情响应超过上限。')
    return raw


def _calendar():
    path = Path(__file__).resolve().parent/'data/chinext/calendar.json'
    payload = json.loads(path.read_text(encoding='utf8'))
    sessions = payload['sessions']
    if not sessions or sessions != sorted(set(sessions)):
        raise ValueError('交易日历格式错误。')
    for day in sessions: _day(day)
    through = _day(payload['verified_through'])
    if sessions[-1] > through:
        raise ValueError('交易日历确认范围错误。')
    return sessions, through, sha256(path.read_bytes()).hexdigest()


def _fetch_daily(symbol, start, end, request):
    cursor = date.fromisoformat(start); points = {}; receipts = []
    while cursor.isoformat() <= end:
        stop = min(date(cursor.year+1, 12, 31), date.fromisoformat(end))
        url = ('https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get?' +
               urlencode({'param':f'{symbol},day,{cursor.isoformat()},{stop.isoformat()},640,',
                          '_var':'benchmark_day'}))
        raw = request(url); text = raw.decode('utf-8-sig').strip()
        if not text.startswith('{') and '=' in text: text = text.split('=', 1)[1].rstrip(';')
        payload = json.loads(text)
        lines = payload.get('data', {}).get(symbol, {}).get('day')
        if payload.get('code') != 0 or not isinstance(lines, list) or not lines:
            raise ValueError('腾讯未返回' + symbol + '未复权日线。')
        for row in lines:
            day = _day(row[0])
            if not cursor.isoformat() <= day <= stop.isoformat(): continue
            point = dict(date=day, open=_number(row[1], positive=True), close=_number(row[2], positive=True),
                         high=_number(row[3], positive=True), low=_number(row[4], positive=True))
            if day in points and points[day] != point:
                raise ValueError('行情源同一批次存在冲突日线。')
            points[day] = point
        receipts.append(dict(url=url, sha256=sha256(raw).hexdigest()))
        cursor = stop + timedelta(days=1)
    return points, receipts


def fetch_snapshot(previous=None, *, now=None, request=None):
    """Fetch independent raw-price/dividend data, fail on gaps or revisions."""
    now = _now(now); request = request or _request
    sessions, calendar_through, calendar_hash = _calendar()
    complete = [d for d in sessions if HISTORY_START <= d <= calendar_through and _complete(d, now)]
    if not complete:
        raise ValueError('当前时间之前没有已验证交易日。')
    end = complete[-1]
    if now.date().isoformat() > calendar_through:
        raise ValueError('交易日历已经过期，请先更新官方交易日历。')
    old = _validate_snapshot(previous) if previous else None
    overlap_start = old['bars'][-1]['date'] if old else HISTORY_START
    bars = {r['date']:dict(r) for r in old['bars']} if old else {}
    incoming, receipts = _fetch_daily(SYMBOL, overlap_start, end, request)
    index, index_receipts = _fetch_daily('sh000001', overlap_start, end, request)
    # The old package's historic calendar is an ETF-observation calendar and
    # has occasional missing sessions. An independent exchange index verifies
    # those sessions; official 2026 dates still constrain the current year.
    expected_overlap = {d for d in complete if d >= overlap_start}
    if expected_overlap - set(index):
        raise ValueError('上证指数交易日期校验存在缺口。')
    if any(d.startswith('2026-') and d not in sessions for d in index):
        raise ValueError('指数日期与2026官方交易日历不一致。')
    if set(incoming) != set(index):
        raise ValueError('ETF与上证指数交易日期不一致，未填补缺失日线。')
    for day, point in incoming.items():
        if day in bars and bars[day] != point:
            raise ValueError('数据源修改了已保存历史价格，基准缓存保留原版等待核验。')
        bars[day] = point
    complete = sorted(set(old['sessions'] if old else []).union(index))
    missing = [d for d in complete if d not in bars]
    if missing:
        raise ValueError('基准日线缺口：' + '、'.join(missing[:5]) + '；未发布不完整更新。')
    actions_url = 'https://fundf10.eastmoney.com/fhsp_510050.html'
    actions_raw = request(actions_url)
    actions = parse_actions(actions_raw.decode('utf-8-sig'))
    official_url = 'https://www.chinaamc.com.cn/product/fundLishifenhong.do?fundcode=510050'
    official_raw = request(official_url)
    official_count = verify_official_dividends(official_raw.decode('utf-8-sig'), actions)
    if old:
        for known in old['corporate_actions']['dividends']:
            matching = [e for e in actions['dividends'] if all(e[k] == known[k] for k in ('record','ex','pay'))
                        and abs(e['cash_per_share']-known['cash_per_share']) < 1e-10]
            if known['ex'] <= end and not matching:
                raise ValueError('分红来源缺失或修改了已核实项目，缓存保留原版。')
    def receipts_with_history(key, latest):
        existing = {r['url']:r for r in (old or {}).get('source',{}).get(key,[])}
        existing.update({r['url']:r for r in latest})
        return list(existing.values())
    snapshot = dict(schema=SCHEMA, symbol=SYMBOL, name=NAME, price_basis='unadjusted',
                    bars=sorted(bars.values(), key=lambda r:r['date']),
                    corporate_actions=actions, actions_verified=True,
                    confirmed_through=end, fetched_at=now.isoformat(timespec='seconds'),
                    sessions=complete, source=dict(price='腾讯未复权日线', dividends='东方财富基金分红资料',
                    actions_url=actions_url, actions_sha256=sha256(actions_raw).hexdigest(),
                    official_dividends_url=official_url, official_dividends_sha256=sha256(official_raw).hexdigest(),
                    official_dividend_records=official_count,
                    calendar_sha256=calendar_hash, calendar='上证指数历史交易日期与包内2026官方交易日历交叉校验',
                    requests=receipts_with_history('requests',receipts),
                    calendar_requests=receipts_with_history('calendar_requests',index_receipts)))
    return _validate_snapshot(snapshot)


class BenchmarkCache:
    """Small independent cache. Network and mutations are explicit refresh only."""
    def __init__(self, folder, seed=None):
        self.path = Path(folder)/'上证50ETF基准行情.json'
        self.seed = Path(seed) if seed is not None else Path(__file__).resolve().parent/'data/account_benchmark/seed.json'
        self._refresh_lock = threading.Lock()
        self.last_error = None

    def read(self):
        try:
            result = _validate_snapshot(json.loads(self.path.read_text(encoding='utf8')))
            result.setdefault('source',{})['cache_status'] = 'local_cache'
            return result
        except (OSError, ValueError, TypeError, KeyError):
            try:
                result = _validate_snapshot(json.loads(self.seed.read_text(encoding='utf8')))
                result.setdefault('source',{})['cache_status'] = 'bundled_seed_fallback' if self.path.exists() else 'bundled_seed'
                return result
            except (OSError, ValueError, TypeError, KeyError):
                return None

    def refresh(self, *, now=None, request=None):
        if not self._refresh_lock.acquire(blocking=False):
            return dict(status='updating')
        try:
            snapshot = fetch_snapshot(self.read(), now=now, request=request)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            target = self.path.with_suffix('.tmp')
            with target.open('w', encoding='utf8') as output:
                json.dump(snapshot, output, ensure_ascii=False, allow_nan=False)
                output.flush(); os.fsync(output.fileno())
            os.replace(target, self.path)
            self.last_error = None
            return dict(status='ok', confirmed_through=snapshot['confirmed_through'], fetched_at=snapshot['fetched_at'])
        except Exception as exc:
            self.last_error = str(exc)
            return dict(status='unavailable', message=str(exc))
        finally:
            self._refresh_lock.release()
