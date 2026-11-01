"""TEMP-only native HTTP download capabilities; no model or platform operations."""
import asyncio
import importlib.util
from pathlib import Path
import threading
import time
from urllib.parse import urlencode, urlsplit, parse_qs
import httpx
import pytest
from starlette.datastructures import QueryParams
from easel_workbench.runtime import download_delivery as delivery
from easel_workbench.runtime.auth_totp import token_hash
from easel_workbench.runtime.auth_forms import SESSION

spec=importlib.util.spec_from_file_location('download_fixtures',Path(__file__).with_name('test_workbench_preview_frames.py'))
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
runtime,commands=f.runtime,f.commands

@pytest.mark.parametrize('bad',['https://evil.test/api/files/id','//evil.test/api/files/id','/api/config','/api/downloads','/api/media/../private','/api/media/%2e%2e/private','/api/files/id?extra=1','/api/media/jobs/id','/api/media/accounts/id/qr','/api/files/id#fragment'])
def test_reject_non_download_targets(bad):
    with pytest.raises(ValueError):delivery.target(bad)

def test_revocation_expiry_and_binding():
    class Auth:pass
    auth=Auth();auth.lock=threading.RLock();session={'csrf':'fixture','until':time.time()+900}
    auth.data={'sessions':{token_hash('owner'):session}}
    url=delivery.issue(session,'owner','/api/files/id','原件.png');q=QueryParams(urlsplit(url).query)
    assert delivery.authorize(auth,q)==session
    for field,value in [('target','/api/files/other'),('name','other.png'),('expires',str(int(time.time())-1)),('signature','0'*64)]:
        pairs=dict(q);pairs[field]=value;assert delivery.authorize(auth,QueryParams(pairs)) is None
    assert delivery.authorize(auth,QueryParams(urlsplit(url).query+'&name=duplicate')) is None
    auth.data['sessions'].clear();assert delivery.authorize(auth,q) is None


def test_issue_reports_invalid_json_and_missing_target_before_handoff(commands):
    app=f.app_for(commands);auth=app.state.auth;auth.lock=threading.RLock()
    auth.data['sessions']={token_hash('fixture-owner'):{'csrf':'fixture','until':9999999999}}
    from easel_workbench.runtime.api_security import csrf_token
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://native.test') as client:
            client.cookies.set(SESSION,'fixture-owner')
            headers={'Origin':'https://native.test','X-CSRF-Token':csrf_token(commands.store)}
            for value in (None,[],True,123,'not an object'):
                response=await client.post('/api/downloads',content=__import__('json').dumps(value),headers={**headers,'Content-Type':'application/json'})
                assert response.status_code==400 and 'url' not in response.json()
            response=await client.post('/api/downloads',json={'target':'/api/files/missing-file','name':'原件.png'},headers=headers)
            assert response.status_code==404 and 'url' not in response.json()
    asyncio.run(run())


