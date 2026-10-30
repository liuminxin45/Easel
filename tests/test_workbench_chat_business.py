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
            'attachments':[],'context':{'skill_id':'content-production','version':1,'action_id':action,'profile_id':'oil-pig'}}


def confirmed(b,action='poster',tid='turn-one'):
    v=value(action,tid);plan=b.plan(v)
    v['context']['plan_token']=plan['plan_token'];v['persona']='oil-pig'
    return v,plan


def test_plan_is_read_only_idempotent_and_exact_root_skill_is_loaded(business):
    b=business;v=value();plan=b.plan(v)
    assert b.plan(v)==plan
    snap=plan['plan']['creator_snapshot']
    assert snap['active_skill_ids']==['content-production','content-writing','image-production']
    assert all(s['entry'].startswith('skills/builtin/') for s in snap['skills'])
    assert b.creator.detail('skill','content-production')['prompt'] in plan['plan']['execution_prompt']['body']
    assert not (b.root/'outputs/_sessions/skill-inputs').exists()
    with b.store.connect() as c:assert c.execute('SELECT count(*) FROM toolbox_jobs').fetchone()[0]==0
    changed=copy.deepcopy(v);changed['message']='另一个目标'
    with pytest.raises(PlanConflict):b.plan(changed)


def test_plan_ignores_display_persona_but_never_recompiles_frozen_input(business):
    b=business;v,plan=confirmed(b)
    p=b.prepare(v)
    assert p['actual_prompt']==plan['plan']['execution_prompt']['body']
    tampered=copy.deepcopy(v);tampered['message']='未确认的变化'
    with pytest.raises(PlanConflict):b.prepare(tampered)
    source=b.root/'skills/builtin/content-writing/SKILL.md'
    source.write_text(source.read_text(encoding='utf-8')+'\nNew unapproved method',encoding='utf-8')
    assert b.plan(value())==plan
    with pytest.raises(PlanConflict):b.prepare(v)


def test_native_acceptance_is_atomic_and_files_are_project_local(business,monkeypatch):
    from easel import harnesses
    class Hold:
        async def run(self,r,emit,ask,bind):
            bind('native-test');r.on_native_turn('native-test','native-turn-test')
            await asyncio.Event().wait()
    monkeypatch.setattr(harnesses,'adapter',lambda runtime:Hold())
    async def scenario():
        b=business;v,plan=confirmed(b)
        result=await b.chat.submit(v,**b.prepare(v));await asyncio.sleep(.03)
        assert result['id']=='turn-one'
        current=b.chat.get_turn(result['id'],private=True)
        with b.store.connect() as c:
            job=c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(result['id'],)).fetchone()
            assert job['status']=='running' and job['turn_id']=='native-turn-test'
            call=json.loads(c.execute('SELECT document FROM creator_model_calls WHERE id=?',('chat-call-turn-one',)).fetchone()[0])
            assert call['status']=='running' and call['native_turn_id']=='native-turn-test'
            frozen=c.execute('SELECT file_id FROM toolbox_review_inputs WHERE job_id=?',(result['id'],)).fetchone()[0]
        assert b.box.file(frozen)[1].is_file()
        bundle=b.root/'outputs/_sessions/skill-inputs'/current['snapshot']['snapshot_sha256']
        assert (bundle/'skills/builtin/content-production/SKILL.md').is_file()
        # Busy rejection cannot create an orphan work or job.
        other,_=confirmed(b,'article','turn-two')
        with pytest.raises(ChatConflict):await b.chat.submit(other,**b.prepare(other))
        with b.store.connect() as c:assert c.execute('SELECT count(*) FROM toolbox_jobs').fetchone()[0]==1
        assert b.prepare(v)['receipt']['id']=='turn-one'
        await b.chat.stop('test-chat','turn-one');await b.chat.close()
    asyncio.run(scenario())


def test_attachment_paths_are_resolved_by_id_and_bytes_are_checked(business):
    b=business;uploaded=b.box.upload('file-one','reference.txt',b'TEMP original evidence')
    v=value();v['attachments']=[{'id':uploaded['id'],'name':uploaded['name'],'path':'C:/Windows/private-secret'}]
    plan=b.plan(v)
    assert 'C:/Windows/private-secret' not in plan['plan']['execution_prompt']['body']
    payload=json.loads(plan['plan']['execution_prompt']['body'].split('## 本轮冻结输入\n')[-1])
    assert Path(payload['attachments'][0]['path']).is_relative_to(b.root/'outputs/_sessions/materials')
    assert payload['attachments'][0]['sha256']==b.box.file(uploaded['id'])[0]['sha256']
    b.box.file(uploaded['id'])[1].write_bytes(b'changed')
    v['context']['plan_token']=plan['plan_token']
    with pytest.raises(ValueError):b.prepare(v)


