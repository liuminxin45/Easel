"""TEMP-only admission proof, trace identity, read-only diagnosis and deploy gates."""
import json
from pathlib import Path
import sqlite3

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient


@pytest.fixture
def entry(tmp_path,monkeypatch):
    from easel_workbench.application import create_app
    from easel_workbench.runtime import toolbox_server,server_logging
    calls=[];events=[];app=FastAPI()
    @app.post('/api/chat/sessions')
    async def create(request:Request):
        calls.append(await request.json());return {'session':{'id':'TEMP-original'}}
    monkeypatch.setattr(toolbox_server,'create_app',lambda **_:app)
    monkeypatch.setattr(server_logging,'emit',lambda event,**fields:events.append((event,fields)))
    monkeypatch.setenv('EASEL_WORKBENCH_ADMISSION','1')
    actual=create_app(root=tmp_path)
    return TestClient(actual),calls,events,tmp_path


def test_switch_rejection_proves_no_handler_executed_and_shares_trace(entry):
    client,calls,events,root=entry
    headers={'X-Workbench-Operation-Protocol':'2','X-Operation-Id':'original-create'}
    result=client.post('/api/chat/sessions',json={'id':'original-create','action':'create'},headers=headers)
    assert result.status_code==503 and not calls
    body=result.json();assert body['operation_state']=='not_accepted' and body['operation_id']=='original-create'
    assert result.headers['X-Workbench-Operation-Protocol']=='2'
    assert result.headers['X-Desk-Trace']==body['trace_id']==events[-1][1]['trace_id']
    assert events[-1][0]=='admission_rejected' and events[-1][1]['phase']=='not_accepted'
    state=root/'.local/workbench-deployment/admission.json';state.write_text(json.dumps({'workers':True}),encoding='utf-8')
    again=client.post('/api/chat/sessions',json={'id':'original-create','action':'create'},headers=headers)
    assert again.status_code==200 and len(calls)==1
    assert again.headers['X-Desk-Trace']!=result.headers['X-Desk-Trace']


def test_unversioned_or_ambiguous_identity_does_not_claim_a_bound_proof(entry):
    client,calls,events,root=entry
    for headers in ({'X-Operation-Id':'legacy'}, {'X-Workbench-Operation-Protocol':'2','X-Operation-Id':'invalid identity'}):
        result=client.post('/api/chat/sessions',json={'action':'create'},headers=headers)
        assert result.status_code==503 and 'operation_state' not in result.json()
        assert 'X-Workbench-Operation-Protocol' not in result.headers
    assert not calls and all(event[0]=='admission_rejected' for event in events)


@pytest.mark.parametrize('state,age,projection,degraded',[
    ('accepted',20,None,False),('running',301,None,True),('completed',999,None,False),
    ('sealed_not_accepted',999,None,False),('rejected',999,None,False),('completed',10,'PermissionError',True),('invalid',10,None,True),
])
def test_session_progress_diagnosis_is_content_free_and_does_not_mutate(tmp_path,state,age,projection,degraded):
    import datetime as dt
    from easel_workbench.business_health import session_creation_health
    file=tmp_path/'data/desk.sqlite';file.parent.mkdir()
    when=dt.datetime.fromtimestamp(1000-age,dt.timezone.utc).isoformat()
    with sqlite3.connect(file) as c:
        c.execute('CREATE TABLE easel_chat_creation_intents(id,state,created_at,projection_error,request)')
        c.execute('INSERT INTO easel_chat_creation_intents VALUES(?,?,?,?,?)',('private-id',state,when,projection,'secret-body'))
    before=file.read_bytes();result=session_creation_health(tmp_path,1000)
    assert (result['status']=='degraded') is degraded
    assert 'secret-body' not in json.dumps(result) and 'private-id' not in json.dumps(result)
    assert file.read_bytes()==before


@pytest.mark.parametrize('state,busy',[('accepted',True),('running',True),('invalid',True),('completed',False),('rejected',False),('sealed_not_accepted',False)])
def test_deployment_fences_unfinished_or_unrecognized_metadata_creates(tmp_path,monkeypatch,state,busy):
    import importlib.util
    from types import SimpleNamespace
    project=Path(__file__).resolve().parents[1];monkeypatch.syspath_prepend(str(project/'scripts'))
    spec=importlib.util.spec_from_file_location('session_idle_guard',project/'scripts/activate_workbench.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    old=tmp_path/'old';directory=old/'evidence/simplify-workbench-20261029';directory.mkdir(parents=True)
    module.atomic(directory/'audit.json',{});ref={'path':'evidence/simplify-workbench-20261029/audit.json','sha256':module.sha(directory/'audit.json')}
    module.atomic(directory/'activation-evidence.json',{'historical_unknown_audit':ref,'collection_historical_unknown_audit':ref})
    database=old/'data/desk.sqlite';database.parent.mkdir()
    with sqlite3.connect(database) as c:
        c.execute('CREATE TABLE easel_chat_creation_intents(id,state)');c.execute('INSERT INTO easel_chat_creation_intents VALUES(?,?)',('TEMP-create',state))
    monkeypatch.setattr(module,'OLD',old)
    monkeypatch.setattr(module,'legacy',lambda:(SimpleNamespace(exists_table=lambda c,t:c.execute('SELECT 1 FROM sqlite_master WHERE name=?',(t,)).fetchone() is not None),SimpleNamespace(busy_state=lambda *_:{'busy':False,'retained_collection_unknown':[]})))
    result=module.idle(database);assert result['busy'] is busy
    if busy:assert result['additional']==[{'table':'easel_chat_creation_intents','id':'TEMP-create','state':state}]


def test_rollback_cannot_remove_the_sealed_command_guard(tmp_path,monkeypatch):
    import importlib.util
    project=Path(__file__).resolve().parents[1];monkeypatch.syspath_prepend(str(project/'scripts'))
    spec=importlib.util.spec_from_file_location('session_rollback_guard',project/'scripts/upgrade_workbench_runtime.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    database=tmp_path/'data/desk.sqlite';database.parent.mkdir()
    with sqlite3.connect(database) as c:
        c.execute('CREATE TABLE easel_chat_creation_intents(id,state)');c.execute('INSERT INTO easel_chat_creation_intents VALUES(?,?)',('old-id','sealed_not_accepted'))
    with pytest.raises(ValueError,match='sealed session'):module.validate_session_creation_compat(tmp_path,{})
    module.validate_session_creation_compat(tmp_path,{'session_creation_protocol':2})


def test_client_diagnostic_phase_never_accepts_original_text_or_logs_raw_id(monkeypatch):
    from easel_workbench.diagnostics.client_operations import observe
    from easel_workbench.runtime import server_logging
    events=[];monkeypatch.setattr(server_logging,'emit',lambda event,**fields:events.append((event,fields)))
    value={'operation_id':'private-operation','flow_id':'private-flow','phase':'checking','elapsed_ms':123,'client':'webview'}
    assert observe(value,trace='f'*16)=={'ok':True}
    assert events[0][0]=='client_operation_phase'
    assert 'private-operation' not in json.dumps(events) and 'private-flow' not in json.dumps(events)
    with pytest.raises(ValueError):observe({**value,'text':'private draft'},trace='f'*16)
    with pytest.raises(ValueError):observe({**value,'phase':'private arbitrary text'},trace='f'*16)
