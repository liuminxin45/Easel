"""TEMP-only immutable package and admission controls; no real process launch."""
import importlib.util
import json
from pathlib import Path
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
