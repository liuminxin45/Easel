"""Connection lifetime and not-sent boundaries; TEMP SQLite and fake native RPC."""
import copy
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest

_spec=importlib.util.spec_from_file_location('command_fixture',Path(__file__).with_name('test_workbench_skill_commands.py'))
_fixtures=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_fixtures)
runtime,commands=_fixtures.runtime,_fixtures.commands

from easel_workbench.runtime import bridge,poster_executor,task_runtime,production_retry
from easel_workbench.runtime.desk import PROJECT,THREAD
from easel_workbench.runtime.poster_rpc import RPCError,RPCNotSentError


class Clock:
    def __init__(self):self.value=dt.datetime(2030,1,1,tzinfo=dt.timezone.utc)
    def __call__(self):return self.value
    def advance(self,seconds):self.value+=dt.timedelta(seconds=seconds)


class Native:
    def __init__(self,box,monkeypatch):
        self.box=box;self.calls=[];self.connections=[];self.failure=None;self.fail_method=None
        self.stream=[];self.before_turn=None;self.resume_error=None;self.queue=[]
        self.state=box.root/'native.sqlite'
        with sqlite3.connect(self.state) as c:c.execute('CREATE TABLE threads(id TEXT PRIMARY KEY,cwd TEXT,rollout_path TEXT)')
        monkeypatch.setattr(bridge,'STATE',self.state)
    def factory(self,on_event=None):
        native=self
        class Connection:
            def __init__(self):
                self.loaded=set();self.on_event=on_event;self.closed=False;self.close_count=0
                self.process=SimpleNamespace(poll=lambda:0 if self.closed else None)
            def call(self,method,params,timeout=None):
                assert not self.closed
                native.calls.append((len(native.connections),method,copy.deepcopy(params)))
                if method==native.fail_method:raise native.failure
                thread=params.get('threadId')
                if method=='thread/start':
                    thread='native-thread-'+str(len(native.connections));self.loaded.add(thread)
                    return {'thread':{'id':thread,'cwd':str(PROJECT),'path':str(native.box.root/(thread+'.jsonl'))}}
                if method=='thread/resume':
                    if native.resume_error:raise native.resume_error
                    with sqlite3.connect(native.state) as c:row=c.execute('SELECT rollout_path FROM threads WHERE id=?',(thread,)).fetchone()
                    if thread not in self.loaded and not row:
                        raise RPCError({'code':-32600,'message':'no rollout found for thread id '+thread})
                    self.loaded.add(thread)
                    return {'thread':{'id':thread,'cwd':str(PROJECT)}}
                if method=='thread/queue/list':return {'data':copy.deepcopy(native.queue)}
                if method=='thread/queue/add':return {'queuedSubmission':{'id':'queued-native'}}
                if method in ('turn/start','thread/queue/start'):
                    assert thread in self.loaded,'A new empty thread must stay on its owning connection.'
                    if native.before_turn:native.before_turn()
                    path=native.box.root/(thread+'.jsonl');path.touch()
                    with sqlite3.connect(native.state) as c:c.execute('INSERT OR REPLACE INTO threads VALUES(?,?,?)',(thread,str(PROJECT),str(path)))
                    turn='turn-'+params.get('clientUserMessageId','queued')
                    for delta in native.stream:
                        self.on_event({'method':'item/agentMessage/delta','params':{'threadId':thread,'turnId':turn,**delta}})
                    return {'turn':{'id':turn,'status':'completed','items':[{'type':'agentMessage','text':'TEMP final reply'}]}}
                raise AssertionError(method)
            def close(self):self.closed=True;self.close_count+=1
        result=Connection();self.connections.append(result);return result


@pytest.fixture
def setup(commands,monkeypatch):
    commands.create({'id':'new-work','format':'poster','title':'隔离制作','material':'不调用真实模型。','files':[]})
    native=Native(commands,monkeypatch);clock=Clock()
    executor=poster_executor.Executor(commands,factory=native.factory,rollout=lambda:commands.root/'legacy.jsonl',clock=clock)
    return commands,native,executor,clock


def row(box):
    with box.store.connect() as c:return dict(c.execute("SELECT * FROM toolbox_jobs WHERE id='new-work'").fetchone())


