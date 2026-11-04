"""TEMP-only closed-unknown review. No network, model, runtime or DB mutations."""
import copy
import contextlib
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import time

import pytest

spec=importlib.util.spec_from_file_location('native_retention',Path(__file__).resolve().parents[1]/'scripts/native_chat_receipt_retention.py')
retention=importlib.util.module_from_spec(spec);spec.loader.exec_module(retention)
sha=lambda raw:hashlib.sha256(raw).hexdigest()


@pytest.fixture
def evidence(tmp_path):
    root=tmp_path;tid='unknown-one';sid='session-one';now=time.time()
    created=now-retention.TIMEOUT_CHAT-retention.GRACE_SECONDS-100
    iso=lambda stamp:dt.datetime.fromtimestamp(stamp,dt.timezone.utc).isoformat()
    turn={'id':tid,'session_id':sid,'session_key':sid,'status':'unknown','runtime':'codex','native_id':'',
          'native_turn_id':None,'work':None,'hook_status':'completed','output':'','cwd':str(root),
          'created_at':iso(created),'message':'Exact user input','actual_prompt':'Exact full native prompt'}
    turn['actual_prompt_sha256']=sha(turn['actual_prompt'].encode())
    raw=json.dumps(turn,ensure_ascii=False,indent=2)
    session={'id':sid,'runtime':'codex','pendingTurnId':tid,'pendingSubmissionId':None}
    session_raw=json.dumps(session)
    (root/'data').mkdir();database=root/'data/desk.sqlite'
    with contextlib.closing(sqlite3.connect(database)) as c, c:
        c.execute('CREATE TABLE easel_chat_turns(id TEXT,document TEXT)')
        c.execute('CREATE TABLE easel_chat_sessions(id TEXT,document TEXT)')
        c.execute('INSERT INTO easel_chat_turns VALUES(?,?)',(tid,raw))
        c.execute('INSERT INTO easel_chat_sessions VALUES(?,?)',(sid,session_raw))
    binding={'runtime':'codex','native_id':'original-thread'}
    binding_path=retention.binding_path(root/'outputs/_sessions',sid);binding_path.parent.mkdir(parents=True)
    binding_path.write_text(json.dumps(binding))
    folder=root/'.local/review';folder.mkdir(parents=True)
    proof={'read_only':True,'new_model_turns':0,'method':'thread/read','thread_id':binding['native_id'],
           'cwd':str(root),'binding':binding,'thread_status':{'type':'notLoaded'},'turn_document_sha256':sha(raw.encode()),
           'turns':[{'id':'old-completed','status':'completed','startedAt':created-300,'completedAt':created-100,
                     'input_sha256':sha(b'Original older request'),'matches_exact_input':False,'contains_exact_input':False}]}
    proof_path=folder/'proof.json';proof_path.write_text(json.dumps(proof))
    events=[{'id':1,'event':'activity','data':'wrapper finished without a native receipt'}, {'id':2,'event':'done','data':{'sessionKey':sid}}]
    events_raw=('\n'.join(json.dumps(event) for event in events)+'\n').encode()
    event_path=folder/'events.jsonl';event_path.write_bytes(events_raw)
    live=root/'outputs/_sessions/jobs'/f'{tid}.jsonl';live.parent.mkdir();live.write_bytes(events_raw)
    audit={'schema_version':1,'kind':retention.KIND,'turn_id':tid,'session_id':sid,'turn_document_sha256':sha(raw.encode()),
           'session_document_sha256':sha(session_raw.encode()),'binding':binding,
           'events':{'path':event_path.relative_to(root).as_posix(),'sha256':sha(events_raw)},
           'native_proof':{'path':proof_path.relative_to(root).as_posix(),'sha256':sha(proof_path.read_bytes())},'retained_at':iso(now-1)}
    audit_path=root/'.local/workbench-deployment/native-chat-retentions'/f'{tid}.json';audit_path.parent.mkdir(parents=True)
    def save_audit():audit_path.write_text(json.dumps(audit))
    save_audit()
    def save_proof():
        proof_path.write_text(json.dumps(proof));audit['native_proof']['sha256']=sha(proof_path.read_bytes());save_audit()
    def save_turn():
        nonlocal raw
        raw=json.dumps(turn,ensure_ascii=False,indent=2)
        with contextlib.closing(sqlite3.connect(database)) as c, c:c.execute('UPDATE easel_chat_turns SET document=?',(raw,))
        audit['turn_document_sha256']=sha(raw.encode());proof['turn_document_sha256']=audit['turn_document_sha256'];save_proof()
    def save_events():
        data=('\n'.join(json.dumps(event) for event in events)+'\n').encode();event_path.write_bytes(data);live.write_bytes(data)
        audit['events']['sha256']=sha(data);save_audit()
    return locals()


