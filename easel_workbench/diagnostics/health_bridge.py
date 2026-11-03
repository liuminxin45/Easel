"""Small operator port: reuse the existing deployment gates and recovery code.

Invoked by an independently installed controller through a verified frozen
runtime. Never expose this command on HTTP; its output contains a health token
for the caller's memory only. Business payloads and credentials are not output.
"""
from pathlib import Path
import json
import os
import re
import subprocess
import sys
import time

from easel_workbench import health_watchdog as watchdog
from easel_workbench.business_health import snapshot
from easel_workbench.diagnostics.usage import snapshot as usage_snapshot
from easel_workbench.diagnostics.content_library import snapshot as library_snapshot
from easel_workbench.processes import rows
from easel_workbench.runtime.feedback_ledger import atomic, atomic_create, locked


def _self_identity():
    from easel_workbench.runtime.scripts.windows_process_identity import ProcessIdentity
    with ProcessIdentity(os.getpid()) as handle:
        return {'pid': os.getpid(), 'creation_ticks': str(handle.creation_ticks)}


def task(root, *, start=False):
    """Start only the existing exact OS-owned manager, never a replacement task."""
    script = r'''
$ErrorActionPreference='Stop'
$r=[IO.Path]::GetFullPath($env:EASEL_HEALTH_APP_ROOT)
$t=Get-ScheduledTask -TaskName 'AINewsDesk'
$a=@($t.Actions)
$me=[Security.Principal.WindowsIdentity]::GetCurrent()
$users=@($me.Name,$me.Name.Split('\')[-1],$me.User.Value)
if($a.Count-ne 1 -or [IO.Path]::GetFullPath($a[0].Execute)-ne (Join-Path $r '.runtime/workbench-python/Scripts/pythonw.exe') -or
 $a[0].Arguments-ne ('"'+(Join-Path $r 'launcher.pyw')+'"') -or
 [IO.Path]::GetFullPath($a[0].WorkingDirectory)-ne $r -or
 $t.Principal.LogonType-ne 'Interactive' -or $t.Principal.UserId-notin $users -or !$t.Settings.Enabled){throw 'unverified_manager_task'}
if($env:EASEL_HEALTH_START-eq '1'){Start-ScheduledTask -TaskName 'AINewsDesk'}
ConvertTo-Json -Compress -InputObject @{verified=$true;started=($env:EASEL_HEALTH_START-eq '1')}
'''
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
        env={**os.environ, 'EASEL_HEALTH_APP_ROOT': str(root), 'EASEL_HEALTH_START': '1' if start else '0'},
        capture_output=True, text=True, timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise watchdog.GuardError('manager_task_unverified')
    return json.loads(result.stdout.lstrip('\ufeff'))['verified'] is True


def _operator_idle(root):
    # The historical audit deliberately distinguishes retained, proven inactive
    # unknowns from active/unresolved executions. Do not invent a second rule.
    sys.path.insert(0, str(root / 'scripts'))
    from activate_workbench import idle
    value = idle(root / 'data/desk.sqlite')
    return {'busy': value.get('busy') is not False,
        'unknown_receipts': value.get('busy') is not False,
        'retained_audited_unknown_count': len(value.get('retained_historical_unknown', [])) + len(value.get('retained_collection_unknown', []))}


