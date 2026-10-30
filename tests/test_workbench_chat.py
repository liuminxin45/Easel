"""TEMP Easel chat receipts, and the real CodexAdapter with fake stdio only."""
import asyncio
from contextlib import asynccontextmanager
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

_spec=importlib.util.spec_from_file_location('chat_fixtures',Path(__file__).with_name('test_workbench_skill_commands.py'))
_fixtures=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_fixtures)
runtime,commands=_fixtures.runtime,_fixtures.commands

from easel import harnesses
from easel.harnesses import codex, rpc, store as harness_store
from easel.harnesses.base import HarnessError,RunRequest
from easel.harnesses.workspace import harness_instructions
from easel_workbench.chat import ChatService,ChatConflict


class Adapter:
    def __init__(self):self.requests=[];self.hold=None;self.question=False;self.failure=False;self.cancelled=False;self.interrupt_ack=True
    async def run(self,request,emit,ask,bind):
        self.requests.append(request)
        native=request.native_id or 'actual-native-session'
        bind(native)
        request.on_native_turn(native,'actual-native-turn-'+str(len(self.requests)))
        emit('token','真实 ')
        if self.question:
            result=await ask([{'questionId':'permission','header':'执行授权','question':'是否允许？',
                              'options':[{'label':'允许本次'},{'label':'拒绝'}]}])
            assert result=={'permission':['拒绝']}
        try:
            if self.hold:await self.hold.wait()
        except asyncio.CancelledError:
            self.cancelled=True
            if self.interrupt_ack and request.on_native_interrupt:
                request.on_native_interrupt(native,'actual-native-turn-'+str(len(self.requests)))
            raise
        if self.failure:raise HarnessError('Native failure after a possible submission')
        emit('activity','工具：fileChange')
        emit('thinking','实际摘要')
        emit('token','输出 fixture-secret-value')


@pytest.fixture
def service(commands,monkeypatch):
    workspace=commands.root/'agents/workspace';workspace.mkdir(parents=True)
    (workspace/'AGENTS.md').write_text('Temporary Easel workspace instructions.',encoding='utf-8')
    (commands.root/'.env').write_text('FIXTURE_SECRET=fixture-secret-value\n',encoding='utf-8')
    adapter=Adapter()
    monkeypatch.setattr(harnesses,'adapter',lambda runtime:adapter if runtime=='codex' else pytest.fail('Wrong runtime'))
    service=ChatService(commands)
    service.create_session({'id':'create-session','session_id':'workbench-session','profile_id':'oil-pig'})
    return service,adapter


def snapshot(service):return service.box.creator.resolve(task='discuss')
def value(operation='operation-one'):return {'operation_id':operation,'turnId':operation,'sessionId':'workbench-session','message':'用户原话'}
async def completed(service,turn_id):
    task=service._tasks.get(turn_id)
    if task:await asyncio.shield(task)


def test_session_metadata_commands_are_versioned_and_preserve_native_binding(service):
    s,_=service
    initial=s.list_sessions()['sessions'][0]
    renamed=s.rename_session(initial['id'],{'id':'rename','expected_revision':1,'title':'实际 Easel 对话'})['session']
    assert renamed['revision']==2
    with pytest.raises(ChatConflict):s.rename_session(initial['id'],{'id':'stale','expected_revision':1,'title':'覆盖旧名'})
    archived=s.archive_session(initial['id'],{'id':'archive','expected_revision':2})['session']
    assert archived['archived'] and archived['revision']==3
    assert s.history(initial['id'])['session']['messages']==[]
    assert s._metadata_path(initial['id']).is_file()
    harness_store.bind(s.sessions_dir,'upstream-existing','codex','native-existing')
    with pytest.raises(ChatConflict):s.create_session({'id':'collision','session_id':'upstream-existing'})


