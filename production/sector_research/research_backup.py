"""Independent research-store backup; no SimpleETF account or credential access.

Call only after the service is closed. Its StoreLease is held during backup;
busy persisted states and a changed source inventory/hash are also rejected.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import gzip
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import uuid
import zipfile

if __package__:
    from .store_lock import StoreLease
else:
    from store_lock import StoreLease

SCHEMA='sector-research-backup.v1'
SEED_FILES=('market.json','index_data.json','verified_actions.json','calendar_2026.json')
MAX_FILES=100000
MAX_TOTAL=8*1024**3


def _hash(path):
    with Path(path).open('rb') as stream: return _stream_hash(stream)


def _stream_hash(stream):
    digest=hashlib.sha256()
    for block in iter(lambda:stream.read(1024*1024),b''): digest.update(block)
    return digest.hexdigest()


def _decode(raw):
    def pairs(values):
        output={}
        for key,value in values:
            if key in output: raise ValueError('JSON清单存在重复键')
            output[key]=value
        return output
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda x:(_ for _ in ()).throw(ValueError('无效JSON数字')))


def _read(path): return _decode(Path(path).read_text('utf-8-sig'))
def _encoded(value): return json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,indent=2).encode('utf8')


def _safe_name(name):
    if not isinstance(name,str) or not name or '\\' in name or ':' in name or '\x00' in name: raise ValueError('非法归档路径')
    p=PurePosixPath(name)
    if p.is_absolute() or p.as_posix()!=name or any(part in ('','.','..') or part.endswith((' ','.')) for part in p.parts): raise ValueError('归档路径越界或不规范')
    if any(ord(c)<32 or c in '<>"|?*' for c in name): raise ValueError('归档路径含非法字符')
    if any(re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?',part,re.I) for part in p.parts): raise ValueError('保留设备名不能作为归档路径')
    return p.parts


def _linked(path):
    return path.is_symlink() or (hasattr(path,'is_junction') and path.is_junction())


def _allowed_store_path(name):
    parts=_safe_name(name)
    if parts==('settings.json',): return True
    if parts[0]=='jobs':
        return len(parts)==3 and bool(re.fullmatch('[a-f0-9]{32}',parts[1])) and (parts[2]=='job.json' or bool(re.fullmatch(r'[A-Z0-9_]+\.json\.gz',parts[2])))
    if parts[0]=='market':
        if len(parts)==2 and parts[1] in ('current.json','status.json'): return True
        return len(parts)>=4 and parts[1] in ('versions','attempts') and bool(re.fullmatch('[A-Za-z0-9_-]+',parts[2]))
    return False


def _snapshot(store):
    if not store.is_dir() or _linked(store): raise ValueError('备份来源必须是独立研究目录，不能是链接')
    inventory={};seen=set()
    for current,dirs,files in os.walk(store,followlinks=False):
        parent=Path(current)
        for name in dirs+files:
            if _linked(parent/name): raise ValueError('研究目录不能包含符号链接或目录联接')
        relative=parent.relative_to(store)
        if relative==Path('.'):
            stable_files={name for name in files if not name.endswith(('.lock','.tmp','.part'))}
            if set(dirs)-{'market','jobs'} or stable_files-{'settings.json'}: raise ValueError('不是独立研究store：发现未知顶层文件或目录')
        if relative==Path('market'):
            if set(dirs)-{'versions','attempts','staging'}: raise ValueError('行情store包含未知目录')
            dirs[:]=[d for d in dirs if d!='staging']
        for name in files:
            # Atomic-write leftovers and advisory locks are not recoverable data.
            if name.endswith(('.lock','.tmp','.part')): continue
            p=parent/name;rel=p.relative_to(store).as_posix()
            if not _allowed_store_path(rel): raise ValueError('研究store包含未知文件：'+rel)
            if rel.casefold() in seen: raise ValueError('文件路径大小写冲突')
            seen.add(rel.casefold())
            inventory[rel]={'sha256':_hash(p),'size':p.stat().st_size}
    if len(inventory)>MAX_FILES or sum(v['size'] for v in inventory.values())>MAX_TOTAL: raise ValueError('研究备份超过允许大小')
    return dict(sorted(inventory.items()))


def _validate_idle(store,inventory):
    settings=store/'settings.json'
    if settings.exists() and not isinstance(_read(settings).get('automatic_updates'),bool): raise ValueError('研究设置无效')
    status=store/'market/status.json'
    if not status.exists():
        history=(store/'market/current.json').exists() or any(
            (store/'market'/name).is_dir() and any((store/'market'/name).iterdir())
            for name in ('versions','attempts','staging'))
        if history: raise ValueError('已有更新记录却缺少状态文件，不能清除可能的待核验队列后备份')
    if status.exists():
        value=_read(status)
        if value.get('running') or value.get('state') in ('running','queued','updating'): raise ValueError('行情更新仍在运行，请完成后备份')
    for relative in inventory:
        if relative.startswith('jobs/') and relative.endswith('/job.json'):
            job=_read(store/relative)
            if job.get('id')!=PurePosixPath(relative).parts[1]: raise ValueError('任务ID不一致')
            if job.get('state') in ('running','queued'): raise ValueError('历史研究仍在运行，请完成后备份')
            if job.get('state') not in ('succeeded','failed','cancelled'): raise ValueError('未知研究任务状态')
            if job['state']=='succeeded':
                runs=job.get('result',{}).get('runs')
                if not isinstance(runs,list) or not runs: raise ValueError('完成任务缺少结果清单')
                for run in runs:
                    model=run.get('model','')
                    if not re.fullmatch('[A-Z0-9_]+',model): raise ValueError('非法研究模型结果名')
                    result=(store/relative).parent/(model+'.json.gz')
                    if not result.is_file() or _hash(result)!=run.get('compressed_sha256'): raise ValueError('已完成研究结果缺失或哈希不一致')
                    with gzip.open(result,'rb') as stream:
                        if _stream_hash(stream)!=run.get('result_sha256'): raise ValueError('研究结果解压后哈希不一致')
    current=store/'market/current.json'
    if current.exists():
        pointer=_read(current);generation=pointer.get('generation','')
        if not re.fullmatch('[A-Za-z0-9_-]+',generation): raise ValueError('无效已发布版本指针')
        base=store/'market/versions'/generation;manifest=base/'manifest.json'
        if not manifest.is_file() or _hash(manifest)!=pointer.get('manifest_sha256'): raise ValueError('已发布版本清单缺失或损坏')
        value=_read(manifest);files=value.get('files',{})
        if value.get('generation')!=generation or not set(SEED_FILES).issubset(files): raise ValueError('已发布版本缺少必需行情文件')
        for relative,expected in files.items():
            _safe_name(relative)
            item=base/relative
            if not item.is_file() or _hash(item)!=expected: raise ValueError('已发布版本文件缺失或损坏')


@contextmanager
def _update_lock(store):
    """Use the updater's existing advisory lock if present; never make one."""
    path=store/'market/update.lock';handle=None
    try:
        if path.exists():
            if _linked(path): raise ValueError('不能读取链接锁文件')
            handle=path.open('r+b')
            try:
                if os.name=='nt':
                    import msvcrt
                    handle.seek(0);msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            except OSError as exc: raise ValueError('行情更新锁仍被占用') from exc
        yield
    finally:
        if handle is not None: handle.close()


