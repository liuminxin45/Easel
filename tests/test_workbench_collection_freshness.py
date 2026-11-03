"""The reading panel contains only observations from today's Beijing batch."""
import datetime as dt
from types import SimpleNamespace

import pytest

from easel_workbench.runtime import native_api
from easel_workbench.runtime.desk import Store, article_identity

@pytest.fixture
def store(tmp_path, monkeypatch):
    value=Store(tmp_path/'data/desk.sqlite')
    meta={'name':'Source','feed':'source-feed','builtin':False,'enabled':True}
    monkeypatch.setattr(value,'sources',lambda **_: {'source':meta,'empty':{**meta,'feed':'empty-feed'}})
    return value


def ingest(store, when, *, title='Exact original', run='batch', event='event-1'):
    article={'title':title,'body':'Original body','url':'https://example.test/'+event,
             'source_event_id':event,'published_at':'2026-10-01T00:00:00Z'}
    receipt=store.ingest({'schema_version':1,'source_job':'source','feed_id':'source-feed','run_id':run,
                         'run_at':when,'final_text':'Original batch '+run,'articles':[article]})
    return article_identity('source',article),receipt


def trends(store, monkeypatch, *, now='2026-11-03T12:10:00+08:00', outcome='completed', enabled=True, query=None):
    monkeypatch.setattr(native_api.time,'time',lambda:dt.datetime.fromisoformat(now).timestamp())
    latest={'status':outcome,'warnings':['NewsNow: missing source'],'error':'Provider failed',
            'finished_at':'2026-11-03T12:00:00+08:00'}
    state={'enabled':enabled,'heartbeat':{'state':'blocked','heartbeat':'2026-11-01T00:00:00Z'},
           'sources':[{'id':'source','last_task':latest,'last_success_at':'2026-11-01T00:00:00Z'}]}
    api=native_api.NativeApi.__new__(native_api.NativeApi)
    api._collection=lambda:SimpleNamespace(definitions=lambda:{
        'source':{'enabled':True,'label':'Source'},'empty':{'enabled':True,'label':'Empty source'}},status=lambda:state)
    api.store=store
    value=api._trends(SimpleNamespace(query_params=query or {}))
    assert latest['status']==outcome and latest['warnings']==['NewsNow: missing source']
    return value


def test_no_data_today_hides_old_sources_without_rewriting_history(store, monkeypatch):
    aid,_=ingest(store,'2026-11-02T15:59:59Z')
    value=trends(store,monkeypatch)
    assert value['day']=='2026-11-03' and value['timezone']=='Asia/Shanghai'
    assert value['trends']==[] and value['warnings']==[]
    old=store.article_day(source='source')
    assert old['day']=='2026-11-02' and old['items'][0]['id']==aid
    assert old['items'][0]['run_at']=='2026-11-02T15:59:59Z'


@pytest.mark.parametrize('outcome',['partial','failed','blocked','cancelled','queued','running','completed'])
def test_partial_actual_rows_survive_all_task_outcomes_without_notices(store,monkeypatch,outcome):
    ids=[ingest(store,'2026-11-03T08:01:00+08:00',run='one',event='one')[0],
         ingest(store,'2026-11-03T09:02:00+08:00',run='two',event='two')[0]]
    value=trends(store,monkeypatch,outcome=outcome,enabled=False)
    assert len(value['trends'])==1 and value['warnings']==[]
    group=value['trends'][0]
    assert group['platform']=='source' and {row['id'] for row in group['items']}==set(ids)
    assert group['ok'] and group['status']=='fresh' and not group['stale']
    assert group['error'] is None and group['warnings']==[]
    assert group['collection_status']==outcome


def test_recollected_article_uses_real_provenance_without_retimestamping_original(store,monkeypatch):
    aid,_=ingest(store,'2026-11-01T08:00:00+08:00',run='initial')
    same,receipt=ingest(store,'2026-11-03T09:00:00+08:00',run='today')
    assert aid==same and receipt['inserted']==0
    value=trends(store,monkeypatch)
    assert len(value['trends'])==1
    group=value['trends'][0]
    assert [row['id'] for row in group['items']]==[aid]
    assert group['fetched_at']=='2026-11-03T01:00:00.000Z'
    with store.connect() as c:
        original=dict(c.execute('SELECT * FROM articles WHERE id=?',(aid,)).fetchone())
        assert original['run_at']=='2026-11-01T08:00:00+08:00'
        assert original['published_at']=='2026-10-01T00:00:00Z'
        assert c.execute('SELECT count(*) FROM articles').fetchone()[0]==1
        assert c.execute('SELECT count(*) FROM provenance WHERE article_id=?',(aid,)).fetchone()[0]==2


def test_day_boundaries_use_beijing_timezone_not_publication_day(store,monkeypatch):
    yesterday,_=ingest(store,'2026-11-02T15:59:59.999Z',run='yesterday',event='yesterday')
    today,_=ingest(store,'2026-11-02T16:00:00Z',run='today',event='today')
    tomorrow,_=ingest(store,'2026-11-03T16:00:00Z',run='tomorrow',event='tomorrow')
    value=trends(store,monkeypatch)
    assert [row['id'] for row in value['trends'][0]['items']]==[today]
    assert yesterday!=today!=tomorrow
    next_day=trends(store,monkeypatch,now='2026-11-03T16:00:00Z')
    assert next_day['day']=='2026-11-04'
    assert [row['id'] for row in next_day['trends'][0]['items']]==[tomorrow]


def test_midnight_clears_yesterday_even_if_last_task_was_completed(store,monkeypatch):
    ingest(store,'2026-11-03T23:59:59+08:00')
    assert trends(store,monkeypatch,now='2026-11-03T23:59:59+08:00')['trends']
    assert trends(store,monkeypatch,now='2026-11-04T00:00:00+08:00')['trends']==[]


def test_legacy_current_row_without_provenance_is_visible_but_previous_day_is_not(store):
    aid,_=ingest(store,'2026-11-03T08:00:00+08:00')
    with store.connect() as c:c.execute('DELETE FROM provenance WHERE article_id=?',(aid,))
    assert [row['id'] for row in store.collected_day('source','2026-11-03')['items']]==[aid]
    assert store.collected_day('source','2026-11-04')['items']==[]


def test_day_query_is_read_only_and_preserves_explicit_history_query(store):
    aid,_=ingest(store,'2026-11-02T08:00:00+08:00')
    with store.connect() as c:
        original=[tuple(row) for row in c.execute('SELECT * FROM articles')]
    assert store.collected_day('source','2026-11-03')['total']==0
    assert store.article_day(source='source',day='2026-11-02')['items'][0]['id']==aid
    with store.connect() as c:
        assert [tuple(row) for row in c.execute('SELECT * FROM articles')]==original
    with pytest.raises(ValueError):store.collected_day('source','2026-02-30')


def test_selected_empty_source_and_limits_do_not_fall_back_to_other_sources(store,monkeypatch):
    ingest(store,'2026-11-03T08:00:00+08:00',event='one',run='one')
    ingest(store,'2026-11-03T09:00:00+08:00',event='two',run='two')
    assert trends(store,monkeypatch,query={'platforms':'empty'})['trends']==[]
    limited=trends(store,monkeypatch,query={'platforms':'source','limit':'1'})
    assert len(limited['trends'][0]['items'])==1
