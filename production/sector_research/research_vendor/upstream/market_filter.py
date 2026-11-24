"""Ten separately funded sector sleeves. Offline research; no production accounts."""
from pathlib import Path
from datetime import date,datetime,timezone
from decimal import Decimal,ROUND_HALF_UP,ROUND_CEILING,ROUND_FLOOR
import json,hashlib,bisect,statistics,math,sys
import pandas as pd
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'vendor'))
import indicators
MODELS=['HOLD','TRIX','ENTRY_GATE','FULL_GATE','HALF_HOLD']
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def write(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,separators=(',',':'),allow_nan=False),encoding='utf-8')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def D(x):return Decimal(str(x))
def money(x):return D(x).quantize(D('.01'),rounding=ROUND_HALF_UP)
def fee(n,rate,minimum=5):return money(max(D(minimum),D(n)*D(rate))) if n else D(0)
def fill(o,side,rate,ticks):
    o=D(o);slip=max(o*D(rate),D('.001')*D(ticks))
    return ((o+slip if side=='BUY' else o-slip)/D('.001')).to_integral_value(rounding=ROUND_CEILING if side=='BUY' else ROUND_FLOOR)*D('.001')

class Study:
    def __init__(self,root=ROOT,market=None,index_data=None):
        self.root=Path(root);self.protocol=read(self.root/'protocol.json')
        self.market=market if market is not None else read(self.root/'data/market.json')
        self.calendar=self.market['calendar'];self.assets=self.market['assets'];self.cache={}
        self.index_data=index_data if index_data is not None else read(self.root/'data_index/index_data.json')
        rows=self.index_data['series']['CSI_ALL_PRICE'];n=self.protocol['market_filter']['window']
        assert len({r['date'] for r in rows})==len(rows) and rows==sorted(rows,key=lambda r:r['date'])
        self.market_features={}
        for i,r in enumerate(rows):
            assert r['close']>0
            ma=sum(D(x['close']) for x in rows[i-n+1:i+1])/D(n) if i>=n-1 else None
            self.market_features[r['date']]={'market_observation_date':r['date'],'market_close':r['close'],'market_ma120':float(ma) if ma is not None else None,'market_allowed':bool(ma is not None and D(r['close'])>ma),'market_ready':ma is not None}
    def gate(self,decision):
        assert decision in self.market_features, 'Missing exact market-index date: '+decision
        r=self.market_features[decision]
        assert r['market_ready'], 'Insufficient MA120 history: '+decision
        return r
    def features(self,code):
        if code in self.cache:return self.cache[code]
        a=self.assets[code];bars=a['bars'];factor=1.;adjusted=[];prevday=None;prevclose=None
        actions=sorted([{'date':s['ex_date'],'kind':'split',**s} for s in a['splits']]+[{'date':d['ex_date'],'kind':'dividend',**d} for d in a['dividends']],key=lambda x:(x['date'],x['kind']))
        for b in bars:
            applied=[]
            if prevday is not None:
                ref=prevclose
                for e in actions:
                    if prevday<e['date']<=b['date']:
                        if e['kind']=='split':factor*=e['ratio'];ref/=e['ratio']
                        else:
                            assert ref>e['cash_per_share'];factor*=ref/(ref-e['cash_per_share']);ref-=e['cash_per_share']
                        applied.append(e['event_id'])
            adjusted.append({'date':b['date'],**{k:b[k]*factor for k in ['open','high','low','close']},'factor':factor,'actions':applied})
            prevday=b['date'];prevclose=b['close']
        f=pd.DataFrame(adjusted).set_index('date');signals={m:indicators.make_signals(f,2 if m=='TRIX' else 1,'base') for m in ['TRIX','SKDJ']}
        state={'TRIX':False,'SKDJ':False};rows=[]
        for i,b in enumerate(adjusted):
            r={'date':b['date'],'factor':b['factor'],'signal_close':b['close'],'actions':b['actions']}
            for m in state:
                s=signals[m].iloc[i]
                if s['entry']:state[m]=True
                if s['exit']:state[m]=False
                r.update({m+'_ready':bool(s['ready']),m+'_entry':bool(s['entry']),m+'_exit':bool(s['exit']),m+'_long':bool(state[m] and s['ready'])})
            rows.append(r)
        self.cache[code]=rows;return rows
    def run(self,code,model,start=None,end=None,commission_rate=.0003,minimum_commission=5,slippage_rate=.0002,minimum_slippage_ticks=1,delay=1,capital=None):
        p=self.protocol;start=start or p['period']['start'];end=end or p['period']['end']
        lo=bisect.bisect_left(self.calendar,start);hi=bisect.bisect_right(self.calendar,end)
        assert self.calendar[lo]==start and self.calendar[hi-1]==end and hi>lo
        a=self.assets[code];bars=a['bars'];dates=[b['date'] for b in bars];bmap={b['date']:b for b in bars};features=self.features(code)
        first=bisect.bisect_left(dates,start)-1;assert first>=0
        assert all(features[first][m+'_ready'] for m in ['TRIX','SKDJ'])
        initial=D(p['sleeve_capital'] if capital is None else capital);cash=initial;shares=0;mark=D(bars[first]['close']);markday=dates[first]
        once=False;entitlements={};receivables={};curve=[];trades=[];events=[];blocked=0
        for i in range(lo,hi):
            day=self.calendar[i];prior=self.calendar[i-1];decision=self.calendar[i-delay]
            f=features[bisect.bisect_right(dates,decision)-1]
            g=self.gate(decision);sector_long=f['TRIX_long']
            if model in ['HOLD','HALF_HOLD']:target=True
            elif model=='TRIX':target=sector_long
            elif model=='ENTRY_GATE':target=sector_long and (shares>0 or g['market_allowed'])
            elif model=='FULL_GATE':target=sector_long and g['market_allowed']
            else:raise ValueError(model)
            allowed=i-lo>=delay-1
            # Economic rights accrue on ex-date; payment later turns the receivable into cash.
            for e in a['dividends']:
                eid=e['event_id']
                if prior<e['ex_date']<=day:
                    qty=entitlements.get(eid,0);amount=money(D(qty)*D(e['cash_per_share']))
                    if amount:
                        receivables[eid]=amount;events.append({'date':day,'event_date':e['ex_date'],'event_id':eid,'type':'dividend_receivable','eligible_shares':qty,'cash_per_share':e['cash_per_share'],'amount':float(amount)})
                    mark-=D(e['cash_per_share']);assert mark>0
            for e in a['splits']:
                if prior<e['ex_date']<=day:
                    old=shares;new=D(shares)*D(e['ratio']);assert new==new.to_integral_value()
                    shares=int(new);mark/=D(e['ratio'])
                    if old:events.append({'date':day,'event_date':e['ex_date'],'event_id':e['event_id'],'type':'split','before':old,'after':shares,'ratio':e['ratio']})
            for e in a['dividends']:
                eid=e['event_id']
                if prior<e['pay_date']<day and eid in receivables:
                    amount=receivables.pop(eid);cash=money(cash+amount)
                    events.append({'date':day,'event_date':e['pay_date'],'event_id':eid,'type':'dividend_payment','amount':float(amount)})
            b=bmap.get(day);side=None
            if allowed:
                if model in ['HOLD','HALF_HOLD']:
                    if not once:side='BUY'
                elif target and shares==0:side='BUY'
                elif not target and shares>0:side='SELL'
            if side and (b is None or b['open']<=0 or b['amount_cny']<=0):blocked+=1;side=None
            if side:
                price=fill(b['open'],side,slippage_rate,minimum_slippage_ticks);assert price>0
                if side=='BUY':
                    budget=min(cash,initial/2) if model=='HALF_HOLD' else cash
                    qty=int((budget/(price*100)).to_integral_value(rounding=ROUND_FLOOR))*100
                    while qty and money(price*qty)+fee(money(price*qty),commission_rate,minimum_commission)>budget:qty-=100
                else:qty=shares
                if qty:
                    amount=money(price*qty);commission=fee(amount,commission_rate,minimum_commission);before=cash;old=shares
                    if side=='BUY':cash=money(cash-amount-commission);shares+=qty
                    else:cash=money(cash+amount-commission);shares-=qty
                    trades.append({'date':day,'side':side,'shares':qty,'raw_open':b['open'],'fill':float(price),'notional':float(amount),'commission':float(commission),'slippage_cost':float(D(qty)*abs(price-D(b['open']))),'cash_before':float(before),'cash_after':float(cash),'shares_before':old,'shares_after':shares,'decision_date':decision,'signal_observation_date':f['date'],'sector_long':sector_long,**g,'target':target,'source_day_amount':b['amount_cny'],'participation_day_amount':float(amount/D(b['amount_cny'])),'fill_outside_recorded_range':price<D(b['low']) or price>D(b['high'])})
                    once=True
            # Registration takes end-of-day holdings, including same-day buys and excluding same-day sales.
            for e in a['dividends']:
                if e['record_date']==day:
                    entitlements[e['event_id']]=shares
                    if shares:events.append({'date':day,'event_date':day,'event_id':e['event_id'],'type':'dividend_registration','eligible_shares':shares})
            # Published payment day is credited after today's trading: available next market open.
            for e in a['dividends']:
                eid=e['event_id']
                if e['pay_date']==day and eid in receivables:
                    amount=receivables.pop(eid);cash=money(cash+amount)
                    events.append({'date':day,'event_date':day,'event_id':eid,'type':'dividend_payment','amount':float(amount)})
            assert cash>=0 and shares>=0 and shares%100==0
            if b:mark=D(b['close']);markday=day
            recv=sum(receivables.values(),D(0));mv=money(D(shares)*mark);value=money(cash+mv+recv)
            curve.append({'date':day,'equity':float(value),'cash':float(cash),'shares':shares,'security_value':float(mv),'dividend_receivable':float(recv),'mark_close':float(mark),'mark_source_date':markday,'stale_mark':markday!=day,'exposure':float(mv/value),'applied_target':bool(target and allowed),'decision_date':decision,'signal_observation_date':f['date'],'sector_long':sector_long,**g})
        return {'code':code,'sector':a['identity']['sector'],'model':model,'start':start,'end':end,'parameters':{'commission_rate':commission_rate,'minimum_commission':minimum_commission,'slippage_rate':slippage_rate,'minimum_slippage_ticks':minimum_slippage_ticks,'delay':delay,'capital':float(initial)},'metrics':{**metrics(curve,trades,float(initial)),'blocked_orders':blocked,'dividend_received':sum(e['amount'] for e in events if e['type']=='dividend_payment')},'curve':curve,'trades':trades,'corporate_events':events,'years':yearly(curve,float(initial))}

