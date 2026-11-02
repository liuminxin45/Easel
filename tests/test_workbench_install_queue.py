"""Real TEMP install receipts shared across current and historical entry points."""
import json
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace

import pytest

from easel_workbench.application import installation
from easel_workbench.features.installations.queue import InstallationQueue
from easel_workbench.runtime import media_environment
from easel_workbench.runtime.desk import Store


def environment(tmp_path):
    box=SimpleNamespace(root=tmp_path,store=Store(tmp_path/'data/desk.sqlite'))
    return box,installation.service(box)


@pytest.mark.parametrize('legacy_first',[False,True])
def test_current_and_legacy_entry_share_receipt_and_only_start_one_installer(tmp_path,monkeypatch,legacy_first):
    box,current=environment(tmp_path)
    legacy=media_environment.MediaEnvironment(box)
    starts=[]
    threads=SimpleNamespace(Thread=lambda **kw:SimpleNamespace(start=lambda:starts.append(kw)))
    monkeypatch.setattr(installation,'threading',threads)
    monkeypatch.setattr(media_environment,'threading',threads)
    monkeypatch.setattr(current,'check',lambda:None)
    monkeypatch.setattr(legacy,'check',lambda:None)
    value={'id':'same-operation','recipe':'browser'}
    first=(legacy if legacy_first else current).install(value)
    assert current.install(value)==first
    assert legacy.install(value)==first
    assert len(starts)==1
    with box.store.connect() as c:
        rows=list(c.execute('SELECT id,document FROM media_install_jobs'))
    assert len(rows)==1 and json.loads(rows[0]['document'])==first
    assert installation.service(box) is current


def test_two_queue_instances_cannot_admit_parallel_installs(tmp_path):
    box,current=environment(tmp_path)
    barrier=Barrier(2)
    def enqueue(operation):
        queue=InstallationQueue(store=box.store,root=tmp_path,directory=current.directory)
        barrier.wait(timeout=5)
        try:return queue.enqueue({'id':operation,'recipe':'browser'})
        except ValueError as error:return error
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(enqueue,['first','second']))
    assert sum(isinstance(value,tuple) for value in results)==1
    assert sum(isinstance(value,ValueError) for value in results)==1
    with box.store.connect() as c:assert c.execute('SELECT count(*) FROM media_install_jobs').fetchone()[0]==1


def test_existing_operation_cannot_switch_recipe_or_rewrite_its_receipt(tmp_path):
    box,current=environment(tmp_path)
    first,created=current.queue.enqueue({'id':'fixed-operation','recipe':'browser'})
    assert created
    with pytest.raises(ValueError,match='同一安装操作不能更换依赖'):
        current.queue.enqueue({'id':'fixed-operation','recipe':'biliup'})
    with box.store.connect() as c:
        assert json.loads(c.execute('SELECT document FROM media_install_jobs').fetchone()[0])==first
