"""Real command/queue paths using TEMP files, SQLite and no model workers."""
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

_fixture_spec = importlib.util.spec_from_file_location('isolated_skill_fixture', Path(__file__).with_name('test_workbench_skill_policy.py'))
_fixture_module = importlib.util.module_from_spec(_fixture_spec)
_fixture_spec.loader.exec_module(_fixture_module)
runtime = _fixture_module.runtime
from easel_workbench.runtime import task_runtime, work_discussions
from easel_workbench.runtime.learning_service import LearningService
from easel_workbench.runtime.studio_service import StudioService
from easel_workbench.runtime.toolbox_store import Toolbox


@pytest.fixture
def commands(runtime):
    box = Toolbox(runtime.store, root=runtime.root)
    runtime.box = box
    box.creator = runtime
    box.studio = StudioService(box, project=runtime.project)
    box.learning = LearningService(box)
    relative = '资料/风格研究/隔离参考.txt'
    path = runtime.project / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = '隔离原话：说明具体事实，保留来源，不把反馈直接改成长期规则。'.encode('utf-8')
    path.write_bytes(raw)
    evidence = {'id': 'fixture-evidence', 'kind': 'sample', 'title': '隔离参考',
                'sha256': hashlib.sha256(raw).hexdigest(), 'available': True,
                'locators': [{'kind': 'file', 'path': relative}]}
    with box.store.connect() as c:
        box.learning._put(c, 'learning_evidence', evidence)
    return box


def candidate(box, sid):
    before = box.creator.detail('skill', sid)
    return box.creator.command({'id': 'candidate-' + sid, 'action': 'skill-draft', 'skill_id': sid,
                               'base_version': before['version'], 'prompt': before['prompt'] + '\nExplicit candidate method.',
                               'reason': 'TEMP candidate'})['result']['skill']


def selection(sid, version=1, trial=False):
    return {'profile_id': 'oil-pig', 'profile_revision': 1,
            'skills': [{'id': sid, 'version': version}], 'trial': trial}


def request(action, operation, sid, *, version=1, trial=False):
    value = {'id': operation, 'action': action, 'creator': selection(sid, version, trial)}
    if action == 'reference-analyze':
        value['evidence_id'] = 'fixture-evidence'
    else:
        value.update(skill_id='content-writing', evidence_ids=['fixture-evidence'])
    return value


def payload(box, task_id):
    with box.store.connect() as c:
        row = c.execute('SELECT payload FROM learning_analysis_queue WHERE id=?', (task_id,)).fetchone()
        return json.loads(row['payload'])


@pytest.mark.parametrize('action,sid,task', [
    ('reference-analyze', 'reference-analysis', 'reference'),
    ('experience-organize', 'experience-distillation', 'learning'),
])
def test_candidate_version_and_trial_reach_actual_queue(commands, action, sid, task):
    candidate(commands, sid)
    value = request(action, 'queue-candidate', sid, version=2, trial=True)
    result = commands.creator.command(value)['result']
    frozen = payload(commands, result['task_id'])
    snapshot = frozen['creator_snapshot']
    assert snapshot['task'] == task
    assert snapshot['trial'] is True
    assert [(s['id'], s['version'], s['status']) for s in snapshot['skills']] == [(sid, 2, 'candidate')]
    assert frozen['manual'] is True and result['model_calls'] == 0
    assert frozen.get('members', [{}])[0].get('text', frozen.get('content'))
    if task == 'learning':
        assert frozen['skill_id'] == 'content-writing' and frozen['base_version'] == 1
        assert 'content-writing' not in snapshot['active_skill_ids']
        assert frozen['base_prompt'] != snapshot['skills'][0]['prompt']
    with commands.store.connect() as c:
        assert c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0] == 0


@pytest.mark.parametrize('action,sid', [
    ('reference-analyze', 'reference-analysis'), ('experience-organize', 'experience-distillation'),
])
def test_candidate_without_explicit_trial_never_queues(commands, action, sid):
    candidate(commands, sid)
    with pytest.raises(ValueError, match='明确选择本次试用'):
        commands.creator.command(request(action, 'not-trial', sid, version=2))
    with commands.store.connect() as c:
        assert c.execute('SELECT count(*) FROM learning_analysis_queue').fetchone()[0] == 0


