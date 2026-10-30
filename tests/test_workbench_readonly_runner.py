"""No real model: exact upstream ports, isolated auth and unknown-call fences."""
import asyncio
import base64
from dataclasses import replace
from contextlib import asynccontextmanager, contextmanager
import json
from pathlib import Path
import sys
import sqlite3
from types import SimpleNamespace

import pytest

from easel.harnesses.base import HarnessError, RunRequest
from easel.harnesses.codex import CodexAdapter
from easel.harnesses.rpc import close_sessions
from easel_workbench import readonly_runner as runner


def snapshot(version=2):
    return {'skills': [{'id': 'delivery-review', 'entry': 'skills/builtin/delivery-review/SKILL.md',
                        'version': version, 'sha256': 'synthetic'}]}


def test_only_explicit_local_v2_snapshots_use_new_runner():
    assert runner.project_snapshot(snapshot())
    assert not runner.project_snapshot(snapshot(1))
    assert not runner.project_snapshot(None)
    old = snapshot(); old['skills'][0]['entry'] = '.agents/skills/neo-delivery-review/SKILL.md'
    assert not runner.project_snapshot(old)


def test_legacy_and_injected_runners_keep_original_arguments_and_output(tmp_path):
    calls = []
    def legacy(*args, **kwargs):
        calls.append((args, kwargs)); return 'original-result'
    assert runner.run(None, ['old-cli'], input=b'exact bytes', cwd=tmp_path, timeout=180, runner=legacy) == 'original-result'
    assert calls[0] == ((['old-cli'],), {'input': b'exact bytes', 'cwd': tmp_path, 'timeout': 180})
    assert runner.run(snapshot(), ['injected'], input='x', cwd=tmp_path, timeout=1, runner=legacy) == 'original-result'


def test_actual_upstream_adapter_maps_images_schema_effort_ephemeral(tmp_path):
    image = tmp_path / 'image.png'; image.write_bytes(b'synthetic-image')
    audit = tmp_path / 'rpc.jsonl'
    import os
    request = RunRequest('exact prompt', tmp_path, {**os.environ, 'FAKE_HARNESS_AUDIT': str(audit)},
        model='gpt-6.1-sol', sandbox='read-only', frozen_instructions='', ephemeral=True,
        input_images=(str(image.resolve()),), reasoning_effort='low', output_schema={'type': 'object'},
        command=(sys.executable, str(Path(__file__).parent / 'fixtures/harness_rpc.py'), 'codex'))
    accepted = []
    async def reject(*args): raise AssertionError('No question expected')
    async def execute():
        try: await CodexAdapter().run(replace(request, on_native_turn=lambda *ids: accepted.append(ids)), lambda *args: None, reject, lambda *_: None)
        finally: await close_sessions()
    asyncio.run(execute())
    messages = [json.loads(line) for line in audit.read_text(encoding='utf-8').splitlines()]
    start = next(row['params'] for row in messages if row.get('method') == 'thread/start')
    turn = next(row['params'] for row in messages if row.get('method') == 'turn/start')
    assert start['ephemeral'] is True and start['sandbox'] == 'read-only'
    assert turn['effort'] == 'low' and turn['outputSchema'] == {'type': 'object'}
    assert turn['model'] == 'gpt-6.1-sol'
    assert turn['input'] == [{'type': 'text', 'text': 'exact prompt'}, {'type': 'localImage', 'path': str(image.resolve())}]
    assert turn['sandboxPolicy'] == {'type': 'readOnly'} and len(accepted) == 1


@pytest.mark.parametrize('patch', [{'input_images': ('relative.png',)}, {'reasoning_effort': ''},
                                  {'output_schema': []}, {'ephemeral': True, 'native_id': 'old-thread'}])
def test_invalid_optional_native_inputs_fail_before_transport(tmp_path, patch):
    request = replace(RunRequest('x', tmp_path, {}, frozen_instructions=''), **patch)
    async def reject(*args): raise AssertionError('Not reached')
    with pytest.raises(HarnessError):
        asyncio.run(CodexAdapter().run(request, lambda *_: None, reject, lambda *_: None))


