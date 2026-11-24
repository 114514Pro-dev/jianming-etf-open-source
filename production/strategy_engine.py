"""Bank ETF research engine. Causal indicators, frozen three-asset accounting.

This research schema is intentionally separate from the v1.1 application schema.
"""
from pathlib import Path
from datetime import date, timedelta
from bisect import bisect_right
from collections import OrderedDict
import sys, json, math, hashlib, itertools

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / 'engine_snapshot'))
from bear_gold_kernel import run_account

CODES = ['sh512800', 'sh518880', 'sh511010']
NAMES = ['银行ETF', '黄金ETF', '5年国债ETF']
FAMILIES = {'sk_trend':'SKDJ顺势', 'sk_rebound':'SKDJ低位反转',
            'tr_signal':'TRIX信号线', 'tr_zero':'TRIX零轴',
            'both':'SKDJ与TRIX共振', 'mixed':'日线SKDJ＋周线TRIX'}
DEFENSE = {'cash':'现金', 'bond':'国债', 'gold':'黄金', 'gold_trend':'黄金120日均线／国债'}
SK = [(3,5),(5,3),(9,3),(9,5),(14,3),(14,5),(21,5)]
TR = [(4,8),(8,5),(8,9),(12,9),(18,9),(30,9)]
PROFILES = [(0,0,0),(20,0,0),(60,.08,0),(120,0,.12)]

