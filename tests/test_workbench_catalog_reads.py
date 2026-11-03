"""TEMP-only catalog projections keep exact releases without full detail reads."""
import importlib.util
import json
import os
from pathlib import Path

import pytest

_fixture_spec=importlib.util.spec_from_file_location('catalog_read_fixtures',Path(__file__).with_name('test_workbench_upstream_skills.py'))
_fixture=importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture)
business=_fixture.business
library=_fixture.library


def assert_list_only(rows):
    forbidden={'body','content','raw','prompt','resources','history','creator','snapshot','meta'}
    assert rows
    for row in rows:assert not forbidden.intersection(row),row['id']


def test_project_menu_preserves_exact_launch_identity_without_detail_reads(business,monkeypatch):
    from easel_workbench.features.skills.catalog_reads import release_metadata
    from easel_workbench.project_skill_sync import matches_source
    from easel_workbench.skills import launch_metadata
    b=business
    expected={}
    for entry in b.catalog.entries():
        full=b.creator.detail('skill',entry['id'])
        expected[entry['id']]={'version':full['version'],'sha256':full['sha256'],'available':matches_source(b.creator,full),**launch_metadata(full)}
        with b.store.connect() as c:
            metadata=release_metadata(c,entry['id'])
        assert {k:metadata.get(k) for k in metadata if k!='resources'}=={k:full.get(k) for k in metadata if k!='resources'}
        assert metadata['resources']==[{k:v for k,v in r.items() if k not in ('url','content')} for r in full['resources']]
        assert not {'history','published_version','is_current'}.intersection(metadata)
    monkeypatch.setattr(b.creator,'detail',lambda *a,**k:pytest.fail('menu must not hydrate creator detail/history'))
    monkeypatch.setattr(b.creator,'_skill',lambda *a,**k:pytest.fail('menu must not hydrate full release via creator service'))
    rows=b.skills(False)
    assert_list_only(rows)
    for row in rows:
        old=expected[row['id']]
        for key in ('version','sha256','available','execution_kind'):assert row[key]==old[key]
        assert [(a['id'],a['task']) for a in row['launch_actions']]==[(a['id'],a['task']) for a in old['launch_actions']]
    assert len(json.dumps(rows,ensure_ascii=False).encode())<30000


def test_native_menu_stored_versions_do_not_decode_frozen_release_packages(library,monkeypatch):
    b=library;native=b.upstream
    expected={entry['id']:native.release(entry['id']) for entry in native.entries()}
    with b.store.connect() as c:
        for sid,release in expected.items():
            c.execute('INSERT INTO creator_skill_versions VALUES(?,?,?)',(sid,release['version'],json.dumps(release)))
    loads=json.loads
    def bounded_loads(value,*a,**k):
        if isinstance(value,str) and '"resources"' in value and '"prompt"' in value:
            pytest.fail('menu decoded a stored full frozen release')
        return loads(value,*a,**k)
    monkeypatch.setattr(json,'loads',bounded_loads)
    monkeypatch.setattr(native,'release',lambda *a,**k:pytest.fail('stored native menu must project scalar identity instead of release detail'))
    rows=native.items()
    assert_list_only(rows)
    for row in rows:
        release=expected[row['id']]
        for key in ('version','sha256','source_revision'):assert row[key]==release[key]
    assert len(json.dumps(rows,ensure_ascii=False).encode())<20000
    shown=native.detail(rows[0]['id'],view='display')
    assert shown['version']==rows[0]['version'] and shown['sha256']==rows[0]['sha256']
    assert shown['prompt']==expected[rows[0]['id']]['prompt'] and 'resources' not in shown
    with b.store.connect() as c:
        assert c.execute('SELECT count(*) FROM creator_skill_versions WHERE skill_id IN (?,?,?)',tuple(expected)).fetchone()[0]==3


