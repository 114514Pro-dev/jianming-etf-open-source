"""Dimensioned copy of the frozen accounting ledger; no signal changes."""
from datetime import date
from decimal import Decimal,ROUND_FLOOR,ROUND_CEILING
from bisect import bisect_left
from bear_gold_kernel import curve_metrics
def run_account(context,slippage=.0002,commission=.0003,save_daily=True,participation=None):
    CODES=context.codes;NAMES=context.names;n=len(CODES)
    SPLIT_EFFECTIVE={c:{d:e['ratio'] for d,e in items.items()} for c,items in context.splits.items()}
    BARS=context.bars; CA=context.actions; ALL=context.all_bars
    DATES=context.dates; START=context.start; END=context.end; INITIAL=context.capital
    REGIME=context.regime; ATTACK_CHANGES=context.events; WEEK_CLOSE=context.week_close
    LOOK=context.look; targets=context.targets; spec=context.spec.copy()
    metric=lambda curve,initial=INITIAL,start=START:curve_metrics(curve,initial,start)
    cash=INITIAL;qty=[0]*n;lastclose=[0.]*n;lastbuy=[-1]*8;costsum=[0.]*n;pnl=[0.]*n;divtotal=[0.]*n;slips=[0.]*n;turn=[0.]*n
    dividends=[];entitlement={};curve=[];logs=[];actions=[];w_prev=None;missing=[];failed_lots=0;rebalance_count=0
    records={};exs={};pays={};pre_records={}
    def action_day(day):
        if not context.general or not START<=day<=END:return day
        index=bisect_left(DATES,day)
        return DATES[index] if index<len(DATES) else day
    for j,c in enumerate(CODES):
        for k,event in enumerate(CA[c]['dividends']):
            if event['ex']>END:continue
            record_day=action_day(event['record'])
            (pre_records if record_day!=event['record'] else records).setdefault(record_day,[]).append((j,k,event))
            exs.setdefault(action_day(event['ex']),[]).append((j,k,event));pays.setdefault(action_day(event['pay']),[]).append((j,k,event))
    receivable={};weights=(0.,)*n;desired=[0]*n;order_signal=START;capacity_limits={};limited=0;deferred_rebalance=False
    if participation is not None:
        for j,c in enumerate(CODES):
            volumes=[];limits={}
            for b in BARS[c]:
                factor=SPLIT_EFFECTIVE.get(c,{}).get(b['date'],1.)
                if factor!=1:volumes=[v*factor for v in volumes]
                limits[b['date']]=int(sum(volumes[-20:])/20*participation)//100*100 if len(volumes)>=20 else 0
                volumes.append(b['volume_lots']*100)
            capacity_limits[j]=limits
    for i,day in enumerate(DATES):
        bars=[LOOK[c].get(day) for c in CODES];oldq=qty.copy();oldclose=lastclose.copy();pnl_before=pnl.copy()
        tradable=[bool(b) and day not in getattr(context,'trade_blocks',{}).get(c,set()) for c,b in zip(CODES,bars)]
        for j,k,event in pre_records.get(day,[]):entitlement[(j,k)]=oldq[j]
        for j,c in enumerate(CODES):
            if day in SPLIT_EFFECTIVE.get(c,{}) and qty[j]:
                ratio=SPLIT_EFFECTIVE[c][day]
                rounding=ROUND_CEILING if context.splits[c][day]['rounding']=='ceil' else ROUND_FLOOR
                convert=lambda q:int((Decimal(q)*Decimal(str(ratio))).to_integral_value(rounding=rounding))
                qty[j]=convert(qty[j]);desired[j]=convert(desired[j])
                actions.append([day,NAMES[j],'份额拆分',qty[j]-oldq[j],ratio])
        for j,k,event in exs.get(day,[]):
            amount=entitlement.pop((j,k),0.)*event['cash_per_share']
            if amount:receivable[(j,k)]=amount;divtotal[j]+=amount;pnl[j]+=amount;actions.append([day,NAMES[j],'应收分红',amount,event['pay']])
        for j,k,event in pays.get(day,[]):
            amount=receivable.pop((j,k),0.)
            if amount:cash+=amount;actions.append([day,NAMES[j],'分红到账',amount,'现金'])
        for j,b in enumerate(bars):
            if b: lastclose[j]=b['close']
            if qty[j] and not b and day not in getattr(context,'suspensions',{}).get(CODES[j],set()):missing.append([day,CODES[j]])
        if i==0 or (DATES[i-1] in WEEK_CLOSE) or day in ATTACK_CHANGES:
            signal_day=DATES[i-1] if i else context.previous_day
            candidate=targets(spec,signal_day,REGIME[i])
            if candidate!=w_prev or deferred_rebalance:weights=candidate;do_rebalance=True;w_prev=candidate
            else:do_rebalance=False
        else:do_rebalance=False
        openpx=[b['open'] if tradable[j] else oldclose[j] for j,b in enumerate(bars)]
        equity_open=cash+sum(q*px for q,px in zip(qty,openpx))+sum(receivable.values())
        # Isolate overnight P&L, including split-adjusted quantities.
        for j in range(n):pnl[j]+=qty[j]*openpx[j]-oldq[j]*oldclose[j]
        if do_rebalance:
            rebalance_count+=1
            order_signal=signal_day
            desired=[int(equity_open*weights[j]/(px*(1+slippage)))//100*100 if px and tradable[j] else qty[j] for j,px in enumerate(openpx)]
            deferred_rebalance=any(not tradable[j] and (weights[j]>0 or qty[j]>0) for j in range(n))
        if do_rebalance or participation is not None:
            if i==len(DATES)-1:desired=[min(q,qty[j]) for j,q in enumerate(desired)]
            for side in [-1,1]:
                for j in range(n):
                    diff=desired[j]-qty[j]
                    if diff*side<=0 or not tradable[j]:continue
                    px=openpx[j]*(1+side*slippage);q=abs(diff)
                    if participation is not None:
                        cap=capacity_limits[j].get(day,0)
                        if q>cap:limited+=1;q=cap
                        if q<=0:continue
                    if side==1:
                        q=q//100*100
                        while q>0 and q*px+max(5,q*px*commission)>cash+1e-8:q-=100
                        if q<=0:failed_lots+=1;continue
                        lastbuy[j]=i
                    else:assert lastbuy[j]<i,('T+1',day,CODES[j])
                    fee=max(5,q*px*commission);cash-=side*q*px+fee;qty[j]+=side*q;costsum[j]+=fee;slips[j]+=q*openpx[j]*slippage;turn[j]+=q*px;pnl[j]-=fee+q*openpx[j]*slippage
                    assert cash>=-1e-6,(spec['id'],day,cash)
                    logs.append(dict(date=day,signal=order_signal,asset=NAMES[j],symbol=CODES[j],side='买入' if side==1 else '卖出',qty=q,price=px,fee=fee,slippage=q*openpx[j]*slippage,cash=cash,reason='进攻切换' if day in ATTACK_CHANGES else ('分批执行' if not do_rebalance else '防御条件变化')))
        for j,k,event in records.get(day,[]):entitlement[(j,k)]=qty[j]
        for j,b in enumerate(bars):
            if b:pnl[j]+=qty[j]*(b['close']-openpx[j])
        market=[q*px for q,px in zip(qty,lastclose)];equity=cash+sum(market)+sum(receivable.values())
        assert abs(equity-INITIAL-sum(pnl))<max(1e-5,equity*1e-10),('reconcile',spec['id'],day,equity,INITIAL+sum(pnl))
        curve.append(dict(date=day,equity=equity,cash=cash,receivable=sum(receivable.values()),attack=REGIME[i],market=market.copy(),qty=qty.copy(),pnl=[pnl[j]-pnl_before[j] for j in range(n)]))
    # Common terminal liquidation, excluded from live trading signals.
    for j,q in enumerate(qty):
        if q:
            px=lastclose[j]*(1-slippage);fee=max(5,q*px*commission);cash+=q*px-fee;costsum[j]+=fee;slips[j]+=q*lastclose[j]*slippage;turn[j]+=q*px;loss=fee+q*lastclose[j]*slippage;pnl[j]-=loss;curve[-1]['pnl'][j]-=loss
            logs.append(dict(date=END,signal=END,asset=NAMES[j],symbol=CODES[j],side='期末清算',qty=q,price=px,fee=fee,slippage=q*lastclose[j]*slippage,cash=cash,reason='仅回测结算'))
    curve[-1]['equity']=cash+sum(receivable.values());curve[-1]['cash']=cash
    m=metric(curve);m.update(fees=sum(costsum),slippage=sum(slips),dividends=sum(divtotal),fills=len(logs),rebalances=rebalance_count,mean_attack=sum(x['market'][0]/x['equity'] for x in curve)/len(curve),mean_equity=sum(sum(x['market'][j] for j in [0])/x['equity'] for x in curve)/len(curve),mean_defense=sum(sum(x['market'][1:])/x['equity'] for x in curve)/len(curve),mean_cash=sum(x['cash']/x['equity'] for x in curve[:-1])/(len(curve)-1),min_cash=min(x['cash'] for x in curve),failed_lots=failed_lots)
    m['capacity_limited_orders']=limited
    curve[-1]['pre_liquidation_market']=curve[-1]['market'].copy();curve[-1]['pre_liquidation_qty']=curve[-1]['qty'].copy();curve[-1]['market']=[0.]*n;curve[-1]['qty']=[0]*n
    assert all(abs(x['equity']-x['cash']-x['receivable']-sum(x['market']))<1e-5 for x in curve)
    yearly=[];year_initial=INITIAL
    for yr in range(date.fromisoformat(START).year,date.fromisoformat(END).year+1):
        rows=[x for x in curve if x['date'].startswith(str(yr))]
        if not rows:continue
        mm=metric(rows,year_initial,rows[0]['date']);yearly.append(dict(year=yr,start=year_initial,end=rows[-1]['equity'],return_=rows[-1]['equity']/year_initial-1,mdd=mm['mdd']));year_initial=rows[-1]['equity']
    segments=[]
    attribution=[dict(asset=NAMES[j],symbol=CODES[j],pnl=pnl[j],dividends=divtotal[j],fees=costsum[j],slippage=slips[j],turnover=turn[j]) for j in range(n)]
    if missing:raise ValueError('持仓资产缺少精确行情：'+str(missing[:3]))
    assert abs(m['final']-INITIAL-sum(x['pnl'] for x in attribution))<1e-5
    return dict(spec=spec,metrics=m,yearly=yearly,segments=segments,attribution=attribution,logs=logs,actions=actions,curve=curve if save_daily else [])
