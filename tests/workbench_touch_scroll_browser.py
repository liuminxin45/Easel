"""Real Edge touch-scroll regression on frozen native UI and TEMP backend data.

CDP dispatchTouchEvent produces browser-trusted touch gestures. scrollTop writes
only arrange initial boundary positions; every asserted movement follows a touch
swipe. No production state, model execution or platform operation is used.
"""
from __future__ import annotations

import argparse
from datetime import date
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from urllib.parse import urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def touch_swipe(page, session, x, y, delta):
    """One continuous finger gesture with a normal drag duration and touch slop."""
    def point(at):
        return {'x': x, 'y': at, 'radiusX': 5, 'radiusY': 5, 'force': 1}
    session.send('Input.dispatchTouchEvent', {'type': 'touchStart', 'touchPoints': [point(y)]})
    page.wait_for_timeout(40)
    for step in range(1, 13):
        session.send('Input.dispatchTouchEvent', {'type': 'touchMove', 'touchPoints': [point(y + delta * step / 12)]})
        page.wait_for_timeout(16)
    session.send('Input.dispatchTouchEvent', {'type': 'touchEnd', 'touchPoints': []})
    page.wait_for_timeout(700)


def prepare_list(page, outer, inner, mode):
    # Arranging a known boundary is setup, never the asserted scrolling action.
    point = page.evaluate('''({outer,inner,mode}) => {
      const parent=document.querySelector(outer),list=document.querySelector(inner);
      const offset=list.getBoundingClientRect().top-parent.getBoundingClientRect().top+parent.scrollTop;
      parent.scrollTop=Math.max(0,offset-100);
      const max=list.scrollHeight-list.clientHeight;
      list.scrollTop=mode==='bottom'?max:mode==='top'?0:max/3;
      const box=list.getBoundingClientRect();
      return {x:Math.min(innerWidth-30,Math.max(70,box.left+box.width/2)),
        y:mode==='top'?Math.max(160,box.top+80):Math.min(innerHeight-100,box.bottom-80)};
    }''', {'outer': outer, 'inner': inner, 'mode': mode})
    page.wait_for_timeout(150)
    return point


def scroll_state(page, outer, inner):
    return page.evaluate('''({outer,inner}) => {
      const parent=document.querySelector(outer),list=document.querySelector(inner);
      return {parentTop:parent.scrollTop,parentMax:parent.scrollHeight-parent.clientHeight,
        listTop:list.scrollTop,listMax:list.scrollHeight-list.clientHeight,
        overscrollY:getComputedStyle(list).overscrollBehaviorY,
        touchAction:getComputedStyle(list).touchAction,
        audit:{...window.nativeTouchAudit},url:location.href};
    }''', {'outer': outer, 'inner': inner})


def reset_audit(page):
    page.evaluate('''() => {
      window.nativeTouchAudit={starts:0,moves:0,prevented:0,untrusted:0,clicks:0};
      if(window.nativeTouchAuditInstalled)return;
      window.nativeTouchAuditInstalled=true;
      for(const type of ['touchstart','touchmove'])document.addEventListener(type,event=>{
        queueMicrotask(()=>{
          const audit=window.nativeTouchAudit;
          audit[type==='touchstart'?'starts':'moves']++;
          if(event.defaultPrevented)audit.prevented++;
          if(!event.isTrusted)audit.untrusted++;
        });
      },{passive:true});
      document.addEventListener('click',event=>{if(event.isTrusted)window.nativeTouchAudit.clicks++},true);
    }''')


