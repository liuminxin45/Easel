"""The real Codex adapter and private receipts; all model calls are synthetic."""
import asyncio
from contextlib import asynccontextmanager
import importlib.util
from pathlib import Path

import pytest

_spec=importlib.util.spec_from_file_location('stop_fixtures',Path(__file__).with_name('test_workbench_chat.py'))
_f=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_f)
runtime,commands,service=_f.runtime,_f.commands,_f.service

from easel import harnesses
from easel.harnesses import codex, codex_stop, store
from easel.harnesses.base import HarnessError
from easel_workbench.chat import ChatService, ChatConflict


@pytest.mark.parametrize('phase,outcome,closure',[
    ('prepare','interrupted',True), ('start','interrupted',True),
    ('start','completed',True), ('start','failed',True),
    ('start','terminal_before_ack',True), ('start','lost_notification',True),
    ('start','missing',True), ('start','missing',False), ('start','no_start_ack',True),
])
def test_immediate_stop_converges_without_replay(service,monkeypatch,phase,outcome,closure):
    async def scenario():
        s,_=service;entered=asyncio.Event();release=asyncio.Event();methods=[];receivers=[]
        class RPC:
            initialized=None;native_id=''
            def __init__(self,request,notify):self.request=request;self.notify=notify;self.turn_id='turn-'+str(len(receivers));self.interrupted=False
            def terminal(self,status):
                self.notify('turn/completed',{'threadId':self.thread_id,
                    'turn':{'id':self.turn_id,'status':status}})
            async def send(self,message):pass
            async def call(self,method,params,**kwargs):
                methods.append(method)
                if method=='initialize':
                    if phase=='prepare' and len(receivers)==1:entered.set();await release.wait()
                    return {}
                if method in ('thread/start','thread/resume'):
                    self.thread_id=params.get('threadId','thread-'+str(len(receivers)))
                    return {'thread':{'id':self.thread_id}}
                if method=='turn/start':
                    if len(receivers)==1:
                        entered.set()
                        if outcome=='no_start_ack':await asyncio.Event().wait()
                        await release.wait()
                    else:self.terminal('completed')
                    return {'turn':{'id':self.turn_id}}
                if method=='turn/interrupt':
                    self.interrupted=True
                    if outcome=='terminal_before_ack':
                        self.terminal('interrupted');await asyncio.Event().wait()
                    if outcome in ('completed','interrupted','failed'):self.terminal(outcome)
                    if outcome=='missing':raise HarnessError('Synthetic interrupt ACK loss')
                    return {}
                if method=='thread/read':
                    return {'thread':{'turns':[{'id':self.turn_id,'status':'interrupted'}] if outcome=='lost_notification' else []}}
                raise AssertionError(method)
            async def wait_notification(self,future):return await asyncio.shield(future)
        @asynccontextmanager
        async def connection(request,command,notify,respond,**kwargs):
            rpc=RPC(request,notify);receivers.append(rpc)
            attached={'pid':1234+len(receivers),'process_token':str(len(receivers))*32}
            request.on_execution_receipt({'kind':'codex_process_attached',**attached})
            try:yield rpc
            except BaseException:
                if closure:request.on_execution_receipt({'kind':'codex_process_closed',**attached,'returncode':1,'tree_closed':True})
                raise
        monkeypatch.setattr(codex,'connection',connection)
        monkeypatch.setattr(harnesses,'adapter',lambda runtime:codex.CodexAdapter())
        monkeypatch.setattr(codex_stop,'STOP_GRACE_SECONDS',.03)
        first=await s.submit(_f.value(),snapshot=None,actual_prompt='EXACT frozen user input')
        await asyncio.wait_for(entered.wait(),2)
        stops=[asyncio.create_task(s.stop('workbench-session',first['id'])) for _ in range(3)]
        while first['id'] not in s._stop_requested:await asyncio.sleep(0)
        if phase=='start':release.set()
        await asyncio.gather(*stops);await _f.completed(s,first['id'])
        turn=s.get_turn(first['id'],private=True)
        expected='stopped' if phase=='prepare' or outcome in ('interrupted','terminal_before_ack','lost_notification') else outcome if outcome in ('completed','failed') else 'unknown'
        assert turn['status']==expected
        assert turn['actual_prompt']=='EXACT frozen user input' and methods.count('turn/start')==(phase=='start')
        assert methods.count('turn/interrupt')<2
        old_binding=store.binding(s.sessions_dir,'workbench-session')
        assert bool(s.history('workbench-session')['session']['pendingTurnId'])==(expected=='unknown' and not closure)
        if expected=='unknown' and not closure:
            with pytest.raises(ChatConflict):await s.submit(_f.value('blocked'),snapshot=None,actual_prompt='no replay')
        else:
            # A lost old callback cannot overwrite the archived turn after finish.
            receivers[0].request.on_execution_receipt({'kind':'codex_process_closed','pid':0})
            second=await s.submit(_f.value('next'),snapshot=None,actual_prompt='NEW explicit message')
            await _f.completed(s,second['id'])
            assert s.get_turn(second['id'])['status']=='completed'
            if old_binding.get('native_id'):assert store.binding(s.sessions_dir,'workbench-session')==old_binding
            if expected=='unknown':
                assert turn['execution_closed'] and s.get_turn(second['id'],private=True)['native_session_key']!='workbench-session'
                assert '只读历史记录' in s.get_turn(second['id'],private=True)['frozen_instructions']
        await s.close()
    asyncio.run(scenario())


