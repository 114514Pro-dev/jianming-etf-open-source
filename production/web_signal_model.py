"""Explanations for read-only model portfolios, never user account commands."""
from copy import deepcopy

LABELS = {'buy':'待买入', 'sell':'待卖出', 'rebalance':'待调仓', 'hold':'继续持有',
          'cash':'保持空仓', 'wait':'等待确认'}


def finish(code, as_of, positions, weights, intents, reasons, rule, execution, **extra):
    sides = {x['action'] for x in intents}
    status = ('rebalance' if {'buy','sell'} <= sides else 'buy' if 'buy' in sides else
              'sell' if 'sell' in sides else 'hold' if any(x > 0 for x in positions.values()) else 'cash')
    return dict(code=code, as_of=as_of, status=status, label=LABELS[status], positions=positions,
                weights=weights, cash_weight=max(0., 1-sum(weights.values())), intents=intents,
                reasons=[str(x) for x in reasons if x], rule=rule, execution=execution, **extra)


def original_model(state, market):
    import trade_book as ledger
    from simulator_core import DESCRIPTIONS
    code=state['auto']['strategy']; obs=deepcopy(state['auto']['last_observation'])
    quote=market.at(state['day']); value=ledger.value(state,quote)
    rows=[]; warnings=[]
    if state['pending']:
        estimate=deepcopy(state)
        for p in estimate['positions'].values():p['locked']={}
        rows,warnings,_=ledger.target_fills(estimate,quote,state['pending']['weights'])
    positions={c:p['qty'] for c,p in state['positions'].items()}
    intents=[dict(symbol=r['symbol'],action='buy' if r['side']=='买入' else 'sell',
                  reason='已确认目标与参考仓位需要调整；方向按当前收盘价格估算。') for r in rows]
    result=finish(code,state['day']+' 15:00:00',positions,obs['weights'],intents,
                  [obs.get('action'),obs.get('reason')]+warnings,DESCRIPTIONS[code],
                  '确认后在下一可执行交易日开盘模拟；实际份数取决于当时价格、整手、费用与可用资金。',
                  evidence=obs, reference_equity=value['equity'])
    if state['pending'] and not rows:
        result.update(status='wait',label=LABELS['wait'])
        result['reasons'].append('已产生目标，但当前估算没有可成交份数；等待可执行价格或满足整手、资金条件。')
    if result['status']=='cash':result['reasons'].append('全部参考持仓为零，且当前没有待执行买入目标，因此保留现金。')
    return result


def top_model(code, state, latest, signal_time, rule, target, tplus=1):
    held=bool(state.get('shares',0)); ready=bool(latest['ready'])
    closed=str(signal_time)==str(state['last_bar'])
    sell=held and (state.get('pending_exit',False) or (ready and closed and bool(latest['exit'])))
    buy=ready and closed and bool(latest['entry']) and not held
    reasons=['最近确认周期：入场条件'+('已触发' if latest['entry'] else '未触发')+
             '；退出条件'+('已触发' if latest['exit'] else '未触发')+'。']
    if not ready:reasons=['指标尚未完成预热，等待完整数据。']
    if not closed:reasons.append('当前时刻没有新完成的策略周期，旧信号不会重复触发入场。')
    if code=='T5WEEK' and held:
        reasons.append('参考仓位已持有 '+str(state.get('held_trading_days',0))+' 个交易日；按原规则固定持有20个交易日，期满后下一交易日开盘退出。')
    if sell:reasons.append('参考仓位仍有持仓，退出指令已确认，等待下一可执行时点；尚未视为卖出。')
    elif buy:reasons.append('参考仓位为空，新入场条件已确认，等待下一根真实完整K线开盘模拟买入。')
    elif held:reasons.append('参考仓位仍在持有，没有待执行卖出指令。')
    else:reasons.append('参考仓位为空，本次没有新的可执行入场条件，因此保留现金。')
    intents=[dict(symbol=target,action='sell' if sell else 'buy',reason=reasons[-1])] if sell or buy else []
    result=finish(code,str(state['last_bar']),{target:int(state.get('shares',0))},
                  {target:float(not sell and (held or buy))},intents,reasons,rule,
                  '下一根真实完整K线开盘模拟；'+('买入当日不可卖，退出指令保留至满足T+1。' if tplus else '目标ETF按原跨境ETF引擎的T+0规则执行。'),
                  signal_time=str(signal_time), evidence=dict(ready=ready,entry=bool(latest['entry']),exit=bool(latest['exit']),
                  newly_closed=closed,pending_exit=bool(state.get('pending_exit')),held_trading_days=state.get('held_trading_days',0)))
    if not ready:result.update(status='wait',label=LABELS['wait'])
    return result


def seven_model(result, service, target):
    from web_account_decision import result_decision
    code=result['strategy']; plan=result['plan']; legs=result['leg_states']
    decision=result_decision(result,target); positions={}; intents=[]; reasons=decision['reasons'][:]
    codes=[target,'sh512800','sh518880']
    if code.startswith('A_'):
        for symbol,leg in legs.items():
            qty=int(leg['shares'] if 'shares' in leg else leg['qty'][0]);positions[symbol]=qty
            if 'shares' in leg:
                # These native A legs use hourly signals. The last signal belongs
                # to the same complete hourly bar as this reference portfolio.
                sell=qty>0 and (leg.get('pending_exit') or leg.get('exit'))
                buy=qty==0 and leg.get('entry') and plan['weights'].get(symbol,0)>0
            else:
                sell=qty>0 and not leg['signal_intent'];buy=qty==0 and leg['signal_intent']>0
            if buy or sell:intents.append(dict(symbol=symbol,action='sell' if sell else 'buy',reason='该份独立本金的已确认信号与当前持仓不同。'))
        reasons.append('各份本金独立：有信号的一份调整，其他份额继续原状态；不跨子组合搬动资金。')
    else:
        positions=dict(zip(codes,legs['last_close']['qty']))
        # Native B routers act on target CHANGES, never price drift alone.
        import seven_service as seven
        _,dates,_,(_,_,states)=service.inputs(service.snapshot(),result['end'],False)
        prior=dates[dates.index(result['end'])-1]
        previous=seven.router_weights(code,states.loc[prior]);current=seven.router_weights(code,states.loc[result['end']])
        changed=previous!=current
        reasons.append('与上一交易日的模型目标'+('不同，等待下一交易日开盘调仓。' if changed else '相同，按原规则继续持有；不会因价格自然漂移而每日调仓。'))
        if changed:
            equity=plan['virtual_equity']
            for i,symbol in enumerate(codes):
                actual=legs['last_close']['market'][i]/equity
                delta=current[i]-actual
                if abs(delta)>1e-8:intents.append(dict(symbol=symbol,action='buy' if delta>0 else 'sell',reason='组合目标变化，按新比例调整；方向为收盘估算，执行时按开盘价格、整手及资金确定。'))
        decision['evidence']=dict(previous_target=dict(zip(codes,previous)),target_changed=changed,signals=legs['signal_values'])
    if not any(positions.values()) and not intents:reasons.append('各资产均未产生待执行买入意向，参考本金保持现金，等待相应条件成立。')
    return finish(code,plan['as_of'],positions,plan['weights'],intents,reasons,decision['rule'],plan['execution'],
                  daily_as_of=plan['daily_as_of'], evidence=decision.get('evidence',legs),reference_equity=plan['virtual_equity'])
