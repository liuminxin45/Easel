"""Identity-fenced cross-project migration, with one authoritative business DB.

No worker admission until the migrated server has passed authenticated smoke
checks. On pre-admission failure the untouched old database remains the owner.
After admission rollback must keep the new database; never restore a snapshot.
"""
from pathlib import Path
import argparse
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
OLD=Path('D:/Projects/ai-news-desk')
STATE=ROOT/'.local/workbench-deployment'
PYTHON=ROOT/'.runtime/workbench-python/Scripts/pythonw.exe'
sys.path.insert(0,str(ROOT))
from workbench_release import atomic,sha,verify,validate_source_binding
from archived_evidence import archived_reads
from easel_workbench.runtime.scripts.windows_process_identity import ProcessIdentity
from easel_workbench.processes import checked_identity


def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))


def legacy():
    sys.path.insert(0,str(OLD))
    from scripts import activate_learning_style as base,activate_automation as automation
    return base,automation


class HistoricalAuditConnection:
    """Keep the original row-hash contract across the nullable snapshot migration.

    Only the retained-row SELECT is projected. Non-null snapshots and changes
    to any original field still fail the original historical audit.
    """
    def __init__(self,connection):self.connection=connection
    def execute(self,sql,parameters=()):
        if sql=='SELECT * FROM collection_tasks WHERE id=?':
            columns=[row[1] for row in self.connection.execute('PRAGMA table_info(collection_tasks)')]
            if 'source_snapshot' in columns:
                snapshot=self.connection.execute('SELECT source_snapshot FROM collection_tasks WHERE id=?',parameters).fetchone()
                if snapshot and snapshot[0] is not None:raise ValueError('Retained historical task unexpectedly has a source snapshot')
                sql='SELECT '+','.join('"'+name+'"' for name in columns if name!='source_snapshot')+' FROM collection_tasks WHERE id=?'
        return self.connection.execute(sql,parameters)


def idle(database=None):
    base,automation=legacy()
    evidence=read(OLD/'evidence/simplify-workbench-20261029/activation-evidence.json')
    def audited(key):
        ref=evidence[key];p=OLD/ref['path']
        if sha(p)!=ref['sha256']:raise ValueError('Historical audit changed')
        return {**ref,'document':read(p)}
    database=Path(database or OLD/'data/desk.sqlite').resolve()
    with contextlib.closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as c:
        c.row_factory=sqlite3.Row
        with archived_reads(ROOT,OLD,base,automation):
            status=automation.busy_state(HistoricalAuditConnection(c),audited('historical_unknown_audit'),audited('collection_historical_unknown_audit'))
        for table in ('creator_model_calls','distribution_executions','distribution_attempts','media_install_jobs','media_account_sessions','easel_chat_turns'):
            if not base.exists_table(c,table):continue
            cols={r[1] for r in c.execute('pragma table_info('+table+')')}
            if 'document' in cols:
                for ident,raw in c.execute('select id,document from '+table):
                    value=json.loads(raw)
                    active=value.get('status') in ('running','dispatching','requested','sending','submitting','accepted')
                    if table=='media_install_jobs':active=value.get('state') in ('queued','running')
                    if table=='media_account_sessions':active=value.get('state') in ('login','checking')
                    if table=='easel_chat_turns':
                        active=active or value.get('status')=='unknown' or value.get('hook_status')=='pending' or value.get('start_hook_status')=='pending'
                    if active:
                        status['busy']=True;status.setdefault('additional',[]).append({'table':table,'id':ident})
        if base.exists_table(c,'easel_native_corrections'):
            for (ident,) in c.execute("SELECT job_id FROM easel_native_corrections WHERE status='queued'"):
                status['busy']=True;status.setdefault('additional',[]).append({'table':'easel_native_corrections','id':ident})
    # The historical audit is anchored to the retained original evidence. New
    # model receipts belong to the authoritative database's data directory.
    # Do not inspect only the retired project's cache during later upgrades.
    if database.parent.resolve()!=(OLD/'data').resolve():
        retained={row['id']:row for row in status.get('retained_collection_unknown',[])}
        for path in (database.parent/'collection/model-cache').glob('*.json'):
            value=read(path)
            if value.get('status') not in ('requested','uncertain'):continue
            previous=retained.get(path.stem)
            if previous and sha(path)==previous['cache_sha256']:continue
            from collection_receipt_retention import retained as reviewed_retention
            reviewed=reviewed_retention(ROOT,path.stem,path) if re.fullmatch('[a-f0-9]{64}',path.stem) else None
            if reviewed:
                status.setdefault('retained_collection_unknown',[]).append({
                    'id':path.stem,'status':value['status'],'cache_sha256':sha(path),
                    'audit_path':reviewed['audit_path'],'audit_sha256':reviewed['audit_sha256'],
                    'replayed':False,'non_running_ephemeral':True})
                continue
            status['busy']=True
            status.setdefault('additional',[]).append({'table':'collection_model_receipt','id':path.stem,'status':value['status']})
    return status