def ghost(box,native,*,dispatch=False):
    with box.store.connect() as c:
        run=task_runtime.read_run(c,'new-work');key=task_runtime.context_id(run)
        context={'id':key,'profile_id':'oil-pig','work_id':'new-work','status':'ready','thread_id':'ghost-native',
                 'rollout_path':str(box.root/'absent-rollout.jsonl'),'created_at':'old'}
        raw=task_runtime.packed(context)
        c.execute('INSERT INTO creator_thread_contexts VALUES(?,?,?)',(key,raw,'old'))
        if dispatch:c.execute("UPDATE toolbox_jobs SET dispatch_started=1,status='uncertain' WHERE id='new-work'")
    return context,raw


def test_first_turn_uses_exact_connection_that_created_empty_thread(setup):
    box,native,executor,_=setup
    def at_send():
        with box.store.connect() as c:
            run=task_runtime.read_run(c,'new-work')
            call=json.loads(c.execute('SELECT document FROM creator_model_calls WHERE id=?',(run['model_call_id'],)).fetchone()[0])
            assert call['status']=='submitting' and 'started_at' not in call
            assert c.execute("SELECT dispatch_started FROM toolbox_jobs WHERE id='new-work'").fetchone()[0]==1
    native.before_turn=at_send
    executor.tick()
    assert len(native.connections)==1
    assert [method for _,method,_ in native.calls]==['thread/start','thread/queue/list','turn/start']
    assert native.connections[0].closed and native.connections[0].close_count==1
    with box.store.connect() as c:
        run=task_runtime.read_run(c,'new-work');call=json.loads(c.execute('SELECT document FROM creator_model_calls').fetchone()[0])
        assert call['status']=='completed' and call['turn_id']=='turn-new-work'
        assert run['model_call_id']==call['id']


def test_preparation_failure_does_not_create_a_running_model_call(setup):
    box,native,executor,_=setup
    native.fail_method='thread/queue/list';native.failure=RPCError({'code':-32600,'message':'TEMP private input must not enter diagnostics'})
    executor.tick()
    with box.store.connect() as c:
        assert c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0]==0
        run=task_runtime.read_run(c,'new-work');assert run['status']=='queued'
        assert run['preparation']['status']=='failed'
        assert run['preparation']['diagnostic']=={'phase':'connect','error_type':'RPCError','reason':'native_request_rejected','rpc_code':-32600}
        assert 'TEMP private' not in json.dumps(run['preparation'])
        assert production_retry.read(c,'new-work')['attempt_count']==1
    assert row(box)['dispatch_started']==0


def test_positively_unsent_turn_records_not_started_and_reuses_frozen_input_and_budget(setup):
    box,native,executor,clock=setup
    native.fail_method='turn/start';native.failure=RPCNotSentError('connection_closed')
    executor.tick()
    with box.store.connect() as c:
        before=production_retry.read(c,'new-work');call=json.loads(c.execute('SELECT document FROM creator_model_calls').fetchone()[0])
        assert call['status']=='not_started' and call['delivery_state']=='not_sent'
        original_id=call['id'];original_inputs=copy.deepcopy(before['inputs'])
    assert row(box)['dispatch_started']==0
    native.fail_method=None;clock.advance(30);executor.tick()
    with box.store.connect() as c:
        after=production_retry.read(c,'new-work');calls=c.execute('SELECT id,document FROM creator_model_calls').fetchall()
        assert after['attempt_count']==2 and after['auto_retry_count']==1
        assert after['inputs']==original_inputs
        assert len(calls)==1 and calls[0]['id']==original_id
        assert json.loads(calls[0]['document'])['status']=='completed'
        assert json.loads(calls[0]['document'])['delivery_state']=='accepted'


def test_unknown_submission_never_allocates_or_sends_another_turn(setup):
    box,native,executor,clock=setup
    native.fail_method='turn/start';native.failure=TimeoutError('TEMP write acknowledgement unknown')
    executor.tick()
    assert row(box)['dispatch_started']==1 and row(box)['status']=='uncertain'
    with box.store.connect() as c:assert json.loads(c.execute('SELECT document FROM creator_model_calls').fetchone()[0])['status']=='unknown'
    calls=len(native.calls);clock.advance(1000);executor.tick()
    assert len(native.calls)==calls


