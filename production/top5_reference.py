"""Read-only reference allocations for the five ChiNext strategies.

The virtual ledger tracks the fixed holding clock and T+1 from 2023-01-03.
It never creates/advances a saved account, fetches quotes, or places orders.
Top-level budgets always allocate the input capital, not historical profits.
"""
from __future__ import annotations

from collections import OrderedDict
from contextlib import nullcontext
from copy import deepcopy
import hashlib
import json
import threading
from types import CodeType

import pandas as pd

import chinext_engine as engine
import chinext_indicators as indicators
from chinext_service import _capital


DEFAULT_START = '2023-01-03'
REFERENCE_VERSION = 'top5.readonly.reference.v1.2.1.20260916'
_CACHE = OrderedDict()
_FRAME_CACHE = OrderedDict()
_CACHE_LOCK = threading.RLock()
_CACHE_LIMIT = 64


def _code_fingerprint(service):
    """Work with source modules and frozen PyInstaller bytecode alike."""
    digest = hashlib.sha256(REFERENCE_VERSION.encode('ascii'))
    functions = [reference_plan, _compute, _reason, _code_fingerprint, _stable_code,
                 engine.simulate, engine.project_signals, engine.combine_same,
                 service._frames, service._signals]
    functions.extend(value for value in vars(indicators).values()
                     if callable(value) and getattr(value, '__module__', None) == indicators.__name__)
    for function in functions:
        code = getattr(getattr(function, '__func__', function), '__code__', None)
        if code is not None:
            digest.update(json.dumps(_stable_code(code), ensure_ascii=True,
                                     separators=(',', ':')).encode('ascii'))
    return digest.hexdigest()


def _stable_code(value):
    # marshal serialisation flags can depend on runtime string interning.
    # These semantic fields stay stable before/after CPython specialisation,
    # and are present when code is loaded from a frozen PyInstaller archive.
    if isinstance(value, CodeType):
        return ['code', value.co_code.hex(), list(value.co_names), list(value.co_varnames),
                value.co_argcount, value.co_posonlyargcount, value.co_kwonlyargcount,
                value.co_flags, [_stable_code(c) for c in value.co_consts]]
    if isinstance(value, (tuple, list)):
        return [type(value).__name__, [_stable_code(v) for v in value]]
    if isinstance(value, frozenset):
        return ['frozenset', sorted(repr(v) for v in value)]
    return [type(value).__name__, repr(value)]


def _reason(strategy_id, held, held_days, pending_buy, pending_sell, t1, ready):
    if not ready:
        return '完整K线尚不足以完成指标预热，参考目标保持现金。'
    if pending_sell:
        trigger = ('固定20个交易日期限已满' if strategy_id == 'T5WEEK' else '退出条件已确认')
        tail = ('参考账户为当日买入，T+1不允许当日卖出；等待下一交易日的真实完整K线确认后模拟成交。'
                if t1 else '尚未取得可执行的下一根真实完整K线，参考账户还未卖出。')
        return trigger + '，参考目标改为现金。' + tail
    if pending_buy:
        return ('最新完整K线满足入场条件，参考目标改为创业板ETF；'
                '下一根真实完整K线尚未到达，参考账户仍是现金，未视为已经买入。')
    if held:
        if strategy_id == 'T5WEEK':
            return (f'只读参考账户仍在固定持有期，当前为第{held_days}个交易日；'
                    '即使最新周线指标转弱，也不提前退出。第20日15:00形成退出指令，第21交易日开盘执行。')
        return '只读参考账户已经持有创业板ETF，尚无待执行退出指令，参考目标继续持有。'
    return ('只读参考账户当前为空仓，最新完整K线没有形成新的待执行入场指令，参考目标保持现金。'
            + ('旧周线曾经多头不代表一直持有；需等待新的完整周K线入场条件。' if strategy_id == 'T5WEEK' else ''))