@pytest.mark.parametrize('action,sid,function', [
    ('reference-analyze', 'reference-analysis', task_runtime.enqueue_reference),
    ('experience-organize', 'experience-distillation', task_runtime.enqueue_experience),
])
def test_same_operation_receipt_does_not_reresolve_or_reread(commands, monkeypatch, action, sid, function):
    value = request(action, 'same-operation', sid)
    with commands.store.connect() as c:
        first = function(commands, value, c)
    before = payload(commands, first['task_id'])
    def forbidden(*args, **kwargs):
        raise AssertionError('An accepted operation must return its frozen receipt.')
    monkeypatch.setattr(commands.creator, 'resolve', forbidden)
    monkeypatch.setattr(commands.creator, '_skill', forbidden)
    monkeypatch.setattr(commands.learning, 'evidence_content', forbidden)
    with commands.store.connect() as c:
        assert function(commands, value, c) == first
        assert c.execute('SELECT count(*) FROM learning_analysis_queue').fetchone()[0] == 1
    assert payload(commands, first['task_id']) == before
    with commands.store.connect() as c, pytest.raises(ValueError, match='不能改变'):
        function(commands, {**value, 'goal': 'A changed goal'}, c)


@pytest.mark.parametrize('action,sid', [
    ('reference-analyze', 'reference-analysis'), ('experience-organize', 'experience-distillation'),
])
def test_different_executor_version_never_reuses_another_queue_input(commands, action, sid):
    candidate(commands, sid)
    first = commands.creator.command(request(action, 'version-one', sid))['result']
    second = commands.creator.command(request(action, 'version-two', sid, version=2, trial=True))['result']
    assert first['task_id'] != second['task_id']
    assert payload(commands, first['task_id'])['scope_signature'] != payload(commands, second['task_id'])['scope_signature']
    same = commands.creator.command(request(action, 'version-two-again', sid, version=2, trial=True))['result']
    assert same['task_id'] == second['task_id']
    with commands.store.connect() as c:
        assert c.execute('SELECT count(*) FROM learning_analysis_queue').fetchone()[0] == 2


def test_target_skill_cannot_impersonate_experience_executor(commands):
    with pytest.raises(ValueError, match='不适用于本次任务'):
        commands.creator.command(request('experience-organize', 'wrong-executor', 'content-writing'))
    with commands.store.connect() as c:
        assert c.execute('SELECT count(*) FROM learning_analysis_queue').fetchone()[0] == 0


@pytest.mark.parametrize('target', [[], {}, True, 1, None, '', 'invalid/path'])
def test_experience_target_requires_stable_skill_identity(commands, target):
    value = request('experience-organize', 'invalid-target', 'experience-distillation')
    value['skill_id'] = target
    with pytest.raises(ValueError, match='标识无效'):
        commands.creator.command(value)
    with commands.store.connect() as c:
        assert c.execute('SELECT count(*) FROM learning_analysis_queue').fetchone()[0] == 0


@pytest.mark.parametrize('action,sid', [
    ('reference-analyze', 'reference-analysis'), ('experience-organize', 'experience-distillation'),
])
@pytest.mark.parametrize('goal', [1, ['a goal'], {'goal': 'unparsed'}])
def test_command_goal_is_validated_before_queueing(commands, action, sid, goal):
    value = request(action, 'invalid-goal', sid)
    value['goal'] = goal
    with pytest.raises(ValueError):
        commands.creator.command(value)
    with commands.store.connect() as c:
        assert c.execute('SELECT count(*) FROM learning_analysis_queue').fetchone()[0] == 0


@pytest.mark.parametrize('trial', [1, 'true', []])
def test_command_trial_flag_uses_the_same_boolean_contract(commands, trial):
    value = request('reference-analyze', 'invalid-trial', 'reference-analysis')
    value['creator']['trial'] = trial
    with pytest.raises(ValueError):
        commands.creator.command(value)


def seed_work(box):
    with box.store.connect() as c:
        c.execute('INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)', ('work', None, '合成作品', '完整原材料', 'old', 'old'))
        c.execute('INSERT INTO toolbox_work_options VALUES(?,?,?)', ('work', 'poster', 'auto'))
        c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,files,signature,status,created_at) VALUES(?,?,?,?,?,?,?,?)',
                  ('version', 'work', 'create', '原要求', '[]', 'legacy', 'completed', 'old'))
        box.studio._put(c, 'publications', {'id': 'publication', 'work_id': 'work', 'version_id': 'version',
                                          'status': 'published', 'channel_id': 'wechat', 'account': 'TEMP',
                                          'title': '合成作品', 'body': '完整原材料', 'images': [],
                                          'url': '', 'published_at': None}, True)


