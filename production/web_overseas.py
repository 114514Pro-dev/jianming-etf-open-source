"""Independent RMB cross-border ETF accounts; immutable data and isolated engines.

Business methods are called only by the web Runtime's serialized executor.
This module never connects to a broker. Research data is a separately dated asset.
"""
from pathlib import Path
from copy import deepcopy
from datetime import date, timedelta
from concurrent.futures import ThreadPoolExecutor
import hashlib, json, math, os, re, subprocess, sys, tempfile, time, uuid
from urllib.parse import urlencode
from intraday import LiveStore, fetch_quotes, now
from simulator_core import write_json
from web_market_revisions import RevisionGuard, POLICY as REVISION_POLICY

ASSETS=Path(__file__).resolve().parent/'overseas_assets'
MARKETS={
 'nasdaq':dict(symbol='sh513100',name='纳指100',fund='国泰纳指100 ETF',url='https://www.gtfund.com/product/productlist/haiwai/513100/index.html'),
 'hangseng':dict(symbol='sz159920',name='恒生指数',fund='华夏恒生ETF',url='https://fund.chinaamc.com/fund/159920/'),
 'hangtech':dict(symbol='sh513180',name='恒生科技',fund='华夏恒生科技ETF',url='https://f.chinaamc.com/fund/513180/jijinjingli.shtml')}
NAMES={v['symbol']:v['fund'] for v in MARKETS.values()}|{'sh512800':'银行ETF','sh518880':'黄金ETF','sh511010':'国债ETF'}
TITLES={'D5':'动态强弱 · 5%偏离调仓','DW':'动态强弱 · 周线调仓','D0':'动态强弱 · 每日调仓',
 'F0':'分阶段配置 · 股票底仓0%','F10':'分阶段配置 · 股票底仓10%','F20':'分阶段配置 · 股票底仓20%',
 'L0':'四态融合 · 股票底仓0%','L10':'四态融合 · 股票底仓10%','L20':'四态融合 · 股票底仓20%',
 'T5VOTE':'目标ETF · 三信号投票','T5WEEK':'目标ETF · 周线固定持有20日','T5DON':'目标ETF · 唐奇安突破',
 'T5SUPER':'目标ETF · 超级趋势','T5MA':'目标ETF · 均线',
 'A_T5VOTE_P2':'投票择时＋黄金 · 独立本金','A_T5VOTE_P3':'投票择时＋银行＋黄金 · 独立本金',
 'A_T5SUPER_P3':'超级趋势＋银行＋黄金 · 独立本金','B_D7':'日线组合 D7','B_D5':'日线组合 D5','B_D4':'日线组合 D4','B_D6':'日线组合 D6'}
SCHEMA='simpleetf.overseas.account.v1'
NOTE='人民币场内跨境ETF；收盘确认后推进模拟，小时策略仍按真实小时顺序重放。费用万三/最低5元，滑点万二，期末按市值计价。'
def read(path):return json.loads(Path(path).read_text('utf-8-sig'))
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def check_stop(stop):
    if stop is not None and stop.is_set():raise InterruptedError('已停止，既有海外账户记录保留。')
def metrics(r):
    m=r['metrics']
    return dict(m,**{'return':m['total_return'],'annualized':m['cagr'],'drawdown':m['max_drawdown'],
        'equity':m['final_equity'],'trades':m['fills'],'trade_unit':'成交笔数'})
def merge(old,new,key,fields):
    known={r[key]:r for r in old};last=old[-1][key]
    if not new or new[0][key]>last:raise ValueError('行情窗口没有重叠，拒绝跳过历史缺口。')
    for row in new:
        k=row[key]
        if k<=last:
            if k not in known:raise ValueError('历史缺口出现新数据，需独立核验后接入：'+k)
            for field in fields:
                if not math.isclose(float(row[field]),float(known[k][field]),rel_tol=1e-8,abs_tol=1e-7):
                    raise ValueError('来源修订了历史 '+k+' '+field+'；保留原快照与账户。')
        else:known[k]=row
    return [known[k] for k in sorted(known)]

