"""Three independent signal engines; the user's four-state allocation."""
from pathlib import Path
from datetime import datetime,timedelta,timezone
from bisect import bisect_right
from copy import deepcopy
import os,json,statistics
import combo_engine as engine
from combo_engine import Inputs,CODES,NAMES
import bear_gold as gold,bear_gold_assets as assets,skdj
from bear_gold_kernel import Context,features,build_schedule
from strategy_engine import digest
from allocation import combine
HERE=Path(__file__).resolve().parent;CN=timezone(timedelta(hours=8));ANCHOR='2017-08-03'
LABELS={'F20':'分阶段四资产 · 股票底仓20%','F10':'分阶段四资产 · 股票底仓10%','F0':'分阶段四资产 · 股票清仓',
        'L20':'四态融合 · 双空股票20%','L10':'四态融合 · 双空股票10%','L0':'四态融合 · 双空股票清仓'}
from dynamic_allocation import MODES as DYNAMIC_MODES
LABELS.update({k:v[0] for k,v in DYNAMIC_MODES.items()})
DEFAULT='D5'
FILES={k:'融合策略.json' for k in LABELS}
def now():return datetime.now(CN)
def cutoff(moment=None):
    t=(moment or now()).astimezone(CN);d=t.date() if (t.hour,t.minute)>=(16,10) else t.date()-timedelta(days=1)
    while d.weekday()>=5:d-=timedelta(days=1)
    return d.isoformat()
def home():
    from suite_paths import home as suite_home
    return Path(os.environ.get('DUALAUTO_HOME') or suite_home()/'自动与演练账户')
