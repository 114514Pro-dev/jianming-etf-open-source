"""Seven research combinations, portable replay and isolated paper accounts."""
from pathlib import Path
from types import SimpleNamespace
from copy import deepcopy
from datetime import date, datetime
import json, hashlib, math, threading, uuid
import numpy as np
import pandas as pd
from seven_vendor import top5_engine as ae
from seven_vendor.top5_indicators import make_signals as a_signal
from seven_vendor.bankgold_indicators import make_signals as defense_signal
from seven_vendor.continuous import continuous_bars
from seven_vendor.portfolio_account import run_account
import chinext_engine as be
from chinext_indicators import make_signals as b_signal
from simulator_core import write_json

DATA=Path(__file__).resolve().parent/'data/seven'
SCHEMA='seven.paper.v1'
CODES=['sz159920','sh512800','sh518880']
NAMES=['恒生指数ETF 159915','银行ETF 512800','黄金ETF 518880']
CATALOG=json.loads((DATA/'catalog.json').read_text(encoding='utf-8-sig'))
TAGS={'A_T5VOTE_P2':'较高收益·两份独立本金','A_T5VOTE_P3':'收益与回撤折中·三份本金',
      'A_T5SUPER_P3':'较低回撤·三份本金','B_D7':'本组回撤最低·均线过滤',
      'B_D5':'本组年化最高·高回撤','B_D4':'黄金持有对照·高回撤','B_D6':'银行黄金切换·高回撤'}
BY_ID={r['research_id']:dict(r,tag=TAGS[r['research_id']]) for r in CATALOG['candidates']}
ORDER=list(BY_ID)
SHORT={'A_T5VOTE_P2':'三指标＋黄金各半','A_T5VOTE_P3':'三指标50/银行25/黄金25','A_T5SUPER_P3':'Supertrend50/银行25/黄金25',
       'B_D7':'三资产MA200过滤','B_D5':'恒生指数→黄金周线/现金','B_D4':'恒生指数→黄金持有','B_D6':'恒生指数→银行/黄金'}
