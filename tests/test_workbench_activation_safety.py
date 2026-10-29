"""Cutover control checks use TEMP data and fake processes only."""
from pathlib import Path
import ast
import hashlib
import importlib
import json
import os
import shutil
import sqlite3
import types

import pytest

PROJECT=Path(__file__).resolve().parents[1]


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding='utf-8')


def prepare_data_function(old,new,state):
    """Load the actual pure composition function, without importing Win32 ops."""
    tree=ast.parse((PROJECT/'scripts/activate_workbench.py').read_text(encoding='utf-8'))
    node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='prepare_data')
    context={'ROOT':new,'OLD':old,'STATE':state,'importlib':importlib,'shutil':shutil,
             'os':os,'read':read,'atomic':write}
    exec(compile(ast.Module(body=[node],type_ignores=[]),'activate_workbench.py','exec'),context)
    return context['prepare_data']


def fixture_paths(tmp_path):
    old=tmp_path/'original';new=tmp_path/'Easel';state=new/'.local/workbench-deployment'
    (old/'data').mkdir(parents=True);state.mkdir(parents=True)
    with sqlite3.connect(old/'data/desk.sqlite') as c:
        c.execute('create table historical(id text primary key, frozen text)')
        c.execute('insert into historical values(?,?)',('unknown-receipt','原冻结输入，不可重放'))
    write(old/'data/collection-sources.json',{'profile_dir':str(old/'data/collection/profile'),'state_root':str(old/'data/collection/sources')})
    write(old/'data/active-web.json',{'release':'web-old','manifest_sha256':'old'})
    write(old/'data/active-native.json',{'release':'native-old','manifest_sha256':'old'})
    for folder,name in [('releases','web-old'),('native-releases','native-old')]:
        p=old/folder/name;p.mkdir(parents=True);(p/'index.html').write_text('retained shell')
    (new/'scripts').mkdir()
    shutil.copy2(PROJECT/'scripts/migrate_workbench_data.py',new/'scripts/migrate_workbench_data.py')
    for name in ('sources.json','usage_registry.json','collection_schedules.json'):
        write(new/'easel_workbench/runtime'/name,{'retained':'source'})
    return old,new,state


def test_final_copy_rebases_mutable_collection_paths_and_preserves_frozen_rows(tmp_path):
    old,new,state=fixture_paths(tmp_path)
    source_db=(old/'data/desk.sqlite').read_bytes()
    choice={'release':'workbench-fixture','manifest_sha256':'runtime','native':{'release':'native-new','manifest_sha256':'frontend'}}
    report=prepare_data_function(old,new,state)(choice)
    cfg=read(new/'data/collection-sources.json')
    assert Path(cfg['profile_dir']).is_relative_to(new/'data')
    assert Path(cfg['state_root']).is_relative_to(new/'data')
    assert str(old) not in json.dumps(cfg)
    with sqlite3.connect(new/'data/desk.sqlite') as c:
        assert c.execute('select * from historical').fetchall()==[('unknown-receipt','原冻结输入，不可重放')]
    assert (old/'data/desk.sqlite').read_bytes()==source_db
    assert read(new/'data/active-workbench.json')['release']==choice['release']
    assert report['mutable_config_rewrites']['collection-sources.json']==['profile_dir','state_root']


def test_prepare_refuses_existing_data_without_overwriting_it(tmp_path):
    old,new,state=fixture_paths(tmp_path)
    (new/'data').mkdir();(new/'data/owner.txt').write_text('pre-existing owner data')
    choice={'release':'workbench-fixture','manifest_sha256':'runtime','native':{}}
    with pytest.raises(ValueError,match='already exists'):
        prepare_data_function(old,new,state)(choice)
    assert (new/'data/owner.txt').read_text()=='pre-existing owner data'


@pytest.mark.skipif(os.name!='nt',reason='The supervisor uses Windows process locks')
def test_fresh_manager_admits_server_only_and_launches_frozen_root(tmp_path,monkeypatch):
    from easel_workbench import supervisor,processes
    root=tmp_path/'Easel';release=root/'workbench-releases/workbench-fixture';release.mkdir(parents=True)
    manifest=release/'workbench-release.json';manifest.write_text('{}')
    write(root/'data/active-workbench.json',{'release':release.name,'manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest()})
    write(root/'.local/workbench-deployment/admission.json',{'workers':False})
    for name,key in [('collection-config.json','enabled'),('learning-enabled.json','enabled'),('automation-enabled.json','local_io')]:
        write(root/'data'/name,{key:True})
    started=[]
    def popen(command,**kwargs):
        started.append((command,kwargs))
        return types.SimpleNamespace(pid=123456,poll=lambda:None)
    class EndIteration(BaseException):pass
    monkeypatch.setattr(supervisor.subprocess,'Popen',popen)
    monkeypatch.setattr(processes,'existing',lambda *args:None)
    monkeypatch.setattr(supervisor.time,'sleep',lambda seconds:(_ for _ in ()).throw(EndIteration()))
    monkeypatch.setenv('PYTHONPATH','old/untrusted/source')
    try:
        with pytest.raises(EndIteration):supervisor.main(root)
        assert len(started)==1
        command,options=started[0]
        assert Path(command[1])==release/'launch.py' and command[2]=='server'
        assert command[command.index('--root')+1]==str(root.resolve())
        assert options['cwd']==release and 'PYTHONPATH' not in options['env']
        assert Path(command[0])==Path(supervisor.sys.executable)
        status=read(root/'.local/workbench-deployment/pids.json')
        assert status['roles']=={'server':123456}
    finally:
        for _,options in started:options['stdout'].close()
