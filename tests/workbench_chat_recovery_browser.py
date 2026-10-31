"""Real mobile browser recovery against TEMP services and a frozen native UI.

Only the TEMP server's stream transport is faulted: one accepted POST ends after
its actual events, then the GET continuation is held and resumed silently. The
application modules/DOM are never replaced. Model work is a controlled adapter.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class StreamFault:
    """End an actual accepted stream once, then hold its actual GET replay."""
    def __init__(self, original, started):
        self.original = original
        self.started = started
        self.allow_resume = threading.Event()
        self.keepalive = threading.Event()
        self.enabled = True
        self.turn_id = None
        self.calls = Counter()
        self.initial_events = []
        self.replayed_events = []

    def __call__(self, service, turn_id, after=0, accepted=False, authenticated=None):
        from fastapi.responses import StreamingResponse
        self.calls[turn_id] += 1
        if self.enabled and self.turn_id is None:
            self.turn_id = turn_id
        faulted = self.enabled and self.turn_id == turn_id
        first = faulted and self.calls[turn_id] == 1
        response = self.original(service, turn_id, after, accepted, authenticated)

        async def body():
            if first:
                while not self.started.is_set():
                    await asyncio.sleep(.01)
                pending = service.read_events(turn_id, after)
                assert pending, 'Real initial events must exist before ending transport'
                self.initial_events = [event['id'] for event in pending]
                final_id = max(self.initial_events)
            elif faulted:
                while not self.allow_resume.is_set():
                    await asyncio.sleep(.01)
            try:
                async for frame in response.body_iterator:
                    text = frame.decode() if isinstance(frame, bytes) else frame
                    if faulted and not first:
                        if text.startswith(': keep-alive'):
                            self.keepalive.set()
                        if text.startswith('id:'):
                            self.replayed_events.append(int(text.split('\n', 1)[0][3:]))
                    yield frame
                    if first and text.startswith('id:') and int(text.split('\n', 1)[0][3:]) >= final_id:
                        return  # EOF, while the separately owned native run stays alive.
            finally:
                await response.body_iterator.aclose()

        return StreamingResponse(body(), status_code=response.status_code,
                                 media_type=response.media_type, headers=dict(response.headers))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('native', 'backend', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    native, backend, out = args.native.resolve(), args.backend.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    backend_manifest = json.loads((backend / 'workbench-release.json').read_text(encoding='utf-8'))
    manifest = json.loads((native / 'native-manifest.json').read_text(encoding='utf-8'))
    assert all(sha(backend / name) == digest for name, digest in backend_manifest['files'].items())
    assert all(sha(native / name) == digest for name, digest in manifest['files'].items())
    sys.path.insert(0, str(backend))
    spec = importlib.util.spec_from_file_location('native_browser_fixture', ROOT / 'tests/workbench_native_browser.py')
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    from playwright.sync_api import sync_playwright, expect
    from easel.harnesses.base import HarnessError
    import easel_workbench.chat_api as chat_api

    report = {'passed': False, 'native': {'release': manifest['release'], 'manifest_sha256': sha(native / 'native-manifest.json')},
              'backend': {'directory': str(backend), 'manifest_sha256': sha(backend / 'workbench-release.json')},
              'harness_sha256': sha(__file__), 'fixture_sha256': sha(ROOT / 'tests/workbench_native_browser.py'),
              'checks': [], 'screenshots': {}, 'real_AI_calls': 0, 'real_platform_writes': 0,
              'physical_mobile_device_tested': False, 'application_source_injected': False, 'DOM_or_CSS_mocked': False}

    def check(name, value=True):
        report['checks'].append({'name': name, 'passed': bool(value)})
        assert value, name

    def screenshot(page, name):
        page.screenshot(path=str(out / name), full_page=True)
        report['screenshots'][name] = sha(out / name)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True, args=['--ignore-certificate-errors'])
            with helper.isolated(native, b'TEMP no media generation') as fixture:
                adapter = fixture['adapter']
                adapter.mode = 'hold'
                started = threading.Event()

                async def run(request, emit, ask, bind):
                    adapter.requests.append(request)
                    native_id = request.native_id or 'temp-native-' + request.session_key
                    native_turn = 'temp-native-turn-' + str(len(adapter.requests))
                    bind(native_id)
                    request.on_native_turn(native_id, native_turn)
                    emit('token', 'TEMP 本回合已受理；这是隔离假执行器输出。')
                    if adapter.mode == 'unknown':
                        raise HarnessError('TEMP 原执行结果未知，禁止重发')
                    started.set()
                    try:
                        await asyncio.Future()
                    except asyncio.CancelledError:
                        request.on_native_interrupt(native_id, native_turn)
                        raise

                adapter.run = run
                fault = StreamFault(chat_api.stream, started)
                with patch.object(chat_api, 'stream', fault):
                    context = browser.new_context(ignore_https_errors=True, viewport={'width': 390, 'height': 844}, is_mobile=True, has_touch=True)
                    fixture['close_clients'] = context.close
                    context.add_cookies([{'name': '__Host-desk_session', 'value': 'fixture-owner', 'url': fixture['origin'], 'secure': True, 'httpOnly': True, 'sameSite': 'Strict'}])
                    page = context.new_page()
                    errors, requests = [], []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('request', lambda request: requests.append({'method': request.method, 'path': urlsplit(request.url).path,
                                                                      'body': request.post_data_json if request.method == 'POST' and request.post_data else None}))
                    page.set_default_timeout(20000)

                    def new_session():
                        page.goto(fixture['origin'] + '/native/chat?fresh=1', wait_until='domcontentloaded')
                        page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.startsWith('/chat/')")
                        sid = parse_qs(urlsplit(page.url).query)['path'][0].split('/chat/')[1].split('?')[0]
                        expect(page.get_by_role('textbox', name='对话输入', exact=True)).to_be_visible()
                        return sid

                    def send_poster(text):
                        composer = page.get_by_role('textbox', name='对话输入', exact=True)
                        composer.fill('/生成贴图 ' + text)
                        expect(page.get_by_role('menuitem', name='/生成贴图', exact=False)).to_be_visible()
                        composer.press('Enter')
                        expect(page.get_by_text('生成贴图 · v', exact=False)).to_be_visible()
                        expect(page.get_by_role('button', name='发送', exact=True)).to_be_enabled()
                        composer.press('Enter')

                    sid = new_session()
                    original = 'TEMP 准确原字贴图；连接恢复不能再次制作'
                    send_poster(original)
                    interrupted = page.get_by_role('status').filter(has_text='连接暂时中断，正在恢复原任务状态。输入已保留。')
                    expect(interrupted).to_be_visible()
                    screenshot(page, '390-transport-interrupted.png')
                    turn_id = fault.turn_id
                    check('one original production POST is accepted by the actual TEMP backend',
                          len(adapter.requests) == 1 and len([r for r in requests if r['path'] == '/api/chat/stream' and r['method'] == 'POST']) == 1)
                    saved = page.evaluate("sid=>JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid))", sid)
                    check('frozen original input and precise turn remain while transport is interrupted',
                          saved['pending']['turnId'] == turn_id and saved['pending']['inputs']['text'] == original and saved['pending']['accepted'] is True)
                    fault.allow_resume.set()
                    page.wait_for_function("()=>document.querySelector('.chat-page button[title=\"停止生成\"]')||document.querySelector('button[title=\"停止生成\"]')")
                    deadline = time.monotonic() + 15
                    while not fault.keepalive.is_set():
                        assert time.monotonic() < deadline, 'Actual resumed stream must deliver a keepalive'
                        page.wait_for_timeout(50)
                    expect(interrupted).to_have_count(0)
                    expect(page.get_by_role('alert').filter(has_text='连接中断，正在核对原任务')).to_have_count(0)
                    expect(page.locator('button[title="停止生成"]')).to_be_visible()
                    check('healthy accepted plus keepalive clears stale transport warning without any new model token', not fault.replayed_events)
                    quiet_events = list(fault.replayed_events)
                    saved_after = page.evaluate("sid=>JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid))", sid)
                    check('transport restoration retains the same frozen turn, original input, and pending identity', saved_after == saved)
                    check('restoration uses GET continuation only and never starts another execution',
                          len(adapter.requests) == 1 and len([r for r in requests if r['path'] == '/api/chat/stream' and r['method'] == 'POST']) == 1 and fault.calls[turn_id] == 2)
                    screenshot(page, '390-silent-stream-restored.png')
                    page.locator('button[title="停止生成"]').click()
                    page.wait_for_function("sid=>!JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid)).pending", arg=sid)
                    receipt = page.request.get(fixture['origin'] + '/api/chat/last/' + sid + '?turn_id=' + turn_id).json()
                    check('actual same-turn interruption receipt releases recovery without claiming completion',
                          receipt['execution_status'] == 'stopped' and receipt['delivery_state'] == 'interrupted' and receipt['interrupt_confirmed'] is True)
                    expect(page.get_by_text('TEMP 本回合已受理；这是隔离假执行器输出。', exact=True)).to_be_visible()
                    expect(interrupted).to_have_count(0)
                    screenshot(page, '390-confirmed-interrupted-history.png')

                    # A real unknown receipt is a distinct second case, never
                    # overwritten with a simulated completed or stopped result.
                    fault.enabled = False
                    adapter.mode = 'unknown'
                    second_sid = new_session()
                    send_poster('UNKNOWN TEMP 原执行结果未知，输入原字保留')
                    page.wait_for_function("sid=>JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid))?.pending?.state==='unknown'", arg=second_sid)
                    unknown = page.evaluate("sid=>JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid))", second_sid)
                    unknown_turn = unknown['pending']['turnId']
                    receipt = page.request.get(fixture['origin'] + '/api/chat/last/' + second_sid + '?turn_id=' + unknown_turn).json()
                    check('unknown native execution remains unknown with original production version', receipt['execution_status'] == receipt['delivery_state'] == 'unknown')
                    expect(page.get_by_role('button', name='发送', exact=True)).to_be_disabled()
                    expect(page.get_by_role('status').filter(has_text='原任务执行结果')).to_be_visible()
                    expect(page.get_by_role('status').filter(has_text='连接暂时中断')).to_have_count(0)
                    screenshot(page, '390-unknown-execution.png')
                    page.reload(wait_until='domcontentloaded')
                    expect(page.get_by_role('button', name='发送', exact=True)).to_be_disabled()
                    expect(page.get_by_role('status').filter(has_text='原任务执行结果')).to_be_visible()
                    check('unknown receipt survives reload without replay, losing original ID, or claiming success',
                          page.evaluate("sid=>JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid)).pending.turnId", second_sid) == unknown_turn
                          and len(adapter.requests) == 2
                          and len([r for r in requests if r['path'] == '/api/chat/stream' and r['method'] == 'POST']) == 2)
                    check('actual mobile page has no JavaScript errors', not errors)
                    report['errors'] = errors
                    report['requests'] = requests
                    report['transport_fault'] = {'original_turn': turn_id, 'initial_event_ids': fault.initial_events,
                                                 'silent_resume_application_event_ids': quiet_events,
                                                 'events_after_explicit_stop': fault.replayed_events,
                                                 'keepalive_received': fault.keepalive.is_set()}
                    report['passed'] = True
                    context.close()
            browser.close()
    except Exception as error:
        report['error'] = repr(error)
    finally:
        report['runtime_modules'] = {name: {'file': str(Path(module.__file__).resolve()), 'sha256': sha(module.__file__)}
                                     for name, module in list(sys.modules.items())
                                     if (name == 'easel' or name.startswith('easel.') or name == 'easel_workbench' or name.startswith('easel_workbench.')) and getattr(module, '__file__', None)}
        report['module_roots_valid'] = all(Path(item['file']).is_relative_to(backend) for item in report['runtime_modules'].values())
        report['passed'] &= report['module_roots_valid']
        shutil.copy2(__file__, out / 'harness.py')
        (out / 'chat-recovery-browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'error': report.get('error')}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