@pytest.mark.parametrize('decision', ['允许本次', '拒绝'])
def test_question_official_ack_terminal_event_and_restart_never_regrant(service, decision):
    async def scenario():
        s,a=service
        class QuestionAdapter:
            async def run(self,request,emit,ask,bind):
                bind('native-permission');request.on_native_turn('native-permission','native-permission-turn')
                self.result=await ask([{'questionId':'permission','options':[{'label':'允许本次'},{'label':'拒绝'}]}])
        adapter=QuestionAdapter()
        original=harnesses.adapter
        harnesses.adapter=lambda name:adapter
        try:
            turn=await s.submit(value(),snapshot=snapshot(s),actual_prompt='Frozen')
            while not s.questions('workbench-session')['questions']:await asyncio.sleep(.001)
            q=s.questions('workbench-session')['questions'][0]
            assert s.question_status(q['id'],'workbench-session',turn['id'])=={'status':'pending'}
            with pytest.raises(ChatConflict):s.answer(q['id'],{'permission':[decision]},'workbench-session','different-turn')
            from easel_workbench.chat_api import handle
            response=await handle(s,None,'/api/chat/question/answer',SimpleNamespace(method='POST'),
                {'questionId':q['id'],'sessionId':'workbench-session','turnId':turn['id'],'answers':{'permission':[decision]}})
            ack=json.loads(response.body)
            assert response.status_code==200 and ack['ok'] and ack['answered'] and ack['status']=='answered'
            again=s.answer(q['id'],{'permission':[decision]},'workbench-session',turn['id'])
            assert not again['ok'] and again['status']=='answered'
            await completed(s,turn['id'])
            assert adapter.result=={'permission':[decision]}
            closed=[e for e in s.read_events(turn['id']) if e['event']=='question_closed']
            assert len(closed)==1 and json.loads(closed[0]['data'])=={'id':q['id'],'status':'answered'}
            recovered=ChatService(s.box)
            assert recovered.question_status(q['id'],'workbench-session',turn['id'])=={'status':'answered'}
            assert not recovered.answer(q['id'],{'permission':[decision]},'workbench-session',turn['id'])['ok']
            assert not s.questions('workbench-session')['questions']
        finally:
            harnesses.adapter=original
            await s.close()
    asyncio.run(scenario())


def test_interrupted_pending_question_expires_without_creating_a_new_turn(service):
    async def scenario():
        s,a=service;a.question=True
        turn=await s.submit(value(),snapshot=snapshot(s),actual_prompt='Frozen')
        while not s.questions('workbench-session')['questions']:await asyncio.sleep(.001)
        q=s.questions('workbench-session')['questions'][0]
        # Another process cannot resume an in-memory native permission future.
        recovered=ChatService(s.box)
        assert recovered.question_status(q['id'],'workbench-session',turn['id'])=={'status':'expired'}
        assert not recovered.answer(q['id'],{'permission':['允许本次']},'workbench-session',turn['id'])['ok']
        await s.close()
        assert s.question_status(q['id'])['status']=='expired'
        assert len(a.requests)==1
        assert any(e['event']=='question_closed' for e in s.read_events(turn['id']))
    asyncio.run(scenario())


def test_first_accepted_title_manual_rename_and_legacy_repair(service):
    async def scenario():
        s,a=service
        first=await s.submit({**value(),'initial_title':'首条消息提取标题'},snapshot=snapshot(s),actual_prompt='Frozen')
        await completed(s,first['id'])
        assert s.history('workbench-session')['session']['title']=='首条消息提取标题'
        second=await s.submit({**value('second'),'initial_title':'不能覆盖第一条'},snapshot=snapshot(s),actual_prompt='Second')
        await completed(s,second['id'])
        assert s.history('workbench-session')['session']['title']=='首条消息提取标题'
        s.create_session({'id':'legacy-create','session_id':'legacy'})
        old=await s.submit({**value('legacy-turn'),'sessionId':'legacy'},snapshot=snapshot(s),actual_prompt='Old')
        await completed(s,old['id'])
        session=s.history('legacy')['session']
        repaired=s._command('auto-title',{'id':'repair','expected_revision':session['revision'],'title':'历史首条标题'},'legacy')['session']
        assert repaired['title']=='历史首条标题'
        s.create_session({'id':'manual-create','session_id':'manual'})
        s.rename_session('manual',{'id':'manual-name','expected_revision':1,'title':'新对话'})
        manual=await s.submit({**value('manual-turn'),'sessionId':'manual','initial_title':'不能覆盖手动标题'},snapshot=snapshot(s),actual_prompt='Manual')
        await completed(s,manual['id'])
        session=s.history('manual')['session']
        assert session['title']=='新对话' and session['title_source']=='manual'
        with pytest.raises(ChatConflict):s._command('auto-title',{'id':'bad-repair','expected_revision':session['revision'],'title':'替换'},'manual')
        await s.close()
    asyncio.run(scenario())


