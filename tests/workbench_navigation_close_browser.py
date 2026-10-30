"""Real Edge close/navigation regressions against immutable UI and TEMP backend.

No application source is injected. TEMP links exercise the installed link adapter;
all browser writes, model turns, installs and platform operations are blocked.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from urllib.parse import parse_qs, urlencode, urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ['web/frontend/src/workbench/platform/navigation.ts',
           'web/frontend/src/workbench/ui/system.tsx',
           'web/frontend/src/workbench/ui/common.tsx',
           'web/frontend/src/workbench/ui/management.tsx']
GOAL = 'TEMP 原始经验目标：保留全部原字  末尾空格  '
DRAFT = 'TEMP 聊天草稿：第一行\n第二行，保留原字  '


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def settle(page):
    page.evaluate('''async()=>{for(let i=0;i<5;i++)await new Promise(requestAnimationFrame)}''')


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
    spec = importlib.util.spec_from_file_location('navigation_close_fixture', ROOT / 'tests/workbench_native_browser.py')
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    fixture.ROOT = backend
    from playwright.sync_api import sync_playwright, expect
    expect.set_options(timeout=12000)
    report = {'passed': False, 'source': {
        'head': subprocess.run(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], capture_output=True, text=True, check=True).stdout.strip(),
        'harness_sha256': sha(__file__), 'files': {path: sha(ROOT / path) for path in SOURCES}},
        'backend': {'release': backend.name, 'manifest_sha256': sha(backend / 'workbench-release.json')},
        'native': {'release': native.name, 'manifest_sha256': sha(native / 'native-manifest.json')},
        'application_source_injected': False, 'physical_mobile_device_tested': False,
        'real_AI_calls': 0, 'real_platform_writes': 0, 'production_data_access': False,
        'temporary_metadata_preparation': [], 'checks': [], 'screenshots': {}, 'blocked_requests': [],
        'synthetic_reads': [], 'not_applicable': [{'state': 'standalone-profile-proposal-modal',
            'reason': 'ProfileProposal is inline in SkillTask inside Experience; the rendered nested candidate and its owning Experience dialog are covered.'}]}

    def mark(profile, scenario, name, passed, **evidence):
        report['checks'].append({'profile': profile, 'scenario': scenario, 'name': name, 'passed': bool(passed), **evidence})
        print(('PASS' if passed else 'FAIL') + ' ' + profile + ' ' + scenario + ': ' + name, flush=True)
        if not passed: print(json.dumps(evidence, ensure_ascii=False), flush=True)

    def shot(page, profile, scenario, state):
        name = '-'.join([profile, scenario, state]) + '.png'
        page.screenshot(path=str(out / name))
        report['screenshots'][name] = {'sha256': sha(out / name), 'profile': profile, 'scenario': scenario, 'state': state}

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
                headless=True, args=['--ignore-certificate-errors'])
            with fixture.isolated(native, b'TEMP unused image') as data:
                data['close_clients'] = lambda: [context.close() for context in browser.contexts]
                for profile, width, height in [('mobile-390', 390, 844), ('desktop-1280', 1280, 900)]:
                    scenarios = [('settings-direct', mode) for mode in ('button', 'escape')]
                    scenarios += [('settings-chat', mode) for mode in ('button', 'escape')]
                    scenarios += [(kind, mode) for kind in ('experience', 'profile-proposal') for mode in ('button', 'escape', 'back', 'external-link')]
                    for kind, mode in scenarios:
                        scenario = kind + '-' + mode
                        context = browser.new_context(ignore_https_errors=True, viewport={'width': width, 'height': height},
                            is_mobile=width < 760, has_touch=width < 760, service_workers='block')
                        context.add_cookies([{'name': '__Host-desk_session', 'value': 'fixture-owner', 'url': data['origin'],
                            'secure': True, 'httpOnly': True, 'sameSite': 'Strict'}])
                        task = 'TEMP-navigation-experience' if kind == 'profile-proposal' else ''
                        context.add_init_script('localStorage.setItem("toolbox:draft:creator:experience",' + json.dumps(json.dumps({
                            'profile_id': 'oil-pig', 'goal': GOAL, 'skill_id': 'content-writing', 'task_id': task, 'work_ids': []}, ensure_ascii=False)) + ')')
                        errors, requests = [], []

                        def route_request(route):
                            request = route.request
                            parsed = urlsplit(request.url)
                            path = parsed.path
                            requests.append({'path': path, 'method': request.method})
                            if parsed.hostname not in ('localhost', '127.0.0.1'):
                                report['blocked_requests'].append({'profile': profile, 'scenario': scenario, 'path': path, 'reason': 'external'})
                                return route.abort()
                            response = None
                            if path == '/api/settings/harness':
                                response = {'runtime': 'codex', 'models': {}, 'sandbox': 'workspace-write', 'locked': False,
                                    'agents': [{'id': 'codex', 'label': 'Codex', 'protocol': 'TEMP', 'installed': True}]}
                            elif path == '/api/settings/models':
                                response = {'channels': {key: {'rows': []} for key in ('chat', 'transcribe', 'speech', 'image', 'video', 'music')}, 'transport': 'api'}
                            elif path == '/api/settings/local-agents': response = {'agents': []}
                            elif path == '/api/env/tools': response = {'tools': [], 'activeJobs': [], 'python': 'TEMP'}
                            elif path == '/api/usage/summary': response = {'config': {'enabled': False}, 'actions': [], 'paths': []}
                            elif path == '/api/creator/experience/TEMP-navigation-experience':
                                response = {'id': 'TEMP-navigation-experience', 'status': 'completed', 'result': {
                                    'analysis': {'summary': 'TEMP 经验结果已完成'}, 'profile_proposal_id': 'TEMP-navigation-proposal'}}
                            elif path == '/api/creator/profile-proposals/TEMP-navigation-proposal':
                                response = {'id': 'TEMP-navigation-proposal', 'status': 'candidate', 'base_revision': 1,
                                    'fields': {'voice': 'TEMP 画像候选原文'}, 'before': {'voice': 'TEMP 原画像'},
                                    'reasons': {'voice': 'TEMP 原始反馈依据'}, 'source_members': ['TEMP-source']}
                            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                                if path == '/api/usage/events': return route.fulfill(status=200, json={'accepted': 0})
                                report['blocked_requests'].append({'profile': profile, 'scenario': scenario, 'path': path, 'reason': 'write forbidden'})
                                return route.fulfill(status=405, json={'error': 'TEMP navigation test prohibits writes'})
                            if response is not None:
                                report['synthetic_reads'].append({'profile': profile, 'scenario': scenario, 'path': path})
                                return route.fulfill(status=200, json=response)
                            route.continue_()

                        context.route('**/*', route_request)
                        page = context.new_page()
                        page.set_default_timeout(12000)
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        link_counter = [0]

                        def go(path):
                            page.goto(data['origin'] + '/native/?' + urlencode({'path': path}), wait_until='domcontentloaded')
                            page.wait_for_selector('.page-host')
                            settle(page)

                        def link(path, scope='#root'):
                            link_counter[0] += 1
                            identity = 'TEMP-navigation-link-' + str(link_counter[0])
                            page.locator(scope).last.evaluate('''(element,{path,identity})=>{const anchor=document.createElement('a');anchor.href=path;anchor.textContent='TEMP navigate to '+path;anchor.id=identity;element.append(anchor)}''', {'path': path, 'identity': identity})
                            expect(page.locator('#' + identity)).to_have_attribute('data-native-path', path)
                            page.locator('#' + identity).click()

                        def wait_closed(selector, expected):
                            try:
                                page.wait_for_function('''({selector,expected})=>new URLSearchParams(location.search).get('path')===expected&&![...document.querySelectorAll(selector)].some(el=>el.getClientRects().length)''',
                                    arg={'selector': selector, 'expected': expected}, timeout=3500)
                            except Exception:
                                pass
                            settle(page)
                            actual = parse_qs(urlsplit(page.url).query).get('path', [None])[0]
                            visible = page.locator(selector).filter(visible=True).count()
                            mark(profile, scenario, 'one close reaches the requested route and unmounts its UI',
                                actual == expected and visible == 0, expected_path=expected, actual_path=actual, visible_layers=visible)
                            mark(profile, scenario, 'accepted close removes the history layer marker',
                                page.evaluate('history.state?.nativeLayer == null'), marker=page.evaluate('history.state?.nativeLayer||null'))

                        try:
                            if kind == 'settings-direct':
                                go('/settings?panel=model')
                                expect(page.locator('.settings-panel')).to_be_visible()
                                shot(page, profile, scenario, 'open')
                                if mode == 'button': page.locator('.settings-close').click()
                                else: page.keyboard.press('Escape')
                                wait_closed('.settings-panel', '/toolbox')
                            elif kind == 'settings-chat':
                                # Only fixture preparation creates local session metadata;
                                # no user turn or browser write is permitted.
                                sid = 'TEMP-nav-' + uuid.uuid4().hex
                                operation = str(uuid.uuid4())
                                csrf = context.request.get(data['origin'] + '/api/config').json()['csrf']
                                prepared = context.request.post(data['origin'] + '/api/chat/sessions',
                                    headers={'Origin': data['origin'], 'X-CSRF-Token': csrf, 'X-Operation-Id': operation},
                                    data={'action': 'create', 'session_id': sid, 'profile_id': 'oil-pig', 'operation_id': operation})
                                assert prepared.ok, prepared.text()
                                report['temporary_metadata_preparation'].append({'profile': profile, 'scenario': scenario, 'session_id': sid, 'status': prepared.status})
                                go('/news')
                                expect(page.locator('[data-native-anchor]').first).to_be_visible()
                                link('/chat/' + sid)
                                textarea = page.get_by_role('textbox', name='对话输入')
                                expect(textarea).to_be_visible()
                                textarea.fill(DRAFT)
                                before = page.evaluate('history.state.nativeNavigation')
                                mark(profile, scenario, 'chat caller retains a real news return anchor',
                                    before.get('returnTo', {}).get('path') == '/news' and bool(before.get('returnTo', {}).get('position', {}).get('anchor')), return_target=before.get('returnTo'))
                                if width < 760: page.locator('.sidebar-toggle').click()
                                page.locator('.settings-gear').click()
                                expect(page.locator('.settings-panel')).to_be_visible()
                                shot(page, profile, scenario, 'open')
                                if mode == 'button': page.locator('.settings-close').click()
                                else: page.keyboard.press('Escape')
                                wait_closed('.settings-panel', '/chat/' + sid)
                                after = page.evaluate('history.state.nativeNavigation')
                                mark(profile, scenario, 'closing settings preserves exact chat draft and return metadata',
                                    textarea.input_value() == DRAFT and after.get('id') == before.get('id') and after.get('returnTo') == before.get('returnTo'),
                                    return_target=after.get('returnTo'), raw_draft_equal=textarea.input_value() == DRAFT)
                            else:
                                # Known caller entry lets browser Back close just the
                                # dialog rather than leave the TEMP application.
                                go('/toolbox?section=skills')
                                link('/toolbox?section=skills&pane=experience')
                                dialog = page.get_by_role('dialog', name='整理经验', exact=True)
                                expect(dialog).to_be_visible()
                                expect(dialog.locator('textarea')).to_have_value(GOAL)
                                if kind == 'profile-proposal':
                                    expect(dialog.get_by_text('画像候选修改', exact=True)).to_be_visible()
                                    dialog.get_by_text('表达方式', exact=True).click()
                                    dialog.locator('summary').filter(has_text=re.compile('^候选$')).click()
                                    expect(dialog.get_by_text('TEMP 画像候选原文', exact=True)).to_be_visible()
                                    mark(profile, scenario, 'actual inline profile proposal is rendered in its owning dialog', True)
                                shot(page, profile, scenario, 'open')
                                expected = '/toolbox?section=skills'
                                if mode == 'button': dialog.get_by_role('button', name='关闭', exact=True).click()
                                elif mode == 'escape': page.keyboard.press('Escape')
                                elif mode == 'back': page.go_back()
                                else:
                                    expected = '/works'
                                    link('/works', 'dialog.ew-dialog .drawer-body')
                                wait_closed('dialog.ew-dialog', expected)
                                raw = page.evaluate('JSON.parse(localStorage.getItem("toolbox:draft:creator:experience")||"{}").goal')
                                mark(profile, scenario, 'closing never clears raw experience input', raw == GOAL)
                            shot(page, profile, scenario, 'closed')
                            mark(profile, scenario, 'no application exception, model or forbidden write',
                                not errors and not data['adapter'].requests and not any(row['profile'] == profile and row['scenario'] == scenario for row in report['blocked_requests']),
                                page_errors=errors, model_turns=len(data['adapter'].requests))
                        except BaseException as error:
                            mark(profile, scenario, 'scenario completes', False, error=repr(error), page_errors=errors)
                            try: shot(page, profile, scenario, 'failure')
                            except Exception: pass
                        finally:
                            context.close()
            browser.close()
    finally:
        report['passed'] = bool(report['checks']) and all(check['passed'] for check in report['checks'])
        report['summary'] = {'passed': sum(check['passed'] for check in report['checks']), 'total': len(report['checks']),
                             'screenshots': len(report['screenshots'])}
        (out / 'navigation-close.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        shutil.copy2(__file__, out / 'harness.py')
        print(json.dumps(report['summary']), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