class OverseasService:
    def __init__(self,folder):
        self.folder=Path(folder)/'海外专区';self.folder.mkdir(exist_ok=True,parents=True)
        for name in ('snapshots','accounts','scratch'):(self.folder/name).mkdir(exist_ok=True)
        self.settings=read(self.folder/'settings.json') if (self.folder/'settings.json').exists() else {}
        if not self.settings.get('snapshot'):
            self.settings['snapshot']=self.store(read(ASSETS/'seed.json'));self.save_settings()
        self.snapshot=self.load_snapshot(self.settings['snapshot'])
        self.store_quotes=LiveStore(self.folder);self.batch=self.store_quotes.latest()
        self.warnings={};self.cache={}
        self.research_summary=read(ASSETS/'research-summary.json');self.errors={g:[] for g in MARKETS}
    @property
    def research(self):
        # Curves are requested separately; startup and account refresh only need
        # the existing compact summary, not all historical research portfolios.
        return read(ASSETS/'research.json')
    def save_settings(self):write_json(self.folder/'settings.json',self.settings)
    def store(self,snap):
        sid=digest(snap);p=self.folder/'snapshots'/(sid+'.json')
        if not p.exists():write_json(p,snap)
        return sid
    def load_snapshot(self,sid):
        if not re.fullmatch('[a-f0-9]{64}',str(sid)):raise ValueError('行情快照编号错误')
        snap=read(self.folder/'snapshots'/(sid+'.json'))
        if digest(snap)!=sid:raise ValueError('海外行情快照校验失败')
        return snap
    def end(self,group,snap=None):
        snap=snap or self.snapshot;codes=[MARKETS[group]['symbol'],'sh512800','sh518880','sh511010']
        dates=[]
        for c in codes:
            ds=snap['datasets'][c]
            daily={x['date'] for x in ds['bars']};hourly={x['datetime'][:10] for x in ds['hourly'] if x['datetime'].endswith('15:00:00')}
            dates.append(daily&hourly)
        return max(set.intersection(*dates))
    def catalog(self):
        out=[]
        for g,m in MARKETS.items():
            base=[r for r in self.research_summary['markets'][m['symbol']] if r['variant']=='base' and r['strategy'] in TITLES]
            best=max(r['metrics']['cagr'] for r in base);low=min(r['metrics']['max_drawdown'] for r in base)
            badges={r['strategy']:(' · 研究年化最高' if r['metrics']['cagr']==best else '')+(' · 研究回撤最低' if r['metrics']['max_drawdown']==low else '') for r in base}
            out.append(dict(id=g,name=m['name']+' · 海外',start='2023-01-03',end=self.end(g),overseas=True,
                strategies=[dict(code=c,label=c+' '+n+badges[c],description=NOTE,earliest='2023-01-03') for c,n in TITLES.items()]))
        return out
    def overview(self):
        quotes=(self.batch or {}).get('quotes',{})
        return dict(markets=[dict(m,id=g,end=self.end(g),quote=quotes.get(m['symbol']),
                    reference=self.settings.get('references',{}).get(g),warning=self.warnings.get(g),
                    account_count=len(list((self.folder/'accounts'/g).glob('*.json')))) for g,m in MARKETS.items()],
            received_at=(self.batch or {}).get('received_at'),quote_warning=self.warnings.get('quotes'),
            research_as_of=self.research_summary['as_of'],rules=NOTE,
            notes=['多资产策略包含黄金、银行或国债贡献，不能视为纯目标ETF择时收益。',
                '境内人民币ETF按境内交易时段报价；不等于美股或港股本地ETF，海外休市、汇率和溢价可能影响价格。',
                '原研究不是未见样本外验证。历史溢价/NAV时间资料不完整，未模拟溢价过滤、排队与大额冲击。'] +
                ([REVISION_POLICY] if self.snapshot.get('history_revisions', {}).get('retained_history_count') else []))
    def quotes(self,stop=None,progress=lambda _:None):
        check_stop(stop);progress('读取纳指、恒生指数、恒生科技报价…')
        try:
            batch=fetch_quotes([m['symbol'] for m in MARKETS.values()],NAMES)
            check_stop(stop);self.store_quotes.save(batch);self.batch=batch;self.warnings.pop('quotes',None)
            return dict(ok=True,received_at=batch['received_at'])
        except InterruptedError:raise
        except Exception as e:self.warnings['quotes']=str(e);return dict(ok=False,error=str(e))
    def _fetch_dataset(self,c,limit):
        from chinext_refresh_support import _capture,parse_tencent_daily,parse_sina_hourly,TENCENT_URL,SINA_URL
        import bear_gold as gold,bear_gold_assets as assets
        cal=self.snapshot['calendar'];sessions=set(cal['sessions']);through=cal['verified_through'];moment=now()
        url=TENCENT_URL+'?'+urlencode({'param':f'{c},day,,{limit},640,'})
        raw,meta=_capture('腾讯未复权日线',url)
        payload=json.loads(raw.decode('utf-8-sig'));payload['data']['sz159915']=payload['data'][c]
        daily,_=parse_tencent_daily(json.dumps(payload).encode(),moment,sessions,through)
        daily=[dict(date=r['date'],open=r['open'],high=r['high'],low=r['low'],close=r['close'],volume_lots=r['volume']/100,amount_cny=r['amount']) for r in daily if r['date']<=limit]
        hr,hmeta=_capture('新浪未复权小时线',SINA_URL.replace('sz159915',c))
        hourly,_=parse_sina_hourly(hr,moment,sessions,through);hourly=[r for r in hourly if r['datetime'][:10]<=limit]
        actions=gold.parse_actions(assets.read_html('https://fundf10.eastmoney.com/fhsp_'+c[2:]+'.html'))
        # Corporate actions require the same disclosure semantics as the frozen study.
        for key in ('dividends','splits'):
            if actions[key]!=self.snapshot['datasets'][c]['actions'][key]:
                raise ValueError(NAMES[c]+'分红/拆分披露发生变化，需先核验，保留快照。')
        return daily,hourly,[meta,hmeta]
    def refresh(self,limit,stop=None,progress=lambda _:None,force=False):
        if not limit:return dict(ok=False,error='没有可确认交易日期')
        if not force and all(self.end(g)>=limit for g in MARKETS):return dict(ok=True,unchanged=True)
        progress('核验海外ETF及防御资产的完整日线、小时线和公司行动…')
        codes=list(self.snapshot['datasets']);incoming={};errors={}
        with ThreadPoolExecutor(max_workers=4) as pool:
            futures={c:pool.submit(self._fetch_dataset,c,limit) for c in codes}
            for c,f in futures.items():
                check_stop(stop)
                try:incoming[c]=f.result()
                except Exception as e:errors[c]=str(e)
        # One observation per instrument/interval, even when three groups share
        # defensive assets. Save the audit before publishing any group's data.
        guard=RevisionGuard(self.folder,now(),self.settings['snapshot'])
        normalized={}
        for c,(daily,hourly,sources) in incoming.items():
            try:
                old=self.snapshot['datasets'][c]
                d=guard.retain(old['bars'],daily,'date',['open','high','low','close','volume_lots'],c,sources)
                h=guard.retain(old['hourly'],hourly,'datetime',['open','high','low','close','volume'],c,sources)
                normalized[c]=(d,h,sources)
            except (ValueError,KeyError,TypeError) as e:errors[c]=str(e)
        try:
            revision_metadata=guard.finish(allow_pending=True)
        except ValueError as e:
            # An unwritable audit never promotes any normalized row.
            for g in MARKETS:self.warnings[g]=str(e)
            return dict(ok=False,ends={g:self.end(g) for g in MARKETS},errors=dict(self.warnings))
        for item in revision_metadata['pending']:
            errors[item['symbol']]='来源历史修订等待至少60秒后的相同观测；旧值与账户保留：'+item['time']
        snap=deepcopy(self.snapshot);changed=False
        for g,m in MARKETS.items():
            required=[m['symbol'],'sh512800','sh518880','sh511010']
            try:
                if any(c in errors for c in required):raise ValueError('; '.join(errors[c] for c in required if c in errors))
                prepared={}
                for c in required:
                    d=deepcopy(self.snapshot['datasets'][c]);daily,hourly,sources=normalized[c]
                    d['bars']=merge(d['bars'],daily,'date',['open','high','low','close','volume_lots'])
                    d['hourly']=merge(d['hourly'],hourly,'datetime',['open','high','low','close','volume'])
                    previous=self.end(g);newdays={r['date'] for r in daily if previous<r['date']<=limit}
                    expected={v for v in snap['calendar']['sessions'] if previous<v<=limit}
                    if newdays!=expected:raise ValueError(NAMES[c]+'新增日线仍缺交易日，等待来源补齐。')
                    if any(day+' 15:00:00' not in {r['datetime'] for r in hourly} for day in expected):raise ValueError(NAMES[c]+'缺少收盘小时柱，等待完整数据。')
                    d['asof']=d['bars'][-1]['date'];d['sources']=sources;prepared[c]=d
                snap['datasets'].update(prepared);self.warnings.pop(g,None);changed=True
            except (ValueError,KeyError,TypeError) as e:self.warnings[g]=str(e)
        check_stop(stop)
        if changed:
            snap['history_revisions']=revision_metadata
            settings=dict(self.settings,snapshot=self.store(snap))
            write_json(self.folder/'settings.json',settings)
            self.snapshot=snap;self.settings=settings;self.cache.clear()
            for g,p in list(self.settings.get('references',{}).items()):
                check_stop(stop)
                if p.get('as_of','')[:10]<self.end(g):
                    try:self.reference(g,p['strategy'],p['capital'],stop,progress)
                    except (ValueError,RuntimeError) as e:self.warnings[g]='参考更新失败：'+str(e)
        return dict(ok=not bool(self.warnings),ends={g:self.end(g) for g in MARKETS},errors=dict(self.warnings),
                    history_revisions=revision_metadata,notes=[REVISION_POLICY] if revision_metadata['retained_history_count'] else [])
    def run(self,group,strategies,start,end,capital,stop=None,progress=lambda _:None,sid=None):
        if group not in MARKETS or not strategies or any(c not in TITLES for c in strategies):raise ValueError('海外市场或策略无效')
        amount=float(capital)
        if not math.isfinite(amount) or not 1000<=amount<=1e9:raise ValueError('本金应为1000到10亿元')
        sid=sid or self.settings['snapshot'];snap=self.snapshot if sid==self.settings['snapshot'] else self.load_snapshot(sid)
        sessions=snap['calendar']['sessions'];date.fromisoformat(start);date.fromisoformat(end)
        if start not in sessions or end not in sessions or not '2023-01-03'<=start<=end<=self.end(group,snap):raise ValueError('请选择2023-01-03起、已有完整数据的交易日')
        key=(sid,group,tuple(strategies),start,end,amount)
        if key in self.cache:return deepcopy(self.cache[key])
        with tempfile.TemporaryDirectory(dir=self.folder/'scratch') as tmp:
            req=Path(tmp)/'request.json';out=Path(tmp)/'result.json';log=Path(tmp)/'worker.log'
            write_json(req,dict(target=MARKETS[group]['symbol'],strategies=strategies,start=start,end=end,capital=amount,snapshot_path=str(self.folder/'snapshots'/(sid+'.json'))))
            progress('海外独立计算：'+MARKETS[group]['name']+' / '+', '.join(strategies))
            with log.open('w',encoding='utf8') as err:
                proc=subprocess.Popen([sys.executable,str(Path(__file__).with_name('overseas_worker.py')),str(req),str(out)],stdout=err,stderr=err,
                    creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                started=time.monotonic()
                try:
                    while proc.poll() is None:
                        check_stop(stop)
                        if time.monotonic()-started>900:raise ValueError('海外策略计算超时')
                        time.sleep(.15)
                finally:
                    if proc.poll() is None:proc.terminate();proc.wait(timeout=10)
            if proc.returncode!=0:raise ValueError('海外计算失败：'+log.read_text('utf8')[-1800:])
            result=read(out)
        check_stop(stop)
        for r in result:r['snapshot']=sid
        if len(self.cache)>12:self.cache.clear()
        self.cache[key]=result;return deepcopy(result)
    def reference(self,g,code,capital,stop=None,progress=lambda _:None):
        r=self.run(g,[code],'2023-01-03',self.end(g),capital,stop,progress)[0]
        weights=r.get('next_target',{});amount=r['capital']
        p=dict(available=True,group=g,strategy=code,label=code+' '+TITLES[code],capital=amount,as_of=r['end']+' 15:00:00',
            computed_at=now().isoformat(),weights=weights,budgets={c:amount*w for c,w in weights.items()},cash=amount*max(0,1-sum(weights.values())),
            notes=[r.get('reference_note','按已确认收盘信号计算下一执行时点目标。'),NOTE,'独立预算参考，不是账户实际持仓。'])
        self.settings.setdefault('references',{})[g]=p;self.save_settings();return p
    def _path(self,g,identity):
        if g not in MARKETS or not re.fullmatch('[a-f0-9]{32}',str(identity)):raise ValueError('海外账户编号错误')
        return self.folder/'accounts'/g/(identity+'.json')
    def get(self,g,identity):
        a=read(self._path(g,identity));h=a.pop('integrity',None)
        if h!=digest(a) or a['schema']!=SCHEMA or a['group']!=g or a['id']!=identity:raise ValueError('海外账户完整性校验失败')
        return a
    def save(self,a):
        check=dict(a);check.pop('integrity',None);check['integrity']=digest(check)
        p=self._path(a['group'],a['id']);p.parent.mkdir(exist_ok=True);write_json(p,check)
    def summary(self,a):
        r=a['result'];m=metrics(r)
        return dict(id=a['id'],name=a['name'],group=a['group'],strategy=r['strategy'],strategy_label=r['strategy']+' '+TITLES[r['strategy']],
            start=r['start'],day=r['end'],capital=r['capital'],equity=m['equity'],cash=r['curve'][-1]['cash'],market_end=self.end(a['group']),
            **{k:m[k] for k in ['return','annualized','drawdown','fees','trades','trade_unit']})
    def accounts(self,g):
        rows=[];self.errors[g]=[]
        for p in sorted((self.folder/'accounts'/g).glob('*.json')):
            try:rows.append(self.summary(self.get(g,p.stem)))
            except (OSError,ValueError,KeyError,TypeError) as e:self.errors[g].append(dict(id=p.stem,error=str(e)))
        return rows
    def account(self,g,identity):
        from web_account_decision import result_decision
        a=self.get(g,identity);r=a['result'];qty=r.get('final_positions',{});target=MARKETS[g]['symbol']
        if r['strategy'].startswith('A_'):
            qty={}
            for c,leg in r['leg_states'].items():qty[c]=leg['shares'] if 'shares' in leg else leg['qty'][0]
        elif r['strategy'].startswith('B_'):qty=dict(zip([target,'sh512800','sh518880'],r['leg_states']['last_close']['qty']))
        positions=[dict(symbol=c,name=NAMES[c],qty=v,price=r['prices'][c],market_value=v*r['prices'][c]) for c,v in qty.items()]
        events=[dict(e,time=e.get('time',e.get('date')),type='成交',qty=e.get('qty',e.get('quantity'))) for e in r['events']]
        return dict(id=identity,group=g,summary=self.summary(a),metrics=metrics(r),positions=positions,curve=r['curve'],events=events,event_count=len(events),
            advice=dict(title='已确认日线参考',text=r.get('reference_note',NOTE),weights=r.get('next_target',{}),notes=['独立账户，不跨市场调仓；下一执行时点前目标不代表已成交。']),
            notes=[NOTE],attribution=r.get('attribution',[]),decision=result_decision(r,target))
    def candidates(self):
        out=[]
        for g in MARKETS:
            for a in self.accounts(g):
                target=self.end(g);allowed=target>a['day'] and not self.warnings.get(g)
                out.append(dict(group=g,id=a['id'],current=a['day'],target=target,can_advance=bool(allowed),reason=self.warnings.get(g) or ('等待确认数据推进' if allowed else '已到本市场最新确认日')))
        return out
    def execute(self,action,p,stop=None,progress=lambda _:None):
        g=p['group'];identity=p.get('id')
        if action=='reference':return self.reference(g,p['strategy'],p.get('capital',100000),stop,progress)
        if action=='compare':
            rs=self.run(g,list(TITLES),p['start'],p['end'],p.get('capital',100000),stop,progress)
            return dict(group=g,start=rs[0]['start'],end=rs[0]['end'],capital=rs[0]['capital'],completed=True,skipped=[],
                rows=[dict(code=r['strategy'],label=r['strategy']+' '+TITLES[r['strategy']],**metrics(r)) for r in rs],
                curves={r['strategy']:r['curve'] for r in rs},notes=[NOTE,'所有21种使用相同区间、本金和期末市值口径；多资产与目标ETF择时仍需区分。'],
                attribution={r['strategy']:r.get('attribution',[]) for r in rs})
        if action=='create':
            name=p.get('name','')
            if not isinstance(name,str) or not 1<=len(name.strip())<=80:raise ValueError('账户名称应为1到80字')
            r=self.run(g,[p['strategy']],p['start'],p['start'],p.get('capital',100000),stop,progress)[0]
            a=dict(schema=SCHEMA,id=uuid.uuid4().hex,name=name.strip(),group=g,created=now().isoformat(),result=r);check_stop(stop);self.save(a);identity=a['id']
        elif action in {'advance','auto_advance'}:
            a=self.get(g,identity);old=a['result'];end=self.end(g) if action=='auto_advance' else p['end']
            if p.get('expected_day') is not None and p['expected_day']!=old['end']:raise ValueError('账户日期已变化，请刷新')
            if end<old['end']:raise ValueError('持续账户不能倒退')
            if action=='auto_advance' and self.warnings.get(g):return dict(group=g,id=identity,advanced=False,reason=self.warnings[g])
            if end>old['end']:
                r=self.run(g,[old['strategy']],old['start'],end,old['capital'],stop,progress)[0]
                if [x for x in r['curve'] if x['date']<=old['end']]!=old['curve'] or [x for x in r['events'] if x.get('time',x.get('date'))[:10]<=old['end']]!=old['events']:
                    raise ValueError('重放与已有记录不一致，拒绝改写历史成交')
                check_stop(stop);a['result']=r;self.save(a)
            if action=='auto_advance':return dict(group=g,id=identity,previous=old['end'],day=end,advanced=end>old['end'])
        elif action=='export':
            a=self.get(g,identity);path=Path(p['path']);path.mkdir(exist_ok=True,parents=True);file=path/('海外账户_'+identity[:8]+'.json')
            write_json(file,dict(schema=SCHEMA,account=a,snapshot=self.load_snapshot(a['result']['snapshot'])))
            return dict(group=g,files=[str(file)],path=str(file))
        elif action=='import':
            path=Path(p['path'])
            if path.stat().st_size>100_000_000:raise ValueError('账户备份超过100MB')
            value=read(path)
            if value.get('schema')!=SCHEMA or value['account']['group']!=g:raise ValueError('请选择相同海外市场导出的账户JSON备份')
            a=value['account'];r=a['result'];snap=value['snapshot']
            if digest(snap)!=r['snapshot']:raise ValueError('备份行情校验失败')
            sid=self.store(snap);replay=self.run(g,[r['strategy']],r['start'],r['end'],r['capital'],stop,progress,sid)[0]
            if replay!=r:raise ValueError('备份重放与记录不一致，未恢复')
            a=deepcopy(a);a['id']=uuid.uuid4().hex;a['name']=str(a['name'])[:65]+'（导入）';check_stop(stop);self.save(a);identity=a['id']
        else:raise ValueError('海外账户不支持此操作')
        return self.account(g,identity)