def test_external_auth_forwards_access_only_and_never_copies_refresh(tmp_path):
    auth = tmp_path / 'auth.json'
    raw = json.dumps({'tokens': {'access_token': 'synthetic-access', 'account_id': 'synthetic-account',
                                 'refresh_token': 'synthetic-refresh'}}).encode()
    auth.write_bytes(raw)
    value, path, fingerprint = runner.external_auth({'CODEX_HOME': str(tmp_path)})
    assert set(value) == {'type', 'accessToken', 'chatgptAccountId'}
    assert 'synthetic-refresh' not in json.dumps(value)
    assert auth.read_bytes() == raw and fingerprint == runner.sha(raw)
    assert path == auth and list(tmp_path.iterdir()) == [auth]


def jwt(expiry):
    payload = base64.urlsafe_b64encode(json.dumps({'exp': expiry}).encode()).decode().rstrip('=')
    return 'e30.' + payload + '.synthetic-signature'


@pytest.mark.parametrize('token', ['opaque-token', 'e30.eyJleHAiOnRydWV9.signature', jwt(-1), jwt(None), jwt(5000)])
def test_valid_or_unknown_expiry_does_not_refresh_native_login(tmp_path, monkeypatch, token):
    path = tmp_path / 'auth.json'
    path.write_text(json.dumps({'tokens': {'access_token': token, 'account_id': 'existing', 'refresh_token': 'never-copy'}}))
    monkeypatch.setattr(runner.time, 'time', lambda: 1000)
    def forbidden(*args, **kwargs):raise AssertionError('No refresh permitted')
    monkeypatch.setattr(runner, 'connection', forbidden)
    receipt = {}; existing = runner.external_auth({'CODEX_HOME': str(tmp_path)})
    auth, fingerprint = asyncio.run(runner.prepare_external_auth({'CODEX_HOME': str(tmp_path)}, tmp_path, 180,
        receipt, lambda: None, existing))
    assert auth == existing[0] and fingerprint == existing[2]
    assert receipt['native_auth_refresh']['requested'] is False
    assert set(auth) == {'type', 'accessToken', 'chatgptAccountId'}


@pytest.mark.parametrize('expiry', [900, 1000, 1300])
def test_near_expiry_uses_managed_native_refresh_once_and_external_access_only(tmp_path, monkeypatch, expiry):
    path = tmp_path / 'auth.json'
    path.write_text(json.dumps({'tokens': {'access_token': jwt(expiry), 'account_id': 'existing', 'refresh_token': 'native-only'}}))
    existing = runner.external_auth({'CODEX_HOME': str(tmp_path)})
    calls, closed = [], []
    class RPC:
        initialized = None
        async def call(self, method, params):
            calls.append((method, params))
            if method == 'initialize':return {'userAgent': 'synthetic-native'}
            assert method == 'account/read' and params == {'refreshToken': True}
            # The fake native process owns this write; application code does not.
            path.write_text(json.dumps({'tokens': {'access_token': jwt(5000), 'account_id': 'existing', 'refresh_token': 'native-rotated'}}))
            return {'account': {'type': 'chatgpt'}}
        async def send(self, message):calls.append((message['method'], None))
    @asynccontextmanager
    async def connection(request, command, notify, respond):
        assert request.env['CODEX_HOME'] == str(tmp_path) and request.prompt == ''
        assert request.session_key.startswith('readonly-auth-refresh-')
        assert command == ['synthetic-codex', 'app-server']
        yield RPC()
    async def close(session_key):closed.append(session_key)
    monkeypatch.setattr(runner, 'connection', connection)
    monkeypatch.setattr(runner, 'close_sessions', close)
    monkeypatch.setattr(runner, 'base_command', lambda *_: ['synthetic-codex'])
    monkeypatch.setattr(runner.time, 'time', lambda: 1000)
    receipt = {}
    auth, fingerprint = asyncio.run(runner.prepare_external_auth({'CODEX_HOME': str(tmp_path)}, tmp_path, 180,
        receipt, lambda: None, existing))
    assert [row[0] for row in calls] == ['initialize', 'initialized', 'account/read']
    assert len(closed) == 1 and auth['accessToken'] == jwt(5000)
    assert set(auth) == {'type', 'accessToken', 'chatgptAccountId'} and 'refresh' not in json.dumps(auth)
    assert fingerprint == runner.sha(path.read_bytes()) and fingerprint != existing[2]
    assert receipt['native_auth_refresh']['completed'] is True
    assert receipt['native_auth_refresh']['source_auth_changed'] is True
    assert 'native-only' not in json.dumps(receipt) and 'native-rotated' not in json.dumps(receipt)


