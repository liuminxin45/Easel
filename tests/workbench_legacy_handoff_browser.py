"""Real Edge Service Worker handoff, TEMP origin/storage, no production calls."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import contextmanager
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import sys
import threading
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from easel_workbench.runtime import pwa_assets


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


@contextmanager
def fixture(legacy_worker):
    state = {'retired': False, 'native_available': True, 'requests': Counter()}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def send(self, body, content_type='text/html; charset=utf-8', status=200):
            body = body.encode('utf-8') if isinstance(body, str) else body
            self.send_response(status)
            for key, value in {'Content-Type': content_type, 'Content-Length': str(len(body)),
                               'Cache-Control': 'no-store', 'X-Desk-Architecture': 'toolbox'}.items():
                self.send_header(key, value)
            self.end_headers()
            self.wfile.write(body)
        def do_GET(self):
            path = urlsplit(self.path).path
            state['requests']['GET ' + path] += 1
            if path == '/sw.js':
                if not state['retired']:
                    return self.send(legacy_worker, 'text/javascript; charset=utf-8')
                return pwa_assets.serve(self, path)
            if path in ('/toolbox-boot.js', '/manifest.webmanifest', '/offline.html'):
                return pwa_assets.serve(self, path)
            if path == '/native/sw.js':
                return self.send("self.addEventListener('install',e=>e.waitUntil(self.skipWaiting()));self.addEventListener('activate',e=>e.waitUntil(self.clients.claim()));", 'text/javascript')
            if path == '/native/':
                if not state['native_available']:
                    return self.send('TEMP synthetic upstream unavailable', status=503)
                return self.send('<!doctype html><meta charset="utf-8"><meta name="native-release" content="native-TEMP"><main id="native">TEMP native shell</main>')
            return self.send('<!doctype html><meta charset="utf-8"><div id="root"><textarea id="editor"></textarea></div>')
        def do_POST(self):
            state['requests']['POST ' + urlsplit(self.path).path] += 1
            self.send('Forbidden in read-only fixture', status=405)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield 'http://127.0.0.1:' + str(server.server_port), state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def run(legacy_path, output, executable):
    from playwright.sync_api import sync_playwright
    output.mkdir(parents=True, exist_ok=True)
    report = {'passed': False, 'checks': [], 'legacy_worker_sha256': sha(legacy_path),
              'harness_sha256': sha(__file__), 'real_AI_calls': 0, 'real_platform_writes': 0,
              'temporary_state_only': True, 'physical_mobile_device_tested': False,
              'migration_assets': {name: hashlib.sha256(pwa_assets.asset(name)[0]).hexdigest() for name in pwa_assets.MIGRATION}}
    def check(name, passed=True):
        report['checks'].append({'name': name, 'passed': bool(passed)})
        assert passed, name
    try:
        with fixture(legacy_path.read_bytes()) as (origin, state), sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(executable), headless=True)
            context = browser.new_context(service_workers='allow')
            try:
                editor = context.new_page()
                editor.goto(origin + '/articles/draft')
                editor.evaluate("""async () => {
                  await navigator.serviceWorker.register('/sw.js',{scope:'/',updateViaCache:'none'});
                  await navigator.serviceWorker.ready;
                  if(!navigator.serviceWorker.controller)await new Promise(resolve=>navigator.serviceWorker.addEventListener('controllerchange',resolve,{once:true}));
                  localStorage.setItem('toolbox:draft:fixture','原字草稿');
                  localStorage.setItem('toolbox:operation:fixture',JSON.stringify({id:'unknown-once',state:'unknown'}));
                  await (await caches.open('desk-attachments-fixture')).put('/fixture-attachment',new Response('attachment-bytes'));
                  await new Promise((resolve,reject)=>{const open=indexedDB.open('handoff-fixture',1);open.onupgradeneeded=()=>open.result.createObjectStore('pending');open.onerror=reject;open.onsuccess=()=>{const db=open.result,tx=db.transaction('pending','readwrite');tx.objectStore('pending').put({id:'unknown-once',state:'unknown'},'operation');tx.oncomplete=()=>{db.close();resolve()}}});
                }""")
                editor.locator('#editor').fill('未保存的当前输入')
                check('actual retained root worker controls the TEMP editor', editor.evaluate("new URL(navigator.serviceWorker.controller.scriptURL).pathname") == '/sw.js')
                state['native_available'] = False
                recovery = context.new_page()
                recovery.goto(origin + '/native/', wait_until='domcontentloaded')
                check('actual old worker reproduces old recovery document on native 503', recovery.locator('[data-toolbox-recovery]').count() == 1)
                check('old recovery message is from retained worker', recovery.get_by_role('heading', name='连接暂时中断').count() == 1)
                state['retired'], state['native_available'] = True, True
                editor.evaluate("""async () => {
                  const prior=navigator.serviceWorker.controller;
                  const changed=new Promise(resolve=>navigator.serviceWorker.addEventListener('controllerchange',resolve,{once:true}));
                  await (await navigator.serviceWorker.getRegistration('/')).update();
                  if(navigator.serviceWorker.controller===prior)await changed;
                }""")
                check('worker handoff does not navigate the already open editor', editor.url == origin + '/articles/draft')
                check('unsaved live editor input survives activation', editor.locator('#editor').input_value() == '未保存的当前输入')
                editor.add_script_tag(url=origin + '/toolbox-boot.js')
                check('legacy boot preserves an open editor and offers explicit handoff', editor.url == origin + '/articles/draft' and editor.locator('#editor').input_value() == '未保存的当前输入' and editor.locator('[data-legacy-handoff] a').count() == 1)
                stored = editor.evaluate("""async () => ({draft:localStorage.getItem('toolbox:draft:fixture'),operation:localStorage.getItem('toolbox:operation:fixture'),attachment:await(await(await caches.open('desk-attachments-fixture')).match('/fixture-attachment')).text(),pending:await new Promise((resolve,reject)=>{const open=indexedDB.open('handoff-fixture',1);open.onerror=reject;open.onsuccess=()=>{const db=open.result,tx=db.transaction('pending','readonly'),request=tx.objectStore('pending').get('operation');request.onsuccess=()=>{resolve(request.result);db.close()}}})})""")
                check('local draft, attachment cache and both unknown operation records remain exact', stored == {'draft': '原字草稿', 'operation': '{"id":"unknown-once","state":"unknown"}', 'attachment': 'attachment-bytes', 'pending': {'id': 'unknown-once', 'state': 'unknown'}})
                migrated = context.new_page()
                for old in ('/', '/toolbox?section=profiles', '/works/exact?version=v01'):
                    migrated.goto(origin + old)
                    check('future legacy navigation reaches native: ' + old, urlsplit(migrated.url).path == '/native/' and migrated.locator('#native').count() == 1)
                migrated.evaluate("""async () => {await navigator.serviceWorker.register('/native/sw.js',{scope:'/native/'});await new Promise(resolve=>{if(navigator.serviceWorker.controller?.scriptURL.endsWith('/native/sw.js'))return resolve();navigator.serviceWorker.addEventListener('controllerchange',resolve,{once:true})})}""")
                check('native scoped worker keeps its more specific ownership', migrated.evaluate("new URL(navigator.serviceWorker.controller.scriptURL).pathname") == '/native/sw.js')
                editor.evaluate("document.getElementById('root').textContent='仅有原字';document.querySelector('[data-legacy-handoff]')?.remove()")
                editor.add_script_tag(url=origin + '/toolbox-boot.js')
                check('plain text without element children is retained rather than treated as empty', editor.url == origin + '/articles/draft' and editor.locator('#root').text_content() == '仅有原字')
                # Deliberately replace only TEMP DOM to exercise an empty stale boot.
                editor.evaluate("document.getElementById('root').innerHTML='<main data-toolbox-boot-status>正在打开</main>';document.querySelector('[data-legacy-handoff]')?.remove()")
                editor.add_script_tag(url=origin + '/toolbox-boot.js')
                editor.wait_for_url('**/native/**')
                check('empty stale startup shell moves into native without loading the old app', urlsplit(editor.url).path == '/native/')
                check('worker never calls a write, model, collection or platform API', not any(key.startswith('POST ') or '/api/' in key for key in state['requests']))
                report['request_counts'] = dict(state['requests'])
                report['passed'] = True
            finally:
                context.close()
                browser.close()
    except Exception as error:
        report['error'] = {'type': type(error).__name__, 'message': str(error)}
    (output / 'legacy-handoff-browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'error': report.get('error')}, ensure_ascii=True))
    return report['passed']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legacy-worker', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--browser', type=Path, default=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'))
    arguments = parser.parse_args()
    raise SystemExit(0 if run(arguments.legacy_worker.resolve(), arguments.output.resolve(), arguments.browser) else 1)