def inspect(root):
    root = Path(root).resolve()
    binding = watchdog.controls(root)
    state = watchdog.read(root / watchdog.STATE_DIR / 'pids.json')
    if state.get('release') != binding['runtime']['release'] or state.get('paused') is not False:
        raise watchdog.GuardError('stale_role_snapshot')
    inventory = rows()
    result = {'schema': 1, 'app_present': True, 'binding': {
        **binding['runtime'], 'native_release': binding['native']['release'],
        'native_manifest_sha256': binding['native']['manifest_sha256']},
        'controls_valid': True, 'ownership_verified': True, **_operator_idle(root),
        'health_token': watchdog.health_token(root), 'ingress_origin': watchdog.ingress_origin(root),
        'business': snapshot(root), 'usage': usage_snapshot(root), 'content_library':library_snapshot(root),
        'server_member_pids': [], 'role_member_pids': []}
    now = time.time()
    for role in ('server', 'manager'):
        pid = state.get('manager') if role == 'manager' else state.get('roles', {}).get('server')
        row = inventory.get(pid)
        if row is None:
            result[role] = {'pid': None, 'creation_ticks': None, 'alive': False, 'age_seconds': 10**9}
        else:
            row = watchdog.role_row(inventory, pid, root, binding['runtime'], manager=role == 'manager')
            result[role] = {'pid': pid, 'creation_ticks': row['creation_ticks'], 'alive': True,
                'age_seconds': watchdog.process_age(row, now)}
            if role == 'server':
                result['server_member_pids'] = sorted(watchdog.process_members(inventory, pid))
        if role == 'manager':
            result[role]['heartbeat_age_seconds'] = max(0, now-state.get('heartbeat', 0))
    try:
        result['manager_task_verified'] = task(root)
    except (watchdog.GuardError, OSError, subprocess.SubprocessError):
        result['manager_task_verified'] = False
    members = set(result['server_member_pids'])
    for role, pid in state.get('roles', {}).items():
        if role not in ('worker', 'collector', 'publisher', 'feedback', 'learning', 'local') or pid not in inventory:
            continue
        # Reuse the original argument shape, varying only the validated role.
        from easel_workbench.processes import argv
        args = argv(inventory[pid].get('command') or '')
        if (len(args) == 7 and Path(args[1]).resolve() == root/'workbench-releases'/binding['runtime']['release']/'launch.py'
                and args[2] == role and args[3:5] == ['--root', str(root)] and args[5:] == ['--port', '9123']):
            members.update(watchdog.process_members(inventory, pid))
    result['role_member_pids'] = sorted(members)
    return result


def recover(root, request):
    root = Path(root).resolve()
    operation = request.get('operation_id')
    if (request.get('schema') != 1 or not isinstance(operation, str) or not re.fullmatch('[a-f0-9]{32}', operation)
            or request.get('action') not in ('recover_server', 'restart_manager')):
        raise watchdog.GuardError('invalid_recovery_request')
    path = root / watchdog.STATE_DIR / ('external-health-' + operation + '.json')
    with locked(root / watchdog.STATE_DIR / 'external-health-bridge.lock', timeout=.1):
        if path.exists():
            old = watchdog.read(path)
            if old.get('request') != request:
                raise watchdog.GuardError('operation_identity_changed')
            # An interrupted bridge is unknown. Never repeat a termination.
            return {key: request[key] for key in ('operation_id', 'action', 'binding')} | {'outcome': 'deferred'}
        current = inspect(root)
        if current['binding'] != request.get('binding') or current['busy'] or current['unknown_receipts']:
            raise watchdog.GuardError('binding_or_idle_changed')
        selected = current['manager' if request['action'] == 'restart_manager' else 'server']
        if {key: selected[key] for key in ('pid', 'creation_ticks')} != request.get('expected_identity'):
            raise watchdog.GuardError('recovery_process_identity_changed')
        reply = {key: request[key] for key in ('operation_id', 'action', 'binding')}
        executor = _self_identity()
        if not atomic_create(path, {'schema': 1, 'request': request, 'phase': 'attempted', 'executor': executor}):
            raise watchdog.GuardError('recovery_operation_already_exists')
        mutation_entry = None
        try:
            try:
                watchdog.operator_gates(root)
            except (ValueError, TimeoutError) as error:
                raise watchdog.GuardError('business_queue_not_idle') from error
            bound = watchdog.controls(root)
            if not selected['alive']:
                if request['action'] != 'restart_manager' or not current['manager_task_verified']:
                    raise watchdog.GuardError('missing_server_wait_for_manager')
                # Recheck immediately before asking the OS task. The existing
                # manager OS lock handles a concurrent scheduler start safely.
                latest = inspect(root)
                if latest['binding'] != current['binding'] or latest['busy'] or latest['unknown_receipts']:
                    outcome = 'deferred'
                elif latest['manager']['alive']:
                    outcome = 'already_healthy'
                else:
                    mutation_entry = 'task'
                    task(root, start=True)
                    outcome = 'manager_restart_requested'
            else:
                policy_path = root / watchdog.STATE_DIR / 'health-policy.json'
                previous = watchdog.read(policy_path) if policy_path.exists() else {}
                target = ':'.join([bound['runtime']['release'], bound['runtime']['manifest_sha256'],
                    request['action'], str(selected['pid']), selected['creation_ticks']])
                policy = watchdog.assess(previous, {'target': target, 'local_ok': False,
                    'ingress_ok': None, 'age_seconds': selected['age_seconds'], 'eligible': True}, time.time(), threshold=1)
                if policy.get('action') != 'recover':
                    outcome = 'deferred'
                else:
                    status = watchdog.read(root / watchdog.STATE_DIR / 'pids.json')
                    if request['action'] == 'restart_manager':
                        mutation_entry = 'manager'
                        _, outcome = watchdog.recover_manager(root, bound, selected, policy)
                    else:
                        mutation_entry = 'server'
                        _, outcome = watchdog.recover_server(root, bound, status, selected, policy, current['health_token'])
                    if outcome.endswith('without_restart'):
                        outcome = 'already_healthy'
            reply['outcome'] = outcome
            atomic(path, {'schema': 1, 'request': request, 'phase': 'completed', 'outcome': outcome, 'executor': executor})
            return reply
        except watchdog.GuardError:
            # A proven pre-termination guard failure is a deferral, not an
            # ambiguous kill. Keep the consumed budget; never repeat this op.
            journal_path = root/watchdog.STATE_DIR/'health-recovery.json'
            journal = watchdog.read(journal_path) if journal_path.exists() else {}
            uncertain = mutation_entry in ('task', 'manager') or (journal.get('watchdog_pid') == executor['pid']
                and journal.get('watchdog_creation_ticks') == executor['creation_ticks']
                and journal.get('phase') in ('stopping', 'stopped'))
            if uncertain:
                atomic(path, {'schema': 1, 'request': request, 'phase': 'unknown', 'executor': executor})
                raise
            atomic(path, {'schema': 1, 'request': request, 'phase': 'completed', 'outcome': 'deferred', 'executor': executor})
            return {**reply, 'outcome': 'deferred'}
        except BaseException:
            atomic(path, {'schema': 1, 'request': request, 'phase': 'unknown', 'executor': executor})
            raise


