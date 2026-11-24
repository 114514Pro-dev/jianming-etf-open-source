"""Thirty-minute public quote snapshots, separate from confirmed daily ledgers."""
from pathlib import Path
from datetime import datetime, timedelta, timezone
from copy import deepcopy, copy
from urllib.request import Request, build_opener, ProxyHandler, urlopen
import re, json, math, sqlite3, time, hashlib, uuid
import bank_model as model
import trade_book as ledger

CN=timezone(timedelta(hours=8));INTERVAL=30*60
URL='https://qt.gtimg.cn/q='+','.join(ledger.CODES)
def now():return datetime.now(CN)

class PollClock:
    def __init__(self,interval=INTERVAL,clock=time.monotonic):self.interval=interval;self.clock=clock;self.next_due=clock()
    def due(self,enabled=True,busy=False):return bool(enabled and not busy and self.clock()>=self.next_due)
    def started(self):self.next_due=self.clock()+self.interval
    def remaining(self):return max(0,int(math.ceil(self.next_due-self.clock())))

def parse_quotes(text,received=None):
    received=received or now();out={}
    for symbol,body in re.findall(r'v_(sh\d{6}|sz\d{6})="([^"\r\n]*)";',text):
        if symbol not in ledger.CODES:continue
        if symbol in out:raise ValueError('行情源返回重复代码')
        fields=body.split('~')
        try:
            if len(fields)<38 or fields[2]!=symbol[2:]:raise ValueError('标的代码不匹配')
            stamp=datetime.strptime(fields[30],'%Y%m%d%H%M%S').replace(tzinfo=CN)
            if stamp>received+timedelta(minutes=5):raise ValueError('行情时间晚于本机时间，请检查时钟')
            price,previous,opening,volume,high,low=map(float,[fields[i] for i in [3,4,5,6,33,34]])
            amount=float(fields[37])*10000
            if not all(math.isfinite(v) for v in [price,previous,opening,volume,high,low,amount]):raise ValueError('行情包含无效数字')
            if min(price,previous)<=0 or min(opening,volume,high,low,amount)<0:raise ValueError('行情价格或成交量无效')
            # A pre-open quote may have zero opening/high/low; show it but do not build a provisional bar.
            started=bool(opening and low and high and volume)
            if started and not low<=min(opening,price)<=max(opening,price)<=high:raise ValueError('当日开高低现价不一致')
            out[symbol]=dict(symbol=symbol,name=ledger.NAMES[symbol],price=price,previous_close=previous,open=opening,high=high,low=low,
                volume_lots=volume,amount_cny=amount,change=price/previous-1,quote_at=stamp.isoformat(),day=stamp.date().isoformat(),started=started)
        except (ValueError,IndexError,TypeError) as e:raise ValueError(symbol+' 行情解析失败：'+str(e)) from e
    if set(out)!=set(ledger.CODES):raise ValueError('四只ETF报价不完整，保留上次成功数据')
    return dict(schema='simpleetf.intraday.v1',received_at=received.isoformat(),source='腾讯公开行情',source_url=URL,quotes=out)

def fetch_quotes():
    req=Request(URL,headers={'User-Agent':'Mozilla/5.0','Referer':'https://gu.qq.com/'})
    last=None
    for opener in [build_opener(ProxyHandler({})),None]:
        try:
            with (opener.open(req,timeout=12) if opener else urlopen(req,timeout=12)) as response:raw=response.read(100001)
            if len(raw)>100000:raise ValueError('行情响应超出预期大小')
            return parse_quotes(raw.decode('gb18030'))
        except (OSError,ValueError) as exc:last=exc
    raise ValueError('当天行情更新失败：'+str(last))

class LiveStore:
    def __init__(self,folder):
        self.path=Path(folder)/'盘中行情.sqlite3'
        with sqlite3.connect(self.path) as con:
            con.execute('CREATE TABLE IF NOT EXISTS snapshots(id TEXT PRIMARY KEY,received_at TEXT,payload TEXT)')
            con.execute('CREATE TABLE IF NOT EXISTS attempts(id TEXT PRIMARY KEY,attempted_at TEXT,status TEXT,note TEXT)')
    def save(self,batch):
        key=ledger.digest(batch)
        with sqlite3.connect(self.path) as con:
            con.execute('INSERT OR IGNORE INTO snapshots VALUES (?,?,?)',(key,batch['received_at'],json.dumps(batch,ensure_ascii=False,allow_nan=False)))
        return key
    def record_attempt(self,status,note):
        with sqlite3.connect(self.path) as con:con.execute('INSERT INTO attempts VALUES (?,?,?,?)',(uuid.uuid4().hex,now().isoformat(),status,note))
    def latest(self):
        with sqlite3.connect(self.path) as con:r=con.execute('SELECT payload FROM snapshots ORDER BY received_at DESC LIMIT 1').fetchone()
        return json.loads(r[0]) if r else None
    def stats(self):
        with sqlite3.connect(self.path) as con:
            count,first,last=con.execute('SELECT count(*),min(received_at),max(received_at) FROM snapshots').fetchone()
        return dict(count=count,first=first,last=last)
    def export(self,path):
        import csv
        with sqlite3.connect(self.path) as con:rows=con.execute('SELECT payload FROM snapshots ORDER BY received_at').fetchall()
        with Path(path).open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.writer(f);w.writerow(['采集时间','报价时间','代码','名称','现价','昨收','涨跌幅','开盘','最高','最低','累计成交手数','累计成交金额元','来源'])
            for raw, in rows:
                b=json.loads(raw)
                for c,q in b['quotes'].items():w.writerow([b['received_at'],q['quote_at'],c,q['name'],q['price'],q['previous_close'],q['change'],q['open'],q['high'],q['low'],q['volume_lots'],q['amount_cny'],b['source']])
        return len(rows)

