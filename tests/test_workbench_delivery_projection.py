"""A persisted completion receipt must resume its projection, never production."""
import sqlite3
from types import SimpleNamespace

import pytest

from easel_workbench.runtime.desk import Store
from easel_workbench.runtime.toolbox_store import Toolbox
from easel_workbench.runtime.production_delivery import record_delivery


@pytest.fixture
def box(tmp_path):
    box=Toolbox(Store(tmp_path/'data/desk.sqlite'),tmp_path)
    with box.store.connect() as c:
        c.execute('INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)',('work-one',None,'Exact work','material','old','old'))
        c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,signature,status,created_at,turn_id) VALUES(?,?,?,?,?,?,?,?)',
                  ('version-one','work-one','create','frozen input','signature','running','old','native-one'))
        c.execute('CREATE TABLE projection_probe(job_id TEXT PRIMARY KEY)')
    return box


def test_late_sqlite_failure_resumes_missing_projection_without_recapturing(box,monkeypatch):
    from easel_workbench.runtime import production_outcome
    monkeypatch.setattr(production_outcome,'assess',lambda *args,**kwargs:{'status':'completed','available_scopes':['images','copy']})
    calls=[];captured=[]
    def enqueue(c,jid):
        calls.append(jid)
        if len(calls)==1:raise sqlite3.OperationalError('database is locked')
        c.execute('INSERT OR IGNORE INTO projection_probe VALUES(?)',(jid,))
    box.learning=SimpleNamespace(enqueue_review=enqueue)
    def deliver():
        return record_delivery(box,'version-one','exact final reply','native-one',
                               receiver=lambda *args,**kwargs:captured.append(True),record_execution=False)
    with pytest.raises(sqlite3.OperationalError):deliver()
    with box.store.connect() as c:
        assert c.execute('SELECT status FROM toolbox_jobs').fetchone()[0]=='completed'
        assert c.execute('SELECT count(*) FROM projection_probe').fetchone()[0]==0
    second=deliver()
    assert second['status']=='completed' and second['reused_receipt'] is True
    assert calls==['version-one','version-one'] and captured==[True]
    deliver()
    with box.store.connect() as c:
        assert c.execute('SELECT count(*) FROM projection_probe').fetchone()[0]==1
    assert captured==[True]


@pytest.mark.parametrize('reply,turn',[('another reply','native-one'),('exact final reply','other-native')])
def test_different_reply_or_native_identity_cannot_resume_projection(box,reply,turn):
    with box.store.connect() as c:
        c.execute("UPDATE toolbox_jobs SET status='completed',reply='exact final reply'")
    box.learning=SimpleNamespace(enqueue_review=lambda *args:pytest.fail('wrong receipt projected'))
    with pytest.raises(ValueError):
        record_delivery(box,'version-one',reply,turn,record_execution=False)


def test_explicit_no_review_projection_stays_no_review_even_on_completed_reuse(box,monkeypatch):
    from easel_workbench.runtime import production_outcome
    monkeypatch.setattr(production_outcome,'assess',lambda *args,**kwargs:{'status':'completed','available_scopes':['images']})
    box.learning=SimpleNamespace(enqueue_review=lambda *args:pytest.fail('no independent review was authorized'))
    for enqueue_review in [False,False,True]:
        record_delivery(box,'version-one','exact final reply','native-one',
                        receiver=lambda *args,**kwargs:None,record_execution=False,enqueue_review=enqueue_review)
    with box.store.connect() as c:
        assert c.execute('SELECT count(*) FROM toolbox_meta WHERE key=?',('delivery-projection-v1:version-one',)).fetchone()[0]==1
        assert c.execute('SELECT count(*) FROM projection_probe').fetchone()[0]==0


def test_unknown_receipt_never_resumes_projection_or_starts_review(box):
    box.learning=SimpleNamespace(enqueue_review=lambda *args:pytest.fail('unknown receipt projected'))
    answer=record_delivery(box,'version-one','','native-one',record_execution=False)
    assert answer['status']=='uncertain'
    with box.store.connect() as c:
        assert c.execute('SELECT count(*) FROM notification_events WHERE event_key=?',('toolbox:version-one',)).fetchone()[0]==0


def test_explicit_file_reconciliation_can_advance_error_projection_to_completed(box,monkeypatch):
    from easel_workbench.runtime import production_outcome
    outcomes=iter([{'status':'error','message':'missing original','available_scopes':[]},
                   {'status':'completed','available_scopes':['images','copy']}])
    monkeypatch.setattr(production_outcome,'assess',lambda *args,**kwargs:next(outcomes))
    calls=[]
    box.learning=SimpleNamespace(enqueue_review=lambda c,jid:calls.append(jid))
    for expected in ['error','completed']:
        result=record_delivery(box,'version-one','exact final reply','native-one',
                               receiver=lambda *args,**kwargs:None,record_execution=False)
        assert result['status']==expected
    assert calls==['version-one']


def test_legacy_completed_receipt_without_marker_cannot_infer_review_authority(box):
    with box.store.connect() as c:
        c.execute("UPDATE toolbox_jobs SET status='completed',reply='exact final reply'")
    box.learning=SimpleNamespace(enqueue_review=lambda *args:pytest.fail('legacy policy cannot be inferred'))
    result=record_delivery(box,'version-one','exact final reply','native-one',
                           receiver=lambda *args,**kwargs:pytest.fail('legacy production recaptured'),
                           enqueue_review=True,record_execution=False)
    assert result['reused_receipt'] is True
    with box.store.connect() as c:
        assert c.execute('SELECT count(*) FROM toolbox_meta WHERE key=?',('delivery-projection-v1:version-one',)).fetchone()[0]==0
