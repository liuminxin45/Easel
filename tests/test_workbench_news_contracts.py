"""Exercise the actual background boundaries with all old skills unavailable."""
import json
from types import SimpleNamespace

import pytest

from easel_workbench.features.collection import news_contracts
from easel_workbench.features.skills.snapshots import SnapshotResolver
from easel_workbench.runtime import task_runtime, news_overviews, watcha_pipeline, collection_model
from easel_workbench.runtime.capability_contracts import resource_text
from easel_workbench.runtime.desk import Store
from easel_workbench import readonly_runner


@pytest.fixture
def retired(tmp_path, monkeypatch):
    def reject(*args, **kwargs):
        raise AssertionError('Background news must not resolve a retired or production skill')
    monkeypatch.setattr(SnapshotResolver, 'resolve', reject)
    from easel_workbench.infrastructure.storage.schema import initialize_creator
    with Store(tmp_path/'data/desk.sqlite').connect() as c:
        initialize_creator(c)
        profile={'id':'oil-pig','name':'TEMP画像','revision':1,'active':True,
                 'default_skills':{'news_enhancement':['topic-research']},'identity':'事实与判断分开'}
        c.execute('INSERT INTO creator_profiles VALUES(?,?,?)',('oil-pig',1,json.dumps(profile)))
    return tmp_path


def test_live_background_contracts_ignore_retired_profile_defaults_and_keep_exact_receipt(retired):
    root=retired
    from easel_workbench.features.profiles.service import read_profile
    box=task_runtime.runtime_box(root)
    with box.store.connect() as c:
        profile=read_profile(c,'oil-pig')
    before=profile.copy()
    prefix,binding=task_runtime.named_prompt(root,'news_enhancement',{'source':'TEMP'})
    assert binding['skills']==[] and readonly_runner.project_snapshot(binding)
    assert 'topic-research' not in prefix
    for name in news_contracts.NAMES:
        text=resource_text(binding,name)
        assert text and news_contracts.REFERENCES.joinpath(name).read_bytes().decode('utf-8-sig')==text
    prompt,bound=task_runtime.contract_prompt(root,'news_enhancement','references/news-summary.md',[])
    assert '一句中文' in prompt and news_contracts.is_snapshot(bound)
    cid=task_runtime.begin_call(root,'news_enhancement',[],prompt,snapshot=bound)
    task_runtime.finish_call(root,cid,'completed',{'items':[]})
    with box.store.connect() as c:
        record=json.loads(c.execute('SELECT document FROM creator_model_calls WHERE id=?',(cid,)).fetchone()[0])
        assert record['active_skills']==[] and record['snapshot']==bound and record['status']=='completed'
        assert read_profile(c,'oil-pig')==before
    changed={**binding,'prompt_text':'tampered'}
    assert not readonly_runner.project_snapshot(changed)


def test_watcha_uses_internal_contract_with_frozen_interest_and_candidates(retired):
    result=watcha_pipeline.editorial_prompt([{'event_id':'event-1'}],{'version':'exact-interest'},[{'title':'recent'}],retired)
    assert 'exact-interest' in result and 'event-1' in result and 'recent' in result
    assert '{profile_json}' not in result and 'reading_summary' in result


def test_screening_real_model_boundary_records_contract_and_reuses_response(retired):
    folder=retired/'task';calls=[]
    def fake_http(request,timeout):
        body=json.loads(request.data);calls.append(body)
        return {'choices':[{'message':{'content':json.dumps({'annotations':[]})}}]}
    cfg={'enabled':True,'backend':'openai_compatible','base_url':'http://127.0.0.1:9',
         'model':'fixture','api_key_required':False}
    for _ in range(2):
        assert collection_model.invoke('准确筛选合同',{'candidates':[]},folder,root=retired,config=cfg,transport=fake_http)=={'annotations':[]}
    assert len(calls)==1
    with Store(retired/'data/desk.sqlite').connect() as c:
        rows=c.execute('SELECT document FROM creator_model_calls').fetchall()
    assert len(rows)==1 and json.loads(rows[0][0])['snapshot']['execution_contract']['id']=='background-news'


def test_titles_reach_native_boundary_without_skill_resolver(retired,monkeypatch):
    calls=[]
    def run(binding,args,**kwargs):
        assert readonly_runner.project_snapshot(binding)
        calls.append(binding)
        output={'items':[{'id':'a','summary':'这个开源工具可以帮助用户整理研究笔记和相关资料。'}]}
        kwargs['cwd'].joinpath('answer.json').write_text(json.dumps(output),encoding='utf8')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(readonly_runner,'run',run)
    assert news_overviews.analyze([{'id':'a','title':'Widget','body':'Organize research notes','url':'https://example.test','source_job':'product-hunt'}],retired)['a'].endswith('。')
    assert len(calls)==1
    with Store(retired/'data/desk.sqlite').connect() as c:
        row=json.loads(c.execute('SELECT document FROM creator_model_calls').fetchone()[0])
    assert row['status']=='completed' and row['active_skills']==[]


def test_weekly_contract_still_loads_after_user_skill_retirement(retired):
    from easel_workbench.runtime import weekly_periodical
    prompt,binding=task_runtime.named_prompt(retired,'news_enhancement',{'operation':'weekly-normalize','items':[]})
    contract=resource_text(binding,'weekly-normalize.md')
    assert '每个输入 id 精确出现一次' in contract and 'theme' in contract
    assert weekly_periodical.SOURCE=='ruanyf-weekly' and binding['skills']==[]


def test_actual_title_queue_persists_sentences_for_both_native_feed_projections(retired,monkeypatch):
    store=Store(retired/'data/desk.sqlite');service=news_overviews.Overviews(store,retired)
    with store.connect() as c:
        for aid,source in [('hn','hacker-news'),('ph','product-hunt')]:
            c.execute('INSERT INTO articles(id,source_job,title,body,url,run_at,run) VALUES(?,?,?,?,?,?,?)',
                      (aid,source,'Widget','A research note tool','https://example.test/'+aid,'2026-11-06T09:30:00+08:00','run'))
    calls=[]
    def native(binding,args,**kwargs):
        assert news_contracts.is_snapshot(binding);calls.append(binding)
        output={'items':[{'id':aid,'summary':'这个开源工具可以帮助用户整理研究笔记和相关资料。'} for aid in ('hn','ph')]}
        kwargs['cwd'].joinpath('answer.json').write_text(json.dumps(output),encoding='utf8')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(readonly_runner,'run',native)
    assert service.tick(sources=['hacker-news','product-hunt'],day='2026-11-06')==2
    for source in ('hacker-news','product-hunt'):
        original=store.collected_day(source,'2026-11-06')['items']
        projected=news_overviews.trend_titles(original,retired)
        assert len(projected)==1 and projected[0]['title'].endswith('。') and original[0]['title']=='Widget'
    assert service.tick(sources=['hacker-news','product-hunt'],day='2026-11-06')==0
    assert len(calls)==1
