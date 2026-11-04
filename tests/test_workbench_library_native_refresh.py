"""Native files publish through the existing metadata worker, TEMP only."""
import json,threading,time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from easel_workbench.features.works.library_index import LibraryIndex,request_refresh,health
from easel_workbench.application.chat import ChatBusiness


@pytest.fixture
def receipt_store(tmp_path):
    from easel_workbench.runtime.desk import Store
    return Store(tmp_path/'receipt.sqlite')


def file_node(name):return {'type':'file','path':name,'name':name,'kind':'text','mtime':1,'size':10}
def wait(predicate,timeout=4):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        if predicate():return
        time.sleep(.01)
    raise AssertionError('metadata worker did not publish its requested generation')


def test_refresh_is_durable_across_worker_restart_and_reads_never_build(tmp_path):
    values=[];calls=[]
    def build():calls.append(1);return list(values)
    first=LibraryIndex(tmp_path,build,lambda:'same-business-revision');first.rebuild();first.close()
    values.append(file_node('new.md'));assert request_refresh(tmp_path)
    reopened=LibraryIndex(tmp_path,build,lambda:'same-business-revision')
    assert reopened.list()['indexing'] is True
    assert len(calls)==1
    reopened.start()
    try:
        wait(lambda:not reopened.list()['indexing'])
        assert reopened.resolve('new.md')['nodes'][-1]['name']=='new.md'
        assert len(calls)==2
        for _ in range(10):reopened.list();reopened.resolve('new.md')
        assert len(calls)==2
    finally:reopened.close()


def test_completion_signal_during_refresh_is_not_cleared_by_older_publication(tmp_path):
    values=[];calls=[];entered=threading.Event();release=threading.Event()
    def build():
        calls.append(1);snapshot=list(values)
        if len(calls)==2:entered.set();assert release.wait(3)
        return snapshot
    index=LibraryIndex(tmp_path,build,lambda:'constant');index.rebuild();index.start()
    try:
        values.append(file_node('first.md'));index.invalidate();assert entered.wait(3)
        values.append(file_node('second.md'));index.invalidate();release.set()
        wait(lambda:len(calls)>=3 and not index.list()['indexing'])
        assert index.resolve('second.md')['nodes'][-1]['name']=='second.md'
        assert len(calls)==3
    finally:release.set();index.close()


def test_resolve_waits_for_requested_publication_without_building_inside_read(tmp_path):
    values=[];entered=threading.Event();release=threading.Event();calls=[]
    def build():
        calls.append(threading.current_thread().name)
        if len(calls)>1:entered.set();assert release.wait(3)
        return list(values)
    index=LibraryIndex(tmp_path,build);index.rebuild();index.start()
    try:
        values.append(file_node('actual-result.md'));index.invalidate();assert entered.wait(3)
        resolved=[];reader=threading.Thread(target=lambda:resolved.append(index.resolve('actual-result.md')),name='read-only-probe');reader.start()
        time.sleep(.08);assert reader.is_alive();assert len(calls)==2
        release.set();reader.join(3);assert not reader.is_alive()
        assert resolved[0]['nodes'][-1]['path']=='actual-result.md'
        assert 'read-only-probe' not in calls
        start=time.monotonic()
        with pytest.raises(HTTPException) as error:index.resolve('not-an-output.md')
        assert error.value.status_code==404 and time.monotonic()-start<.5
    finally:release.set();index.close()


@pytest.mark.parametrize('status',['completed','stopped','failed','unknown'])
def test_every_terminal_native_run_requests_refresh_without_changing_its_receipt(tmp_path,status,receipt_store):
    calls=[];index=SimpleNamespace(invalidate=lambda:calls.append(1));turn={'id':'native-turn','session_id':'original-session','status':status,'output':'Original preserved reply'}
    business=SimpleNamespace(root=tmp_path,store=receipt_store,box=SimpleNamespace(_native_api=SimpleNamespace(library=index)))
    before=json.dumps(turn,sort_keys=True)
    assert ChatBusiness.finished(business,turn)=={'session_id':'original-session','model_status':status}
    assert calls==[1] and json.dumps(turn,sort_keys=True)==before


def test_refresh_signal_failure_does_not_turn_a_real_native_result_into_hook_failure(tmp_path,monkeypatch,receipt_store):
    from easel_workbench.runtime import server_logging
    events=[];monkeypatch.setattr(server_logging,'exception',lambda *args,**kwargs:events.append((args,kwargs)))
    def fail():raise OSError('TEMP index unavailable')
    business=SimpleNamespace(root=tmp_path,store=receipt_store,box=SimpleNamespace(_native_api=SimpleNamespace(library=SimpleNamespace(invalidate=fail))))
    turn={'session_id':'original','status':'completed','output':'actual result remains intact'}
    assert ChatBusiness.finished(business,turn)=={'session_id':'original','model_status':'completed'}
    assert turn['output']=='actual result remains intact' and len(events)==1


def test_adapter_not_created_can_leave_a_durable_signal_for_existing_index(tmp_path,receipt_store):
    index=LibraryIndex(tmp_path,lambda:[]);index.rebuild();index.close()
    business=SimpleNamespace(root=tmp_path,store=receipt_store,box=SimpleNamespace())
    ChatBusiness.finished(business,{'session_id':'original','status':'stopped'})
    assert LibraryIndex(tmp_path,lambda:[]).list()['indexing'] is True
    assert request_refresh(tmp_path/'no-index-yet') is False


@pytest.mark.parametrize('alias',[False,True])
def test_pending_resolve_and_alias_wait_off_event_loop(tmp_path,alias):
    import asyncio,contextlib,sqlite3
    from starlette.requests import Request
    from easel_workbench.runtime.native_api import NativeApi
    database=tmp_path/'temp.sqlite'
    with sqlite3.connect(database) as c:c.execute('CREATE TABLE artifacts(id TEXT,name TEXT,path TEXT)')
    def connection():
        c=sqlite3.connect(database);c.row_factory=sqlite3.Row;return contextlib.closing(c)
    api=NativeApi.__new__(NativeApi);api.root=tmp_path;api.store=SimpleNamespace(connect=connection)
    main_thread=threading.get_ident();seen=[]
    def resolve(path):
        seen.append((path,threading.get_ident()));assert threading.get_ident()!=main_thread
        time.sleep(.12)
        if alias and not path.startswith('native-session-'):raise HTTPException(404,'TEMP unregistered alias')
        return {'nodes':[{'path':path}]}
    api.library=SimpleNamespace(resolve=resolve,generation=lambda:'TEMP-generation');api._output_context=lambda path:{}
    from easel_workbench.features.works.library_deletion import LibraryDeletion
    api.deletions=LibraryDeletion(api)
    request=Request({'type':'http','method':'GET','path':'/api/library/resolve','query_string':b'path=session/turn/products/result.md','headers':[]})
    async def scenario():
        pending=asyncio.create_task(api.dispatch('/api/library/resolve',request,None))
        await asyncio.sleep(.025);assert not pending.done()
        return await pending
    result=asyncio.run(scenario());assert result['nodes']
    assert len(seen)==(2 if alias else 1)
