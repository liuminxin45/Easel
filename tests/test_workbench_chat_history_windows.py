"""TEMP-only bounded history and summary queries; no model transport."""
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import json
import sqlite3
from types import SimpleNamespace

import pytest

from easel_workbench.features.conversations.service import ChatService
from easel_workbench.application.chat_admission import ChatAdmission


class Store:
    def __init__(self,path):self.path=path;self.queries=[]
    @contextmanager
    def connect(self):
        c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;c.set_trace_callback(self.queries.append)
        try:
            with c:yield c
        finally:c.close()


@pytest.fixture
def history(tmp_path):
    store=Store(tmp_path/'fixture.sqlite');box=SimpleNamespace(root=tmp_path,store=store)
    service=ChatService(box,settings=SimpleNamespace())
    with store.connect() as c:
        for sid in ('one','two'):c.execute('INSERT INTO easel_chat_sessions VALUES(?,?)',(sid,json.dumps({'id':sid,'profile_id':'profile','revision':1})))
        for i in range(123):
            moment=datetime(2026,11,3,tzinfo=timezone.utc)+timedelta(seconds=i)
            # Cursors compare instants, not lexically mixed ISO offsets.
            at=moment.astimezone(timezone(timedelta(hours=8))).isoformat() if i%2 else moment.isoformat()
            document={'id':f'turn-{i:03}','session_id':'one','status':'completed','created_at':at,'updated_at':at,
                      'message':f'original-{i}','output':'long output '+('x'*1024),'runtime':'codex',
                      'work':{'work_id':'original-work','version_id':'exact-version'} if i in (0,122) else None}
            c.execute('INSERT INTO easel_chat_turns VALUES(?,?,?,?,?)',(document['id'],'one',document['id'],'signature',json.dumps(document)))
    admission=ChatAdmission(chat=service,business=SimpleNamespace(history=service.history))
    return service,admission,store


def test_sidebar_summary_never_materializes_history_or_turn_bodies(history,monkeypatch):
    service,_,store=history
    monkeypatch.setattr(service,'history',lambda *_a,**_k:pytest.fail('Summary rebuilt history'))
    monkeypatch.setattr(service,'get_turn',lambda *_a,**_k:pytest.fail('Summary read a turn body'))
    store.queries.clear();result=service.list_sessions(summaries=True)
    one=next(v for v in result['sessions'] if v['id']=='one')
    assert one['message_count']==246
    assert one['linked_works']==[{'work_id':'original-work','version_id':'exact-version'}]
    assert 'long output' not in json.dumps(result)
    assert len([q for q in store.queries if q.lstrip().upper().startswith('SELECT')])<=5


def test_cursor_windows_cover_exact_turns_once_and_keep_legacy_full_history(history):
    service,admission,_=history;cursor=None;seen=[]
    while True:
        page=admission.history('one',limit=50,before=cursor)
        messages=page['session']['messages'];ids=[m['turnId'] for m in messages if m['role']=='assistant']
        assert len(messages)<=100 and len(ids)<=50
        assert ids==sorted(ids)
        seen[0:0]=ids
        if not page['history_page']['has_more']:break
        cursor=page['history_page']['next_before'];assert cursor==ids[0]
    assert seen==[f'turn-{i:03}' for i in range(123)]
    assert len(service.history('one')['session']['messages'])==246


def test_pagination_cannot_use_another_session_cursor_or_unbounded_limit(history):
    service,admission,_=history
    for limit in (0,101,-1,True):
        with pytest.raises(ValueError):admission.history('one',limit=limit)
    with pytest.raises(ValueError,match='当前会话'):service.history_window('two',before='turn-020')
    assert admission.history('two',limit=50)['session']['messages']==[]


def test_pending_submissions_are_visible_once_and_respect_the_same_cursor(history):
    service,admission,store=history
    with store.connect() as c:
        for tid,at in [('turn-122','2026-11-03T00:02:02+00:00'),('pending','2026-11-03T00:03:00+00:00')]:
            doc={'id':tid,'session_id':'one','status':'requested','request':{'message':'unsent original'},'created_at':at,'updated_at':at}
            c.execute('INSERT INTO easel_chat_submissions VALUES(?,?,?,?)',(tid,'one','signature',json.dumps(doc)))
    latest=admission.history('one',limit=1)
    assert [m['id'] for m in latest['session']['messages']]==['pending-user','pending']
    earlier=admission.history('one',limit=2,before='pending')
    assert [m['id'] for m in earlier['session']['messages'] if m['role']=='assistant']==['turn-121','turn-122']
    assert next(x for x in service.list_sessions(summaries=True)['sessions'] if x['id']=='one')['message_count']==248
