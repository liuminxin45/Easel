"""Independent, bounded health supervision; never replay a business operation.

Windows owns this job independently from the app and manager. Only an idle,
identity-fenced server branch may be replaced. Network failures are diagnostic.
"""
from contextlib import ExitStack, closing
from pathlib import Path
import hashlib
import json
import os
import re
import secrets
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

from .health_endpoint import HEALTH_PATH, health_token
from .health_policy import assess, attempted
from .runtime.feedback_ledger import atomic, atomic_create, locked

ALLOWED_CHILDREN = frozenset(('python.exe', 'pythonw.exe', 'node.exe', 'codex.exe'))
STATE_DIR = '.local/workbench-deployment'


class GuardError(ValueError):
    pass


def read(path):
    path = Path(path)
    if path.stat().st_size > 4 * 1024 * 1024:
        raise GuardError('oversized_control')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def controls(root, *, own_pause=None):
    state = root / STATE_DIR
    runtime = read(root / 'data/active-workbench.json')
    native = read(root / 'data/active-native.json')
    for value, prefix in ((runtime, 'workbench'), (native, 'native')):
        if not isinstance(value, dict) or not re.fullmatch(prefix + r'-[A-Za-z0-9_-]+', str(value.get('release', ''))) or not re.fullmatch('[a-f0-9]{64}', str(value.get('manifest_sha256', ''))):
            raise GuardError('invalid_binding')
    manifest = root / 'workbench-releases' / runtime['release'] / 'workbench-release.json'
    if hashlib.sha256(manifest.read_bytes()).hexdigest() != runtime['manifest_sha256']:
        raise GuardError('manifest_changed')
    owner = read(root / 'data/migration-owner.json')
    cutover = read(state / 'cutover.json')
    admission = read(state / 'admission.json')
    if (not all(isinstance(value, dict) for value in (owner, cutover, admission))
            or Path(owner.get('target_root', '')).resolve() != root
            or any(owner.get(k) != runtime[k] for k in ('release', 'manifest_sha256'))
            or cutover.get('phase') != 'live'
            or Path(cutover.get('target_root', '')).resolve() != root
            or admission.get('workers') is not True):
        raise GuardError('maintenance_or_owner')
    pause = state / 'paused'
    if pause.exists():
        if own_pause is None or read(pause).get('operation_id') != own_pause:
            raise GuardError('maintenance_pause')
    return {'runtime': runtime, 'native': native}


def request_health(url, token, release, *, timeout=3):
    nonce = secrets.token_hex(16)
    request = urllib.request.Request(url, headers={
        'X-Workbench-Health-Token': token, 'X-Workbench-Health-Nonce': nonce,
        'Cache-Control': 'no-cache'})
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    start = time.monotonic()
    try:
        with opener.open(request, timeout=timeout) as response:
            raw = response.read(4097)
            if len(raw) > 4096:
                raise GuardError('unexpected_health_body')
            value = json.loads(raw)
            if (not isinstance(value, dict) or response.status != 200 or response.headers.get('X-Workbench-Health') != '1'
                    or value.get('ok') is not True or value.get('nonce') != nonce
                    or value.get('release') != release or type(value.get('pid')) is not int or value['pid'] <= 0):
                raise GuardError('unexpected_health_identity')
            return {'ok': True, 'pid': value['pid'], 'seconds': round(time.monotonic() - start, 4)}
    except urllib.error.HTTPError:
        return {'ok': False, 'reason': 'unverified_http', 'recoverable': False}
    except GuardError:
        return {'ok': False, 'reason': 'unverified_identity', 'recoverable': False}
    except (ValueError, TypeError):
        return {'ok': False, 'reason': 'invalid_health_response', 'recoverable': False}
    except (OSError, TimeoutError):
        return {'ok': False, 'reason': 'connection_or_timeout', 'recoverable': True}


