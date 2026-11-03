"""One official skill implementation; TEMP native ports and no model calls."""
import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from easel.web_services.skills import create_skills_context
from easel_workbench.runtime.native_skills import NativeSkills

spec=importlib.util.spec_from_file_location('official_skill_fixtures',Path(__file__).with_name('test_workbench_skill_commands.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
runtime,commands=fixtures.runtime,fixtures.commands


def test_shared_metadata_and_execution_have_one_body_and_official_shapes(tmp_path):
    folder=tmp_path/'skills/builtin/skill-test';folder.mkdir(parents=True)
    (folder/'SKILL.md').write_text('---\nname: test\ndescription: A selected skill\nlayer: produce\n---\nExact workflow',encoding='utf-8')
    calls=[]
    async def execute(message,timeout):calls.append((message,timeout));return 'Actual native result'
    native=create_skills_context(tmp_path,environment=lambda:{},execute=execute,persona=lambda name:'PROFILE\n',direct_api=lambda:False)
    assert native.get_skills()==[{'name':'skill-test','description':'A selected skill','layer':'produce','needsApi':False,'apiConfigured':True}]
    detail=asyncio.run(native.api_skill_detail('test'))
    assert detail=={'name':'skill-test','description':'A selected skill','layer':'produce','body':'Exact workflow','needsApi':False,'apiConfigured':True,'apiSpec':None}
    result=asyncio.run(native.api_skill(SimpleNamespace(skill='test',input='Original input',persona='p')))
    assert result=={'response':'Actual native result'}
    assert calls[0][0]=='PROFILE\n请执行 /skill-test，内容如下：\n\nOriginal input'
    assert native.api_skill.__code__.co_filename.replace('\\','/').endswith('easel/web_services/skills.py')
    with pytest.raises(HTTPException) as error:asyncio.run(native.api_skill_detail('missing'))
    assert error.value.status_code==404
    blocked=create_skills_context(tmp_path,environment=lambda:{},execute=execute,persona=lambda name:'',direct_api=lambda:True)
    with pytest.raises(HTTPException) as error:asyncio.run(blocked.api_skill(SimpleNamespace(skill='test',input='x',persona=None)))
    assert error.value.status_code==409 and len(calls)==1


class FakeChat:
    def __init__(self,status='completed'):
        self.settings=SimpleNamespace(environment=lambda:{},current=lambda:{'runtime':'codex'})
        self.calls=[];self.status=status
    def create_session(self,value):self.calls.append(('create',value));return {'id':value['session_id']}
    def create_internal_session(self,value):return self.create_session(value)
    async def submit(self,value,**ports):
        self.calls.append(('submit',value,ports));return {'id':value['turnId']}
    async def events(self,turn):yield {'event':'done','data':{}}
    def get_turn(self,turn):return {'id':turn,'status':self.status,'output':'Exact result'}


def request(operation):
    return Request({'type':'http','method':'POST','path':'/api/skill','query_string':b'',
        'headers':[(b'x-operation-id',operation.encode())],'scheme':'https','server':('fixture.test',443)})


def test_native_skill_endpoint_preserves_receipt_and_uses_plain_existing_transport(commands):
    async def scenario():
        folder=commands.root/'skills/builtin/content-writing';folder.mkdir(parents=True,exist_ok=True)
        (folder/'SKILL.md').write_text('---\nname: content-writing\nlayer: produce\ndescription: TEMP\n---\nExact instructions',encoding='utf-8')
        chat=FakeChat();native=NativeSkills(commands,chat)
        with commands.store.connect() as c:c.execute('CREATE TABLE IF NOT EXISTS easel_chat_sessions(id TEXT PRIMARY KEY,document TEXT NOT NULL)')
        fields={'skill':'content-writing','input':'Original text','persona':'oil-pig'}
        first=await native.execute(request('native-skill-one'),fields)
        second=await native.execute(request('native-skill-one'),fields)
        assert first==second=={'response':'Exact result'}
        sent=[row for row in chat.calls if row[0]=='submit'];assert len(sent)==1
        assert sent[0][2]=={'snapshot':None,'actual_prompt':native.context()._publishing_message(native.prepare_message('content-writing','Original text','oil-pig')),'interactive':False}
        assert 'plan_token' not in sent[0][1]['context'] and 'version' not in sent[0][1]['context']
        with commands.store.connect() as c:
            row=c.execute('SELECT result FROM easel_ui_operations WHERE id=?',('native-skill-one',)).fetchone()
            assert json.loads(row[0])['state']=='completed'
        with pytest.raises(HTTPException) as error:await native.execute(request('native-skill-one'),{**fields,'input':'Changed'})
        assert error.value.status_code==409 and len([row for row in chat.calls if row[0]=='submit'])==1
        commands._native_api.library.close()
    asyncio.run(scenario())


def test_unknown_skill_result_cannot_be_replayed(commands):
    async def scenario():
        folder=commands.root/'skills/builtin/content-writing';folder.mkdir(parents=True,exist_ok=True)
        (folder/'SKILL.md').write_text('---\nname: content-writing\nlayer: produce\ndescription: TEMP\n---\nExact instructions',encoding='utf-8')
        chat=FakeChat('unknown');native=NativeSkills(commands,chat)
        with commands.store.connect() as c:c.execute('CREATE TABLE IF NOT EXISTS easel_chat_sessions(id TEXT PRIMARY KEY,document TEXT NOT NULL)')
        value={'skill':'content-writing','input':'Exact input','persona':'oil-pig'}
        with pytest.raises(HTTPException) as error:await native.execute(request('native-skill-unknown'),value)
        assert error.value.status_code==503
        with commands.store.connect() as c:
            stored=json.loads(c.execute('SELECT result FROM easel_ui_operations WHERE id=?',('native-skill-unknown',)).fetchone()[0])
            assert stored['state']=='unavailable'
        with pytest.raises(HTTPException) as error:await native.execute(request('native-skill-unknown'),value)
        assert error.value.status_code==409
        assert len([row for row in chat.calls if row[0]=='submit'])==1
        commands._native_api.library.close()
    asyncio.run(scenario())


def test_plain_native_skill_uses_real_chat_service_without_private_snapshot(commands,monkeypatch):
    from easel import harnesses
    from easel_workbench.features.conversations.service import ChatService
    calls=[]
    class Engine:
        async def run(self,req,emit,ask,bind):
            calls.append(req);bind('TEMP-native-skill')
            req.on_native_turn('TEMP-native-skill','TEMP-native-turn')
            emit('token','Actual TEMP native response')
    monkeypatch.setattr(harnesses,'adapter',lambda runtime:Engine())
    folder=commands.root/'skills/builtin/content-writing';folder.mkdir(parents=True,exist_ok=True)
    (folder/'SKILL.md').write_text('---\nname: content-writing\nlayer: produce\n---\nTEMP workflow',encoding='utf-8')
    (commands.root/'AGENTS.md').write_text('TEMP original native instructions',encoding='utf-8')
    async def scenario():
        chat=ChatService(commands);native=NativeSkills(commands,chat)
        try:
            result=await native.execute(request('native-actual-transport'),{'skill':'content-writing','input':'Exact input','persona':'oil-pig'})
            assert result=={'response':'Actual TEMP native response'} and len(calls)==1
            assert '/content-writing' in calls[0].prompt and '本轮冻结输入' not in calls[0].prompt
            with commands.store.connect() as c:
                row=c.execute('SELECT document FROM easel_chat_turns WHERE id=?',('skill-turn-native-actual-transport',)).fetchone()
                turn=json.loads(row[0]);assert turn['snapshot'] is None and turn['work'] is None
                assert turn['status']=='completed' and turn['interactive'] is False
            public=chat.get_turn(turn['id']);assert public.get('selected_skills',[])==[]
            assert chat.list_sessions(summaries=True)['sessions']==[]
            assert len(chat.list_sessions(include_internal=True)['sessions'])==1
            with commands.store.connect() as c:
                assert json.loads(c.execute('SELECT document FROM easel_chat_sessions WHERE id=?',(turn['session_id'],)).fetchone()[0])['internal_skill_run'] is True
        finally:
            await chat.close()
            commands._native_api.library.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('engine',['codex','openclaw','api'])
def test_original_plain_chat_handler_uses_same_native_port_without_skill_plans(commands,engine):
    async def scenario():
        chat=FakeChat();chat.settings.current=lambda:{'runtime':engine}
        native=NativeSkills(commands,chat)
        with commands.store.connect() as c:c.execute('CREATE TABLE IF NOT EXISTS easel_chat_sessions(id TEXT PRIMARY KEY,document TEXT NOT NULL)')
        req=request('plain-chat-'+engine)
        req.scope['path']='/api/chat'
        value={'message':'Analyze this exact reference','persona':'oil-pig'}
        result=await native.execute(req,value,plain_chat=True)
        assert result['response']=='Exact result'
        assert ('sessionKey' in result)==(engine!='openclaw')
        again=await native.execute(req,value,plain_chat=True)
        assert result==again
        sent=[row for row in chat.calls if row[0]=='submit'];assert len(sent)==1
        assert sent[0][2]['snapshot'] is None and 'skill_id' not in sent[0][1]['context']
        assert 'Analyze this exact reference' in sent[0][2]['actual_prompt']
        assert native.context().api_chat.__code__.co_filename.replace('\\','/').endswith('easel/web_services/skills.py')
        commands._native_api.library.close()
    asyncio.run(scenario())
