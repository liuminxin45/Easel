"""Official source delegation with TEMP references and no media/provider calls."""
import hashlib
import importlib.util
import json
import io
import os
import base64
from pathlib import Path
import sys

import pytest

from easel_workbench.runtime import easel_integration as integration
from easel_workbench.runtime import easel_media_worker as worker
from easel_workbench.runtime.easel_source import OFFICIAL_SCRIPTS, MEDIA_FILES, media_source


def test_current_media_catalog_and_source_use_main_official_files(monkeypatch,tmp_path):
    assert OFFICIAL_SCRIPTS==Path(__file__).resolve().parents[1]/'skills/shared/scripts'
    source=media_source()
    assert source['kind']=='official_main_tree' and source['path']=='skills/shared/scripts'
    assert set(source['files'])==set(MEDIA_FILES)
    for name,digest in source['files'].items():assert hashlib.sha256((OFFICIAL_SCRIPTS/name).read_bytes()).hexdigest()==digest
    # Loading the current catalog must not need even an existing vendor tree.
    monkeypatch.setattr(integration,'SOURCE',tmp_path/'nonexistent-old-vendor')
    actual=integration.load_catalog()
    spec=importlib.util.spec_from_file_location('fixture_main_media_registry',OFFICIAL_SCRIPTS/'model_registry.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    for channel in ('image','video','music'):assert actual[channel]==module.MODEL_GROUPS[channel]
    assert actual['speech']==module.MODEL_GROUPS['voice' if 'voice' in module.MODEL_GROUPS else 'speech']


@pytest.mark.parametrize('name',['voice_clone','ai_image','ai_video','ai_music'])
def test_each_runner_dispatches_same_official_file_not_vendor(monkeypatch,name):
    calls=[]
    monkeypatch.setattr(sys,'argv',[])
    monkeypatch.setattr(worker.runpy,'run_path',lambda path,run_name:calls.append((Path(path),run_name,list(sys.argv))))
    worker.run_official(name,['check'],OFFICIAL_SCRIPTS)
    assert calls==[(OFFICIAL_SCRIPTS/(name+'.py'),'__main__',[str(OFFICIAL_SCRIPTS/(name+'.py')),'check'])]
    with pytest.raises(ValueError):worker.run_official(name,[],Path('old/vendor/easel/scripts'))


def test_multireference_adapter_loads_actual_official_script_and_preserves_all_bytes(monkeypatch,tmp_path):
    monkeypatch.syspath_prepend(str(OFFICIAL_SCRIPTS))
    first,second=tmp_path/'one.png',tmp_path/'two.png'
    first.write_bytes(b'TEMP approved exact first');second.write_bytes(b'TEMP approved exact second')
    original=importlib.util.spec_from_file_location
    results={}
    def spec_port(name,path,*args,**kwargs):
        assert Path(path)==OFFICIAL_SCRIPTS/'ai_image.py'
        spec=original(name,path,*args,**kwargs);real_loader=spec.loader
        class Loader:
            def create_module(self,spec):return None
            def exec_module(self,module):
                real_loader.exec_module(module)
                module.http_post=lambda url,key,payload,**kw:results.update(payload=payload)
                def run(argv):
                    body,content_type=module._encode_multipart({},[('image','old.png','image/png',b'old'),('mask','mask.png','image/png',b'mask-bytes')])
                    results.update(body=body,content_type=content_type,argv=argv)
                    module.http_post('https://never.called.test','TEMP',{'image_urls':[], 'extra_body':{'image':[]}})
                module.main=run
        spec.loader=Loader();return spec
    monkeypatch.setattr(importlib.util,'spec_from_file_location',spec_port)
    monkeypatch.setattr(sys,'argv',[])
    worker.run_official('ai_image',['img2img'],OFFICIAL_SCRIPTS,[str(first),str(second)])
    assert first.read_bytes() in results['body'] and second.read_bytes() in results['body'] and b'mask-bytes' in results['body']
    assert b'filename="old.png"' not in results['body']
    assert len(results['payload']['image_urls'])==2 and results['payload']['image_urls']==results['payload']['extra_body']['image']


def test_source_alignment_does_not_enable_retired_new_media_tasks(tmp_path):
    (tmp_path/'data').mkdir();flags=tmp_path/'data/easel-runtime.json'
    flags.write_text(json.dumps({'accept_new_tasks':False,'preserve_records':True}),encoding='utf-8')
    adapter=object.__new__(integration.EaselIntegration);adapter.root=tmp_path
    before=flags.read_bytes()
    for stage in ('speech','image','video','music','transcribe','compose'):assert adapter.accepts_new(stage) is False
    integration.load_catalog()
    assert flags.read_bytes()==before


def test_reconciliation_remains_read_only_and_cannot_submit_without_exact_task():
    with pytest.raises(worker.TaskPending):worker.read_only_reconcile({'env':{}},{},Path('not-written'))


@pytest.mark.parametrize('release',[None,'f'*64])
def test_real_worker_rejects_old_or_missing_source_before_any_provider_call(tmp_path,monkeypatch,release):
    payload={'id':'old-job','fingerprint':'exact-original','directory':str(tmp_path/'stage')}
    if release is not None:payload['source_release']=release
    original=json.dumps(payload)
    plan=tmp_path/'old-plan.json';plan.write_text(original,encoding='utf-8')
    monkeypatch.setattr(sys,'stdin',io.StringIO(original))
    calls=[]
    monkeypatch.setattr(worker,'run_official',lambda *a,**k:calls.append('provider-script'))
    monkeypatch.setattr(worker.urllib.request,'urlopen',lambda *a,**k:calls.append('provider-http'))
    assert worker.main()==0
    receipt=json.loads((tmp_path/'stage/receipt.json').read_text(encoding='utf-8'))
    assert receipt['status']=='failed' and receipt['send_state']=='not_sent'
    assert '冻结源码' in receipt['error'] and receipt['tool_events']==[] and calls==[]
    assert plan.read_text(encoding='utf-8')==original
    # Even an injected host runner cannot bypass the same source boundary.
    adapter=object.__new__(integration.EaselIntegration);adapter.runner=lambda value:calls.append('host-runner')
    with pytest.raises(ValueError):adapter._invoke_worker(payload,Path(sys.executable))
    assert calls==[]


def worker_environment(monkeypatch,tmp_path,payload):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(os,'environ',dict(os.environ))
    monkeypatch.setattr(sys,'path',list(sys.path))
    monkeypatch.setattr(sys,'stdin',io.StringIO(json.dumps(payload)))


def test_real_worker_current_source_can_complete_ordinary_local_fixture(tmp_path,monkeypatch):
    payload={'id':'current-job','fingerprint':'current-original','directory':str(tmp_path/'stage'),
             'source_release':media_source()['source_tree_sha256'],'env':{},'stage':'image','options':{},
             'source_paths':[],'instruction':'TEMP local test, no model'}
    worker_environment(monkeypatch,tmp_path,payload);calls=[]
    def produce(name,args,source,images=None):
        from PIL import Image
        calls.append((name,source));Image.new('RGB',(2,2),'white').save(Path(args[args.index('-o')+1]),format='PNG')
    monkeypatch.setattr(worker,'run_official',produce)
    assert worker.main()==0
    receipt=json.loads((tmp_path/'stage/receipt.json').read_text(encoding='utf-8'))
    assert receipt['status']=='completed' and calls==[('ai_image',OFFICIAL_SCRIPTS)]
    assert receipt['implementation_source']==media_source() and receipt['outputs']


def test_real_worker_old_source_reconcile_uses_only_exact_status_get_and_original_key(tmp_path,monkeypatch):
    from types import SimpleNamespace
    from PIL import Image
    buffer=io.BytesIO();Image.new('RGB',(2,2),'white').save(buffer,format='PNG')
    directory=tmp_path/'stage';directory.mkdir()
    original_source={'source_tree_sha256':'old-vendor'}
    saved={'job_id':'old-job','fingerprint':'exact-old','status':'unknown','send_state':'unknown','outputs':[],
           'tool_events':[],'upstream_task_id':'exact-upstream-task','_poll_url':'https://provider.test/tasks/exact-upstream-task',
           'implementation_source':original_source}
    (directory/'receipt.json').write_text(json.dumps(saved),encoding='utf-8')
    payload={'id':'old-job','fingerprint':'exact-old','directory':str(directory),'source_release':'old-vendor',
             'mode':'reconcile','stage':'image','config':{'provider':'original'},'options':{},
             'env':{'IMG_BASE_URL':'https://provider.test','ORIGINAL_KEY':'TEMP-original-key'}}
    worker_environment(monkeypatch,tmp_path,payload)
    monkeypatch.setitem(sys.modules,'model_registry',SimpleNamespace(MODEL_GROUPS={'image':{'providers':[{'id':'original','keys':[{'env':'ORIGINAL_KEY'}]}]}}))
    monkeypatch.setattr(worker,'run_official',lambda *a,**k:pytest.fail('Reconciliation cannot start a script or POST'))
    requests=[]
    def get(request,**kwargs):
        requests.append(request)
        return io.BytesIO(json.dumps({'status':'completed','b64_json':base64.b64encode(buffer.getvalue()).decode()}).encode())
    monkeypatch.setattr(worker.urllib.request,'urlopen',get)
    assert worker.main()==0
    receipt=json.loads((directory/'receipt.json').read_text(encoding='utf-8'))
    assert receipt['status']=='completed' and receipt['implementation_source']==original_source
    assert len(requests)==1 and requests[0].get_method()=='GET'
    assert requests[0].full_url==saved['_poll_url'] and requests[0].get_header('Authorization')=='Bearer TEMP-original-key'
    assert payload['source_release']=='old-vendor'
