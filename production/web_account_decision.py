"""Read-only explanations of an account's own confirmed snapshot.

These describe recorded decisions, never place orders or use the live quote as
a replacement for a closed bar. No explanation is persisted into a ledger.
"""
from chinext_service import BY_ID
from chinext_engine import signal_state


def original_decision(snapshot):
    state = snapshot['state']
    obs = snapshot['observation']
    return dict(as_of=state['day'], title=snapshot['title'],
                reasons=[obs.get('action') or '等待原策略确认调仓条件。'], evidence=obs.get('reason', ''),
                rule=snapshot['conditions'], pending=bool(state['pending']),
                execution=('已生成目标，等待下一可执行交易日开盘；成交份数届时按资金、价格和费用计算。'
                           if state['pending'] else '没有待执行目标；等待原策略的下一次确认。'),
                weights=obs.get('weights', {}))


def top5_decision(service, identity):
    account = service._load_account(identity)
    code = account['strategy_id']
    through = account.get('through')
    rule = BY_ID[code]['parameters']+'。'+BY_ID[code]['description']
    if not through:
        return dict(as_of=None, title='等待首次确认', reasons=['账户尚未推进到完整K线。'], rule=rule)
    # Explicitly select this account's frozen snapshot AND cutoff. An old or
    # paused account must not acquire evidence from a newer market snapshot.
    sig = service._signals(code, account['snapshot_id'], through)
    sig = sig.loc[sig.index <= through]
    state = account.get('state', {})
    pending = account.get('pending', {})
    held = bool(state.get('shares', 0))
    reasons = []
    if sig.empty:
        return dict(as_of=through, title='等待完整信号', reasons=['没有可用的已确认策略周期。'], rule=rule)
    last = sig.iloc[-1]
    ready, entry, leave = bool(last.ready), bool(last.entry), bool(last['exit'])
    signal_time = str(sig.index[-1])
    closed = signal_time == through
    if not ready:
        reasons.append('指标预热尚未完成，不能把缺失指标当作买卖信号。')
    else:
        reasons.append('最近确认周期：入场条件'+('已触发' if entry else '未触发')+
                       '，退出条件'+('已触发' if leave else '未触发')+'。')
        if code == 'T5SUPER':
            model = signal_state(sig).iloc[-1]
            reasons.append('Supertrend 模型'+('处于多头状态' if model == 1 else '处于现金状态')+
                           '；买入要求本根出现由空转多，已有多头状态不等于重新触发买入。')
    if code == 'T5WEEK':
        if not closed:
            reasons.append('当前账户时刻没有新完成的周K线；上一次周线条件不会在每根小时线重复开仓。')
        if held:
            reasons.append('当前已持有 '+str(state.get('held_trading_days', 0))+
                           ' 个交易日；第20日收盘确认期满后，下一交易日开盘退出。')
    if pending.get('sell'):
        title = '等待模拟卖出'
        reasons.append('已有退出指令。'+('持有期已满。' if code == 'T5WEEK' and state.get('pending_exit') else
                                      '退出条件已触发，未成交的卖出指令会继续保留。'))
    elif pending.get('buy'):
        title = '等待模拟买入'
        reasons.append('账户当前没有持仓，本次确认满足入场条件；尚未记为成交。')
    elif held:
        title = '继续持有'
        reasons.append('账户仍有持仓，没有待执行卖出指令。')
    else:
        title = '保持现金，等待入场'
        reasons.append('账户当前没有持仓，也没有待执行买入指令。')
    return dict(as_of=through, signal_time=signal_time, title=title, reasons=reasons,
                rule=rule, pending=bool(pending.get('buy') or pending.get('sell')),
                execution=pending.get('description', '等待下一次完整周期确认。')+
                          ' 创业板ETF买入当日不可卖出；只用真实完整K线开盘记账。',
                signal=dict(ready=ready, entry=entry, exit=leave, newly_closed=closed))


def result_decision(result, target='sz159915'):
    """Use only evidence already saved by seven/overseas result engines."""
    code = result['strategy']
    plan = result.get('plan', {})
    weights = result.get('next_target', plan.get('weights', {}))
    reasons = []
    legs = result.get('leg_states', {})
    values = legs.get('signal_values', {})
    if code == 'B_D7':
        for symbol, name in ((target, '目标ETF'), ('sh512800', '银行ETF'), ('sh518880', '黄金ETF')):
            key = symbol+'_ma200'
            if key in values:
                reasons.append(name+'的200日均线过滤：'+('通过，目标配置1/3' if values[key] else '未通过，对应资金保留现金')+'。')
        rule = '三份资金各占1/3，分别按目标ETF、银行、黄金的200日均线过滤；未通过的份额保留现金。'
    elif code.startswith('B_'):
        for key, name in (('chi_vote', '目标ETF组合信号'), ('bank_trix', '银行TRIX'), ('gold_don', '黄金周线突破')):
            if key in values:reasons.append(name+'：'+('多头' if values[key] else '非多头')+'。')
        rule = {'B_D4':'目标ETF多头时配置目标ETF，否则配置黄金。',
                'B_D5':'目标ETF多头时配置目标ETF，否则按黄金周线信号选择黄金或现金。',
                'B_D6':'目标ETF多头时配置目标ETF，否则银行、黄金各分配一半预算，再由各自信号决定持仓或现金。'}.get(code, '')
    elif code.startswith('A_'):
        for symbol, leg in legs.items():
            name = '目标ETF' if symbol == target else '银行ETF' if symbol == 'sh512800' else '黄金ETF'
            if 'signal_intent' in leg:
                reasons.append(name+'独立资金：'+('模型允许持有' if leg['signal_intent'] else '模型要求现金')+'。')
            elif 'entry' in leg:
                reasons.append(name+'在 '+str(leg.get('signal_time', '已确认周期'))+'：入场条件'+
                               ('触发' if leg['entry'] else '未触发')+'，退出条件'+('触发' if leg.get('exit') else '未触发')+
                               ('，已有待卖出指令' if leg.get('pending_exit') else '')+'。')
        rule = '目标ETF使用'+('Supertrend' if 'SUPER' in code else '均线、突破、量能三模型投票')+'；'+(
            '目标ETF与黄金各用初始本金50%。' if code.endswith('P2') else '目标ETF用50%，银行和黄金各用25%。')+'各份资金独立复利。'
    elif code in BY_ID:
        rule = BY_ID[code]['parameters']+'。'+BY_ID[code]['description'].replace('买入算第1日，第21交易日开盘退出。', '固定持有20个交易日后按原执行时点退出。')
        if result.get('reference_note'):reasons.append(result['reference_note'])
    else:
        from simulator_core import DESCRIPTIONS
        rule = DESCRIPTIONS.get(code, '按账户已选策略的原规则判断。')
    if not reasons:
        reasons.append('这份历史结果未保存更细的触发条件；这里只展示已保存的参考目标和成交原因，不补造指标判断。')
    return dict(as_of=plan.get('as_of', result['end']+' 15:00:00'), title='最近确认的策略判断',
                reasons=reasons, weights=weights, rule=rule,
                execution=plan.get('execution', result.get('reference_note', '下一执行时点前，参考目标不代表已成交。')))
