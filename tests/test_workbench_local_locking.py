"""Local archive inference must never monopolize the shared business writer."""
import json
import sqlite3
import threading
from pathlib import Path

import pytest

from easel_workbench.runtime.desk import Store
from easel_workbench.runtime.toolbox_store import Toolbox
from easel_workbench.runtime.local_operations import LocalOperations, pack


@pytest.fixture
def worker(tmp_path):
    box = Toolbox(Store(tmp_path / 'data/desk.sqlite'), tmp_path)
    worker = LocalOperations(box, project=tmp_path / 'project')
    with box.store.connect() as c:
        c.execute('CREATE TABLE probe(value TEXT)')
    return worker


def enqueue(worker, wid='work-one', key='task-one', kind='record'):
    task = dict(id=key, work_id=wid, job_id='decision-' + key, kind=kind,
                status='queued', revision=1, created_at='2026-11-03', updated_at='2026-11-03')
    with worker.store.connect() as c:
        c.execute('INSERT INTO toolbox_local_tasks VALUES(?,?,?,?,?,?,?,?,?)',
                  (key, wid, task['job_id'], kind, task['status'], pack(task), 1,
                   task['created_at'], task['updated_at']))
    return task


def test_real_slow_catalog_scan_does_not_block_other_business_writes(worker, monkeypatch):
    enqueue(worker)
    folder = worker.project / '内容/历史'; folder.mkdir(parents=True)
    catalog = folder / '内容档案.md'; catalog.write_text('unrelated legacy work', encoding='utf-8')
    entered = threading.Event(); release = threading.Event(); errors = []
    read_text = Path.read_text
    def slow_read(path, *args, **kwargs):
        if path == catalog:
            entered.set()
            assert release.wait(5), 'scan was not released'
        return read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', slow_read)
    def scan():
        try: worker._process_one()
        except BaseException as error: errors.append(error)
    thread = threading.Thread(target=scan); thread.start()
    try:
        assert entered.wait(3), errors
        # This is the collector/feedback/publisher admission boundary: a real
        # independent SQLite writer succeeds while filesystem I/O is suspended.
        with sqlite3.connect(worker.store.path, timeout=.2) as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('INSERT INTO probe VALUES(?)', ('concurrent business write',))
    finally:
        release.set(); thread.join(5)
    assert not thread.is_alive() and not errors
    with worker.store.connect() as c:
        assert c.execute('SELECT count(*) FROM probe').fetchone()[0] == 1
        assert c.execute('SELECT status FROM toolbox_local_tasks').fetchone()[0] == 'waiting_binding'


@pytest.mark.parametrize('changed', ['task', 'binding', 'completion', 'artifact'])
def test_inference_snapshot_change_cannot_claim_or_overwrite_binding(worker, monkeypatch, changed):
    enqueue(worker)
    def infer(c, wid, **kwargs):
        assert not c.in_transaction
        with worker.store.connect() as other:
            if changed == 'task':
                row = json.loads(other.execute('SELECT document FROM toolbox_local_tasks').fetchone()[0])
                worker._put(other, row, status='cancelled')
            elif changed == 'binding':
                worker._save_binding(other, wid, '内容/owner-choice', {'kind': 'explicit_owner_binding'})
            elif changed == 'completion':
                other.execute('INSERT INTO toolbox_completions VALUES(?,?,?,?,?,?)',
                              ('decision-one', wid, 'version-one', '{}', 'now', 'now'))
            else:
                other.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,signature,status,created_at) VALUES(?,?,?,?,?,?,?)',
                              ('version-one', wid, 'create', '', 'sig', 'completed', 'now'))
                other.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)',
                              ('artifact-one', 'version-one', 'new.png', '/new.png', 'image/png'))
        return {'work_id': wid, 'relative_path': '内容/stale-choice',
                'evidence': {'kind': 'exact_work_version_and_bytes'}, '_inferred': True}
    monkeypatch.setattr(worker, '_infer', infer)
    monkeypatch.setattr(worker, '_record', lambda *args: pytest.fail('stale inference executed'))
    assert worker._process_one() is None
    with worker.store.connect() as c:
        binding = worker._binding(c, 'work-one')
        if changed == 'binding': assert binding['relative_path'] == '内容/owner-choice'
        else: assert binding is None
        assert c.execute('SELECT status FROM toolbox_local_tasks').fetchone()[0] != 'running'


def test_bounded_scan_rotates_and_deduplicates_same_work(worker, monkeypatch):
    for number in range(7):
        enqueue(worker, 'work-' + str(number), 'record-' + str(number))
        enqueue(worker, 'work-' + str(number), 'cleanup-' + str(number), 'cleanup')
    seen = []
    def infer(c, wid, **kwargs): seen.append(wid); return None
    monkeypatch.setattr(worker, '_infer', infer)
    assert worker._process_one() is None
    assert len(seen) == len(set(seen)) == 4
    worker._process_one()
    assert len(seen) == 8 and len(set(seen)) == 7


def test_exact_new_binding_is_committed_then_deterministic_record_runs(worker, monkeypatch):
    enqueue(worker)
    calls = []
    def infer(c, wid, **kwargs):
        assert not c.in_transaction
        return {'work_id': wid, 'relative_path': '内容/new',
                'evidence': {'kind': 'exact_work_version_and_bytes'}, '_inferred': True}
    monkeypatch.setattr(worker, '_infer', infer)
    monkeypatch.setattr(worker, '_record', lambda task, target: calls.append(target) or {'files': {}})
    result = worker._process_one()
    assert result['status'] == 'completed'
    assert calls == [worker.project / '内容/new']
    with worker.store.connect() as c:
        assert worker._binding(c, 'work-one')['relative_path'] == '内容/new'