@pytest.mark.parametrize('failure', ['protocol_error', 'same_expired_token', 'changed_account', 'not_chatgpt'])
def test_refresh_failure_stops_before_any_model_or_new_login(tmp_path, monkeypatch, failure):
    home = tmp_path / 'managed'; home.mkdir()
    authfile = home / 'auth.json'
    authfile.write_text(json.dumps({'tokens': {'access_token': jwt(900), 'account_id': 'existing', 'refresh_token': 'native-only'}}))
    folder = tmp_path / 'call'; folder.mkdir()
    (folder / 'schema.json').write_text('{"type":"object"}')
    methods = []
    class RPC:
        initialized = {}
        async def call(self, method, params):
            methods.append(method)
            assert method == 'account/read' and params == {'refreshToken': True}
            if failure == 'protocol_error':raise HarnessError('synthetic protocol failure')
            if failure == 'changed_account':
                authfile.write_text(json.dumps({'tokens': {'access_token': jwt(5000), 'account_id': 'different', 'refresh_token': 'native-only'}}))
            return {'account': {'type': 'apiKey' if failure == 'not_chatgpt' else 'chatgpt'}}
    @asynccontextmanager
    async def connection(*args):yield RPC()
    def model_forbidden(*args, **kwargs):raise AssertionError('Model must not start')
    monkeypatch.setattr(runner, 'connection', connection)
    monkeypatch.setattr(runner, 'invoke', model_forbidden)
    monkeypatch.setattr(runner.time, 'time', lambda: 1000)
    monkeypatch.setattr(runner, 'base_command', lambda *_: ['synthetic-codex'])
    with pytest.raises(ValueError, match='续期未通过'):
        runner.run(snapshot(), ['old'], input='exact', cwd=folder, timeout=180,
                   env={'CODEX_HOME': str(home)}, runtime_root=tmp_path)
    assert methods == ['account/read'] and not (folder / 'answer.json').exists()
    receipt = json.loads(next((tmp_path / 'data/readonly-receipts').glob('*.json')).read_text(encoding='utf-8'))
    assert receipt['status'] == 'not_started' and receipt['native_auth_refresh']['completed'] is False
    assert receipt['source_auth_unchanged'] is (failure != 'changed_account')


def test_full_run_records_native_auth_change_and_keeps_isolated_home_refresh_free(tmp_path, monkeypatch):
    home = tmp_path / 'managed'; home.mkdir()
    authfile = home / 'auth.json'
    authfile.write_text(json.dumps({'tokens': {'access_token': jwt(900), 'account_id': 'existing', 'refresh_token': 'native-only'}}))
    folder = tmp_path / 'call'; folder.mkdir(); (folder / 'schema.json').write_text('{"type":"object"}')
    class RPC:
        initialized = {}
        async def call(self, method, params):
            assert method == 'account/read' and params == {'refreshToken': True}
            authfile.write_text(json.dumps({'tokens': {'access_token': jwt(5000), 'account_id': 'existing', 'refresh_token': 'native-rotated'}}))
            return {'account': {'type': 'chatgpt'}}
    @asynccontextmanager
    async def connection(*args):yield RPC()
    calls = []
    async def invoke(request, command, receipt, persist, **kwargs):
        calls.append(request)
        assert request.env['CODEX_HOME'] != str(home) and list(Path(request.env['CODEX_HOME']).iterdir()) == []
        assert kwargs['auth'] == {'type': 'chatgptAuthTokens', 'accessToken': jwt(5000), 'chatgptAccountId': 'existing'}
        receipt.update(status='completed');persist()
        return {'ok': True}, '{"ok":true}'
    monkeypatch.setattr(runner, 'connection', connection)
    monkeypatch.setattr(runner, 'invoke', invoke)
    monkeypatch.setattr(runner.time, 'time', lambda: 1000)
    monkeypatch.setattr(runner, 'base_command', lambda *_: ['synthetic-codex'])
    result = runner.run(snapshot(), ['old'], input='exact', cwd=folder, timeout=180,
                        env={'CODEX_HOME': str(home)}, runtime_root=tmp_path)
    assert len(calls) == 1 and (folder / 'answer.json').read_text(encoding='utf-8') == '{"ok":true}'
    assert result.execution_receipt['source_auth_unchanged'] is False
    assert result.execution_receipt['source_auth_unchanged_during_isolated_execution'] is True
    assert result.execution_receipt['native_auth_refresh']['source_auth_changed'] is True


