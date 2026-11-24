"""Frozen-parameter cross-border study. Isolated data, memory-only accounts."""
from pathlib import Path
import sys,json,hashlib,contextlib,copy,collections,math
from datetime import date
from types import SimpleNamespace
import pandas as pd
import numpy as np
R=Path(__file__).resolve().parent/'overseas_assets'
REQUEST=json.loads(Path(sys.argv[1]).read_text('utf8'))
SNAP=json.loads(Path(REQUEST['snapshot_path']).read_text('utf8'))
TARGET=REQUEST['target']
ENGINE=R/'engines'/TARGET
sys.path[:0]=[str(ENGINE),str(ENGINE/'engine_snapshot')]
import bear_gold as gold,bear_gold_assets as assets,bank_model,combo_engine
import trade_book as ledger
from suite_book import SuiteBook
import chinext_engine as ce
from chinext_indicators import make_signals
import seven_service as seven
from seven_vendor.continuous import continuous_bars
from seven_vendor.portfolio_account import run_account as daily_account
from simulator_core import ORDER,TITLES
from functools import lru_cache

END=REQUEST['end'];START=REQUEST['start'];CAPITAL=float(REQUEST['capital'])
NAMES={'sh513100':'纳指100 ETF 513100','sz159920':'恒生ETF 159920','sh513180':'恒生科技ETF 513180',
       'sh512800':'银行ETF 512800','sh518880':'黄金ETF 518880','sh511010':'国债ETF 511010'}
CODES=[TARGET,'sh512800','sh518880','sh511010']
RAW={c:copy.deepcopy(SNAP['datasets'][c]) for c in CODES}
CAL=SNAP['calendar']
for d in RAW.values():
 d['bars']=[r for r in d['bars'] if r['date']<=END]
 d['hourly']=[r for r in d['hourly'] if r['datetime'][:10]<=END]
 for k in d['actions']:d['actions'][k]=[r for r in d['actions'][k] if r.get('ex',r.get('date',''))<=END] if isinstance(d['actions'][k],list) else d['actions'][k]
gold.FIRST.pop(TARGET,None)
SPLIT_URL='https://st.gtfund.com/report/2022/01/国泰基金管理有限公司关于纳斯达克100交易型开放式指数证券投资基金实施基金份额拆分及相关业务安排的第二次提示性公告.pdf'
assets.SPLITS['sh513100']={'2022-01-13':dict(effective='2022-01-14',ratio=5.0,rounding='floor',source=SPLIT_URL)}
SPLITS={c:assets.approved_splits(c,RAW[c]['actions']['splits'],RAW[c]['bars'][0]['date'],END) for c in CODES}
def dataset(c):
 codes=[c,'sh518880','sh511010']
 return gold.validate_dataset(dict(schema=assets.DATA_SCHEMA,asof=END,attack_symbol=c,
  asset_names={x:NAMES[x] for x in codes},first_dates={x:RAW[x]['bars'][0]['date'] for x in codes},
  history_start={x:RAW[x]['profile'][1] for x in codes},split_adjustments={x:SPLITS[x] for x in codes},
  bars={x:RAW[x]['bars'] for x in codes},corporate_actions={x:RAW[x]['actions'] for x in codes},source_mode='research_frozen'))
PAIR={'chi':dataset(TARGET),'bank':dataset('sh512800')}
combo_engine.SUSPENSIONS={TARGET:{'2022-01-13'} if TARGET=='sh513100' else set()}
combo_engine.TRADE_BLOCKS={TARGET:{'2022-01-13'} if TARGET=='sh513100' else set()}
ledger.T0.add(TARGET)

# On partial-opening days execute the entire daily basket at the first common
# observed hourly open, preserving funding chronology across all its legs.
HLOOK={c:{r['datetime']:r for r in RAW[c]['hourly']} for c in CODES}
HGROUP={c:collections.defaultdict(list) for c in CODES}
for c in CODES:
 for stamp in HLOOK[c]:HGROUP[c][stamp[:10]].append(stamp)
EXEC={}
for day,stamps in HGROUP[TARGET].items():
 if stamps[0].endswith('10:30:00'):continue
 common=sorted(set.intersection(*[set(HGROUP[c].get(day,[])) for c in CODES]))
 if not common:raise ValueError('缺少共同执行行情 '+day)
 stamp=common[0];EXEC[day]=dict(time=str(pd.Timestamp(stamp)-pd.Timedelta(hours=1)),prices={c:HLOOK[c][stamp]['open'] for c in CODES})

