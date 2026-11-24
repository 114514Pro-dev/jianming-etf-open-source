"""Versioned research data and isolated, persistent historical calculation jobs.

No imports from SimpleETF's account bridge. One immutable data bundle is captured
per operation; published source updates cannot mutate an in-flight simulation.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import re
import secrets
import threading
import uuid

if __package__:
    from .core import Environment, SECTORS
    from .opportunity import Opportunity
    from .data_updater import DataUpdater
    from .store_lock import StoreLease
else:
    from core import Environment, SECTORS
    from opportunity import Opportunity
    from data_updater import DataUpdater
    from store_lock import StoreLease

VERSION = '2.0.0'
SCENARIOS = [
    {'id':'primary','name':'原费用：佣金万3／最低5元'},
    {'id':'double_cost','name':'佣金与滑点翻倍'},
    {'id':'extra_execution_day','name':'额外延迟一个交易日'},
    {'id':'no_minimum_commission','name':'取消最低佣金（比例费用与滑点保留）'},
]

def stamp(): return datetime.now(timezone.utc).isoformat()
def encode(value): return json.dumps(value,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
def read(path): return json.loads(path.read_text('utf-8-sig'))
def atomic_write(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    try:
        with temporary.open('wb') as f:
            f.write(encode(value));f.flush();os.fsync(f.fileno())
        os.replace(temporary,path)
    finally:
        if temporary.exists(): temporary.unlink()

def scalar(query,key,default=None):
    value=query.get(key,default)
    if isinstance(value,list):
        if len(value)!=1: raise ValueError('重复的查询参数：'+key)
        return value[0]
    return value

def finite_cash(value, name='本金', positive=True):
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
        raise ValueError(name+'须为有限数字')
    if value < 0 or (positive and value == 0) or value > 1_000_000_000_000:
        raise ValueError(name+'须大于0且不超过1万亿元')
    from decimal import Decimal
    if Decimal(str(value)).quantize(Decimal('.01')) != Decimal(str(value)):
        raise ValueError(name+'最多两位小数')
    return value

class Bundle:
    def __init__(self,path,resource_root):
        self.env=Environment(path)
        self.opportunity=Opportunity(self.env)
        self.path=Path(path)
        algorithms={}
        for relative in ['contract.json','opportunity_contract.json','capital_contract.json']:
            p=resource_root/relative
            if p.exists(): algorithms[relative]=hashlib.sha256(p.read_bytes()).hexdigest()
        self.version=hashlib.sha256(encode(self.env._hashes)).hexdigest()
        self.algorithm_version=hashlib.sha256(encode({'contracts':algorithms,'version':VERSION})).hexdigest()
        self._capital=None
        self._capital_init_lock=threading.RLock()
        self.capital_lock=threading.RLock()

    def capital(self):
        with self._capital_init_lock:
            if self._capital is None:
                if __package__:
                    from .capital_engine import CapitalResearch
                else:
                    from capital_engine import CapitalResearch
                self._capital=CapitalResearch(self.env,self.opportunity)
            return self._capital

class ResearchService:
    def __init__(self,resource_root,store_dir,auto_update=True,seed_data_dir=None):
        self.root=Path(resource_root).resolve()
        self.store=Path(store_dir).resolve()
        self.store.mkdir(parents=True,exist_ok=True)
        self._lease=StoreLease(self.store)
        try:
            self._initialize(auto_update,seed_data_dir)
        except Exception:
            if hasattr(self,'updater'):
                self.updater.close() if hasattr(self.updater,'close') else self.updater.stop()
            if hasattr(self,'_executor'): self._executor.shutdown(wait=True)
            self._lease.close()
            raise

    def _initialize(self,auto_update,seed_data_dir):
        self.token=secrets.token_urlsafe(32)
        self._lock=threading.RLock()
        self._jobs_lock=threading.RLock()
        self._lifecycle_lock=threading.RLock()
        self._closed=False
        self._shutdown_lock=threading.RLock()
        self._shutdown_active=False
        self._shutdown_complete=False
        self._executor=ThreadPoolExecutor(max_workers=1,thread_name_prefix='sector-research')
        self._jobs={}
        self.settings={'automatic_updates':bool(auto_update)}
        self.settings_error=None
        settings_path=self.store/'settings.json'
        if settings_path.exists():
            try:
                saved=read(settings_path)
                if not isinstance(saved,dict) or not isinstance(saved.get('automatic_updates'),bool): raise ValueError('invalid setting')
                self.settings={'automatic_updates':saved['automatic_updates']}
            except (ValueError,OSError) as exc:
                self.settings_error='设置文件无法读取，已暂停自动更新；可手动重新设置。'
                self.settings={'automatic_updates':False}
        if not auto_update: self.settings['automatic_updates']=False
        self.updater=DataUpdater(seed_data_dir or self.root/'data',self.store/'market',
                                 validator=self._validate_candidate,on_publish=self._on_publish)
        self._bundle=Bundle(self.updater.active_data_dir,self.root)
        self.recovery_warnings=[]
        self._recover_jobs()
        if self.settings['automatic_updates']: self.updater.start(1800)

    def _validate_candidate(self,path):
        # Action validity, calendar, economic continuity and no fabrication.
        # Capital construction is lazy; previews/backtests refuse unsupported dates.
        Bundle(path,self.root)

    def _on_publish(self,path):
        candidate=Bundle(path,self.root)
        with self._lock: self._bundle=candidate

    def _capture(self):
        with self._lock: return self._bundle

    def _tag(self,value,bundle):
        result=deepcopy(value)
        result['data_version']=bundle.version
        result['runtime']={'automatic_updates':self.settings['automatic_updates'],
                           'data_status_url':'/api/data-status',
                           'version':VERSION,'algorithm_version':bundle.algorithm_version,
                           'snapshot_is_published_version':True}
        return result

    def _recover_jobs(self):
        job_dir=self.store/'jobs'
        job_dir.mkdir(exist_ok=True)
        for p in job_dir.glob('*/job.json'):
            try:
                value=read(p)
                if not self._valid_job_record(value,p.parent.name):
                    raise ValueError('invalid saved job structure')
                if value['state'] in ('running','queued'):
                    value.update(state='failed',error='程序上次退出时计算尚未完成；请重新运行。',finished_at=stamp())
                    atomic_write(p,value)
                if value['state']=='succeeded':
                    intact=all((p.parent/(r['model']+'.json.gz')).is_file() and
                        hashlib.sha256((p.parent/(r['model']+'.json.gz')).read_bytes()).hexdigest()==r['compressed_sha256']
                        for r in value['result']['runs'])
                    if not intact:
                        value.update(state='failed',error='已保存结果缺失或校验不一致，请重新计算。')
                        atomic_write(p,value)
                self._jobs[value['id']]=value
            except (KeyError,ValueError,OSError,TypeError):
                # Never turn a corrupt record into a completed result.
                self.recovery_warnings.append(p.parent.name+'：已跳过无法校验的研究记录，可重新计算。')
                continue

    @staticmethod
    def _valid_job_record(value,job_id):
        if not isinstance(value,dict) or value.get('id')!=job_id or not re.fullmatch(r'[a-f0-9]{32}',job_id): return False
        if value.get('state') not in ('queued','running','succeeded','failed'): return False
        for key in ('created_at','data_version','algorithm_version'):
            if not isinstance(value.get(key),str) or not value[key]: return False
        request=value.get('request');progress=value.get('progress')
        if not isinstance(request,dict) or not isinstance(progress,dict): return False
        models=request.get('models')
        if not isinstance(models,list) or not 1<=len(models)<=7 or any(not isinstance(m,str) or not re.fullmatch('[A-Z0-9_]+',m) for m in models): return False
        if len(set(models))!=len(models): return False
        if any(not isinstance(request.get(k),str) for k in ('start','end','scenario')): return False
        try: finite_cash(request.get('capital'))
        except ValueError: return False
        if type(progress.get('completed')) is not int or type(progress.get('total')) is not int: return False
        if progress['total']!=len(models) or not 0<=progress['completed']<=progress['total']: return False
        if value['state']=='succeeded':
            result=value.get('result')
            if not isinstance(result,dict) or not isinstance(result.get('runs'),list): return False
            runs=result['runs']
            if len(runs)!=len(models) or any(not isinstance(r,dict) for r in runs): return False
            if [r.get('model') for r in runs]!=models: return False
            for run in runs:
                if not isinstance(run.get('metrics'),dict) or not isinstance(run.get('curve'),list): return False
                if type(run.get('trade_count')) is not int or run['trade_count']<0: return False
                for key in ('compressed_sha256','result_sha256'):
                    if not isinstance(run.get(key),str) or not re.fullmatch('[a-f0-9]{64}',run[key]): return False
        return True

    def _job_save(self,value):
        atomic_write(self.store/'jobs'/value['id']/'job.json',value)

    def _job_read(self,job_id):
        if not re.fullmatch(r'[a-f0-9]{32}',job_id): raise ValueError('无效任务编号')
        with self._jobs_lock:
            if job_id not in self._jobs: raise ValueError('未找到这次历史模拟')
            return deepcopy(self._jobs[job_id])

    def _run_job(self,job_id,bundle):
        try:
            with self._jobs_lock:
                job=self._jobs[job_id]
                job.update(state='running',started_at=stamp());self._job_save(job)
                request=deepcopy(job['request'])
            runs=[]
            with bundle.capital_lock:
                engine=bundle.capital()
                for model in request['models']:
                    with self._jobs_lock:
                        self._jobs[job_id]['progress']['model']=model
                        self._job_save(self._jobs[job_id])
                    value=engine.backtest(model,request['start'],request['end'],request['capital'],request['scenario'])
                    economic=value.get('result',value)
                    portfolio=economic['portfolio']
                    peak=float(request['capital'])
                    curve=[]
                    for row in portfolio['curve']:
                        peak=max(peak,row['equity'])
                        curve.append({k:row.get(k) for k in ['date','equity','cash','exposure']}|{'drawdown':1-row['equity']/peak})
                    result_dir=self.store/'jobs'/job_id
                    result_dir.mkdir(parents=True,exist_ok=True)
                    result_file=result_dir/(model+'.json.gz')
                    raw=encode(value)
                    compressed=gzip.compress(raw,mtime=0)
                    tmp=result_file.with_suffix('.gz.tmp')
                    with tmp.open('wb') as f:
                        f.write(compressed);f.flush();os.fsync(f.fileno())
                    os.replace(tmp,result_file)
                    runs.append({'model':model,'metrics':portfolio['metrics'],'curve':curve,
                                 'trade_count':len(portfolio['trades']),
                                 'result_sha256':hashlib.sha256(raw).hexdigest(),
                                 'compressed_sha256':hashlib.sha256(compressed).hexdigest(),
                                 'warnings':value.get('warnings',[])})
                    with self._jobs_lock:
                        self._jobs[job_id]['progress']['completed']=len(runs)
                        self._job_save(self._jobs[job_id])
            with self._jobs_lock:
                job=self._jobs[job_id]
                complete=deepcopy(job)
                complete.update(state='succeeded',finished_at=stamp(),result={'runs':runs})
                self._job_save(complete) # Publish persisted success before in-memory success.
                self._jobs[job_id]=complete
        except Exception as exc:
            with self._jobs_lock:
                failed=deepcopy(self._jobs[job_id])
                failed.update(state='failed',error=f'{type(exc).__name__}: {exc}',finished_at=stamp())
                self._jobs[job_id]=failed
                try: self._job_save(failed)
                except OSError: failed['persistence_error']='失败状态未能写入磁盘，已有账户未操作。'

    def _submit(self,payload,bundle):
        if set(payload)-{'models','start','end','capital','scenario'}: raise ValueError('历史模拟存在未知参数')
        request=deepcopy(payload)
        selected=request.get('models')
        metadata=bundle.capital().models()
        allowed={m['id'] for m in metadata['models']}
        if not isinstance(selected,list) or not 1<=len(selected)<=7 or any(not isinstance(m,str) for m in selected) or len(set(selected))!=len(selected) or any(m not in allowed for m in selected):
            raise ValueError('请选择1至7个不重复的已知模型')
        for key in ['start','end']:
            if request.get(key) not in bundle.env.dates(): raise ValueError('回测起止日必须为可选交易日')
        if request['start']>request['end']: raise ValueError('起始日不能晚于结束日')
        request['capital']=finite_cash(request.get('capital'))
        if float(request['capital']).is_integer(): request['capital']=int(request['capital'])
        request.setdefault('scenario','primary')
        if request['scenario'] not in {s['id'] for s in SCENARIOS}: raise ValueError('未知费用或执行场景')
        identity={'request':request,'data_version':bundle.version,'algorithm_version':bundle.algorithm_version}
        job_id=hashlib.sha256(json.dumps(identity,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()[:32]
        with self._jobs_lock:
            if self._closed: raise ValueError('服务正在关闭，请重新启动后再计算')
            existing=self._jobs.get(job_id)
            if existing and existing['state'] in ('queued','running','succeeded'):
                return {'id':job_id,'state':existing['state'],'data_version':bundle.version,'deduplicated':True}
            if sum(j['state'] in ('queued','running') for j in self._jobs.values())>=3:
                raise ValueError('已有三个历史计算在进行，请稍后再提交')
            job={'id':job_id,'state':'queued','created_at':stamp(),'data_version':bundle.version,'algorithm_version':bundle.algorithm_version,
                 'request':request,'progress':{'completed':0,'total':len(selected),'model':None}}
            self._job_save(job)
            self._jobs[job_id]=job
            try: self._executor.submit(self._run_job,job_id,bundle)
            except RuntimeError:
                job.update(state='failed',error='服务正在关闭');self._job_save(job)
                raise ValueError('服务正在关闭，请重新启动后再计算')
        return {'id':job_id,'state':'queued','data_version':bundle.version,'deduplicated':False}

    def _full_result(self,job_id,model):
        with self._lifecycle_lock:
            if self._closed: raise ValueError('服务正在关闭')
            return self._read_full_result(job_id,model)

    def _read_full_result(self,job_id,model):
        job=self._job_read(job_id)
        if job['state']!='succeeded': raise ValueError('历史模拟尚未成功完成')
        match=next((r for r in job['result']['runs'] if r['model']==model),None)
        if match is None: raise ValueError('本次没有此模型结果')
        path=self.store/'jobs'/job_id/(model+'.json.gz')
        try:
            compressed=path.read_bytes()
            if hashlib.sha256(compressed).hexdigest()!=match['compressed_sha256']: raise ValueError('结果文件校验不一致')
            raw=gzip.decompress(compressed)
            if hashlib.sha256(raw).hexdigest()!=match['result_sha256']: raise ValueError('结果内容校验不一致')
            result=json.loads(raw)
        except (OSError,ValueError,EOFError) as exc:
            with self._jobs_lock:
                failed=deepcopy(self._jobs[job_id])
                failed.update(state='failed',error='已保存结果无法核验：'+str(exc),finished_at=stamp())
                self._jobs[job_id]=failed
                self._job_save(failed)
            raise ValueError('已保存结果无法核验，请重新计算：'+str(exc)) from exc
        return {'job_id':job_id,'data_version':job['data_version'],'request':job['request'],'result':result}

    def dispatch_get(self,path,query):
        if path=='/api/runtime':
            return {'version':VERSION,'csrf_token':self.token,'account_operations':False,
                    'persistent_research_results':True,'settings_error':self.settings_error,
                    'recovery_warnings':list(self.recovery_warnings)}
        if path=='/api/data-status':
            return self.updater.status()|{'data_version':self._capture().version,'settings_error':self.settings_error}
        if path=='/api/capital/jobs':
            with self._jobs_lock:
                jobs=[deepcopy({k:v for k,v in job.items() if k!='result'}) for job in self._jobs.values()]
            return {'jobs':sorted(jobs,key=lambda j:j['created_at'],reverse=True)[:40]}
        job=re.fullmatch(r'/api/capital/jobs/([a-f0-9]{32})(/result)?',path)
        if job:
            return self._full_result(job[1],scalar(query,'model')) if job[2] else self._job_read(job[1])
        bundle=self._capture()
        as_of=scalar(query,'as_of')
        if path=='/api/health':
            return {'ok':True,'version':VERSION,'read_only':False,'account_read_only':True,
                    'automatic_market_download':self.settings['automatic_updates'],'data_version':bundle.version}
        if path=='/api/dates': return self._tag({'dates':bundle.env.dates()},bundle)
        if path in ('/api/market-regime','/api/export'): return self._tag(bundle.env.snapshot(as_of=as_of),bundle)
        if path=='/api/history':
            limit=int(scalar(query,'limit','252'))
            if not 1<=limit<=5000: raise ValueError('limit必须在1至5000之间')
            return self._tag({'rows':bundle.env.history(as_of=as_of,limit=limit)},bundle)
        if path in ('/api/sector-opportunities','/api/sector-export'):
            return self._tag(bundle.opportunity.snapshot(as_of=as_of),bundle)
        if path=='/api/sector-history':
            return self._tag(bundle.opportunity.history(scalar(query,'code',''),as_of=as_of,limit=int(scalar(query,'limit','252'))),bundle)
        contract={'/api/contract':'contract.json','/api/opportunity-contract':'opportunity_contract.json','/api/capital/contract':'capital_contract.json'}
        if path in contract: return read(self.root/contract[path])
        if path=='/api/capital/meta':
            metadata=bundle.capital().models()
            current=bundle.env.snapshot()
            return self._tag(metadata|{'sectors':[{'code':c,'name':n} for c,n in SECTORS],
                   'dates':bundle.env.dates(),'default_end':metadata.get('data_as_of',current['snapshot_date']),
                   'freshness':current['freshness'],'cost_scenarios':SCENARIOS},bundle)
        return None

    def dispatch_post(self,path,body):
        with self._lifecycle_lock:
            if self._closed: raise ValueError('服务正在关闭')
            return self._dispatch_post(path,body)

    def _dispatch_post(self,path,body):
        if not isinstance(body,dict): raise ValueError('请求内容必须为JSON对象')
        if self._closed: raise ValueError('服务正在关闭')
        if path=='/api/data-update':
            if body: raise ValueError('手动行情检查不接受额外参数')
            return self.updater.request_update('manual')|{'data_version':self._capture().version}
        if path=='/api/data-settings':
            if set(body)!={'enabled'} or not isinstance(body['enabled'],bool): raise ValueError('enabled必须为布尔值')
            settings={'automatic_updates':body['enabled']}
            atomic_write(self.store/'settings.json',settings)
            self.settings=settings;self.settings_error=None
            result=self.updater.start(1800) if body['enabled'] else self.updater.stop()
            return result|{'data_version':self._capture().version}
        bundle=self._capture()
        if path=='/api/capital/backtest': return self._submit(body,bundle)
        if path=='/api/capital/preview':
            allowed={'model','cash','positions','as_of','execution_prices','sleeve_cash','initialized','entitlements','receivables'}
            if set(body)-allowed: raise ValueError('持仓预演存在未知参数')
            with bundle.capital_lock: result=bundle.capital().preview(**body)
            return self._tag({'schema':'sector-capital.preview-response.v1','input':deepcopy(body),'result':result},bundle)
        raise ValueError('不支持此研究操作')

    def import_reviewed_package(self,path):
        # Trusted local CLI/administrator integration only; not a remotely supplied path.
        with self._lifecycle_lock:
            if self._closed: raise ValueError('服务正在关闭')
            return self.updater.import_reviewed_package(path)

    @property
    def shutdown_complete(self):
        return self._shutdown_complete

    def _shutdown_threads(self):
        # These owners are part of the verified updater/executor contract.
        # A missing member is an unverified shutdown, never proof of no worker.
        return [self.updater._scheduler,self.updater._worker,self.updater._run_thread,
                *tuple(self._executor._threads)]

    def close(self):
        with self._lifecycle_lock,self._jobs_lock:
            # Admission closes immediately and stays closed even after failure.
            self._closed=True
        current=threading.current_thread()
        # Reject before waiting for the coordinator lock: another close may be
        # waiting for this very worker to return from its callback.
        if any(thread is current for thread in self._shutdown_threads()):
            raise RuntimeError('行业研究工作线程不能确认自身已退出')
        with self._shutdown_lock:
            if self._shutdown_complete: return
            if self._shutdown_active:
                raise RuntimeError('行业研究关闭回调不能重入关闭流程')
            self._shutdown_active=True
            try:
                errors=[]
                try:
                    self.updater.close() if hasattr(self.updater,'close') else self.updater.stop()
                except BaseException as exc:
                    errors.append(exc)
                try:
                    self._executor.shutdown(wait=True,cancel_futures=False)
                except BaseException as exc:
                    errors.append(exc)
                try:
                    for thread in self._shutdown_threads():
                        if thread is not None and thread.is_alive():
                            errors.append(RuntimeError('行业研究后台线程仍在运行；保留资料目录锁'))
                except BaseException as exc:
                    errors.append(exc)
                if errors: raise errors[0]
                # A failure above must leave both the lease and retry path intact.
                self._lease.close()
                self._shutdown_complete=True
            finally:
                self._shutdown_active=False
