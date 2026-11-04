import json,time,threading,statistics
import pytest
from fastapi import HTTPException
from easel_workbench.features.works.library_index import LibraryIndex,health


def node(i,children=None):
    return {'path':'project-'+str(i),'name':'项目 '+str(i),'type':'dir','mtime':i,'fileCount':len(children or []),
            'meta':{'title':'项目 '+str(i),'kind':'poster','cover':'project-'+str(i)+'/cover.png','summary':'x'*10000},'children':children or []}


@pytest.mark.parametrize('count',[100,1000,10000])
def test_summary_scale_page_is_bounded_and_does_not_call_builder_on_read(tmp_path,count):
    calls=[]
    def build():calls.append(1);return [node(i) for i in range(count)]
    index=LibraryIndex(tmp_path,build);index.rebuild()
    timings=[]
    for _ in range(20):
        start=time.perf_counter();page=index.list();timings.append(time.perf_counter()-start)
        assert len(page['items'])==50
        assert len(json.dumps(page,ensure_ascii=False).encode())<100000
        assert all('children' not in r and 'summary' not in r['meta'] for r in page['items'])
        assert page['next_cursor'] and page['revision']
    assert len(calls)==1 and sorted(timings)[18]<1
    assert health(tmp_path)['counts']=={'nodes':count,'projects':count}


def test_lazy_children_full_parent_metadata_and_exact_deep_link(tmp_path):
    file={'type':'file','path':'__workbench__/exact/name.png','name':'name.png','kind':'image','mtime':4,'size':100}
    version={'type':'dir','path':'project-1/v1','name':'v1','mtime':5,'meta':{'work_id':'w','version_id':'v1','deliverablePaths':[file['path']]},'children':[file]}
    index=LibraryIndex(tmp_path,lambda:[node(1,[version])]);index.rebuild()
    root=index.list()['items'][0];assert root['fileCount']==1 and 'children' not in root
    children=index.list(parent=root['path']);assert children['items'][0]['path']==version['path']
    assert 'deliverablePaths' not in children['items'][0]['meta']
    files=index.list(parent=version['path']);assert files['parent']['meta']['deliverablePaths']==[file['path']]
    assert files['items'][0]['path']==file['path']
    chain=index.resolve(file['path'])['nodes'];assert [r['path'] for r in chain]==[root['path'],version['path'],file['path']]
    assert index.thumbnail_source(root['meta']['cover'].split('/')[1][:-4])=='project-1/cover.png'


def test_cursor_no_duplicates_and_stale_generation_restarts_instead_of_mixing(tmp_path):
    values=[node(i) for i in range(103)];index=LibraryIndex(tmp_path,lambda:values);index.rebuild()
    seen=[];cursor=None
    while True:
        page=index.list(cursor=cursor);seen.extend(r['path'] for r in page['items']);cursor=page['next_cursor']
        if not cursor:break
    assert len(seen)==len(set(seen))==103
    cursor=index.list()['next_cursor'];values.append(node(104));index.rebuild()
    with pytest.raises(HTTPException) as failure:index.list(cursor=cursor)
    assert failure.value.status_code==409 and failure.value.detail=='library_cursor_stale'


def test_unchanged_reconciliation_preserves_generation_and_cursor(tmp_path):
    index=LibraryIndex(tmp_path,lambda:[node(i) for i in range(60)]);index.rebuild()
    page=index.list();index.rebuild()
    assert index.list()['revision']==page['revision']
    assert len(index.list(cursor=page['next_cursor'])['items'])==10


def test_query_cursor_binding_and_literal_search(tmp_path):
    values=[node(i) for i in range(60)];values[0]['name']='literal%_!'
    index=LibraryIndex(tmp_path,lambda:values);index.rebuild()
    assert [r['name'] for r in index.list(query='%_!')['items']]==['literal%_!']
    values[1]['meta']['title']='准确展示标题';index.rebuild()
    assert [r['path'] for r in index.list(query='准确展示标题')['items']]==['project-1']
    cursor=index.list()['next_cursor']
    with pytest.raises(HTTPException):index.list(cursor=cursor,query='other')
    with pytest.raises(HTTPException):index.list(cursor='invalid cursor')
    with pytest.raises(HTTPException):index.list(limit=1000)