def process_members(inventory, pid):
    if pid not in inventory:
        raise GuardError('missing_process_root')
    selected = {pid}
    while True:
        more = {p for p, row in inventory.items() if row['parent'] in selected} - selected
        for child in more:
            if int(inventory[child]['creation_ticks']) < int(inventory[inventory[child]['parent']]['creation_ticks']):
                raise GuardError('reused_parent_identity')
        if not more:
            return selected
        selected |= more


def role_row(inventory, pid, root, runtime, *, manager=False):
    from .processes import argv
    row = inventory.get(pid)
    if not row or row['name'].lower() not in ('python.exe', 'pythonw.exe') or not row.get('command'):
        raise GuardError('unverified_role')
    args = argv(row['command'])
    if manager:
        valid = len(args) == 2 and Path(args[1]).resolve() == root / 'launcher.pyw'
    else:
        valid = (len(args) == 7 and Path(args[1]).resolve() == root / 'workbench-releases' / runtime['release'] / 'launch.py'
                 and args[2:4] == ['server', '--root'] and Path(args[4]).resolve() == root
                 and args[5:] == ['--port', '9123'])
    if not valid:
        raise GuardError('foreign_role')
    return row


def process_age(row, now):
    return max(0.0, now - (int(row['creation_ticks']) / 10_000_000 - 11644473600))


def verify_server_branch(inventory, members, root, runtime):
    from .processes import argv
    for pid in members:
        row = inventory[pid]
        name = row['name'].lower()
        if name not in ALLOWED_CHILDREN or not row.get('command'):
            raise GuardError('unverified_server_child')
        if name in ('python.exe', 'pythonw.exe'):
            # QR login/install helpers are not the server, even though they
            # use Python and may not have finished writing their status file.
            try:role_row(inventory, pid, root, runtime)
            except (GuardError, ValueError):raise GuardError('unverified_server_child') from None
        elif 'app-server' not in argv(row['command']):
            raise GuardError('unverified_server_child')


def listeners():
    command = "ConvertTo-Json -InputObject @((Get-NetTCPConnection -LocalPort 9123 -State Listen -ErrorAction SilentlyContinue).OwningProcess) -Compress"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            capture_output=True, text=True, timeout=12, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise GuardError('listener_inventory_unavailable')
    return {int(value) for value in json.loads(result.stdout.strip().lstrip('\ufeff')) if value is not None}


def operator_gates(root):
    # Reuse the deployment gates and their exact reviewed historical receipts.
    # They are operator code, never a second copy inside the application.
    sys.path.insert(0, str(root / 'scripts'))
    from activate_workbench import idle, queue_idle
    state = idle(root / 'data/desk.sqlite')
    if state.get('busy'):
        raise GuardError('active_or_unresolved_work')
    if queue_idle().get('empty') is not True:
        raise GuardError('native_queue_active')


def event(root, kind, **value):
    record = {'at': time.time(), 'kind': kind, **value}
    with (root / STATE_DIR / 'health-events.jsonl').open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(record, separators=(',', ':')) + '\n');stream.flush();os.fsync(stream.fileno())


def pause_owned(root, operation, binding):
    path = root / STATE_DIR / 'paused'
    marker = {'owner': 'health-watchdog', 'operation_id': operation, 'binding': binding, 'created_at': time.time()}
    if not atomic_create(path, marker):
        raise FileExistsError(path)
    return marker


def clear_owned_pause(root, operation):
    path = root / STATE_DIR / 'paused'
    if path.exists() and read(path).get('owner') == 'health-watchdog' and read(path).get('operation_id') == operation:
        path.unlink()


