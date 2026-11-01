"""TEMP controls, real loopback probes and identity-fenced recovery exercises.

All process inventories and held termination handles are synthetic. No production
selector, database, listener or Windows process is inspected or modified.
"""
from collections import deque
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from easel_workbench import health_watchdog as watchdog
from easel_workbench import processes
from easel_workbench.health_endpoint import health_token
from easel_workbench.health_policy import assess


@pytest.fixture(scope='module')
def health_http():
    token = '9' * 64
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            calls.append(self.path)
            mode = self.path.strip('/')
            supplied = self.headers.get('X-Workbench-Health-Token')
            nonce = self.headers.get('X-Workbench-Health-Nonce')
            if mode == 'slow':
                time.sleep(.15)
            if supplied != token:
                self.send_response(404); self.end_headers(); return
            if mode == 'redirect':
                self.send_response(302); self.send_header('Location', '/ok'); self.end_headers(); return
            value = {'ok': True, 'nonce': nonce, 'release': 'workbench-test', 'pid': 1234}
            changes = {'nonce': {'nonce': 'cached'}, 'release': {'release': 'workbench-other'},
                       'pid': {'pid': True}, 'not-ok': {'ok': False}, 'zero-pid': {'pid': 0}}
            value.update(changes.get(mode, {}))
            body = json.dumps(value).encode()
            if mode == 'invalid':
                body = b'not-json'
            elif mode == 'oversized':
                body = b' ' * 5000
            self.send_response(503 if mode == 'status' else 200)
            if mode != 'header':
                self.send_header('X-Workbench-Health', '1')
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body))); self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    server.daemon_threads = True
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=.05), daemon=True)
    thread.start()
    try:
        yield SimpleNamespace(url=f'http://127.0.0.1:{server.server_port}', token=token, calls=calls)
    finally:
        server.shutdown(); server.server_close(); thread.join(timeout=2)


def test_real_http_nonce_token_and_release_are_verified(health_http):
    result = watchdog.request_health(health_http.url + '/ok', health_http.token, 'workbench-test')
    assert result['ok'] and result['pid'] == 1234 and result['seconds'] < 2
    assert health_http.token not in json.dumps(result)
    rejected = watchdog.request_health(health_http.url + '/ok', 'wrong', 'workbench-test')
    assert rejected == {'ok': False, 'reason': 'unverified_http', 'recoverable': False}


@pytest.mark.parametrize('mode', ['nonce', 'release', 'pid', 'zero-pid', 'not-ok', 'invalid', 'header', 'oversized', 'status'])
def test_wrong_http_response_cannot_trigger_a_restart(health_http, mode):
    result = watchdog.request_health(health_http.url + '/' + mode, health_http.token, 'workbench-test')
    assert result['ok'] is False and result['recoverable'] is False


def test_health_redirect_is_not_followed(health_http):
    before = len(health_http.calls)
    result = watchdog.request_health(health_http.url + '/redirect', health_http.token, 'workbench-test')
    assert result['ok'] is False and result['recoverable'] is False
    assert health_http.calls[before:] == ['/redirect']


def test_real_http_timeout_is_recoverable_but_never_sleeps_unbounded(health_http):
    start = time.monotonic()
    result = watchdog.request_health(health_http.url + '/slow', health_http.token, 'workbench-test', timeout=.03)
    assert result == {'ok': False, 'reason': 'connection_or_timeout', 'recoverable': True}
    assert time.monotonic() - start < 1


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding='utf-8')


@pytest.fixture
def controls(tmp_path):
    root = tmp_path.resolve(); state = root / watchdog.STATE_DIR
    manifest = root / 'workbench-releases/workbench-test/workbench-release.json'
    put(manifest, {'release': 'workbench-test', 'files': {}})
    runtime = {'release': 'workbench-test', 'manifest_sha256': hashlib.sha256(manifest.read_bytes()).hexdigest()}
    native = {'release': 'native-test', 'manifest_sha256': 'b' * 64}
    put(root / 'data/active-workbench.json', runtime)
    put(root / 'data/active-native.json', native)
    put(root / 'data/migration-owner.json', {**runtime, 'target_root': str(root)})
    put(state / 'cutover.json', {'phase': 'live', 'target_root': str(root)})
    put(state / 'admission.json', {'workers': True})
    with sqlite3.connect(root / 'data/desk.sqlite') as connection:
        connection.execute('CREATE TABLE original(id TEXT PRIMARY KEY, value TEXT)')
        connection.execute('INSERT INTO original VALUES(?,?)', ('original', 'preserve exactly'))
    return SimpleNamespace(root=root, state=state, runtime=runtime, native=native,
                           binding={'runtime': runtime, 'native': native}, manifest=manifest)


