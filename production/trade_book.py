"""Persistent paper accounts: atomic previews, next-open strategy orders, daily settlement."""
from pathlib import Path
from copy import deepcopy
from contextlib import contextmanager
from datetime import date
from decimal import Decimal,ROUND_HALF_UP,ROUND_FLOOR,ROUND_CEILING
from bisect import bisect_right
import os,json,sqlite3,uuid,math
import bank_model as research

CODES=research.CODES;NAMES=dict(zip(CODES,research.NAMES));T0={'sh518880','sh511010'}
VERSION='1.1';SCHEMA='dualauto.account.v1';RATE=.0003;SLIP=.0002
digest=research.digest
def home():return research.home()
def rounded(v):return float(Decimal(str(v)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP))
def number(v,label,maximum=1e10):
    try:n=float(str(v).replace(',',''))
    except (ValueError,TypeError):raise ValueError(label+'须为数字')
    if not math.isfinite(n) or not 0<=n<=maximum:raise ValueError(label+'超出有效范围')
    return n
def quantity(v):
    n=number(v,'份额',1e12)
    if not n.is_integer():raise ValueError('份额须为整数')
    return int(n)
def available(s,c):return s['positions'][c]['qty']-sum(v for d,v in s['positions'][c]['locked'].items() if d>=s['day'])
def receipt(c,side,qty,reference):
    price=round(reference*(1+SLIP if side=='买入' else 1-SLIP),8);gross=rounded(price*qty);fee=rounded(max(5,gross*RATE))
    return dict(symbol=c,name=NAMES[c],side=side,qty=qty,price=price,reference=reference,gross=gross,fee=fee,
                cash_change=-(gross+fee) if side=='买入' else gross-fee)

class Market:
    def __init__(self,data=None,folder=None):
        self.data=research.validate_data(data) if data is not None else research.load_data(folder or home())
        self.inputs=research.inputs(self.data);self.hash=digest(self.data)
        latest=min(arr[-1]['date'] for c,arr in self.inputs.bars.items())
        self.dates=sorted({b['date'] for arr in self.inputs.bars.values() for b in arr if '2012-01-04'<=b['date']<=min(latest,research.cutoff())})
        self.latest=self.dates[-1];self.bars=self.inputs.bars;self.look={c:{b['date']:b for b in self.bars[c]} for c in CODES}
        self.bar_dates={c:[b['date'] for b in self.bars[c]] for c in CODES};self.signals=research.Signals(self)
    def at(self,day,opening=False):
        if day not in self.dates:raise ValueError('该日期没有完整的市场交易日，请选择已有交易日')
        prices={};dates={}
        for c in CODES:
            bars=self.bars[c];i=bisect_right(self.bar_dates[c],day)-1
            if i<0:prices[c]=None;dates[c]=None;continue
            b=bars[i]
            prices[c]=b['open' if opening and b['date']==day else 'close'];dates[c]=b['date']
        return dict(day=day,prices=prices,dates=dates,market_hash=self.hash)
    def next_day(self,day):
        ix=bisect_right(self.dates,day)
        if ix>=len(self.dates):raise ValueError('已到最后一个已知收盘日。可联网更新，或新建历史练习账户。')
        return self.dates[ix]
    def observation(self,code,day):return self.signals.observation(code,day)

def value(s,quote):
    rows=[];market=0.;floating=0.
    for c,p in s['positions'].items():
        price=quote['prices'][c]
        if p['qty'] and price is None:raise ValueError(NAMES[c]+'尚未上市，账户却有持仓')
        mv=p['qty']*price if price is not None else 0.;unreal=mv-p['cost'];market+=mv;floating+=unreal
        rows.append(dict(symbol=c,name=NAMES[c],qty=p['qty'],available=available(s,c),cost=p['cost'],average=p['cost']/p['qty'] if p['qty'] else 0.,
                         price=price,quote_date=quote['dates'][c],market=mv,pnl=unreal))
    receivable=sum(s['receivables'].values());equity=s['cash']+receivable+market
    return dict(equity=equity,cash=s['cash'],market=market,receivable=receivable,pnl=equity-s['initial'],
                return_=equity/s['initial']-1,realized=s['realized'],unrealized=floating,dividends=s['dividends'],fees=s['fees'],rows=rows)

