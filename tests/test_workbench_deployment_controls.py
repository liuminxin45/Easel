"""TEMP-only immutable package and admission controls; no real process launch."""
import importlib.util
import json
from pathlib import Path
import shutil
import sqlite3
import sys

import pytest


PROJECT=Path(__file__).resolve().parents[1]


def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def release_module():
    return load('workbench_release_controls_test',PROJECT/'scripts/workbench_release.py')


def package(tmp_path):
    module=release_module();directory=tmp_path/'package';directory.mkdir()
    (directory/'launch.py').write_text('print("fixture")',encoding='utf-8')
    value={'release':'workbench-fixture','files':{'launch.py':module.sha(directory/'launch.py')}}
    module.atomic(directory/'workbench-release.json',value)
    return module,directory


def test_release_rejects_mutated_member(tmp_path):
    module,directory=package(tmp_path)
    expected=module.sha(directory/'workbench-release.json')
    assert module.verify(directory,expected)['release']=='workbench-fixture'
    (directory/'launch.py').write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError):module.verify(directory,expected)


def test_release_rejects_manifest_hash_change(tmp_path):
    module,directory=package(tmp_path)
    with pytest.raises(ValueError):module.verify(directory,'0'*64)


def test_release_rejects_escaping_member(tmp_path):
    module,directory=package(tmp_path);outside=tmp_path/'outside.py';outside.write_text('outside',encoding='utf-8')
    module.atomic(directory/'workbench-release.json',{'files':{'../outside.py':module.sha(outside)}})
    with pytest.raises(ValueError):module.verify(directory)


def upgrade_fixture(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(PROJECT/'scripts'))
    upgrade=load('workbench_upgrade_controls_test',PROJECT/'scripts/upgrade_workbench_runtime.py')
    release=release_module()
    state=tmp_path/'.local/workbench-deployment';state.mkdir(parents=True)
    runtime=tmp_path/'workbench-releases/workbench-next';runtime.mkdir(parents=True)
    native=tmp_path/'native-releases/native-next';native.mkdir(parents=True)
    (native/'index.html').write_text('reviewed frontend',encoding='utf-8')
    release.atomic(native/'native-manifest.json',{'release':native.name,'files':{'index.html':release.sha(native/'index.html')}})
    frontend={'release':native.name,'manifest_sha256':release.sha(native/'native-manifest.json')}
    (runtime/'launch.py').write_text('# fixture',encoding='utf-8')
    for sid in ('content-production','topic-research','content-writing','image-production',
                'reference-analysis','delivery-review','publication-analysis','experience-distillation'):
        shutil.copytree(PROJECT/'skills/builtin'/sid,tmp_path/'skills/builtin'/sid)
    shutil.copytree(PROJECT/'skills/shared/workbench',tmp_path/'skills/shared/workbench')
    shutil.copytree(PROJECT/'agents/workspace',tmp_path/'agents/workspace')
    shutil.copytree(tmp_path/'skills',runtime/'skills')
    shutil.copytree(tmp_path/'agents',runtime/'agents')
    upgrade._fixture_skill_source=tmp_path/'skills/builtin/content-writing/SKILL.md'
    release.atomic(runtime/'workbench-release.json',{'release':runtime.name,'native':frontend,
        'capabilities_type':'easel_project_builtin','capabilities_sha256':release.capabilities_revision(tmp_path),
        'workspace_sha256':release.workspace_revision(tmp_path),
        'files':{p.relative_to(runtime).as_posix():release.sha(p) for p in runtime.rglob('*') if p.is_file()}})
    choice={'release':runtime.name,'manifest_sha256':release.sha(runtime/'workbench-release.json'),'native':frontend}
    release.atomic(state/'candidate.json',choice)
    (state/'evidence.json').write_text('{"passed":true}',encoding='utf-8')
    acceptance=state/'upgrade-acceptance.json'
    release.atomic(acceptance,{'passed':True,'candidate':choice,'evidence':{(state/'evidence.json').relative_to(tmp_path).as_posix():release.sha(state/'evidence.json')}})
    return upgrade,state,native,acceptance,choice


