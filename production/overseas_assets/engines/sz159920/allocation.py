"""The user's four-state allocation, independent of indicator implementations."""
CODES=['sz159920','sh512800','sh518880','sh511010']
STATES={'both':'双多：恒生指数60%／银行40%','chi':'恒生指数单多','bank':'银行单多','neither':'双空：股票轻仓，防守资金另行判断'}
def combine(chi_long,bank_long,light=.2,gold_long=True):
    if not isinstance(chi_long,bool) or not isinstance(bank_long,bool):raise ValueError('两套策略必须分别给出明确的多空判断')
    if not 0<=light<=.2:raise ValueError('本版双空股票底仓范围为0%至20%')
    if chi_long and bank_long:key='both';weights=(.6,.4,0.,0.)
    elif chi_long:key='chi';weights=(1.,0.,0.,0.)
    elif bank_long:key='bank';weights=(0.,1.,0.,0.)
    else:key='neither';weights=(.6*light,.4*light,1-light if gold_long else 0.,0.)
    return dict(state=key,label=STATES[key],weights=dict(zip(CODES,weights)),cash_weight=max(0.,1-sum(weights)))

def staged(longs,ready,light=.2):
    """Eligible assets participate together; ChiNext keeps the agreed 60% core."""
    if set(longs)!=set(CODES) or set(ready)!=set(CODES):raise ValueError('需要四种资产的独立判断')
    if any(not isinstance(v,bool) for v in [*longs.values(),*ready.values()]):raise ValueError('资产信号须明确')
    if any(longs[c] and not ready[c] for c in CODES):raise ValueError('资料不足的资产不能发出多头信号')
    if light not in (0.,.1,.2):raise ValueError('股票底仓仅支持0%、10%、20%')
    chi,bank,gold,bond=CODES;weights=dict.fromkeys(CODES,0.)
    if longs[chi]:
        peers=[c for c in CODES[1:] if longs[c]]
        weights[chi]=.6 if peers else 1.
        for c in peers:weights[c]=.4/len(peers)
        state='chi_core';label='恒生指数多头：保留60%主仓' if peers else '仅恒生指数多头：恒生指数100%'
    elif longs[bank]:
        peers=[c for c in CODES[1:] if longs[c]]
        for c in peers:weights[c]=1./len(peers)
        state='bank_peers';label='恒生指数未确认多头：银行与合格防守资产平分'
    else:
        stocks=[c for c in CODES[:2] if ready[c]];ratios={chi:.6,bank:.4}
        if stocks:
            total=sum(ratios[c] for c in stocks)
            for c in stocks:weights[c]=light*ratios[c]/total
        budget=1-sum(weights.values());peers=[c for c in CODES[2:] if longs[c]]
        for c in peers:weights[c]=budget/len(peers)
        state='defense';label='股票未确认多头：轻仓与独立防守'
    return dict(state=state,label=label,weights=weights,cash_weight=max(0.,1-sum(weights.values())))
