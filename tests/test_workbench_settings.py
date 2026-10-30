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
            await chat._tasks[turn['id']]
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
        await chat._tasks[turn['id']]
        assert len(calls)==1 and chat.get_turn(turn['id'])['status']=='completed'
        assert not chat.get_turn(turn['id']).get('native_turn_id')
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
    from easel_workbench.runtime import distribution_runtime
    environment=service(settings.box)
    environment.python.parent.mkdir(parents=True)
    environment.python.write_bytes(b'TEMP never executed')
    monkeypatch.setattr(environment,'_run',lambda *args,**kwargs:SimpleNamespace(returncode=0 if detected else 1,stdout='v24.19.0',stderr=''))
    monkeypatch.setattr(environment,'_install_run',lambda *args,**kwargs:pytest.fail('Interrupted installer replayed'))
    monkeypatch.setattr(distribution_runtime,'process_identity',lambda *args:None)
    job={'id':'install-recovery','recipe':'browser','state':'running','owner_pid':999999,'owner_identity':{'created':'old'}}
    with settings.store.connect() as c:c.execute('INSERT INTO media_install_jobs VALUES(?,?,?)',(job['id'],job['recipe'],json.dumps(job)))
    result=environment.check();recovered=next(row for row in result['jobs'] if row['id']==job['id'])
    assert recovered['state']==('ok' if detected else 'fail')
    assert recovered['recovered_by']=='read_only_dependency_check'


def test_settings_projection_tracks_actual_upstream_functions():
    import ast
    root=Path(__file__).resolve().parents[1]
    upstream=ast.parse((root/'web/app.py').read_text(encoding='utf-8'))
    projection=ast.parse((root/'easel_workbench/runtime/settings_upstream.py').read_text(encoding='utf-8'))
    original={n.name:n for n in upstream.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))}
    for node in projection.body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
            expected=copy.deepcopy(original[node.name]);expected.decorator_list=[]
            assert ast.dump(node)==ast.dump(expected),node.name


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
