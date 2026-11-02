"""The external daily canary receives a minimal frozen seed, never a DB clone."""
import importlib.util
import json
from pathlib import Path

import pytest
from easel_workbench.diagnostics.canary_export import export_seed

_spec=importlib.util.spec_from_file_location('canary_export_fixture',Path(__file__).with_name('test_workbench_chat_business.py'))
_fixture=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_fixture)
business=_fixture.business


def prepared(business):
    with business.store.connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS workbench_settings_versions(revision INTEGER PRIMARY KEY,document TEXT)')
        c.execute('INSERT OR REPLACE INTO workbench_settings_versions VALUES(?,?)',(2,json.dumps({'revision':2,'runtime':'codex','models':{},'sandbox':'workspace-write','codex_auto_approve':True,'secret_ref':'opaque-reference-only'})))


def test_export_minimal_seed_has_no_works_sessions_accounts_or_plain_credentials(business):
    prepared(business);value=export_seed(business.root,business.root)
    assert value['profile_id']=='oil-pig' and value['settings_revision']==2
    assert len(value['rows']['creator_skill_pointers'])==8
    assert len(value['rows']['creator_skill_versions'])==8
    assert value['blob_bytes']<32*1024*1024
    assert set(value['rows'])<= {'creator_skills','creator_skill_pointers','creator_skill_versions','creator_profiles','creator_profile_history','creator_skill_blobs','creator_skill_source_outbox','workbench_settings_versions'}
    with business.store.connect() as c:
        assert c.execute('SELECT count(*) FROM easel_chat_sessions').fetchone()[0]==1
        assert c.execute('SELECT count(*) FROM toolbox_jobs').fetchone()[0]==0
    assert 'opaque-reference-only' in value['rows']['workbench_settings_versions'][0]['document']


def test_missing_frozen_resource_fails_closed(business):
    prepared(business)
    with business.store.connect() as c:c.execute('DELETE FROM creator_skill_blobs')
    with pytest.raises(ValueError,match='blob_missing'):export_seed(business.root,business.root)


def test_non_native_configuration_cannot_silently_use_fake_or_api_engine(business):
    prepared(business)
    with business.store.connect() as c:c.execute('UPDATE workbench_settings_versions SET document=?',(json.dumps({'revision':2,'runtime':'api'}),))
    with pytest.raises(ValueError,match='native_codex'):export_seed(business.root,business.root)


def test_external_worker_dry_bootstrap_uses_real_services_only_inside_canary(business,tmp_path,monkeypatch):
    import asyncio
    import hashlib
    import sys
    import shutil
    import os
    repository=Path(__file__).resolve().parents[1]
    controller=repository/'tools/health-control'
    if not controller.is_dir():controller=repository.parent/'easel-health-control'
    old_paths=list(sys.path)
    monkeypatch.setenv('AI_DESK_PROJECT_ROOT',os.environ.get('AI_DESK_PROJECT_ROOT',str(repository)))
    monkeypatch.setenv('AI_DESK_RELEASE',os.environ.get('AI_DESK_RELEASE','test-only'))
    sys.path.insert(0,str(controller))
    from easel_health_control import canary_worker
    prepared(business)
    source=business.root
    (source/'sources.json').write_bytes((Path(__file__).resolve().parents[1]/'sources.json').read_bytes())
    files={p.relative_to(source).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for prefix in ['skills','agents'] for p in (source/prefix).rglob('*') if p.is_file()}
    files['sources.json']=hashlib.sha256((source/'sources.json').read_bytes()).hexdigest()
    pointer={'release':'workbench-fixture','manifest_sha256':'a'*64}
    monkeypatch.setattr(canary_worker,'selected_release',lambda app:(source,pointer,{'files':files}))
    workspace=tmp_path/'external-canary'
    request={'application_root':str(business.root),'workspace':str(workspace),'operation_id':'canary-fixture','timeout_seconds':10}
    # Sibling external workspace, not a descendant of the production root.
    workspace=business.root.parent/(business.root.name+'-external')
    request['workspace']=str(workspace)
    try:
        context=canary_worker.prepare(request)
        assert context['store'].path.is_relative_to(workspace)
        assert context['box'].studio.project==workspace/'project/content-project'
        assert context['box'].learning.project==workspace/'project/content-project'
        assert context['chat'].settings.current()['codex_auto_approve'] is False
        assert context['chat'].settings.current()['canary_source_revision']==2
        assert context['chat']._tasks=={} and context['admission'].tasks=={}
        with context['store'].connect() as c:
            assert c.execute('SELECT count(*) FROM toolbox_jobs').fetchone()[0]==0
            assert c.execute('SELECT count(*) FROM easel_chat_sessions').fetchone()[0]==0
        asyncio.run(context['admission'].close());asyncio.run(context['chat'].close())
    finally:
        shutil.rmtree(workspace,ignore_errors=True)
        sys.path[:]=old_paths