def test_empty_ready_context_recovers_only_after_exact_missing_proof(setup):
    box,native,_,_=setup;old,raw=ghost(box,native)
    with task_runtime.prepare_target(box,'new-work',native.factory,lambda:None) as prepared:
        assert prepared.owned and not prepared.connection.closed
        assert [method for _,method,_ in native.calls]==['thread/resume','thread/start']
        with box.store.connect() as c:
            context=json.loads(c.execute('SELECT document FROM creator_thread_contexts').fetchone()[0])
            assert context['replaced_empty_context']==old
            assert context['replacement_evidence']['native_record_absent'] is True
            assert c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0]==0
    assert row(box)['dispatch_started']==0


@pytest.mark.parametrize('boundary',['rollout','native-row','sent-history','other-revision','unknown-model','wrong-error'])
def test_missing_context_recovery_rejects_every_uncertain_or_nonempty_authority(setup,boundary):
    box,native,_,_=setup;context,raw=ghost(box,native)
    if boundary=='rollout':Path(context['rollout_path']).touch()
    if boundary=='native-row':
        with sqlite3.connect(native.state) as c:c.execute('INSERT INTO threads VALUES(?,?,?)',('ghost-native',str(PROJECT),context['rollout_path']))
        native.resume_error=RPCError({'code':-32600,'message':'no rollout found for thread id ghost-native'})
    with box.store.connect() as c:
        if boundary=='sent-history':
            c.execute('INSERT INTO toolbox_dispatch_retries VALUES(?,?)',('new-work',json.dumps({'history':[{'event':'submitted'}]})))
        elif boundary=='other-revision':
            c.execute("INSERT INTO toolbox_jobs(id,work_id,kind,text,signature,status,created_at,dispatch_started) VALUES('older','new-work','create','','old','completed','old',1)")
        elif boundary=='unknown-model':
            c.execute('INSERT INTO creator_model_calls VALUES(?,?,?,?)',('unknown','new-work',json.dumps({'status':'unknown'}),'old'))
    if boundary=='wrong-error':native.resume_error=RPCError({'code':-32603,'message':'no rollout found for thread id ghost-native'})
    with pytest.raises((ValueError,RPCError)):
        task_runtime.prepare_target(box,'new-work',native.factory,lambda:None)
    assert not any(method=='thread/start' for _,method,_ in native.calls)
    with box.store.connect() as c:assert c.execute('SELECT document FROM creator_thread_contexts').fetchone()[0]==raw
    assert all(connection.closed for connection in native.connections)


def test_submitted_and_legacy_contexts_never_create_new_native_threads(setup):
    box,native,_,_=setup;context,_=ghost(box,native,dispatch=True)
    with task_runtime.prepare_target(box,'new-work',native.factory,lambda:None) as prepared:
        assert prepared.thread_id=='ghost-native' and prepared.connection is None
    assert not native.calls
    with box.store.connect() as c:c.execute("DELETE FROM creator_task_runs WHERE id='new-work'")
    legacy=box.root/'legacy.jsonl';legacy.touch()
    with task_runtime.prepare_target(box,'new-work',native.factory,lambda:legacy) as prepared:
        assert prepared.thread_id==THREAD and prepared.path==legacy
    assert not native.calls