def provisional_market(base,batch,moment=None):
    """Pure copy: only provisional observation, never a tradable account market."""
    moment=moment or now();today=moment.date().isoformat();quotes=batch['quotes']
    if any(q['day']!=today or not q['started'] for q in quotes.values()):raise ValueError('部分报价不是今天的有效成交行情，仅展示报价，暂不生成盘中目标')
    if moment.weekday()>=5:raise ValueError('非工作日，仅展示来源最后报价')
    stamps=[datetime.fromisoformat(q['quote_at']) for q in quotes.values()]
    if (max(stamps)-min(stamps)).total_seconds()>1800:raise ValueError('四只ETF报价时间相差超过30分钟，暂不合成盘中目标')
    # Time since last trade can span lunch; use an explicit age notice in the UI.
    if (moment-max(stamps)).total_seconds()>3*3600:raise ValueError('报价已超过3小时，暂不生成盘中目标')
    if today<base.latest:raise ValueError('报价日期早于已确认历史')
    if today>base.latest:
        expected=model.cutoff(moment.replace(hour=12,minute=0))
        if base.latest<expected:raise ValueError('已确认日线尚未衔接到上一工作日，请先更新历史；节假日也可等下一有效交易日核对')
        for c,q in quotes.items():
            if abs(base.at(base.latest)['prices'][c]-q['previous_close'])>max(.0011,abs(q['previous_close'])*.0001):
                raise ValueError(ledger.NAMES[c]+'昨收与历史末日不一致，可能有除权或数据修订，暂停盘中目标')
    data=deepcopy(base.data)
    for dataset in data.values():
        dataset['asof']=today
        for c,arr in dataset['bars'].items():
            q=quotes[c];bar=dict(date=today,open=q['open'],close=q['price'],high=q['high'],low=q['low'],volume_lots=q['volume_lots'],amount_cny=q['amount_cny'])
            dataset['bars'][c]=[r for r in arr if r['date']<today]+[bar]
    m=copy(base);m.data=model.validate_data(data);m.inputs=model.inputs(m.data);m.hash=ledger.digest(m.data);m.latest=today;m.provisional=True
    m.bars=m.inputs.bars;m.dates=sorted({r['date'] for arr in m.bars.values() for r in arr if '2012-01-04'<=r['date']<=today})
    m.look={c:{r['date']:r for r in arr} for c,arr in m.bars.items()};m.bar_dates={c:[r['date'] for r in arr] for c,arr in m.bars.items()}
    m.signals=model.Signals(m)
    # Avoid the cached bound observation function inherited from the confirmed market.
    m.observation=lambda code,day:m.signals.observation(code,day)
    return m

class LiveService:
    def __init__(self,service):self.service=service;self.store=LiveStore(service.folder);self.batch=self.store.latest();self.preview=None;self.preview_note='等待当天报价';self.history_note='';self.history_error='';self.observations={}
    def refresh(self,progress=lambda _:None,force_history=False,fetcher=fetch_quotes,moment=None):
        moment=moment or now();progress('正在读取四只ETF当天报价…')
        self.observations={};self.preview=None;self.history_note='';self.history_error=''
        try:
            batch=fetcher();self.store.save(batch);self.batch=batch;self.store.record_attempt('成功','报价采集成功')
        except Exception as exc:
            self.preview=None;self.preview_note='本次更新失败，显示上次保存的报价；'+str(exc);self.store.record_attempt('失败',str(exc));raise
        self.history_note=''
        needs_history=self.service.market.latest<model.cutoff(moment)
        if force_history or needs_history:
            # No account is advanced by a quote timer. Binding confirmed snapshots is explicit on the account page.
            try:self.history_note=self.service.update_market(progress=progress)
            except Exception as exc:
                self.history_error=str(exc);self.history_note='收盘日线更新失败：'+self.history_error
                self.store.record_attempt('日线失败',self.history_error)
        progress('正在生成独立盘中参考目标…')
        try:
            self.preview=provisional_market(self.service.market,batch,moment)
            self.observations={code:deepcopy(self.preview.observation(code,self.preview.latest)) for code in model.LABELS}
            self.preview_note='盘中临时目标：以当前累计日线试算，收盘前可能变化；不写入历史账户或提交委托。'
        except ValueError as exc:self.preview=None;self.preview_note=str(exc)
        return batch
    def refresh_status(self):
        if self.history_error:return '当天报价已保存，但收盘日线更新失败；盘中方案需等待历史补齐。'
        if self.preview is None:return '当天报价已保存；当前暂不能生成盘中方案，请查看页面提示。'
        return '当天报价与盘中方案已更新；收盘日线至 '+self.service.market.latest+'，30分钟后再次检查。'
    def plan(self,code,capital):
        capital=ledger.number(capital,'参考本金',1e9)
        if capital<1000:raise ValueError('参考本金至少1000元')
        if not self.preview:return None
        obs=self.observations[code]
        budget={c:capital*obs['weights'][c] for c in ledger.CODES}
        return dict(day=self.preview.latest,strategy=code,observation=deepcopy(obs),capital=capital,budgets=budget,cash=capital*max(0,1-sum(obs['weights'].values())))
