"""Real Edge / TEMP HTTPS: slow preparation, navigation and full browser exit."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import threading
import time
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ('native', 'backend', 'out'): parser.add_argument('--'+key, type=Path, required=True)
    args = parser.parse_args()
    native, backend, out = args.native.resolve(), args.backend.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    package = json.loads((backend/'workbench-release.json').read_bytes()) if (backend/'workbench-release.json').exists() else None
    manifest = json.loads((native/'native-manifest.json').read_bytes())
    assert all(sha(native/p) == digest for p, digest in manifest['files'].items())
    if package: assert all(sha(backend/p) == digest for p, digest in package['files'].items())
    sys.path.insert(0, str(backend))
    spec = importlib.util.spec_from_file_location('admission_browser_fixture', ROOT/'tests/workbench_native_browser.py')
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    from playwright.sync_api import sync_playwright, expect
    report = {'passed': False, 'checks': [], 'native': manifest['release'], 'backend': str(backend),
              'harness_sha256': sha(__file__), 'screenshots': {}, 'real_AI_calls': 0,
              'real_platform_writes': 0, 'physical_mobile_device_tested': False,
              'application_source_injected': False, 'DOM_or_CSS_mocked': False}
    def check(name, value):
        report['checks'].append({'name': name, 'passed': bool(value)})
        assert value, name
    def shot(page, name):
        page.screenshot(path=str(out/name), full_page=True); report['screenshots'][name] = sha(out/name)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            for profile, width in [('desktop', 1280), ('mobile', 390)]:
                with helper.isolated(native, (ROOT/'web/static/easel-icon.png').read_bytes()) as f:
                    admissions = f['app'].state.chat_admissions
                    gate, entered = threading.Event(), threading.Event()
                    original_prepare = admissions._prepare
                    def slow(row):
                        entered.set(); assert gate.wait(90), 'TEMP preparation gate timed out'
                        return original_prepare(row)
                    admissions._prepare = slow
                    def context():
                        c = browser.new_context(ignore_https_errors=True, viewport={'width': width, 'height': 960}, is_mobile=width<600, has_touch=width<600)
                        c.add_cookies([{'name': '__Host-desk_session', 'value': 'fixture-owner', 'url': f['origin'], 'secure': True, 'httpOnly': True, 'sameSite': 'Strict'}])
                        return c
                    c = context(); page = c.new_page(); page.set_default_timeout(20000)
                    errors, requests = [], []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('request', lambda r: requests.append({'method': r.method, 'path': urlsplit(r.url).path}))
                    try:
                        page.goto(f['origin']+'/native/chat?fresh=1', wait_until='domcontentloaded')
                        page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.startsWith('/chat/')")
                        sid = parse_qs(urlsplit(page.url).query)['path'][0].split('/chat/')[1].split('?')[0]
                        composer = page.get_by_role('textbox', name='对话输入', exact=True)
                        raw = 'TEMP 按建议的三个角度制作贴图 '+profile
                        composer.fill('/生成贴图 '+raw)
                        expect(page.get_by_role('menuitem', name='/生成贴图', exact=False)).to_be_visible()
                        composer.press('Enter'); expect(composer).to_have_value(raw)
                        start = time.monotonic()
                        with page.expect_response(lambda r: r.request.method=='POST' and urlsplit(r.url).path=='/api/chat/submit') as response:
                            page.get_by_role('button', name='发送', exact=True).evaluate('button=>{button.click();button.click()}')
                        ack = response.value; elapsed = time.monotonic()-start; receipt = ack.json(); tid = receipt['id']
                        check(profile+' durable acknowledgement precedes slow preparation', ack.status==202 and elapsed<2 and receipt['accepted_by_server'])
                        expect(composer).to_have_value('')
                        expect(page.locator('.chat-thread').get_by_text(raw, exact=True)).to_be_visible()
                        expect(page.get_by_text('AI已接收，正在处理', exact=False).first).to_be_visible()
                        check(profile+' exactly one receipt and no client plan or execution POST', len([r for r in requests if r['method']=='POST' and r['path']=='/api/chat/submit'])==1 and not any(r['method']=='POST' and r['path'] in ('/api/chat/plan','/api/chat/stream') for r in requests))
                        assert entered.wait(2) and not f['adapter'].requests
                        if profile=='desktop': page.wait_for_timeout(32000)
                        check(profile+' preparation beyond former timeout is healthy', '连接暂时中断' not in page.locator('body').inner_text() and '正在恢复操作状态' not in page.locator('body').inner_text() and not f['adapter'].requests)
                        shot(page, profile+'-received-preparing.png')
                        if profile=='desktop':
                            page.goto(f['origin']+'/native/?path=%2Ftoolbox', wait_until='domcontentloaded')
                        else:
                            c.close(); c = None
                        gate.set()
                        deadline=time.monotonic()+30
                        while time.monotonic()<deadline:
                            try: turn=admissions.chat.get_turn(tid, private=True)
                            except ValueError: turn={}
                            if turn.get('hook_status')=='completed': break
                            time.sleep(.1)
                        check(profile+' same accepted turn completes after leaving page', turn.get('status')=='completed' and turn.get('hook_status')=='completed' and len(f['adapter'].requests)==1)
                        files=admissions.history(sid)['session']['messages'][-1].get('output_files',[])
                        check(profile+' original message and exact selected production survive', turn['message']==raw and turn['snapshot']['task']=='poster' and bool(files))
                        if c is None: c=context(); page=c.new_page(); page.set_default_timeout(20000)
                        page.goto(f['origin']+'/native/chat/'+sid, wait_until='domcontentloaded')
                        expect(page.locator('.chat-thread').get_by_text(raw, exact=True)).to_be_visible()
                        expect(page.locator('.artifact-gallery')).to_have_count(1)
                        page.wait_for_timeout(500)
                        check(profile+' return uses durable history without a second execution', len(f['adapter'].requests)==1 and page.locator('.chat-thread').get_by_text(raw, exact=True).count()==1 and not errors)
                        shot(page, profile+'-returned-completed.png')
                        report.setdefault('scenarios', []).append({'profile': profile, 'session_id': sid, 'turn_id': tid, 'ack_seconds': elapsed, 'fake_calls': len(f['adapter'].requests), 'output_files': files, 'errors': errors})
                    except Exception:
                        if c is not None:
                            report['failure_body']=page.locator('body').inner_text(); shot(page, profile+'-failure.png')
                        raise
                    finally:
                        gate.set()
                        if c is not None: c.close()
            browser.close()
        report['passed']=True
    except Exception as error:
        import traceback
        report.update(error=repr(error), traceback=traceback.format_exc())
    finally:
        report['module_roots_valid']=all(Path(m.__file__).resolve().is_relative_to(backend) for name,m in list(sys.modules.items()) if (name=='easel' or name.startswith('easel.') or name=='easel_workbench' or name.startswith('easel_workbench.')) and getattr(m,'__file__',None))
        report['passed'] &= report['module_roots_valid']
        shutil.copy2(__file__,out/'harness.py')
        (out/'chat-admission-browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed':report['passed'], 'checks':len(report['checks']), 'error':report.get('error')}, ensure_ascii=False),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__': raise SystemExit(main())