def test_new_call_preserves_exact_parameters_and_program_receipt(tmp_path, monkeypatch):
    auth_home = tmp_path / 'auth-home'; auth_home.mkdir()
    (auth_home / 'auth.json').write_text(json.dumps({'tokens': {'access_token': 'a', 'account_id': 'b', 'refresh_token': 'do-not-copy'}}))
    folder = tmp_path / 'call'; folder.mkdir(); image = folder / 'image.png'; image.write_bytes(b'exact image bytes')
    schema = {'type': 'object', 'properties': {'ok': {'type': 'boolean'}}}
    (folder / 'schema.json').write_text(json.dumps(schema))
    captured = []
    async def fake(request, command, receipt, persist, **kwargs):
        captured.append(request)
        assert not (Path(request.env['CODEX_HOME']) / 'auth.json').exists()
        assert set(kwargs['auth']) == {'type', 'accessToken', 'chatgptAccountId'}
        assert request.output_schema == schema and request.reasoning_effort == 'low'
        assert request.model == 'gpt-6.1-sol' and request.sandbox == 'read-only' and request.ephemeral
        assert request.input_images == (str(image.resolve()),) and request.prompt == '保留原始输入\n'
        receipt.update(status='completed', native_thread_id='thread-exact', native_turn_id='turn-exact'); persist()
        return {'ok': True}, '{"ok":true}'
    monkeypatch.setattr(runner, 'invoke', fake)
    monkeypatch.setattr(runner, 'base_command', lambda *_: ['native-cli'])
    arguments = ['old', '--model', 'gpt-6.1-sol', '-c', 'model_reasoning_effort="low"', '--image', str(image), '-']
    result = runner.run(snapshot(), arguments, input='保留原始输入\n', cwd=folder, timeout=180,
                        env={'CODEX_HOME': str(auth_home)}, runtime_root=tmp_path, task_id='task-1')
    assert len(captured) == 1 and (folder / 'answer.json').read_text(encoding='utf-8') == '{"ok":true}'
    assert result.execution_receipt['source_auth_unchanged'] is True
    assert result.execution_receipt['images'][0]['sha256'] == runner.sha(image.read_bytes())
    assert runner.recorded_output(result, {'ok': True})['execution_receipt']['native_turn_id'] == 'turn-exact'
    assert len(list((tmp_path / 'data/readonly-receipts').glob('*.json'))) == 1


@pytest.mark.parametrize('mode', ['timeout', 'permission', 'transport'])
def test_after_native_ack_failure_remains_unknown_without_retry(tmp_path, mode):
    calls = []
    class Fake:
        async def run(self, request, emit, ask, bind):
            calls.append(request); bind('thread-known'); request.on_native_turn('thread-known', 'turn-known')
            if mode == 'timeout': await asyncio.Event().wait()
            if mode == 'permission': await ask([{'question': 'Do not auto approve'}])
            raise HarnessError('synthetic disconnect')
    receipt = {}; request = RunRequest('x', tmp_path, {}, timeout=0.01, frozen_instructions='')
    with pytest.raises(runner.ReadonlyExecutionUnknown) as error:
        asyncio.run(runner.invoke(request, [], receipt, lambda: None, adapter=Fake(), preflight=False))
    assert len(calls) == 1 and receipt['status'] == 'unknown'
    assert error.value.receipt['native_turn_id'] == 'turn-known'


