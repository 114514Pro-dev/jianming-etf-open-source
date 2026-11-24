from __future__ import annotations
import copy, hashlib, json, sqlite3, uuid, re
from pathlib import Path
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR
from realtime_paper_pnl_history import update_and_read_history, read_history
from realtime_paper_notifications import PaperNotifications

TZ = timezone(timedelta(hours=8))
CENT, TICK = Decimal('.01'), Decimal('.001')
RULE_VERSION = 'paper-cn-etf-2026-v1'
STRATEGIES = frozenset(('D0', 'D0I-BOND-WW'))
RESPONSE_CONTEXT_FIELDS = frozenset(('source_status','reason','last_observed','daily_origin','daily_asof','historical_seed','observation_state'))
RULES = {s: {'lot': 100, 'tick': '.001', 'settlement': t, 'limit_pct': p}
         for s,t,p in [('sz159915','T1','.20'),('sh512800','T1','.10'),
                       ('sh518880','T0','.10'),('sh511010','T0','.10')]}
MODEL_NOTICE = ('仅为独立纸上现金账户。需委托后同券同源两次新鲜且递增的成交量、成交额证据。'
 '合格时按报价加滑点整单估计成交；无盘口，不代表真实排队、深度或流动性，不生成部分成交。'
 '来源缺少交易状态时仅记未核实；费用及滑点均为可见模拟假设。')

def D(x):
    if isinstance(x,bool): raise ValueError('finite decimal required')
    try: v = Decimal(str(x))
    except (ValueError, TypeError, InvalidOperation): raise ValueError('finite decimal required') from None
    if not v.is_finite(): raise ValueError('finite decimal required')
    return v

def dt(x):
    try: v = x if isinstance(x,datetime) else datetime.fromisoformat(x.replace('Z','+00:00'))
    except (ValueError,TypeError,AttributeError): raise ValueError('invalid timestamp') from None
    if v.tzinfo is None: raise ValueError('timestamp timezone required')
    return v.astimezone(TZ)

def iso(x): return dt(x).isoformat()
def cash(x): return format(D(x).quantize(CENT,rounding=ROUND_HALF_UP),'.2f')
def px(x): return format(D(x).quantize(TICK),'.3f')
def uid(): return uuid.uuid4().hex
def digest(x): return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()

class PaperError(ValueError):
    def __init__(self,code,message):
        super().__init__(message); self.code=code; self.status_code=409 if code=='IDEMPOTENCY_CONFLICT' else 400

class TradingCalendar:
    first, last = date(2026,7,6),date(2026,12,31)
    def is_session(self,day):
        day=date.fromisoformat(day) if isinstance(day,str) else day
        if not self.first<=day<=self.last: return None
        return day.weekday()<5 and not (date(2026,9,25)<=day<=date(2026,9,27) or date(2026,10,1)<=day<=date(2026,10,7))
    def next_session(self,day):
        day=date.fromisoformat(day) if isinstance(day,str) else day
        for n in range(1,16):
            target=day+timedelta(days=n); valid=self.is_session(target)
            if valid is None: return None
            if valid: return target
        return None
    def expected_confirmed_day(self,at):
        at=dt(at); day=at.date()
        if self.is_session(day) is None: return None
        if self.is_session(day) and at.time().replace(tzinfo=None)>=time(16,10): return day
        for n in range(1,16):
            candidate=day-timedelta(days=n); valid=self.is_session(candidate)
            if valid is None: return None
            if valid: return candidate
        return None
    def segment(self,at):
        at=dt(at)
        if self.is_session(at.date()) is not True: return None
        t=at.time().replace(tzinfo=None)
        return 'AM' if time(9,30)<=t<time(11,30) else 'PM' if time(13)<=t<time(14,57) else None
    def is_continuous(self,at): return self.segment(at) is not None

