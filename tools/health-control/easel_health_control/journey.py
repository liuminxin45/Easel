"""Daily isolated browser acceptance, separate from native Agent canaries.

Launching is journaled before Popen. A lost launch or receipt is inspected, never
silently repeated. The OS monitor remains responsive while the child runs.
"""
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import time

from .state import StateStore


class JourneyDeferred(ValueError):
    """Preflight proved that no browser subprocess has started."""


def _document(path):
    raw=Path(path).read_bytes()
    if len(raw)>4*1024*1024:raise ValueError('oversized_journey_document')
    value=json.loads(raw)
    if not isinstance(value,dict):raise ValueError('invalid_journey_document')
    return value,hashlib.sha256(raw).hexdigest()


def _gate(app):
    state=app/'.local/workbench-deployment'
    try:
        if (state/'paused').exists() or (state/'paused').is_symlink():raise JourneyDeferred('application_transition')
        admission,admission_sha=_document(state/'admission.json')
        cutover,cutover_sha=_document(state/'cutover.json')
        if (admission.get('workers') is not True or cutover.get('phase')!='live'
                or Path(cutover.get('target_root','')).resolve()!=app):
            raise JourneyDeferred('application_transition')
        return admission_sha,cutover_sha,cutover
    except (OSError,ValueError) as error:
        if isinstance(error,JourneyDeferred):raise
        raise JourneyDeferred('application_admission_unavailable') from error


def selected(config):
    app = Path(config['app_root']).resolve()
    first_gate=_gate(app)
    runtime,runtime_sha = _document(app/'data/active-workbench.json')
    native,native_sha = _document(app/'data/active-native.json')
    for value, prefix in ((runtime, 'workbench'), (native, 'native')):
        if (not re.fullmatch(prefix+r'-[A-Za-z0-9_-]{1,80}', str(value.get('release', '')))
                or not re.fullmatch('[a-f0-9]{64}', str(value.get('manifest_sha256', '')))):
            raise ValueError('invalid_journey_binding')
    manifest,manifest_sha=_document(app/'workbench-releases'/runtime['release']/'workbench-release.json')
    if manifest_sha!=runtime['manifest_sha256']:raise ValueError('journey_backend_manifest_changed')
    if manifest.get('native')!=native:raise JourneyDeferred('selected_pair_mismatch')
    if 'easel_workbench/diagnostics/session_journey.py' not in manifest.get('files',{}):
        raise JourneyDeferred('selected_runtime_has_no_browser_journey')
    if first_gate!=_gate(app) or _document(app/'data/active-workbench.json')[1]!=runtime_sha or _document(app/'data/active-native.json')[1]!=native_sha:
        raise JourneyDeferred('application_selection_changed')
    return {'runtime': runtime, 'native': native}


def _success_evidence(operation,receipt):
    workspace=Path(operation['workspace']).resolve();path=workspace/'evidence/report.json'
    if path.is_symlink() or not path.resolve().is_relative_to(workspace):raise ValueError('linked_journey_evidence')
    report,digest=_document(path)
    if (not re.fullmatch('[a-f0-9]{64}',str(receipt.get('report_sha256',''))) or digest!=receipt['report_sha256']
            or report.get('binding')!=operation['binding'] or report.get('passed') is not True
            or report.get('real_model_calls')!=0 or report.get('production_data_access') is not False
            or not isinstance(report.get('checks'),list) or not report['checks']
            or not all(isinstance(row,dict) and row.get('passed') is True for row in report['checks'])
            or len(report['checks'])!=receipt.get('checks')):
        raise ValueError('unverified_journey_evidence')


def observe(operation, *, clock=time.time):
    path = Path(operation['workspace'])/'receipt.json'
    try:
        receipt = StateStore(path.parent).read(path.name)
    except (OSError, ValueError):
        receipt = None
    if receipt is not None:
        if (receipt.get('operation_id') == operation['operation_id']
                and receipt.get('binding') == operation['binding']
                and receipt.get('status') in ('completed', 'failed', 'deferred')
                and receipt.get('real_model_calls') == 0
                and receipt.get('production_data_access') is False):
            if receipt['status']=='completed':
                try:_success_evidence(operation,receipt)
                except (OSError,ValueError):
                    return {**operation,'status':'unknown','reason':'journey_success_evidence_unverified'}
            if receipt['status']=='deferred' and not (receipt.get('preflight_confirmed_not_started') is True and receipt.get('child_started') is False):
                return {**operation,'status':'unknown','reason':'journey_deferred_not_proven'}
            return {**operation, **receipt, 'worker_receipt_confirmed': True}
        return {**operation, 'status': 'unknown', 'reason': 'journey_receipt_identity_changed'}
    if clock()-operation.get('launch_at', 0) > operation.get('timeout_seconds', 240)+60:
        return {**operation, 'status': 'unknown', 'reason': 'journey_receipt_missing'}
    return {**operation, 'status': 'running'}


