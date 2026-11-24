"""2012 onward, listing-aware signals with point-in-time dividend adjustment."""
from bisect import bisect_right
from copy import deepcopy
import statistics
from allocation import CODES,staged
from bear_gold_kernel import features,build_schedule
from strategy_engine import adjusted
from etf_forecast import total_return_series
from datetime import date

START='2012-01-04'
def confirmed_features(bars,window,end):
    """A short holiday week is confirmed at next week's first close."""
    raw=features(bars,window,end);dates=[b['date'] for b in bars];out={}
    for d,f in raw.items():
        ix=bisect_right(dates,d)
        if date.fromisoformat(d).weekday()==4:available=d
        elif ix<len(dates):available=dates[ix]
        else:continue
        out[available]={**f,'week_end':d,'available':available}
    return out
def defense_series(data,code,end,window):
    series=total_return_series({**data,'attack_symbol':code},end);out={};values=[]
    for row in series:
        values.append(row['value']);ready=len(values)>=max(window,21)
        ma=statistics.mean(values[-window:]) if len(values)>=window else None
        mom=values[-1]/values[-21]-1 if len(values)>=21 else None
        out[row['date']]=dict(close=row['close'],value=row['value'],ma=ma,ma_window=window,momentum20=mom,
                             count=len(values),ready=ready,long=bool(ready and row['value']>ma and mom>0),quote_date=row['date'])
    return out

class StagedSignals:
    def __init__(self,market,legacy):
        self.market=market;self.legacy=legacy;self.cfg=legacy.s;end=market.latest
        bars=adjusted([b for b in market.inputs.bars[CODES[0]] if b['date']<=end],market.inputs.splits[CODES[0]])
        self.weekly=confirmed_features(bars,20,end);self.weekly50=confirmed_features(bars,50,end)
        _,_,states=build_schedule(bars,START,end,self.cfg['chi'],terminal_guard=False,completed_through=end,feature_map=self.weekly,market_map=self.weekly50)
        self.chi={r['date']:r for r in states};self.chi_dates=list(self.chi)
        self.week_dates=list(self.weekly);self.ma_dates=list(self.weekly50)
        self.defense={c:defense_series(market.data['chi'],c,end,w) for c,w in [(CODES[2],120),(CODES[3],60)]}
        self.first={c:market.inputs.bars[c][0]['date'] for c in CODES}
    def observation(self,code,day,light):
        chi,bank,gold,bond=CODES;i=bisect_right(self.chi_dates,day)-1
        if i<0:raise ValueError('恒生科技尚无历史行情')
        cs=self.chi[self.chi_dates[i]];wi=bisect_right(self.week_dates,day)-1;mi=bisect_right(self.ma_dates,day)-1
        wf=self.weekly[self.week_dates[wi]] if wi>=0 else {};mf=self.weekly50[self.ma_dates[mi]] if mi>=0 else {}
        bs=self.legacy.bank.get(day,dict(next_risk=0.,holding_days=0,reason='银行ETF尚未上市，暂不参与'))
        bi=self.legacy.bank_index.get(day);bf=self.legacy.bank_features[bi] if bi is not None else dict(k=None,d=None)
        ready={chi:bool(mf and wf),bank:bf.get('k') is not None and bf.get('d') is not None}
        longs={chi:bool(ready[chi] and cs['close_market']=='bull' and cs['next_risk']>=.999999),bank:bool(ready[bank] and bs['next_risk']>0)}
        fs={};available={c:self.first[c]<=day for c in CODES}
        for c,w in [(gold,120),(bond,60)]:
            f=self.defense[c].get(day,dict(close=None,value=None,ma=None,ma_window=w,momentum20=None,count=0,ready=False,long=False,quote_date=None))
            fs[c]=f;ready[c]=bool(f['ready']);longs[c]=bool(f['long'])
        allocation=staged(longs,ready,light)
        stage='四资产阶段' if available[bank] else '银行上市前阶段'
        notes={}
        for c,name in zip(CODES,['恒生科技','银行','黄金','国债']):
            if not available[c]:note=f'尚未上市，{self.first[c]}起才有场内行情'
            elif not ready[c]:note='指标历史不足，等待预热完成'
            elif c in [chi,bank]:note=('多头有效；' if longs[c] else '未确认多头；')+(cs if c==chi else bs)['reason']
            else:
                f=fs[c];note=('多头有效' if longs[c] else '未确认多头')+f'；含息指标价{f["value"]:.3f}，{f["ma_window"]}日均线{f["ma"]:.3f}，20日涨幅{f["momentum20"]:+.2%}'
            notes[c]=note
        reason='；'.join(name+'：'+notes[c] for c,name in zip(CODES,['恒生科技','银行','黄金','国债']))
        return dict(day=day,strategy=code,**allocation,stage=stage,reason=reason,notes=notes,ready=ready,available=available,longs=longs,
                    chi_long=longs[chi],bank_long=longs[bank],gold_long=longs[gold],bond_long=longs[bond],
                    chi_state=deepcopy(cs),bank_state=deepcopy(bs),weekly_date=wf.get('week_end'),weekly_confirmed=wf.get('available'),
                    chi_quote_date=self.chi_dates[i],features=dict(chi_weekly=wf,chi_market=mf,bank=bf,gold=fs[gold],bond=fs[bond]),market_hash=self.market.hash)
