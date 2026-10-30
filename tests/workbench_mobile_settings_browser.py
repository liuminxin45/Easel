"""Expanded settings/mobile coverage using real Edge, frozen UI and TEMP data.

Catalogs, environment checks and job polls are explicitly synthetic. Save,
self-test, installer, clear and account/model execution requests are blocked.
Viewport shrink is an emulated keyboard layout change, not a physical IME test.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
CHANNELS = [('chat', '对话与脚本'), ('transcribe', '语音转写'), ('speech', '配音'), ('image', '生图'), ('video', '视频'), ('music', '音乐')]
LABELS = {'api': '仅聊天模式', 'openclaw': 'OpenClaw', 'opencode': 'OpenCode', 'codex': 'Codex', 'acp': '通用 ACP'}
SOURCES = ['web/frontend/src/components/SettingsPanel.tsx', 'web/frontend/src/components/HarnessSettings.tsx',
           'web/frontend/src/components/SettingsSelect.tsx', 'web/frontend/src/components/EnvBoard.tsx',
           'web/frontend/src/components/Sidebar.tsx', 'web/frontend/src/workbench/ui/system.tsx']
LONG_MODEL = 'TEMP-provider/' + 'long-model-label-' * 8
LONG_URL = 'https://temp.invalid/' + 'long-private-compatible-api-path/' * 6
FAKE_KEY = 'TEMP-NOT-A-CREDENTIAL-ONLY-LIVE-FORM'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', required=True, type=Path)
    parser.add_argument('--backend', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    native, backend, out = args.native.resolve(), args.backend.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    for directory, name in [(native, 'native-manifest.json'), (backend, 'workbench-release.json')]:
        manifest = json.loads((directory / name).read_text(encoding='utf-8'))
        assert all(sha(directory / path) == digest for path, digest in manifest['files'].items()), 'Frozen package bytes changed'
    sys.path.insert(0, str(backend))
    spec = importlib.util.spec_from_file_location('mobile_settings_fixture', ROOT / 'tests/workbench_native_browser.py')
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    fixture.ROOT = backend
    from easel import harnesses
    from playwright.sync_api import sync_playwright, expect
    expect.set_options(timeout=12000)
    report = {'passed': False, 'source': {'head': subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip(),
                                        'harness_sha256': sha(__file__), 'files': {path: sha(ROOT / path) for path in SOURCES}},
              'backend': {'release': backend.name, 'manifest_sha256': sha(backend / 'workbench-release.json')},
              'native': {'release': native.name, 'manifest_sha256': sha(native / 'native-manifest.json')},
              'checks': [], 'screenshots': {}, 'covered_states': {}, 'not_applicable': [
                  {'surface_id': 'settings.environment', 'state': 'expand_install_detail', 'reason': 'EnvBoard has no details expander; actual foot-status text/title are tested.'},
                  {'surface_id': 'nav.selectors', 'state': 'native_popup_dom_bounds', 'reason': 'Sidebar uses native select; OS/browser popup is outside the DOM. Control, options, open screenshot and Escape are tested.'}],
              'physical_mobile_device_tested': False, 'real_AI_calls': 0, 'real_installations': 0, 'real_platform_writes': 0,
              'production_data_access': False, 'synthetic_catalog_requests': [], 'blocked_requests': [], 'profiles': []}

    def mark(profile, surface_id, state, name, passed=True, **evidence):
        report['checks'].append({'profile': profile, 'surface_id': surface_id, 'state': state, 'name': name, 'passed': bool(passed), **evidence})
        if passed:
            covered = report['covered_states'].setdefault(surface_id, [])
            if state not in covered: covered.append(state)
        print(('PASS' if passed else 'FAIL') + ' ' + profile + ' ' + surface_id + '/' + state + ' ' + name, flush=True)

    def screenshot(page, profile, surface_id, state):
        name = profile + '-' + surface_id.replace('.', '-') + '-' + re.sub(r'[^A-Za-z0-9_-]', '-', state) + '.png'
        page.screenshot(path=str(out / name))
        report['screenshots'][name] = {'sha256': sha(out / name), 'profile': profile, 'surface_id': surface_id, 'state': state}

    def inspect(page, profile, surface_id, state, selector='.settings-panel'):
        scope = page.locator(selector).last
        expect(scope).to_be_visible()
        info = scope.evaluate('''element=>{
          const r=element.getBoundingClientRect(),v=visualViewport;
          const width=v?.width||innerWidth,height=v?.height||innerHeight;
          const failures=[];
          for(const node of element.querySelectorAll('button,input,select,textarea,[role=button],.prow:not(.head),.settings-field,.card')){
            if(!node.getClientRects().length)continue;
            const b=node.getBoundingClientRect();if(!b.width||!b.height)continue;
            let left=0,right=width,parent=node.parentElement;
            while(parent&&parent!==document.body){
              const s=getComputedStyle(parent),p=parent.getBoundingClientRect();
              if(s.overflowX==='hidden'||s.overflowX==='clip'){left=Math.max(left,p.left);right=Math.min(right,p.right)}
              if((s.overflowX==='auto'||s.overflowX==='scroll')&&parent.scrollWidth>parent.clientWidth+1){
                // A deliberate horizontal scroller may reveal an off-screen
                // target, but cannot reveal a control wider than its viewport.
                if(b.width>p.width+2)failures.push({kind:'wider-than-scrollport',tag:node.tagName,label:node.getAttribute('aria-label')||node.className,width:b.width,limit:p.width});
                left=-Infinity;right=Infinity;break;
              }
              parent=parent.parentElement;
            }
            if(b.left<left-2||b.right>right+2)failures.push({kind:'horizontal-clip',tag:node.tagName,label:node.getAttribute('aria-label')||node.className,left:b.left,right:b.right,clip:[left,right]});
          }
          return {viewport:{width,height},box:{left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height},
            rootOverflow:document.documentElement.scrollWidth-innerWidth,scopeOverflow:element.scrollWidth-element.clientWidth,
            controls:element.querySelectorAll('button,input,select,textarea,[role=button]').length,failures:failures.slice(0,30)};
        }''')
        box, viewport = info['box'], info['viewport']
        passed = info['rootOverflow'] <= 1 and box['left'] >= -1 and box['right'] <= viewport['width'] + 1 and not info['failures']
        mark(profile, surface_id, state, 'actual expanded DOM has no horizontal clipping', passed, layout=info)
        screenshot(page, profile, surface_id, state)
        return info

    def reach(page, profile, state, locator, surface_id='settings.panel'):
        locator.scroll_into_view_if_needed(timeout=3000)
        info = locator.evaluate('''element=>{const r=element.getBoundingClientRect(),x=r.left+r.width/2,y=r.top+r.height/2,hit=document.elementFromPoint(x,y);return {label:element.getAttribute('aria-label')||element.textContent,left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height,hit:!!hit&&(hit===element||element.contains(hit)),hit_tag:hit?.tagName,hit_class:hit?.className,viewport:{width:innerWidth,height:innerHeight}}}''')
        mark(profile, surface_id, state, 'named control is visible and hit-test reachable', info['width'] > 0 and info['height'] > 0 and info['left'] >= -1 and info['right'] <= info['viewport']['width'] + 1 and info['top'] >= -1 and info['bottom'] <= info['viewport']['height'] + 1 and info['hit'], target=info)

    def menu(page, profile, state, trigger, label=None):
        trigger.click()
        popup = page.get_by_role('listbox', name=label, exact=True) if label else page.get_by_role('listbox').last
        expect(popup).to_be_visible()
        inspect(page, profile, 'settings.options', state, '[role=listbox]')
        box = popup.bounding_box()
        mark(profile, 'settings.options', state, 'popup stays vertically inside the active viewport', box['y'] >= 7 and box['y'] + box['height'] <= page.viewport_size['height'] - 7)
        return popup

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True, args=['--ignore-certificate-errors'])
            with fixture.isolated(native, b'TEMP unused image') as data, patch.object(harnesses, 'describe', lambda runtime: {'id': runtime, 'label': LABELS[runtime], 'installed': True, 'protocol': 'TEMP synthetic capabilities', 'install_hint': 'TEMP CLI instruction ' + LONG_MODEL}):
                data['close_clients'] = lambda: [context.close() for context in browser.contexts]
                for profile, width, height, theme in [('mobile-320-light', 320, 800, 'light'), ('mobile-390-dark', 390, 844, 'dark'), ('landscape-844-light', 844, 390, 'light')]:
                    report['profiles'].append({'id': profile, 'width': width, 'height': height, 'theme': theme, 'is_mobile': True, 'has_touch': True})
                    context = browser.new_context(ignore_https_errors=True, viewport={'width': width, 'height': height}, is_mobile=True, has_touch=True, color_scheme=theme, service_workers='block')
                    context.add_cookies([{'name': '__Host-desk_session', 'value': 'fixture-owner', 'url': data['origin'], 'secure': True, 'httpOnly': True, 'sameSite': 'Strict'}])
                    flags = {'missing': False, 'empty_usage': False, 'job_polls': {}}
                    bootstrap = context.request.get(data['origin'] + '/api/creator/bootstrap').json()
                    bootstrap['profiles'].extend({'id': f'TEMP-role-{number}', 'name': f'TEMP 画像 {number} ' + ('long-profile-name-' * 12 if number == 10 else '')} for number in range(24))

                    def mock(route):
                        request = route.request
                        parsed = urlsplit(request.url)
                        path = parsed.path
                        if parsed.hostname not in ('localhost', '127.0.0.1'):
                            report['blocked_requests'].append({'profile': profile, 'path': path, 'reason': 'nonlocal network'})
                            return route.abort()
                        response = None
                        if path == '/api/settings/harness' and request.method == 'GET':
                            response = {'runtime': 'codex', 'models': {}, 'sandbox': 'workspace-write', 'codex_auto_approve': False, 'locked': False,
                                        'agents': [{'id': key, 'label': label, 'protocol': 'TEMP synthetic protocol', 'installed': not (flags['missing'] and key == 'opencode'), 'install_hint': LONG_MODEL} for key, label in LABELS.items()]}
                        elif path == '/api/settings/models' and request.method == 'GET':
                            runtime = parse_qs(parsed.query).get('runtime', ['codex'])[0]
                            channels = {}
                            for channel, _ in CHANNELS:
                                channels[channel] = {'rows': [{'slot': 'direct-api' if channel == 'chat' and runtime == 'api' and number == 0 else 'custom' if channel == 'chat' else 'openai',
                                    'order': number + 1, 'name': f'TEMP-{channel}-{number}', 'sub': 'TEMP synthetic provider', 'type': 'openai',
                                    'model': LONG_MODEL + str(number), 'baseUrl': LONG_URL, 'keyMasked': 'TEMP ****', 'role': '主' if number == 0 else '备',
                                    'result': '已配置', 'protocol': 'openai', 'thinking': False, 'thinkingFormat': 'openai',
                                    **({'key2Label': 'SecretKey', 'key2Masked': 'TEMP ****'} if channel == 'speech' and number == 0 else {})} for number in range(2)]}
                            response = {'channels': channels, 'primary': 'TEMP', 'transport': 'api' if runtime == 'api' else 'openclaw'}
                        elif path.startswith('/api/settings/harness/models/') or path == '/api/settings/models/available':
                            report['synthetic_catalog_requests'].append({'profile': profile, 'path': path})
                            response = {'runtime': path.rsplit('/', 1)[-1], 'models': [{'id': LONG_MODEL + str(number), 'label': LONG_MODEL + str(number), 'default': number == 0} for number in range(24)]} if '/harness/models/' in path else {'models': [LONG_MODEL + str(number) for number in range(24)]}
                        elif path == '/api/settings/local-agents':
                            response = {'agents': [{'id': 'TEMP-agent', 'label': 'TEMP 长名称本地 Agent', 'installed': True, 'supported': True, 'configured': False,
                                                   'path': 'C:/TEMP/' + 'long-path/' * 15, 'loginHint': 'TEMP synthetic only', 'models': [{'id': 'TEMP-model', 'name': LONG_MODEL}]}]}
                        elif path == '/api/env/tools':
                            response = {'python': 'C:/TEMP/' + 'long-isolated-runtime-path/' * 10 + 'python.exe',
                                'activeJobs': [{'id': 'ffmpeg', 'jobId': 'TEMP-running'}, {'id': 'pw', 'jobId': 'TEMP-failed'}],
                                'tools': [{'id': key, 'name': 'TEMP ' + key + ' ' + ('long-tool-name-' * 4), 'state': state, 'version': LONG_MODEL if state == 'ok' else None,
                                           'detail': 'TEMP failure detail ' + LONG_URL if state == 'fail' else None, 'desc': 'TEMP capability description ' + LONG_MODEL,
                                           'group': group, 'installable': key not in ('node', 'python'), 'scope': 'project_local'}
                                          for key, state, group in [('node', 'ok', 'rm'), ('python', 'ok', 'common'), ('rmdeps', 'missing', 'rm'), ('ffmpeg', 'missing', 'rm'), ('pw', 'fail', 'pub')]]}
                        elif path.startswith('/api/env/job/'):
                            job = path.rsplit('/', 1)[-1]
                            polls = flags['job_polls'].get(job, 0)
                            flags['job_polls'][job] = polls + 1
                            response = {'jobId': job, 'id': 'pw' if job == 'TEMP-failed' else 'ffmpeg', 'state': 'fail' if job == 'TEMP-failed' else 'running',
                                        'lines': ['TEMP failed detail ' + LONG_URL] if job == 'TEMP-failed' else ['TEMP 排队中 ' + LONG_URL if polls == 0 else 'TEMP running ' + LONG_URL],
                                        'result': {'detail': 'TEMP failure detail ' + LONG_URL} if job == 'TEMP-failed' else None}
                        elif path == '/api/usage/summary':
                            response = {'config': {'enabled': False}, 'actions': [] if flags['empty_usage'] else [{'id': 'TEMP-action-' + str(number), 'label': 'TEMP 长操作名称 ' + LONG_MODEL, 'activate': number, 'accepted': number, 'uncertain': 0} for number in range(8)],
                                        'paths': [] if flags['empty_usage'] else [{'from': 'TEMP/from/' + LONG_MODEL, 'to': 'TEMP/to/' + LONG_MODEL, 'count': 3}]}
                        elif path == '/api/creator/bootstrap' and request.method == 'GET':
                            response = bootstrap
                        elif request.method not in ('GET', 'HEAD', 'OPTIONS') and path != '/api/usage/events':
                            report['blocked_requests'].append({'profile': profile, 'path': path, 'reason': 'unexpected action'})
                            return route.fulfill(status=405, json={'error': 'TEMP settings inspection prohibits this action'})
                        if response is not None: return route.fulfill(status=200, json=response)
                        route.continue_()

                    context.route('**/*', mock)
                    page = context.new_page()
                    page.set_default_timeout(12000)
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))

                    def go(path):
                        page.goto(data['origin'] + '/native/?' + urlencode({'path': path}), wait_until='domcontentloaded')

                    def open_sidebar_settings():
                        if width <= 760: page.locator('.sidebar-toggle').click()
                        gear = page.locator('.settings-gear')
                        box = gear.bounding_box()
                        if box and (box['y'] < 0 or box['y'] + box['height'] > page.viewport_size['height']):
                            # A low-height expanded sidebar may intentionally
                            # scroll. Prove reachability with a trusted swipe.
                            sidebar = page.locator('.sidebar')
                            scroll_before = sidebar.evaluate('element=>element.scrollTop')
                            session = context.new_cdp_session(page)
                            session.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [{'x': 150, 'y': 290}]})
                            for step in range(1, 9):
                                session.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [{'x': 150, 'y': 290 - step * 20}]})
                                page.wait_for_timeout(20)
                            session.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
                            page.wait_for_timeout(500)
                            mark(profile, 'nav.selectors', 'landscape_sidebar_scroll', 'trusted touch reveals the bottom settings entry', sidebar.evaluate('element=>element.scrollTop') > scroll_before)
                            box = gear.bounding_box()
                        reachable = bool(box and box['y'] >= 0 and box['y'] + box['height'] <= page.viewport_size['height'] + 1)
                        mark(profile, 'nav.selectors', 'settings_button', 'sidebar bottom settings entry is touch reachable at this height', reachable, box=box)
                        screenshot(page, profile, 'nav.selectors', 'sidebar-bottom')
                        if not reachable: raise AssertionError('sidebar settings remains unreachable after native touch')
                        gear.click()
                        expect(page.get_by_role('dialog', name='设置', exact=True)).to_be_visible()

                    def choose_runtime(runtime):
                        popup = menu(page, profile, 'engine_dropdown-' + runtime, page.get_by_role('button', name='执行引擎', exact=True), '执行引擎')
                        popup.get_by_role('option', name=re.compile('^' + re.escape(LABELS[runtime]))).click()
                        expect(page.get_by_role('button', name='执行引擎', exact=True)).to_contain_text(LABELS[runtime])

                    def stage(name, action):
                        try: action()
                        except BaseException as error:
                            mark(profile, 'settings.panel', name, 'scenario completed', False, error=repr(error))
                            screenshot(page, profile, 'settings.panel', name + '-failure')

                    def navigation():
                        go('/news')
                        page.wait_for_selector('.trends-page')
                        if width <= 760: page.locator('.sidebar-toggle').click()
                        select = page.locator('select.persona-select')
                        expect(select).to_be_visible()
                        before = select.input_value()
                        mark(profile, 'nav.selectors', 'profile_options', 'native selector has populated long options', select.locator('option').count() >= 25)
                        reach(page, profile, 'profile_options', select, 'nav.selectors')
                        select.click()
                        screenshot(page, profile, 'nav.selectors', 'profile-options-open')
                        page.keyboard.press('Escape')
                        mark(profile, 'nav.selectors', 'profile_options', 'closing native option popup preserves the selected profile', select.input_value() == before)
                        # Selector inspection already opened the narrow drawer.
                        if width <= 760: page.locator('.sidebar-close').click()
                        open_sidebar_settings()
                        expect(page.get_by_role('dialog', name='设置', exact=True)).to_be_visible()
                        inspect(page, profile, 'settings.panel', 'model_section')
                        for name, locator in [('close', page.locator('.settings-close')), ('save', page.get_by_role('button', name='保存配置', exact=True))]:
                            reach(page, profile, 'header-' + name, locator)

                    def engines():
                        go('/settings?panel=model')
                        expect(page.get_by_role('button', name='执行引擎', exact=True)).to_be_enabled()
                        for runtime in ('codex', 'opencode', 'acp', 'api', 'openclaw'):
                            choose_runtime(runtime)
                            if runtime in ('codex', 'opencode', 'acp'):
                                model = page.locator('#harness-model')
                                model.fill(LONG_MODEL)
                                reach(page, profile, runtime + '-model', model, 'settings.harness')
                            if runtime in ('codex', 'opencode'):
                                page.locator('.harness-settings').get_by_role('button', name='拉取模型', exact=True).click()
                                popup = menu(page, profile, runtime + '-long-native-models', page.get_by_role('button', name='原生模型', exact=True), '原生模型')
                                mark(profile, 'settings.options', 'long_labels', 'native catalog has 24 long model labels', popup.get_by_role('option').count() >= 24)
                                page.keyboard.press('End'); page.keyboard.press('Home'); page.keyboard.press('Escape')
                            if runtime == 'codex':
                                menu(page, profile, 'sandbox_dropdown', page.get_by_role('button', name='Codex 沙箱', exact=True), 'Codex 沙箱')
                                page.keyboard.press('Escape')
                                permission = page.get_by_role('switch', name='永久通过授权', exact=True)
                                reach(page, profile, 'codex_sandbox_approval', permission, 'settings.harness')
                                permission.click(); permission.click()
                            help_button = page.get_by_role('button', name='仅聊天模式说明', exact=True)
                            help_button.scroll_into_view_if_needed(); help_button.focus()
                            expect(page.get_by_role('tooltip')).to_be_visible()
                            inspect(page, profile, 'settings.harness', runtime + '-help', '[role=tooltip]')
                            page.locator('.settings-title').click()
                            inspect(page, profile, 'settings.harness', runtime, '.harness-settings')
                        flags['missing'] = True
                        page.locator('.harness-settings').get_by_role('button', name='重新读取', exact=True).click()
                        choose_runtime('opencode')
                        expect(page.get_by_text('未检测到 OpenCode。', exact=False)).to_be_visible()
                        mark(profile, 'settings.harness', 'missing_cli', 'missing CLI preview cannot save', page.get_by_role('button', name='保存底座', exact=True).is_disabled())
                        inspect(page, profile, 'settings.harness', 'missing_cli', '.harness-settings')
                        flags['missing'] = False

                    def channels():
                        go('/settings?panel=model')
                        expect(page.get_by_role('button', name='执行引擎', exact=True)).to_be_enabled()
                        choose_runtime('api')
                        for channel, label in CHANNELS:
                            page.get_by_role('button', name=label, exact=True).click()
                            expect(page.locator('.board .prow:not(.head)').first).to_contain_text('TEMP-' + channel)
                            while page.get_by_role('button', name='高级', exact=True).count(): page.get_by_role('button', name='高级', exact=True).first.click()
                            inputs = page.locator('.board input')
                            for field in inputs.all():
                                if field.get_attribute('type') == 'checkbox': continue
                                label_text = field.get_attribute('aria-label') or ''
                                value = FAKE_KEY if field.get_attribute('type') == 'password' else LONG_URL if 'API 地址' in label_text else LONG_MODEL
                                field.fill(value)
                            if page.get_by_role('listbox').count(): page.keyboard.press('Escape')
                            page.locator('.settings-title').click()
                            inspect(page, profile, 'settings.channels', channel)
                            for field in inputs.all():
                                if field.get_attribute('type') != 'checkbox':
                                    page.locator('.settings-title').click()
                                    reach(page, profile, channel + '-field', field, 'settings.channels')
                            model_cell = page.locator('.board .model-cell').first
                            if model_cell.count():
                                page.locator('.settings-title').click()
                                model_cell.locator('.fetch-btn').click()
                                popup = page.get_by_role('listbox').last
                                expect(popup.get_by_role('option')).to_have_count(24)
                                inspect(page, profile, 'settings.options', channel + '-provider-models', '[role=listbox]')
                                page.keyboard.press('Escape')
                            mark(profile, 'settings.channels', channel, 'live synthetic key is absent from browser persistence', not page.evaluate('(key)=>Object.values(localStorage).some(value=>value.includes(key))', FAKE_KEY))
                        page.get_by_role('button', name='对话与脚本', exact=True).click()
                        choose_runtime('openclaw')
                        add = page.locator('.add-row')
                        expect(add).to_be_visible()
                        count = page.locator('.board .prow:not(.head)').count()
                        add.click()
                        row = page.locator('.board .prow:not(.head)').last
                        row.locator('.pname input').fill('TEMP ' + 'long-provider-name-' * 5)
                        row.locator('.model-cell input').first.fill(LONG_MODEL)
                        if page.get_by_role('listbox').count(): page.keyboard.press('Escape')
                        inspect(page, profile, 'settings.channels', 'provider-added')
                        mark(profile, 'settings.channels', 'provider_advanced_fields', 'adding a custom provider retains a complete editable row', page.locator('.board .prow:not(.head)').count() == count + 1)
                        menu(page, profile, 'protocol_dropdown', row.locator('.proto-trigger[role=button]'))
                        page.get_by_role('option', name='anthropic（原生 /v1/messages）', exact=True).click()
                        menu(page, profile, 'protocol_dropdown-openai', row.locator('.proto-trigger[role=button]'))
                        page.get_by_role('option', name='openai（OpenAI 兼容）', exact=True).click()
                        row.get_by_role('checkbox').check()
                        menu(page, profile, 'thinking-format', row.get_by_role('button', name=re.compile('思考格式$')))
                        page.keyboard.press('Escape')

                    def environment():
                        go('/settings?panel=env')
                        expect(page.locator('.st-env [data-tool]')).to_have_count(5)
                        inspect(page, profile, 'settings.environment', 'tool_groups', '.st-env')
                        for key in ('node', 'python'):
                            mark(profile, 'settings.environment', 'installed_missing', key + ' is a fixed runtime', page.locator('[data-tool=' + key + '] button').is_disabled())
                        page.wait_for_timeout(1700)
                        inspect(page, profile, 'settings.environment', 'queued_jobs', '.st-env')
                        page.wait_for_timeout(1700)
                        inspect(page, profile, 'settings.environment', 'running_failed_jobs', '.st-env')
                        failed = page.locator('[data-tool=pw] .foot-status')
                        mark(profile, 'settings.environment', 'long_paths', 'actual failure detail/title retains the long synthetic diagnostic', 'TEMP failure detail' in (failed.get_attribute('title') or ''))
                        for control in page.locator('.st-env button').all(): reach(page, profile, 'install-control-visible-no-install', control, 'settings.environment')
                        mark(profile, 'settings.environment', 'progress', 'environment progress is a real rendered named progressbar', page.get_by_role('progressbar', name='环境就绪进度').count() == 1)

                    def more():
                        go('/settings?panel=more')
                        expect(page.get_by_role('heading', name='使用与路径', exact=True)).to_be_visible()
                        inspect(page, profile, 'settings.usage', 'usage_table_populated')
                        details = page.locator('.settings-panel details').filter(has=page.locator('summary', has_text='常走路径'))
                        details.locator('summary').click()
                        inspect(page, profile, 'settings.usage', 'paths_details')
                        page.get_by_role('button', name='清空统计', exact=True).click()
                        confirm = page.get_by_role('dialog', name='清空操作统计？', exact=True)
                        expect(confirm).to_be_visible()
                        inspect(page, profile, 'settings.clear-usage', 'confirm_text', 'dialog.ew-dialog')
                        reach(page, profile, 'nested_focus', confirm.get_by_role('button', name='确认清空统计', exact=True), 'settings.clear-usage')
                        page.keyboard.press('Tab'); page.keyboard.press('Shift+Tab')
                        mark(profile, 'settings.clear-usage', 'nested_focus', 'focus remains inside native confirmation', confirm.evaluate('element=>element.contains(document.activeElement)'))
                        page.keyboard.press('Escape')
                        expect(confirm).not_to_be_visible()
                        mark(profile, 'settings.clear-usage', 'cancel', 'Escape returns to parent settings without a clear request', page.get_by_role('dialog', name='设置', exact=True).is_visible())
                        flags['empty_usage'] = True
                        page.get_by_role('button', name='刷新', exact=True).click()
                        expect(page.locator('.ew-table-wrap tbody tr')).to_have_count(0)
                        inspect(page, profile, 'settings.usage', 'empty_summary')

                    def keyboard_and_return():
                        go('/news')
                        page.wait_for_selector('.trends-page')
                        open_sidebar_settings()
                        expect(page.get_by_role('button', name='执行引擎', exact=True)).to_be_enabled()
                        model = page.locator('#harness-model')
                        model.fill(LONG_MODEL)
                        page.set_viewport_size({'width': width, 'height': max(260, height - 300)})
                        reach(page, profile, 'viewport_resize', model, 'settings.options')
                        inspect(page, profile, 'settings.panel', 'keyboard-shrunken')
                        mark(profile, 'settings.options', 'viewport_resize', 'simulated keyboard shrink retains the live model input', model.input_value() == LONG_MODEL)
                        page.set_viewport_size({'width': width, 'height': height})
                        menu(page, profile, 'viewport_resize', page.get_by_role('button', name='执行引擎', exact=True), '执行引擎')
                        page.set_viewport_size({'width': width, 'height': max(260, height - 300)})
                        inspect(page, profile, 'settings.options', 'viewport-resized-menu', '[role=listbox]')
                        page.keyboard.press('Escape')
                        expect(page.get_by_role('dialog', name='设置', exact=True)).to_be_visible()
                        mark(profile, 'settings.options', 'keyboard_escape', 'Escape closes only the child dropdown')
                        page.set_viewport_size({'width': width, 'height': height})
                        controls = page.locator('.settings-panel').locator('button:not(:disabled),input:not(:disabled),select:not(:disabled),[tabindex="0"]').filter(visible=True)
                        controls.last.focus(); page.keyboard.press('Tab')
                        mark(profile, 'settings.panel', 'focus_loop', 'Tab from last control remains in settings', page.locator('.settings-panel').evaluate('element=>element.contains(document.activeElement)'))
                        page.keyboard.press('Escape')
                        expect(page.get_by_role('dialog', name='设置', exact=True)).not_to_be_visible()
                        go('/news')
                        page.wait_for_selector('.trends-page')
                        open_sidebar_settings()
                        expect(page.get_by_role('dialog', name='设置', exact=True)).to_be_visible()
                        page.locator('.settings-close').click()
                        expect(page.get_by_role('dialog', name='设置', exact=True)).not_to_be_visible()
                        mark(profile, 'settings.panel', 'escape_restore', 'close returns to the exact prior news page', parse_qs(urlsplit(page.url).query).get('path') == ['/news'])

                    try:
                        for name, action in [('navigation', navigation), ('engines', engines), ('channels', channels), ('environment', environment), ('more', more), ('keyboard-return', keyboard_and_return)]: stage(name, action)
                        mark(profile, 'settings.panel', 'runtime', 'no page errors, model turns, installs, saves or platform actions', not errors and not data['adapter'].requests and not any(row['profile'] == profile for row in report['blocked_requests']), errors=errors)
                    finally: context.close()
            browser.close()
        report['passed'] = bool(report['checks']) and all(row['passed'] for row in report['checks'])
    except BaseException as error:
        report['error'] = repr(error)
    finally:
        (out / 'settings-browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        (out / 'harness.py').write_bytes(Path(__file__).read_bytes())
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'screenshots': len(report['screenshots']), 'error': report.get('error')}, ensure_ascii=True), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
