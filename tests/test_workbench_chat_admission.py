"""Real TEMP HTTP/SQLite admission with controlled slow preparation and fake AI."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import threading
import time

import httpx
import pytest

spec=importlib.util.spec_from_file_location('admission_business_fixtures',Path(__file__).with_name('test_workbench_chat_business.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
business=fixtures.business
from easel import harnesses
from easel.harnesses.codex import CodexAdapter
from easel_workbench.application import create_app
from easel_workbench.application.chat_admission import ChatAdmission


class Auth:
    data={'origin':'https://localhost','host':'localhost','secret':'a'*32}
    def session(self,token):return {'csrf':'fixture','until':9999999999} if token=='owner' else None


class FakeAdapter:
    descriptor=CodexAdapter.descriptor
    def __init__(self):self.requests=[]
    async def run(self,request,emit,ask,bind):
        self.requests.append(request);native=request.native_id or 'TEMP-native'
        bind(native);request.on_native_turn(native,'TEMP-turn-'+str(len(self.requests)))
        emit('token','TEMP 已完成原字讨论，未调用真实模型。')


def setup(business,monkeypatch):
    adapter=FakeAdapter();monkeypatch.setattr(harnesses,'adapter',lambda runtime:adapter)
    app=create_app(root=business.root,store=business.store,box=business.box,auth=Auth())
    return app,app.state.chat_admissions,adapter


def request(tid='fast-one'):
    value=fixtures.value('discuss',tid);value['context'].update(skill_id='oil-pig-learn-article');value['message']='  按原字继续\n保留来源  '
    return value


async def wait_for(predicate):
    async with asyncio.timeout(10):
        while not predicate():await asyncio.sleep(.01)


async def finish(admissions,tid):
    await wait_for(lambda:tid not in admissions.tasks)
    task=admissions.chat._tasks.get(tid)
    if task:await task


def test_legacy_native_admission_is_owned_after_http_waiter_cancellation(business,monkeypatch):
    app,admissions,adapter=setup(business,monkeypatch)
    value,prepared=admissions._prepare({'request':request('legacy-cancel')})
    entered,release=threading.Event(),threading.Event();admit=admissions.chat._admit
    def slow(*args,**kwargs):
        entered.set();assert release.wait(10)
        return admit(*args,**kwargs)
    monkeypatch.setattr(admissions.chat,'_admit',slow)
    async def scenario():
        try:
            waiter=asyncio.create_task(admissions.chat.submit(value,**prepared))
            await wait_for(entered.is_set);waiter.cancel()
            with pytest.raises(asyncio.CancelledError):await waiter
            release.set()
            await wait_for(lambda:not admissions.chat._admissions)
            if admissions.chat._tasks:await asyncio.gather(*list(admissions.chat._tasks.values()))
            assert len(adapter.requests)==1 and admissions.chat.get_turn(value['turnId'])['status']=='completed'
        finally:
            release.set();await admissions.close();await admissions.chat.close()
    asyncio.run(scenario())


def test_real_http_ack_precedes_slow_preparation_and_client_exit_does_not_stop_execution(business,monkeypatch):
    app,admissions,adapter=setup(business,monkeypatch)
    entered,release=threading.Event(),threading.Event();prepare=admissions._prepare
    def slow(row):entered.set();assert release.wait(10);return prepare(row)
    monkeypatch.setattr(admissions,'_prepare',slow)
    async def scenario():
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url=Auth.data['origin']) as client:
                client.cookies.set('__Host-desk_session','owner');config=(await client.get('/api/config')).json()
                headers={'Origin':Auth.data['origin'],'X-CSRF-Token':config['csrf']};value=request()
                start=time.monotonic();response=await client.post('/api/chat/submit',json=value,headers=headers)
                assert response.status_code==202 and time.monotonic()-start<1
                assert response.json()['accepted_by_server'] and response.json()['id']==value['turnId']
                await wait_for(entered.is_set)
                assert not adapter.requests
                with business.store.connect() as c:
                    assert c.execute('SELECT count(*) FROM easel_chat_turns').fetchone()[0]==0
                    assert c.execute('SELECT count(*) FROM easel_chat_submissions').fetchone()[0]==1
                history=(await client.get('/api/chat/sessions/test-chat')).json()['session']
                assert history['pendingSubmissionId']==value['turnId'] and history['messages'][0]['content']==value['message']
                again=await client.post('/api/chat/submit',json=value,headers=headers);assert again.status_code==202
                altered=copy.deepcopy(value);altered['message']='different'
                assert (await client.post('/api/chat/submit',json=altered,headers=headers)).status_code==409
                injected={**value,'_selection':{}}
                assert (await client.post('/api/chat/submit',json=injected,headers=headers)).status_code==400
            # The browser/client is gone before preparation can finish.
            release.set();await finish(admissions,value['turnId'])
            assert len(adapter.requests)==1
            assert admissions.chat.get_turn(value['turnId'])['status']=='completed'
            assert not admissions.chat.history('test-chat')['session'].get('pendingSubmissionId')
        finally:
            release.set();await admissions.close();await admissions.chat.close()
    asyncio.run(scenario())


def test_lost_http_waiter_cannot_orphan_durably_received_request(business,monkeypatch):
    _,admissions,adapter=setup(business,monkeypatch)
    entered,release=threading.Event(),threading.Event();receive=admissions._receive
    def held(value):entered.set();assert release.wait(10);return receive(value)
    monkeypatch.setattr(admissions,'_receive',held)
    async def scenario():
        try:
            waiter=asyncio.create_task(admissions.receive(request()))
            await wait_for(entered.is_set);waiter.cancel()
            with pytest.raises(asyncio.CancelledError):await waiter
            release.set();await wait_for(lambda:not admissions.receivers);await finish(admissions,'fast-one')
            assert len(adapter.requests)==1 and admissions.get_turn('fast-one')['status']=='completed'
        finally:release.set();await admissions.close();await admissions.chat.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('stop',[False,True])
def test_preparing_stop_or_anchor_change_never_runs_model(business,monkeypatch,stop):
    _,admissions,adapter=setup(business,monkeypatch)
    entered,release=threading.Event(),threading.Event();prepare=admissions._prepare
    def held(row):entered.set();assert release.wait(10);return prepare(row)
    monkeypatch.setattr(admissions,'_prepare',held)
    async def scenario():
        try:
            await admissions.receive(request());await wait_for(entered.is_set)
            if stop:
                result=await admissions.stop('test-chat','fast-one');assert result['stopped'] and not result['native_started']
            else:
                with business.store.connect() as c:c.execute('UPDATE creator_profiles SET revision=revision+1')
            release.set();await finish(admissions,'fast-one')
            receipt=admissions.get_turn('fast-one');assert receipt['status']==('stopped' if stop else 'failed')
            assert not adapter.requests
            assert not admissions.chat.history('test-chat')['session'].get('pendingSubmissionId')
            assert (await admissions.receive(request()))['status']==receipt['status'] and not adapter.requests
            monkeypatch.setattr(admissions,'_prepare',prepare)
            await admissions.receive(request('corrected-followup'));await finish(admissions,'corrected-followup')
            history=admissions.history('test-chat')['session']['messages']
            assert [m['id'] for m in history]==['fast-one-user','fast-one','corrected-followup-user','corrected-followup']
            assert len(adapter.requests)==1
        finally:release.set();await admissions.close();await admissions.chat.close()
    asyncio.run(scenario())


def test_stop_in_admitting_transaction_prevents_the_native_handoff(business,monkeypatch):
    _,admissions,adapter=setup(business,monkeypatch)
    async def scenario():
        try:
            admissions._receive(request('at-handoff'))
            admissions._stage('at-handoff','admitting')
            result=await admissions.stop('test-chat','at-handoff')
            assert result['stopped'] and result['native_started'] is False
            row={'request':request('at-handoff')}
            original,prepared=admissions._prepare(row)
            with pytest.raises(ValueError):
                await admissions.chat.submit(original,**prepared,admission_id='at-handoff')
            assert not adapter.requests and admissions.get_turn('at-handoff')['status']=='stopped'
        finally:await admissions.close();await admissions.chat.close()
    asyncio.run(scenario())


def test_restart_resumes_saved_request_but_never_replays_existing_turn(business,monkeypatch):
    _,old,adapter=setup(business,monkeypatch)
    old._receive(request())
    replacement=ChatAdmission(chat=old.chat,business=old.business)
    async def scenario():
        try:
            await replacement.start();await finish(replacement,'fast-one');assert len(adapter.requests)==1
            with business.store.connect() as c:
                row=replacement._row(c,'fast-one');row['status']='admitting';replacement._put(c,row)
            await replacement.start();await finish(replacement,'fast-one');assert len(adapter.requests)==1
        finally:await replacement.close();await old.chat.close()
    asyncio.run(scenario())


def test_native_turn_registration_failure_rolls_back_and_releases_intake(business,monkeypatch):
    _,admissions,adapter=setup(business,monkeypatch)
    with business.store.connect() as c:
        c.execute("CREATE TRIGGER admission_fail_turn AFTER INSERT ON easel_chat_turns BEGIN SELECT RAISE(ABORT,'TEMP native turn register'); END")
    async def scenario():
        try:
            receipt=await admissions.receive(fixtures.value('poster','poster-one'));assert receipt['id']=='poster-one'
            await finish(admissions,'poster-one')
            failed=admissions.get_turn('poster-one')
            assert failed['admission_failed'] and 'IntegrityError' in failed['error']
            assert not adapter.requests and 'poster-one' not in admissions.chat._owned_turns
            with business.store.connect() as c:
                for table in ('easel_chat_turns','toolbox_works','toolbox_jobs','creator_model_calls'):
                    assert c.execute('SELECT count(*) FROM '+table).fetchone()[0]==0,table
            assert not admissions.chat.history('test-chat')['session'].get('pendingSubmissionId')
            with business.store.connect() as c:c.execute('DROP TRIGGER admission_fail_turn')
            await admissions.receive(request('after-register-failure'))
            await finish(admissions,'after-register-failure')
            assert len(adapter.requests)==1
            assert admissions.get_turn('after-register-failure')['status']=='completed'
        finally:await admissions.close();await admissions.chat.close()
    asyncio.run(scenario())
