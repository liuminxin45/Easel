"""TEMP liveness credentials cannot become business or session authority."""
import os
import re
import json
from concurrent.futures import ThreadPoolExecutor
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
import pytest

from easel_workbench.health_endpoint import HEALTH_PATH, health_token, install_health


NONCE = 'b4' * 16
TOKEN_HEADER = 'x-workbench-health-token'
NONCE_HEADER = 'x-workbench-health-nonce'


def files(root):
    return {p.relative_to(root).as_posix(): p.read_bytes()
            for p in root.rglob('*') if p.is_file()}


def test_token_is_created_once_and_preserves_unrelated_files(tmp_path, monkeypatch):
    original = tmp_path / 'data' / 'original.txt'
    original.parent.mkdir()
    original.write_bytes(b'original business evidence\r\n')
    before = files(tmp_path)
    with pytest.raises(FileNotFoundError):
        health_token(tmp_path)
    assert files(tmp_path) == before

    first = health_token(tmp_path, create=True)
    assert re.fullmatch('[a-f0-9]{64}', first)
    token_path = tmp_path / '.local/workbench-deployment/health-token'
    assert token_path.read_bytes() == first.encode('ascii')
    created_files = files(tmp_path)
    assert set(created_files) == set(before) | {
        '.local/workbench-deployment/health-token',
        '.local/workbench-deployment/health-token.lock',
    }
    assert {name: created_files[name] for name in before} == before
    created = token_path.stat().st_mtime_ns

    # An existing token must never be silently rotated by another app start.
    monkeypatch.setattr('easel_workbench.health_endpoint.secrets.token_hex',
                        lambda *_: pytest.fail('existing health token was regenerated'))
    assert health_token(tmp_path, create=True) == first
    assert health_token(tmp_path) == first
    assert token_path.stat().st_mtime_ns == created
    assert files(tmp_path) == created_files


@pytest.mark.parametrize('bad', ['', 'short', 'F' * 64, 'a' * 63, 'a' * 65, 'z' * 64])
def test_invalid_existing_token_is_rejected_without_overwriting(tmp_path, bad):
    path = tmp_path / '.local/workbench-deployment/health-token'
    path.parent.mkdir(parents=True)
    path.write_text(bad, encoding='ascii')
    with pytest.raises(ValueError, match='Invalid private health token'):
        health_token(tmp_path, create=True)
    assert path.read_text(encoding='ascii') == bad


def test_concurrent_first_creators_share_one_complete_token(tmp_path, monkeypatch):
    from easel_workbench import health_endpoint
    actual_generate = health_endpoint.secrets.token_hex
    barrier = threading.Barrier(8)
    generated = []

    def slow_generate(size):
        generated.append(size)
        # Expose the empty-file window between O_EXCL and write. All eight
        # callers must wait for the creator rather than reading partial bytes.
        time.sleep(.1)
        return actual_generate(size)

    def create():
        barrier.wait(timeout=5)
        return health_token(tmp_path, create=True)

    monkeypatch.setattr(health_endpoint.secrets, 'token_hex', slow_generate)
    with ThreadPoolExecutor(max_workers=8) as pool:
        tokens = list(pool.map(lambda _: create(), range(8)))
    assert generated == [32]
    assert len(set(tokens)) == 1
    assert re.fullmatch('[a-f0-9]{64}', tokens[0])
    assert health_token(tmp_path) == tokens[0]


