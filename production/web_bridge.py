"""JSON adapter for the unchanged v1.4 services.

The caller owns a SINGLE serialized executor for every Bridge call.  This is
not a multi-worker store or a scheduler.  No tkinter module is imported here.
An explicit profile is mandatory; no default desktop account is ever selected.
"""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import json
import math

from simulator_core import Service, ORDER, TITLES, DESCRIPTIONS, CODES, NAMES, RULE_NOTE, write_json, compatible
from strategy_labels import StrategyLabels
from chinext_service import Top5Service, BY_ID as TOP5
from seven_service import SevenService, BY_ID as SEVEN, ORDER as SEVEN_ORDER, CODES as SEVEN_CODES, NAMES as SEVEN_NAMES, label as seven_label
from intraday import LiveService, now as china_now
from top5_reference import reference_plan
from chinext_engine import clean_json
from bank_model import spec
from trade_book import value as ledger_value
from web_auto import AutoSupport, WebTop5Service
from web_overseas import OverseasService, MARKETS
from web_account_trash import AccountTrash
from web_account_decision import original_decision, top5_decision, result_decision

GROUPS = {'original': '四资产原9策略', 'top5': '创业板5策略', 'seven': '七组合', **{g:m['name']+' · 海外' for g,m in MARKETS.items()}}


def _json(value):
    """Fail closed if an adapter accidentally exposes a Market or other object."""
    return json.loads(json.dumps(clean_json(value), ensure_ascii=False, allow_nan=False))


def _metrics(native, capital=None, equity=None, trades=None, trade_unit='成交笔数'):
    result = dict(native or {})
    final = result.get('final_equity', result.get('end_equity', equity))
    ret = result.get('total_return')
    if ret is None and final is not None and capital:
        ret = final / capital - 1
    result.update({'return': ret, 'annualized': result.get('cagr'),
                   'drawdown': abs(result.get('max_drawdown') or 0),
                   'equity': final, 'fees': result.get('fees', 0),
                   'trades': trades if trades is not None else result.get('fills', result.get('trades', 0)),
                   'trade_unit': trade_unit})
    return _json(result)


def _curve(rows):
    out = []
    for row in rows:
        point = dict(row)
        point['date'] = row.get('date', row.get('day', row.get('datetime')))
        point['market_value'] = row.get('market_value', row.get('market',
            row.get('equity', 0) - row.get('cash', 0) - row.get('receivable', 0)))
        out.append(point)
    return _json(out)


def _event(row, group):
    # Daily analysis payloads contain thousands of indicator values. Keep the
    # browser list small; complete original evidence stays in native backups.
    data = row.get('data', row)
    return _json(dict(id=row.get('id'), time=row.get('time', row.get('day', row.get('date'))),
        type=row.get('kind', '成交'), symbol=data.get('symbol', 'sz159915' if group == 'top5' else None),
        side=data.get('side'), qty=data.get('qty', data.get('quantity')),
        price=data.get('price'), fee=data.get('fee'), cash_change=data.get('cash_change'),
        signal_day=data.get('signal_day'), reason=data.get('reason', data.get('action', data.get('note', ''))),
        bar_time=data.get('bar_time'), leg=data.get('leg')))


