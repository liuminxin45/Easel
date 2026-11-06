"""Idle private-profile upgrade; keep the authoritative database in place.

The runtime manifest binds its frontend. Both selectors change behind the same
admission fence, before the server is checked and existing workers are admitted.
An explicitly reviewed builtin migration can add immutable releases while
writers are stopped. This command never copies or restores a database.
"""
from pathlib import Path
import argparse
import contextlib
import json
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from activate_workbench import STATE,OLD,PYTHON,read,atomic,sha,verify,idle,queue_idle,authenticate,smoke,stop_new_profile
from workbench_release import validate_source_binding,validate_published_skills


def validate_session_creation_compat(root,package):
    """A sealed legacy command must stay fenced after any future cutover."""
    import sqlite3
    database=Path(root)/'data/desk.sqlite'
    if not database.is_file():return
    with contextlib.closing(sqlite3.connect(database.resolve().as_uri()+'?mode=ro',uri=True,timeout=1)) as c:
        if not c.execute("SELECT 1 FROM sqlite_master WHERE name='easel_chat_creation_intents'").fetchone():return
        sealed=c.execute("SELECT 1 FROM easel_chat_creation_intents WHERE state='sealed_not_accepted' LIMIT 1").fetchone()
    if sealed and package.get('session_creation_protocol')!=2:
        raise ValueError('Selected runtime cannot preserve sealed session creation commands')


def validate_candidate(root, state, acceptance_path, candidate_path=None):
    """Verify the reviewed pair before changing admission or any selector."""
    import re
    choice=read(candidate_path or state/'candidate.json')
    if not re.fullmatch(r'workbench-[A-Za-z0-9_-]+',str(choice.get('release',''))):
        raise ValueError('Invalid runtime candidate')
    package=verify(root/'workbench-releases'/choice['release'],choice['manifest_sha256'])
    validate_source_binding(package,root)
    validate_source_binding(package,root/'workbench-releases'/choice['release'])
    validate_session_creation_compat(root,package)
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
    validate_published_skills(root)
    validate_published_skills(root,source_root=Path(root)/'workbench-releases'/choice['release'])
    return choice,package


def reviewed_builtin_plan(root,package,acceptance_path,path,expected):
    """Bind an explicitly requested data migration before fencing services."""
    if path is None and expected is None:return None
    if path is None or not expected:raise ValueError('Builtin activation needs both plan and expected plan SHA')
    path=Path(path).resolve();root=Path(root).resolve()
    if not path.is_relative_to(root/'.local') or not path.is_file():
        raise ValueError('Builtin plan must be a reviewed local project report')
    value=read(path)
    acceptance=read(acceptance_path)
    relative=path.relative_to(root).as_posix()
    if acceptance.get('evidence',{}).get(relative)!=sha(path):
        raise ValueError('Builtin plan is not bound to candidate acceptance')
    if value.get('already_applied') or value.get('conflicts') or value.get('busy') or value.get('plan_sha256')!=expected:
        raise ValueError('Builtin plan is not an exact idle conflict-free preview')
    if value.get('source',{}).get('catalog_revision')!=package.get('capabilities_sha256'):
        raise ValueError('Builtin plan uses a different project skill source')
    return {'path':str(path),'sha256':sha(path),'plan_sha256':expected,'source_revision':value['source_revision']}


def activate_builtin_after_stop(root,binding):
    if binding is None:return None
    if sha(binding['path'])!=binding['sha256']:raise ValueError('Reviewed builtin plan file changed')
    from activate_workbench_builtin_skills import apply_plan
    return apply_plan(Path(root)/'data/desk.sqlite',root,binding['plan_sha256'])


def needs_builtin_activation(root):
    """Never silently run the new project flow on external legacy defaults."""
    import sqlite3
    from easel_workbench.features.skills.retirement import native_mode
    if native_mode(root):return False
    from easel_workbench.skill_catalog import ProjectSkillCatalog
    expected={row['id'] for row in ProjectSkillCatalog(root).entries()}
    database=(Path(root)/'data/desk.sqlite').resolve()
    with contextlib.closing(sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)) as connection:
        if not connection.execute("SELECT 1 FROM sqlite_master WHERE name='creator_skill_pointers'").fetchone():return True
        rows=connection.execute('SELECT p.skill_id,v.document FROM creator_skill_pointers p JOIN creator_skill_versions v ON v.skill_id=p.skill_id AND v.version=p.version').fetchall()
    active={sid:json.loads(raw) for sid,raw in rows if sid in expected}
    if set(active)!=expected:return True
    return any(not value.get('entry','').startswith('skills/builtin/') for value in active.values())