def test_controls_verify_actual_manifest_and_exact_owner(controls):
    assert watchdog.controls(controls.root) == controls.binding
    controls.manifest.write_text('changed', encoding='utf-8')
    with pytest.raises(watchdog.GuardError, match='manifest_changed'):
        watchdog.controls(controls.root)


@pytest.mark.parametrize('file,changes', [
    ('data/migration-owner.json', {'manifest_sha256': 'f' * 64}),
    ('data/migration-owner.json', {'target_root': 'C:/foreign'}),
    ('.local/workbench-deployment/cutover.json', {'phase': 'fenced'}),
    ('.local/workbench-deployment/cutover.json', {'target_root': 'C:/foreign'}),
    ('.local/workbench-deployment/admission.json', {'workers': False}),
    ('data/active-native.json', {'release': '../foreign'}),
])
def test_controls_reject_maintenance_owner_and_binding_changes(controls, file, changes):
    path = controls.root / file
    put(path, {**watchdog.read(path), **changes})
    with pytest.raises(watchdog.GuardError):
        watchdog.controls(controls.root)


def test_owned_pause_is_still_rejected_without_the_exact_operation(controls):
    watchdog.pause_owned(controls.root, 'mine', controls.binding)
    with pytest.raises(watchdog.GuardError, match='maintenance_pause'):
        watchdog.controls(controls.root)
    with pytest.raises(watchdog.GuardError, match='maintenance_pause'):
        watchdog.controls(controls.root, own_pause='other')
    assert watchdog.controls(controls.root, own_pause='mine') == controls.binding


def abandoned(controls, **marker_changes):
    put(controls.state / 'health-recovery.json', {'operation_id': 'mine', 'binding': controls.binding, 'phase': 'stopping'})
    put(controls.state / 'paused', {'owner': 'health-watchdog', 'operation_id': 'mine',
                                  'binding': controls.binding, **marker_changes})


def test_abandoned_fence_releases_only_its_owned_pause(controls):
    abandoned(controls)
    watchdog.resume_fence(controls.root)
    assert not (controls.state / 'paused').exists()
    assert watchdog.read(controls.state / 'health-recovery.json')['phase'] == 'abandoned_fence_released'


@pytest.mark.parametrize('changes', [{'owner': 'deployment'}, {'operation_id': 'foreign'}])
def test_resume_never_clears_someone_elses_pause(controls, changes):
    abandoned(controls, **changes)
    original = (controls.state / 'paused').read_bytes()
    watchdog.resume_fence(controls.root)
    assert (controls.state / 'paused').read_bytes() == original


def test_abandoned_fence_cannot_clear_a_pause_after_release_selection_changes(controls):
    abandoned(controls)
    native = {**controls.native, 'release': 'native-new'}
    put(controls.root / 'data/active-native.json', native)
    original = (controls.state / 'paused').read_bytes()
    with pytest.raises(watchdog.GuardError, match='abandoned_fence_binding_changed'):
        watchdog.resume_fence(controls.root)
    assert (controls.state / 'paused').read_bytes() == original


