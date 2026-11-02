"""Headless Edge return/state acceptance against an immutable native/backend pair.

All data and the HTTPS server are TEMP. No production window, database, model,
installation or platform submission is used. Only account subprocesses and
settings capability reads are synthetic; navigation and rendering use the real
compiled application. Run with --native RELEASE --backend RELEASE --out DIR.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
DRAFT = 'TEMP 未发送原字\n第二行，尾部空格  '
FOLDER = 'TEMP_RETURN 素材目录'
SOURCE_FILES = [
    'web/frontend/src/workbench/platform/navigation.ts',
    'web/frontend/src/workbench/core/client.ts',
    'web/frontend/src/workbench/platform/native-resume.ts',
    'web/frontend/src/components/TrendsPage.tsx',
    'web/frontend/src/components/OutputsPage.tsx',
    'web/frontend/src/components/SkillDrawer.tsx',
    'web/frontend/src/components/ChatPage.tsx',
    'web/frontend/src/components/SettingsPanel.tsx',
    'web/frontend/src/components/ResponsiveSidebar.tsx',
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frozen(directory, name):
    manifest = json.loads((directory / name).read_text(encoding='utf-8'))
    assert manifest.get('files'), 'Missing frozen member hashes'
    for member, digest in manifest['files'].items():
        file = (directory / member).resolve()
        assert file.is_relative_to(directory) and sha(file) == digest, f'Frozen bytes changed: {file}'
    return {'release': manifest.get('release', directory.name), 'directory': str(directory),
            'manifest_sha256': sha(directory / name)}


def seed(data, image):
    """Only prepare metadata/files in the isolated server's own TEMP root."""
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    source, config = next(iter(data['app'].state.collection.registry.baseline().items()))
    data['box'].store.ingest({'schema_version': 1, 'source_job': source, 'feed_id': config['feed'],
        'run_id': 'TEMP-mobile-return', 'run_at': now, 'final_text': 'TEMP only', 'articles': [
            {'title': f'TEMP_RETURN 热点 {n:02d}：保留筛选与滚动位置',
             'body': ('TEMP 原文，非模型生成。\n\n' * 60),
             'url': f'https://example.invalid/return/{n}', 'source_order': n} for n in range(1, 61)]})
    folder = data['root'] / 'outputs' / FOLDER
    folder.mkdir(parents=True)
    (folder / '封面.png').write_bytes(image)
    (folder / '正文.md').write_text('# TEMP_RETURN 文档\n\n仅用于返回验收。', encoding='utf-8')
    session = data['app'].state.chat.create_session({'id': 'TEMP-mobile-return-session',
        'profile_id': 'oil-pig', 'title': 'TEMP 返回与阅读验证'})['session']
    documents = []
    for n in range(24):
        stamp = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=n)).isoformat()
        document = {'id': f'TEMP-return-turn-{n:02d}', 'session_id': session['id'], 'status': 'completed',
            'message': f'TEMP 第 {n} 条原始问题', 'output': f'TEMP 第 {n} 条历史回答\n\n' + ('历史正文保留原字。' * 100),
            'snapshot': {'task': 'discuss'}, 'created_at': stamp, 'updated_at': stamp,
            'runtime': 'codex', 'delivery_state': 'completed'}
        documents.append(document)
    with data['box'].store.connect() as connection:
        for document in documents:
            connection.execute('INSERT INTO easel_chat_turns VALUES(?,?,?,?,?)',
                (document['id'], session['id'], document['id'], 'TEMP metadata only', json.dumps(document, ensure_ascii=False)))
    return {'source': source, 'source_label': config['name'], 'session': session['id'],
            'last_turn': documents[-1], 'folder': FOLDER}


