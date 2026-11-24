"""Fixed 50-week gold defense research strategy; pure, instance-local accounting."""
from datetime import date,timedelta
from decimal import Decimal,ROUND_FLOOR,ROUND_CEILING
from bisect import bisect_left
import math,statistics
CODES=['sz159920','sh518880','sh511010']
NAMES=['恒生指数','黄金','5年国债']
SPLIT_EFFECTIVE={}
RULE={'id':'w50_a100_b20_gold','name':'熊市黄金50周','ma':50,'attack':1.0,'bear_cap':0.2,'gate':True,
      'skdj':[3,5],'trix':[4,8],'hold_days':20,'trail_arm':0.15,'trail_half':0.08,'trail_exit':0.12,
      'bear_defense':'gold','bull_wait_defense':'gold_bond_equal','commission':0.0003,'minimum_commission':5.0,'slippage':0.0002}

class Context:
    def __init__(self,dataset,start,end,capital,spec=None,completed_through=None):
        from bear_gold_assets import identity
        from copy import deepcopy
        self.spec=deepcopy(RULE if spec is None else spec)
        self.symbol,self.codes,self.names=identity(dataset)
        self.general=dataset.get('schema')=='skdj.bear-gold.data.v2'
        self.splits=dataset.get("split_adjustments",{})
        CODES=self.codes
        self.capital=float(capital)
        self.bars={c:[z for z in dataset['bars'][c] if z['date']<=end] for c in CODES}
        self.actions=dataset['corporate_actions']
        self.all_bars=self.bars[CODES[0]]
        self.dates=[z['date'] for z in self.all_bars if start<=z['date']<=end]
        if len(self.dates)<2:raise ValueError('所选区间至少需要2个交易日。')
        self.start=self.dates[0];self.end=self.dates[-1]
        ix=next(i for i,z in enumerate(self.all_bars) if z['date']==self.start)
        self.previous_day=self.all_bars[ix-1]['date'] if ix else (date.fromisoformat(self.start)-timedelta(days=1)).isoformat()
        self.look={c:{z['date']:z for z in arr} for c,arr in self.bars.items()}
        for c in CODES:
            if not self.bars[c]:continue
            first=self.bars[c][0]['date']
            missing=[d for d in self.dates if d>=first and d not in self.look[c]]
            if missing:raise ValueError(c+' 上市后存在缺失交易日：'+','.join(missing[:3]))
        signal_bars=[];factor=1.
        for bar in self.all_bars:
            factor*=self.splits.get(self.symbol,{}).get(bar['date'],{}).get('ratio',1.)
            signal_bars.append({**bar,**{k:bar[k]*factor for k in ['open','close','high','low']}})
        self.signal_bars=signal_bars
        self.regime,self.events,self.states=build_schedule(signal_bars,self.start,self.end,self.spec,completed_through=completed_through)
        self.state_lookup={z['date']:z for z in self.states}
        prior=[v for d,v in features(signal_bars,self.spec['ma'],completed_through).items() if d<self.start]
        if prior:
            f=prior[-1]
            self.state_lookup[self.previous_day]={'close_market':'bull' if f['close']>f['ma'] else 'bear'}
        # Only completed weeks are used; the first and current final week are omitted.
        groups=[]
        for bar in self.all_bars:
            key=date.fromisoformat(bar['date']).isocalendar()[:2]
            if not groups or groups[-1][0]!=key:groups.append([key,[]])
            groups[-1][1].append(bar['date'])
        self.week_close={g[1][-1] for g in groups[1:-1]}

    def targets(self,spec,signal_day,risk):
        mode=self.state_lookup.get(signal_day,{}).get('close_market','warmup')
        w=[float(risk),0.,0.];budget=1-float(risk)
        for j,weight in ([(1,1.)] if mode=='bear' else [(1,.5),(2,.5)]):
            arr=self.bars[self.codes[j]]
            if arr and arr[0]['date']<=signal_day:w[j]=budget*weight
        # One symbol may fill both a risk and a defense role; trade it once.
        for j,c in enumerate(self.codes):
            if c in self.codes[:j]:w[self.codes.index(c)]+=w[j];w[j]=0.
        return tuple(w)

