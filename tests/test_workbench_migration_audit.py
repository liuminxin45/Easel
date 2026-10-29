"""Synthetic migration and new-task path tests; no production state is opened."""
import hashlib
import json
from pathlib import Path
import sqlite3
from unittest.mock import patch

import pytest

from scripts.migrate_workbench_data import database_fingerprint, migrate, validate


def source_tree(tmp_path):
    source=tmp_path/'source';(source/'data').mkdir(parents=True)
    with sqlite3.connect(source/'data/desk.sqlite') as connection:
        connection.executescript('CREATE TABLE frozen(id INTEGER PRIMARY KEY,document TEXT,payload BLOB); CREATE TABLE duplicates(value TEXT); CREATE INDEX doc_index ON frozen(document);')
        document=json.dumps({'frozen_path':str(source/'data/artifacts/original.png'),'operation_id':'unknown-operation'},ensure_ascii=False)
        connection.execute('INSERT INTO frozen VALUES(?,?,?)',(1,document,b'\x00\xff\x01'))
        connection.executemany('INSERT INTO duplicates VALUES(?)',[('same',),('same',)])
    config={'profile_dir':str(source/'data/collection/profile'),'state_root':str(source/'data/collection/sources'),'external':str(tmp_path/'external')}
    (source/'data/collection-sources.json').write_text(json.dumps(config),encoding='utf-8')
    (source/'data/feedback-config.json').write_text(json.dumps({'profile_dir':config['profile_dir'],'enabled':True}),encoding='utf-8')
    (source/'data/history.json').write_text(document,encoding='utf-8')
    (source/'data/plain.bin').write_bytes(b'original\x00bytes')
    return source


def test_copy_preserves_schema_every_row_and_frozen_bytes(tmp_path):
    source=source_tree(tmp_path);target=tmp_path/'candidate'
    frozen=(source/'data/history.json').read_bytes()
    report=migrate(source,target)
    assert validate(source,target)['passed']
    assert report['database_fingerprints']['desk.sqlite']['tables']['duplicates']['rows']==2
    with sqlite3.connect(source/'data/desk.sqlite') as old,sqlite3.connect(target/'data/desk.sqlite') as new:
        assert database_fingerprint(old)==database_fingerprint(new)
        assert old.execute('select document from frozen').fetchone()==new.execute('select document from frozen').fetchone()
    assert (target/'data/history.json').read_bytes()==frozen
    assert (source/'data/history.json').read_bytes()==frozen
    assert (target/'data/plain.bin').read_bytes()==b'original\x00bytes'


def test_only_owned_mutable_path_keys_are_rebased(tmp_path):
    source=source_tree(tmp_path);target=tmp_path/'candidate';report=migrate(source,target)
    config=json.loads((target/'data/collection-sources.json').read_text(encoding='utf-8'))
    assert Path(config['profile_dir'])==target/'data/collection/profile'
    assert Path(config['state_root'])==target/'data/collection/sources'
    assert config['external']==str(tmp_path/'external')
    assert json.loads((source/'data/collection-sources.json').read_text())['profile_dir']==str(source/'data/collection/profile')
    assert report['mutable_config_rewrites']=={'collection-sources.json':['profile_dir','state_root'],'feedback-config.json':['profile_dir']}


def test_staged_copy_can_target_final_runtime_paths_without_writing_final_root(tmp_path):
    source=source_tree(tmp_path);target=tmp_path/'candidate';runtime_root=tmp_path/'final'
    report=migrate(source,target,runtime_root=runtime_root)
    assert validate(source,target)['passed']
    config=json.loads((target/'data/collection-sources.json').read_text(encoding='utf-8'))
    assert Path(config['state_root'])==runtime_root/'data/collection/sources'
    assert not runtime_root.exists()
    assert report['runtime_root']==str(runtime_root.resolve())


def test_original_names_and_database_extensions_are_not_treated_as_runtime_controls(tmp_path):
    source=source_tree(tmp_path);target=tmp_path/'candidate'
    for relative,content in [('artifacts/active-note.lock',b'original lock attachment'),
                             ('toolbox/files/id/active-trace.log',b'original log attachment'),
                             ('toolbox/files/id/reference.db',b'opaque original file')]:
        path=source/'data'/relative;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(content)
    (source/'data/active-native.json').write_text('{"release":"old"}',encoding='utf-8')
    report=migrate(source,target)
    assert validate(source,target)['passed']
    assert 'active-native.json' not in report['files']
    assert 'toolbox/files/id/reference.db' not in report['database_fingerprints']
    assert (target/'data/artifacts/active-note.lock').read_bytes()==b'original lock attachment'
    assert (target/'data/toolbox/files/id/active-trace.log').read_bytes()==b'original log attachment'
    assert (target/'data/toolbox/files/id/reference.db').read_bytes()==b'opaque original file'