def validate(s):
    if s.get('schema')!=SCHEMA or set(s.get('positions',{}))!=set(CODES):raise ValueError('账户格式不正确')
    date.fromisoformat(s['day']);date.fromisoformat(s['start'])
    if s['day']<s['start'] or not 1000<=number(s['initial'],'本金',1e9):raise ValueError('本金或账户日期错误')
    number(s['cash'],'现金');number(s['fees'],'累计费用');number(s['dividends'],'累计分红')
    if not math.isfinite(s['realized']):raise ValueError('已实现盈亏无效')
    for c,p in s['positions'].items():
        quantity(p['qty']);number(p['cost'],'持仓成本')
        if p['qty']==0 and abs(p['cost'])>1e-6:raise ValueError('空持仓不应有剩余成本')
        for d,q in p['locked'].items():date.fromisoformat(d);quantity(q)
        if not 0<=available(s,c)<=p['qty']:raise ValueError('可卖份额错误')
    for v in s['receivables'].values():number(v,'应收分红')
    # With no external deposits, asset cost plus cash reconciles to realized profit and dividends.
    basis=s['cash']+sum(s['receivables'].values())+sum(p['cost'] for p in s['positions'].values())
    if abs(basis-s['initial']-s['realized']-s['dividends'])>.05:raise ValueError('账户成本与现金不能核对，已停止写入')
    return s

def snapshot(s,quote):
    v=value(s,quote);row=dict(day=s['day'],equity=v['equity'],cash=s['cash'],pnl=v['pnl'],market=v['market'],receivable=v['receivable'])
    if s['curve'] and s['curve'][-1]['day']==s['day']:s['curve'][-1]=row
    else:s['curve'].append(row)

def apply_fill(s,z):
    c=z['symbol'];p=s['positions'][c];qty=z['qty']
    if z['side']=='买入':
        if qty<=0 or qty%100:raise ValueError('买入须为100份的整数倍')
        if -z['cash_change']>s['cash']+1e-7:raise ValueError('可用现金不足，已为佣金预留资金')
        p['qty']+=qty;p['cost']-=z['cash_change']
        if c not in T0:p['locked'][s['day']]=p['locked'].get(s['day'],0)+qty
        realized=0.
    else:
        if qty<=0 or qty>available(s,c):raise ValueError('可卖份额不足；股票ETF当日买入次一交易日可卖')
        if qty%100 and qty!=p['qty']:raise ValueError('零碎份额须与剩余持仓一并卖出')
        if z['cash_change']<=0:raise ValueError('卖出金额不足最低佣金')
        cost=p['cost']*qty/p['qty'];p['qty']-=qty;p['cost']-=cost
        if not p['qty']:p['cost']=0.
        realized=z['cash_change']-cost;s['realized']+=realized
    s['cash']=rounded(s['cash']+z['cash_change']);s['fees']=rounded(s['fees']+z['fee'])
    z['realized_pnl']=realized;z['day']=s['day'];return z

