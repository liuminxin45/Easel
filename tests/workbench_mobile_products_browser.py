"""Real Edge, TEMP owner data: large products, literal copy and return paths.

Synthetic files/read fixtures never submit inference or a platform operation.
--baseline records observed defects; only the default strict run is acceptance.
"""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import threading
from urllib.parse import urlencode, urlsplit
import zlib

ROOT = Path(__file__).resolve().parents[1]
TITLE = '移动端长标题需要完整换行' * 12
BODY = ('这是需要自动换行并且保持原始复制内容的正文。' * 24
        + '\n\nhttps://example.test/' + 'long-unbroken-path-' * 25)
DRAFT = 'TEMP 未发送的原始输入，返回后必须保留。'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def png(width, height):
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    rows = b''.join(b'\0' + bytes((50, 90 + (y // 100 % 3) * 40, 150)) * width for y in range(height))
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', width, height, 8, 2, 0, 0, 0)) + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', type=Path, required=True)
    parser.add_argument('--backend', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--baseline', action='store_true')
    parser.add_argument('--widths', default='320,360,390,430,844,1280')
    args = parser.parse_args()
    native, backend, out = args.native.resolve(), args.backend.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    report = {'passed': False, 'baseline': args.baseline, 'checks': [], 'errors': [],
              'native': {'directory': str(native), 'sha256': sha(native / 'native-manifest.json')},
              'backend': {'directory': str(backend), 'sha256': sha(backend / 'workbench-release.json')},
              'scope': 'Windows Edge, simulated mobile/touch; TEMP files and synthetic read fixtures; no real model/platform/device'}
    spec = importlib.util.spec_from_file_location('product_audit', ROOT / 'tests/workbench_mobile_audit.py')
    audit = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(audit)
    for directory, name in ((native, 'native-manifest.json'), (backend, 'workbench-release.json')):
        manifest = json.loads((directory / name).read_text(encoding='utf-8-sig'))
        assert all(sha(directory / path) == digest for path, digest in manifest['files'].items())
    from playwright.sync_api import sync_playwright, expect
    try:
        with tempfile.TemporaryDirectory(prefix='mobile-products-bootstrap-', dir=out) as bootstrap:
            for name in ('sources.json', 'usage_registry.json', 'collection_schedules.json'):
                source = backend / 'easel_workbench/runtime' / name
                if source.is_file(): shutil.copy2(source, Path(bootstrap) / name)
            os.environ['AI_DESK_PROJECT_ROOT'] = bootstrap
            os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
            os.environ.pop('AI_DESK_RELEASE', None)
            fixtures = audit.load_fixture(backend)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel='msedge', headless=True, args=['--ignore-certificate-errors'])
                with fixtures.isolated(native, png(1086, 4096)) as fixture:
                    fixture['close_clients'] = lambda: [ctx.close() for ctx in browser.contexts]
                    from easel_workbench.runtime.auth_totp import token_hash
                    fixture['auth'].lock = threading.RLock()
                    fixture['auth'].data['sessions'] = {token_hash('fixture-owner'): dict(fixture['auth'].session('fixture-owner'))}
                    ids = audit.seed(fixture, png(1086, 4096), b'TEMP unused video')
                    reads, _ = audit.synthetic_reads(fixture, ids)
                    history = reads['/api/chat/sessions/' + ids['session']]
                    session = history['session']
                    session['title'] = TITLE
                    session['messages'][0]['content'] = 'TEMP 只读贴图会话'
                    message = session['messages'][1]
                    message.update(content='[外部原始来源](https://example.test/article)\n\n[本机网页](/api/outputs/file?path=preview.html)', questions=[])
                    files = [message['output_files'][0]]
                    for index, dimensions in enumerate(((2200, 500), (800, 800))):
                        file_id = 'mobile-aspect-' + str(index)
                        path = fixture['root'] / 'data/artifacts' / (file_id + '.png')
                        path.write_bytes(png(*dimensions))
                        with fixture['box'].store.connect() as connection:
                            connection.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)', (file_id, ids['work'], file_id + '.png', str(path), 'image/png'))
                        files.append({'id': file_id, 'name': file_id + '.png', 'mime': 'image/png', 'url': '/api/files/' + file_id})
                    message['output_files'] = files
                    product = reads['/api/chat/products/mobile-audit-turn']
                    product.update(files=files, text_blocks=[{'label': '标题', 'text': TITLE}, {'label': '正文', 'text': BODY}])
                    for width in map(int, args.widths.split(',')):
                        height = 390 if width == 844 else 844
                        mobile = width < 1000
                        for theme in ('light', 'dark'):
                            context = browser.new_context(ignore_https_errors=True, viewport={'width': width, 'height': height},
                                                          is_mobile=mobile, has_touch=mobile, color_scheme=theme,
                                                          permissions=['clipboard-read', 'clipboard-write'])
                            context.add_cookies([{'name': '__Host-desk_session', 'value': 'fixture-owner', 'url': fixture['origin'], 'secure': True, 'httpOnly': True, 'sameSite': 'Strict'}])
                            context.add_init_script('if(window===window.top){localStorage.setItem("native:theme",' + json.dumps(theme) + ');localStorage.setItem(' + json.dumps('toolbox:draft:chat:' + ids['session']) + ',' + json.dumps(json.dumps({'text': DRAFT, 'files': []})) + ')}')
                            external = fixture['origin'] + '/external-test-page'
                            # Cross-origin page is served by the browser fixture, without network access.
                            external = 'https://example.test/article'
                            def guard(route):
                                request = route.request
                                url = urlsplit(request.url)
                                if request.url == external:
                                    return route.fulfill(content_type='text/html; charset=utf-8', body='<meta charset="utf-8"><title>TEMP 外部网页</title><h1>TEMP 外部网页</h1>')
                                if url.netloc != urlsplit(fixture['origin']).netloc: return route.abort()
                                if url.path == '/api/outputs/file':
                                    return route.fulfill(content_type='text/html; charset=utf-8', body='<meta charset="utf-8"><title>TEMP 本机网页</title><h1>TEMP 本机网页</h1>')
                                if request.method not in ('GET', 'HEAD'):
                                    return route.fulfill(status=409, json={'error': 'TEMP read-only interaction test'})
                                if url.path in reads: return route.fulfill(status=200, json=reads[url.path])
                                route.continue_()
                            context.route('**/*', guard)
                            page = context.new_page()
                            page.set_default_timeout(12000)
                            def activate(control):
                                control.tap() if mobile else control.click()
                            page.on('pageerror', lambda error: report['errors'].append(str(error)))
                            label = f'{width}x{height}-{theme}'
                            page.goto(fixture['origin'] + '/native/?' + urlencode({'path': '/chat/' + ids['session']}))
                            gallery = page.locator('.artifact-gallery').first
                            expect(gallery).to_be_visible()
                            text = page.get_by_role('region', name='正文', exact=True)
                            # section accessible name may be exposed as region by Chromium.
                            expect(page.locator('.copyable-text').filter(has=page.get_by_role('button', name='复制正文', exact=True))).to_be_visible()
                            text = page.locator('.copyable-text').filter(has=page.get_by_role('button', name='复制正文', exact=True))
                            measurements = []
                            for index in range(3):
                                image = gallery.locator('img')
                                expect(image).to_have_js_property('complete', True)
                                page.wait_for_function('()=>document.querySelector(".artifact-gallery img")?.naturalWidth>0')
                                measurements.append(image.evaluate('img=>{const r=img.getBoundingClientRect(),stage=img.closest(".artifact-stage").getBoundingClientRect();return {width:r.width,height:r.height,naturalWidth:img.naturalWidth,naturalHeight:img.naturalHeight,stageWidth:stage.width,ratio:r.width/r.height,expected:img.naturalWidth/img.naturalHeight,contained:r.width<=stage.width&&r.height<=Math.min(innerHeight*.56,520)+2}}'))
                                activate(gallery.get_by_role('button', name='下一个产物'))
                            wrap = text.locator('pre').evaluate('el=>({width:el.clientWidth,scrollWidth:el.scrollWidth,whiteSpace:getComputedStyle(el).whiteSpace})')
                            text.locator('header').scroll_into_view_if_needed()
                            screenshot = out / (label + '-copy.png')
                            page.screenshot(path=str(screenshot))
                            activate(text.get_by_role('button', name='复制正文', exact=True))
                            expect(text.get_by_role('button', name='复制正文', exact=True)).to_have_text('已复制')
                            clipboard = page.evaluate('navigator.clipboard.readText()')
                            report.setdefault('clipboard_observations', []).append({'case': label, 'crlf': clipboard.count('\r\n'), 'lf': clipboard.count('\n'), 'expected_lf': BODY.count('\n')})
                            # Windows' native clipboard serializes newlines as CRLF.
                            # Rendering and the clipboard payload must otherwise retain every character.
                            copy_ok = clipboard.replace('\r\n', '\n') == BODY and text.locator('pre').text_content() == BODY
                            image_link = gallery.locator('.artifact-image-link')
                            image_link.scroll_into_view_if_needed()
                            page.screenshot(path=str(out / (label + '-image.png')))
                            before_scroll = page.locator('.chat-messages').evaluate('el=>el.scrollTop')
                            before_url = page.url
                            count = len(context.pages)
                            activate(image_link)
                            page.wait_for_timeout(250)
                            if args.baseline:
                                item = {'case': label, 'images': measurements, 'text': wrap, 'copy_exact': copy_ok,
                                        'image_opened_new_page': len(context.pages) > count,
                                        'preview_with_close': page.locator('dialog[open]').count() > 0,
                                        'screenshot': str(screenshot), 'sha256': sha(screenshot)}
                                report['checks'].append(item)
                                context.close()
                                continue
                            assert len(context.pages) == count, 'Image opened a history-less window'
                            preview = page.get_by_role('dialog', name='查看图片')
                            expect(preview).to_be_visible()
                            expect(preview.locator('img')).to_have_js_property('complete', True)
                            page.screenshot(path=str(out / (label + '-preview.png')))
                            activate(preview.get_by_role('button', name='关闭', exact=True))
                            expect(preview).to_have_count(0)
                            assert page.url == before_url
                            assert abs(page.locator('.chat-messages').evaluate('el=>el.scrollTop') - before_scroll) < 3
                            activate(image_link)
                            expect(preview).to_be_visible()
                            page.go_back()
                            expect(preview).to_have_count(0)
                            expect(page.get_by_role('textbox', name='对话输入')).to_have_value(DRAFT)
                            footer_open = gallery.get_by_role('link', name='打开 ↗', exact=True)
                            activate(footer_open)
                            expect(preview).to_be_visible()
                            activate(preview.get_by_role('button', name='关闭', exact=True))
                            expect(preview).to_have_count(0)
                            for name in ('外部原始来源', '本机网页'):
                                link = page.get_by_role('link', name=name, exact=True)
                                requests_new_window = link.get_attribute('target') == '_blank'
                                # Polling may replace a message between the locator's
                                # lookup and Playwright's two-frame stability wait.
                                # Scroll the freshly resolved DOM node atomically;
                                # the following trusted tap still performs hit testing.
                                link.evaluate("el=>el.scrollIntoView({block:'nearest',behavior:'instant'})")
                                document_scroll = page.locator('.chat-messages').evaluate('el=>el.scrollTop')
                                activate(link)
                                if mobile or not requests_new_window:
                                    expect(page.get_by_role('heading', name='TEMP ' + ('外部网页' if name.startswith('外部') else '本机网页'))).to_be_visible()
                                    assert len(context.pages) == count
                                    page.go_back()
                                    expect(gallery).to_be_visible()
                                    expect(page.get_by_role('textbox', name='对话输入')).to_have_value(DRAFT)
                                    page.wait_for_timeout(400)
                                    restored_scroll = page.locator('.chat-messages').evaluate('el=>el.scrollTop')
                                    assert abs(restored_scroll - document_scroll) < 3, (name, document_scroll, restored_scroll)
                                else:
                                    assert len(context.pages) > count
                                    context.pages[-1].close()
                            if mobile:
                                assert all(item['contained'] and abs(item['ratio'] - item['expected']) < .01 for item in measurements), measurements
                                assert wrap['scrollWidth'] <= wrap['width'] + 1, wrap
                                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                                for control in gallery.locator('button,a').all():
                                    bounds = control.bounding_box()
                                    assert bounds and bounds['width'] >= 43.5 and bounds['height'] >= 43.5, bounds
                                for control in page.locator('.msg-action,.composer-attach-btn,.brush-btn').all():
                                    if not control.is_visible(): continue
                                    bounds = control.bounding_box()
                                    assert bounds and bounds['width'] >= 43.5 and bounds['height'] >= 43.5, bounds
                                assert page.locator('.msg-actions').first.evaluate('el=>getComputedStyle(el).opacity') == '1'
                                toolbar = page.locator('.composer-bar').evaluate('el=>[...el.children].map(child=>{const r=child.getBoundingClientRect();return {left:r.left,right:r.right,width:child.clientWidth,scrollWidth:child.scrollWidth}})')
                                assert all(item['scrollWidth'] <= item['width'] + 1 for item in toolbar), toolbar
                                assert all(toolbar[index]['right'] <= toolbar[index+1]['left'] + 1 for index in range(len(toolbar)-1)), toolbar
                            assert copy_ok
                            report['checks'].append({'case': label, 'passed': True, 'images': measurements, 'text': wrap,
                                                     'clipboard_exact': copy_ok, 'close_and_browser_back': True,
                                                     'external_and_local_html_return': True, 'draft_and_scroll_preserved': True})
                            context.close()
                    assert not fixture['adapter'].requests, 'Unexpected inference request'
                    report['no_inference'] = True
                browser.close()
        report['diagnostic_completed'] = not report['errors'] and bool(report['checks'])
        report['passed'] = report['diagnostic_completed'] and not args.baseline
    except Exception as error:
        report['errors'].append(repr(error))
        raise
    finally:
        (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    assert report['diagnostic_completed'] if args.baseline else report['passed'], report
    print(json.dumps({'status': 'diagnostic' if args.baseline else 'ok', 'passed': report['passed'], 'baseline': args.baseline, 'cases': len(report['checks']), 'report': str(out / 'report.json')}))


if __name__ == '__main__':
    main()
