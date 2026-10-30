"""TEMP source management, frozen queue execution and raw news persistence."""
import datetime as dt
import json
from pathlib import Path
import uuid

import pytest

from easel_workbench.runtime.desk import Store
from easel_workbench.runtime.collection_service import CollectionService, slot
from easel_workbench.runtime.collection_worker import CollectionWorker
from easel_workbench.runtime.source_registry import SourceRegistry
from easel_workbench.runtime.news_overviews import Overviews


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path/'data/desk.sqlite')
    (tmp_path/'data/collection-config.json').write_text('{"enabled":true}', encoding='utf-8')
    service = CollectionService(store, tmp_path)
    return store, service, service.registry


def command(registry, **fields):
    return registry.update({'operation_id': uuid.uuid4().hex, **fields})


def add(registry, **fields):
    return command(registry, action='add', label='TEMP source', type='http', url='https://example.com/feed', **fields)['id']


def test_source_receipt_versions_and_private_public_view(setup):
    store, service, registry = setup
    value = {'operation_id':'same-operation', 'action':'add', 'label':'TEMP', 'type':'http',
             'url':'https://example.com/feed', 'headers':{'Authorization':'Bearer private-test'}}
    first = registry.update(value)
    assert registry.update(value) == first
    assert registry.receipt('same-operation')['result']==first
    assert registry.receipt('unknown')['state']=='unknown'
    with pytest.raises(ValueError): registry.update({**value, 'label':'different'})
    public = registry.public()
    assert 'private-test' not in json.dumps(public)
    identifier = first['id']
    command(registry, action='toggle', source_id=identifier, expected_revision=1, enabled=False)
    assert not service.definitions()[identifier]['enabled']
    with pytest.raises(ValueError): command(registry, action='toggle', source_id=identifier, expected_revision=1, enabled=True)
    command(registry, action='delete', source_id=identifier, expected_revision=2)
    assert identifier not in registry.entries()
    assert registry.entries(include_deleted=True)[identifier]['deleted']
    builtin = next(iter(registry.baseline()))
    with pytest.raises(ValueError): command(registry, action='delete', source_id=builtin, expected_revision=0)


def test_second_schedule_and_frozen_task_survive_delete_and_retry(setup, monkeypatch):
    store, service, registry = setup
    identifier = add(registry, refresh_seconds=7)
    now = dt.datetime(2026,10,30,12,0,tzinfo=dt.timezone(dt.timedelta(hours=8)))
    service.clock = lambda: now
    service.schedule_due()
    now += dt.timedelta(seconds=8)
    runs = service.schedule_due()
    assert any(task['source_id']==identifier for run in runs for task in service.get(run)['tasks'])
    run = service.enqueue({'id':'manual', 'scope':'source', 'source':identifier})
    assert service.enqueue({'id':'manual', 'scope':'source', 'source':identifier})['id'] == run['id']
    assert service.enqueue({'id':'second-window', 'scope':'source', 'source':identifier})['id'] == run['id']
    command(registry, action='delete', source_id=identifier, expected_revision=1)
    assert service.get(run['id'])['tasks'][0]['name']=='TEMP source'
    with pytest.raises(ValueError): service.enqueue({'id':'new-after-delete','scope':'source','source':identifier})
    task = service.claim('temp-owner')
    assert task['source_id'] == identifier
    snapshot = json.loads(task['source_snapshot'])
    assert snapshot['revision'] == 1 and snapshot['refresh_seconds'] == 7
    service.finish(task['id'],task['lease_token'],{'status':'failed'})
    retried = service.retry(run['id'],{'id':'retry'})
    next_task = service.claim('temp-owner')
    assert json.loads(next_task['source_snapshot']) == snapshot
    assert next_task['resume_from'] == task['id'] and retried['tasks'][0]['source_id']==identifier
    assert (slot({'kind':'interval','seconds':7},now)-now).total_seconds() <= 7
    with pytest.raises(ValueError): service.enqueue({'id':'injected','source_snapshot':snapshot})


