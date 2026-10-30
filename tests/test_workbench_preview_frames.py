"""Authenticated HTML preview boundaries; all files and servers are TEMP-only."""
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import httpx
import pytest
from starlette.responses import Response

spec = importlib.util.spec_from_file_location('preview_command_fixtures', Path(__file__).with_name('test_workbench_skill_commands.py'))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
runtime, commands = fixtures.runtime, fixtures.commands

from easel_workbench.runtime.auth_forms import SESSION
from easel_workbench.runtime.native_api import HTML_PREVIEW_CSP, is_html_preview_response


def app_for(box):
    from easel_workbench.runtime.toolbox_server import create_app
    class Auth:
        data = {'origin': 'https://native.test', 'host': 'native.test', 'secret': 'A' * 32}
        def session(self, token):
            return {'csrf': 'fixture', 'until': 9999999999} if token == 'fixture-owner' else None
    return create_app(store=box.store, auth=Auth(), box=box, root=box.root, studio=box.studio)


def seed(box, body=b'<!doctype html><h1>TEMP exact HTML</h1><script>document.body.dataset.inline="ran"</script>'):
    directory = box.root / 'outputs/preview'
    directory.mkdir(parents=True)
    path = directory / 'exact.html'
    path.write_bytes(body)
    (directory / 'plain.txt').write_text('TEMP plain', encoding='utf-8')
    registered = box.register_file('preview-registered', 'registered.html', path)
    return body, '/api/media/preview/exact.html', '/api/media/__workbench__/' + registered['id'] + '/' + registered['name']


def test_only_validated_html_media_get_and_head_can_be_framed(commands):
    body, *paths = seed(commands)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app_for(commands)),
                                     base_url='https://native.test', cookies={SESSION: 'fixture-owner'}) as client:
            for path in paths:
                for method in ('GET', 'HEAD'):
                    response = await client.request(method, path)
                    assert response.status_code == 200, response.text
                    assert response.headers['x-frame-options'] == 'SAMEORIGIN'
                    assert response.headers['content-security-policy'] == HTML_PREVIEW_CSP
                    assert response.headers['x-content-type-options'] == 'nosniff'
                    assert response.content == (body if method == 'GET' else b'')
                    assert int(response.headers['content-length']) == len(body)
                download = await client.get(path + '?download=1')
                assert download.status_code == 200 and download.content == body
                assert download.headers['x-frame-options'] == 'DENY'
                assert download.headers['content-disposition'] == 'attachment'
                assert download.headers['content-security-policy'] == HTML_PREVIEW_CSP
                for range_value in ('bytes=0-9', 'bytes=999999-', 'malformed'):
                    complete = await client.get(path, headers={'Range': range_value})
                    assert complete.status_code == 200 and complete.content == body
                    assert complete.headers['x-frame-options'] == 'SAMEORIGIN'
                    assert complete.headers['content-security-policy'] == HTML_PREVIEW_CSP
                    assert complete.headers['accept-ranges'] == 'none'
                range_download = await client.get(path + '?download=1', headers={'Range': 'malformed'})
                assert range_download.status_code == 200 and range_download.content == body
                assert range_download.headers['x-frame-options'] == 'DENY'
            plain = await client.get('/api/media/preview/plain.txt', headers={'Range': 'bytes=0-3'})
            assert plain.status_code == 206 and plain.content == b'TEMP'
            assert plain.headers['x-frame-options'] == 'DENY'
    asyncio.run(scenario())