def test_native_completion_with_bad_json_is_failed_and_not_replayed(tmp_path):
    class Fake:
        async def run(self, request, emit, ask, bind):
            bind('thread'); request.on_native_turn('thread', 'turn'); emit('token', 'invalid JSON')
            request.on_agent_message('thread', 'turn', {'id': 'final', 'type': 'agentMessage',
                                                      'text': 'invalid JSON', 'phase': 'final_answer'})
    receipt = {}
    with pytest.raises(ValueError):
        asyncio.run(runner.invoke(RunRequest('x', tmp_path, {}, frozen_instructions=''), [], receipt,
                                  lambda: None, adapter=Fake(), preflight=False))
    assert receipt['status'] == 'failed' and receipt['completion_received'] is True
    assert receipt['model_output_text'] == 'invalid JSON'


@pytest.mark.parametrize('source', ['item_event', 'turn_items', 'legacy_no_phase'])
def test_actual_adapter_uses_final_whole_message_and_preserves_commentary(tmp_path, monkeypatch, source):
    from easel.harnesses import codex
    calls, ordinary_tokens = [], []
    preamble = '我来核对，说明文字含有示意 {"ok":false}。\n'
    final = '{"ok":true}'
    class RPC:
        initialized = {'userAgent': 'synthetic'}
        native_id = ''
        def __init__(self, notify):self.notify = notify
        async def call(self, method, params):
            calls.append(method)
            if method == 'thread/start':return {'thread': {'id': 'native-thread'}}
            assert method == 'turn/start'
            common = {'threadId': 'native-thread', 'turnId': 'native-turn'}
            commentary = {'type': 'agentMessage', 'id': 'preamble', 'text': preamble, 'phase': 'commentary'}
            answer = {'type': 'agentMessage', 'id': 'answer', 'text': final,
                      'phase': None if source == 'legacy_no_phase' else 'final_answer'}
            self.notify('item/agentMessage/delta', {**common, 'itemId': 'preamble', 'delta': preamble})
            self.notify('item/completed', {**common, 'item': commentary})
            self.notify('item/agentMessage/delta', {**common, 'itemId': 'answer', 'delta': final})
            if source != 'turn_items':self.notify('item/completed', {**common, 'item': answer})
            self.notify('turn/completed', {**common, 'turn': {'id': 'native-turn', 'status': 'completed',
                'items': [commentary, answer]}})
            return {'turn': {'id': 'native-turn'}}
        async def wait_notification(self, completion):return await completion
    @asynccontextmanager
    async def connection(request, command, notify, respond):yield RPC(notify)
    monkeypatch.setattr(codex, 'connection', connection)
    class RecordingAdapter(CodexAdapter):
        async def run(self, request, emit, ask, bind):
            def record(kind, text):
                if kind == 'token':ordinary_tokens.append(text)
                emit(kind, text)
            return await super().run(request, record, ask, bind)
    receipt = {}
    value, raw = asyncio.run(runner.invoke(RunRequest('x', tmp_path, {}, frozen_instructions='', command=('fake',)),
        [], receipt, lambda: None, adapter=RecordingAdapter(), preflight=False))
    assert value == {'ok': True} and raw == final
    assert ''.join(ordinary_tokens) == preamble + final
    assert receipt['raw_stream_text'] == preamble + final
    assert receipt['model_output_text'] == final and receipt['model_output_item_id'] == 'answer'
    assert [item['id'] for item in receipt['native_agent_messages']] == ['preamble', 'answer']
    assert receipt['model_output_selection'] == ('last_complete_unphased_message' if source == 'legacy_no_phase' else 'final_answer')
    assert calls == ['thread/start', 'turn/start']


