"""TEMP pointer-only deployment; live auth, process controls and DB stay untouched."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT=Path(__file__).resolve().parents[1]
_spec=importlib.util.spec_from_file_location('frontend_activation_test_module',ROOT/'scripts/activate_workbench_frontend.py')
activation=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(activation)


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False),encoding='utf-8')


def fingerprint(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def native(root,name,source):
    directory=root/'native-releases'/name;directory.mkdir(parents=True)
    files={'index.html':'<meta name="native-release" content="'+name+'"><script type="module" src="/native-assets/'+name+'/app.js"></script>',
           'auth.html':'TEMP public login shell','app.js':'/* immutable '+name+' */','sw.js':'/* TEMP service worker '+name+' */',
           'manifest.webmanifest':'{"scope":"/native/"}'}
    for member,body in files.items():(directory/member).write_text(body,encoding='utf-8')
    write(directory/'build-inputs.json',{'node':'v24.19.0','inputs':{source.relative_to(root).as_posix():fingerprint(source)}})
    write(directory/'native-manifest.json',{'schema':1,'release':name,'architecture':'easel-workbench-extension',
          'files':{path.name:fingerprint(path) for path in directory.iterdir()}})
    return {'release':name,'manifest_sha256':fingerprint(directory/'native-manifest.json')}


@pytest.fixture
def fixture(tmp_path,monkeypatch):
    root=tmp_path;source=root/'web/frontend/src/workbench/screen.tsx';source.parent.mkdir(parents=True);source.write_text('TEMP frontend source',encoding='utf-8')
    previous=native(root,'native-before',source);candidate=native(root,'native-after',source)
    runtime=root/'workbench-releases/workbench-current';runtime.mkdir(parents=True);(runtime/'launch.py').write_text('TEMP immutable runtime',encoding='utf-8')
    write(runtime/'workbench-release.json',{'release':runtime.name,'native':previous,'files':{'launch.py':fingerprint(runtime/'launch.py')}})
    backend={'release':runtime.name,'manifest_sha256':fingerprint(runtime/'workbench-release.json')}
    data=root/'data';state=root/'.local/workbench-deployment';data.mkdir()
    write(data/'active-workbench.json',backend);write(data/'active-native.json',previous);write(data/'active-web.json',{'release':'legacy-kept'})
    write(data/'migration-owner.json',{'target_root':str(root),**backend});write(state/'admission.json',{'workers':True})
    write(state/'cutover.json',{'target_root':str(root),'phase':'live','candidate':{'release':backend['release']}})
    database=data/'desk.sqlite';database.write_bytes(b'TEMP DB sentinel; activation must never open this file')
    roles={'manager':{'pid':101,'creation_ticks':123001},'roles':{'server':{'pid':102,'creation_ticks':123002},'worker':{'pid':103,'creation_ticks':123003}}}
    process_calls=[]
    def process_snapshot(project,selected):
        assert project==root and selected==backend;process_calls.append(True);return copy.deepcopy(roles)
    monkeypatch.setattr(activation,'process_snapshot',process_snapshot)
    out=root/'.local/workbench-validation/frontend';out.mkdir(parents=True)
    references={}
    for kind in ('browser','upgrade','frontend'):
        report={'passed':True,'native':candidate}
        if kind in ('browser','upgrade'):
            report.update(backend={'directory':str(runtime),'manifest_sha256':backend['manifest_sha256']},real_AI_calls=0,real_platform_writes=0,checks=[{'check':'TEMP exact candidate','passed':True}])
        if kind=='upgrade':report['previous']=previous
        if kind=='frontend':
            transcript=out/'node-tests.txt';transcript.write_text('TEMP node contract transcript: passed 3 tests',encoding='utf-8')
            report.update(test_count=3,evidence={transcript.name:fingerprint(transcript)})
        path=out/(kind+'.json');write(path,report);references[kind]={'path':path.relative_to(root).as_posix(),'sha256':fingerprint(path)}
    acceptance_path=out/'acceptance.json'
    acceptance=copy.deepcopy({'schema_version':1,'passed':True,'backend':backend,'previous_native':previous,'native':candidate,'evidence':references})
    write(acceptance_path,acceptance)
    class Response:
        def __init__(self,body=b'',status=200,document=None):self.content=body;self.status_code=status;self.document=document;self.text=body.decode('utf-8')
        def json(self):return self.document
    class Client:
        def __init__(self):self.closed=False;self.gets=[]
        def get(self,url):
            self.gets.append(url);selected=activation.read(data/'active-native.json');directory=root/'native-releases'/selected['release']
            if url.startswith('/api/'):return Response(document={})
            if url=='/native/version':return Response(document={'release':selected['release']})
            if url=='/native/':return Response((directory/'index.html').read_bytes())
            if url.startswith('/native-assets/'):
                _,_,release,*member=url.split('/');return Response((root/'native-releases'/release/Path(*member)).read_bytes())
            names={'/native/sw.js':'sw.js','/native/manifest.webmanifest':'manifest.webmanifest'}
            return Response((directory/names[url]).read_bytes())
        def close(self):self.closed=True
    client=Client();auth_calls=[]
    def authenticate():auth_calls.append(True);return client
    monkeypatch.setattr(activation,'authenticate',authenticate)
    return SimpleNamespace(root=root,source=source,previous=previous,candidate=candidate,backend=backend,state=state,
                           runtime=runtime,acceptance=acceptance,path=acceptance_path,client=client,auth_calls=auth_calls,
                           process_calls=process_calls,roles=roles,database=database)


def test_preview_validates_only_and_does_not_authenticate_or_change_selectors(fixture):
    f=fixture;before=activation.controls(f.root)
    result=activation.execute(f.path,root=f.root)
    assert result['status']=='ready' and result['applied'] is False and not f.auth_calls
    assert activation.controls(f.root)==before and f.database.read_bytes().startswith(b'TEMP DB sentinel')


def test_pointer_only_apply_preserves_runtime_manifest_controls_database_and_processes(fixture):
    f=fixture;before=activation.controls(f.root);manifest=(f.runtime/'workbench-release.json').read_bytes();database=f.database.read_bytes()
    result=activation.execute(f.path,root=f.root,apply=True,expected_native=f.previous['release'])
    assert result['status']=='live' and result['before_processes']==result['after_processes']==f.roles
    assert result['workers_restarted'] is False and result['business_database_opened'] is False
    assert activation.controls(f.root)=={**before,'native':f.candidate}
    assert f.database.read_bytes()==database and (f.runtime/'workbench-release.json').read_bytes()==manifest
    assert activation.read(f.runtime/'workbench-release.json')['native']==f.previous
    assert f.client.closed and f.auth_calls==[True]
    assert set(f.client.gets)>={'/native/version','/native/','/native/sw.js','/native/manifest.webmanifest'}
    assert activation.read(f.state/'frontend-upgrades'/(f.candidate['release']+'.json'))==result


@pytest.mark.parametrize('change',['asset','source','evidence','transcript','backend','previous','paused','admission'])
def test_changed_candidate_or_live_baseline_is_rejected_before_pointer_write(fixture,change):
    f=fixture
    if change=='asset':(f.root/'native-releases'/f.candidate['release']/'app.js').write_text('Changed candidate',encoding='utf-8')
    elif change=='source':f.source.write_text('Newer unvalidated source',encoding='utf-8')
    elif change=='evidence':(f.path.parent/'browser.json').write_text('{}',encoding='utf-8')
    elif change=='transcript':(f.path.parent/'node-tests.txt').write_text('Changed node transcript',encoding='utf-8')
    elif change in ('backend','previous'):
        f.acceptance['backend' if change=='backend' else 'previous_native']['manifest_sha256']='0'*64;write(f.path,f.acceptance)
    elif change=='paused':(f.state/'paused').touch()
    elif change=='admission':write(f.state/'admission.json',{'workers':False})
    with pytest.raises(ValueError):activation.execute(f.path,root=f.root,apply=True)
    assert activation.read(f.root/'data/active-native.json')==f.previous and not f.auth_calls


def test_documents_and_tests_outside_build_inputs_do_not_require_backend_refreeze(fixture):
    f=fixture;(f.root/'docs').mkdir();(f.root/'docs/new-note.md').write_text('Changed documentation',encoding='utf-8')
    assert activation.execute(f.path,root=f.root)['status']=='ready'


def test_frontend_summary_can_bind_original_text_transcript_and_string_native(fixture):
    f=fixture;path=f.path.parent/'frontend.json';report=activation.read(path)
    report.update(native=f.candidate['release'],manifest_sha256=f.candidate['manifest_sha256']);write(path,report)
    f.acceptance['evidence']['frontend']['sha256']=fingerprint(path);write(f.path,f.acceptance)
    assert activation.execute(f.path,root=f.root)['status']=='ready'


def test_smoke_failure_rolls_back_only_own_native_selection(fixture,monkeypatch):
    f=fixture;before=activation.controls(f.root)
    monkeypatch.setattr(activation,'frontend_smoke',lambda *args:(_ for _ in ()).throw(ValueError('Synthetic readiness failure')))
    with pytest.raises(ValueError):activation.execute(f.path,root=f.root,apply=True)
    assert activation.controls(f.root)==before and f.client.closed
    failure=activation.read(next((f.state/'frontend-upgrades').glob('*.failure-*.json')))
    assert failure['native_rolled_back'] is True and failure['runtime_stop_requested'] is False


def test_concurrent_native_change_is_never_overwritten_by_failure_rollback(fixture,monkeypatch):
    f=fixture;other={**f.candidate,'release':'native-other-writer'}
    def failed(*args):
        write(f.root/'data/active-native.json',other);raise ValueError('Concurrent writer replaced native selection')
    monkeypatch.setattr(activation,'frontend_smoke',failed)
    with pytest.raises(ValueError):activation.execute(f.path,root=f.root,apply=True)
    assert activation.read(f.root/'data/active-native.json')==other
    assert activation.read(next((f.state/'frontend-upgrades').glob('*.failure-*.json')))['native_rolled_back'] is False


def test_pid_creation_change_during_smoke_fails_and_reverts_frontend(fixture,monkeypatch):
    f=fixture;original=activation.frontend_smoke
    def smoke(*args):
        result=original(*args);f.roles['roles']['worker']['creation_ticks']+=1;return result
    monkeypatch.setattr(activation,'frontend_smoke',smoke)
    with pytest.raises(ValueError,match='processes changed'):activation.execute(f.path,root=f.root,apply=True)
    assert activation.read(f.root/'data/active-native.json')==f.previous


def test_guard_rechecks_native_and_runtime_after_authentication(fixture,monkeypatch):
    f=fixture;other={**f.previous,'release':'native-concurrent'}
    def authentication():write(f.root/'data/active-native.json',other);return f.client
    monkeypatch.setattr(activation,'authenticate',authentication)
    with pytest.raises(ValueError,match='changed before'):activation.execute(f.path,root=f.root,apply=True)
    assert activation.read(f.root/'data/active-native.json')==other


def test_process_ownership_and_exact_native_creation_ticks_are_checked(tmp_path,monkeypatch):
    root=tmp_path;runtime={'release':'workbench-owned','manifest_sha256':'a'*64};state=root/'.local/workbench-deployment'
    write(state/'pids.json',{'release':runtime['release'],'paused':False,'manager':101,'roles':{'server':102}})
    inventory={101:{'pid':101,'name':'pythonw.exe','command':'manager'},102:{'pid':102,'name':'python.exe','command':'server'}}
    arguments={'manager':['pythonw.exe',str(root/'launcher.pyw')],
               'server':['python.exe',str(root/'workbench-releases'/runtime['release']/'launch.py'),'server','--root',str(root),'--port','9123']}
    monkeypatch.setattr(activation,'rows',lambda:inventory);monkeypatch.setattr(activation,'argv',lambda value:arguments[value])
    closed=[]
    monkeypatch.setattr(activation,'checked_identity',lambda row:SimpleNamespace(creation_ticks=row['pid']*100+7,exited=lambda:False,close=lambda:closed.append(row['pid'])))
    result=activation.process_snapshot(root,runtime)
    assert result['manager']['creation_ticks']==10107 and result['roles']['server']['creation_ticks']==10207 and closed==[101,102]
    arguments['server'].append('--unexpected')
    with pytest.raises(ValueError,match='ownership changed'):activation.process_snapshot(root,runtime)
