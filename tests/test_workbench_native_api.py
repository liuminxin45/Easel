"""TEMP-only native protocols, shared handlers and irreversible-state guards."""
import asyncio
import importlib.util
import json
from pathlib import Path

import pytest
from starlette.requests import Request

spec = importlib.util.spec_from_file_location('native_api_fixtures', Path(__file__).with_name('test_workbench_skill_commands.py'))
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
runtime, commands = fixtures.runtime, fixtures.commands

from easel_workbench.runtime.native_api import NativeApi, handle
from easel_workbench.runtime.easel_accounts import EaselAccounts
from easel_workbench.runtime.distribution_service import DistributionService


def request(path, method='GET', operation='', query=''):
    headers = [(b'x-operation-id', operation.encode())] if operation else []
    return Request({'type': 'http', 'method': method, 'path': path,
                    'query_string': query.encode(), 'headers': headers,
                    'scheme': 'https', 'server': ('native.test', 443)})


def call(box, path, method='GET', body=None, operation='', query=''):
    response = asyncio.run(handle(box, path, request(path, method, operation, query), body))
    return response, json.loads(response.body) if response is not None and hasattr(response, 'body') else None


def test_native_ideas_reuse_original_handlers_and_preserve_one_operation(commands):
    api = NativeApi(commands)
    assert api.planning.api_ideas_create.__code__.co_filename.replace('\\', '/').endswith('web_services/planning.py')
    commands._native_api = api
    body = {'title': ' 原生选题 ', 'note': '准确原话', 'status': 'pending'}
    first, value = call(commands, '/api/ideas', 'POST', body, 'native-idea-once')
    second, repeated = call(commands, '/api/ideas', 'POST', body, 'native-idea-once')
    assert first.status_code == second.status_code == 200
    assert value == repeated and value['title'] == '原生选题'
    with commands.store.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM easel_topics').fetchone()[0] == 1
        assert c.execute('SELECT COUNT(*) FROM easel_topic_history').fetchone()[0] == 1
    receipt, data = call(commands, '/api/native/operations/native-idea-once')
    assert receipt.status_code == 200 and data['state'] == 'completed' and data['result'] == value
    conflict, _ = call(commands, '/api/ideas', 'POST', {**body, 'title': '替换原请求'}, 'native-idea-once')
    assert conflict.status_code == 409


def test_native_idea_exact_source_survives_save_edit_and_get(commands):
    with commands.store.connect() as c:
        c.execute('INSERT INTO articles(id,source_job,title,body,url,run_at,run) VALUES(?,?,?,?,?,?,?)',
                  ('exact-article', 'source', 'Original source', 'Exact body', 'https://example.test/original',
                   '2026-11-01T00:00:00+08:00', 'original-run'))
    created, idea = call(commands, '/api/ideas', 'POST',
                         {'title': 'New angle', 'note': 'Original angle', 'source_id': 'exact-article'}, 'bound-idea')
    assert created.status_code == 200 and idea['source_id'] == 'exact-article'
    for index, fields in enumerate(({'title': 'Edited angle', 'note': 'Edited note'},
                                    {'title': 'Null from older client', 'source_id': None})):
        edited, value = call(commands, '/api/ideas/' + idea['id'], 'PUT', fields, 'edit-bound-' + str(index))
        assert edited.status_code == 200 and value['source_id'] == 'exact-article'
    _, listing = call(commands, '/api/ideas')
    assert next(item for item in listing if item['id'] == idea['id'])['source_id'] == 'exact-article'
    with commands.store.connect() as c:
        history = [json.loads(row[0]) for row in c.execute('SELECT document FROM easel_topic_history WHERE id=? ORDER BY revision', (idea['id'],))]
    assert len(history) == 3 and all(item['source_id'] == 'exact-article' for item in history)


