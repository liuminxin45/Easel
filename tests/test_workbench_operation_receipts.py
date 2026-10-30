"""TEMP receipt recovery never executes a command or changes business records."""
import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

spec=importlib.util.spec_from_file_location('receipt_fixtures',Path(__file__).with_name('test_workbench_platform_accounts.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
runtime,commands,accounts=fixtures.runtime,fixtures.commands,fixtures.accounts

from easel_workbench.runtime.operation_receipts import read


def test_receipt_reads_the_original_ack_without_starting_login(accounts,monkeypatch):
    session=fixtures.create(accounts)
    request={'id':'original-login','action':'login','session_id':session['id'],'base_revision':1}
    receipt=accounts.command(request)
    monkeypatch.setattr(accounts,'command',lambda *_:pytest.fail('receipt replayed a command'))
    monkeypatch.setattr(accounts,'run',lambda *_:pytest.fail('receipt started a browser'))
    with accounts.store.connect() as c:
        before=[tuple(row) for row in c.execute('SELECT * FROM media_account_sessions')]
    for _ in range(3):
        assert read(accounts.store,'original-login','/api/platform-accounts')=={'id':'original-login','state':'received','result':receipt}
    with accounts.store.connect() as c:
        assert [tuple(row) for row in c.execute('SELECT * FROM media_account_sessions')]==before
        assert c.execute('SELECT count(*) FROM media_operations').fetchone()[0]==2


def test_missing_receipt_is_waiting_and_never_treated_as_unsent(accounts):
    assert read(accounts.store,'not-yet-committed','/api/platform-accounts')['state']=='waiting'
    assert read(accounts.store,'not-yet-committed','/api/not-supported')['state']=='unavailable'
    assert read(accounts.store,'not-yet-committed',"/api/platform-accounts';DELETE FROM media_operations")['state']=='unavailable'
    with pytest.raises(ValueError):read(accounts.store,'../bad','/api/platform-accounts')


def test_receipts_are_namespaced_by_endpoint(accounts):
    fixtures.create(accounts)
    assert read(accounts.store,'create-wechat-oa','/api/platform-accounts')['state']=='received'
    assert read(accounts.store,'create-wechat-oa','/api/creator/commands')['state']=='waiting'


def test_existing_production_receipt_reads_never_queue_a_second_job(accounts):
    result=accounts.box.create({'id':'receipt-work','title':'TEMP','material':'TEMP source','format':'poster'})
    for _ in range(3):assert read(accounts.store,'receipt-work','/api/works')['result']==result
    assert read(accounts.store,'receipt-work','/api/works/other-work/finalize')['state']=='waiting'
    with accounts.store.connect() as c:assert c.execute('SELECT count(*) FROM toolbox_jobs WHERE id=?',('receipt-work',)).fetchone()[0]==1


def test_collection_receipt_projects_the_original_run_without_enqueue(accounts):
    with accounts.store.connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS collection_operations(id TEXT PRIMARY KEY,signature TEXT NOT NULL,run_id TEXT NOT NULL)')
        c.execute('INSERT INTO collection_operations VALUES(?,?,?)',('collect-once','original-signature','original-run'))
    calls=[]
    collection=SimpleNamespace(get=lambda key:calls.append(key) or {'id':key,'status':'running'})
    result=read(accounts.store,'collect-once','/api/collection/runs',collection=collection)
    assert result['result']['id']=='original-run' and result['result']['reused'] and calls==['original-run']


def test_login_ack_does_not_wait_for_full_dependency_diagnostics(accounts,monkeypatch):
    import json
    from starlette.requests import Request
    from easel.web_services.accounts import create_accounts_context
    from easel_workbench.runtime.easel_connection_support import ConnectionConflict
    from easel_workbench.runtime.native_api import handle
    from easel_workbench.runtime import connection_environment
    session=fixtures.create(accounts);accounts.runner=None;accounts.autostart=True
    monkeypatch.setattr(connection_environment,'service',lambda *_:pytest.fail('synchronous dependency diagnostics delayed login'))
    starts=[]
    monkeypatch.setattr('easel_workbench.runtime.easel_accounts.threading.Thread',lambda **kwargs:SimpleNamespace(start=lambda:starts.append(kwargs)))
    with accounts.store.connect() as c:
        before=[tuple(row) for row in c.execute('SELECT * FROM media_account_sessions')]
    # The retired executor cannot regain a write path merely to satisfy an old
    # acknowledgement test. It must reject before launching or diagnosing.
    with pytest.raises(ConnectionConflict,match='旧账号执行入口已退役'):
        accounts.command({'id':'fast-login','action':'login','session_id':session['id'],'base_revision':1})
    assert starts==[]
    with accounts.store.connect() as c:
        assert [tuple(row) for row in c.execute('SELECT * FROM media_account_sessions')]==before
        assert c.execute('SELECT result FROM media_operations WHERE id=?',('fast-login',)).fetchone() is None

    processes=[]
    def launch(command,**options):
        processes.append(command)
        return SimpleNamespace(poll=lambda:None)
    native=create_accounts_context(accounts.root,environment={},process_factory=launch)
    accounts._native_context=native
    assert native.api_mp_login_start.__code__.co_filename.replace('\\','/').endswith('web_services/accounts.py')
    path='/api/accounts/wechat-oa/mp-login'
    def request():
        return Request({'type':'http','method':'POST','path':path,'headers':[(b'x-operation-id',b'native-fast-login')],
                        'query_string':b'','scheme':'https','server':('native.test',443)})
    first=asyncio.run(handle(accounts.box,path,request(),{}))
    repeated=asyncio.run(handle(accounts.box,path,request(),{}))
    assert first.status_code==repeated.status_code==200
    assert json.loads(first.body)==json.loads(repeated.body)
    assert json.loads(first.body)['state']=='starting'
    assert len(processes)==1 and Path(processes[0][1]).name=='weixin_mp_stats.py'
    assert starts==[]
    observed=asyncio.run(native.api_accounts())
    assert not next(value for value in observed if value['platform']=='wechat-oa')['loggedIn']


def test_receipt_http_endpoint_requires_owner_auth_and_is_read_only(accounts):
    from easel_workbench.application import create_app
    fixtures.create(accounts)
    auth=SimpleNamespace(data={'origin':'https://localhost','host':'localhost','secret':'a'*32},session=lambda token:{'csrf':'test','until':9999999999} if token=='owner' else None)
    app=create_app(store=accounts.store,box=accounts.box,root=accounts.root,studio=accounts.box.studio,distribution=accounts.distribution,auth=auth)
    async def check():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://localhost') as client:
            url='/api/operations/create-wechat-oa?path=%2Fapi%2Fplatform-accounts'
            assert (await client.get(url)).status_code==401
            response=await client.get(url,headers={'Cookie':'__Host-desk_session=owner'})
            assert response.status_code==200 and response.json()['state']=='received'
            assert response.headers['cache-control']=='no-store'
            assert (await client.get(url,headers={'Cookie':'__Host-desk_session=owner','Sec-Fetch-Site':'cross-site'})).status_code==403
            csrf=(await client.get('/api/config',headers={'Cookie':'__Host-desk_session=owner'})).json()['csrf']
            response=await client.post(url,headers={'Cookie':'__Host-desk_session=owner','Origin':'https://localhost','X-CSRF-Token':csrf},json={'id':'never-replay'})
            assert response.status_code==404
    asyncio.run(check())
