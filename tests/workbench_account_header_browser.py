"""Narrow account-header delta against a frozen UI and TEMP account drivers.

Actual default seven-card catalog and original QR service/UI are used. Only the
account subprocess is synthetic. No UI/CSS/data-response replacement is made.
Historical full-matrix evidence remains explicitly bound to the older bundle.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
CSS = 'web/frontend/src/workbench/ui/styles/mobile.css'
FIXTURES = ['tests/workbench_native_browser.py', 'tests/workbench_base_browser.py']


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def verify(directory, manifest_name):
    manifest = load(directory / manifest_name)
    for name, digest in manifest['files'].items():
        member = (directory / name).resolve()
        assert member.is_relative_to(directory) and sha(member) == digest, ('Immutable member changed', name)
    return manifest


HEADER = """element=>{
 const header=element.firstElementChild,button=header.querySelector(':scope > .btn');
 const title=header.querySelector('.page-title'),description=header.querySelector('.page-subtitle');
 const box=node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height,scrollWidth:node.scrollWidth,clientWidth:node.clientWidth}};
 const lines=node=>{const range=document.createRange();range.selectNodeContents(node);return [...range.getClientRects()].filter(r=>r.width&&r.height).map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height}))};
 const buttonBox=box(button),label=lines(button),style=getComputedStyle(button);
 const center={x:buttonBox.left+buttonBox.width/2,y:buttonBox.top+buttonBox.height/2};
 const hit=document.elementFromPoint(center.x,center.y);
 return {rootOverflow:document.documentElement.scrollWidth-innerWidth,viewport:{width:innerWidth,height:innerHeight},
   header:box(header),button:buttonBox,title:box(title),description:box(description),
   label:button.textContent,buttonLines:label,buttonLineTops:[...new Set(label.map(r=>Math.round(r.top)))],
   textStyles:{whiteSpace:style.whiteSpace,flexShrink:style.flexShrink,lineHeight:style.lineHeight,fontSize:style.fontSize},
   titleLines:lines(title),descriptionLines:lines(description),descriptionWhiteSpace:getComputedStyle(description).whiteSpace,
   hit:button===hit||button.contains(hit),buttonCenter:center};
}"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', required=True, type=Path)
    parser.add_argument('--backend', required=True, type=Path)
    parser.add_argument('--previous-native', required=True, type=Path)
    parser.add_argument('--previous-backend', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    args = parser.parse_args()
    native, backend, previous, old_backend, out = [getattr(args, name).resolve() for name in ('native', 'backend', 'previous_native', 'previous_backend', 'out')]
    out.mkdir(parents=True, exist_ok=True)
    report = {'passed': False, 'scope': 'Account header delta, actual seven cards and original synthetic QR open/close only.',
        'native': {'release': native.name, 'manifest_sha256': sha(native / 'native-manifest.json')},
        'backend': {'release': backend.name, 'manifest_sha256': sha(backend / 'workbench-release.json')},
        'previous_native': {'release': previous.name, 'manifest_sha256': sha(previous / 'native-manifest.json')},
        'previous_backend': {'release': old_backend.name, 'manifest_sha256': sha(old_backend / 'workbench-release.json')},
        'source': {'head': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
                   'harness_sha256': sha(__file__), 'fixtures': {p: sha(ROOT / p) for p in FIXTURES}},
        'checks': [], 'screenshots': {}, 'requests': [], 'blocked_requests': [], 'page_errors': [],
        'application_source_injected': False, 'UI_or_CSS_overridden': False, 'account_catalog_response_mocked': False,
        'real_AI_calls': 0, 'real_platform_writes': 0, 'real_installations': 0, 'production_data_access': False,
        'physical_mobile_device_tested': False,
        'historical_full_matrix_reexecuted_on_this_bundle': False,
        'historical_reference': '705 delegated checks and full matrix remain actual executions on native192342; this report adds only account-header delta evidence.'}

    def mark(case, name, passed, **evidence):
        report['checks'].append({'case': case, 'name': name, 'passed': bool(passed), **evidence})
        print(('PASS' if passed else 'FAIL') + ' ' + case + ' ' + name, flush=True)

    def shot(page, case, state):
        name = case + '-' + state + '.png'
        page.screenshot(path=str(out / name))
        report['screenshots'][name] = {'sha256': sha(out / name), 'case': case, 'state': state}

    try:
        verify(native, 'native-manifest.json'); verify(previous, 'native-manifest.json')
        current_backend = verify(backend, 'workbench-release.json'); prior_backend = verify(old_backend, 'workbench-release.json')
        inputs, old_inputs = load(native / 'build-inputs.json')['inputs'], load(previous / 'build-inputs.json')['inputs']
        assert set(inputs) == set(old_inputs) and len(inputs) == 144
        changed = {path: {'previous': old_inputs[path], 'current': inputs[path]} for path in inputs if inputs[path] != old_inputs[path]}
        assert set(changed) == {CSS}, ('UI delta is not confined to private mobile.css', changed)
        assert all(sha(ROOT / path) == digest for path, digest in inputs.items())
        assert current_backend['files'] == prior_backend['files'] and len(current_backend['files']) == 1103
        assert all((backend / path).read_bytes() == (old_backend / path).read_bytes() for path in current_backend['files'])
        report['delta_binding'] = {'build_input_count': 144, 'unchanged_build_inputs': 143, 'changed_build_inputs': changed,
            'new_source_matches_all_build_inputs': True, 'backend_actual_member_count': 1103, 'backend_actual_member_bytes_equal': True,
            'backend_metadata_changes': [key for key in current_backend if current_backend[key] != prior_backend.get(key)]}
        sys.path.insert(0, str(backend))
        fixture = module('account_header_native_fixture', ROOT / FIXTURES[0]); fixture.ROOT = backend
        account_fixture = module('account_header_driver_fixture', ROOT / FIXTURES[1])
        from PIL import Image, ImageDraw
        from playwright.sync_api import sync_playwright, expect
        expect.set_options(timeout=12000)
        picture = Image.new('RGB', (256, 256), 'white'); ImageDraw.Draw(picture).text((12, 115), 'TEMP synthetic QR - do not scan', fill='black')
        buffer = io.BytesIO(); picture.save(buffer, format='PNG'); image = buffer.getvalue()
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True, args=['--ignore-certificate-errors'])
            with fixture.isolated(native, image) as f:
                f['close_clients'] = lambda: [context.close() for context in browser.contexts]
                from easel_workbench.runtime.auth_totp import token_hash
                f['auth'].lock = threading.RLock()
                f['auth'].data['sessions'] = {token_hash('fixture-owner'): dict(f['auth'].session('fixture-owner'))}
                account_context = f['app'].state.easel_accounts.native_context()
                synthetic = account_fixture.SyntheticAccounts(account_context, image)
                fake_process = SimpleNamespace(**{key: getattr(subprocess, key) for key in dir(subprocess) if not key.startswith('__')})
                fake_process.Popen, fake_process.run = synthetic.start, synthetic.run
                account_context.namespace['subprocess'] = fake_process
                for width, height in [(320, 844), (360, 844), (390, 844), (430, 844), (844, 390), (1440, 900)]:
                    for theme in ('light', 'dark'):
                        case = f'{width}x{height}-{theme}'; compact = width <= 900
                        errors = []; reads = []; writes = []
                        context = browser.new_context(ignore_https_errors=True, viewport={'width': width, 'height': height},
                            is_mobile=compact, has_touch=compact, color_scheme=theme, service_workers='block')
                        context.add_cookies([{'name': '__Host-desk_session', 'value': 'fixture-owner', 'url': f['origin'], 'secure': True, 'httpOnly': True, 'sameSite': 'Strict'}])
                        context.add_init_script('localStorage.setItem("native:theme",' + json.dumps(theme) + ');localStorage.setItem("easel_theme",' + json.dumps(theme) + ')')

                        def route_request(route):
                            request = route.request; parsed = urlsplit(request.url); path = parsed.path
                            row = {'case': case, 'method': request.method, 'path': path}; report['requests'].append(row)
                            if parsed.hostname not in ('localhost', '127.0.0.1'):
                                report['blocked_requests'].append(row); return route.abort()
                            if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                                if path == '/api/usage/events': return route.fulfill(status=200, json={'accepted': 0})
                                if not (path.startswith('/api/accounts/') and path.endswith('/mp-login')):
                                    report['blocked_requests'].append(row); return route.fulfill(status=405, json={'error': 'TEMP header audit forbids this action'})
                                writes.append(row)
                            if path == '/api/accounts' and request.method == 'GET': reads.append(row)
                            route.continue_()

                        context.route('**/*', route_request)
                        page = context.new_page(); page.on('pageerror', lambda error: errors.append(str(error)))
                        try:
                            page.goto(f['origin'] + '/native/?' + urlencode({'path': '/toolbox?section=distribution&pane=connections'}), wait_until='domcontentloaded')
                            accounts = page.locator('.accounts-page'); expect(accounts).to_be_visible()
                            expect(page.locator('.account-card')).to_have_count(7)
                            expect(page.locator('html')).to_have_attribute('data-theme', theme)
                            refresh = page.locator('.accounts-page > div:first-child > .btn')
                            refresh.scroll_into_view_if_needed()
                            metrics = accounts.evaluate(HEADER)
                            shot(page, case, 'header')
                            h, b = metrics['header'], metrics['button']
                            mark(case, 'header and document do not overflow horizontally', metrics['rootOverflow'] <= 1 and h['scrollWidth'] <= h['clientWidth'] + 1 and h['left'] >= -1 and h['right'] <= width + 1, metrics=metrics)
                            mark(case, 'refresh label is one intact visible line', metrics['label'].strip() == '⟳ 刷新' and len(metrics['buttonLineTops']) == 1 and all(r['left'] >= b['left'] - 1 and r['right'] <= b['right'] + 1 for r in metrics['buttonLines']))
                            mark(case, 'refresh is hit reachable with compact44px target', metrics['hit'] and (not compact or (b['width'] >= 44 and b['height'] >= 44)), box=b, desktop44px_requirement='not applicable; original desktop btn-sm geometry preserved' if not compact else None)
                            mark(case, 'title and description retain natural wrapping without clipping', all(metrics[key]['scrollWidth'] <= metrics[key]['clientWidth'] + 1 for key in ('title', 'description')) and len(metrics['descriptionLines']) >= 2 and metrics['descriptionWhiteSpace'] in ('normal', 'pre-wrap'), title_lines=metrics['titleLines'], description_lines=metrics['descriptionLines'])
                            before = len(reads)
                            with page.expect_response(lambda response: urlsplit(response.url).path == '/api/accounts' and response.request.method == 'GET'):
                                if compact: refresh.tap()
                                else: refresh.click()
                            expect(page.locator('.account-card')).to_have_count(7)
                            mark(case, 'one real refresh activation performs exactly one catalog GET', len(reads) == before + 1, before=before, after=len(reads), trusted_input='tap' if compact else 'click')
                            card_info = []
                            for card in page.locator('.account-card').all():
                                card.scroll_into_view_if_needed()
                                info = card.evaluate('''el=>{const r=el.getBoundingClientRect(),button=el.querySelector('button'),b=button.getBoundingClientRect(),hit=document.elementFromPoint(b.left+b.width/2,b.top+b.height/2);return {name:el.querySelector('.account-card-name').textContent,width:r.width,scrollWidth:el.scrollWidth,clientWidth:el.clientWidth,left:r.left,right:r.right,buttonWidth:b.width,buttonHeight:b.height,buttonLabel:button.textContent,disabled:button.disabled,hit:button===hit||button.contains(hit),buttonCount:el.querySelectorAll('button').length}}''')
                                card_info.append(info)
                            mark(case, 'all seven original cards and login controls remain reachable', len(card_info) == 7 and all(c['buttonCount'] == 1 and c['buttonLabel'].strip() == '登录' and c['hit'] and c['scrollWidth'] <= c['clientWidth'] + 1 and (not compact or c['buttonHeight'] >= 44 and c['buttonWidth'] >= 44) for c in card_info), cards=card_info)
                            shot(page, case, 'last-cards')
                            card = page.locator('.account-card').filter(has=page.locator('.account-card-name', has_text='微信公众号'))
                            login = card.get_by_role('button', name='登录', exact=True); login.scroll_into_view_if_needed()
                            if compact: login.tap()
                            else: login.click()
                            modal = page.locator('.overlay > .modal'); expect(modal).to_be_visible()
                            qr = modal.get_by_alt_text('登录二维码', exact=True); expect(qr).to_be_visible()
                            qr.evaluate('img=>img.decode()')
                            mark(case, 'original QR path reaches decoded qr_ready without success claim', qr.evaluate('img=>img.complete&&img.naturalWidth>0') and '请扫码' in modal.inner_text() and '登录成功' not in modal.inner_text(), synthetic_process_count=len(synthetic.calls))
                            close = modal.get_by_role('button', name='关闭', exact=True); close.scroll_into_view_if_needed()
                            geometry = close.evaluate('''el=>{const r=el.getBoundingClientRect(),m=el.closest('.modal').getBoundingClientRect(),hit=document.elementFromPoint(r.left+r.width/2,r.top+r.height/2);return {width:r.width,height:r.height,hit:el===hit||el.contains(hit),left:m.left,right:m.right,top:m.top,bottom:m.bottom}}''')
                            mark(case, 'QR close stays in viewport and retains compact44px target', geometry['hit'] and geometry['left'] >= -1 and geometry['right'] <= width + 1 and (not compact or geometry['height'] >= 44 and geometry['width'] >= 44), geometry=geometry)
                            shot(page, case, 'QR-ready')
                            if compact: close.tap()
                            else: close.click()
                            expect(modal).not_to_be_visible(); expect(card.get_by_role('button', name='登录', exact=True)).to_be_visible()
                            mark(case, 'closing QR returns to the same seven-card account page', page.locator('.account-card').count() == 7 and len(writes) == 1 and writes[0]['path'].endswith('/mp-login'))
                            mark(case, 'no runtime error, external connection, model or unexpected operation', not errors and not f['adapter'].requests and not any(row['case'] == case for row in report['blocked_requests']), errors=errors)
                        except Exception as error:
                            mark(case, 'scenario completed', False, error=repr(error)); shot(page, case, 'failure')
                        finally:
                            report['page_errors'].extend({'case': case, 'error': error} for error in errors)
                            context.close()
                            if synthetic.current: synthetic.finish('expired', 'TEMP synthetic case cleanup')
                report['synthetic_account_processes'] = len(synthetic.calls)
                assert not f['adapter'].requests
            browser.close()
        report['passed'] = len({item['case'] for item in report['checks']}) == 12 and all(item['passed'] for item in report['checks'])
    except Exception as error:
        report['error'] = repr(error)
    finally:
        report['runtime_modules'] = {name: {'file': str(Path(value.__file__).resolve()), 'sha256': sha(value.__file__)}
            for name, value in list(sys.modules.items()) if (name == 'easel' or name.startswith('easel.') or name == 'easel_workbench' or name.startswith('easel_workbench.')) and getattr(value, '__file__', None)}
        report['module_roots_valid'] = all(Path(info['file']).is_relative_to(backend) for info in report['runtime_modules'].values())
        if report['runtime_modules'] and not report['module_roots_valid']: report['passed'] = False
        shutil.copy2(__file__, out / 'harness.py')
        (out / 'account-header.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'screenshots': len(report['screenshots']), 'error': report.get('error')}, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