def metrics(curve,trades,initial):
    years=(date.fromisoformat(curve[-1]['date'])-date.fromisoformat(curve[0]['date'])).days/365.25
    peak=initial;peakdate=curve[0]['date'];maxdd=0.;worstpeak=peakdate;trough=peakdate;longest=0;under=0;prev=initial;rets=[];recover=None
    for r in curve:
        v=r['equity'];rets.append(v/prev-1);prev=v
        if v>=peak:peak=v;peakdate=r['date'];under=0
        else:under+=1;longest=max(longest,under)
        dd=1-v/peak
        if dd>maxdd:maxdd=dd;worstpeak=peakdate;trough=r['date'];worstlevel=peak
    if maxdd:
        recover=next((r['date'] for r in curve if r['date']>trough and r['equity']>=worstlevel),None)
    final=curve[-1]['equity'];parts=[x['participation_day_amount'] for x in trades]
    return {'initial':initial,'final_equity':final,'net_profit':final-initial,'total_return':final/initial-1,'cagr':(final/initial)**(1/years)-1,'calendar_years':years,'market_days':len(curve),'max_drawdown':maxdd,'max_drawdown_peak':worstpeak,'max_drawdown_trough':trough,'max_drawdown_recovery':recover,'longest_underwater_market_days':longest,'current_underwater_market_days':under,'annual_volatility':statistics.stdev(rets)*math.sqrt(252),'average_exposure':statistics.mean(x['exposure'] for x in curve),'trades':len(trades),'commission':sum(x['commission'] for x in trades),'slippage_cost':sum(x['slippage_cost'] for x in trades),'turnover_times_initial':sum(x['notional'] for x in trades)/initial,'fills_outside_day_range':sum(x['fill_outside_recorded_range'] for x in trades),'max_participation_day_amount':max(parts,default=0),'trades_above_one_pct_day_amount':sum(p>.01 for p in parts),'trades_above_total_day_amount':sum(p>1 for p in parts),'stale_mark_days':sum(x['stale_mark'] for x in curve),'end_cash':curve[-1]['cash'],'end_receivable':curve[-1]['dividend_receivable']}
