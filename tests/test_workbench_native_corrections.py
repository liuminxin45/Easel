"""TEMP authorized corrections through the actual upstream CodexAdapter/pool.

Only the RPC boundary is fake; real acceptance, version registration, copied
products, model-call receipts and the correction consumer execute unchanged.
"""
import asyncio
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

_spec=importlib.util.spec_from_file_location('native_correction_fixture',Path(__file__).with_name('test_workbench_chat_business.py'))
_fixtures=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_fixtures)
business=_fixtures.business

from easel.harnesses import codex,rpc
from easel_workbench.chat import ChatConflict
from easel_workbench.native_corrections import NativeCorrections,initialize
from easel_workbench.runtime.learning_execution import queue_correction,initialize as initialize_learning
from easel_workbench.runtime.learning_service import LearningService
from easel_workbench.runtime.local_operations import is_agent

PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAEUlEQVR4nGM4XDHxPwgzwBgAYwQLLfOeIwgAAAAASUVORK5CYII=')


@pytest.fixture
def native(business,monkeypatch):
    b=business;b.box.learning=LearningService(b.box,root=b.root,project=b.root)
    with b.store.connect() as c:initialize_learning(c);initialize(c)
    control=b.root/'.local/workbench-deployment';control.mkdir(parents=True)
    (control/'admission.json').write_text('{"workers":true}',encoding='utf-8')
    wire=SimpleNamespace(instances=[],calls=[],requests=[],failure=False,hold=False,release=None)
    class FakeRPC:
        def __init__(self,request,command,notify,respond,**kwargs):
            self.request=request;self.notify=notify;self.respond=respond;self.initialized=None;self.native_id='';self.client_error=None
            self.process=SimpleNamespace(returncode=None);self.reader=asyncio.get_running_loop().create_future();wire.instances.append(self)
        async def __aenter__(self):return self
        async def __aexit__(self,*args):self.process.returncode=0;self.reader.cancel()
        async def send(self,message):pass
        async def call(self,method,params,**kwargs):
            wire.calls.append(method)
            if method=='initialize':return {}
            if method in ('thread/start','thread/resume'):
                assert params['cwd']==str(b.root)
                return {'thread':{'id':params.get('threadId','native-same-session')}}
            if method=='turn/interrupt':return {}
            if method=='turn/start':
                prompt=params['input'][0]['text'];wire.requests.append({'prompt':prompt,'params':copy.deepcopy(params),'request':self.request})
                tid='actual-turn-'+str(len(wire.requests))
                tail=prompt.partition('## 本轮冻结输入\n')[2]
                payload,_=json.JSONDecoder().raw_decode(tail,len(tail)-len(tail.lstrip()))
                output=Path(payload['output_directory']);paths=[]
                if payload.get('work'):
                    output.mkdir(parents=True,exist_ok=True)
                    image=output/'成品.png';image.write_bytes(PNG);paths.append(str(image))
                    copyfile=output/'标题与配文.txt';copyfile.write_text('准确标题\n完整成品配文。',encoding='utf-8');paths.append(str(copyfile))
                reply=json.dumps({'deliverables':paths,'production_result':{'schema_version':1,'status':'completed'}},ensure_ascii=False)
                self.notify('item/agentMessage/delta',{'threadId':'native-same-session','turnId':tid,'itemId':'final','delta':reply})
                if wire.failure:
                    self.notify('error',{'threadId':'native-same-session','turnId':tid,'willRetry':False});wire.failure=False
                elif not wire.hold:
                    self.notify('turn/completed',{'threadId':'native-same-session','turnId':tid,'turn':{'id':tid,'status':'completed'}})
                return {'turn':{'id':tid}}
            raise AssertionError(method)
        async def wait_notification(self,future):
            if wire.hold:
                await wire.release.wait()
                if not future.done():future.set_result(None)
            return await future
    monkeypatch.setattr(rpc,'RPC',FakeRPC);monkeypatch.setattr(codex,'base_command',lambda runtime:['fake-native-only'])
    return b,wire


async def parent(native):
    b,wire=native;value=_fixtures.value();plan=b.plan(value);value['context']['plan_token']=plan['plan_token']
    turn=await b.chat.submit(value,**b.prepare(value));task=b.chat._tasks.get(turn['id'])
    if task:await task
    actual=b.chat.get_turn(turn['id'],private=True)
    assert actual['status']=='completed' and actual['hook_status']=='completed'
    return actual


