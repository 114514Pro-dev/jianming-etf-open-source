"""One persistent ledger for manual rehearsal and automatic portfolio strategies."""
from copy import deepcopy
import math
import bank_model as model
import trade_book as b
from automation import AutoBook
from dynamic_allocation import MODES,rebalance_reason

class SuiteBook(AutoBook):
    def __init__(self,folder=None):
        if folder is None:model.prepare_home()
        super().__init__(folder)
        if folder is None:
            from suite_migration import import_paper_accounts
            import_paper_accounts(self)

    def get(self,id,con=None):
        s=super().get(id,con)
        if s['auto'].get('execution','auto') not in ['auto','paper']:raise ValueError('账户执行方式无效')
        return s

    def create(self,name,capital,day,market,strategy=model.DEFAULT,execution='auto'):
        if execution not in ['auto','paper']:raise ValueError('执行方式无效')
        s=super().create(name,capital,day,market,strategy)
        if execution=='paper':return self.set_execution(s['id'],'paper')
        return s

    def set_execution(self,id,mode):
        if mode not in ['auto','paper']:raise ValueError('请选择自动模拟或手动演练')
        with self.connection() as con:
            s=self.get(id,con)
            if mode==s['auto'].get('execution','auto'):return s
            if s['pending']:self.event(con,s,'撤销策略委托',dict(order_id=s['pending']['id'],reason='切换操作方式，旧委托撤销'))
            s['pending']=None;s['auto'].update(execution=mode,evaluated=None)
            if mode=='paper':s['auto']['watch']=False
            self.event(con,s,'切换执行方式',dict(execution=mode,note='手动演练不自动覆盖仓位；切回自动后按当前日信号生成次日目标'))
            self.save(con,s)
        return s

    def set_strategy(self,id,strategy):
        config=model.spec(strategy)
        with self.connection() as con:
            s=self.get(id,con)
            if s['day']<config['anchor']:raise ValueError('账户日期早于此方案起点')
            old=s['auto']['strategy']
            if strategy==old:return s
            if s['pending']:self.event(con,s,'撤销策略委托',dict(order_id=s['pending']['id'],reason='更换后续策略'))
            s['pending']=None;s['last_target']=None
            s['auto'].update(strategy=strategy,spec_hash=model.digest(config),evaluated=None)
            self.event(con,s,'更换后续策略',dict(previous=old,current=strategy,effective_from=s['day'],note='已有历史不重算，后续按新方案；全区间比较请新建回测'))
            self.save(con,s)
        return s

    def require_paper(self,id):
        s=self.get(id)
        if s['auto'].get('execution','auto')!='paper':raise ValueError('请先切换为手动演练，再预览或确认买卖')
        return s

    def preview(self,id,market,c,side,qty):
        self.require_paper(id)
        return b.Book.preview(self,id,market,c,side,qty)

    def commit(self,plan,market):
        self.require_paper(plan['account'])
        return b.Book.commit(self,plan,market)

    def preview_weights(self,id,market,weights):
        s=self.require_paper(id)
        if s['pending']:raise ValueError('已有待执行委托，请先撤销或推进日期')
        if set(weights)!=set(b.CODES) or any(not math.isfinite(v) or v<0 or v>1 for v in weights.values()) or sum(weights.values())>1.0000001:raise ValueError('每项仓位须在0%～100%，合计不能超过100%；剩余为现金')
        rows,warnings,blocked=b.target_fills(deepcopy(s),market.at(s['day']),weights)
        p=dict(kind='strategy',account=id,revision=s['revision'],market_hash=market.hash,day=s['day'],weights=weights,
            observation_id=None,reasons=['用户设置的手动目标仓位；按下一可执行日开盘模拟'],rows=rows,warnings=warnings)
        p['id']=b.digest(p);return p

    def queue_strategy(self,plan,market):
        self.require_paper(plan['account'])
        return b.Book.queue_strategy(self,plan,market)

    def set_watch(self,id,enabled):
        if enabled and self.get(id)['auto'].get('execution','auto')!='auto':raise ValueError('每日自动跟踪需使用自动模拟方式')
        return super().set_watch(id,enabled)

    def evaluate(self,con,s,market):
        a=s['auto'];day=s['day']
        if a['evaluated']==day:return
        obs=market.observation(a['strategy'],day);weights=obs['weights']
        if a.get('execution','auto')=='paper':
            needed=False;action='手动演练：信号仅供参考，不自动改动仓位'
        elif a['strategy'] in MODES:
            needed,action,actual,drift=rebalance_reason(s,market.at(day),weights,a['strategy'],market.dates)
            obs.update(actual_weights=actual,max_drift=drift)
        else:needed=s['last_target']!=weights;action='组合目标改变' if needed else '目标未改变，继续持有'
        if a.get('execution','auto')=='auto':
            if s['pending'] and (not needed or s['pending']['weights']!=weights):
                self.event(con,s,'更新未成交目标',dict(old_signal=s['pending']['day'],old_weights=s['pending']['weights'],new_weights=weights,reason=action))
                s['pending']=None
            if needed and not s['pending']:
                plan=dict(kind='strategy',account=s['id'],revision=s['revision'],market_hash=market.hash,day=day,weights=weights,
                    observation_id=model.digest(obs),reasons=[action,obs['reason']],evidence=deepcopy(obs))
                plan['id']=model.digest(plan);s['pending']=plan
                self.event(con,s,'自动策略委托',dict(weights=weights,signal_day=day,reason=action,features=obs['features'],state=obs['state']),plan['id'])
                action+='；已生成下一可执行日开盘目标'
        obs['action']=action;a['last_observation']=obs;a['evaluated']=day
        self.event(con,s,'收盘分析',obs)