@pytest.mark.parametrize('terminal',[True,False])
def test_real_stdio_process_and_child_are_closed_without_native_ack(tmp_path,monkeypatch,terminal):
    import os
    import sys
    import json
    from easel.harnesses.base import RunRequest
    fixture=tmp_path/'fake.py'
    fixture.write_text('''import sys,json,subprocess,time
child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(120)'])
open('child.pid','w').write(str(child.pid))
for line in sys.stdin:
 m=json.loads(line);method=m.get('method');result={}
 if method=='thread/start':result={'thread':{'id':'thread'}}
 if method=='turn/start':result={'turn':{'id':'turn'}}
 if method=='turn/interrupt':
  if sys.argv[1]=='True':
   print(json.dumps({'method':'turn/completed','params':{'threadId':'thread','turn':{'id':'turn','status':'interrupted'}}}),flush=True)
   time.sleep(5)
  else:continue
 if method=='thread/read':result={'thread':{'turns':[]}}
 if 'id' in m:print(json.dumps({'id':m['id'],'result':result}),flush=True)
''',encoding='utf-8')
    async def scenario():
        event=asyncio.Event();ready=asyncio.Event();receipts=[]
        request=RunRequest('TEMP synthetic, no model',tmp_path,dict(os.environ),
            command=(sys.executable,str(fixture),str(terminal)),session_key='stdio-test',stop_event=event,
            on_native_turn=lambda *ids:ready.set(),on_execution_receipt=receipts.append)
        async def ask(items):raise AssertionError('No tool interaction')
        task=asyncio.create_task(codex.CodexAdapter().run(request,lambda *args:None,ask,lambda value:None))
        await asyncio.wait_for(ready.wait(),5)
        child=None
        if os.name=='nt':
            from easel_workbench.runtime.scripts.windows_process_identity import ProcessIdentity
            child=ProcessIdentity(int((tmp_path/'child.pid').read_text()))
        event.set()
        with pytest.raises(HarnessError):await asyncio.wait_for(task,8)
        attached=next(value for value in receipts if value['kind']=='codex_process_attached')
        closed=next(value for value in receipts if value['kind']=='codex_process_closed')
        assert closed['tree_closed'] and type(closed['returncode']) is int
        assert attached['pid']==closed['pid'] and attached['process_token']==closed['process_token']
        assert any(value.get('status')=='interrupted' for value in receipts)==terminal
        if child:
            try:assert child.exited()
            finally:child.close()
    monkeypatch.setattr(codex_stop,'STOP_GRACE_SECONDS',.05)
    asyncio.run(scenario())


@pytest.mark.parametrize('terminal',[None,'completed','interrupted'])
def test_restart_releases_only_a_proven_closed_exact_generation(service,terminal):
    s,_=service
    async def scenario():
        # Persist an orphan in TEMP; no native call is made during reconciliation.
        turn,env=s._admit(_f.value(),snapshot=None,actual_prompt='Frozen')
        s._release_owned(turn['id'])
        attached={'pid':33,'process_token':'a'*32}
        with s.store.connect() as c:
            turn.update(status='running',stop_requested=True,local_process=attached,
                local_execution_closed={**attached,'source':'owned_rpc_process','tree_closed':True,'returncode':1,'turn_id':turn['id']})
            if terminal:
                turn.update(native_id='thread',native_turn_id='turn',native_terminal={
                    'kind':'codex_terminal','thread_id':'thread','turn_id':'turn','status':terminal})
            s._put_turn(c,turn)
        restored=ChatService(s.box)
        result=await restored.reconcile('workbench-session',turn['id'])
        assert result['status']==('unknown' if terminal is None else 'stopped' if terminal=='interrupted' else 'completed')
        session=restored.history('workbench-session')['session']
        assert session['pendingTurnId'] is None
        if terminal is None:assert session['native_session_key']!='workbench-session' and result['execution_closed']
        assert restored.history('workbench-session')['session']['messages'][0]['content']=='用户原话'
        await restored.close();await s.close()
    asyncio.run(scenario())