@pytest.fixture
def running(controls, monkeypatch):
    fixture = controls
    fixture.clock = [2000.0]
    monkeypatch.setattr(watchdog.time, 'time', lambda: fixture.clock[0])
    ticks = str(int((1000 + 11644473600) * 10_000_000))
    launch = fixture.root / 'workbench-releases/workbench-test/launch.py'
    command = f'"C:/runtime/pythonw.exe" "{launch}" server --root "{fixture.root}" --port 9123'
    fixture.inventory = {
        11: {'pid': 11, 'parent': 1, 'name': 'pythonw.exe', 'command': command, 'creation_ticks': ticks},
        12: {'pid': 12, 'parent': 11, 'name': 'python.exe', 'command': command, 'creation_ticks': ticks},
        13: {'pid': 13, 'parent': 12, 'name': 'codex.exe', 'command': '"C:/runtime/codex.exe" app-server', 'creation_ticks': ticks},
        21: {'pid': 21, 'parent': 1, 'name': 'python.exe', 'command': command.replace(' server ', ' worker '), 'creation_ticks': ticks},
        31: {'pid': 31, 'parent': 1, 'name': 'pythonw.exe', 'command': f'"C:/runtime/pythonw.exe" "{fixture.root / "launcher.pyw"}"', 'creation_ticks': ticks},
    }
    other_roles = {'worker': 21}
    for pid, role in enumerate(('publisher', 'feedback', 'collector', 'learning', 'local'), 22):
        fixture.inventory[pid] = {'pid': pid, 'parent': 1, 'name': 'python.exe',
                                  'command': command.replace(' server ', ' ' + role + ' '), 'creation_ticks': ticks}
        other_roles[role] = pid
    fixture.status = {'manager': 31, 'release': 'workbench-test', 'paused': False,
                      'heartbeat': 1999.0, 'roles': {'server': 11, **other_roles}}
    put(fixture.state / 'pids.json', fixture.status)
    fixture.terminated = []; fixture.opened = []; fixture.closed = []
    fixture.token = health_token(fixture.root, create=True)
    monkeypatch.setattr(processes, 'rows', lambda: copy_rows(fixture.inventory))
    monkeypatch.setattr(watchdog, 'listeners', lambda: {12})
    monkeypatch.setattr(watchdog, 'operator_gates', lambda root: None)
    monkeypatch.setattr(watchdog, 'request_health', lambda *args, **kwargs: {'ok': False, 'recoverable': True})
    original_pause = watchdog.pause_owned

    def pause_ack(root, operation, binding):
        marker = original_pause(root, operation, binding)
        put(fixture.state / 'pids.json', {**fixture.status, 'paused': True, 'heartbeat': marker['created_at']})
        return marker

    monkeypatch.setattr(watchdog, 'pause_owned', pause_ack)

    class Held:
        def __init__(self, row):
            self.pid = row['pid']; self.creation_ticks = int(row['creation_ticks']); self.dead = False
        def __enter__(self):
            fixture.opened.append(self.pid); return self
        def __exit__(self, *args):
            fixture.closed.append(self.pid)
        def terminate(self, *, expected_creation_ticks):
            assert expected_creation_ticks == self.creation_ticks
            budget = watchdog.read(fixture.state / 'health-policy.json')
            assert budget['attempts'] == [fixture.clock[0]], 'budget must be durable before the first termination'
            assert set(fixture.opened) == {11, 12, 13}, 'all creation identities must be held before stopping'
            fixture.terminated.append(self.pid); self.dead = True
        def exited(self):
            return self.dead

    monkeypatch.setattr(processes, 'checked_identity', Held)
    observation = {'target': 'workbench-test:server:11:' + ticks, 'local_ok': False,
                   'ingress_ok': False, 'age_seconds': 1000, 'eligible': True}
    policy = {}
    for at in (1970, 1980, 1990):
        policy = assess(policy, observation, at)
    fixture.policy = policy
    return fixture


def copy_rows(inventory):
    return {pid: dict(row) for pid, row in inventory.items()}


def recover(fixture):
    return watchdog.recover_server(fixture.root, fixture.binding, fixture.status,
                                   fixture.inventory[11], fixture.policy, fixture.token)


def test_idle_recovery_stops_only_held_server_branch_and_preserves_database(running):
    before = (running.root / 'data/desk.sqlite').read_bytes()
    policy, outcome = recover(running)
    assert outcome == 'server_restart_requested' and policy['attempts'] == [2000]
    assert running.terminated == [11, 12, 13]
    assert set(running.closed) == {11, 12, 13}
    assert not ({*running.status['roles'].values()} - {11}) & set(running.terminated)
    assert 31 not in running.terminated
    assert not (running.state / 'paused').exists()
    assert (running.root / 'data/desk.sqlite').read_bytes() == before
    assert watchdog.read(running.state / 'health-recovery.json')['phase'] == 'stopped'
    assert running.token not in (running.state / 'health-events.jsonl').read_text()


def test_active_or_unknown_work_is_never_terminated(running, monkeypatch):
    def active(root):
        raise watchdog.GuardError('active_or_unresolved_work')
    monkeypatch.setattr(watchdog, 'operator_gates', active)
    with pytest.raises(watchdog.GuardError, match='active_or_unresolved_work'):
        recover(running)
    assert running.terminated == [] and not (running.state / 'paused').exists()
    assert not (running.state / 'health-policy.json').exists()


