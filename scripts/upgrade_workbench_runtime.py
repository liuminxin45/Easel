"""Idle private-profile upgrade; keep the authoritative database in place.

The runtime manifest binds its frontend. Both selectors change behind the same
admission fence, before the server is checked and existing workers are admitted.
This command never migrates or restores a database.
"""
from pathlib import Path
import argparse
import json
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from activate_workbench import STATE,OLD,PYTHON,read,atomic,sha,verify,idle,queue_idle,authenticate,smoke,stop_new_profile
from workbench_release import CAPABILITIES


def validate_candidate(root, state, acceptance_path):
    """Verify the reviewed pair before changing admission or any selector."""
    import re
    choice=read(state/'candidate.json')
    if not re.fullmatch(r'workbench-[A-Za-z0-9_-]+',str(choice.get('release',''))):
        raise ValueError('Invalid runtime candidate')
    package=verify(root/'workbench-releases'/choice['release'],choice['manifest_sha256'])
    if package.get('capabilities_sha256')!=sha(CAPABILITIES):
        raise ValueError('Skill source changed after candidate validation')
    native=choice['native']
    if package['native']!=native or not re.fullmatch(r'native-[A-Za-z0-9_-]+',str(native.get('release',''))):
        raise ValueError('Frontend does not match the runtime manifest')
    directory=(root/'native-releases'/native['release']).resolve()
    manifest=directory/'native-manifest.json'
    if sha(manifest)!=native['manifest_sha256']:
        raise ValueError('Frontend manifest changed')
    assets=read(manifest)
    if assets.get('release')!=native['release'] or not assets.get('files'):
        raise ValueError('Invalid frontend manifest')
    for name,expected in assets['files'].items():
        member=(directory/name).resolve()
        if not member.is_relative_to(directory) or not member.is_file() or sha(member)!=expected:
            raise ValueError('Frontend member changed: '+name)
    acceptance=read(acceptance_path)
    if not acceptance.get('passed') or acceptance['candidate']!=choice:
        raise ValueError('Acceptance does not match the candidate pair')
    if not acceptance.get('evidence'):
        raise ValueError('Acceptance evidence missing')
    for name,expected in acceptance['evidence'].items():
        member=(root/name).resolve()
        if not member.is_relative_to(root.resolve()) or sha(member)!=expected:
            raise ValueError('Acceptance evidence changed')
    return choice,package


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acceptance',type=Path,default=STATE/'upgrade-acceptance.json')
    options=parser.parse_args()
    choice,package=validate_candidate(ROOT,STATE,options.acceptance)
    previous=read(ROOT/'data/active-workbench.json');owner=read(ROOT/'data/migration-owner.json')
    previous_native=read(ROOT/'data/active-native.json')
    if owner['target_root']!=str(ROOT) or any(owner[k]!=previous[k] for k in ('release','manifest_sha256')):
        raise ValueError('Business data ownership does not match the current runtime')
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
        atomic(ROOT/'data/active-native.json',choice['native'])
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
        result={'status':'live','candidate':choice,'previous_runtime':previous,'previous_native':previous_native,'data_root':str(ROOT/'data'),
            'database_copied':False,'database_restored':False,'manager':manager.pid,'smoke':ready,'idle':state}
        atomic(STATE/'runtime-upgrade.json',result)
        atomic(STATE/'upgrades'/(choice['release']+'.json'),result)
        original=read(STATE/'deployment.json')
        if not (STATE/'deployment-initial.json').exists():atomic(STATE/'deployment-initial.json',original)
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