def exec_market(pair=PAIR):
 m=ledger.Market(pair);native=m.at
 def at(day,opening=False):
  q=native(day,opening)
  if opening and day in EXEC:q['prices']=dict(EXEC[day]['prices'])
  return q
 m.at=at
 obs=m.observation
 @lru_cache(maxsize=60000)
 def cached(code,day):return obs(code,day)
 m.observation=lambda code,day:copy.deepcopy(cached(code,day))
 return m

def measure(curve,events,capital=CAPITAL):
 eq=np.r_[capital,[x['equity'] for x in curve]];days=(date.fromisoformat(curve[-1]['date'])-date.fromisoformat(curve[0]['date'])).days
 annual=[];prior=capital
 for year in sorted({r['date'][:4] for r in curve}):
  vals=np.array([r['equity'] for r in curve if r['date'].startswith(year)]);seq=np.r_[prior,vals]
  annual.append(dict(year=year,return_=float(vals[-1]/prior-1),max_drawdown=float(1-np.min(seq/np.maximum.accumulate(seq)))))
  prior=vals[-1]
 return dict(total_return=float(eq[-1]/capital-1),cagr=float((eq[-1]/capital)**(365.25/days)-1) if days>=365 else None,
  max_drawdown=float(1-np.min(eq/np.maximum.accumulate(eq))),final_equity=float(eq[-1]),fees=sum(x['fee'] for x in events),fills=len(events),annual=annual,
  average_cash=float(np.mean([r['cash']/r['equity'] for r in curve])),days=len(curve))

class MemoryBook(SuiteBook):
 """Identical inherited advance/evaluate/fill code without any SQLite writes."""
 def __init__(self):self.state=None;self.fills=[];self.actions=[]
 @contextlib.contextmanager
 def connection(self):yield self
 def execute(self,query,params):
  assert query.startswith('INSERT INTO accounts');self.state=json.loads(params[-1])
 def get(self,id,con=None):return self.state
 def save(self,con,s):ledger.validate(s);s['revision']+=1;self.state=s
 def event(self,con,s,kind,payload,id=None):
  if kind=='策略成交':
   e={k:v for k,v in payload.items() if k not in ['features','reason']}
   if REQUEST.get('signal_board'):e['reason']=payload.get('reason','按已确认目标模拟执行。')
   e.update(time=EXEC.get(s['day'],{}).get('time',s['day']+' 09:30:00'))
   self.fills.append(e)
  elif kind in ['份额折算','应收分红','分红到账']:self.actions.append(dict(date=s['day'],kind=kind,**payload))

def old9(m,code,start,end=END,variant='base'):
 factor=2 if variant=='cost2' else 1;ledger.RATE=.0003*factor;ledger.SLIP=.0002*factor
 previous=m.dates[m.dates.index(start)-1];book=MemoryBook();book.create(code,CAPITAL,previous,m,code)
 original=m.observation
 if variant=='delay':
  def obs(c,d):
   prior=m.dates[m.dates.index(d)-1];x=original(c,prior)
   if d==previous:x['weights']={c:0. for c in CODES}
   x['information_date']=prior;x['day']=d;return x
  m.observation=obs
 try:s=book.advance(book.state['id'],m,end)
 finally:m.observation=original
 if REQUEST.get('signal_board'):
  from web_signal_model import original_model
  from web_signal_activity import attach_activity
  return attach_activity(original_model(s,m),book.fills)
 curve=[dict(date=r['day'],equity=r['equity'],cash=r['cash'],market_value=r['market'],receivable=r['receivable']) for r in s['curve'] if r['day']>=start]
 attribution=[]
 for c in CODES:
  p=s['positions'][c];px=m.at(end)['prices'][c]
  realized=sum(e['realized_pnl'] for e in book.fills if e['symbol']==c)
  div=sum(e['amount'] for e in book.actions if e['kind']=='应收分红' and e['symbol']==c)
  attribution.append(dict(symbol=c,pnl=realized+p['qty']*px-p['cost']+div,fees=sum(e['fee'] for e in book.fills if e['symbol']==c)))
 assert abs(sum(a['pnl'] for a in attribution)-(curve[-1]['equity']-CAPITAL))<.06
 return dict(strategy=code,name=TITLES[code],group='原9配置',target=TARGET,variant=variant,start=start,end=end,capital=CAPITAL,
  metrics=measure(curve,book.fills),curve=curve,events=book.fills,corporate_actions=book.actions,
  final_positions={c:p['qty'] for c,p in s['positions'].items()},next_target=s['auto']['last_observation']['weights'],attribution=attribution)