def reviewed_delivery_plan(root,acceptance_path,path,expected):
    if path is None and expected is None:return None
    if path is None or not expected:raise ValueError('Delivery correction needs exact plan and SHA')
    path=Path(path).resolve();root=Path(root).resolve()
    if not path.is_relative_to(root/'.local') or not path.is_file():raise ValueError('Delivery plan must be local reviewed evidence')
    value=read(path);acceptance=read(acceptance_path)
    if acceptance.get('evidence',{}).get(path.relative_to(root).as_posix())!=sha(path) or value.get('plan_sha256')!=expected:
        raise ValueError('Delivery correction is not bound to candidate acceptance')
    from easel_workbench.application.delivery_reconciliation import preview
    if preview(root,value['turn_id'])!=value:raise ValueError('Original delivery or bytes changed')
    return {'path':str(path),'sha256':sha(path),'plan_sha256':expected}


def reviewed_skill_retirement(root,package,acceptance_path,path,expected):
    from easel_workbench.features.skills.retirement import preview,migration_runtime,MIGRATION
    import sqlite3
    native=package.get('skills_protocol')=='easel-native-v1'
    if path is None and expected is None:
        if not native:return None
        with contextlib.closing(sqlite3.connect((Path(root)/'data/desk.sqlite').resolve().as_uri()+'?mode=ro',uri=True)) as c:
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='creator_feature_retirements'").fetchone() and c.execute('SELECT 1 FROM creator_feature_retirements WHERE id=?',(MIGRATION,)).fetchone():return None
        raise ValueError('First native skill cutover requires an explicit reviewed retirement plan')
    if not native or path is None or not expected:raise ValueError('Native skill retirement needs the exact plan and SHA')
    path=Path(path).resolve();root=Path(root).resolve()
    if not path.is_relative_to(root/'.local') or not path.is_file():raise ValueError('Retirement plan must be reviewed local evidence')
    value=read(path);acceptance=read(acceptance_path)
    if value.get('plan_sha256')!=expected or acceptance.get('evidence',{}).get(path.relative_to(root).as_posix())!=sha(path):raise ValueError('Skill retirement plan is not bound to candidate acceptance')
    with contextlib.closing(sqlite3.connect((root/'data/desk.sqlite').as_uri()+'?mode=ro',uri=True)) as c:
        c.row_factory=sqlite3.Row
        if preview(migration_runtime(root),c)!=value:raise ValueError('Profile revision changed after retirement preview')
    return {'path':str(path),'sha256':sha(path),'plan_sha256':expected}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--acceptance',type=Path,default=STATE/'upgrade-acceptance.json')
    parser.add_argument('--candidate',type=Path,help='Exact reviewed pair; leaves the shared candidate selector untouched')
    parser.add_argument('--builtin-plan',type=Path)
    parser.add_argument('--builtin-plan-sha256')
    parser.add_argument('--delivery-plan',type=Path)
    parser.add_argument('--delivery-plan-sha256')
    parser.add_argument('--skill-retirement-plan',type=Path)
    parser.add_argument('--skill-retirement-plan-sha256')
    parser.add_argument('--authenticate-after-cutover',action='store_true',help='Recover a full legacy login-session table; authenticate before admitting workers')
    options=parser.parse_args()
    from easel_workbench.runtime.feedback_ledger import locked
    with locked(STATE/'runtime-release.lock',timeout=30),locked(STATE/'frontend-release.lock',timeout=30):
        upgrade(options)


def start_scheduled_manager(choice):
    """The OS owns the resident manager, not this deployment command's job."""
    subprocess.run(['pwsh','-NoProfile','-NonInteractive','-File',
        str(ROOT/'scripts/ensure_workbench_autostart.ps1'),'-Start'],
        cwd=ROOT,check=True,capture_output=True,text=True,timeout=45,
        creationflags=subprocess.CREATE_NO_WINDOW)
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        try:
            status=read(STATE/'pids.json')
            if (status.get('release')==choice['release'] and not status.get('paused')
                    and time.time()-status.get('heartbeat',0)<15 and 'server' in status.get('roles',{})):
                return status['manager']
        except (OSError,ValueError):
            pass
        time.sleep(.5)
    raise RuntimeError('Scheduled manager did not report the selected release; writes remain fenced')