def test_actual_upstream_request_has_root_session_frozen_input_and_receipts(service):
    async def scenario():
        s,a=service;started=[];finished=[]
        s.on_started=lambda record:started.append(record)
        s.on_finish=lambda record:finished.append(record) or {'work_id':'work-one'}
        result=await s.submit(value(),snapshot=snapshot(s),actual_prompt='EXACT frozen prompt',work={'work_id':'work-one'})
        await completed(s,result['id'])
        request=a.requests[0]
        assert request.cwd==s.root and request.session_key=='workbench-session' and request.prompt=='EXACT frozen prompt'
        assert request.sandbox=='workspace-write' and request.codex_auto_approve is False
        assert 'Temporary Easel' in request.frozen_instructions
        turn=s.get_turn(result['id'],private=True)
        assert turn['status']=='completed' and turn['native_id']=='actual-native-session'
        assert turn['native_turn_id']=='actual-native-turn-1'
        assert turn['output']=='真实 输出 ***'
        assert started[0]['native_turn_id']==finished[0]['native_turn_id']
        assert started[0]['status']=='running' and finished[0]['status']=='completed'
        assert turn['hook_status']=='completed'
        assert harness_store.binding(s.sessions_dir,'workbench-session')['native_id']=='actual-native-session'
        assert s.last('workbench-session')['status']=='done' and s.last('workbench-session')['clean_end']
        history=s.history('workbench-session')
        assert history['session']['pendingTurnId'] is None and history['linked_works']==[{'work_id':'work-one'}]
        assert [m['role'] for m in history['session']['messages']]==['user','assistant']
        assert 'actual_prompt' not in s.get_turn(result['id']) and 'frozen_instructions' not in s.get_turn(result['id'])
        assert [e['event'] for e in s.read_events(result['id'])][-1]=='done'
        await s.close()
    asyncio.run(scenario())


def test_idempotent_receipt_does_not_recompile_or_repeat_model(service):
    async def scenario():
        s,a=service
        result=await s.submit(value(),snapshot=snapshot(s),actual_prompt='Original compiled input')
        await completed(s,result['id'])
        original=s.get_turn(result['id'],private=True)
        again=await s.submit(value(),snapshot=None,actual_prompt='New defaults must never replace original input')
        assert again['id']==result['id'] and len(a.requests)==1
        assert s.get_turn(result['id'],private=True)['actual_prompt']==original['actual_prompt']
        with pytest.raises(ChatConflict):
            await s.submit({**value(),'message':'Changed request'},snapshot=None,actual_prompt='ignored')
        await s.close()
    asyncio.run(scenario())


def test_disconnect_and_replay_never_cancel_or_start_another_native_turn(service):
    async def scenario():
        s,a=service;a.hold=asyncio.Event()
        result=await s.submit(value(),snapshot=snapshot(s),actual_prompt='Frozen')
        stream=s.events(result['id']);first=await anext(stream);await stream.aclose()
        assert first['event']=='activity' and not a.cancelled
        a.hold.set();await completed(s,result['id'])
        events=[event async for event in s.events(result['id'],first['id'])]
        assert events[-1]['event']=='done' and len(a.requests)==1
        assert all(event['id']>first['id'] for event in events)
        await s.close()
    asyncio.run(scenario())