@pytest.mark.parametrize('source_id', ['missing-article', '', 'Original source'])
def test_native_idea_rejects_unresolved_source_without_title_guessing(commands, source_id):
    with commands.store.connect() as c:
        c.execute('INSERT INTO articles(id,source_job,title,body,url,run_at,run) VALUES(?,?,?,?,?,?,?)',
                  ('exact-article', 'source', 'Original source', 'Body', 'https://example.test/source',
                   '2026-11-01T00:00:00+08:00', 'source-run'))
    response, _ = call(commands, '/api/ideas', 'POST', {'title': 'Original source', 'source_id': source_id}, 'bad-bound')
    assert response.status_code == 400
    _, manual = call(commands, '/api/ideas', 'POST', {'title': 'Manual'}, 'manual-for-edit')
    response, _ = call(commands, '/api/ideas/' + manual['id'], 'PUT',
                       {'title': 'Changed', 'source_id': source_id}, 'bad-bound-edit')
    assert response.status_code == 400
    with commands.store.connect() as c:
        saved = json.loads(c.execute('SELECT document FROM easel_topics WHERE id=?', (manual['id'],)).fetchone()[0])
        assert saved['title'] == 'Manual' and 'source_id' not in saved
        before = c.execute('SELECT document FROM easel_topics WHERE id=?', (manual['id'],)).fetchone()[0]
    _, listing = call(commands, '/api/ideas')
    assert len(listing) == 1 and 'source_id' not in listing[0]
    with commands.store.connect() as c:
        assert c.execute('SELECT document FROM easel_topics WHERE id=?', (manual['id'],)).fetchone()[0] == before


def test_native_calendar_is_versioned_and_delete_is_a_tombstone(commands):
    response, value = call(commands, '/api/schedule', 'POST',
                           {'title': '人工排期', 'date': '2026-11-02', 'time': '09:30'}, 'native-plan-once')
    assert response.status_code == 200
    key = value['id']
    deleted, data = call(commands, '/api/schedule/' + key, 'DELETE', {}, 'delete-native-plan')
    assert deleted.status_code == 200 and data['ok']
    _, listing = call(commands, '/api/schedule')
    assert listing == []
    with commands.store.connect() as c:
        saved = json.loads(c.execute('SELECT document FROM easel_plans WHERE id=?', (key,)).fetchone()[0])
        assert saved['deleted'] and not saved['automatic_publication']
        assert c.execute('SELECT COUNT(*) FROM easel_plan_history').fetchone()[0] == 2


def test_native_profile_raw_files_use_creator_revisions(commands):
    original = commands.creator.detail('profile', 'oil-pig')
    response, saved = call(commands, '/api/persona/oil-pig/file', 'PUT',
                           {'filename': 'identity.md', 'content': '准确身份原字\n第二行',
                            'expected_revision': original['revision']}, 'native-profile-file')
    assert response.status_code == 200 and saved['ok']
    updated = commands.creator.detail('profile', 'oil-pig')
    assert updated['identity'] == '准确身份原字\n第二行'
    assert updated['revision'] == original['revision'] + 1
    response, files = call(commands, '/api/persona/oil-pig/files')
    assert next(item for item in files['files'] if item['filename'] == 'identity.md')['content'] == updated['identity']
    rejected, _ = call(commands, '/api/persona/oil-pig/file', 'PUT',
                        {'filename': 'identity.md', 'content': '旧客户端',
                         'expected_revision': original['revision']}, 'native-stale-profile')
    assert rejected.status_code == 409


def test_native_profile_extra_document_survives_binding_only_revision(commands):
    first, data = call(commands, '/api/persona/oil-pig/file', 'PUT',
                       {'filename': 'memory.md', 'content': '独立原字记忆\n',
                        'expected_revision': commands.creator.detail('profile', 'oil-pig')['revision']}, 'native-memory-file')
    assert first.status_code == 200
    profile = commands.creator.detail('profile', 'oil-pig')
    commands.creator.command({'id': 'binding-only-revision', 'action': 'profile-save', 'profile_id': 'oil-pig',
                              'base_revision': profile['revision'], 'document': {'name': profile['name']}})
    _, files = call(commands, '/api/persona/oil-pig/files')
    assert next(item for item in files['files'] if item['filename'] == 'memory.md')['content'] == '独立原字记忆\n'


def test_native_never_exposes_frozen_system_inputs_or_deletes_originals(commands):
    secret = commands.root / 'outputs/_sessions/private/input.txt'
    secret.parent.mkdir(parents=True); secret.write_text('FROZEN PRIVATE INPUT', encoding='utf-8')
    for path in ('/api/output/_sessions/private/input.txt', '/api/media/_sessions/private/input.txt'):
        response, _ = call(commands, path)
        assert response.status_code == 403
    deleted, _ = call(commands, '/api/output/project', 'DELETE', {}, 'do-not-delete')
    assert deleted.status_code == 403 and secret.read_text(encoding='utf-8') == 'FROZEN PRIVATE INPUT'


