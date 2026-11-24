"""Causal strength/risk weights, independent asset gates and drift rebalancing."""
import math,statistics
from bisect import bisect_right
from datetime import date
from copy import deepcopy
from etf_forecast import total_return_series
from allocation import CODES

MODES={'D5':('动态强弱 · 偏离5个百分点调仓',.05,'daily'),
       'D0':('动态强弱 · 每日调仓',0.,'daily'),
       'DW':('动态强弱 · 周线确认调仓',.05,'weekly')}

def config(code):
    label,threshold,frequency=MODES[code]
    return dict(id=code,name=label,schema='etfsuite.dynamic.v1',anchor='2012-01-04',
        gate='independent_original_confirmed',momentum=[20,60],volatility=20,vol_floor=.08,
        score='max(0.05,0.6*mom20*sqrt(252/20)+0.4*mom60*sqrt(252/60))/max(vol20,0.08)',
        weights='eligible_score/sum_eligible_scores',single_asset_cap=1.,total_cap=1.,
        no_eligible='cash',threshold=threshold,frequency=frequency,risk_exit='next_executable_open',
        execution='close_to_next_executable_open')

def allocate(scores,eligible):
    if set(scores)!=set(CODES) or set(eligible)!=set(CODES):raise ValueError('须包含四种资产')
    if any(not math.isfinite(x) or x<0 for x in scores.values()):raise ValueError('评分须为有效非负数')
    valid={c:scores[c] if eligible[c] else 0. for c in CODES}
    total=sum(valid.values())
    weights={c:v/total if total else 0. for c,v in valid.items()}
    return dict(weights=weights,cash_weight=max(0.,1-sum(weights.values())))

def week_confirmed(day,dates):
    d=date.fromisoformat(day)
    if d.weekday()==4:return True
    i=bisect_right(dates,day)-1
    if i<=0:return False
    previous=date.fromisoformat(dates[i-1])
    return d.isocalendar()[:2]!=previous.isocalendar()[:2] and previous.weekday()!=4

def rebalance_reason(state,quote,weights,code,dates):
    from trade_book import value
    v=value(state,quote)
    actual={c:state['positions'][c]['qty']*(quote['prices'][c] or 0)/v['equity'] for c in CODES}
    drift=max([abs(actual[c]-weights[c]) for c in CODES]+[abs(1-sum(actual.values())-(1-sum(weights.values())))])
    exits=[c for c in CODES if state['positions'][c]['qty']>0 and weights[c]<=1e-12]
    cfg=config(code)
    if exits:return True,f'多头资格失效，退出：'+','.join(exits),actual,drift
    if cfg['frequency']=='weekly' and not week_confirmed(state['day'],dates):return False,'等待已完成周线确认；风险失效退出仍按日检查',actual,drift
    if drift>cfg['threshold']+1e-8:return True,f'最大仓位偏离{drift:.2%}，超过{cfg["threshold"]:.0%}调仓阈值',actual,drift
    return False,f'最大仓位偏离{drift:.2%}，未超过{cfg["threshold"]:.0%}阈值，继续持有',actual,drift

class DynamicSignals:
    def __init__(self,market,staged):
        self.market=market;self.staged=staged;self.stats={};self.dates={}
        for c in CODES:
            data=market.data['bank' if c==CODES[1] else 'chi']
            rows=total_return_series({**data,'attack_symbol':c},market.latest)
            values=[];returns=[];out={}
            for row in rows:
                v=row['value']
                if values:returns.append(v/values[-1]-1)
                values.append(v);ready=len(values)>=61
                m20=v/values[-21]-1 if len(values)>=21 else None
                m60=v/values[-61]-1 if ready else None
                vol=statistics.stdev(returns[-20:])*math.sqrt(252) if len(returns)>=20 else None
                numerator=max(.05,.6*m20*math.sqrt(252/20)+.4*m60*math.sqrt(252/60)) if ready else None
                score=numerator/max(.08,vol) if ready else 0.
                out[row['date']]=dict(momentum20=m20,momentum60=m60,volatility20=vol,score=score,score_ready=ready,quote_date=row['date'])
            self.stats[c]=out;self.dates[c]=list(out)

    def observation(self,code,day):
        base=self.staged.observation('F0',day,0.)
        scores={};eligible={};detail={};notes={}
        for c in CODES:
            ix=bisect_right(self.dates[c],day)-1
            f=deepcopy(self.stats[c][self.dates[c][ix]]) if ix>=0 else dict(momentum20=None,momentum60=None,volatility20=None,score=0.,score_ready=False,quote_date=None)
            eligible[c]=bool(base['longs'][c] and base['ready'][c] and f['score_ready'] and f['quote_date']==day)
            scores[c]=f['score'] if eligible[c] else 0.
            detail[c]={**f,'eligible':eligible[c],'effective_score':scores[c]}
            reason=('动态多头资格通过；原指标：' if eligible[c] else '动态多头资格未通过，目标0%；原指标：')+base['notes'][c]
            if not f['score_ready']:reason+='；强弱指标尚不足61个交易日'
            elif f['quote_date']!=day:reason+='；当日缺少行情，暂不增配'
            else:reason+=f'；20日{f["momentum20"]:+.2%}，60日{f["momentum60"]:+.2%}，20日年化波动{f["volatility20"]:.2%}，有效评分{scores[c]:.3f}'
            notes[c]=reason
        allocation=allocate(scores,eligible)
        base.update(strategy=code,**allocation,state='dynamic',dynamic=detail,longs=eligible,
            notes=notes,reason='；'.join(c+'：'+notes[c] for c in CODES),allocation_rule='达标资产按强弱/波动评分分配，可0%至100%；未达标留现金')
        base['features']['dynamic']=detail
        return base