def test_protocol_batch_ingest_missing_urls_and_no_model(setup, monkeypatch, tmp_path):
    store, service, registry = setup
    identifier = add(registry)
    from easel.trends.protocol import validate_payload
    from easel_workbench.runtime import custom_source_collection as custom
    payload = validate_payload({'version':1,'fetched_at':'2026-10-30T08:00:00Z','items':[
        {'id':str(index),'title':'TEMP '+str(index),'url':'' if index==0 else 'https://example.com/'+str(index),'heat':{'text':'热度 '+str(index)}} for index in range(250)]})
    monkeypatch.setattr(custom,'collect',lambda source,env:payload)
    run = service.enqueue({'id':'custom-batch','scope':'source','source':identifier})
    task = service.claim('owner')
    worker = CollectionWorker(service)
    try: result = worker.execute(task)
    finally: worker.close()
    assert result['status']=='completed' and result['inserted']==250
    service.finish(task['id'],task['lease_token'],result)
    listing = store.article_day(source=identifier)
    assert len(listing['items'])==250 and [row['source_order'] for row in listing['items']]==list(range(1,251))
    first = listing['items'][0]
    assert first['url']=='' and '来源仅提供标题' in first['body'] and first['hot']=='热度 0'
    assert first['source_protocol_id']=='0'
    assert Overviews(store,tmp_path).project([first])[0]['overview_status']=='source_only'
    calls=[]
    assert Overviews(store,tmp_path).tick(runner=lambda *args:calls.append(args)) == 0 and not calls
    assert custom.run(json.loads(task['source_snapshot']),service.state/'tasks'/task['id'],root=tmp_path,report=lambda *args:None)['inserted']==0
    command(registry, action='delete', source_id=identifier, expected_revision=1)
    assert store.detail(first['id'])['body']==first['body']


def test_python_syntax_is_not_execution_and_asset_hash_is_enforced(setup, tmp_path):
    store, service, registry = setup
    marker = tmp_path/'must-not-exist'
    code = 'from pathlib import Path\nPath('+repr(str(marker))+').write_text("executed")\n'
    identifier = command(registry,action='add',label='Python TEMP',type='python',script_name='collector.py',script_code=code)['id']
    assert not marker.exists()
    row = registry.entries()[identifier]
    source = registry.source(row)
    path = Path(source.options['script'])
    assert path.name == row['script_sha256']+'.py'
    original = path.read_bytes()
    path.write_text('changed',encoding='utf-8')
    with pytest.raises(ValueError): registry.source(row)
    path.write_bytes(original)
    with pytest.raises(ValueError): command(registry,action='add',label='invalid',type='python',script_name='bad.py',script_code='not valid python ???')


def test_legacy_builtin_overrides_and_minute_schedules_remain(setup):
    store, service, registry = setup
    builtin = next(iter(registry.baseline()))
    path = service.root/'data/collection-config.json'
    path.write_text(json.dumps({'enabled':True,'sources':{builtin:{'enabled':False,'schedule':{'kind':'interval','minutes':11}}}}),encoding='utf-8')
    assert not service.definitions()[builtin]['enabled']
    command(registry,action='toggle',source_id=builtin,expected_revision=0,enabled=True)
    assert service.definitions()[builtin]['enabled']
    assert service.definitions()[builtin]['schedule']['minutes']==11


def test_real_local_rss_http_and_python_transports(setup):
    import http.server
    import threading
    store, service, registry = setup
    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if self.path=='/rss':
                data=b'<rss version="2.0"><channel><title>TEMP</title><item><guid>rss-one</guid><title>RSS title</title><link>https://example.com/rss</link></item></channel></rss>'
            else:
                data=json.dumps({'version':1,'fetched_at':'2026-10-30T08:00:00Z','items':[{'id':'http-one','title':'HTTP title','url':'https://example.com/http'}]}).encode()
            self.send_response(200);self.end_headers();self.wfile.write(data)
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        for kind in ('rss','http','python'):
            fields={'url':f'http://127.0.0.1:{server.server_port}/'+kind} if kind!='python' else {'script_name':'source.py','script_code':'import json\nprint(json.dumps({"version":1,"fetched_at":"2026-10-30T08:00:00Z","items":[{"id":"python-one","title":"Python title"}]}))\n'}
            identifier=command(registry,action='add',label=kind,type=kind,**fields)['id']
            run=service.enqueue({'id':uuid.uuid4().hex,'scope':'source','source':identifier})
            task=service.claim('transport-test')
            worker=CollectionWorker(service)
            try:result=worker.execute(task)
            finally:worker.close()
            assert result['status']=='completed',result
            assert result['inserted']==1
            service.finish(task['id'],task['lease_token'],result)
            assert store.article_day(source=identifier)['items'][0]['title'].lower().startswith(kind)
    finally:
        server.shutdown();server.server_close();thread.join()
