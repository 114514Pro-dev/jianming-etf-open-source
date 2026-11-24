"""Versioned data/replay boundary for the fixed bear-market gold strategy."""
from __future__ import annotations
from copy import deepcopy
from dataclasses import asdict
from datetime import date,datetime,timedelta,timezone
from html.parser import HTMLParser
from pathlib import Path
import csv,hashlib,json,math,os,re,tempfile,urllib.request
from bear_gold_kernel import CODES,NAMES,RULE,Context,run_account
import bear_gold_assets as assets

DATA_SCHEMA='skdj.bear-gold.data.v1'
RESULT_SCHEMA='skdj.bear-gold.result.v1'
REFERENCE_SHA='30342427ea87802dd037d439e57023e9989140edb608f9528ad108b488afe187'
REFERENCE_START='2012-01-04'; REFERENCE_END='2026-09-07'
EXPECTED={'final':4247986.667266309,'cagr':.29107167536130873,'mdd':.2207378250379799,'fills':453}
FIRST={'sz159920':'2011-12-09','sh518880':'2013-07-29','sh511010':'2013-03-25'}
KNOWN_PRELIST_SPLITS={'sz159920':('2011-11-30',1.1456),'sh518880':('2013-07-24',.3776),'sh511010':('2013-03-05',.01)}

def fingerprint(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf8')).hexdigest()

def _day(value):
    if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):raise ValueError('日期必须为YYYY-MM-DD。')
    return date.fromisoformat(value).isoformat()

def _number(value,minimum=0):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<minimum:raise ValueError('数据存在无效数值。')
    return value

def validate_dataset(dataset):
    if not isinstance(dataset,dict) or dataset.get('schema') not in (DATA_SCHEMA,assets.DATA_SCHEMA):raise ValueError('不是熊市黄金策略行情包。')
    general=dataset['schema']==assets.DATA_SCHEMA
    symbol,codes,names=assets.identity(dataset)
    if general:
        if assets.normalize_etf(symbol)!=symbol:raise ValueError('进攻ETF代码必须使用标准交易所前缀。')
        for field in ['first_dates','history_start','asset_names','split_adjustments']:
            if not isinstance(dataset.get(field),dict) or set(dataset[field])!=set(codes):raise ValueError('ETF数据包缺少身份、历史起点或折算信息。')
        if any(not isinstance(n,str) or not n.strip() or len(n)>100 for n in dataset['asset_names'].values()):raise ValueError('ETF名称无效。')
    asof=_day(dataset.get('asof'))
    if set(dataset.get('bars',{}))!=set(codes) or set(dataset.get('corporate_actions',{}))!=set(codes):raise ValueError('行情必须对应所选进攻ETF、黄金518880及国债511010。')
    for c in dict.fromkeys(codes):
        bars=dataset['bars'][c]
        if not isinstance(bars,list) or not bars or len(bars)>30000:raise ValueError(c+' 行情为空或数量异常。')
        first=_day(dataset['first_dates'][c]) if general else FIRST[c]
        if bars[0].get('date')!=first or (c in FIRST and first!=FIRST[c]):raise ValueError(c+' 缺少上市起完整历史，无法保持指标初始化一致。')
        if general and not _day(dataset['history_start'][c])<=first<=asof:raise ValueError('ETF历史起点无效。')
        previous=''
        for z in bars:
            d=_day(z.get('date'))
            if d<=previous or d>asof:raise ValueError(c+' 行情日期重复、乱序或晚于截止日。')
            previous=d
            for key in ['open','close','high','low']:_number(z.get(key),1e-12)
            if not z['low']<=min(z['open'],z['close'])<=max(z['open'],z['close'])<=z['high']:raise ValueError(c+' OHLC价格关系错误。')
            _number(z.get('volume_lots'),1e-12);_number(z.get('amount_cny'),0)
        actions=dataset['corporate_actions'][c]
        if not isinstance(actions,dict) or not isinstance(actions.get('dividends'),list) or not isinstance(actions.get('splits'),list):raise ValueError(c+' 缺少分红与份额折算记录。')
        seen=set()
        for event in actions['dividends']:
            rec=_day(event.get('record'));ex=_day(event.get('ex'));pay=_day(event.get('pay'))
            if not rec<=ex<=pay or ex in seen:raise ValueError(c+' 分红日期关系错误或重复。')
            seen.add(ex);_number(event.get('cash_per_share'),1e-12)
        for event in actions['splits']:
            d=_day(event.get('date'));ratio=_number(event.get('ratio'),1e-12)
            if not general and (d,ratio)!=KNOWN_PRELIST_SPLITS[c]:raise ValueError(c+' 出现尚未核准生效日的新份额折算，请先核实公司行动再回测。')
        if general and dataset['split_adjustments'][c]!=assets.approved_splits(c,actions['splits'],first,asof):raise ValueError(c+' 折算生效日期或精确比例校验不一致。')
    return dataset