def resume_fence(root):
    state = root / STATE_DIR
    journal = state / 'health-recovery.json'
    if not journal.exists() or not (state / 'paused').exists():
        return
    value = read(journal)
    operation = value.get('operation_id')
    marker = read(state / 'paused')
    if marker.get('owner') != 'health-watchdog' or marker.get('operation_id') != operation:
        return
    with locked(state / 'runtime-release.lock', timeout=.1), locked(state / 'frontend-release.lock', timeout=.1):
        if controls(root, own_pause=operation) != value.get('binding'):
            raise GuardError('abandoned_fence_binding_changed')
        # A new bounded job never resumes a partially executed kill. Release
        # only its exact abandoned fence; the manager/next probe rechecks reality.
        clear_owned_pause(root, operation)
        atomic(journal, {**value, 'phase': 'abandoned_fence_released', 'at': time.time()})
        event(root, 'abandoned_fence_released', operation_id=operation)


def consume_budget(root, policy, target):
    policy = attempted(policy, time.time(), target)
    atomic(root / STATE_DIR / 'health-policy.json', policy)
    return policy


def recover_server(root, binding, status, expected_row, policy, token):
    from .processes import rows, checked_identity
    state = root / STATE_DIR;operation = uuid.uuid4().hex
    journal = state / 'health-recovery.json'
    with locked(state / 'runtime-release.lock', timeout=.1), locked(state / 'frontend-release.lock', timeout=.1):
        if controls(root) != binding:
            raise GuardError('binding_changed')
        probe = request_health('http://127.0.0.1:9123' + HEALTH_PATH, token, binding['runtime']['release'])
        if probe['ok']:
            return policy, 'recovered_without_restart'
        if probe.get('recoverable') is not True:
            raise GuardError('health_no_longer_recoverable')
        operator_gates(root)
        inventory = rows();pid = expected_row['pid']
        current = role_row(inventory, pid, root, binding['runtime'])
        if current['creation_ticks'] != expected_row['creation_ticks']:
            raise GuardError('server_identity_changed')
        members = process_members(inventory, pid)
        if not listeners().issubset(members):
            raise GuardError('foreign_listener')
        verify_server_branch(inventory, members, root, binding['runtime'])
        from .runtime.scripts.windows_process_identity import ProcessIdentity
        with ProcessIdentity(os.getpid()) as own_identity:
            own_creation = str(own_identity.creation_ticks)
        recovery = {'operation_id': operation, 'binding': binding, 'phase': 'prepared',
                    'server': pid, 'creation_ticks': current['creation_ticks'], 'at': time.time(),
                    'watchdog_pid': os.getpid(), 'watchdog_creation_ticks': own_creation}
        atomic(journal, recovery)
        marker = pause_owned(root, operation, binding)
        try:
            deadline = time.monotonic() + 18
            while True:
                heartbeat = read(state / 'pids.json')
                if (heartbeat.get('manager') == status['manager'] and heartbeat.get('paused') is True
                        and heartbeat.get('release') == binding['runtime']['release']
                        and heartbeat.get('heartbeat', 0) >= marker['created_at']):
                    break
                if time.monotonic() >= deadline:
                    raise GuardError('manager_pause_not_acknowledged')
                time.sleep(.25)
            with closing(sqlite3.connect((root / 'data/desk.sqlite').as_uri() + '?mode=rw', uri=True,
                                         timeout=3, isolation_level=None)) as fence, ExitStack() as held:
                fence.execute('BEGIN IMMEDIATE')
                if controls(root, own_pause=operation) != binding:
                    raise GuardError('fenced_binding_changed')
                operator_gates(root)
                fresh = rows()
                if process_members(fresh, pid) != members:
                    raise GuardError('server_branch_changed')
                handles = {}
                for child in members:
                    if any(fresh[child].get(k) != inventory[child].get(k) for k in ('creation_ticks', 'parent', 'name', 'command')):
                        raise GuardError('branch_identity_changed')
                    handles[child] = held.enter_context(checked_identity(fresh[child]))
                if not listeners().issubset(members):
                    raise GuardError('fenced_foreign_listener')
                probe = request_health('http://127.0.0.1:9123' + HEALTH_PATH, token, binding['runtime']['release'])
                if probe['ok']:
                    return policy, 'recovered_without_restart'
                if probe.get('recoverable') is not True:
                    raise GuardError('fenced_health_unverified')
                policy = consume_budget(root, policy, policy['target'])
                atomic(journal, {**recovery, 'phase': 'stopping'})
                # Stop parents before their children; hold all creation identities.
                order = [];remaining = set(members)
                while remaining:
                    top = [p for p in remaining if inventory[p]['parent'] not in remaining]
                    if not top:
                        raise GuardError('invalid_process_tree')
                    order.extend(top);remaining.difference_update(top)
                for child in order:
                    handles[child].terminate(expected_creation_ticks=handles[child].creation_ticks)
                if any(not h.exited() for h in handles.values()):
                    raise GuardError('server_exit_unconfirmed')
                fence.execute('ROLLBACK')
            atomic(journal, {**recovery, 'phase': 'stopped', 'at': time.time()})
            event(root, 'server_restarted', operation_id=operation, stopped_pids=order, release=binding['runtime']['release'])
            return policy, 'server_restart_requested'
        finally:
            clear_owned_pause(root, operation)