def label(code):return code+'  '+SHORT[code]+'【'+TAGS[code]+'】'
def digest(x):return hashlib.sha256(json.dumps(ae.clean_json(x),ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def capital_value(value):
    try:v=float(value)
    except (TypeError,ValueError):raise ValueError('本金请输入有效数字。')
    if not math.isfinite(v) or not 1000<=v<=1e10:raise ValueError('本金须为1,000至100亿元之间的有限数字。')
    return v
def metric(curve,capital):
    eq=np.r_[capital,[r['equity'] for r in curve]]
    days=(date.fromisoformat(curve[-1]['date'])-date.fromisoformat(curve[0]['date'])).days
    return dict(total_return=float(eq[-1]/capital-1),cagr=float((eq[-1]/capital)**(365.25/days)-1) if days>=365 else None,
                max_drawdown=float(1-np.min(eq/np.maximum.accumulate(eq))),final_equity=float(eq[-1]),days=len(curve))
def router_weights(code,row):
    c,b,g=(float(row[k]) for k in ['chi_vote','bank_trix','gold_don'])
    if code=='B_D4':return (1.,0.,0.) if c else (0.,0.,1.)
    if code=='B_D5':return (1.,0.,0.) if c else (0.,0.,g)
    if code=='B_D6':return (1.,0.,0.) if c else (0.,.5*b,.5*g)
    if code=='B_D7':return tuple(float(row[k+'_ma200'])/3 for k in CODES)
    raise ValueError('未知组合。')

class SevenService:
    def __init__(self,folder,market_service=None,top5=None):
        self.folder=Path(folder)/'七组合模拟';self.folder.mkdir(parents=True,exist_ok=True)
        self.market_service=market_service;self.top5=top5;self.lock=threading.RLock();self.cache={};self.signal_cache={}
        self.settings_path=self.folder/'设置.json'
        if self.settings_path.exists():self.settings=read(self.settings_path)
        else:
            market=read(DATA/'market.json');bars={};actions={};splits={}
            for c in CODES:
                side=market['bank' if c=='sh512800' else 'chi']
                bars[c]=side['bars'][c];actions[c]=side['corporate_actions'][c];splits[c]=side['split_adjustments'][c]
            h=pd.read_csv(DATA/'hourly.csv').to_dict('records')
            snap=dict(bars=bars,actions=actions,splits=splits,hourly=h,calendar=read(DATA/'calendar.json'),schema=SCHEMA)
            self.settings={'snapshot':self.store(snap)};write_json(self.settings_path,self.settings)
        self.snapshot()
    def store(self,snap):
        sid=digest(snap);p=self.folder/'行情快照'/(sid+'.json')
        if not p.exists():write_json(p,ae.clean_json(snap))
        return sid
    def snapshot(self,sid=None):
        sid=sid or self.settings['snapshot']
        if len(sid)!=64 or any(c not in '0123456789abcdef' for c in sid):raise ValueError('七组合行情编号无效。')
        snap=read(self.folder/'行情快照'/(sid+'.json'))
        if digest(snap)!=sid:raise ValueError('七组合行情完整性校验失败。')
        return snap
    def info(self,snap=None):
        snap=snap or self.snapshot()
        full={r['datetime'][:10] for r in snap['hourly'] if r['datetime'].endswith('15:00:00')}
        common=sorted(full.intersection(*[{r['date'] for r in snap['bars'][c]} for c in CODES]))
        if not common:raise ValueError('缺少共同完整交易日。')
        return dict(latest=common[-1],hourly=snap['hourly'][-1]['datetime'],earliest='2023-01-03')
    def sync(self):
        """Append only validated source rows; never fetch or advance accounts here."""
        with self.lock:
            old=self.snapshot();new=deepcopy(old)
            if self.market_service:
                m=self.market_service.market
                for c in CODES:
                    last=old['bars'][c][-1]['date'];fresh={r['date']:r for r in m.bars[c]}
                    # All overlapping price, volume and corporate-action history is immutable.
                    for r in old['bars'][c]:
                        if r['date'] in fresh:
                            for k in ['open','high','low','close','volume_lots']:
                                if r.get(k)!=fresh[r['date']].get(k):raise ValueError(f'{c} {r["date"]} {k}历史被修订；七组合保留旧快照。')
                    new['bars'][c]+= [r for d,r in sorted(fresh.items()) if d>last]
                    for d,e in old['splits'][c].items():
                        if d<=last and m.inputs.splits[c].get(d)!=e:raise ValueError('历史拆分记录不一致。')
                    prior=[r for r in m.inputs.actions[c]['dividends'] if min(r.get(k,'9999') for k in ['record','ex','pay'])<=last]
                    known=[r for r in old['actions'][c]['dividends'] if min(r.get(k,'9999') for k in ['record','ex','pay'])<=last]
                    if prior!=known:raise ValueError('历史分红记录不一致。')
                    new['actions'][c]=deepcopy(m.inputs.actions[c]);new['splits'][c]=deepcopy(m.inputs.splits[c])
            if self.top5:
                t=self.top5._snapshot();fresh={r['datetime']:r for r in t['hourly']};last=old['hourly'][-1]['datetime']
                for r in old['hourly']:
                    if r['datetime'] in fresh:
                        for k in ['open','high','low','close','volume']:
                            if r.get(k)!=fresh[r['datetime']].get(k):raise ValueError('60分钟历史发生修订；保留七组合旧快照。')
                new['hourly'] += [r for stamp,r in sorted(fresh.items()) if stamp>last]
                sessions=t['calendar']['sessions']
                if [d for d in sessions if d<=last[:10]]!=[d for d in old['calendar']['sessions'] if d<=last[:10]]:raise ValueError('历史交易日历发生修订。')
                new['calendar']=deepcopy(t['calendar'])
            dates=[d for d in new['calendar']['sessions'] if '2023-01-03'<=d<=self.info(new)['latest']]
            for c in CODES:
                if not set(dates)<={r['date'] for r in new['bars'][c]}:raise ValueError('共同交易区间缺少日线，保留旧快照。')
            sid=self.store(new);self.settings['snapshot']=sid;write_json(self.settings_path,self.settings)
            return self.info(new)
    def inputs(self,snap,end,intraday=False):
        cutoff=pd.Timestamp(end)+pd.Timedelta(hours=15)
        h=pd.DataFrame(snap['hourly']);h.index=pd.to_datetime(h.pop('datetime'));h['open_time']=h.index-pd.Timedelta(hours=1)
        if not intraday:h=h.loc[h.index<=cutoff]
        raw={c:[r for r in snap['bars'][c] if r['date']<=end] for c in CODES}
        dates=sorted(set.intersection(*[{r['date'] for r in raw[c]} for c in CODES]))
        calendar=pd.to_datetime(snap['calendar']['sessions'])
        frames={c:continuous_bars(raw[c],snap['splits'][c]) for c in CODES}
        key=(digest(snap),end,intraday)
        if key in self.signal_cache:return raw,dates,h,self.signal_cache[key]
        ai=pd.to_datetime([d for d in snap['calendar']['sessions'] if d<=end])+pd.Timedelta(hours=15)
        ag=ae.aggregate_bars(frames[CODES[2]],h.iloc[:0],'W',calendar)
        a_states={}
        for key_,f,sid in [('bank',frames[CODES[1]],2),('gold',ag,8)]:
            sig=defense_signal(f,sid,'base');s=ae.signal_state(sig)
            a_states[key_]=s.reindex(s.index.union(ai)).sort_index().ffill().reindex(ai).fillna(0)
        am={i:a_signal(h,i) for i in [4,8,11,12]}
        signals={'T5VOTE':ae.combine_same(am,[4,8,11],2,2),'T5SUPER':am[12]}
        index=pd.to_datetime(dates)+pd.Timedelta(hours=15)
        vote=be.combine_same({i:b_signal(h,i) for i in [4,8,11]},[4,8,11],2,2)
        bw=be.aggregate_bars(frames[CODES[2]],h.iloc[:0],'W',calendar+pd.Timedelta(hours=15))
        bs={'chi_vote':vote,'bank_trix':b_signal(frames[CODES[1]],2),'gold_don':b_signal(bw,8)}
        states=pd.DataFrame(index=index)
        for name,sig in bs.items():
            state=be.signal_state(sig);states[name]=state.reindex(state.index.union(index)).sort_index().ffill().reindex(index)
        for c,f in frames.items():
            ma=f.close.rolling(200,min_periods=200).mean();states[c+'_ma200']=(f.close>ma).where(ma.notna()).reindex(index)
        states.index=states.index.strftime('%Y-%m-%d')
        for name,s in a_states.items():s.index=s.index.strftime('%Y-%m-%d')
        bundle=(signals,a_states,states);self.signal_cache[key]=bundle
        if len(self.signal_cache)>4:self.signal_cache.pop(next(iter(self.signal_cache)))
        return raw,dates,h,bundle
    def run(self,code,start='2023-01-03',end=None,capital=100000,terminal=True,variant='base',sid=None,intraday=False):
        if code not in BY_ID:raise ValueError('未知七组合编号。')
        if variant not in ['base','cost2','delay']:raise ValueError('未知成本情景。')
        capital=capital_value(capital);snap=self.snapshot(sid);sid=digest(snap);info=self.info(snap)
        try:start=date.fromisoformat(start).isoformat();end=date.fromisoformat(end or info['latest']).isoformat()
        except (ValueError,TypeError):raise ValueError('日期应为YYYY-MM-DD。')
        if start<'2023-01-03' or end>info['latest'] or start>end:raise ValueError('七组合支持2023-01-03至'+info['latest']+'，开始日期不能晚于结束日期。')
        intraday=bool(intraday and code.startswith('A_') and not terminal and end==info['latest'])
        cachekey=(code,start,end,capital,terminal,variant,sid,intraday)
        if cachekey in self.cache:return deepcopy(self.cache[cachekey])
        raw,all_dates,h,(signals,states,b_states)=self.inputs(snap,end,intraday)
        fullhourly={str(t.date()) for t in h.index if t.hour==15}
        dates=[d for d in all_dates if start<=d<=end and d in fullhourly]
        if not dates:raise ValueError('所选区间没有共同完整交易日。')
        start,end=dates[0],dates[-1];previous=all_dates[all_dates.index(start)-1];factor=2 if variant=='cost2' else 1
        def account(codes,amount,target):
            ctx=SimpleNamespace(codes=codes,names=[NAMES[CODES.index(c)] for c in codes],splits={c:snap['splits'][c] for c in codes},
                bars={c:raw[c] for c in codes},actions={c:snap['actions'][c] for c in codes},all_bars=raw[codes[0]],dates=dates,
                start=start,end=end,capital=amount,regime=[0.]*len(dates),events={},week_close=set(dates),look={c:{b['date']:b for b in raw[c]} for c in codes},
                spec={'id':code,'name':BY_ID[code]['name']},previous_day=previous,targets=target,general=True,suspensions={},trade_blocks={})
            return run_account(ctx,commission=.0003*factor,slippage=.0002*factor,terminal_liquidation=terminal)
        def lag(day):return all_dates[max(0,all_dates.index(day)-int(variant=='delay'))]
        legs=[];events=[];actions=[];leg_states={};fees=0.;slips=0.;targets={c:0. for c in CODES};budgets={c:0. for c in CODES}
        if code.startswith('A_'):
            chi='T5SUPER' if 'SUPER' in code else 'T5VOTE';signals_=signals[chi]
            _,daily,book,_,_=ae.simulate(h,signals_,start,case_id=code,initial=capital*.5,commission=.0003*factor,slippage=.0002*factor,delay=int(variant=='delay'),terminal_liquidation=terminal,t_plus=0)
            chi_curve=[dict(date=str(i.date()),equity=float(r.equity),cash=float(r.cash),receivable=0.,market=[float(r.equity-r.cash)],qty=[int(r.shares)]) for i,r in daily.iterrows() if str(i.date()) in dates]
            ce=[dict(e,symbol=CODES[0],leg='恒生指数独立本金') for e in book.attrs['events']]
            events.extend(ce);fees+=sum(e['fee'] for e in ce)
            # The native hourly engine handles latched T+1 exits independently of model intent.
            st=book.attrs['state'];lastsig=signals_.iloc[-1]
            leg_states[CODES[0]]=dict(st,signal_time=str(signals_.index[-1]),entry=bool(lastsig.entry),exit=bool(lastsig.exit))
            hold=(st['shares']>0 and not st['pending_exit'] and not bool(lastsig.exit)) or (st['shares']==0 and bool(lastsig.ready) and bool(lastsig.entry))
            equity=float(book.iloc[-1].equity);budgets[CODES[0]]=equity;targets[CODES[0]]=equity if hold else 0.
            legs.append(chi_curve)
            defense=[('gold',CODES[2],.5)] if code.endswith('P2') else [('bank',CODES[1],.25),('gold',CODES[2],.25)]
            for key_,c,w in defense:
                b=account([c],capital*w,lambda spec,day,risk,key_=key_:(float(states[key_].loc[lag(day)]),))
                legs.append(b['curve']);fees+=b['metrics']['fees'];slips+=b['metrics']['slippage']
                actions.extend(b['actions']);leg_states[c]=dict(b['curve'][-1],signal_intent=float(states[key_].loc[end]))
                events.extend(dict(e,leg=key_,time=e['date']+(' 15:00:00' if e['side']=='期末清算' else ' 09:30:00')) for e in b['logs'])
                budgets[c]=b['curve'][-1]['equity'];targets[c]=budgets[c]*float(states[key_].loc[end])
            curve=[]
            for i,d in enumerate(dates):
                rows=[leg[i] for leg in legs]
                curve.append(dict(date=d,equity=sum(r['equity'] for r in rows),cash=sum(r['cash'] for r in rows),receivable=sum(r['receivable'] for r in rows),
                                  market_value=sum(sum(r['market']) for r in rows)))
            execution='独立本金各自复利；恒生指数在下一60分钟开盘执行，银行/黄金在下一交易日开盘执行；不在子账户间再平衡。'
        else:
            if b_states.loc[previous:end].isna().any().any():raise ValueError('组合指标尚未完成预热。')
            b=account(CODES,capital,lambda spec,day,risk:(0.,0.,0.) if variant=='delay' and day==previous else router_weights(code,b_states.loc[lag(day)]))
            curve=[dict(date=r['date'],equity=r['equity'],cash=r['cash'],receivable=r['receivable'],market_value=sum(r['market']),qty=r['qty']) for r in b['curve']]
            events=[dict(e,time=e['date']+(' 15:00:00' if e['side']=='期末清算' else ' 09:30:00')) for e in b['logs']]
            fees=b['metrics']['fees'];slips=b['metrics']['slippage'];equity=curve[-1]['equity']
            actions=b['actions'];leg_states=dict(last_close=b['curve'][-1],signal_values=b_states.loc[end].to_dict())
            targets=dict(zip(CODES,[w*equity for w in router_weights(code,b_states.loc[end])]))
            budgets=dict(zip(CODES,b['curve'][-1]['market']))
            execution='15点确认信号，目标组合变化时在下一交易日实际开盘调仓；目标不变时持仓自然漂移。'
        events.sort(key=lambda e:e['time'])
        virtual_equity=sum(budgets.values()) if code.startswith('A_') else curve[-1]['equity']
        weights={c:targets[c]/virtual_equity for c in CODES}
        result=ae.clean_json(dict(strategy=code,name=BY_ID[code]['name'],tag=TAGS[code],start=start,end=end,capital=capital,snapshot=sid,
            terminal=terminal,variant=variant,metrics=dict(metric(curve,capital),fees=fees,fills=len(events)),curve=curve,events=events,corporate_actions=actions,leg_states=leg_states,
            plan=dict(weights=weights,cash_weight=max(0.,1-sum(weights.values())),virtual_equity=virtual_equity,execution=execution,
                      as_of=info['hourly'] if intraday else end+' 15:00:00',daily_as_of=end,independent_budgets=budgets)))
        self.cache[cachekey]=result
        if len(self.cache)>48:self.cache.pop(next(iter(self.cache)))
        return deepcopy(result)
    def compare(self,start,end,capital,progress=lambda _:None):
        out=[];sid=self.settings['snapshot']
        for code in ORDER:
            progress('正在复算七组合：'+code);out.append(self.run(code,start,end,capital,sid=sid))
        return out
    def create_account(self,code,name,capital,start):
        if not name.strip():raise ValueError('请输入账户名称。')
        result=self.run(code,start,start,capital,terminal=False)
        a=dict(schema=SCHEMA,id=uuid.uuid4().hex,name=name.strip(),created=datetime.now().isoformat(),result=result)
        self._save_account(a);return a
    def _save_account(self,a):
        a=deepcopy(a);a.pop('integrity',None);a['integrity']=digest(a)
        write_json(self.folder/'账户'/(a['id']+'.json'),a)
    def get_account(self,id):
        if len(id)!=32 or any(c not in '0123456789abcdef' for c in id):raise ValueError('账户编号无效。')
        a=read(self.folder/'账户'/(id+'.json'));h=a.pop('integrity')
        if digest(a)!=h or a['schema']!=SCHEMA:raise ValueError('账户校验不符，停止接续。')
        return a
    def accounts(self):return [self.get_account(p.stem) for p in sorted((self.folder/'账户').glob('*.json'))]
    def advance(self,id,end):
        with self.lock:
            a=self.get_account(id);old=a['result']
            date.fromisoformat(end)
            if end<=old['end']:return a
            r=self.run(old['strategy'],old['start'],end,old['capital'],terminal=False)
            if [x for x in r['curve'] if x['date']<=old['end']]!=old['curve'] or [e for e in r['events'] if e['time'][:10]<=old['end']]!=old['events']:
                raise ValueError('历史账户前缀不一致，拒绝改写既有成交。')
            a['result']=r;self._save_account(a);return a
    def export_account(self,id,path):
        a=self.get_account(id);write_json(path,dict(schema=SCHEMA,account=a,snapshot=self.snapshot(a['result']['snapshot'])))
    def import_account(self,path):
        payload=read(path)
        if payload.get('schema')!=SCHEMA:raise ValueError('不是七组合账户备份。')
        a=payload['account'];r=a['result'];snap=payload['snapshot']
        if digest(snap)!=r['snapshot']:raise ValueError('备份行情校验不符。')
        sid=self.store(snap);replay=self.run(r['strategy'],r['start'],r['end'],r['capital'],terminal=False,sid=sid)
        if replay!=r:raise ValueError('备份账户与重新记账不一致。')
        a=deepcopy(a);a['id']=uuid.uuid4().hex;a['name']+='（导入）';self._save_account(a);return a
