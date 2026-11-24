"""Causal, timeframe-neutral signals for the 15-strategy ChiNext study.

All lookbacks count the rows supplied by the caller.  Bars must be complete,
ascending and unique; resampling, execution, cash, lots, costs, settlement and
the 20-trading-day holding clock belong to the caller's ledger.

Public API: make_signals(bars, strategy_id, variant='base') returns the same
index and exactly three boolean columns: entry, exit, ready.  Entry/exit are
orders requested at that bar's close, never permission to trade at that close.
PARAMS stores base parameters and NEAR_PARAMS stores the fixed sensitivity set.
Result.attrs['metadata'] records the actual parameter set and warmup.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import numpy as np
import pandas as pd


STRATEGY_NAMES = {
    1: 'SKDJ波段', 2: 'TRIX趋势', 3: 'MACD金叉死叉', 4: '双均线',
    5: 'RSI强弱趋势', 6: '布林带突破', 7: 'DMI＋ADX趋势过滤',
    8: '唐奇安通道突破', 9: 'ROC动量', 10: 'CCI强势',
    11: 'OBV量能趋势', 12: 'Supertrend超级趋势', 13: 'RSI超跌反转',
    14: '50根均线择时', 15: 'SKDJ＋TRIX固定持有20交易日',
}

PARAMS = {
    1: {'n': 9, 'm': 3},
    2: {'n': 12, 'signal': 9},
    3: {'fast': 12, 'slow': 26, 'signal': 9},
    4: {'fast': 20, 'slow': 60},
    5: {'n': 14, 'threshold': 50.0},
    6: {'n': 20, 'multiplier': 2.0, 'ddof': 0},
    7: {'n': 14, 'adx_n': 14, 'threshold': 25.0},
    8: {'entry_n': 20, 'exit_n': 10},
    9: {'n': 20, 'threshold': 0.0},
    10: {'n': 20, 'entry_threshold': 100.0, 'exit_threshold': 0.0},
    11: {'n': 20},
    12: {'atr_n': 10, 'multiplier': 3.0},
    13: {'n': 14, 'entry_threshold': 30.0, 'exit_threshold': 70.0},
    14: {'n': 50},
    15: {'skdj_n': 3, 'skdj_m': 5, 'trix_n': 4, 'trix_signal': 8,
         'holding_trading_days': 20},
}

# A single predeclared neighbouring set.  This is a robustness check, not a
# parameter search; reporting code must not select whichever set earns more.
NEAR_PARAMS = {
    1: {'n': 11, 'm': 4},
    2: {'n': 14, 'signal': 10},
    3: {'fast': 14, 'slow': 30, 'signal': 10},
    4: {'fast': 24, 'slow': 72},
    5: {'n': 17, 'threshold': 50.0},
    6: {'n': 24, 'multiplier': 2.2, 'ddof': 0},
    7: {'n': 17, 'adx_n': 17, 'threshold': 25.0},
    8: {'entry_n': 24, 'exit_n': 12},
    9: {'n': 24, 'threshold': 0.0},
    10: {'n': 24, 'entry_threshold': 100.0, 'exit_threshold': 0.0},
    11: {'n': 24},
    12: {'atr_n': 12, 'multiplier': 3.3},
    13: {'n': 17, 'entry_threshold': 30.0, 'exit_threshold': 70.0},
    14: {'n': 60},
    15: {'skdj_n': 4, 'skdj_m': 6, 'trix_n': 5, 'trix_signal': 10,
         'holding_trading_days': 20},
}


def get_parameters(strategy_id: int, variant: str = 'base') -> dict[str, Any]:
    if strategy_id not in STRATEGY_NAMES:
        raise ValueError(f'Unknown strategy_id: {strategy_id!r}; expected 1..15')
    if variant not in ('base', 'near'):
        raise ValueError(f'Unknown variant: {variant!r}; expected base or near')
    return deepcopy((PARAMS if variant == 'base' else NEAR_PARAMS)[strategy_id])


def warmup_bars(strategy_id: int, variant: str = 'base') -> int:
    """First eligible bar is this one-based bar count; crosses need one more.

    Rolling indicators require their full windows; recursively smoothed
    indicators get extra observations beyond the first finite calculation.
    There is no claim that an EMA ever loses all dependence on its seed.
    """
    p = get_parameters(strategy_id, variant)
    if strategy_id == 1:
        return p['n'] + 3 * p['m']
    if strategy_id == 2:
        return 3 * p['n'] + p['signal']
    if strategy_id == 3:
        return p['slow'] + p['signal']
    if strategy_id == 4:
        return p['slow']
    if strategy_id in (5, 13):
        return 3 * p['n'] + 1
    if strategy_id in (6, 10, 11, 14):
        return p['n']
    if strategy_id == 7:
        return p['n'] + 3 * p['adx_n']
    if strategy_id == 8:
        return max(p['entry_n'], p['exit_n']) + 1
    if strategy_id == 9:
        return p['n'] + 1
    if strategy_id == 12:
        return 3 * p['atr_n']
    return max(p['skdj_n'] + 3 * p['skdj_m'],
               3 * p['trix_n'] + p['trix_signal'])


def _ema(s: pd.Series, n: int) -> pd.Series:
    # Preserve the original project's first-observation seed at every EMA
    # layer.  Readiness is masked at the strategy level, not between layers.
    return s.ewm(span=n, adjust=False, min_periods=1).mean()


def _wilder(s: pd.Series, n: int) -> pd.Series:
    """Wilder RMA with an exact first-n-observation arithmetic-mean seed.

    A non-finite value resets the seed so missing bars cannot silently be
    treated as observations.  The first finite n-value run produces a value.
    """
    values = s.to_numpy(dtype=float)
    out = np.full(len(values), np.nan, dtype=float)
    count, total, previous = 0, 0.0, np.nan
    for i, value in enumerate(values):
        if not np.isfinite(value):
            count, total, previous = 0, 0.0, np.nan
        elif count < n:
            total += value
            count += 1
            if count == n:
                previous = total / n
                out[i] = previous
        else:
            previous = (previous * (n - 1) + value) / n
            out[i] = previous
    return pd.Series(out, index=s.index)


def _skdj(b: pd.DataFrame, n: int, m: int) -> tuple[pd.Series, pd.Series]:
    low = b['low'].rolling(n, min_periods=n).min()
    high = b['high'].rolling(n, min_periods=n).max()
    spread = high - low
    rsv = 100.0 * (b['close'] - low) / spread.replace(0.0, np.nan)
    # Match the original project: a flat full window carries prior raw RSV,
    # seeded at 50.  No forward values are used to fill the initial window.
    carried = rsv.ffill().fillna(50.0)
    rsv = rsv.mask(spread.eq(0), carried)
    k = _ema(_ema(rsv, m), m)
    d = k.rolling(m, min_periods=m).mean()
    return k, d


def _trix(close: pd.Series, n: int, signal: int) -> tuple[pd.Series, pd.Series]:
    smoothed = _ema(_ema(_ema(close, n), n), n)
    trix = 100.0 * smoothed.pct_change(fill_method=None)
    return trix, trix.rolling(signal, min_periods=signal).mean()


def _rsi(close: pd.Series, n: int) -> pd.Series:
    change = close.diff()
    gain = _wilder(change.clip(lower=0.0), n)
    loss = _wilder((-change).clip(lower=0.0), n)
    result = 100.0 - 100.0 / (1.0 + gain / loss.replace(0.0, np.nan))
    result = result.mask(loss.eq(0) & gain.gt(0), 100.0)
    return result.mask(loss.eq(0) & gain.eq(0), 50.0)


def _true_range(b: pd.DataFrame) -> pd.Series:
    previous_close = b['close'].shift(1)
    return pd.concat([b['high'] - b['low'],
                      (b['high'] - previous_close).abs(),
                      (b['low'] - previous_close).abs()], axis=1).max(axis=1)


def _dmi(b: pd.DataFrame, n: int, adx_n: int) -> tuple[pd.Series, pd.Series, pd.Series]:
    up = b['high'].diff()
    down = -b['low'].diff()
    plus_dm = up.where((up > down) & (up > 0.0), 0.0)
    minus_dm = down.where((down > up) & (down > 0.0), 0.0)
    # No directional movement is knowable on the first input bar.
    if len(b):
        plus_dm.iloc[0] = np.nan
        minus_dm.iloc[0] = np.nan
    tr = _true_range(b)
    if len(b):
        tr.iloc[0] = np.nan
    atr = _wilder(tr, n)
    plus = 100.0 * _wilder(plus_dm, n) / atr.replace(0.0, np.nan)
    minus = 100.0 * _wilder(minus_dm, n) / atr.replace(0.0, np.nan)
    plus = plus.mask(atr.eq(0), 0.0)
    minus = minus.mask(atr.eq(0), 0.0)
    di_sum = plus + minus
    dx = 100.0 * (plus - minus).abs() / di_sum.replace(0.0, np.nan)
    dx = dx.mask(di_sum.eq(0), 0.0)
    return plus, minus, _wilder(dx, adx_n)


def _supertrend(b: pd.DataFrame, n: int, multiplier: float) -> pd.Series:
    """Return 1 for uptrend, -1 for downtrend; NaN before ATR exists."""
    atr = _wilder(_true_range(b), n)
    midpoint = (b['high'] + b['low']) / 2.0
    basic_upper = (midpoint + multiplier * atr).to_numpy(dtype=float)
    basic_lower = (midpoint - multiplier * atr).to_numpy(dtype=float)
    closes = b['close'].to_numpy(dtype=float)
    direction = np.full(len(b), np.nan, dtype=float)
    upper = lower = np.nan
    last_direction = -1.0
    for i in range(len(b)):
        if not np.isfinite(basic_upper[i] + basic_lower[i] + closes[i]):
            upper = lower = np.nan
            continue
        if not np.isfinite(upper + lower):
            upper, lower = basic_upper[i], basic_lower[i]
            last_direction = -1.0
        else:
            upper = (basic_upper[i] if basic_upper[i] < upper or closes[i - 1] > upper
                     else upper)
            lower = (basic_lower[i] if basic_lower[i] > lower or closes[i - 1] < lower
                     else lower)
            if last_direction == -1.0:
                last_direction = 1.0 if closes[i] > upper else -1.0
            else:
                last_direction = -1.0 if closes[i] < lower else 1.0
        direction[i] = last_direction
    return pd.Series(direction, index=b.index)


def _cross_up(a: pd.Series, b: pd.Series | float) -> pd.Series:
    if np.isscalar(b):
        return a.gt(b) & a.shift(1).le(b)
    return a.gt(b) & a.shift(1).le(b.shift(1))


def _cross_down(a: pd.Series, b: pd.Series | float) -> pd.Series:
    if np.isscalar(b):
        return a.lt(b) & a.shift(1).ge(b)
    return a.lt(b) & a.shift(1).ge(b.shift(1))


def _prepare(bars: pd.DataFrame, strategy_id: int) -> pd.DataFrame:
    if not isinstance(bars, pd.DataFrame):
        raise TypeError('bars must be a pandas DataFrame')
    if not bars.index.is_monotonic_increasing or not bars.index.is_unique:
        raise ValueError('bars must have a unique, ascending index')
    out = bars.rename(columns={c: c.lower() for c in bars.columns if isinstance(c, str)})
    needed = ['high', 'low', 'close'] + (['volume'] if strategy_id == 11 else [])
    missing = set(needed) - set(out.columns)
    if missing:
        raise ValueError(f'Missing required columns: {sorted(missing)}')
    if not out.columns.is_unique:
        raise ValueError('bar column names are ambiguous after lowercasing')
    out = out.copy()
    for column in needed:
        out[column] = pd.to_numeric(out[column], errors='raise')
    # A missing/invalid observed bar needs a data decision, not an implicit
    # rolling-window fill.  Indicator warmup NaNs are handled separately.
    if len(out) and not np.isfinite(out[needed].to_numpy(dtype=float)).all():
        raise ValueError('Observed OHLCV inputs contain missing/non-finite values')
    if ((out['high'] < out['low']) | (out['close'] <= 0)).any():
        raise ValueError('Invalid OHLC price values')
    if strategy_id == 11 and out['volume'].lt(0).any():
        raise ValueError('Volume must be non-negative')
    return out


def make_signals(bars: pd.DataFrame, strategy_id: int,
                 variant: str = 'base') -> pd.DataFrame:
    """Produce close-time signals; see module documentation for execution.

    Crossing strategies emit pulses; state strategies emit persistent entry
    or exit requests.  A single-position ledger ignores redundant requests.
    Strategy 15 emits entry only; its 20 trading day exit is a ledger rule.
    No strategy forces entry at the first ready bar merely because it is
    already in a bullish state, unless its published rule is state-based.
    """
    p = get_parameters(strategy_id, variant)
    b = _prepare(bars, strategy_id)
    close = b['close']
    valid_indicators: list[pd.Series] = []
    crossing = True
    rule = ''

    if strategy_id == 1:
        k, d = _skdj(b, p['n'], p['m'])
        entry, leave = _cross_up(k, d), _cross_down(k, d)
        valid_indicators = [k, d]
        rule = 'RSV -> EMA(M) -> EMA(M)=K; SMA(M,K)=D; K/D crosses'
    elif strategy_id == 2:
        trix, signal = _trix(close, p['n'], p['signal'])
        entry, leave = _cross_up(trix, signal), _cross_down(trix, signal)
        valid_indicators = [trix, signal]
        rule = 'TRIX percent change of triple EMA; signal is SMA; crosses'
    elif strategy_id == 3:
        dif = _ema(close, p['fast']) - _ema(close, p['slow'])
        dea = _ema(dif, p['signal'])
        entry, leave = _cross_up(dif, dea), _cross_down(dif, dea)
        valid_indicators = [dif, dea]
        rule = 'DIF / DEA crosses; all averages are EMA'
    elif strategy_id == 4:
        fast = close.rolling(p['fast']).mean()
        slow = close.rolling(p['slow']).mean()
        entry, leave = _cross_up(fast, slow), _cross_down(fast, slow)
        valid_indicators = [fast, slow]
        rule = 'Fast / slow SMA crosses'
    elif strategy_id == 5:
        rsi = _rsi(close, p['n'])
        entry, leave = _cross_up(rsi, p['threshold']), _cross_down(rsi, p['threshold'])
        valid_indicators = [rsi]
        rule = 'Wilder RSI crosses above/below threshold'
    elif strategy_id == 6:
        middle = close.rolling(p['n']).mean()
        upper = middle + p['multiplier'] * close.rolling(p['n']).std(ddof=p['ddof'])
        entry, leave = _cross_up(close, upper), _cross_down(close, middle)
        valid_indicators = [middle, upper]
        rule = 'Close crosses above upper Bollinger band; below middle SMA exits'
    elif strategy_id == 7:
        plus, minus, adx = _dmi(b, p['n'], p['adx_n'])
        entry = plus.gt(minus) & adx.ge(p['threshold'])
        leave = ~entry
        valid_indicators = [plus, minus, adx]
        crossing = False
        rule = '+DI > -DI and ADX >= threshold holds; otherwise cash'
    elif strategy_id == 8:
        previous_high = b['high'].shift(1).rolling(p['entry_n']).max()
        previous_low = b['low'].shift(1).rolling(p['exit_n']).min()
        entry, leave = close.gt(previous_high), close.lt(previous_low)
        valid_indicators = [previous_high, previous_low]
        crossing = False
        rule = 'Close above prior entry_n highs enters; below prior exit_n lows exits; current bar excluded'
    elif strategy_id == 9:
        roc = 100.0 * close.pct_change(p['n'], fill_method=None)
        entry, leave = roc.gt(p['threshold']), roc.le(p['threshold'])
        valid_indicators = [roc]
        crossing = False
        rule = 'ROC > threshold holds; otherwise cash'
    elif strategy_id == 10:
        typical = (b['high'] + b['low'] + close) / 3.0
        average = typical.rolling(p['n']).mean()
        mad = typical.rolling(p['n']).apply(lambda x: np.abs(x - x.mean()).mean(), raw=True)
        cci = (typical - average) / (0.015 * mad.replace(0.0, np.nan))
        cci = cci.mask(mad.eq(0), 0.0)
        entry, leave = _cross_up(cci, p['entry_threshold']), _cross_down(cci, p['exit_threshold'])
        valid_indicators = [cci]
        rule = 'Typical-price CCI; mean absolute deviation; up through +100 enters, down through 0 exits'
    elif strategy_id == 11:
        obv = (np.sign(close.diff()).fillna(0.0) * b['volume']).cumsum()
        average = obv.rolling(p['n']).mean()
        entry, leave = _cross_up(obv, average), _cross_down(obv, average)
        valid_indicators = [obv, average]
        rule = 'OBV increments by sign(close change)*volume; crosses its SMA'
    elif strategy_id == 12:
        direction = _supertrend(b, p['atr_n'], p['multiplier'])
        entry = direction.eq(1.0) & direction.shift(1).eq(-1.0)
        leave = direction.eq(-1.0) & direction.shift(1).eq(1.0)
        valid_indicators = [direction]
        rule = 'Supertrend direction flips; Wilder ATR and trailing final bands'
    elif strategy_id == 13:
        rsi = _rsi(close, p['n'])
        entry, leave = rsi.lt(p['entry_threshold']), rsi.gt(p['exit_threshold'])
        valid_indicators = [rsi]
        crossing = False
        rule = 'RSI < 30 enters; RSI > 70 exits; between thresholds keeps position'
    elif strategy_id == 14:
        average = close.rolling(p['n']).mean()
        entry, leave = close.gt(average), close.le(average)
        valid_indicators = [average]
        crossing = False
        rule = 'Close above n-bar SMA holds; otherwise cash; original reference uses 50 WEEKLY bars'
    else:
        k, d = _skdj(b, p['skdj_n'], p['skdj_m'])
        trix, signal = _trix(close, p['trix_n'], p['trix_signal'])
        entry = k.gt(d) & trix.gt(signal)
        leave = pd.Series(False, index=b.index)
        valid_indicators = [k, d, trix, signal]
        crossing = False
        rule = 'K>D and TRIX>signal enters if flat; fixed 20 TRADING DAYS exit belongs to ledger; original timeframe WEEKLY'

    required = warmup_bars(strategy_id, variant)
    ready = pd.Series(np.arange(1, len(b) + 1) >= required, index=b.index)
    for indicator in valid_indicators:
        ready &= pd.Series(np.isfinite(indicator.to_numpy(dtype=float)), index=b.index)
    permitted = ready & ready.shift(1, fill_value=False) if crossing else ready
    result = pd.DataFrame({
        'entry': (entry & permitted).fillna(False).astype(bool),
        'exit': (leave & permitted).fillna(False).astype(bool),
        'ready': ready.fillna(False).astype(bool),
    }, index=bars.index)
    result.attrs['metadata'] = {
        'strategy_id': strategy_id,
        'name': STRATEGY_NAMES[strategy_id],
        'variant': variant,
        'parameters': p,
        'parameter_unit': 'input bars; holding_trading_days is always trading days',
        'warmup_bars': required,
        'signal_mode': 'crossing' if crossing else 'state',
        'rule': rule,
        'execution': 'After completed bar close; earliest eligible later market open in caller ledger',
        'original_timeframe': 'W' if strategy_id in (14, 15) else 'D',
        'historically_selected_reference': strategy_id == 15,
        'fixed_holding_trading_days': p.get('holding_trading_days'),
        'fixed_hold': p.get('holding_trading_days'),
    }
    if (result['entry'] & result['exit']).any():
        raise AssertionError('Conflicting entry/exit signals')
    return result
