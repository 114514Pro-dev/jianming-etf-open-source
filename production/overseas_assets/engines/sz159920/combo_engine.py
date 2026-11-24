"""Fixed, interpretable combinations of two already researched strategies."""
from strategy_engine import Market,write_json,digest,HERE
from bear_gold_kernel import Context,run_account as original_account,curve_metrics
from portfolio_account import run_account
from datetime import date,timedelta
from copy import deepcopy
from bisect import bisect_right
import json,math,statistics

CODES=['sz159920','sh512800','sh518880','sh511010']
NAMES=['恒生指数ETF','银行ETF','黄金ETF','5年国债ETF']
SUSPENSIONS={'sz159920':{'2021-02-08'}}
# Daily OHLC on the resumption date opens at 10:30. Do not use that price
# for a 09:30 simultaneous basket; defer its orders to the next normal open.
TRADE_BLOCKS={'sz159920':{'2021-02-08','2021-02-09'}}

def specifications():
    s=[dict(id='chi',name='原恒生指数50周策略',kind='fixed',w=1,bank='A',group='control'),
       dict(id='bank',name='银行A：SKDJ(9,5)＋黄金',kind='fixed',w=0,bank='A',group='control')]
    for w in [.25,.5,.75]:
        s.append(dict(id='blend'+str(round(w*100)),name=f'目标预算：恒生指数{w:.0%}／银行{1-w:.0%}',kind='fixed',w=w,bank='A',group='primary'))
    for bull,bear in [(1,0),(.8,.2),(.6,.4)]:
        s.append(dict(id='regime'+str(round(bull*100)),name=f'牛熊切换：牛市恒生指数{bull:.0%}／熊市{bear:.0%}',kind='regime',bull=bull,bear=bear,bank='A',group='primary'))
    s.extend([
        dict(id='residual',name='恒生指数进攻优先，剩余预算运行银行A',kind='residual',bank='A',group='primary'),
        dict(id='sleeves50',name='各5万元独立运行，不相互调拨',kind='sleeves',w=.5,bank='A',group='primary'),
        dict(id='bankB',name='银行B：SKDJ(21,5)＋黄金',kind='fixed',w=0,bank='B',group='sensitivity'),
        dict(id='blend50B',name='50／50目标预算，银行改用B参数',kind='fixed',w=.5,bank='B',group='sensitivity'),
        dict(id='regime80B',name='牛80%／熊20%，银行改用B参数',kind='regime',bull=.8,bear=.2,bank='B',group='sensitivity'),
        dict(id='chi_hold',name='恒生指数ETF买入持有',kind='hold',weights=(1,0,0,0),bank='A',group='control'),
        dict(id='bank_hold',name='银行ETF买入持有',kind='hold',weights=(0,1,0,0),bank='A',group='control'),
        dict(id='gold_hold',name='黄金ETF买入持有',kind='hold',weights=(0,0,1,0),bank='A',group='control'),
        dict(id='dual_hold',name='恒生指数／银行各半买入，之后持有',kind='hold',weights=(.5,.5,0,0),bank='A',group='control')])
    return s

class Inputs:
    def __init__(self,chi=None,bank=None):
        self.chi=chi or json.loads((HERE/'恒生指数行情.json').read_text(encoding='utf8'))
        self.bank=bank or json.loads((HERE/'银行行情.json').read_text(encoding='utf8'))
        for c in CODES[2:]:
            assert self.chi['bars'][c]==self.bank['bars'][c],c+'行情不同'
            assert self.chi['corporate_actions'][c]==self.bank['corporate_actions'][c],c+'分红不同'
        self.chi_spec=json.loads((HERE/'原恒生指数策略.json').read_text(encoding='utf8'))['rule']
        self.bank_specs={k:json.loads((HERE/f'银行{k}策略.json').read_text(encoding='utf8'))['spec'] for k in ['A','B']}
        self.market=Market(self.bank)
        self.bars={c:(self.bank if c=='sh512800' else self.chi)['bars'][c] for c in CODES}
        self.actions={c:(self.bank if c=='sh512800' else self.chi)['corporate_actions'][c] for c in CODES}
        self.splits={c:(self.bank if c=='sh512800' else self.chi)['split_adjustments'][c] for c in CODES}
        self.look={c:{b['date']:b for b in self.bars[c]} for c in CODES}
        self.cache={}

    def components(self,start,end):
        key=(start,end)
        if key in self.cache:return self.cache[key]
        chi=Context(self.chi,start,end,100000,self.chi_spec)
        bank={k:self.market.context(s,start,end,100000) for k,s in self.bank_specs.items()}
        dates=bank['A'].dates
        assert set(dates)-set(chi.dates)<=SUSPENSIONS['sz159920']
        for c in CODES:assert all(d in self.look[c] or d in SUSPENSIONS.get(c,set()) for d in dates)
        def target_schedule(ctx):
            weights=None;out=[]
            for i,d in enumerate(ctx.dates):
                prev=ctx.previous_day if i==0 else ctx.dates[i-1]
                if i==0 or prev in ctx.week_close or d in ctx.events:
                    weights=ctx.targets(ctx.spec,prev,ctx.regime[i])
                out.append(weights)
            return out
        native_ct=target_schedule(chi);bt={k:target_schedule(c) for k,c in bank.items()}
        ct=[];modes=[]
        for d in dates:
            j=bisect_right(chi.dates,d)-1
            ct.append(native_ct[j] if j>=0 else (0.,0.,0.))
            modes.append(chi.states[j]['market'] if j>=0 and chi.dates[j]==d else chi.states[j]['close_market'] if j>=0 else 'warmup')
        # 'market' is the regime known before this day's open, while
        # 'close_market' is only available after today's close.
        r=dict(chi=chi,bank=bank,chi_targets=ct,bank_targets=bt,modes=modes,dates=dates)
        self.cache[key]=r;return r