def target_fills(s,quote,weights):
    v=value(s,quote);rows=[];warnings=[];blocked=False
    if set(weights)!=set(CODES) or any(not math.isfinite(w) or w<0 for w in weights.values()) or sum(weights.values())>1.000001:raise ValueError('目标权重无效')
    for c in CODES:
        if weights[c] and quote['prices'][c] is None:raise ValueError(NAMES[c]+'尚未上市，不能配置')
    target={c:int(v['equity']*weights[c]/quote['prices'][c]//100)*100 if weights[c] else 0 for c in CODES}
    for c in CODES:
        if (s['positions'][c]['qty'] or target[c]) and quote['dates'][c]!=s['day']:raise ValueError(NAMES[c]+'缺少本日可执行报价')
    for c in CODES:
        excess=max(0,s['positions'][c]['qty']-target[c]);qty=min(excess,available(s,c))
        if qty!=s['positions'][c]['qty']:qty=qty//100*100
        if qty and receipt(c,'卖出',qty,quote['prices'][c])['cash_change']>0:rows.append(apply_fill(s,receipt(c,'卖出',qty,quote['prices'][c])))
        if excess>qty and available(s,c)<excess:blocked=True;warnings.append(NAMES[c]+'部分份额尚不可卖，保留原持仓')
    for c in CODES:
        need=max(0,target[c]-s['positions'][c]['qty'])//100*100
        if not need:continue
        price=quote['prices'][c]*(1+SLIP)
        qty=min(need,max(0,int(min((s['cash']-5)/price,s['cash']/(price*(1+RATE)))//100)*100))
        while qty and -receipt(c,'买入',qty,quote['prices'][c])['cash_change']>s['cash']+1e-8:qty-=100
        if qty:rows.append(apply_fill(s,receipt(c,'买入',qty,quote['prices'][c])))
        if qty<need:warnings.append(NAMES[c]+'已按现金、费用与整手限制调整数量')
    return rows,warnings,blocked

class Book:
    def __init__(self,folder=None):
        self.folder=Path(folder or home());self.folder.mkdir(parents=True,exist_ok=True);self.path=self.folder/'模拟交易账户.sqlite3'
        with self.connection() as con:
            con.execute('CREATE TABLE IF NOT EXISTS accounts(id TEXT PRIMARY KEY,name TEXT,revision INTEGER,payload TEXT)')
            con.execute('CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,account TEXT,day TEXT,kind TEXT,payload TEXT)')
    @contextmanager
    def connection(self):
        con=sqlite3.connect(self.path,timeout=10)
        try:
            con.execute('BEGIN IMMEDIATE');yield con;con.commit()
        except Exception:con.rollback();raise
        finally:con.close()
    def list(self):
        with self.connection() as con:return [dict(id=x[0],name=x[1]) for x in con.execute('SELECT id,name FROM accounts ORDER BY rowid')]
    def get(self,id,con=None):
        if con is None:
            with self.connection() as cx:return self.get(id,cx)
        row=con.execute('SELECT payload FROM accounts WHERE id=?',(id,)).fetchone()
        if not row:raise ValueError('未找到模拟账户')
        return validate(json.loads(row[0]))
    def event(self,con,s,kind,payload,id=None):
        con.execute('INSERT INTO events VALUES (?,?,?,?,?)',(id or uuid.uuid4().hex,s['id'],s['day'],kind,json.dumps(payload,ensure_ascii=False,allow_nan=False)))
    def save(self,con,s):
        validate(s);s['revision']+=1
        con.execute('UPDATE accounts SET name=?,revision=?,payload=? WHERE id=?',(s['name'],s['revision'],json.dumps(s,ensure_ascii=False,allow_nan=False),s['id']))
    def create(self,name,capital,day,market):
        name=str(name).strip()
        if not name or len(name)>40:raise ValueError('账户名称为1至40字')
        capital=rounded(number(capital,'本金',1e9))
        if capital<1000:raise ValueError('模拟本金至少1000元')
        quote=market.at(day)
        s=dict(schema=SCHEMA,id=uuid.uuid4().hex,name=name,start=day,day=day,initial=capital,cash=capital,
            positions={c:dict(qty=0,cost=0.,locked={}) for c in CODES},realized=0.,dividends=0.,fees=0.,
            receivables={},entitlements={},processed=[],curve=[],revision=0,pending=None,last_target=None)
        snapshot(s,quote);validate(s)
        with self.connection() as con:
            con.execute('INSERT INTO accounts VALUES (?,?,?,?)',(s['id'],name,0,json.dumps(s,ensure_ascii=False)))
            self.event(con,s,'新建账户',dict(capital=capital,start=day))
        return s
    def preview(self,id,market,c,side,qty):
        s=self.get(id)
        if s['pending']:raise ValueError('已有待执行策略单，请先撤销或推进交易日')
        if c not in CODES or side not in ['买入','卖出']:raise ValueError('交易资产或方向不支持')
        q=market.at(s['day']);qty=quantity(qty)
        if q['dates'][c]!=s['day']:raise ValueError('该ETF在账户日期没有报价，不能模拟成交')
        if s['day'] in research.engine.TRADE_BLOCKS.get(c,set()):raise ValueError('该日期存在停牌或非正常开盘，演练跳过成交')
        z=apply_fill(s,receipt(c,side,qty,q['prices'][c]));validate(s)
        plan=dict(kind='manual',account=id,revision=s['revision'],market_hash=market.hash,day=s['day'],request=[c,side,qty],rows=[z],after=value(s,q))
        plan['id']=digest(plan);return plan
    def commit(self,plan,market):
        with self.connection() as con:
            if plan.get('kind')!='manual' or digest({k:v for k,v in plan.items() if k!='id'})!=plan.get('id'):raise ValueError('订单预览已改变，请重新生成')
            s=self.get(plan['account'],con)
            if s['revision']!=plan['revision'] or market.hash!=plan['market_hash']:raise ValueError('账户或行情已改变，请重新预览')
            if s['pending']:raise ValueError('策略委托尚未处理')
            c,side,qty=plan['request'];q=market.at(s['day'])
            if c not in CODES or side not in ['买入','卖出'] or q['dates'][c]!=s['day']:raise ValueError('订单资料无效')
            if s['day'] in research.engine.TRADE_BLOCKS.get(c,set()):raise ValueError('该日期不支持正常开盘演练，请推进交易日')
            z=apply_fill(s,receipt(c,side,quantity(qty),q['prices'][c]));validate(s)
            expect=dict(kind='manual',account=s['id'],revision=s['revision'],market_hash=market.hash,day=s['day'],request=[c,side,qty],rows=[z],after=value(s,q))
            if digest(expect)!=plan.get('id'):raise ValueError('订单预览校验失败，未成交')
            s['last_target']=None;snapshot(s,q);self.event(con,s,'模拟成交',z,plan['id']);self.save(con,s)
        return s
    def strategy_preview(self,id,market,observation):
        s=self.get(id)
        if s['pending']:raise ValueError('已有策略委托等待下一交易日')
        if observation['asof']!=s['day'] or digest({k:v for k,v in observation.items() if k!='id'})!=observation.get('id'):raise ValueError('策略观察日期或校验不匹配，请重新分析')
        weights={a['symbol']:a['weight'] for a in observation['allocation']}
        if s['last_target']==weights:raise ValueError('策略目标未变，本轮继续持有，不按每日价格漂移重复调仓')
        rows,warnings,blocked=target_fills(deepcopy(s),market.at(s['day']),weights)
        p=dict(kind='strategy',account=id,revision=s['revision'],market_hash=market.hash,day=s['day'],weights=weights,
               observation_id=observation['id'],reasons=observation['reasons'],rows=rows,warnings=warnings)
        p['id']=digest(p);return p
    def queue_strategy(self,plan,market):
        with self.connection() as con:
            s=self.get(plan['account'],con)
            if plan.get('kind')!='strategy' or plan.get('day')!=s['day']:raise ValueError('策略单日期或类型不匹配')
            if s['pending'] or s['revision']!=plan['revision'] or market.hash!=plan['market_hash']:raise ValueError('账户或行情已变化，请重新生成策略单')
            if digest({k:v for k,v in plan.items() if k!='id'})!=plan.get('id'):raise ValueError('策略单校验失败')
            target_fills(deepcopy(s),market.at(s['day']),plan['weights'])
            s['pending']=deepcopy(plan);self.event(con,s,'策略委托',dict(weights=plan['weights'],signal_day=s['day'],reasons=plan['reasons']),plan['id']);self.save(con,s)
        return s
    def cancel(self,id):
        with self.connection() as con:
            s=self.get(id,con)
            if not s['pending']:raise ValueError('没有待撤销的模拟委托')
            self.event(con,s,'撤销策略委托',dict(order_id=s['pending']['id']));s['pending']=None;self.save(con,s)
        return s
    def evaluate(self,con,s,market):pass
    def advance(self,id,market,to,allow_stale=False):
        if getattr(market,'provisional',False):raise ValueError('盘中临时行情不能用于历史成交或结算')
        quote=market.at(to)
        with self.connection() as con:
            s=self.get(id,con)
            if to<s['day']:
                if allow_stale:return s
                raise ValueError('持续账户不能倒退日期。要重练请新建账户。')
            self.evaluate(con,s,market)
            for day in [d for d in market.dates if s['day']<d<=to]:
                previous=s['day']
                # Register at the close after all user trades on the old day.
                for c in CODES:
                    for event in market.inputs.actions[c]['dividends']:
                        if event['record']==previous:s['entitlements'][c+'_'+event['ex']]=s['positions'][c]['qty']
                events=[]
                for c in CODES:
                    for d,x in market.inputs.splits[c].items():
                        if previous<d<=day:events.append((d,0,c,'split',x))
                    for x in market.inputs.actions[c]['dividends']:
                        if previous<x['ex']<=day:events.append((x['ex'],1,c,'ex',x))
                        if previous<x['pay']<=day:events.append((x['pay'],2,c,'pay',x))
                s['day']=day
                for d,_,c,kind,x in sorted(events,key=lambda x:(x[0],x[1],x[2])):
                    key=c+'_'+kind+'_'+d
                    if key in s['processed']:continue
                    s['processed'].append(key);pos=s['positions'][c]
                    if kind=='split':
                        mode=ROUND_CEILING if x['rounding']=='ceil' else ROUND_FLOOR
                        conv=lambda n:int((Decimal(n)*Decimal(str(x['ratio']))).to_integral_value(rounding=mode))
                        old=pos['qty'];pos['qty']=conv(old);pos['locked']={d:conv(v) for d,v in pos['locked'].items()}
                        if old:self.event(con,s,'份额折算',dict(symbol=c,ratio=x['ratio'],before=old,after=pos['qty']))
                    elif kind=='ex':
                        entitlement=s['entitlements'].pop(c+'_'+x['ex'],0);amount=rounded(entitlement*x['cash_per_share'])
                        if amount:s['receivables'][c+'_'+x['ex']]=amount;s['dividends']+=amount;self.event(con,s,'应收分红',dict(symbol=c,amount=amount,pay=x['pay']))
                    else:
                        amount=s['receivables'].pop(c+'_'+x['ex'],0)
                        if amount:s['cash']=rounded(s['cash']+amount);self.event(con,s,'分红到账',dict(symbol=c,amount=amount))
                for pos in s['positions'].values():pos['locked']={d:v for d,v in pos['locked'].items() if d>=day}
                if s['pending']:
                    order=s['pending'];opening=market.at(day,True)
                    relevant=[c for c in CODES if order['weights'][c]>0 or s['positions'][c]['qty']>0]
                    tradable=all(opening['dates'][c]==day and day not in research.engine.TRADE_BLOCKS.get(c,set()) for c in relevant)
                    if tradable:
                        rows,warnings,blocked=target_fills(s,opening,order['weights'])
                        for z in rows:
                            z['signal_day']=order['day'];z['reason']='；'.join(order.get('reasons',[]));z['features']=order.get('evidence',{}).get('features',{});z['execution']='按上次收盘确认的目标，在本日开盘模拟执行';self.event(con,s,'策略成交',z)
                        self.event(con,s,'策略单完成',dict(order_id=order['id'],warnings=warnings,filled=len(rows)))
                        s['last_target']=None if blocked else order['weights'];s['pending']=None
                snapshot(s,market.at(day));validate(s)
                self.evaluate(con,s,market)
            snapshot(s,quote);self.save(con,s)
        return s
    def events(self,id):
        with self.connection() as con:return [dict(id=r[0],day=r[1],kind=r[2],data=json.loads(r[3])) for r in con.execute('SELECT id,day,kind,payload FROM events WHERE account=? ORDER BY rowid DESC',(id,))]
    def export(self,id):
        with self.connection() as con:
            state=self.get(id,con);rows=[dict(id=r[0],day=r[1],kind=r[2],data=json.loads(r[3])) for r in con.execute('SELECT id,day,kind,payload FROM events WHERE account=? ORDER BY rowid',(id,))]
        payload=dict(schema='paperdesk.backup.v1',account=state,events=rows);payload['sha256']=digest(payload);return payload
    def import_copy(self,payload):
        if payload.get('schema')!='paperdesk.backup.v1' or digest({k:v for k,v in payload.items() if k!='sha256'})!=payload.get('sha256'):raise ValueError('账户备份校验失败')
        s=deepcopy(validate(payload['account']));s['id']=uuid.uuid4().hex;s['name']=(s['name'][:30]+'（导入副本）');s['revision']=0;s['pending']=None
        with self.connection() as con:
            con.execute('INSERT INTO accounts VALUES (?,?,?,?)',(s['id'],s['name'],0,json.dumps(s,ensure_ascii=False)))
            for z in payload['events']:self.event(con,{**s,'day':z['day']},z['kind'],z['data'])
            self.event(con,s,'导入副本',dict(note='保留原始历史，待执行委托不带入新账户'))
        return s
