"""Exact host media protocols coexist with native output directories (TEMP)."""
import asyncio
import hashlib
import importlib.util
import io
from pathlib import Path

import httpx
from PIL import Image

spec = importlib.util.spec_from_file_location('media_route_fixtures', Path(__file__).with_name('test_workbench_preview_frames.py'))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
runtime, commands = fixtures.runtime, fixtures.commands
from easel_workbench.runtime.auth_forms import SESSION
from easel_workbench.runtime.native_api import supports


def test_ownership_excludes_exact_protocols_and_keeps_same_named_output_directories():
    digest = 'a' * 64
    for path in (
        '/api/media/images/picture/' + digest + '/original',
        '/api/media/images/picture/' + digest + '/thumb-256',
        '/api/media/jobs/history', '/api/media/jobs/history/transcript',
        '/api/media/accounts', '/api/media/accounts/session/qr',
    ):
        assert not supports(path), path
        assert not supports(path, 'GET') and not supports(path, 'HEAD'), path
    for directory in ('images', 'jobs', 'accounts'):
        assert supports('/api/media/' + directory + '/notes.html', 'GET')
        assert supports('/api/output/' + directory + '/notes.html', 'GET')
    assert supports('/api/media/jobs/history/notes.html', 'GET')
    assert supports('/api/media/images/notes.html', 'HEAD')


def test_full_http_image_versions_auth_cache_and_ordinary_media_outputs(commands):
    app = fixtures.app_for(commands)
    raw = io.BytesIO()
    Image.new('RGB', (12, 9), '#a04020').save(raw, format='PNG')
    image = raw.getvalue()
    source = commands.root / 'TEMP-original.png'
    source.write_bytes(image)
    stored = commands.register_file('route-picture', 'original.png', source)
    descriptor = app.state.media.describe(stored)
    digest = hashlib.sha256(image).hexdigest()
    assert descriptor['content_sha256'] == digest
    html = b'<!doctype html><h1>TEMP same-named ordinary output directory</h1>'
    for directory in ('images', 'jobs', 'accounts'):
        folder = commands.root / 'outputs' / directory
        folder.mkdir(parents=True)
        (folder / 'notes.html').write_bytes(html)
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://native.test') as client:
            for path in (descriptor['display_url'], descriptor['thumbnail_url']):
                rejected = await client.get(path)
                assert rejected.status_code == 401 and rejected.headers['x-frame-options'] == 'DENY'
            client.cookies.set(SESSION, 'fixture-owner')
            original = await client.get(descriptor['display_url'])
            assert original.status_code == 200 and original.content == image
            assert hashlib.sha256(original.content).hexdigest() == digest
            assert original.headers['content-type'] == 'image/png'
            assert original.headers['x-frame-options'] == 'DENY'
            assert original.headers['content-security-policy'] == "default-src 'none'; sandbox allow-downloads"
            head = await client.head(descriptor['display_url'])
            assert head.status_code == 200 and head.content == b''
            assert int(head.headers['content-length']) == len(image)
            cached = await client.get(descriptor['display_url'], headers={'If-None-Match': original.headers['etag']})
            assert cached.status_code == 304 and cached.content == b''
            assert cached.headers['x-frame-options'] == 'DENY'
            thumbnail = await client.get(descriptor['thumbnail_url'])
            assert thumbnail.status_code == 200 and thumbnail.headers['x-frame-options'] == 'DENY'
            with Image.open(io.BytesIO(thumbnail.content)) as decoded:
                decoded.verify()
            for path, code in (
                (descriptor['display_url'] + '?not-a-display-query=1', 400),
                (descriptor['display_url'].replace(digest, '0' * 64), 410),
                (descriptor['display_url'].replace('route-picture', 'missing-picture'), 404),
            ):
                failed = await client.get(path)
                assert failed.status_code == code, (path, failed.status_code, failed.text)
                assert failed.headers['x-frame-options'] == 'DENY'
            refused = await client.post(descriptor['display_url'])
            assert refused.status_code == 405 and refused.headers['x-frame-options'] == 'DENY'
            for directory in ('images', 'jobs', 'accounts'):
                plain_output = await client.get('/api/media/' + directory + '/notes.html')
                assert plain_output.status_code == 200 and plain_output.content == html
                assert plain_output.headers['x-frame-options'] == 'SAMEORIGIN'
                metadata = await client.get('/api/output/' + directory + '/notes.html')
                assert metadata.status_code == 200 and metadata.json()['content'].encode() == html
    asyncio.run(scenario())


def test_full_http_existing_account_and_history_read_handlers(commands):
    from easel_workbench.runtime.easel_integration import EaselIntegration
    app = fixtures.app_for(commands)
    text = 'TEMP 原始历史转写文本\n未触发制作。'
    source = commands.root / 'TEMP-history.txt'
    source.write_bytes(text.encode('utf-8'))
    stored = commands.register_file('route-transcript', 'history.txt', source)
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    commands.easel = EaselIntegration(commands, autostart=False)
    history = {'id': 'route-history', 'stage': 'transcribe', 'status': 'completed',
               '_private': 'not returned', 'artifacts': [{**stored, 'sha256': digest}]}
    with commands.store.connect() as c:
        commands.easel._put_job(c, history)
        app.state.easel_accounts._put(c, {'id': 'route-account', 'revision': 7, 'state': 'login',
                                          '_native_managed': True, '_private': 'not returned'})
    qr = commands.root / 'data/easel-accounts/route-account/qr.png'
    qr.parent.mkdir(parents=True)
    qr.write_bytes(b'TEMP historical QR bytes; no driver started')
    async def scenario():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='https://native.test') as client:
            for path in ('/api/media/accounts', '/api/media/accounts/route-account/qr?revision=7',
                         '/api/media/jobs/route-history', '/api/media/jobs/route-history/transcript'):
                rejected = await client.get(path)
                assert rejected.status_code == 401 and rejected.headers['x-frame-options'] == 'DENY'
            client.cookies.set(SESSION, 'fixture-owner')
            accounts = await client.get('/api/media/accounts')
            assert accounts.status_code == 200
            assert accounts.json()['sessions'][0]['id'] == 'route-account'
            assert '_private' not in accounts.json()['sessions'][0]
            image = await client.get('/api/media/accounts/route-account/qr?revision=7')
            assert image.status_code == 200 and image.content == qr.read_bytes()
            stale = await client.get('/api/media/accounts/route-account/qr?revision=6')
            assert stale.status_code == 404 and stale.headers['x-frame-options'] == 'DENY'
            job = await client.get('/api/media/jobs/route-history')
            assert job.status_code == 200 and job.json()['id'] == 'route-history'
            assert '_private' not in job.json()
            transcript = await client.get('/api/media/jobs/route-history/transcript')
            assert transcript.status_code == 200
            assert transcript.json() == {'text': text, 'artifact_id': stored['id'], 'sha256': digest,
                                          'version_id': 'route-history', 'automatic_send': False}
            missing = await client.get('/api/media/jobs/missing-history')
            assert missing.status_code == 404 and missing.json()['error'] == '媒体任务不存在'
            for response in (accounts, image, job, transcript, missing):
                assert response.headers['x-frame-options'] == 'DENY'
    asyncio.run(scenario())