def test_analysis_service_chain_freezes_analysis_not_discuss(commands, monkeypatch):
    seed_work(commands)
    candidate(commands, 'publication-analysis')
    value = {'operation_id': 'analyze', 'action': 'analysis-start', 'publication_id': 'publication',
             'question': '这份合成作品有哪些有据观察？', 'creator': selection('publication-analysis', 2, True)}
    response = commands.studio.command(value)
    job_id = response['result']['job']['id']
    with commands.store.connect() as c:
        job = dict(c.execute('SELECT * FROM toolbox_jobs WHERE id=?', (job_id,)).fetchone())
        frozen = json.loads(c.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?', (job_id,)).fetchone()[0])
        run = task_runtime.read_run(c, job_id)
        intent = commands.studio._get(c, 'analyses', 'analyze')
        assert job['kind'] == 'discuss' and job['status'] == 'queued'
        assert intent['creator_snapshot']['task'] == frozen['creator_snapshot']['task'] == run['snapshot']['task'] == 'analysis'
        assert intent['creator_snapshot']['snapshot_sha256'] == frozen['creator_snapshot']['snapshot_sha256'] == run['snapshot']['snapshot_sha256']
        assert run['snapshot']['trial'] is True
        assert [(row['id'], row['version']) for row in run['snapshot']['skills']] == [('publication-analysis', 2)]
        assert [step['id'] for step in run['steps']] == ['freeze', 'production', 'capture']
        raw = c.execute('SELECT document FROM creator_task_runs WHERE id=?', (job_id,)).fetchone()[0]
    def forbidden(*args, **kwargs):
        raise AssertionError('Completed command receipts do not resolve new defaults.')
    monkeypatch.setattr(commands.creator, 'resolve', forbidden)
    assert commands.studio.command(value) == response
    with commands.store.connect() as c:
        assert c.execute('SELECT document FROM creator_task_runs WHERE id=?', (job_id,)).fetchone()[0] == raw
        assert c.execute("SELECT count(*) FROM toolbox_jobs WHERE kind='discuss'").fetchone()[0] == 1
        assert c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0] == 0


def test_analysis_pending_intent_reuses_frozen_snapshot_after_candidate_publish(commands, monkeypatch):
    seed_work(commands)
    candidate(commands, 'publication-analysis')
    value = {'operation_id': 'pending-analyze', 'action': 'analysis-start', 'publication_id': 'publication',
             'question': '这份合成作品有哪些有据观察？', 'creator': selection('publication-analysis', 2, True)}
    upload = commands.upload
    def interrupted(*args, **kwargs):
        raise OSError('TEMP attachment interruption after intent freeze')
    monkeypatch.setattr(commands, 'upload', interrupted)
    with pytest.raises(OSError, match='TEMP attachment'):
        commands.studio.command(value)
    with commands.store.connect() as c:
        intent = commands.studio._get(c, 'analyses', 'pending-analyze')
        original = intent['creator_snapshot']
        assert original['trial'] is True
    monkeypatch.setattr(commands, 'upload', upload)
    commands.creator.command({'id': 'publish-during-pause', 'action': 'skill-publish', 'skill_id': 'publication-analysis',
                              'version': 2, 'expected_published_version': 1, 'confirm': True})
    def forbidden(*args, **kwargs):
        raise AssertionError('An accepted analysis intent must not resolve skills again.')
    monkeypatch.setattr(commands.creator, 'resolve', forbidden)
    response = commands.studio.command(value)
    with commands.store.connect() as c:
        run = task_runtime.read_run(c, response['result']['job']['id'])
        assert run['snapshot'] == original


def test_analysis_cannot_reown_legacy_work_via_top_level_profile(commands):
    seed_work(commands)
    profile = commands.creator.command({'id': 'another-profile', 'action': 'profile-save',
        'profile_id': 'another-author', 'base_revision': 0, 'document': {'name': '另一个合成作者'}})['result']['profile']
    with pytest.raises(ValueError, match='画像'):
        commands.studio.command({'operation_id': 'wrong-owner', 'action': 'analysis-start',
            'publication_id': 'publication', 'question': '只读复盘', 'profile_id': profile['id']})
    with commands.store.connect() as c:
        assert c.execute("SELECT count(*) FROM toolbox_jobs WHERE kind='discuss'").fetchone()[0] == 0


@pytest.mark.parametrize('creative', [[], ['invalid'], 1, {'creator': []}, {'creator': ['invalid']}, {'creator': 1}, {'creator': None}])
def test_discussion_creative_type_is_rejected_before_attribute_access(commands, creative):
    seed_work(commands)
    with pytest.raises(ValueError):
        work_discussions.enqueue(commands, 'work', {'id': 'bad-creative', 'revision': 0,
            'text': '只读讨论', 'files': [], 'creative': creative})


def test_internal_execution_task_is_part_of_analysis_idempotency(commands):
    seed_work(commands)
    value = {'id': 'read-only', 'revision': 0, 'text': '只读讨论', 'files': [],
             'creative': {'creator': selection('topic-research')}}
    work_discussions.enqueue(commands, 'work', value)
    with commands.store.connect() as c:
        assert c.execute("SELECT signature FROM toolbox_jobs WHERE id='read-only'").fetchone()[0] == task_runtime.packed({'discussion': 'work', 'request': value})
    with pytest.raises(ValueError, match='同一操作'):
        work_discussions.enqueue(commands, 'work', value, execution_task='analysis')