def features(bars,ma,completed_through=None):
    groups=[]
    for bar in bars:
        key=date.fromisoformat(bar['date']).isocalendar()[:2]
        if not groups or groups[-1][0]!=key:groups.append([key,[]])
        groups[-1][1].append(bar)
    prices=[];ks=[];trs=[];sr=k=e1=e2=e3=prev=None;last_rsv=50.;out={}
    complete=groups[1:-1]
    # Live close analysis may confirm a final Friday once its daily bar is complete.
    # Historical callers retain their original final-week omission by default.
    if completed_through and len(groups)>1 and groups[-1][1][-1]['date']<=completed_through and date.fromisoformat(groups[-1][1][-1]['date']).weekday()==4:
        complete=groups[1:]
    for j,(_,bucket) in enumerate(complete):
        p=dict(date=bucket[-1]['date'],close=bucket[-1]['close'],low=min(x['low'] for x in bucket),high=max(x['high'] for x in bucket));prices.append(p);d=None
        if j>=2:
            ll=min(x['low'] for x in prices[-3:]);hh=max(x['high'] for x in prices[-3:]);rsv=last_rsv if hh==ll else (p['close']-ll)/(hh-ll)*100;last_rsv=rsv
            sr=rsv if sr is None else rsv/3+sr*2/3;k=sr if k is None else sr/3+k*2/3;ks.append(k)
            if len(ks)>=5:d=sum(ks[-5:])/5
        a=.4;e1=p['close'] if e1 is None else a*p['close']+(1-a)*e1;e2=e1 if e2 is None else a*e1+(1-a)*e2;e3=e2 if e3 is None else a*e2+(1-a)*e3
        if prev is not None:trs.append((e3/prev-1)*100)
        prev=e3
        if d is not None and j>=max(19,ma-1):out[p['date']]=dict(close=p['close'],k=k,d=d,trix=trs[-1],signal=sum(trs[-8:])/8,ma=sum(z['close'] for z in prices[-ma:])/ma)
    return out

def build_schedule(allbars,start,end,spec=None,terminal_guard=True,completed_through=None,feature_map=None,market_map=None):
    spec=RULE if spec is None else spec
    feat=features(allbars,20,completed_through) if feature_map is None else feature_map
    market=features(allbars,spec['ma'],completed_through) if market_map is None else market_map
    bars=[x for x in allbars if start<=x['date']<=end]
    full=spec['attack']; risk=0.; pending=None; entry=peak=None; ceiling=full
    blocked=False; entered=None; regime=[]; events={}; days=[]; mode='warmup'; last_ma=None
    prior=[v for d,v in market.items() if d<start]
    if prior:
        f=prior[-1];last_ma=f['ma'];mode='bull' if f['close']>f['ma'] else 'bear'
    for i,bar in enumerate(bars):
        day=bar['date']; close=bar['close']
        if pending is not None:
            new,sd=pending
            if terminal_guard and i==len(bars)-1 and new>risk:new=risk
            if new!=risk:
                if not risk and new:entry=bar['open'];peak=entry;ceiling=full;entered=i
                if not new:entry=peak=None;ceiling=full;entered=None
                risk=new; events[day]=sd
            pending=None
        applied_mode=mode
        regime.append(risk); target=risk; reason='继续持有' if risk else '维持防御配置'
        if risk and close>peak:peak=close;ceiling=full
        if day in market:
            f=market[day];last_ma=f['ma'];mode='bull' if f['close']>f['ma'] else 'bear'
        if not spec.get('gate',True):mode=applied_mode='bull'
        cap=full if mode=='bull' else spec['bear_cap'] if mode=='bear' else 0.
        if day in feat:
            f=feat[day];both=f['k']>f['d'] and f['trix']>f['signal']
            if not risk:
                if blocked:
                    reason='价格保护后等待新信号'
                    if not both:blocked=False;reason='等待下一次双多头'
                elif both and cap>0:target=cap;reason='牛市信号进攻' if mode=='bull' else '熊市小仓反弹'
            elif both and ceiling==full:target=cap;reason='多头延续或恢复仓位'
            if risk and spec.get('signal_exit') and not both:
                target=0.;reason='周线双多头失效退出'
        gain=peak/entry-1 if risk else 0.;pullback=1-close/peak if risk else 0.
        if risk and gain>=spec['trail_arm']:
            if pullback>=spec['trail_exit']:target=0.;blocked=True;reason='涨后回落12%退出'
            elif pullback>=spec['trail_half']:ceiling=full/2;target=min(target,cap/2);reason='涨后回落8%减半'
        if risk and spec.get('initial_stop') and close/entry-1<=-spec['initial_stop']:
            target=0.;blocked=True;reason='入场参考价下跌8%退出'
        if risk and i-entered+1>=spec['hold_days'] and target>0:target=0.;reason=f"持满{spec['hold_days']}日退出"
        if target>cap:target=cap;reason='熊市减至防守仓位' if cap else '退出进攻ETF'
        if target!=risk:pending=(target,day)
        days.append(dict(date=day,market=applied_mode,close_market=mode,market_ma=last_ma,
                         risk=risk,next_risk=target,reason=reason,entry=entry,peak=peak,
                         holding_days=i-entered+1 if entered is not None else 0,blocked=blocked))
    return regime,events,days

