"""TEMP end-to-end attachment auth, CSRF and streaming; zero model calls."""
import asyncio
import importlib.util
from pathlib import Path
import httpx
from starlette.requests import Request
spec=importlib.util.spec_from_file_location('upload_http_fixtures',Path(__file__).with_name('test_workbench_native_api.py'))
f=importlib.util.module_from_spec(spec);spec.loader.exec_module(f)
runtime,commands=f.runtime,f.commands

class Auth:
    data={'origin':'https://temp.local','host':'temp.local','secret':'A'*32}
    def session(self,token):return {'csrf':'fixture','until':9999999999} if token=='fixture-owner' else None

class ForbiddenBody(httpx.AsyncByteStream):
    async def __aiter__(self):
        raise AssertionError('unauthorized upload body must not be read')
        yield b''

def test_actual_upload_route_streams_after_auth_and_preserves_idempotent_refs(commands,monkeypatch):
    from easel_workbench.runtime.toolbox_server import create_app
    original=Request.body
    async def no_upload_body(self):
        if self.url.path in ('/api/upload','/api/uploads'):raise AssertionError('multipart must not call request.body')
        return await original(self)
    monkeypatch.setattr(Request,'body',no_upload_body)
    async def scenario():
        app=create_app(store=commands.store,auth=Auth(),box=commands,root=commands.root)
        with commands.store.connect() as c:
            c.execute('INSERT INTO easel_chat_sessions VALUES(?,?)',('upload-session','{"id":"upload-session"}'))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='https://temp.local') as client:
            base={'content-type':'multipart/form-data; boundary=test','x-operation-id':'stream-upload-once'}
            assert (await client.post('/api/upload',content=ForbiddenBody(),headers=base)).status_code==401
            client.cookies.set('__Host-desk_session','fixture-owner')
            assert (await client.post('/api/upload',content=ForbiddenBody(),headers=base)).status_code==403
            config=(await client.get('/api/config')).json()
            headers={'Origin':'https://temp.local','X-CSRF-Token':config['csrf'],'X-Operation-ID':'stream-upload-once'}
            values=dict(data={'sessionId':'upload-session'},files={'files':('original.txt',b'original','text/plain')},headers=headers)
            first=await client.post('/api/upload',**values)
            assert first.status_code==200,first.text
            again=await client.post('/api/upload',**values)
            assert again.status_code==200 and again.json()==first.json()
            ref=first.json()['files'][0]
            assert commands.file(ref['id'])[1].read_bytes()==b'original'
            assert (await client.get('/api/upload/limits')).json()=={'ok':True,'max_mb':50}
            raw_headers={**headers,'Content-Type':'application/octet-stream','X-File-Name':'raw.txt','X-Operation-ID':'raw-upload-once'}
            # No receive at all until authorization and CSRF have succeeded.
            client.cookies.clear()
            assert (await client.post('/api/uploads',headers=raw_headers,content=ForbiddenBody())).status_code==401
            client.cookies.set('__Host-desk_session','fixture-owner')
            assert (await client.post('/api/uploads',headers={**raw_headers,'X-CSRF-Token':'bad'},content=ForbiddenBody())).status_code==403
            class FiftyMB(httpx.AsyncByteStream):
                async def __aiter__(self):
                    for _ in range(50):yield b'x'*1024**2
            raw=await client.post('/api/uploads',headers=raw_headers,content=FiftyMB())
            assert raw.status_code==200,raw.text
            assert raw.json()['size']==50*1024**2
            registered=commands.file(raw.json()['id'])[1]
            assert registered.stat().st_size==50*1024**2
            conflicting=await client.post('/api/uploads',headers=raw_headers,content=b'changed')
            assert conflicting.status_code==400
            assert registered.stat().st_size==50*1024**2
        await app.state.chat.close()
    asyncio.run(scenario())