def settings_reads():
    row = {'slot': 'custom', 'name': 'TEMP provider', 'sub': 'TEMP', 'type': 'openai', 'order': 0,
           'model': 'temp-model', 'baseUrl': 'https://example.invalid/v1', 'keyMasked': '', 'role': '主', 'result': '待保存'}
    return {
        '/api/settings/harness': {'runtime': 'api', 'models': {}, 'sandbox': 'workspace-write', 'locked': False,
            'agents': [{'id': 'api', 'label': 'API', 'installed': True, 'protocol': 'TEMP'},
                       {'id': 'codex', 'label': 'Codex', 'installed': True, 'protocol': 'TEMP'}]},
        '/api/settings/models': {'channels': {name: {'rows': [row] if name == 'chat' else []}
            for name in ('chat', 'transcribe', 'speech', 'image', 'video', 'music')}, 'transport': 'api'},
        '/api/settings/local-agents': {'agents': []}, '/api/env/tools': {'tools': [], 'activeJobs': [], 'python': 'TEMP'},
        '/api/usage/summary': {'config': {'enabled': False}, 'actions': [], 'paths': []},
    }


def settle(page):
    page.evaluate('async()=>{for(let n=0;n<5;n++)await new Promise(requestAnimationFrame)}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('native', 'backend', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    native, backend, out = args.native.resolve(), args.backend.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = {'passed': False, 'native': frozen(native, 'native-manifest.json'),
        'backend': frozen(backend, 'workbench-release.json'), 'harness_sha256': sha(__file__),
        'fixture_sha256': sha(ROOT / 'tests/workbench_native_browser.py'),
        'working_source_sha256': {name: sha(ROOT / name) for name in SOURCE_FILES if (ROOT / name).is_file()},
        'checks': [], 'requests': [], 'synthetic_reads': [], 'blocked_requests': [], 'page_errors': [],
        'real_AI_calls': 0, 'real_platform_writes': 0, 'production_data_access': False,
        'application_source_injected': False, 'physical_mobile_device_tested': False}

    def check(name, passed, **evidence):
        report['checks'].append({'name': name, 'passed': bool(passed), **evidence})
        print(('PASS ' if passed else 'FAIL ') + name, flush=True)
        assert passed, json.dumps(evidence, ensure_ascii=False)

    def scenario(name, run):
        try:
            print('START ' + name, flush=True)
            run()
        except Exception as error:
            report['checks'].append({'name': name + ' completes', 'passed': False, 'error': str(error)})
            try: page.screenshot(path=str(out / (name + '-failed.png')))
            except Exception: pass
            print('FAIL ' + name + ': ' + str(error), flush=True)

    try:
        with ExitStack() as stack:
            stack.enter_context(patch.object(sys, 'dont_write_bytecode', True))
            bootstrap = Path(stack.enter_context(tempfile.TemporaryDirectory(prefix='easel-return-bootstrap-')))
            for name in ('sources.json', 'usage_registry.json', 'collection_schedules.json'):
                source = backend / 'easel_workbench/runtime' / name
                if source.is_file(): shutil.copy2(source, bootstrap / name)
            stack.enter_context(patch.dict(os.environ, {'AI_DESK_PROJECT_ROOT': str(bootstrap), 'PYTHONDONTWRITEBYTECODE': '1'}))
            os.environ.pop('AI_DESK_RELEASE', None)
            sys.path.insert(0, str(backend))
            fixture = load_module('mobile_return_fixture', ROOT / 'tests/workbench_native_browser.py')
            fixture.ROOT = backend
            from playwright.sync_api import sync_playwright, expect
            expect.set_options(timeout=12000)
            pw = stack.enter_context(sync_playwright())
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
                headless=True, args=['--ignore-certificate-errors'])
            stack.callback(browser.close)
            image_page = browser.new_page()
            image_page.set_content('<p>TEMP return acceptance only</p>')
            image = image_page.screenshot()
            image_page.close()
            data = stack.enter_context(fixture.isolated(native, image))
            data['close_clients'] = lambda: [context.close() for context in browser.contexts]
            from easel_workbench.runtime.auth_totp import token_hash
            data['auth'].lock = threading.RLock()
            data['auth'].data['sessions'] = {token_hash('fixture-owner'): dict(data['auth'].session('fixture-owner'))}
            data['app'].state.chat_business.upstream.source = backend
            ids = seed(data, image)
            report['seed'] = {key: value for key, value in ids.items() if key != 'last_turn'}
            modules = {name: str(Path(module.__file__).resolve()) for name, module in sys.modules.items()
                       if (name == 'easel' or name.startswith('easel_workbench')) and getattr(module, '__file__', None)}
            assert modules and all(Path(path).is_relative_to(backend) for path in modules.values()), modules
            report['loaded_backend_modules'] = modules
            account_module = load_module('mobile_return_accounts', ROOT / 'tests/workbench_base_browser.py')
            account_context = data['app'].state.easel_accounts.native_context()
            accounts = account_module.SyntheticAccounts(account_context, image)
            fake_process = SimpleNamespace(**{key: getattr(subprocess, key) for key in dir(subprocess) if not key.startswith('__')})
            fake_process.Popen, fake_process.run = accounts.start, accounts.run
            account_context.namespace['subprocess'] = fake_process
            reads = settings_reads()
            context = browser.new_context(ignore_https_errors=True, viewport={'width': 390, 'height': 844},
                is_mobile=True, has_touch=True, service_workers='block')
            context.add_cookies([{'name': '__Host-desk_session', 'value': 'fixture-owner', 'url': data['origin'],
                'secure': True, 'httpOnly': True, 'sameSite': 'Strict'}])

            def route_request(route):
                request, parsed = route.request, urlsplit(route.request.url)
                path = parsed.path
                report['requests'].append({'path': path, 'query': parsed.query, 'method': request.method, 'time': time.monotonic()})
                if parsed.netloc != urlsplit(data['origin']).netloc:
                    report['blocked_requests'].append({'path': path, 'reason': 'external'})
                    return route.abort()
                if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                    if path == '/api/accounts/wechat-oa/mp-login': return route.continue_()
                    if path == '/api/usage/events': return route.fulfill(status=200, json={'accepted': 0})
                    report['blocked_requests'].append({'path': path, 'reason': 'write forbidden'})
                    return route.fulfill(status=405, json={'error': 'TEMP return acceptance forbids writes'})
                if path in reads:
                    report['synthetic_reads'].append(path)
                    return route.fulfill(status=200, json=reads[path])
                route.continue_()

            context.route('**/*', route_request)
            page = context.new_page()
            page.set_default_timeout(12000)
            page.on('pageerror', lambda error: report['page_errors'].append(str(error)))

            def go(path):
                page.goto(data['origin'] + '/native/?' + urlencode({'path': path}), wait_until='domcontentloaded')
                page.wait_for_selector('.page-host')
                settle(page)

            def nav(label):
                if not page.locator('.sidebar-panel').is_visible():
                    page.get_by_role('button', name='打开导航', exact=True).click()
                page.locator('.sidebar-nav').get_by_role('button', name=label, exact=True).click()
                settle(page)

            def back():
                page.evaluate('history.back()')
                settle(page)

            def gets(path):
                return sum(item['method'] == 'GET' and item['path'] == path for item in report['requests'])

            def news_return():
                go('/news?sources=' + ids['source'])
                rows = page.locator('.trend-item')
                # The native backend intentionally caps each source at thirty
                # items even if the caller asks for a larger limit.
                page.wait_for_function('()=>document.querySelectorAll(".trend-item").length>=30')
                # Exercise the real filter setter as well as a URL declaration.
                label = page.locator('.trend-platforms button[aria-pressed=true]').first.inner_text()
                chosen = page.locator('.trend-platforms').get_by_role('button', name=label, exact=True)
                chosen.click()
                expect(chosen).to_have_attribute('aria-pressed', 'false')
                chosen.click()
                expect(chosen).to_have_attribute('aria-pressed', 'true')
                page.wait_for_function('()=>document.querySelectorAll(".trend-item").length>=30')
                chips = page.locator('.trend-platforms button[aria-pressed=true]')
                selected = chips.all_text_contents()
                page.locator('.trends-page').evaluate('(el)=>el.scrollTop=1050')
                settle(page)
                before = page.locator('.trends-page').evaluate('(el)=>el.scrollTop')
                # Pick an already visible article; clicking must not change the
                # saved viewport through an automated scroll-into-view action.
                visible = page.locator('.trend-title').evaluate_all('els=>els.findIndex(el=>{const r=el.getBoundingClientRect();return r.top>100&&r.bottom<innerHeight-30})')
                assert visible >= 0
                counts = {path: gets(path) for path in ('/api/trends', '/api/trends/sources')}
                page.locator('.trend-title').nth(visible).click()
                expect(page.locator('.ew-news-reading')).to_be_visible()
                back()
                expect(page.locator('.trends-page')).to_be_visible()
                page.wait_for_function('(value)=>Math.abs(document.querySelector(".trends-page").scrollTop-value)<8', arg=before)
                check('news Back retains filter and ready scroll without repeated GET',
                    chips.all_text_contents() == selected and all(gets(path) == count for path, count in counts.items()),
                    before_scroll=before, after_scroll=page.locator('.trends-page').evaluate('(el)=>el.scrollTop'),
                    before_GET=counts, after_GET={path: gets(path) for path in counts})
                check('compact news uses one page scroll rather than nested capped list',
                    page.locator('.trend-list').first.evaluate('(el)=>el.scrollHeight<=el.clientHeight+1'))

            def outputs_return():
                go('/works')
                page.locator('.gcard').filter(has=page.get_by_text(FOLDER, exact=True)).click()
                page.locator('.gallery-filters').get_by_role('button', name='文档', exact=True).click()
                expect(page.locator('.gcard-name', has_text='正文.md')).to_be_visible()
                count = gets('/api/outputs')
                nav('账号')
                expect(page.locator('.accounts-page')).to_be_visible()
                back()
                expect(page.locator('.gallery-page')).to_be_visible()
                check('library Back retains directory/filter and fresh tree cache',
                    page.locator('.gcard-name', has_text='正文.md').is_visible()
                    and not page.locator('.gcard-name', has_text='封面.png').count()
                    and gets('/api/outputs') == count,
                    before_GET=count, after_GET=gets('/api/outputs'))

            def skill_return():
                go('/toolbox?section=skills')
                search = page.get_by_placeholder('搜索技能名或描述…')
                expect(page.locator('.skills-page')).to_have_attribute('data-catalog-state', 'ready')
                search.fill('ai-image-gen')
                page.locator('.skill-card').first.click()
                field = page.get_by_placeholder('输入内容，例如主题 / 素材 / 要求…')
                expect(field).to_be_visible()
                field.fill(DRAFT)
                back()
                expect(field).not_to_be_visible()
                count = gets('/api/skills')
                nav('内容库')
                expect(page.locator('.gallery-page')).to_be_visible()
                back()
                expect(search).to_have_value('ai-image-gen')
                page.locator('.skill-card').first.click()
                expect(field).to_have_value(DRAFT)
                check('skills Back retains query and exact unsent input without catalog reload',
                    gets('/api/skills') == count, before_GET=count, after_GET=gets('/api/skills'))
                back()

            def layer_return():
                go('/toolbox?section=distribution&pane=connections')
                expect(page.locator('.accounts-page')).to_be_visible()
                path = parse_qs(urlsplit(page.url).query).get('path')
                page.get_by_role('button', name='打开导航', exact=True).click()
                expect(page.locator('.sidebar-panel')).to_be_visible()
                back()
                expect(page.locator('.sidebar-panel')).not_to_be_visible()
                check('browser Back closes Sidebar before changing the page', parse_qs(urlsplit(page.url).query).get('path') == path)
                card = page.locator('.account-card').filter(has=page.locator('.account-card-name', has_text='微信公众号'))
                card.get_by_role('button', name='登录', exact=True).click()
                expect(page.locator('.accounts-page > .overlay')).to_be_visible()
                expect(page.get_by_text('请扫码', exact=False)).to_be_visible()
                calls = len(accounts.calls)
                back()
                expect(page.locator('.accounts-page > .overlay')).not_to_be_visible()
                check('browser Back closes QR without starting another login or leaving accounts',
                    len(accounts.calls) == calls and parse_qs(urlsplit(page.url).query).get('path') == path,
                    synthetic_login_processes=calls)

            def settings_guard():
                go('/settings?panel=model')
                expect(page.locator('.settings-panel')).to_be_visible()
                field = page.get_by_label('TEMP provider API Key', exact=True)
                field.fill('TEMP-SECRET-NOT-A-CREDENTIAL')
                dialogs = []
                def reject(dialog):
                    dialogs.append(dialog.message)
                    dialog.dismiss()
                page.once('dialog', reject)
                page.locator('.settings-close').click()
                expect(field).to_have_value('TEMP-SECRET-NOT-A-CREDENTIAL')
                check('settings leave guard rejects close once and retains in-memory input', len(dialogs) == 1)
                stored = page.evaluate('JSON.stringify({...localStorage})+JSON.stringify({...sessionStorage})')
                check('settings secret draft is absent from browser persistent storage', 'TEMP-SECRET-NOT-A-CREDENTIAL' not in stored)
                page.once('dialog', lambda dialog: (dialogs.append(dialog.message), dialog.accept()))
                page.locator('.settings-close').click()
                expect(page.locator('.settings-panel')).not_to_be_visible()
                check('confirmed settings leave does not prompt twice', len(dialogs) == 2)

            def chat_scroll_probe():
                go('/chat/' + ids['session'])
                field = page.get_by_role('textbox', name='对话输入')
                expect(field).to_be_visible()
                messages = page.locator('.chat-messages')
                expect(messages).to_be_visible()
                page.wait_for_function('()=>{const el=document.querySelector(".chat-messages");return el.scrollHeight>el.clientHeight*2}')
                messages.evaluate('(el)=>el.scrollTop=Math.min(600,el.scrollHeight-el.clientHeight-300)')
                # Native scroll handler establishes whether the reader follows
                # the bottom. This is a real DOM scroll, not a state mock.
                page.wait_for_timeout(150)
                before = messages.evaluate('(el)=>el.scrollTop')
                document = dict(ids['last_turn'])
                document['output'] += '\n\nTEMP_RETURN 新内容到达，阅读位置不能被拉到底。'
                document['updated_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
                with data['box'].store.connect() as connection:
                    connection.execute('UPDATE easel_chat_turns SET document=? WHERE id=?',
                        (json.dumps(document, ensure_ascii=False), document['id']))
                expect(page.get_by_text('TEMP_RETURN 新内容到达，阅读位置不能被拉到底。', exact=False)).to_be_attached(timeout=40000)
                settle(page)
                after = messages.evaluate('(el)=>el.scrollTop')
                check('chat scrolled-up reader is not pulled down by new server content', abs(before-after) < 10,
                    before_scroll=before, after_scroll=after)
                count = gets('/native/version')
                field.press_sequentially('TEMP typing twenty keys', delay=30)
                page.wait_for_timeout(300)
                check('version probe is not issued per keystroke', gets('/native/version') - count <= 1,
                    probe_delta=gets('/native/version') - count, keys=23)
                background = context.new_page()
                background.goto('about:blank')
                background.bring_to_front()
                hidden = page.evaluate('document.hidden')
                before = gets('/native/version')
                page.bring_to_front()
                page.wait_for_timeout(500)
                check('foreground return coalesces version probes', gets('/native/version') - before <= 1,
                    actual_document_hidden=hidden, probe_delta=gets('/native/version') - before,
                    note='Headless focus is not physical WebToApp app suspension')
                background.close()

            for name, run in [('news-return', news_return), ('outputs-return', outputs_return),
                ('skills-return', skill_return), ('layer-back', layer_return),
                ('settings-guard', settings_guard), ('chat-scroll-probe', chat_scroll_probe)]:
                scenario(name, run)
            check('no application runtime exceptions', not report['page_errors'], errors=report['page_errors'])
            attempted_writes = [item for item in report['blocked_requests'] if item['reason'] == 'write forbidden']
            check('no model or unexpected write was executed', not data['adapter'].requests and not attempted_writes,
                model_calls=len(data['adapter'].requests), blocked_writes=attempted_writes)
            report['synthetic_account_processes'] = accounts.calls
            page.screenshot(path=str(out / 'mobile-return-final.png'))
            report['passed'] = all(item['passed'] for item in report['checks'])
    except Exception as error:
        report['error'] = str(error)
        print('ERROR ' + str(error), flush=True)
    finally:
        (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    raise SystemExit(0 if report['passed'] else 1)


if __name__ == '__main__':
    main()
