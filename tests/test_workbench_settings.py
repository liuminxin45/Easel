"""TEMP settings, actual upstream provider rules, and frozen engine dispatch."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

_spec=importlib.util.spec_from_file_location('settings_fixtures',Path(__file__).with_name('test_workbench_skill_commands.py'))
_fixtures=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_fixtures)
runtime,commands=_fixtures.runtime,_fixtures.commands

from easel import harnesses
from easel_workbench.settings import SettingsService,SettingsConflict
from easel_workbench.chat import ChatService,ChatConflict


class Vault:
    def __init__(self):self.values={}
    def put(self,owner,value):
        key=str(len(self.values));self.values[key]=(owner,copy.deepcopy(value));return key
    def get(self,key,owner):
        actual,value=self.values[key];assert owner==actual;return copy.deepcopy(value)


@pytest.fixture
def settings(commands,monkeypatch):
    (commands.root/'.env').write_text('FIXTURE_SECRET=initial-private-secret\n',encoding='utf-8')
    settings=SettingsService(commands,vault=Vault());commands.settings_service=settings
    monkeypatch.setattr(harnesses,'describe',lambda runtime:{'id':runtime,'label':runtime,'installed':True,'protocol':'fixture','install_hint':'fixture'})
    return settings


async def save(settings,runtime='codex',**changes):
    return await settings.command('/api/settings/harness',{'id':'settings-'+str(settings.current()['revision'])+'-'+runtime,
        'runtime':runtime,'model':'fixture-model','sandbox':'workspace-write','expected_revision':settings.current()['revision'],**changes})


async def completed_turn(chat,turn_id):
    # Fast runners can finish and release their in-memory task before submit
    # returns. The same public event tail works before and after that cleanup.
    async def tail():
        async for _ in chat.events(turn_id):
            pass
    await asyncio.wait_for(tail(),20)
    assert chat.get_turn(turn_id)['status']=='completed'


def test_provider_catalog_all_six_channels_and_no_secret_response(settings):
    async def scenario():
        data=await settings.channels();assert set(data['channels'])=={'chat','transcribe','speech','image','video','music'}
        assert len(data['channels']['image']['rows'])>0
        assert 'initial-private-secret' not in json.dumps(data)
        await save(settings,'api')
        request={'id':'save-api','expected_revision':settings.current()['revision'],'channel':'chat',
            'rows':[{'slot':'direct-api','model':'fixture-chat','baseUrl':'http://127.0.0.1:12345/v1','key':'new-private-key'}]}
        result=await settings.command('/api/settings/models/save',request)
        assert result['channels']['chat']['rows'][0]['model']=='fixture-chat'
        assert 'new-private-key' not in json.dumps(result)
        assert settings.environment()['EASEL_DIRECT_API_KEY']=='new-private-key'
        assert (settings.root/'.env').read_text()=='FIXTURE_SECRET=initial-private-secret\n'
        assert await settings.command('/api/settings/models/save',request)==result
        assert settings.operation('save-api')['state']=='completed'
        with pytest.raises(SettingsConflict):
            await settings.command('/api/settings/models/save',{**request,'channel':'image'})
    asyncio.run(scenario())


def test_stale_config_and_uninstalled_engine_do_not_change_current(settings,monkeypatch):
    async def scenario():
        original=settings.current()
        with pytest.raises(SettingsConflict):await save(settings,expected_revision=999)
        assert settings.current()==original
        monkeypatch.setattr(harnesses,'describe',lambda runtime:{'installed':False})
        with pytest.raises(ValueError):await save(settings,'acp')
        assert settings.current()==original
    asyncio.run(scenario())


def test_pending_operations_never_replay_provider_request(settings,monkeypatch):
    calls=[]
    async def execute(path,request,**kwargs):
        calls.append(path);raise RuntimeError('transport lost')
    monkeypatch.setattr(settings,'_execute',execute)
    async def scenario():
        value={'id':'lost-provider-request'}
        with pytest.raises(RuntimeError):await settings.command('/api/settings/models/selftest',value)
        with pytest.raises(SettingsConflict):await settings.command('/api/settings/models/selftest',value)
        assert len(calls)==1 and settings.operation(value['id'])['state']=='pending'
    asyncio.run(scenario())


def test_saved_defaults_only_change_new_sessions_and_freeze_real_dispatch(settings,monkeypatch):
    calls=[]
    class Adapter:
        async def run(self,request,emit,ask,bind):
            calls.append(request);bind(request.native_id or 'native-'+request.session_key)
            request.on_native_turn(request.native_id or 'native-'+request.session_key,'actual-turn')
            emit('token','TEMP output')
    monkeypatch.setattr(harnesses,'adapter',lambda runtime:Adapter())
    chat=ChatService(settings.box)
    chat.create_session({'id':'old-session','session_id':'old'})
    async def scenario():
        await save(settings,'opencode',sandbox='read-only',codex_auto_approve=True)
        chat.create_session({'id':'new-session','session_id':'new'})
        for sid,engine in [('old','codex'),('new','opencode')]:
            value={'id':'turn-'+sid,'sessionId':sid,'message':'TEMP'}
            turn=await chat.submit(value,snapshot=settings.box.creator.resolve(task='discuss'),actual_prompt='exact input')
            await completed_turn(chat,turn['id'])
            assert chat.get_turn(turn['id'])['runtime']==engine
            assert calls[-1].env['EASEL_AGENT_RUNTIME']==engine
            assert 'initial-private-secret' in calls[-1].env.values()
        assert calls[0].sandbox=='workspace-write' and calls[0].codex_auto_approve is False
        assert calls[1].sandbox=='read-only'
        assert chat.history('old')['session']['runtime']=='codex'
        await chat.close()
    asyncio.run(scenario())


def test_legacy_codex_conversation_survives_switch_before_first_new_session(settings):
    async def scenario():
        await save(settings,'api')
        chat=ChatService(settings.box)
        assert chat.execution_settings({'runtime':'codex'})['runtime']=='codex'
        await chat.close()
    asyncio.run(scenario())


def test_codex_full_access_is_frozen_per_session_and_overrides_readonly_production(settings, monkeypatch):
    calls = []
    class Adapter:
        async def run(self, request, emit, ask, bind):
            calls.append(request)
            bind('native-' + request.session_key)
            request.on_native_turn('native-' + request.session_key, 'temp-turn')
            emit('token', 'TEMP output')
    monkeypatch.setattr(harnesses, 'adapter', lambda runtime: Adapter())
    chat = ChatService(settings.box)
    async def scenario():
        await save(settings, sandbox='read-only', codex_auto_approve=True)
        chat.create_session({'id': 'create-full', 'session_id': 'full'})
        from easel_workbench.chat_business import ChatBusiness
        business = ChatBusiness(settings.box)
        business.chat = chat
        assert '权限范围：danger-full-access' in business._workspace(chat.history('full')['session'])
        await save(settings, sandbox='read-only', codex_auto_approve=False)
        chat.create_session({'id': 'create-limited', 'session_id': 'limited'})
        snapshot = settings.box.creator.resolve(task='discuss')
        turn = await chat.submit({'id': 'full-turn', 'sessionId': 'full', 'message': 'TEMP'},
            snapshot=snapshot, actual_prompt='TEMP frozen', work={'work_id': 'temp-work'})
        await completed_turn(chat,turn['id'])
        assert calls[-1].codex_auto_approve is True
        assert '权限范围：danger-full-access' in calls[-1].frozen_instructions
        with pytest.raises(ChatConflict, match='只读'):
            await chat.submit({'id': 'limited-turn', 'sessionId': 'limited', 'message': 'TEMP'},
                snapshot=snapshot, actual_prompt='TEMP frozen', work={'work_id': 'temp-work'})
        assert len(calls) == 1
        assert chat.execution_settings(chat.history('full')['session'])['codex_auto_approve'] is True
        await chat.close()
    asyncio.run(scenario())


def test_api_mode_runs_original_stream_but_rejects_tools_before_acceptance(settings,monkeypatch):
    from easel_workbench import settings_execution
    calls=[]
    async def stream(env,content,**options):
        calls.append((env,content,options));yield 'token','TEMP API';yield 'finish','stop'
    monkeypatch.setattr(settings_execution,'stream_chat',stream)
    async def scenario():
        await save(settings,'api')
        chat=ChatService(settings.box);chat.create_session({'id':'api-create','session_id':'api'})
        value={'id':'blocked','sessionId':'api','message':'TEMP','context':{'skill_id':'content-production'}}
        with pytest.raises(ChatConflict):await chat.submit(value,snapshot=settings.box.creator.resolve(task='discuss'),actual_prompt='TEMP')
        assert not calls and not chat.history('api')['session']['messages']
        value={'id':'allowed','sessionId':'api','message':'TEMP'}
        turn=await chat.submit(value,snapshot=settings.box.creator.resolve(task='discuss'),actual_prompt='TEMP')
        await completed_turn(chat,turn['id'])
        assert len(calls)==1 and chat.get_turn(turn['id'])['status']=='completed'
        assert not chat.get_turn(turn['id']).get('native_turn_id')
        await chat.close()
    asyncio.run(scenario())


def test_api_stop_after_dispatch_keeps_unknown_without_provider_ack(settings,monkeypatch):
    from easel_workbench import settings_execution
    calls=[]
    async def scenario():
        entered=asyncio.Event()
        async def stream(env,content,**options):
            calls.append(content);entered.set()
            yield 'token','partial retained'
            await asyncio.Event().wait()
        monkeypatch.setattr(settings_execution,'stream_chat',stream)
        await save(settings,'api')
        chat=ChatService(settings.box);chat.create_session({'id':'api-create','session_id':'api-stop'})
        turn=await chat.submit({'id':'api-stop-turn','sessionId':'api-stop','message':'TEMP'},
            snapshot=settings.box.creator.resolve(task='discuss'),actual_prompt='TEMP')
        await asyncio.wait_for(entered.wait(),5)
        assert chat._native_controls['api-stop']._task is chat._tasks[turn['id']]
        result=await chat.stop('api-stop',turn['id'])
        assert not result['stopped'] and result['status']=='unknown'
        receipt=chat.get_turn(turn['id'])
        assert receipt['stop_requested'] and not receipt.get('interrupt_confirmed')
        assert receipt['output']=='partial retained' and len(calls)==1
        await chat.close()
    asyncio.run(scenario())


def test_api_stop_while_waiting_for_shared_session_lock_never_dispatches(settings,monkeypatch):
    from easel_workbench import settings_execution
    from easel.web_services.chat import SessionFileLock
    async def forbidden(*args,**kwargs):
        pytest.fail('A stopped queued turn must not send a model request')
        yield
    monkeypatch.setattr(settings_execution,'stream_chat',forbidden)
    async def scenario():
        await save(settings,'api')
        chat=ChatService(settings.box);chat.create_session({'id':'api-create','session_id':'api-queued'})
        lock=SessionFileLock(chat.sessions_dir,'api-queued');assert lock.acquire(0)
        try:
            turn=await chat.submit({'id':'api-queued-turn','sessionId':'api-queued','message':'TEMP'},
                snapshot=settings.box.creator.resolve(task='discuss'),actual_prompt='TEMP')
            result=await chat.stop('api-queued',turn['id'])
            assert result['stopped'] and chat.get_turn(turn['id'])['delivery_state']=='not_started'
        finally:
            lock.release();await chat.close()
    asyncio.run(scenario())


def test_openclaw_uses_shared_supervisor_with_frozen_environment(settings,monkeypatch):
    from easel.harnesses.openclaw import OpenClawAdapter
    calls=[]
    async def scenario():
        entered=asyncio.Event()
        async def run(adapter,request,emit,ask,bind):
            calls.append(request);bind('openclaw-native');entered.set()
            await asyncio.Event().wait()
        monkeypatch.setattr(OpenClawAdapter,'run',run)
        await save(settings,'openclaw')
        chat=ChatService(settings.box);chat.create_session({'id':'claw-create','session_id':'claw'})
        turn=await chat.submit({'id':'claw-turn','sessionId':'claw','message':'TEMP'},
            snapshot=settings.box.creator.resolve(task='discuss'),actual_prompt='TEMP')
        await asyncio.wait_for(entered.wait(),5)
        assert chat._native_controls['claw']._task is chat._tasks[turn['id']]
        request=calls[0]
        assert request.env['OPENCLAW_CONFIG_PATH'].endswith('openclaw.json')
        assert settings.current()['revision']==turn['execution_settings']['revision']
        result=await chat.stop('claw',turn['id'])
        assert not result['stopped'] and result['status']=='unknown'
        assert len(calls)==1 and chat.get_turn(turn['id'])['stop_requested']
        assert not any(event['data']=='已停止' for event in chat.read_events(turn['id']))
        await chat.close()
    asyncio.run(scenario())


def test_real_status_distinguishes_installation_from_web_reachability(settings,monkeypatch):
    monkeypatch.setattr(harnesses,'describe',lambda runtime:{'installed':False})
    result=asyncio.run(settings.status())
    assert result['gateway'] is False and result['installed'] is False and result['authVerified'] is False


def test_fixed_runtime_install_rejected_and_isolated_child_paths(settings):
    from easel_workbench.runtime.connection_environment import service
    environment=service(settings.box)
    assert str(settings.root/'.runtime/media-tools') in environment.child_environment()['PATH']
    with pytest.raises(ValueError):environment.install({'id':'replace-python','recipe':'python'})


def test_installation_keeps_operation_identity_across_settings_and_shared_queue(settings,monkeypatch):
    from easel_workbench.runtime.connection_environment import service
    calls=[]
    def install(value):
        calls.append(value);return {'id':'install-receipt','state':'queued'}
    monkeypatch.setattr(service(settings.box),'install',install)
    async def scenario():
        request={'id':'exact-install-operation','tool_id':'pw'}
        first=await settings.command('/api/env/install',request)
        assert first['jobId']=='install-receipt' and calls==[{'id':'exact-install-operation','recipe':'browser'}]
        assert await settings.command('/api/env/install',request)==first and len(calls)==1
    asyncio.run(scenario())


@pytest.mark.parametrize('detected',[True,False])
def test_interrupted_installer_only_rechecks_dependencies_and_never_replays(settings,monkeypatch,detected):
    from easel_workbench.runtime.connection_environment import service
    from easel_workbench.infrastructure import processes
    environment=service(settings.box)
    environment.python.parent.mkdir(parents=True)
    environment.python.write_bytes(b'TEMP never executed')
    monkeypatch.setattr(environment,'_run',lambda *args,**kwargs:SimpleNamespace(returncode=0 if detected else 1,stdout='v24.19.0',stderr=''))
    monkeypatch.setattr(environment,'_install_run',lambda *args,**kwargs:pytest.fail('Interrupted installer replayed'))
    monkeypatch.setattr(processes,'process_identity',lambda *args:None)
    job={'id':'install-recovery','recipe':'browser','state':'running','owner_pid':999999,'owner_identity':{'created':'old'}}
    with settings.store.connect() as c:c.execute('INSERT INTO media_install_jobs VALUES(?,?,?)',(job['id'],job['recipe'],json.dumps(job)))
    result=environment.check();recovered=next(row for row in result['jobs'] if row['id']==job['id'])
    assert recovered['state']==('ok' if detected else 'fail')
    assert recovered['recovered_by']=='read_only_dependency_check'


def test_settings_hosts_share_native_function_code_and_isolate_revisions(settings,tmp_path):
    from easel.web_services import settings as native
    one=tmp_path/'one';two=tmp_path/'two';one.mkdir();two.mkdir()
    first,_=settings._module(one,{'OPENAI_API_KEY':'first'},settings.current())
    second,_=settings._module(two,{'OPENAI_API_KEY':'second'},settings.current())
    default=native.bind(into={'_read_env':lambda:{},'_harness_settings':lambda:{'runtime':'api'}})
    for name in ('_model_channels','api_settings_models_save','api_models_available','api_models_selftest'):
        assert getattr(first,name).__code__ is getattr(native,name).__code__
        assert getattr(default,name).__code__ is getattr(first,name).__code__
    assert first._read_env()['OPENAI_API_KEY']=='first'
    assert second._read_env()['OPENAI_API_KEY']=='second'
    assert first.api_models_available.__globals__ is not second.api_models_available.__globals__
    root=Path(__file__).resolve().parents[1]
    assert not (root/'easel_workbench/runtime/settings_upstream.py').exists()
    assert not (root/'scripts/extract_workbench_settings.py').exists()


@pytest.mark.parametrize('mode',['normal','slow-cancel'])
def test_actual_acp_rpc_request_and_stop_receipts_are_preserved(tmp_path,mode):
    import os,sys
    from easel.harnesses.acp import ACPAdapter
    from easel.harnesses.base import RunRequest
    from easel.harnesses.rpc import close_sessions
    fixture=Path(__file__).parent/'fixtures/harness_rpc.py';audit=tmp_path/'audit.jsonl';observed=[];interrupts=[]
    async def scenario():
        request=RunRequest('TEMP',tmp_path,{**os.environ,'FAKE_HARNESS_MODE':mode,'FAKE_HARNESS_AUDIT':str(audit)},
            command=(sys.executable,str(fixture),'acp'),session_key='settings-acp-'+mode,
            on_native_turn=lambda session,rid:observed.append((session,rid)),
            on_native_interrupt=lambda session,rid:interrupts.append((session,rid)))
        async def ask(questions):return {}
        task=asyncio.create_task(ACPAdapter().run(request,lambda *args:None,ask,lambda value:None))
        if mode=='slow-cancel':
            for _ in range(100):
                if audit.exists() and 'session/prompt' in audit.read_text():break
                await asyncio.sleep(.03)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):await task
            assert interrupts==observed and len(interrupts)==1
        else:
            await task
            assert len(observed)==1 and not interrupts
        rows=[json.loads(line) for line in audit.read_text().splitlines()]
        prompt=next(row for row in rows if row.get('method')=='session/prompt')
        assert observed[0]==('native-session',str(prompt['id']))
        await close_sessions(request.session_key)
    asyncio.run(scenario())


@pytest.mark.parametrize('invalid',[False,True])
def test_openclaw_embedded_result_keeps_cli_receipt_distinct_from_native_turn(tmp_path,monkeypatch,invalid):
    from easel.harnesses import openclaw
    from easel.harnesses.base import RunRequest,HarnessError
    receipts=[];turns=[];bound=[];output=[]
    payload={'payloads':[{'text':'TEMP'}],'meta':{'agentMeta':{'sessionId':'known-session'},**({'error':{'kind':'failed'}} if invalid else {})}}
    class Process:
        returncode=0
        async def communicate(self):return json.dumps(payload).encode(),b''
    async def spawn(*args,**kwargs):
        assert '--local' in args and '--json' in args
        return Process()
    monkeypatch.setattr(openclaw,'openclaw_base_cmd',lambda:['fixture-openclaw'])
    monkeypatch.setattr(openclaw.asyncio,'create_subprocess_exec',spawn)
    async def scenario():
        request=RunRequest('TEMP',tmp_path,{},native_id='known-session',on_native_turn=lambda *value:turns.append(value),on_execution_receipt=receipts.append)
        if invalid:
            with pytest.raises(HarnessError):await openclaw.OpenClawAdapter().run(request,lambda *value:output.append(value),None,bound.append)
            assert not receipts and not output[1:]
        else:
            await openclaw.OpenClawAdapter().run(request,lambda *value:output.append(value),None,bound.append)
            assert not turns and receipts[0]['kind']=='openclaw_cli_result' and len(receipts[0]['sha256'])==64
    asyncio.run(scenario())
