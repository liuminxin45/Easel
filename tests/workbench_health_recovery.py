"""Explicit real Windows hang + watchdog-loss acceptance, with exact handles.

Only --exercise suspends an idle server's checked process. Finally resumes that
same handle on failure. No model, publication, adoption or unknown replay.
"""
from pathlib import Path
import argparse
import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts')]
from easel_workbench.health_endpoint import HEALTH_PATH, health_token
from easel_workbench.health_watchdog import controls, request_health, operator_gates, process_age, role_row, process_members, resume_fence
from easel_workbench.processes import rows, argv, checked_identity
from easel_workbench.runtime.feedback_ledger import atomic, locked
from easel_workbench.runtime.scripts.windows_process_identity import ProcessIdentity, kernel

read = lambda p: json.loads(Path(p).read_text(encoding='utf-8-sig'))
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
STATE = ROOT / '.local/workbench-deployment'
ROLES = {'server', 'worker', 'publisher', 'feedback', 'collector', 'learning', 'local'}


class Suspended:
    def __init__(self, row):
        self.identity = checked_identity(row)
        self.handle = kernel.OpenProcess(0x0800 | 0x1000 | 0x100000, False, row['pid'])
        if not self.handle:
            self.identity.close();raise ctypes.WinError(ctypes.get_last_error())
        self.nt = ctypes.WinDLL('ntdll')
        self.nt.NtSuspendProcess.argtypes = [wintypes.HANDLE];self.nt.NtSuspendProcess.restype = wintypes.LONG
        self.nt.NtResumeProcess.argtypes = [wintypes.HANDLE];self.nt.NtResumeProcess.restype = wintypes.LONG
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(self.handle, *(ctypes.byref(t) for t in times)):
            self.close();raise ctypes.WinError(ctypes.get_last_error())
        actual = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        if actual != self.identity.creation_ticks:
            self.close();raise ValueError('Suspension identity changed')
        self.suspended = False

    def suspend(self):
        assert not self.identity.exited()
        status = self.nt.NtSuspendProcess(self.handle)
        if status < 0:
            raise OSError('Exact process suspension failed')
        self.suspended = True

    def close(self):
        try:
            if getattr(self, 'suspended', False) and not self.identity.exited():
                if self.nt.NtResumeProcess(self.handle) < 0:
                    raise OSError('Original server could not be resumed')
        finally:
            if self.handle:
                kernel.CloseHandle(self.handle);self.handle = None
            self.identity.close()


def cleanup_file(path):
    """Out-of-process fallback if the test runner was killed before finally."""
    value = read(path);assert value['root'] == str(ROOT)
    errors = []
    try:
        if value.get('server'):
            expected = value['server'];row = rows().get(expected['pid'])
            if row is not None:
                role_row({row['pid']: row}, row['pid'], ROOT, value['binding']['runtime'])
                with ProcessIdentity(row['pid'], expected_creation_ticks=int(expected['creation_ticks'])):
                    process = Suspended(row);process.suspended = True;process.close()
    except Exception as error:errors.append('resume:' + type(error).__name__)
    try:
        with locked(STATE / 'health-watchdog.lock', timeout=.1):resume_fence(ROOT)
    except TimeoutError:pass  # An actual live watchdog owns and will finish its fence.
    except Exception as error:errors.append('fence:' + type(error).__name__)
    try:
        target = ROOT / 'data/automation-enabled.json';original = base64.b64decode(value['automatic_original_base64'])
        assert hashlib.sha256(original).hexdigest() == value['automatic_original_sha256']
        current = sha(target)
        if current == value['automatic_paused_sha256']:
            tmp = target.with_suffix('.health-test.recover');tmp.write_bytes(original);os.replace(tmp, target)
        elif current != value['automatic_original_sha256']:
            raise ValueError('Maintenance configuration changed')
    except Exception as error:errors.append('configuration:' + type(error).__name__)
    atomic(path, {**value, 'cleanup_complete': not errors, 'cleanup_errors': errors})
    if errors:raise RuntimeError('Cleanup incomplete: ' + ','.join(errors))