def test_commentary_json_and_partial_answer_are_never_used_as_final(tmp_path):
    class Fake:
        async def run(self, request, emit, ask, bind):
            bind('thread'); request.on_native_turn('thread', 'turn')
            for identity, phase in [('comment', 'commentary'), ('partial', 'partial_answer')]:
                emit('token', '{"ok":true}')
                request.on_agent_message('thread', 'turn', {'id': identity, 'text': '{"ok":true}', 'phase': phase})
    receipt = {}
    with pytest.raises(runner.ReadonlyOutputInvalid):
        asyncio.run(runner.invoke(RunRequest('x', tmp_path, {}, frozen_instructions=''), [], receipt,
                                  lambda: None, adapter=Fake(), preflight=False))
    assert receipt['status'] == 'failed' and receipt['raw_stream_text'] == '{"ok":true}{"ok":true}'
    assert 'model_output_text' not in receipt and len(receipt['native_agent_messages']) == 2


def test_preflight_mcp_inventory_rejects_before_model(tmp_path, monkeypatch):
    class RPC:
        initialized = None
        async def call(self, method, params):
            if method == 'account/read': return {'account': {'type': 'chatgpt'}}
            if method == 'mcpServerStatus/list': return {'data': [{'name': 'unexpected-mcp'}]}
            if method == 'experimentalFeature/list': return {'data': []}
            return {}
        async def send(self, message): pass
    @asynccontextmanager
    async def connection(*args): yield RPC()
    monkeypatch.setattr(runner, 'connection', connection)
    with pytest.raises(ValueError, match='隔离'):
        asyncio.run(runner.prepare_connection(RunRequest('', tmp_path, {}, frozen_instructions=''), [], {}, lambda: None,
                                              {'type': 'chatgptAuthTokens', 'accessToken': 'synthetic', 'chatgptAccountId': 'synthetic'}))


@pytest.mark.parametrize('failure', [runner.ReadonlyExecutionUnknown, runner.ReadonlyOutputInvalid])
def test_news_outer_cache_holds_unknown_or_completed_invalid_output_without_second_call(tmp_path, failure):
    from easel_workbench.runtime.news_overviews import Overviews
    database = tmp_path / 'desk.sqlite'
    class Store:
        def sources(self,include_deleted=False):
            return {'github-trending':{'builtin':True,'kind':'news'}}
        @contextmanager
        def connect(self):
            connection = sqlite3.connect(database); connection.row_factory = sqlite3.Row
            try:
                with connection:yield connection
            finally:connection.close()
    store = Store()
    with store.connect() as connection:
        connection.execute('CREATE TABLE articles(id TEXT PRIMARY KEY,source_job TEXT,title TEXT,body TEXT,url TEXT,run_at TEXT)')
        connection.execute('INSERT INTO articles VALUES(?,?,?,?,?,?)', ('article-1', 'github-trending', 'title', 'body', 'https://example.test', '2026-10-30'))
    service = Overviews(store, tmp_path); calls = []
    def execute(rows):
        calls.append(rows)
        raise failure({'native_thread_id': 'thread', 'native_turn_id': 'turn'})
    with pytest.raises(failure):service.tick(runner=execute)
    with service.connect() as connection:
        row = dict(connection.execute('SELECT * FROM overviews').fetchone())
    assert row['attempts'] == 1 and row['retry_at'] == 253402300799.0 and '未自动重跑' in row['error']
    assert service.tick(runner=execute) == 0 and len(calls) == 1


def test_learning_outer_worker_blocks_connection_unknown_instead_of_generic_failure(tmp_path):
    from easel_workbench.runtime.learning_worker import LearningWorker
    calls, results = [], []
    task = {'id': 'explicit-reference', 'kind': 'reference_analysis', 'lease_token': 'one-lease',
            'payload': {'content': 'bounded source', 'images': []}}
    class Service:
        root = tmp_path
        def claim_task(self, *args, **kwargs):return task if not results else None
        def finish_task(self, *args):results.append(args[-1])
    def execute(payload):
        calls.append(payload)
        raise runner.ReadonlyExecutionUnknown({'native_turn_id': 'accepted-once'})
    worker = LearningWorker(Service(), runner=execute)
    result = worker.process_one()
    assert result['result']['status'] == 'blocked' and '未自动重放' in result['result']['error']
    assert worker.process_one() is None and len(calls) == 1