def five_inputs(end=END):
 raw=[r for r in RAW[TARGET]['bars'] if r['date']<=end]
 daily=continuous_bars(raw,SPLITS[TARGET])
 h=pd.DataFrame([r for r in RAW[TARGET]['hourly'] if r['datetime'][:10]<=end]);h.index=pd.to_datetime(h.pop('datetime'));h['open_time']=h.index-pd.Timedelta(hours=1)
 weekly=ce.aggregate_bars(daily,h,'W',pd.to_datetime(CAL['sessions']))
 sm={i:make_signals(h,i) for i in [4,8,11,12,14]}
 signals={'T5VOTE':ce.combine_same(sm,[4,8,11],2,2),'T5WEEK':make_signals(weekly,15),'T5DON':sm[8],'T5SUPER':sm[12],'T5MA':sm[14]}
 return h,signals

def five(h,signals,code,variant='base',start=START):
 factor=2 if variant=='cost2' else 1
 mt,day,book,trades,annual=ce.simulate(h,signals[code],start,code,commission=.0003*factor,slippage=.0002*factor,
  delay=int(variant=='delay'),fixed_hold=20 if code=='T5WEEK' else None,terminal_liquidation=False,t_plus=0,initial=CAPITAL)
 events=[dict(x,symbol=TARGET) for x in book.attrs['events']]
 curve=[dict(date=str(i.date()),equity=float(r.equity),cash=float(r.cash),market_value=float(r.equity-r.cash),receivable=0.) for i,r in day.iterrows()]
 return dict(strategy=code,name=code,group='5个目标ETF择时',target=TARGET,variant=variant,start=start,end=curve[-1]['date'],capital=CAPITAL,
  metrics=measure(curve,events),curve=curve,events=events,final_positions={TARGET:int(book.attrs['state']['shares'])},engine_state=book.attrs['state'])

class ResearchSeven(seven.SevenService):
 def __init__(self):
  self.snap=dict(schema=seven.SCHEMA,bars={c:RAW[c]['bars'] for c in CODES[:3]},actions={c:RAW[c]['actions'] for c in CODES[:3]},
   splits={c:SPLITS[c] for c in CODES[:3]},hourly=RAW[TARGET]['hourly'],calendar=CAL)
  self.cache={};self.signal_cache={};self.settings={'snapshot':seven.digest(self.snap)}
 def snapshot(self,sid=None):return self.snap

ACCOUNT_RESULTS=[]
def synchronized_account(ctx,**kwargs):
 if TARGET in ctx.codes and len(ctx.codes)>1:
  ctx.look=copy.deepcopy(ctx.look)
  for day,item in EXEC.items():
   for c in ctx.codes:
    if day in ctx.look[c]:ctx.look[c][day]['open']=item['prices'][c]
 result=daily_account(ctx,**kwargs)
 ACCOUNT_RESULTS.append(result)
 for e in result['logs']:
  if TARGET in ctx.codes and len(ctx.codes)>1 and e['date'] in EXEC:e['execution_time']=EXEC[e['date']]['time']
 return result
seven.run_account=synchronized_account

def seven_run(service,code,variant='base'):
 ACCOUNT_RESULTS.clear()
 r=service.run(code,START,END,CAPITAL,terminal=False,variant=variant)
 for e in r['events']:
  if e.get('execution_time'):e['time']=e['execution_time']
 r.update(group='7个多资产组合',target=TARGET)
 r['metrics']=measure(r['curve'],r['events'])
 if code.startswith('A_'):
  attribution=[a for result in ACCOUNT_RESULTS for a in result['attribution']]
  target_pnl=r['metrics']['final_equity']-CAPITAL-sum(a['pnl'] for a in attribution)
  attribution.insert(0,dict(symbol=TARGET,pnl=target_pnl,fees=sum(e['fee'] for e in r['events'] if e['symbol']==TARGET)))
 else:attribution=ACCOUNT_RESULTS[-1]['attribution']
 assert abs(sum(a['pnl'] for a in attribution)-(r['metrics']['final_equity']-CAPITAL))<1e-5
 r['attribution']=attribution
 return r

