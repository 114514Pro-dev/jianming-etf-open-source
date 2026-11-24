"""Simple UI service; all money movements use the inherited audited ledger."""
from pathlib import Path
from copy import deepcopy
from functools import lru_cache
from datetime import date, datetime
import os, json, csv, io, zipfile, tempfile, threading, uuid, math
import bank_model as model
import trade_book as ledger
from suite_book import SuiteBook
from suite_analysis import metrics
from dynamic_allocation import rebalance_reason, MODES

ROOT=Path(__file__).resolve().parent
VERSION='1.3'
ENGINE='simpleetf-confirmed-20260914-v1'
CODES=ledger.CODES
NAMES=ledger.NAMES
ORDER=['D5','DW','D0','F0','F10','F20','L0','L10','L20']
TITLES={'D5':'动态强弱 · 5%偏离调仓','DW':'动态强弱 · 周线调仓','D0':'动态强弱 · 每日调仓',
        'F0':'分阶段配置 · 股票底仓0%','F10':'分阶段配置 · 股票底仓10%','F20':'分阶段配置 · 股票底仓20%',
        'L0':'四态融合 · 股票底仓0%','L10':'四态融合 · 股票底仓10%','L20':'四态融合 · 股票底仓20%'}
DESCRIPTIONS={
 'D5':'在已通过趋势确认的资产中，按动量与波动率分配仓位。偏离目标超过5个百分点才调仓；趋势失效按日退出。',
 'DW':'与动态强弱使用相同选股和配比；周线确认后检查5个百分点偏离，趋势失效仍按日退出。',
 'D0':'每日检查目标偏离并调仓，跟随更紧，交易频率与费用可能更高。',
 'F0':'纳指100采用原50周趋势与SKDJ/TRIX，银行采用原SKDJ规则；黄金和国债通过各自趋势门槛。股票均转弱时股票清仓。',
 'F10':'分阶段配置；股票均转弱时保留合计10%的股票预算，其余根据黄金、国债趋势分配，条件不符留现金。',
 'F20':'分阶段配置；股票均转弱时保留合计20%的股票预算。相比0%底仓，仍承担股票继续下跌的风险。',
 'L0':'纳指100与银行双多时60/40，单多时100%配置该股票ETF；双空时退出股票，黄金满足条件才接替，否则现金。',
 'L10':'四态融合；双空时保留合计10%的股票底仓，剩余黄金或现金。短周信号使用保守确认规则。',
 'L20':'四态融合；双空时保留合计20%的股票底仓，剩余黄金或现金。短周信号使用保守确认规则。'}
RULE_NOTE='收盘产生信号 → 下一可执行日开盘模拟；佣金万三、每笔最低5元，单边滑点万二；买入100份整数倍。'