class Portfolio:
    def __init__(self,inputs,s,start,end,capital):
        parts=inputs.components(start,end);chi=parts['chi'];bank=parts['bank'][s['bank']]
        self.spec=deepcopy(s);self.codes=CODES;self.names=NAMES;self.general=True
        self.splits=inputs.splits;self.bars=inputs.bars;self.actions=inputs.actions;self.look=inputs.look
        self.suspensions=SUSPENSIONS;self.trade_blocks=TRADE_BLOCKS
        self.all_bars=inputs.bars[CODES[0]];self.dates=parts['dates'];self.start=self.dates[0];self.end=self.dates[-1]
        self.previous_day=chi.previous_day;self.capital=capital;self.week_close=set(self.dates)
        self.events={};self.regime=[];self.target_history=[];self.by_signal={}
        prev_w=None
        for i,d in enumerate(self.dates):
            c=parts['chi_targets'][i];b=parts['bank_targets'][s['bank']][i];mode=parts['modes'][i]
            if s['kind']=='hold':w=tuple(s['weights']);budget=None
            elif s['kind']=='residual':
                budget=c[0]
                w=(c[0],(1-c[0])*b[0],(1-c[0])*b[1],(1-c[0])*b[2])
                if 'bear_stock_cap' in s and mode!='bull':
                    cap=s['bear_stock_cap'] if mode=='bear' else 0.
                    stock=w[0]+w[1]
                    if stock>cap:
                        ratio=cap/stock
                        w=(w[0]*ratio,w[1]*ratio,w[2]+stock-cap,w[3])
            else:
                budget=s['w'] if s['kind']=='fixed' else s['bull'] if mode=='bull' else s['bear']
                w=(budget*c[0],(1-budget)*b[0],budget*c[1]+(1-budget)*b[1],budget*c[2]+(1-budget)*b[2])
            assert all(x>=-1e-12 for x in w) and sum(w)<=1+1e-12
            signal=self.previous_day if i==0 else self.dates[i-1]
            self.by_signal[signal]=w;self.regime.append(w[0]+w[1])
            if w!=prev_w:self.events[d]=signal
            self.target_history.append(dict(date=d,signal=signal,weights=list(w),market_before_open=mode,
                chi_strategy_budget=budget,chi_reference_targets=list(c),bank_reference_targets=list(b)))
            prev_w=w

    def targets(self,s,signal,risk):return self.by_signal[signal]

def expand_curve(r,source):
    mapping=[0,2,3] if source=='chi' else [1,2,3]
    for row in r['curve']:
        for field in ['market','qty','pnl','pre_liquidation_market','pre_liquidation_qty']:
            if field in row:
                arr=[0.]*4
                for j,k in enumerate(mapping):arr[k]=row[field][j]
                row[field]=arr
    return r