def test_native_menu_content_addressed_cache_detects_equal_size_equal_mtime_changes(library):
    native=library.upstream
    first=native.items()
    path=library.root/'skills/shared/scripts/catalog-byte-test.txt'
    path.write_bytes(b'Original source byte A')
    before=native.items()
    assert before[0]['source_revision']!=first[0]['source_revision']
    original=path.stat()
    path.write_bytes(b'Original source byte B')
    os.utime(path,ns=(original.st_atime_ns,original.st_mtime_ns))
    assert path.stat().st_size==original.st_size and path.stat().st_mtime_ns==original.st_mtime_ns
    after=native.items()
    assert after[0]['source_revision']!=before[0]['source_revision']
    assert after[0]['sha256']!=before[0]['sha256']
    exact=native.release(after[0]['id'])
    assert {k:after[0][k] for k in ('version','sha256','source_revision')}=={k:exact[k] for k in ('version','sha256','source_revision')}
    # Repeated reads may use metadata cache, never stale byte/mtime identity.
    assert native.items()==after


def test_project_menu_source_validation_is_fresh_even_when_stat_is_unchanged(business):
    b=business
    original=next(row for row in b.skills(False) if row['id']=='content-writing')
    assert original['available']
    path=b.root/'skills/builtin/content-writing/SKILL.md';stat=path.stat();raw=path.read_bytes()
    # Change the instruction body only, leaving capability/contract metadata valid.
    at=raw.rfind(b'\n')
    changed=bytearray(raw)
    position=next(i for i in range(len(raw)-1,at,-1) if raw[i] not in (10,13,32)) if at<len(raw)-2 else len(raw)-2
    changed[position]=65 if raw[position]!=65 else 66
    path.write_bytes(changed);os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
    assert path.stat().st_size==stat.st_size and path.stat().st_mtime_ns==stat.st_mtime_ns
    updated=next(row for row in b.skills(False) if row['id']=='content-writing')
    assert not updated['available']
    assert updated['version']==original['version'] and updated['sha256']==original['sha256']
    assert updated['source_revision']!=original['source_revision']


def test_frozen_native_catalog_uses_verified_inventory_without_loading_dependency_bytes(library,monkeypatch):
    import hashlib
    import shutil
    from easel_workbench.upstream_skills import UpstreamSkills
    b=library;source=b.root/'releases/approved';shutil.copytree(b.root/'skills',source/'skills')
    inventory={p.relative_to(source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in (source/'skills').rglob('*') if p.is_file()}
    (source/'workbench-release.json').write_text(json.dumps({'files':inventory}),encoding='utf-8')
    native=UpstreamSkills(b.root,b.creator,source)
    expected={entry['id']:native.release(entry['id']) for entry in native.entries()}
    full_detail=native.detail('card-quote')
    monkeypatch.setattr(native,'_common',lambda *a,**k:pytest.fail('frozen catalog must not load all dependency bytes'))
    rows=native.items();assert_list_only(rows)
    for row in rows:
        assert {k:row[k] for k in ('version','sha256','source_revision')}=={k:expected[row['id']][k] for k in ('version','sha256','source_revision')}
    assert native.items()==rows
    shown=native.detail('card-quote',view='display')
    for key in ('id','version','sha256','source_revision','description','layer','body','content','meta','raw','prompt','needsApi','apiConfigured','apiSpec','configuration_revision'):
        assert shown.get(key)==full_detail.get(key),key
    assert 'resources' not in shown and 'creator' not in shown and 'history' not in shown
    b.upstream=native
    assert b.skill('card-quote')==shown
    # Only list reads use the approved inventory shortcut; selected execution
    # continues to validate its complete byte package through _common.
    with pytest.raises(pytest.fail.Exception,match='dependency bytes'):native.release(rows[0]['id'])


def test_native_display_refreshes_source_body_and_configuration_without_changing_full_contract(library):
    native=library.upstream
    native.configuration=lambda:{'revision':'configuration-one','environment':{}}
    first=native.detail('card-quote',view='display')
    source=library.root/'skills/builtin/card-quote/SKILL.md'
    source.write_bytes(source.read_bytes()+b'\nCurrent display instructions changed.\n')
    native.configuration=lambda:{'revision':'configuration-two','environment':{}}
    second=native.detail('card-quote',view='display')
    assert 'Current display instructions changed.' in second['body']
    assert first['source_revision']!=second['source_revision'] and first['sha256']!=second['sha256']
    assert second['configuration_revision']=='configuration-two'
    full=native.detail('card-quote')
    assert full['resources'] and full['prompt']==second['prompt']
    for key in ('version','sha256','source_revision'):assert full[key]==second[key]
    with pytest.raises(ValueError,match='视图'):native.detail('card-quote',view='invalid')
