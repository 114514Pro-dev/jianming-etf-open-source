"""Past-only empirical ETF return scenarios with chronological calibration checks."""
from bisect import bisect_right
import math,statistics
from datetime import date
import bear_gold as gold,bear_gold_assets as assets

METHOD='skdj.etf-scenarios.v1'
HORIZONS=(5,20,60)
MIN_SAMPLES=20

def quantile(values,p):
    a=sorted(values);ix=(len(a)-1)*p;lo=int(ix);hi=min(lo+1,len(a)-1)
    return a[lo]+(a[hi]-a[lo])*(ix-lo)

def total_return_series(data,end):
    """Unit total-return index: ex-date cash notionally reinvested, before costs.

    This is the forecast target, not the gold strategy's cash ledger.
    Only already-effective conversions and ex-dates enter each daily increment.
    """
    symbol=assets.identity(data)[0];bars=[b for b in data['bars'][symbol] if b['date']<=end]
    splits=data.get('split_adjustments',{}).get(symbol,{})
    divs=data['corporate_actions'][symbol]['dividends'];out=[];value=100.
    for i,b in enumerate(bars):
        if i:
            prev=bars[i-1];factor=1.;cash=0.
            events=sorted([(d,'split',x['ratio']) for d,x in splits.items() if prev['date']<d<=b['date']]+
                          [(x['ex'],'div',x['cash_per_share']) for x in divs if prev['date']<x['ex']<=b['date']])
            # Corporate actions within a halted interval still accrue in event order.
            for _,kind,v in events:
                if kind=='split':factor*=v
                else:cash+=factor*v
            value*=(factor*b['close']+cash)/prev['close']
        out.append(dict(date=b['date'],value=value,close=b['close']))
    return out

def states(series):
    values=[r['value'] for r in series];out={}
    for i in range(119,len(values)):
        out[i]=(values[i]>statistics.mean(values[i-119:i+1]),values[i]>values[i-20])
    return out

def distribution(series,features,origin,horizon,conditional=True):
    # Select the most recent non-overlapping realized forward windows; no label
    # can finish after origin. The same rule is used at every validation origin.
    def select(match):
        indexes=[];last=origin+1
        for j in range(origin-horizon,118,-1):
            if j+horizon>origin or j+horizon>last:continue
            if match and features[j]!=features[origin]:continue
            indexes.append(j);last=j
        return indexes
    candidates=select(conditional)
    matched=conditional and len(candidates)>=MIN_SAMPLES
    if conditional and not matched:candidates=select(False)
    if len(candidates)<MIN_SAMPLES:return None
    returns=[series[j+horizon]['value']/series[j]['value']-1 for j in candidates]
    positive=sum(r>0 for r in returns);n=len(returns);p=positive/n
    # Wilson interval is descriptive; windows do not overlap but market regimes
    # can remain dependent, so this is not a guarantee of frequentist coverage.
    z=1.96;den=1+z*z/n;center=(p+z*z/(2*n))/den
    margin=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return dict(horizon=horizon,n=n,conditional=matched,p_up=p,p_interval=[center-margin,center+margin],
      q10=quantile(returns,.1),q50=quantile(returns,.5),q90=quantile(returns,.9),
      sample_first=series[min(candidates)]['date'],sample_last_end=series[max(candidates)+horizon]['date'],
      sample_origins=[series[j]['date'] for j in candidates])

def forecast(data,end=None,validate=True):
    data=gold.validate_dataset(data);end=gold._day(end or data['asof'])
    if end>data['asof']:raise ValueError('预测截止日不能晚于行情包。')
    rows=total_return_series(data,end)
    if len(rows)<240:raise ValueError('至少需要240个交易日的有效行情才能分析情景。')
    feat=states(rows);origin=len(rows)-1;latest=[];checks=[]
    for h in HORIZONS:
        result=distribution(rows,feat,origin,h)
        if result:latest.append(result)
        else:latest.append(dict(horizon=h,n=0,unavailable='至少20个不重叠历史窗口；当前样本不足'))
        history=[]
        if validate:
            for i in range(756,len(rows)-h,h):
                pred=distribution(rows,feat,i,h);base=distribution(rows,feat,i,h,False)
                if not pred or not base:continue
                realized=rows[i+h]['value']/rows[i]['value']-1;y=float(realized>0)
                history.append(dict(date=rows[i]['date'],end=rows[i+h]['date'],realized=realized,
                  probability=pred['p_up'],baseline_probability=base['p_up'],q10=pred['q10'],q90=pred['q90'],
                  brier=(pred['p_up']-y)**2,baseline_brier=(base['p_up']-y)**2,
                  covered=pred['q10']<=realized<=pred['q90'],conditional=pred['conditional'],
                  sample_last_end=pred['sample_last_end']))
        checks.append(dict(horizon=h,n=len(history),
          brier=statistics.mean(x['brier'] for x in history) if history else None,
          baseline_brier=statistics.mean(x['baseline_brier'] for x in history) if history else None,
          coverage=statistics.mean(x['covered'] for x in history) if history else None,
          first=history[0]['date'] if history else None,last=history[-1]['end'] if history else None,history=history))
    tr=rows[-1]['value'];ma120=statistics.mean(r['value'] for r in rows[-120:]);momentum20=tr/rows[-21]['value']-1
    return dict(schema=METHOD,symbol=assets.identity(data)[0],asof=rows[-1]['date'],requested_asof=end,
      observations=len(rows),last_close=rows[-1]['close'],
      technical=dict(total_return_index=tr,ma120=ma120,distance_ma120=tr/ma120-1,momentum20=momentum20),
      state=dict(above_ma120=feat[origin][0],positive_momentum20=feat[origin][1]),
      scenarios=latest,validation=checks,
      explanation='预测目标为所选ETF自身未来5/20/60个该ETF交易日的含息收益（除息日理论再投、未扣成本），不是黄金防守组合收益或价格目标。',
      method='按120日趋势和20日动量匹配历史；历史结果必须在预测当日已知，所选收益窗口互不重叠。相似样本不足20个退回无条件历史分布，仍不足则不输出。P10/P50/P90为经验情景分位数，非承诺收益。',
      caveat='检验从第757个交易日起每隔相应期限滚动，Brier越低越好；80%区间实际覆盖率不保证80%。概率区间为Wilson近似，市场相关性会使不确定性更大。短历史、制度变化和极端行情会削弱外推。')
