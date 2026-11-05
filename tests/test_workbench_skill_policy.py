"""Private native creation exposes two formats and rejects retired skills."""
from pathlib import Path
import importlib.util
import pytest

from easel_workbench.skills import RETIRED_EASEL_SKILLS, require_selection, supports_task

spec=importlib.util.spec_from_file_location('policy_business_fixture',Path(__file__).with_name('test_workbench_chat_business.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
business=fixture.business


def test_formats_resolve_to_their_own_skills_and_no_independent_hidden_checker(business):
    poster=business.creator.resolve(task='poster')
    article=business.creator.resolve(task='article')
    assert [s['id'] for s in poster['skills']]==['oil-pig-poster']
    assert [s['id'] for s in article['skills']]==['oil-pig-article']
    assert poster['active_skill_ids']==['oil-pig-poster']
    assert article['active_skill_ids']==['oil-pig-article']


def test_changes_require_an_explicit_format_and_preserve_the_selected_one(business):
    with pytest.raises(ValueError,match='请选择'):
        business.creator.resolve(task='change')
    for sid in ('oil-pig-poster','oil-pig-article'):
        result=business.creator.resolve(task='change',skill_refs=[{'id':sid}])
        assert [s['id'] for s in result['skills']]==[sid]


def test_wrong_format_and_retired_skills_are_rejected_before_creating_a_call(business):
    with pytest.raises(ValueError,match='不适用于'):
        business.creator.resolve(task='article',skill_refs=[{'id':'oil-pig-poster'}])
    for sid in ('content-production','content-writing','image-production','delivery-review',
                'topic-research','reference-analysis','publication-analysis'):
        assert sid in RETIRED_EASEL_SKILLS
        with pytest.raises(ValueError,match='已撤下'):
            business.creator.resolve(task='poster',skill_refs=[{'id':sid}])
    with business.store.connect() as c:
        exists=c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='creator_model_calls'").fetchone()
        assert not exists or c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0]==0


def test_image_uses_poster_skill_but_article_cannot_satisfy_it():
    assert supports_task({'id':'oil-pig-poster','tasks':['poster','change']},'image')
    assert not supports_task({'id':'oil-pig-article','tasks':['article','change']},'image')
    require_selection('image',['oil-pig-poster'])
    with pytest.raises(ValueError,match='油猪技能'):
        require_selection('image',['oil-pig-article'])
