"""Bounded IPC and nonce-bound HTTP; no application package imports."""
from pathlib import Path
import json
import math
import os
import secrets
import subprocess
import time
import urllib.request


class BridgeUnavailable(RuntimeError):
    pass


def performance(value):
    if not isinstance(value, dict):
        return {'status': 'unavailable'}
    rows = value.get('recent', [])
    if not isinstance(rows, list):
        return {'status': 'unavailable'}
    now = time.time()
    rows = [item for item in rows[-32:] if isinstance(item, dict) and type(item.get('at')) in (int,float) and 0 <= now-item['at'] < 300]
    def numeric(item, key):
        v = item.get(key, 0)
        return v if type(v) in (int, float) and math.isfinite(v) and 0 <= v <= 2**53 else 0
    result = {'slow_count': sum(numeric(v, 'duration_ms') > 2000 for v in rows),
        'db_copy_bytes': sum(numeric(v, 'db_copy_bytes') for v in rows),
        'db_busy_count': sum(numeric(v, 'db_busy_count') for v in rows),
        'max_write_tx_ms': max((numeric(v, 'write_tx_ms') for v in rows), default=0)}
    for item in value.get('writers', [])[:128]:
        if isinstance(item, dict):
            result['max_write_tx_ms'] = max(result['max_write_tx_ms'], numeric(item, 'write_tx_ms'))
    result['status'] = 'degraded' if (result['db_copy_bytes'] > 16*1024*1024 or result['db_busy_count'] > 0
        or result['max_write_tx_ms'] > 1000 or result['slow_count'] >= 3) else 'healthy'
    return result


def journal_performance(root, inspected, *, now=None):
    """Bounded journal tails also see locks held by background worker processes."""
    now = time.time() if now is None else now
    directory = Path(root)/'data/logs/toolbox'
    events = []
    members = inspected.get('role_member_pids', inspected.get('server_member_pids', []))
    for role in ('server', 'worker', 'feedback', 'learning', 'local', 'supervisor'):
        paths = sorted(directory.glob(role+'-*.jsonl'), key=lambda p:p.stat().st_mtime, reverse=True)[:2]
        for path in paths:
            if path.is_symlink():
                continue
            with path.open('rb') as stream:
                size = path.stat().st_size
                stream.seek(max(0, size-256*1024))
                raw = stream.read(256*1024)
            lines = raw.splitlines()[1:] if size > 256*1024 else raw.splitlines()
            for line in lines:
                try: item = json.loads(line)
                except (ValueError, UnicodeError): continue
                if (isinstance(item, dict) and item.get('release') == inspected['binding']['release']
                        and item.get('pid') in members and type(item.get('at')) in (int,float)
                        and 0 <= now-item['at'] <= 900):
                    events.append(item)
    events.sort(key=lambda v:v['at'])
    active = {}
    recent = []
    maximum = 0
    for item in events:
        key = (item.get('pid'), item.get('resource_ref'))
        if item.get('event') == 'database_write_started':
            active[key] = item['at']
        elif item.get('event') == 'database_write_finished':
            active.pop(key, None)
            if now-item['at'] <= 300 and type(item.get('write_tx_ms')) in (int,float):
                maximum = max(maximum, item['write_tx_ms'])
        elif item.get('event') == 'performance_finished' and now-item['at'] <= 300:
            recent.append(item)
    # Only a numeric projection leaves this function; never persist raw records.
    result = performance({'recent': recent[-32:]})
    maximum = max([maximum, *((now-stamp)*1000 for stamp in active.values())])
    result['max_write_tx_ms'] = max(result['max_write_tx_ms'], maximum)
    if result['max_write_tx_ms'] > 1000:
        result['status'] = 'degraded'
    return result


class ApplicationAdapter:
    def __init__(self, config):
        self.config = dict(config)
        self.root = Path(config['app_root']).resolve()
        self.python = self.root/'.runtime/workbench-python/Scripts/python.exe'

    def call(self, action, request=None):
        if not self.python.is_file():
            raise BridgeUnavailable('application_python_missing')
        result = subprocess.run([str(self.python), '-I', str(Path(__file__).with_name('bridge_entry.py')),
            '--app-root', str(self.root), action], cwd=self.root,
            input=json.dumps(request) if request is not None else '', capture_output=True, text=True, encoding='utf-8',
            env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONDONTWRITEBYTECODE': '1'},
            timeout=180 if action == 'recover' else 35, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode or len(result.stdout.encode()) > 128*1024:
            # Do not log command stderr: application exceptions can contain data.
            raise BridgeUnavailable('application_bridge_unavailable')
        answer = json.loads(result.stdout)
        if not isinstance(answer, dict):
            raise BridgeUnavailable('invalid_bridge_reply')
        return answer

    def inspect(self):
        value = self.call('inspect')
        nonce = secrets.token_hex(16)
        request = urllib.request.Request('http://127.0.0.1:9123/_workbench/diagnostics',
            headers={'X-Workbench-Health-Token': value['health_token'], 'X-Workbench-Health-Nonce': nonce, 'Cache-Control': 'no-cache'})
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs): return None
        try:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            with opener.open(request, timeout=3) as response:
                raw = response.read(131073)
                data = json.loads(raw) if len(raw) <= 131072 else {}
                if (response.status != 200 or response.headers.get('X-Workbench-Health') != '1'
                        or data.get('nonce') != nonce or data.get('ok') is not True
                        or data.get('release') != value['binding']['release']
                        or data.get('pid') not in value['server_member_pids']):
                    raise BridgeUnavailable('unverified_diagnostics')
                if isinstance(data.get('business'), dict):
                    value['business'] = data['business']
                value['performance'] = performance(data.get('performance'))
        except (OSError, ValueError, BridgeUnavailable):
            value['performance'] = {'status': 'unavailable'}
        try:
            journal = journal_performance(self.root, value)
            current = value['performance']
            # HTTP and journal can cover the same event: maxima avoid double counting.
            for key in ('slow_count', 'db_copy_bytes', 'db_busy_count', 'max_write_tx_ms'):
                current[key] = max(current.get(key, 0), journal.get(key, 0))
            if journal['status'] == 'degraded':
                current['status'] = 'degraded'
        except (OSError, ValueError, TypeError):
            pass
        return value

    def recover(self, request):
        return self.call('recover', request)

    def reconcile(self, request):
        return self.call('reconcile', request)