@pytest.fixture
def protected_app(tmp_path, monkeypatch):
    monkeypatch.setenv('AI_DESK_RELEASE', 'workbench-test-exact-release')
    app = FastAPI()
    calls = []

    @app.api_route('/{path:path}', methods=['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'TRACE'])
    async def owner_authentication(request: Request, path: str):
        calls.append((request.method, request.url.path))
        return JSONResponse({'error': 'authentication_required'}, status_code=401)

    install_health(app, tmp_path)
    token = health_token(tmp_path)
    with TestClient(app) as client:
        yield client, token, calls


def headers(token, nonce=NONCE):
    return [(TOKEN_HEADER, token), (NONCE_HEADER, nonce)]


def test_nonce_release_pid_are_exact_without_disclosing_token(protected_app):
    client, token, calls = protected_app
    for nonce in [NONCE, '01' * 16]:
        response = client.get(HEALTH_PATH, headers=headers(token, nonce))
        assert response.status_code == 200
        assert response.json() == {'ok': True, 'nonce': nonce, 'pid': os.getpid(),
                                   'release': 'workbench-test-exact-release'}
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers['x-workbench-health'] == '1'
        assert token not in response.text
        assert token not in str(dict(response.headers))
        assert 'set-cookie' not in response.headers
    assert calls == []


@pytest.mark.parametrize('case', [
    'missing', 'missing-token', 'missing-nonce', 'wrong-token',
    'duplicate-token', 'duplicate-nonce', 'uppercase-nonce',
    'short-nonce', 'long-nonce', 'hyphenated-nonce', 'nonhex-nonce',
])
def test_invalid_health_headers_grant_no_health_or_session(protected_app, case):
    client, token, calls = protected_app
    request_headers = headers(token)
    if case == 'missing': request_headers = []
    elif case == 'missing-token': request_headers = [(NONCE_HEADER, NONCE)]
    elif case == 'missing-nonce': request_headers = [(TOKEN_HEADER, token)]
    elif case == 'wrong-token': request_headers = headers('0' * 64 if token != '0' * 64 else '1' * 64)
    elif case == 'duplicate-token': request_headers.append((TOKEN_HEADER, token))
    elif case == 'duplicate-nonce': request_headers.append((NONCE_HEADER, NONCE))
    else:
        invalid = {'uppercase-nonce': NONCE.upper(), 'short-nonce': NONCE[:-1],
                   'long-nonce': NONCE + '0', 'hyphenated-nonce': 'b4-' * 10 + 'b4',
                   'nonhex-nonce': 'z' * 32}[case]
        request_headers = headers(token, invalid)
    response = client.get(HEALTH_PATH, headers=request_headers)
    assert response.status_code == 404
    assert response.json() == {'error': 'not_found'}
    assert response.headers['cache-control'] == 'no-store'
    assert 'x-workbench-health' not in response.headers
    assert 'set-cookie' not in response.headers
    assert token not in response.text
    assert calls == []


def test_non_ascii_token_is_rejected_without_digest_error(protected_app):
    client, token, calls = protected_app
    # Raw header bytes reach ASGI through latin-1, unlike httpx's convenient
    # string header API which rejects non-ASCII before sending the request.
    response = client.get(HEALTH_PATH, headers=[
        (TOKEN_HEADER.encode('ascii'), b'\xe9' * 64),
        (NONCE_HEADER.encode('ascii'), NONCE.encode('ascii')),
    ])
    assert response.status_code == 404
    assert response.json() == {'error': 'not_found'}
    assert 'x-workbench-health' not in response.headers
    assert 'set-cookie' not in response.headers
    assert token not in response.text
    assert calls == []


@pytest.mark.parametrize('method', ['HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS', 'TRACE'])
def test_non_get_never_returns_health_or_business_credentials(protected_app, method):
    client, token, calls = protected_app
    response = client.request(method, HEALTH_PATH, headers=headers(token))
    assert response.status_code == 404
    assert 'x-workbench-health' not in response.headers
    assert 'set-cookie' not in response.headers
    assert token not in response.text
    if method != 'HEAD': assert response.json() == {'error': 'not_found'}
    assert calls == []


@pytest.mark.parametrize('path', [
    HEALTH_PATH + '/', HEALTH_PATH + 'z', HEALTH_PATH + '/api/config',
    '/_workbench/health-other', '/api/config', '/api/chat/sessions', '/api/works',
])
@pytest.mark.parametrize('method', ['GET', 'POST'])
def test_health_token_cannot_bypass_auth_for_similar_or_business_urls(protected_app, path, method):
    client, token, calls = protected_app
    response = client.request(method, path, headers=headers(token))
    assert response.status_code == 401
    assert response.json() == {'error': 'authentication_required'}
    assert calls == [(method, path)]
    assert 'x-workbench-health' not in response.headers
    assert 'set-cookie' not in response.headers
    assert token not in response.text


def test_atomic_create_never_overwrites_an_existing_owner(tmp_path):
    from easel_workbench.runtime.feedback_ledger import atomic_create
    target = tmp_path / 'paused'
    original = b'{"owner":"existing-maintenance","operation_id":"original"}\n'
    target.write_bytes(original)
    assert atomic_create(target, {'owner': 'new-watchdog'}) is False
    assert target.read_bytes() == original
    assert set(tmp_path.iterdir()) == {target}


def test_atomic_create_concurrent_publication_has_one_complete_winner(tmp_path):
    from easel_workbench.runtime.feedback_ledger import atomic_create
    target = tmp_path / 'paused'
    barrier = threading.Barrier(8)
    payloads = [{'owner': index, 'operation_id': str(index), 'complete': ['x' * 4096, index]}
                for index in range(8)]

    def publish(index):
        barrier.wait(timeout=5)
        return atomic_create(target, payloads[index])

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(publish, range(8)))
    assert results.count(True) == 1
    assert results.count(False) == 7
    assert json.loads(target.read_text(encoding='utf-8')) == payloads[results.index(True)]
    assert set(tmp_path.iterdir()) == {target}


@pytest.mark.parametrize('already_exists', [False, True])
def test_atomic_create_partial_write_failure_does_not_publish_or_damage_owner(tmp_path, monkeypatch, already_exists):
    from easel_workbench.runtime import feedback_ledger
    target = tmp_path / 'paused'
    original = b'{"owner":"existing-owner"}\n'
    if already_exists:
        target.write_bytes(original)

    def fail_after_partial_write(temporary, value):
        temporary.write_bytes(b'{"owner":"partially-written')
        raise OSError('TEMP injected incomplete atomic write')

    monkeypatch.setattr(feedback_ledger, 'atomic', fail_after_partial_write)
    with pytest.raises(OSError, match='incomplete atomic write'):
        feedback_ledger.atomic_create(target, {'owner': 'new-watchdog'})
    assert target.exists() is already_exists
    if already_exists:
        assert target.read_bytes() == original
    assert set(tmp_path.iterdir()) == ({target} if already_exists else set())


@pytest.mark.parametrize('damaged', [b'invalid-token', b'\xff' * 64])
def test_damaged_monitor_token_does_not_prevent_existing_business_auth(tmp_path, damaged):
    target = tmp_path / '.local/workbench-deployment/health-token'
    target.parent.mkdir(parents=True)
    target.write_bytes(damaged)
    app = FastAPI()

    @app.get('/api/business')
    async def authenticated_business(request: Request):
        if request.headers.get('authorization') != 'Bearer TEMP-owner':
            return JSONResponse({'error': 'authentication_required'}, status_code=401)
        return {'business': 'ready'}

    # Installation itself must succeed; monitoring credentials have no right
    # to disable or authenticate the application's existing owner routes.
    install_health(app, tmp_path)
    with TestClient(app) as client:
        health = client.get(HEALTH_PATH, headers=headers('0' * 64))
        assert health.status_code == 404
        assert health.json() == {'error': 'not_found'}
        assert 'x-workbench-health' not in health.headers
        assert 'set-cookie' not in health.headers
        assert client.get('/api/business').status_code == 401
        assert client.get('/api/business', headers=headers('0' * 64)).status_code == 401
        business = client.get('/api/business', headers={'authorization': 'Bearer TEMP-owner'})
        assert business.status_code == 200
        assert business.json() == {'business': 'ready'}
    assert target.read_bytes() == damaged