def identities():
    base,_=legacy();host=base.WindowsHost();rows=host.processes()
    main=read(OLD/'data/pids.json');dist=read(OLD/'data/distribution-pids.json');coll=read(OLD/'data/collection-pids.json')
    pids={v for k,v in main.items() if isinstance(v,int)}|{dist['supervisor'],dist['publisher'],coll['supervisor'],coll['collector']}
    # Windows venv executables can have a wrapper above the recorded main PID.
    # Hold that same owned launcher too; otherwise the task can outlive its child.
    for pid in list(pids):
        parent=rows.get(pid,{}).get('parent')
        while parent in rows:
            line=(rows[parent].get('command') or '').replace('\\','/').lower()
            if str(OLD).replace('\\','/').lower() not in line or 'launcher.pyw' not in line:break
            pids.add(parent);parent=rows[parent].get('parent')
    parents=set(pids)
    while True:
        added={pid for pid,row in rows.items() if row.get('parent') in pids}-pids
        if not added:break
        pids|=added
    held={}
    try:
        for pid in sorted(pids):
            row=rows.get(pid)
            if not row:raise ValueError('Process disappeared; refresh plan')
            command=(row.get('command') or '').replace('\\','/').lower()
            if pid in parents and str(OLD).replace('\\','/').lower() not in command:
                raise ValueError('Old service identity mismatch: '+str(pid))
            if row['name'].lower() not in ('python.exe','pythonw.exe','node.exe'):
                raise ValueError('Active helper child requires separate reconciliation: '+str(pid))
            identity=checked_identity(row)
            held[pid]=(identity,row)
        return held,parents
    except BaseException:
        for identity,_ in held.values():identity.close()
        raise


def stop(held,parents):
    # Stop guardians first, then leaf workers, so none can be respawned mid-copy.
    order=sorted(parents,key=lambda pid:0 if 'supervisor' in (held[pid][1].get('command') or '') or 'launcher.pyw' in (held[pid][1].get('command') or '') else 1)
    order+=sorted(set(held)-parents,reverse=True)
    for pid in order:
        handle,_=held[pid];handle.terminate(expected_creation_ticks=handle.creation_ticks)
    if any(not h.exited() for h,_ in held.values()):raise ValueError('A source writer is still alive')
    # Guardians are now dead. Catch a final venv child spawned between the
    # last inventory and guardian exit, using its exact legacy service argv.
    base,_=legacy();host=base.WindowsHost()
    for row in host.processes().values():
        line=(row.get('command') or '').replace('\\','/').lower()
        if row['name'].lower() not in ('python.exe','pythonw.exe'):continue
        prefix=str(OLD).replace('\\','/').lower()+'/'
        if not any(prefix+name in line for name in ('scripts/run_toolbox.py','scripts/collection_supervisor.py','scripts/distribution_supervisor.py','launcher.pyw')):continue
        with checked_identity(row) as identity:
            identity.terminate(expected_creation_ticks=identity.creation_ticks)


def queue_idle():
    base,_=legacy()
    from poster_rpc import RPC
    from desk import THREAD
    rpc=RPC()
    try:result=rpc.call('thread/queue/list',{'threadId':THREAD,'limit':100},timeout=20)
    finally:rpc.close()
    if result.get('data') or result.get('nextCursor'):raise ValueError('Native production queue is active')
    return {'method':'thread/queue/list','empty':True,'read_only':True}


