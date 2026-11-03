"""Retired authoring cannot queue; exact historical receipts and versions survive."""
import importlib.util
import json
from pathlib import Path

import pytest
from easel_workbench.features.skills.retirement import RETIRED_ACTIONS,SkillFeatureRetired,preview,apply
from easel_workbench.features.skills.records import packed,digest,CreatorConflict

spec=importlib.util.spec_from_file_location('retirement_fixtures',Path(__file__).with_name('test_workbench_skill_commands.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
runtime,commands=fixtures.runtime,fixtures.commands


@pytest.mark.parametrize('action',sorted(RETIRED_ACTIONS))
def test_retired_new_command_is_gone_without_operation_or_model_or_queue(commands,action):
    with pytest.raises(SkillFeatureRetired) as error:
        commands.creator.command({'id':'new-retired-operation','action':action})
    assert error.value.status_code==410 and error.value.feature=='private_skill_management'
    with commands.store.connect() as c:
        assert c.execute('SELECT count(*) FROM creator_operations').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM learning_analysis_queue').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0]==0


def test_historical_retired_receipt_is_read_without_resync_or_new_side_effect(commands,monkeypatch):
    value={'id':'saved-publish','action':'skill-publish','skill_id':'content-writing'}
    result={'id':'saved-publish','status':'completed','result':{'skill':{'id':'content-writing','version':1},'source_sync':{'id':'old-outbox','status':'pending'}}}
    with commands.store.connect() as c:
        c.execute('INSERT INTO creator_operations VALUES(?,?,?,?)',(value['id'],digest(packed(value)),packed(result),'old-time'))
        before=[tuple(row) for row in c.execute('SELECT * FROM creator_operations')]
    from easel_workbench import project_skill_sync
    monkeypatch.setattr(project_skill_sync,'finish_response',lambda *args:pytest.fail('historical receipt must not restart filesystem delivery'))
    assert commands.creator.command(value)==result
    with pytest.raises(CreatorConflict):commands.creator.command({**value,'version':2})
    with commands.store.connect() as c:
        assert [tuple(row) for row in c.execute('SELECT * FROM creator_operations')]==before


def legacy_profile(runtime):
    with runtime.store.connect() as c:
        profile=runtime._profile(c,'oil-pig');profile['revision']+=1
        profile['default_skills']['learning']=['experience-distillation']
        profile.setdefault('skill_versions',{}).update({'experience-distillation':1,'content-writing':1})
        profile.setdefault('task_skill_versions',{}).update({'learning':{'experience-distillation':1},'poster':{'content-writing':1}})
        runtime._put_profile(c,profile)
    return profile


def test_exact_plan_adds_profile_revision_without_rewriting_old_versions_or_history(runtime):
    before=legacy_profile(runtime)
    with runtime.store.connect() as c:
        history=[tuple(r) for r in c.execute('SELECT * FROM creator_profile_history ORDER BY revision')]
        versions=[tuple(r) for r in c.execute('SELECT * FROM creator_skill_versions ORDER BY skill_id,version')]
    plan=preview(runtime);assert len(plan['changes'])==1
    receipt=apply(runtime,plan['plan_sha256']);assert receipt['profiles'][0]['revision']==before['revision']+1
    current=runtime.detail('profile','oil-pig')
    assert 'learning' not in current['default_skills'] and 'skill_versions' not in current
    assert 'task_skill_versions' not in current
    assert apply(runtime,plan['plan_sha256'])==receipt and preview(runtime)['changes']==[]
    with runtime.store.connect() as c:
        assert [tuple(r) for r in c.execute('SELECT * FROM creator_profile_history WHERE revision<=? ORDER BY revision',(before['revision'],))]==history
        assert [tuple(r) for r in c.execute('SELECT * FROM creator_skill_versions ORDER BY skill_id,version')]==versions
    assert runtime.detail('profile','oil-pig',before['revision'])['default_skills']['learning']==['experience-distillation']


def test_stale_plan_refuses_current_profile_changes(runtime):
    profile=legacy_profile(runtime);plan=preview(runtime)
    with runtime.store.connect() as c:
        profile['revision']+=1;profile['name']='Concurrent profile revision';runtime._put_profile(c,profile)
    with pytest.raises(ValueError,match='已变化'):apply(runtime,plan['plan_sha256'])
    assert runtime.detail('profile','oil-pig')['name']=='Concurrent profile revision'
    assert runtime.detail('profile','oil-pig')['default_skills']['learning']==['experience-distillation']


def test_direct_enqueue_returns_known_historical_receipt_but_refuses_new_experience(commands):
    from easel_workbench.runtime import task_runtime
    value={'id':'historical-experience','goal':'old scope'}
    with commands.store.connect() as c:
        task_runtime.initialize(c)
        receipt={'signature':task_runtime.digest(value),'result':{'task_id':'original-task'}}
        c.execute('INSERT INTO creator_experience_receipts VALUES(?,?,?)',(value['id'],json.dumps(receipt),'historical-time'))
        assert task_runtime.enqueue_experience(commands,value,c)==receipt['result']
        with pytest.raises(SkillFeatureRetired):task_runtime.enqueue_experience(commands,{'id':'new-experience'},c)
