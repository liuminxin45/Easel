"""Retired root entry keeps only migration and inert compatibility contracts."""
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

from easel_workbench.runtime import pwa_assets
from easel_workbench.runtime.http_context import Context

spec = importlib.util.spec_from_file_location('legacy_pwa_fixtures', Path(__file__).with_name('test_workbench_skill_commands.py'))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
runtime, commands = fixtures.runtime, fixtures.commands
archive_spec = importlib.util.spec_from_file_location('legacy_archive_fixtures', Path(__file__).with_name('test_workbench_archive_assets.py'))
archive_fixtures = importlib.util.module_from_spec(archive_spec)
archive_spec.loader.exec_module(archive_fixtures)
stored = archive_fixtures.stored


@pytest.mark.parametrize('path', pwa_assets.MIGRATION)
def test_root_migration_assets_ignore_missing_old_release(tmp_path, path):
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'active-web.json').write_text('{"release":"archived-old-release"}')
    body, mime = pwa_assets.asset(path, project=tmp_path)
    assert body and mime
    assert pwa_assets.asset(path, web=tmp_path / 'missing-old-web') == (body, mime)


def test_unknown_paths_do_not_resolve_the_old_selector(tmp_path):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'data/active-web.json').write_text('invalid json')
    assert pwa_assets.asset('/native/', project=tmp_path) is None
    assert pwa_assets.asset('/api/config', project=tmp_path) is None


def test_legacy_manifest_updates_existing_app_start_without_changing_identity():
    manifest = json.loads(pwa_assets.asset('/manifest.webmanifest')[0])
    assert manifest['id'] == '/' and manifest['scope'] == '/'
    assert manifest['start_url'] == '/native/'
    offline = pwa_assets.asset('/offline.html')[0].decode()
    assert 'href="/native/"' in offline
    assert '<script' not in offline


def test_migration_worker_is_no_store_root_scoped_and_head_safe():
    request = Context('GET', '/sw.js', [])
    assert pwa_assets.serve(request, '/sw.js')
    response = request.response()
    assert response.status_code == 200
    assert 'no-store' in response.headers['cache-control']
    assert response.headers['service-worker-allowed'] == '/'
    head = Context('HEAD', '/sw.js', [])
    pwa_assets.serve(head, '/sw.js')
    assert head.response().body == b''


def test_necessary_old_static_files_are_still_read_only(tmp_path):
    path = tmp_path / 'auth-app.js'
    path.write_bytes(b'/* retained auth compatibility */')
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    assert pwa_assets.asset('/auth-app.js', web=tmp_path)[0] == path.read_bytes()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_public_compatibility_uses_exact_archive_alias_after_old_selector_retirement(stored):
    root, _, _ = stored
    assert pwa_assets.asset('/auth-app.js', project=root)[0] == b'auth compatibility'
    (root / 'data').mkdir()
    (root / 'data/active-web.json').write_text('{"retired":true}')
    assert pwa_assets.asset('/icons/app.svg', project=root)[0] == b'<svg/>'
    with pytest.raises(FileNotFoundError):
        pwa_assets.asset('/auth-ui.js', project=root)
    assert pwa_assets.asset('/native/', project=root) is None
    for path in pwa_assets.MIGRATION:
        assert pwa_assets.asset(path, project=root)[0]


def test_archive_alias_does_not_replace_existing_live_compatibility_bytes(stored):
    root, _, _ = stored
    live = root / 'web'
    live.mkdir()
    (live / 'auth-app.js').write_bytes(b'live compatibility')
    assert pwa_assets.asset('/auth-app.js', project=root)[0] == b'live compatibility'


def test_broken_archive_registry_cannot_break_native_or_migration_routes(stored):
    root, _, registry = stored
    registry.write_text('not json')
    assert pwa_assets.asset('/api/config', project=root) is None
    assert pwa_assets.asset('/native/', project=root) is None
    assert pwa_assets.asset('/sw.js', project=root)[0]


def test_default_auth_forms_keep_their_original_layout_and_inert_mode_has_no_asset_dependency(tmp_path):
    from types import SimpleNamespace
    from easel_workbench.runtime.auth_forms import Forms
    (tmp_path / 'style.css').write_text('body{color:black}')
    state = SimpleNamespace(web_root=tmp_path)
    original = Forms(state).page('synthetic-csrf', '/native/')
    assert 'body{color:black}' in original and '/auth-app.js' in original
    (tmp_path / 'style.css').unlink()
    inert = Forms(state, inert=True).page('synthetic-csrf', '/native/')
    assert 'name="csrf" value="synthetic-csrf"' in inert
    assert '<script' not in inert and '<style' not in inert


