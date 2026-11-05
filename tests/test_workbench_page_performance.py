import json
import math
import time
import pytest

from easel_workbench.diagnostics import page_performance as perf


def summary():
    return {'kind':'summary','metric':'boot','screen':'home','platform':'android',
            'release':'native-test','buckets':[0,0,0,1,0,0,0,0,0]}


def test_allowlisted_metadata_only():
    values,dropped=perf.validate({'events':[summary()],'dropped':0})
    assert values==[summary()] and dropped==0
    for change in ({'url':'/chat/private'},{'release':'native-test?token=secret'},
                   {'buckets':[1]*100},{'screen':'private title'},{'buckets':[True]*9}):
        with pytest.raises(ValueError):perf.validate({'events':[{**summary(),**change}],'dropped':0})
    with pytest.raises(ValueError):perf.validate({'events':[{'kind':'slow','metric':'boot','screen':'home','platform':'android','release':'native-test','duration_ms':math.nan,'outcome':'failed','hidden':False}],'dropped':0})


def test_bounded_nonblocking_sink_writes_only_diagnostics(tmp_path):
    sink=perf.Sink(tmp_path,max_bytes=1024*1024)
    try:
        assert sink.submit([summary()],0)
        sink.queue.join()
        path=next(tmp_path.glob('performance-*.jsonl'))
        data=json.loads(path.read_text(encoding='utf8'))
        assert data['events']==[summary()] and data['dropped']==0
        for _ in range(59):assert sink.submit([summary()],0)
        assert not sink.submit([summary()],0)
        assert sink.dropped==1
    finally:sink.close()


def test_full_queue_drops_without_blocking_business(tmp_path,monkeypatch):
    import threading
    entered=threading.Event();release=threading.Event()
    def blocked(_self,_value):entered.set();release.wait(3)
    monkeypatch.setattr(perf.Sink,'_write',blocked)
    sink=perf.Sink(tmp_path,queue_size=1)
    try:
        assert sink.submit([summary()],0) and entered.wait(2)
        assert sink.submit([summary()],0)
        start=time.monotonic();assert sink.submit([summary()],0) is False
        assert time.monotonic()-start<0.2 and sink.dropped==1
    finally:release.set();sink.close()


def test_real_endpoint_requires_session_and_csrf_and_never_records_input(tmp_path,monkeypatch):
    import importlib.util
    import httpx
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    spec=importlib.util.spec_from_file_location('page_perf_fixture',root/'tests/workbench_native_browser.py')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    native=tmp_path/'native-test';native.mkdir();(native/'native-manifest.json').write_text(json.dumps({'release':'native-test','files':{}}),encoding='utf8')
    sink=perf.Sink(tmp_path/'logs');monkeypatch.setattr(perf,'_sink',sink)
    try:
        with helper.isolated(native,b'') as fixture, httpx.Client(base_url=fixture['origin'],verify=False,trust_env=False) as client:
            data={'events':[summary()],'dropped':0};headers={'Origin':fixture['origin']}
            assert client.post('/api/diagnostics/page-performance',json=data,headers=headers).status_code==401
            client.cookies.set('__Host-desk_session','fixture-owner')
            config=client.get('/api/config');assert config.status_code==200
            assert client.post('/api/diagnostics/page-performance',json=data,headers=headers).status_code==403
            headers['X-CSRF-Token']=config.json()['csrf']
            assert client.post('/api/diagnostics/page-performance',json=data,headers={**headers,'Origin':'https://foreign.invalid'}).status_code==403
            assert client.post('/api/diagnostics/page-performance',content=b' '*17000,headers={**headers,'Content-Type':'application/json'}).status_code in (400,413)
            assert client.post('/api/diagnostics/page-performance',json={'events':[{**summary(),'url':'private'}],'dropped':0},headers=headers).status_code==400
            response=client.post('/api/diagnostics/page-performance',json=data,headers=headers)
            assert response.status_code==200 and response.json()['accepted'] is True
            sink.queue.join();assert 'private' not in next((tmp_path/'logs').glob('*.jsonl')).read_text(encoding='utf8')
    finally:sink.close()


def test_private_shell_nonce_and_trace_do_not_relax_csp(tmp_path):
    import hashlib,re
    from easel_workbench.runtime.native_preview import page
    root=tmp_path;folder=root/'native-releases/native-test';folder.mkdir(parents=True)
    source='<html><head></head><body><script nonce="__DESK_STYLE_NONCE__">x()</script></body></html>'
    (folder/'index.html').write_text(source,encoding='utf8');manifest={'release':'native-test','files':{'index.html':hashlib.sha256(source.encode()).hexdigest()}}
    (folder/'native-manifest.json').write_text(json.dumps(manifest),encoding='utf8')
    response=page(root,folder,manifest,trace='a'*16);body=response.body.decode();csp=response.headers['content-security-policy']
    nonce=re.search(r'<script nonce="([^"]+)"',body).group(1)
    assert "script-src 'self' 'nonce-"+nonce+"'" in csp and "'unsafe-inline'" not in csp
    assert '<meta name="desk-document-trace" content="'+'a'*16+'">' in body
    assert 'bad-trace' not in page(root,folder,manifest,trace='bad-trace').body.decode()