def test_preview_like_urls_and_client_headers_cannot_relax_denial(commands):
    seed(commands)
    secret = commands.root / 'outputs/_sessions/secret.html'
    secret.parent.mkdir(parents=True)
    secret.write_text('<h1>private frozen input</h1>', encoding='utf-8')
    async def scenario():
        app = app_for(commands)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://native.test') as client:
            forged = {'X-Easel-Html-Preview': 'true', 'X-Frame-Options': 'SAMEORIGIN',
                      'Content-Security-Policy': "frame-ancestors *"}
            response = await client.get('/api/media/preview/exact.html', headers=forged)
            assert response.status_code == 401 and response.headers['x-frame-options'] == 'DENY'
            client.cookies.set(SESSION, 'fixture-owner')
            for path, expected in (
                ('/api/media/preview/missing.html', 404),
                ('/api/media/__workbench__/missing/missing.html', 400),
                ('/api/media/_sessions/secret.html', 403),
                ('/api/media/preview/%2e%2e/%2e%2e/secret.html', 403),
                ('/api/media/preview/plain.txt', 200),
                ('/api/output/preview/exact.html', 200),
                ('/login', 200), ('/native/login', 503), ('/nothing.html', 404),
            ):
                response = await client.get(path, headers=forged)
                assert response.status_code == expected, (path, response.status_code, response.text)
                assert response.headers['x-frame-options'] == 'DENY', path
            response = await client.post('/api/media/preview/exact.html', json={}, headers={
                **forged, 'Origin': 'https://native.test', 'X-CSRF-Token': 'wrong', 'X-Operation-ID': 'forged-preview'})
            assert response.status_code == 403 and response.headers['x-frame-options'] == 'DENY'
    asyncio.run(scenario())


def test_framing_capability_is_not_a_serialized_header_or_generic_response():
    for marker in (None, True, 'true', object()):
        response = Response('<h1>not an approved file</h1>', media_type='text/html', headers={
            'Content-Security-Policy': HTML_PREVIEW_CSP, 'X-Easel-Html-Preview': 'true'})
        response._easel_html_preview = marker
        assert not is_html_preview_response(response)
    directives = {part.strip().split()[0]: part.strip().split()[1:] for part in HTML_PREVIEW_CSP.split(';')}
    assert directives['sandbox'] == ['allow-scripts']
    assert directives['script-src'] == ["'unsafe-inline'"]
    for key in ('default-src', 'connect-src', 'form-action', 'base-uri', 'frame-src', 'object-src', 'worker-src'):
        assert directives[key] == ["'none'"]
    assert directives['frame-ancestors'] == ["'self'"]
    assert not any('http' in token or token == "'self'" for key in ('img-src', 'media-src', 'font-src') for token in directives[key])


