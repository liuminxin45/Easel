"""Logical session deletion hides list entries without deleting evidence or work."""
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('session_delete_fixture',Path(__file__).with_name('test_workbench_chat.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
runtime,commands,service=fixture.runtime,fixture.commands,fixture.service

from easel_workbench.chat import ChatService,ChatConflict
from easel.harnesses import store as harness_store


def request(s,operation='delete-one'):
    with s.store.connect() as c:session=s._session(c,'workbench-session')
    return {'id':operation,'action':'delete','session_id':session['id'],'expected_revision':session['revision']}


def stored(s,table):
    with s.store.connect() as c:return [tuple(row) for row in c.execute('SELECT * FROM '+table+' ORDER BY rowid')]


def test_delete_is_idempotent_logical_and_survives_restart_without_removing_native_binding(service):
    s,adapter=service
    harness_store.bind(s.sessions_dir,'workbench-session','codex','native-original')
    binding=harness_store.binding(s.sessions_dir,'workbench-session')
    value=request(s);result=s.delete_session('workbench-session',value)
    assert result['deleted'] is True and result['session']['archived'] is True
    assert result['session']['deleted_at'] and result['session']['revision']==2
    assert s.delete_session('workbench-session',value)==result
    assert s.list_sessions()['sessions']==s.list_sessions(summaries=True)['sessions']==[]
    assert s.history('workbench-session')['session']['messages']==[]
    assert harness_store.binding(s.sessions_dir,'workbench-session')==binding
    restarted=ChatService(s.box)
    assert restarted.list_sessions()['sessions']==[]
    assert restarted.delete_session('workbench-session',value)==result
    with pytest.raises(ChatConflict):restarted.archive_session('workbench-session',{'id':'unarchive','expected_revision':2,'archived':False})
    with pytest.raises(ChatConflict):restarted.rename_session('workbench-session',{'id':'rename','expected_revision':2,'title':'Revive'})
    with pytest.raises(ChatConflict):restarted.create_session({'id':'reuse','session_id':'workbench-session'})
    assert not adapter.requests


def test_delete_completed_conversation_retains_raw_turns_exact_releases_files_and_linked_work(service):
    async def scenario():
        s,adapter=service
        await s.submit(fixture.value(),snapshot=fixture.snapshot(s),actual_prompt='TEMP discuss')
        await fixture.completed(s,'operation-one')
        file=s.root/'data/artifacts'/'original.txt';file.parent.mkdir(parents=True,exist_ok=True);file.write_bytes(b'EXACT ORIGINAL')
        with s.store.connect() as c:
            turn=s._turn(c,'operation-one');turn['work']={'work_id':'retained-work','version_id':'retained-version'};s._put_turn(c,turn)
            c.execute('INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)',('retained-work',None,'Kept work','','2026-11-03','2026-11-03'))
        before={table:stored(s,table) for table in ('easel_chat_turns','toolbox_works','creator_skill_versions')}
        binding=harness_store.binding(s.sessions_dir,'workbench-session')
        s.delete_session('workbench-session',request(s))
        assert {table:stored(s,table) for table in before}==before
        assert file.read_bytes()==b'EXACT ORIGINAL'
        assert harness_store.binding(s.sessions_dir,'workbench-session')==binding
        history=s.history('workbench-session')
        assert len(history['session']['messages'])==2 and history['linked_works']==[{'work_id':'retained-work','version_id':'retained-version'}]
        with pytest.raises(ChatConflict):
            await s.submit(fixture.value('after-delete'),snapshot=fixture.snapshot(s),actual_prompt='must not run')
        assert len(adapter.requests)==1
    asyncio.run(scenario())


@pytest.mark.parametrize(('status','hook','started'),[
    ('accepted','not_started',None),('running',None,None),('unknown','completed',None),
    ('completed','pending',None),('completed','completed','pending'),(None,None,None),
])
def test_delete_refuses_actual_active_unknown_or_pending_hooks_even_without_session_pointer(service,status,hook,started):
    s,adapter=service
    with s.store.connect() as c:
        c.execute('INSERT INTO easel_chat_turns VALUES(?,?,?,?,?)',('held','workbench-session','held-operation','signature',json.dumps({'id':'held','status':status,'hook_status':hook,'start_hook_status':started})))
    before=stored(s,'easel_chat_sessions')
    with pytest.raises(ChatConflict):s.delete_session('workbench-session',request(s))
    assert stored(s,'easel_chat_sessions')==before and not adapter.requests
    with s.store.connect() as c:assert not c.execute("SELECT 1 FROM easel_chat_operations WHERE id='delete-one'").fetchone()


@pytest.mark.parametrize('state',['queued','preparing','admitting','unknown'])
def test_delete_refuses_pending_preparation_without_projection_pointer(service,state):
    s,_=service
    with s.store.connect() as c:
        c.execute('CREATE TABLE easel_chat_submissions(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,signature TEXT NOT NULL,document TEXT NOT NULL)')
        c.execute('INSERT INTO easel_chat_submissions VALUES(?,?,?,?)',('prepare','workbench-session','sig',json.dumps({'status':state})))
    with pytest.raises(ChatConflict):s.delete_session('workbench-session',request(s))


def test_stale_delete_revision_cannot_hide_a_renamed_session(service):
    s,_=service;old=request(s)
    s.rename_session('workbench-session',{'id':'renamed','expected_revision':1,'title':'New title'})
    with pytest.raises(ChatConflict):s.delete_session('workbench-session',old)
    assert s.list_sessions()['sessions'][0]['title']=='New title'


def test_authenticated_http_delete_requires_csrf_and_hides_only_after_acknowledgement(commands):
    from fastapi.testclient import TestClient
    from easel_workbench.application import create_app
    from easel_workbench.runtime.auth_forms import SESSION
    class Auth:
        data={'origin':'https://fixture.test','host':'fixture.test','secret':'A'*32}
        def session(self,token):return {'csrf':'fixture','until':9999999999} if token=='fixture-owner' else None
    app=create_app(root=commands.root,store=commands.store,auth=Auth(),box=commands,studio=commands.studio)
    chat=app.state.chat
    session=chat.create_session({'id':'create-http','session_id':'http-delete','profile_id':'oil-pig'})['session']
    value={'id':'delete-http','action':'delete','session_id':session['id'],'expected_revision':session['revision']}
    client=TestClient(app,base_url='https://fixture.test')
    try:
        assert client.post('/api/chat/sessions',json=value).status_code==401
        client.cookies.set(SESSION,'fixture-owner',domain='fixture.test',path='/')
        assert client.post('/api/chat/sessions',json=value,headers={'Origin':Auth.data['origin']}).status_code==403
        assert len(chat.list_sessions()['sessions'])==1
        csrf=client.get('/api/config').json()['csrf']
        headers={'Origin':Auth.data['origin'],'X-CSRF-Token':csrf,'X-Operation-ID':value['id']}
        deleted=client.post('/api/chat/sessions',json=value,headers=headers)
        assert deleted.status_code==200 and deleted.json()['deleted'] is True
        assert client.post('/api/chat/sessions',json=value,headers=headers).json()==deleted.json()
        assert client.get('/api/chat/sessions').json()['sessions']==[]
        history=client.get('/api/chat/sessions/http-delete?limit=50')
        assert history.status_code==200 and history.json()['session']['deleted_at']
        assert history.json()['session']['messages']==[]
        with chat.store.connect() as c:
            assert c.execute('SELECT count(*) FROM easel_chat_sessions').fetchone()[0]==1
            assert c.execute('SELECT count(*) FROM easel_chat_turns').fetchone()[0]==0
            assert c.execute("SELECT count(*) FROM easel_chat_operations WHERE id='delete-http'").fetchone()[0]==1
    finally:client.close()
