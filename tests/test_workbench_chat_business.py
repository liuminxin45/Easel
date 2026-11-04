"""Project skills and native conversations with TEMP data and fake inference."""
import asyncio
import copy
import json
from pathlib import Path
import shutil

import pytest

from easel_workbench.chat import ChatService,ChatConflict
from easel_workbench.chat_business import ChatBusiness,PlanConflict
from easel_workbench.runtime.creator_runtime import CreatorRuntime
from easel_workbench.runtime.desk import Store
from easel_workbench.runtime.toolbox_store import Toolbox
from easel_workbench import skill_catalog

ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def business(tmp_path):
    for sid in [s['id'] for s in skill_catalog.ProjectSkillCatalog(ROOT).entries()]:
        shutil.copytree(ROOT/'skills/builtin'/sid,tmp_path/'skills/builtin'/sid)
    shutil.copytree(ROOT/'skills/shared/workbench',tmp_path/'skills/shared/workbench')
    workspace=tmp_path/'agents/workspace';workspace.mkdir(parents=True)
    (workspace/'AGENTS.md').write_text('TEMP Easel shared workspace',encoding='utf-8')
    box=Toolbox(Store(tmp_path/'data/desk.sqlite'),tmp_path)
    box.creator=CreatorRuntime(box)
    b=ChatBusiness(box)
    b.chat=ChatService(box,on_accept=b.accept,on_started=b.started,on_finish=b.finished)
    b.chat.create_session({'id':'create-session','session_id':'test-chat','profile_id':'oil-pig'})
    return b


def value(action='poster',tid='turn-one'):
    return {'sessionId':'test-chat','turnId':tid,'message':'说明本次具体变化，保留准确来源。',
            'attachments':[],'context':{'skill_id':'topic-research' if action=='discuss' else 'content-production',
                                      'action_id':'native','profile_id':'oil-pig'}}


def test_history_projects_only_available_generated_images(business,monkeypatch,tmp_path):
    path=tmp_path/'candidate.png';path.write_bytes(b'candidate')
    source='C:/Users/person/.codex/generated_images/thread/image.png'
    monkeypatch.setattr(business.chat,'history',lambda *args,**kwargs:{'session':{'messages':[{'role':'assistant','turnId':'turn-image','content':f'[候选]({source})'}]},'linked_works':[]})
    with business.store.connect() as c:
        c.execute('CREATE TABLE easel_generated_image_sources(turn_id TEXT,source TEXT,artifact_id TEXT,sha256 TEXT)')
        c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)',('image-id','turn-image','candidate.png',str(path),'image/png'))
        c.execute('INSERT INTO easel_generated_image_sources VALUES(?,?,?,?)',('turn-image',source,'image-id','hash'))
    message=business.history('test-chat')['session']['messages'][0]
    assert message['content']=='[候选](/api/files/image-id)' and len(message['output_files'])==1
    path.unlink()
    message=business.history('test-chat')['session']['messages'][0]
    assert message['content']=='候选（图片暂不可用）' and message['output_files']==[]


def confirmed(b,action='poster',tid='turn-one'):
    from easel_workbench.features.skills.retirement import SkillFeatureRetired
    raise SkillFeatureRetired('legacy-test-plan-fixture')


def test_generic_prepare_preserves_exact_input_without_private_plan_snapshot_or_work(business,monkeypatch):
    b=business;v={'sessionId':'test-chat','turnId':'plain-input','message':' 原始一行\n 第二行 ','context':{}}
    monkeypatch.setattr(b.creator,'resolve',lambda *a,**k:pytest.fail('ordinary native chat cannot resolve a private workflow'))
    prepared=b.prepare(v)
    assert v['message'] in prepared['actual_prompt'] and prepared['snapshot'] is None and prepared['work'] is None
    from easel.persona import turn_reminder
    assert turn_reminder() in prepared['actual_prompt']
    assert 'frozen_instructions' in prepared
    with b.store.connect() as c:
        assert c.execute('SELECT count(*) FROM easel_chat_plans').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM toolbox_works').fetchone()[0]==0


@pytest.mark.parametrize('legacy',[{'version':1},{'plan_token':'old-plan'},{'work_id':'old-work'},
    {'parent_version_id':'old-version'},{'trial':True},{'skill_revision':'old-sha'},{'action_id':'poster'}])
def test_new_private_orchestration_fields_are_retired(business,legacy):
    from easel_workbench.features.skills.retirement import SkillFeatureRetired
    with pytest.raises(SkillFeatureRetired):business.prepare({'sessionId':'test-chat','turnId':'legacy-input','message':'raw','context':legacy})