def yearly(curve,initial):
    out=[];prior=initial
    for y in sorted({x['date'][:4] for x in curve}):
        rows=[x for x in curve if x['date'].startswith(y)];last=rows[-1]['equity']
        out.append({'year':y,'start':rows[0]['date'],'end':rows[-1]['date'],'initial':prior,'final':last,'return':last/prior-1});prior=last
    return out
def portfolio(accounts,initial):
    dates=[r['date'] for r in accounts[0]['curve']];curve=[];trades=[]
    assert all([r['date'] for r in a['curve']]==dates for a in accounts)
    for i,d in enumerate(dates):
        components=[a['curve'][i] for a in accounts]
        total={k:float(sum((D(r[k]) for r in components),D(0))) for k in ['equity','cash','security_value','dividend_receivable']}
        assert money(total['equity'])==money(D(total['cash'])+D(total['security_value'])+D(total['dividend_receivable']))
        curve.append({'date':d,**total,'exposure':total['security_value']/total['equity'],'invested_sleeves':sum(r['shares']>0 for r in components),'stale_mark':any(r['stale_mark'] for r in components),'sleeve_equity':{a['code']:a['curve'][i]['equity'] for a in accounts}})
    for a in accounts:trades.extend([{**t,'code':a['code']} for t in a['trades']])
    trades.sort(key=lambda x:(x['date'],x['code']))
    contributions=[{'code':a['code'],'sector':a['sector'],'profit':a['metrics']['net_profit'],'contribution_to_initial_total':a['metrics']['net_profit']/initial,'final_weight':a['metrics']['final_equity']/curve[-1]['equity']} for a in accounts]
    return {'model':accounts[0]['model'],'start':dates[0],'end':dates[-1],'metrics':metrics(curve,trades,initial),'curve':curve,'years':yearly(curve,initial),'contributions':contributions,'trades':trades}