def sleeves(inputs,s,start,end,capital,cost):
    a=backtest(inputs,dict(id='chi_sleeve',name='恒生指数子账户',kind='fixed',w=1,bank=s['bank']),start,end,capital*s['w'],cost)
    b=backtest(inputs,dict(id='bank_sleeve',name='银行子账户',kind='fixed',w=0,bank=s['bank']),start,end,capital*(1-s['w']),cost)
    curve=[]
    for x,y in zip(a['curve'],b['curve']):
        assert x['date']==y['date'];row={'date':x['date']}
        for k in ['cash','equity','receivable']:row[k]=x[k]+y[k]
        for k in ['market','qty','pnl']:row[k]=[v+w for v,w in zip(x[k],y[k])]
        if 'pre_liquidation_market' in x:
            for k in ['pre_liquidation_market','pre_liquidation_qty']:row[k]=[v+w for v,w in zip(x[k],y[k])]
        row['attack']=(row['market'][0]+row['market'][1])/row['equity'];curve.append(row)
    m=curve_metrics(curve,capital,a['actual']['start'])
    for k in ['fees','slippage','fills','rebalances','dividends','failed_lots','capacity_limited_orders']:m[k]=a['metrics'][k]+b['metrics'][k]
    m['min_cash']=min(z['cash'] for z in curve)
    yearly=[];prev=capital
    for yr in sorted({x['date'][:4] for x in curve}):
        rows=[x for x in curve if x['date'].startswith(yr)]
        mm=curve_metrics(rows,prev,rows[0]['date']);yearly.append(dict(year=int(yr),start=prev,end=rows[-1]['equity'],return_=rows[-1]['equity']/prev-1,mdd=mm['mdd']));prev=rows[-1]['equity']
    attrs=[]
    for c,name in zip(CODES,NAMES):
        rows=[z for r in (a,b) for z in r['attribution'] if z['symbol']==c]
        attrs.append(dict(symbol=c,asset=name,**{k:sum(z[k] for z in rows) for k in ['pnl','dividends','fees','slippage','turnover']}))
    logs=sorted([{**z,'sleeve':name} for name,r in [('恒生指数子账户',a),('银行子账户',b)] for z in r['logs']],key=lambda z:z['date'])
    return dict(spec=s,curve=curve,metrics=m,yearly=yearly,attribution=attrs,logs=logs,actions=a['actions']+b['actions'],
                actual=a['actual'],target_history=[])

def backtest(inputs,s,start,end,capital=100000,cost=1):
    if s['kind']=='sleeves':r=sleeves(inputs,s,start,end,capital,cost)
    else:
        c=Portfolio(inputs,s,start,end,capital)
        r=run_account(c,commission=.0003*cost,slippage=.0002*cost,save_daily=True)
        r['target_history']=c.target_history;r['actual']=dict(start=c.start,end=c.end,days=len(c.dates))
        for z in r['logs']:
            if z['side']!='期末清算':z['reason']='组合目标仓位变化，合并同一ETF订单'
    rows=r['curve'];m=r['metrics']
    terminal_cost=sum(z['fee']+z['slippage'] for z in r['logs'] if z['side']=='期末清算')
    weights=[[v/(z['equity']+(terminal_cost if 'pre_liquidation_market' in z else 0)) for v in z.get('pre_liquidation_market',z['market'])] for z in rows]
    m['mean_weights']=[statistics.mean(x[j] for x in weights) for j in range(4)]
    m['mean_equity']=m['mean_weights'][0]+m['mean_weights'][1]
    m['mean_attack']=m['mean_equity'];m['mean_defense']=sum(m['mean_weights'][2:])
    m['mean_cash']=statistics.mean(z['cash']/z['equity'] for z in rows[:-1])
    m['maximum_stock_weight']=max(sum(x[:2]) for x in weights)
    assert abs(m['final']-capital-sum(z['pnl'] for z in r['attribution']))<1e-5
    for z in rows:assert abs(z['equity']-z['cash']-z['receivable']-sum(z['market']))<1e-5
    return r

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description='恒生指数50周＋银行SKDJ组合复算')
    p.add_argument('--strategy',default='blend50',choices=[s['id'] for s in specifications()])
    p.add_argument('--start',default='2017-08-03');p.add_argument('--end',default='2026-09-09')
    p.add_argument('--capital',type=float,default=100000);p.add_argument('--output',default='组合复算结果.json')
    p.add_argument('--bank-variant',choices=['A','B'],help='仅用于参数敏感性复算，覆盖银行参数')
    p.add_argument('--bear-stock-cap',type=float,help='剩余预算方案的熊市股票目标总仓位上限，例如0.2')
    args=p.parse_args();s=next(s for s in specifications() if s['id']==args.strategy)
    if args.bank_variant:s={**s,'bank':args.bank_variant,'name':s['name']+'（银行参数'+args.bank_variant+'）'}
    if args.bear_stock_cap is not None:
        if s['kind']!='residual' or not 0<=args.bear_stock_cap<=1:p.error('总仓位上限仅用于residual，范围0—1')
        s={**s,'bear_stock_cap':args.bear_stock_cap,'name':s['name']+f'（熊市股票目标仓≤{args.bear_stock_cap:.0%}）'}
    r=backtest(Inputs(),s,args.start,args.end,args.capital);write_json(args.output,r)
    print(json.dumps(r['metrics'],ensure_ascii=False,indent=2))