@pytest.mark.parametrize('problem', ['foreign_role', 'reused_pid', 'listener', 'unknown_child'])
def test_unverified_identity_or_listener_cannot_be_stopped(running, monkeypatch, problem):
    expected = dict(running.inventory[11])
    if problem == 'foreign_role':
        running.inventory[11]['command'] = '"C:/runtime/python.exe" "C:/foreign/server.py"'
    elif problem == 'reused_pid':
        running.inventory[11]['creation_ticks'] = str(int(expected['creation_ticks']) + 1000)
    elif problem == 'listener':
        monkeypatch.setattr(watchdog, 'listeners', lambda: {999})
    else:
        running.inventory[14] = {'pid': 14, 'parent': 12, 'name': 'unknown.exe', 'command': 'unknown', 'creation_ticks': expected['creation_ticks']}
    with pytest.raises(watchdog.GuardError):
        watchdog.recover_server(running.root, running.binding, running.status, expected, running.policy, running.token)
    assert running.terminated == [] and not (running.state / 'paused').exists()


def test_fenced_second_idle_check_holds_real_sqlite_writer_lock_and_defers(running, monkeypatch):
    calls = []
    def gates(root):
        calls.append(True)
        if len(calls) == 2:
            with closing(sqlite3.connect(root / 'data/desk.sqlite', timeout=0, isolation_level=None)) as connection:
                with pytest.raises(sqlite3.OperationalError, match='locked'):
                    connection.execute('BEGIN IMMEDIATE')
            raise watchdog.GuardError('new_active_work')
    monkeypatch.setattr(watchdog, 'operator_gates', gates)
    with pytest.raises(watchdog.GuardError, match='new_active_work'):
        recover(running)
    assert len(calls) == 2 and running.terminated == []
    assert not (running.state / 'health-policy.json').exists()
    assert not (running.state / 'paused').exists()
    with sqlite3.connect(running.root / 'data/desk.sqlite', timeout=0, isolation_level=None) as connection:
        connection.execute('BEGIN IMMEDIATE'); connection.execute('ROLLBACK')


def test_changed_branch_during_pause_is_not_killed(running, monkeypatch):
    first = copy_rows(running.inventory); changed = copy_rows(first)
    changed[14] = {**first[13], 'pid': 14}
    inventories = iter([first, changed])
    monkeypatch.setattr(processes, 'rows', lambda: next(inventories))
    with pytest.raises(watchdog.GuardError, match='server_branch_changed'):
        recover(running)
    assert running.terminated == [] and not (running.state / 'paused').exists()


@pytest.mark.parametrize('field,value', [
    ('parent', 11), ('name', 'node.exe'), ('command', 'changed native command'),
    ('creation_ticks', str(int((1000 + 11644473600) * 10_000_000) + 1000)),
])
def test_same_pid_branch_requires_unchanged_parent_command_name_and_creation(running, monkeypatch, field, value):
    first = copy_rows(running.inventory); changed = copy_rows(first)
    changed[13][field] = value
    inventories = iter([first, changed])
    monkeypatch.setattr(processes, 'rows', lambda: next(inventories))
    with pytest.raises(watchdog.GuardError, match='branch_identity_changed'):
        recover(running)
    assert running.terminated == [] and not (running.state / 'health-policy.json').exists()
    assert set(running.closed) == set(running.opened)
    assert not (running.state / 'paused').exists()


def test_missing_process_root_cannot_create_an_empty_owned_branch():
    with pytest.raises(watchdog.GuardError, match='missing_process_root'):
        watchdog.process_members({}, 11)


def test_child_older_than_parent_is_a_reused_parent_pid_not_an_owned_descendant(running):
    running.inventory[13]['creation_ticks'] = str(int(running.inventory[12]['creation_ticks']) - 1000)
    assert watchdog.process_members(running.inventory, 11) == {11, 12}


@pytest.mark.parametrize('change', ['extra_argument', 'duplicate_root', 'reordered'])
def test_role_command_is_exact_and_cannot_hide_overrides(running, change):
    row = running.inventory[11]
    if change == 'extra_argument':
        row['command'] += ' --extra'
    elif change == 'duplicate_root':
        row['command'] += ' --root C:/foreign'
    else:
        row['command'] = row['command'].replace(f'--root "{running.root}" --port 9123', f'--port 9123 --root "{running.root}"')
    with pytest.raises(watchdog.GuardError, match='foreign_role'):
        watchdog.role_row(running.inventory, 11, running.root, running.runtime)


def test_release_locked_probe_must_still_be_a_recoverable_transport_failure(running, monkeypatch):
    monkeypatch.setattr(watchdog, 'request_health', lambda *a, **kw: {'ok': False, 'recoverable': False, 'reason': 'unverified_identity'})
    with pytest.raises(watchdog.GuardError, match='health_no_longer_recoverable'):
        recover(running)
    assert running.terminated == [] and not (running.state / 'paused').exists()