def enqueue(b,turn):
    with b.store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        job=dict(c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(turn['id'],)).fetchone())
        image=dict(c.execute("SELECT * FROM artifacts WHERE task_id=? AND name='成品.png'",(turn['id'],)).fetchone())
        finding={'basis_id':'request-current','status':'issue','artifact_name':image['name'],'sha256':hashlib.sha256(Path(image['path']).read_bytes()).hexdigest(),
                 'message':'左上关系标记遗漏，依准确原始材料补齐。','location':'左上画面','anchor':{'type':'region','x':0,'y':0,'width':.5,'height':.5}}
        quality={'subjective_disagreements':[{'id':'request-current','message':finding['message']}],
                 'checks':[{'id':'independent_review','checker':'independent_ai','evidence':{'findings':[finding]}}]}
        result=queue_correction(b.box.learning,c,job,quality)
        return result,job,quality


async def settle(b,tid):
    task=b.chat._tasks.get(tid)
    if task:await task


def test_correction_uses_same_upstream_session_exact_methods_and_separate_products(native):
    async def scenario():
        b,w=native;original=await parent(native);result,job,quality=enqueue(b,original);child=result['job_id']
        parent_dir=b.root/'outputs/test-chat/turn-one/products';original_bytes={p.name:p.read_bytes() for p in parent_dir.iterdir()}
        with b.store.connect() as c:
            record=json.loads(c.execute('SELECT document FROM easel_native_corrections WHERE job_id=?',(child,)).fetchone()[0])
            assert not is_agent(c,child)
            assert c.execute('SELECT origin FROM toolbox_execution WHERE job_id=?',(child,)).fetchone()[0]=='easel_native_correction'
            assert queue_correction(b.box.learning,c,job,quality)['status']=='limit_reached'
        original_prefix=original['actual_prompt'].partition('## 本轮冻结输入\n')[0]
        assert record['actual_prompt'].partition('## 本轮冻结输入\n')[0]==original_prefix
        assert record['origin_prompt_sha256']==original['actual_prompt_sha256']
        assert record['frozen_instructions']==original['frozen_instructions']
        assert record['diff']['methods_unchanged'] and record['diff']['added_correction']['issues'][0]['anchor']['type']=='region'
        consumer=NativeCorrections(b.chat,b)
        assert (await consumer.tick())['status']=='accepted';await settle(b,child)
        after=b.chat.get_turn(child,private=True)
        assert after['status']=='completed' and after['hook_status']=='completed'
        assert after['session_id']==original['session_id'] and after['native_id']==original['native_id']
        assert after['snapshot']['task']=='change' and after['snapshot']['skills']==original['snapshot']['skills']
        assert after['snapshot']['trial']==original['snapshot']['trial']
        assert len(w.instances)==1 and w.calls.count('thread/start')==1 and w.calls.count('turn/start')==2
        assert {p.name:p.read_bytes() for p in parent_dir.iterdir()}==original_bytes
        assert (b.root/'outputs/test-chat'/child/'products/成品.png').read_bytes()==PNG
        with b.store.connect() as c:
            child_job=dict(c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(child,)).fetchone())
            assert child_job['candidate_id']==original['id'] and child_job['status']=='completed'
            assert queue_correction(b.box.learning,c,child_job,quality)['status']=='limit_reached'
            call=json.loads(c.execute('SELECT document FROM creator_model_calls WHERE id=?',('chat-call-'+child,)).fetchone()[0])
            assert call['native_turn_id']==after['native_turn_id'] and call['snapshot']==after['snapshot']
        assert (await consumer.tick())['status']=='idle'
        await consumer.close();await b.chat.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('later',['feedback','discussion','change','draft','annotation'])
