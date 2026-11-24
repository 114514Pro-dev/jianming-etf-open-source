"""Read-only Tencent daily/Sina hourly fetchers for immutable app snapshots.

No account, file, database or network writes. The caller owns immutable merging,
overlap revision rejection and persistence. The calendar is package-relative.
"""
from __future__ import annotations

from pathlib import Path
from datetime import date,datetime,time,timedelta,timezone
from concurrent.futures import ThreadPoolExecutor
import collections,hashlib,json,math,urllib.request,urllib.parse

TZ=timezone(timedelta(hours=8))
TIMES=('10:30:00','11:30:00','14:00:00','15:00:00')
SETTLEMENT_SECONDS=60
SINA_URL='https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData?symbol=sz159920&scale=60&ma=no&datalen=50000'
TENCENT_URL='https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get'


def _read_calendar():
    base=Path(__file__).resolve().parent
    candidates=[base/'data/chinext/calendar.json',base/'calendar/verified_sessions.json']
    path=next((p for p in candidates if p.is_file()),None)
    if path is None:raise ValueError('缺少已验证交易日历，暂不采纳更新。')
    payload=json.loads(path.read_text(encoding='utf-8-sig'))
    sessions=payload.get('sessions');through=payload.get('verified_through') or payload.get('valid_through')
    if not isinstance(sessions,list) or not sessions or sorted(set(sessions))!=sessions:
        raise ValueError('交易日历日期异常。')
    if not isinstance(through,str) or sessions[-1]>through:raise ValueError('交易日历有效边界异常。')
    for session in sessions:date.fromisoformat(session)
    return set(sessions),through,hashlib.sha256(path.read_bytes()).hexdigest()


def _request_bytes(url):
    last=None
    for _ in range(2):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0',
                'Referer':'https://finance.sina.com.cn/','Cache-Control':'no-cache'})
            with urllib.request.urlopen(req,timeout=20) as response:
                raw=response.read(20_000_001)
            if len(raw)>20_000_000:raise ValueError('行情响应过大。')
            return raw
        except Exception as error:last=error
    raise RuntimeError(str(last)) from last


def _capture(source,url):
    fetched=datetime.now(TZ).isoformat(timespec='seconds')
    raw=_request_bytes(url)
    return raw,dict(source=source,url=url,fetched_at=fetched,
                    sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))


def _number(value,positive=False):
    result=float(value)
    if not math.isfinite(result) or (result<=0 if positive else result<0):
        raise ValueError('行情含非法价格或成交量。')
    return result


def _prices(row):
    values={key:_number(row[key],True) for key in ('open','high','low','close')}
    if not values['low']<=min(values['open'],values['close'])<=max(values['open'],values['close'])<=values['high']:
        raise ValueError('OHLC关系异常。')
    return values


def parse_sina_hourly(raw,now,sessions,verified_through):
    """Return completed raw bars and warnings; retain historical overlap."""
    data=json.loads(raw.decode('utf-8-sig'))
    if not isinstance(data,list) or not data:raise ValueError('新浪60分钟接口返回空数据或格式变化。')
    now=now.astimezone(TZ);by_stamp={};excluded_unfinished=0;unknown_dates=set()
    for entry in data:
        stamp=datetime.strptime(entry['day'],'%Y-%m-%d %H:%M:%S').replace(tzinfo=TZ)
        day=stamp.date().isoformat()
        if stamp.strftime('%H:%M:%S') not in TIMES:raise ValueError('60分钟柱结束时间异常。')
        if day>verified_through or day not in sessions:
            unknown_dates.add(day);continue
        if stamp+timedelta(seconds=SETTLEMENT_SECONDS)>now:
            excluded_unfinished+=1;continue
        row=dict(datetime=stamp.strftime('%Y-%m-%d %H:%M:%S'),**_prices(entry),
                 volume=_number(entry['volume']),amount=None)
        if row['datetime'] in by_stamp and by_stamp[row['datetime']]!=row:
            raise ValueError('新浪60分钟重复时间戳存在冲突。')
        by_stamp[row['datetime']]=row
    rows=sorted(by_stamp.values(),key=lambda r:r['datetime']);warnings=[]
    if not rows:raise ValueError('新浪没有可确认的完整60分钟柱。')
    groups=collections.defaultdict(list)
    for row in rows:groups[row['datetime'][:10]].append(row)
    first=rows[0]['datetime'][:10]
    # A rolling provider may begin mid-session; discard that single incomplete
    # historical first day, but retain a legitimate partially elapsed current day.
    if first<now.date().isoformat() and tuple(r['datetime'][11:] for r in groups[first])!=TIMES:
        rows=[r for r in rows if r['datetime'][:10]!=first]
        warnings.append('新浪最早可用日不是完整交易日，已剔除该首日。')
    if unknown_dates:warnings.append('剔除未在已验证日历内的分钟日期：'+','.join(sorted(unknown_dates)[:8]))
    if excluded_unfinished:warnings.append(f'已剔除{excluded_unfinished}根尚未结束或未过60秒缓冲的分钟柱。')
    return rows,warnings


