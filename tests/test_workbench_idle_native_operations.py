"""TEMP SQLite receipts fence upgrades and recovery without rewriting evidence."""
from contextlib import nullcontext
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import pytest


ROOT=Path(__file__).resolve().parents[1]


@pytest.fixture
def idle_gate(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT/'scripts'))
    spec=importlib.util.spec_from_file_location('native_idle_gate',ROOT/'scripts/activate_workbench.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    old=tmp_path/'retired';root=tmp_path/'current'
    evidence=old/'evidence/simplify-workbench-20261029';evidence.mkdir(parents=True)
    refs={}
    for name in ('historical_unknown_audit','collection_historical_unknown_audit'):
        path=evidence/(name+'.json');path.write_text('{"retained":true}',encoding='utf-8')
        refs[name]={'path':str(path.relative_to(old)),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    (evidence/'activation-evidence.json').write_text(json.dumps(refs),encoding='utf-8')
    root.mkdir();database=root/'desk.sqlite'
    with sqlite3.connect(database) as c:c.execute('CREATE TABLE untouched(id TEXT PRIMARY KEY,raw TEXT)');c.execute('INSERT INTO untouched VALUES(?,?)',('history','original unknown input'))
    base=SimpleNamespace(exists_table=lambda c,name:c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() is not None)
    original={'busy':False,'retained_historical_unknown':[{'id':'original-unknown','replayed':False}]}
    automation=SimpleNamespace(busy_state=lambda *_:copy.deepcopy(original))
    monkeypatch.setattr(module,'ROOT',root);monkeypatch.setattr(module,'OLD',old)
    monkeypatch.setattr(module,'legacy',lambda:(base,automation))
    monkeypatch.setattr(module,'archived_reads',lambda *_:nullcontext())
    return module,database,original


def rows_digest(database):
    with sqlite3.connect(database) as c:
        rows={name:[tuple(r) for r in c.execute('SELECT * FROM "'+name+'" ORDER BY rowid')] for (name,) in c.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")}
    return hashlib.sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()


def install(database,values):
    with sqlite3.connect(database) as c:
        c.execute('CREATE TABLE easel_ui_operations(id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL)')
        for index,value in enumerate(values):
            c.execute('INSERT INTO easel_ui_operations VALUES(?,?,?)',(str(index),'frozen-signature',value))


@pytest.mark.parametrize('state',['unavailable','unknown','pending','requested','running','future-state',None,[],{}])
def test_native_nonterminal_receipt_blocks_without_mutating_any_row(idle_gate,state):
    module,database,original=idle_gate
    install(database,[json.dumps({'native_protocol':True,'state':state,'result':{'original':'untouched'}})])
    before=rows_digest(database)
    for _ in range(2):
        status=module.idle(database)
        assert status['busy'] is True
        assert status['additional'][0]['table']=='easel_ui_operations'
        assert status['additional'][0]['id']=='0'
        assert status['retained_historical_unknown']==original['retained_historical_unknown']
    assert rows_digest(database)==before


@pytest.mark.parametrize('state',['completed','rejected'])
def test_exact_terminal_native_receipt_allows_idle_and_retains_original(idle_gate,state):
    module,database,original=idle_gate
    install(database,[json.dumps({'native_protocol':True,'state':state,'result':{'id':'original-action'}})])
    before=rows_digest(database)
    assert module.idle(database)==original
    assert rows_digest(database)==before


@pytest.mark.parametrize('raw',['{invalid','[]','null','true','"text"','{"native_protocol":"true","state":"completed"}','{"native_protocol":1}','{"native_protocol":null}'])
def test_malformed_receipts_fail_closed_without_logging_payload(idle_gate,raw):
    module,database,_=idle_gate;install(database,[raw]);before=rows_digest(database)
    status=module.idle(database)
    assert status['busy'] and status['additional']==[{'table':'easel_ui_operations','id':'0','state':'invalid_receipt'}]
    assert rows_digest(database)==before


def test_pre_native_history_is_not_reinterpreted_or_changed(idle_gate):
    module,database,original=idle_gate
    install(database,[json.dumps({'id':'old-result','state':'legacy'}),json.dumps({'native_protocol':False,'state':'unavailable'})])
    before=rows_digest(database)
    assert module.idle(database)==original
    assert rows_digest(database)==before


def test_old_database_without_native_receipt_table_keeps_prior_gate(idle_gate):
    module,database,original=idle_gate;before=rows_digest(database)
    assert module.idle(database)==original
    assert rows_digest(database)==before


@pytest.mark.parametrize('state,busy', [('queued',True),('preparing',True),('admitting',True),('dispatched',False),('failed',False),('stopped',False)])
def test_durable_chat_preparation_fences_deployment_before_native_execution(idle_gate,state,busy):
    module,database,_=idle_gate
    with sqlite3.connect(database) as c:
        c.execute('CREATE TABLE easel_chat_submissions(id TEXT PRIMARY KEY,document TEXT NOT NULL)')
        c.execute('INSERT INTO easel_chat_submissions VALUES(?,?)',('received-original',json.dumps({'status':state,'request':{'message':'accurate original'}})))
    before=rows_digest(database)
    result=module.idle(database)
    assert result['busy'] is busy
    if busy:assert result['additional']==[{'table':'easel_chat_submissions','id':'received-original'}]
    assert rows_digest(database)==before


def test_pending_receipt_cannot_be_hidden_by_a_terminal_one(idle_gate):
    module,database,_=idle_gate
    install(database,[json.dumps({'native_protocol':True,'state':'completed'}),json.dumps({'native_protocol':True,'state':'unavailable'}),json.dumps({'native_protocol':True,'state':'rejected'})])
    before=rows_digest(database);status=module.idle(database)
    assert status['busy'] and status['additional']==[{'table':'easel_ui_operations','id':'1','state':'unavailable'}]
    assert rows_digest(database)==before