def load_reference():
    module_dir=Path(__file__).resolve().parent
    # PyInstaller flattens top-level modules into the extraction root; source
    # checkouts keep this module and its data under engine_snapshot.
    candidates=[module_dir/'bear_gold_reference.json',module_dir/'engine_snapshot/bear_gold_reference.json']
    path=next((p for p in candidates if p.is_file()),None)
    if path is None:raise ValueError('程序缺少内置历史校验资料，请使用完整修复版重新打开。')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=REFERENCE_SHA:raise ValueError('内置研究行情校验失败，请恢复原版本数据文件。')
    return validate_dataset(json.loads(raw))

def _read_json(path):
    p=Path(path)
    if p.stat().st_size>50_000_000:raise ValueError('结果文件大于50MB。')
    def pairs(items):
        out={}
        for k,v in items:
            if k in out:raise ValueError('JSON字段重复：'+k)
            out[k]=v
        return out
    def constant(v):raise ValueError('JSON不接受非有限数值：'+v)
    return json.loads(p.read_text(encoding='utf-8-sig'),object_pairs_hook=pairs,parse_constant=constant)

def atomic_json(path,payload):
    output=Path(path).expanduser().resolve();temporary=None
    try:
        with tempfile.NamedTemporaryFile('w',encoding='utf8',dir=output.parent,prefix='.'+output.name,suffix='.tmp',delete=False) as f:
            temporary=Path(f.name);json.dump(payload,f,ensure_ascii=False,allow_nan=False,separators=(',',':'))
        os.replace(temporary,output)
    finally:
        if temporary and temporary.exists():temporary.unlink()
    return output

def buy_hold_account(dataset,start,end,capital=100000.,save_daily=True):
    """Same ETF/dates/capital/costs: buy once, retain dividends as cash, sell at end."""
    context=Context(dataset,start,end,capital)
    context.regime=[1.]*len(context.dates);context.events={}
    context.targets=lambda spec,day,risk:(1.,0.,0.)
    result=run_account(context,save_daily=save_daily)
    result['name']='所选ETF买入持有'
    result['symbol']=context.symbol
    result['actual']={'start':context.start,'end':context.end,'days':len(context.dates)}
    result['policy']='相同资金、日期、佣金与滑点；首日开盘买入所选ETF，分红留现金，末日收盘统一清算。'
    return result