def test_unselected_message_uses_project_research_skill_without_work(business):
    b=business;v={'sessionId':'test-chat','turnId':'discuss-one','message':'讨论题目','context':{}}
    result=b.prepare(v)
    assert result['work'] is None and result['snapshot']['task']=='discuss'
    assert result['snapshot']['active_skill_ids']==['topic-research']


@pytest.mark.parametrize('format',['poster','article'])
def test_native_production_records_real_files_versions_and_exact_receipts(business,monkeypatch,format):
    from easel import harnesses
    class Produce:
        async def run(self,r,emit,ask,bind):
            bind('native-products');r.on_native_turn('native-products','native-products-turn')
            payload=json.loads(r.prompt.split('## 本轮冻结输入\n')[-1]);folder=Path(payload['output_directory'])
            folder.mkdir(parents=True,exist_ok=True)
            if format=='poster':
                path=folder/'成品.png'
                path.write_bytes(b'\x89PNG\r\n\x1a\n'+b'\x00\x00\x00\rIHDR'+(1).to_bytes(4,'big')*2+b'\x08\x02\x00\x00\x00')
            else:
                path=folder/'文章交付.json'
                body=folder/'正文.md';body.write_text('有来源的具体正文。',encoding='utf-8')
                path.write_text(json.dumps({'schema_version':1,'article_type':'general','title':'具体变化','body_file':'正文.md','sources':[]},ensure_ascii=False),encoding='utf-8')
            emit('token',json.dumps({'deliverables':[str(path),*([str(body)] if format=='article' else [])],'production_result':{'schema_version':1,'status':'completed'}}))
    monkeypatch.setattr(harnesses,'adapter',lambda runtime:Produce())
    async def scenario():
        b=business;v,_=confirmed(b,format)
        result=await b.chat.submit(v,**b.prepare(v))
        if result['id'] in b.chat._tasks:await b.chat._tasks[result['id']]
        final=b.chat.get_turn(result['id'],private=True)
        assert final['status']=='completed' and final['hook_status']=='completed',final.get('hook_error')
        work=b.box.work(final['work']['work_id'])
        assert work['versions'][0]['status']=='completed',work['versions'][0].get('error')
        assert work['versions'][0]['artifacts']
        for file in work['versions'][0]['artifacts']:assert b.box.file(file['id'])[1].is_relative_to(b.root/'data/artifacts')
        assert b.chat.history('test-chat')['linked_works'][0]['version_id']==result['id']
        # Repeated HTTP receipt inspection cannot rerun the adapter or create a version.
        assert b.prepare(v)['receipt']['id']==result['id']
        with b.store.connect() as c:assert c.execute('SELECT count(*) FROM toolbox_jobs').fetchone()[0]==1
        await b.chat.close()
    asyncio.run(scenario())


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
            assert (await client.get('/api/skills')).json()[0]['available']
            assert (await client.get('/api/skill/content-production')).json()['entry'].startswith('skills/builtin/')
        await app.state.chat.close()
    asyncio.run(scenario())


