"""One durable daily native-agent canary; never automatically repeat an unknown send."""
import datetime as dt
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time

from .state import StateStore


def run_daily(config, runtime_root, *, execute=False, clock=time.time, runner=subprocess.run):
    root=Path(runtime_root).resolve();application=Path(config['application_root']).resolve()
    if root==application or root.is_relative_to(application):raise ValueError('canary_runtime_must_be_external')
    directory=root/'canary';state=StateStore(directory)
    day=dt.datetime.fromtimestamp(clock(),dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    with state.lock():
        old=state.read('operation.json')
        if old and old.get('day')!=day and old.get('status') in ('dispatching','launching','unknown','running'):
            inspect=inspect_operation(old,config,runner)
            if inspect.get('status') in ('completed','failed','blocked'):old.update(inspect);state.write('operation.json',old)
            else:return {**old,'status':'blocked','reason':'previous_native_receipt_unresolved'}
        old=state.read('operation.json')
        if old and old.get('day')==day and (old.get('dispatch_started') or old.get('worker_uncertain') or old.get('status')=='launching'):
            observed=inspect_operation(old,config,runner)
            value={**old,**observed};state.write('operation.json',value);return value
        operation=old if old and old.get('day')==day else {
            'schema':1,'day':day,'operation_id':'health-'+day.replace('-','')+'-'+secrets.token_hex(8),
            'application_root':str(application),'workspace':str(directory/day),'status':'prepared','dispatch_started':False}
        if execute and operation.get('worker_launch_count',0)>=3:
            return {**operation,'status':'blocked','reason':'daily_preflight_attempt_limit'}
        if execute and operation.get('worker_launch_attempted') and not (operation.get('preflight_confirmed_unsent') and operation.get('worker_exited')):
            return {**operation,'status':'unknown','reason':'worker_outcome_not_confirmed_unsent'}
        for field in ('reason','error_type','error_frames'):
            operation.pop(field,None)
        workspace=Path(operation['workspace']);workspace.mkdir(parents=True,exist_ok=True)
        request={**operation,'execute':execute,'timeout_seconds':int(config.get('canary_timeout_seconds',900))}
        request_path=workspace/'request.json';StateStore(workspace).write('request.json',request)
        operation.update(status='launching',worker_launch_attempted=True,worker_exited=False,
                         worker_launch_count=operation.get('worker_launch_count',0)+(1 if execute else 0),last_launch_at=clock())
        state.write('operation.json',operation)  # Launch uncertainty is durable before the child starts.
        command=[str(application/'.runtime/workbench-python/Scripts/python.exe'),'-I',str(Path(__file__).with_name('canary_entry.py')),str(request_path)]
        try:
            result=runner(command,capture_output=True,text=True,encoding='utf-8',timeout=request['timeout_seconds']+180,
                          creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
            receipt=json.loads((workspace/'receipt.json').read_text(encoding='utf-8'))
            if receipt.get('operation_id')!=operation['operation_id']:raise ValueError('receipt_identity_changed')
            operation.update(receipt,worker_exited=True,worker_uncertain=False)
            operation['dispatch_started']=bool(receipt.get('native_intent_saved') or (workspace/'native-intent.json').exists() or receipt.get('status')=='completed')
            operation['preflight_confirmed_unsent']=bool(receipt.get('preflight_confirmed_unsent') and not operation['dispatch_started'])
        except (OSError,ValueError,subprocess.TimeoutExpired):
            operation.update(status='unknown',worker_uncertain=True,reason='canary_worker_receipt_unavailable')
        state.write('operation.json',operation)
        StateStore(workspace).write('controller-result.json',operation)
        return operation


def inspect_operation(operation,config,runner=subprocess.run):
    workspace=Path(operation['workspace'])
    # Inspection launches no native adapter and never invokes a production API.
    command=[str(Path(config['application_root'])/'.runtime/workbench-python/Scripts/python.exe'),'-I',str(Path(__file__).with_name('canary_entry.py')),str(workspace/'request.json'),'--inspect']
    try:
        result=runner(command,capture_output=True,text=True,encoding='utf-8',timeout=30,
                      creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
        value=json.loads(result.stdout)
        if value.get('operation_id')!=operation['operation_id']:raise ValueError('receipt_identity_changed')
        return value
    except (OSError,ValueError,subprocess.TimeoutExpired):return {'status':'unknown','reason':'original_receipt_not_confirmed'}


def scheduled_run(config,store):
    translated={'application_root':config['app_root'],'python_executable':config.get('python_executable',sys.executable),
                'canary_timeout_seconds':config.get('canary_timeout_seconds',900)}
    result=run_daily(translated,store.root,execute=config.get('daily_real_agent_authorized') is True)
    report={'schema':1,'at':time.time(),'daily_real_agent_authorized':config.get('daily_real_agent_authorized') is True,**result}
    store.write('daily-status.json',report)
    return report