def test_question_answers_are_scoped_and_stop_uses_native_cancellation(service):
    async def scenario():
        s,a=service;a.question=True
        result=await s.submit(value(),snapshot=snapshot(s),actual_prompt='Frozen')
        for _ in range(100):
            pending=s.questions('workbench-session')['questions']
            if pending:break
            await asyncio.sleep(.001)
        question=pending[0]
        with pytest.raises(ChatConflict):s.answer(question['id'],{'permission':['拒绝']},'another-session')
        with pytest.raises(ValueError):s.answer(question['id'],{'permission':['arbitrary grant']},'workbench-session')
        assert s.answer(question['id'],{'permission':['拒绝']},'workbench-session')['answered']
        await completed(s,result['id']);assert not s.questions('workbench-session')['questions']
        a.question=False;a.hold=asyncio.Event()
        second=await s.submit(value('second'),snapshot=snapshot(s),actual_prompt='Second')
        while len(a.requests)<2:await asyncio.sleep(.001)
        assert (await s.stop('workbench-session',second['id']))['stopped']
        assert a.cancelled and s.get_turn(second['id'])['status']=='stopped'
        assert s.history('workbench-session')['session']['pendingTurnId'] is None
        await s.close()
    asyncio.run(scenario())


def test_unknown_turn_remains_bound_and_is_never_restarted(service):
    async def scenario():
        s,a=service;a.failure=True
        result=await s.submit(value(),snapshot=snapshot(s),actual_prompt='Frozen')
        await completed(s,result['id'])
        assert s.get_turn(result['id'])['status']=='unknown'
        with pytest.raises(ChatConflict):await s.submit(value('new-operation'),snapshot=snapshot(s),actual_prompt='New')
        restored=ChatService(s.box)
        assert restored.receipt(value())['status']=='unknown'
        assert len(a.requests)==1 and restored.history('workbench-session')['session']['pendingTurnId']==result['id']
        await restored.close();await s.close()
    asyncio.run(scenario())


def test_business_hook_failure_is_separate_and_does_not_repeat_model(service):
    async def scenario():
        s,a=service
        def failed(record):raise OSError('Synthetic business archive failure')
        s.on_finish=failed
        result=await s.submit(value(),snapshot=snapshot(s),actual_prompt='Frozen')
        await completed(s,result['id'])
        turn=s.get_turn(result['id']);assert turn['status']=='completed' and turn['hook_status']=='failed'
        await s.submit(value(),snapshot=None,actual_prompt='Ignored retry')
        assert len(a.requests)==1 and turn['output']
        await s.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('shutdown', [False, True])
def test_native_completion_is_preserved_while_business_hook_is_stopped_or_interrupted(service,shutdown):
    async def scenario():
        s,_=service;hook_entered=asyncio.Event();release=asyncio.Event()
        async def archive(record):
            hook_entered.set();await release.wait();return {'saved':True}
        s.on_finish=archive
        result=await s.submit(value(),snapshot=snapshot(s),actual_prompt='Frozen')
        await hook_entered.wait()
        if shutdown:
            await s.close()
            assert s.get_turn(result['id'])['hook_status']=='unknown'
        else:
            assert (await s.stop('workbench-session',result['id']))['stopped'] is False
            release.set();await completed(s,result['id'])
            assert s.get_turn(result['id'])['hook_status']=='completed'
            await s.close()
        assert s.get_turn(result['id'])['status']=='completed'
        assert s.history('workbench-session')['session']['pendingTurnId'] is None
    asyncio.run(scenario())


def test_client_cannot_override_frozen_prompt_runtime_or_instructions(service):
    async def scenario():
        s,a=service
        request={**value(),'frozen_prompt':'FORGED','frozen_instructions':'FORGED','runtime':'api','model':'fake','sandbox':'read-only'}
        result=await s.submit(request,snapshot=snapshot(s),actual_prompt='Server compiled',frozen_instructions='SERVER frozen workspace')
        await completed(s,result['id'])
        actual=a.requests[0]
        assert actual.prompt=='Server compiled' and actual.frozen_instructions=='SERVER frozen workspace'
        assert actual.sandbox=='workspace-write' and actual.env['EASEL_AGENT_RUNTIME']=='codex'
        await s.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('context', [None, [], {'trial':'true'}, {'trial':1}, {'work_id':'work-only'},
                                      {'parent_version_id':'parent-only'}, {'work_id':12,'parent_version_id':'parent'}])
def test_submit_rejects_ambiguous_trial_and_parent_context_before_acceptance(service,context):
    async def scenario():
        s,a=service
        with pytest.raises(ValueError):
            await s.submit({**value(),'context':context},snapshot=snapshot(s),actual_prompt='Frozen')
        assert not a.requests and s.history('workbench-session')['session']['pendingTurnId'] is None
        await s.close()
    asyncio.run(scenario())