def test_upgrade_verifies_new_runtime_and_frontend_as_one_pair(tmp_path,monkeypatch):
    upgrade,state,native,acceptance,choice=upgrade_fixture(tmp_path,monkeypatch)
    assert upgrade.validate_candidate(tmp_path,state,acceptance)[0]==choice
    assert not (state/'admission.json').exists()
    assert not (tmp_path/'data').exists()


def test_upgrade_rejects_changed_frontend_before_fencing(tmp_path,monkeypatch):
    upgrade,state,native,acceptance,choice=upgrade_fixture(tmp_path,monkeypatch)
    (native/'index.html').write_text('unreviewed frontend',encoding='utf-8')
    with pytest.raises(ValueError,match='Frontend member changed'):
        upgrade.validate_candidate(tmp_path,state,acceptance)
    assert not (state/'admission.json').exists()


def test_upgrade_rejects_skill_source_drift_before_fencing(tmp_path,monkeypatch):
    upgrade,state,native,acceptance,choice=upgrade_fixture(tmp_path,monkeypatch)
    with upgrade._fixture_skill_source.open('a',encoding='utf-8') as stream:stream.write('\nUnreviewed skill instructions.\n')
    with pytest.raises(ValueError,match='Skill source changed'):
        upgrade.validate_candidate(tmp_path,state,acceptance)
    assert not (state/'admission.json').exists()


def test_upgrade_rejects_workspace_source_drift_before_fencing(tmp_path,monkeypatch):
    upgrade,state,native,acceptance,choice=upgrade_fixture(tmp_path,monkeypatch)
    with (tmp_path/'agents/workspace/AGENTS.md').open('a',encoding='utf-8') as stream:
        stream.write('\nUnreviewed workspace instruction.\n')
    with pytest.raises(ValueError,match='Workspace instructions changed'):
        upgrade.validate_candidate(tmp_path,state,acceptance)
    assert not (state/'admission.json').exists()


def test_release_freezes_project_builtin_assets_and_workspace_in_temp(tmp_path,monkeypatch):
    upgrade,state,native,acceptance,choice=upgrade_fixture(tmp_path,monkeypatch)
    module=release_module();monkeypatch.setattr(module,'ROOT',tmp_path)
    for folder in ('easel_workbench','easel','config'):
        (tmp_path/folder).mkdir()
    selected=module.freeze(native.name)
    frozen=tmp_path/'workbench-releases'/selected['release']
    manifest=module.verify(frozen,selected['manifest_sha256'])
    assert manifest['capabilities_type']=='easel_project_builtin'
    assert manifest['capabilities_sha256']==module.capabilities_revision(tmp_path)==module.capabilities_revision(frozen)
    assert manifest['workspace_sha256']==module.workspace_revision(frozen)
    assert 'agents/workspace/AGENTS.md' in manifest['files']
    assert 'skills/builtin/content-production/SKILL.md' in manifest['files']
    assert any(name.endswith('认可母版.png') for name in manifest['files'])


