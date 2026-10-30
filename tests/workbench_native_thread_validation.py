"""Opt-in real native thread lifecycle checks; never starts a model turn.

This script creates one empty thread in a temporary working directory. Native
session metadata is intentionally left to Codex; no application database is
opened. A transport allowlist fails before writing any model or queue method.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import importlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import uuid


ALLOWED_METHODS = {
    'initialize', 'thread/start', 'thread/read', 'thread/loaded/list',
    'thread/resume',
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_transport(backend):
    path = backend / 'easel_workbench/runtime/poster_rpc.py'
    spec = importlib.util.spec_from_file_location('_native_lifecycle_transport', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


def safe_error(error):
    native = getattr(error, 'error', {})
    return {'type': type(error).__name__, 'code': native.get('code'),
            'message': str(error)[:500]}


def summary(result):
    thread = result.get('thread') or {}
    raw = thread.get('path')
    path = Path(raw.removeprefix('\\\\?\\')) if raw else None
    return {key: thread.get(key) for key in ('id', 'cwd', 'ephemeral', 'status')} | {
        'path': str(path) if path else None,
        'path_exists': bool(path and path.is_file()),
        'turn_count': len(thread.get('turns') or []),
    }


def probe(backend):
    transport, source = load_transport(backend)
    calls, events = [], []

    class GuardedRPC(transport.RPC):
        def call(self, method, params=None, timeout=30):
            if method not in ALLOWED_METHODS:
                raise AssertionError('Forbidden native validation method: ' + method)
            calls.append(method)
            return super().call(method, params, timeout)

        def write(self, message):
            if message.get('method') not in ALLOWED_METHODS | {'initialized'}:
                raise AssertionError('Forbidden native write')
            return super().write(message)

    report = {'transport_source': str(source), 'transport_sha256': digest(source),
              'codex': str(transport.CODEX),
              'codex_version': subprocess.check_output(
                  [str(transport.CODEX), '--version'], text=True, encoding='utf-8').strip(),
              'model_calls': 0, 'queue_writes': 0, 'production_database_writes': 0}
    with tempfile.TemporaryDirectory(prefix='easel-native-empty-') as directory:
        working = Path(directory).resolve()
        first = GuardedRPC(on_event=lambda event: events.append(event.get('method', '')))
        try:
            started = first.call('thread/start', {'cwd': str(working), 'ephemeral': False})
            native = summary(started)
            assert native['id'], 'thread/start must return an exact identity'
            assert Path(native['cwd'].removeprefix('\\\\?\\')).resolve() == working
            assert not native['turn_count'], 'Validation thread must remain empty'
            report['started'] = native
            report['first_process_id'] = first.process.pid
            loaded = first.call('thread/loaded/list', {})
            report['same_connection_loaded'] = native['id'] in loaded.get('data', [])
            assert report['same_connection_loaded'], 'Empty thread lost before close'
            try:
                report['same_connection_read'] = summary(first.call(
                    'thread/read', {'threadId': native['id'], 'includeTurns': False}))
            except transport.RPCError as error:
                report['same_connection_read_error'] = safe_error(error)
            report['same_connection_alive'] = first.process.poll() is None and not first.closed
            assert report['same_connection_alive']
        finally:
            first.close()
        report['first_closed'] = first.closed and first.process.poll() is not None
        # Read-only resume of this exact empty validation thread reproduces the
        # old create/close/resume lifecycle; it never submits user input.
        second = GuardedRPC(on_event=lambda event: events.append(event.get('method', '')))
        try:
            report['second_process_id'] = second.process.pid
            try:
                report['after_close_resume'] = summary(second.call(
                    'thread/resume', {'threadId': native['id'], 'excludeTurns': True}))
                report['ghost_reproduced'] = False
            except transport.RPCError as error:
                report['after_close_resume_error'] = safe_error(error)
                report['ghost_reproduced'] = 'no rollout found' in str(error).lower()
            if native.get('path'):
                report['rollout_exists_after_close'] = Path(native['path']).is_file()
        finally:
            second.close()
    report['methods'] = calls
    report['event_methods'] = sorted(set(events))
    report['passed'] = bool(report['same_connection_loaded'] and report['same_connection_alive']
                            and report['first_closed'] and not any(
                                method.startswith('turn/') for method in events))
    return report


def probe_account(backend):
    """Return only safe local authentication/catalog facts, never credentials."""
    transport, source = load_transport(backend)
    calls = []
    allowed = {'initialize', 'account/read', 'model/list'}

    class ReadOnlyRPC(transport.RPC):
        def call(self, method, params=None, timeout=30):
            assert method in allowed, 'Only authentication/catalog reads are allowed'
            calls.append(method)
            return super().call(method, params, timeout)

        def write(self, message):
            assert message.get('method') in allowed | {'initialized'}
            return super().write(message)

    with tempfile.TemporaryDirectory(prefix='easel-native-schema-') as directory:
        subprocess.run([str(transport.CODEX), 'app-server', 'generate-json-schema',
                        '--experimental', '--out', directory],
                       check=True, capture_output=True, timeout=30)
        schemas = {}
        for name, required in [('GetAccountParams.json', {'refreshToken'}),
                               ('ModelListParams.json', {'limit', 'includeHidden'})]:
            paths = list(Path(directory).rglob(name))
            assert len(paths) == 1, 'Expected one local native request schema'
            schema = json.loads(paths[0].read_text(encoding='utf-8'))
            assert required <= schema.get('properties', {}).keys()
            schemas[name] = digest(paths[0])
    connection = ReadOnlyRPC()
    try:
        account = connection.call('account/read', {'refreshToken': False})
        value = account.get('account')
        catalog = connection.call('model/list', {'limit': 100, 'includeHidden': False})
        data = catalog.get('data') or []
        result = {
            'passed': bool(data) and not (account.get('requiresOpenaiAuth') and value is None),
            'account_read_succeeded': True,
            'account_type': value.get('type') if isinstance(value, dict) else None,
            'requires_openai_auth': account.get('requiresOpenaiAuth'),
            'needs_auth_derived': bool(account.get('requiresOpenaiAuth') and value is None),
            'model_list_succeeded': True, 'visible_model_count': len(data),
            'default_model_present': any(row.get('isDefault') for row in data),
            'catalog_has_more': bool(catalog.get('nextCursor')),
            'catalog_is_not_an_inference_entitlement_test': True,
            'schema_sha256': schemas, 'transport_source': str(source),
            'transport_sha256': digest(source), 'methods': calls,
            'model_calls': 0, 'queue_writes': 0, 'production_database_writes': 0,
        }
        return result
    finally:
        connection.close()


def probe_owned(backend):
    """Exercise the real preparation API against a synthetic TEMP database."""
    with tempfile.TemporaryDirectory(prefix='easel-owned-native-') as directory:
        owner = Path(directory).resolve()
        workspace = owner / 'empty-workspace'
        workspace.mkdir()
        sources = backend / 'sources.json'
        if not sources.is_file():
            sources = backend / 'easel_workbench/runtime/sources.json'
        (owner / 'sources.json').write_bytes(sources.read_bytes())
        os.environ['AI_DESK_PROJECT_ROOT'] = str(owner)
        os.environ['AI_DESK_RELEASE'] = backend.name
        sys.path.insert(0, str(backend))
        desk = importlib.import_module('easel_workbench.runtime.desk')
        desk.PROJECT = workspace
        runtime = importlib.import_module('easel_workbench.runtime.task_runtime')
        transport = importlib.import_module('easel_workbench.runtime.poster_rpc')
        assert Path(runtime.__file__).resolve() == backend / 'easel_workbench/runtime/task_runtime.py'
        assert Path(transport.__file__).resolve() == backend / 'easel_workbench/runtime/poster_rpc.py'
        assert hasattr(runtime, 'prepare_target'), 'This backend has no ownership fix'

        class TempStore:
            path = owner / 'fixture.sqlite'

            @contextlib.contextmanager
            def connect(self):
                connection = sqlite3.connect(self.path)
                connection.row_factory = sqlite3.Row
                try:
                    with connection:
                        yield connection
                finally:
                    connection.close()

        box = SimpleNamespace(root=owner, store=TempStore())
        identity = 'native-validation-' + uuid.uuid4().hex
        calls, instances = [], []

        class GuardedRPC(transport.RPC):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                instances.append(self)

            def call(self, method, params=None, timeout=30):
                assert method in ALLOWED_METHODS, 'Forbidden production method in lifecycle validation'
                calls.append(method)
                return super().call(method, params, timeout)

            def write(self, message):
                assert message.get('method') in ALLOWED_METHODS | {'initialized'}
                return super().write(message)

        with box.store.connect() as connection:
            runtime.initialize(connection)
            connection.execute('CREATE TABLE toolbox_jobs(id TEXT PRIMARY KEY,work_id TEXT,status TEXT,dispatch_started INTEGER,queue_id TEXT,turn_id TEXT)')
            connection.execute('CREATE TABLE toolbox_dispatch_retries(job_id TEXT PRIMARY KEY,document TEXT)')
            connection.execute('INSERT INTO toolbox_jobs VALUES(?,?,?,0,NULL,NULL)', (identity, identity, 'queued'))
            runtime._put_run(connection, {'id': identity, 'work_id': identity, 'status': 'queued',
                                         'snapshot': {'profile': {'id': 'synthetic-validation'}}, 'steps': []})

        observations = []
        for iteration in range(2):
            def forbidden_legacy():
                raise AssertionError('Synthetic isolated work cannot resolve a legacy target')

            with runtime.prepare_target(box, identity, GuardedRPC, forbidden_legacy) as target:
                connection = target.connection
                assert target.owned and connection is not None
                assert not connection.closed and connection.process.poll() is None
                loaded = connection.call('thread/loaded/list', {})
                assert target.thread_id in loaded.get('data', [])
                read = summary(connection.call('thread/read', {'threadId': target.thread_id, 'includeTurns': False}))
                assert read['id'] == target.thread_id and read['turn_count'] == 0
                assert Path(read['cwd'].removeprefix('\\\\?\\')).resolve() == workspace
                observations.append({'iteration': iteration + 1, 'thread': read,
                                     'connection_alive_while_held': True,
                                     'same_connection_loaded': True, 'owned': target.owned,
                                     'process_id': connection.process.pid})
            assert connection.closed and connection.process.poll() is not None
            assert target.connection is None
            observations[-1]['closed_on_context_exit'] = True
        assert observations[0]['thread']['id'] != observations[1]['thread']['id']
        with box.store.connect() as connection:
            run = runtime.read_run(connection, identity)
            context = json.loads(connection.execute('SELECT document FROM creator_thread_contexts').fetchone()[0])
            assert context['replaced_empty_context']['thread_id'] == observations[0]['thread']['id']
            assert context['replacement_evidence']['rollout_absent'] is True
            assert context['replacement_evidence']['native_record_absent'] is True
            assert not connection.execute('SELECT 1 FROM creator_model_calls').fetchone()
            assert not connection.execute('SELECT 1 FROM toolbox_dispatch_retries').fetchone()
            job = dict(connection.execute('SELECT * FROM toolbox_jobs').fetchone())
            assert job['status'] == 'queued' and not any(job.get(key) for key in ('dispatch_started', 'queue_id', 'turn_id'))
            assert run['status'] == 'queued'
        report = {'passed': True, 'api': 'task_runtime.prepare_target', 'observations': observations,
                  'empty_context_recovery_verified': True, 'model_calls': 0, 'queue_writes': 0,
                  'production_database_writes': 0, 'synthetic_job_unchanged': True,
                  'synthetic_model_call_count': 0, 'methods': calls,
                  'runtime_source': str(Path(runtime.__file__).resolve()),
                  'runtime_sha256': digest(Path(runtime.__file__)),
                  'transport_source': str(Path(transport.__file__).resolve()),
                  'transport_sha256': digest(Path(transport.__file__)),
                  'source_dependencies': {name: digest(backend / name) for name in (
                      'easel_workbench/runtime/project_paths.py', 'easel_workbench/runtime/desk.py',
                      'easel_workbench/runtime/bridge.py')},
                  'temporary_database_removed_after_validation': True}
        return report


def probe_capabilities(backend, workspace):
    """Inspect feature/tool metadata in the actual production project, 0 turns."""
    assert workspace and workspace.is_dir(), 'An explicit existing project is required'
    transport, source = load_transport(backend)
    calls = []
    allowed = {'initialize', 'thread/start', 'thread/read', 'thread/loaded/list',
               'experimentalFeature/list', 'mcpServerStatus/list'}

    class MetadataRPC(transport.RPC):
        def call(self, method, params=None, timeout=30):
            assert method in allowed, 'Capability validation accepts metadata methods only'
            calls.append(method)
            return super().call(method, params, timeout)

        def write(self, message):
            assert message.get('method') in allowed | {'initialized'}
            return super().write(message)

    with tempfile.TemporaryDirectory(prefix='easel-native-capability-schema-') as directory:
        subprocess.run([str(transport.CODEX), 'app-server', 'generate-json-schema',
                        '--experimental', '--out', directory], check=True,
                       capture_output=True, timeout=30)
        request = next(Path(directory).rglob('ClientRequest.json'))
        definition = json.loads(request.read_text(encoding='utf-8'))
        assert all(method in json.dumps(definition) for method in (
            'experimentalFeature/list', 'mcpServerStatus/list'))
        schema_hashes = {}
        for name, required in [('ExperimentalFeatureListParams.json', {'threadId', 'limit'}),
                               ('ListMcpServerStatusParams.json', {'threadId', 'detail', 'limit'})]:
            path = next(Path(directory).rglob(name))
            schema = json.loads(path.read_text(encoding='utf-8'))
            assert required <= schema['properties'].keys()
            schema_hashes[name] = digest(path)
    connection = MetadataRPC()
    try:
        started = connection.call('thread/start', {'cwd': str(workspace.resolve()), 'ephemeral': False})
        thread = summary(started)
        assert thread['id'] and thread['turn_count'] == 0
        assert Path(thread['cwd'].removeprefix('\\\\?\\')).resolve() == workspace.resolve()
        assert thread['id'] in connection.call('thread/loaded/list', {}).get('data', [])
        features, servers = [], []
        for method, target in [('experimentalFeature/list', features), ('mcpServerStatus/list', servers)]:
            cursor = None
            for _ in range(10):
                params = {'threadId': thread['id'], 'limit': 100}
                if cursor:
                    params['cursor'] = cursor
                if method == 'mcpServerStatus/list':
                    params['detail'] = 'toolsAndAuthOnly'
                page = connection.call(method, params)
                target.extend(page.get('data') or [])
                cursor = page.get('nextCursor')
                if not cursor:
                    break
            assert not cursor, 'Metadata exceeds bounded validation page count'
        selected = [{key: row.get(key) for key in ('name', 'enabled', 'stage', 'defaultEnabled')}
                    for row in features if re.search(r'image|shell|exec|mcp|code_mode|apps', row.get('name', ''), re.I)]
        mcp = []
        safe_name = lambda value: value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:/-]{1,160}', value) else '[nonstandard-name]'
        for row in servers:
            names = sorted((row.get('tools') or {}).keys())
            mcp.append({'name': safe_name(row.get('name')), 'auth_status': row.get('authStatus'),
                        'runtime_status': row.get('runtimeStatus'), 'tool_count': len(names),
                        'tool_discovery_error': bool(row.get('toolsError')),
                        'image_generation_tool_names': [safe_name(name) for name in names
                                                       if re.search(r'image.?gen|generate.?image|draw', name, re.I)],
                        'local_execution_tool_names': [safe_name(name) for name in names
                                                      if re.search(r'exec_command|run_command|shell|file_system', name, re.I)]})
        read = summary(connection.call('thread/read', {'threadId': thread['id'], 'includeTurns': False}))
        assert read['id'] == thread['id'] and read['turn_count'] == 0
        return {'passed': True, 'project': str(workspace.resolve()), 'thread': thread,
                'instruction_source_count': len(started.get('instructionSources') or []),
                'features': selected, 'feature_count': len(features), 'mcp_servers': mcp,
                'schema_sha256': schema_hashes, 'methods': calls,
                'transport_source': str(source), 'transport_sha256': digest(source),
                'model_calls': 0, 'queue_writes': 0, 'production_database_writes': 0,
                'limitations': ['Feature/tool metadata does not verify inference execution or file delivery.',
                                'Desktop host-injected tools are not forwarded by a bare app-server thread/start request.',
                                'This probe does not invoke any image generation or local execution tool.']}
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--mode', choices=('lifecycle', 'account', 'owned', 'capabilities'), default='lifecycle')
    parser.add_argument('--cwd', type=Path)
    args = parser.parse_args()
    backend = args.backend.resolve()
    report = probe_capabilities(backend, args.cwd) if args.mode == 'capabilities' else {
        'lifecycle': probe, 'account': probe_account, 'owned': probe_owned}[args.mode](backend)
    manifest = backend / 'workbench-release.json'
    report['backend'] = {'release': backend.name,
                         'manifest_sha256': digest(manifest) if manifest.is_file() else None}
    report['harness_sha256'] = digest(Path(__file__).resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    if args.mode == 'lifecycle':
        print(json.dumps({'passed': report['passed'], 'ghost_reproduced': report['ghost_reproduced'],
                          'thread_id': report['started']['id'], 'methods': report['methods']}, ensure_ascii=False))
    elif args.mode == 'account':
        print(json.dumps({key: report[key] for key in ('passed', 'account_type', 'requires_openai_auth',
                          'needs_auth_derived', 'visible_model_count', 'default_model_present', 'methods')}, ensure_ascii=False))
    elif args.mode == 'owned':
        print(json.dumps({key: report[key] for key in ('passed', 'api', 'empty_context_recovery_verified',
                          'synthetic_job_unchanged', 'model_calls', 'methods')}, ensure_ascii=False))
    else:
        print(json.dumps({'passed': report['passed'], 'project': report['project'],
                          'features': report['features'], 'mcp_servers': report['mcp_servers'],
                          'model_calls': 0}, ensure_ascii=False))
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