def configuration():
    raw = subprocess.check_output(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); Export-ScheduledTask -TaskName AINewsDeskHealth"], text=True, encoding='utf-8').lstrip('\ufeff')
    doc = ET.fromstring(raw);ns = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
    text = lambda name: doc.findtext(name, namespaces=ns)
    assert text('t:Actions/t:Exec/t:Command') == str(ROOT / '.runtime/workbench-python/Scripts/pythonw.exe')
    assert text('t:Actions/t:Exec/t:Arguments') == '"' + str(ROOT / 'health_launcher.pyw') + '"'
    assert text('t:Actions/t:Exec/t:WorkingDirectory') == str(ROOT)
    assert text('t:Principals/t:Principal/t:LogonType') == 'InteractiveToken'
    assert text('t:Settings/t:ExecutionTimeLimit') == 'PT2M'
    assert text('t:Settings/t:MultipleInstancesPolicy') == 'IgnoreNew'
    assert text('t:Settings/t:DisallowStartIfOnBatteries') == 'false'
    assert text('t:Settings/t:StopIfGoingOnBatteries') == 'false'
    assert text('t:Triggers/t:TimeTrigger/t:Repetition/t:Interval') == 'PT1M'
    assert not text('t:Triggers/t:TimeTrigger/t:Repetition/t:Duration')
    return {'interval': 'PT1M', 'job_hard_limit': 'PT2M', 'overlap': 'IgnoreNew', 'logon': 'existing-owner'}


