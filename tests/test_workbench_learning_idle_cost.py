"""Actual idle worker cost and concurrent writers, on TEMP history only."""
import json
import sqlite3
import threading

import pytest

from easel_workbench.runtime.desk import Store, Connection, stamp
from easel_workbench.runtime.toolbox_store import Toolbox
from easel_workbench.runtime.studio_service import StudioService
from easel_workbench.runtime.learning_service import LearningService
from easel_workbench.runtime.learning_worker import LearningWorker
from easel_workbench.runtime import news_feedback
from easel_workbench.diagnostics import performance


@pytest.fixture
def service(tmp_path,monkeypatch):
    monkeypatch.setattr(news_feedback,'configuration',lambda:{'skill':str(tmp_path/'isolated-interest-ledger')})
    box=Toolbox(Store(tmp_path/'data/desk.sqlite'),tmp_path)
    studio=StudioService(box,project=tmp_path/'isolated-content');box.studio=studio
    s=LearningService(box,studio);box.learning=s
    now=stamp()
    with s.store.connect() as c:
        c.execute('INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)',('work',None,'Exact source title','Exact original material',now,now))
        for i in range(600):
            c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,candidate_id,scope,files,signature,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',
                      ('feedback-'+str(i),'work','feedback','Exact author feedback '+str(i),'version-'+str(i),'[]','[]','original-'+str(i),'completed',now))
            fid='ND_'+format(i,'032x')
            event={'id':fid,'kind':'topic_feedback','title':'Exact news '+str(i),'raw_text':'Exact interest feedback '+str(i),
                   'body':'Source factual body '+str(i),'url':'https://example.invalid/'+str(i),'source':'TEMP','source_job':'fixture',
                   'article_id':'article-'+str(i),'source_event_id':'event-'+str(i),'created_at':now}
            c.execute('INSERT INTO news_feedback(id,article_id,event_json,status,created_at,updated_at) VALUES(?,?,?,?,?,?)',
                      (fid,event['article_id'],json.dumps(event,ensure_ascii=False),'pending_batch',now,now))
        s.index_database(c)
        s.batch.sync_sources(c)
        c.execute("INSERT OR REPLACE INTO learning_index_state VALUES('file-watch',?)",(json.dumps({'generation':1,'fingerprint':s.watch_fingerprint()}),))
    return s


def projection(service):
    with service.store.connect() as c:
        return [tuple(row) for row in c.execute('SELECT id,document,updated_at FROM learning_batch_sources ORDER BY id')]


def test_repeated_idle_worker_ticks_have_constant_queries_and_do_not_rewrite_history(service,record_property):
    worker=LearningWorker(service,runner=lambda *a:pytest.fail('idle poll invoked a model'))
    before=projection(service)
    observations=[]
    try:
        for _ in range(3):
            with performance.span(role='learning') as measured:
                assert worker.tick() is None
            assert measured.metrics.read()['query_count']<40
            observations.append(measured.read())
        assert projection(service)==before
    finally:worker.close()
    record_property('idle_query_counts',','.join(str(row['query_count']) for row in observations))
    record_property('max_write_tx_ms',max(row['write_tx_ms'] for row in observations))


def test_idle_claim_does_not_hold_a_writer_while_syncing_existing_history(service,monkeypatch):
    entered,release,finished=threading.Event(),threading.Event(),threading.Event()
    original=service.batch.sync_sources;failures=[]
    def slow_sync(connection,*args,**kwargs):
        entered.set();assert release.wait(5)
        return original(connection,*args,**kwargs)
    monkeypatch.setattr(service.batch,'sync_sources',slow_sync)
    def claim():
        try:assert service.claim_task('TEMP-idle-worker') is None
        except BaseException as error:failures.append(error)
        finally:finished.set()
    thread=threading.Thread(target=claim);thread.start()
    for _ in range(100):
        if entered.wait(.005) or finished.is_set():break
    committed=False
    try:
        with sqlite3.connect(service.store.path,timeout=.1) as independent:
            independent.execute("INSERT OR REPLACE INTO toolbox_meta VALUES('collector-can-write','actual')")
        committed=True
    except sqlite3.OperationalError:pass
    finally:release.set();thread.join(10)
    assert not thread.is_alive() and not failures
    assert committed,'idle metadata synchronization blocked an independent writer'
    assert not entered.is_set(),'idle claim rebuilt already registered history'


def test_identical_batch_source_does_not_change_projection_or_take_a_write_transaction(service):
    with service.store.connect() as c:
        item=service.batch.rows(c,'learning_batch_sources')[0]
        before=c.total_changes
        actual=service.batch._register(c,item)
        assert actual==item
        assert c.total_changes==before
        assert not c.in_transaction