def stop_new_profile(manager=None):
    from easel_workbench.processes import rows
    (STATE/'paused').write_text('failure recovery: do not respawn roles',encoding='utf-8')
    inventory=rows();selected={manager} if manager else set()
    pointer=STATE/'pids.json'
    if pointer.exists():
        p=read(pointer);selected.add(p['manager']);selected.update(p.get('roles',{}).values())
    while True:
        more={pid for pid,row in inventory.items() if row['parent'] in selected}-selected
        if not more:break
        selected|=more
    held=[]
    try:
        for pid in selected:
            row=inventory.get(pid)
            if row is None:continue
            line=(row.get('command') or '').replace('\\','/').lower()
            if str(ROOT).replace('\\','/').lower() not in line:raise ValueError('Unexpected new-profile child')
            if 'workbench-releases/' not in line and '/launcher.pyw' not in line:raise ValueError('Unowned new-profile process')
            held.append((checked_identity(row),line))
        for handle,line in sorted(held,key=lambda item:0 if '/launcher.pyw' in item[1] else 1):handle.terminate(expected_creation_ticks=handle.creation_ticks)
        # No guardian can now spawn another server. Reconcile the tiny window
        # between its last tick and our first process inventory.
        release=read(ROOT/'data/active-workbench.json')['release']
        marker=str(ROOT/'workbench-releases'/release/'launch.py').replace('\\','/').lower()
        for row in rows().values():
            line=(row.get('command') or '').replace('\\','/').lower()
            if marker not in line:continue
            with checked_identity(row) as handle:handle.terminate(expected_creation_ticks=handle.creation_ticks)
    finally:
        for handle,_ in held:handle.close()