def reconcile(root, request):
    """Release only this proven-dead bridge's abandoned fence; never repeat kill."""
    root = Path(root).resolve(); state = root/watchdog.STATE_DIR
    operation = request.get('operation_id', '')
    if not isinstance(operation, str) or not re.fullmatch('[a-f0-9]{32}', operation):
        raise watchdog.GuardError('invalid_reconciliation_identity')
    record = watchdog.read(state/('external-health-'+operation+'.json'))
    if record.get('request') != request:
        raise watchdog.GuardError('reconciliation_request_changed')
    if record.get('phase') == 'completed' and record.get('outcome') in (
            'server_restart_requested', 'manager_restart_requested', 'already_healthy', 'deferred'):
        return {key: request[key] for key in ('operation_id', 'action', 'binding')} | {
            'status': 'receipt_confirmed', 'outcome': record['outcome']}
    executor = record.get('executor', {})
    current = rows().get(executor.get('pid'))
    if current and int(current['creation_ticks'])//10 == int(executor['creation_ticks'])//10:
        return {'status': 'executor_still_alive'}
    if not (state/'paused').exists():
        return {'status': 'fence_absent'}
    journal = watchdog.read(state/'health-recovery.json')
    if (journal.get('watchdog_pid') != executor.get('pid')
            or int(journal.get('watchdog_creation_ticks', 0)) != int(executor.get('creation_ticks', -1))):
        raise watchdog.GuardError('foreign_recovery_fence')
    bound = journal.get('binding', {})
    flat = {**bound.get('runtime', {}), 'native_release': bound.get('native', {}).get('release'),
            'native_manifest_sha256': bound.get('native', {}).get('manifest_sha256')}
    if flat != request.get('binding'):
        raise watchdog.GuardError('reconciliation_binding_changed')
    watchdog.resume_fence(root)
    return {'status': 'owned_abandoned_fence_reconciled'}


def main(root, action):
    if action == 'inspect':
        result = inspect(root)
    elif action in ('recover', 'reconcile'):
        raw = sys.stdin.buffer.read(16385)
        if len(raw) > 16384:
            raise watchdog.GuardError('oversized_recovery_request')
        result = (recover if action == 'recover' else reconcile)(root, json.loads(raw))
    else:
        raise watchdog.GuardError('unknown_bridge_action')
    print(json.dumps(result, ensure_ascii=True, separators=(',', ':')))