def test_identical_database_evidence_does_not_start_an_implicit_write(service):
    with service.store.connect() as c:
        before=c.total_changes
        answer=service.index_database(c)
        assert answer=={'indexed':600,'excluded':0}
        assert c.total_changes==before
        assert not c.in_transaction


def test_manual_cycle_still_freezes_actual_sources_and_exact_occurrences(service):
    before=projection(service)
    with service.store.connect() as c:
        cycle=service.batch.start(c,'explicit-manual-only',kind='manual')
        assert cycle['batch_ids'] and len(cycle['batch_ids'])<=cycle['limits']['max_requests']
        sources=[source for bid in cycle['batch_ids'] for source in service.batch.get(c,'learning_batches',bid)['frozen_sources']]
        assert sources
        assert all(source['status']=='pending' for source in sources)
        for source in sources:
            if source['domain']=='style':
                original=service.evidence_content(c,source['evidence_id'])
                assert original['sha256']==source['sha256']
                assert original['content']==source['text']
                assert source['occurrences'][0]['version_id'].startswith('version-')
            else:
                assert source['text']==source['original_event']['raw_text']
                assert source['occurrences'][0]['event_id']==source['original_event']['id']
        queued=[json.loads(row[0]) for row in c.execute("SELECT payload FROM learning_analysis_queue WHERE kind='batch_analysis'")]
        assert len(queued)==len(cycle['batch_ids']) and all(row['manual'] for row in queued)
        assert not c.execute("SELECT 1 FROM sqlite_master WHERE name='creator_model_calls'").fetchone() or c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0]==0
    assert len(projection(service))==len(before)


def test_idle_worker_cost_stays_bounded_on_384_mib_database(service,record_property):
    with service.store.connect() as c:
        c.execute('CREATE TABLE unrelated_history(id INTEGER PRIMARY KEY,payload BLOB)')
        c.executemany('INSERT INTO unrelated_history VALUES(?,zeroblob(6291456))',[(i,) for i in range(64)])
    size=service.store.path.stat().st_size
    assert size>=384*1024*1024
    worker=LearningWorker(service,runner=lambda *a:pytest.fail('idle worker invoked model'))
    try:
        with performance.span(role='learning') as measured:assert worker.tick() is None
        metrics=measured.read()
        assert metrics['query_count']<40 and metrics['db_copy_bytes']==0
        assert metrics['write_tx_ms']<1000
    finally:worker.close()
    for key,value in {'database_bytes':size,**metrics}.items():
        if isinstance(value,(int,float)):record_property(key,value)


@pytest.mark.parametrize('method',['claim_task','queue_index_refresh'])
def test_filesystem_runtime_flag_read_never_holds_a_sqlite_writer(service,monkeypatch,method):
    entered,release=threading.Event(),threading.Event();errors=[]
    def flags():entered.set();assert release.wait(5);return {}
    monkeypatch.setattr(service.batch,'runtime_flags',flags)
    def run():
        try:
            if method=='claim_task':service.claim_task('TEMP-flags')
            else:service.queue_index_refresh()
        except BaseException as error:errors.append(error)
    thread=threading.Thread(target=run);thread.start();assert entered.wait(5)
    try:
        with sqlite3.connect(service.store.path,timeout=.1) as independent:
            independent.execute("INSERT OR REPLACE INTO toolbox_meta VALUES('flags-reader-not-writer','actual')")
    finally:release.set();thread.join(5)
    assert not thread.is_alive() and not errors


def test_expired_unknown_and_exact_queued_review_identity_remain_separate(service):
    with service.store.connect() as c:
        service._enqueue(c,'already-started','skill_distillation',{'operation_id':'original-unknown'},30)
        c.execute("UPDATE learning_analysis_queue SET status='running',started_at=?,lease_until=?,owner='old',lease_token='old-token' WHERE id='already-started'",(stamp(),service.clock()-10))
        service._enqueue(c,'exact-review','production_review',{'work_id':'work','job_id':'version-exact','source_sha256':'a'*64},80)
    task=service.claim_task('new-owner')
    assert task['id']=='exact-review' and task['payload']=={'work_id':'work','job_id':'version-exact','source_sha256':'a'*64}
    assert service.claim_task('another-owner') is None
    with service.store.connect() as c:
        old=dict(c.execute("SELECT * FROM learning_analysis_queue WHERE id='already-started'").fetchone())
        assert old['status']=='blocked' and old['lease_token']=='old-token' and old['started_at']
        assert json.loads(old['payload'])=={'operation_id':'original-unknown'}
