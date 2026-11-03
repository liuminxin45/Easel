"""Review previews reuse the production contract without copying the business DB."""
import contextlib
import copy
import hashlib
import importlib.util
import sqlite3
import tempfile
from pathlib import Path

import pytest

from easel_workbench.runtime import task_runtime
from easel_workbench.runtime.desk import Connection
from easel_workbench.runtime.learning_execution import attach

_spec=importlib.util.spec_from_file_location('plan_preview_fixture',Path(__file__).with_name('test_workbench_chat_business.py'))
_fixture=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_fixture)
business=_fixture.business


def inputs(business, image=False):
    attach(business.box)
    # Persisted historical contracts can be inspected without a live plan API.
    snapshot=business.creator.resolve('oil-pig','poster',[{'id':sid} for sid in ('content-writing','image-production','delivery-review')])
    if image:
        raw=b'frozen required image fixture';sha=hashlib.sha256(raw).hexdigest()
        with business.store.connect() as c:
            c.execute('INSERT OR IGNORE INTO creator_skill_blobs VALUES(?,?)',(sha,raw))
        snapshot['profile'].setdefault('asset_refs',[]).append({
            'path':'reference/test.png','sha256':sha,'required':True,'available':True,'label':'exact image'})
    return snapshot,{'work_id':'preview-work','version_id':'preview-version','format':'poster'},'保持原文，仅调整排版'


def reference_clone(business, initial, message):
    # Reproduce the former isolation path only as a comparison oracle in TEMP.
    # The application is forbidden from invoking backup in the separate guard.
    with tempfile.TemporaryDirectory() as folder:
        database=Path(folder)/'preview.sqlite'
        with business.store.connect() as source,contextlib.closing(sqlite3.connect(database)) as target:
            sqlite3.Connection.backup(source,target)
        store=copy.copy(business.store);store.path=database
        box=copy.copy(business.box);box.store=store;box.creative_preview=True
        box.creator=copy.copy(business.creator);box.creator.store=store;box.creator.box=box
        box.learning=copy.copy(box.learning);box.learning.store=store;box.learning.box=box
        result=copy.deepcopy(initial)
        with store.connect() as c:
            task_runtime.attach_profile_contract(box,c,result,'preview-version',request_text=message)
    return result


@pytest.mark.parametrize('image',[False,True])
@pytest.mark.parametrize('has_parent',[False,True])
def test_preview_deep_matches_old_clone_and_does_no_writes_or_backups(business,monkeypatch,image,has_parent):
    b=business;snapshot,work,message=inputs(b,image)
    parent={'annotations':[{'id':'note-one','dimension':'style','note':'保留原始反馈'}],
            'raw_feedback':[{'id':'feedback-one','text':'准确版本原话'}],
            'creation_options':{'keep_text':True}} if has_parent else None
    captured=[];builder=task_runtime.attach_profile_contract
    def observe(box,c,document,job_id,request_text=None):
        assert c.execute('PRAGMA query_only').fetchone()[0]==1
        assert box.learning is None and box.creative_preview
        captured.append(copy.deepcopy(document))
        return builder(box,c,document,job_id,request_text=request_text)
    with monkeypatch.context() as patch:
        patch.setattr(task_runtime,'attach_profile_contract',observe)
        actual=b._review_document(snapshot,work,message,parent)
    expected=reference_clone(b,captured[0],message)
    assert actual==expected
    traces=[];connect=b.store.connect
    @contextlib.contextmanager
    def readonly_connection():
        with connect() as c:
            c.set_trace_callback(traces.append)
            yield c
    with monkeypatch.context() as patch:
        patch.setattr(b.store,'connect',readonly_connection)
        patch.setattr(Connection,'backup',lambda *args,**kwargs:pytest.fail('whole DB copied during preview'))
        patch.setattr(b.box.learning,'_put',lambda *args,**kwargs:pytest.fail('preview persisted a learning run'))
        again=b._review_document(snapshot,work,message,parent)
    assert again==expected
    assert all(sql.lstrip().split()[0].upper() in {'SELECT','PRAGMA'} for sql in traces)
    with b.store.connect() as c:
        assert c.execute('SELECT count(*) FROM learning_runs WHERE id=?',('preview-version',)).fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0]==0
    assert not (b.root/'data/creator-inputs').exists()


def test_unexpected_preview_write_is_rejected_by_sqlite(business,monkeypatch):
    snapshot,work,message=inputs(business)
    def accidental_write(box,c,*args,**kwargs):
        c.execute("INSERT INTO toolbox_meta VALUES('preview-must-not-write','no')")
    monkeypatch.setattr(task_runtime,'attach_profile_contract',accidental_write)
    with pytest.raises(sqlite3.OperationalError,match='readonly'):
        business._review_document(snapshot,work,message)
    with business.store.connect() as c:
        assert c.execute("SELECT 1 FROM toolbox_meta WHERE key='preview-must-not-write'").fetchone() is None


def test_real_acceptance_builder_still_persists_exact_learning_contract(business,monkeypatch):
    b=business;snapshot,work,message=inputs(b)
    captured=[];builder=task_runtime.attach_profile_contract
    def observe(box,c,document,*args,**kwargs):
        captured.append(copy.deepcopy(document));return builder(box,c,document,*args,**kwargs)
    with monkeypatch.context() as patch:
        patch.setattr(task_runtime,'attach_profile_contract',observe)
        preview=b._review_document(snapshot,work,message)
    assert b.box.learning is not None and not getattr(b.box,'creative_preview',False)
    accepted=copy.deepcopy(captured[0])
    with b.store.connect() as c:
        builder(b.box,c,accepted,work['version_id'],request_text=message)
        run=b.box.learning.read_run(c,work['version_id'])
        assert run and run['snapshot']==accepted['learning_snapshot']
        assert run['status']=='frozen' and run['quality']=={'status':'pending','checked':False}
    assert accepted==preview