def retained(e):return retention.retained(e['root'],e['tid'],e['raw'])


def test_exact_individual_audit_retains_unknown_without_modifying_any_file(evidence):
    e=evidence;before={p:p.read_bytes() for p in e['root'].rglob('*') if p.is_file()}
    result=retained(e)
    assert result and result['retained_unknown'] and result['replayed'] is False
    assert result['audit_sha256']==sha(e['audit_path'].read_bytes())
    assert all(path.read_bytes()==raw for path,raw in before.items())
    with contextlib.closing(sqlite3.connect(e['database'])) as c, c:assert json.loads(c.execute('SELECT document FROM easel_chat_turns').fetchone()[0])['status']=='unknown'


@pytest.mark.parametrize('which',['audit_path','proof_path','event_path','live','binding_path','database'])
def test_missing_evidence_fails_closed(evidence,which):
    evidence[which].unlink();assert retained(evidence) is None


@pytest.mark.parametrize('which',['proof_path','event_path','live','binding_path'])
def test_changed_evidence_bytes_fail_closed(evidence,which):
    with evidence[which].open('ab') as stream:stream.write(b'changed')
    assert retained(evidence) is None


@pytest.mark.parametrize('change',[{'status':'running'},{'native_id':'real-native'},{'native_turn_id':'real-turn'},
    {'output':'actual output'},{'work':{}},{'hook_status':'pending'},{'start_hook_status':'pending'},
    {'execution_identity':{'id':'actual'}},{'cwd':''},{'pending_hooks':['task']},
    {'created_at':dt.datetime.now(dt.timezone.utc).isoformat()}])
def test_even_rehashed_review_cannot_retain_active_or_executed_turn(evidence,change):
    e=evidence;e['turn'].update(change);e['save_turn']()
    # save_turn updates the fixture closure's exact raw document.
    raw=json.loads(e['audit_path'].read_text())['turn_document_sha256']
    with contextlib.closing(sqlite3.connect(e['database'])) as c, c:current=c.execute('SELECT document FROM easel_chat_turns').fetchone()[0]
    assert sha(current.encode())==raw
    assert retention.retained(e['root'],e['tid'],current) is None


@pytest.mark.parametrize('change',[{'status':'running'},{'completedAt':time.time()},
    {'matches_exact_input':True},{'contains_exact_input':True},{'completedAt':None}])
def test_native_nonterminal_later_or_matching_input_cannot_be_retained(evidence,change):
    e=evidence;e['proof']['turns'][0].update(change);e['save_proof']();assert retained(e) is None


@pytest.mark.parametrize('change',[{'read_only':False},{'new_model_turns':1},{'method':'turn/start'},
    {'cwd':''},{'binding':{'runtime':'codex','native_id':'different'}},{'thread_status':{'type':'active'}}])
def test_proof_must_be_readonly_same_binding_and_cwd(evidence,change):
    e=evidence;e['proof'].update(change);e['save_proof']();assert retained(e) is None


@pytest.mark.parametrize('kind',['wrong-session','token','missing-done'])
def test_forged_done_or_output_event_cannot_claim_closed_wrapper(evidence,kind):
    e=evidence
    if kind=='wrong-session':e['events'][-1]['data']['sessionKey']='other'
    elif kind=='token':e['events'][0]['event']='token'
    else:e['events'][-1]['event']='activity'
    e['save_events']();assert retained(e) is None


def test_session_document_change_and_bare_allowlist_fail_closed(evidence):
    e=evidence
    with contextlib.closing(sqlite3.connect(e['database'])) as c, c:c.execute('UPDATE easel_chat_sessions SET document=?',(json.dumps(e['session']|{'pendingTurnId':'other'}),))
    assert retained(e) is None
    e['audit_path'].write_text(json.dumps({'turn_id':e['tid']}));assert retained(e) is None


def test_evidence_paths_are_closed_even_when_outside_bytes_match(evidence,tmp_path):
    e=evidence;original=copy.deepcopy(e['audit']['native_proof'])
    for path in (str(e['proof_path'].resolve()),'.local/../../outside.json'):
        e['audit']['native_proof']={**original,'path':path};e['save_audit']();assert retained(e) is None