def parse_tencent_daily(raw,now,sessions,verified_through):
    text=raw.decode('utf-8-sig')
    if not text.lstrip().startswith('{') and '=' in text:text=text.split('=',1)[1].rstrip(';')
    payload=json.loads(text)
    stock=payload.get('data',{}).get('sz159920',{})
    lines=stock.get('day')
    if payload.get('code')!=0 or not isinstance(lines,list) or not lines:
        raise ValueError('腾讯未复权日线为空或格式变化。')
    now=now.astimezone(TZ);by_date={};excluded=0;unknown=[]
    for fields in lines:
        day=date.fromisoformat(fields[0]).isoformat()
        if day>verified_through or day not in sessions:unknown.append(day);continue
        close_time=datetime.combine(date.fromisoformat(day),time(15),TZ)
        if close_time+timedelta(seconds=SETTLEMENT_SECONDS)>now:excluded+=1;continue
        prices=dict(open=fields[1],close=fields[2],high=fields[3],low=fields[4])
        row=dict(date=day,**_prices(prices),volume=_number(fields[5])*100,
                 amount=_number(fields[8])*10000)
        if day in by_date and by_date[day]!=row:raise ValueError('腾讯重复日期的行情冲突。')
        by_date[day]=row
    rows=sorted(by_date.values(),key=lambda r:r['date']);warnings=[]
    if not rows:raise ValueError('腾讯没有可确认的完整日线。')
    if excluded:warnings.append(f'已剔除{excluded}条尚未完成收盘或未过60秒缓冲的日线。')
    if unknown:warnings.append('剔除未在已验证日历内的日线日期：'+','.join(sorted(set(unknown))[:8]))
    return rows,warnings


def fetch_market_updates(latest_daily:str,latest_bar:str,progress=None):
    """Fetch source overlap + new completed bars without modifying any state.

    latest_daily: YYYY-MM-DD; latest_bar: YYYY-MM-DD HH:MM:SS. Existing overlap
    is intentional: the service must reject revisions before extending a ledger.
    The last completed daily date can lag the last completed hourly date.
    """
    progress=progress or (lambda _:None)
    now=datetime.now(TZ)
    result=dict(daily=[],hourly=[],fetched_at=now.isoformat(timespec='seconds'),sources=[],warnings=[])
    try:
        sessions,through,calendar_sha=_read_calendar()
        if latest_daily:date.fromisoformat(latest_daily[:10])
        if latest_bar:datetime.fromisoformat(latest_bar)
    except Exception as error:
        result['warnings'].append(str(error));return result
    if now.date().isoformat()>through:result['warnings'].append(f'交易日历仅验证至{through}，其后行情不采纳；请先更新官方日历。')
    progress('正在读取腾讯完整日线与新浪已完成60分钟行情…')
    # Tencent returns up to 640 historical rows; retain overlap, then parse only
    # complete trading sessions. No current-day quote is promoted to daily OHLC.
    daily_url=TENCENT_URL+'?'+urllib.parse.urlencode({'param':f'sz159920,day,,{now.date().isoformat()},640,'})
    jobs=[('腾讯未复权日线',daily_url,'daily',parse_tencent_daily),
          ('新浪未复权60分钟',SINA_URL,'hourly',parse_sina_hourly)]
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[(job,pool.submit(_capture,job[0],job[1])) for job in jobs]
        for (source,url,key,parser),future in futures:
            try:
                raw,meta=future.result()
                rows,warnings=parser(raw,now,sessions,through)
                meta.update(rows=len(rows),first=rows[0].get('date',rows[0].get('datetime')),
                            last=rows[-1].get('date',rows[-1].get('datetime')),
                            volume_unit='ETF shares',price_adjustment='none',
                            bar_time='end (Asia/Shanghai)',calendar_sha256=calendar_sha)
                result[key]=rows;result['sources'].append(meta);result['warnings'].extend(warnings)
                progress(source+'读取完成，最新完整数据：'+meta['last'])
            except Exception as error:
                result['sources'].append(dict(source=source,url=url,error=str(error)))
                result['warnings'].append(source+'更新失败：'+str(error))
    if result['daily'] and latest_daily:
        if result['daily'][-1]['date']<latest_daily:result['warnings'].append('日线接口比现有快照更旧；保留现有数据。')
        if result['daily'][0]['date']>latest_daily:
            expected=sorted(d for d in sessions if latest_daily<d<result['daily'][0]['date'])
            if expected:result['warnings'].append('日线可用窗口与已有末日之间存在缺口；不可直接续接。')
    if result['hourly']:
        rows=result['hourly'];by_stamp={r['datetime'] for r in rows}
        if latest_bar and rows[-1]['datetime']<latest_bar:result['warnings'].append('分钟接口比现有快照更旧；保留现有数据。')
        first_day=rows[0]['datetime'][:10];last_day=rows[-1]['datetime'][:10]
        missing=[]
        for day in sorted(d for d in sessions if first_day<=d<=last_day):
            for end in TIMES:
                stamp=day+' '+end
                if datetime.fromisoformat(stamp).replace(tzinfo=TZ)+timedelta(seconds=SETTLEMENT_SECONDS)<=now and stamp not in by_stamp:
                    missing.append(stamp)
        if missing:result['warnings'].append(f'分钟来源在完整区间缺{len(missing)}根柱，未插补；首个缺口{missing[0]}。')
        if latest_bar and rows[0]['datetime']>latest_bar:
            result['warnings'].append('分钟可用窗口起点晚于已有末柱；需校验衔接，不能忽略中间缺口。')
    return result