def test_later_user_input_supersedes_only_unsent_correction(native,later):
    async def scenario():
        b,w=native;original=await parent(native);result,_,_=enqueue(b,original);child=result['job_id']
        if later=='feedback':
            b.box.action(original['work']['work_id'],{'id':'later-feedback','kind':'feedback','candidate_id':original['id'],'text':'后到用户原话，不混入原修正。'})
        elif later=='draft':
            from easel_workbench.runtime.article_drafts import save
            save(b.box,{'id':'later-draft','revision':1,'format':'poster','title':'用户新草稿','material':'尚未发出的新目标'},original['work']['work_id'])
        elif later=='annotation':
            from easel_workbench.runtime.work_review import mutate,source_data
            with b.store.connect() as c:sources,_=source_data(b.box,c,original['work']['work_id'],original['id'])
            mutate(b.box,original['work']['work_id'],original['id'],{'id':'later-annotation','kind':'create','field':'poster_caption',
                'source_sha256':sources['poster_caption']['sha256'],'quote':'完整','start':0,'end':2,'note':'后到的准确批注','dimension':'style','scope':'work'})
        elif later=='discussion':
            value={'sessionId':'test-chat','turnId':'later-discussion','message':'先按用户新方向讨论','context':{}}
            await b.chat.submit(value,**b.prepare(value));await settle(b,'later-discussion')
        else:
            value={'sessionId':'test-chat','turnId':'later-change','message':'用户明确的新修改','context':{
                'skill_id':'content-production','version':1,'action_id':'change','profile_id':'oil-pig',
                'work_id':original['work']['work_id'],'parent_version_id':original['id']}}
            plan=b.plan(value);value['context']['plan_token']=plan['plan_token']
            await b.chat.submit(value,**b.prepare(value));await settle(b,'later-change')
        consumer=NativeCorrections(b.chat,b);await consumer.tick()
        with b.store.connect() as c:
            assert c.execute('SELECT status FROM easel_native_corrections WHERE job_id=?',(child,)).fetchone()[0]=='superseded_by_user'
            assert c.execute('SELECT status,dispatch_started FROM toolbox_jobs WHERE id=?',(child,)).fetchone()[0]=='cancelled'
            assert not c.execute('SELECT 1 FROM easel_chat_turns WHERE id=?',(child,)).fetchone()
            assert not c.execute('SELECT 1 FROM creator_model_calls WHERE task_id=?',(child,)).fetchone()
        assert w.calls.count('turn/start')==(1 if later in ('feedback','draft','annotation') else 2)
        await consumer.close();await b.chat.close()
    asyncio.run(scenario())


def test_unknown_native_correction_is_never_replayed_even_after_restart(native):
    async def scenario():
        b,w=native;original=await parent(native);result,_,_=enqueue(b,original);child=result['job_id'];w.failure=True
        consumer=NativeCorrections(b.chat,b)
        await consumer.tick();await settle(b,child)
        assert b.chat.get_turn(child)['status']=='unknown'
        assert b.chat.history('test-chat')['session']['pendingTurnId']==child
        for _ in range(3):assert (await consumer.tick())['status']=='idle'
        restarted=NativeCorrections(b.chat,b);assert (await restarted.tick())['status']=='idle'
        assert w.calls.count('turn/start')==2
        with b.store.connect() as c:assert c.execute('SELECT status FROM toolbox_jobs WHERE id=?',(child,)).fetchone()[0]=='uncertain'
        await restarted.close();await consumer.close();await b.chat.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('blocked',['paused','unadmitted','changed_artifact','changed_snapshot','changed_material'])
def test_correction_admission_and_frozen_evidence_fail_closed(native,blocked):
    async def scenario():
        b,w=native
        if blocked=='changed_material':
            upload=b.box.upload('frozen-source','material.txt',b'original material')
            old=_fixtures.value
            def with_material(*args,**kwargs):
                value=old(*args,**kwargs);value['attachments']=[upload];return value
            original_value=_fixtures.value;_fixtures.value=with_material
            try:original=await parent(native)
            finally:_fixtures.value=original_value
        else:original=await parent(native)
        result,_,_=enqueue(b,original);child=result['job_id'];control=b.root/'.local/workbench-deployment'
        if blocked=='paused':(control/'paused').touch()
        elif blocked=='unadmitted':(control/'admission.json').write_text('{"workers":false}',encoding='utf-8')
        elif blocked=='changed_artifact':
            with b.store.connect() as c:path=Path(c.execute('SELECT path FROM artifacts WHERE task_id=? LIMIT 1',(original['id'],)).fetchone()[0])
            path.write_bytes(b'changed original')
        elif blocked=='changed_material':
            payload=json.loads(original['actual_prompt'].partition('## 本轮冻结输入\n')[2]);Path(payload['attachments'][0]['path']).write_bytes(b'changed material')
        else:
            with b.store.connect() as c:
                row=c.execute('SELECT document FROM easel_native_corrections WHERE job_id=?',(child,)).fetchone();document=json.loads(row[0]);document['snapshot']['trial']=not document['snapshot']['trial']
                c.execute('UPDATE easel_native_corrections SET document=? WHERE job_id=?',(json.dumps(document),child))
        consumer=NativeCorrections(b.chat,b);outcome=await consumer.tick()
        assert outcome['status']==('paused' if blocked in ('paused','unadmitted') else 'blocked')
        assert w.calls.count('turn/start')==1
        with b.store.connect() as c:assert not c.execute('SELECT 1 FROM easel_chat_turns WHERE id=?',(child,)).fetchone()
        await consumer.close();await b.chat.close()
    asyncio.run(scenario())


