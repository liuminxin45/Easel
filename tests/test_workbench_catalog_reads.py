"""Current official catalog reads and historical frozen-release compatibility, TEMP only."""
import importlib.util
import asyncio
import json
import os
from pathlib import Path

import pytest

_fixture_spec=importlib.util.spec_from_file_location('catalog_read_fixtures',Path(__file__).with_name('test_workbench_upstream_skills.py'))
_fixture=importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture)
business=_fixture.business
library=_fixture.library


def test_current_project_menu_and_detail_use_official_shapes_without_private_release_hydration(business,monkeypatch):
    from easel_workbench.runtime.native_skills import service
    b=business;native=service(b.box,b.chat)
    monkeypatch.setattr(b.creator,'detail',lambda *a,**k:pytest.fail('current menu must not hydrate private creator details'))
    monkeypatch.setattr(b.creator,'_skill',lambda *a,**k:pytest.fail('current menu must not hydrate private versions'))
    monkeypatch.setattr(b.upstream,'_common',lambda *a,**k:pytest.fail('current menu must not read complete dependency bytes'))
    rows=native.items();assert rows
    assert {r['name'] for r in rows}=={p.parent.name for p in (b.root/'skills/builtin').glob('*/SKILL.md')}
    for row in rows:assert not {'body','resources','prompt','history','version','sha256','launch_actions','origin'}.intersection(row)
    detail=asyncio.run(native.detail('content-production'))
    assert set(detail)-{'configuration_revision'}=={'name','description','body','layer','needsApi','apiConfigured','apiSpec'}
    assert detail['body'] and detail['name']=='content-production'


def test_historical_project_release_byte_check_remains_fresh_without_current_private_menu(business):
    from easel_workbench.project_skill_sync import matches_source
    b=business;release=b.creator.detail('skill','content-writing')
    assert matches_source(b.creator,release)
    path=b.root/'skills/builtin/content-writing/SKILL.md';original=path.stat();raw=path.read_bytes()
    changed=raw[:-2]+bytes([65 if raw[-2]!=65 else 66])+raw[-1:]
    assert len(changed)==len(raw)
    path.write_bytes(changed);os.utime(path,ns=(original.st_atime_ns,original.st_mtime_ns))
    assert path.stat().st_size==original.st_size and path.stat().st_mtime_ns==original.st_mtime_ns
    assert not matches_source(b.creator,release)


def test_native_mode_seeds_profiles_without_private_releases_and_rejects_new_profile_pins(tmp_path):
    from types import SimpleNamespace
    from easel_workbench.runtime.creator_runtime import CreatorRuntime
    from easel_workbench.runtime.desk import Store
    from easel_workbench.features.skills.retirement import SkillFeatureRetired
    config=tmp_path/'config';config.mkdir()
    (config/'workbench-skills.json').write_text('{"schema_version":1,"mode":"easel-native"}',encoding='utf-8')
    box=SimpleNamespace(root=tmp_path,store=Store(tmp_path/'data/desk.sqlite'))
    runtime=CreatorRuntime(box,project=tmp_path)
    with box.store.connect() as c:
        assert c.execute('SELECT count(*) FROM creator_profiles').fetchone()[0]==1
        for table in ('creator_skills','creator_skill_versions','creator_skill_pointers'):
            assert c.execute('SELECT count(*) FROM '+table).fetchone()[0]==0
    bootstrap=runtime.bootstrap();assert bootstrap['skills']==[] and bootstrap['task_defaults']=={} and bootstrap['task_policy']=={}
    profile=runtime.detail('profile','oil-pig');assert profile['default_skills']=={}
    assert 'skill_versions' not in profile and 'task_skill_versions' not in profile
    for field,value in [('skill_versions',{'content-writing':1}),('task_skill_versions',{'poster':{'content-writing':1}}),('default_skills',{'poster':['content-writing']})]:
        with pytest.raises(SkillFeatureRetired):runtime.command({'id':'new-pins-'+field,'action':'profile-save','profile_id':'oil-pig','base_revision':profile['revision'],'document':{field:value}})
    saved=runtime.command({'id':'normal-profile-edit','action':'profile-save','profile_id':'oil-pig','base_revision':profile['revision'],'document':{'voice':'Exact changed expression'}})['result']['profile']
    assert saved['voice']=='Exact changed expression' and 'skill_versions' not in saved and 'task_skill_versions' not in saved


def assert_list_only(rows):
    forbidden={'body','content','raw','prompt','resources','history','creator','snapshot','meta'}
    assert rows
    for row in rows:assert not forbidden.intersection(row),row['id']




def test_historical_native_menu_stored_versions_do_not_decode_frozen_release_packages(library,monkeypatch):
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


def test_historical_native_menu_content_addressed_cache_detects_equal_size_equal_mtime_changes(library):
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




def test_historical_frozen_native_catalog_uses_verified_inventory_without_loading_dependency_bytes(library,monkeypatch):
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
    # Only list reads use the approved inventory shortcut; selected execution
    # continues to validate its complete byte package through _common.
    with pytest.raises(pytest.fail.Exception,match='dependency bytes'):native.release(rows[0]['id'])


def test_historical_native_display_refreshes_source_body_and_configuration_without_changing_full_contract(library):
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
