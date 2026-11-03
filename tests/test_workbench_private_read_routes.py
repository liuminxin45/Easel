"""Authenticated TEMP HTTP integration for summary/detail routing and cache keys."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

spec=importlib.util.spec_from_file_location('private_route_fixtures',Path(__file__).with_name('test_workbench_private_read_views.py'))
fixtures=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixtures)
runtime,commands=fixtures.runtime,fixtures.commands


@pytest.fixture
def routes(commands):
    from easel_workbench.application import create_app
    from easel_workbench.runtime.auth_forms import SESSION
    service=fixtures.distribution(commands);service.runtime=SimpleNamespace(extension_retired=True)
    fixtures.add_work(commands,'work-one')
    class Auth:
        data={'origin':'https://fixture.test','host':'fixture.test','secret':'A'*32}
        def session(self,token):return {'csrf':'fixture','until':9999999999} if token=='fixture-owner' else None
    app=create_app(root=commands.root,store=commands.store,auth=Auth(),box=commands,studio=commands.studio,distribution=service)
    # No lifespan: no queue, index or model worker is started by this read test.
    client=TestClient(app,base_url='https://fixture.test',raise_server_exceptions=True)
    client.cookies.set(SESSION,'fixture-owner',domain='fixture.test',path='/')
    try:yield client,app,commands,service
    finally:
        client.close()
        native=getattr(commands,'_native_api',None)
        if native:native.library.close()


def rows(box):
    tables=('distribution_operations','distribution_approvals','distribution_deliveries','distribution_attempts','studio_operations','toolbox_jobs','creator_skill_versions')
    with box.store.connect() as c:
        return {table:[tuple(row) for row in c.execute('SELECT * FROM '+table+' ORDER BY rowid')] for table in tables}


def test_creator_query_variants_have_separate_authenticated_cache_entries(routes,monkeypatch):
    client,app,box,_=routes
    monkeypatch.setattr(box.creator,'_skill',fixtures.forbidden)
    full=client.get('/api/creator/bootstrap');summary=client.get('/api/creator/bootstrap?view=summary')
    assert full.status_code==summary.status_code==200
    assert 'voice' in full.json()['profiles'][0] and 'voice' not in summary.json()['profiles'][0]
    assert full.headers['etag']!=summary.headers['etag']
    assert client.get('/api/creator/bootstrap?view=summary',headers={'If-None-Match':full.headers['etag']}).status_code==200
    assert client.get('/api/creator/bootstrap?view=summary',headers={'If-None-Match':summary.headers['etag']}).status_code==304
    assert client.get('/api/creator/bootstrap',headers={'If-None-Match':full.headers['etag']}).status_code==304
    client.cookies.clear()
    assert client.get('/api/creator/bootstrap?view=summary',headers={'If-None-Match':summary.headers['etag']}).status_code==401


def test_summary_and_exact_detail_routes_reach_private_handlers_without_authorizing_writes(routes,monkeypatch):
    client,app,box,service=routes
    before=rows(box)
    monkeypatch.setattr(app.state.view_cache,'_assets',fixtures.forbidden)
    monkeypatch.setattr(app.state.view_cache,'_foundation',fixtures.forbidden)
    for name in ('foundation','capabilities','_records'):monkeypatch.setattr(box.studio,name,fixtures.forbidden)
    monkeypatch.setattr(box,'works',fixtures.forbidden)
    monkeypatch.setattr(service,'_records',fixtures.forbidden)
    monkeypatch.setattr(service,'command',fixtures.forbidden)
    monkeypatch.setattr(box.creator,'command',fixtures.forbidden)
    selected=[]
    def validate(c,value):selected.append(value['id'])
    monkeypatch.setattr(service,'_validate_revision',validate)
    publication=client.get('/api/studio/bootstrap?view=publications')
    distribution=client.get('/api/distribution/bootstrap?view=summary&work_id=work-one')
    assert publication.status_code==distribution.status_code==200
    assert publication.json()['total']==1 and distribution.json()['counts']['revisions']==1
    assert 'PRIVATE' not in publication.text+distribution.text and selected==[]
    exact=client.get('/api/distribution/revisions/revision-two')
    assert exact.status_code==200 and selected==['revision-two']
    assert exact.json()['revision']['body'].startswith('PRIVATE_BODY')
    detail=client.get('/api/distribution/deliveries/delivery-one')
    assert detail.status_code==200 and detail.json()['delivery']['status']=='unknown'
    assert [row['id'] for row in detail.json()['attempts']]==['attempt-one']
    pub=client.get('/api/studio/publications/pub-one')
    assert pub.status_code==200 and pub.json()['publication']['history'][0]['body']=='PRIVATE_HISTORY'
    assert client.head('/api/studio/publications/pub-one').status_code==200
    assert client.head('/api/distribution/deliveries/delivery-one').content==b''
    assert rows(box)==before


def test_work_summary_and_view_paths_and_native_personas_do_not_fall_into_legacy_full_reads(routes,monkeypatch):
    client,app,box,_=routes;before=rows(box)
    monkeypatch.setattr(app.state.view_cache,'_assets',fixtures.forbidden)
    monkeypatch.setattr(app.state.view_cache,'_foundation',fixtures.forbidden)
    monkeypatch.setattr(box,'works',fixtures.forbidden)
    monkeypatch.setattr(box.creator,'bootstrap',fixtures.forbidden)
    summaries=client.get('/api/works?view=summary&limit=1')
    assert summaries.status_code==200 and summaries.json()['total']==1
    assert summaries.json()['items'][0]['id']=='work-one'
    assert 'material' not in summaries.json()['items'][0] and 'history' not in summaries.json()['items'][0]
    detail=client.get('/api/works/work-one/view')
    assert detail.status_code==200 and detail.json()['id']=='work-one'
    assert detail.json()['versions']==[] and detail.json()['draft']['revision']==1
    assert client.get('/api/personas').status_code==200
    assert client.get('/api/persona/oil-pig/files').status_code==200
    assert rows(box)==before


@pytest.mark.parametrize('path',[
    '/api/studio/bootstrap?view=invalid',
    '/api/distribution/bootstrap?view=invalid',
    '/api/studio/publications/missing',
    '/api/distribution/revisions/missing',
    '/api/distribution/deliveries/missing',
])
def test_invalid_or_missing_detail_is_a_defined_client_error_not_server_failure(routes,path):
    client,_,box,_=routes;before=rows(box)
    response=client.get(path)
    assert response.status_code==400 and isinstance(response.json()['error'],str)
    assert rows(box)==before