def recover_manager(root, binding, expected_row, policy):
    from .processes import rows, checked_identity
    state = root / STATE_DIR
    with locked(state / 'runtime-release.lock', timeout=.1), locked(state / 'frontend-release.lock', timeout=.1):
        if controls(root) != binding:
            raise GuardError('binding_changed')
        current = read(state / 'pids.json')
        if time.time() - current.get('heartbeat', 0) <= 90:
            return policy, 'manager_recovered_without_restart'
        row = role_row(rows(), expected_row['pid'], root, binding['runtime'], manager=True)
        if row['creation_ticks'] != expected_row['creation_ticks']:
            raise GuardError('manager_identity_changed')
        with checked_identity(row) as handle:
            policy = consume_budget(root, policy, policy['target'])
            handle.terminate(expected_creation_ticks=handle.creation_ticks)
        # The OS recurring manager task starts independently; leave all roles.
        event(root, 'manager_restarted', pid=row['pid'], release=binding['runtime']['release'])
        return policy, 'manager_restart_requested'


def ingress_origin(root):
    from .runtime.auth_totp import CONFIG
    value = read(CONFIG).get('origin', '')
    from urllib.parse import urlsplit
    parsed = urlsplit(value)
    if (parsed.scheme != 'https' or not parsed.hostname or not parsed.hostname.endswith('.ts.net')
            or parsed.port != 8443 or parsed.path not in ('', '/') or parsed.username or parsed.password):
        raise GuardError('invalid_ingress_origin')
    return value.rstrip('/')