def test_native_writes_obey_cutover_and_admission(commands):
    state = commands.root / '.local/workbench-deployment'
    state.mkdir(parents=True)
    (state / 'admission.json').write_text('{"workers":false}')
    response, _ = call(commands, '/api/ideas', 'POST', {'title': '停写期间'}, 'admission-blocks')
    assert response.status_code == 503
    with commands.store.connect() as c:
        assert not c.execute('SELECT 1 FROM easel_ui_operations WHERE id=?', ('admission-blocks',)).fetchone()
    (state / 'admission.json').write_text('{"workers":true}')
    (state / 'cutover.json').write_text(json.dumps({'phase': 'live', 'target_root': str(commands.root / 'other')}))
    response, _ = call(commands, '/api/ideas', 'POST', {'title': '错误写入者'}, 'wrong-owner')
    assert response.status_code == 503


def test_native_account_observation_binds_exact_id_and_never_nickname(commands):
    accounts = EaselAccounts(commands, DistributionService(commands), autostart=False)
    accounts.record_native_observation('wechat-oa', {'loggedIn': True, 'name': '只有昵称'})
    first = accounts.bootstrap()['sessions'][0]
    assert first['identity_status'] == 'not_provided' and not first.get('connection_id')
    accounts.record_native_observation('wechat-oa', {'loggedIn': True, 'name': '原账号', 'provider_user_id': 'gh_original'})
    original = accounts.bootstrap()['sessions'][0]
    assert original['identity_status'] == 'resolved'
    accounts.record_native_observation('wechat-oa', {'loggedIn': True, 'name': '原账号', 'provider_user_id': 'gh_other'})
    wrong = accounts.bootstrap()['sessions'][0]
    assert wrong['identity_status'] == 'mismatch'
    assert accounts.distribution.connection_internal(original['connection_id'])['account'] == 'gh_original'


def test_native_account_context_uses_shared_code_and_private_root(commands):
    accounts = EaselAccounts(commands, DistributionService(commands), autostart=False)
    native = accounts.native_context()
    assert native.api_mp_login_start.__code__.co_filename.replace('\\', '/').endswith('web_services/accounts.py')
    assert native.LOGIN_DIR == commands.root / 'outputs/_login'
    assert native.CREDENTIALS_AS_BROWSER_LOGIN is False
    assert native._account_profile_root('wechat-oa').is_relative_to(commands.root)


def test_native_pending_receipt_does_not_replay(commands):
    api = NativeApi(commands); commands._native_api = api
    body = {'title': '未确认的选题'}
    req = request('/api/ideas', 'POST', 'lost-native-result')
    from fastapi import HTTPException
    async def fail(_):
        raise RuntimeError('lost result after dispatch')
    with pytest.raises(RuntimeError):
        asyncio.run(api._mutate(req, body, fail))
    response, _ = call(commands, '/api/ideas', 'POST', body, 'lost-native-result')
    assert response.status_code == 409
    assert api.receipt('lost-native-result')['state'] == 'unavailable'


def test_native_upload_keeps_same_named_files_and_one_receipt(commands):
    with commands.store.connect() as c:
        c.execute('CREATE TABLE easel_chat_sessions(id TEXT PRIMARY KEY,document TEXT NOT NULL)')
        c.execute('INSERT INTO easel_chat_sessions VALUES(?,?)', ('native-session', '{}'))
    boundary = 'native-test-boundary'
    raw = (f'--{boundary}\r\nContent-Disposition: form-data; name="sessionId"\r\n\r\nnative-session\r\n'
           f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="same.txt"\r\n'
           'Content-Type: text/plain\r\n\r\nfirst\r\n'
           f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="same.txt"\r\n'
           'Content-Type: text/plain\r\n\r\nsecond\r\n'
           f'--{boundary}--\r\n').encode()
    def upload():
        req = request('/api/upload', 'POST', 'native-upload-once')
        req.scope['headers'].append((b'content-type', f'multipart/form-data; boundary={boundary}'.encode()))
        req._body = raw
        response = asyncio.run(handle(commands, '/api/upload', req))
        return response, json.loads(response.body)
    first, saved = upload()
    assert first.status_code == 200 and len(saved['files']) == 2
    assert saved['files'][0]['id'] != saved['files'][1]['id']
    assert commands.file(saved['files'][0]['id'])[1].read_bytes() == b'first'
    assert commands.file(saved['files'][1]['id'])[1].read_bytes() == b'second'
    _, again = upload()
    assert again == saved


