"""Observe an actual retained root worker recover into a real candidate login.

Only a TEMP HTTP origin and browser profile are used. No credentials, production
data, model calls, or platform operations are sent. Unlike the handoff test, this
test never calls registration.update(): the old recovery document must recover
through its own GET probe, and the candidate login must retire the root worker.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import mimetypes
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from easel_workbench.runtime import pwa_assets


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def candidate_member(directory, manifest, name):
    path = (directory / name).resolve()
    if not path.is_relative_to(directory) or not path.is_file():
        raise FileNotFoundError(name)
    body = path.read_bytes()
    if hashlib.sha256(body).hexdigest() != manifest['files'].get(name):
        raise ValueError('Candidate member does not match manifest: ' + name)
    return body


@contextmanager
def fixture(directory, manifest, legacy_worker):
    state = {'available': True, 'retired': False, 'requests': Counter()}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def send(self, body=b'', content_type='text/html; charset=utf-8', status=200, **headers):
            if isinstance(body, str):
                body = body.encode('utf-8')
            self.send_response(status)
            values = {'Content-Type': content_type, 'Content-Length': str(len(body)),
                      'Cache-Control': 'no-store', 'X-Desk-Architecture': 'toolbox', **headers}
            for key, value in values.items():
                self.send_header(key, value)
            self.end_headers()
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                pass  # The old probe deliberately cancels its unused response body.

        def do_GET(self):
            path = urlsplit(self.path).path
            state['requests']['GET ' + path] += 1
            if path == '/fixture/seed':
                return self.send('<!doctype html><meta charset="utf-8"><main>TEMP seed only</main>')
            if path == '/sw.js':
                if state['retired']:
                    return pwa_assets.serve(self, path)
                return self.send(legacy_worker, 'text/javascript', **{'Service-Worker-Allowed': '/'})
            if path.startswith('/native-assets/' + manifest['release'] + '/'):
                name = path.removeprefix('/native-assets/' + manifest['release'] + '/')
                try:
                    body = candidate_member(directory, manifest, name)
                except (FileNotFoundError, ValueError):
                    return self.send('Unknown candidate member', status=404)
                mime = 'text/javascript' if name.endswith('.js') else mimetypes.guess_type(name)[0]
                return self.send(body, mime or 'application/octet-stream')
            if path in ('/native', '/native/', '/native/login'):
                if not state['available']:
                    return self.send('TEMP synthetic unavailable response', status=503)
                if path != '/native/login':
                    return self.send(status=303, Location='/native/login?' + urlencode({'next': self.path}))
                return self.send(candidate_member(directory, manifest, 'auth.html'))
            return self.send('TEMP fixture has no business API', status=404)

        def reject_write(self):
            state['requests'][self.command + ' ' + urlsplit(self.path).path] += 1
            self.send('Writes are forbidden in this read-only fixture', status=405)

        do_POST = do_PUT = do_PATCH = do_DELETE = reject_write

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port), state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


SEED = """async () => {
  await navigator.serviceWorker.register('/sw.js',{scope:'/',updateViaCache:'none'});
  await navigator.serviceWorker.ready;
  if(!navigator.serviceWorker.controller)await new Promise(resolve=>navigator.serviceWorker.addEventListener('controllerchange',resolve,{once:true}));
  localStorage.setItem('toolbox:draft:recovery-fixture','原字草稿');
  localStorage.setItem('toolbox:operation:recovery-fixture',JSON.stringify({id:'unknown-once',state:'unknown'}));
  await (await caches.open('desk-attachments-recovery-fixture')).put('/fixture-attachment',new Response('attachment-bytes'));
  await new Promise((resolve,reject)=>{
    const open=indexedDB.open('recovery-fixture',1);
    open.onupgradeneeded=()=>open.result.createObjectStore('pending');
    open.onerror=reject;
    open.onsuccess=()=>{
      const db=open.result,tx=db.transaction('pending','readwrite');
      tx.objectStore('pending').put({id:'unknown-once',state:'unknown'},'operation');
      tx.oncomplete=()=>{db.close();resolve()};
    };
  });
}"""

SNAPSHOT = """async () => ({
  draft:localStorage.getItem('toolbox:draft:recovery-fixture'),
  operation:localStorage.getItem('toolbox:operation:recovery-fixture'),
  attachment:await(await(await caches.open('desk-attachments-recovery-fixture')).match('/fixture-attachment')).text(),
  pending:await new Promise((resolve,reject)=>{
    const open=indexedDB.open('recovery-fixture',1);open.onerror=reject;
    open.onsuccess=()=>{
      const db=open.result,tx=db.transaction('pending','readonly'),request=tx.objectStore('pending').get('operation');
      request.onsuccess=()=>{resolve(request.result);db.close()};
    };
  })
})"""


def run(directory, legacy_path, output, executable):
    from playwright.sync_api import sync_playwright

    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((directory / 'native-manifest.json').read_text(encoding='utf-8'))
    report = {'passed': False, 'checks': [], 'legacy_worker_sha256': sha(legacy_path),
              'harness_sha256': sha(__file__), 'native_release': manifest['release'],
              'native_manifest_sha256': sha(directory / 'native-manifest.json'),
              'temporary_origin_and_storage_only': True, 'production_calls': 0,
              'manual_registration_updates': 0, 'credentials_sent': False,
              'physical_mobile_device_tested': False, 'console_errors': []}

    def check(name, passed):
        report['checks'].append({'name': name, 'passed': bool(passed)})
        assert passed, name

    try:
        # Validate the real auth document before opening the temporary origin.
        candidate_member(directory, manifest, 'auth.html')
        with fixture(directory, manifest, legacy_path.read_bytes()) as (origin, state), sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            context = browser.new_context(service_workers='allow', viewport={'width': 1280, 'height': 800})
            try:
                page = context.new_page()
                external_requests = []
                page.on('request', lambda request: external_requests.append(request.url)
                        if urlsplit(request.url).netloc != urlsplit(origin).netloc else None)
                page.on('pageerror', lambda error: report['console_errors'].append(str(error)))
                page.goto(origin + '/fixture/seed')
                page.evaluate(SEED)
                before = page.evaluate(SNAPSHOT)
                check('actual archived root worker controls the TEMP page',
                      page.evaluate("new URL(navigator.serviceWorker.controller.scriptURL).pathname") == '/sw.js')
                state['available'] = False
                page.goto(origin + '/native', wait_until='domcontentloaded')
                check('actual old worker produces the reported recovery document',
                      page.locator('[data-toolbox-recovery]').count() == 1
                      and page.get_by_role('heading', name='连接暂时中断').count() == 1)
                page.screenshot(path=str(output / 'old-recovery.png'), full_page=True)
                # Restore only the fixture server. No reload, update(), online
                # event, retry click, or new navigation is injected into the tab.
                started = time.monotonic()
                state['retired'], state['available'] = True, True
                page.wait_for_url('**/native/login?**', timeout=45000)
                page.get_by_role('heading', name='登录创作工作台').wait_for(timeout=20000)
                check('old recovery self-heals into the real candidate login',
                      urlsplit(page.url).path == '/native/login'
                      and page.locator('[data-toolbox-recovery]').count() == 0)
                report['recovery_seconds'] = round(time.monotonic() - started, 3)
                # Poll the awaited browser API explicitly: a Promise itself is
                # truthy and must not be mistaken for successful retirement.
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if page.evaluate("async () => !(await navigator.serviceWorker.getRegistrations()).some(r=>r.scope===location.origin+'/')"):
                        break
                    page.wait_for_timeout(100)
                report['remaining_registrations'] = page.evaluate("async () => (await navigator.serviceWorker.getRegistrations()).map(r=>({scope:r.scope,script:(r.active||r.waiting||r.installing)?.scriptURL}))")
                check('candidate login retires the exact old root registration before authentication',
                      page.evaluate("async () => !(await navigator.serviceWorker.getRegistrations()).some(r=>r.scope===location.origin+'/')"))
                after = page.evaluate(SNAPSHOT)
                check('draft, attachment, local unknown ID and IndexedDB pending record remain byte-exact', before == after)
                check('candidate login input is usable without submitting credentials',
                      page.get_by_role('textbox', name='6位验证码').is_visible())
                check('no write, model, collection or platform request is issued',
                      not any(not key.startswith('GET ') or '/api/' in key for key in state['requests']))
                check('all observed document requests stay within the TEMP origin', not external_requests)
                check('real candidate login has no JavaScript page error', not report['console_errors'])
                page.screenshot(path=str(output / 'recovered-login.png'), full_page=True)
                report['request_counts'] = dict(state['requests'])
                report['artifacts'] = {name: sha(output / name) for name in ('old-recovery.png', 'recovered-login.png')}
                report['passed'] = True
            finally:
                context.close()
                browser.close()
    except Exception as error:
        report['error'] = {'type': type(error).__name__, 'message': str(error)}
    (output / 'legacy-recovery-browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'error': report.get('error')}, ensure_ascii=True))
    return report['passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--legacy-worker', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--browser', type=Path, default=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'))
    args = parser.parse_args()
    raise SystemExit(0 if run(args.native.resolve(), args.legacy_worker.resolve(), args.output.resolve(), args.browser) else 1)
