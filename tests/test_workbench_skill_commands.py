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
    # Seed a historical release internally; public authoring is retired.
    with box.store.connect() as c:
        return box.creator.propose(c,sid,before['version'],before['prompt']+'\nExplicit candidate method.',
                                   'TEMP historical candidate',operation_id='candidate-'+sid)



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










def test_target_skill_cannot_impersonate_experience_executor(commands):
    with pytest.raises(ValueError, match='已退役'):
        commands.creator.command(request('experience-organize', 'wrong-executor', 'content-writing'))
    with commands.store.connect() as c:
        assert c.execute('SELECT count(*) FROM learning_analysis_queue').fetchone()[0] == 0


@pytest.mark.parametrize('target', [[], {}, True, 1, None, '', 'invalid/path'])
def test_experience_target_requires_stable_skill_identity(commands, target):
    value = request('experience-organize', 'invalid-target', 'experience-distillation')
    value['skill_id'] = target
    with pytest.raises(ValueError, match='已退役'):
        commands.creator.command(value)
    with commands.store.connect() as c:
        assert c.execute('SELECT count(*) FROM learning_analysis_queue').fetchone()[0] == 0


@pytest.mark.parametrize('action,sid', [
    ('reference-analyze', 'reference-analysis'),
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
