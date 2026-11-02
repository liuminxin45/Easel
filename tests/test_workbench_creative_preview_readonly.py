"""Production compiler equality against the former TEMP clone, never live work."""
import contextlib
import base64
import asyncio
import importlib.util
import copy
import json
import sqlite3
import tempfile
import threading
from pathlib import Path

import pytest

from easel_workbench.runtime.desk import Store, Connection
from easel_workbench.runtime.toolbox_store import Toolbox
from easel_workbench.runtime.studio_service import StudioService, SECTIONS, CONTEXT_FILES
from easel_workbench.runtime.learning_service import LearningService
from easel_workbench.runtime.creative_recipes import CreativeRecipes, digest
from easel_workbench.runtime.creator_runtime import CreatorRuntime
from easel_workbench.runtime import article_drafts, content_studio
from easel_workbench.diagnostics import performance


@pytest.fixture(params=[False, True], ids=['legacy', 'explicit-creator'])
def recipes(tmp_path, request):
    project = tmp_path / 'project'
    for relative in {path for _, path in SECTIONS.values()} | set(CONTEXT_FILES.values()):
        path = project / relative; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# TEMP canonical original\nKeep the actual facts.\n', encoding='utf-8')
    (project / '规范/创作策略.json').write_text(json.dumps({'schema_version': 2, 'revision': 1, 'methods': [], 'profiles': []}), encoding='utf-8')
    prompt = project / '规范/创作方案/写法.md'; prompt.parent.mkdir(parents=True, exist_ok=True)
    prompt.write_text('Use the exact current author feedback.', encoding='utf-8')
    asset=prompt.parent/'reference.png'
    asset.write_bytes(base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII='))
    catalog = {'schema_version': 1, 'revision': 1, 'components': [{'id': 'writing', 'slot': 'writing', 'name': 'TEMP writing',
               'status': 'confirmed', 'prompt_file': '规范/创作方案/写法.md', 'assets': [{'path':'规范/创作方案/reference.png','sha256':digest(asset.read_bytes()),'label':'Exact frozen reference','role':'example','required':True}]}],
               'packs': [{'id': 'editorial-poster', 'name': 'TEMP recipe', 'status': 'confirmed', 'formats': ['poster', 'article'], 'components': {'writing': 'writing'}}]}
    (prompt.parent / '目录.json').write_text(json.dumps(catalog), encoding='utf-8')
    if request.param:
        skills = []
        definitions=[('content-production','workflow',['poster','article','change']),('content-writing','agent',['poster','article','change']),('image-production','agent',['poster','article','image','change']),('delivery-review','readonly-agent',['review','poster','article','change']),('topic-research','agent',['research','discuss']),('reference-analysis','agent',['reference']),('publication-analysis','agent',['analysis']),('experience-distillation','readonly-agent',['learning'])]
        for sid, executor, tasks in definitions:
            entry = '.agents/skills/' + sid + '/SKILL.md'; path = project / entry
            path.parent.mkdir(parents=True, exist_ok=True); path.write_text('---\nname: ' + sid + '\ndescription: TEMP method\n---\nExact fixture skill.', encoding='utf-8')
            skills.append({'id': sid, 'name': sid, 'entry': entry, 'tasks': tasks, 'executor': executor,
                           'resources': [{'path': '规范/创作方案/目录.json', 'kind': 'contract'}, {'path': '规范/创作方案/写法.md', 'kind': 'prompt', 'variant': 'writing'},{'path':'规范/创作方案/reference.png','kind':'asset','required':True}] if sid == 'content-writing' else [],
                           'input_contract': {'required': ['material']}, 'output_contract': {'required': ['actual_files']}})
        path = project / '.agents/skills/capabilities.json'; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'schema_version': 1, 'skills': skills}), encoding='utf-8')
    box = Toolbox(Store(tmp_path / 'data/desk.sqlite'), tmp_path)
    box.studio = StudioService(box, project=project)
    box.learning = LearningService(box, box.studio, project=project)
    if request.param:
        box.creator = CreatorRuntime(box)
    return CreativeRecipes(box.learning)


def request_input(kind='create', **more):
    value = {'id': 'preview-' + kind, 'title': 'Exact title', 'material': 'Exact original material', 'guidance': 'Exact author request',
             'format': 'poster', 'files': [], 'creative': {'schema_version': 2, 'recipe': {'pack_id': 'editorial-poster', 'prompt_text': 'Editable exact prompt'}}}
    value.update(more)
    return value