class Bridge:
    def __init__(self, folder):
        if not folder:
            raise ValueError('必须明确指定独立的数据目录。')
        self.folder = Path(folder).expanduser().resolve()
        self.folder.mkdir(parents=True, exist_ok=True)
        self.trash = AccountTrash(self.folder)
        self.trash.read()
        self.original = Service(self.folder)
        self.top5 = WebTop5Service(self.folder)
        self.seven = SevenService(self.folder, self.original, self.top5)
        self.live = LiveService(self.original)
        self.overseas = OverseasService(self.folder)
        self.labels = StrategyLabels()
        prior = self.folder / '最近策略比较.json'
        if prior.exists():
            try:
                self.labels.update(json.loads(prior.read_text(encoding='utf8')))
            except (OSError, ValueError, KeyError, TypeError):
                pass
        self.account_warnings = {group: [] for group in GROUPS}
        self.refresh_notes = []
        self.quote_notes = []
        self.last_reference = None
        self._signal_key = None
        self._signal_summary = None
        self.automation = AutoSupport(self, lambda: china_now())

    @staticmethod
    def _group(group):
        group = group or 'original'
        if group not in GROUPS:
            raise ValueError('请选择original、top5或seven账户类型。')
        return group

    @staticmethod
    def _check_stop(stop):
        if stop is not None and stop.is_set():
            raise InterruptedError('操作已停止；已完成的安全步骤保留。')

    def _check_expected_day(self, group, identity, expected):
        if expected is None:
            return
        if group == 'original':
            actual = self.original.book.get(identity)['day']
        elif group == 'top5':
            actual = self.top5.account_detail(identity)['account']['last_bar']
        else:
            actual = self.seven.get_account(identity)['result']['end']
        if str(expected) != str(actual):
            raise ValueError('账户日期已变化，请刷新页面后再操作。预期 '+str(expected)+'，当前 '+str(actual))

    def _market_info(self):
        top = self.top5.info()
        seven = self.seven.info()
        batch = self.live.batch or {}
        return dict(daily_end=self.original.market.latest, hourly_end=top['latest_bar'],
            quote_received_at=batch.get('received_at'), original_daily=self.original.market.latest,
            top5_daily=top['latest_daily'], top5_hourly=top['latest_bar'],
            seven_daily=seven['latest'], seven_hourly=seven['hourly'],
            calendar_end=top['calendar_end'], timezone='Asia/Shanghai')

    def catalog(self):
        top = self.top5.info()
        seven = self.seven.info()
        start = self.original.default_start()
        return _json(dict(groups=[
            dict(id='original', name=GROUPS['original'], start=start, end=self.original.market.latest,
                 strategies=[dict(code=c, label=self.labels.label(c), description=DESCRIPTIONS[c],
                                  earliest=max(start, spec(c)['anchor'])) for c in ORDER]),
            dict(id='top5', name=GROUPS['top5'], start=top['default_start'], end=top['latest_daily'],
                 strategies=[dict(code=s['id'], label=s['id']+' '+s['name'], description=s['description'],
                                  parameters=s['parameters'], earliest=top['data_start']) for s in self.top5.list_strategies()]),
            dict(id='seven', name=GROUPS['seven'], start='2023-01-03', end=seven['latest'],
                 strategies=[dict(code=c, label=seven_label(c), description=SEVEN[c]['name'],
                                  earliest='2023-01-03', fixed_research_tag=SEVEN[c]['tag']) for c in SEVEN_ORDER]),
        ]+self.overseas.catalog(), market=self._market_info(), ranking_note=self.labels.note,
        default_reference_strategy=self.original.settings.get('live_reference_strategy', 'T5VOTE'),
        default_reference_capital=self.original.settings.get('live_reference_capital', 100000),
        rules=RULE_NOTE, notes=['三类账户独立记账；启用自动模拟后，只在确认数据到达时按各账户原规则推进。',
            '原9比较期末按市值结算；五策略和七组合比较按原研究口径期末清算，不能直接混排。']))

    def overseas_overview(self):
        return _json(self.overseas.overview())

    def overseas_curve(self, group, strategy, variant):
        from web_overseas import MARKETS
        rows = self.overseas.research['markets'][MARKETS[group]['symbol']]
        return _json(next(r['curve'] for r in rows if r['strategy'] == strategy and r['variant'] == variant))

    def overview(self):
        key = self.top5.settings['snapshot_id']
        if self._signal_key != key:
            self._signal_summary = self.top5.signal_summary()
            self._signal_key = key
        market = self._market_info()
        warnings = list(dict.fromkeys(self.refresh_notes + self.quote_notes))
        for group, rows in self.account_warnings.items():
            if rows:
                warnings.append(GROUPS[group]+'有'+str(len(rows))+'个账户读取失败，已保留原文件；请查看账户异常详情。')
        if china_now().date().isoformat() > market['calendar_end']:
            warnings.append('交易日历仅核验至'+market['calendar_end']+'，之后行情须先更新日历。')
        if not self.live.batch:
            warnings.append('尚未采集当天报价，请刷新；已确认的历史行情仍可用于研究。')
        elif any(q['day'] != china_now().date().isoformat() for q in self.live.batch['quotes'].values()):
            warnings.append('部分报价来自历史日期；来源时间如实保留，不冒充今天。')
        reference = deepcopy(self.last_reference)
        if reference:
            reference.pop('details', None)
        return _json(dict(market=market, quotes=list((self.live.batch or {}).get('quotes', {}).values()),
            quote_stats=self.live.store.stats(), warnings=warnings,
            account_warnings=deepcopy(self.account_warnings),
            notes=['市场数据与账户模拟日期是两回事；参考配置不直接成交，自动模拟只使用已确认数据。', self.labels.note],
            top5_signals=self._signal_summary, reference=reference,
            reference_strategy=self.original.settings.get('live_reference_strategy', 'T5VOTE'),
            reference_capital=self.original.settings.get('live_reference_capital', 100000),
            info=dict(top5={k:v for k,v in self.top5.info().items() if k != 'folder'}, seven=self.seven.info()),
            source=(self.live.batch or {}).get('source'), original_reference_note=self.live.preview_note))

    def _original_summary(self, identity):
        state = self.original.book.get(identity)
        market = self.original.account_market(state)
        val = ledger_value(state, market.at(state['day']))
        from suite_analysis import metrics
        with self.original.book.connection() as con:
            count = con.execute("SELECT count(*) FROM events WHERE account=? AND kind='策略成交'", (identity,)).fetchone()[0]
        m = _metrics(dict(metrics(state['curve'], state['initial']), fees=state['fees']),
                     state['initial'], val['equity'], count)
        return dict(id=identity, name=state['name'], group='original', strategy=state['auto']['strategy'],
            strategy_label=self.labels.label(state['auto']['strategy']), start=state['start'], day=state['day'],
            capital=state['initial'], equity=val['equity'], cash=val['cash'], market_end=market.latest,
            **{k:m[k] for k in ['return','annualized','drawdown','fees','trades','trade_unit']})

    def _top5_summary(self, summary):
        a = summary
        return dict(id=a['id'], name=a['name'], group='top5', strategy=a['strategy_id'],
            strategy_label=a['strategy_id']+' '+a['strategy_name'], start=a['start'], day=a['last_bar'],
            capital=a['capital'], equity=a['equity'], cash=a['cash'], shares=a['shares'],
            return_=a['total_return'], **{'return':a['total_return']}, trades=a['trades'],
            trade_unit='已完成往返交易数', market_end=self.top5.info()['latest_bar'])

    @staticmethod
    def _seven_summary(account):
        r=account['result']; m=_metrics(r['metrics'],r['capital']); last=r['curve'][-1]
        return dict(id=account['id'],name=account['name'],group='seven',strategy=r['strategy'],
            strategy_label=seven_label(r['strategy']),start=r['start'],day=r['end'],capital=r['capital'],
            equity=m['equity'],cash=last['cash'],**{k:m[k] for k in ['return','annualized','drawdown','fees','trades','trade_unit']})

    def accounts(self, group, include_deleted=False):
        group=self._group(group)
        deleted=self.trash.read()
        visible=lambda rows: _json([r for r in rows if include_deleted or group+':'+r['id'] not in deleted])
        self.account_warnings[group]=[]
        if group in MARKETS:
            rows=self.overseas.accounts(group);self.account_warnings[group]=self.overseas.errors[group];return visible(rows)
        if group=='original':
            rows=[]
            for row in self.original.book.list():
                try:rows.append(self._original_summary(row['id']))
                except (OSError,ValueError,TypeError,KeyError) as exc:
                    self.account_warnings[group].append(dict(id=row['id'],name=row['name'],error=str(exc)))
        elif group=='top5':
            rows=[]
            for row in self.top5.list_accounts():
                item=self._top5_summary(row); detail=self.top5.account_detail(row['id'])
                m=_metrics(detail.get('metrics',{}),row['capital'],row['equity'],trade_unit='已完成往返交易数')
                item.update({k:m[k] for k in ['annualized','drawdown','fees']});rows.append(item)
            self.account_warnings[group]=deepcopy(self.top5.account_errors)
        else:
            rows=[self._seven_summary(a) for a in self.seven.accounts()]
            self.account_warnings[group]=deepcopy(self.seven.account_errors)
        return visible(rows)

    def deleted_accounts(self, group):
        return _json(self.trash.entries(self._group(group)))

    def manage_account(self, action, group, identity, expected_day=None):
        self.trash.key(group, identity)
        deleted=self.trash.contains(group, identity)
        if action=='delete' and deleted:
            return dict(group=group,id=identity,deleted=True,note='账户已在“已删除账户”中，可随时恢复。')
        row=next((r for r in self.accounts(group,include_deleted=True) if r['id']==identity),None)
        if row is None:raise ValueError('账户不存在或原始记录无法读取，未更改删除状态。')
        if action=='delete':
            if expected_day is not None and str(row['day'])!=str(expected_day):
                raise ValueError('账户日期已变化，请刷新账户后重新确认删除。')
            self.trash.delete(group,identity,row,china_now().isoformat(timespec='seconds'))
            return dict(group=group,id=identity,deleted=True,note='账户已移入“已删除账户”，不会继续自动模拟；历史记录保留，可恢复。')
        self.trash.restore(group,identity)
        return dict(group=group,id=identity,deleted=False,note='账户已恢复，历史记录保留；沿用原有自动模拟设置。')

    def account(self, group, identity):
        group=self._group(group)
        if self.trash.contains(group,identity):raise ValueError('账户已删除，请先在“已删除账户”中恢复。')
        if group in MARKETS:return _json(self.overseas.account(group,identity))
        if group=='original':
            z=self.original.snapshot(identity);s=z['state'];v=z['value']
            decision=original_decision(z)
            summary=self._original_summary(identity)
            positions=[dict(r,market_value=r['market']) for r in v['rows']]
            events=[_event(e,group) for e in reversed(self.original.book.events(identity))]
            advice=dict(title=z['title'],text=z['observation'].get('reason',''),weights=z['observation']['weights'],
                plan_rows=z['rows'],pending=bool(s['pending']),next=z['next'],notes=z['warnings']+[z['conditions'],
                '操作份数按账户收盘价估算，真实模拟在下一可执行开盘按原规则重算。'])
            stats=_metrics(dict(z['metrics'],fees=s['fees']),s['initial'],v['equity'],summary['trades'])
            curve=_curve(s['curve'])
        elif group=='top5':
            d=self.top5.account_detail(identity);a=d['account'];summary=self._top5_summary(a)
            decision=top5_decision(self.top5,identity)
            stats=_metrics(d['metrics'],a['capital'],a['equity'],trade_unit='已完成往返交易数')
            summary.update({k:stats[k] for k in ['annualized','drawdown','fees']})
            mv=a['equity']-a['cash'];qty=a['shares']
            positions=[dict(symbol='sz159915',name='创业板ETF',qty=qty,market_value=mv,price=mv/qty if qty else None)]
            curve=_curve(d['ledger']);events=[_event(e,group) for e in d['events']]
            advice=dict(title=a['status'],text=d.get('pending',{}).get('description','暂无待执行指令。'),
                pending=d.get('pending',{}),notes=d.get('warnings',[]))
        else:
            a=self.seven.get_account(identity);r=a['result'];summary=self._seven_summary(a)
            decision=result_decision(r)
            stats=_metrics(r['metrics'],r['capital']);curve=_curve(r['curve'])
            events=[_event(e,group) for e in r['events']];positions=[]
            if r['strategy'].startswith('A_'):
                snap=self.seven.snapshot(r['snapshot'])
                for symbol,name in zip(SEVEN_CODES,SEVEN_NAMES):
                    leg=r['leg_states'].get(symbol)
                    if not leg:continue
                    if symbol=='sz159915':
                        qty=leg['shares'];last=next((b for b in reversed(snap['hourly']) if b['datetime']<=leg['last_bar']),None)
                        price=last['close'] if last else None;mv=qty*price if price is not None else None
                    else:
                        qty=leg['qty'][0];mv=leg['market'][0];price=mv/qty if qty else None
                    positions.append(dict(symbol=symbol,name=name,qty=qty,market_value=mv,price=price))
            else:
                last=r['leg_states']['last_close']
                for symbol,name,qty,mv in zip(SEVEN_CODES,SEVEN_NAMES,last['qty'],last['market']):
                    positions.append(dict(symbol=symbol,name=name,qty=qty,market_value=mv,price=mv/qty if qty else None))
            advice=dict(title='下一执行时点参考配置',text=r['plan']['execution'],weights=r['plan']['weights'],
                cash_weight=r['plan']['cash_weight'],as_of=r['plan']['as_of'],
                notes=['持续账户未强制期末清仓。参考目标不是已成交仓位。'])
        return _json(dict(id=identity,group=group,summary=summary,metrics=stats,positions=positions,
            curve=curve,events=events,event_count=len(events),advice=advice,decision=decision,
            notes=['页面事件为精简列表；导出的原生完整备份包含全部原始事件与行情。']))

    def _reference(self, code, capital):
        if code in ORDER:
            return dict(self.automation.original_reference(code,capital),label=self.labels.label(code))
        if code in TOP5:
            p=reference_plan(self.top5,code,capital)
            return dict(available=True,strategy=code,label=code+' '+p['name'],capital=p['capital'],as_of=p['as_of'],
                weights={'sz159915':p['weight']},budgets=p['budgets'],cash=p['cash'],notes=[p['reason']]+p['warnings'],details=p)
        if code in SEVEN:
            r=self.seven.run(code,capital=capital,terminal=False,intraday=True);p=r['plan']
            return dict(available=True,strategy=code,label=seven_label(code),capital=r['capital'],as_of=p['as_of'],
                daily_as_of=p['daily_as_of'],weights=p['weights'],budgets={c:r['capital']*w for c,w in p['weights'].items()},
                cash=r['capital']*p['cash_weight'],notes=[p['execution'],
                    '独立参考预算，不是实际账户仓位；A类各份资金独立复利后的参考比例会漂移。'],
                details=dict(plan=p,metrics=r['metrics'],leg_states=r['leg_states']))
        raise ValueError('请选择21种参考策略之一。')

    def _refresh(self, params, stop, progress):
        result=self.automation.refresh(params,stop,progress)
        result.setdefault('sources',{})['overseas']=self.overseas.refresh(self.automation.daily_limit(china_now()),stop,progress,params.get('force_history',False))
        result['sources']['overseas_quotes']=self.overseas.quotes(stop,progress)
        return result

    def auto_candidates(self):
        deleted=self.trash.read()
        return _json([r for r in self.automation.candidates()+self.overseas.candidates() if r['group']+':'+r['id'] not in deleted])

    def _compare(self,group,params,stop,progress):
        start=params['start'];end=params['end'];capital=params.get('capital',100000)
        if group=='original':
            raw=self.original.compare(start,end,capital,stop=stop,progress=progress)
            self.labels.update(raw)
            rows=[{**_metrics(r,raw['capital']),'code':r['code'],'label':self.labels.label(r['code'])} for r in raw['rows']]
            curves={r['code']:_curve(r['curve']) for r in raw['rows']}
            for row in rows:row.pop('curve',None)
            return dict(group=group,start=raw['start'],end=raw['end'],capital=raw['capital'],rows=rows,curves=curves,
                completed=raw['completed'],skipped=raw['skipped'],ranking_note=self.labels.note,
                notes=['原9比较期末按持仓市值评价，不强制清仓。'],native=raw)
        if group=='top5':
            raw=self.top5.compare(start,end,capital,progress=progress,stop=stop)
            rows=[dict(code=r['id'],label=r['id']+' '+r['name'],**_metrics(r,raw['capital'],trade_unit='已完成往返交易数')) for r in raw['rows']]
            for row in rows:row.pop('trade_detail',None)
            return dict(group=group,start=raw['start'],end=raw['end'],capital=raw['capital'],rows=rows,curves=raw['curves'],
                completed=True,skipped=[],notes=raw['warnings'],native=raw)
        raw=self.seven.compare(start,end,capital,progress=progress,stop=stop)
        rows=[dict(code=r['strategy'],label=seven_label(r['strategy']),**_metrics(r['metrics'],r['capital'])) for r in raw]
        if rows:
            annual=[r for r in rows if r['annualized'] is not None]
            top=max((r['annualized'] for r in annual),default=None);low=min(r['drawdown'] for r in rows)
            for row in rows:
                row['current_badges']=[]
                if top is not None and row['annualized'] is not None and math.isclose(row['annualized'],top,abs_tol=1e-10):row['current_badges'].append('本次年化最高')
                if math.isclose(row['drawdown'],low,abs_tol=1e-10):row['current_badges'].append('本次回撤最低')
        return dict(group=group,start=raw[0]['start'],end=raw[0]['end'],capital=raw[0]['capital'],rows=rows,
            curves={r['strategy']:_curve(r['curve']) for r in raw},completed=True,skipped=[],
            notes=['七组合历史比较期末清算；固定研究标签仍仅对应2023-01-03至2026-09-15、10万元原研究。'],native=raw)

    def accept_comparison(self, params, result):
        """Commit a completed subprocess result without rerunning any strategy.

        `result` is the JSON object returned by execute('compare', params).
        Only original-nine labels are dynamic; other groups retain their
        separate research labels and expose current ranks in comparison rows.
        """
        group=self._group(params.get('group'))
        if result.get('group')!=group:
            raise ValueError('比较结果与请求的策略组不一致。')
        if not result.get('completed'):
            return dict(accepted=False,group=group,reason='未完成比较，保留上一次完整标签。')
        if group!='original':
            return dict(accepted=True,group=group)
        raw=result.get('native',{})
        if (raw.get('start')!=params.get('start') or raw.get('end')!=params.get('end') or
            float(raw.get('capital',0))!=float(params.get('capital',100000)) or
            raw.get('market_hash')!=self.original.market.hash):
            raise ValueError('比较区间、本金或行情快照已变化，未更新标签。')
        checked=StrategyLabels()
        if not checked.update(raw):
            raise ValueError('比较结果不完整或排名口径不合法，未更新标签。')
        write_json(self.folder/'最近策略比较.json',_json(raw))
        self.labels=checked
        return dict(accepted=True,group=group,ranking_note=self.labels.note)

    def execute(self, action, params, stop=None, progress=None):
        params=dict(params or {});group=self._group(params.get('group'));progress=progress or (lambda _:None)
        self._check_stop(stop)
        identity=params.get('id');code=params.get('strategy');capital=params.get('capital',100000)
        if action in {'delete','restore'}:
            return self.manage_account(action,group,identity,params.get('expected_day'))
        if identity is not None and self.trash.contains(group,identity):
            if action=='auto_advance':return dict(group=group,id=identity,advanced=False,skipped=True,reason='账户已删除，跳过自动模拟。')
            raise ValueError('账户已删除，请先在“已删除账户”中恢复。')
        if group in MARKETS and action not in {'quotes','refresh'}:
            return _json(self.overseas.execute(action,dict(params,group=group),stop,progress))
        if action in {'advance','switch','attach'}:
            self._check_expected_day(group,identity,params.get('expected_day'))
        if action=='create':
            progress('正在新建独立模拟账户…')
            if group=='original':a=self.original.create(params['name'],capital,params['start'],code);identity=a['id']
            elif group=='top5':a=self.top5.create_account(params['name'],code,params['start'],capital);identity=a['account']['id']
            else:a=self.seven.create_account(code,params['name'],capital,params['start']);identity=a['id']
            result=self.account(group,identity)
        elif action=='advance':
            progress('正在按已有规则推进模拟账户…')
            if group=='original':
                state=self.original.book.get(identity)
                if params['end']>state['day']:
                    old=self.original.account_market(state)
                    if params['end']>old.latest:
                        # Use the automatic extension's confirmation/compatibility
                        # gates, but honor the manually selected endpoint exactly.
                        candidate=self.automation.candidate('original',identity)
                        if not candidate['can_advance']:
                            raise ValueError('尚不能接入新行情：'+candidate['reason'])
                        target=candidate['target']
                        if params['end']>target or params['end'] not in self.original.market.dates:
                            raise ValueError('所选终点没有已确认收盘行情；最新可用日期为'+target+'。请选择已有交易日，或先刷新行情。')
                        self._check_stop(stop)
                        self.automation.attach_original_extension(identity,event_kind='更新配套行情',
                            note='手动接续时接入确认行情；保留既有待执行目标与收盘分析。')
                        progress('已接入确认行情，正在模拟至'+params['end'])
                    self._check_stop(stop)
                    self.original.run(identity,params['end'],stop=stop,progress=progress)
                elif params['end']<state['day']:raise ValueError('持续账户不能倒退日期；重练请新建账户。')
            elif group=='top5':self.top5.advance_account(identity,params.get('end'))
            else:self.seven.advance(identity,params['end'])
            result=self.account(group,identity)
        elif action=='switch':
            if group!='original':raise ValueError('只有原9账户可更换后续策略；五策略和七组合账户规则固定。')
            self.original.switch(identity,code);result=self.account(group,identity)
        elif action=='attach':
            if group!='original':raise ValueError('此操作仅适用于原9账户。')
            note=self.original.update_market(identity,data=self.original.market.data)
            result=self.account(group,identity);result['notes'].append(note)
        elif action=='compare':result=self._compare(group,params,stop,progress)
        elif action=='refresh':result=self._refresh(params,stop,progress)
        elif action=='quotes':
            result=self.automation.quotes(params,stop,progress)
            result.setdefault('sources',{})['overseas_quotes']=self.overseas.quotes(stop,progress)
        elif action=='auto_advance':result=self.automation.advance(params,stop,progress)
        elif action=='reference':
            self.last_reference=None
            result=self.automation.reference(code,capital,force=True);self.last_reference=_json(result)
            self.original.settings['live_reference_strategy']=code
            self.original.settings['live_reference_capital']=result['capital']
            self.original.save_settings()
        elif action=='export':
            path=Path(params['path']).expanduser().resolve()
            path.mkdir(parents=True,exist_ok=True)
            if group=='original':
                self.original.export(identity,path);files=sorted(str(p) for p in path.iterdir() if p.is_file())
            elif group=='top5':files=[self.top5.export_account(identity,path)['path']]
            else:
                if path.is_dir():path=path/('七组合账户_'+identity[:8]+'.json')
                elif path.suffix.lower()!='.json':path=path.with_suffix('.json')
                self.seven.export_account(identity,path);files=[str(path)]
            result=dict(group=group,files=files,path=str(path))
        elif action=='import':
            progress('正在核验备份并恢复为独立副本…')
            if group=='original':identity=self.original.import_backup(params['path'])['id']
            elif group=='top5':identity=self.top5.import_account(params['path'])['account']['id']
            else:identity=self.seven.import_account(params['path'])['id']
            result=self.account(group,identity)
        elif action=='history_export':
            path=Path(params['path']).expanduser().resolve();self.original.export_history(path)
            result=dict(files=sorted(str(p) for p in path.iterdir() if p.is_file()),path=str(path))
        elif action=='quotes_export':
            path=Path(params['path']).expanduser().resolve()
            path.mkdir(parents=True,exist_ok=True)
            path=path/'已采集的30分钟报价.csv'
            path.parent.mkdir(parents=True,exist_ok=True);count=self.live.store.export(path)
            result=dict(files=[str(path)],batches=count,path=str(path))
        else:raise ValueError('不支持的操作：'+str(action))
        return _json(result)
