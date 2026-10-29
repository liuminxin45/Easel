"""Exercise the real __main__ startup and real journal for all seven roles.

Each role runs in its own process with a TEMP root and a flat-import rejection
fence. Only the final business loop/uvicorn is replaced, so no Agent, collector,
publication or production listener can be started by this acceptance.
"""
from __future__ import annotations

import argparse
from importlib.abc import MetaPathFinder
import hashlib
import importlib
import json
import os
from pathlib import Path
import runpy
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

ROLES=('server','worker','collector','publisher','learning','local','feedback')


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(backend):
    manifest=backend/'workbench-release.json';doc=json.loads(manifest.read_text(encoding='utf-8'))
    for relative,expected in doc['files'].items():
        path=(backend/relative).resolve()
        assert path.is_relative_to(backend) and sha(path)==expected,relative
    return {'release':doc['release'],'manifest_sha256':sha(manifest)}


def child(backend,root,role,output):
    selection=verify(backend)
    root.mkdir(parents=True,exist_ok=True)
    for name in ('sources.json','usage_registry.json','collection_schedules.json'):
        shutil.copy2(backend/'easel_workbench/runtime'/name,root/name)
    admission=root/'.local/workbench-deployment/admission.json';admission.parent.mkdir(parents=True)
    admission.write_text('{"workers":true}',encoding='utf-8')
    os.environ['AI_DESK_PROJECT_ROOT']=str(root)
    os.environ['AI_DESK_RELEASE']=selection['release']
    sys.path.insert(0,str(backend))
    flat={p.stem for p in (backend/'easel_workbench/runtime').glob('*.py')}|{'collection_adapters'}
    assert not any(n.split('.')[0] in flat for n in sys.modules)
    refused=[]
    class RefuseFlat(MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if fullname.split('.')[0] in flat:
                refused.append(fullname)
                raise ModuleNotFoundError('Legacy flat import forbidden: '+fullname)
            return None
    sys.meta_path.insert(0,RefuseFlat())
    calls=[]
    if role=='server':
        application=importlib.import_module('easel_workbench.application')
        server_app=SimpleNamespace(state=SimpleNamespace(overviews=object()))
        application.create_app=lambda **kwargs:server_app
        background=importlib.import_module('easel_workbench.runtime.news_overviews')
        background.background=lambda overviews,stop:calls.append('background')
        import uvicorn
        def fake_server(app,**kwargs):
            assert app is server_app and kwargs['host']=='127.0.0.1'
            deadline=time.monotonic()+3
            while 'background' not in calls and time.monotonic()<deadline:time.sleep(.01)
            assert 'background' in calls
            calls.append('server')
        uvicorn.run=fake_server
    else:
        module,function={'worker':('poster_executor','run'),'collector':('collection_worker','run'),
            'publisher':('distribution_worker','run'),'learning':('learning_worker','run'),
            'local':('local_worker','run'),'feedback':('news_feedback','worker')}[role]
        service=importlib.import_module('easel_workbench.runtime.'+module)
        def fake_service(*args,**kwargs):
            if role=='feedback':assert args[0].path.is_relative_to(root)
            calls.append(role)
        setattr(service,function,fake_service)
    sys.argv=['easel_workbench.entry',role,'--root',str(root),'--port','0']
    runpy.run_module('easel_workbench.entry',run_name='__main__')
    journal=importlib.import_module('easel_workbench.runtime.server_logging')
    expected='worker' if role in ('collector','publisher') else role
    assert journal._sink.role==expected
    assert journal._sink.release==selection['release']
    journal._sink.close()
    assert calls.count(role)==1,calls
    assert not refused and not any(n.split('.')[0] in flat for n in sys.modules)
    if os.name=='nt':assert (root/'.local/workbench-deployment/roles'/(role+'.lock')).read_bytes()==b'0'
    entries=[]
    logs=root/'data/logs/toolbox'
    for path in logs.glob('*.jsonl'):
        entries.extend(json.loads(line) for line in path.read_text(encoding='utf-8').splitlines())
        shutil.copy2(path,output/path.name)
    assert any(row.get('event')=='process_started' and row.get('role')==expected and row.get('release')==selection['release'] for row in entries),entries
    result={'passed':True,'requested_role':role,'journal_role':expected,'journal_release':journal._sink.release,'real_journal_configure':True,
        'ran_as_main':True,'flat_aliases':0,'forbidden_import_attempts':refused,
        'business_loop_invocations':calls,'business_loop_stubbed':True,'backend':selection,
        'real_AI_calls':0,'real_platform_writes':0,'real_server_listeners':0}
    (output/(role+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False))


def main(backend,output):
    selection=verify(backend);output.mkdir(parents=True,exist_ok=True)
    records=[]
    for role in ROLES:
        with tempfile.TemporaryDirectory(prefix='easel-entry-'+role+'-') as temp:
            result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--backend',str(backend),'--output',str(output),
                '--child-role',role,'--temporary-root',temp],capture_output=True,text=True,encoding='utf-8',timeout=45)
            (output/(role+'.stdout.log')).write_text(result.stdout,encoding='utf-8')
            (output/(role+'.stderr.log')).write_text(result.stderr,encoding='utf-8')
            assert result.returncode==0,(role,result.returncode,result.stdout,result.stderr)
            records.append(json.loads((output/(role+'.json')).read_text(encoding='utf-8')))
    assert verify(backend)==selection
    report={'passed':True,'backend':selection,'python':sys.executable,'python_version':sys.version,
        'roles':records,'role_count':len(records),'harness_sha256':sha(__file__),
        'real_AI_calls':0,'real_platform_writes':0,'real_server_listeners':0}
    (output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':True,'backend':selection,'role_count':len(records)},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--backend',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--child-role',choices=ROLES);p.add_argument('--temporary-root',type=Path)
    a=p.parse_args();backend=a.backend.resolve();output=a.output.resolve();output.mkdir(parents=True,exist_ok=True)
    if a.child_role:child(backend,a.temporary_root.resolve(),a.child_role,output)
    else:main(backend,output)