def prepare_data(choice):
    path=ROOT/'scripts/migrate_workbench_data.py'
    spec=importlib.util.spec_from_file_location('migration',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    target=STATE/('final-'+choice['release'])
    report=module.migrate(OLD,target,runtime_root=ROOT)
    verified=module.validate(OLD,target,compare_source=True,manifest=report)
    if not verified['passed']:raise ValueError('Final migration comparison failed: '+json.dumps(verified['errors']))
    if (ROOT/'data').exists():raise ValueError('Target production data already exists')
    os.replace(target/'data',ROOT/'data')
    verified=module.validate(OLD,ROOT,compare_source=True,manifest=report)
    if not verified['passed']:raise ValueError('Moved data comparison failed')
    atomic(STATE/'migration-verification.json',verified)
    shutil.copy2(target/'migration-report.json',STATE/'final-migration-report.json')
    evidence={}
    for original in (OLD/'evidence/discovery').rglob('*'):
        if not original.is_file():continue
        relative=original.relative_to(OLD);destination=ROOT/relative
        before=sha(original);destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(original,destination)
        if sha(destination)!=before or sha(original)!=before:raise ValueError('Discovery evidence changed during copy')
        evidence[relative.as_posix()]=before
    atomic(STATE/'discovery-evidence.json',{'files':evidence,'copied_without_rewriting':True})
    web=read(OLD/'data/active-web.json')
    for selected,folder in [(web,'releases'),(read(OLD/'data/active-native.json'),'native-releases')]:
        dst=ROOT/folder/selected['release']
        if not dst.exists():shutil.copytree(OLD/folder/selected['release'],dst)
    # Old installed shells may still reference an older immutable asset URL.
    # Keep those exact manifests/assets reachable through the unchanged origin.
    for source in (OLD/'native-releases').iterdir():
        if source.is_dir() and (source/'native-manifest.json').is_file():
            destination=ROOT/'native-releases'/source.name
            if not destination.exists():shutil.copytree(source,destination)
    for name in ('sources.json','usage_registry.json','collection_schedules.json'):
        shutil.copy2(ROOT/'easel_workbench/runtime'/name,ROOT/name)
    atomic(ROOT/'data/active-web.json',web)
    atomic(ROOT/'data/active-native.json',choice['native'])
    atomic(ROOT/'data/active-workbench.json',{k:choice[k] for k in ('release','manifest_sha256')})
    return read(STATE/'final-migration-report.json')


def authenticate():
    import httpx
    from easel_workbench.runtime.auth_totp import CONFIG,totp
    cfg=read(CONFIG);origin=cfg['origin']
    client=httpx.Client(base_url=origin,follow_redirects=False,trust_env=False,timeout=20)
    response=client.get('/login?next=%2Fnative%2F')
    match=re.search(r'name="csrf" value="([^"]+)"',response.text)
    if response.status_code!=200 or not match:raise ValueError('Login challenge unavailable')
    step=int(time.time()//30)
    while step<=cfg.get('last_step',-1):
        time.sleep(1);step=int(time.time()//30);cfg=read(CONFIG)
    response=client.post('/login',data={'csrf':match[1],'code':totp(cfg['secret'],step),'next':'/native/'},headers={'Origin':origin})
    if response.status_code!=303:raise ValueError('Owner smoke login failed')
    return client


def smoke(client,native):
    for path in ('/api/config','/api/works','/api/creator/bootstrap','/api/platform-accounts'):
        response=client.get(path)
        if response.status_code!=200:raise ValueError('Readiness check failed: '+path+' '+str(response.status_code))
    response=client.get('/native/version')
    if response.status_code!=200 or response.json().get('release')!=native['release']:raise ValueError('Wrong native release')
    return {'authenticated_routes':4,'native':native['release'],'business_POSTs':0}


def execute(apply=False):
    STATE.mkdir(parents=True,exist_ok=True)
    choice=read(STATE/'candidate.json');package=verify(ROOT/'workbench-releases'/choice['release'],choice['manifest_sha256'])
    if choice['native']!=package['native']:raise ValueError('Frontend is not bound to runtime')
    native=ROOT/'native-releases'/choice['native']['release'];manifest=native/'native-manifest.json'
    if sha(manifest)!=choice['native']['manifest_sha256']:raise ValueError('Frontend manifest changed')
    for member,expected in read(manifest)['files'].items():
        file=(native/member).resolve()
        if not file.is_relative_to(native.resolve()) or sha(file)!=expected:raise ValueError('Frontend asset changed')
    validate_source_binding(package,ROOT)
    status=idle()
    if status['busy']:return {'status':'waiting','busy':status,'production_changed':False}
    held,parents=identities()
    plan={'candidate':choice,'old_processes':{str(pid):{'name':r['name'],'created':h.creation_ticks} for pid,(h,r) in held.items()},'idle':status}
    try:
        if not apply:return {'status':'plan',**plan}
        if (ROOT/'data').exists():raise ValueError('Target production data already exists; no source process stopped')
        checks=read(STATE/'acceptance.json')
        if checks.get('passed') is not True or checks.get('candidate')!=choice:raise ValueError('Exact-candidate acceptance is incomplete')
        for p,h in checks['evidence'].items():
            if sha(ROOT/p)!=h:raise ValueError('Acceptance evidence changed')
        client=authenticate();stopped=False;admitted=False;startup_disabled=False;process=None
        try:
            queue=queue_idle()
            status=idle()
            if status['busy']:return {'status':'waiting','busy':status,'production_changed':False}
            # A writer transaction closes the last admission window. Every held
            # process is stopped before this lock is released for the final copy.
            with sqlite3.connect(OLD/'data/desk.sqlite',timeout=30,isolation_level=None) as fence:
                fence.execute('BEGIN IMMEDIATE')
                if idle()['busy']:raise ValueError('Work started before the writer fence')
                for handle,_ in held.values():handle.close()
                held,parents=identities()
                atomic(STATE/'cutover.json',{'source_root':str(OLD),'target_root':str(ROOT),'phase':'fenced','candidate':choice})
                # Prevent the logon task's configured failure recovery from
                # restarting its old launcher during the final copy.
                result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',
                    "$ErrorActionPreference='Stop'; Disable-ScheduledTask -TaskName 'AINewsDesk' | Out-Null"],
                    capture_output=True,text=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=30)
                if result.returncode:raise ValueError('Cannot fence the old startup task')
                startup_disabled=True
                atomic(STATE/'source-stop-plan.json',{'pids':{str(k):v[0].creation_ticks for k,v in held.items()},'queue':queue})
                stopped=True
                stop(held,parents)
                fence.execute('ROLLBACK')
            report=prepare_data(choice)
            # DPAPI remains bound to the same owner; restore owner-only DACLs
            # explicitly because copy2 does not carry the Windows security ACL.
            from easel_workbench.runtime.distribution_runtime import _private_acl
            for name in ('distribution-secrets','media-vault','private'):
                path=ROOT/'data'/name
                if path.exists():
                    _private_acl(path,True)
                    for member in path.rglob('*'):_private_acl(member,member.is_dir())
            atomic(STATE/'admission.json',{'workers':False})
            (STATE/'paused').unlink(missing_ok=True)
            log=(STATE/'manager.log').open('ab')
            process=subprocess.Popen([str(PYTHON),str(ROOT/'launcher.pyw')],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
            deadline=time.monotonic()+60;ready=None
            while time.monotonic()<deadline:
                try:ready=smoke(client,choice['native']);break
                except Exception:time.sleep(1)
            if ready is None:raise RuntimeError('Migrated server did not become ready; workers were not admitted')
            # Existing startup registrations now reach Easel through a tiny
            # compatibility launcher. Keep the old source/data as rollback evidence.
            launcher=OLD/'launcher.pyw';shutil.copy2(launcher,STATE/'old-launcher.pyw')
            launcher.write_text("import sys,runpy\nsys.path.insert(0,'D:/Projects/Easel')\nrunpy.run_path('D:/Projects/Easel/launcher.pyw',run_name='__main__')\n",encoding='utf-8')
            from startup_task import configure
            startup=configure('install',PYTHON,ROOT)
            import winreg
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
                winreg.SetValueEx(key,'AINewsDesk',0,winreg.REG_SZ,'"'+str(PYTHON)+'" "'+str(ROOT/'launcher.pyw')+'"')
            # The flag is conservative: once admission might be visible,
            # failure recovery must keep this database even after an interrupt.
            atomic(ROOT/'data/migration-owner.json',{'source_root':str(OLD),'target_root':str(ROOT),
                'release':choice['release'],'manifest_sha256':choice['manifest_sha256'],'native':choice['native'],'admitted':True})
            admitted=True;atomic(STATE/'admission.json',{'workers':True})
            atomic(STATE/'cutover.json',{'source_root':str(OLD),'target_root':str(ROOT),'phase':'live','candidate':choice})
            result={'status':'live','candidate':choice,'smoke':ready,'manager':process.pid,
                'migration_files':len(report['files']),'database_restored':False,'old_data_retained':True,
                'startup_task':{'task':startup.get('task'),'state':startup.get('state')},'idle':status}
            atomic(STATE/'deployment.json',result);return result
        except BaseException as error:
            failure={'status':'failed','type':type(error).__name__,'error':str(error),'workers_admitted':admitted,'source_stopped':stopped,'database_restored':False}
            atomic(STATE/'failure.json',failure)
            if stopped and not admitted:
                atomic(STATE/'admission.json',{'workers':False})
                stop_new_profile(process.pid if process else None)
                if (ROOT/'data').exists():
                    destination=(STATE/('failed-data-'+str(int(time.time())))).resolve()
                    if not destination.is_relative_to(ROOT.resolve()):raise ValueError('Recovery destination outside workspace')
                    os.replace(ROOT/'data',destination)
                saved=STATE/'old-launcher.pyw'
                if saved.exists():shutil.copy2(saved,OLD/'launcher.pyw')
                # No business command was admitted on the copied database.
                # Restart against the untouched original, without restoring DB.
                from startup_task import configure
                configure('install',OLD/'.venv/Scripts/pythonw.exe',OLD)
                import winreg
                with winreg.CreateKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Run') as key:
                    winreg.SetValueEx(key,'AINewsDesk',0,winreg.REG_SZ,'"'+str(OLD/'.venv/Scripts/pythonw.exe')+'" "'+str(OLD/'launcher.pyw')+'"')
                subprocess.Popen([str(OLD/'.venv/Scripts/pythonw.exe'),str(OLD/'launcher.pyw')],cwd=OLD,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,creationflags=subprocess.CREATE_NO_WINDOW)
                (STATE/'cutover.json').unlink(missing_ok=True)
                failure['old_service_restarted']=True;atomic(STATE/'failure.json',failure)
            elif startup_disabled and not stopped:
                subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',"Enable-ScheduledTask -TaskName 'AINewsDesk' | Out-Null"],capture_output=True,creationflags=subprocess.CREATE_NO_WINDOW,timeout=30)
                (STATE/'cutover.json').unlink(missing_ok=True)
            elif not stopped:
                (STATE/'cutover.json').unlink(missing_ok=True)
            raise
        finally:client.close()
    finally:
        for handle,_ in held.values():handle.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--apply',action='store_true');a=p.parse_args()
    print(json.dumps(execute(a.apply),ensure_ascii=False,indent=2))