def test_attachment_only_message_preserves_empty_user_text_and_rejects_empty_request(service):
    async def scenario():
        s,a=service
        with pytest.raises(ValueError):
            await s.submit({**value(),'message':''},snapshot=snapshot(s),actual_prompt='Frozen')
        result=await s.submit({**value(),'message':'','attachments':[{'id':'upload','name':'source.txt'}]},
                              snapshot=snapshot(s),actual_prompt='Frozen attachment request')
        await completed(s,result['id'])
        assert len(a.requests)==1 and s.get_turn(result['id'])['message']==''
        assert s.history('workbench-session')['session']['messages'][0]['content']==''
        await s.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('interrupt_fails', [False, True])
def test_real_codex_adapter_uses_real_pool_store_and_native_turn_hook(commands,monkeypatch,interrupt_fails):
    async def scenario():
        root=commands.root;workspace=root/'agents/workspace';workspace.mkdir(parents=True)
        (workspace/'AGENTS.md').write_text('Actual shared harness workspace.',encoding='utf-8')
        instances=[];methods=[];complete_turns=[True]
        class FakeRPC:
            def __init__(self,request,command,notify,respond,**kwargs):
                self.request=request;self.notify=notify;self.respond=respond
                self.initialized=None;self.native_id='';self.client_error=None;self.process=SimpleNamespace(returncode=None)
                self.reader=asyncio.get_running_loop().create_future();instances.append(self)
            async def __aenter__(self):return self
            async def __aexit__(self,*args):self.process.returncode=0;self.reader.cancel()
            async def send(self,message):methods.append(message.get('method'))
            async def call(self,method,params,**kwargs):
                methods.append(method)
                if method=='initialize':return {'ok':True}
                if method in ('thread/start','thread/resume'):
                    assert params['cwd']==str(root)
                    assert params['developerInstructions']=='EXACT developer instruction'
                    return {'thread':{'id':params.get('threadId','upstream-native-thread')}}
                if method=='turn/start':
                    turn='upstream-turn-'+str(methods.count('turn/start'))
                    assert params['input'][0]['text'].startswith('EXACT actual user prompt')
                    self.notify('item/agentMessage/delta',{'threadId':'foreign','turnId':turn,'delta':'WRONG SESSION'})
                    self.notify('item/agentMessage/delta',{'threadId':'upstream-native-thread','turnId':turn,'itemId':'message','delta':'上游真实事件'})
                    if complete_turns[0]:
                        self.notify('turn/completed',{'threadId':'upstream-native-thread','turnId':turn,'turn':{'id':turn,'status':'completed'}})
                    return {'turn':{'id':turn}}
                if method=='turn/interrupt':
                    if interrupt_fails:raise HarnessError('Synthetic missing interrupt acknowledgment')
                    return {}
                raise AssertionError(method)
            async def wait_notification(self,future):return await future
        monkeypatch.setattr(rpc,'RPC',FakeRPC)
        monkeypatch.setattr(codex,'base_command',lambda runtime:['fake-codex'])
        service=ChatService(commands)
        service.create_session({'id':'new-upstream','session_id':'upstream-pool','profile_id':'oil-pig'})
        for index in (1,2):
            request={'operation_id':'turn-'+str(index),'session_id':'upstream-pool','message':'用户 '+str(index)}
            result=await service.submit(request,snapshot=commands.creator.resolve(task='discuss'),
                actual_prompt='EXACT actual user prompt '+str(index),frozen_instructions='EXACT developer instruction')
            await completed(service,result['id'])
            turn=service.get_turn(result['id']);assert turn['native_turn_id']=='upstream-turn-'+str(index)
            assert turn['output']=='上游真实事件' and turn['native_id']=='upstream-native-thread'
        assert len(instances)==1 and methods.count('initialize')==1 and methods.count('thread/start')==1
        assert methods.count('turn/start')==2 and 'thread/resume' not in methods
        assert harness_store.binding(service.sessions_dir,'upstream-pool')['native_id']=='upstream-native-thread'
        complete_turns[0]=False
        pending=await service.submit({'operation_id':'third','session_id':'upstream-pool','message':'停止验收'},
            snapshot=commands.creator.resolve(task='discuss'),actual_prompt='EXACT actual user prompt third',
            frozen_instructions='EXACT developer instruction')
        while not service.get_turn(pending['id']).get('native_turn_id'):
            await asyncio.sleep(.001)
        assert (await service.stop('upstream-pool',pending['id']))['stopped'] is not interrupt_fails
        assert 'turn/interrupt' in methods
        assert service.get_turn(pending['id'])['status']==('unknown' if interrupt_fails else 'stopped')
        assert bool(service.get_turn(pending['id']).get('interrupt_confirmed')) is not interrupt_fails
        assert service.history('upstream-pool')['session']['pendingTurnId']==(pending['id'] if interrupt_fails else None)
        if interrupt_fails:
            same=await service.submit({'operation_id':'third','session_id':'upstream-pool','message':'停止验收'},snapshot=None,actual_prompt='Must not recompile')
            assert same['id']==pending['id'] and methods.count('turn/start')==3
            with pytest.raises(ChatConflict):
                await service.submit({'operation_id':'fourth','session_id':'upstream-pool','message':'不能重发'},snapshot=commands.creator.resolve(task='discuss'),actual_prompt='Blocked')
        assert service.get_turn(pending['id'])['output']=='上游真实事件'
        await service.close();assert instances[0].process.returncode==0
    asyncio.run(scenario())