def test_native_trends_only_reads_existing_results(commands, monkeypatch):
    from types import SimpleNamespace
    api = NativeApi(commands); commands._native_api = api
    api._collection_service = SimpleNamespace(
        definitions=lambda: {'native-source': {'enabled': True, 'label': '原来源'}},
        status=lambda: {'sources': [{'id': 'native-source', 'last_task': {'status': 'failed', 'error': '上次失败'}}]},
        enqueue=lambda *_: pytest.fail('Opening native trends must never collect'))
    monkeypatch.setattr(commands.store, 'article_day', lambda **_: {'items': [
        {'id': 'news-one', 'title': '准确原标题', 'url': 'https://example.test/source',
         'run_at': '2026-10-30T08:00:00+08:00'}]})
    response, data = call(commands, '/api/trends')
    assert response.status_code == 200
    group = data['trends'][0]
    assert group['stale'] and group['status'] == 'stale'
    assert group['items'][0]['title'] == '准确原标题'
    api._collection_service.status = lambda: {'sources': [{'id': 'native-source', 'last_task': {'status': 'queued'}}]}
    _, pending = call(commands, '/api/trends')
    assert pending['trends'][0]['error']['code'] == 'busy'


@pytest.mark.parametrize('status', ['partial', 'blocked', 'failed', 'cancelled'])
@pytest.mark.parametrize('has_results', [False, True])
def test_native_trends_report_incomplete_collection_truthfully(commands, monkeypatch, status, has_results):
    from types import SimpleNamespace
    api = NativeApi(commands); commands._native_api = api
    api._collection_service = SimpleNamespace(
        definitions=lambda: {'source': {'enabled': True, 'label': 'News source'}},
        status=lambda: {'sources': [{'id': 'source', 'last_task': {
            'status': status, 'warnings': ['Missing source: HTTP 500'],
            'finished_at': '2026-11-01T00:04:00+08:00'}}]},
        enqueue=lambda *_: pytest.fail('Observing a partial result must not collect'))
    rows = [{'id': 'exact-article', 'title': 'Saved result', 'run_at': '2026-11-01T00:03:00+08:00'}] if has_results else []
    monkeypatch.setattr(commands.store, 'article_day', lambda **_: {'items': rows})
    response, value = call(commands, '/api/trends')
    assert response.status_code == 200
    group = value['trends'][0]
    assert group['items'] == [{**{k: row[k] for k in ('id', 'title')}, 'hot': '', 'url': '', 'published_at': None,
                               'heat': {'value': None, 'text': '', 'unit': ''}} for row in rows]
    assert not group['ok'] and group['stale'] is has_results
    assert group['status'] == ('stale' if has_results else 'error')
    assert group['error']['code'] == 'collection_' + status
    assert group['collection_status'] == status and group['finished_at'] == '2026-11-01T00:04:00+08:00'
    assert group['warnings'] == ['Missing source: HTTP 500']
    assert value['warnings'] == ['News source：Missing source: HTTP 500']


def test_native_manual_export_uses_original_builder_and_never_marks_published(commands):
    import io
    import zipfile
    payload = {'title': '人工审核标题', 'body': '准确正文', 'tags': '', 'media': [], 'reviewed': True}
    response, exported = call(commands, '/api/manual-publish/zhihu/export', 'POST', payload, 'manual-native-export')
    assert response.status_code == 200 and exported['published'] is False
    download, _ = call(commands, '/api/output/' + exported['path'])
    assert download.status_code == 200
    identifier = exported['path'].split('/')[1]
    _, path = commands.file(identifier)
    with zipfile.ZipFile(path) as archive:
        assert archive.read('body.txt').decode() == '准确正文'
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['status'] == 'ready_for_manual_submission'
    _, again = call(commands, '/api/manual-publish/zhihu/export', 'POST', payload, 'manual-native-export')
    assert again == exported
    rejected, _ = call(commands, '/api/manual-publish/zhihu/export', 'POST', {**payload, 'reviewed': False}, 'unreviewed-native-export')
    assert rejected.status_code == 400