def network_diagnosis():
    # Existing Tailscale Windows service already has escalating OS restart
    # actions. Never reset global Funnel config or restart it for remote loss.
    result = subprocess.run(['tailscale', 'funnel', 'status', '--json'], capture_output=True,
                            text=True, timeout=6, creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        return {'state': 'tailscale_unavailable'}
    value = json.loads(result.stdout)
    return {'state': 'configured' if value.get('TCP', {}).get('8443', {}).get('HTTPS') is True else 'mapping_missing'}


def tick(root):
    root = Path(root).resolve();state = root / STATE_DIR;now = time.time()
    status_existed = (state / 'health-status.json').exists()
    try:
        previous_status = read(state / 'health-status.json') if status_existed else {}
        if not isinstance(previous_status, dict):previous_status = {}
    except (ValueError, OSError):
        previous_status = {}
    policy_path = state / 'health-policy.json'
    try:
        previous = read(policy_path) if policy_path.exists() else (None if status_existed else {})
    except (ValueError, OSError):
        previous = None
    report = {'schema': 1, 'at': now, 'watchdog_pid': os.getpid()}
    try:
        resume_fence(root)
        binding = controls(root)
        status = read(state / 'pids.json')
        if status.get('release') != binding['runtime']['release'] or status.get('paused') is not False:
            raise GuardError('stale_role_snapshot')
        from .processes import rows
        inventory = rows()
        server = role_row(inventory, status.get('roles', {}).get('server'), root, binding['runtime'])
        manager = role_row(inventory, status.get('manager'), root, binding['runtime'], manager=True)
        token = health_token(root)
        local = request_health('http://127.0.0.1:9123' + HEALTH_PATH, token, binding['runtime']['release'])
        members = process_members(inventory, server['pid'])
        if local['ok'] and local['pid'] not in members:
            local = {'ok': False, 'reason': 'foreign_health_pid', 'recoverable': False}
        ingress = previous_status.get('ingress')
        if (not isinstance(ingress, dict) or type(ingress.get('at')) not in (int, float)
                or type(ingress.get('ok')) is not bool or now - ingress['at'] >= 60):
            ingress = {**request_health(ingress_origin(root) + HEALTH_PATH, token, binding['runtime']['release'], timeout=5), 'at': now}
            if not ingress['ok']:
                try:ingress['diagnosis'] = network_diagnosis()
                except (OSError, ValueError, subprocess.SubprocessError):ingress['diagnosis'] = {'state': 'diagnosis_unavailable'}
        if ingress.get('ok') and ingress.get('pid') not in members:
            ingress = {'ok': False, 'reason': 'foreign_ingress_pid', 'recoverable': False, 'at': now}
        stalled = now - status.get('heartbeat', 0) > 90
        target_row = manager if stalled else server
        target = ':'.join([binding['runtime']['release'], binding['runtime']['manifest_sha256'],
                           'manager' if stalled else 'server', str(target_row['pid']), target_row['creation_ticks']])
        observation = {'target': target, 'local_ok': local['ok'] and not stalled,
                       'ingress_ok': ingress.get('ok'), 'age_seconds': process_age(target_row, now),
                       'eligible': local['ok'] or local.get('recoverable') is True,
                       'blocked_reason': None if local['ok'] or local.get('recoverable') else local.get('reason')}
        policy = assess(previous, observation, now)
        atomic(policy_path, policy)
        report.update(binding=binding, local=local, ingress=ingress, manager_heartbeat_age=round(now - status['heartbeat'], 2),
                      roles=status['roles'], policy=policy, decision=policy['status'])
        if policy['action'] == 'recover':
            try:
                if stalled:policy, outcome = recover_manager(root, binding, manager, policy)
                else:policy, outcome = recover_server(root, binding, status, server, policy, token)
                report.update(decision=outcome, policy=policy)
            except (GuardError, TimeoutError, OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as error:
                report.update(decision='deferred', reason=str(error) if isinstance(error, GuardError) else type(error).__name__)
    except (GuardError, TimeoutError, OSError, ValueError, KeyError, TypeError, AttributeError, subprocess.SubprocessError) as error:
        reason = str(error) if isinstance(error, GuardError) else type(error).__name__
        policy = assess(previous, {'target': 'unverified', 'local_ok': False, 'ingress_ok': None,
                                  'age_seconds': 0, 'eligible': False, 'blocked_reason': reason}, now)
        atomic(policy_path, policy)
        report.update(decision='deferred', reason=reason, policy=policy)
    atomic(state / 'health-status.json', report)
    if (report.get('decision'), report.get('reason')) != (previous_status.get('decision'), previous_status.get('reason')):
        event(root, 'status_changed', decision=report['decision'], reason=report.get('reason'))
    return report


def run(root, *, duration=50, interval=10):
    root = Path(root).resolve();state = root / STATE_DIR;state.mkdir(parents=True, exist_ok=True)
    try:
        with locked(state / 'health-watchdog.lock', timeout=.1):
            deadline = time.monotonic() + duration
            while True:
                started = time.monotonic();tick(root)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(remaining, max(.1, interval - (time.monotonic() - started))))
    except TimeoutError:
        return
