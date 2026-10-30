"""Atomic builtin publication migration tests, all writes in TEMP databases."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('builtin_activation', ROOT / 'scripts/activate_workbench_builtin_skills.py')
activation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(activation)


@pytest.fixture(scope='module')
def seed():
    return activation.generated_packages(ROOT)


def legacy_database(tmp_path, seed):
    from easel_workbench.runtime.creator_runtime import initialize
    runtime, descriptors, releases, blobs = seed
    receipt = json.loads((ROOT / 'skills/workbench-import.json').read_text(encoding='utf-8'))
    mapping = {row['new_path']: row for row in receipt['mapping']}
    entries = {row['new_path'].split('/')[2]: row['old_path'] for row in receipt['mapping'] if row['kind'] == 'skill_entry'}
    path = tmp_path / 'legacy.sqlite'
    with activation.connect(path, write=True) as connection:
        initialize(connection)
        for digest, raw in blobs.items():
            connection.execute('INSERT INTO creator_skill_blobs VALUES(?,?)', (digest, raw))
        for sid in activation.IDS:
            document = copy.deepcopy(releases[sid]); document['entry'] = entries[sid]
            document.pop('composition', None); document.pop('layer', None)
            if sid == 'content-production':
                document['executor'] = 'workflow'
            resources = []
            for resource in document['resources']:
                row = mapping.get(resource['path']) or next((item for item in mapping.values() if item['old_path'] == resource['path']), None)
                # This synthetic legacy package predates raw policy JSON
                # snapshots; all actual style/asset/derived bytes are real.
                if row and row['transformation'] == 'json_project_path_rebase':
                    continue
                if row:
                    resource['path'] = row['old_path']
                if resource['path'].endswith('/references/confirmed-baseline.json'):
                    resource['path'] = str(Path(entries[sid]).parent / 'references/confirmed-baseline.json').replace('\\', '/')
                resources.append(resource)
            document['resources'] = resources
            document['sha256'] = runtime._release_hash(document)
            connection.execute('INSERT INTO creator_skill_versions VALUES(?,?,?)', (sid, 1, activation.pack(document)))
            descriptor = copy.deepcopy(descriptors[sid]); descriptor['entry'] = entries[sid]
            connection.execute('INSERT INTO creator_skills VALUES(?,?)', (sid, activation.pack(descriptor)))
            connection.execute('INSERT INTO creator_skill_pointers VALUES(?,?,?)', (sid, 1, 1))
        profile = {'id': 'synthetic-profile', 'revision': 1, 'name': 'Synthetic', 'created_at': 'old-time',
                   'default_skills': {task: list(activation.OLD_PRODUCTION) for task in ('poster', 'article', 'change')},
                   'skill_versions': {sid: 1 for sid in activation.IDS if sid != 'content-production'},
                   'task_skill_versions': {task: {sid: 1 for sid in activation.OLD_PRODUCTION} for task in ('poster', 'article', 'change')},
                   'asset_refs': []}
        raw = activation.pack(profile)
        connection.execute('INSERT INTO creator_profiles VALUES(?,?,?)', (profile['id'], 1, raw))
        connection.execute('INSERT INTO creator_profile_history VALUES(?,?,?)', (profile['id'], 1, raw))
        connection.execute('CREATE TABLE toolbox_jobs(id TEXT PRIMARY KEY,status TEXT,payload TEXT)')
        connection.execute('INSERT INTO toolbox_jobs VALUES(?,?,?)', ('old-job', 'completed', 'unchanged frozen input and feedback'))
        connection.execute('CREATE TABLE creator_model_calls(id TEXT PRIMARY KEY,document TEXT)')
        connection.commit()
    return path


def snapshot(path):
    with activation.connect(path) as connection:
        return {row[0]: [list(value) for value in connection.execute('SELECT * FROM ' + row[0] + ' ORDER BY rowid')]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def read_plan(path, seed):
    with activation.connect(path) as connection:
        return activation.build_plan(connection, ROOT, seed=seed)[0]


def test_read_only_preview_and_exact_root_skill_pin_adaptation(tmp_path, seed):
    path = legacy_database(tmp_path, seed); before = snapshot(path)
    plan = read_plan(path, seed)
    assert not plan['conflicts'] and not plan['busy'] and len(plan['skills']) == 8
    assert snapshot(path) == before
    profile = plan['profiles'][0]['document']
    assert profile['revision'] == 2 and profile['skill_versions']['content-production'] == 2
    for task in ('poster', 'article', 'change'):
        assert profile['default_skills'][task] == ['content-production', *activation.OLD_PRODUCTION]
        assert set(profile['task_skill_versions'][task].values()) == {2}
    assert len({item['new_sha256'] for item in plan['skills']}) == 8
    assert all(resource['path'].startswith('skills/') for item in plan['skills'] for resource in item['release']['resources'])


def test_apply_atomic_and_idempotent_preserves_all_v1_history_and_jobs(tmp_path, seed, monkeypatch):
    path = legacy_database(tmp_path, seed); before = snapshot(path); plan = read_plan(path, seed)
    monkeypatch.setattr(activation, 'require_fence', lambda root: None)
    result = activation.apply_plan(path, ROOT, plan['plan_sha256'])
    assert result['applied'] and result['old_versions_rewritten'] == 0 and result['jobs_requeued'] == 0
    after = snapshot(path)
    assert after['creator_skill_versions'][:8] == before['creator_skill_versions']
    assert after['creator_profile_history'][0] == before['creator_profile_history'][0]
    assert after['toolbox_jobs'] == before['toolbox_jobs']
    assert len(after['creator_skill_versions']) == 16 and len(after['creator_skill_events']) == 8
    assert activation.apply_plan(path, ROOT, plan['plan_sha256'])['already_applied']
    assert snapshot(path) == after


def test_transaction_rolls_back_every_write_if_profile_update_fails(tmp_path, seed, monkeypatch):
    path = legacy_database(tmp_path, seed)
    with activation.connect(path, write=True) as connection:
        connection.execute("CREATE TRIGGER stop_profile_update BEFORE UPDATE ON creator_profiles BEGIN SELECT RAISE(ABORT,'synthetic stop'); END")
        connection.commit()
    before = snapshot(path); plan = read_plan(path, seed)
    monkeypatch.setattr(activation, 'require_fence', lambda root: None)
    with pytest.raises(Exception, match='synthetic stop'):
        activation.apply_plan(path, ROOT, plan['plan_sha256'])
    assert snapshot(path) == before


@pytest.mark.parametrize('mutation,reason', [('candidate', 'current_pointer_or_versions'), ('baseline', 'baseline_instructions'),
                                           ('pin', 'custom_skill_version_pin'), ('defaults', 'custom_production_defaults')])
def test_custom_versions_candidate_scope_and_style_change_are_conflicts(tmp_path, seed, mutation, reason):
    path = legacy_database(tmp_path, seed)
    with activation.connect(path, write=True) as connection:
        if mutation == 'candidate':
            row = json.loads(connection.execute("SELECT document FROM creator_skill_versions WHERE skill_id='content-writing'").fetchone()[0])
            row.update(version=2, status='candidate')
            connection.execute('INSERT INTO creator_skill_versions VALUES(?,?,?)', ('content-writing', 2, activation.pack(row)))
        elif mutation == 'baseline':
            row = json.loads(connection.execute("SELECT document FROM creator_skill_versions WHERE skill_id='content-writing'").fetchone()[0])
            row['baseline_rules'][0]['instructions'].append('synthetic semantic change')
            row['sha256'] = seed[0]._release_hash(row)
            connection.execute("UPDATE creator_skill_versions SET document=? WHERE skill_id='content-writing'", (activation.pack(row),))
        else:
            row = json.loads(connection.execute('SELECT document FROM creator_profiles').fetchone()[0])
            if mutation == 'pin':
                row['skill_versions']['content-writing'] = 7
            else:
                row['default_skills']['poster'] = ['content-writing']
            connection.execute('UPDATE creator_profiles SET document=?', (activation.pack(row),))
        connection.commit()
    before = snapshot(path); plan = read_plan(path, seed)
    assert any(reason in conflict['reason'] for conflict in plan['conflicts'])
    assert snapshot(path) == before


def test_busy_or_changed_preview_refuses_apply_without_modifying_any_rows(tmp_path, seed, monkeypatch):
    path = legacy_database(tmp_path, seed); plan = read_plan(path, seed)
    monkeypatch.setattr(activation, 'require_fence', lambda root: None)
    with activation.connect(path, write=True) as connection:
        connection.execute('INSERT INTO creator_model_calls VALUES(?,?)', ('pending-call', activation.pack({'status': 'running'})))
        connection.commit()
    before = snapshot(path)
    with pytest.raises(ValueError, match='plan changed'):
        activation.apply_plan(path, ROOT, plan['plan_sha256'])
    assert snapshot(path) == before
    updated = read_plan(path, seed)
    assert updated['busy'][0]['id'] == 'pending-call'
    with pytest.raises(ValueError, match='active execution'):
        activation.apply_plan(path, ROOT, updated['plan_sha256'])
    assert snapshot(path) == before


def test_fence_and_missing_database_fail_without_creating_files(tmp_path, monkeypatch):
    state = tmp_path / '.local/workbench-deployment'; state.mkdir(parents=True)
    (state / 'admission.json').write_text('{"workers":true}', encoding='utf-8')
    (state / 'paused').write_text('synthetic fence', encoding='utf-8')
    with pytest.raises(ValueError, match='admission=false'):
        activation.require_fence(tmp_path)
    (state / 'admission.json').write_text('{"workers":false}', encoding='utf-8')
    activation.require_fence(tmp_path)
    missing = tmp_path / 'missing.sqlite'
    with pytest.raises(ValueError, match='already exist'):
        activation.apply_plan(missing, tmp_path, 'not-reviewed')
    assert not missing.exists()


def test_applied_receipt_does_not_hide_tampered_immutable_v2(tmp_path, seed, monkeypatch):
    path = legacy_database(tmp_path, seed); plan = read_plan(path, seed)
    monkeypatch.setattr(activation, 'require_fence', lambda root: None)
    activation.apply_plan(path, ROOT, plan['plan_sha256'])
    with activation.connect(path, write=True) as connection:
        row = json.loads(connection.execute("SELECT document FROM creator_skill_versions WHERE skill_id='content-writing' AND version=2").fetchone()[0])
        row['prompt'] += '\nunauthorized alteration'
        connection.execute("UPDATE creator_skill_versions SET document=? WHERE skill_id='content-writing' AND version=2", (activation.pack(row),))
        connection.commit()
    with pytest.raises(ValueError, match='immutable v2'):
        read_plan(path, seed)
