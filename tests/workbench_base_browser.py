"""TEMP full-stack acceptance for the shared Easel UI and native HTTP protocols.

Only injected synthetic account processes run. No model, production database,
real account login, platform submission or physical mobile device is involved.
An optional default-app build is served against the same TEMP data for visual
comparison; its exact directory is recorded rather than called official by fiat.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit, parse_qs
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def fixture_module(backend):
    sys.path.insert(0, str(backend))
    spec = importlib.util.spec_from_file_location('base_browser_fixture', ROOT / 'tests/workbench_native_browser.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = backend
    return module


class SyntheticAccounts:
    def __init__(self, context, image):
        self.context, self.image, self.calls = context, image, []
        self.current = None

    def start(self, command, **_):
        self.calls.append(list(command))
        status = Path(command[command.index('--status-file') + 1])
        qr = Path(command[command.index('--qr-out') + 1])
        status.parent.mkdir(parents=True, exist_ok=True)
        qr.write_bytes(self.image)
        owner = self
        class Process:
            returncode = None
            def poll(self): return self.returncode
            def terminate(self): self.returncode = -15
            def kill(self): self.returncode = -9
            def wait(self, timeout=None):
                if self.returncode is None:
                    raise subprocess.TimeoutExpired(command, timeout)
                return self.returncode
        process = Process()
        self.current = (process, status)
        self.finish('qr_ready', 'TEMP 合成二维码，请勿作为真实平台登录证据', running=True)
        return process

    def finish(self, state, message='', running=False):
        process, status = self.current
        status.write_text(json.dumps({'state': state, 'message': message, 'ts': int(time.time())}), encoding='utf-8')
        if not running: process.returncode = 0 if state == 'success' else 1

    def run(self, command, **_):
        platform = 'wechat-oa' if 'weixin_mp_stats.py' in ' '.join(command) else 'other'
        state = self.context._mp_login_status().get('state') if platform == 'wechat-oa' else ''
        return SimpleNamespace(returncode=0, stdout=json.dumps({'loggedIn': state == 'success', 'provider_user_id': 'gh_temp_exact' if state == 'success' else '', 'name': 'TEMP 合成账号' if state == 'success' else '', 'avatar': ''}))


def install_reference(application, directory):
    """A test-only static mount; reads use the same authenticated fixture API."""
    from starlette.responses import FileResponse, HTMLResponse, Response
    @application.middleware('http')
    async def reference(request, call_next):
        path = request.url.path
        if not path.startswith('/canonical'):
            return await call_next(request)
        relative = path.removeprefix('/canonical').lstrip('/')
        if relative.startswith('api/'):
            request.scope['path'] = '/' + relative
            request.scope['raw_path'] = ('/' + relative).encode()
            return await call_next(request)
        if relative.startswith('static/'):
            root = (ROOT / 'web/static').resolve()
            target = (root / relative.removeprefix('static/')).resolve()
        else:
            root = directory.resolve()
            target = (root / (relative or 'index.html')).resolve()
        if not target.is_relative_to(root) or not target.is_file(): return Response(status_code=404)
        if target.name == 'index.html':
            html = target.read_text(encoding='utf-8').replace('"/assets/', '"/canonical/assets/').replace('"./assets/', '"/canonical/assets/')
            return HTMLResponse(html)
        return FileResponse(target)


def styles(page, selectors):
    return page.evaluate("""selectors=>Object.fromEntries(selectors.flatMap(selector=>{
      const el=document.querySelector(selector);if(!el)return [];
      const style=getComputedStyle(el),keys=['fontFamily','fontSize','lineHeight','fontWeight','borderRadius','backgroundColor','color','padding','gap'];
      return [[selector,Object.fromEntries(keys.map(key=>[key,style[key]]))]];
    }))""", selectors)


def legacy_account_caches(page):
    return page.evaluate("""()=>Object.keys(localStorage).filter(key=>
      /^(?:easel|postcraft)_(?:whoami|analytics)(?:_|$)/.test(key))""")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--native', required=True)
    parser.add_argument('--backend', default=str(ROOT))
    parser.add_argument('--canonical')
    parser.add_argument('--canonical-ref')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    backend, native, out = Path(args.backend).resolve(), Path(args.native).resolve(), Path(args.out).resolve()
    canonical = Path(args.canonical).resolve() if args.canonical else None
    out.mkdir(parents=True, exist_ok=True)
    h = fixture_module(backend)
    frozen_path=backend/'workbench-release.json'
    frozen=json.loads(frozen_path.read_text(encoding='utf-8')) if frozen_path.is_file() else None
    if frozen: assert all(h.sha(backend/name)==digest for name,digest in frozen['files'].items()),'Frozen backend bytes changed'
    native_manifest=json.loads((native/'native-manifest.json').read_text(encoding='utf-8'))
    assert all(h.sha(native/name)==digest for name,digest in native_manifest['files'].items()),'Frozen frontend bytes changed'
    from playwright.sync_api import sync_playwright, expect
    expect.set_options(timeout=20000)
    import easel_workbench.application as composition
    original_factory = composition.create_app
    def factory(**kwargs):
        app = original_factory(**kwargs)
        if canonical: install_reference(app, canonical)
        return app
    report = {'passed': False, 'checks': [], 'real_AI_calls': 0, 'real_platform_writes': 0,
              'physical_mobile_device_tested': False, 'synthetic_account_processes': 0,
              'native': {'release': native.name, 'manifest_sha256': h.sha(native / 'native-manifest.json')},
              'backend': {'directory':str(backend),'release':frozen.get('release') if frozen else None,'manifest_sha256':h.sha(frozen_path) if frozen else None}, 'harness_sha256':h.sha(__file__), 'canonical': str(canonical) if canonical else None,
              'comparison_kind': 'reference application against identical TEMP data' if canonical else None,
              'canonical_ref': args.canonical_ref,
              'allowed_visual_extensions': ['15 visible trend rows with internal scrolling', 'dashboard lists capped at 360px', 'private exact-version lifecycle extension slots']}
    def check(name, **evidence):
        report['checks'].append({'name': name, 'passed': True, **evidence})
        print('PASS', name, flush=True)
    try:
        with patch.object(composition, 'create_app', factory), sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            seed = browser.new_page()
            seed.set_content('<p>TEMP synthetic QR and registered image</p>')
            image = seed.screenshot()
            seed.close()
            with h.isolated(native, image) as f:
                f['close_clients'] = lambda: [context.close() for context in browser.contexts]
                accounts = f['app'].state.easel_accounts
                account_context = accounts.native_context()
                synthetic = SyntheticAccounts(account_context, image)
                fake_process = SimpleNamespace(**{key: getattr(subprocess, key) for key in dir(subprocess) if not key.startswith('__')})
                fake_process.Popen, fake_process.run = synthetic.start, synthetic.run
                account_context.namespace['subprocess'] = fake_process
                physical = f['root'] / 'outputs/TEMP已有素材'
                physical.mkdir(parents=True)
                (physical / '封面.png').write_bytes(image)
                (physical / '正文.md').write_text('# TEMP 原文\n\n保留已有文件。', encoding='utf-8')
                work_id='temp-base-registered-work'
                f['box'].create({'id':work_id,'title':'TEMP 已登记版本','material':'TEMP 合成持久记录，不代表实际模型完成。','format':'poster','files':[]})
                artifact=f['root']/'data/artifacts/temp-base-image.png';artifact.parent.mkdir(parents=True,exist_ok=True);artifact.write_bytes(image)
                with f['box'].store.connect() as connection:
                    connection.execute('UPDATE toolbox_jobs SET status=?,error=?,finished_at=? WHERE id=?',('error','TEMP 合成中断记录','2026-10-30T08:00:00Z',work_id))
                    connection.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)',('temp-base-image',work_id,'成品.png',str(artifact),'image/png'))
                collection = f['app'].state.collection
                definitions = collection.registry.baseline()
                source, source_config = next(iter(definitions.items()))
                f['box'].store.ingest({'schema_version': 1, 'source_job': source, 'feed_id': source_config['feed'],
                  'run_id': 'base-browser-news', 'run_at': '2026-10-30T08:00:00Z', 'final_text': 'TEMP',
                  'articles': [{'title': f'TEMP 热点 {number:02d}', 'body': 'TEMP stored source text.', 'url': f'https://example.com/{number}', 'source_order': number} for number in range(1, 31)]})
                all_errors = []
                for mobile, width, height in [(False, 1440, 900), (True, 390, 844)]:
                    for theme in ('light', 'dark'):
                        label = ('mobile-simulated' if mobile else 'windows') + '-' + theme
                        context = browser.new_context(ignore_https_errors=True, viewport={'width': width, 'height': height}, is_mobile=mobile, has_touch=mobile, color_scheme=theme)
                        context.add_cookies([{'name': '__Host-desk_session', 'value': 'fixture-owner', 'url': f['origin'], 'secure': True, 'httpOnly': True, 'sameSite': 'Strict'}])
                        context.add_init_script("""theme=>{}""".replace('theme=>{}', 'localStorage.setItem("native:theme",'+json.dumps(theme)+');localStorage.setItem("easel_theme",'+json.dumps(theme)+');localStorage.setItem("easel_onboarding_seen","1");'))
                        page = context.new_page()
                        page.set_default_timeout(20000)
                        errors, requests = [], []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.on('request', lambda request: requests.append({'path': urlsplit(request.url).path, 'query':urlsplit(request.url).query, 'method': request.method, 'operation_id':request.headers.get('x-operation-id')}))
                        def visit(path):
                            page.goto(f['origin'] + '/native/?' + urlencode({'path': path}), wait_until='domcontentloaded')
                        def capture(name):
                            page.screenshot(path=str(out / (label + '-' + name + '.png')), full_page=True)
                            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'), name
                        held_boot=[]
                        boot_handler=lambda route:held_boot.append(route)
                        page.route('**/api/config',boot_handler)
                        visit('/toolbox')
                        expect(page.locator('.ew-loading')).to_be_visible()
                        assert len(held_boot)==1,held_boot
                        assert page.locator('.dash-page').count()==0,'A native page mounted before its authenticated transport was ready'
                        assert not legacy_account_caches(page),legacy_account_caches(page)
                        assert not any(item['path'].startswith('/native/api/') for item in requests),requests
                        held_boot[0].continue_()
                        page.unroute('**/api/config',boot_handler)
                        expect(page.locator('.dash-page')).to_be_visible()
                        assert not legacy_account_caches(page),legacy_account_caches(page)
                        assert not any(item['path'].startswith('/native/api/') for item in requests),requests
                        check(label+': startup gate prevents premature page effects, legacy account caches and native-relative API requests')
                        expect(page.locator('.sidebar .nav-item')).to_have_count(6)
                        assert page.locator('.sidebar select.persona-select').count() == 1
                        assert page.locator('.sidebar-logo-icon').count() == 1
                        assert page.locator('.sidebar .theme-toggle').count() == 1
                        assert page.locator('.ew-topbar').count() == 0
                        assert page.get_by_role('button', name='返回', exact=True).count() == 0
                        expect(page.locator('.dash-card-list')).to_have_count(4)
                        assert all(row<=360 for row in page.locator('.dash-card-list').evaluate_all('items=>items.map(el=>el.clientHeight)'))
                        capture('dashboard')
                        check(label + ': native sidebar, select, logo, theme and dashboard')
                        dashboard_styles = styles(page, ['.sidebar .nav-item', '.sidebar .persona-select', '.dash-quick-btn', '.dash-stat'])
                        assert not [item for item in requests if item['path'] == '/api/collection/runs' and item['method'] == 'POST']
                        check(label + ': entry only reads stored collection results')
                        for path, selector, name in [
                            ('/toolbox?section=research&pane=topics', '.ideas-page', 'ideas'),
                            ('/toolbox?section=calendar', '.calendar-page', 'calendar'),
                            ('/works', '.gallery-page', 'outputs'),
                            ('/toolbox?section=profiles', '.profile-page', 'profiles'),
                            ('/toolbox?section=publications', '.publishing-workspace', 'publishing'),
                            ('/toolbox?section=research&pane=breakdown', '.breakdown-page', 'breakdown'),
                            ('/settings', '.settings-panel', 'settings'),
                        ]:
                            visit(path)
                            expect(page.locator(selector)).to_be_visible()
                            capture(name)
                            check(label + ': complete native ' + name + ' page')
                        visit('/works')
                        project=page.locator('.gcard').filter(has_text='TEMP 已登记版本')
                        expect(project).to_be_visible();project.click()
                        exact=page.get_by_role('button',name='查看准确版本、采纳与交付',exact=True)
                        expect(exact).to_be_visible();exact.click()
                        page.wait_for_function('id=>new URLSearchParams(location.search).get("path")?.includes(id)',arg=work_id)
                        target=parse_qs(urlsplit(page.url).query)['path'][0]
                        assert target.split('?')[0].endswith('/'+work_id) and parse_qs(urlsplit(target).query)['version']==[work_id]
                        visit('/works?'+urlencode({'path':'__workbench__/temp-base-image/成品.png'}))
                        expect(page.locator('.drawer img')).to_be_visible()
                        capture('registered-output')
                        check(label+': native gallery preserves exact-version link and opens registered virtual file path')
                        visit('/news')
                        expect(page.locator('.trend-list').first).to_be_visible()
                        page.wait_for_timeout(250)
                        assert page.locator('.trend-item').count() >= 30
                        bounds = page.locator('.trend-list').first.evaluate('el=>({height:el.clientHeight,full:el.scrollHeight,overflow:getComputedStyle(el).overflowY})')
                        assert bounds['height'] < bounds['full'] and bounds['overflow'] == 'auto', bounds
                        capture('trends')
                        check(label + ': full hotspot list retained behind 15-row scroll limit', bounds=bounds)
                        visit('/toolbox?section=distribution&pane=connections')
                        card = page.locator('.account-card').filter(has=page.locator('.account-card-name', has_text='微信公众号'))
                        expect(card).to_be_visible()
                        expect(card.get_by_role('button', name='登录', exact=True)).to_be_visible()
                        assert card.get_by_role('button', name='退出登录', exact=True).count() == 0
                        assert page.get_by_text('平台连接所需依赖', exact=True).count() == 0
                        assert page.get_by_text('历史账号记录', exact=True).count() == 0
                        assert page.get_by_role('button', name='配置 AppID 凭据', exact=True).count() == 0
                        capture('accounts-initial')
                        assert not legacy_account_caches(page),legacy_account_caches(page)
                        assert not any(item['path'].startswith('/api/accounts/') and item['path'].endswith('/whoami') for item in requests),requests
                        check(label+': entering the native account page never starts automatic whoami verification')
                        account_styles = styles(page, ['.accounts-grid', '.account-card', '.account-card-name', '.account-card .btn'])
                        if canonical:
                            reference_context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':height},is_mobile=mobile,has_touch=mobile,color_scheme=theme)
                            reference_context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
                            reference_context.add_init_script('localStorage.setItem("easel_theme",'+json.dumps(theme)+');localStorage.setItem("easel_onboarding_seen","1");')
                            reference = reference_context.new_page()
                            with reference.expect_response(lambda response: urlsplit(response.url).path=='/canonical/api/settings/bootstrap') as boot_response:
                                reference.goto(f['origin'] + '/canonical/', wait_until='domcontentloaded')
                            expect(reference.locator('.dash-page')).to_be_visible()
                            if boot_response.value.json().get('modelConfigured') is False:
                                expect(reference.locator('.settings-close')).to_be_visible()
                                reference.locator('.settings-close').click()
                            assert styles(reference, list(dashboard_styles)) == dashboard_styles, {'native': dashboard_styles, 'reference': styles(reference, list(dashboard_styles))}
                            reference.locator('.sidebar-nav .nav-item').filter(has_text='账号').click()
                            expect(reference.locator('.accounts-page')).to_be_visible()
                            expect(reference.locator('.account-card').first).to_be_visible()
                            assert styles(reference, list(account_styles)) == account_styles, {'native': account_styles, 'reference': styles(reference, list(account_styles))}
                            reference.screenshot(path=str(out / (label + '-canonical-accounts.png')), full_page=True)
                            reference_context.close()
                            check(label + ': default-app and hosted shared controls have equal computed styles')
                        modal = page.locator('.modal').filter(has=page.get_by_role('heading', name='登录 微信公众号 · 后台取数', exact=True))
                        def start_login():
                            count=len(synthetic.calls)
                            with page.expect_response(lambda response: response.request.method=='POST' and urlsplit(response.url).path=='/api/accounts/wechat-oa/mp-login') as accepted:
                                card.get_by_role('button',name='登录',exact=True).click()
                            assert accepted.value.ok,accepted.value.text()
                            assert len(synthetic.calls)==count+1
                            expect(modal.get_by_alt_text('登录二维码')).to_be_visible()
                        before = len(synthetic.calls)
                        start_login()
                        assert len(synthetic.calls) == before + 1
                        assert card.get_by_role('button', name='退出登录', exact=True).count() == 0
                        capture('account-qr')
                        # Calling the same native start while its owner is alive only observes that owner.
                        response = page.request.post(f['origin'] + '/api/accounts/wechat-oa/mp-login', headers={'X-CSRF-Token': page.request.get(f['origin']+'/api/config').json()['csrf'], 'X-Operation-Id': 'repeat-' + label, 'Origin': f['origin']}, data={})
                        assert response.ok, response.text()
                        assert len(synthetic.calls) == before + 1
                        synthetic.finish('scanned', 'TEMP 已扫码，等待确认', running=True)
                        expect(modal.get_by_text('扫码成功', exact=False).first).to_be_visible()
                        synthetic.finish('expired', 'TEMP 二维码超时未扫')
                        expect(modal.get_by_text('二维码已过期', exact=False)).to_be_visible()
                        modal.get_by_role('button', name='关闭', exact=True).click()
                        start_login()
                        synthetic.finish('error', 'TEMP 合成浏览器异常')
                        expect(modal.get_by_text('登录出错', exact=False)).to_be_visible()
                        modal.get_by_role('button', name='关闭', exact=True).click()
                        start_login()
                        with page.expect_request(lambda request:urlsplit(request.url).path=='/api/accounts/wechat-oa/whoami' and parse_qs(urlsplit(request.url).query).get('force')==['true']) as explicit_verification:
                            synthetic.finish('success', 'TEMP 合成成功回执')
                            expect(modal.get_by_text('登录成功 ✅', exact=False)).to_be_visible()
                            modal.get_by_role('button', name='完成', exact=True).click()
                        assert explicit_verification.value.method=='GET'
                        expect(card.get_by_role('button', name='退出登录', exact=True)).to_be_visible()
                        manual_verification=card.get_by_role('button',name='校验账号',exact=True)
                        expect(manual_verification).to_be_enabled()
                        with page.expect_request(lambda request:urlsplit(request.url).path=='/api/accounts/wechat-oa/whoami' and parse_qs(urlsplit(request.url).query).get('force')==['true']) as manual_request:
                            manual_verification.click()
                        assert manual_request.value.method=='GET'
                        expect(manual_verification).to_be_enabled()
                        check(label+': manual account verification and successful QR login retain explicit force requests')
                        capture('account-success')
                        page.once('dialog', lambda dialog: dialog.accept())
                        card.get_by_role('button', name='退出登录', exact=True).click()
                        expect(card.get_by_role('button', name='登录', exact=True)).to_be_visible()
                        check(label + ': native QR, shared owner, scan, expiration, error, success and logout use actual TEMP receipts')
                        if not mobile and theme == 'light':
                            visit('/toolbox?section=research&pane=topics')
                            page.get_by_role('button', name='+ 新建选题', exact=True).click()
                            fields = page.locator('.modal .field')
                            fields.nth(0).fill('TEMP 原生 HTTP 选题')
                            fields.nth(1).fill('原始备注')
                            page.locator('.modal').get_by_role('button', name='保存', exact=True).click()
                            topic = page.locator('.idea-card').filter(has_text='TEMP 原生 HTTP 选题')
                            expect(topic).to_be_visible()
                            topic.hover()
                            topic.get_by_title('编辑', exact=True).click()
                            page.locator('.modal .field').nth(0).fill('TEMP 修改后 HTTP 选题')
                            page.locator('.modal').get_by_role('button', name='保存', exact=True).click()
                            topic = page.locator('.idea-card').filter(has_text='TEMP 修改后 HTTP 选题')
                            expect(topic).to_be_visible()
                            topic.hover()
                            topic.get_by_title('删除', exact=True).click()
                            expect(topic).to_have_count(0)
                            verbs = {(item['path'], item['method']) for item in requests if item['path'].startswith('/api/ideas')}
                            assert any(method == 'POST' for _, method in verbs) and any(method == 'PUT' for _, method in verbs) and any(method == 'DELETE' for _, method in verbs), verbs
                            check('native idea CRUD uses original POST, PUT and DELETE with durable host transport')
                            visit('/toolbox?section=profiles&item=oil-pig')
                            page.get_by_role('button', name='✏️ 编辑资料', exact=True).click()
                            first = page.locator('.profile-dim').filter(has_text='身份定位').first
                            original = first.locator('textarea').input_value()
                            revision=page.request.get(f['origin']+'/api/persona/oil-pig/files').json()['revision']
                            external=original+'\nTEMP 另一编辑器的新修订'
                            updated=page.request.put(f['origin']+'/api/persona/oil-pig/file',headers={'X-CSRF-Token':page.request.get(f['origin']+'/api/config').json()['csrf'],'X-Operation-Id':'external-profile-edit','Origin':f['origin']},data={'filename':'identity.md','content':external,'expected_revision':revision})
                            assert updated.ok,updated.text()
                            first.locator('textarea').fill(original+'\nTEMP 旧编辑器输入仍保留')
                            first.get_by_role('button',name='保存',exact=True).click()
                            expect(page.get_by_text('画像已有新修订，请重新核对',exact=False)).to_be_visible()
                            expect(first.locator('textarea')).to_have_value(original+'\nTEMP 旧编辑器输入仍保留')
                            saved_files=page.request.get(f['origin']+'/api/persona/oil-pig/files').json()['files']
                            assert next(item for item in saved_files if item['filename']=='identity.md')['content']==external
                            check('a stale native profile editor preserves typed input and cannot overwrite a newer server revision')
                            page.reload(wait_until='domcontentloaded')
                            first=page.locator('.profile-dim').filter(has_text='身份定位').first
                            expect(first.locator('textarea')).to_have_value(original+'\nTEMP 旧编辑器输入仍保留')
                            retained=page.evaluate("JSON.parse(localStorage.getItem('toolbox:draft:easel:profile-files:oil-pig'))")
                            assert retained['revision']==revision,retained
                            assert retained['fields']=={'identity.md':original+'\nTEMP 旧编辑器输入仍保留'},retained
                            page.get_by_role('button',name='查看当前修订',exact=True).click()
                            expect(first.locator('.profile-content')).to_contain_text('TEMP 另一编辑器的新修订')
                            assert page.evaluate("JSON.parse(localStorage.getItem('toolbox:draft:easel:profile-files:oil-pig')).revision")==revision
                            page.get_by_role('button',name='已核对当前修订，保留输入继续编辑',exact=True).click()
                            expect(page.get_by_role('button',name='已核对当前修订，保留输入继续编辑',exact=True)).to_have_count(0)
                            expect(first.locator('textarea')).to_have_value(original+'\nTEMP 旧编辑器输入仍保留')
                            check('profile reload retains only user text and captured revision; explicit review alone advances the parent')
                            original=first.locator('textarea').input_value()
                            first.locator('textarea').fill(original + '\nTEMP 原字画像检查')
                            first.get_by_role('button', name='保存', exact=True).click()
                            expect(first.get_by_role('button', name='已保存', exact=True)).to_be_visible()
                            assert any(item['method'] == 'PUT' and item['path'].endswith('/api/persona/oil-pig/file') for item in requests)
                            assert page.get_by_role('button', name='📊 抓取公众号数据', exact=True).count() == 0
                            check('native file editor writes exact profile revision without account import or deletion')
                            # A real owner401 must keep local input and the original
                            # durable request identity even when auth memory is reset.
                            retained_text=first.locator('textarea').input_value()+'\nTEMP 401原字输入'
                            first.locator('textarea').fill(retained_text)
                            held_profile_write=[]
                            profile_write_handler=lambda route:held_profile_write.append(route)
                            page.route('**/api/persona/oil-pig/file',profile_write_handler)
                            first.get_by_role('button',name='保存',exact=True).click()
                            assert len(held_profile_write)==1
                            f['auth'].expired=True
                            with page.expect_response(lambda response:response.request.method=='PUT' and urlsplit(response.url).path=='/api/persona/oil-pig/file') as rejected:
                                held_profile_write[0].continue_()
                            assert rejected.value.status==401,rejected.value.status
                            page.unroute('**/api/persona/oil-pig/file',profile_write_handler)
                            expect(page.locator('.native-host-notice').filter(has_text='登录已过期')).to_be_visible()
                            profile_key='toolbox:draft:easel:profile-files:oil-pig'
                            pending_key='toolbox:draft:native:pending:easel-native:PUT:/api/persona/oil-pig/file'
                            retained_profile=page.evaluate('key=>JSON.parse(localStorage.getItem(key))',profile_key)
                            original_pending=page.evaluate('key=>JSON.parse(localStorage.getItem(key)).operation',pending_key)
                            assert retained_profile['fields']=={'identity.md':retained_text}
                            assert original_pending['id'] and original_pending['metadataOnly'] and original_pending['body']=={},original_pending
                            f['auth'].expired=False
                            recover_start=len(requests)
                            page.reload(wait_until='domcontentloaded')
                            first=page.locator('.profile-dim').filter(has_text='身份定位').first
                            expect(first.locator('textarea')).to_have_value(retained_text)
                            assert page.evaluate('key=>JSON.parse(localStorage.getItem(key)).operation.id',pending_key)==original_pending['id']
                            assert not any(item['path']=='/api/persona/oil-pig/file' and item['method']=='PUT' for item in requests[recover_start:])
                            check('real owner401 and authenticated reload preserve exact profile input and request identity without replay')
                            # Lose only the acknowledgement of a genuine TEMP idea
                            # write; suppress receipt visibility, never replay POST.
                            visit('/toolbox?section=research&pane=topics')
                            page.get_by_role('button',name='+ 新建选题',exact=True).click()
                            page.locator('.modal .field').nth(0).fill('TEMP 未知回执原字选题')
                            def hide_receipt(route):
                                operation=urlsplit(route.request.url).path.rsplit('/',1)[-1]
                                route.fulfill(status=200,content_type='application/json',body=json.dumps({'id':operation,'state':'unavailable','result':None}))
                            page.route('**/api/native/operations/*',hide_receipt)
                            accepted_idea=[]
                            def lose_idea_ack(route):
                                if route.request.method!='POST':route.continue_();return
                                response=route.fetch()
                                assert response.ok,response.text()
                                accepted_idea.append({'id':route.request.headers['x-operation-id'],'result':response.json()})
                                route.abort('connectionreset')
                            page.route('**/api/ideas',lose_idea_ack)
                            unknown_start=len(requests)
                            page.locator('.modal').get_by_role('button',name='保存',exact=True).click()
                            idea_pending_key='toolbox:draft:native:pending:easel-native:POST:/api/ideas'
                            page.wait_for_function('key=>JSON.parse(localStorage.getItem(key)||"{}").operation?.uncertain===true',arg=idea_pending_key)
                            assert len(accepted_idea)==1,accepted_idea
                            operation_id=accepted_idea[0]['id']
                            assert page.evaluate('key=>JSON.parse(localStorage.getItem(key)).operation.id',idea_pending_key)==operation_id
                            page.unroute('**/api/ideas',lose_idea_ack)
                            page.locator('.modal').get_by_role('button',name='×',exact=True).click()
                            f['auth'].expired=True
                            with page.expect_response(lambda response:response.status==401 and urlsplit(response.url).path.startswith('/api/')) as expired_unknown:
                                page.locator('.sidebar .nav-item').filter(has_text='账号').click()
                            assert expired_unknown.value.request.method=='GET'
                            expect(page.locator('.native-host-notice').filter(has_text='登录已过期')).to_be_visible()
                            assert page.evaluate('key=>JSON.parse(localStorage.getItem(key)).operation.id',idea_pending_key)==operation_id
                            visit('/toolbox?section=distribution&pane=connections')
                            expect(page.get_by_role('heading',name='登录创作工作台',exact=True)).to_be_visible()
                            assert page.evaluate('key=>JSON.parse(localStorage.getItem(key)).operation.id',idea_pending_key)==operation_id
                            f['auth'].expired=False
                            visit('/toolbox?section=research&pane=topics')
                            expect(page.locator('.modal .field').nth(0)).to_have_value('TEMP 未知回执原字选题')
                            page.wait_for_timeout(200)
                            assert page.evaluate('key=>JSON.parse(localStorage.getItem(key)).operation.id',idea_pending_key)==operation_id
                            assert len([item for item in requests[unknown_start:] if item['path']=='/api/ideas' and item['method']=='POST'])==1
                            remote_ideas=page.request.get(f['origin']+'/api/ideas').json()
                            assert len([item for item in remote_ideas if item['title']=='TEMP 未知回执原字选题'])==1,remote_ideas
                            page.unroute('**/api/native/operations/*',hide_receipt)
                            check('accepted write with lost acknowledgement retains exact idea input and unknown operation identity through401 and reload; POST is never replayed')
                        assert not errors, errors
                        assert not legacy_account_caches(page),legacy_account_caches(page)
                        assert not any(item['path'].startswith('/native/api/') for item in requests),requests
                        all_errors.extend(errors)
                        context.close()
                assert not f['adapter'].requests, 'Page acceptance must not run an inference adapter'
                report['synthetic_account_processes'] = len(synthetic.calls)
                report['page_errors'] = all_errors
                check('all browser checks used TEMP data and synthetic platform processes, with zero model turns')
            browser.close()
        if frozen:
            modules={name:str(Path(module.__file__).resolve()) for name,module in sys.modules.items() if (name=='easel' or name.startswith('easel.') or name=='easel_workbench' or name.startswith('easel_workbench.')) and getattr(module,'__file__',None)}
            assert modules and all(Path(path).is_relative_to(backend) for path in modules.values()),modules
            assert all(h.sha(backend/name)==digest for name,digest in frozen['files'].items())
            report.update(module_roots_valid=True,module_count=len(modules))
            check('frozen backend bytes and every Easel runtime module belong to the exact candidate')
        report['screenshots']={path.name:h.sha(path) for path in out.glob('*.png')}
        report['passed'] = True
    finally:
        (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