def test_native_receipt_can_be_read_during_pause_without_starting_new_write(commands):
    payload = {'title': '先前已完成'}
    response, first = call(commands, '/api/ideas', 'POST', payload, 'before-pause')
    assert response.status_code == 200
    state = commands.root / '.local/workbench-deployment'
    state.mkdir(parents=True); (state / 'admission.json').write_text('{"workers":false}')
    response, again = call(commands, '/api/ideas', 'POST', payload, 'before-pause')
    assert response.status_code == 200 and first == again


def test_private_environment_uses_native_endpoints_and_one_durable_queue(commands, monkeypatch):
    from easel.web_services import environment as shared
    from easel_workbench.settings import SettingsService
    from easel_workbench.runtime.connection_environment import service
    settings = SettingsService(commands)
    native = settings.installation_api('shared-native-install')
    assert native.api_env_install.__code__ is shared.api_env_install.__code__
    calls = []
    monkeypatch.setattr(service(commands), 'install', lambda value: calls.append(value) or {'id': 'exact-project-job', 'state': 'queued'})
    async def scenario():
        request = {'id': 'same-install-operation', 'tool_id': 'pw'}
        first = await settings.command('/api/env/install', request)
        assert await settings.command('/api/env/install', request) == first
        assert calls == [{'id': 'same-install-operation', 'recipe': 'browser'}]
        assert native._ENV_JOBS == {}
    asyncio.run(scenario())


def test_local_export_streams_above_upload_limit_without_replacing_registered_bytes(commands):
    source = commands.root / 'large-approved.zip'
    with source.open('wb') as output:
        for _ in range(21):
            output.write(b'x' * 1024 * 1024)
    saved = commands.register_file('streamed-export', 'approved.zip', source)
    assert saved['size'] == 21 * 1024 * 1024
    assert commands.register_file('streamed-export', 'approved.zip', source) == saved
    _, registered = commands.file('streamed-export')
    with source.open('r+b') as stream:
        stream.write(b'y')
    with pytest.raises(ValueError, match='同一附件 ID'):
        commands.register_file('streamed-export', 'approved.zip', source)
    with registered.open('rb') as stream:
        assert stream.read(1) == b'x'
    with pytest.raises(ValueError, match='20 MB'):
        commands.upload('large-http-upload', 'upload.zip', b'x' * (20 * 1024 * 1024 + 1))
    with commands.store.connect() as c:
        assert c.execute('SELECT COUNT(*) FROM toolbox_files WHERE id=?', ('streamed-export',)).fetchone()[0] == 1


def test_same_upload_id_does_not_bless_a_damaged_file(commands):
    commands.upload('stored-once', 'original.txt', b'original')
    _, registered = commands.file('stored-once')
    registered.write_bytes(b'tampered')
    with pytest.raises(ValueError, match='校验失败'):
        commands.upload('stored-once', 'original.txt', b'original')
    assert registered.read_bytes() == b'tampered'


def test_native_shutdown_uses_only_existing_owned_process_handles(commands):
    accounts = EaselAccounts(commands, DistributionService(commands), autostart=False)
    accounts.close_native()
    assert not hasattr(accounts, '_native_context')
    native = accounts.native_context()
    class Process:
        stopped = False
        def poll(self):return 0 if self.stopped else None
        def terminate(self):self.stopped = True
        def wait(self, timeout):return 0
    process = Process(); native.LOGIN_PROCESSES['douyin'] = process
    accounts.close_native()
    assert process.stopped and not native.LOGIN_PROCESSES
    marker = json.loads((native.LOGIN_DIR / 'douyin.json').read_text(encoding='utf-8'))
    assert marker['state'] == 'expired'


def test_explicit_native_logout_allows_new_account_without_rebinding_old_approval(commands):
    accounts = EaselAccounts(commands, DistributionService(commands), autostart=False)
    accounts.record_native_observation('wechat-oa', {'loggedIn': True, 'provider_user_id': 'gh_original'})
    original = accounts._native_session('wechat-oa')
    old_connection = accounts.distribution.connection_internal(original['connection_id'])
    accounts.record_native_logout('wechat-oa')
    accounts.prepare_native_login('wechat-oa', 'new-account-login')
    accounts.record_native_observation('wechat-oa', {'loggedIn': True, 'provider_user_id': 'gh_new_account'})
    current = accounts._native_session('wechat-oa')
    assert current['id'] != original['id'] and current['account'] == 'gh_new_account'
    assert current['connection_id'] != old_connection['id']
    assert accounts.distribution.connection_internal(old_connection['id']) == old_connection