@pytest.mark.parametrize('status,hook,start_hook,expected',[
    ('accepted','not_started',None,True),('submitting','not_started',None,True),
    ('running','not_started','completed',True),('unknown','unknown',None,True),
    ('completed','pending','completed',True),('completed','completed','pending',True),
    ('completed','completed','completed',False),('failed','failed',None,False),
    ('stopped','completed','completed',False),
])
def test_idle_observes_chat_native_and_business_hook_lifecycle(tmp_path,monkeypatch,status,hook,start_hook,expected):
    from types import SimpleNamespace
    monkeypatch.syspath_prepend(str(PROJECT/'scripts'))
    module=load('workbench_chat_idle_test',PROJECT/'scripts/activate_workbench.py')
    old=tmp_path/'old';directory=old/'evidence/simplify-workbench-20261029';directory.mkdir(parents=True)
    module.atomic(directory/'audit.json',{})
    reference={'path':'evidence/simplify-workbench-20261029/audit.json','sha256':module.sha(directory/'audit.json')}
    module.atomic(directory/'activation-evidence.json',{'historical_unknown_audit':reference,'collection_historical_unknown_audit':reference})
    database=tmp_path/'data/desk.sqlite';database.parent.mkdir()
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE easel_chat_turns(id TEXT PRIMARY KEY,document TEXT)')
        connection.execute('INSERT INTO easel_chat_turns VALUES(?,?)',('turn-synthetic',json.dumps({'status':status,'hook_status':hook,'start_hook_status':start_hook})))
    monkeypatch.setattr(module,'OLD',old)
    monkeypatch.setattr(module,'legacy',lambda:(SimpleNamespace(exists_table=lambda connection,table:connection.execute("SELECT 1 FROM sqlite_master WHERE name=?",(table,)).fetchone() is not None),
        SimpleNamespace(busy_state=lambda *_:{'busy':False,'retained_collection_unknown':[]})))
    result=module.idle(database)
    assert result['busy'] is expected
    if expected:assert result['additional']==[{'table':'easel_chat_turns','id':'turn-synthetic'}]


def test_reviewed_builtin_plan_and_upgrade_order_only_activate_after_stop(tmp_path,monkeypatch):
    from types import SimpleNamespace
    upgrade,state,native,acceptance,choice=upgrade_fixture(tmp_path,monkeypatch)
    release=release_module();package=upgrade.validate_candidate(tmp_path,state,acceptance)[1]
    plan_path=state/'builtin-plan.json';expected='reviewed-plan-hash'
    release.atomic(plan_path,{'plan_sha256':expected,'source_revision':'source-revision',
        'source':{'catalog_revision':package['capabilities_sha256']},'conflicts':[],'busy':[]})
    document=json.loads(acceptance.read_text(encoding='utf-8'))
    document['evidence'][plan_path.relative_to(tmp_path).as_posix()]=release.sha(plan_path)
    release.atomic(acceptance,document)
    binding=upgrade.reviewed_builtin_plan(tmp_path,package,acceptance,plan_path,expected)
    assert binding['plan_sha256']==expected
    with pytest.raises(ValueError,match='exact idle'):
        upgrade.reviewed_builtin_plan(tmp_path,package,acceptance,plan_path,'other')
    data=tmp_path/'data';data.mkdir();sqlite3.connect(data/'desk.sqlite').close()
    previous={'release':'workbench-before','manifest_sha256':'previous-runtime'}
    release.atomic(data/'active-workbench.json',previous)
    release.atomic(data/'active-native.json',{'release':'native-before','manifest_sha256':'previous-frontend'})
    release.atomic(data/'migration-owner.json',{'target_root':str(tmp_path),**previous})
    release.atomic(state/'deployment.json',{'candidate':previous})
    order=[]
    monkeypatch.setattr(upgrade,'ROOT',tmp_path);monkeypatch.setattr(upgrade,'STATE',state)
    monkeypatch.setattr(upgrade,'idle',lambda *_:{'busy':False})
    monkeypatch.setattr(upgrade,'queue_idle',lambda:order.append('queue_read'))
    monkeypatch.setattr(upgrade,'authenticate',lambda:SimpleNamespace(close=lambda:None))
    def stopped():
        assert json.loads((state/'admission.json').read_text())['workers'] is False
        (state/'paused').write_text('synthetic stop',encoding='utf-8');order.append('stopped')
    monkeypatch.setattr(upgrade,'stop_new_profile',stopped)
    def activate(root,selected):
        assert order[-1]=='stopped' and selected['plan_sha256']==expected
        assert (state/'paused').is_file()
        assert json.loads((data/'active-workbench.json').read_text())==previous
        order.append('skills_applied');return {'applied':True,'jobs_requeued':0}
    monkeypatch.setattr(upgrade,'activate_builtin_after_stop',activate)
    monkeypatch.setattr(upgrade.subprocess,'Popen',lambda *args,**kwargs:SimpleNamespace(pid=9999))
    monkeypatch.setattr(upgrade.subprocess,'CREATE_NO_WINDOW',getattr(upgrade.subprocess,'CREATE_NO_WINDOW',0),raising=False)
    monkeypatch.setattr(upgrade,'smoke',lambda *_:{'ready':True})
    monkeypatch.setattr(sys,'argv',['upgrade','--acceptance',str(acceptance),'--builtin-plan',str(plan_path),'--builtin-plan-sha256',expected])
    upgrade.main()
    assert order==['queue_read','stopped','skills_applied']
    result=json.loads((state/'runtime-upgrade.json').read_text(encoding='utf-8'))
    assert result['builtin_activation']['applied'] and result['database_restored'] is False
    assert json.loads((state/'admission.json').read_text())['workers'] is True


