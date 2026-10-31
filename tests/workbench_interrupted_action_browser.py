"""Real browser acceptance of a proven interrupted production's continuation.

Actual TEMP owner routes, frozen services and immutable frontend are exercised.
The fake inference adapter writes actual retained files and ends unknown. The
real read-only receipt reconciliation is then applied only to the TEMP database.
No application source, DOM, CSS, production database or provider is substituted.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
import time
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('native', 'backend', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    native, backend, out = args.native.resolve(), args.backend.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((native / 'native-manifest.json').read_text(encoding='utf-8'))
    backend_manifest = json.loads((backend / 'workbench-release.json').read_text(encoding='utf-8'))
    assert all(sha(native / name) == digest for name, digest in manifest['files'].items())
    assert all(sha(backend / name) == digest for name, digest in backend_manifest['files'].items())
    helper = load('interrupted_browser_fixture', ROOT / 'tests/workbench_native_browser.py')
    reconcile = load('interrupted_browser_reconcile', ROOT / 'scripts/reconcile_workbench_native_receipt.py')
    sys.path.insert(0, str(backend))
    from playwright.sync_api import sync_playwright, expect
    from easel.harnesses.base import HarnessError

    report = {'passed': False,
              'native': {'release': manifest['release'], 'manifest_sha256': sha(native / 'native-manifest.json')},
              'backend': {'directory': str(backend), 'manifest_sha256': sha(backend / 'workbench-release.json')},
              'harness_sha256': sha(__file__), 'fixture_sha256': sha(ROOT / 'tests/workbench_native_browser.py'),
              'reconciliation_sha256': sha(ROOT / 'scripts/reconcile_workbench_native_receipt.py'),
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
            browser = playwright.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
                                                 headless=True, args=['--ignore-certificate-errors'])
            with helper.isolated(native, (ROOT / 'web/static/easel-icon.png').read_bytes()) as fixture:
                contexts, errors, requests, retained = [], [], [], {}
                fixture['close_clients'] = lambda: [context.close() for context in contexts]
                adapter = fixture['adapter']

                async def run(request, emit, ask, bind):
                    adapter.requests.append(request)
                    native_id = request.native_id or 'temp-native-' + request.session_key
                    native_turn = 'temp-native-turn-' + str(len(adapter.requests))
                    bind(native_id)
                    request.on_native_turn(native_id, native_turn)
                    payload = json.JSONDecoder().raw_decode(request.prompt.split('## 本轮冻结输入\n')[-1])[0]
                    folder = Path(payload['output_directory']).resolve()
                    assert folder.is_relative_to(fixture['root'])
                    folder.mkdir(parents=True, exist_ok=True)
                    image, copy = folder / '成品.png', folder / '标题与配文.txt'
                    image.write_bytes(adapter.image)
                    copy.write_text('TEMP 中断贴图标题\n\n准确原文和文件必须保留。', encoding='utf-8')
                    retained.update({str(path): sha(path) for path in (image, copy)})
                    emit('activity', 'TEMP 已写入本轮准确目录，尚未完成制作交付。')
                    emit('token', 'TEMP 本轮制作原始响应，文件已保留但制作未完成。')
                    await asyncio.sleep(.2)
                    raise HarnessError('TEMP 已发送但回执未知；禁止重放原制作请求')

                adapter.run = run

                def new_page(width, theme):
                    context = browser.new_context(ignore_https_errors=True, viewport={'width': width, 'height': 900},
                                                  is_mobile=width < 600, has_touch=width < 600, color_scheme=theme)
                    contexts.append(context)
                    context.add_cookies([{'name': '__Host-desk_session', 'value': 'fixture-owner', 'url': fixture['origin'],
                                          'secure': True, 'httpOnly': True, 'sameSite': 'Strict'}])
                    page = context.new_page()
                    page.set_default_timeout(20000)
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('request', lambda request: requests.append({'method': request.method, 'path': urlsplit(request.url).path,
                                                                        'body': request.post_data_json if request.method == 'POST' and request.post_data else None}))
                    return page

                def production_posts():
                    return [request for request in requests if request['method'] == 'POST'
                            and request['path'] in ('/api/chat/plan', '/api/chat/stream')]

                def session(page, sid):
                    response = page.request.get(fixture['origin'] + '/api/chat/sessions/' + sid)
                    assert response.ok, response.text()
                    return response.json()['session']

                page = new_page(390, 'light')
                page.goto(fixture['origin'] + '/native/chat?fresh=1', wait_until='domcontentloaded')
                page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.startsWith('/chat/')")
                sid = parse_qs(urlsplit(page.url).query)['path'][0].split('/chat/')[1].split('?')[0]
                original = 'TEMP 制作贴图原字；保留原文件，未授权自动重发。'
                composer = page.get_by_role('textbox', name='对话输入', exact=True)
                composer.fill('/生成贴图 ' + original)
                expect(page.get_by_role('menuitem', name='/生成贴图', exact=False)).to_be_visible()
                expect(page.get_by_role('button', name='发送', exact=True)).to_be_enabled()
                composer.press('Enter')
                expect(page.get_by_text('生成贴图 · v', exact=False)).to_be_visible()
                expect(composer).to_have_value(original)
                composer.press('Enter')
                page.wait_for_function("sid=>JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid))?.pending?.state==='unknown'", arg=sid)
                draft = page.evaluate("sid=>JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid))", sid)
                turn_id = draft['pending']['turnId']
                check('real unknown execution retains its frozen original text and pending identity',
                      draft['pending']['inputs']['text'] == original and draft['pending']['accepted'] is True)
                expect(page.get_by_role('status', name='制作中断', exact=True)).to_have_count(0)
                expect(page.get_by_role('button', name='继续制作', exact=True)).to_have_count(0)
                check('unknown receipt cannot acquire the proven-interruption action')
                later = 'TEMP 后写草稿：只导航，不重新制作，不覆盖这些原字。'
                composer.fill(later)
                page.wait_for_function("({sid,text})=>JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid))?.text===text", arg={'sid': sid, 'text': later})
                screenshot(page, '390-light-unknown-no-continuation.png')

                deadline = time.monotonic() + 20
                while True:
                    with fixture['box'].store.connect() as connection:
                        before = reconcile.affected(connection, turn_id)
                    turn = json.loads(before['turn']['document'])
                    if turn.get('hook_status') == 'completed':
                        break
                    assert time.monotonic() < deadline, 'Real business completion hook did not finish'
                    page.wait_for_timeout(100)
                check('fake inference really wrote two retained files before becoming unknown', len(retained) == 2 and turn['status'] == 'unknown')
                proof = {'method': 'thread/read', 'thread': {'id': turn['native_id'], 'cwd': str(fixture['root']), 'status': {'type': 'notLoaded'}},
                         'turn': {'id': turn['native_turn_id'], 'status': 'interrupted'}, 'read_only': True, 'new_model_turns': 0}
                with fixture['box'].store.connect() as connection:
                    expected_hash = reconcile.sha(reconcile.packed(reconcile.affected(connection, turn_id)))
                    with patch.object(reconcile, 'ROOT', fixture['root']):
                        journal = reconcile.apply(connection, turn_id, proof, expected_hash)
                history = session(page, sid)
                last = history['messages'][-1]
                recovery = last['business_recovery']
                work = last['work']
                check('real receipt reconciliation authorizes only the exact original work and version',
                      recovery['can_continue'] is True and recovery['continuation']['session_id'] == sid
                      and recovery['continuation']['work_id'] == work['work_id']
                      and recovery['continuation']['version_id'] == turn_id)
                check('read-only reconciliation neither reruns nor completes or delivers production',
                      journal['replayed'] is journal['completed'] is journal['delivered'] is False and len(adapter.requests) == 1)
                report['fixture'] = {'session_id': sid, 'turn_id': turn_id, 'work': work, 'recovery': recovery,
                                     'original': original, 'later_draft': later, 'retained_files': retained,
                                     'original_receipt_sha256': expected_hash, 'native_proof': proof}
                page.reload(wait_until='domcontentloaded')
                page.wait_for_function("sid=>!JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid))?.pending", arg=sid)
                check('same-session pending state clears only after the actual stopped receipt is read')

                for width, theme in ((390, 'light'), (320, 'dark'), (1440, 'light')):
                    if width != 390:
                        page = new_page(width, theme)
                        page.goto(fixture['origin'] + '/native/?' + urlencode({'path': '/chat/' + sid}), wait_until='domcontentloaded')
                        composer = page.get_by_role('textbox', name='对话输入', exact=True)
                        expect(composer).to_be_visible()
                    else:
                        composer = page.get_by_role('textbox', name='对话输入', exact=True)
                    top = page.get_by_role('status', name='制作中断', exact=True)
                    expect(top).to_be_visible()
                    if width != 390:
                        # The shell mounts its textbox before the real session
                        # resource is hydrated; enter a later draft only once
                        # that exact server-authorized session has rendered.
                        composer.fill(later)
                    expect(top).to_contain_text('本轮已中断，原文件已保留。')
                    button = top.get_by_role('button', name='继续制作', exact=True)
                    expect(button).to_be_visible()
                    expect(page.get_by_role('button', name='继续制作', exact=True)).to_have_count(1)
                    expect(page.get_by_role('alert').filter(has_text='原生接口已核对本回合中断')).to_have_count(0)
                    expect(composer).to_have_value(later)
                    check(str(width) + '-' + theme + ' notice and its single action fit without horizontal overflow',
                          top.evaluate('element=>element.scrollWidth<=element.clientWidth+1')
                          and page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1')
                          and page.evaluate('()=>document.documentElement.dataset.theme') == theme)
                    screenshot(page, str(width) + '-' + theme + '-interrupted-action.png')
                    before_posts, before_calls = len(production_posts()), len(adapter.requests)
                    button.click()
                    page.wait_for_function("()=>new URLSearchParams(new URLSearchParams(location.search).get('path').split('?')[1]).get('continue')==='1'")
                    path = parse_qs(urlsplit(page.url).query)['path'][0]
                    query = parse_qs(urlsplit(path).query)
                    identity = recovery['continuation']
                    check(str(width) + '-' + theme + ' action navigates the exact original session, work, version and skill',
                          urlsplit(path).path == '/chat/' + sid
                          and query.get('work') == [work['work_id']] and query.get('version') == [turn_id]
                          and query.get('skill') == [identity['skill_id']]
                          and query.get('skill_version') == [str(identity['skill_version'])]
                          and query.get('action') == ['change'])
                    expect(page.get_by_role('status', name='制作中断', exact=True)).to_have_count(0)
                    expect(page.get_by_role('button', name='继续制作', exact=True)).to_have_count(0)
                    expect(composer).to_have_value(later)
                    page.wait_for_function("({sid,skill,version})=>{const command=JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid))?.command;return command?.skill_id===skill&&command?.version===version&&command?.action_id==='change'}",
                                           arg={'sid': sid, 'skill': identity['skill_id'], 'version': identity['skill_version']})
                    page.wait_for_timeout(400)
                    check(str(width) + '-' + theme + ' navigation preserves later draft and never starts another plan, stream or model call',
                          len(production_posts()) == before_posts and len(adapter.requests) == before_calls)
                    screenshot(page, str(width) + '-' + theme + '-continuation-context.png')

                # A clean device has no later local draft: continuation may
                # prefill, but it still must never execute without Send.
                empty_page = new_page(390, 'dark')
                empty_page.goto(fixture['origin'] + '/native/?' + urlencode({'path': path}), wait_until='domcontentloaded')
                expect(empty_page.get_by_role('textbox', name='对话输入', exact=True)).to_have_value(re.compile('^请继续完成《'))
                expect(empty_page.get_by_role('button', name='继续制作', exact=True)).to_have_count(0)
                check('clean-device continuation only prefills and preserves the same original profile and frozen skill',
                      len(adapter.requests) == 1 and identity['profile_id'] == turn['snapshot']['profile']['id']
                      and identity['skill_version'] == next(skill['version'] for skill in turn['snapshot']['skills'] if skill['id'] == identity['skill_id'])
                      and empty_page.evaluate('()=>document.documentElement.dataset.theme') == 'dark')
                screenshot(empty_page, '390-dark-clean-continuation-prefill.png')
                final_history = session(empty_page, sid)
                final = final_history['messages'][-1]
                products = empty_page.request.get(fixture['origin'] + '/api/chat/products/' + turn_id).json()
                with fixture['box'].store.connect() as connection:
                    final_turn = json.loads(connection.execute('SELECT document FROM easel_chat_turns WHERE id=?', (turn_id,)).fetchone()[0])
                check('original turn, input and actual retained files stay unchanged after all navigation',
                      len(final_history['messages']) == len(history['messages']) and final['turnId'] == turn_id
                      and final['status'] == 'stopped' and all(sha(file) == digest for file, digest in retained.items())
                      and products['incomplete'] is True and products['can_adopt'] is False
                      and final_turn['actual_prompt'] == turn['actual_prompt'] and final_turn['snapshot'] == turn['snapshot'])
                check('actual 320/390 mobile and desktop browsers have no JavaScript errors', not errors)
                report['errors'], report['requests'], report['products'] = errors, requests, products
                report['passed'] = True
            browser.close()
    except Exception as error:
        report['error'] = repr(error)
        import traceback
        report['traceback'] = traceback.format_exc()
    finally:
        report['runtime_modules'] = {name: {'file': str(Path(module.__file__).resolve()), 'sha256': sha(module.__file__)}
                                     for name, module in list(sys.modules.items())
                                     if (name == 'easel' or name.startswith('easel.') or name == 'easel_workbench' or name.startswith('easel_workbench.')) and getattr(module, '__file__', None)}
        report['module_roots_valid'] = all(Path(item['file']).is_relative_to(backend) for item in report['runtime_modules'].values())
        report['passed'] &= report['module_roots_valid']
        shutil.copy2(__file__, out / 'harness.py')
        (out / 'interrupted-action-browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'error': report.get('error')}))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