@pytest.mark.skipif(os.environ.get('EASEL_PREVIEW_BROWSER') != '1', reason='Explicit real Edge TEMP acceptance; set EASEL_PREVIEW_BROWSER=1 and EASEL_PREVIEW_NATIVE')
def test_actual_official_iframe_renders_with_opaque_scripts_and_no_network(tmp_path):
    """Real Edge; unchanged official iframe and unmodified output bytes."""
    from urllib.parse import urlencode
    from playwright.sync_api import sync_playwright, expect
    module_spec = importlib.util.spec_from_file_location('preview_native_browser_fixture', Path(__file__).with_name('workbench_native_browser.py'))
    browser_fixture = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(browser_fixture)
    native = Path(os.environ['EASEL_PREVIEW_NATIVE']).resolve()
    evidence = Path(os.environ.get('EASEL_PREVIEW_EVIDENCE', str(tmp_path / 'preview-browser'))).resolve()
    evidence.mkdir(parents=True, exist_ok=True)
    report = {'passed': False, 'physical_mobile_device_tested': False, 'real_model_calls': 0,
              'real_platform_writes': 0, 'native': str(native), 'cases': [],
              'resource_policy': 'Inline script/style and data/blob media only; network images, fonts, scripts and APIs are intentionally blocked.'}
    try:
        with browser_fixture.isolated(native, b'TEMP unused image') as fixture, sync_playwright() as pw:
            origin = fixture['origin']
            source = '''<!doctype html><meta name="viewport" content="width=device-width">
<style>body{padding:16px}h1{margin:0}</style><h1>TEMP visible exact HTML</h1>
<pre id="probe">waiting</pre><button id="copy">Copy TEMP text</button><p id="copy-result"></p>
<form action="ORIGIN/api/ideas?preview-probe=form" method="post"><button id="submit">Blocked form</button></form>
<img src="ORIGIN/api/config?preview-probe=image" alt="network image intentionally blocked">
<script>
const result={inline:true,parentBlocked:false,cookieBlocked:false,storageBlocked:false,fetchBlocked:false,evalBlocked:false};
try{parent.document.body.dataset.previewEscape='bad'}catch(e){result.parentBlocked=true}
try{document.cookie}catch(e){result.cookieBlocked=true}
try{localStorage.getItem('private')}catch(e){result.storageBlocked=true}
try{eval('1+1')}catch(e){result.evalBlocked=true}
fetch('ORIGIN/api/config?preview-probe=fetch',{credentials:'include'}).then(()=>{}).catch(()=>{result.fetchBlocked=true;document.querySelector('#probe').textContent=JSON.stringify(result)});
document.querySelector('#copy').onclick=()=>{const range=document.createRange();range.selectNodeContents(document.querySelector('h1'));getSelection().removeAllRanges();getSelection().addRange(range);try{document.querySelector('#copy-result').textContent=String(document.execCommand('copy'))}catch(e){document.querySelector('#copy-result').textContent=e.name}};
</script>'''.replace('ORIGIN', origin).encode('utf-8')
            _, normal, registered = seed(fixture['box'], source)
            box = fixture['box']
            box.create({'id': 'preview-work', 'title': 'TEMP registered HTML', 'material': 'TEMP only', 'format': 'poster', 'files': []})
            value, path = box.file('preview-registered')
            with box.store.connect() as c:
                c.execute('UPDATE toolbox_jobs SET status=?,reply=?,finished_at=? WHERE id=?', ('completed', 'TEMP seeded HTML', '2026-10-31T00:00:00+00:00', 'preview-work'))
                c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)', ('preview-artifact', 'preview-work', value['name'], str(path), value['mime']))
            inbound = []
            original_stack = fixture['app'].middleware_stack
            class Observe:
                async def __call__(self, scope, receive, send):
                    if scope['type'] == 'http':
                        inbound.append(scope['path'] + '?' + scope.get('query_string', b'').decode())
                    await original_stack(scope, receive, send)
            fixture['app'].middleware_stack = Observe()
            browser = pw.chromium.launch(channel='msedge', headless=True, args=['--ignore-certificate-errors'])
            context = browser.new_context(ignore_https_errors=True, viewport={'width': 390, 'height': 844}, has_touch=True, is_mobile=True)
            context.add_cookies([{'name': SESSION, 'value': 'fixture-owner', 'url': origin, 'secure': True, 'httpOnly': True, 'sameSite': 'Strict'}])
            page = context.new_page()
            for label, relative, api_path in (
                ('outputs', 'preview/exact.html', normal),
                ('artifact', '__workbench__/preview-artifact/registered.html', '/api/media/__workbench__/preview-artifact/registered.html'),
            ):
                route = '/works?' + urlencode({'path': relative})
                page.goto(origin + '/native/?' + urlencode({'path': route}), wait_until='domcontentloaded')
                iframe = page.locator('.drawer iframe')
                expect(iframe).to_be_visible(timeout=20000)
                assert iframe.get_attribute('sandbox') == 'allow-scripts'
                assert iframe.get_attribute('allow') == 'clipboard-write'
                frame = iframe.content_frame
                expect(frame.locator('h1')).to_have_text('TEMP visible exact HTML')
                expect(frame.locator('#probe')).to_contain_text('"fetchBlocked":true')
                actual = json.loads(frame.locator('#probe').inner_text())
                assert all(actual.values()), actual
                assert page.locator('body').get_attribute('data-preview-escape') is None
                frame.locator('#copy').click()
                copy_result = frame.locator('#copy-result').inner_text()
                assert copy_result in ('true', 'false'), copy_result
                old_url = frame.locator('body').evaluate('()=>location.href')
                frame.locator('#submit').click()
                page.wait_for_timeout(150)
                assert frame.locator('body').evaluate('()=>location.href') == old_url
                response = context.request.get(origin + api_path)
                assert response.status == 200 and response.body() == source
                assert response.headers['x-frame-options'] == 'SAMEORIGIN'
                screenshot = evidence / (label + '-390.png')
                page.screenshot(path=str(screenshot))
                report['cases'].append({'branch': label, 'html_sha256': hashlib.sha256(source).hexdigest(),
                                        'script_probe': actual, 'copy_execCommand': copy_result,
                                        'screenshot': str(screenshot), 'source_bytes_unchanged': True})
            assert not any('preview-probe=' in item for item in inbound), inbound
            assert fixture['adapter'].requests == []
            report['server_network_probes'] = [item for item in inbound if 'preview-probe=' in item]
            report['passed'] = True
            context.close()
            browser.close()
    finally:
        (evidence / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