def test_old_snapshot_remains_readable_during_build_and_failure(tmp_path):
    entered=threading.Event();finish=threading.Event()
    index=LibraryIndex(tmp_path,lambda:[node(1)]);index.rebuild();revision=index.list()['revision']
    def hold():entered.set();assert finish.wait(5);raise ValueError('synthetic failure')
    index.builder=hold;errors=[]
    def refresh():
        try:index.rebuild()
        except ValueError:errors.append(1)
    worker=threading.Thread(target=refresh);worker.start();assert entered.wait(3)
    page=index.list();assert page['revision']==revision and not page['indexing'] and len(page['items'])==1
    assert health(tmp_path)['building']
    finish.set();worker.join(5);assert errors and index.list()['revision']==revision
    assert health(tmp_path)['status']=='error'


def test_first_empty_index_is_building_not_false_empty_ready(tmp_path):
    index=LibraryIndex(tmp_path,lambda:[])
    assert index.list()=={'items':[],'next_cursor':None,'revision':'','indexing':True,'total':0}
    index.rebuild();assert index.list()['items']==[] and not index.list()['indexing']


def test_health_is_readonly_and_expired_build_is_stale(tmp_path):
    index=LibraryIndex(tmp_path,lambda:[node(1)]);index.rebuild()
    before=index.path.read_bytes();assert health(tmp_path)['status']=='ready';assert index.path.read_bytes()==before
    import sqlite3
    with sqlite3.connect(index.path) as c:
        c.execute("UPDATE metadata SET value=? WHERE key='state'",(json.dumps({'status':'building','building':True,'build_started_at':time.time()-601}),))
    assert health(tmp_path)['status']=='stale'


def test_thumbnail_is_bounded_and_missing_original_is_not_served_from_cache(tmp_path):
    from PIL import Image
    from types import SimpleNamespace
    from easel_workbench.runtime.native_api import NativeApi
    from easel.web_services.outputs import create_outputs_context
    folder=tmp_path/'outputs/project';folder.mkdir(parents=True)
    source=folder/'large.png';Image.new('RGB',(2000,1000),'red').save(source)
    file={'type':'file','path':'project/large.png','name':'large.png','kind':'image','mtime':1}
    index=LibraryIndex(tmp_path,lambda:[{'type':'dir','path':'project','name':'project','children':[file]}]);index.rebuild()
    row=index.list()['items'][0];key=row['meta']['cover'].split('/')[1][:-4]
    api=NativeApi.__new__(NativeApi);api.root=tmp_path;api.library=index;api.outputs=create_outputs_context(tmp_path);api._registered_file=lambda _:None
    response=api._thumbnail(key)
    with Image.open(response.path) as image:assert image.width<=384 and image.height<=384
    source.unlink()
    with pytest.raises(HTTPException) as failure:api._thumbnail(key)
    assert failure.value.status_code==404


def test_library_protocol_and_old_registered_physical_alias_do_not_walk_tree(tmp_path):
    import asyncio,sqlite3
    from types import SimpleNamespace
    from starlette.requests import Request
    from easel_workbench.runtime.native_api import NativeApi
    physical=tmp_path/'outputs/session/turn/file.md';physical.parent.mkdir(parents=True);physical.write_text('original',encoding='utf-8')
    database=tmp_path/'source.sqlite'
    def connect():
        c=sqlite3.connect(database);c.row_factory=sqlite3.Row;return c
    with connect() as c:
        c.execute('CREATE TABLE artifacts(id TEXT,name TEXT,path TEXT)');c.execute('INSERT INTO artifacts VALUES(?,?,?)',('file-id','file.md',str(physical)))
    leaf={'type':'file','path':'__workbench__/file-id/file.md','name':'file.md','kind':'text'}
    tree={'type':'dir','path':'native-session-session','name':'registered session','children':[{'type':'dir','path':'native-session-session/turn','name':'turn','children':[leaf]}]}
    api=NativeApi.__new__(NativeApi);api.root=tmp_path;api.store=SimpleNamespace(connect=connect);api.library=LibraryIndex(tmp_path,lambda:[tree]);api.library.rebuild()
    def forbidden(*args):raise AssertionError('legacy full tree called')
    api._work_tree=forbidden;api._outputs_tree=forbidden
    def request(path,query):return Request({'type':'http','method':'GET','path':path,'query_string':query.encode(),'headers':[]})
    result=asyncio.run(api.dispatch('/api/library/items',request('/api/library/items','limit=50'),{}));assert result['total']==1 and len(result['items'])==1
    value=asyncio.run(api.dispatch('/api/library/resolve',request('/api/library/resolve','path=session/turn/file.md'),{}))
    assert value['nodes'][-1]['path']==leaf['path']
    with pytest.raises(HTTPException):asyncio.run(api.dispatch('/api/library/resolve',request('/api/library/resolve','path=../secret.txt'),{}))