def test_attachment_only_generic_chat_references_actual_verified_material_without_inventing_user_text(business):
    b=business;upload=b.box.upload('only-material','素材.txt',b'Exact original material')
    v={'sessionId':'test-chat','turnId':'material-only','message':'','context':{},'attachments':[{'id':upload['id'],'name':upload['name']}]}
    prepared=b.prepare(v);assert prepared['snapshot'] is None and prepared['work'] is None
    data=json.loads(prepared['actual_prompt'].split('## 本轮附件\n',1)[1]);assert len(data)==1
    assert Path(data[0]['path']).read_bytes()==b'Exact original material'
    assert v['message']==''


def test_explicit_project_skill_uses_same_official_native_message_and_no_plan(business,monkeypatch):
    b=business;v=value()
    monkeypatch.setattr(b.creator,'resolve',lambda *a,**k:pytest.fail('project SKILL must not invoke private workflow resolution'))
    prepared=b.prepare(v)
    assert prepared['snapshot'] is None and prepared['work'] is None
    assert '请执行 /content-production，内容如下：' in prepared['actual_prompt']
    assert prepared['actual_prompt'].split('内容如下：\n\n',1)[1].startswith(v['message']+'\n\n## 画像显式创作默认值')
    material=json.loads((b.root/'outputs/_sessions/inputs'/v['turnId']/'manifest.json').read_text(encoding='utf-8'))
    assert material['input_text'].startswith(v['message'])
    assert material['creation']['defaults']=={} and material['material_manifest']['files']==[]
    assert '## 本轮冻结输入' not in prepared['actual_prompt']


def test_actual_generic_turn_uses_existing_native_engine_once_and_never_creates_private_work(business,monkeypatch):
    from easel import harnesses
    calls=[]
    class Native:
        async def run(self,request,emit,ask,bind):
            calls.append(request);bind('native-generic');request.on_native_turn('native-generic','native-generic-turn')
            emit('token','TEMP actual generic result')
    monkeypatch.setattr(harnesses,'adapter',lambda runtime:Native())
    async def scenario():
        b=business;v=value();original=b.prepare(v);turn=await b.chat.submit(v,**original)
        async for _ in b.chat.events(turn['id']):pass
        assert b.chat.get_turn(turn['id'],private=True)['actual_prompt']==original['actual_prompt']
        assert b.chat.get_turn(turn['id'])['status']=='completed'
        assert len(calls)==1 and b.prepare(v)['receipt']['id']==turn['id']
        assert b.history('test-chat')['linked_works']==[]
        with b.store.connect() as c:
            assert c.execute('SELECT count(*) FROM toolbox_works').fetchone()[0]==0
            assert c.execute('SELECT count(*) FROM creator_work_owners').fetchone()[0]==0
            assert c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0]==0
            assert c.execute('SELECT count(*) FROM creator_task_runs').fetchone()[0]==0
        await b.chat.close()
    asyncio.run(scenario())


def test_historical_receipt_is_read_before_retired_field_validation_without_replay(business,monkeypatch):
    from easel_workbench.features.conversations.receipts import sha
    b=business;value={'sessionId':'test-chat','turnId':'original-turn','message':' 原始输入 ',
        'context':{'plan_token':'old','version':1,'work_id':'old-work'}}
    old={'id':'original-turn','session_id':'test-chat','status':'completed','hook_status':'completed',
        'snapshot':{'task':'poster','skills':[{'id':'content-production','version':1,'prompt':'HISTORICAL EXACT METHOD'}]},
        'work':{'work_id':'old-work','version_id':'original-turn'},'request_signature':sha(value),
        'actual_prompt':'HISTORICAL EXACT PROMPT'}
    raw=json.dumps(old,ensure_ascii=False,indent=3)
    with b.store.connect() as c:c.execute('INSERT INTO easel_chat_turns VALUES(?,?,?,?,?)',('original-turn','test-chat','original-turn','legacy-signature',raw))
    monkeypatch.setattr(b,'_session',lambda *a:pytest.fail('historical receipt cannot resolve current session or skill'))
    receipt=b.prepare(value)['receipt']
    assert receipt['id']=='original-turn' and receipt['work']==old['work']
    assert b.chat.get_turn('original-turn',private=True)['snapshot']==old['snapshot']
    with b.store.connect() as c:assert c.execute('SELECT document FROM easel_chat_turns WHERE id=?',('original-turn',)).fetchone()[0]==raw

