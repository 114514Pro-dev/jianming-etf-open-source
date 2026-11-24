"""Background model board, independent of the serialized account writer.

Only immutable market inputs cross the boundary. One child at a time, latest
input wins per group, persisted results and bounded retries survive restarts.
"""
from pathlib import Path
from copy import deepcopy
from datetime import datetime,timezone,timedelta
import hashlib,json,os,subprocess,sys,threading,time,logging

ROOT=Path(__file__).resolve().parent
CN=timezone(timedelta(hours=8))
LOG=logging.getLogger('etfweb.signals')
GROUPS=('original','top5','seven','nasdaq','hangseng','hangtech')


def stamp():return datetime.now(CN).isoformat(timespec='seconds')
def digest(data):return hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()).hexdigest()
def write(path,data):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,allow_nan=False),encoding='utf8');os.replace(tmp,path)


def valid_rows(rows, codes=None):
    if not isinstance(rows,list) or not rows:return False
    try:
        json.dumps(rows,allow_nan=False)
        seen=[]
        for row in rows:
            if not isinstance(row,dict):return False
            if not isinstance(row.get('code'),str) or not row['code']:return False
            seen.append(row['code'])
            if row.get('status') not in {'buy','sell','rebalance','hold','cash','wait'}:return False
            if not isinstance(row.get('reasons'),list) or not row['reasons'] or not all(isinstance(x,str) and x for x in row['reasons']):return False
            datetime.fromisoformat(row['as_of'])
            for field in ('positions','weights'):
                if not isinstance(row.get(field),dict):return False
                if not all(isinstance(k,str) and isinstance(v,(int,float)) and not isinstance(v,bool) and v>=0 for k,v in row[field].items()):return False
            if not isinstance(row.get('intents'),list):return False
            for item in row['intents']:
                if not isinstance(item,dict) or not isinstance(item.get('symbol'),str) or item.get('action') not in ('buy','sell') or not isinstance(item.get('reason'),str):return False
            for field in ('rule','execution'):
                if not isinstance(row.get(field),str) or not row[field]:return False
            from web_signal_activity import valid_activity
            if not valid_activity(row.get('activity'),row['as_of']):return False
        return len(seen)==len(set(seen)) and (codes is None or set(seen)==set(codes))
    except (ValueError,TypeError,KeyError):return False


def freshness(row, group, moment, sessions, through):
    """Confirmed-bar age, separate from cache completion. Five minutes for hourly publication."""
    moment=moment.astimezone(CN);today=moment.date().isoformat()
    if not sessions or not through or today>through:
        return dict(source_status='unknown',source_warning='交易日历尚未覆盖当前日期，行情时效待核对。')
    hourly=group=='top5' or (group=='seven' and row['code'].startswith('A_'))
    eligible=sorted(d for d in sessions if d<=today)
    expected=None
    for day in reversed(eligible):
        if hourly:
            for clock in ('15:00:00','14:00:00','11:30:00','10:30:00'):
                t=datetime.fromisoformat(day+' '+clock).replace(tzinfo=CN)
                if moment>=t+timedelta(minutes=5):expected=day+' '+clock;break
        elif day<today or (moment.hour,moment.minute)>=(16,10):expected=day
        if expected:break
    actual=str(row.get('as_of') or '').replace('T',' ')
    stale=bool(expected and actual[:19 if hourly else 10]<expected)
    return dict(source_status='stale' if stale else 'confirmed',expected_end=expected,
                source_warning=('行情尚未跟上应确认周期 '+str(expected)+'；保留旧依据，等待后台补齐。' if stale else None))