def prepare_home():
    """Copy the prior account database once; the old app keeps its own ledger."""
    import sqlite3,shutil
    dest=home();base=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))
    if os.environ.get('DUALAUTO_HOME') or os.environ.get('ETF_SUITE_HOME'):return
    old=base/'FourAssetTrendSimulation';src=old/'模拟交易账户.sqlite3';target=dest/'模拟交易账户.sqlite3'
    if target.exists() or not src.exists():return
    dest.mkdir(parents=True,exist_ok=True)
    with sqlite3.connect(src.as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(target) as copied:source.backup(copied)
    for name in ['偏好.json','联合行情缓存.json']:
        if (old/name).exists() and not (dest/name).exists():shutil.copy2(old/name,dest/name)
    gold.atomic_json(dest/'账户迁移记录.json',dict(copied_from=str(old),copied_at=now().isoformat(),note='旧库保留；新版继续运行后两份账户独立变化'))
def spec(code):
    if code not in LABELS:raise ValueError('请选择四态融合方案')
    if code in DYNAMIC_MODES:
        from dynamic_allocation import config
        return {**config(code),'signal_rules':spec('F0')}
    chi=gold._read_json(HERE/'原纳指100策略.json')['rule'];bank=gold._read_json(HERE/'银行A策略.json')['spec']
    if code.startswith('F'):
        return dict(id=code,name=LABELS[code],schema='dualauto.strategy.v2',chi=chi,bank=bank,anchor='2012-01-04',bank_anchor=ANCHOR,
            signal_mode='original_confirmed',chi_requires_bull_and_full_attack=True,chi_core=.6,eligible_peers='equal',
            both_short_stock={'F20':.2,'F10':.1,'F0':0.}[code],gold=dict(ma=120,momentum=20),bond=dict(ma=60,momentum=20),
            defense_price='point_in_time_total_return',before_listing='unavailable',warmup='excluded',no_defense='cash',rebalance='target_change_next_open')
    return dict(id=code,name=LABELS[code],schema='simpleetf.strategy.confirmed.v1',weekly_confirmation='friday_or_next_week_first_close',chi=chi,bank=bank,
        signal_mode='original_confirmed',chi_requires_bull_and_full_attack=True,anchor=ANCHOR,
        both_long=[.6,.4],single_long=1.,both_short_stock={'L20':.2,'L10':.1,'L0':0.}[code],
        gold=dict(ma=120,momentum=20,require_both=True),gold_failure='cash',rebalance='target_change_next_open')
def validate_data(pair):
    if not isinstance(pair,dict) or set(pair)!= {'chi','bank'}:raise ValueError('需要同时包含纳指100和银行行情')
    chi=gold.validate_dataset(pair['chi']);bank=gold.validate_dataset(pair['bank'])
    if chi.get('attack_symbol')!='sh513100' or bank.get('attack_symbol')!='sh512800':raise ValueError('行情标的身份错误')
    inputs=Inputs(chi,bank)
    calendar={b['date'] for arr in inputs.bars.values() for b in arr if b['date']>='2012-01-04'}
    for c in CODES:
        first=inputs.bars[c][0]['date'];missing={d for d in calendar if d>=first}-{b['date'] for b in inputs.bars[c]}-engine.SUSPENSIONS.get(c,set())
        if missing:raise ValueError(c+'缺少配套行情：'+','.join(sorted(missing)[:3]))
    return dict(chi=chi,bank=bank)
def load_data(folder=None):
    path=Path(folder or home())/'联合行情缓存.json'
    pair=gold._read_json(path) if path.exists() else {k:gold._read_json(HERE/name) for k,name in [('chi','纳指100行情.json'),('bank','银行行情.json')]}
    return validate_data(pair)
def refresh(progress=lambda _:None):
    end=cutoff();progress('更新纳指100、黄金及国债的完整日线…');chi=assets.refresh(skdj,'159915',end,progress,allow_completed_today=True)
    progress('更新银行ETF并核对共同资产…');bank=assets.refresh(skdj,'512800',end,progress,allow_completed_today=True)
    return validate_data(dict(chi=chi,bank=bank))
def inputs(data):return Inputs(data['chi'],data['bank'])

class Signals:
    def __init__(self,market):
        self.market=market;self.inputs=market.inputs;end=market.latest;s=spec('L20');self.s=s
        ctx=Context(market.data['chi'],ANCHOR,end,100000,s['chi'],completed_through=end)
        from staged_signals import confirmed_features
        self.weekly=confirmed_features(ctx.signal_bars,20,end);self.weekly50=confirmed_features(ctx.signal_bars,50,end)
        _,_,states=build_schedule(ctx.signal_bars,ANCHOR,end,s['chi'],terminal_guard=False,completed_through=end,feature_map=self.weekly,market_map=self.weekly50)
        self.chi={x['date']:x for x in states};self.chi_dates=list(self.chi)
        self.week_dates=list(self.weekly);self.ma_dates=list(self.weekly50)
        bank=self.inputs.market.context(s['bank'],ANCHOR,end,100000)
        self.bank={x['date']:x for x in bank.states};self.bank_features=self.inputs.market.features(s['bank']);self.bank_index={d:i for i,d in enumerate(self.inputs.market.dates)}
        from strategy_engine import adjusted
        raw=adjusted(self.inputs.bars['sh518880'],self.inputs.splits['sh518880']);self.gold={};values=[]
        for row in raw:
            values.append(row['close']);ma=statistics.mean(values[-120:]) if len(values)>=120 else None;momentum=values[-1]/values[-21]-1 if len(values)>=21 else None
            self.gold[row['date']]=dict(close=values[-1],ma120=ma,momentum20=momentum,long=ma is not None and values[-1]>ma and momentum>0)
    def observation(self,code,day):
        if code in DYNAMIC_MODES:
            if not hasattr(self,'dynamic'):
                from staged_signals import StagedSignals
                from dynamic_allocation import DynamicSignals
                if not hasattr(self,'staged'):self.staged=StagedSignals(self.market,self)
                self.dynamic=DynamicSignals(self.market,self.staged)
            return self.dynamic.observation(code,day)
        if code.startswith('F'):
            if not hasattr(self,'staged'):
                from staged_signals import StagedSignals
                self.staged=StagedSignals(self.market,self)
            return self.staged.observation(code,day,spec(code)['both_short_stock'])
        if day<ANCHOR:raise ValueError('旧版四态方案最早2017-08-03；2012起请新建分阶段四资产账户')
        i=bisect_right(self.chi_dates,day)-1;cs=self.chi[self.chi_dates[i]];bs=self.bank[day];bf=self.bank_features[self.bank_index[day]];gf=self.gold[day]
        wi=bisect_right(self.week_dates,day)-1;mi=bisect_right(self.ma_dates,day)-1
        wf=self.weekly[self.week_dates[wi]] if wi>=0 else {};mf=self.weekly50[self.ma_dates[mi]] if mi>=0 else {}
        # Reduced or bear-market reference exposure is not upgraded into a full long.
        chi_long=cs['close_market']=='bull' and cs['next_risk']>=.999999;bank_long=bs['next_risk']>0
        cfg=spec(code);alloc=combine(chi_long,bank_long,cfg['both_short_stock'],bool(gf['long']))
        reason='纳指100：'+('多头有效' if chi_long else '未达到完整多头确认')+'，'+cs['reason']+'；银行：'+('多头有效' if bank_long else '未达到多头确认')+'，'+bs['reason']
        if alloc['state']=='neither':reason+='；'+('黄金趋势确认，配置防守预算' if gf['long'] else '黄金未通过趋势确认，防守预算留现金')
        return dict(day=day,strategy=code,chi_long=chi_long,bank_long=bank_long,gold_long=bool(gf['long']),
            **alloc,reason=reason,chi_state=deepcopy(cs),bank_state=deepcopy(bs),
            weekly_date=wf.get('week_end'),weekly_confirmed=wf.get('available'),chi_quote_date=self.chi_dates[i],
            features=dict(chi_weekly=wf,chi_market=mf,bank=bf,gold=gf),market_hash=self.market.hash)
