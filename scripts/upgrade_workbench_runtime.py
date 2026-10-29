"""Idle runtime replacement in Easel; keep the authoritative database in place."""
from pathlib import Path
import json
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from activate_workbench import STATE,OLD,PYTHON,read,atomic,sha,verify,idle,queue_idle,authenticate,smoke,stop_new_profile


def main():
    choice=read(STATE/'candidate.json');package=verify(ROOT/'workbench-releases'/choice['release'],choice['manifest_sha256'])
    previous=read(ROOT/'data/active-workbench.json');owner=read(ROOT/'data/migration-owner.json')
    if owner['target_root']!=str(ROOT) or any(owner[k]!=previous[k] for k in ('release','manifest_sha256')):
        raise ValueError('Business data ownership does not match the current runtime')
    acceptance=read(STATE/'hotfix-acceptance.json')
    if not acceptance.get('passed') or acceptance['candidate']!=choice:raise ValueError('Hotfix acceptance missing')
    for p,h in acceptance['evidence'].items():
        if sha(ROOT/p)!=h:raise ValueError('Hotfix evidence changed')
    if package['native']!=choice['native'] or read(ROOT/'data/active-native.json')!=choice['native']:
        raise ValueError('This runtime-only change cannot change the frontend')
    state=idle(ROOT/'data/desk.sqlite')
    if state['busy']:print(json.dumps({'status':'waiting','busy':state}));return
    queue_idle();client=authenticate();stopped=False
    try:
        atomic(STATE/'cutover.json',{'source_root':str(OLD),'target_root':str(ROOT),'phase':'fenced','candidate':choice})
        atomic(STATE/'admission.json',{'workers':False})
        import sqlite3
        with sqlite3.connect(ROOT/'data/desk.sqlite',timeout=30,isolation_level=None) as fence:
            fence.execute('BEGIN IMMEDIATE')
            state=idle(ROOT/'data/desk.sqlite')
            if state['busy']:
                atomic(STATE/'admission.json',{'workers':True})
                atomic(STATE/'cutover.json',{'source_root':str(OLD),'target_root':str(ROOT),'phase':'live','candidate':previous})
                print(json.dumps({'status':'waiting','busy':state}));return
            stop_new_profile();stopped=True
            fence.execute('ROLLBACK')
        atomic(ROOT/'data/active-workbench.json',{k:choice[k] for k in ('release','manifest_sha256')})
        atomic(ROOT/'data/migration-owner.json',{**owner,'release':choice['release'],'manifest_sha256':choice['manifest_sha256']})
        (STATE/'paused').unlink(missing_ok=True)
        with (STATE/'manager.log').open('ab') as log:
            manager=subprocess.Popen([str(PYTHON),str(ROOT/'launcher.pyw')],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        deadline=time.monotonic()+60
        while True:
            try:ready=smoke(client,choice['native']);break
            except Exception:
                if time.monotonic()>deadline:raise RuntimeError('Updated server is not ready; data retained, writes remain fenced')
                time.sleep(1)
        atomic(STATE/'admission.json',{'workers':True})
        atomic(STATE/'cutover.json',{'source_root':str(OLD),'target_root':str(ROOT),'phase':'live','candidate':choice})
        result={'status':'live','candidate':choice,'previous_runtime':previous,'data_root':str(ROOT/'data'),
            'database_copied':False,'database_restored':False,'manager':manager.pid,'smoke':ready,'idle':state}
        atomic(STATE/'runtime-upgrade.json',result)
        original=read(STATE/'deployment.json')
        atomic(STATE/'deployment-initial.json',original)
        atomic(STATE/'deployment.json',{**original,'candidate':choice,'runtime_upgrade':result})
        print(json.dumps(result,ensure_ascii=False,indent=2))
    except BaseException:
        # Never return to the pre-migration database after admission. Preserve
        # this same database even when the updated runtime needs a forward fix.
        if not stopped:
            atomic(STATE/'admission.json',{'workers':True})
            atomic(STATE/'cutover.json',{'source_root':str(OLD),'target_root':str(ROOT),'phase':'live','candidate':previous})
        raise
    finally:client.close()


if __name__=='__main__':main()