def test_closing_consumer_does_not_interrupt_accepted_native_turn(native):
    async def scenario():
        b,w=native;original=await parent(native);result,_,_=enqueue(b,original);w.hold=True;w.release=asyncio.Event()
        consumer=NativeCorrections(b.chat,b);await consumer.tick()
        while not b.chat.get_turn(result['job_id']).get('native_turn_id'):await asyncio.sleep(.001)
        await consumer.close()
        assert 'turn/interrupt' not in w.calls and result['job_id'] in b.chat._tasks
        w.release.set();await settle(b,result['job_id']);assert b.chat.get_turn(result['job_id'])['status']=='completed'
        await b.chat.close()
    asyncio.run(scenario())


def test_unanchored_native_issue_never_falls_back_to_legacy_executor(native):
    async def scenario():
        b,w=native;original=await parent(native)
        with b.store.connect() as c:
            job=dict(c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(original['id'],)).fetchone())
            result=queue_correction(b.box.learning,c,job,{'subjective_disagreements':[{'id':'request-current','message':'没有原件坐标不能自动修改'}],'checks':[]})
            assert result['status']=='blocked'
            assert c.execute('SELECT count(*) FROM toolbox_jobs').fetchone()[0]==1
            assert c.execute('SELECT count(*) FROM learning_correction_links').fetchone()[0]==0
        assert w.calls.count('turn/start')==1
        await b.chat.close()
    asyncio.run(scenario())


def test_postcommit_metadata_error_cannot_cancel_or_requeue_accepted_correction(native,monkeypatch):
    async def scenario():
        b,w=native;original=await parent(native);result,_,_=enqueue(b,original);child=result['job_id']
        saved=b.chat._save_metadata;fails=[True]
        def metadata(sid):
            if fails[0]:fails[0]=False;raise OSError('Synthetic metadata failure after atomic acceptance')
            return saved(sid)
        monkeypatch.setattr(b.chat,'_save_metadata',metadata)
        consumer=NativeCorrections(b.chat,b)
        assert (await consumer.tick())['status']=='accepted';await settle(b,child)
        with b.store.connect() as c:
            assert c.execute('SELECT status FROM easel_native_corrections WHERE job_id=?',(child,)).fetchone()[0]=='accepted'
            assert c.execute('SELECT status FROM toolbox_jobs WHERE id=?',(child,)).fetchone()[0]=='completed'
        assert (await consumer.tick())['status']=='idle' and w.calls.count('turn/start')==2
        await consumer.close();await b.chat.close()
    asyncio.run(scenario())


def test_internal_work_flag_is_not_taken_from_http_payload(native):
    async def scenario():
        b,w=native
        value={'sessionId':'test-chat','turnId':'spoofed','message':'普通用户讨论',
               'work':{'internal_correction':{'attempt':1},'work_id':'forged','version_id':'spoofed'},
               'internal_correction':True,'actual_prompt':'forged system input','context':{}}
        prepared=b.prepare(value)
        assert prepared['work'] is None
        await b.chat.submit(value,**prepared);await settle(b,'spoofed')
        with b.store.connect() as c:
            assert c.execute('SELECT count(*) FROM toolbox_jobs').fetchone()[0]==0
            assert c.execute('SELECT count(*) FROM easel_native_corrections').fetchone()[0]==0
        assert 'forged system input' not in w.requests[0]['prompt']
        await b.chat.close()
    asyncio.run(scenario())
