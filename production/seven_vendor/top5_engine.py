"""Auditable long-only ETF research ledger. No live trading or application writes."""
from __future__ import annotations
from pathlib import Path
import json, hashlib, math
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent
TF_NAMES = {'60m':'60分钟','120m':'120分钟','D':'日线','W':'周线','2W':'双周线','M':'月线'}

def period_key(dates, tf):
    x = pd.DatetimeIndex(dates)
    if tf == 'W': return x.to_period('W-FRI').astype(str)
    if tf == 'M': return x.to_period('M').astype(str)
    if tf == '2W':
        # Fixed Monday anchor; no sample-dependent grouping.
        return ((x.normalize() - pd.Timestamp('2011-12-05')).days // 14).astype(str)
    return x.strftime('%Y-%m-%d')

def read_data():
    daily = pd.read_csv(ROOT/'data/chinext/daily.csv')
    daily.index = pd.to_datetime(daily.pop('date'))
    daily = daily.sort_index()
    daily['open_time'] = daily.index + pd.Timedelta(hours=9, minutes=30)
    daily.index = daily.index + pd.Timedelta(hours=15)
    hourly = pd.read_csv(ROOT/'data/chinext/hourly.csv')
    hourly.index = pd.to_datetime(hourly.pop('datetime'))
    hourly = hourly.sort_index()
    hourly['open_time'] = hourly.index - pd.Timedelta(hours=1)
    # Completed sessions only. Intraday source must contain four bars per day.
    assert set(hourly.index.strftime('%H:%M')) == {'10:30','11:30','14:00','15:00'}
    assert hourly.groupby(hourly.index.normalize()).size().eq(4).all()
    for data in (daily,hourly):
        assert data.index.is_unique and data.index.is_monotonic_increasing
        assert data[['open','high','low','close']].notna().all().all()
        assert (data.low <= data[['open','close']].min(axis=1)+1e-9).all()
        assert (data.high >= data[['open','close']].max(axis=1)-1e-9).all()
        assert (data[['open','high','low','close']]>0).all().all()
    return daily, hourly

def aggregate_bars(daily, hourly, tf, calendar=None):
    if tf == 'D': return daily.copy()
    if tf == '60m': return hourly.copy()
    data = hourly if tf=='120m' else daily
    if tf == '120m':
        keys = data.index.strftime('%Y-%m-%d') + np.where(data.index.hour<12,'-AM','-PM')
    else: keys = period_key(data.index,tf)
    cal = pd.DatetimeIndex(calendar if calendar is not None else daily.index).normalize()
    calkeys = period_key(cal,tf) if tf not in ('120m',) else None
    expected = {}
    if calkeys is not None:
        for j in range(len(cal)-1):
            if calkeys[j] != calkeys[j+1]: expected[calkeys[j]] = cal[j]
        # Final group intentionally unconfirmed: source ends before current week/month.
    out=[]
    for key,g in data.groupby(keys,sort=False):
        if tf=='120m':
            if len(g)!=2: continue
        else:
            if key not in expected or g.index[-1].normalize()!=expected[key]: continue
            # Omit initial partly observed calendar bucket, except a full session.
            if key==keys[0]: continue
        row=dict(open=float(g.open.iloc[0]),high=float(g.high.max()),low=float(g.low.min()),
                 close=float(g.close.iloc[-1]),volume=float(g.volume.sum()),
                 open_time=g.open_time.iloc[0],end=g.index[-1])
        if 'amount' in g: row['amount']=float(g.amount.sum())
        out.append(row)
    if not out:
        empty=data.iloc[:0].copy()
        empty.index=pd.DatetimeIndex([],name='end')
        return empty
    return pd.DataFrame(out).set_index('end')

def project_signals(signals, grid, delay=0):
    """A completed bar may first affect the next execution bar's open."""
    entry=np.zeros(len(grid),bool); exit_=entry.copy()
    opens=pd.DatetimeIndex(grid.open_time).asi8
    ids=np.searchsorted(opens, signals.index.asi8, side='left')+delay
    for j,k in enumerate(ids):
        if signals.index.asi8[j] < opens[0]: continue
        if k>=len(grid): continue
        if signals.ready.iloc[j]:
            entry[k] |= bool(signals.entry.iloc[j])
            exit_[k] |= bool(signals.exit.iloc[j])
    return entry,exit_

def signal_state(signals):
    """Latched model intent, independent of fills; warm-up remains unknown."""
    s=False; arr=[]
    for r in signals.itertuples():
        if not r.ready: arr.append(np.nan); continue
        if r.exit: s=False
        elif r.entry: s=True
        arr.append(float(s))
    return pd.Series(arr,index=signals.index)

def combine_same(signals, ids, enter_votes, exit_below):
    states=pd.concat([signal_state(signals[i]) for i in ids],axis=1)
    ready=states.notna().all(axis=1); count=states.sum(axis=1)
    return pd.DataFrame({'entry':ready&(count>=enter_votes),
                         'exit':ready&(count<exit_below),'ready':ready},index=states.index)

def align_state(signals,index):
    return signal_state(signals).reindex(signal_state(signals).index.union(index)).sort_index().ffill().reindex(index)

def combine_cross(signal_map, keys, event_index, threshold):
    states=pd.concat([align_state(signal_map[k],event_index) for k in keys],axis=1)
    ready=states.notna().all(axis=1); votes=states.sum(axis=1)
    return pd.DataFrame({'entry':ready&(votes>=threshold),'exit':ready&(votes<threshold),'ready':ready},index=event_index)

def simulate(grid, signals, start, case_id='', commission=.0003, slippage=.0002,
             delay=0, fixed_hold=None, initial=100000., benchmark=False,
             terminal_liquidation=True):
    """Signals at completed closes; next-open fills; T+1; 100-share lots."""
    g=grid.loc[grid.index.normalize()>=pd.Timestamp(start)].copy()
    assert len(g)>=1
    all_entry,all_exit=project_signals(signals,grid,delay)
    mask=grid.index.normalize()>=pd.Timestamp(start)
    entry,exit_=all_entry[mask].copy(),all_exit[mask].copy()
    if benchmark: entry[:]=True; exit_[:]=False
    days=g.index.normalize(); day_ids=pd.factorize(days)[0]
    # Partial current sessions must not activate a 20-day exit before 15:00.
    day_last=np.asarray(g.index.strftime('%H:%M')=='15:00')
    cash=initial; shares=0; buy_day=-1; pending_exit=False
    fee_total=slip_total=0.; t1_delays=0; trades=[]; ledger=[]; events=[]
    buy_record=None; last_day=day_ids[-1]
    prices=g[['open','close']].to_numpy(float); ots=pd.DatetimeIndex(g.open_time)
    for i,(op,cl) in enumerate(prices):
        sold=False
        if shares and exit_[i] and not pending_exit:
            pending_exit=True
            if day_ids[i]==buy_day: t1_delays+=1
        if shares and pending_exit and day_ids[i]>buy_day:
            p=op*(1-slippage); fee=round(max(5.,shares*p*commission),2)
            proceeds=shares*p-fee; cash+=proceeds
            slip=shares*op*slippage; fee_total+=fee; slip_total+=slip
            events.append(dict(time=str(ots[i]),bar_time=str(g.index[i]),side='SELL',quantity=shares,
                price=p,fee=fee,reason='持有期满' if fixed_hold else '退出信号'))
            trades.append(dict(case_id=case_id,**buy_record,sell_time=str(ots[i]),sell_price=p,
                sell_fee=fee,profit=proceeds-buy_record['buy_cost'],
                hold_days=int(day_ids[i]-buy_day),reason='持有期满' if fixed_hold else '退出信号'))
            shares=0; pending_exit=False; buy_record=None; sold=True
        # Never buy on terminal day, so compulsory endpoint liquidation respects T+1.
        if shares==0 and not sold and entry[i] and (not terminal_liquidation or day_ids[i]<last_day):
            p=op*(1+slippage); qty=int(cash/(p*100)) *100
            while qty>0:
                fee=round(max(5.,qty*p*commission),2)
                if qty*p+fee <=cash+1e-8: break
                qty-=100
            if qty:
                cost=qty*p+fee; cash-=cost; shares=qty; buy_day=int(day_ids[i])
                fee_total+=fee; slip_total+=qty*op*slippage
                buy_record=dict(buy_time=str(ots[i]),buy_price=p,quantity=qty,buy_fee=fee,buy_cost=cost)
                events.append(dict(time=str(ots[i]),bar_time=str(g.index[i]),side='BUY',quantity=qty,
                    price=p,fee=fee,reason='入场信号'))
        assert cash>=-1e-6 and shares%100==0
        if shares and fixed_hold and day_last[i] and day_ids[i]-buy_day+1>=fixed_hold:
            pending_exit=True
        if terminal_liquidation and i==len(g)-1 and shares:
            assert day_ids[i]>buy_day
            p=cl*(1-slippage); fee=round(max(5.,shares*p*commission),2)
            proceeds=shares*p-fee; cash+=proceeds; fee_total+=fee; slip_total+=shares*cl*slippage
            events.append(dict(time=str(g.index[i]),bar_time=str(g.index[i]),side='SELL',quantity=shares,
                price=p,fee=fee,reason='期末统一清算'))
            trades.append(dict(case_id=case_id,**buy_record,sell_time=str(g.index[i]),sell_price=p,
                sell_fee=fee,profit=proceeds-buy_record['buy_cost'],hold_days=int(day_ids[i]-buy_day),reason='期末统一清算'))
            shares=0
        equity=cash+shares*cl
        ledger.append((str(g.index[i]),cash,shares,equity,shares*cl/equity))
    book=pd.DataFrame(ledger,columns=['datetime','cash','shares','equity','exposure'])
    book.index=pd.to_datetime(book.datetime)
    daily=book.groupby(book.index.normalize()).last()
    eq=daily.equity.to_numpy(); ret=np.diff(np.r_[initial,eq])/np.r_[initial,eq][:-1]
    years=(g.index[-1]-ots[0]).total_seconds()/(365.25*86400)
    peaks=np.maximum.accumulate(np.r_[initial,eq]); dd=np.r_[initial,eq]/peaks-1
    mdd=-float(dd.min()); total=eq[-1]/initial-1
    cagr=(eq[-1]/initial)**(1/years)-1 if years>=1 else None
    sd=float(np.std(ret,ddof=1)) if len(ret)>1 else 0.; sharpe=float(np.mean(ret)/sd*np.sqrt(252)) if sd>0 else None
    profits=np.array([t['profit'] for t in trades]); holds=[t['hold_days'] for t in trades]
    bar_eq=book.equity.to_numpy(); bar_mdd=-float((np.r_[initial,bar_eq]/np.maximum.accumulate(np.r_[initial,bar_eq])-1).min())
    metrics=dict(start=str(days[0].date()),end=str(days[-1].date()),bars=len(g),days=len(daily),
        final_equity=float(eq[-1]),total_return=float(total),cagr=cagr,max_drawdown=mdd,
        bar_close_drawdown=bar_mdd,sharpe=sharpe,calmar=cagr/mdd if cagr is not None and mdd>0 else None,
        trades=len(trades),win_rate=float((profits>0).mean()) if len(trades) else None,
        exposure=float(book.exposure.mean()),fees=fee_total,slippage=slip_total,
        average_hold=float(np.mean(holds)) if holds else None,max_hold=max(holds) if holds else None,
        t1_delays=t1_delays,status='已完成' if trades else '无成交')
    annual=[]; prior=initial
    for year,d in daily.groupby(daily.index.year):
        vals=d.equity.to_numpy(); seq=np.r_[prior,vals]
        annual.append(dict(year=int(year),return_=float(vals[-1]/prior-1),
                           max_drawdown=-float((seq/np.maximum.accumulate(seq)-1).min())))
        prior=vals[-1]
    book.attrs['state']=dict(cash=float(cash),shares=int(shares),pending_exit=bool(pending_exit),
        buy_record=buy_record if shares else None,buy_day=int(buy_day),
        last_bar=str(g.index[-1]),held_trading_days=int(day_ids[-1]-buy_day+1) if shares else 0,
        terminal_liquidation=bool(terminal_liquidation))
    book.attrs['events']=events
    return metrics,daily,book,trades,annual

def sha256(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def clean_json(x):
    if isinstance(x,dict): return {str(k):clean_json(v) for k,v in x.items()}
    if isinstance(x,(list,tuple)): return [clean_json(v) for v in x]
    if isinstance(x,(np.integer,)): return int(x)
    if isinstance(x,(np.floating,float)): return float(x) if np.isfinite(x) else None
    if isinstance(x,(pd.Timestamp,Path)): return str(x)
    if isinstance(x,np.bool_): return bool(x)
    return x

def save_json(path,obj): Path(path).write_text(json.dumps(clean_json(obj),ensure_ascii=False,indent=2),encoding='utf-8')