def test_owner_http_ports_use_original_auth_origin_csrf_and_native_sse(business,monkeypatch):
    from easel import harnesses
    from easel_workbench.runtime.toolbox_server import create_app
    import httpx
    class Auth:
        data={'origin':'https://temp.local','host':'temp.local','secret':'A'*32}
        def session(self,token):return {'csrf':'fixture','until':9999999999} if token=='fixture-owner' else None
    class Reply:
        async def run(self,r,emit,ask,bind):
            bind('native-http');r.on_native_turn('native-http','native-http-turn');emit('token','TEMP原生输出')
    monkeypatch.setattr(harnesses,'adapter',lambda runtime:Reply())
    async def scenario():
        b=business;app=create_app(store=b.store,auth=Auth(),box=b.box,root=b.root)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://temp.local') as client:
            assert (await client.get('/api/chat/sessions')).status_code==401
            client.cookies.set('__Host-desk_session','fixture-owner')
            cfg=(await client.get('/api/config')).json()
            headers={'Origin':'https://temp.local','X-CSRF-Token':cfg['csrf']}
            v={'id':'http-new','session_id':'http-session','profile_id':'oil-pig','action':'create'}
            assert (await client.post('/api/chat/sessions',json=v)).status_code==403
            assert (await client.post('/api/chat/sessions',json=v,headers=headers)).status_code==200
            payload={'sessionId':'http-session','turnId':'http-one','message':'讨论本次目标','context':{}}
            result=await client.post('/api/chat/stream',json=payload,headers=headers)
            assert result.status_code==200 and result.headers['content-type'].startswith('text/event-stream')
            assert 'event: accepted' in result.text and 'event: token' in result.text and 'event: done' in result.text
            assert (await client.get('/api/chat/last/http-session')).json()['clean_end']
            assert (await client.get('/api/chat/sessions')).json()['sessions'][0]['message_count']==2
            assert (await client.get('/api/chat/jobs/http-one/stream')).status_code==200
            assert (await client.get('/api/skills')).json()[0]['name']
            assert (await client.get('/api/skill/content-production')).json()['name']=='content-production'
        await app.state.chat.close()
    asyncio.run(scenario())


def test_revoked_stream_stops_reading_without_cancelling_the_native_turn(business,monkeypatch):
    from easel import harnesses
    from easel_workbench.chat_api import stream
    class Waiting:
        def __init__(self):self.release=None;self.cancelled=False
        async def run(self,r,emit,ask,bind):
            bind('native-revocation');r.on_native_turn('native-revocation','native-revocation-turn')
            emit('token','撤销前可见')
            try:await self.release.wait()
            except asyncio.CancelledError:self.cancelled=True;raise
            emit('token','撤销后不再向旧连接交付')
    adapter=Waiting();monkeypatch.setattr(harnesses,'adapter',lambda runtime:adapter)
    async def scenario():
        b=business;adapter.release=asyncio.Event()
        v={'sessionId':'test-chat','turnId':'revoked-turn','message':'讨论目标','context':{}}
        turn=await b.chat.submit(v,**b.prepare(v))
        allowed=[True];reader=stream(b.chat,turn['id'],accepted=True,authenticated=lambda:allowed[0]).body_iterator
        assert 'event: accepted' in await anext(reader)
        allowed[0]=False
        with pytest.raises(StopAsyncIteration):await asyncio.wait_for(anext(reader),2)
        assert not adapter.cancelled and not b.chat._tasks[turn['id']].done()
        adapter.release.set();await b.chat._tasks[turn['id']]
        assert '撤销后' in b.chat.get_turn(turn['id'])['output']
        await b.chat.close()
    asyncio.run(scenario())


def test_native_trace_uses_exact_easel_project_authority(tmp_path,monkeypatch):
    import sqlite3
    from easel_workbench.runtime import bridge,task_runtime
    native=tmp_path/'native-state.sqlite';project=tmp_path/'easel';project.mkdir()
    rollout=tmp_path/'native-rollout.jsonl';rollout.write_text('native event evidence',encoding='utf-8')
    with sqlite3.connect(native) as c:
        c.execute('CREATE TABLE threads(id TEXT,cwd TEXT,rollout_path TEXT)')
        c.execute('INSERT INTO threads VALUES(?,?,?)',('exact-native',str(project),str(rollout)))
    monkeypatch.setattr(bridge,'STATE',native)
    assert task_runtime.target_for_thread('exact-native',expected_project=project)==rollout
    with pytest.raises(ValueError):task_runtime.target_for_thread('exact-native',expected_project=tmp_path/'other-project')
    with pytest.raises(ValueError):task_runtime.target_for_thread('missing-native',expected_project=project)


def test_frozen_output_paths_reject_ancestors_links_and_windows_stream_names(tmp_path):
    from easel_workbench.paths import owned_output_path
    root=tmp_path/'project';root.mkdir();outside=tmp_path/'outside';outside.mkdir()
    for value in ('outputs/../escape','outputs/materials/file:stream','outputs/materials/CON.txt'):
        with pytest.raises(ValueError):owned_output_path(root,value)
    import os,subprocess
    if os.name=='nt':
        subprocess.run(['cmd','/c','mklink','/J',str(root/'outputs'),str(outside)],check=True,capture_output=True)
    else:(root/'outputs').symlink_to(outside,target_is_directory=True)
    with pytest.raises(ValueError):owned_output_path(root,'outputs/_sessions/materials/test/file.txt')
    assert not (outside/'_sessions').exists()