def app_for(commands):
    from easel_workbench.runtime.toolbox_server import create_app
    class Auth:
        data = {'origin': 'https://native.test', 'host': 'native.test', 'secret': 'A' * 32}
        def session(self, token):
            return {'csrf': 'fixture', 'until': 9999999999} if token in ('fixture-owner', 'fixture-new-session') else None
        def login(self, code):
            return (303, 'fixture-new-session') if code == '123456' else (403, None)
    native = commands.root / 'native-releases/native-legacy-fixture'
    native.mkdir(parents=True)
    files = {'index.html': '<html><meta name="native-release" content="native-legacy-fixture"><body>NEW NATIVE ONLY</body></html>',
             'auth.html': '<html><body>NEW NATIVE LOGIN</body></html>'}
    for name, body in files.items():
        (native / name).write_text(body, encoding='utf-8')
    manifest = {'schema': 1, 'release': native.name, 'files': {name: hashlib.sha256((native / name).read_bytes()).hexdigest() for name in files}}
    (native / 'native-manifest.json').write_text(json.dumps(manifest))
    (commands.root / 'data/active-native.json').write_text(json.dumps({'release': native.name, 'manifest_sha256': hashlib.sha256((native / 'native-manifest.json').read_bytes()).hexdigest()}))
    # All new routes must survive a retired selector pointing to absent bytes.
    (commands.root / 'data/active-web.json').write_text('{"release":"missing-retired-web"}')
    return create_app(store=commands.store, auth=Auth(), box=commands, root=commands.root, studio=commands.studio)


def test_server_native_and_old_navigation_do_not_require_old_web(commands):
    async def scenario():
        app = app_for(commands)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://native.test',
                                     cookies={'__Host-toolbox-session': 'fixture-owner'}) as client:
            # Obtain actual cookie name without assuming a historical spelling.
            from easel_workbench.runtime.auth_forms import SESSION
            client.cookies.set(SESSION, 'fixture-owner')
            for path in ('/sw.js', '/toolbox-boot.js', '/manifest.webmanifest', '/offline.html'):
                assert (await client.get(path)).status_code == 200
            for path in ('/', '/toolbox', '/articles/new', '/works', '/settings', '/account', '/account/password', '/wiki', '/workbench'):
                response = await client.get(path, follow_redirects=True)
                assert response.status_code == 200, (path, response.status_code, response.text)
                assert response.url.path == '/native/' and 'NEW NATIVE ONLY' in response.text
            assert (await client.get('/api/config')).status_code == 200
    asyncio.run(scenario())


def test_login_document_moves_but_native_csrf_fetch_and_post_remain(commands):
    async def scenario():
        app = app_for(commands)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://native.test') as client:
            navigation = await client.get('/login?next=%2Fnative%2F', headers={'Sec-Fetch-Mode': 'navigate', 'Accept': 'text/html'})
            assert navigation.status_code == 303
            assert navigation.headers['location'] == '/native/login?next=%2Fnative%2F'
            challenge = await client.get('/login?next=%2Fnative%2F', headers={'Accept': '*/*', 'Sec-Fetch-Mode': 'cors'})
            assert challenge.status_code == 200 and 'name="csrf"' in challenge.text
            assert '<script' not in challenge.text and '<style' not in challenge.text
            import re
            token = re.search('name="csrf" value="([^"]+)"', challenge.text)[1]
            rejected = await client.post('/login', data={'csrf': token, 'code': '000000', 'next': '/native/'},
                                         headers={'Origin': 'https://native.test', 'Sec-Fetch-Site': 'same-origin'})
            assert rejected.status_code == 403 and '验证码不正确' in rejected.text
            accepted = await client.post('/login', data={'csrf': token, 'code': '123456', 'next': '/native/'},
                                         headers={'Origin': 'https://native.test', 'Sec-Fetch-Site': 'same-origin'}, follow_redirects=True)
            assert accepted.status_code == 200 and accepted.url.path == '/native/'
            assert 'NEW NATIVE ONLY' in accepted.text
    asyncio.run(scenario())


def test_unauthenticated_legacy_chat_and_account_paths_open_native_login(commands):
    async def scenario():
        from urllib.parse import parse_qs, urlsplit
        app = app_for(commands)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://native.test') as client:
            for path in ('/chat', '/chat/exact?draft=keep', '/account/password', '/works/exact?version=v01'):
                response = await client.get(path)
                assert response.status_code == 303
                location = urlsplit(response.headers['location'])
                assert location.path == '/native/login'
                destination = urlsplit(parse_qs(location.query)['next'][0])
                assert destination.path == '/native/' and parse_qs(destination.query)['path'] == [path]
            assert (await client.get('/api/config')).status_code == 401
    asyncio.run(scenario())