@pytest.mark.parametrize('final', [
    {'ok': True, 'pid': 12},
    {'ok': False, 'recoverable': False, 'reason': 'unverified_identity'},
])
def test_final_fenced_probe_cancels_restart_on_recovery_or_unverified_identity(running, monkeypatch, final):
    probes = iter([{'ok': False, 'recoverable': True}, final])
    monkeypatch.setattr(watchdog, 'request_health', lambda *a, **kw: next(probes))
    if final['ok']:
        policy, outcome = recover(running)
        assert policy == running.policy and outcome == 'recovered_without_restart'
    else:
        with pytest.raises(watchdog.GuardError, match='fenced_health_unverified'):
            recover(running)
    assert not running.terminated and not (running.state / 'health-policy.json').exists()
    assert not (running.state / 'paused').exists()


def test_health_recovered_under_release_lock_requires_no_restart(running, monkeypatch):
    monkeypatch.setattr(watchdog, 'request_health', lambda *a, **kw: {'ok': True, 'pid': 12})
    policy, outcome = recover(running)
    assert outcome == 'recovered_without_restart' and policy == running.policy
    assert not running.terminated and not (running.state / 'health-policy.json').exists()


def tick_fixture(running, monkeypatch, local_results, *, ingress_ok=False):
    results = deque(local_results)
    monkeypatch.setattr(watchdog, 'ingress_origin', lambda root: 'https://test.ts.net:8443')
    monkeypatch.setattr(watchdog, 'network_diagnosis', lambda: {'state': 'configured'})
    def health(url, *args, **kwargs):
        if url.startswith('http://127.0.0.1:9123'):
            return results.popleft()
        return {'ok': ingress_ok, 'pid': 12, 'recoverable': False}
    monkeypatch.setattr(watchdog, 'request_health', health)
    monkeypatch.setattr(watchdog, 'recover_server', lambda *a: pytest.fail('unexpected server restart'))
    monkeypatch.setattr(watchdog, 'recover_manager', lambda *a: pytest.fail('unexpected manager restart'))


def test_network_failure_with_local_health_never_restarts_processes(running, monkeypatch):
    tick_fixture(running, monkeypatch, [{'ok': True, 'pid': 12}])
    report = watchdog.tick(running.root)
    assert report['decision'] == 'network_degraded' and report['local']['ok']
    assert report['ingress']['diagnosis']['state'] == 'configured'
    assert running.token not in json.dumps(report)


def test_transient_local_failure_is_reset_by_a_healthy_probe(running, monkeypatch):
    bad = {'ok': False, 'recoverable': True, 'reason': 'connection_or_timeout'}
    tick_fixture(running, monkeypatch, [bad, bad, {'ok': True, 'pid': 12}, bad], ingress_ok=True)
    statuses = []
    for at in (2000, 2010, 2020, 2030):
        running.clock[0] = at
        put(running.state / 'pids.json', {**running.status, 'heartbeat': at - 1})
        statuses.append(watchdog.tick(running.root)['decision'])
    assert statuses == ['waiting', 'waiting', 'healthy', 'waiting']
    assert watchdog.read(running.state / 'health-policy.json')['failures'] == 1


def test_corrupt_policy_cannot_turn_into_an_empty_restart_budget(running, monkeypatch):
    (running.state / 'health-policy.json').write_text('{broken', encoding='utf-8')
    tick_fixture(running, monkeypatch, [{'ok': True, 'pid': 12}])
    report = watchdog.tick(running.root)
    assert report['decision'] == 'invalid_state' and report['policy']['invalid_state'] is True


def test_foreign_health_pid_is_not_accepted_as_a_live_server(running, monkeypatch):
    tick_fixture(running, monkeypatch, [{'ok': True, 'pid': 21}])
    report = watchdog.tick(running.root)
    assert report['local']['reason'] == 'foreign_health_pid'
    assert report['decision'] == 'deferred' and report['policy']['action'] is None


def test_ingress_identity_must_match_the_owned_server_without_restarting_local(running, monkeypatch):
    tick_fixture(running, monkeypatch, [{'ok': True, 'pid': 12}], ingress_ok=True)
    def health(url, *args, **kwargs):
        return {'ok': True, 'pid': 12 if url.startswith('http://127.0.0.1:9123') else 21}
    monkeypatch.setattr(watchdog, 'request_health', health)
    report = watchdog.tick(running.root)
    assert report['local']['ok'] and report['ingress']['ok'] is False
    assert report['ingress']['reason'] == 'foreign_ingress_pid'
    assert report['decision'] == 'network_degraded' and report['policy']['action'] is None