def scheduled_tick(config, store, *, clock=time.time, spawn=subprocess.Popen):
    if config.get('daily_browser_journey_enabled', True) is not True:
        value = {'schema': 1, 'at': clock(), 'status': 'disabled', 'real_model_calls': 0, 'production_data_access': False}
        store.write('journey-status.json', value)
        return value
    app = Path(config['app_root']).resolve()
    root = store.root/'browser-journey'
    if root == app or root.is_relative_to(app):
        raise ValueError('journey_runtime_must_be_external')
    state = StateStore(root)
    day = dt.datetime.fromtimestamp(clock(), dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    with state.lock():
        old = state.read('operation.json')
        retained_days=sorted(path.name for path in root.iterdir() if path.is_dir() and re.fullmatch(r'\d{4}-\d{2}-\d{2}',path.name))
        if (old and str(old.get('day',''))>day) or retained_days and retained_days[-1]>day:
            value={'schema':1,'status':'blocked','reason':'browser_journey_clock_rollback','day':day,
                   'real_model_calls':0,'production_data_access':False}
            store.write('journey-status.json',{'at':clock(),**value});return value
        if old is None and (root/day).exists():
            original=StateStore(root/day).read('request.json')
            if (not original or original.get('day')!=day or original.get('launch_attempted') is not True
                    or Path(original.get('workspace','')).resolve()!=(root/day).resolve()
                    or not re.fullmatch(r'journey-\d{8}-[a-f0-9]{16}',str(original.get('operation_id','')))):
                value={'schema':1,'status':'unknown','reason':'daily_browser_identity_missing','day':day,
                       'real_model_calls':0,'production_data_access':False}
                store.write('journey-status.json',{'at':clock(),**value});return value
            old=original
        if old and old.get('launch_attempted'):
            old = observe(old, clock=clock)
            state.write('operation.json', old)
        if old and old.get('day') == day:
            value = old
        elif old and old.get('status') not in ('completed', 'failed', 'deferred'):
            value = {**old, 'status': 'blocked', 'reason': 'previous_browser_journey_unresolved'}
        else:
            try:binding = selected(config)
            except JourneyDeferred as error:
                value={'schema':1,'status':'deferred','reason':str(error),'day':day,'launch_attempted':False,
                       'preflight_confirmed_not_started':True,'child_started':False,'real_model_calls':0,'production_data_access':False}
                store.write('journey-status.json',{'at':clock(),**value});return value
            identity = 'journey-'+day.replace('-', '')+'-'+secrets.token_hex(8)
            workspace = root/day
            workspace.mkdir(parents=True, exist_ok=False)
            operation = {'schema': 1, 'operation_id': identity, 'day': day, 'binding': binding,
                'app_root': str(app), 'workspace': str(workspace), 'status': 'launching',
                'launch_attempted': True, 'launch_at': clock(), 'real_model_calls': 0,
                'production_data_access': False,
                'timeout_seconds': max(60, min(300, int(config.get('browser_journey_timeout_seconds', 240))))}
            StateStore(workspace).write('request.json', operation)
            state.write('operation.json', operation)
            command = [str(app/'.runtime/workbench-python/Scripts/python.exe'), '-I',
                str(Path(__file__).with_name('journey_entry.py')), str(workspace/'request.json')]
            try:
                process = spawn(command, cwd=workspace, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL, env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'},
                    creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                value = {**operation, 'status': 'running', 'worker_pid': process.pid}
            except (OSError, ValueError):
                value = {**operation, 'status': 'unknown', 'reason': 'browser_journey_launch_unconfirmed'}
            state.write('operation.json', value)
    if value.get('status')=='completed':
        try:
            if selected(config)!=value['binding']:
                value={**value,'status':'stale_binding','tested_status':'completed','reason':'selected_pair_changed','binding_matches_current':False}
            else:value={**value,'binding_matches_current':True}
        except (OSError,ValueError):
            value={**value,'status':'stale_binding','tested_status':'completed','reason':'current_pair_not_verified','binding_matches_current':False}
    report = {'schema': 1, 'at': clock(), **value}
    store.write('journey-status.json', report)
    return report
