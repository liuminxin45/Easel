"""TEMP-only regressions for task scopes, exact releases and launch projections."""
import json
from types import SimpleNamespace

import pytest

from easel_workbench.runtime.creator_runtime import CreatorRuntime, packed
from easel_workbench.runtime.desk import Store
from easel_workbench.runtime import task_runtime
from easel_workbench.skills import launch_actions, supports_task, task_policy


@pytest.fixture
def runtime(tmp_path):
    project = tmp_path / 'content'
    definitions = (
        ('content-production', ['poster', 'article', 'change'], 'workflow'),
        ('content-writing', ['poster', 'article', 'change'], 'agent'),
        ('image-production', ['poster', 'image', 'article', 'change'], 'agent'),
        ('delivery-review', ['review', 'poster', 'article', 'change'], 'readonly-agent'),
        ('topic-research', ['research', 'discuss', 'news_enhancement'], 'agent'),
        ('reference-analysis', ['reference'], 'agent'),
        ('publication-analysis', ['analysis'], 'agent'),
        ('experience-distillation', ['learning'], 'readonly-agent'),
    )
    skills = []
    for sid, tasks, executor in definitions:
        entry = '.agents/skills/' + sid + '/SKILL.md'
        path = project / entry
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('---\nname: ' + sid + '\ndescription: A bounded test method.\n---\nTest method ' + sid + '.\n', encoding='utf-8')
        skills.append({'id': sid, 'name': sid, 'description': 'Test method',
                       'entry': entry, 'tasks': tasks, 'executor': executor, 'resources': [],
                       'input_contract': {'required': ['material']},
                       'output_contract': {'required': ['result']}})
    manifest = project / '.agents/skills/capabilities.json'
    manifest.write_text(json.dumps({'schema_version': 1, 'skills': skills}), encoding='utf-8')
    box = SimpleNamespace(root=tmp_path, store=Store(tmp_path / 'data/desk.sqlite'),
                          studio=SimpleNamespace(project=project))
    box.creator = CreatorRuntime(box)
    return box.creator


def refs(*ids):
    return [{'id': sid, 'version': 1} for sid in ids]


def published_variant(runtime, sid, tasks):
    with runtime.store.connect() as c:
        release = runtime._skill(c, sid, 1, False)
        for field in ('history', 'published_version', 'is_current'):
            release.pop(field, None)
        release.update(version=2, tasks=tasks, base_version=1)
        release['sha256'] = runtime._release_hash(release)
        c.execute('INSERT INTO creator_skill_versions VALUES(?,?,?)', (sid, 2, packed(release)))


def test_new_execution_rejects_wrong_scope_even_with_valid_producers(runtime):
    with pytest.raises(ValueError, match='不适用于本次任务'):
        runtime.resolve(task='poster', skill_refs=refs('content-writing', 'delivery-review', 'topic-research'))
    with runtime.store.connect() as c:
        assert not c.execute("SELECT name FROM sqlite_master WHERE name='creator_model_calls'").fetchone()


def test_candidate_trial_does_not_bypass_task_scope(runtime):
    detail = runtime.detail('skill', 'topic-research')
    candidate = runtime.command({'id': 'candidate', 'action': 'skill-draft', 'skill_id': 'topic-research',
                                 'base_version': 1, 'prompt': detail['prompt'] + '\nCandidate method.', 'reason': 'test'})['result']['skill']
    assert candidate['status'] == 'candidate'
    with pytest.raises(ValueError, match='不适用于本次任务'):
        runtime.resolve(task='article', skill_refs=refs('content-writing', 'delivery-review') +
                        [{'id': 'topic-research', 'version': 2}], allow_trial=True)


def test_image_uses_only_the_existing_independent_review_compatibility(runtime):
    result = runtime.resolve(task='image')
    assert [row['id'] for row in result['skills']] == ['image-production', 'delivery-review']
    assert result['skills'][1]['execution_role'] == 'reserved_independent'
    assert not supports_task({'id': 'other-checker', 'executor': 'readonly-agent', 'tasks': ['review']}, 'image')
    assert not supports_task({'id': 'delivery-review', 'executor': 'agent', 'tasks': ['review']}, 'image')


def test_safety_requirements_still_reject_missing_producer_or_review(runtime):
    with pytest.raises(ValueError, match='交付核验'):
        runtime.resolve(task='poster', skill_refs=refs('content-writing'))
    with pytest.raises(ValueError, match='写作或配图'):
        runtime.resolve(task='poster', skill_refs=refs('delivery-review', 'content-production'))


def test_workflow_is_frozen_as_program_entry_and_adds_no_model_skill(runtime):
    default = runtime.resolve(task='poster')
    assert 'content-production' not in [row['id'] for row in default['skills']]
    result = runtime.resolve(task='poster', skill_refs=refs('content-writing', 'delivery-review', 'content-production'))
    entry = result['skills'][-1]
    assert entry['execution_role'] == 'workflow_entry'
    assert 'content-production' not in result['active_skill_ids']
    assert entry['prompt'] not in result['prompt_text']
    assert '程序编排入口' in result['prompt_text']
    assert entry['prompt'].strip()  # complete immutable package remains inspectable
    with runtime.store.connect() as c:
        assert runtime._profile(c, 'oil-pig')['task_skill_versions']['poster'] == {
            'content-writing': 1, 'image-production': 1, 'delivery-review': 1}