def test_observed_call_stores_connection_unknown_without_finishing_as_error(tmp_path):
    from easel_workbench.runtime import task_runtime
    from easel_workbench.runtime.creator_runtime import initialize
    from contextlib import contextmanager
    class Store:
        @contextmanager
        def connect(self):
            connection = sqlite3.connect(tmp_path / 'trace.sqlite'); connection.row_factory = sqlite3.Row
            try:
                with connection:yield connection
            finally:connection.close()
    box = SimpleNamespace(store=Store(), root=tmp_path)
    with box.store.connect() as connection:
        initialize(connection);task_runtime.initialize(connection)
    explicit = snapshot(); explicit.update(profile={'id': 'synthetic'}, task='review')
    with pytest.raises(runner.ReadonlyExecutionUnknown):
        with task_runtime.observed_call(box, 'review', {'source': 'exact'}, 'exact prompt', explicit):
            raise runner.ReadonlyExecutionUnknown({'native_turn_id': 'turn-exact'})
    with box.store.connect() as connection:
        records = [json.loads(row[0]) for row in connection.execute('SELECT document FROM creator_model_calls')]
    assert len(records) == 1 and records[0]['status'] == 'unknown'


def test_learning_batch_outer_catch_marks_blocked_and_preserves_one_call(tmp_path):
    from easel_workbench.runtime.learning_worker import LearningWorker
    completed, finished, calls = [], [], []
    class Batch:
        def get(self, *args):return {'id': 'batch-1'}
        def payload(self, *args):return {'images': []}
        def begin_call(self, identity):calls.append(identity);return {'id': 'call-once'}
        def complete(self, *args):completed.append(args)
    class Store:
        @contextmanager
        def connect(self):yield None
    service = SimpleNamespace(root=tmp_path, store=Store(), batch=Batch(),
                              finish_task=lambda *args:finished.append(args))
    def execute(payload):raise runner.ReadonlyExecutionUnknown({'native_turn_id': 'unknown-turn'})
    worker = LearningWorker(service, batch_runner=execute)
    result = worker._process_batch({'id': 'task-batch', 'lease_token': 'lease', 'payload': {'batch_id': 'batch-1'}})
    assert result['result']['status'] == 'blocked'
    assert calls == ['batch-1'] and completed[0][1]['status'] == 'blocked'
    assert finished[0][-1]['status'] == 'blocked'


@pytest.mark.parametrize('native_allowed', [True, False])
def test_news_boundary_keeps_model_effort_schema_timeout_and_legacy_login(tmp_path, monkeypatch, native_allowed):
    from easel_workbench.runtime import news_overviews as news, task_runtime
    binding = snapshot(); calls, login, recorded = [], [], []
    monkeypatch.setattr(task_runtime, 'contract_prompt', lambda *args, **kwargs:('exact news prompt', binding))
    @contextmanager
    def observed(*args, **kwargs):yield recorded.append
    monkeypatch.setattr(task_runtime, 'observed_call', observed)
    def login_probe(*args, **kwargs):
        login.append(args);return SimpleNamespace(returncode=0, stdout='Logged in using ChatGPT', stderr='')
    monkeypatch.setattr(news.subprocess, 'run', login_probe)
    def execute(selected, arguments, **kwargs):
        calls.append(selected)
        assert bool(selected) is native_allowed
        assert runner.option(arguments, '--model') == news.MODEL == 'gpt-6-luna'
        assert 'model_reasoning_effort="low"' in arguments and kwargs['timeout'] == 360
        folder = Path(kwargs['cwd'])
        assert json.loads((folder / 'schema.json').read_text(encoding='utf-8')) == news.SCHEMA
        (folder / 'answer.json').write_text(json.dumps({'items': [{'id': 'article-1', 'summary': '这是一条用于核对新闻概述执行路径的真实格式测试。'}]}, ensure_ascii=False), encoding='utf-8')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(runner, 'run', execute)
    result = news.analyze([{'id': 'article-1', 'title': 'title', 'body': 'body', 'url': 'https://example.test', 'source_job': 'github-trending'}], tmp_path, native_allowed=native_allowed)
    assert list(result) == ['article-1'] and len(calls) == 1 and len(recorded) == 1
    assert len(login) == (0 if native_allowed else 1)