def test_upgrade_rejects_evidence_from_different_frontend(tmp_path,monkeypatch):
    upgrade,state,native,acceptance,choice=upgrade_fixture(tmp_path,monkeypatch)
    document=json.loads(acceptance.read_text(encoding='utf-8'))
    document['candidate']['native']['release']='native-unreviewed'
    acceptance.write_text(json.dumps(document),encoding='utf-8')
    with pytest.raises(ValueError,match='Acceptance does not match'):
        upgrade.validate_candidate(tmp_path,state,acceptance)


def test_upgrade_rejects_evidence_path_outside_project(tmp_path,monkeypatch):
    upgrade,state,native,acceptance,choice=upgrade_fixture(tmp_path,monkeypatch)
    outside=tmp_path.parent/(tmp_path.name+'-outside.json');outside.write_text('{}',encoding='utf-8')
    document=json.loads(acceptance.read_text(encoding='utf-8'))
    document['evidence']={'../'+outside.name:release_module().sha(outside)}
    acceptance.write_text(json.dumps(document),encoding='utf-8')
    with pytest.raises(ValueError,match='Acceptance evidence changed'):
        upgrade.validate_candidate(tmp_path,state,acceptance)


@pytest.mark.parametrize('receipt_status',['requested','uncertain'])
def test_idle_scans_authoritative_model_receipts_after_migration(tmp_path,monkeypatch,receipt_status):
    from types import SimpleNamespace
    import sqlite3
    monkeypatch.syspath_prepend(str(PROJECT/'scripts'))
    module=load('workbench_idle_controls_test',PROJECT/'scripts/activate_workbench.py')
    old=tmp_path/'retained-old';evidence=old/'evidence/simplify-workbench-20261029';evidence.mkdir(parents=True)
    audit=evidence/'audit.json';audit.write_text('{}',encoding='utf-8')
    reference={'path':audit.relative_to(old).as_posix(),'sha256':module.sha(audit)}
    module.atomic(evidence/'activation-evidence.json',{'historical_unknown_audit':reference,'collection_historical_unknown_audit':reference})
    root=tmp_path/'authoritative';database=root/'data/desk.sqlite';database.parent.mkdir(parents=True)
    sqlite3.connect(database).close()
    cache=database.parent/'collection/model-cache';cache.mkdir(parents=True)
    module.atomic(cache/'new-receipt.json',{'status':receipt_status})
    monkeypatch.setattr(module,'OLD',old)
    monkeypatch.setattr(module,'legacy',lambda:(SimpleNamespace(exists_table=lambda *_:False),
        SimpleNamespace(busy_state=lambda *_:{'busy':False,'retained_collection_unknown':[]})))
    result=module.idle(database)
    assert result['busy'] and result['additional']==[
        {'table':'collection_model_receipt','id':'new-receipt','status':receipt_status}]