def run(dataset=None,start=REFERENCE_START,end=REFERENCE_END,capital=100000.,progress=None):
    dataset=validate_dataset(deepcopy(dataset) if dataset is not None else load_reference())
    start=_day(start);end=_day(end);capital=float(capital)
    if start<REFERENCE_START or start>=end:raise ValueError('起始日期不得早于2012-01-04，且必须早于结束日期。')
    if not math.isfinite(capital) or not 1000<=capital<=1e10:raise ValueError('初始资金应在1,000元至100亿元之间。')
    if end>dataset['asof']:raise ValueError('所选结束日期晚于行情包截止日，请先联网更新行情。')
    if progress:progress('正在按50周固定规则从初始资金和空仓重新计算…')
    context=Context(dataset,start,end,capital);result=run_account(context)
    result['buy_hold']=buy_hold_account(dataset,start,end,capital)
    for row,state in zip(result['curve'],context.states):row['state']=state
    for z in result['logs']:
        state=context.state_lookup.get(z['signal'],{})
        z['market']=state.get('close_market','warmup')
        z['trigger']=state.get('reason','初始配置') if z['side']!='期末清算' else '期末回测结算'
    states=context.states;last=states[-1]
    result['latest_state']=dict(last,defense='黄金' if last['close_market']=='bear' else '黄金和国债各半')
    result['requested']={'start':start,'end':end,'capital':capital}
    result['actual']={'start':context.start,'end':context.end,'days':len(context.dates)}
    result['schema']=RESULT_SCHEMA;result['rule']=deepcopy(RULE)
    if dataset['schema']==assets.DATA_SCHEMA:
        result['schema']=assets.RESULT_SCHEMA
        result['requested']['symbol']=context.symbol
    result['dataset']=dataset;result['data_sha256']=fingerprint(dataset)
    result['generated_at']=datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds')
    reference=load_reference()
    same_inputs=result['data_sha256']==fingerprint(reference)
    result['reference_check']=None
    if same_inputs and start==REFERENCE_START and end==REFERENCE_END and capital==100000.:
        delta={key:result['metrics'][key]-value for key,value in EXPECTED.items()}
        if any(abs(v)>1e-5 for v in delta.values()):raise ValueError('内置研究结果复现失败，已停止显示。')
        result['reference_check']={'matched':True,'differences':delta}
    result['notices']=[
        '固定研究规则，未进行新的参数优选；这段历史已用于开发，不能当成独立样本外。',
        '熊市最多20%是目标上限，价格变化可使实际占比漂移；收盘确认，次日开盘执行。',
        '基准佣金万三、最低5元、滑点万二；现金不计息，ETF不收印花税。',
        '黄金与国债上市前对应份额留现金。末日统一清算仅用于回测结算。',
        '首周与最后一周不参与完整周线信号；历史区间子集从该区间初始资金和空仓运行。',
    ]
    if dataset.get('source_mode')=='online':result['notices'].append('本次使用联网重新获取的数据批次，供应商修订历史数据可能使结果与冻结研究不同。')
    if dataset['schema']==assets.DATA_SCHEMA:
        result['notices'][0]='沿用恒生指数研究的固定参数，未为所选ETF重新选参；其他ETF的收益须按本次行情重新计算。'
        result['notices'].append('趋势和入场信号使用所选ETF自身周线；已发生的上市后折算按当时比例衔接指标，交易使用原始价格和实际份额。')
        result['notices'].append('按所选ETF的可用交易日计时；未满50周时先按金债防守配置，进攻ETF无历史的早期日期不计收益。')
        if context.start>start:result['notices'].append('所选ETF尚无更早交易行情，实际起点后移至'+context.start+'。')
    if context.end<end:result['notices'].append('结束日期不是可用交易日，实际计算至'+context.end+'。')
    return result

def replay_file(path,progress=None):
    payload=_read_json(path)
    if not isinstance(payload,dict) or payload.get('schema') not in (RESULT_SCHEMA,assets.RESULT_SCHEMA) or payload.get('rule')!=RULE:raise ValueError('文件不是本版本熊市黄金50周的固定结果包。')
    data=validate_dataset(payload.get('dataset'))
    general=data['schema']==assets.DATA_SCHEMA
    if payload['schema']!=(assets.RESULT_SCHEMA if general else RESULT_SCHEMA):raise ValueError('结果与行情包版本不一致。')
    if payload.get('data_sha256')!=fingerprint(data):raise ValueError('结果包的行情哈希校验失败。')
    req=payload.get('requested',{})
    if general and req.get('symbol')!=assets.identity(data)[0]:raise ValueError('保存的进攻ETF与行情包身份不一致。')
    fresh=run(data,req.get('start'),req.get('end'),req.get('capital'),progress)
    fresh['replay_comparison']={key:fresh['metrics'][key]-payload['metrics'][key] for key in EXPECTED}
    if any(abs(v)>1e-5 for v in fresh['replay_comparison'].values()):raise ValueError('保存结果与按包内数据重算的结果不一致。')
    if 'buy_hold' in payload:
        differences={key:fresh['buy_hold']['metrics'][key]-payload['buy_hold']['metrics'][key] for key in EXPECTED}
        if any(abs(v)>1e-5 for v in differences.values()):raise ValueError('保存的买入持有结果与重算不一致。')
        fresh['buy_hold_replay_comparison']=differences
    return fresh