class PaperLedger:
    def __init__(self,home,now=None,rules=None,calendar=None,strategy='D0'):
        if strategy not in STRATEGIES: raise ValueError('unsupported paper strategy')
        self.strategy=strategy
        self.account_id='D0-forward-paper' if strategy=='D0' else strategy+'-forward-paper'
        self.home=Path(home); self.home.mkdir(parents=True,exist_ok=True)
        self.path=self.home/'realtime-paper.sqlite3'; self.now=now or (lambda:datetime.now(TZ))
        self.rules=copy.deepcopy(rules or RULES); self.calendar=calendar or TradingCalendar()
        if self.rules!=RULES: raise ValueError('first phase instrument rules are fixed')
        self.notifications=PaperNotifications(self._db, lambda: dt(self.now()), strategy)
        db=self._db()
        try:
            db.execute('CREATE TABLE IF NOT EXISTS ledger(id INTEGER PRIMARY KEY CHECK(id=1),data TEXT NOT NULL)')
            initial={'revision':0,'account':None,'positions':{},'orders':[],'fills':[],'quotes':{},'signal':None,'plan':None,'events':[],'observations':{},'commands':{},'reset_at':iso(self.now())}
            db.execute('INSERT OR IGNORE INTO ledger VALUES(1,?)',(json.dumps(initial),))
            self.notifications.initialize(db)
        finally: db.close()
        def reset(s):
            s['observations']={}; s['reset_at']=iso(self.now())
            # Preserve explicit trusted states already stored by the prior schema.
            if 'status_watermarks' not in s:
                s['status_watermarks']={symbol:{k:q[k] for k in ('symbol','source','status','quote_at','received_at')}
                    for symbol,q in s.get('quotes',{}).items() if q.get('status') in ('halted','normal','unknown')}
        self._change('restart',{},None,reset)
    def _db(self):
        db=sqlite3.connect(str(self.path),timeout=30,isolation_level=None)
        db.execute('PRAGMA busy_timeout=30000'); db.execute('PRAGMA synchronous=FULL')
        return db
    def _change(self,op,payload,key,action,response_context=None):
        return self._transaction(op,payload,key,lambda s,db:action(s),response_context)
    def _transaction(self,op,payload,key,action,response_context=None):
        if key is not None and (not isinstance(key,str) or not 8<=len(key)<=100):
            raise PaperError('VALIDATION_ERROR','idempotency_key must have 8–100 characters')
        db=self._db()
        try:
            db.execute('BEGIN IMMEDIATE'); s=json.loads(db.execute('SELECT data FROM ledger WHERE id=1').fetchone()[0])
            self._assert_strategy(s)
            fingerprint=digest({'operation':op,'account':self.account_id,'payload':payload})
            if key in s['commands']:
                command=s['commands'][key]
                if command['fingerprint']!=fingerprint: raise PaperError('IDEMPOTENCY_CONFLICT','同一幂等键已用于不同操作或参数')
                db.rollback(); return copy.deepcopy(command['result'])
            # Context is response evidence, never part of business identity.
            # Existing keys above return their original result without consulting it.
            context={} if response_context is None else copy.deepcopy(response_context)
            if not isinstance(context,dict) or set(context)-RESPONSE_CONTEXT_FIELDS:
                raise ValueError('invalid command response context')
            before=json.dumps(s,sort_keys=True)
            was_running=(s['account'] or {}).get('running')
            extra=action(s,db) or {}
            if was_running and not s['account']['running']:
                self.notifications.account_paused(db,s['account'])
            if json.dumps(s,sort_keys=True)!=before: s['revision']+=1
            result=self._view(s); result.update(extra); result.update(context)
            result['_pnl_history']=update_and_read_history(db,result,self.calendar)
            if key is not None: s['commands'][key]={'fingerprint':fingerprint,'result':copy.deepcopy(result)}
            db.execute('UPDATE ledger SET data=? WHERE id=1',(json.dumps(s,ensure_ascii=False,allow_nan=False),)); db.commit()
            return result
        except BaseException: db.rollback(); raise
        finally: db.close()
    def _event(self,s,kind,**data): s['events'].append({'id':uid(),'type':kind,'at':iso(self.now()),**data})
    def _assert_strategy(self,s):
        if s.get('account') is not None and s['account'].get('strategy')!=self.strategy:
            raise ValueError('paper account strategy does not match its isolated ledger')
        if s.get('signal') is not None and s['signal'].get('strategy')!=self.strategy:
            raise ValueError('paper signal strategy does not match its isolated ledger')
    def _account(self,s):
        if s['account'] is None: raise PaperError('ACCOUNT_NOT_FOUND','请先创建纸上账户')
        return s['account']
    def _reserved(self,s): return sum((D(o['reserved_cash']) for o in s['orders'] if o['status']=='pending'),Decimal(0))
    def _frozen(self,s,symbol): return sum(o['qty'] for o in s['orders'] if o['status']=='pending' and o['side']=='sell' and o['symbol']==symbol)
    def _settled(self,s,symbol,day): return sum(l['qty'] for l in s['positions'].get(symbol,[]) if l['available_date']<=day)
    def _fee(self,gross,fees): return max(gross*D(fees['rate']),D(fees['minimum'])).quantize(CENT,rounding=ROUND_HALF_UP)
    def _capital(self,value):
        n=D(value)
        if n<=0 or n>1000000000 or n!=n.quantize(CENT): raise ValueError('capital must be positive cents <=1000000000')
        return cash(n)
    def create(self,capital,fees=None,name=None,idempotency_key=None,*,response_context=None):
        capital=self._capital(capital); supplied=dict(fees or {})
        for old,new in [('commission_rate','rate'),('minimum_commission','minimum'),('min_fee','minimum')]:
            if old in supplied: supplied[new]=supplied.pop(old)
        if set(supplied)-{'rate','minimum','slippage_bps'}: raise ValueError('unsupported fee assumption')
        fees={'rate':str(D(supplied.get('rate','.0003'))),'minimum':cash(supplied.get('minimum','5')),'slippage_bps':str(D(supplied.get('slippage_bps','2')))}
        if not 0<=D(fees['rate'])<=D('.01') or not 0<=D(fees['minimum'])<=1000 or not 0<=D(fees['slippage_bps'])<=100: raise ValueError('invalid fee assumptions')
        if name is not None and (not isinstance(name,str) or not 1<=len(name.strip())<=80): raise ValueError('invalid account name')
        def action(s):
            if s['account'] is not None: raise PaperError('ACCOUNT_EXISTS','仅支持一个独立账户，已有账户保留')
            s['account']={'id':self.account_id,'name':name or ('D0前瞻模拟' if self.strategy=='D0' else '周线择债前瞻模拟'),'strategy':self.strategy,'initial_capital':capital,'cash':capital,'running':False,'created_at':iso(self.now()),'resumed_at':None,'activation_generation':0,'fees':fees,'fee_version':digest(fees),'rule_version':RULE_VERSION}
            self._event(s,'created',capital=capital)
        return self._change('create',{'capital':capital,'fees':fees,'name':name},idempotency_key,action,response_context=response_context)
    def configure_capital(self,capital,idempotency_key=None,*,response_context=None):
        capital=self._capital(capital)
        def action(s):
            a=self._account(s)
            if a['running'] or s['fills'] or any(o['status']=='pending' for o in s['orders']): raise PaperError('CAPITAL_LOCKED','仅停止且没有成交及未结委托时可改本金')
            a['initial_capital']=a['cash']=capital; s['plan']=None
            self._event(s,'capital_changed',capital=capital)
        return self._change('capital',{'capital':capital},idempotency_key,action,response_context=response_context)
    set_capital=configure_capital
    def _terminal(self,s,o,status,reason):
        o.update(status=status,terminal_at=iso(self.now()),reason=reason,reserved_cash='0.00',reserved_qty=0)
        self._event(s,status,order_id=o['id'])
    def set_running(self,running,idempotency_key=None,*,response_context=None):
        if not isinstance(running,bool): raise ValueError('running must be boolean')
        def action(s):
            a=self._account(s); self._expire(s)
            if running and not a['running']:
                a['activation_generation']+=1; a['resumed_at']=iso(self.now()); s['observations']={}; s['plan']=None
            if not running:
                for o in s['orders']:
                    if o['status']=='pending': self._terminal(s,o,'cancelled','账户停止，释放冻结')
                s['observations']={}
            a['running']=running; self._event(s,'started' if running else 'paused')
        return self._change('start' if running else 'pause',{'running':running},idempotency_key,action,response_context=response_context)
    def set_signal(self,signal):
        if not isinstance(signal,dict) or signal.get('strategy')!=self.strategy: raise ValueError('confirmed account-strategy signal required')
        signal=copy.deepcopy(signal)
        for k in ('id','market_hash','spec_hash','reason'):
            if not isinstance(signal.get(k),str) or not signal[k] or len(signal[k])>4096: raise ValueError('invalid signal '+k)
        at,received,eligible=(dt(signal.get(k)) for k in ('signal_at','received_at','eligible_at'))
        cutoff=dt(signal.get('data_cutoff',signal.get('market_at',signal['signal_at'])))
        known=dt(signal.get('known_at',signal['received_at']))
        if not cutoff<=at<=known<=received<=dt(self.now()) or eligible<cutoff: raise ValueError('signal time is not causal')
        if signal.get('day')!=cutoff.date().isoformat(): raise ValueError('signal confirmed day mismatch')
        weights=signal.get('weights')
        if not isinstance(weights,dict) or not weights or set(weights)-set(self.rules): raise ValueError('invalid weights')
        if any(not 0<=D(v)<=1 for v in weights.values()) or sum(D(v) for v in weights.values())>1: raise ValueError('invalid weights')
        if self.strategy=='D0I-BOND-WW' and D(weights.get('sh518880',0))!=0: raise ValueError('WW excludes gold')
        signal['weights']={k:str(D(v)) for k,v in weights.items()}
        for k in ('signal_at','received_at','eligible_at'): signal[k]=iso(signal[k])
        references=signal.get('reference_prices',{})
        if not isinstance(references,dict) or set(references)-set(self.rules) or any(D(v)<=0 for v in references.values()): raise ValueError('invalid reference prices')
        signal['reference_prices']={k:px(v) for k,v in references.items()}
        def action(s,db):
            old=s['signal']
            if old and (dt(old['signal_at'])>at or (old['id']==signal['id'] and old!=signal)): raise ValueError('signal regression or ID conflict')
            s['signal']=signal
            self.notifications.record_signal(db,s['account'],old,signal)
        return self._transaction('signal',{},None,action)
    def set_plan(self,plan):
        if not isinstance(plan,dict) or not isinstance(plan.get('id'),str): raise ValueError('plan identifier required')
        plan=copy.deepcopy(plan)
        if not isinstance(plan.get('targets'),dict) or set(plan['targets'])-set(self.rules): raise ValueError('invalid plan targets')
        if any(isinstance(q,bool) or not isinstance(q,int) or q<0 or q>1000000000000 or q%100 for q in plan['targets'].values()): raise ValueError('invalid plan quantity')
        def action(s):
            a=self._account(s)
            if not a['running'] or not s['signal'] or plan.get('signal_id')!=s['signal']['id']: raise ValueError('plan requires current signal and running account')
            if s['plan'] and s['plan']['id']==plan['id']:
                if s['plan']!=plan: raise ValueError('plan is already frozen')
            else: s['plan']=plan; self._event(s,'plan_created',plan_id=plan['id'])
        return self._change('plan',{},None,action)
    def _expire(self,s):
        for o in s['orders']:
            if o['status']=='pending' and dt(self.now())>=dt(o['expires_at']): self._terminal(s,o,'expired','DAY委托到期')
    def tick(self): return self._change('tick',{},None,lambda s:self._expire(s))
    def _bounds(self,q,r):
        c,p=D(q['previous_close']),D(r['limit_pct'])
        return ((c*(1-p)).quantize(TICK,rounding=ROUND_HALF_UP),(c*(1+p)).quantize(TICK,rounding=ROUND_HALF_UP))
    def _fresh(self,q,now):
        at,received=dt(q['quote_at']),dt(q['received_at'])
        return (at.date()==now.date() and at<=received<=now and
                (received-at).total_seconds()<=60 and (now-at).total_seconds()<=60 and
                (now-received).total_seconds()<=5 and self.calendar.segment(at) is not None and
                self.calendar.segment(at)==self.calendar.segment(received)==self.calendar.segment(now))
    def cancel(self,order_id,idempotency_key=None,*,response_context=None):
        def action(s):
            self._account(s); self._expire(s)
            o=next((o for o in s['orders'] if o['id']==order_id),None)
            if o is None: raise PaperError('ORDER_NOT_FOUND','委托不存在')
            if o['status']=='pending': self._terminal(s,o,'cancelled','用户撤销')
        return self._change('cancel',{'order_id':order_id},idempotency_key,action,response_context=response_context)
    def submit(self,symbol,side,qty,limit_price,expires_at=None,signal_id=None,client_order_id=None,plan_id=None,intent_id=None):
        if not isinstance(client_order_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',client_order_id): raise ValueError('client_order_id required, max100 safe characters')
        if not isinstance(symbol,str) or not isinstance(side,str) or isinstance(qty,bool) or not isinstance(qty,int): raise ValueError('invalid order field type')
        limit=D(limit_price); expiry=dt(expires_at) if expires_at is not None else None
        request={'symbol':symbol,'side':side,'qty':qty,'limit_price':str(limit),'expires_at':iso(expiry) if expiry else None,'signal_id':signal_id,'plan_id':plan_id,'intent_id':intent_id}
        fp=digest(request)
        def action(s,db):
            a=self._account(s); self._expire(s); now=dt(self.now())
            old=next((o for o in s['orders'] if o['client_order_id']==client_order_id),None)
            if old:
                if old['request_hash']!=fp: raise PaperError('IDEMPOTENCY_CONFLICT','委托键已用于不同参数')
                return {'order_id':old['id']}
            end=datetime.combine(now.date(),time(14,57),TZ); expiry_at=expiry or end
            sig=s['signal']; r=self.rules.get(symbol); q=s['quotes'].get(symbol)
            o={'id':uid(),'client_order_id':client_order_id,'request_hash':fp,'symbol':symbol,'side':side,'qty':qty,'remaining_qty':qty,'qty_filled':0,'limit_price':str(limit),'status':'pending','signal_id':signal_id,'signal_at':sig['signal_at'] if sig else None,'submitted_at':iso(now),'eligible_at':iso(max(now,dt(sig['eligible_at']))) if sig else iso(now),'expires_at':iso(expiry_at),'plan_id':plan_id or (s['plan'] or {}).get('id'),'intent_id':intent_id or client_order_id,'fees':dict(a['fees']),'fee_version':a['fee_version'],'rules':copy.deepcopy(r),'rule_version':RULE_VERSION,'reserved_cash':'0.00','reserved_qty':0,'terminal_at':None,'quote_at':None,'received_at':None,'matched_at':None,'reason':'等待委托后两次新鲜成交证据'}
            reason=None
            if not a['running']: reason='账户已停止'
            elif self.calendar.is_session(now.date()) is None: reason='交易日历或规则覆盖未知'
            elif not self.calendar.is_continuous(now): reason='当前非支持的连续交易时段'
            elif r is None or side not in ('buy','sell'): reason='标的或方向不支持'
            elif self.strategy=='D0I-BOND-WW' and symbol=='sh518880': reason='周线择债策略不配置黄金'
            elif qty<=0 or qty>1000000 or qty%r['lot']: reason='数量须100份整手且不超过1000000份'
            elif limit<=0 or limit>100000 or limit!=limit.quantize(TICK): reason='限价须有效0.001元价位'
            elif not sig or signal_id!=sig['id']: reason='委托必须关联当前已确认D0信号'
            elif now<dt(sig['eligible_at']): reason='信号尚未到可执行时间'
            elif not now<expiry_at<=end or expiry_at.date()!=now.date(): reason='仅支持当日14:57前到期DAY委托'
            elif not q or not self._fresh(q,now) or q['status'] in ('halted','unknown') or s.get('status_watermarks',{}).get(symbol,{}).get('status')=='halted': reason='缺少当日新鲜报价及有效前收盘价'
            elif not self._bounds(q,r)[0]<=limit<=self._bounds(q,r)[1]: reason='限价超出当日涨跌幅范围'
            elif side=='buy' and r['settlement']=='T1' and self.calendar.next_session(now.date()) is None: reason='下一结算日超出已知日历'
            if reason is None:
                gross=limit*qty
                if side=='buy':
                    reserved=gross+self._fee(gross,o['fees'])
                    if reserved>D(a['cash'])-self._reserved(s): reason='可用现金不足'
                    else: o['reserved_cash']=cash(reserved)
                elif qty>self._settled(s,symbol,now.date().isoformat())-self._frozen(s,symbol): reason='可卖份额不足或未完成T+1结算'
                else:
                    fee_gap=max(Decimal(0),self._fee(gross,o['fees'])-gross)
                    if fee_gap>D(a['cash'])-self._reserved(s): reason='可用现金不足以支付卖出费用缺口'
                    else: o['reserved_qty']=qty; o['reserved_cash']=cash(fee_gap)
            if reason: o.update(status='rejected',reason=reason,remaining_qty=0,terminal_at=iso(now))
            s['orders'].append(o); self._event(s,'rejected' if reason else 'submitted',order_id=o['id'],reason=o['reason'])
            if not reason:
                self.notifications.record_order(db,a,o)
            return {'order_id':o['id']}
        return self._transaction('submit',request,None,action)
    @staticmethod
    def _raw_status(raw):
        if raw.get('suspended') is True: return 'halted'
        value=raw.get('status',raw.get('exchange_status',raw.get('market_status',raw.get('market_state'))))
        if raw.get('corporate_actions_known') is False or raw.get('corporate_action_pending') is True: return 'unknown'
        if value is None: return 'unverified'
        if value in ('trading','active','normal','open','verified_tradable'): return 'normal'
        if value in ('halted','suspended','closed'): return 'halted'
        return 'unknown'
    def _status_packet(self,raw,received_at,now):
        if not isinstance(raw,dict) or not isinstance(raw.get('symbol'),str) or raw.get('symbol') not in self.rules: raise ValueError('invalid quote symbol')
        source=raw.get('source')
        if not isinstance(source,str) or not 1<=len(source)<=128: raise ValueError('invalid quote source')
        packet={'symbol':raw['symbol'],'quote_at':iso(raw.get('quote_at')),
                'received_at':iso(raw.get('received_at',received_at)),
                'source':source,'status':self._raw_status(raw)}
        if not self._fresh(packet,now): raise ValueError('stale/future/cross-day/phase/queue-delay quote')
        return packet
    def _clear_activity(self,s,symbols=None):
        for symbol in (self.rules if symbols is None else symbols):
            s['observations'].pop(symbol,None)
    def invalidate_activity(self,reason,symbols=None):
        if not isinstance(reason,str) or not reason: raise ValueError('activity invalidation reason required')
        if symbols is not None and (not isinstance(symbols,(list,tuple,set)) or any(x not in self.rules for x in symbols)):
            raise ValueError('invalid activity symbols')
        def action(s):
            self._clear_activity(s,symbols)
        return self._change('invalidate_activity',{'reason':reason},None,action)
    def _record_adverse_status(self,s,packet):
        symbol=packet['symbol']; status=packet['status']
        if status not in ('halted','unknown'): return
        states=s.setdefault('status_watermarks',{}); old=states.get(symbol)
        if old:
            # Neither timestamp may move backwards. Equal-time packets cannot
            # replace a recorded state, and unknown cannot clear a halt latch.
            if dt(packet['quote_at'])<=dt(old['quote_at']) or dt(packet['received_at'])<=dt(old['received_at']): return
            if old['status']=='halted' and status!='halted':
                # Preserve explicit halt provenance while a newer uncertain
                # state advances the barrier that recovery must follow.
                blocked=copy.deepcopy(old)
                blocked.setdefault('halt_quote_at',old['quote_at'])
                blocked.setdefault('halt_received_at',old['received_at'])
                blocked.update(quote_at=packet['quote_at'],received_at=packet['received_at'])
                states[symbol]=blocked
                self._clear_activity(s,[symbol])
                return
        states[symbol]=copy.deepcopy(packet)
        if status=='halted':
            states[symbol].update(halt_quote_at=packet['quote_at'],halt_received_at=packet['received_at'])
        self._clear_activity(s,[symbol])
    @staticmethod
    def _raw_quotes(batch):
        if not isinstance(batch,dict): raise ValueError('batch object required')
        rows=batch.get('quotes',[])
        if isinstance(rows,dict): rows=[{'symbol':symbol,**raw} if isinstance(raw,dict) else raw for symbol,raw in rows.items()]
        if not isinstance(rows,list) or len(rows)>4: raise ValueError('at most four quotes per batch')
        return [{'source':batch.get('source'),**raw} if isinstance(raw,dict) else raw for raw in rows]
    def observe_status(self,batch):
        # This path never matches or clears a halt; it is safe while a source
        # rejects prices or the daily strategy inputs are unavailable.
        rows=self._raw_quotes(batch)
        def action(s):
            for raw in rows:
                try: packet=self._status_packet(raw,batch.get('received_at'),dt(self.now()))
                except (ValueError,TypeError): continue
                self._record_adverse_status(s,packet)
        return self._change('observe_status',{},None,action)
    def _quote(self,raw,received_at,now):
        q=self._status_packet(raw,received_at,now)
        p,close,volume,amount=(D(raw.get(k)) for k in ('price','previous_close','volume_lots','amount_cny'))
        if p<=0 or close<=0 or p!=p.quantize(TICK) or close!=close.quantize(TICK) or volume<0 or amount<0: raise ValueError('invalid quote fields')
        q.update(price=px(p),previous_close=px(close),volume_lots=str(volume),amount_cny=str(amount),
                 corporate_unknown=raw.get('corporate_actions_known') is False or raw.get('corporate_action_pending') is True)
        q['id']=digest(q)
        return q
    def ingest_batch(self,batch):
        try: raw_quotes=self._raw_quotes(batch)
        except ValueError:
            self.invalidate_activity('malformed_batch')
            raise
        def action(s):
            self._expire(s); now=dt(self.now()); errors=[]
            for raw in raw_quotes:
                symbol=raw.get('symbol') if isinstance(raw,dict) else None
                symbol=symbol if isinstance(symbol,str) and symbol in self.rules else None
                # Exact already-observed packets are no-ops even after ageing.
                # Changed fields or either timestamp make a distinct observation.
                key=digest({'raw':raw,'received_at':raw.get('received_at',batch.get('received_at')) if isinstance(raw,dict) else batch.get('received_at')})
                seen=s.setdefault('seen_packets',{}).setdefault(symbol or '_invalid',[])
                if key in seen: continue
                seen.append(key); del seen[:-64]
                try:
                    packet=self._status_packet(raw,batch.get('received_at'),now)
                    self._record_adverse_status(s,packet)
                    q=self._quote(raw,batch.get('received_at'),now)
                except (ValueError,InvalidOperation,TypeError,KeyError) as exc:
                    self._clear_activity(s,[symbol] if symbol else None)
                    errors.append({'symbol':symbol,'reason':str(exc)}); continue
                symbol=q['symbol']; prev=s['observations'].get(symbol)
                water=s.setdefault('watermarks',{}).get(symbol)
                state=s.setdefault('status_watermarks',{}).get(symbol)
                if q['status'] in ('halted','unknown'):
                    self._clear_activity(s,[symbol])
                    current=s['quotes'].get(symbol)
                    if current is None or (dt(q['quote_at'])>dt(current['quote_at']) and dt(q['received_at'])>dt(current['received_at'])):
                        s['quotes'][symbol]=q
                    if q['corporate_unknown'] and s['account'] and s['account']['running']:
                        s['account']['running']=False
                        for o in s['orders']:
                            if o['status']=='pending': self._terminal(s,o,'cancelled','公司行动状态未确认，账户停止')
                        self._event(s,'paused',reason='corporate_actions_unknown')
                    continue
                if state and (dt(q['quote_at'])<=dt(state['quote_at']) or dt(q['received_at'])<=dt(state['received_at'])):
                    self._clear_activity(s,[symbol]); errors.append({'symbol':symbol,'reason':'quote does not follow trusted trading status'}); continue
                recovering=bool(state and state['status']=='halted')
                if recovering and (q['status']!='normal' or q['source']!=state['source']):
                    self._clear_activity(s,[symbol]); errors.append({'symbol':symbol,'reason':'halt requires newer explicit same-source normal evidence'}); continue
                if water and (dt(q['quote_at'])<=dt(water['quote_at']) or dt(q['received_at'])<=dt(water['received_at'])):
                    self._clear_activity(s,[symbol]); errors.append({'symbol':symbol,'reason':'conflicting or out-of-order quote'}); continue
                same_day=water and water['source']==q['source'] and water['quote_at'][:10]==q['quote_at'][:10]
                if same_day and (D(q['volume_lots'])<=D(water['volume_lots']) or D(q['amount_cny'])<=D(water['amount_cny'])):
                    self._clear_activity(s,[symbol]); errors.append({'symbol':symbol,'reason':'no strictly newer cumulative trade evidence'}); continue
                if same_day and water['previous_close']!=q['previous_close']:
                    self._clear_activity(s,[symbol]); errors.append({'symbol':symbol,'reason':'previous close changed within session; unverified adjustment'})
                    if s['account'] and s['account']['running']:
                        s['account']['running']=False
                        for o in s['orders']:
                            if o['status']=='pending': self._terminal(s,o,'cancelled','前收盘价盘中变化，账户停止待核对')
                        self._event(s,'paused',reason='previous_close_changed')
                    continue
                if recovering: self._clear_activity(s,[symbol]); prev=None
                if q['status']=='normal' or (state and state['status']=='unknown'):
                    s['status_watermarks'][symbol]={k:q[k] for k in ('symbol','source','status','quote_at','received_at')}
                comparable=prev and prev['source']==q['source'] and prev['quote_at'][:10]==q['quote_at'][:10]
                s['quotes'][symbol]=q; s['watermarks'][symbol]=q; s['observations'][symbol]=q
                a=s['account']
                if not a or not a['running'] or not comparable: continue
                if self.calendar.segment(dt(prev['quote_at']))!=self.calendar.segment(now) or (now-dt(prev['quote_at'])).total_seconds()>60: continue
                for o in s['orders']:
                    if o['status']!='pending' or o['symbol']!=symbol: continue
                    threshold=max(dt(o['submitted_at']),dt(o['eligible_at']),dt(a['resumed_at']),dt(s['reset_at']))
                    if not (dt(prev['quote_at'])>threshold and dt(prev['received_at'])>threshold): continue
                    self._match(s,o,prev,q,now)
            return {'ingest_errors':errors}
        return self._change('ingest',{},None,action)
    def _match(self,s,o,prev,q,now):
        r=o['rules']; low,high=self._bounds(q,r); market=D(q['price']); buy=o['side']=='buy'
        if not low<market<high: o['reason']='涨跌停边界或异常价，无盘口不估计成交'; return
        slip=D(o['fees']['slippage_bps'])/10000
        estimate=(market*(1+slip if buy else 1-slip)).quantize(TICK,rounding=ROUND_CEILING if buy else ROUND_FLOOR)
        if not low<estimate<high or (buy and estimate>D(o['limit_price'])) or (not buy and estimate<D(o['limit_price'])):
            o['reason']='估计价尚未满足限价与涨跌幅规则'; return
        gross=estimate*o['qty']; fee=self._fee(gross,o['fees']); a=s['account']; day=now.date().isoformat()
        if buy:
            if gross+fee>D(o['reserved_cash']): raise ValueError('cash reservation invariant violated')
            available=now.date() if r['settlement']=='T0' else self.calendar.next_session(now.date())
            if available is None: raise ValueError('settlement calendar unknown')
            a['cash']=cash(D(a['cash'])-gross-fee)
            s['positions'].setdefault(o['symbol'],[]).append({'qty':o['qty'],'acquired_at':iso(now),'available_date':available.isoformat(),'cost':cash(gross+fee),'order_id':o['id']})
        else:
            if o['qty']>self._settled(s,o['symbol'],day): raise ValueError('sell reservation invariant violated')
            if max(Decimal(0),fee-gross)>D(o['reserved_cash']): raise ValueError('sell fee reservation invariant violated')
            left=o['qty']
            for lot in s['positions'].get(o['symbol'],[]):
                if lot['available_date']>day or not left: continue
                take=min(left,lot['qty']); original=lot['qty']; lot['qty']-=take; left-=take
                lot['cost']=cash(D(lot['cost'])*lot['qty']/original)
            s['positions'][o['symbol']]=[lot for lot in s['positions'][o['symbol']] if lot['qty']]
            a['cash']=cash(D(a['cash'])+gross-fee)
        evidence=[{k:item[k] for k in ('id','quote_at','received_at','volume_lots','amount_cny','source','status')} for item in (prev,q)]
        f={'id':uid(),'order_id':o['id'],'client_order_id':o['client_order_id'],'plan_id':o['plan_id'],'intent_id':o['intent_id'],'signal_id':o['signal_id'],'signal_at':o['signal_at'],'submitted_at':o['submitted_at'],'eligible_at':o['eligible_at'],'quote_at':q['quote_at'],'received_at':q['received_at'],'matched_at':iso(now),'symbol':o['symbol'],'side':o['side'],'qty':o['qty'],'price':px(estimate),'gross':cash(gross),'fee':cash(fee),'fees':copy.deepcopy(o['fees']),'fee_version':o['fee_version'],'rules':copy.deepcopy(r),'rule_version':o['rule_version'],'exchange_status':'unverified' if 'unverified' in (prev['status'],q['status']) else 'provider_reported_normal','evidence':evidence,'model':'observed_new_trade_full_order_estimate','model_notice':MODEL_NOTICE}
        s['fills'].append(f)
        o.update(status='filled',qty_filled=o['qty'],remaining_qty=0,terminal_at=iso(now),reserved_cash='0.00',reserved_qty=0,reason='新鲜成交证据满足，整单模拟估计成交',fill_id=f['id'],quote_at=q['quote_at'],received_at=q['received_at'],matched_at=iso(now))
        self._event(s,'estimated_fill',order_id=o['id'],fill_id=f['id'])
    def _view(self,s):
        self._assert_strategy(s)
        result=copy.deepcopy({k:v for k,v in s.items() if k not in ('observations','commands','reset_at','watermarks','seen_packets')})
        result['revision']=str(s['revision']); result['positions']=[]; now=dt(self.now()); day=now.date().isoformat()
        # The same captured instant drives both valuation and persisted first response.
        result['response_at']=iso(now)
        for symbol,state in s.get('status_watermarks',{}).items():
            if state['status']=='halted' and symbol in result['quotes']:
                result['quotes'][symbol].update(status='halted',status_quote_at=state.get('halt_quote_at',state['quote_at']),status_received_at=state.get('halt_received_at',state['received_at']))
        marked=Decimal(0); valuation_status='current'
        for symbol in self.rules:
            lots=s['positions'].get(symbol,[]); qty=sum(l['qty'] for l in lots); frozen=self._frozen(s,symbol)
            q=s['quotes'].get(symbol); value=None; mark=None; status='not_held'
            if qty:
                if not q: status='unknown'; valuation_status='unknown'
                else:
                    mark=q['price']; value=cash(D(mark)*qty)
                    status='current' if self._fresh(q,now) and q['status'] not in ('halted','unknown') and s.get('status_watermarks',{}).get(symbol,{}).get('status')!='halted' else 'stale'
                    if status!='current' and valuation_status!='unknown': valuation_status='stale'
                    marked+=D(value)
            result['positions'].append({'symbol':symbol,'qty':qty,'settled_qty':self._settled(s,symbol,day),'reserved_qty':frozen,'available_qty':self._settled(s,symbol,day)-frozen,'cost':cash(sum((D(l['cost']) for l in lots),Decimal(0))),'price':mark,'market_value':value,'valuation_status':status,'lots':copy.deepcopy(lots)})
        if result['account']:
            a=result['account']; frozen=self._reserved(s)
            a.update(reserved_cash=cash(frozen),available_cash=cash(D(a['cash'])-frozen),equity=cash(D(a['cash'])+marked) if valuation_status!='unknown' else None,valuation_status=valuation_status)
        result['rules']={'version':RULE_VERSION,'coverage_from':'2026-07-06','coverage_until':'2026-12-31','coverage_note':'本模型日历及规则覆盖边界，不是法律有效期','instruments':copy.deepcopy(self.rules),'source_delay_max_seconds':60,'match_age_max_seconds':60,'queue_delay_max_seconds':5,'partial_fills_supported':False,'sessions':['09:30<=t<11:30','13:00<=t<14:57'],'order_type':'DAY limit'}
        result['model_notice']=MODEL_NOTICE
        return result
    def snapshot(self):
        db=self._db()
        try:
            db.execute('BEGIN')
            result=self._view(json.loads(db.execute('SELECT data FROM ledger WHERE id=1').fetchone()[0]))
            try: result['_pnl_history']=read_history(db,result)
            except Exception: result['_pnl_history']={'error':'history_unavailable'}
            db.rollback()
            return result
        finally: db.close()

    def close(self):
        # Each database connection is scoped and closed in its operation.
        pass