def test_modification_uses_same_native_session_exact_parent_and_raw_feedback(business,monkeypatch):
    from easel import harnesses
    class Versions:
        def __init__(self):self.requests=[]
        async def run(self,r,emit,ask,bind):
            self.requests.append(r);bind('native-version-session')
            r.on_native_turn('native-version-session','native-turn-'+str(len(self.requests)))
            payload=json.loads(r.prompt.split('## 本轮冻结输入\n')[-1].split('\n\n## 准确父版与原始意见')[0])
            folder=Path(payload['output_directory']);folder.mkdir(parents=True,exist_ok=True)
            path=folder/'标题与配文.txt';path.write_text('有据的标题\n说明准确的变化与来源。',encoding='utf-8')
            emit('token',json.dumps({'deliverables':[str(path)]}))
    adapter=Versions();monkeypatch.setattr(harnesses,'adapter',lambda runtime:adapter)
    async def scenario():
        b=business;v,_=confirmed(b)
        first=await b.chat.submit(v,**b.prepare(v));await b.chat._tasks[first['id']]
        original=b.chat.get_turn(first['id'],private=True);wid=original['work']['work_id']
        discussion=b.prepare({'sessionId':'test-chat','turnId':'only-discuss-parent','message':'只讨论这版的背景关系',
                              'context':{'work_id':wid,'parent_version_id':first['id'],'action_id':'discuss'}})
        assert discussion['work'] is None and discussion['snapshot']['task']=='discuss'
        context=json.loads(discussion['actual_prompt'].split('## 本轮冻结输入\n')[-1])
        assert context['reference_work']['version_id']==first['id'] and context['authorization']['discussion_only']
        assert context['authorization']['production'] is False
        b.box.action(wid,{'id':'record-feedback','kind':'feedback','candidate_id':first['id'],'text':'这一版背景太乱，只记录意见。'})
        change=value('change','version-two');change['context'].update(work_id=wid,parent_version_id=first['id'])
        plan=b.plan(change);change['context']['plan_token']=plan['plan_token']
        second=await b.chat.submit(change,**b.prepare(change));await b.chat._tasks[second['id']]
        final=b.chat.get_turn(second['id'],private=True)
        assert final['hook_status']=='completed'
        assert len(adapter.requests)==2 and adapter.requests[1].native_id=='native-version-session'
        assert adapter.requests[1].session_key==adapter.requests[0].session_key
        assert '这一版背景太乱，只记录意见。' in adapter.requests[1].prompt
        assert final['snapshot']['skills']==original['snapshot']['skills']
        work=b.box.work(wid)
        assert len(work['versions'])==2 and any(v['candidate_id']==first['id'] for v in work['history'] if v['id']=='version-two')
        # A parent from this work cannot be attached to an unrelated chat.
        b.chat.create_session({'id':'unrelated-create','session_id':'unrelated'})
        wrong=value('change','wrong-parent');wrong.update(sessionId='unrelated');wrong['context'].update(work_id=wid,parent_version_id=first['id'])
        with pytest.raises(PlanConflict):b.plan(wrong)
        await b.chat.close()
    asyncio.run(scenario())


def test_candidate_trial_is_explicit_and_does_not_change_defaults(business):
    b=business;base=b.creator.detail('skill','content-production')
    draft=b.creator.command({'id':'new-trial','action':'skill-draft','skill_id':base['id'],'base_version':base['version'],
                             'prompt':base['prompt']+'\nExplicit TEMP candidate method.','reason':'trial only'})['result']['skill']
    v=value();v['context']['version']=draft['version']
    with pytest.raises(ValueError,match='候选'):b.plan(v)
    v['context']['trial']=True
    plan=b.plan(v)
    assert plan['plan']['creator_snapshot']['trial'] is True
    assert b.creator.detail('skill',base['id'])['published_version']==base['version']
    assert 'Explicit TEMP candidate method.' in plan['plan']['execution_prompt']['body']


def test_plan_binds_workspace_instructions_and_cannot_accept_changed_defaults(business):
    b=business;v,plan=confirmed(b)
    assert plan['plan']['execution_prompt']['runtime_instructions']==b.prepare(v)['frozen_instructions']
    path=b.root/'agents/workspace/AGENTS.md'
    path.write_text('New workspace instructions',encoding='utf-8')
    with pytest.raises(PlanConflict,match='会话约定'):b.prepare(v)


def test_attachment_only_plan_preserves_empty_user_text_and_rejects_empty_input(business):
    b=business;v=value();v['message']=''
    with pytest.raises(ValueError):b.plan(v)
    upload=b.box.upload('only-material','素材.txt',b'Only attachment, no invented original user words')
    v['attachments']=[{'id':upload['id'],'name':upload['name'],'path':upload['id']}]
    plan=b.plan(v);v['context']['plan_token']=plan['plan_token']
    assert plan['plan']['production_input']['material']==''
    payload=json.loads(b.prepare(v)['actual_prompt'].split('## 本轮冻结输入\n')[-1])
    assert payload['user_message']=='' and len(payload['attachments'])==1


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


