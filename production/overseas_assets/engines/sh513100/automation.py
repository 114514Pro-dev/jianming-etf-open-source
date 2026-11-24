"""One close -> one decision -> next available open, persisted per account."""
from copy import deepcopy
from contextlib import contextmanager
import time,uuid,json,threading
import bank_model as model
import trade_book as b

class AutoBook(b.Book):
    def __init__(self,folder=None):
        super().__init__(folder)
        with self.connection() as c:c.execute('CREATE TABLE IF NOT EXISTS leases(account TEXT PRIMARY KEY, owner TEXT, expires REAL)')
    def create(self,name,capital,day,market,strategy=model.DEFAULT):
        model.spec(strategy);name=str(name).strip();capital=b.rounded(b.number(capital,'本金',1e9));q=market.at(day)
        if day<model.spec(strategy)['anchor']:raise ValueError('此方案最早开始日为'+model.spec(strategy)['anchor'])
        if not name or len(name)>40:raise ValueError('账户名称为1至40字')
        if capital<1000:raise ValueError('模拟本金至少1000元')
        s=dict(schema=b.SCHEMA,id=uuid.uuid4().hex,name=name,start=day,day=day,initial=capital,cash=capital,
            positions={c:dict(qty=0,cost=0.,locked={}) for c in b.CODES},realized=0.,dividends=0.,fees=0.,
            receivables={},entitlements={},processed=[],curve=[],revision=0,pending=None,last_target=None,
            auto=dict(strategy=strategy,spec_hash=model.digest(model.spec(strategy)),evaluated=None,entered=None,blocked=False,watch=False,last_observation=None))
        b.snapshot(s,q);b.validate(s)
        with self.connection() as con:
            con.execute('INSERT INTO accounts VALUES (?,?,?,?)',(s['id'],name,0,json.dumps(s,ensure_ascii=False)))
            self.event(con,s,'新建自动账户',dict(capital=capital,start=day,strategy=model.LABELS[strategy]))
        return s
    def get(self,id,con=None):
        s=super().get(id,con);a=s.get('auto',{})
        if a.get('strategy') not in model.FILES or a.get('spec_hash')!=model.digest(model.spec(a['strategy'])):raise ValueError('自动策略版本不匹配，已停止运行')
        if a.get('entered') and a['entered']>s['day']:raise ValueError('持有开始日期无效')
        if a.get('evaluated') and a['evaluated']>s['day']:raise ValueError('信号日期晚于账户日期')
        return s
    def preview(self,*args,**kw):raise ValueError('自动账户由固定策略管理；手动练习请使用ETF模拟交易App')
    def commit(self,*args,**kw):raise ValueError('自动账户不接受手动成交')
    def strategy_preview(self,*args,**kw):raise ValueError('点击开始自动模拟，系统逐日生成委托')
    def queue_strategy(self,*args,**kw):raise ValueError('系统自动生成经过收盘确认的委托')
    def evaluate(self,con,s,market):
        a=s['auto'];day=s['day']
        if a['evaluated']==day:return
        obs=market.observation(a['strategy'],day);weights=obs['weights']
        if s['pending'] and s['pending']['weights']!=weights:
            self.event(con,s,'更新未成交目标',dict(old_signal=s['pending']['day'],old_weights=s['pending']['weights'],new_weights=weights,reason='尚未成交的目标随新收盘判断更新'))
            s['pending']=None
        if s['pending']:obs['action']='已有相同目标等待可执行开盘，不重复委托'
        elif s['last_target']!=weights:
            plan=dict(kind='strategy',account=s['id'],revision=s['revision'],market_hash=market.hash,day=day,weights=weights,
                      observation_id=model.digest(obs),reasons=[obs['reason']],evidence=deepcopy(obs))
            plan['id']=model.digest(plan);s['pending']=plan;obs['action']='已生成下一可执行交易日的模拟目标'
            self.event(con,s,'自动策略委托',dict(weights=weights,signal_day=day,reason=obs['reason'],features=obs['features'],state=obs['state']),plan['id'])
        else:obs['action']='组合目标未改变，保留持仓，不因价格漂移每日调仓'
        a['last_observation']=obs;a['evaluated']=day
        self.event(con,s,'收盘分析',obs,model.digest(dict(account=s['id'],day=day,kind='close')))
    def set_watch(self,id,enabled):
        with self.connection() as con:
            target=self.get(id,con)
            if enabled:
                for row in con.execute('SELECT id FROM accounts').fetchall():
                    if row[0]==id:continue
                    s=self.get(row[0],con)
                    if s['auto']['watch']:
                        s['auto']['watch']=False;self.event(con,s,'停止收盘跟踪',dict(reason='已改为跟踪另一个模拟账户'));self.save(con,s)
            target['auto']['watch']=bool(enabled);self.event(con,target,'开启收盘跟踪' if enabled else '停止收盘跟踪',dict(note='软件运行时，16:10后检查已完成日线'));self.save(con,target)
        return target
    def watched(self):
        for a in self.list():
            s=self.get(a['id'])
            if s['auto']['watch']:return s
        return None
    @contextmanager
    def lease(self,id):
        owner=uuid.uuid4().hex
        with self.connection() as con:
            prior=con.execute('SELECT owner,expires FROM leases WHERE account=?',(id,)).fetchone()
            if prior and prior[1]>time.time():raise ValueError('该账户正在另一个窗口运行，请等待完成；异常退出后最多90秒恢复')
            con.execute('INSERT OR REPLACE INTO leases VALUES (?,?,?)',(id,owner,time.time()+90))
        try:yield owner
        finally:
            with self.connection() as con:con.execute('DELETE FROM leases WHERE account=? AND owner=?',(id,owner))
    def run_to(self,id,market,end,stop=None,progress=lambda _:None):
        market.at(end);initial=self.get(id)
        if end<initial['day']:raise ValueError('目标日期早于账户日期；重练请新建账户')
        stop=stop or threading.Event()
        with self.lease(id) as owner:
            dates=[d for d in market.dates if initial['day']<=d<=end];completed=0
            for i,day in enumerate(dates):
                if stop.is_set():break
                s=self.advance(id,market,day,allow_stale=True);completed+=1
                if i%20==0:
                    with self.connection() as con:con.execute('UPDATE leases SET expires=? WHERE account=? AND owner=?',(time.time()+90,id,owner))
                    progress(dict(day=s['day'],done=i+1,total=len(dates),equity=b.value(s,market.at(s['day']))['equity']))
            s=self.get(id)
            with self.connection() as con:
                self.event(con,s,'自动模拟暂停' if stop.is_set() else '自动模拟完成',dict(requested=end,actual=s['day'],steps=completed,note='已完成交易保留；期末不强制清仓'))
        return dict(account=id,state=s,stopped=stop.is_set(),steps=completed)
    def export(self,id):
        p=super().export(id);p['schema']='dualauto.backup.v1';p.pop('sha256');p['sha256']=b.digest(p);return p
    def import_copy(self,payload):
        if payload.get('schema')!='dualauto.backup.v1' or b.digest({k:v for k,v in payload.items() if k!='sha256'})!=payload.get('sha256'):raise ValueError('自动模拟账户备份校验失败')
        s=deepcopy(b.validate(payload['account']));a=s['auto']
        if a['spec_hash']!=model.digest(model.spec(a['strategy'])):raise ValueError('备份策略版本不匹配')
        s['id']=uuid.uuid4().hex;s['name']=s['name'][:30]+'（导入副本）';s['revision']=0;s['pending']=None;s['last_target']=None;a['watch']=False;a['evaluated']=None;a['last_observation']=None
        with self.connection() as con:
            con.execute('INSERT INTO accounts VALUES (?,?,?,?)',(s['id'],s['name'],0,json.dumps(s,ensure_ascii=False)))
            # Imported close events need fresh IDs because this account can re-evaluate its last date.
            for e in payload['events']:self.event(con,{**s,'day':e['day']},e['kind'],e['data'])
            self.event(con,s,'导入副本',dict(note='原账户保留；每日跟踪关闭，旧委托不自动执行'))
        return s

def historical_scenarios(market,day):
    import etf_forecast as fc
    out=[]
    for code in b.CODES:
        data={**market.data['bank' if code=='sh512800' else 'chi'],'attack_symbol':code};series=fc.total_return_series(data,day)
        if len(series)<240:out.append(dict(symbol=code,scenarios=[],note='不足240日，暂不计算历史情景'));continue
        feats=fc.states(series);rows=[]
        for h in [5,20,60]:
            z=fc.distribution(series,feats,len(series)-1,h)
            rows.append({k:v for k,v in z.items() if k!='sample_origins'} if z else dict(horizon=h,n=0))
        out.append(dict(symbol=code,scenarios=rows,note='单只ETF的历史含息上涨比例；不参与交易规则，不代表未来组合盈利概率'))
    return out