def test_idle_retains_only_byte_identical_audited_historical_receipt(tmp_path,monkeypatch):
    from types import SimpleNamespace
    import sqlite3
    monkeypatch.syspath_prepend(str(PROJECT/'scripts'))
    module=load('workbench_idle_retention_test',PROJECT/'scripts/activate_workbench.py')
    old=tmp_path/'retained-old';evidence=old/'evidence/simplify-workbench-20261029';evidence.mkdir(parents=True)
    audit=evidence/'audit.json';audit.write_text('{}',encoding='utf-8')
    reference={'path':audit.relative_to(old).as_posix(),'sha256':module.sha(audit)}
    module.atomic(evidence/'activation-evidence.json',{'historical_unknown_audit':reference,'collection_historical_unknown_audit':reference})
    database=tmp_path/'authoritative/data/desk.sqlite';database.parent.mkdir(parents=True)
    sqlite3.connect(database).close()
    receipt=database.parent/'collection/model-cache/historical.json'
    module.atomic(receipt,{'status':'uncertain','input':'synthetic frozen input'})
    retained={'id':'historical','cache_sha256':module.sha(receipt)}
    monkeypatch.setattr(module,'OLD',old)
    monkeypatch.setattr(module,'legacy',lambda:(SimpleNamespace(exists_table=lambda *_:False),
        SimpleNamespace(busy_state=lambda *_:{'busy':False,'retained_collection_unknown':[retained]})))
    assert module.idle(database)['busy'] is False
    module.atomic(receipt,{'status':'uncertain','input':'changed input'})
    assert module.idle(database)['busy'] is True


class StopSupervisor(BaseException):
    pass