def test_projection_metadata_never_changes_release_or_snapshot_bytes(runtime):
    before = runtime.resolve(task='article')
    with runtime.store.connect() as c:
        release_before = c.execute("SELECT document FROM creator_skill_versions WHERE skill_id='content-production'").fetchone()[0]
    bootstrap = runtime.bootstrap()
    skill = next(row for row in bootstrap['skills'] if row['id'] == 'content-production')
    detail = runtime.detail('skill', 'content-production', 1)
    assert skill['execution_kind'] == detail['execution_kind'] == 'workflow'
    assert skill['launch_actions'] == detail['launch_actions']
    assert bootstrap['task_policy']['poster']['entry_skills'] == ['content-production']
    assert bootstrap['task_policy']['article']['required_all'] == ['delivery-review', 'content-writing']
    assert 'video' not in bootstrap['task_policy']
    assert runtime.resolve(task='article') == before
    assert all('launch_actions' not in row and 'execution_kind' not in row for row in before['skills'])
    with runtime.store.connect() as c:
        assert c.execute("SELECT document FROM creator_skill_versions WHERE skill_id='content-production'").fetchone()[0] == release_before


def test_launches_derive_from_scope_and_executor_not_known_skill_identity():
    release = {'id': 'new-editor-method', 'tasks': ['article', 'reference'], 'executor': 'agent', 'status': 'candidate'}
    actions = launch_actions(release)
    assert [(row['task'], row['path']) for row in actions] == [
        ('article', '/articles/new'), ('reference', '/toolbox?section=research&pane=breakdown')]
    assert all('version' not in row and 'skill' not in row['path'] for row in actions)
    workflow = {**release, 'id': 'new-workflow', 'executor': 'workflow', 'status': 'published'}
    assert task_policy([workflow])['article']['entry_skills'] == ['new-workflow']
    assert not task_policy([release])['article']['entry_skills']
    assert not launch_actions({'id': 'easel-video', 'tasks': ['video'], 'executor': 'program'})
    assert not launch_actions({'id': 'research-only', 'tasks': ['research'], 'executor': 'agent'})


def test_invalid_profile_default_is_rejected_without_revision_change(runtime):
    before = runtime.detail('profile', 'oil-pig')
    with pytest.raises(ValueError, match='不适用于本次任务'):
        runtime.command({'id': 'bad-default', 'action': 'profile-save', 'profile_id': 'oil-pig',
                         'base_revision': before['revision'], 'document': {'default_skills': {'poster': ['topic-research']}}})
    assert runtime.detail('profile', 'oil-pig') == before


@pytest.mark.parametrize('field,value', [
    ('task_skill_versions', {'poster': {'content-writing': 2}}),
    ('skill_versions', {'content-writing': 2}),
])
def test_incompatible_exact_pin_is_rejected(runtime, field, value):
    published_variant(runtime, 'content-writing', ['article'])
    before = runtime.detail('profile', 'oil-pig')
    with pytest.raises(ValueError, match='不适用于本次任务'):
        runtime.command({'id': 'bad-pin', 'action': 'profile-save', 'profile_id': 'oil-pig',
                         'base_revision': before['revision'], 'document': {field: value}})
    assert runtime.detail('profile', 'oil-pig') == before


def test_publish_wrong_scope_rolls_back_pointer_event_and_profile(runtime):
    detail = runtime.detail('skill', 'topic-research')
    runtime.command({'id': 'draft', 'action': 'skill-draft', 'skill_id': 'topic-research', 'base_version': 1,
                     'prompt': detail['prompt'] + '\nRefined test.', 'reason': 'test'})
    before = runtime.detail('profile', 'oil-pig')
    with pytest.raises(ValueError, match='不适用于本次任务'):
        runtime.command({'id': 'bad-publish', 'action': 'skill-publish', 'skill_id': 'topic-research',
                         'version': 2, 'expected_published_version': 1, 'confirm': True,
                         'profile_id': 'oil-pig', 'profile_revision': before['revision'], 'tasks': ['poster']})
    assert runtime.detail('profile', 'oil-pig') == before
    assert runtime.detail('skill', 'topic-research', 2)['status'] == 'candidate'
    assert runtime.detail('skill', 'topic-research')['published_version'] == 1
    with runtime.store.connect() as c:
        assert not c.execute("SELECT 1 FROM creator_operations WHERE id='bad-publish'").fetchone()


def test_legacy_frozen_input_is_read_without_new_scope_validation(runtime):
    old = {'id': 'legacy-task', 'work_id': 'legacy-work', 'snapshot': {
        'task': 'poster', 'skills': [{'id': 'topic-research', 'tasks': ['research']}],
        'snapshot_sha256': 'historical-sha'}, 'status': 'unknown'}
    # Preserve formatting too: no deployment/backfill may rewrite frozen JSON.
    raw = json.dumps(old, indent=3)
    with runtime.store.connect() as c:
        task_runtime.initialize(c)
        c.execute('INSERT INTO creator_task_runs VALUES(?,?,?,?)', ('legacy-task', 'legacy-work', raw, 'old'))
    with runtime.store.connect() as c:
        result = task_runtime.freeze(c, runtime.box, 'legacy-work', 'legacy-task',
                                     {'creator': {'skills': refs('topic-research')}})
        assert result == old['snapshot']
        assert c.execute("SELECT document FROM creator_task_runs WHERE id='legacy-task'").fetchone()[0] == raw