def test_ambiguous_legacy_accounts_get_fresh_native_browser_without_guessing(commands):
    accounts = EaselAccounts(commands, DistributionService(commands), autostart=False)
    old = [accounts.command({'id': 'old-' + str(index), 'action': 'create', 'platform': 'wechat-oa'})['result']['session']
           for index in (1, 2)]
    native = accounts._native_session('wechat-oa', create=True)
    assert native['id'] not in {item['id'] for item in old}
    with accounts.store.connect() as c:
        assert [accounts._public(accounts._get(c, item['id'])) for item in old] == old


def test_registered_native_chat_products_remain_in_original_output_tree(commands):
    from easel_workbench.upstream_skills import UpstreamSkills
    session, turn = 'native-session-proof', 'native-turn-proof'
    product = commands.root / 'outputs' / session / turn / 'products' / 'native.txt'
    product.parent.mkdir(parents=True); product.write_text('已登记原生正文', encoding='utf-8')
    document = {'id': turn, 'session_id': session, 'status': 'completed',
                'message': '原生技能准确产物', 'snapshot': {'task': 'native'}}
    with commands.store.connect() as c:
        c.execute('CREATE TABLE easel_chat_turns(id TEXT PRIMARY KEY,document TEXT NOT NULL)')
        c.execute('INSERT INTO easel_chat_turns VALUES(?,?)', (turn, json.dumps(document)))
    upstream = UpstreamSkills(commands.root, commands.creator)
    upstream.receive(document)
    registered = upstream.library()['items'][0]['files'][0]
    response, nodes = call(commands, '/api/outputs')
    assert response.status_code == 200
    group = next(item for item in nodes if item['path'] == 'native-session-' + session)
    assert group['meta']['session_id'] == session
    child = group['children'][0]
    assert child['meta']['turn_id'] == turn
    assert child['children'][0]['path'] == '__workbench__/' + registered['id'] + '/native.txt'
    assert not any(item['path'] == session for item in nodes)


def test_native_profile_requires_the_revision_that_was_read(commands):
    _, first_view = call(commands, '/api/persona/oil-pig/files')
    _, other_view = call(commands, '/api/persona/oil-pig/files')
    response, _ = call(commands, '/api/persona/oil-pig/file', 'PUT',
                       {'filename': 'identity.md', 'content': '另一个窗口已保存',
                        'expected_revision': other_view['revision']}, 'other-profile-window')
    assert response.status_code == 200
    stale, _ = call(commands, '/api/persona/oil-pig/file', 'PUT',
                   {'filename': 'identity.md', 'content': '旧窗口不得覆盖',
                    'expected_revision': first_view['revision']}, 'stale-profile-window')
    missing, _ = call(commands, '/api/persona/oil-pig/file', 'PUT',
                     {'filename': 'identity.md', 'content': '无修订号不得覆盖'}, 'missing-profile-revision')
    assert stale.status_code == missing.status_code == 409
    assert commands.creator.detail('profile', 'oil-pig')['identity'] == '另一个窗口已保存'


