"""TEMP schema/order, caller-owned transactions, and native capability contracts."""
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from easel_workbench.runtime.desk import Store
from easel_workbench.runtime.toolbox_store import Toolbox
from easel_workbench.infrastructure.storage import schema


def test_bootstrap_preserves_same_database_and_one_time_historical_import(tmp_path):
    path=tmp_path/'data/desk.sqlite'
    store=Store(path)
    box=Toolbox(store,tmp_path)
    identity=path.stat().st_ino
    with store.connect() as c:
        c.execute("INSERT INTO toolbox_meta VALUES('TEMP-sentinel','original')")
        before=[tuple(row) for row in c.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY rowid')]
    again=Toolbox(Store(path),tmp_path)
    assert again.root==box.root and path.stat().st_ino==identity
    with again.store.connect() as c:
        assert c.execute("SELECT value FROM toolbox_meta WHERE key='TEMP-sentinel'").fetchone()[0]=='original'
        assert [tuple(row) for row in c.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY rowid')]==before
        assert c.execute("SELECT count(*) FROM toolbox_meta WHERE key IN ('legacy-import-v1','legacy-files-v1')").fetchone()[0]==2


@pytest.mark.parametrize('initialize',[schema.initialize_creator,schema.initialize_tasks])
def test_version_schema_never_commits_the_callers_transaction(initialize):
    with sqlite3.connect(':memory:') as c:
        c.execute('BEGIN IMMEDIATE')
        initialize(c)
        assert c.in_transaction
        assert c.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]>0
        c.rollback()
        assert c.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]==0


def test_explicit_application_root_is_used_for_default_store(tmp_path,monkeypatch):
    from easel_workbench.runtime import toolbox_server
    from easel_workbench.application import create_app
    class ObservedRoot(Exception):pass
    calls=[]
    def inspect(path):
        calls.append(Path(path))
        raise ObservedRoot
    monkeypatch.setattr(toolbox_server,'Store',inspect)
    with pytest.raises(ObservedRoot):create_app(root=tmp_path)
    assert calls==[tmp_path/'data/desk.sqlite']


@pytest.mark.skipif(os.name!='nt',reason='Original Windows user DPAPI contract')
def test_native_vault_format_roundtrip_and_legacy_exports(tmp_path):
    from easel_workbench.infrastructure.credentials import DPAPIVault,VaultError
    from easel_workbench.infrastructure.processes import process_identity
    from easel_workbench.runtime import distribution_runtime
    assert distribution_runtime.DPAPIVault is DPAPIVault
    assert distribution_runtime.VaultError is VaultError
    assert distribution_runtime.process_identity is process_identity
    vault=DPAPIVault(tmp_path)
    reference=vault.put('TEMP-connection',{'test':'synthetic secret'})
    assert vault.get(reference,'TEMP-connection')=={'test':'synthetic secret'}
    with pytest.raises(VaultError):vault.get(reference,'different-connection')
    encrypted=next(vault.directory.glob('*.dpapi')).read_bytes()
    assert encrypted.startswith(b'NDV1') and b'synthetic secret' not in encrypted
    assert process_identity(os.getpid()) and process_identity(-1) is None
