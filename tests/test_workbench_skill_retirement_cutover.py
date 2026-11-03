"""TEMP exact-plan cutover guard; no application startup, models or real data."""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

spec=importlib.util.spec_from_file_location('retirement_cutover_fixtures',Path(__file__).with_name('test_workbench_skill_commands.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
runtime,commands=fixtures.runtime,fixtures.commands
spec=importlib.util.spec_from_file_location('retirement_cutover_script',Path(__file__).resolve().parents[1]/'scripts/upgrade_workbench_runtime.py')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
upgrade=importlib.util.module_from_spec(spec);spec.loader.exec_module(upgrade)


def test_first_native_cutover_requires_reviewed_profile_plan_and_rejects_changed_revision(commands):
    from easel_workbench.features.skills.retirement import preview,migration_runtime
    root=commands.root;package={'skills_protocol':'easel-native-v1'}
    acceptance=root/'.local/acceptance.json';acceptance.parent.mkdir()
    acceptance.write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='explicit reviewed retirement plan'):
        upgrade.reviewed_skill_retirement(root,package,acceptance,None,None)
    plan=preview(commands.creator);path=root/'.local/retirement.json';path.write_text(json.dumps(plan),encoding='utf-8')
    sha=hashlib.sha256(path.read_bytes()).hexdigest()
    acceptance.write_text(json.dumps({'evidence':{'.local/retirement.json':sha}}),encoding='utf-8')
    result=upgrade.reviewed_skill_retirement(root,package,acceptance,path,plan['plan_sha256'])
    assert result['plan_sha256']==plan['plan_sha256'] and result['sha256']==sha
    with commands.store.connect() as c:
        c.execute('UPDATE creator_profiles SET revision=revision+1,document=json_set(document,\'$.revision\',revision+1)')
    with pytest.raises(ValueError,match='revision changed'):
        upgrade.reviewed_skill_retirement(root,package,acceptance,path,plan['plan_sha256'])


def test_retirement_cutover_does_not_seed_or_modify_historical_skill_versions(commands):
    from easel_workbench.features.skills.retirement import preview,apply,migration_runtime
    runtime=migration_runtime(commands.root)
    with commands.store.connect() as c:
        before=[tuple(r) for r in c.execute('SELECT * FROM creator_skill_versions ORDER BY rowid')]
        history=[tuple(r) for r in c.execute('SELECT * FROM creator_profile_history ORDER BY rowid')]
    plan=preview(runtime);result=apply(runtime,plan['plan_sha256'])
    assert result==apply(runtime,plan['plan_sha256'])
    with commands.store.connect() as c:
        assert [tuple(r) for r in c.execute('SELECT * FROM creator_skill_versions ORDER BY rowid')]==before
        assert [tuple(r) for r in c.execute('SELECT * FROM creator_profile_history ORDER BY rowid LIMIT ?', (len(history),))]==history
        profiles=[json.loads(r[0]) for r in c.execute('SELECT document FROM creator_profiles')]
    assert all('skill_versions' not in p and 'task_skill_versions' not in p and 'learning' not in p['default_skills'] for p in profiles)
