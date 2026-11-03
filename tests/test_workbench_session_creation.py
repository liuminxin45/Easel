"""Real TEMP SQLite session creation intake; no models or production writes."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import json
from pathlib import Path
import threading

import pytest

_spec=importlib.util.spec_from_file_location('session_creation_fixtures',Path(__file__).with_name('test_workbench_skill_commands.py'))
_fixtures=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_fixtures)
runtime,commands=_fixtures.runtime,_fixtures.commands

from easel_workbench.chat import ChatService,ChatConflict
from easel_workbench.runtime.operation_receipts import read as receipt


@pytest.fixture
def chat(commands,monkeypatch):
    from easel import harnesses
    monkeypatch.setattr(harnesses,'adapter',lambda *_:pytest.fail('Session metadata recovery must never invoke a model'))
    return ChatService(commands)


def request(operation='create-one'):
    return {'id':operation,'action':'create','profile_id':'oil-pig'}


def validate(profile):
    assert profile=='oil-pig'
    return {'id':profile,'revision':7,'active':True}


def counts(chat):
    with chat.store.connect() as c:
        return {table:c.execute('SELECT count(*) FROM '+table).fetchone()[0]
                for table in ('easel_chat_sessions','easel_chat_operations','easel_chat_turns')}


def test_v2_completes_once_and_retains_original_receipt(chat):
    async def scenario():
        value=await chat.session_creations.receive(request(),validate)
        assert value['operation_state']=='completed' and value['protocol_version']==2
        assert value['result']['session']==value['session']
        sid=value['session']['id']
        again=await chat.session_creations.receive(request(),lambda *_:pytest.fail('A completed operation must not revalidate current profile'))
        assert again['session']['id']==sid
        assert chat.create_session(request())['session']['id']==sid
        assert counts(chat)=={'easel_chat_sessions':1,'easel_chat_operations':1,'easel_chat_turns':0}
        observed=receipt(chat.store,'create-one','/api/chat/sessions')
        assert observed['state']=='received' and observed['operation_state']=='completed'
        assert observed['result']['session']['id']==sid
    asyncio.run(scenario())


def test_accepted_http_wait_timeout_does_not_cancel_metadata_work(chat,monkeypatch):
    async def scenario():
        entered=threading.Event();release=threading.Event();original=chat.create_session
        def hold(value):
            entered.set();assert release.wait(5)
            return original(value)
        monkeypatch.setattr(chat,'create_session',hold)
        try:
            value=await chat.session_creations.receive(request(),validate,timeout=.01)
            assert value['operation_state'] in ('accepted','running') and entered.is_set()
            assert counts(chat)['easel_chat_sessions']==0
        finally:release.set()
        await chat.session_creations.close()
        assert chat.session_creations.inspect('create-one')['operation_state']=='completed'
        assert counts(chat)['easel_chat_sessions']==1
    asyncio.run(scenario())


def test_cancelled_http_wait_preserves_accepted_worker(chat,monkeypatch):
    async def scenario():
        entered=threading.Event();release=threading.Event();original=chat.create_session
        def hold(value):
            entered.set();assert release.wait(5)
            return original(value)
        monkeypatch.setattr(chat,'create_session',hold)
        pending=asyncio.create_task(chat.session_creations.receive(request(),validate,timeout=4))
        while not entered.is_set():await asyncio.sleep(.001)
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):await pending
        release.set();await chat.session_creations.close()
        assert chat.session_creations.inspect('create-one')['operation_state']=='completed'
        assert counts(chat)['easel_chat_sessions']==1
    asyncio.run(scenario())


def test_absent_legacy_operation_is_sealed_and_late_original_cannot_create(chat):
    value=chat.session_creations.resolve('create-one',{'request':request(),'id':'independent-control'})
    assert value['operation_state']=='sealed_not_accepted'
    assert chat.session_creations.resolve('create-one',{'request':request()})==value
    with pytest.raises(ChatConflict):chat.create_session(request())
    observed=receipt(chat.store,'create-one','/api/chat/sessions')
    assert observed['state']=='rejected' and observed['operation_state']=='sealed_not_accepted'
    assert counts(chat)=={'easel_chat_sessions':0,'easel_chat_operations':0,'easel_chat_turns':0}


def test_legacy_request_paused_before_writer_is_fenced_by_atomic_seal(chat,monkeypatch):
    entered=threading.Event();release=threading.Event();original=chat.settings.capture
    def capture():
        entered.set();assert release.wait(5)
        return original()
    monkeypatch.setattr(chat.settings,'capture',capture)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(chat.create_session,request())
        assert entered.wait(3)
        value=chat.session_creations.resolve('create-one',{'request':request()})
        assert value['operation_state']=='sealed_not_accepted'
        release.set()
        with pytest.raises(ChatConflict):pending.result(timeout=5)
    assert counts(chat)['easel_chat_sessions']==0


def test_resolve_waits_for_inflight_transaction_and_returns_committed_session(chat,monkeypatch):
    entered=threading.Event();release=threading.Event();original=chat._put_session
    def put(c,session):
        original(c,session);entered.set();assert release.wait(5)
    monkeypatch.setattr(chat,'_put_session',put)
    with ThreadPoolExecutor(max_workers=2) as pool:
        creating=pool.submit(chat.create_session,request());assert entered.wait(3)
        resolving=pool.submit(chat.session_creations.resolve,'create-one',{'request':request()})
        assert not resolving.done()
        release.set();created=creating.result(timeout=5);resolved=resolving.result(timeout=5)
    assert resolved['operation_state']=='completed' and resolved['session']['id']==created['session']['id']
    assert counts(chat)['easel_chat_sessions']==1


def test_restart_resumes_only_accepted_metadata_with_frozen_settings(chat,commands,monkeypatch):
    accepted=chat.session_creations.accept(request(),validate)
    assert accepted['operation_state']=='accepted'
    with chat.store.connect() as c:
        frozen=json.loads(c.execute('SELECT settings FROM easel_chat_creation_intents').fetchone()[0])
    restarted=ChatService(commands)
    monkeypatch.setattr(restarted.settings,'capture',lambda:pytest.fail('Accepted creation must use its frozen settings'))
    async def scenario():
        await restarted.session_creations.start();await restarted.session_creations.close()
    asyncio.run(scenario())
    value=restarted.session_creations.inspect('create-one')
    assert value['operation_state']=='completed' and value['session']['execution_settings']==frozen
    assert counts(chat)=={'easel_chat_sessions':1,'easel_chat_operations':1,'easel_chat_turns':0}


def test_projection_failure_does_not_erase_success_and_startup_repairs_it(chat,monkeypatch):
    original=chat._save_metadata
    monkeypatch.setattr(chat,'_save_metadata',lambda *_:(_ for _ in ()).throw(PermissionError('TEMP file locked')))
    async def first():return await chat.session_creations.receive(request(),validate)
    value=asyncio.run(first())
    assert value['operation_state']=='completed'
    with chat.store.connect() as c:
        assert c.execute('SELECT projection_error FROM easel_chat_creation_intents').fetchone()[0]=='PermissionError'
    monkeypatch.setattr(chat,'_save_metadata',original)
    async def repair():
        await chat.session_creations.start();await chat.session_creations.close()
    asyncio.run(repair())
    assert chat._metadata_path(value['session']['id']).is_file()
    with chat.store.connect() as c:
        assert c.execute('SELECT projection_error FROM easel_chat_creation_intents').fetchone()[0] is None
    assert counts(chat)['easel_chat_sessions']==1


def test_same_operation_cannot_change_parameters_or_resolve_another_identity(chat):
    chat.session_creations.accept(request(),validate)
    with pytest.raises(ChatConflict):chat.session_creations.accept({**request(),'title':'Changed'},validate)
    with pytest.raises(ChatConflict):chat.session_creations.resolve('create-one',{'request':{**request(),'title':'Changed'}})
    with pytest.raises(ChatConflict):chat.session_creations.resolve('other',{'request':request()})
    assert chat.session_creations.inspect('create-one')['operation_state']=='accepted'


def test_receipt_inspection_has_no_writes_or_execution(chat):
    chat.session_creations.accept(request(),validate)
    with chat.store.connect() as c:
        original=[tuple(r) for r in c.execute('SELECT * FROM easel_chat_creation_intents')]
    for _ in range(3):
        assert receipt(chat.store,'create-one','/api/chat/sessions')['operation_state']=='accepted'
        assert receipt(chat.store,'no-operation','/api/chat/sessions')['operation_state']=='unresolved'
    with chat.store.connect() as c:
        assert [tuple(r) for r in c.execute('SELECT * FROM easel_chat_creation_intents')]==original
    assert counts(chat)['easel_chat_sessions']==0


def test_concurrent_same_operation_only_creates_one_session(chat):
    async def scenario():
        first,second=await asyncio.gather(chat.session_creations.receive(request(),validate),chat.session_creations.receive(request(),validate))
        await chat.session_creations.close()
        assert first['session']['id']==second['session']['id']
    asyncio.run(scenario())
    assert counts(chat)['easel_chat_sessions']==1


def test_metadata_worker_failure_is_terminal_and_never_becomes_infinite_waiting(chat,monkeypatch):
    monkeypatch.setattr(chat,'create_session',lambda *_:(_ for _ in ()).throw(ValueError('TEMP invalid metadata')))
    async def scenario():return await chat.session_creations.receive(request(),validate)
    value=asyncio.run(scenario())
    assert value['operation_state']=='rejected' and value['code']=='session_creation_rejected'
    assert receipt(chat.store,'create-one','/api/chat/sessions')['state']=='rejected'
    assert counts(chat)['easel_chat_sessions']==0


def test_http_v2_and_legacy_response_contracts_share_the_only_creation_service(chat):
    from types import SimpleNamespace
    from starlette.requests import Request
    from easel_workbench.http.chat import handle
    business=SimpleNamespace(creator=SimpleNamespace(detail=lambda _kind,pid:validate(pid)))
    def http(path,protocol=None):
        headers=[(b'x-operation-id',b'create-one' if path=='/api/chat/sessions' else b'control-id')]
        if protocol:headers.append((b'x-workbench-operation-protocol',protocol.encode()))
        return Request({'type':'http','method':'POST','path':path,'headers':headers,'query_string':b''})
    async def scenario():
        response=await handle(chat,business,'/api/chat/sessions',http('/api/chat/sessions','2'),request())
        assert response.status_code==200
        assert response.headers['x-workbench-operation-protocol']=='2'
        v2=json.loads(response.body);assert v2['operation_state']=='completed'
        response=await handle(chat,business,'/api/chat/sessions',http('/api/chat/sessions'),request())
        assert json.loads(response.body)=={'session':v2['session']}
        path='/api/chat/sessions/operations/old-missing/resolve'
        response=await handle(chat,business,path,http(path),{'id':'control-id','request':request('old-missing')})
        assert response.status_code==200 and json.loads(response.body)['operation_state']=='sealed_not_accepted'
    asyncio.run(scenario())
    assert counts(chat)['easel_chat_sessions']==1


def test_transient_projection_failure_repairs_without_server_restart(chat,monkeypatch):
    original=chat._save_metadata;calls=[]
    def transient(sid):
        calls.append(sid)
        if len(calls)==1:raise PermissionError('TEMP denied once')
        return original(sid)
    monkeypatch.setattr(chat,'_save_metadata',transient)
    chat.session_creations.projection_delays=(.001,.002,.003)
    async def scenario():
        value=await chat.session_creations.receive(request(),validate)
        assert value['operation_state']=='completed'
        await asyncio.gather(*list(chat.session_creations.projection_tasks.values()))
        await chat.session_creations.close()
    asyncio.run(scenario())
    assert len(calls)==2 and counts(chat)['easel_chat_sessions']==1
    with chat.store.connect() as c:
        assert c.execute('SELECT projection_error FROM easel_chat_creation_intents').fetchone()[0] is None


def test_permanent_projection_failure_has_bounded_attempts_and_keeps_success(chat,monkeypatch):
    calls=[]
    def denied(sid):
        calls.append(sid);raise PermissionError('TEMP locked indefinitely')
    monkeypatch.setattr(chat,'_save_metadata',denied)
    chat.session_creations.projection_delays=(.001,.002,.003)
    async def scenario():
        value=await chat.session_creations.receive(request(),validate)
        await asyncio.gather(*list(chat.session_creations.projection_tasks.values()))
        assert chat.session_creations.inspect('create-one')['operation_state']=='completed'
        await chat.session_creations.close()
    asyncio.run(scenario())
    assert len(calls)==4 and counts(chat)['easel_chat_sessions']==1


def test_lifecycle_journal_contains_only_hashed_identity_and_stage(chat,monkeypatch):
    from easel_workbench.runtime import server_logging
    events=[];monkeypatch.setattr(server_logging,'emit',lambda event,**fields:events.append((event,fields)))
    async def scenario():return await chat.session_creations.receive({**request(),'title':'PRIVATE TITLE SHOULD NEVER APPEAR'},validate)
    asyncio.run(scenario())
    phases=[fields['phase'] for event,fields in events if event=='session_creation']
    assert phases==['accepted','running','completed']
    assert 'PRIVATE TITLE' not in json.dumps(events)
    assert all('operation_ref' in fields and len(fields['operation_ref'])==24 for event,fields in events if event=='session_creation')