def benchmark(codes,weights,start=START,end=END,code='BENCH',variant='base'):
 dates=[d for d in CAL['sessions'] if start<=d<=end];prior=CAL['sessions'][CAL['sessions'].index(start)-1]
 curves=[];events=[];actions=[];factor=2 if variant=='cost2' else 1
 for c,w in zip(codes,weights):
  bars=RAW[c]['bars'];lookup={r['date']:r for r in bars}
  ctx=SimpleNamespace(codes=[c],names=[NAMES[c]],splits={c:SPLITS[c]},bars={c:bars},actions={c:RAW[c]['actions']},all_bars=bars,
   dates=dates,start=start,end=end,capital=CAPITAL*w,regime=[0.]*len(dates),events={},week_close=set(dates),look={c:lookup},
   spec=dict(id=code),previous_day=prior,targets=lambda spec,day,risk:(1.,),general=True,
   suspensions=combo_engine.SUSPENSIONS,trade_blocks=combo_engine.TRADE_BLOCKS)
  b=daily_account(ctx,commission=.0003*factor,slippage=.0002*factor,terminal_liquidation=False)
  curves.append(b['curve']);events.extend(b['logs']);actions.extend(b['actions'])
 curve=[dict(date=d,equity=sum(a[i]['equity'] for a in curves),cash=sum(a[i]['cash'] for a in curves),receivable=sum(a[i]['receivable'] for a in curves),market_value=sum(sum(a[i]['market']) for a in curves)) for i,d in enumerate(dates)]
 return dict(strategy=code,name=code,group='对照基准',target=TARGET,variant=variant,start=start,end=end,capital=CAPITAL,metrics=measure(curve,events),curve=curve,events=events,corporate_actions=actions)

def save(path,obj):path.write_text(json.dumps(ce.clean_json(obj),ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
def main():
 results=[];m=None;inputs=None;svc=None
 for code in REQUEST['strategies']:
  if code in ORDER:
   if m is None:m=exec_market()
   r=old9(m,code,START)
  elif code.startswith('T5'):
   if inputs is None:inputs=five_inputs()
   # Hourly engine has no corporate-action cash ledger. Refuse unsupported changes.
   if any(START<=x.get('ex',x.get('date',''))<=END for rows in RAW[TARGET]['actions'].values() if isinstance(rows,list) for x in rows):raise ValueError('择时策略期间出现公司行动，需先扩展并核验小时账本。')
   r=five(*inputs,code)
   es=r['engine_state'];sig=inputs[1][code];latest=sig.iloc[-1];held=bool(es['shares']);ready=bool(latest.ready)
   closed=sig.index[-1]==pd.Timestamp(es['last_bar'])
   sell=bool(held and (es['pending_exit'] or (ready and closed and latest['exit'])))
   buy=bool(ready and closed and latest.entry and not held)
   weights={TARGET:float(ready and not sell and (held or buy))}
   r['next_target']=weights
   r['reference_note']=('待卖出' if sell else '待买入' if buy else '继续持有' if held else '现金等待')+'；使用完整周期信号，下一根真实完整K线开盘执行。'
   if REQUEST.get('signal_board'):
    from web_signal_model import top_model
    from web_signal_activity import attach_activity
    from chinext_service import BY_ID
    r=attach_activity(top_model(code,es,latest,str(sig.index[-1]),BY_ID[code]['parameters']+'。'+BY_ID[code]['description'],TARGET,0),r['events'])
  elif code in seven.ORDER:
   if svc is None:svc=ResearchSeven()
   r=seven_run(svc,code)
   if code.startswith('A_'):
    target_state=r['leg_states']['target'] if 'target' in r['leg_states'] else None
   r['next_target']=r['plan']['weights']
   if REQUEST.get('signal_board'):
    from web_signal_model import seven_model
    from web_signal_activity import attach_activity
    r=attach_activity(seven_model(r,svc,TARGET),r['events'])
  else:raise ValueError('未知海外策略')
  if not REQUEST.get('signal_board'):r['prices']={c:RAW[c]['bars'][-1]['close'] for c in CODES}
  results.append(r)
 Path(sys.argv[2]).write_text(json.dumps(ce.clean_json(results),ensure_ascii=False,allow_nan=False,separators=(',',':')),encoding='utf8')
if __name__=='__main__':main()
