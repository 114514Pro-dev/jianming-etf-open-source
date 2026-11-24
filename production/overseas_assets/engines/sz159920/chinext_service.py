"""Isolated five-strategy ChiNext service, immutable snapshots and paper accounts.

This module never writes the old nine-strategy account or changes SuiteBook.
Historical comparisons use the research terminal-liquidation convention;
continuing paper accounts retain positions and execute only on observed bars.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path
import threading
import uuid
import zipfile

import numpy as np
import pandas as pd

import chinext_engine as engine
from chinext_indicators import make_signals

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'chinext'
CN = timezone(timedelta(hours=8))
VERSION = 'chinext.top5.paper.v1.2.20260916'
HOURS = ['10:30:00', '11:30:00', '14:00:00', '15:00:00']
STRATEGIES = [
    dict(id='T5VOTE', name='60分钟·均线突破量能组合', timeframe='60分钟', tf='60m',
         parameters='SMA20/60＋唐奇安20/10＋OBV/SMA20；至少2票持有',
         description='三种模型中至少两种为多头时入场，否则退出；使用真实60分钟K线。'),
    dict(id='T5WEEK', name='周线·SKDJ＋TRIX持有20日', timeframe='周线', tf='W',
         parameters='SKDJ(3,5)＋TRIX(4,8)；固定20个交易日',
         description='已完成周K线的K>D且TRIX>信号线时入场；买入算第1日，第21交易日开盘退出。原参数曾历史选优。'),
    dict(id='T5DON', name='60分钟·唐奇安突破', timeframe='60分钟', tf='60m',
         parameters='前20根最高价入场；前10根最低价退出',
         description='收盘突破此前20根最高价买入，跌破此前10根最低价退出，通道不含当前K线。'),
    dict(id='T5SUPER', name='60分钟·Supertrend', timeframe='60分钟', tf='60m',
         parameters='Wilder ATR10，倍数3',
         description='超级趋势由空转多入场，由多转空退出；始终以完整60分钟K线计算。'),
    dict(id='T5MA', name='60分钟·50根均线择时', timeframe='60分钟', tf='60m',
         parameters='SMA50（50根60分钟K线）',
         description='收盘高于50根均线持有，否则现金；不是50日或50周均线。'),
]
BY_ID = {s['id']: s for s in STRATEGIES}
_LOCKS = {}
_LOCK_GUARD = threading.Lock()


def _lock_for(path):
    key = str(Path(path).resolve())
    with _LOCK_GUARD:
        return _LOCKS.setdefault(key, threading.RLock())


def _now():
    return datetime.now(CN).isoformat(timespec='seconds')


def _clean(value):
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if isinstance(value, (pd.Timestamp, datetime, Path)):
        return str(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return float(value) if math.isfinite(float(value)) else None
    return value


def _canonical(value):
    return json.dumps(_clean(value), ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def _digest(value):
    return hashlib.sha256(_canonical(value)).hexdigest()


def _read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def _write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    tmp.write_bytes(_canonical(value))
    os.replace(tmp, path)


def _date(value):
    try:
        result = pd.Timestamp(str(value))
    except (TypeError, ValueError) as exc:
        raise ValueError('日期格式应为 YYYY-MM-DD。') from exc
    if pd.isna(result):
        raise ValueError('日期不能为空。')
    if result.tzinfo is not None:
        result = result.tz_convert('Asia/Shanghai').tz_localize(None)
    return result


def _capital(value):
    amount = float(value)
    if not math.isfinite(amount) or amount < 1000 or amount > 1e10:
        raise ValueError('模拟本金应在1,000元至100亿元之间。')
    return amount


def _numeric_row(row, key):
    stamp = _date(row[key])
    timestamp = stamp.strftime('%Y-%m-%d') if key == 'date' else stamp.strftime('%Y-%m-%d %H:%M:%S')
    result = {key: timestamp}
    for field in ['open', 'high', 'low', 'close', 'volume']:
        value = float(row[field])
        if not math.isfinite(value):
            raise ValueError(f'{timestamp} {field} 含无效数字。')
        result[field] = value
    amount = row.get('amount')
    result['amount'] = None if amount is None or pd.isna(amount) else float(amount)
    if result['amount'] is not None and (not math.isfinite(result['amount']) or result['amount'] < 0):
        raise ValueError(f'{timestamp} 成交额不合法。')
    if (min(result[k] for k in ['open', 'high', 'low', 'close']) <= 0 or result['volume'] < 0 or
            result['low'] > min(result['open'], result['close']) + 1e-9 or
            result['high'] + 1e-9 < max(result['open'], result['close'])):
        raise ValueError(f'{timestamp} 开高低收或成交量不合法。')
    return result


def _frame(rows, key):
    result = pd.DataFrame(rows)
    result.index = pd.to_datetime(result.pop(key))
    if key == 'date':
        result['open_time'] = result.index + pd.Timedelta(hours=9, minutes=30)
        result.index = result.index + pd.Timedelta(hours=15)
    else:
        result['open_time'] = result.index - pd.Timedelta(hours=1)
    return result


class Top5Service:
    def __init__(self, folder=None):
        profile = Path(folder or os.environ.get('SIMPLE_ETF_HOME') or
                       Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'SimpleETFSimulator')
        self.folder = profile / '恒生指数优选'
        self.folder.mkdir(parents=True, exist_ok=True)
        self._lock = _lock_for(self.folder)
        self._cache = {}
        self._signals_cache = {}
        self._state_path = self.folder / '设置.json'
        with self._lock:
            if not self._state_path.exists():
                seed = self._seed()
                snapshot_id = self._store_snapshot(seed)
                _write(self._state_path, {'schema': VERSION, 'snapshot_id': snapshot_id,
                                          'created_at': _now(), 'last_refresh': None})
            self.settings = _read(self._state_path)
            if self.settings.get('schema') != VERSION:
                raise ValueError('恒生指数优选数据版本不兼容，请使用对应版本打开。')
            self._snapshot(self.settings['snapshot_id'])

    def _seed(self):
        daily = [_numeric_row(row, 'date') for row in pd.read_csv(DATA / 'daily.csv').to_dict('records')]
        hourly = [_numeric_row(row, 'datetime') for row in pd.read_csv(DATA / 'hourly.csv').to_dict('records')]
        calendar = _read(DATA / 'calendar.json')
        seed = dict(schema='chinext.snapshot.v1', daily=daily, hourly=hourly, calendar=calendar,
                    parent=None, created_at='2026-09-16-frozen-seed',
                    provenance={'type': '已核验研究冻结行情', 'source_manifest': _read(DATA / 'data_manifest.json'),
                                'source_sha256': {name: hashlib.sha256((DATA / name).read_bytes()).hexdigest()
                                                  for name in ['daily.csv', 'hourly.csv', 'calendar.json']}},
                    warnings=['60分钟行情为新浪口径；与腾讯日线个别价格及成交量存在差别，保留原数据。'])
        self._validate_snapshot(seed)
        return seed

    def _validate_snapshot(self, snap):
        sessions = snap['calendar']['sessions']
        known = set(sessions)
        if sorted(set(sessions)) != sessions:
            raise ValueError('交易日历不递增或存在重复。')
        for key, rows in [('date', snap['daily']), ('datetime', snap['hourly'])]:
            times = [r[key] for r in rows]
            if not times or times != sorted(set(times)):
                raise ValueError('行情必须非空、严格递增且无重复。')
            for r in rows:
                _numeric_row(r, key)
                if r[key][:10] not in known:
                    raise ValueError(f'{r[key]} 不在已核验交易日历中。')
            included_days = sorted(set(t[:10] for t in times))
            expected_days = [d for d in sessions if included_days[0] <= d <= included_days[-1]]
            if included_days != expected_days:
                raise ValueError('行情中缺少完整交易日；不补造缺失价格。')
        grouped = {}
        for row in snap['hourly']:
            grouped.setdefault(row['datetime'][:10], []).append(row['datetime'][11:])
        last = max(grouped)
        for day, times in grouped.items():
            if times != HOURS[:len(times)] or len(times) > 4 or (day != last and len(times) != 4):
                raise ValueError(f'{day} 60分钟K线不连续或时段不合法。')
        daily_days = {r['date'] for r in snap['daily']}
        if any(len(times) == 4 and day not in daily_days for day, times in grouped.items()):
            raise ValueError('完整分钟交易日缺少正式日线，暂不发布该日15点柱。')

    def _store_snapshot(self, snap):
        sid = _digest(snap)
        path = self.folder / '行情快照' / (sid + '.json')
        if path.exists():
            if _digest(_read(path)) != sid:
                raise ValueError('已存行情快照哈希不符。')
        else:
            _write(path, snap)
        self._cache[sid] = snap
        return sid

    def _snapshot(self, sid=None):
        sid = sid or self.settings['snapshot_id']
        if len(sid) != 64 or any(c not in '0123456789abcdef' for c in sid):
            raise ValueError('行情快照编号无效。')
        if sid not in self._cache:
            snap = _read(self.folder / '行情快照' / (sid + '.json'))
            if _digest(snap) != sid:
                raise ValueError('行情快照遭到修改，已停止使用。')
            self._cache[sid] = snap
        return self._cache[sid]

    def _frames(self, snapshot_id=None, through=None):
        snap = self._snapshot(snapshot_id)
        daily = _frame(snap['daily'], 'date')
        hourly = _frame(snap['hourly'], 'datetime')
        cutoff = _date(through) if through is not None else hourly.index[-1]
        daily = daily.loc[daily.index <= cutoff]
        hourly = hourly.loc[hourly.index <= cutoff]
        if hourly.empty:
            raise ValueError('所选时间尚无真实60分钟行情。')
        calendar = pd.DatetimeIndex(pd.to_datetime(snap['calendar']['sessions']))
        weekly = engine.aggregate_bars(daily, hourly, 'W', calendar)
        return daily, hourly, weekly

    def _signals(self, strategy_id, snapshot_id=None, through=None):
        if strategy_id not in BY_ID:
            raise ValueError('未知优选策略。')
        sid = snapshot_id or self.settings['snapshot_id']
        key = (sid, str(through), strategy_id)
        if key in self._signals_cache:
            return self._signals_cache[key]
        _, hourly, weekly = self._frames(sid, through)
        if strategy_id == 'T5VOTE':
            model = {i: make_signals(hourly, i) for i in [4, 8, 11]}
            result = engine.combine_same(model, [4, 8, 11], 2, 2)
        elif strategy_id == 'T5WEEK':
            result = make_signals(weekly, 15)
        else:
            number = {'T5DON': 8, 'T5SUPER': 12, 'T5MA': 14}[strategy_id]
            result = make_signals(hourly, number)
        self._signals_cache[key] = result
        if len(self._signals_cache) > 60:
            self._signals_cache.pop(next(iter(self._signals_cache)))
        return result

    def list_strategies(self):
        return deepcopy(STRATEGIES)

    def info(self):
        snap = self._snapshot()
        groups = {}
        for r in snap['hourly']:
            groups[r['datetime'][:10]] = groups.get(r['datetime'][:10], 0) + 1
        complete = [d for d, n in groups.items() if n == 4 and d <= snap['daily'][-1]['date']]
        return dict(latest_daily=max(complete), latest_source_daily=snap['daily'][-1]['date'],
                    latest_bar=snap['hourly'][-1]['datetime'], data_start=snap['hourly'][0]['datetime'][:10],
                    snapshot_id=self.settings['snapshot_id'], calendar_end=snap['calendar']['verified_through'],
                    hourly_bars=len(snap['hourly']), daily_bars=len(snap['daily']),
                    warnings=deepcopy(snap.get('warnings', [])), folder=str(self.folder),
                    default_start='2023-01-03', engine=VERSION)

    def compare(self, start='2023-01-03', end=None, capital=100000, progress=None):
        progress = progress or (lambda _: None)
        with self._lock:
            amount = _capital(capital)
            meta = self.info()
            requested_start = _date(start).normalize()
            requested_end = _date(end or meta['latest_daily']).normalize()
            if requested_start < _date(meta['data_start']):
                raise ValueError(f'真实60分钟行情从{meta["data_start"]}开始，不能使用更早的比较起点。')
            if requested_end > _date(meta['latest_daily']):
                raise ValueError(f'历史比较仅支持完整交易日，最新为{meta["latest_daily"]}。盘中完整柱请查看信号或持续账户。')
            cutoff = requested_end + pd.Timedelta(hours=15)
            _, grid, _ = self._frames(through=cutoff)
            available = grid.index.normalize().unique()
            selected = available[(available >= requested_start) & (available <= requested_end)]
            if len(selected) < 2:
                raise ValueError('历史比较至少需要两个有真实行情的完整交易日。')
            actual_start, actual_end = selected[0].strftime('%Y-%m-%d'), selected[-1].strftime('%Y-%m-%d')
            rows, curves = [], {}
            cases = self.list_strategies() + [dict(id='BENCH', name='恒生指数ETF买入并持有', timeframe='基准')]
            for number, strategy in enumerate(cases, 1):
                progress(f'比较 {number}/{len(cases)}：{strategy["name"]}')
                code = strategy['id']
                sig = (pd.DataFrame({'entry': False, 'exit': False, 'ready': True}, index=grid.index)
                       if code == 'BENCH' else self._signals(code, through=cutoff))
                m, day, _, trades, annual = engine.simulate(
                    grid, sig, actual_start, code, fixed_hold=20 if code == 'T5WEEK' else None,
                    initial=amount, benchmark=code == 'BENCH', terminal_liquidation=True)
                rows.append(_clean(dict(id=code, name=strategy['name'], timeframe=strategy['timeframe'],
                                        parameters=strategy.get('parameters', ''), **m,
                                        annual=annual, trade_detail=trades)))
                curves[code] = [{'date': str(t.date()), 'equity': float(v)} for t, v in day.equity.items()]
            return dict(start=actual_start, end=actual_end, capital=amount, rows=rows, curves=curves,
                        snapshot_id=self.settings['snapshot_id'],
                        warnings=['比较采用末个交易日不新开仓、期末统一扣费清算；持续账户保留持仓，结果口径不同。',
                                  '此页是同一ETF的五套择时模型，不将它们同时叠加为五倍仓位。'] + meta['warnings'])

    def signal_summary(self):
        with self._lock:
            meta = self.info()
            output = []
            for strategy in STRATEGIES:
                sig = self._signals(strategy['id'])
                if sig.empty:
                    row = dict(last_bar=None, ready=False, entry=False, exit=False,
                               signal='等待完整K线', detail='尚无足够完整K线。')
                else:
                    last = sig.iloc[-1]
                    ready, entry, leave = bool(last.ready), bool(last.entry), bool(last['exit'])
                    state = engine.signal_state(sig).iloc[-1]
                    text = ('预热等待' if not ready else '满足入场条件' if entry else
                            '退出信号' if leave else '模型保持多头' if state == 1 else '模型保持现金')
                    detail = ('仅在新完成周K线时判断入场；已持仓账户按20交易日时钟退出。'
                              if strategy['id'] == 'T5WEEK' else '这是指标模型状态，实际账户还需检查持仓、待执行指令及T+1。')
                    row = dict(last_bar=str(sig.index[-1]), ready=ready, entry=entry, exit=leave,
                               signal=text, detail=detail)
                output.append(dict(id=strategy['id'], name=strategy['name'], timeframe=strategy['timeframe'], **row))
            return dict(as_of=meta['latest_bar'], complete_day=meta['latest_daily'], rows=output,
                        snapshot_id=meta['snapshot_id'], warnings=meta['warnings'])

    def _account_path(self, account_id):
        if len(str(account_id)) != 32 or any(c not in '0123456789abcdef' for c in str(account_id)):
            raise ValueError('账户编号无效。')
        return self.folder / '账户' / (str(account_id) + '.json')

    def _load_account(self, account_id):
        account = _read(self._account_path(account_id))
        if account.get('engine') != VERSION or account.get('strategy_id') not in BY_ID:
            raise ValueError('该账户的策略或版本不兼容。')
        verify = {k: v for k, v in account.items() if k != 'integrity'}
        if account.get('integrity') != _digest(verify):
            raise ValueError('账户文件完整性校验失败，已停止接续。')
        return account

    def _save_account(self, account):
        account = _clean(account)
        account.pop('integrity', None)
        account['integrity'] = _digest(account)
        _write(self._account_path(account['id']), account)

    @staticmethod
    def _summary(account):
        state = account.get('state', {})
        return dict(id=account['id'], name=account['name'], strategy_id=account['strategy_id'],
                    strategy_name=BY_ID[account['strategy_id']]['name'], start=account['start'], capital=account['capital'],
                    last_bar=account.get('through'), equity=account.get('metrics', {}).get('final_equity', account['capital']),
                    cash=state.get('cash', account['capital']), shares=state.get('shares', 0),
                    total_return=account.get('metrics', {}).get('total_return', 0),
                    trades=account.get('metrics', {}).get('trades', 0),
                    snapshot_id=account['snapshot_id'], held_trading_days=state.get('held_trading_days', 0),
                    status='持有恒生指数ETF' if state.get('shares', 0) else '持有现金')

    def list_accounts(self):
        with self._lock:
            paths = sorted((self.folder / '账户').glob('*.json'))
            return [self._summary(self._load_account(p.stem)) for p in paths]

    def account_detail(self, account_id):
        with self._lock:
            account = self._load_account(account_id)
            return dict(account=self._summary(account), trades=deepcopy(account.get('trades', [])),
                        events=deepcopy(account.get('events', [])), ledger=deepcopy(account.get('ledger', [])),
                        pending=deepcopy(account.get('pending', {})), metrics=deepcopy(account.get('metrics', {})),
                        history=deepcopy(account.get('history', [])),
                        warnings=['持续账户不期末强制清仓；买入当日不可卖，退出指令会保留至下一交易日。',
                                  '账户策略固定，不能在同一账本里切换到另一策略后混算。'])

    def create_account(self, name, strategy, start, capital):
        with self._lock:
            if strategy not in BY_ID:
                raise ValueError('请选择五套优选策略之一。')
            name = str(name).strip()
            if not name or len(name) > 80:
                raise ValueError('账户名称应为1至80个字符。')
            first = _date(start).normalize()
            _, grid, _ = self._frames()
            if first < grid.index[0].normalize():
                raise ValueError('起点早于真实60分钟数据；不能用日线补造盘中交易。')
            sessions = grid.index.normalize().unique()
            eligible = sessions[sessions >= first]
            if not len(eligible):
                raise ValueError('起点之后还没有真实完整60分钟K线。')
            first = eligible[0]
            account = dict(id=uuid.uuid4().hex, engine=VERSION, name=name, strategy_id=strategy,
                           start=first.strftime('%Y-%m-%d'), capital=_capital(capital), created_at=_now(),
                           snapshot_id=self.settings['snapshot_id'], through=None,
                           history=[], ledger=[], trades=[], events=[])
            self._save_account(account)
            try:
                return self.advance_account(account['id'], first.strftime('%Y-%m-%d'))
            except Exception:
                # Keep the created valid empty account for diagnosis/retry; never
                # erase an existing account or alter any nine-strategy file.
                raise

    def _assert_extension(self, old, new, through):
        for key, collection in [('date', 'daily'), ('datetime', 'hourly')]:
            old_rows = old[collection]
            new_prefix = new[collection][:len(old_rows)]
            if old_rows != new_prefix:
                raise ValueError('新行情修改或删除了账户使用的历史价格，拒绝接续。')
        old_sessions = [d for d in old['calendar']['sessions'] if d <= through[:10]]
        new_sessions = [d for d in new['calendar']['sessions'] if d <= through[:10]]
        if old_sessions != new_sessions:
            raise ValueError('新日历修改了账户已发生的交易日，拒绝接续。')

    def advance_account(self, account_id, end=None):
        with self._lock:
            account = self._load_account(account_id)
            current_sid = self.settings['snapshot_id']
            latest = self._snapshot(current_sid)['hourly'][-1]['datetime']
            desired = _date(end or latest)
            if end is not None and len(str(end)) <= 10:
                desired = desired.normalize() + pd.Timedelta(hours=15)
            cutoff = min(desired, _date(latest))
            _, grid, _ = self._frames(current_sid, cutoff)
            grid = grid.loc[grid.index <= cutoff]
            relevant = grid.loc[grid.index.normalize() >= _date(account['start'])]
            if relevant.empty:
                raise ValueError('所选终点早于账户起点。')
            through = str(relevant.index[-1])
            if account.get('through') and through <= account['through']:
                return self.account_detail(account_id)
            if account.get('through'):
                self._assert_extension(self._snapshot(account['snapshot_id']), self._snapshot(current_sid), account['through'])
            sig = self._signals(account['strategy_id'], current_sid, cutoff)
            m, _, book, trades, _ = engine.simulate(
                grid, sig, account['start'], account_id,
                fixed_hold=20 if account['strategy_id'] == 'T5WEEK' else None,
                initial=account['capital'], terminal_liquidation=False)
            new_ledger = _clean(book[['datetime', 'cash', 'shares', 'equity', 'exposure']].to_dict('records'))
            events = _clean(book.attrs['events'])
            if account.get('ledger'):
                if _canonical(new_ledger[:len(account['ledger'])]) != _canonical(account['ledger']):
                    raise ValueError('接续会改写既有逐K线账本，已停止，原账户保持不变。')
                if _canonical(events[:len(account['events'])]) != _canonical(account['events']):
                    raise ValueError('接续会改写既有成交记录，已停止。')
            state = _clean(book.attrs['state'])
            last_signal = sig.loc[sig.index <= cutoff].iloc[-1] if len(sig) else None
            just_closed_signal = bool(len(sig) and sig.index[-1] == relevant.index[-1])
            awaiting_entry = bool(just_closed_signal and last_signal.ready and last_signal.entry and state['shares'] == 0)
            awaiting_exit = bool(state['pending_exit'] or (just_closed_signal and last_signal.ready and last_signal['exit'] and state['shares'] > 0))
            pending = dict(buy=awaiting_entry, sell=awaiting_exit,
                           description=('等待下一真实完整K线开盘模拟卖出；买入当日则延到下一交易日。' if awaiting_exit else
                                        '等待下一真实完整K线开盘模拟买入。' if awaiting_entry else '暂无待执行指令。'))
            account.update(snapshot_id=current_sid, through=through, state=state, metrics=_clean(m),
                           ledger=new_ledger, trades=_clean(trades), events=events, pending=pending,
                           updated_at=_now())
            account['history'].append(dict(through=through, snapshot_id=current_sid,
                                           ledger_hash=_digest(new_ledger), event_count=len(events)))
            self._save_account(account)
            return self.account_detail(account_id)

    @staticmethod
    def _merge_rows(old, additions, key):
        old_map = {r[key]: r for r in old}
        end = old[-1][key]
        additions_map = {}
        for raw in additions:
            row = _numeric_row(raw, key)
            stamp = row[key]
            if stamp in additions_map and additions_map[stamp] != row:
                raise ValueError(f'来源重复返回不同的{stamp}行情，保留旧快照。')
            additions_map[stamp] = row
            if stamp in old_map and row != old_map[stamp]:
                changed = [f for f in row if row[f] != old_map[stamp].get(f)]
                # Tencent converts amount from 10,000 CNY to CNY; binary
                # multiplication can differ from a CSV round-trip by 1 ULP.
                # Only this unused diagnostic field permits representational
                # error.  Keep the old value; never rewrite a historical row.
                if changed == ['amount'] and row['amount'] is not None and old_map[stamp]['amount'] is not None:
                    old_amount = old_map[stamp]['amount']
                    if abs(row['amount'] - old_amount) <= max(1e-8, 4 * math.ulp(old_amount)):
                        changed = []
                if changed:
                    raise ValueError(f'来源修订了历史行情{stamp}（{",".join(changed)}），拒绝覆盖；原快照保留。')
            if stamp <= end and stamp not in old_map:
                raise ValueError(f'新来源插入既有历史范围内的{stamp}，拒绝回写。')
        return old + [additions_map[t] for t in sorted(additions_map) if t > end]

    def refresh(self, progress=None):
        progress = progress or (lambda _: None)
        from chinext_refresh_support import fetch_market_updates
        with self._lock:
            old = self._snapshot()
            previous_sid = self.settings['snapshot_id']
            try:
                progress('抓取真实日线与完整60分钟K线…')
                fresh = fetch_market_updates(old['daily'][-1]['date'], old['hourly'][-1]['datetime'], progress)
                daily = self._merge_rows(old['daily'], fresh.get('daily', []), 'date')
                hourly = self._merge_rows(old['hourly'], fresh.get('hourly', []), 'datetime')
                warnings = list(fresh.get('warnings', []))
                daily_dates = {r['date'] for r in daily}
                hold_from = next((r['datetime'] for r in hourly if r['datetime'].endswith('15:00:00')
                                  and r['datetime'][:10] not in daily_dates), None)
                if hold_from:
                    hourly = [r for r in hourly if r['datetime'] < hold_from]
                    warnings.append(f'{hold_from[:10]}正式日线尚未取得，15点及后续分钟柱暂缓入库，以保护周线与账户前缀。')
                if daily == old['daily'] and hourly == old['hourly']:
                    return dict(updated=False, snapshot_id=previous_sid, rows_added={'daily': 0, 'hourly': 0},
                                latest_daily=self.info()['latest_daily'], latest_bar=self.info()['latest_bar'],
                                warnings=warnings or ['没有新的完整K线，保留既有快照。'])
                updated = dict(schema=old['schema'], daily=daily, hourly=hourly, calendar=deepcopy(old['calendar']),
                               parent=previous_sid, created_at=fresh.get('fetched_at', _now()),
                               provenance={'type': '公开真实行情追加', 'sources': fresh.get('sources', []),
                                           'previous_snapshot': previous_sid},
                               warnings=old.get('warnings', [])[:1] + warnings)
                self._validate_snapshot(updated)
                new_sid = self._store_snapshot(updated)
                self.settings.update(snapshot_id=new_sid, last_refresh=_now())
                _write(self._state_path, self.settings)
                progress('已校验并保存新的不可变行情快照。')
                return dict(updated=True, snapshot_id=new_sid,
                            rows_added={'daily': len(daily)-len(old['daily']), 'hourly': len(hourly)-len(old['hourly'])},
                            latest_daily=self.info()['latest_daily'], latest_bar=self.info()['latest_bar'], warnings=warnings)
            except Exception as exc:
                # Never promote a partially fetched/revised snapshot or mutate
                # any paper account during network refresh.
                progress('刷新失败，已保留上一份行情快照。')
                raise ValueError('恒生指数行情更新失败，旧快照和账户均保留：' + str(exc)) from exc

    def export_account(self, account_id, dest):
        with self._lock:
            account = self._load_account(account_id)
            target = Path(dest)
            if target.exists() and target.is_dir():
                target = target / ('恒生指数优选账户_' + account_id[:8] + '.zip')
            elif target.suffix.lower() != '.zip':
                target = target.with_suffix('.zip')
            target.parent.mkdir(parents=True, exist_ok=True)
            files = ['账户.json', '逐笔交易.csv', '全部成交事件.csv', '逐K线账本.csv', '行情快照.json', '说明.txt']
            with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr(files[0], _canonical(account))
                for name, key in [(files[1], 'trades'), (files[2], 'events'), (files[3], 'ledger')]:
                    archive.writestr(name, pd.DataFrame(account.get(key, [])).to_csv(index=False).encode('utf-8-sig'))
                archive.writestr(files[4], _canonical(self._snapshot(account['snapshot_id'])))
                archive.writestr(files[5], ('恒生指数优选独立模拟账户；仅159915，无真实下单。\n'
                    '持续账户不期末清仓，策略固定；费用万三最低5元、滑点万二、100份整数手、T+1。\n'
                    '导出含账户、成交、逐K线账本及原始不可变行情快照，用于核验与备份。\n'
                    '导入时将验证账本并新建独立副本，不覆盖原账户。').encode('utf-8'))
            return dict(path=str(target), files=files)

    def import_account(self, path):
        """Verify an archive completely, then create a separate account id."""
        with self._lock:
            allowed = {'账户.json', '逐笔交易.csv', '全部成交事件.csv', '逐K线账本.csv', '行情快照.json', '说明.txt'}
            with zipfile.ZipFile(Path(path), 'r') as archive:
                names = archive.namelist()
                if len(names) != len(set(names)) or not set(names).issubset(allowed):
                    raise ValueError('备份ZIP包含重复、未知或带目录路径的条目，拒绝导入。')
                if not {'账户.json', '行情快照.json'}.issubset(names):
                    raise ValueError('备份缺少账户或行情快照。')
                if sum(x.file_size for x in archive.infolist()) > 100_000_000:
                    raise ValueError('备份解压后过大，拒绝导入。')
                account = json.loads(archive.read('账户.json').decode('utf-8-sig'))
                snap = json.loads(archive.read('行情快照.json').decode('utf-8-sig'))
            if account.get('engine') != VERSION or account.get('strategy_id') not in BY_ID:
                raise ValueError('备份策略或版本不兼容。')
            if account.get('integrity') != _digest({k: v for k, v in account.items() if k != 'integrity'}):
                raise ValueError('备份账户校验失败，未导入。')
            self._account_path(account['id'])  # Validate stored id; never use archive paths.
            _capital(account['capital'])
            _date(account['start'])
            if not account.get('through'):
                raise ValueError('备份尚无可验证的完整K线账本。')
            sid = _digest(snap)
            if sid != account.get('snapshot_id'):
                raise ValueError('备份行情哈希与账户引用不一致。')
            self._validate_snapshot(snap)
            # Evaluate imported data in memory first.  Nothing is promoted to
            # current market settings; imported snapshot remains independent.
            had_cache = sid in self._cache
            self._cache[sid] = snap
            try:
                cutoff = _date(account['through'])
                if cutoff > _date(snap['hourly'][-1]['datetime']):
                    raise ValueError('账户日期晚于备份中的真实行情。')
                _, grid, _ = self._frames(sid, cutoff)
                sig = self._signals(account['strategy_id'], sid, cutoff)
                m, _, book, trades, _ = engine.simulate(
                    grid, sig, account['start'], account['id'],
                    fixed_hold=20 if account['strategy_id'] == 'T5WEEK' else None,
                    initial=account['capital'], terminal_liquidation=False)
                rebuilt = _clean(book[['datetime', 'cash', 'shares', 'equity', 'exposure']].to_dict('records'))
                for label, actual, expected in [
                    ('逐K线账本', rebuilt, account.get('ledger')),
                    ('成交事件', _clean(book.attrs['events']), account.get('events')),
                    ('往返交易', _clean(trades), account.get('trades')),
                    ('当前持仓', _clean(book.attrs['state']), account.get('state')),
                    ('统计结果', _clean(m), account.get('metrics')),
                ]:
                    if _canonical(actual) != _canonical(expected):
                        raise ValueError(f'备份{label}与冻结行情重算不符，未导入。')
                source_id = account['id']
                account['id'] = uuid.uuid4().hex
                account['name'] = str(account['name'])[:65] + '（导入副本）'
                account['imported_from'] = source_id
                account['imported_at'] = _now()
                # Trade case ids are labels, so update them without changing
                # prices, timestamps, quantities or the independently checked cash.
                for trade in account.get('trades', []):
                    trade['case_id'] = account['id']
                self._store_snapshot(snap)
                self._save_account(account)
                return self.account_detail(account['id'])
            except Exception:
                if not had_cache:
                    self._cache.pop(sid, None)
                raise
