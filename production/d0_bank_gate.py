"""D0-only conditional bank K50 gate, with causal reference-state replay.

The K40 bank engine remains an independent shadow reference. Outside a usable
confirmed ChiNext close-below-MA50 regime we restore that shadow's state. On
entering the regime we inherit its already-effective position and age, then
evaluate the K50 close rule. Consecutive active days evolve independently.
This matches the audited research cross50 state machine, including exits before
entries, next-open reference activation and regime resets of the time-exit lock.
No account, shared strategy configuration, market data or network IO is mutated.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import date
import math
import threading

from allocation import CODES

CHI, BANK = CODES[:2]
SCHEMA = 'd0.bank-ma50-k50.v1'


def rule_spec():
    return dict(schema=SCHEMA, bank_symbol=BANK, reference_start='2017-08-03',
        default_entry_k_limit=40, relaxed_entry_k_limit=50, bank_skdj=[9, 5],
        entry='previous_k<=previous_d and k>d and k<=entry_k_limit',
        exit='k>=70 or k<=d or reference_holding_days>=20',
        trigger=dict(symbol=CHI, timeframe='completed_week', ma_weeks=50,
            comparison='close<ma', equality='inactive', source='features.chi_market',
            confirmation='canonical_week_end<=available<=signal_day',
            quality='original_chi_bank_ready_and_score_ready_and_all_same_day_quotes'),
        transition='inactive_restore_original_k40_shadow;enter_inherit_original_position_and_age;active_replay_k50',
        clock='reference_next_open_activation_including_first_holding_day',
        time_exit_lock='until_k<=d_within_active_regime;reset_to_shadow_on_regime_exit')


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def weekly_market_evidence(observation):
    feature = observation.get('features', {}).get('chi_market', {})
    return dict(weekly_close=feature.get('close'), ma=feature.get('ma'),
        week_end=feature.get('week_end'), available=feature.get('available'))


def relaxation_gate(observation, day):
    dynamic = observation.get('dynamic', {})
    ready = observation.get('ready', {})
    reasons = []
    weekly = weekly_market_evidence(observation)
    if not finite(weekly['weekly_close']) or not finite(weekly['ma']):
        reasons.append('chi_50week_values_unready')
    elif not weekly['weekly_close'] < weekly['ma']:
        reasons.append('chi_weekly_close_not_below_50week_ma')
    try:
        if not date.fromisoformat(weekly['week_end']) <= date.fromisoformat(weekly['available']) <= date.fromisoformat(day):
            reasons.append('chi_50week_not_yet_confirmed')
    except (TypeError, ValueError):
        reasons.append('chi_50week_confirmation_missing_or_invalid')
    if not ready.get(CHI, False): reasons.append('chi_original_indicators_unready')
    if not dynamic.get(CHI, {}).get('score_ready', False): reasons.append('chi_score_unready')
    if not ready.get(BANK, False): reasons.append('bank_original_indicators_unready')
    if not dynamic.get(BANK, {}).get('score_ready', False): reasons.append('bank_score_unready')
    for code in CODES:
        if dynamic.get(code, {}).get('quote_date') != day:
            reasons.append(code + '_quote_not_current')
    return not reasons, reasons


@dataclass
class BankState:
    held: bool = False
    holding_days: int = 0
    next_eligible: bool = False
    blocked: bool = False
    previous_relaxed: bool = False


def step_bank(state, original, relaxed, k, d, previous_k, previous_d):
    """One close of the research cross50 state machine; inputs are dated facts."""
    original_held = bool(original.get('risk', 0) > 0)
    original_age = int(original.get('holding_days', 0)) if original_held else 0
    if not relaxed or not state.previous_relaxed:
        state.held = original_held
        state.holding_days = original_age
        state.blocked = bool(original.get('blocked', False))
        transition = 'return_to_original' if state.previous_relaxed else 'enter_relaxed' if relaxed else 'original'
    else:
        was_held = state.held
        state.held = state.next_eligible
        state.holding_days = state.holding_days + 1 if state.held and was_held else 1 if state.held else 0
        transition = 'continue_relaxed'
    ready = finite(k) and finite(d)
    cross = bool(ready and finite(previous_k) and finite(previous_d) and previous_k <= previous_d and k > d)
    if not relaxed:
        state.next_eligible = bool(original.get('next_risk', 0) > 0)
        reason = 'original_reference_state'
    else:
        if ready and k <= d:
            state.blocked = False
        if state.held:
            if not ready:
                reason, state.next_eligible = 'indicator_unavailable_hold_reference', True
            elif k <= d:
                reason, state.next_eligible = 'dead_cross_or_equal_exit', False
            elif k >= 70:
                reason, state.next_eligible = 'high_threshold_exit', False
            elif state.holding_days >= 20:
                reason, state.next_eligible, state.blocked = 'time_limit_exit', False, True
            else:
                reason, state.next_eligible = 'hold_reference', True
        else:
            entry = bool(ready and k > d and not state.blocked and cross and k <= 50 and k < 70)
            state.next_eligible = entry
            reason = 'entry_confirmed' if entry else 'time_exit_blocked' if state.blocked else 'wait_entry'
    state.previous_relaxed = bool(relaxed)
    return dict(transition=transition, reference_held=state.held,
        holding_days=state.holding_days, next_eligible=state.next_eligible,
        blocked=state.blocked, reason=reason, crossover=cross,
        indicator_ready=ready, original_reference_held=original_held,
        original_holding_days=original_age,
        original_next_eligible=bool(original.get('next_risk', 0) > 0))


REASONS = dict(entry_confirmed='日线SKDJ新金叉且K≤50，银行入场确认',
    hold_reference='继续持有条件K50银行参考仓位',
    wait_entry='等待日线SKDJ新金叉且K≤50',
    time_exit_blocked='满20交易日退出后，等待K≤D重置再出现新金叉',
    dead_cross_or_equal_exit='银行K≤D，退出参考仓位',
    high_threshold_exit='银行K≥70，退出参考仓位',
    time_limit_exit='银行参考仓位达到20交易日，退出',
    indicator_unavailable_hold_reference='指标暂不可用，保留参考状态')


class ConditionalBankGate:
    """Cache one chronological pass, regardless of observation query order.

    Only reference decisions are cached, not mutable public observations. A
    latest-date request computes each preceding day once; historical lookups
    thereafter are O(1). The lock protects concurrent readers of one market.
    """
    def __init__(self, market, original_observation):
        self.market = market
        self.original_observation = original_observation
        self.days = tuple(market.dates)
        self.indices = {day: i for i, day in enumerate(self.days)}
        self.bank_days = set(market.bar_dates[BANK])
        # Shadow entry/peak use strategy_engine.Market.daily's cumulative
        # split-adjusted prices. Keep candidate reference evidence in that same
        # unit; raw executable prices belong only to the account ledger.
        self.reference_prices = {bar['date']: dict(open=bar['open'], close=bar['close'])
            for bar in market.inputs.market.daily}
        self.cache = {}
        self.state = BankState()
        self.previous_k = self.previous_d = None
        self.reference_entry = self.reference_peak = None
        self.lock = threading.RLock()

    def __deepcopy__(self, memo):
        # Reference replay deep-copies accepted markets. RLock is not picklable,
        # and the callback must bind to the copied DynamicSignals/market graph.
        copied = type(self).__new__(type(self))
        memo[id(self)] = copied
        with self.lock:
            for name, value in self.__dict__.items():
                if name != 'lock':
                    setattr(copied, name, deepcopy(value, memo))
        copied.lock = threading.RLock()
        return copied

    def get(self, day):
        if day not in self.indices:
            raise ValueError('D0银行信号日期不在已确认行情日历内')
        with self.lock:
            while len(self.cache) <= self.indices[day]:
                current = self.days[len(self.cache)]
                self.cache[current] = self._process(current, self.original_observation(current))
            return deepcopy(self.cache[day])

    def _process(self, day, original):
        feature = original.get('features', {}).get('bank', {})
        k, d = feature.get('k'), feature.get('d')
        shadow = original.get('bank_state', {})
        relaxed, gate_reasons = relaxation_gate(original, day)
        has_bar = day in self.bank_days
        if not has_bar:
            relaxed = False
            gate_reasons.append('bank_no_bar')
        previous_held = self.state.held
        previous_relaxed = self.state.previous_relaxed
        decision = step_bank(self.state, shadow, relaxed, k, d, self.previous_k, self.previous_d)
        if not relaxed or not previous_relaxed:
            self.reference_entry = shadow.get('entry')
            self.reference_peak = shadow.get('peak')
        elif self.state.held and not previous_held:
            bar = self.reference_prices.get(day, {})
            self.reference_entry = self.reference_peak = bar.get('open')
        elif not self.state.held:
            self.reference_entry = self.reference_peak = None
        if relaxed and self.state.held:
            close = self.reference_prices.get(day, {}).get('close')
            if finite(close):
                self.reference_peak = max(close, self.reference_peak) if finite(self.reference_peak) else close
        detail = original['dynamic'][BANK]
        eligible = bool(decision['next_eligible'] and original.get('ready', {}).get(BANK)
            and detail.get('score_ready') and detail.get('quote_date') == day)
        evidence = dict(schema=SCHEMA, day=day, active=relaxed, relaxed=relaxed,
            entry_k_limit=50 if relaxed else 40, exit_k_limit=70, max_holding_days=20,
            gate_reasons=gate_reasons, k=k, d=d, previous_k=self.previous_k,
            previous_d=self.previous_d, has_bank_bar=has_bar,
            bank_eligible=eligible, original_bank_eligible=bool(detail['eligible']),
            raw_bank_score=detail.get('score'),
            quote_dates={c: original['dynamic'][c].get('quote_date') for c in CODES},
            **weekly_market_evidence(original), **decision)
        bank_state = deepcopy(shadow)
        bank_feature = deepcopy(feature)
        if relaxed:
            bank_state.update(date=day, risk=float(decision['reference_held']),
                next_risk=float(decision['next_eligible']), holding_days=decision['holding_days'],
                blocked=decision['blocked'], entry=self.reference_entry,
                peak=self.reference_peak, reason=REASONS[decision['reason']])
            positive = bool(decision['crossover'] and finite(k) and k <= 50)
            bank_feature.update(entry=bool(positive and not decision['blocked']),
                exit=bool(decision['indicator_ready'] and (k >= 70 or k <= d)),
                positive=positive, entry_k_limit=50)
        if has_bar:
            self.previous_k, self.previous_d = k, d
        return dict(evidence=evidence, bank_state=bank_state, bank_feature=bank_feature)


def apply_gate(original, record):
    """Project the cached decision onto a fresh original D0 observation."""
    from dynamic_allocation import allocate
    result = original
    evidence = record['evidence']
    detail = result['dynamic'][BANK]
    if evidence['active']:
        detail.update(eligible=evidence['bank_eligible'],
            effective_score=detail['score'] if evidence['bank_eligible'] else 0.)
        eligible = {c: bool(result['dynamic'][c]['eligible']) for c in CODES}
        scores = {c: result['dynamic'][c]['score'] if eligible[c] else 0. for c in CODES}
        result.update(**allocate(scores, eligible))
        result['longs'][BANK] = evidence['bank_eligible']
        result['bank_long'] = evidence['bank_eligible']
        result['bank_state'] = record['bank_state']
        result['features']['bank'] = record['bank_feature']
    evidence['bank_weight'] = result['weights'][BANK]
    state_reason = result.get('bank_state', {}).get('reason', '等待银行参考信号')
    condition = '已确认创业板周收盘低于50周均线，银行新金叉入场上限K≤50' if evidence['active'] else '条件放宽未启用，沿用原银行K≤40规则'
    note = ('动态多头资格通过；' if detail['eligible'] else '动态多头资格未通过，目标0%；') + condition + '；' + state_reason
    if detail['score_ready'] and detail['quote_date'] == result['day']:
        note += f'；20日{detail["momentum20"]:+.2%}，60日{detail["momentum60"]:+.2%}，20日年化波动{detail["volatility20"]:.2%}，有效评分{detail["effective_score"]:.3f}'
    elif not detail['score_ready']:
        note += '；强弱指标尚不足61个交易日'
    else:
        note += '；当日缺少行情，暂不增配'
    result['notes'][BANK] = note
    result['reason'] = '；'.join(c + '：' + result['notes'][c] for c in CODES)
    result['features']['dynamic'] = result['dynamic']
    result['bank_gate'] = evidence
    return result