def test_news_source_is_server_frozen_and_selection_is_local(business,monkeypatch):
    from easel import harnesses
    from easel_workbench.runtime.desk import SOURCES
    b=business;source=next(iter(SOURCES))
    b.store.ingest({'schema_version':1,'source_job':source,'feed_id':SOURCES[source]['feed'],'run_id':'native-source-fixture',
                    'run_at':'2026-10-30T08:00:00+08:00','final_text':'原始采集载荷','articles':[{'title':'真实来源标题','body':'原始正文事实A',
                    'url':'https://example.invalid/source-evidence','source_event_id':'exact-source-event'}]})
    with b.store.connect() as c:aid=c.execute('SELECT id FROM articles').fetchone()[0]
    v=value();v['message']='客户端编辑的制作目标';v['context']['article_id']=aid
    plan=b.plan(v);v['context']['plan_token']=plan['plan_token']
    payload=json.loads(b.prepare(v)['actual_prompt'].split('## 本轮冻结输入\n')[-1])
    assert payload['source_article']['body']=='原始正文事实A' and payload['source_article']['provenance']
    class Blocked:
        async def run(self,r,emit,ask,bind):
            bind('native-news');r.on_native_turn('native-news','native-news-turn')
            emit('token','{"production_result":{"schema_version":1,"status":"blocked","message":"TEMP停止于来源验证之后"}}')
    monkeypatch.setattr(harnesses,'adapter',lambda runtime:Blocked())
    async def scenario():
        result=await b.chat.submit(v,**b.prepare(v));await b.chat._tasks[result['id']]
        work=b.chat.get_turn(result['id'])['work']
        with b.store.connect() as c:
            assert c.execute('SELECT article_id FROM toolbox_works WHERE id=?',(work['work_id'],)).fetchone()[0]==aid
            feedback=c.execute('SELECT status,execution,event_json FROM news_feedback WHERE task_id=?',(result['id'],)).fetchone()
            assert feedback['status']=='recorded' and feedback['execution']=='local'
            assert json.loads(feedback['event_json'])['raw_text']==''
            frozen=json.loads(c.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?',(result['id'],)).fetchone()[0])
            assert frozen['source_article']==payload['source_article']
        await b.chat.close()
    asyncio.run(scenario())
    changed=value(tid='source-changed');changed['context']['article_id']=aid
    preview=b.plan(changed);changed['context']['plan_token']=preview['plan_token']
    with b.store.connect() as c:c.execute('UPDATE articles SET body=? WHERE id=?',('新来源字节',aid))
    with pytest.raises(PlanConflict,match='资讯来源'):b.prepare(changed)


def test_default_discussion_keeps_profile_pin_after_global_skill_publication(business):
    b=business;base=b.creator.detail('skill','topic-research')
    candidate=b.creator.command({'id':'new-current-topic','action':'skill-draft','skill_id':base['id'],'base_version':base['version'],
                                 'prompt':base['prompt']+'\nNew globally published method.','reason':'Test pin isolation'})['result']['skill']
    b.creator.command({'id':'publish-new-topic','action':'skill-publish','skill_id':base['id'],'version':candidate['version'],
                       'expected_published_version':base['version'],'confirm':True})
    assert b.creator.detail('skill',base['id'])['published_version']==candidate['version']
    v={'sessionId':'test-chat','turnId':'profile-default-discussion','message':'讨论目标','context':{}}
    prepared=b.prepare(v)
    assert prepared['snapshot']['skills'][0]['version']==base['version']
    assert 'New globally published method.' not in prepared['actual_prompt']


def test_parallel_preview_returns_one_frozen_plan_without_orphan_work(business):
    from concurrent.futures import ThreadPoolExecutor
    b=business;v=value(tid='concurrent-plan')
    with ThreadPoolExecutor(max_workers=2) as executor:
        plans=list(executor.map(lambda _:b.plan(v),range(2)))
    assert plans[0]==plans[1]
    with b.store.connect() as c:
        assert c.execute('SELECT count(*) FROM easel_chat_plans WHERE id=?',('plan-concurrent-plan',)).fetchone()[0]==1
        assert c.execute('SELECT count(*) FROM toolbox_works').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0]==0


def test_product_article_mode_is_frozen_and_cannot_change_after_plan(business):
    b=business;v=value('article','product-plan');v['context']['article_mode']='product'
    plan=b.plan(v);assert plan['plan']['production_input']['article_mode']=='product'
    v['context']['plan_token']=plan['plan_token']
    payload=json.loads(b.prepare(v)['actual_prompt'].split('## 本轮冻结输入\n')[-1])
    assert payload['work']['article_mode']=='product'
    changed=copy.deepcopy(v);changed['context']['article_mode']='auto'
    with pytest.raises(PlanConflict):b.prepare(changed)
    poster=value(tid='poster-invalid-mode');poster['context']['article_mode']='product'
    with pytest.raises(ValueError):b.plan(poster)