def test_upstream_workspace_default_stays_unchanged_and_frozen_value_is_exact(tmp_path):
    workspace=tmp_path/'agents/workspace';workspace.mkdir(parents=True)
    path=workspace/'AGENTS.md';path.write_text('ORIGINAL instructions',encoding='utf-8')
    original=harness_instructions(RunRequest('x',tmp_path,{}))
    path.write_text('CHANGED instructions',encoding='utf-8')
    assert harness_instructions(RunRequest('x',tmp_path,{},frozen_instructions=original))==original
    assert 'CHANGED instructions' in harness_instructions(RunRequest('x',tmp_path,{}))


def test_accept_hook_is_atomic_and_not_called_for_busy_or_repeated_operations(service):
    async def scenario():
        s,a=service;a.hold=asyncio.Event()
        with s.store.connect() as c:c.execute('CREATE TABLE acceptance_work(id TEXT PRIMARY KEY)')
        calls=[]
        def accepted(c,turn):
            calls.append(turn['id']);c.execute('INSERT INTO acceptance_work VALUES(?)',(turn['id'],));return {'work_id':turn['id']}
        s.on_accept=accepted
        first=await s.submit(value(),snapshot=snapshot(s),actual_prompt='Frozen')
        await s.submit(value(),snapshot=None,actual_prompt='Ignored')
        with pytest.raises(ChatConflict):await s.submit(value('busy'),snapshot=snapshot(s),actual_prompt='Not accepted')
        with s.store.connect() as c:assert c.execute('SELECT count(*) FROM acceptance_work').fetchone()[0]==1
        assert calls==[first['id']]
        a.hold.set();await completed(s,first['id']);await s.close()
    asyncio.run(scenario())


def test_accept_hook_failure_rolls_back_work_turn_and_pending_session(service):
    async def scenario():
        s,a=service
        with s.store.connect() as c:c.execute('CREATE TABLE acceptance_work(id TEXT PRIMARY KEY)')
        def rejected(c,turn):
            c.execute('INSERT INTO acceptance_work VALUES(?)',(turn['id'],));raise ValueError('Synthetic acceptance failure')
        s.on_accept=rejected
        with pytest.raises(ValueError):await s.submit(value(),snapshot=snapshot(s),actual_prompt='Frozen')
        with s.store.connect() as c:
            assert c.execute('SELECT count(*) FROM acceptance_work').fetchone()[0]==0
            assert c.execute('SELECT count(*) FROM easel_chat_turns').fetchone()[0]==0
        assert s.history('workbench-session')['session']['pendingTurnId'] is None and not a.requests
        await s.close()
    asyncio.run(scenario())
