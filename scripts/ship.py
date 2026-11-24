"""Server-side committed-image activation with retained rollback and source verification."""
import copy
import gzip
import hashlib
import http.client
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import subprocess
import sys
import tarfile
import time
from urllib.parse import quote

def digest(file):
    value=hashlib.sha256()
    with file.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):value.update(chunk)
    return value.hexdigest()

def command(args):
    result=subprocess.run(args,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    if result.returncode: raise RuntimeError('Command failed: '+args[0]+' '+str(result.returncode))
    return result.stdout

def inspect(name): return json.loads(command(['docker','inspect',name]))[0]

def exported_image_ids(archive_path, config_digest):
    """Classic Docker identifies configs; containerd-backed Docker identifies manifests."""
    accepted={config_digest}
    with tarfile.open(archive_path,'r:gz') as archive:
        try:index=json.load(archive.extractfile('index.json'))
        except KeyError:return accepted
        pending=list(index.get('manifests',[]))
        visited=set()
        while pending:
            descriptor=pending.pop()
            digest_value=descriptor.get('digest','')
            if digest_value in visited:continue
            if len(visited)>=64 or not re.fullmatch('sha256:[a-f0-9]{64}',digest_value):
                raise ValueError('Unexpected exported image descriptor')
            visited.add(digest_value)
            member=archive.getmember('blobs/sha256/'+digest_value.split(':')[1])
            if member.size>1024*1024:raise ValueError('Oversized image manifest')
            body=archive.extractfile(member).read()
            if 'sha256:'+hashlib.sha256(body).hexdigest()!=digest_value:
                raise ValueError('Exported image manifest checksum mismatch')
            value=json.loads(body)
            if value.get('config',{}).get('digest')==config_digest:accepted.add(digest_value)
            pending.extend(value.get('manifests',[]))
    return accepted

class UnixHTTP(http.client.HTTPConnection):
    def connect(self):
        self.sock=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.connect('/var/run/docker.sock')

def engine(method,route,payload=None):
    connection=UnixHTTP('localhost')
    data=None if payload is None else json.dumps(payload).encode()
    connection.request(method,'/v1.45'+route,body=data,headers={'Content-Type':'application/json'})
    response=connection.getresponse();body=response.read();connection.close()
    if response.status>=300: raise RuntimeError('Docker engine operation failed: '+str(response.status)+' '+route)
    return json.loads(body) if body else None

def private_json(path,value):
    descriptor=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(descriptor,'w') as file:json.dump(value,file,indent=2)

def health(container,project,revision,timeout=240):
    route='/api/health' if project=='ai-tutor' else '/healthz'
    port=3000 if project=='ai-tutor' else 8000
    script=("fetch('http://127.0.0.1:%d%s',{signal:AbortSignal.timeout(4000)}).then(async r=>{if(!r.ok)process.exit(1);console.log(await r.text())}).catch(()=>process.exit(1))"%(port,route))
    began=time.monotonic()
    while time.monotonic()-began<timeout:
        args=['docker','exec',container,'node','-e',script] if project=='ai-tutor' else [
            'docker','exec',container,'python','-c',
            "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8000/healthz',timeout=4).read().decode())"]
        result=subprocess.run(args,capture_output=True,text=True)
        if result.returncode==0:
            data=json.loads(result.stdout)
            if data.get('revision')==revision and (data.get('ok') is True or data.get('status')=='ok'):return
        if not inspect(container)['State']['Running']:raise RuntimeError('Application exited during activation')
        time.sleep(2)
    raise RuntimeError('New application health/revision deadline exceeded')

def main():
    import fcntl

    os.umask(0o077)
    staging=Path(sys.argv[1]).resolve()
    receipt=json.loads((staging/'release.json').read_text())
    project=receipt['project'];ai=project=='ai-tutor';revision=receipt['gitRevision']
    if project not in ('ai-tutor','jianming-etf') or not re.fullmatch('[a-f0-9]{40}',revision):raise ValueError('Invalid release')
    expected_hostname=os.environ['ETF_DEPLOY_HOST']
    if socket.gethostname()!=expected_hostname or os.getuid()!=0:raise ValueError('Wrong deployment host')
    public_host=os.environ['ETF_DEPLOY_PUBLIC_HOST']
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]*', public_host):raise ValueError('Invalid public hostname')
    if digest(Path(__file__))!=receipt['shipScriptSha256']:raise ValueError('Deployment helper checksum mismatch')
    base=Path('/srv/ai-tutor' if ai else '/opt/simple-etf-web')
    if not base.is_dir() or base.is_symlink() or base.resolve()!=base or base.stat().st_uid!=0:
        raise ValueError('Unrecognized deployment base')
    canonical='cie-study-aliyun-app-1' if ai else 'simple-etf-web-app-1'
    compose_project='cie-study-aliyun' if ai else 'simple-etf-web'
    for filename,key in [('source.tar.gz','sourceSha256'),('image.tar.gz','imageArchiveSha256')]:
        if digest(staging/filename)!=receipt[key]:raise ValueError('Release archive checksum mismatch')
    print(json.dumps({'phase':'verified-artifacts','project':project,'revision':revision}),flush=True)
    command(['docker','load','-i',str(staging/'image.tar.gz')])
    image=inspect(receipt['imageTag'])
    expected_ids=exported_image_ids(staging/'image.tar.gz',receipt['imageId'])
    if image['Id'] not in expected_ids or image['Config']['Labels'].get('org.opencontainers.image.revision')!=revision:
        raise ValueError('Loaded image identity mismatch')
    built_image_id=receipt['imageId']
    receipt['imageId']=image['Id']
    if image['Config']['Labels'].get('io.project.source-archive-sha256')!=receipt['sourceSha256']:
        raise ValueError('Loaded image source digest mismatch')
    release=(base/'releases'/receipt['sourceSha256'][:16]) if ai else (base/('release-main-'+revision[:12]))
    if release.exists():raise ValueError('Fresh release directory required; do not overwrite an existing attempt')
    release.mkdir(parents=True,mode=0o700)
    with tarfile.open(staging/'source.tar.gz','r:gz') as archive:
        for item in archive.getmembers():
            p=PurePosixPath(item.name)
            if p.is_absolute() or '..' in p.parts or not (item.isfile() or item.isdir()):raise ValueError('Unsafe release member')
        archive.extractall(release,filter='data')
    manifest=json.loads((release/'release-manifest.json').read_text())
    if manifest['gitRevision']!=revision:raise ValueError('Manifest revision mismatch')
    for row in manifest['files']:
        p=release/row['path']
        if p.is_symlink() or p.stat().st_size!=row['bytes'] or digest(p)!=row['sha256']:raise ValueError('Source verification failed')
    (release/'verified-source-sha256.txt').write_text(receipt['sourceSha256']+'\n')
    old=inspect(canonical)
    if not old['State']['Running'] or old['Config']['Labels'].get('com.docker.compose.project')!=compose_project:
        raise ValueError('Expected active production application')
    private_json(staging/'rollback-inspect.private.json',old)
    if ai:
        current=Path((base/'current-release.path').read_text().strip())
        config=(current/'compose.env').read_text()
        config=re.sub(r'^STUDY_IMAGE=.*$', 'STUDY_IMAGE='+receipt['imageId'],config,flags=re.M)
        fd=os.open(release/'compose.env',os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w') as f:f.write(config)
        # The application schema is unchanged in this maintenance release.
        live=command(['docker','exec',canonical,'node','-e',
            'const fs=require("fs"),c=require("crypto");console.log(JSON.stringify(Object.fromEntries(fs.readdirSync("/srv/app/drizzle").filter(x=>x.endsWith(".sql")).map(x=>[x,c.createHash("sha256").update(fs.readFileSync("/srv/app/drizzle/"+x)).digest("hex")]))))'])
        expected={p.name:digest(p) for p in (release/'drizzle').glob('*.sql')}
        if json.loads(live)!=expected:raise ValueError('Unexpected database migration change')
    lock=open(base/'maintenance.lock','a+');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    ship_lock=open(base/'committed-release.lock','a+');fcntl.flock(ship_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    rollback_name=canonical+'-before-'+revision[:12]
    new_id=None;old_disconnected=False;renamed=False;proxy_original=None
    timer_was_enabled=ai and subprocess.run(['systemctl','is-enabled','--quiet','cie-study-backup-ai-tutor.timer']).returncode==0
    if timer_was_enabled:command(['systemctl','stop','cie-study-backup-ai-tutor.timer'])
    try:
        print(json.dumps({'phase':'consistent-backup','project':project}),flush=True)
        command(['docker','stop','--time','120',old['Id']])
        state=inspect(old['Id'])['State']
        if state['Running'] or state.get('OOMKilled') or state.get('ExitCode')==137:raise ValueError('Writers did not drain cleanly')
        if ai:
            backup=base/'backups'/('pre-main-'+revision[:12]+'.tar')
            report=backup.with_suffix('.json')
            value=json.loads(command([sys.executable,str(release/'scripts/aliyun-backup-data.py'),'--data-dir',str(base/'data'),
                '--offline','--output',str(backup),'--report',str(report)]))
            if set(value['databases'])!={'study.sqlite','auth.sqlite'} or any(x['integrity']!='ok' or x['foreignKeyViolations'] for x in value['databases'].values()):
                raise ValueError('Pre-release database backup validation failed')
            command(['docker','start',old['Id']])
            restored=base/'restore-checks'/('pre-main-'+revision[:12])
            command([sys.executable,str(release/'scripts/aliyun-restore-data.py'),'--archive',str(backup),
                '--destination',str(restored),'--report',str(staging/'isolated-restore.json')])
            restored_report=json.loads((staging/'isolated-restore.json').read_text())
            if restored_report.get('existingDataOverwritten') is not False or restored_report.get('serviceActivated') is not False:
                raise ValueError('Unexpected restore activation')
            command(['docker','stop','--time','120',old['Id']])
            if inspect(old['Id'])['State']['Running']:raise ValueError('Application still running')
        else:
            # A stopped-volume copy includes auth/runtime state; it remains root-private on this host.
            backup=base/'backups'/('pre-main-'+revision[:12]+'.tar.gz')
            backup.parent.mkdir(mode=0o700,exist_ok=True)
            volume=next(m['Source'] for m in old['Mounts'] if m['Destination']=='/data')
            if not volume.startswith('/var/lib/docker/volumes/'):raise ValueError('Unexpected ETF data volume')
            if backup.exists():raise ValueError('Existing pre-release backup refused')
            with tarfile.open(backup,'w:gz',compresslevel=3) as archive:archive.add(volume,arcname='data')
            os.chmod(backup,0o600)
            with tarfile.open(backup,'r:gz') as archive:
                for member in archive:
                    if member.isfile():
                        file=archive.extractfile(member)
                        for _ in iter(lambda:file.read(1024*1024),b''):pass
        if ai:
            proxy_file=base/'ip-https/caddy/Caddyfile'
            proxy_original=proxy_file.read_text()
            candidate=re.sub(r'(?m)^\s*header_up X-Cie-Proxy-Client-IP .*\n','',proxy_original)
            marker='reverse_proxy app:3000 {'
            if candidate.count(marker)!=1:raise ValueError('Unknown live reverse proxy structure')
            candidate=candidate.replace(marker,marker+'\n        header_up X-Cie-Proxy-Client-IP {remote_host}')
            pending=proxy_file.with_name('Caddyfile.main-'+revision[:12]);pending.write_text(candidate)
            command(['docker','exec','cie-study-aliyun-proxy-1','caddy','validate','--config','/etc/caddy/'+pending.name,'--adapter','caddyfile'])
            shutil.copy2(proxy_file,staging/'Caddyfile.before')
            os.replace(pending,proxy_file)
            command(['docker','exec','cie-study-aliyun-proxy-1','caddy','reload','--config','/etc/caddy/Caddyfile','--adapter','caddyfile'])
        networks={name:{'Aliases':['app',canonical]} for name in old['NetworkSettings']['Networks']}
        for name in networks:engine('POST','/networks/'+quote(name,safe='')+'/disconnect',{'Container':old['Id'],'Force':False})
        old_disconnected=True
        engine('POST','/containers/'+old['Id']+'/rename?name='+quote(rollback_name))
        renamed=True
        new=copy.deepcopy(old['Config'])
        for field in ['Hostname','Domainname','Image','Env','Cmd','Entrypoint','Labels','Healthcheck']:
            new.pop(field,None)
        new.update(Image=receipt['imageId'],Cmd=image['Config'].get('Cmd'),Entrypoint=image['Config'].get('Entrypoint'),
            Healthcheck=image['Config'].get('Healthcheck'))
        env=dict(x.split('=',1) for x in image['Config'].get('Env',[]) if '=' in x)
        env.update(dict(x.split('=',1) for x in old['Config'].get('Env',[]) if '=' in x))
        env['RELEASE_REVISION']=revision
        if ai:env['CIE_TRUSTED_PROXY_CLIENT_IP']='1'
        new['Env']=[key+'='+value for key,value in env.items()]
        labels={key:value for key,value in old['Config'].get('Labels',{}).items() if not key.startswith('org.ai-tutor.')}
        labels.update(image['Config'].get('Labels',{}))
        labels['com.docker.compose.project.working_dir']=str(release/'deploy/aliyun' if ai else release)
        labels['com.docker.compose.project.config_files']=str(release/'deploy/aliyun/compose.ip-https.yaml' if ai else release/'compose.yaml')
        new['Labels']=labels
        host=copy.deepcopy(old['HostConfig'])
        if not ai:host.update(Memory=5*1024**3,MemorySwap=5*1024**3,NanoCpus=2_000_000_000,PidsLimit=192)
        new['HostConfig']=host;new['NetworkingConfig']={'EndpointsConfig':networks}
        new_id=engine('POST','/containers/create?name='+quote(canonical),new)['Id']
        engine('POST','/containers/'+new_id+'/start')
        health(new_id,project,revision)
        print(json.dumps({'phase':'application-healthy','project':project,'revision':revision}),flush=True)
        if ai:
            (base/'current-release.path').write_text(str(release)+'\n')
            (base/'active-compose.path').write_text(str(release/'deploy/aliyun/compose.ip-https.yaml')+'\n')
        private_json(staging/'activation.json',{'project':project,'revision':revision,'imageId':receipt['imageId'],
            'sourceSha256':receipt['sourceSha256'],'previousContainerId':old['Id'],'activeContainerId':new_id,
            'preReleaseBackup':str(backup),'status':'healthy'})
    except BaseException:
        if new_id:
            subprocess.run(['docker','stop','--time','60',new_id],capture_output=True)
            for name in old['NetworkSettings']['Networks']:
                try:engine('POST','/networks/'+quote(name,safe='')+'/disconnect',{'Container':new_id,'Force':True})
                except Exception:pass
            engine('POST','/containers/'+new_id+'/rename?name='+quote(canonical+'-failed-'+revision[:12]))
        if renamed:engine('POST','/containers/'+old['Id']+'/rename?name='+quote(canonical))
        if old_disconnected:
            for name in old['NetworkSettings']['Networks']:
                engine('POST','/networks/'+quote(name,safe='')+'/connect',{'Container':old['Id'],'EndpointConfig':{'Aliases':['app',canonical]}})
        if proxy_original is not None:
            proxy_file.write_text(proxy_original)
            subprocess.run(['docker','exec','cie-study-aliyun-proxy-1','caddy','reload','--config','/etc/caddy/Caddyfile','--adapter','caddyfile'],capture_output=True)
        subprocess.run(['docker','start',old['Id']],capture_output=True)
        if ai:
            (base/'current-release.path').write_text(str(current)+'\n')
            (base/'active-compose.path').write_text(str(current/'deploy/aliyun/compose.ip-https.yaml')+'\n')
        raise
    finally:
        fcntl.flock(lock,fcntl.LOCK_UN);lock.close()
        if timer_was_enabled:subprocess.run(['systemctl','start','cie-study-backup-ai-tutor.timer'],capture_output=True)
    # Scheduler installer owns its own maintenance lock and performs a fresh
    # coordinated backup + isolated restore before replacing its reviewed runner.
    if ai:
        print(json.dumps({'phase':'backup-scheduler-validation','project':project}),flush=True)
        output=command(['bash',str(release/'deploy/aliyun/ops/local-backup-scheduler.sh'),'install'])
        print(output.strip(),flush=True)
        command(['systemctl','start','cie-study-backup-ai-tutor.service'])
        command([sys.executable,str(release/'deploy/aliyun/ops/backup-health.py')])
    host=public_host
    route='/api/health' if ai else '/healthz'
    public=json.loads(command(['curl','--noproxy','*','-fsS','--max-time','15','--resolve',host+':443:127.0.0.1','https://'+host+route]))
    if public.get('revision')!=revision:raise ValueError('Public origin revision mismatch')
    print(json.dumps({'status':'shipped','project':project,'gitRevision':revision,'imageId':receipt['imageId'],'builtImageConfigId':built_image_id,'sourceSha256':receipt['sourceSha256'],'publicRevisionVerified':True}),flush=True)

if __name__=='__main__':main()