def originals():
    result = {'cache': {p.name: sha(p) for p in (ROOT / 'data/collection/model-cache').glob('*.json')
                        if read(p).get('status') in ('requested', 'uncertain')}}
    with sqlite3.connect((ROOT / 'data/desk.sqlite').as_uri() + '?mode=ro', uri=True) as c:
        row = c.execute('SELECT document FROM easel_chat_turns WHERE id=?', ('b2ef839a-9640-4190-9e5e-3a0053187bfc',)).fetchone()
        result['original_turn_sha256'] = hashlib.sha256(row[0].encode()).hexdigest()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exercise', action='store_true');parser.add_argument('--output', type=Path)
    parser.add_argument('--recover-cleanup', type=Path)
    args = parser.parse_args()
    if args.recover_cleanup:
        cleanup_file(args.recover_cleanup);print(json.dumps({'passed': True, 'cleanup': 'completed'}));return
    assert args.output is not None
    report = {'passed': False, 'configuration': configuration()}
    token = health_token(ROOT);binding = controls(ROOT);release = binding['runtime']['release']
    probe = lambda: request_health('http://127.0.0.1:9123' + HEALTH_PATH, token, release, timeout=2)
    selectors = {name: (ROOT / name).read_bytes() for name in ('data/active-workbench.json', 'data/active-native.json')}
    report['originals_before'] = originals();report['binding'] = binding
    before = read(STATE / 'pids.json');assert set(before['roles']) == ROLES
    before_health = probe();assert before_health['ok'];report['before'] = before
    held = {};suspended = None;auto_path = ROOT / 'data/automation-enabled.json';auto_original = None;auto_paused = None
    cleanup_path = args.output.with_name(args.output.stem + '-cleanup.json');cleanup = None
    try:
        if args.exercise:
            # Existing operator pause drains optional AI enrichment, not business
            # receipts. No existing invocation is interrupted or replayed.
            auto_original = auto_path.read_bytes();value = json.loads(auto_original)
            assert value.get('cutover_paused') is False
            value['cutover_paused'] = True;auto_paused = json.dumps(value, indent=2).encode()
            cleanup = {'root': str(ROOT), 'binding': binding, 'cleanup_complete': False,
                       'automatic_original_base64': base64.b64encode(auto_original).decode(),
                       'automatic_original_sha256': hashlib.sha256(auto_original).hexdigest(),
                       'automatic_paused_sha256': hashlib.sha256(auto_paused).hexdigest()}
            atomic(cleanup_path, cleanup)
            temporary = auto_path.with_suffix('.health-test.tmp');temporary.write_bytes(auto_paused);os.replace(temporary, auto_path)
            deadline = time.monotonic() + 360
            while True:
                try:operator_gates(ROOT);break
                except Exception:
                    if time.monotonic() >= deadline:raise
                    time.sleep(3)
            # Do not force a premature cold-start recovery; leave UI responsive
            # during the real startup grace before injecting the hang.
            while True:
                before = read(STATE / 'pids.json');before_health = probe();assert before_health['ok']
                inventory = rows()
                role_row(inventory, before['roles']['server'], ROOT, binding['runtime'])
                assert before_health['pid'] in process_members(inventory, before['roles']['server'])
                actual = role_row(inventory, before_health['pid'], ROOT, binding['runtime'])
                if process_age(actual, time.time()) >= 95:break
                time.sleep(2)
            operator_gates(ROOT)
            before = read(STATE / 'pids.json');before_health = probe();assert before_health['ok']
            inventory = rows();assert set(before['roles']) == ROLES
            role_row(inventory, before['roles']['server'], ROOT, binding['runtime'])
            assert before_health['pid'] in process_members(inventory, before['roles']['server'])
            actual = role_row(inventory, before_health['pid'], ROOT, binding['runtime'])
            for role, pid in before['roles'].items():held[role] = checked_identity(inventory[pid])
            role_row(inventory, before['manager'], ROOT, binding['runtime'], manager=True)
            held['manager'] = checked_identity(inventory[before['manager']])
            suspended = Suspended(actual)
            assert probe().get('pid') == actual['pid']
            assert read(STATE / 'pids.json')['roles'] == before['roles']
            cleanup['server'] = {'pid': actual['pid'], 'creation_ticks': str(suspended.identity.creation_ticks)}
            atomic(cleanup_path, cleanup)
            report['before'] = before;suspended.suspend();started = time.monotonic()
            report['suspended_pid'] = actual['pid'];interrupted_watchdog = None;probes = []
            deadline = time.monotonic() + 360
            while time.monotonic() < deadline:
                assert all(not handle.exited() for role, handle in held.items() if role != 'server'), 'Another business role exited'
                current = read(STATE / 'pids.json')
                if interrupted_watchdog is None and (STATE / 'paused').exists() and (STATE / 'health-recovery.json').exists():
                    journal = read(STATE / 'health-recovery.json');marker = read(STATE / 'paused')
                    if journal.get('phase') in ('prepared', 'stopping', 'stopped') and marker.get('operation_id') == journal.get('operation_id'):
                        row = rows().get(journal.get('watchdog_pid'))
                        if row and Path(argv(row['command'])[1]).resolve() == ROOT / 'health_launcher.pyw':
                            with checked_identity(row) as handle:
                                latest = read(STATE / 'health-recovery.json')
                                latest_marker = read(STATE / 'paused') if (STATE / 'paused').exists() else {}
                                if (not handle.exited() and str(handle.creation_ticks) == journal.get('watchdog_creation_ticks')
                                        and latest.get('phase') in ('prepared', 'stopping', 'stopped')
                                        and latest.get('operation_id') == journal['operation_id']
                                        and latest_marker.get('operation_id') == journal['operation_id']):
                                    handle.terminate(expected_creation_ticks=handle.creation_ticks)
                                    assert (STATE / 'paused').exists() and read(STATE / 'paused').get('operation_id') == journal['operation_id']
                                    interrupted_watchdog = {'pid': row['pid'], 'operation_id': journal['operation_id'],
                                                            'observed_phase_before_termination': latest['phase'],
                                                            'owned_pause_remained_after_exit': True}
                                    report['watchdog_killed_inside_owned_fence'] = interrupted_watchdog
                health = probe();probes.append({'at': round(time.monotonic() - started, 2), 'ok': health['ok']})
                if current['roles'].get('server') != before['roles']['server'] and health['ok']:
                    assert current['manager'] == before['manager'], 'Server recovery must retain manager'
                    assert all(current['roles'][role] == pid for role, pid in before['roles'].items() if role != 'server')
                    assert held['server'].exited() and suspended.identity.exited()
                    assert interrupted_watchdog is not None, 'Owned-fence watchdog-loss exercise was not observed'
                    events = [json.loads(line) for line in (STATE / 'health-events.jsonl').read_text().splitlines()]
                    assert any(e['kind'] == 'abandoned_fence_released' and e.get('operation_id') == interrupted_watchdog['operation_id'] for e in events)
                    status = read(STATE / 'health-status.json')
                    assert status['watchdog_pid'] != interrupted_watchdog['pid']
                    assert not (STATE / 'paused').exists()
                    report.update(after=current, hang_recovery_seconds=round(time.monotonic() - started, 2),
                                  watchdog_after=status['watchdog_pid'], probes=probes,
                                  policy_budget=read(STATE / 'health-policy.json')['attempts'])
                    break
                time.sleep(.5)
            else:raise AssertionError('Independent OS health task did not restore the hung server after its own interruption')
        assert controls(ROOT) == binding
        for name, raw in selectors.items():assert (ROOT / name).read_bytes() == raw
        assert originals() == report['originals_before']
        report.update(passed=True, selectors_unchanged=True, originals_preserved=True, business_POSTs=0, new_model_turns=0)
    finally:
        original_error = sys.exc_info()[1];cleanup_errors = []
        try:
            if suspended is not None:suspended.close()
        except Exception as error:cleanup_errors.append('resume:' + type(error).__name__)
        for handle in held.values():
            try:handle.close()
            except Exception as error:cleanup_errors.append('handle:' + type(error).__name__)
        if cleanup is not None:
            try:cleanup_file(cleanup_path)
            except Exception as error:cleanup_errors.append('persistent_cleanup:' + type(error).__name__)
            else:report['automatic_configuration_restored_sha256'] = sha(auto_path)
        if cleanup_errors:report.update(passed=False, cleanup_errors=cleanup_errors)
        args.output.parent.mkdir(parents=True, exist_ok=True);args.output.write_text(json.dumps(report, indent=2), encoding='utf-8')
        if cleanup_errors and original_error is None:
            raise RuntimeError('Fault exercise cleanup failed: ' + ','.join(cleanup_errors))
    print(json.dumps(report))


if __name__ == '__main__':main()