def write_json(path, obj):
    Path(path).write_text(json.dumps(obj,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')

def digest(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def spec_id(s):
    return s['family'] + '_' + digest({k:v for k,v in s.items() if k not in ('id','name')})[:12]

def named(s):
    s = dict(s)
    parts = [FAMILIES.get(s['family'],s['family']), '日线' if s['frame']=='D' else '周线']
    if s.get('sk'): parts.append('SKDJ('+','.join(map(str,s['sk']))+')')
    if s.get('tr'): parts.append('TRIX('+','.join(map(str,s['tr']))+')')
    if s.get('ma'): parts.append(str(s['ma'])+'周均线')
    if s.get('volume'): parts.append('放量1.2倍')
    if s.get('low'): parts.append('K≤'+str(s['low'])+'／退出K≥'+str(s['high']))
    if s.get('hold'): parts.append('最多'+str(s['hold'])+'交易日')
    if s.get('stop'): parts.append('止损'+format(s['stop'],'.0%'))
    if s.get('trail'): parts.append('跟踪止损'+format(s['trail'],'.0%'))
    s['name'] = ' · '.join(parts) + ' · 空仓配'+DEFENSE[s['defense']]
    s['id'] = spec_id(s)
    return s

def grid():
    out=[]
    def add(family, frame, sk=None, tr=None, ma=0, volume=False, profile=(0,0,0), **kw):
        out.append(named(dict(family=family,frame=frame,sk=sk,tr=tr,ma=ma,volume=volume,
                   hold=profile[0],stop=profile[1],trail=profile[2],defense='cash',**kw)))
    for sk,frame,ma,vol,p in itertools.product(SK,'DW',[0,20,50],[False,True],PROFILES):
        add('sk_trend',frame,sk=sk,ma=ma,volume=vol,profile=p)
    for sk,frame,ma,vol,lo,exit_ in itertools.product(SK,'DW',[0,20,50],[False,True],[20,30,40],[(20,70),(60,80)]):
        add('sk_rebound',frame,sk=sk,ma=ma,volume=vol,profile=(exit_[0],0,0),low=lo,high=exit_[1])
    for tr,frame,ma,vol,p in itertools.product(TR,'DW',[0,20,50],[False,True],PROFILES):
        add('tr_signal',frame,tr=tr,ma=ma,volume=vol,profile=p)
    for n,frame,ma,vol,p in itertools.product([4,8,12,18,30],'DW',[0,20,50],[False,True],PROFILES):
        add('tr_zero',frame,tr=(n,1),ma=ma,volume=vol,profile=p)
    for sk,tr,frame,ma,vol,p in itertools.product(SK,TR,'DW',[0,50],[False,True],[PROFILES[0],PROFILES[2],PROFILES[3]]):
        add('both',frame,sk=sk,tr=tr,ma=ma,volume=vol,profile=p)
    for sk,tr,ma,vol,p in itertools.product(SK,TR,[0,50],[False,True],[PROFILES[0],PROFILES[2],PROFILES[3]]):
        add('mixed','D',sk=sk,tr=tr,ma=ma,volume=vol,profile=p)
    assert len({x['id'] for x in out})==len(out)
    return out

def adjusted(bars, splits):
    factor=1.; out=[]
    for b in bars:
        factor*=splits.get(b['date'],{}).get('ratio',1.)
        out.append({**b,**{k:b[k]*factor for k in ('open','high','low','close')},
                    'volume_lots':b['volume_lots']/factor})
    return out

def weeks(bars):
    """Friday closes are available immediately. Holiday-short weeks become
    available at the first next-week close; never use an incomplete week.
    Omit initial partial week when listing did not begin on Monday.
    """
    groups=[]
    for b in bars:
        key=date.fromisoformat(b['date']).isocalendar()[:2]
        if not groups or groups[-1][0]!=key: groups.append([key,[]])
        groups[-1][1].append(b)
    out=[]
    for i,(_,g) in enumerate(groups):
        if i==0 and date.fromisoformat(g[0]['date']).weekday()!=0: continue
        if date.fromisoformat(g[-1]['date']).weekday()==4: available=g[-1]['date']
        elif i+1<len(groups): available=groups[i+1][1][0]['date']
        else: continue
        out.append(dict(date=available,week_end=g[-1]['date'],open=g[0]['open'],close=g[-1]['close'],
               high=max(b['high'] for b in g),low=min(b['low'] for b in g),
               volume_lots=sum(b['volume_lots'] for b in g),amount_cny=sum(b['amount_cny'] for b in g)))
    return out

def skdj(bars,n,m):
    rows=[]; ks=[]; raw=50.; sr=k=None; a=2/(m+1)
    for i,b in enumerate(bars):
        if i<n-1: rows.append(None); continue
        sub=bars[i-n+1:i+1]; lo=min(x['low'] for x in sub); hi=max(x['high'] for x in sub)
        raw=raw if hi==lo else 100*(b['close']-lo)/(hi-lo)
        sr=raw if sr is None else a*raw+(1-a)*sr
        k=sr if k is None else a*sr+(1-a)*k; ks.append(k)
        rows.append((k,math.fsum(ks[-m:])/m) if len(ks)>=m else None)
    return rows

def trix(bars,n,sig):
    rows=[]; history=[]; e1=e2=e3=prev=None; a=2/(n+1)
    for i,b in enumerate(bars):
        e1=b['close'] if e1 is None else a*b['close']+(1-a)*e1
        e2=e1 if e2 is None else a*e1+(1-a)*e2
        e3=e2 if e3 is None else a*e2+(1-a)*e3
        if prev is not None: history.append(100*(e3/prev-1))
        prev=e3
        rows.append((history[-1],math.fsum(history[-sig:])/sig) if i>=3*n+sig-2 and len(history)>=sig else None)
    return rows

class Market:
    def __init__(self,data):
        self.data=data; self.raw=data['bars'][CODES[0]]
        self.daily=adjusted(self.raw,data['split_adjustments'][CODES[0]])
        self.frames={'D':self.daily,'W':weeks(self.daily)}
        self.dates=[b['date'] for b in self.daily]
        self.cache={}; self.feature_cache=OrderedDict(); self.frame_dates={k:[b['date'] for b in v] for k,v in self.frames.items()}
        self.lookup={c:{b['date']:b for b in data['bars'][c]} for c in CODES}
        self.w_index=[bisect_right(self.frame_dates['W'],d)-1 for d in self.dates]
        self.ma_week={n:[math.fsum(z['close'] for z in self.frames['W'][i-n+1:i+1])/n if i>=n-1 else None
                            for i in range(len(self.frames['W']))] for n in (20,50)}
        self.vol={k:[b['volume_lots']/(math.fsum(z['volume_lots'] for z in v[i-20:i])/20)
                    if i>=20 and math.fsum(z['volume_lots'] for z in v[i-20:i])>0 else None
                    for i,b in enumerate(v)] for k,v in self.frames.items()}
        gb=adjusted(data['bars'][CODES[1]],data['split_adjustments'].get(CODES[1],{}))
        self.gold_bull={b['date']:i>=119 and b['close']>math.fsum(x['close'] for x in gb[i-119:i+1])/120 for i,b in enumerate(gb)}

    def indicator(self,kind,frame,param):
        key=(kind,frame,*param)
        if key not in self.cache: self.cache[key]=(skdj if kind=='sk' else trix)(self.frames[frame],*param)
        return self.cache[key]

    def features(self,s):
        key=('features',s['family'],s['frame'],tuple(s['sk'] or []),tuple(s['tr'] or []),s['ma'],s['volume'],s.get('low'),s.get('high'))
        if key in self.feature_cache:
            self.feature_cache.move_to_end(key)
            return self.feature_cache[key]
        si=self.indicator('sk',s['frame'],s['sk']) if s['sk'] else None
        tf='W' if s['family']=='mixed' else s['frame']
        ti=self.indicator('tr',tf,s['tr']) if s['tr'] else None
        out=[]
        for i,b in enumerate(self.daily):
            j=i if s['frame']=='D' else self.w_index[i]; tj=i if tf=='D' else self.w_index[i]
            a=si[j] if si is not None and j>=0 else None
            pa=si[j-1] if si is not None and j>=1 else None
            t=ti[tj] if ti is not None and tj>=0 else None
            ready=(si is None or a is not None) and (ti is None or t is not None)
            f=s['family']; positive=False; exit_=False
            if ready:
                if f=='sk_trend': positive=a[0]>a[1]; exit_=not positive
                elif f=='sk_rebound':
                    positive=pa is not None and pa[0]<=pa[1] and a[0]>a[1] and a[0]<=s['low']
                    exit_=a[0]>=s['high'] or a[0]<=a[1]
                elif f=='tr_signal': positive=t[0]>t[1]; exit_=not positive
                elif f=='tr_zero': positive=t[0]>0; exit_=not positive
                else: positive=a[0]>a[1] and t[0]>t[1]; exit_=not positive
            trend=True; ma=None; wj=self.w_index[i]
            if s['ma']:
                ma=self.ma_week[s['ma']][wj] if wj>=0 else None
                trend=ma is not None and self.frames['W'][wj]['close']>ma
            volume=self.vol[s['frame']][j] if j>=0 else None
            volume_ok=not s['volume'] or volume is not None and volume>=1.2
            frame_updated=s['frame']=='D' or j>=0 and self.frames['W'][j]['date']==b['date']
            # Weekly cross and volume entries are evaluated once per completed frame.
            entry=ready and positive and trend and volume_ok and (frame_updated or (f!='sk_rebound' and not s['volume']))
            out.append(dict(entry=entry,exit=ready and (exit_ or not trend),positive=positive and trend,
                            ready=ready,k=a[0] if a else None,d=a[1] if a else None,
                            trix=t[0] if t else None,signal=t[1] if t else None,ma=ma,volume_ratio=volume))
        self.feature_cache[key]=out
        if len(self.feature_cache)>16:self.feature_cache.popitem(last=False)
        return out

    def context(self,s,start,end,capital=100000):
        return ResearchContext(self,s,start,end,capital)

class ResearchContext:
    def __init__(self,market,s,start,end,capital):
        self.spec=s.copy(); self.codes=CODES; self.names=NAMES; self.general=True
        self.splits=market.data['split_adjustments']; self.bars=market.data['bars']
        self.actions=market.data['corporate_actions']; self.all_bars=market.raw
        self.look=market.lookup; self.capital=capital
        ix=[i for i,d in enumerate(market.dates) if start<=d<=end]
        if len(ix)<2:raise ValueError('区间至少2个交易日')
        self.dates=[market.dates[i] for i in ix]; self.start=self.dates[0]; self.end=self.dates[-1]
        self.previous_day=market.dates[ix[0]-1] if ix[0] else (date.fromisoformat(self.start)-timedelta(days=1)).isoformat()
        self.week_close=set(self.dates); self.regime=[]; self.events={}; self.decisions=[]
        self.gold_bull=market.gold_bull
        if s['family']=='buy_hold':self.regime=[1.]*len(ix);return
        if s['family']=='gold_hold':self.regime=[0.]*len(ix);return
        self.states=[]; features=market.features(s); risk=0.; pending=None; entered=None; entry=peak=None; blocked=False
        scan=([ix[0]-1] if ix[0] else [])+ix
        for i in scan:
            b=market.daily[i]; d=b['date']; is_account=d>=self.start
            if pending is not None and is_account:
                risk,signal,reason=pending; self.events[d]=signal
                if risk:entered=i;entry=peak=b['open']
                else:entered=entry=peak=None
                self.decisions.append(dict(date=d,signal=signal,bank_target=risk,reason=reason,features=features[i-1] if i else None))
                pending=None
            if is_account:self.regime.append(risk)
            f=features[i]
            if not f['positive']:blocked=False
            if risk:
                peak=max(peak,b['close']);reason=None
                if s.get('stop') and b['close']<=entry*(1-s['stop']):reason='收盘触发初始止损'
                elif s.get('trail') and b['close']<=peak*(1-s['trail']):reason='收盘触发跟踪止损'
                elif f['exit']:reason='指标退出／周均线过滤失效'
                elif s.get('hold') and i-entered+1>=s['hold']:reason='达到最长持有交易日'
                if reason:
                    pending=(0.,d,reason)
                    if reason!='指标退出／周均线过滤失效':blocked=True
            elif f['entry'] and not blocked:
                pending=(1.,d,'指标入场确认')
            if is_account:self.states.append(dict(date=d,risk=risk,next_risk=pending[0] if pending is not None else risk,holding_days=i-entered+1 if entered is not None else 0,entry=entry,peak=peak,reason=pending[2] if pending else ('继续持有银行参考仓位' if risk else '等待银行低位金叉')))
        assert len(self.regime)==len(self.dates)
        self.next_risk=pending[0] if pending is not None else risk
        self.last_state=dict(date=self.end,risk=risk,next_risk=self.next_risk,entry=entry,peak=peak,
             holding_days=(ix[-1]-entered+1 if entered is not None else 0),blocked=blocked,
             reason=pending[2] if pending else '继续持有银行参考仓位' if risk else '等待银行低位金叉')

    def targets(self,s,signal_day,risk):
        if s['family']=='gold_hold':return (0.,1.,0.)
        if risk:return (1.,0.,0.)
        mode=s['defense']
        if mode=='cash':return (0.,0.,0.)
        if mode=='bond':return (0.,0.,1.)
        if mode=='gold':return (0.,1.,0.)
        return (0.,1.,0.) if self.gold_bull.get(signal_day,False) else (0.,0.,1.)

def backtest(market,s,start,end,capital=100000,full=False,cost=1):
    ctx=market.context(s,start,end,capital)
    result=run_account(ctx,commission=.0003*cost,slippage=.0002*cost,save_daily=full)
    result['actual']=dict(start=ctx.start,end=ctx.end,days=len(ctx.dates))
    result['metrics']['bank_entries']=sum(z['symbol']==CODES[0] and z['side']=='买入' for z in result['logs'])
    if full:
        result['decisions']=ctx.decisions
        reasons={z['date']:z for z in ctx.decisions}
        for z in result['logs']:
            if z['date'] in reasons and z['side']!='期末清算':z['reason']=reasons[z['date']]['reason']
    else:result={k:result[k] for k in ('spec','metrics','actual')}
    return result

def baseline(kind):
    return dict(id=kind,name='银行ETF买入持有' if kind=='buy_hold' else '黄金ETF买入持有',
                family=kind,frame='D',sk=None,tr=None,ma=0,volume=False,hold=0,stop=0,trail=0,defense='cash')

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser(description='复算研究策略：收盘确认，下一交易日开盘执行。')
    p.add_argument('--strategy',required=True);p.add_argument('--data',default=str(HERE/'行情.json'))
    p.add_argument('--start',default='2017-08-03');p.add_argument('--end',default='2026-09-09')
    p.add_argument('--output',default='复算结果.json');a=p.parse_args()
    data=json.loads(Path(a.data).read_text(encoding='utf8'));s=json.loads(Path(a.strategy).read_text(encoding='utf8'))
    if 'spec' in s:s=s['spec']
    r=backtest(Market(data),s,a.start,a.end,full=True);write_json(a.output,r)
    print(json.dumps(r['metrics'],ensure_ascii=False,indent=2))
