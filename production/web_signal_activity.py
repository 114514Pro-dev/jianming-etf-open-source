"""Recent fills from the native read-only model ledger, never from its targets."""
from datetime import datetime
import math


def number(value, positive=False):
    if isinstance(value,bool):raise ValueError('成交数值无效')
    n=float(value)
    if not math.isfinite(n) or n<0 or (positive and n==0):raise ValueError('成交数值无效')
    return n


def attach_activity(row, events, symbol=None):
    """Keep all fills on the confirmed date plus all fills at the latest timestamp."""
    end=datetime.fromisoformat(row['as_of']);fills=[]
    for event in events:
        side={'BUY':'buy','SELL':'sell','买入':'buy','卖出':'sell'}.get(event.get('side'))
        if side is None:raise ValueError('信号参考组合包含未知成交方向')
        rawtime=event.get('execution_time') or event.get('time')
        if not rawtime:rawtime=(event.get('day') or event['date'])+' 09:30:00'
        moment=datetime.fromisoformat(str(rawtime))
        if moment>end:raise ValueError('成交晚于模型确认时间')
        qty=number(event.get('quantity',event.get('qty')),True)
        if not qty.is_integer():raise ValueError('成交份数不是整数')
        price=number(event['price'],True);fee=number(event['fee'])
        asset=event.get('symbol') or symbol
        if not isinstance(asset,str) or not asset:raise ValueError('成交缺少资产代码')
        fills.append(dict(time=moment.isoformat(sep=' ',timespec='seconds'),symbol=asset,side=side,
                          quantity=int(qty),price=price,amount=number(event.get('gross',round(qty*price,2))),fee=fee,
                          reason=str(event.get('reason') or '按已确认的策略目标模拟执行。')))
    fills.sort(key=lambda item:item['time'])
    day=end.date().isoformat();day_trades=[e for e in fills if e['time'][:10]==day]
    latest_time=fills[-1]['time'] if fills else None
    latest=[e for e in fills if e['time']==latest_time] if fills else []
    holding=any(qty>0 for qty in row['positions'].values())
    if day_trades:summary='该确认日已发生模拟成交，买卖明细见下方。'
    elif row['intents']:summary='该确认日没有模拟成交；已有新的买卖意向，等待下一可执行时点。'
    elif row['status']=='wait':summary='该确认日没有模拟成交，等待完整信号或可执行条件。'
    elif holding:summary='该确认日未操作，继续持有现有参考仓位。'
    else:summary='该确认日未操作，保持空仓。'
    row['activity']=dict(as_of=row['as_of'],day=day,summary=summary,day_trades=day_trades,
                         latest_time=latest_time,latest_trades=latest,total_trades=len(fills),
                         source='独立模型参考组合的原引擎模拟成交；与个人账户成交分别记录。')
    return row


def valid_activity(activity, as_of):
    try:
        if not isinstance(activity,dict) or activity['as_of']!=as_of or activity['day']!=as_of[:10]:return False
        if not isinstance(activity['summary'],str) or not activity['summary']:return False
        total=activity['total_trades']
        if not isinstance(total,int) or isinstance(total,bool) or total<0:return False
        for key in ('day_trades','latest_trades'):
            events=activity[key]
            if not isinstance(events,list) or len(events)>total:return False
            for e in events:
                if e['side'] not in ('buy','sell') or not isinstance(e['symbol'],str) or not e['symbol']:return False
                if datetime.fromisoformat(e['time'])>datetime.fromisoformat(as_of):return False
                if key=='day_trades' and e['time'][:10]!=activity['day']:return False
                if key=='latest_trades' and e['time']!=activity['latest_time']:return False
                qty=number(e['quantity'],True)
                if not qty.is_integer():return False
                number(e['price'],True);number(e['fee']);number(e['amount'])
        if bool(total)!=bool(activity['latest_trades']):return False
        if not total and activity['latest_time'] is not None:return False
        return True
    except (KeyError,ValueError,TypeError,OverflowError):return False
