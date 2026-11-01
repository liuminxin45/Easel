"""Explicit Windows runtime acceptance. --exercise terminates only the checked
manager, never business roles; observe scheduler recovery/adoption over HTTP.
No business API writes, queue replay, database access or selector changes.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from easel_workbench.processes import rows, argv, checked_identity, existing

NS = {'t': 'http://schemas.microsoft.com/windows/2004/02/mit/task'}
ROLES = {'server', 'worker', 'publisher', 'feedback', 'collector', 'learning', 'local'}


def scheduled_xml():
    return subprocess.check_output(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
        "[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); Export-ScheduledTask -TaskName AINewsDesk"],
        text=True, encoding='utf-8').lstrip('\ufeff')


def configuration():
    doc = ET.fromstring(scheduled_xml())
    def text(path):
        return doc.findtext(path, namespaces=NS)
    assert text('t:Actions/t:Exec/t:Command') == str(ROOT / '.runtime/workbench-python/Scripts/pythonw.exe')
    assert text('t:Actions/t:Exec/t:Arguments') == '"' + str(ROOT / 'launcher.pyw') + '"'
    assert text('t:Principals/t:Principal/t:LogonType') == 'InteractiveToken'
    assert text('t:Settings/t:ExecutionTimeLimit') == 'PT0S'
    assert text('t:Settings/t:MultipleInstancesPolicy') == 'IgnoreNew'
    assert text('t:Settings/t:DisallowStartIfOnBatteries') == 'false'
    assert text('t:Settings/t:StopIfGoingOnBatteries') == 'false'
    assert text('t:Settings/t:IdleSettings/t:StopOnIdleEnd') == 'false'
    assert text('t:Triggers/t:TimeTrigger/t:Repetition/t:Interval') == 'PT1M'
    assert not text('t:Triggers/t:TimeTrigger/t:Repetition/t:Duration')
    # Scheduler omits this element when false (the schema default).
    assert text('t:Triggers/t:TimeTrigger/t:Repetition/t:StopAtDurationEnd') in (None, 'false')
    assert text('t:Triggers/t:LogonTrigger/t:UserId')
    assert len(doc.findall('t:Triggers/*', NS)) == 2
    return {'interval': 'PT1M', 'duration': 'indefinite', 'identity': 'existing-interactive-owner', 'overlap': 'IgnoreNew'}


def snapshot():
    return json.loads((ROOT / '.local/workbench-deployment/pids.json').read_text(encoding='utf-8'))


def http(url, expected, *, public=False):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        response = opener.open(urllib.request.Request(url, headers={'Host': 'leopc.tail2ce65.ts.net:8443'}), timeout=12)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        assert response.status == expected, (url, response.status)
        content = response.read()
        if public:
            assert urllib.parse.urlsplit(response.url).path == '/native/login', response.url
            assert b'<html' in content.lower()
        return {'url': url, 'status': response.status, 'final_url': response.url, 'bytes': len(content)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--exercise', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    options = parser.parse_args()
    result = {'passed': False, 'configuration': configuration()}
    selectors = {p: (ROOT / p).read_bytes() for p in ('data/active-workbench.json', 'data/active-native.json')}
    before = snapshot()
    assert not before['paused'] and set(before['roles']) == ROLES
    assert time.time() - before['heartbeat'] < 15
    inventory = rows()
    manager = inventory[before['manager']]
    arguments = argv(manager['command'])
    assert Path(arguments[1]).resolve() == ROOT / 'launcher.pyw', arguments
    handles = {}
    try:
        for role, pid in before['roles'].items():
            handle = existing(ROOT, ROOT / 'workbench-releases' / before['release'], role)
            assert handle is not None and handle.pid == pid, (role, pid)
            handles[role] = handle
        result['before'] = before
        result['health_before'] = http('http://127.0.0.1:9123/health', 401)
        if options.exercise:
            started = time.monotonic()
            with checked_identity(manager) as identity:
                identity.terminate(expected_creation_ticks=identity.creation_ticks)
            # Restart is initiated by the OS task, not this script. Preserve
            # live roles and verify their held creation-time handles each poll.
            probes = []
            deadline = started + 155
            while time.monotonic() < deadline:
                assert all(not handle.identity.exited() for handle in handles.values()), 'A business role exited'
                probes.append(http('http://127.0.0.1:9123/health', 401))
                current = snapshot()
                if current['manager'] != before['manager'] and time.time() - current['heartbeat'] < 10:
                    assert current['roles'] == before['roles'], 'Recovery must adopt exact roles'
                    assert current['release'] == before['release'] and not current['paused']
                    result.update(recovered_seconds=round(time.monotonic() - started, 2), after=current, continuity_probes=len(probes))
                    break
                time.sleep(3)
            else:
                raise AssertionError('OS scheduler did not restore the manager within deadline')
        result['public'] = [http('https://leopc.tail2ce65.ts.net:8443/native', 200, public=True),
                            http('https://leopc.tail2ce65.ts.net:8443/native/', 200, public=True)]
        for path, content in selectors.items():
            assert (ROOT / path).read_bytes() == content
        result['selectors'] = {path: hashlib.sha256(content).hexdigest() for path, content in selectors.items()}
        result['passed'] = True
    finally:
        for handle in handles.values():
            handle.close()
        options.output.parent.mkdir(parents=True, exist_ok=True)
        options.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