def read_json(path):return json.loads(Path(path).read_text(encoding='utf8'))
def write_json(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8');os.replace(tmp,path)

def compatible(old,new):
    """Reject any historical quote/action revision. Existing accounts keep their snapshot."""
    end=old.latest
    if new.latest<end:return False
    for c in CODES:
        if [r for r in old.bars[c] if r['date']<=end]!=[r for r in new.bars[c] if r['date']<=end]:return False
        if {k:v for k,v in old.inputs.splits[c].items() if k<=end}!={k:v for k,v in new.inputs.splits[c].items() if k<=end}:return False
        for key in ['dividends']:
            keep=lambda arr:[r for r in arr if min(r.get(k,'9999-12-31') for k in ['record','ex','pay'])<=end]
            if keep(old.inputs.actions[c][key])!=keep(new.inputs.actions[c][key]):return False
    return True

class Service:
    def __init__(self,folder=None):
        self.folder=Path(folder or os.environ.get('SIMPLE_ETF_HOME') or Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'SimpleETFSimulator')
        self.folder.mkdir(parents=True,exist_ok=True);self.cache={};self.book=SuiteBook(self.folder/'账户')
        self.settings=read_json(self.folder/'设置.json') if (self.folder/'设置.json').exists() else {}
        if not self.settings.get('market'):
            m=self.store_market(read_json(ROOT/'初始行情.json'));self.settings['market']=m.hash;self.save_settings()
        self.market=self.market_by_hash(self.settings['market'])
    def save_settings(self):write_json(self.folder/'设置.json',self.settings)
    def store_market(self,data):
        m=ledger.Market(data=data);m.observation=lru_cache(maxsize=50000)(m.observation)
        path=self.folder/'行情快照'/(m.hash+'.json')
        if not path.exists():write_json(path,m.data)
        self.cache[m.hash]=m;return m
    def market_by_hash(self,h):
        if len(h)!=64 or any(x not in '0123456789abcdef' for x in h):raise ValueError('行情快照编号无效')
        if h not in self.cache:
            m=self.store_market(read_json(self.folder/'行情快照'/(h+'.json')))
            if m.hash!=h:raise ValueError('行情快照校验失败')
        return self.cache[h]
    def account_market(self,state):
        meta=state.get('simulator',{})
        if meta.get('engine')!=ENGINE:raise ValueError('账户版本不匹配，请使用对应版本的软件打开')
        return self.market_by_hash(meta['market'])
    def default_start(self):
        return next(d for d in self.market.dates if d>='2013-01-01')
    def create(self,name,capital,start,strategy,market=None,book=None):
        m=market or self.market;b=book or self.book
        if getattr(m,'provisional',False):raise ValueError('盘中临时行情不能建立正式历史账户')
        s=b.create(name,float(capital),start,m,strategy)
        with b.connection() as con:
            s=b.get(s['id'],con);s['simulator']=dict(engine=ENGINE,market=m.hash);b.save(con,s)
        return b.advance(s['id'],m,start)
    def switch(self,id,strategy):
        with self.book.lease(id):
            s=self.book.get(id);m=self.account_market(s)
            self.book.set_strategy(id,strategy)
            return self.book.advance(id,m,s['day'])
    def run(self,id,end,stop=None,progress=lambda _:None):
        initial=self.book.get(id);m=self.account_market(initial);m.at(end)
        if end<=initial['day']:raise ValueError('请选择账户日期之后的交易日；重练请新建账户。')
        return self.run_book(self.book,initial,m,end,stop,progress)
    @staticmethod
    def run_book(book,s,market,end,stop=None,progress=lambda _:None):
        stop=stop or threading.Event();days=[d for d in market.dates if s['day']<d<=end];done=0
        with book.lease(s['id']) as owner:
            for i in range(0,len(days),20):
                if stop.is_set():break
                s=book.advance(s['id'],market,days[min(i+19,len(days)-1)])
                done=min(i+20,len(days));progress(f'{s["day"]} · 已模拟 {done}/{len(days)} 个交易日')
                import time
                with book.connection() as con:con.execute('UPDATE leases SET expires=? WHERE account=? AND owner=?',(time.time()+90,s['id'],owner))
        return s
    def snapshot(self,id):
        s=self.book.get(id);m=self.account_market(s);q=m.at(s['day']);v=ledger.value(s,q)
        obs=deepcopy(s['auto']['last_observation'] or m.observation(s['auto']['strategy'],s['day']))
        pending=s['pending'];rows=[];warnings=[]
        if pending:
            estimate=deepcopy(s)
            for p in estimate['positions'].values():p['locked']={}
            try:rows,warnings,_=ledger.target_fills(estimate,q,pending['weights'])
            except ValueError as e:warnings.append(str(e))
        sells=[r for r in rows if r['side']=='卖出'];buys=[r for r in rows if r['side']=='买入']
        title='调整仓位' if buys and sells else '按信号建仓 / 加仓' if buys else '减仓 / 退出' if sells else '继续持有' if v['market'] else '保持现金'
        if pending and warnings and not rows:title='等待可执行报价'
        code=s['auto']['strategy']
        extra='所有趋势条件失效时退出至现金。' if code in MODES else ('股票均转弱时仍保留'+str(int(model.spec(code)['both_short_stock']*100))+'%股票预算。')
        try:nextday=m.next_day(s['day'])
        except ValueError:nextday=None
        conditions=DESCRIPTIONS[code]+' '+extra+' 每次收盘重新确认；已确认的方案遇停牌顺延至可执行日。'
        return dict(state=s,market=m,value=v,observation=obs,rows=rows,warnings=warnings,title=title,next=nextday,
                    metrics=metrics(s['curve'],s['initial']),conditions=conditions)
    def compare(self,start,end,capital,stop=None,progress=lambda _:None):
        m=self.market;m.at(start);m.at(end)
        if start<'2013-01-01' or end<=start:raise ValueError('历史比较从2013年起，结束日期须晚于开始日期。')
        eligible=[code for code in ORDER if start>=model.spec(code)['anchor']]
        skipped=[dict(code=code,name=TITLES[code],reason='需银行ETF完整历史，最早2017-08-03') for code in ORDER if code not in eligible]
        out=[];stop=stop or threading.Event()
        with tempfile.TemporaryDirectory(prefix='compare_',dir=self.folder) as tmp:
            b=SuiteBook(Path(tmp))
            for i,code in enumerate(eligible):
                if stop.is_set():break
                progress(f'策略 {i+1}/{len(eligible)} · {TITLES[code]}')
                s=self.create('策略比较',capital,start,code,m,b)
                s=self.run_book(b,s,m,end,stop,lambda p:progress(f'策略 {i+1}/{len(eligible)} · {code} · {p}'))
                if s['day']!=end:break
                events=b.events(s['id']);fills=[e for e in events if e['kind']=='策略成交']
                out.append(dict(code=code,name=TITLES[code],**metrics(s['curve'],s['initial']),fees=s['fees'],fills=len(fills),curve=s['curve']))
        result=dict(engine=ENGINE,market_hash=m.hash,start=start,end=end,capital=float(capital),completed=len(out)==len(eligible),rows=out,skipped=skipped,eligible=len(eligible))
        if result['completed']:write_json(self.folder/'最近策略比较.json',result)
        return result
    def update_market(self,id=None,progress=lambda _:None,data=None):
        new=self.store_market(model.refresh(progress) if data is None else data)
        if new.latest<self.market.latest:raise ValueError('新数据结束日期更早，继续保留当前行情。')
        self.settings['market']=new.hash;self.market=new;self.save_settings();note='行情已更新至 '+new.latest
        if id:
            s=self.book.get(id);old=self.account_market(s)
            if not compatible(old,new):return note+'。发现历史数据修订，此账户继续使用原快照；新建账户可使用新数据。'
            if old.hash!=new.hash:
                with self.book.lease(id):
                    with self.book.connection() as con:
                        s=self.book.get(id,con);s['simulator']['market']=new.hash;s['pending']=None
                        s['auto'].update(evaluated=None,last_observation=None)
                        self.book.event(con,s,'更新配套行情',dict(previous=old.hash,current=new.hash,end=new.latest));self.book.save(con,s)
                    self.book.advance(id,new,s['day'])
        return note+'。已完成的模拟历史保留。'
    def report(self,id):
        z=self.snapshot(id);s=z['state'];v=z['value'];o=z['observation'];m=z['market']
        lines=[f'# {s["name"]} · 模拟交易方案',f'生成时间：{datetime.now():%Y-%m-%d %H:%M:%S}',
            f'账户收盘日期：{s["day"]}；所用行情截至：{m.latest}；策略：{s["auto"]["strategy"]} {TITLES[s["auto"]["strategy"]]}',
            '此为历史行情驱动的规则建议。不是实时价格、个股荐股或收益保证；未接入实盘订单。',
            f'\n总资产 {v["equity"]:,.2f} 元；现金 {v["cash"]:,.2f} 元；累计收益 {v["return_"]:+.2%}；最大回撤 {z["metrics"]["max_drawdown"]:.2%}；累计佣金 {v["fees"]:,.2f} 元。',
            '\n## 下一步方案',z['title'],o.get('action',''),
            '以下份数以账户当天收盘价估算，已计费用与整手限制；下一可执行日开盘重新计算，最终成交可能不同。']
        lines+=['','|资产|当前份数|目标仓位|估算操作|','|---|---:|---:|---|']
        by={r['symbol']:r for r in z['rows']}
        for c in CODES:
            r=by.get(c);action=f'{r["side"]} {r["qty"]:,} 份' if r else '持有' if s['positions'][c]['qty'] else '观望'
            lines.append(f'|{NAMES[c]} {c[2:]}|{s["positions"][c]["qty"]:,}|{o["weights"][c]:.1%}|{action}|')
        lines+=['',f'目标现金：{max(0,1-sum(o["weights"].values())):.1%}',
            '\n## 信号依据',o['reason'],'\n## 调整与退出条件',z['conditions'],
            '\n## 模拟口径',RULE_NOTE,'股票ETF当日买入次一交易日可卖；黄金与国债ETF允许当日卖出。分红和份额折算沿用原账本规则。',
            '未建模盘口深度、排队成交、涨跌停无法成交及实际券商费率差异，资金规模越大，日线模拟与真实执行偏差可能越大。',
            '默认策略用于演练，不按历史最高收益自动选为未来最佳方案。比较页的成绩取决于所选区间。',
            '交易规则参考：[上交所ETF常见问题](https://www.sse.com.cn/assortment/fund/etf/question/)',
            '\n## 可追溯信息',f'引擎：{ENGINE}；行情SHA256：{m.hash}',f'本机账户目录：{self.folder}']
        lines+=['\n提示：'+x for x in z['warnings']]
        return '\n\n'.join(lines[:8])+'\n'+'\n'.join(lines[8:])
    def export(self,id,dest):
        dest=Path(dest);dest.mkdir(parents=True,exist_ok=True);z=self.snapshot(id);backup=self.book.export(id)
        (dest/'模拟账户与交易方案.md').write_text(self.report(id),encoding='utf8')
        with (dest/'逐笔交易.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.writer(f);w.writerow(['成交日期','信号日期','资产','方向','份数','成交价','佣金','现金变动','原因'])
            for e in backup['events']:
                if e['kind']=='策略成交':
                    d=e['data'];w.writerow([e['day'],d['signal_day'],NAMES[d['symbol']],d['side'],d['qty'],d['price'],d['fee'],d['cash_change'],d.get('reason','')])
        with (dest/'每日资产.csv').open('w',encoding='utf-8-sig',newline='') as f:
            w=csv.writer(f);w.writerow(['日期','总资产','现金','持仓市值','应收分红'])
            for r in z['state']['curve']:w.writerow([r['day'],r['equity'],r['cash'],r['market'],r['receivable']])
        with zipfile.ZipFile(dest/'账户备份_含完整行情.zip','w',zipfile.ZIP_DEFLATED) as arc:
            for name,obj in [('账户.json',backup),('行情.json',z['market'].data),('版本.json',dict(engine=ENGINE,version=VERSION))]:
                arc.writestr(name,json.dumps(obj,ensure_ascii=False,allow_nan=False))
        return str(dest)
    def import_backup(self,path):
        with zipfile.ZipFile(path) as arc:
            if set(arc.namelist())!={'账户.json','行情.json','版本.json'} or any(x.file_size>100_000_000 for x in arc.infolist()):raise ValueError('请选择本软件导出的完整账户备份')
            version=json.loads(arc.read('版本.json'))
            if version.get('engine')!=ENGINE:raise ValueError('此备份需要对应版本的软件')
            payload=json.loads(arc.read('账户.json'));m=self.store_market(json.loads(arc.read('行情.json')))
            if payload['account'].get('simulator')!={'engine':ENGINE,'market':m.hash}:raise ValueError('账户与行情快照不匹配')
            s=self.book.import_copy(payload)
        return self.book.advance(s['id'],m,s['day'])

    def export_history(self,dest):
        dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
        counts={}
        for c in CODES:
            rows=[r for r in self.market.bars[c] if r['date']>='2013-01-01'];counts[c]=len(rows)
            with (dest/(NAMES[c]+'_'+c[2:]+'_2013起日线.csv')).open('w',encoding='utf-8-sig',newline='') as f:
                w=csv.writer(f);w.writerow(['日期','开盘','最高','最低','收盘','成交手数','成交金额元'])
                for r in rows:w.writerow([r[k] for k in ['date','open','high','low','close','volume_lots','amount_cny']])
        write_json(dest/'历史行情说明.json',dict(start='2013-01-01',end=self.market.latest,market_hash=self.market.hash,
            counts=counts,first_dates={c:self.market.bars[c][0]['date'] for c in CODES},note='未复权真实日线，按上市起点记录；指标另计折算与分红调整。30分钟盘中记录仅从实际采集开始。'))
        return str(dest)