def upgrade(options):
    choice,package=validate_candidate(ROOT,STATE,options.acceptance,options.candidate)
    builtin=reviewed_builtin_plan(ROOT,package,options.acceptance,options.builtin_plan,options.builtin_plan_sha256)
    delivery=reviewed_delivery_plan(ROOT,options.acceptance,getattr(options,'delivery_plan',None),getattr(options,'delivery_plan_sha256',None))
    retirement=reviewed_skill_retirement(ROOT,package,options.acceptance,getattr(options,'skill_retirement_plan',None),getattr(options,'skill_retirement_plan_sha256',None))
    if builtin is None and needs_builtin_activation(ROOT):
        raise ValueError('Legacy skill defaults require an explicit reviewed builtin migration plan')
    previous=read(ROOT/'data/active-workbench.json');owner=read(ROOT/'data/migration-owner.json')
    previous_native=read(ROOT/'data/active-native.json')
    acceptance=read(options.acceptance)
    if (acceptance.get('base_runtime',previous)!=previous or acceptance.get('base_native',previous_native)!=previous_native):
        raise ValueError('Reviewed deployment base changed; integrate the current live pair before retrying')
    if owner['target_root']!=str(ROOT) or any(owner[k]!=previous[k] for k in ('release','manifest_sha256')):
        raise ValueError('Business data ownership does not match the current runtime')
    state=idle(ROOT/'data/desk.sqlite')
    if state['busy']:print(json.dumps({'status':'waiting','busy':state}));return
    queue_idle();client=None;stopped=False
    if getattr(options,'authenticate_after_cutover',False):
        from easel_workbench.runtime.auth_totp import CONFIG
        auth=read(CONFIG);now=time.time()
        live=sum(1 for value in auth.get('sessions',{}).values() if value.get('until',0)>now)
        target=(ROOT/'workbench-releases'/choice['release']/'easel_workbench/runtime/auth_totp.py').read_text(encoding='utf-8')
        if live<256 or "len(updated['sessions']) >= 256" in target:
            raise ValueError('Deferred authentication is only for a saturated legacy session table with the limit removed')
    else:client=authenticate()
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
            if read(ROOT/'data/active-workbench.json')!=previous or read(ROOT/'data/active-native.json')!=previous_native or read(ROOT/'data/migration-owner.json')!=owner:
                raise ValueError('Active deployment changed during preflight; review the current pair before retrying')
            stop_new_profile();stopped=True
            fence.execute('ROLLBACK')
        builtin_activation=activate_builtin_after_stop(ROOT,builtin)
        skill_retirement=None
        if retirement:
            from easel_workbench.features.skills.retirement import apply as apply_retirement,migration_runtime
            if sha(retirement['path'])!=retirement['sha256']:raise ValueError('Skill retirement evidence changed after stop')
            skill_retirement=apply_retirement(migration_runtime(ROOT),retirement['plan_sha256'])
        # Recheck behind the writer fence, including an explicit migration's
        # resulting published versions, before selecting or admitting services.
        validate_published_skills(ROOT)
        validate_published_skills(ROOT,source_root=ROOT/'workbench-releases'/choice['release'])
        delivery_reconciliation=None
        if delivery:
            if sha(delivery['path'])!=delivery['sha256']:raise ValueError('Delivery correction plan changed after stop')
            from easel_workbench.application.delivery_reconciliation import apply as apply_delivery_correction
            delivery_reconciliation=apply_delivery_correction(ROOT,read(delivery['path']),delivery['plan_sha256'])
        atomic(ROOT/'data/active-workbench.json',{k:choice[k] for k in ('release','manifest_sha256')})
        atomic(ROOT/'data/active-native.json',choice['native'])
        atomic(ROOT/'data/migration-owner.json',{**owner,'release':choice['release'],'manifest_sha256':choice['manifest_sha256']})
        (STATE/'paused').unlink(missing_ok=True)
        manager_pid=start_scheduled_manager(choice)
        if client is None:
            # Never admit workers until the new runtime issues a valid login.
            import httpx
            from easel_workbench.runtime.auth_totp import CONFIG
            origin=read(CONFIG)['origin'];deadline=time.monotonic()+60
            while True:
                try:
                    response=httpx.get(origin+'/login?next=%2Fnative%2F',follow_redirects=False,trust_env=False,timeout=3)
                    if response.status_code==200:break
                except httpx.HTTPError:pass
                if time.monotonic()>deadline:raise RuntimeError('Updated login challenge unavailable; writes remain fenced')
                time.sleep(1)
            client=authenticate()
        deadline=time.monotonic()+60
        while True:
            try:ready=smoke(client,choice['native']);break
            except Exception:
                if time.monotonic()>deadline:raise RuntimeError('Updated server is not ready; data retained, writes remain fenced')
                time.sleep(1)
        atomic(STATE/'admission.json',{'workers':True})
        atomic(STATE/'cutover.json',{'source_root':str(OLD),'target_root':str(ROOT),'phase':'live','candidate':choice})
        result={'status':'live','candidate':choice,'previous_runtime':previous,'previous_native':previous_native,'data_root':str(ROOT/'data'),
            'database_copied':False,'database_restored':False,'manager':manager_pid,'manager_started_by':'windows-task-scheduler','smoke':ready,'idle':state,
            'builtin_activation':builtin_activation,'delivery_reconciliation':delivery_reconciliation,'skill_retirement':skill_retirement}
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
            current={**read(ROOT/'data/active-workbench.json'),'native':read(ROOT/'data/active-native.json')}
            atomic(STATE/'cutover.json',{'source_root':str(OLD),'target_root':str(ROOT),'phase':'live','candidate':current})
        raise
    finally:
        if client is not None:client.close()


if __name__=='__main__':main()
