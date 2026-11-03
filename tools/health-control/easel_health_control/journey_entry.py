"""App-Python child: verify immutable members, run TEMP browser checks, receipt."""
from pathlib import Path
import hashlib
import json
import os
import re
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from easel_health_control.state import StateStore
from easel_health_control.journey import JourneyDeferred,selected
from easel_health_control.process_tree import run_contained


def package(directory, filename, expected):
    directory = Path(directory).resolve()
    raw = (directory/filename).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('journey_manifest_changed')
    value = json.loads(raw)
    for name, digest in value['files'].items():
        raw_member = directory/name
        member = raw_member.resolve()
        if (not member.is_relative_to(directory) or raw_member.is_symlink()
                or hashlib.sha256(member.read_bytes()).hexdigest() != digest):
            raise ValueError('journey_member_changed')
    return value


def execute(request,*,runner=run_contained):
    workspace = Path(request['workspace']).resolve()
    app = Path(request['app_root']).resolve()
    if workspace == app or workspace.is_relative_to(app):
        raise ValueError('journey_workspace_must_be_external')
    binding = request['binding']
    if selected({'app_root':str(app)})!=binding:
        raise JourneyDeferred('application_selection_changed')
    for value, prefix in ((binding['runtime'], 'workbench'), (binding['native'], 'native')):
        if not re.fullmatch(prefix+r'-[A-Za-z0-9_-]{1,80}', str(value['release'])):
            raise ValueError('invalid_journey_release')
    backend = app/'workbench-releases'/binding['runtime']['release']
    native = app/'native-releases'/binding['native']['release']
    runtime_manifest=package(backend, 'workbench-release.json', binding['runtime']['manifest_sha256'])
    if runtime_manifest.get('native')!=binding['native']:
        raise JourneyDeferred('selected_pair_mismatch')
    package(native, 'native-manifest.json', binding['native']['manifest_sha256'])
    # The app module is the same frozen harness used by deployment acceptance;
    # neither the independent process nor this bootstrap imports production data.
    command = [sys.executable, '-I', str(backend/'easel_workbench/diagnostics/session_journey.py'),
        '--backend', str(backend), '--native', str(native), '--out', str(workspace/'evidence'), '--mode', 'daily']
    environment = {key: value for key, value in os.environ.items()
                   if key not in {'AI_DESK_RELEASE', 'AI_DESK_PROJECT_ROOT', 'EASEL_WORKBENCH_ADMISSION', 'EASEL_ROOT'}}
    if selected({'app_root':str(app)})!=binding:
        raise JourneyDeferred('application_selection_changed')
    result = runner(command, cwd=workspace, timeout=request['timeout_seconds'],
        env={**environment, 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'})
    report = StateStore(workspace/'evidence').read('report.json')
    if (result.returncode or not report or report.get('passed') is not True
            or report.get('real_model_calls') != 0 or report.get('production_data_access') is not False
            or report.get('binding') != binding):
        raise ValueError('browser_journey_failed')
    return {'status': 'completed', 'checks': len(report['checks']), 'child_started':True,
        'report_sha256': hashlib.sha256((workspace/'evidence/report.json').read_bytes()).hexdigest()}


def main():
    request = json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
    store = StateStore(request['workspace'])
    value = {'schema': 1, 'operation_id': request['operation_id'], 'binding': request['binding'],
        'real_model_calls': 0, 'production_data_access': False, 'at': time.time()}
    try:
        value.update(execute(request))
    except JourneyDeferred as error:
        value.update(status='deferred',reason=str(error),child_started=False,preflight_confirmed_not_started=True)
    except BaseException as error:
        # Never copy raw HTTP, stdout, stderr, exception strings or credentials.
        value.update(status='failed', reason='browser_journey_failed', error_type=type(error).__name__,child_started=True)
    store.write('receipt.json', value)
    return 0 if value['status'] == 'completed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
