"""Exact native terminal evidence repairs an orphan; execution is never replayed."""
import asyncio
import importlib.util
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest
from easel import harnesses
from easel.harnesses.base import HarnessError
from easel_workbench.http.chat import handle

spec=importlib.util.spec_from_file_location('reconcile_chat_fixture',Path(__file__).with_name('test_workbench_chat.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
runtime,commands,service=fixture.runtime,fixture.commands,fixture.service
THREAD='01a1a762-3add-76a0-a82c-744bf3a9a3dc'
TURN='01a1a762-414b-7002-acf9-ec998b2bfb60'


def rollout(s,tmp_path,monkeypatch,kind='task_complete',**overrides):
    home=tmp_path/'codex';path=home/'sessions/rollout.jsonl';path.parent.mkdir(parents=True)
    with sqlite3.connect(home/'state_5.sqlite') as c:
        c.execute('CREATE TABLE threads(id TEXT,rollout_path TEXT)');c.execute('INSERT INTO threads VALUES(?,?)',(THREAD,str(path)))
    payload={'type':kind,'turn_id':TURN,'last_agent_message':'完整的最终回复',**overrides}
    rows=[{'type':'session_meta','payload':{'id':THREAD,'cwd':str(s.root)}},{'type':'event_msg','payload':payload}]
    path.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows),encoding='utf8')
    monkeypatch.setattr(s,'_environment',lambda:{'CODEX_HOME':str(home)})
    return path


async def orphan(s,monkeypatch):
    calls=[]
    class BrokenAdapter:
        async def run(self,request,emit,ask,bind):
            calls.append(request);bind(THREAD);request.on_native_turn(THREAD,TURN);emit('token','部分回复')
            raise HarnessError('Transport lost after native dispatch')
    monkeypatch.setattr(harnesses,'adapter',lambda _:BrokenAdapter())
    turn=await s.submit(fixture.value(),snapshot=None,actual_prompt='Frozen original')
    await fixture.completed(s,turn['id'])
    assert s.get_turn(turn['id'])['status']=='unknown'
    return turn['id'],calls


@pytest.mark.parametrize('kind,status,delivery',[('task_complete','completed','accepted'),('turn_aborted','stopped','interrupted')])
def test_exact_native_terminal_recovers_same_session_and_allows_next_turn(service,tmp_path,monkeypatch,kind,status,delivery):
    async def run():
        s,_=service;tid,calls=await orphan(s,monkeypatch);path=rollout(s,tmp_path,monkeypatch,kind)
        before=path.read_bytes();hook_calls=[];s.on_finish=lambda turn:hook_calls.append(turn['id']) or {'verified':True}
        request=SimpleNamespace(method='POST')
        result=await handle(s,None,'/api/chat/reconcile',request,{'sessionId':'workbench-session','turnId':tid})
        receipt=json.loads(result.body)
        assert receipt['execution_status']==status and receipt['delivery_state']==delivery
        assert receipt['native_receipt_reconciliation']['native_turn_id']==TURN
        assert s.history('workbench-session')['session']['pendingTurnId'] is None
        assert receipt['output']==('完整的最终回复' if status=='completed' else '部分回复')
        assert hook_calls==[tid] and len(calls)==1 and path.read_bytes()==before
        await s.reconcile('workbench-session',tid);assert hook_calls==[tid] and len(calls)==1
        next_turn=await s.submit(fixture.value('explicit-next'),snapshot=None,actual_prompt='Explicit followup')
        await fixture.completed(s,next_turn['id']);assert len(calls)==2 and calls[-1].native_id==THREAD
        await s.close()
    asyncio.run(run())


@pytest.mark.parametrize('case',['wrong-turn','missing','running','partial-line','wrong-thread','wrong-cwd','null-complete','damaged','outside-home'])
def test_insufficient_native_evidence_keeps_unknown_and_never_replays(service,tmp_path,monkeypatch,case):
    async def run():
        s,_=service;tid,calls=await orphan(s,monkeypatch)
        path=rollout(s,tmp_path,monkeypatch,'task_started' if case=='running' else 'task_complete',**({'turn_id':'another-turn'} if case=='wrong-turn' else {'last_agent_message':None} if case=='null-complete' else {}))
        if case=='missing':path.unlink()
        elif case=='partial-line':path.write_bytes(path.read_bytes().rstrip(b'\n'))
        elif case in ('wrong-thread','wrong-cwd'):
            rows=[json.loads(line) for line in path.read_text(encoding='utf8').splitlines()];rows[0]['payload']['id' if case=='wrong-thread' else 'cwd']='another-value';path.write_text('\n'.join(json.dumps(row) for row in rows)+'\n',encoding='utf8')
        elif case=='damaged':path.write_text('null\n[]\n{"unfinished":',encoding='utf8')
        elif case=='outside-home':
            outside=tmp_path/'outside.jsonl';outside.write_bytes(path.read_bytes())
            with sqlite3.connect(path.parent.parent/'state_5.sqlite') as c:c.execute('UPDATE threads SET rollout_path=?',(str(outside),))
        receipt=await s.reconcile('workbench-session',tid)
        assert receipt['execution_status']=='unknown' and len(calls)==1
        assert s.history('workbench-session')['session']['pendingTurnId']==tid
        await s.close()
    asyncio.run(run())


def test_active_owner_and_wrong_session_cannot_be_reconciled(service,tmp_path,monkeypatch):
    async def run():
        s,adapter=service;adapter.hold=asyncio.Event()
        turn=await s.submit(fixture.value(),snapshot=None,actual_prompt='Frozen')
        receipt=await s.reconcile('workbench-session',turn['id']);assert receipt['execution_status'] in ('accepted','submitting','running')
        with pytest.raises(fixture.ChatConflict):await s.reconcile('other-session',turn['id'])
        assert s.history('workbench-session')['session']['pendingTurnId']==turn['id']
        adapter.hold.set();await fixture.completed(s,turn['id']);await s.close()
    asyncio.run(run())


def test_restart_orphan_projection_can_converge_and_concurrent_checks_run_hook_once(service,tmp_path,monkeypatch):
    async def run():
        s,_=service;tid,calls=await orphan(s,monkeypatch);rollout(s,tmp_path,monkeypatch)
        with s.store.connect() as c:
            turn=s._turn(c,tid);turn.update(status='running',delivery_state='accepted');s._put_turn(c,turn)
        assert s.get_turn(tid)['status']=='unknown'  # Restart loses only in-memory ownership.
        entered=asyncio.Event();release=asyncio.Event();count=[]
        async def hook(turn):count.append(turn['id']);entered.set();await release.wait();return {'ok':True}
        s.on_finish=hook;one=asyncio.create_task(s.reconcile('workbench-session',tid));await entered.wait()
        two=asyncio.create_task(s.reconcile('workbench-session',tid));release.set();await asyncio.gather(one,two)
        assert count==[tid] and len(calls)==1 and s.get_turn(tid)['status']=='completed'
        await s.close()
    asyncio.run(run())