def experiment():
    receipt=read(ROOT/'freeze_receipt.json')
    for rel,h in receipt['inputs'].items():assert sha(ROOT/rel)==h,rel
    assert not (ROOT/'output/results.json').exists(),'Preserve existing output before rerunning.'
    s=Study();started=datetime.now(timezone.utc).isoformat();groups=[]
    core=MODELS[:4]
    setups=[('primary',{},MODELS),('double_cost',{'commission_rate':.0006,'minimum_commission':10,'slippage_rate':.0004,'minimum_slippage_ticks':2},core),('extra_day',{'delay':2},core)]
    for a,b in s.protocol['fixed_periods']:setups.append(('period/'+a,{'start':a,'end':b},core))
    for name,params,models in setups:
        for m in models:
            sleeves=[s.run(c,m,**params) for c in s.protocol['codes']]
            groups.append({'case_id':name+'/'+m,'group':name,'model':m,'sleeves':sleeves,'portfolio':portfolio(sleeves,s.protocol['total_capital'])})
    assert len(groups)==21 and sum(len(g['sleeves']) for g in groups)==210
    result={'study':s.protocol['study'],'started_utc':started,'finished_utc':datetime.now(timezone.utc).isoformat(),'input_hashes':receipt['inputs'],'portfolio_cases':21,'sleeve_cases':210,'groups':groups}
    write(ROOT/'output/results.json',result)
    write(ROOT/'output/daily_features.json',{c:s.features(c) for c in s.assets})
    write(ROOT/'output/market_features.json',list(s.market_features.values()))
    print(json.dumps({g['case_id']:{k:g['portfolio']['metrics'][k] for k in ['cagr','max_drawdown','final_equity','average_exposure','trades']} for g in groups},ensure_ascii=False,indent=2))
if __name__=='__main__':experiment()
