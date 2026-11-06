import json
import sqlite3
from types import SimpleNamespace

import pytest

from easel_workbench.runtime.news_overviews import Overviews, fingerprint, trend_titles,validate
from easel_workbench.runtime.desk import Store
from easel_workbench.runtime.native_api import NativeApi


@pytest.fixture
def setup(tmp_path,monkeypatch):
    store=Store(tmp_path/'data/desk.sqlite')
    monkeypatch.setattr(store,'sources',lambda **_: {k:{'builtin':True,'kind':'news'} for k in ('hacker-news','product-hunt')})
    service=Overviews(store,tmp_path)
    rows=[{'id':'hn','title':'A new open model','body':'Source news','url':'https://example.test/hn','source_job':'hacker-news','collected_at':'2026-11-03T01:00:00Z'},
          {'id':'ph','title':'Widget','body':'A tool for organizing research notes','url':'https://example.test/ph','source_job':'product-hunt','collected_at':'2026-11-03T01:00:00Z'}]
    return tmp_path,store,service,rows


def save(service,row,title,status='ready',hash_=None):
    with service.connect() as c:
        c.execute('INSERT OR REPLACE INTO overviews VALUES(?,?,?,?,NULL,1,0,?)',(row['id'],hash_ or fingerprint(row),status,title,'now'))


def test_both_native_lists_use_exact_chinese_projection_without_mutating_sources(setup):
    root,store,service,rows=setup
    titles=['研究团队发布用于文本处理的新开放模型。','Widget 帮助用户整理研究笔记和相关资料。']
    for row,title in zip(rows,titles):save(service,row,title)
    before=(root/'data/news-overviews.sqlite').read_bytes()
    api=NativeApi.__new__(NativeApi);api.root=root;api.store=SimpleNamespace(collected_day=lambda source,day:{'items':[r for r in rows if r['source_job']==source]})
    api._collection=lambda:SimpleNamespace(definitions=lambda:{k:{'enabled':True,'label':k} for k in ('hacker-news','product-hunt')},status=lambda:{'sources':[]})
    for query in ({},{'platforms':'hacker-news,product-hunt'}):
        result=api._trends(SimpleNamespace(query_params=query))
        assert [g['items'][0]['title'] for g in result['trends']]==titles
        assert [g['items'][0]['id'] for g in result['trends']]==['hn','ph']
        assert result['warnings']==[]
    assert rows[1]['title']=='Widget' and rows[0]['title']=='A new open model'
    assert (root/'data/news-overviews.sqlite').read_bytes()==before


@pytest.mark.parametrize('state,title,hash_',[
    ('pending',None,None),('running',None,None),('error',None,None),
    ('ready','Widget',None),('ready','An English sentence.',None),
    ('ready','Widget 帮助用户整理研究笔记和相关资料。','outdated'),
])
def test_unready_invalid_or_stale_title_is_hidden(setup,state,title,hash_):
    root,store,service,rows=setup
    save(service,rows[1],title,state,hash_)
    assert trend_titles(rows,root)==[]


def test_missing_projection_database_is_empty_without_creating_file(tmp_path):
    assert trend_titles([{'id':'a'}],tmp_path)==[]
    assert not (tmp_path/'data/news-overviews.sqlite').exists()


def test_changed_original_invalidates_previous_chinese_sentence(setup):
    root,store,service,rows=setup
    save(service,rows[1],'Widget 帮助用户整理研究笔记和相关资料。')
    assert len(trend_titles(rows,root))==1
    assert trend_titles([{**rows[1],'body':'Changed source material'}],root)==[]


def test_question_mark_inside_quoted_original_title_is_one_sentence():
    value='作者以“WTF Ubuntu?”为题讨论 Ubuntu。'
    assert validate(value)==value
    with pytest.raises(ValueError):validate('这是第一句中文内容。这里是第二句中文内容。')


@pytest.mark.parametrize('call_state',[None,'unknown','failed','completed'])
def test_only_proven_unstarted_legacy_contract_errors_can_be_reopened(setup,monkeypatch,call_state):
    root,store,service,rows=setup
    monkeypatch.setattr(store,'collected_day',lambda source,day:{'items':[r for r in rows if r['source_job']==source]})
    for row in rows:
        save(service,row,None,'error')
    with service.connect() as c:
        c.execute("UPDATE overviews SET error='中文概述未完成（ValueError），原始资料已保留',attempts=3")
    with store.connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS creator_model_calls(id TEXT PRIMARY KEY,document TEXT)')
        if call_state:
            c.execute('INSERT INTO creator_model_calls VALUES(?,?)',('original',json.dumps({'task':'news_enhancement','status':call_state,'input':[rows[0]]})))
    preview=service.reopen_unstarted(sources=['hacker-news','product-hunt'],day='2026-11-03')
    assert preview['eligible']==(['ph'] if call_state else ['hn','ph'])
    assert preview['held']==(['hn'] if call_state else [])
    with service.connect() as c:assert c.execute("SELECT count(*) FROM overviews WHERE status='error'").fetchone()[0]==2
    result=service.reopen_unstarted(sources=['hacker-news','product-hunt'],day='2026-11-03',apply=True)
    assert result['model_calls']==0
    with service.connect() as c:
        assert c.execute("SELECT count(*) FROM overviews WHERE status='pending' AND attempts=0").fetchone()[0]==len(preview['eligible'])


@pytest.mark.parametrize('status,tampered', [('completed',False),('unknown',False),('completed',True)])
def test_reconcile_checks_original_completed_receipt_and_exact_inputs(setup,status,tampered,monkeypatch):
    import hashlib
    root,store,service,rows=setup
    for row in rows:save(service,row,None,'error')
    monkeypatch.setattr(store,'collected_day',lambda source,day:{'items':[r for r in rows if r['source_job']==source]})
    prompt='exact original prompt'
    inputs=[{k:r[k] for k in ('id','title','body','url','source_job')} for r in rows]
    with store.connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS creator_model_calls(id TEXT PRIMARY KEY,task_id TEXT,document TEXT,updated_at TEXT)')
        c.execute('INSERT INTO creator_model_calls VALUES(?,?,?,?)',('call',None,json.dumps({'task':'news_enhancement','prompt':prompt,'input':inputs}),'now'))
    raw=json.dumps({'items':[{'id':r['id'],'summary':'这个产品可以帮助用户整理研究笔记和相关资料。'} for r in rows]})
    receipt={'id':'receipt','status':status,'completion_received':True,'prompt_sha256':hashlib.sha256(prompt.encode()).hexdigest(),'model_output_text':raw,'model_output_sha256':'bad' if tampered else hashlib.sha256(raw.encode()).hexdigest()}
    folder=root/'data/readonly-receipts';folder.mkdir();path=folder/'receipt.json';path.write_text(json.dumps(receipt),encoding='utf-8')
    if status!='completed' or tampered:
        with pytest.raises(ValueError):service.reconcile_completed(path,sources=['hacker-news','product-hunt'],day='2026-11-03')
        assert trend_titles(rows,root)==[]
    else:
        assert service.reconcile_completed(path,sources=['hacker-news','product-hunt'],day='2026-11-03')=={'recovered':2,'completed_invalid':0,'model_calls':0}
        assert len(trend_titles(rows,root))==2
        assert service.reconcile_completed(path,sources=['hacker-news','product-hunt'],day='2026-11-03')['recovered']==0