def supervisor_fixture(tmp_path,monkeypatch,*,admit=False):
    module=load('easel_workbench.supervisor_controls_test',PROJECT/'easel_workbench/supervisor.py')
    from easel_workbench import processes
    monkeypatch.setattr(processes,'existing',lambda *args,**kwargs:None)
    state=tmp_path/'.local/workbench-deployment';state.mkdir(parents=True)
    data=tmp_path/'data';data.mkdir()
    release=tmp_path/'workbench-releases/workbench-fixture';release.mkdir(parents=True)
    manifest=release/'workbench-release.json';manifest.write_text('{}',encoding='utf-8')
    import hashlib
    (data/'active-workbench.json').write_text(json.dumps({'release':release.name,'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()}),encoding='utf-8')
    (state/'admission.json').write_text(json.dumps({'workers':admit}),encoding='utf-8')
    started=[]
    class Process:
        def __init__(self,*args,**kwargs):
            self.pid=100+len(started);started.append(args[0])
        def poll(self):return None
    monkeypatch.setattr(module.subprocess,'Popen',Process)
    def stop(_):raise StopSupervisor()
    monkeypatch.setattr(module.time,'sleep',stop)
    return module,state,data,started


def test_server_only_before_worker_admission(tmp_path,monkeypatch):
    module,state,data,started=supervisor_fixture(tmp_path,monkeypatch)
    with pytest.raises(StopSupervisor):module.main(tmp_path)
    assert [command[2] for command in started]==['server']


def test_admission_enables_existing_roles_without_extra_schedules(tmp_path,monkeypatch):
    module,state,data,started=supervisor_fixture(tmp_path,monkeypatch,admit=True)
    (data/'feedback-config.json').write_text('{}',encoding='utf-8')
    (data/'collection-config.json').write_text('{"enabled":true}',encoding='utf-8')
    (data/'learning-enabled.json').write_text('{"enabled":false}',encoding='utf-8')
    with pytest.raises(StopSupervisor):module.main(tmp_path)
    assert [command[2] for command in started]==['server','worker','publisher','feedback','collector']


def test_changed_selected_manifest_starts_nothing(tmp_path,monkeypatch):
    module,state,data,started=supervisor_fixture(tmp_path,monkeypatch)
    choice=json.loads((data/'active-workbench.json').read_text(encoding='utf-8'));choice['manifest_sha256']='0'*64
    (data/'active-workbench.json').write_text(json.dumps(choice),encoding='utf-8')
    with pytest.raises(RuntimeError):module.main(tmp_path)
    assert not started


def test_supervisor_adopts_verified_owned_server_without_relaunch(tmp_path,monkeypatch):
    module,state,data,started=supervisor_fixture(tmp_path,monkeypatch)
    from easel_workbench import processes
    class Existing:
        pid=7654
        def poll(self):return None
        def close(self):pass
    calls=[]
    def owned(*args,**kwargs):
        calls.append((args,kwargs));return Existing()
    monkeypatch.setattr(processes,'existing',owned)
    with pytest.raises(StopSupervisor):module.main(tmp_path)
    assert not started and len(calls)==1
    status=json.loads((state/'pids.json').read_text(encoding='utf-8'))
    assert status['roles']=={'server':7654}


def test_supervisor_rejects_selector_directory_traversal(tmp_path,monkeypatch):
    module,state,data,started=supervisor_fixture(tmp_path,monkeypatch)
    choice=json.loads((data/'active-workbench.json').read_text(encoding='utf-8'));choice['release']='../../outside'
    (data/'active-workbench.json').write_text(json.dumps(choice),encoding='utf-8')
    with pytest.raises(RuntimeError):module.main(tmp_path)
    assert not started


def test_pre_admission_and_pause_reject_business_posts_before_handler(tmp_path,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from easel_workbench import application
    from easel_workbench.runtime import toolbox_server
    fake=FastAPI();calls=[]
    @fake.post('/api/works')
    def create():calls.append('business');return {'accepted':True}
    @fake.get('/api/config')
    def config():return {'ready':True}
    @fake.post('/login')
    def login():return {'login':True}
    monkeypatch.setenv('EASEL_WORKBENCH_ADMISSION','1')
    monkeypatch.setattr(toolbox_server,'create_app',lambda **kwargs:fake)
    state=tmp_path/'.local/workbench-deployment';state.mkdir(parents=True)
    with TestClient(application.create_app(root=tmp_path)) as client:
        assert client.post('/api/works',json={'id':'preserved-operation'}).status_code==503
        assert calls==[]
        assert client.get('/api/config').status_code==200
        assert client.post('/login').status_code==200
        (state/'admission.json').write_text('{"workers":false}',encoding='utf-8')
        assert client.post('/api/works',json={'id':'preserved-operation'}).status_code==503
        assert calls==[]
        (state/'admission.json').write_text('{"workers":true}',encoding='utf-8')
        assert client.post('/api/works',json={'id':'preserved-operation'}).status_code==200
        assert calls==['business']
        (state/'paused').touch()
        assert client.post('/api/works',json={'id':'another-operation'}).status_code==503
        assert calls==['business']


def test_cim_microsecond_precision_keeps_exact_native_identity_handle(monkeypatch):
    from easel_workbench import processes
    native_ticks=133116604567890127
    class Identity:
        creation_ticks=native_ticks
        closed=False
        def __init__(self,pid):self.pid=pid
        def close(self):self.closed=True
    monkeypatch.setattr(processes,'ProcessIdentity',Identity)
    handle=processes.checked_identity({'pid':4321,'creation_ticks':str(native_ticks-native_ticks%10)})
    assert handle.pid==4321 and handle.creation_ticks==native_ticks
    assert not handle.closed


def test_different_creation_microsecond_rejects_and_closes_handle(monkeypatch):
    from easel_workbench import processes
    created=[]
    class Identity:
        creation_ticks=133116604567890127
        def __init__(self,pid):self.pid=pid;self.closed=False;created.append(self)
        def close(self):self.closed=True
    monkeypatch.setattr(processes,'ProcessIdentity',Identity)
    with pytest.raises(ValueError,match='identity changed'):
        processes.checked_identity({'pid':4321,'creation_ticks':'133116604567890130'})
    assert len(created)==1 and created[0].closed