def test_zip_probe_does_not_build_archive_and_get_closes_spooled_file(commands,monkeypatch):
    import io,tempfile,zipfile
    commands.create({'id':'zip-probe','title':'TEMP ZIP','material':'原文','format':'poster','files':[]})
    folder=commands.root/'data/artifacts';folder.mkdir(parents=True,exist_ok=True)
    image=folder/'zip-probe.png';raw=(Path(__file__).resolve().parents[1]/'web/static/easel-icon.png').read_bytes();image.write_bytes(raw)
    copy=folder/'zip-probe-copy.txt';copy.write_text('TEMP 标题\n\nTEMP 准确原件配文',encoding='utf-8')
    with commands.store.connect() as connection:
        connection.execute("UPDATE toolbox_jobs SET status='completed' WHERE id='zip-probe'")
        connection.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)',('zip-image','zip-probe','原图.png',str(image),'image/png'))
        connection.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)',('zip-copy','zip-probe','标题与配文.txt',str(copy),'text/plain'))
    work=commands.work('zip-probe')
    assert any(version['id']=='zip-probe' and version['status']=='completed' for version in work['versions']),work
    app=f.app_for(commands);auth=app.state.auth;auth.lock=threading.RLock()
    auth.data['sessions']={token_hash('fixture-owner'):{'csrf':'fixture','until':9999999999}}
    from easel_workbench.runtime.api_security import csrf_token
    factory=tempfile.SpooledTemporaryFile;opened=[]
    def forbidden(*args,**kwargs):raise AssertionError('HEAD must not allocate or build a ZIP')
    def tracked(*args,**kwargs):
        value=factory(*args,**kwargs);opened.append(value);return value
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://native.test') as client:
            client.cookies.set(SESSION,'fixture-owner')
            path='/api/works/zip-probe/versions/zip-probe/download'
            with monkeypatch.context() as patch:
                patch.setattr(tempfile,'SpooledTemporaryFile',forbidden)
                response=await client.head(path);assert response.status_code==200 and 'content-length' not in response.headers
                issued=await client.post('/api/downloads',json={'target':path,'name':'原图.zip'},headers={'Origin':'https://native.test','X-CSRF-Token':csrf_token(commands.store)})
                assert issued.status_code==200,issued.text
                link=issued.json()['url'];client.cookies.clear()
                response=await client.head(link);assert response.status_code==200 and 'content-length' not in response.headers
            with monkeypatch.context() as patch:
                patch.setattr(tempfile,'SpooledTemporaryFile',tracked)
                response=await client.get(link);assert response.status_code==200
                with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:assert bundle.read(bundle.namelist()[0])==raw
            assert len(opened)==1 and opened[0].closed
    asyncio.run(run())

@pytest.mark.parametrize('directory',['downloads','accounts','images','jobs'])
@pytest.mark.parametrize('suffix',['png','txt','json','html','zip','mp3','mp4','pdf'])
def test_full_http_issue_authenticated_download_cookie_less_exact_bytes_head_range(commands,suffix,directory):
    app=f.app_for(commands);auth=app.state.auth;auth.lock=threading.RLock()
    auth.data['sessions']={token_hash('fixture-owner'):{'csrf':'fixture','until':9999999999}}
    folder=commands.root/'outputs'/directory;folder.mkdir(parents=True,exist_ok=True)
    original=folder/('原件.'+suffix);raw=b'exact captured original bytes';original.write_bytes(raw)
    item=commands.register_file('download-'+suffix,original.name,original)
    paths=['/api/files/'+item['id']+'?download=1','/api/media/'+directory+'/'+original.name,'/api/media/__workbench__/'+item['id']+'/'+original.name]
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://native.test') as client:
            for target in paths:
                query=urlencode({'target':target,'name':original.name})
                assert (await client.post('/api/downloads',json={'target':target,'name':original.name})).status_code==401
                client.cookies.set(SESSION,'fixture-owner')
                assert (await client.post('/api/downloads',json={'target':target,'name':original.name})).status_code==403
                response=await client.post('/api/downloads',json={'target':target,'name':original.name},headers={'Origin':'https://native.test','X-CSRF-Token':__import__('easel_workbench.runtime.api_security',fromlist=['csrf_token']).csrf_token(commands.store)});assert response.status_code==200,response.text
                link=response.json()['url'];client.cookies.clear()
                response=await client.get(link);assert response.status_code==200,response.text
                assert response.content==raw and response.headers['content-disposition'].startswith('attachment;')
                assert response.headers['cache-control']=='no-store'
                head=await client.head(link);assert head.status_code==200 and not head.content and int(head.headers['content-length'])==len(raw)
                ranged=await client.get(link,headers={'Range':'bytes=1-3'});assert (ranged.status_code==206 and ranged.content==raw[1:4]) or (suffix=='html' and target.startswith('/api/media/') and ranged.status_code==200 and ranged.content==raw)
                bad=await client.get(link.replace('signature=','signature=0'));assert bad.status_code==403
            auth.data['sessions'].clear();assert (await client.get(link)).status_code==403
    asyncio.run(run())