def old_clone(recipes, value):
    """Only the old isolation orchestration is copied; all builders stay real."""
    request = copy.deepcopy(value['input']); request['creative']['recipe'].pop('preview_id', None)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'oracle.sqlite'
        with recipes.store.connect() as source, contextlib.closing(sqlite3.connect(path)) as target:
            sqlite3.Connection.backup(source, target)
        store = copy.copy(recipes.store); store.path = path
        box = copy.copy(recipes.box); box.store = store; box.creative_preview = True
        box.studio = copy.copy(box.studio); box.studio.box = box; box.studio.store = store
        box.learning = copy.copy(box.learning); box.learning.box = box; box.learning.store = store; box.learning.studio = box.studio
        if value['kind'] == 'create': result = box.create(request)
        elif value['kind'] == 'change': result = box.action(value['work_id'], {**request, 'kind': 'change'})
        else: result = article_drafts.finalize(box, value['work_id'], request)
        with store.connect() as c:
            document = json.loads(c.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?', (request['id'],)).fetchone()[0])
        return document, result


@pytest.mark.parametrize('kind', ['create', 'change', 'finalize'])
@pytest.mark.parametrize('format',['poster','article'])
def test_real_shared_compiler_matches_old_clone_for_all_kinds_and_retains_exact_inputs(recipes, kind, format, monkeypatch):
    box = recipes.box
    value = {'kind': kind, 'input': request_input(kind,format=format)}
    upload=box.upload('attachment','exact-original.txt',b'Exact original attached bytes')
    value['input']['files']=[upload['id']]
    if kind == 'change':
        content_studio.save_text(box, 'parent', {'id': 'parent', 'format': format, 'title': 'Exact parent title', 'body': 'Exact parent original'}, new=True)
        # Bind a real, immutable creator snapshot for the parent when applicable.
        if getattr(box, 'creator', None):
            from easel_workbench.runtime import task_runtime
            with box.store.connect() as c:
                task_runtime.freeze(c, box, 'parent', 'parent', {}, task=format)
        box.action('parent', {'id': 'parent-feedback', 'kind': 'feedback', 'candidate_id': 'parent', 'text': 'Exact scoped author feedback', 'files': []})
        from easel_workbench.runtime import work_review
        field='poster_title' if format=='poster' else 'article_title'
        source=work_review.read(box,'parent','parent')['sources'][field]
        work_review.mutate(box,'parent','parent',{'id':'annotation','kind':'create','field':field,'source_sha256':source['sha256'],'quote':'Exact','start':0,'end':5,'note':'Exact scoped author annotation','dimension':'text','scope':'work'})
        value.update(work_id='parent'); value['input'].update(candidate_id='parent', text='Change layout only; retain the exact parent words')
    elif kind == 'finalize':
        article_drafts.save(box, {'id': 'draft', 'title': 'Current saved title', 'material': 'Current exact saved material', 'guidance': 'Draft exact author request', 'revision': 0, 'format': format, 'files': [upload['id']], 'creative': value['input']['creative']})
        value.update(work_id='draft'); value['input'] = {'id': 'preview-finalize', 'revision': 1, 'creative': value['input']['creative']}
    expected, identity = old_clone(recipes, value)
    before = None
    with box.store.connect() as c:
        before = {name: c.execute('SELECT count(*) FROM ' + name).fetchone()[0] for name in ['toolbox_jobs', 'creator_work_owners', 'creator_task_runs', 'learning_runs', 'toolbox_files']}
    monkeypatch.setattr(Connection, 'backup', lambda *args, **kwargs: pytest.fail('application preview copied full DB'))
    actual = recipes.preview(value)
    assert actual['execution_prompt'] == expected['execution_prompt']
    assert actual['context'] == expected.get('studio_context', {})
    assert actual['work_id'] == identity['work_id']
    assert actual['input']['creative']['recipe']['prompt_text'] == value['input']['creative']['recipe']['prompt_text']
    returned=copy.deepcopy(actual['input']);returned['creative']['recipe'].pop('preview_id')
    original=copy.deepcopy(value['input']);original['creative']['recipe'].pop('preview_id',None)
    assert returned==original
    if kind=='change':
        assert expected['candidate_id']=='parent'
        assert expected['annotations'][0]['note']=='Exact scoped author annotation'
        assert any(row['text']=='Exact scoped author feedback' for row in expected['raw_feedback']['items'])
    if getattr(box,'creator',None):
        assert expected['creator_snapshot']['profile']['id']=='oil-pig'
        assert {row['id'] for row in expected['creator_snapshot']['skills']}=={'content-writing','image-production','delivery-review'}
    with box.store.connect() as c:
        assert before == {name: c.execute('SELECT count(*) FROM ' + name).fetchone()[0] for name in before}
        assert c.execute('SELECT count(*) FROM creative_prompt_previews').fetchone()[0] == 1
    assert len(list((box.root/'data/toolbox/files').rglob('审阅与风格反馈.json')))==(2 if kind=='change' else 0)
    # The unchanged acceptance path consumes this exact receipt, not a second compiler.
    if kind=='create':accepted=box.create(actual['input'])
    elif kind=='change':accepted=box.action(value['work_id'],{**actual['input'],'kind':'change'})
    else:accepted=article_drafts.finalize(box,value['work_id'],actual['input'])
    with box.store.connect() as c:
        stored=json.loads(c.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?',(accepted['id'],)).fetchone()[0])
    assert stored['execution_prompt']['body']==actual['execution_prompt']['body']
    assert stored['execution_prompt']['approved_preview_id']==actual['preview_id']


def test_compilation_is_query_only_and_can_run_while_an_unrelated_writer_commits(recipes, monkeypatch):
    from easel_workbench.runtime import work_review
    original = work_review.freeze; seen = []
    def inspect(box, connection, *args, **kwargs):
        assert connection.execute('PRAGMA query_only').fetchone()[0] == 1
        seen.append(True)
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("INSERT INTO toolbox_meta VALUES('forbidden-preview-write','original')")
        committed, failures = threading.Event(), []
        def write():
            try:
                with box.store.connect() as writer:
                    writer.execute("INSERT OR REPLACE INTO toolbox_meta VALUES('independent-writer','actual')")
                committed.set()
            except BaseException as error: failures.append(error)
        thread = threading.Thread(target=write); thread.start(); thread.join(3)
        assert committed.is_set() and not thread.is_alive() and not failures
        return original(box, connection, *args, **kwargs)
    monkeypatch.setattr(work_review, 'freeze', inspect)
    assert recipes.preview({'kind': 'create', 'input': request_input()})['execution_prompt']['body']
    assert seen


def test_real_scale_preview_never_copies_unrelated_history(recipes,monkeypatch):
    with recipes.store.connect() as c:
        c.execute('CREATE TABLE unrelated_history(id INTEGER PRIMARY KEY,payload BLOB)')
        c.executemany('INSERT INTO unrelated_history VALUES(?,zeroblob(6291456))',[(i,) for i in range(64)])
    assert recipes.store.path.stat().st_size>=384*1024*1024
    monkeypatch.setattr(Connection,'backup',lambda *args,**kwargs:pytest.fail('large DB copied'))
    with performance.span(route='/api/creative/preview',allow_db_copy=False) as measured:
        assert recipes.preview({'kind':'create','input':request_input()})['execution_prompt']['body']
    assert measured.metrics.read()['db_copy_bytes']==0
    assert measured.metrics.read()['db_copy_count']==0
    # Query count is bounded by the same actual metadata compiler, not history rows.
    assert measured.metrics.read()['query_count']<250


def test_public_context_cannot_supply_a_trusted_prepared_work(recipes):
    fake={'id':'unpersisted','title':'UNTRUSTED SPOOF','material':'UNTRUSTED SPOOF'}
    with recipes.store.connect() as c:
        result=recipes.learning.resolve(c,'unpersisted',context={'_learning_pending_work':fake,'pending_work':fake})
    assert result['work_context'] is None
    from easel_workbench.features.evidence.rules import compilation_work
    with compilation_work(fake):
        with recipes.store.connect() as c:
            assert recipes.learning.resolve(c,'another-work')['work_context'] is None
    with recipes.store.connect() as c:
        assert recipes.learning.resolve(c,'unpersisted')['work_context'] is None


def test_preview_keeps_profile_revision_validation_and_never_queues_on_rejection(recipes):
    if not getattr(recipes.box,'creator',None):pytest.skip('explicit identity validation covered on the explicit runtime')
    value=request_input();value['creative']['creator']={'profile_id':'oil-pig','profile_revision':999}
    with pytest.raises(ValueError):old_clone(recipes,{'kind':'create','input':value})
    with pytest.raises(ValueError):recipes.preview({'kind':'create','input':value})
    with recipes.store.connect() as c:
        assert c.execute('SELECT count(*) FROM toolbox_jobs').fetchone()[0]==0
        assert c.execute('SELECT count(*) FROM creative_prompt_previews').fetchone()[0]==0


def test_actual_creative_preview_http_route_has_correlated_copy_free_observations(recipes,monkeypatch):
    if not getattr(recipes.box,'creator',None):pytest.skip('the mounted owner app always initializes explicit identity')
    import httpx
    from easel_workbench.runtime.toolbox_server import create_app
    class Auth:
        data={'origin':'https://performance.test','host':'performance.test','secret':'A'*32}
        def session(self,token):return {'csrf':'fixture','until':9999999999} if token=='owner' else None
    events=[];monkeypatch.setattr(performance,'_emit',lambda event,**fields:events.append({'event':event,**fields}))
    monkeypatch.setattr(Connection,'backup',lambda *args,**kwargs:pytest.fail('HTTP preview copied database'))
    async def run():
        app=create_app(store=recipes.store,auth=Auth(),box=recipes.box,root=recipes.root,studio=recipes.box.studio)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://performance.test') as client:
            client.cookies.set('__Host-desk_session','owner');cfg=(await client.get('/api/config')).json()
            response=await client.post('/api/creative/preview',headers={'Origin':'https://performance.test','X-CSRF-Token':cfg['csrf']},json={'kind':'create','input':request_input()})
            assert response.status_code==200,response.text
            trace=response.headers['X-Desk-Trace'];event=next(row for row in events if row['event']=='performance_finished' and row['trace_id']==trace)
            assert event['route']=='/api/creative/preview' and event['query_count']>0 and event['db_copy_bytes']==0
            assert response.json()['execution_prompt']['body']
        await app.state.chat.close()
    asyncio.run(run())


_http_spec=importlib.util.spec_from_file_location('performance_http_fixture',Path(__file__).with_name('test_workbench_chat_business.py'))
_http_fixture=importlib.util.module_from_spec(_http_spec);_http_spec.loader.exec_module(_http_fixture)
business=_http_fixture.business


def test_actual_chat_plan_http_route_correlates_trace_and_rejects_accidental_backup(business,monkeypatch):
    import httpx
    from easel_workbench.runtime.toolbox_server import create_app
    class Auth:
        data={'origin':'https://performance.test','host':'performance.test','secret':'A'*32}
        def session(self,token):return {'csrf':'fixture','until':9999999999} if token=='owner' else None
    events=[];monkeypatch.setattr(performance,'_emit',lambda event,**fields:events.append({'event':event,**fields}))
    async def run():
        b=business;app=create_app(store=b.store,auth=Auth(),box=b.box,root=b.root)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://performance.test') as client:
            client.cookies.set('__Host-desk_session','owner');cfg=(await client.get('/api/config')).json();headers={'Origin':'https://performance.test','X-CSRF-Token':cfg['csrf']}
            assert (await client.post('/api/chat/sessions',headers=headers,json={'id':'http-create','session_id':'http-plan','profile_id':'oil-pig','action':'create'})).status_code==200
            payload=_http_fixture.value(tid='http-plan-one');payload['sessionId']='http-plan'
            response=await client.post('/api/chat/plan',headers=headers,json=payload)
            assert response.status_code==200,response.text
            trace=response.headers['X-Desk-Trace'];event=next(row for row in events if row['event']=='performance_finished' and row['trace_id']==trace)
            assert event['route']=='/api/chat/plan' and event['query_count']>0 and event['db_copy_bytes']==0
            def accidental_copy(value):
                with b.store.connect() as source,contextlib.closing(sqlite3.connect(':memory:')) as target:source.backup(target)
                raise AssertionError('copy was not forbidden')
            monkeypatch.setattr(app.state.chat_business,'plan',accidental_copy)
            rejected=await client.post('/api/chat/plan',headers=headers,json=payload)
            assert rejected.status_code==503
            trace=rejected.headers['X-Desk-Trace'];blocked=next(row for row in events if row['event']=='performance_finished' and row['trace_id']==trace)
            assert blocked['db_copy_blocked']==1 and blocked['db_copy_bytes']==0
            with b.store.connect() as c:
                assert c.execute('SELECT count(*) FROM toolbox_jobs').fetchone()[0]==0
                assert c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0]==0
        await app.state.chat.close()
    asyncio.run(run())