def test_internal_prepared_snapshot_has_hash_task_and_selection_guards(commands):
    snapshot = commands.creator.resolve(task='analysis')
    selected = selection('publication-analysis')
    copy = task_runtime.validated_snapshot(snapshot, 'analysis', selected)
    assert copy == snapshot and copy is not snapshot and copy['skills'] is not snapshot['skills']
    with pytest.raises(ValueError, match='任务不一致'):
        task_runtime.validated_snapshot(snapshot, 'discuss', selected)
    with pytest.raises(ValueError, match='字节已变化'):
        task_runtime.validated_snapshot({**snapshot, 'prompt_text': 'Changed input'}, 'analysis', selected)
    with pytest.raises(ValueError, match='技能版本不一致'):
        task_runtime.validated_snapshot(snapshot, 'analysis', selection('publication-analysis', 2))
    with pytest.raises(ValueError, match='画像修订不一致'):
        task_runtime.validated_snapshot(snapshot, 'analysis', {**selected, 'profile_revision': 2})
    with pytest.raises(ValueError, match='试用身份不一致'):
        task_runtime.validated_snapshot(snapshot, 'analysis', selection('publication-analysis', trial=True))


def test_public_command_snapshot_field_cannot_inject_internal_context(commands):
    injected = commands.creator.resolve(task='analysis')
    value = request('reference-analyze', 'public-field', 'reference-analysis')
    value['creator_snapshot'] = injected
    result = commands.creator.command(value)['result']
    actual = payload(commands, result['task_id'])['creator_snapshot']
    assert actual['task'] == 'reference'
    assert [(row['id'], row['version']) for row in actual['skills']] == [('reference-analysis', 1)]
    value = request('reference-analyze', 'nested-field', 'reference-analysis')
    value['creator']['creator_snapshot'] = injected
    with pytest.raises(ValueError, match='执行技能选择无效'):
        commands.creator.command(value)


def test_public_discussion_creative_snapshot_field_is_not_an_internal_keyword(commands):
    seed_work(commands)
    injected = commands.creator.resolve(task='analysis')
    value = {'id': 'public-creative-field', 'revision': 0, 'text': '只读讨论', 'files': [],
             'creator_snapshot': injected,
             'creative': {'creator': selection('topic-research'), 'creator_snapshot': injected}}
    result = work_discussions.enqueue(commands, 'work', value)
    with commands.store.connect() as c:
        actual = task_runtime.read_run(c, result['id'])['snapshot']
        assert actual['task'] == 'discuss'
        assert [(row['id'], row['version']) for row in actual['skills']] == [('topic-research', 1)]


def test_discussion_preserves_future_recipe_without_compiling_production_catalog(commands, monkeypatch):
    from easel_workbench.runtime.creative_recipes import CreativeRecipes
    seed_work(commands)
    candidate(commands, 'topic-research')
    assert not (commands.studio.project / '规范/创作方案/目录.json').exists()
    def forbidden(*args, **kwargs):
        raise AssertionError('A read-only discussion cannot compile a production recipe.')
    monkeypatch.setattr(CreativeRecipes, 'context', forbidden)
    recipe = {'pack_id': 'missing-production-pack', 'overrides': {},
              'prompt_text': '保留供日后明确制作时使用的方案。'}
    value = {'id': 'candidate-discuss-with-recipe', 'revision': 0, 'text': '先讨论选题，不开始制作', 'files': [],
             'creative': {'creator': selection('topic-research', 2, True), 'recipe': recipe}}
    result = work_discussions.enqueue(commands, 'work', value)
    with commands.store.connect() as c:
        job = c.execute('SELECT kind,status FROM toolbox_jobs WHERE id=?', (result['id'],)).fetchone()
        frozen = json.loads(c.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?', (result['id'],)).fetchone()[0])
        run = task_runtime.read_run(c, result['id'])
        assert tuple(job) == ('discuss', 'queued')
        assert run['snapshot']['task'] == 'discuss' and run['snapshot']['trial'] is True
        assert [(row['id'], row['version']) for row in run['snapshot']['skills']] == [('topic-research', 2)]
        assert run['snapshot']['active_skill_ids'] == ['topic-research']
        assert frozen['creation_options']['recipe'] == recipe
        assert frozen['studio_context']['creation_options']['recipe'] == recipe
        assert 'prompt_preview' not in frozen['studio_context']
        assert c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0] == 0