def backup_store(store_dir,destination_zip,*,seed_dir=None):
    store=Path(store_dir).absolute();destination=Path(destination_zip).absolute()
    if _linked(store): raise ValueError('来源不能是链接')
    if _linked(destination): raise ValueError('备份目标不能是链接')
    store=store.resolve();destination=destination.resolve()
    if destination==store or store in destination.parents: raise ValueError('备份ZIP必须放在研究store之外')
    if destination.exists(): raise ValueError('备份目标已存在，不覆盖已有文件')
    destination.parent.mkdir(parents=True,exist_ok=True)
    temporary=destination.with_name(destination.name+'.'+uuid.uuid4().hex+'.part')
    try:
        # Validate the folder's narrow research scope before creating a lease
        # file. An accidental account-home path must receive no writes.
        _snapshot(store)
        with StoreLease(store), _update_lock(store):
            before=_snapshot(store);_validate_idle(store,before)
            sources={'store/'+rel:store/rel for rel in before}
            if 'market/current.json' not in before:
                seed=Path(seed_dir) if seed_dir is not None else Path(__file__).resolve().parent/'data'
                if not seed.is_dir() or _linked(seed): raise ValueError('首次资料版本缺少配套种子行情')
                for name in SEED_FILES:
                    p=seed/name
                    if not p.is_file() or _linked(p): raise ValueError('配套种子行情不完整')
                    _read(p)
                    sources['seed_data/'+name]=p
            entries={name:{'sha256':_hash(p),'size':p.stat().st_size} for name,p in sources.items()}
            manifest={'schema':SCHEMA,'created_utc':datetime.now(timezone.utc).isoformat(),'files':entries,
                      'seed_embedded':any(p.startswith('seed_data/') for p in entries),
                      'initial_store_without_status':'market/status.json' not in before,
                      'scope':'Research data versions, source receipts, settings and research jobs only. No original accounts or credentials.'}
            with zipfile.ZipFile(temporary,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as archive:
                for name,p in sources.items(): archive.write(p,name)
                archive.writestr('manifest.json',_encoded(manifest))
            after=_snapshot(store);_validate_idle(store,after)
            if after!=before or any(_hash(p)!=entries[name]['sha256'] or p.stat().st_size!=entries[name]['size'] for name,p in sources.items()): raise ValueError('复制期间研究目录发生变化，已拒绝不一致备份')
            # Verify compressed content rather than trusting only source hashes.
            _verify_archive(temporary)
            os.link(temporary,destination) # Atomic publication, fails if target exists.
        return {'status':'PASS','schema':SCHEMA,'archive':str(destination),'sha256':_hash(destination),
                'file_count':len(entries),'seed_embedded':manifest['seed_embedded'],
                'boundary':'恢复只还原独立研究资料；不是原模拟账户备份。'}
    finally:
        temporary.unlink(missing_ok=True)


def _verify_archive(path):
    with zipfile.ZipFile(path) as archive:
        infos=archive.infolist();names=[i.filename for i in infos]
        if len(names)>MAX_FILES+5 or len({n.casefold() for n in names})!=len(names): raise ValueError('归档存在重复路径或文件过多')
        total=0
        for info in infos:
            _safe_name(info.filename)
            mode=(info.external_attr>>16)&0o170000
            if info.is_dir() or mode==stat.S_IFLNK or mode not in (0,stat.S_IFREG) or info.flag_bits&1: raise ValueError('归档包含链接、目录或加密条目')
            total+=info.file_size
        if total>MAX_TOTAL or 'manifest.json' not in names or archive.getinfo('manifest.json').file_size>32*1024**2: raise ValueError('归档清单缺失或大小异常')
        manifest=_decode(archive.read('manifest.json').decode('utf8'))
        entries=manifest.get('files')
        if manifest.get('schema')!=SCHEMA or not isinstance(entries,dict) or set(names)!=set(entries)|{'manifest.json'}: raise ValueError('归档文件与清单不完整匹配')
        seed=[]
        for name,expected in entries.items():
            parts=_safe_name(name)
            if parts[0]=='store' and len(parts)>1:
                if not _allowed_store_path('/'.join(parts[1:])): raise ValueError('归档包含非研究store文件')
            elif parts[0]=='seed_data' and len(parts)==2 and parts[1] in SEED_FILES: seed.append(parts[1])
            else: raise ValueError('归档包含未知数据区域')
            info=archive.getinfo(name)
            if not isinstance(expected,dict) or expected.get('size')!=info.file_size or not re.fullmatch('[a-f0-9]{64}',str(expected.get('sha256',''))): raise ValueError('归档项清单无效')
            with archive.open(info) as stream:
                if _stream_hash(stream)!=expected['sha256']: raise ValueError('归档文件哈希不一致')
        has_current='store/market/current.json' in entries
        if has_current and seed or not has_current and set(seed)!=set(SEED_FILES) or bool(seed)!=manifest.get('seed_embedded'): raise ValueError('初始行情或已发布行情指针不完整')
        initial_without_status='store/market/status.json' not in entries
        if manifest.get('initial_store_without_status') is not initial_without_status: raise ValueError('初始状态来源声明缺失或不一致')
        if initial_without_status and (has_current or any(n.startswith(('store/market/versions/','store/market/attempts/')) for n in entries)):
            raise ValueError('已有更新记录却缺少状态文件，不能推断待核验队列为空')
        return manifest


def restore_store(zip_path,new_empty_store_dir):
    archive=Path(zip_path).resolve();target=Path(new_empty_store_dir).absolute()
    if _linked(target) or target.exists() and (not target.is_dir() or any(target.iterdir())): raise ValueError('恢复只允许全新空目录，不能覆盖现有研究或原账户')
    target=target.resolve();target.parent.mkdir(parents=True,exist_ok=True)
    archive_hash=_hash(archive)
    manifest=_verify_archive(archive)
    stage=Path(tempfile.mkdtemp(prefix='.research-restore-',dir=target.parent))
    assert stage.resolve().parent==target.parent and stage.name.startswith('.research-restore-')
    try:
        with zipfile.ZipFile(archive) as source:
            for name,expected in manifest['files'].items():
                parts=PurePosixPath(name).parts
                if parts[0]=='store': output=stage.joinpath(*parts[1:])
                else: output=stage/'market/versions/backup_seed'/parts[1]
                output.parent.mkdir(parents=True,exist_ok=True)
                with source.open(name) as incoming,output.open('xb') as outgoing: shutil.copyfileobj(incoming,outgoing,1024*1024)
                if _hash(output)!=expected['sha256']: raise ValueError('恢复过程中归档发生变化')
        generated=[]
        if manifest['seed_embedded']:
            base=stage/'market/versions/backup_seed'
            version={'schema':'sector-data-version.v1','generation':'backup_seed','kind':'restored_initial_seed',
                     'files':{name:_hash(base/name) for name in SEED_FILES},'backup_created_utc':manifest['created_utc']}
            (base/'manifest.json').write_bytes(_encoded(version))
            (stage/'market/current.json').write_bytes(_encoded({'schema':'sector-data-pointer.v1','generation':'backup_seed','manifest_sha256':_hash(base/'manifest.json')}))
            generated=['market/versions/backup_seed/manifest.json','market/current.json']
            if manifest['initial_store_without_status']:
                initial_status={'schema':'sector-data-update.status.v1','running':False,'automatic_enabled':False,
                                'state':'not_checked','message':'从未更新初始种子恢复，尚未联网核对',
                                'generation':'backup_seed','pending_review':[], 'sources':[],
                                'last_attempt_at':None,'last_success_at':None,'publication_blocked':False}
                (stage/'market/status.json').write_bytes(_encoded(initial_status))
                generated.append('market/status.json')
        inventory=_snapshot(stage);_validate_idle(stage,inventory)
        if _hash(archive)!=archive_hash: raise ValueError('恢复过程中归档发生变化')
        if target.exists():
            if _linked(target) or any(target.iterdir()): raise ValueError('恢复目标在操作期间已不为空')
            target.rmdir() # Only the explicitly checked empty target directory.
        os.rename(stage,target)
        return {'status':'PASS','archive_sha256':archive_hash,'restored_to':str(target),
                'file_count':len(inventory),'generated_seed_pointer_files':generated,'files':inventory,
                'boundary':'仅独立研究store；程序仍须使用经过核验的兼容模块代码。'}
    finally:
        if stage.exists():
            assert stage.resolve().parent==target.parent and stage.name.startswith('.research-restore-')
            shutil.rmtree(stage)


def main():
    parser=argparse.ArgumentParser(description='独立研究store备份或恢复，不含原交易账户')
    sub=parser.add_subparsers(dest='action',required=True)
    backup=sub.add_parser('backup');backup.add_argument('store');backup.add_argument('zip');backup.add_argument('--seed-dir')
    restore=sub.add_parser('restore');restore.add_argument('zip');restore.add_argument('empty_store')
    args=parser.parse_args()
    receipt=backup_store(args.store,args.zip,seed_dir=args.seed_dir) if args.action=='backup' else restore_store(args.zip,args.empty_store)
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