def test_native_analytics_reuses_original_handler_and_preserves_real_metric_shape(commands):
    import sys
    from easel.web_services import analytics as shared
    accounts = EaselAccounts(commands, DistributionService(commands), autostart=False)
    commands.easel_accounts = accounts
    native = accounts.native_context()
    native.LOGIN_DIR.mkdir(parents=True)
    (native.LOGIN_DIR / 'xiaohongshu.json').write_text('{"state":"success"}')
    calls = []
    payload = {'platform': 'xiaohongshu', 'loggedIn': True, 'followers': 42,
               'likes': None, 'following': 0, 'posts': None, 'metrics': [], 'notes': []}
    class Process:
        returncode = 0
        def __init__(self, args, **options):calls.append((args, options))
        def communicate(self, timeout):return json.dumps(payload), ''
    context = shared.create_analytics_context(commands.root, native,
        scripts=Path(__file__).resolve().parents[1] / 'skills/shared/scripts',
        python=sys.executable, environment={'EASEL_ROOT': str(commands.root)}, process_factory=Process)
    api = NativeApi(commands); api._analytics = context; commands._native_api = api
    assert context.api_analytics.__code__ is shared.api_analytics.__code__
    response, platforms = call(commands, '/api/analytics/platforms')
    assert response.status_code == 200
    assert next(row for row in platforms if row['platform'] == 'xiaohongshu')['loggedIn'] is True
    response, data = call(commands, '/api/analytics/xiaohongshu')
    assert response.status_code == 200 and data == payload
    assert data['likes'] is None and data['following'] == 0
    args, options = calls[0]
    assert args[0] == sys.executable and Path(args[1]).name == 'account_stats.py'
    assert '--profile-base' in args and str(commands.root) in args[-1]
    assert options['env']['EASEL_ROOT'] == str(commands.root)
    assert Path(options['env']['EASEL_ANALYTICS_DIR']).is_relative_to(commands.root / 'data/easel-accounts')
    assert context._ANALYTICS_PROCESSES == {}
    assert accounts.bootstrap()['sessions'][0]['identity_status'] == 'unconfirmed'
    state = commands.root / '.local/workbench-deployment'
    state.mkdir(parents=True); (state / 'admission.json').write_text('{"workers":false}')
    response, _ = call(commands, '/api/analytics/xiaohongshu')
    assert response.status_code == 503 and len(calls) == 1


def test_account_switch_stops_old_analytics_and_completed_logout_receipt_keeps_new_task(commands, monkeypatch):
    from easel.web_services.analytics import create_analytics_context
    accounts = EaselAccounts(commands, DistributionService(commands), autostart=False)
    commands.easel_accounts = accounts
    accounts.record_native_observation('wechat-oa', {'loggedIn': True, 'provider_user_id': 'gh_old_account'})
    native = accounts.native_context()
    async def logout(_):return {'ok': True, 'deleted': []}
    async def start(_):return {'mode': 'qr', 'state': 'starting', 'qr': '', 'message': ''}
    monkeypatch.setattr(native, 'api_logout', logout)
    monkeypatch.setattr(native, 'api_mp_login_start', start)
    api = NativeApi(commands)
    old = create_analytics_context(commands.root, native)
    api._analytics = old; accounts._native_analytics_context = old
    async def scenario():
        old_started, old_release = asyncio.Event(), asyncio.Event()
        async def old_fetch(_):
            old_started.set(); await old_release.wait(); return {'followers': 123}
        old.namespace['_fetch_analytics'] = old_fetch
        first = asyncio.create_task(api.dispatch('/api/analytics/wechat-oa', request('/api/analytics/wechat-oa'), {}))
        await old_started.wait()
        result = await api.dispatch('/api/logout/wechat-oa', request('/api/logout/wechat-oa', 'POST', 'switch-account-logout'), {})
        assert result['ok'] and api._analytics is None
        with pytest.raises(asyncio.CancelledError):
            await first
        gap = api.analytics_context()
        gap_started, gap_release = asyncio.Event(), asyncio.Event()
        async def gap_fetch(_):
            gap_started.set(); await gap_release.wait(); return {'followers': 99}
        gap.namespace['_fetch_analytics'] = gap_fetch
        during_logout = asyncio.create_task(api.dispatch('/api/analytics/wechat-oa', request('/api/analytics/wechat-oa'), {}))
        await gap_started.wait()
        await api.dispatch('/api/accounts/wechat-oa/mp-login',
                           request('/api/accounts/wechat-oa/mp-login', 'POST', 'new-identity-login'), {})
        with pytest.raises(asyncio.CancelledError):
            await during_logout
        accounts.record_native_observation('wechat-oa', {'loggedIn': True, 'provider_user_id': 'gh_new_account'})
        current = api.analytics_context()
        assert current is not old and current is not gap
        new_started, new_release = asyncio.Event(), asyncio.Event()
        async def new_fetch(_):
            new_started.set(); await new_release.wait(); return {'followers': 7}
        current.namespace['_fetch_analytics'] = new_fetch
        second = asyncio.create_task(api.dispatch('/api/analytics/wechat-oa', request('/api/analytics/wechat-oa'), {}))
        await new_started.wait()
        repeated = await api.dispatch('/api/logout/wechat-oa', request('/api/logout/wechat-oa', 'POST', 'switch-account-logout'), {})
        assert repeated == result and api._analytics is current and not second.done()
        new_release.set()
        assert await second == {'followers': 7}
    asyncio.run(scenario())