def export_trades(result,path):
    from market_data_export import _safe_text
    with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.writer(f);w.writerow(['成交日期','信号日期','标的','方向','份额','成交价元','佣金元','信号时市场','触发原因'])
        for z in result['logs']:
            w.writerow([_safe_text(z[k]) if isinstance(z[k],str) else z[k] for k in ['date','signal','asset','side','qty','price','fee','market','trigger']])
    return Path(path)

class _Rows(HTMLParser):
    def __init__(self):super().__init__();self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,t,a):
        if t=='tr':self.row=[]
        if t in ['td','th'] and self.row is not None:self.cell=[]
    def handle_data(self,x):
        if self.cell is not None:self.cell.append(x)
    def handle_endtag(self,t):
        if t in ['td','th'] and self.cell is not None:self.row.append(''.join(self.cell).strip());self.cell=None
        if t=='tr' and self.row is not None:self.rows.append(self.row);self.row=None

def parse_actions(html):
    if '拆分详情' not in html or '分红送配详情' not in html:raise ValueError('分红页面结构无法识别，不能按零分红继续。')
    parser=_Rows();parser.feed(html);div=[];spl=[]
    for row in parser.rows:
        if len(row)==5 and re.fullmatch(r'\d{4}-\d{2}-\d{2}',row[1]):
            match=re.search(r'派现金([\d.]+)',row[3])
            if not match:raise ValueError('分红金额格式无法识别。')
            div.append(dict(record=row[1],ex=row[2],cash_per_share=float(match.group(1))/10,pay=row[4]))
        if len(row)==4 and re.fullmatch(r'\d{4}-\d{2}-\d{2}',row[1]):
            spl.append(dict(date=row[1],type=row[2],ratio=float(row[3].split(':')[1])))
    return dict(dividends=div,splits=spl)

def refresh(core,end,progress=None):
    """Explicit fresh network batch. Never fall back silently to the bundled research."""
    end=_day(end)
    if end>=core.cn_today().isoformat():raise ValueError('联网更新仅使用已结束交易日，结束日期请设为北京时间昨天或更早。')
    if end<'2013-07-29':raise ValueError('联网完整三资产包的截止日期不得早于黄金ETF上市日；更早区间可用内置研究包。')
    reference=load_reference();bars={};actions={};receipts={}
    for c,name in zip(CODES,NAMES):
        if progress:progress('正在联网读取'+name+'未复权行情与分红记录…')
        _,arr=core._fetch_history_tencent(c,date.fromisoformat(FIRST[c]),date.fromisoformat(end),'none')
        bars[c]=[asdict(z) for z in arr]
        url=f'https://fundf10.eastmoney.com/fhsp_{c[2:]}.html'
        request=urllib.request.Request(url,headers={'User-Agent':'Mozilla/5.0'})
        with urllib.request.urlopen(request,timeout=35) as response:html=response.read(3_000_001).decode('utf8')
        if len(html)>3_000_000:raise ValueError('分红响应过大。')
        parsed=parse_actions(html);parsed['url']=url;actions[c]=parsed
        # Missing an already verified payment must not silently turn into zero dividends.
        for known in reference['corporate_actions'][c]['dividends']:
            if known['ex']<=end and known not in parsed['dividends']:raise ValueError(c+' 联网分红记录缺少或改变了已核实项目，请核对数据源。')
        receipts[c]={'corporate_actions_html':html,'corporate_actions_sha256':hashlib.sha256(html.encode('utf8')).hexdigest(),'price_source':'腾讯未复权日线；已解析标准化OHLCV'}
    dataset=dict(schema=DATA_SCHEMA,asof=end,bars=bars,corporate_actions=actions,source_mode='online',source='腾讯未复权行情及东方财富分红页面的本次联网批次',receipts=receipts)
    return validate_dataset(dataset)
