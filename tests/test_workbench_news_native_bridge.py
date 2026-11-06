"""Native business/session integration on TEMP data; no real inference."""
import importlib.util
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import json
import pytest
from easel_workbench.runtime.desk import SOURCES
from easel_workbench.features.news_creation import NewsCreation
from easel_workbench.features.conversations.news_links import current

spec=importlib.util.spec_from_file_location('news_bridge_fixture',Path(__file__).with_name('test_workbench_chat_business.py'))
fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
business=fixture.business

def article(b):
    source=next(iter(SOURCES))
    b.store.ingest({'schema_version':1,'source_job':source,'feed_id':SOURCES[source]['feed'],'run_id':'TEMP-news-bridge','run_at':'2026-11-03T12:00:00+08:00','final_text':'TEMP','articles':[{'title':'真实新闻标题','body':'真实材料\n编辑备注不能替代用户要求','url':'https://source.test/article'}]})
    with b.store.connect() as c:return c.execute('SELECT id FROM articles LIMIT 1').fetchone()[0]

def test_concurrent_news_session_creation_reuses_one_original_session(business):
    aid=article(business)
    def create(i):return business.chat.create_session({'id':'news-create-'+str(i),'profile_id':'oil-pig','news_article_id':aid})
    with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(create,range(8)))
    ids={r['session']['id'] for r in results};assert len(ids)==1
    with business.store.connect() as c:assert current(c,aid,'oil-pig')['id']==next(iter(ids))
    assert all(r['session']['source_article_id']==aid for r in results)
    assert create(0)==results[0]

def test_archive_requires_explicit_new_news_conversation(business):
    aid=article(business);session=business.chat.create_session({'id':'news-archive-create','profile_id':'oil-pig','news_article_id':aid})['session']
    business.chat.archive_session(session['id'],{'id':'archive-news','expected_revision':session['revision'],'archived':True})
    with pytest.raises(ValueError):business.chat.create_session({'id':'news-after-archive','profile_id':'oil-pig','news_article_id':aid})
    fresh=business.chat.create_session({'id':'news-new-explicit','profile_id':'oil-pig','news_article_id':aid,'news_new_session':True})['session']
    assert fresh['id']!=session['id']

@pytest.mark.parametrize('intent',['discuss','produce'])
def test_native_prompt_uses_selected_materials_and_original_skill_only(business,intent):
    aid=article(business);service=NewsCreation(business.box);context=service.context(aid,'oil-pig')
    creation={k:context[k] for k in ('catalog_revision','profile_revision','source_revision')}
    creation.update(intent=intent,note='原话\n不得改变')
    if intent=='produce':creation.update(format='poster',style=next(p['components'] for p in context['packs'] if p['id']=='oil-pig-simple'))
    value={'sessionId':'test-chat','turnId':'news-native-'+intent,'message':'本次明确请求','context':{'article_id':aid,'profile_id':'oil-pig','creation':creation,**({'skill_id':'oil-pig-poster','action_id':'native'} if intent=='produce' else {})}}
    prepared=business.prepare(value)
    assert prepared['snapshot'] is None and prepared['work'] is None
    assert '原话\n不得改变' in prepared['actual_prompt']
    # Production appends its output contract after the exact attachment JSON.
    attached=json.JSONDecoder().raw_decode(prepared['actual_prompt'].split('## 本轮附件\n',1)[1])[0]
    assert attached and all(Path(item['path']).is_file() for item in attached)
    assert all(Path(item['path']).parent==business.root/'outputs/_sessions/inputs'/value['turnId'] for item in attached)
    assert ('请执行 /oil-pig-poster' in prepared['actual_prompt'])==(intent=='produce')
    manifest=json.loads((business.root/'outputs/_sessions/inputs'/value['turnId']/'manifest.json').read_text(encoding='utf-8'))
    assert manifest['creation']==creation|{'style':creation.get('style',{})}
    if intent=='discuss':assert '不制作文件' in prepared['actual_prompt']

def test_news_production_does_not_escalate_a_readonly_native_session(business):
    aid=article(business)
    with business.store.connect() as c:
        session=business.chat._session(c,'test-chat');session['runtime']='codex';session['execution_settings']['runtime']='codex';session['execution_settings']['sandbox']='read-only';business.chat._put_session(c,session)
    with pytest.raises(ValueError,match='只读'):
        business.prepare({'sessionId':'test-chat','turnId':'readonly-news','message':'制作','context':{'article_id':aid,'creation':{'intent':'produce'},'skill_id':'content-production'}})
    assert not (business.root/'outputs/_sessions/inputs/readonly-news').exists()
