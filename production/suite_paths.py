from pathlib import Path
import os,shutil,sqlite3,json

def home():return Path(os.environ.get('ETF_SUITE_HOME') or Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/'ETFStrategySuite')

def skdj_home():return home()/'SKDJ研究'

def copy_records(prior,dest):
    shutil.copytree(prior,dest,ignore=shutil.ignore_patterns('*-wal','*-shm','*.lock'))
    for source in prior.rglob('*.sqlite3'):
        with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as old,sqlite3.connect(dest/source.relative_to(prior)) as new:old.backup(new)

def prepare():
    root=home();root.mkdir(parents=True,exist_ok=True)
    # All integrated modules keep their own records under one application folder.
    for var,folder,old in [('BULLBEAR50_HOME','单ETF实验','BullBear50Lab'),('COMBO50_HOME','联合研究','Combo50Lab'),('BANKAUTO_HOME','银行原策略账户','BankAutoSimulation'),('SKDJ_SUITE_HOME','SKDJ研究','SKDJBacktest')]:
        dest=root/folder
        prior=Path(os.environ.get('LOCALAPPDATA',str(Path.home())))/old
        if not dest.exists() and prior.exists() and not os.environ.get('ETF_SUITE_HOME'):
            copy_records(prior,dest)
            if var=='BANKAUTO_HOME':
                # The primary ledger owns the carried-over daily watcher. Legacy
                # research accounts are available, but must be explicitly enabled.
                db=dest/'模拟交易账户.sqlite3'
                if db.exists():
                    with sqlite3.connect(db) as conn:
                        for identity,payload in conn.execute('SELECT id,payload FROM accounts').fetchall():
                            state=json.loads(payload)
                            if state.get('auto',{}).get('watch'):
                                state['auto']['watch']=False
                                conn.execute('UPDATE accounts SET payload=? WHERE id=?',(json.dumps(state,ensure_ascii=False),identity))
                (dest/'迁移说明.txt').write_text('原银行账户历史已复制。此研究模块的每日跟踪初始关闭，可手动开启；主账户区继续承接原四资产跟踪。原账本未修改。',encoding='utf8')
        dest.mkdir(parents=True,exist_ok=True);os.environ[var]=str(dest)
    return root