def arrange_background(page, selector):
    position = page.locator(selector).evaluate('''element=>{
      const max=element.scrollHeight-element.clientHeight;
      element.scrollTop=max/2;return {top:element.scrollTop,max};
    }''')
    assert position['top'] >= 80 and position['max'] - position['top'] >= 80, 'Modal fixture needs scroll room in both directions'
    return position['top']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', required=True, type=Path)
    parser.add_argument('--backend', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--browser', type=Path, default=Path('C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'))
    args = parser.parse_args()
    native, backend, out = args.native.resolve(), args.backend.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((native / 'native-manifest.json').read_text(encoding='utf-8'))
    frozen = json.loads((backend / 'workbench-release.json').read_text(encoding='utf-8'))
    assert all(sha(native / name) == digest for name, digest in manifest['files'].items()), 'Frozen frontend bytes changed'
    assert all(sha(backend / name) == digest for name, digest in frozen['files'].items()), 'Frozen backend bytes changed'
    sys.path.insert(0, str(backend))
    fixture_path = ROOT / 'tests/workbench_native_browser.py'
    spec = importlib.util.spec_from_file_location('touch_browser_fixture', fixture_path)
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    fixture.ROOT = backend
    from playwright.sync_api import sync_playwright, expect
    expect.set_options(timeout=20000)
    report = {'passed': False, 'schema': 2, 'design_version': 'mobile-dashboard-single-scroll-v2',
              'replaced_design': {'version': 'nested-dashboard-v1', 'harness_snapshot': '.local/workbench-validation/touch-scroll-20261031/nested-dashboard-v1-harness.py',
                                  'replaced_assertions': ['dashboard inner scroll', 'dashboard nested top/bottom chaining', 'dashboard natural inner-to-outer transition'],
                                  'reason': 'Mobile dashboard summaries have three items per source; use one page scroller. Desktop bounded lists and mobile full news list remain unchanged.'},
              'checks': [], 'gestures': [], 'real_AI_calls': 0,
              'real_platform_writes': 0, 'physical_mobile_device_tested': False,
              'browser': str(args.browser), 'input': 'CDP Input.dispatchTouchEvent, browser-trusted touch events',
              'native': {'release': native.name, 'manifest_sha256': sha(native / 'native-manifest.json')},
              'backend': {'release': backend.name, 'manifest_sha256': sha(backend / 'workbench-release.json')},
              'harness_sha256': sha(__file__), 'fixture_sha256': sha(fixture_path)}

    def check(profile, name, passed, **evidence):
        report['checks'].append({'profile': profile, 'name': name, 'passed': bool(passed), **evidence})
        print(('PASS' if passed else 'FAIL') + ' ' + profile + ' ' + name, flush=True)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=str(args.browser), headless=True, args=['--ignore-certificate-errors'])
            seed = browser.new_page()
            seed.set_content('TEMP synthetic scroll image')
            image = seed.screenshot()
            seed.close()
            with fixture.isolated(native, image) as context_data:
                context_data['close_clients'] = lambda: [context.close() for context in browser.contexts]
                from easel_workbench.runtime.native_api import NativeApi
                native_api = NativeApi(context_data['box'])
                context_data['box']._native_api = native_api
                native_api._save_ideas([{'id': 'TEMP-touch-topic-' + str(number), 'title': 'TEMP_TOUCH_TOPIC ' + '真实摘要末条 ' * 8 + str(number),
                                         'note': 'TEMP only', 'source': 'TEMP', 'status': 'pending'} for number in range(6)])
                native_api._save_schedule([{'id': 'TEMP-touch-plan-' + str(number), 'title': 'TEMP_TOUCH_PLAN ' + '真实排期摘要 ' * 8 + str(number),
                                           'date': date.today().isoformat(), 'time': '12:30', 'platform': '公众号', 'status': 'scheduled',
                                           'note': 'TEMP only', 'kind': 'content', 'source': 'manual'} for number in range(6)])
                source, definition = next(iter(context_data['app'].state.collection.registry.baseline().items()))
                context_data['box'].store.ingest({'schema_version': 1, 'source_job': source, 'feed_id': definition['feed'],
                    'run_id': 'touch-scroll-regression', 'run_at': '2026-10-31T08:00:00Z', 'final_text': 'TEMP',
                    'articles': [{'title': f'TEMP {number:02d} ' + '触摸滚动测试文本 ' * 8, 'body': 'TEMP stored text.',
                                  'url': f'https://example.com/touch/{number}', 'source_order': number} for number in range(1, 51)]})
                for profile, width, theme in [('mobile-320-light', 320, 'light'), ('mobile-390-dark', 390, 'dark')]:
                    context = browser.new_context(ignore_https_errors=True, viewport={'width': width, 'height': 844},
                                                  is_mobile=True, has_touch=True, color_scheme=theme)
                    context.add_cookies([{'name': '__Host-desk_session', 'value': 'fixture-owner', 'url': context_data['origin'],
                                          'secure': True, 'httpOnly': True, 'sameSite': 'Strict'}])
                    page = context.new_page()
                    session = context.new_cdp_session(page)
                    errors, writes = [], []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    # Durable analytics flushes are independent of a swipe; only
                    # those known telemetry batches are excluded from action writes.
                    page.on('request', lambda request: writes.append({'path': urlsplit(request.url).path, 'method': request.method})
                            if request.method not in ('GET', 'HEAD', 'OPTIONS') and urlsplit(request.url).path != '/api/usage/events' else None)

                    def go(path):
                        page.goto(context_data['origin'] + '/native/?' + urlencode({'path': path}), wait_until='domcontentloaded')

                    def ready_list(path, inner):
                        # Each independent scroll case has a fresh document and
                        # input widget/context. Do not JS-jump a list between
                        # completed gestures from different cases.
                        nonlocal context, page, session
                        context.close()
                        context = browser.new_context(ignore_https_errors=True, viewport={'width': width, 'height': 844},
                                                      is_mobile=True, has_touch=True, color_scheme=theme)
                        context.add_cookies([{'name': '__Host-desk_session', 'value': 'fixture-owner', 'url': context_data['origin'],
                                              'secure': True, 'httpOnly': True, 'sameSite': 'Strict'}])
                        page = context.new_page()
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.on('request', lambda request: writes.append({'path': urlsplit(request.url).path, 'method': request.method})
                                if request.method not in ('GET', 'HEAD', 'OPTIONS') and urlsplit(request.url).path != '/api/usage/events' else None)
                        session = context.new_cdp_session(page)
                        go(path)
                        page.wait_for_function('''selector=>{
                          const element=document.querySelector(selector);
                          return element&&element.scrollHeight-element.clientHeight>160
                            && !element.closest('[aria-busy=true]')&&!document.querySelector('.ew-loading');
                        }''', arg=inner)
                        page.evaluate('''async selector=>{
                          await document.fonts.ready;
                          const element=document.querySelector(selector);
                          let last=element.scrollTop,stable=0;
                          while(stable<8){await new Promise(requestAnimationFrame);const next=element.scrollTop;stable=next===last?stable+1:0;last=next}
                        }''', inner)

                    def gesture(outer, inner, mode, label):
                        point = prepare_list(page, outer, inner, mode)
                        reset_audit(page)
                        before = scroll_state(page, outer, inner)
                        action_count, page_count = len(writes), len(context.pages)
                        touch_swipe(page, session, point['x'], point['y'], 180 if mode == 'top' else -90 if mode == 'inside' else -180)
                        after = scroll_state(page, outer, inner)
                        evidence = {'profile': profile, 'page': label, 'mode': mode, 'before': before, 'after': after}
                        report['gestures'].append(evidence)
                        parent_delta = after['parentTop'] - before['parentTop']
                        child_delta = after['listTop'] - before['listTop']
                        if mode == 'inside':
                            check(profile, label + ' list scrolls internally on the first swipe', before['listMax'] > 160 and child_delta >= 45 and abs(parent_delta) <= 3,
                                  child_delta=child_delta, parent_delta=parent_delta)
                        else:
                            available = before['parentTop'] if mode == 'top' else before['parentMax'] - before['parentTop']
                            check(profile, label + ' ' + mode + ' boundary hands the first swipe to its page', available >= 80 and (parent_delta <= -60 if mode == 'top' else parent_delta >= 60),
                                  available=available, parent_delta=parent_delta)
                        audit = after['audit']
                        check(profile, label + ' ' + mode + ' gesture stays native without clicks, navigation or action writes',
                              audit['starts'] == 1 and audit['moves'] > 0 and audit['untrusted'] == 0 and audit['prevented'] == 0
                              and audit['clicks'] == 0 and len(writes) == action_count and len(context.pages) == page_count and after['url'] == before['url'], audit=audit)

                    try:
                        for label, path, outer, inner in [('news', '/news', '.trends-page', '.trend-list')]:
                            for mode in ('inside', 'bottom', 'top'):
                                ready_list(path, inner)
                                gesture(outer, inner, mode, label)
                            page.screenshot(path=str(out / (profile + '-' + label + '.png')))

                            # Natural continuous scrolling: start near the end,
                            # consume any remaining inner pixels with real touch,
                            # then assert the first gesture that STARTS at the
                            # actual boundary scrolls the outer page. A gesture
                            # beginning with 4px left may consume those 4px only;
                            # that is browser scroll latching, not application JS.
                            ready_list(path, inner)
                            point = prepare_list(page, outer, inner, 'bottom')
                            page.locator(inner).first.evaluate('element=>element.scrollTop=element.scrollHeight-element.clientHeight-90')
                            reset_audit(page)
                            steps = []
                            for _ in range(4):
                                before = scroll_state(page, outer, inner)
                                if before['listMax'] - before['listTop'] <= 1: break
                                touch_swipe(page, session, point['x'], point['y'], -90 if not steps else -130)
                                after = scroll_state(page, outer, inner)
                                steps.append({'phase': 'consume_remaining_inner_pixels', 'before': before, 'after': after})
                            before = scroll_state(page, outer, inner)
                            touch_swipe(page, session, point['x'], point['y'], -180)
                            after = scroll_state(page, outer, inner)
                            report['gestures'].append({'profile': profile, 'page': label, 'mode': 'natural-bottom-chain', 'steps': steps, 'before': before, 'after': after})
                            check(profile, label + ' naturally reached bottom hands the next first boundary swipe to its page',
                                  before['listMax']-before['listTop'] <= 1 and after['parentTop']-before['parentTop'] >= 60,
                                  inner_gestures=len(steps), remaining=before['listMax']-before['listTop'], parent_delta=after['parentTop']-before['parentTop'])

                        def ready_dashboard():
                            go('/toolbox')
                            page.wait_for_function("()=>document.querySelectorAll('.dash-trend-item').length>=3&&document.querySelector('.dash-idea-title')?.textContent.includes('TEMP_TOUCH_TOPIC')&&document.querySelector('.dash-sched-title')?.textContent.includes('TEMP_TOUCH_PLAN')&&!document.querySelector('.ew-loading')")
                            page.evaluate('''async()=>{await document.fonts.ready;for(let n=0;n<8;n++)await new Promise(requestAnimationFrame)}''')

                        ready_dashboard()
                        boards = page.locator('.dash-card')
                        layout = boards.evaluate_all('''nodes=>nodes.map(element=>{const style=getComputedStyle(element);return {overflowY:style.overflowY,maxHeight:style.maxHeight,clientHeight:element.clientHeight,scrollHeight:element.scrollHeight,childCount:element.children.length}})''')
                        check(profile, 'dashboard summaries have no nested vertical scroll container',
                              page.locator('.dash-card-list').count()==0 and bool(layout) and all(row['overflowY']=='visible' and row['maxHeight']=='none' and row['scrollHeight']<=row['clientHeight']+1 for row in layout), boards=layout)
                        check(profile, 'dashboard keeps every source summary and its real final item',
                              boards.count()>=3 and page.locator('.dash-trend-item').count()>=3 and all(row['childCount']>0 for row in layout), board_count=boards.count(), trend_items=page.locator('.dash-trend-item').count())
                        point = prepare_list(page, '.dash-page', '.dash-card', 'top')
                        point['y'] = min(600, max(200, point['y']))
                        reset_audit(page)
                        before = scroll_state(page, '.dash-page', '.dash-card')
                        action_count = len(writes)
                        touch_swipe(page, session, point['x'], point['y'], -180)
                        after = scroll_state(page, '.dash-page', '.dash-card')
                        check(profile, 'first swipe starting within a dashboard summary moves the page', after['parentTop']-before['parentTop']>=60 and after['listTop']==0,
                              parent_delta=after['parentTop']-before['parentTop'], inner_top=after['listTop'])
                        audit = after['audit']
                        check(profile, 'dashboard page swipe is trusted and has no accidental click or action', audit['starts']==1 and audit['moves']>0 and audit['prevented']==0 and audit['untrusted']==0 and audit['clicks']==0 and len(writes)==action_count and after['url']==before['url'], audit=audit)
                        reachable = []
                        for index in range(boards.count()):
                            last = boards.nth(index).locator(':scope > :last-child')
                            for _ in range(12):
                                box = last.bounding_box()
                                if box and box['y']+box['height']<=824: break
                                touch_swipe(page, session, width/2, 680, -260)
                            box = last.bounding_box()
                            reachable.append(bool(box and box['y']>=0 and box['y']+box['height']<=844))
                        check(profile, 'all dashboard summary final items are reachable through native page touch scrolling', all(reachable), final_items=reachable)
                        ready_dashboard()
                        point = prepare_list(page, '.dash-page', '.dash-card', 'top')
                        point['y'] = min(600, max(200, point['y']))
                        deltas = []
                        for _ in range(2):
                            before = page.locator('.dash-page').evaluate('element=>element.scrollTop')
                            touch_swipe(page, session, point['x'], point['y'], -180)
                            deltas.append(page.locator('.dash-page').evaluate('element=>element.scrollTop')-before)
                        check(profile, 'dashboard consecutive native swipes keep scrolling the single page', all(delta>=60 for delta in deltas), page_deltas=deltas)
                        page.screenshot(path=str(out / (profile + '-dashboard-single-scroll.png')))

                        # The navigation backdrop intentionally captures gestures;
                        # removing list containment must not unlock background pages.
                        page.locator('.sidebar-toggle').click()
                        expect(page.locator('.sidebar-panel')).to_have_attribute('aria-modal', 'true')
                        backdrop = page.locator('.sidebar-backdrop')
                        expect(backdrop).to_be_visible()
                        background_before = arrange_background(page, '.dash-page')
                        reset_audit(page)
                        action_count = len(writes)
                        touch_swipe(page, session, width - 20, 600, -180)
                        check(profile, 'navigation backdrop swipe does not scroll or dismiss its background',
                              page.locator('.dash-page').evaluate('element=>element.scrollTop') == background_before
                              and page.locator('.sidebar-panel').get_attribute('aria-modal') == 'true' and len(writes) == action_count)
                        page.locator('.sidebar-close').click()

                        go('/settings?panel=more')
                        expect(page.get_by_role('dialog', name='设置', exact=True)).to_be_visible()
                        settings = '.settings-main'
                        page.wait_for_selector(settings)
                        page.wait_for_timeout(500)
                        # Boundary positions are arranged on the actual modal. All
                        # background observations still follow genuine touch input.
                        for boundary, delta in [('bottom', -180), ('top', 180)]:
                            point = page.locator(settings).evaluate('''(element,boundary)=>{
                              element.scrollTop=boundary==='bottom'?element.scrollHeight:0;
                              const box=element.getBoundingClientRect();return {x:box.left+box.width/2,y:boundary==='bottom'?box.bottom-70:box.top+70};
                            }''', boundary)
                            before = arrange_background(page, '.dash-page')
                            action_count = len(writes)
                            reset_audit(page)
                            touch_swipe(page, session, point['x'], point['y'], delta)
                            after = page.locator('.dash-page').evaluate('element=>element.scrollTop')
                            audit = page.evaluate('window.nativeTouchAudit')
                            report['gestures'].append({'profile': profile, 'page': 'settings', 'mode': boundary,
                                                       'background_before': before, 'background_after': after, 'audit': audit})
                            check(profile, 'settings ' + boundary + ' boundary does not scroll its background or issue an action',
                                  after == before and len(writes) == action_count and audit['starts'] == 1 and audit['moves'] > 0
                                  and audit['untrusted'] == 0 and audit['clicks'] == 0
                                  and page.get_by_role('dialog', name='设置', exact=True).is_visible())

                        go('/news')
                        page.wait_for_selector('.trend-list')
                        # Also cover an actual showModal() top-layer dialog,
                        # whose DOM remains inside the scrollable news page.
                        page.locator('.trends-page').evaluate('element=>element.scrollTop=150')
                        page.get_by_role('button', name='数据源', exact=True).click()
                        manager = page.locator('dialog.trend-manager')
                        expect(manager).to_be_visible()
                        for boundary, delta in [('bottom', -180), ('top', 180)]:
                            point = manager.evaluate('''(element,boundary)=>{
                              element.scrollTop=boundary==='bottom'?element.scrollHeight:0;
                              const box=element.getBoundingClientRect();return {x:box.left+box.width/2,y:boundary==='bottom'?box.bottom-70:box.top+70};
                            }''', boundary)
                            before = arrange_background(page, '.trends-page')
                            action_count = len(writes)
                            reset_audit(page)
                            touch_swipe(page, session, point['x'], point['y'], delta)
                            after = page.locator('.trends-page').evaluate('element=>element.scrollTop')
                            audit = page.evaluate('window.nativeTouchAudit')
                            report['gestures'].append({'profile': profile, 'page': 'native-dialog', 'mode': boundary,
                                                       'background_before': before, 'background_after': after, 'audit': audit})
                            check(profile, 'native dialog ' + boundary + ' boundary does not scroll its background or issue an action',
                                  after == before and len(writes) == action_count and manager.is_visible()
                                  and audit['starts'] == 1 and audit['moves'] > 0 and audit['untrusted'] == 0 and audit['clicks'] == 0)

                        # Old div modals have no native showModal scroll barrier.
                        # Use a short layout viewport so both the actual modal
                        # and its long background have genuine scroll ranges.
                        page.set_viewport_size({'width': width, 'height': 390})
                        page.route('**/api/ideas', lambda route: route.fulfill(json=[{
                            'id': 'TEMP-idea-' + str(number), 'title': 'TEMP 长选题 ' + '原始来源内容 ' * 8,
                            'note': 'TEMP synthetic notes only.', 'source': 'TEMP', 'status': 'pending'} for number in range(30)])
                            if route.request.method == 'GET' else route.fulfill(status=405, json={'error': 'TEMP no saves'}))
                        page.route('**/api/accounts', lambda route: route.fulfill(json=[{
                            'platform': 'TEMP-platform-' + str(number), 'name': 'TEMP 合成账号 ' + str(number),
                            'backend': 'web', 'supported': True, 'loggedIn': False} for number in range(20)]))
                        qr_status = {'mode': 'qr', 'state': 'qr_ready', 'message': 'TEMP 合成二维码，请勿扫码。' + '触摸验证 ' * 12,
                                     'qr': 'TEMP-touch-qr.png', 'qrTs': 1}
                        page.route('**/api/login/TEMP-platform-0**', lambda route: route.fulfill(json=qr_status))
                        page.route('**/api/media/TEMP-touch-qr.png**', lambda route: route.fulfill(content_type='image/png', body=image))
                        for label, path, background in [
                            ('calendar-div-modal', '/toolbox?section=calendar', '.calendar-page'),
                            ('idea-div-modal', '/toolbox?section=research', '.ideas-page'),
                            ('QR-div-modal', '/toolbox?section=distribution&pane=connections', '.accounts-page')]:
                            go(path)
                            page.wait_for_selector(background)
                            if label == 'calendar-div-modal': page.locator('.cal-cell').first.click()
                            elif label == 'idea-div-modal': page.get_by_role('button', name='+ 新建选题', exact=True).click()
                            else:
                                page.get_by_role('button', name='登录', exact=True).first.click()
                                expect(page.get_by_alt_text('登录二维码', exact=True)).to_be_visible()
                            modal = page.locator('.overlay > .modal')
                            expect(modal).to_be_visible()
                            for boundary, delta in [('bottom', -130), ('top', 130), ('backdrop', -130)]:
                                if boundary == 'backdrop':
                                    point = {'x': 4, 'y': 240}
                                else:
                                    point = modal.evaluate('''(element,boundary)=>{
                                      element.scrollTop=boundary==='bottom'?element.scrollHeight:0;
                                      const box=element.getBoundingClientRect();return {x:box.left+box.width/2,y:boundary==='bottom'?box.bottom-65:box.top+65};
                                    }''', boundary)
                                before = arrange_background(page, background)
                                action_count = len(writes)
                                reset_audit(page)
                                touch_swipe(page, session, point['x'], point['y'], delta)
                                after = page.locator(background).evaluate('element=>element.scrollTop')
                                audit = page.evaluate('window.nativeTouchAudit')
                                report['gestures'].append({'profile': profile, 'page': label, 'mode': boundary,
                                                           'background_before': before, 'background_after': after, 'audit': audit})
                                check(profile, label + ' ' + boundary + ' swipe stays isolated from its background and actions',
                                      after == before and len(writes) == action_count and modal.is_visible()
                                      and audit['starts'] == 1 and audit['moves'] > 0 and audit['untrusted'] == 0 and audit['clicks'] == 0)
                            page.screenshot(path=str(out / (profile + '-' + label + '.png')))
                        page.set_viewport_size({'width': width, 'height': 844})
                        check(profile, 'touch regressions have no runtime errors or model calls', not errors and not context_data['adapter'].requests, errors=errors)
                    except BaseException as error:
                        page.screenshot(path=str(out / (profile + '-failure.png')), full_page=True)
                        raise error
                    finally:
                        context.close()
                roots = []
                for name, module in sys.modules.items():
                    filename = getattr(module, '__file__', None)
                    if filename and (name == 'easel_workbench' or name.startswith('easel_workbench.') or name == 'easel' or name.startswith('easel.')):
                        roots.append(Path(filename).resolve())
                report['module_count'] = len(roots)
                report['module_roots_valid'] = all(path.is_relative_to(backend) for path in roots)
                assert report['module_roots_valid'], 'Runtime imported source outside the frozen backend'
                report['passed'] = bool(report['checks']) and all(item['passed'] for item in report['checks'])
            browser.close()
    except BaseException as error:
        report['error'] = {'type': type(error).__name__, 'message': str(error)}
    finally:
        report['evidence'] = {path.name: sha(path) for path in out.glob('*.png')}
        (out / 'touch-scroll.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'error': report.get('error')}, ensure_ascii=True), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