def evidence_for_reconciliation(box,native):
    context,_=ghost(box,native)
    inputs=[{'type':'text','text':'TEMP exact frozen input'}]
    task_runtime.production_call(box,'new-work',inputs,status='running')
    state={'attempt_count':4,'auto_retry_count':3,'revision':9,'cycle':1,'phase':'exhausted','retry_exhausted':True,
           'inputs':inputs,'input_hash':'original','history':[{'event':'unsent_failure'}]}
    with box.store.connect() as c:
        c.execute("UPDATE toolbox_jobs SET status='error',error='Original unsent error' WHERE id='new-work'")
        c.execute('INSERT INTO toolbox_dispatch_retries VALUES(?,?)',('new-work',task_runtime.packed(state)))
    path=box.root/'.local/native-empty-proof.json';path.parent.mkdir()
    path.write_text(json.dumps({'job_id':'new-work','thread_id':'ghost-native','rpc_code':-32600,
        'rpc_reason':'thread_rollout_missing','rollout_absent':True,'native_record_absent':True}),encoding='utf-8')
    return {'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}


def test_controlled_reconciliation_changes_only_projections_and_preserves_retry_identity(setup):
    box,native,_,_=setup;proof=evidence_for_reconciliation(box,native)
    before=row(box)
    with box.store.connect() as c:
        retry_before=c.execute('SELECT document FROM toolbox_dispatch_retries').fetchone()[0]
        snapshot=copy.deepcopy(task_runtime.read_run(c,'new-work')['snapshot'])
    result=task_runtime.reconcile_preparation_failure(box,'new-work',proof)
    assert result['changed'] is True and result['requeued'] is False
    with box.store.connect() as c:
        assert c.execute('SELECT document FROM toolbox_dispatch_retries').fetchone()[0]==retry_before
        run=task_runtime.read_run(c,'new-work');assert run['status']=='failed' and run['snapshot']==snapshot
        call=json.loads(c.execute('SELECT document FROM creator_model_calls').fetchone()[0])
        assert call['status']=='not_started' and call['delivery_state']=='not_sent'
        assert 'started_at' not in call and call['preparation_started_at']
        assert call['input']==json.loads(retry_before)['inputs']
    assert row(box)==before
    assert task_runtime.reconcile_preparation_failure(box,'new-work',proof)['changed'] is False


@pytest.mark.parametrize('fault',['sha','sent','native-row','unknown-call'])
def test_controlled_reconciliation_rechecks_proof_and_refuses_sent_or_unknown(setup,fault):
    box,native,_,_=setup;proof=evidence_for_reconciliation(box,native)
    if fault=='sha':proof['sha256']='0'*64
    if fault=='native-row':
        with sqlite3.connect(native.state) as c:c.execute('INSERT INTO threads VALUES(?,?,?)',('ghost-native',str(PROJECT),'unavailable'))
    with box.store.connect() as c:
        if fault=='sent':c.execute("UPDATE toolbox_jobs SET dispatch_started=1 WHERE id='new-work'")
        if fault=='unknown-call':
            r=c.execute('SELECT id,document FROM creator_model_calls').fetchone();call=json.loads(r['document']);call['status']='unknown'
            c.execute('UPDATE creator_model_calls SET document=? WHERE id=?',(json.dumps(call),r['id']))
        before=c.execute('SELECT document FROM creator_task_runs').fetchone()[0]
    with pytest.raises(ValueError):task_runtime.reconcile_preparation_failure(box,'new-work',proof)
    with box.store.connect() as c:assert c.execute('SELECT document FROM creator_task_runs').fetchone()[0]==before


def test_actual_agent_text_stream_is_throttled_fenced_and_final_reply_remains_authoritative(setup,monkeypatch):
    box,native,executor,_=setup
    native.stream=[{'delta':'A'},{'delta':'B'},{'delta':'C'}]
    ticks=iter([100.0,100.2,101.2]);monkeypatch.setattr(poster_executor,'time',SimpleNamespace(monotonic=lambda:next(ticks)))
    updates=[];original=executor.fenced_update
    def observed(*args,**kwargs):
        if 'reply' in kwargs:updates.append(kwargs['reply'])
        return original(*args,**kwargs)
    monkeypatch.setattr(executor,'fenced_update',observed)
    executor.tick()
    assert updates==['A','ABC'] and row(box)['reply']=='TEMP final reply'
    # A late callback from the same old turn cannot update a terminal task.
    native.connections[0].on_event({'method':'item/agentMessage/delta','params':{
        'threadId':'native-thread-1','turnId':'turn-new-work','delta':'LATE'}})
    assert updates==['A','ABC'] and row(box)['reply']=='TEMP final reply'


def test_changed_context_is_fenced_again_at_the_actual_submission_boundary(setup,monkeypatch):
    box,native,executor,_=setup
    original=executor.mark_dispatch
    def changed(*args,**kwargs):
        with box.store.connect() as c:
            r=c.execute('SELECT id,document FROM creator_thread_contexts').fetchone()
            context=json.loads(r['document']);context['thread_id']='another-preparation'
            c.execute('UPDATE creator_thread_contexts SET document=? WHERE id=?',(json.dumps(context),r['id']))
        return original(*args,**kwargs)
    monkeypatch.setattr(executor,'mark_dispatch',changed)
    executor.tick()
    assert not any(method in ('turn/start','thread/queue/add') for _,method,_ in native.calls)
    assert row(box)['dispatch_started']==0
    with box.store.connect() as c:assert c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0]==0