def test_same_count_row_change_is_detected_on_each_side(tmp_path):
    source=source_tree(tmp_path);target=tmp_path/'candidate';migrate(source,target)
    with sqlite3.connect(source/'data/desk.sqlite') as connection:
        connection.execute("update frozen set document='changed-source' where id=1")
    result=validate(source,target)
    assert not result['passed']
    assert any(e['reason']=='source_rows_changed' for e in result['errors'])
    with sqlite3.connect(target/'data/desk.sqlite') as connection:
        connection.execute("update frozen set document='changed-target' where id=1")
    result=validate(source,target,compare_source=False)
    assert any(e['reason']=='target_rows_changed' for e in result['errors'])


def test_duplicate_rows_and_source_additions_are_detected(tmp_path):
    source=source_tree(tmp_path);target=tmp_path/'candidate';migrate(source,target)
    (source/'data/new-input.txt').write_text('late accepted input',encoding='utf-8')
    assert any(e['reason']=='source_file_added' for e in validate(source,target)['errors'])
    with sqlite3.connect(target/'data/desk.sqlite') as connection:
        connection.execute('delete from duplicates where rowid=1')
    assert any(e['reason']=='target_rows_changed' for e in validate(source,target,compare_source=False)['errors'])


def test_overwrite_or_nested_target_is_refused(tmp_path):
    source=source_tree(tmp_path)
    with pytest.raises(ValueError):migrate(source,source/'nested')
    target=tmp_path/'candidate';migrate(source,target)
    with pytest.raises(ValueError):migrate(source,target)


def test_new_task_metadata_uses_migrated_file_without_changing_original_db_path(tmp_path):
    from easel_workbench import paths
    from easel_workbench.runtime.desk import Store
    from easel_workbench.runtime.toolbox_store import Toolbox
    original=tmp_path/'original';target=tmp_path/'candidate';target.mkdir()
    data=b'owned original bytes';relative=Path('data/toolbox/files/file-id/reference.png')
    destination=target/relative;destination.parent.mkdir(parents=True);destination.write_bytes(data)
    box=Toolbox(Store(target/'data/desk.sqlite'),target)
    old_path=str(original/relative)
    with box.store.connect() as connection:
        connection.execute('INSERT INTO toolbox_files VALUES(?,?,?,?,?,?)',('file-id','reference.png',old_path,'image/png',len(data),hashlib.sha256(data).hexdigest()))
    with patch.object(paths,'PREVIOUS_ROOT',original.resolve()):
        metadata,path=box.file('file-id')
    assert path==destination.resolve()
    assert Path(metadata['path'])==destination.resolve()
    with box.store.connect() as connection:
        assert connection.execute("select path from toolbox_files where id='file-id'").fetchone()[0]==old_path


def test_migrated_discovery_input_keeps_original_sha_and_maps_owned_evidence(tmp_path):
    import shutil
    from easel_workbench import paths
    from easel_workbench.runtime.discovery_feeds import discovery_input,read_discovery_input
    original=tmp_path/'old';target=tmp_path/'candidate';source='hacker-news'
    before=original/'evidence/discovery'/source/'original-capture'
    before.mkdir(parents=True)
    (before/'items.json').write_text('[{"rank":1,"item":{"id":123},"error":null}]',encoding='utf-8')
    (before/'topstories.json').write_text('[123]',encoding='utf-8')
    frozen=discovery_input(source,[{'source_event_id':'hn:123','title':'原字材料'}],{'errors':[]},before,['hn:123'],'2026-10-30')
    raw=(json.dumps(frozen,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    old_input=original/'data/collection/frozen/discovery-input.json';old_input.parent.mkdir(parents=True);old_input.write_bytes(raw)
    new_input=target/'data/collection/frozen/discovery-input.json';new_input.parent.mkdir(parents=True);shutil.copy2(old_input,new_input)
    after=target/'evidence/discovery'/source/'original-capture';shutil.copytree(before,after)
    original_sha=hashlib.sha256(raw).hexdigest()
    with patch.object(paths,'PREVIOUS_ROOT',original.resolve()):
        result=read_discovery_input(new_input,source,target)
        resolved=paths.discovery_evidence(result['evidence'],target)
    assert result==frozen and result['sha256']==frozen['sha256']
    assert result['evidence']==str(before)
    assert resolved==after.resolve()
    assert (resolved/'items.json').read_bytes()==(before/'items.json').read_bytes()
    assert hashlib.sha256(new_input.read_bytes()).hexdigest()==original_sha
    assert hashlib.sha256(old_input.read_bytes()).hexdigest()==original_sha