def _compute(service, strategy, capital, snapshot_id, fingerprint):
    frame_key = (snapshot_id, fingerprint)
    if frame_key not in _FRAME_CACHE:
        _FRAME_CACHE[frame_key] = service._frames(snapshot_id)
        while len(_FRAME_CACHE) > 3:
            _FRAME_CACHE.popitem(last=False)
    else:
        _FRAME_CACHE.move_to_end(frame_key)
    frames = _FRAME_CACHE[frame_key]
    _, grid, _ = frames
    eligible = grid.loc[grid.index.normalize() >= pd.Timestamp(DEFAULT_START)]
    if eligible.empty:
        raise ValueError('2023-01-03之后尚无真实完整60分钟K线，不能计算优选策略参考仓位。')
    # Invoke the unchanged service directly.  Do not monkeypatch its methods:
    # the same service may also be used by the refresh worker.
    signals = service._signals(strategy['id'], snapshot_id)
    as_of = eligible.index[-1]
    # _frames and _signals both use the same immutable snapshot.  Never use
    # a live tick or an incomplete candle from the separate intraday UI.
    signals = signals.loc[signals.index <= as_of]
    metrics, _, book, _, _ = engine.simulate(
        grid, signals, DEFAULT_START, 'READONLY-REFERENCE-' + strategy['id'],
        fixed_hold=20 if strategy['id'] == 'T5WEEK' else None,
        initial=capital, terminal_liquidation=False)
    state = book.attrs['state']
    held = int(state['shares']) > 0
    held_days = int(state['held_trading_days'])
    latest = signals.iloc[-1] if not signals.empty else None
    ready = bool(latest is not None and latest.ready)
    signal_bar = str(signals.index[-1]) if latest is not None else None
    just_closed = bool(latest is not None and signals.index[-1] == as_of)
    # A signal on the last completed close has no later observed execution
    # bar yet.  Earlier closes were already processed by the virtual ledger.
    pending_buy = bool(ready and just_closed and latest.entry and not held)
    pending_sell = bool(held and (state['pending_exit'] or
                        (ready and just_closed and latest['exit'])))
    buy_record = state.get('buy_record') or {}
    t1_blocked = bool(pending_sell and buy_record and
                      pd.Timestamp(buy_record['buy_time']).normalize() == as_of.normalize())
    weight = 0 if not ready or pending_sell else 1 if held or pending_buy else 0
    if not ready:
        label = '预热等待'
    elif pending_sell:
        label = '待卖出（T+1）' if t1_blocked else '待卖出'
    elif pending_buy:
        label = '待买入'
    elif held:
        label = '继续持有'
    else:
        label = '现金等待'
    execution_after = ('下一交易日的真实完整K线开盘' if t1_blocked else
                       '下一根真实完整K线开盘') if pending_buy or pending_sell else None
    reason = _reason(strategy['id'], held, held_days, pending_buy, pending_sell, t1_blocked, ready)
    snapshot = service._snapshot(snapshot_id)
    warnings = [
        '这是按独立参考本金计算的资金分配，不是实际账户仓位或下单手数；不会保存或推进任何账户。',
        '只读参考账户从2023-01-03跟踪完整K线，以识别持有期和T+1；未完成的盘中K线不参与。',
    ] + list(snapshot.get('warnings', []))
    pending = dict(buy=pending_buy, sell=pending_sell, t1_blocked=t1_blocked,
                   execution_after=execution_after,
                   description=reason if pending_buy or pending_sell else '暂无待执行参考指令。')
    result = dict(
        strategy=strategy['id'], name=strategy['name'], timeframe=strategy['timeframe'],
        parameters=strategy['parameters'], capital=capital, as_of=str(as_of),
        signal_bar=signal_bar, start=DEFAULT_START, ready=ready, signal=label,
        weight=weight, budgets={'sz159915': capital * weight}, cash=capital * (1 - weight),
        reason=reason, pending=pending, held_days=held_days, warnings=warnings,
        snapshot_id=snapshot_id, code_fingerprint=fingerprint,
        reference_state=dict(
            cash=float(state['cash']), shares=int(state['shares']),
            equity=float(metrics['final_equity']), held_trading_days=held_days,
            pending_exit=bool(state['pending_exit']), last_bar=str(as_of),
            position='创业板ETF' if held else '现金', buy_time=buy_record.get('buy_time'),
            source='2023-01-03起只读虚拟参考账户', not_an_order=True,
            terminal_liquidation=False),
    )
    return engine.clean_json(result)


def reference_plan(service, strategy_id, capital):
    """Return a JSON-safe reference plan; invalid inputs raise ValueError.

    Top-level ``weight`` is the 0/1 desired next allocation; ``pending``
    explains why it can differ from the virtual ledger's current position.
    ``budgets`` and ``cash`` partition exactly the independently supplied
    capital.  ``reference_state`` is only clock/settlement context, never an
    instruction to trade its number of shares.
    """
    try:
        amount = _capital(capital)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError('参考本金应为1,000元至100亿元之间的有限数字。') from exc
    if not isinstance(strategy_id, str):
        raise ValueError('请选择五套优选策略之一。')
    service_lock = getattr(service, '_lock', None)
    with service_lock if service_lock is not None else nullcontext():
        catalog = {row['id']: row for row in service.list_strategies()}
        if strategy_id not in catalog:
            raise ValueError('请选择五套优选策略之一。')
        snapshot_id = service.settings['snapshot_id']
        fingerprint = _code_fingerprint(service)
        key = (snapshot_id, fingerprint, strategy_id, amount.hex(), DEFAULT_START)
        # The lock covers cache misses as well, so simultaneous UI requests
        # do not perform the same full reference simulation repeatedly.
        with _CACHE_LOCK:
            if key in _CACHE:
                _CACHE.move_to_end(key)
                return deepcopy(_CACHE[key])
            result = _compute(service, catalog[strategy_id], amount, snapshot_id, fingerprint)
            _CACHE[key] = deepcopy(result)
            while len(_CACHE) > _CACHE_LIMIT:
                _CACHE.popitem(last=False)
            return deepcopy(result)
