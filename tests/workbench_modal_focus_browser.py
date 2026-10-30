"""Native div-modal focus regression: real shared UI plus adapter lifecycle units.

All application state is TEMP. --inject-source is diagnostic only and is recorded;
omit it to validate the adapter actually compiled into a frozen candidate.
"""
from __future__ import annotations
import argparse
from datetime import date
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'web/frontend/src/workbench/platform/modal-focus.ts'


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def compiled_adapter():
    code = "const fs=require('fs'),ts=require(process.argv[2]);process.stdout.write(ts.transpileModule(fs.readFileSync(process.argv[1],'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022}}).outputText.replace(/^export /gm,''))"
    return subprocess.run(['C:/Users/38482/AppData/Local/nvm/v24.19.0/node.exe', '-e', code, str(SOURCE), str(ROOT / 'web/frontend/node_modules/typescript')], capture_output=True, text=True, encoding='utf-8', check=True).stdout


def settle(page):
    page.evaluate('''async()=>{for(let n=0;n<4;n++)await new Promise(requestAnimationFrame)}''')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', required=True, type=Path)
    parser.add_argument('--backend', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--inject-source', action='store_true')
    parser.add_argument('--source-unit-only', action='store_true')
    args = parser.parse_args()
    native, backend, out = args.native.resolve(), args.backend.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(backend))
    spec = importlib.util.spec_from_file_location('modal_fixture', ROOT / 'tests/workbench_native_browser.py')
    h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h); h.ROOT = backend
    from playwright.sync_api import sync_playwright, expect
    expect.set_options(timeout=15000)
    source = compiled_adapter()
    report = {'passed': False, 'native': {'release': native.name, 'manifest_sha256': sha(native / 'native-manifest.json')},
              'backend': {'release': backend.name, 'manifest_sha256': sha(backend / 'workbench-release.json')},
              'source': {'harness_sha256': sha(__file__), 'adapter_sha256': sha(SOURCE)}, 'source_injected_into_application': args.inject_source,
              'application_scenarios_run': not args.source_unit_only,
              'physical_device_tested': False, 'real_AI_calls': 0, 'real_platform_writes': 0, 'checks': [], 'screenshots': {}}
    def check(profile, state, passed, **evidence):
        report['checks'].append({'profile': profile, 'state': state, 'passed': bool(passed), **evidence})
        print(('PASS' if passed else 'FAIL') + ' ' + profile + ' ' + state, flush=True)
    def snap(page, profile, state):
        path = out / (profile + '-' + state + '.png'); page.screenshot(path=str(path)); report['screenshots'][path.name] = sha(path)
    def inject(page): page.evaluate('()=>{' + source + ';window.releaseModalFixture=bindNativeModalFocus()}')
    def focus_boundary(page, selector, last):
        return page.locator(selector).evaluate('''(root,last)=>{
          const nodes=[...root.querySelectorAll('a[href],button,input,select,textarea,summary,[tabindex]')].filter(el=>el.tabIndex>=0&&!el.matches(':disabled')&&!el.closest('[inert]')&&el.getClientRects().length&&getComputedStyle(el).visibility!=='hidden');
          const target=last?nodes.at(-1):nodes[0];target?.focus();return {count:nodes.length,label:target?.textContent||target?.getAttribute('aria-label')};
        }''', last)
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True, args=['--ignore-certificate-errors'])
            seed = browser.new_page(); seed.set_content('TEMP modal image'); image = seed.screenshot(); seed.close()
            with h.isolated(native, image) as f:
                f['close_clients'] = lambda: [context.close() for context in browser.contexts]
                f['box'].create({'id': 'TEMP-focus-work', 'title': 'TEMP 焦点作品', 'material': 'TEMP', 'format': 'poster', 'files': []})
                artifact = f['root'] / 'data/artifacts/TEMP-focus-image.png'; artifact.parent.mkdir(parents=True, exist_ok=True); artifact.write_bytes(image)
                with f['box'].store.connect() as connection:
                    connection.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)', ('TEMP-focus-image', 'TEMP-focus-work', '成品.png', str(artifact), 'image/png'))
                for profile, width, height in ([] if args.source_unit_only else [('320-portrait', 320, 800), ('844-compact', 844, 844), ('844-landscape', 844, 390)]):
                    context = browser.new_context(ignore_https_errors=True, viewport={'width': width, 'height': height}, is_mobile=True, has_touch=True)
                    context.add_cookies([{'name': '__Host-desk_session', 'value': 'fixture-owner', 'url': f['origin'], 'secure': True, 'httpOnly': True, 'sameSite': 'Strict'}])
                    page = context.new_page()
                    def go(path):
                        page.goto(f['origin'] + '/native/?' + urlencode({'path': path}), wait_until='domcontentloaded')
                        page.wait_for_selector('.page-host'); settle(page)
                        if args.inject_source: inject(page)
                        page.evaluate('''()=>{const button=document.createElement('button');button.id='TEMP-background-button';button.textContent='TEMP background';document.body.append(button);const saved=document.createElement('aside');saved.id='TEMP-preserved-inert';saved.setAttribute('inert','preserve-original');document.body.append(saved)}''')
                    def verify(state, selector, closer):
                        panel = page.locator(selector); expect(panel).to_be_visible(); settle(page)
                        check(profile, state + '-initial-focus', panel.evaluate('element=>element.contains(document.activeElement)'), active=page.evaluate('({tag:document.activeElement.tagName,class:document.activeElement.className})'))
                        check(profile, state + '-background-inert', page.locator('#TEMP-background-button').get_attribute('inert') is not None)
                        positions = page.locator('.page-scroll,.skills-page').evaluate_all('nodes=>nodes.map(element=>({top:element.scrollTop,left:element.scrollLeft}))')
                        info = focus_boundary(page, selector, False); page.keyboard.press('Shift+Tab')
                        check(profile, state + '-reverse-tab-loop', info['count'] > 0 and panel.evaluate('element=>element.contains(document.activeElement)'))
                        check(profile, state + '-reverse-tab-visible-without-background-scroll', panel.evaluate('''element=>{const target=document.activeElement,a=target.getBoundingClientRect(),b=element.getBoundingClientRect(),hit=document.elementFromPoint(a.left+a.width/2,a.top+a.height/2);return a.top>=Math.max(0,b.top)-1&&a.bottom<=Math.min(innerHeight,b.bottom)+1&&!!hit&&(hit===target||target.contains(hit))}''') and positions == page.locator('.page-scroll,.skills-page').evaluate_all('nodes=>nodes.map(element=>({top:element.scrollTop,left:element.scrollLeft}))'))
                        info = focus_boundary(page, selector, True); page.keyboard.press('Tab')
                        check(profile, state + '-forward-tab-loop', info['count'] > 0 and panel.evaluate('element=>element.contains(document.activeElement)'))
                        check(profile, state + '-forward-tab-visible-without-background-scroll', panel.evaluate('''element=>{const target=document.activeElement,a=target.getBoundingClientRect(),b=element.getBoundingClientRect(),hit=document.elementFromPoint(a.left+a.width/2,a.top+a.height/2);return a.top>=Math.max(0,b.top)-1&&a.bottom<=Math.min(innerHeight,b.bottom)+1&&!!hit&&(hit===target||target.contains(hit))}''') and positions == page.locator('.page-scroll,.skills-page').evaluate_all('nodes=>nodes.map(element=>({top:element.scrollTop,left:element.scrollLeft}))'))
                        snap(page, profile, state)
                        closer.click(); expect(panel).not_to_be_visible(); settle(page)
                        check(profile, state + '-original-inert-restored', page.locator('#TEMP-background-button').get_attribute('inert') is None and page.locator('#TEMP-preserved-inert').get_attribute('inert') == 'preserve-original')
                    try:
                        go('/toolbox?section=research'); page.get_by_role('button', name='+ 新建选题', exact=True).click()
                        verify('idea', '.overlay > .modal', page.locator('.modal .icon-btn').first)
                        go('/toolbox?section=calendar'); page.locator('.cal-cell').first.click()
                        verify('calendar', '.overlay > .modal', page.locator('.modal .icon-btn').first)
                        go('/works?' + urlencode({'path': '__workbench__/TEMP-focus-image/成品.png'}))
                        expect(page.locator('.drawer img')).to_be_visible()
                        page.wait_for_function("()=>{const image=document.querySelector('.drawer img');return image?.complete&&image.naturalWidth>0}")
                        verify('output', '.drawer-overlay > .drawer', page.locator('.drawer-header .icon-btn').first)
                        go('/toolbox?section=skills'); page.locator('.skill-card').first.click()
                        expect(page.locator('.drawer .skill-body-md')).to_contain_text(re.compile(r'\S'))
                        verify('skill', '.drawer-overlay > .drawer', page.locator('.drawer button[title="关闭"]').first)
                        check(profile, 'no-model-or-platform-operation', not f['adapter'].requests)
                    except BaseException as error:
                        check(profile, 'application-scenarios-complete', False, error=repr(error)); snap(page, profile, 'failure')
                    finally: context.close()

            # Lifecycle checks run the exact source adapter in a clean browser
            # document, separately from frozen-application integration checks.
            context = browser.new_context(viewport={'width': 390, 'height': 800})
            page = context.new_page()
            page.set_content('<div class="native-host"><button id="open">Open</button><aside id="preserved" inert="original"><button>old inert</button></aside><section id="background"><button>background</button></section><div id="mount"></div></div>')
            page.locator('#open').focus(); inject(page)
            page.evaluate('''()=>document.getElementById('mount').innerHTML='<div class="overlay"><div class="modal" style="height:180px;overflow:auto"><button id="first">close</button><button id="portal-trigger" aria-controls="portal" aria-expanded="false">options</button><div style="height:600px">long modal body</div><button id="last">last</button></div></div>' '''); settle(page)
            check('source-unit', 'initial-focus', page.locator('#first').evaluate('element=>element===document.activeElement'))
            page.locator('#first').focus(); page.keyboard.press('Shift+Tab')
            check('source-unit', 'reverse-tab-scrolls-last-control-into-modal-view', page.locator('#last').evaluate('element=>{const a=element.getBoundingClientRect(),b=element.closest(".modal").getBoundingClientRect();return element===document.activeElement&&a.top>=b.top&&a.bottom<=b.bottom}'))
            page.locator('#last').focus(); page.keyboard.press('Tab')
            check('source-unit', 'forward-tab-scrolls-first-control-into-modal-view', page.locator('#first').evaluate('element=>{const a=element.getBoundingClientRect(),b=element.closest(".modal").getBoundingClientRect();return element===document.activeElement&&a.top>=b.top&&a.bottom<=b.bottom}'))
            page.locator('#portal-trigger').focus()
            page.evaluate('''()=>{const portal=document.createElement('div');portal.id='portal';portal.className='model-dd';portal.setAttribute('role','listbox');portal.innerHTML='<button id="option" role="option" tabindex="-1">option</button>';portal.hidden=true;document.body.append(portal)}'''); settle(page)
            check('source-unit', 'preexisting-closed-portal-is-background-inert', page.locator('#portal').get_attribute('inert') is not None)
            page.evaluate('''()=>{document.getElementById('portal').hidden=false;document.getElementById('portal-trigger').setAttribute('aria-expanded','true')}'''); settle(page)
            page.locator('#option').click()
            check('source-unit', 'portal-option-remains-interactive', page.locator('#portal').get_attribute('inert') is None and page.locator('#background').get_attribute('inert') is not None)
            page.evaluate('''()=>{document.getElementById('portal').hidden=true;document.getElementById('portal-trigger').setAttribute('aria-expanded','false');const dialog=document.createElement('dialog');dialog.id='native';dialog.innerHTML='<button id="native-button">native modal</button>';document.body.append(dialog);dialog.showModal()}'''); settle(page)
            check('source-unit', 'closed-portal-returns-to-background-isolation', page.locator('#portal').get_attribute('inert') is not None)
            page.locator('#native-button').click()
            check('source-unit', 'native-dialog-keeps-ownership', page.locator('#native').get_attribute('inert') is None and page.locator('#native-button').evaluate('element=>element===document.activeElement'))
            page.evaluate('document.getElementById("native").close();document.getElementById("native").remove()'); settle(page)
            page.evaluate('''()=>{window.modalLayoutReads=0;const modal=document.querySelector('.overlay'),original=modal.getClientRects.bind(modal);modal.getClientRects=()=>{window.modalLayoutReads++;return original()};const stream=document.createElement('p');stream.id='stream';document.querySelector('.modal').append(stream)}'''); settle(page)
            before = page.evaluate('window.modalLayoutReads')
            page.evaluate('''()=>{for(let n=0;n<200;n++)document.getElementById('stream').append(document.createTextNode('token'))}'''); settle(page)
            check('source-unit', 'streaming-text-does-not-rescan-layout', page.evaluate('window.modalLayoutReads') == before)
            for owner in ('settings-panel', 'sidebar-panel'):
                page.evaluate('''owner=>{const host=document.createElement('div');host.id='higher-owner';host.className=owner==='settings-panel'?'settings-overlay':owner;const panel=owner==='settings-panel'?document.createElement('div'):host;if(panel!==host)host.append(panel);panel.className=owner;panel.setAttribute('aria-modal','true');panel.innerHTML='<button id="higher-focus">higher owner</button>';document.querySelector('.native-host').append(host);document.getElementById('higher-focus').focus()}''', owner); settle(page)
                check('source-unit', owner + '-retains-own-initial-focus', page.locator('#higher-focus').evaluate('element=>element===document.activeElement') and page.locator('#higher-owner').get_attribute('inert') is None)
                page.evaluate('document.getElementById("higher-owner").remove()'); settle(page)
            page.evaluate('window.releaseModalFixture()'); settle(page)
            check('source-unit', 'unmount-restores-exact-inert-and-focus', page.locator('#background').get_attribute('inert') is None and page.locator('#preserved').get_attribute('inert') == 'original' and page.locator('#open').evaluate('element=>element===document.activeElement'))
            inject(page); settle(page); page.set_viewport_size({'width': 1440, 'height': 900}); settle(page)
            check('source-unit', 'desktop-resize-releases-private-modal-trap', page.locator('#background').get_attribute('inert') is None)
            page.set_viewport_size({'width': 390, 'height': 800}); settle(page)
            page.evaluate('''()=>{document.querySelector('.overlay').getClientRects=()=>{throw Error('TEMP layout failure')};document.querySelector('.overlay').classList.add('TEMP-change')}'''); settle(page)
            check('source-unit', 'layout-exception-releases-background-inert', page.locator('#background').get_attribute('inert') is None and page.locator('#preserved').get_attribute('inert') == 'original')
            page.evaluate('window.releaseModalFixture();document.querySelector(".overlay").remove();document.getElementById("portal").remove()'); inject(page); settle(page)
            page.evaluate('''()=>{const brush=document.createElement('div');brush.className='brush-panel';brush.innerHTML='<button>nonmodal tool</button>';document.getElementById('mount').append(brush)}'''); settle(page)
            check('source-unit', 'nonmodal-brush-does-not-lock-background', page.locator('#background').get_attribute('inert') is None)
            page.evaluate('window.releaseModalFixture()'); context.close(); browser.close()
        report['passed'] = bool(report['checks']) and all(row['passed'] for row in report['checks'])
    except BaseException as error: report['error'] = repr(error)
    finally:
        (out / 'modal-focus.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        (out / 'harness.py').write_bytes(Path(__file__).read_bytes())
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'error': report.get('error')}, ensure_ascii=True), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__': raise SystemExit(main())