def curve_metrics(curve,initial,start):
    vals=[x['equity'] for x in curve];peak=initial;mdd=0.;peak_day=start;pday=start;tday=start;prev=initial;ret=[];underwater=0;longest=0
    for row in curve:
        v=row['equity'];ret.append(v/prev-1);prev=v
        if v>=peak:peak=v;peak_day=row['date'];underwater=0
        else:underwater+=1;longest=max(longest,underwater)
        dd=1-v/peak
        if dd>mdd:mdd=dd;pday=peak_day;tday=row['date']
    years=(date.fromisoformat(curve[-1]['date'])-date.fromisoformat(start)).days/365.25
    return dict(final=vals[-1],total=vals[-1]/initial-1,cagr=(vals[-1]/initial)**(1/years)-1 if years else None,mdd=mdd,peak_date=pday,trough_date=tday,longest_underwater=longest,volatility=statistics.stdev(ret)*math.sqrt(242) if len(ret)>1 else 0,years=years)

def run_account(context,slippage=.0002,commission=.0003,save_daily=True,participation=None):
    CODES=context.codes;NAMES=context.names
    SPLIT_EFFECTIVE={c:{d:e['ratio'] for d,e in items.items()} for c,items in context.splits.items()}
    BARS=context.bars; CA=context.actions; ALL=context.all_bars
    DATES=context.dates; START=context.start; END=context.end; INITIAL=context.capital
    REGIME=context.regime; ATTACK_CHANGES=context.events; WEEK_CLOSE=context.week_close
    LOOK=context.look; targets=context.targets; spec=context.spec.copy()
    metric=lambda curve,initial=INITIAL,start=START:curve_metrics(curve,initial,start)
    cash=INITIAL;qty=[0]*3;lastclose=[0.]*3;lastbuy=[-1]*8;costsum=[0.]*3;pnl=[0.]*3;divtotal=[0.]*3;slips=[0.]*3;turn=[0.]*3
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
    receivable={};weights=(0.,)*3;desired=[0]*3;order_signal=START;capacity_limits={};limited=0
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
            if qty[j] and not b:missing.append([day,CODES[j]])
        if i==0 or (DATES[i-1] in WEEK_CLOSE) or day in ATTACK_CHANGES:
            signal_day=DATES[i-1] if i else context.previous_day
            candidate=targets(spec,signal_day,REGIME[i])
            if candidate!=w_prev:weights=candidate;do_rebalance=True;w_prev=candidate
            else:do_rebalance=False
        else:do_rebalance=False
        openpx=[b['open'] if b else lastclose[j] for j,b in enumerate(bars)]
        equity_open=cash+sum(q*px for q,px in zip(qty,openpx))+sum(receivable.values())
        # Isolate overnight P&L, including split-adjusted quantities.
        for j in range(3):pnl[j]+=qty[j]*openpx[j]-oldq[j]*oldclose[j]
        if do_rebalance:
            rebalance_count+=1
            order_signal=signal_day
            desired=[int(equity_open*weights[j]/(px*(1+slippage)))//100*100 if px and bars[j] else qty[j] for j,px in enumerate(openpx)]
        if do_rebalance or participation is not None:
            if i==len(DATES)-1:desired=[min(q,qty[j]) for j,q in enumerate(desired)]
            for side in [-1,1]:
                for j in range(3):
                    diff=desired[j]-qty[j]
                    if diff*side<=0 or not bars[j]:continue
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
        curve.append(dict(date=day,equity=equity,cash=cash,receivable=sum(receivable.values()),attack=REGIME[i],market=market.copy(),qty=qty.copy(),pnl=[pnl[j]-pnl_before[j] for j in range(3)]))
    # Common terminal liquidation, excluded from live trading signals.
    for j,q in enumerate(qty):
        if q:
            px=lastclose[j]*(1-slippage);fee=max(5,q*px*commission);cash+=q*px-fee;costsum[j]+=fee;slips[j]+=q*lastclose[j]*slippage;turn[j]+=q*px;loss=fee+q*lastclose[j]*slippage;pnl[j]-=loss;curve[-1]['pnl'][j]-=loss
            logs.append(dict(date=END,signal=END,asset=NAMES[j],symbol=CODES[j],side='期末清算',qty=q,price=px,fee=fee,slippage=q*lastclose[j]*slippage,cash=cash,reason='仅回测结算'))
    curve[-1]['equity']=cash+sum(receivable.values());curve[-1]['cash']=cash
    m=metric(curve);m.update(fees=sum(costsum),slippage=sum(slips),dividends=sum(divtotal),fills=len(logs),rebalances=rebalance_count,mean_attack=sum(x['market'][0]/x['equity'] for x in curve)/len(curve),mean_equity=sum(sum(x['market'][j] for j in [0])/x['equity'] for x in curve)/len(curve),mean_defense=sum(sum(x['market'][1:])/x['equity'] for x in curve)/len(curve),mean_cash=sum(x['cash']/x['equity'] for x in curve[:-1])/(len(curve)-1),min_cash=min(x['cash'] for x in curve),failed_lots=failed_lots)
    m['capacity_limited_orders']=limited
    curve[-1]['pre_liquidation_market']=curve[-1]['market'].copy();curve[-1]['pre_liquidation_qty']=curve[-1]['qty'].copy();curve[-1]['market']=[0.]*3;curve[-1]['qty']=[0]*3
    assert all(abs(x['equity']-x['cash']-x['receivable']-sum(x['market']))<1e-5 for x in curve)
    yearly=[];year_initial=INITIAL
    for yr in range(date.fromisoformat(START).year,date.fromisoformat(END).year+1):
        rows=[x for x in curve if x['date'].startswith(str(yr))]
        if not rows:continue
        mm=metric(rows,year_initial,rows[0]['date']);yearly.append(dict(year=yr,start=year_initial,end=rows[-1]['equity'],return_=rows[-1]['equity']/year_initial-1,mdd=mm['mdd']));year_initial=rows[-1]['equity']
    segments=[]
    attribution=[dict(asset=NAMES[j],symbol=CODES[j],pnl=pnl[j],dividends=divtotal[j],fees=costsum[j],slippage=slips[j],turnover=turn[j]) for j in range(3)]
    if missing:raise ValueError('持仓资产缺少精确行情：'+str(missing[:3]))
    assert abs(m['final']-INITIAL-sum(x['pnl'] for x in attribution))<1e-5
    return dict(spec=spec,metrics=m,yearly=yearly,segments=segments,attribution=attribution,logs=logs,actions=actions,curve=curve if save_daily else [])
