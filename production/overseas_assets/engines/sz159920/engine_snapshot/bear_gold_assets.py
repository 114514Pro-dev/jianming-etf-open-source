"""ETF identity and verified post-listing share conversions for the gold strategy."""
from copy import deepcopy
from datetime import date,datetime,timedelta,timezone
import re,urllib.request,time
from urllib.error import URLError,HTTPError

DATA_SCHEMA='skdj.bear-gold.data.v2'
RESULT_SCHEMA='skdj.bear-gold.result.v2'
DEFENSE=['sh518880','sh511010']
SPLITS={
    'sh512100':{
        '2022-09-02':{'effective':'2022-09-05','ratio':0.36555,'rounding':'ceil',
            'source':'https://pdf.dfcfw.com/pdf/H2_AN202209051578033984_1.pdf'},
    },
    'sh512800':{
        '2025-07-04':{'effective':'2025-07-07','ratio':2.0,'rounding':'floor',
            'source':'https://www.sse.com.cn/disclosure/fund/announcement/c/new/2025-07-07/512800_20250707_PJ9L.pdf'},
    },
    'sh510500':{
        '2015-04-14':{'effective':'2015-04-15','ratio':0.28032483,'rounding':'floor',
            'source':'https://pdf.dfcfw.com/pdf/H2_AN201504150009203406_1.pdf'},
        '2022-08-26':{'effective':'2022-08-29','ratio':1.14539,'rounding':'ceil',
            'source':'https://pdf.dfcfw.com/pdf/H2_AN202208291577764682_1.pdf'},
    }
}


def identity(dataset):
    symbol=dataset.get('attack_symbol','sz159920') if dataset.get('schema')==DATA_SCHEMA else 'sz159920'
    codes=[symbol,*DEFENSE]
    mapping=dataset.get('asset_names',{})
    names=[mapping.get(symbol,'恒生指数' if symbol=='sz159920' else symbol),'黄金','5年国债']
    return symbol,codes,names


def normalize_etf(symbol):
    import skdj
    code=skdj.normalize_symbol(symbol)
    if not skdj.is_etf_symbol(code):raise ValueError('该组合策略的进攻标的应为沪深场内ETF，请输入ETF代码。')
    return code


def approved_splits(code,events,first,asof):
    out={}
    for event in events:
        if event['date']<first or event['date']>asof:continue
        approved=SPLITS.get(code,{}).get(event['date'])
        if approved is None or abs(approved['ratio']-event['ratio'])>0.000051:
            raise ValueError(f"{code}在{event['date']}发生上市后份额折算，精确比例及生效时点尚未核准，不能忽略折算继续回测。")
        if approved['effective']<=asof:out[approved['effective']]=deepcopy(approved)
    return out


def read_html(url):
    request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request,timeout=12) as response:raw=response.read(3_000_001)
            break
        except (URLError,OSError) as exc:
            if isinstance(exc,HTTPError) and exc.code not in (408,429,500,502,503,504):raise
            if attempt==2:raise
            time.sleep(.5*(attempt+1))
    if len(raw)>3_000_000:raise ValueError('基金资料响应过大。')
    return raw.decode('utf8')


def fund_profile(html,code):
    # Match the fund facts table, not a date elsewhere in the navigation.
    if not re.search(r'<th>基金代码</th>\s*<td>\s*'+code[2:],html):raise ValueError('基金资料与ETF代码不一致。')
    name=re.search(r'<th>基金简称</th>\s*<td>([^<]+)',html)
    inception=re.search(r'<th>成立日期/规模</th>\s*<td>(\d{4})年(\d{1,2})月(\d{1,2})日',html)
    full_name=re.search(r'<th>基金全称</th>\s*<td[^>]*>([^<]+)',html)
    if not name or not inception or not full_name or '交易型' not in full_name.group(1):
        raise ValueError('无法确认ETF身份及成立日期，未使用不完整历史。')
    start=date(*map(int,inception.groups())).isoformat()
    return name.group(1).strip(),start


def refresh(core,symbol,end,progress=None,allow_completed_today=False):
    from dataclasses import asdict
    import hashlib
    import bear_gold as gold
    symbol=normalize_etf(symbol);end=gold._day(end)
    today=core.cn_today().isoformat()
    after_close=datetime.now(timezone(timedelta(hours=8))).hour>=16
    if end>today or (end==today and not (allow_completed_today and after_close)):
        raise ValueError('结束日期请设为北京时间昨天或更早；动态分析仅在16:00后允许读取当日已收盘日线。')
    if end<'2013-07-29':raise ValueError('其他ETF的完整金债行情包需截止到2013-07-29或以后。')
    reference=gold.load_reference();bars={};actions={};receipts={};names={};firsts={};history={};adjustments={}
    for code in dict.fromkeys([symbol,*DEFENSE]):
        if progress:progress('正在读取'+code+'的完整ETF行情、分红与折算记录…')
        if code in gold.FIRST:
            history[code]=gold.FIRST[code]
            names[code]=dict(zip(gold.CODES,gold.NAMES))[code]
        else:
            profile_url=f'https://fundf10.eastmoney.com/jbgk_{code[2:]}.html'
            profile=read_html(profile_url);names[code],history[code]=fund_profile(profile,code)
            receipts[code]={'profile_url':profile_url,'profile_html':profile}
        if history[code]>end:raise ValueError(code+'在截止日期尚未成立，没有可交易历史。')
        fetched_name,arr=core._fetch_history_tencent(code,date.fromisoformat(history[code]),date.fromisoformat(end),'none')
        if not arr:raise ValueError(code+'未返回有效ETF行情。')
        bars[code]=[asdict(z) for z in arr];firsts[code]=arr[0].date
        if code not in gold.FIRST and fetched_name:names[code]=fetched_name
        url=f'https://fundf10.eastmoney.com/fhsp_{code[2:]}.html';html=read_html(url)
        parsed=gold.parse_actions(html);parsed['url']=url;actions[code]=parsed
        if code in reference['corporate_actions']:
            for known in reference['corporate_actions'][code]['dividends']:
                if known['ex']<=end and known not in parsed['dividends']:raise ValueError(code+'联网记录缺少已核实分红。')
        adjustments[code]=approved_splits(code,parsed['splits'],firsts[code],end)
        receipts.setdefault(code,{}).update(corporate_actions_html=html,corporate_actions_sha256=hashlib.sha256(html.encode('utf8')).hexdigest(),price_source='腾讯未复权日线')
    dataset=dict(schema=DATA_SCHEMA,asof=end,attack_symbol=symbol,asset_names=names,first_dates=firsts,
        history_start=history,split_adjustments=adjustments,bars=bars,corporate_actions=actions,receipts=receipts,
        source_mode='online',source='腾讯未复权行情及东方财富基金资料、分红；上市后折算按已核准公告处理')
    return gold.validate_dataset(dataset)