class SignalBoard:
    def __init__(self,folder,timeout=900):
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True)
        self.timeout=timeout;self.lock=threading.RLock();self.wake=threading.Event();self.halt=threading.Event()
        self._child=None;self._child_lock=threading.Lock();self._close_lock=threading.Lock()
        self._shutdown_complete=False
        self.desired={};self.results={};self.errors={};self.retry={};self.active=None;self.checked_at=None
        h=hashlib.sha256(b'signal-board-v1')
        for p in sorted(ROOT.rglob('*.py')):h.update(p.relative_to(ROOT).as_posix().encode());h.update(p.read_bytes())
        self.version=h.hexdigest()
        try:
            from chinext_refresh_support import _read_calendar
            self.sessions,self.through,_=_read_calendar()
        except (OSError,ValueError,TypeError,KeyError):self.sessions=set();self.through=None
        try:
            saved=json.loads((self.folder/'results.json').read_text('utf8'))
            if isinstance(saved,dict) and saved.get('version')==self.version and isinstance(saved.get('groups'),dict):
                for group,record in saved['groups'].items():
                    if group not in GROUPS or not isinstance(record,dict):continue
                    if not all(isinstance(record.get(k),str) and record[k] for k in ('key','snapshot','computed_at')):continue
                    if valid_rows(record.get('rows')) and record.get('checksum')==digest(record['rows']):self.results[group]=record
        except (OSError,ValueError,TypeError,KeyError):pass
        self.thread=threading.Thread(target=self.run,name='readonly-strategy-board',daemon=True);self.thread.start()

    def offer(self,bridge):
        # Called only by the unique business executor after its confirmed refresh.
        snapshots={'original':bridge.original.market.hash,'top5':bridge.top5.settings['snapshot_id'],
                   'seven':bridge.seven.settings['snapshot'],**{g:bridge.overseas.settings['snapshot'] for g in GROUPS[3:]}}
        catalog={g['id']:g for g in bridge.catalog()['groups']}
        for group in GROUPS:
            meta=catalog[group];key=digest([self.version,group,snapshots[group],meta['end']])
            with self.lock:
                if self.desired.get(group,{}).get('key')==key:continue
            if group=='original':data=bridge.original.market.data
            elif group=='top5':data=bridge.top5._snapshot()
            elif group=='seven':data=bridge.seven.snapshot()
            else:data=bridge.overseas.snapshot
            path=self.folder/(group+'-'+key+'.json')
            request=dict(group=group,snapshot=snapshots[group],strategies=[s['code'] for s in meta['strategies']],end=meta['end'])
            if group in GROUPS[3:]:
                from web_overseas import MARKETS
                # One immutable market snapshot shared by all overseas requests.
                sp=self.folder/('overseas-'+snapshots[group]+'.json')
                with self.lock:
                    if not sp.exists():write(sp,data)
                request.update(target=MARKETS[group]['symbol'],start='2023-01-03',capital=100000,
                               snapshot_path=str(sp),signal_board=True)
            else:request['data']=data
            with self.lock:
                if not path.exists():write(path,request)
                self.desired[group]=dict(key=key,path=str(path),catalog=deepcopy(meta),snapshot=snapshots[group])
                if group in self.results and not valid_rows(self.results[group].get('rows'),request['strategies']):self.results.pop(group)
                self.errors.pop(group,None);self.retry.pop(group,None)
        with self.lock:self.checked_at=stamp()
        self.wake.set()

    def snapshot(self):
        with self.lock:
            rows=[];groups=[]
            for group in GROUPS:
                wanted=self.desired.get(group)
                if not wanted:continue
                saved=self.results.get(group,{})
                current=(saved.get('key')==wanted['key'] and valid_rows(saved.get('rows'),[s['code'] for s in wanted['catalog']['strategies']]))
                prior={r['code']:r for r in saved.get('rows',[])}
                error=self.errors.get(group)
                groups.append(dict(id=group,name=wanted['catalog']['name'],ready=current,error=error,as_of=saved.get('computed_at')))
                for strategy in wanted['catalog']['strategies']:
                    row=deepcopy(prior.get(strategy['code'],dict(status='wait',label='等待计算',reasons=['后台正在独立计算该模型，完成后自动显示。'])))
                    name=strategy['label'].split('【')[0].replace(' · 研究年化最高','').replace(' · 研究回撤最低','').strip()
                    row.update(group=group,group_name=wanted['catalog']['name'],code=strategy['code'],name=name,
                               current=current,computed_at=saved.get('computed_at'),snapshot=saved.get('snapshot'),
                               latest_known_end=wanted['catalog']['end'])
                    if not current and row.get('as_of'):
                        row.update(previous_status=row['status'],status='wait',label='等待更新 · 旧信号')
                    if row.get('as_of'):
                        row.update(freshness(row,group,datetime.now(CN),self.sessions,self.through))
                        if row['source_status']!='confirmed':
                            row.update(previous_status=row.get('previous_status',row['status']),status='wait',label='等待行情更新' if row['source_status']=='stale' else '等待日历核对')
                    if error:row['error']=error
                    rows.append(row)
            return dict(rows=rows,groups=groups,active=self.active,checked_at=self.checked_at,server_time=stamp(),
                        ready=sum(bool(r['current']) for r in rows),stale=sum(r.get('source_status')=='stale' for r in rows),total=len(rows),reference_start='2023-01-03',reference_capital=100000,
                        note='全部模型用2023-01-03起、初始10万元的独立只读参考组合跟踪持有期；不读取或改动你的账户。不同建户日期、本金和持仓可能产生不同操作。只用已确认K线；成交动态是上述模型已发生的模拟记录，待买入/待卖出是尚未成交的下一步意向。')

    def run(self):
        while not self.halt.is_set():
            self.wake.wait(2);self.wake.clear()
            with self.lock:
                pending=[(g,deepcopy(v)) for g,v in self.desired.items()
                         if self.results.get(g,{}).get('key')!=v['key'] and time.monotonic()>=self.retry.get(g,0)]
            for group,wanted in pending:
                if self.halt.is_set():return
                with self.lock:
                    if self.desired[group]['key']!=wanted['key']:continue
                    self.active=group
                output=self.folder/(group+'-output.json');log=self.folder/(group+'-worker.log');proc=None
                try:
                    output.unlink(missing_ok=True)
                    script='overseas_worker.py' if group in GROUPS[3:] else 'web_signal_worker.py'
                    with log.open('w',encoding='utf8') as err:
                        with self._child_lock:
                            if self.halt.is_set():raise InterruptedError('服务停止')
                            if self._child is not None:
                                self.request_stop()
                                raise RuntimeError('上一模型子进程尚未确认退出')
                            # Publish directly: cleanup/retry must retain this handle
                            # even when a process-control operation raises.
                            self._child=subprocess.Popen([sys.executable,str(ROOT/script),wanted['path'],str(output)],stdout=err,stderr=err,
                                                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                            proc=self._child
                        deadline=time.monotonic()+self.timeout
                        while proc.poll() is None:
                            if self.halt.wait(.2):raise InterruptedError('服务停止')
                            if time.monotonic()>deadline:raise TimeoutError('该组模型计算超时，稍后自动重试。')
                    if proc.returncode:raise ValueError('模型计算失败：'+log.read_text('utf8')[-600:])
                    rows=json.loads(output.read_text('utf8'))
                    if not valid_rows(rows,[s['code'] for s in wanted['catalog']['strategies']]):raise ValueError('模型输出结构不完整')
                    with self.lock:
                        if self.desired[group]['key']!=wanted['key']:continue
                        candidate=dict(self.results)
                        candidate[group]=dict(key=wanted['key'],snapshot=wanted['snapshot'],computed_at=stamp(),rows=rows,checksum=digest(rows))
                        # A failed disk write must remain retryable, never look completed.
                        write(self.folder/'results.json',dict(version=self.version,groups=candidate))
                        self.results=candidate
                        self.errors.pop(group,None);self.retry.pop(group,None)
                except InterruptedError: return
                except Exception as e:
                    LOG.exception('Signal board group failed: %s',group)
                    with self.lock:
                        if self.desired[group]['key']==wanted['key']:
                            self.errors[group]='该组模型计算未完成，已保留此前结果；后台将在5分钟后重试。'
                            self.retry[group]=time.monotonic()+300
                finally:
                    try:
                        if not self._cleanup_child(time.monotonic()+10):
                            LOG.error('Signal child exit unconfirmed; board halted and handle retained')
                    finally:
                        with self.lock:self.active=None
                if self.halt.is_set():return
            # Input files can be large. Keep only current/active sources and the
            # latest overseas snapshot; these files contain no account data.
            with self.lock:
                keep={Path(v['path']).name for v in self.desired.values()}
                keep|={'overseas-'+v['snapshot']+'.json' for g,v in self.desired.items() if g in GROUPS[3:]}
                for p in self.folder.glob('*.json'):
                    try:
                        if p.name!='results.json' and p.name not in keep and time.time()-p.stat().st_mtime>1800:p.unlink(missing_ok=True)
                    except OSError:LOG.warning('Cannot clean signal cache: %s',p.name,exc_info=True)

    def request_stop(self):
        self.halt.set();self.wake.set()

    @property
    def shutdown_complete(self):
        # A live/stalled Popen may still own the publication lock. Confirmation
        # must fail closed immediately, not wait beyond a failed close timeout.
        if not self._child_lock.acquire(blocking=False):return False
        try:
            return bool(self._shutdown_complete and self.halt.is_set()
                        and not self.thread.is_alive() and self._child is None)
        finally:self._child_lock.release()

    def _confirm_child_exit(self,proc):
        try:
            if proc.poll() is None:return False
        except Exception:
            LOG.warning('Cannot confirm signal child exit',exc_info=True)
            return False
        with self._child_lock:
            if self._child is proc:self._child=None
        return True

    def _cleanup_child(self,deadline):
        # Only run owns process control while its thread is alive. close joins
        # that thread first, then serializes all retry attempts with _close_lock.
        with self._child_lock:proc=self._child
        if proc is None:return True
        try:
            if self._confirm_child_exit(proc):return True
            for operation in ('terminate','kill'):
                if time.monotonic()>=deadline:break
                try:
                    getattr(proc,operation)()
                    remaining=deadline-time.monotonic()
                    if remaining>0:proc.wait(timeout=min(5,remaining))
                except Exception:
                    LOG.warning('Cannot %s/wait signal child',operation,exc_info=True)
                # wait/terminate/kill returning is not exit evidence by itself.
                if self._confirm_child_exit(proc):return True
        except BaseException:
            self.request_stop()
            raise
        self.request_stop()
        return False

    def close(self,timeout=15):
        self.request_stop()
        if threading.current_thread() is self.thread:
            raise RuntimeError('Signal board cannot close from its own run thread')
        timeout=float(timeout)
        if not 0<=timeout<float('inf'):raise ValueError('timeout must be finite and non-negative')
        deadline=time.monotonic()+timeout
        if not self._close_lock.acquire(timeout=max(0,deadline-time.monotonic())):
            raise TimeoutError('Signal board close is still in progress')
        try:
            if self._shutdown_complete:return
            # Never hold _child_lock while joining: run needs it to publish and
            # reap its process. A live parent remains the sole cleanup owner.
            self.thread.join(timeout=max(0,deadline-time.monotonic()))
            if self.thread.is_alive():
                raise TimeoutError('Signal board thread has not stopped')
            if not self._cleanup_child(deadline):
                raise TimeoutError('Signal board child exit has not been confirmed')
            with self._child_lock:
                if self._child is not None or self.thread.is_alive():
                    raise TimeoutError('Signal board shutdown remains incomplete')
                self._shutdown_complete=True
        finally:
            self._close_lock.release()
