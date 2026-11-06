"""Frozen candidate, actual Edge/TEMP owner API; synthetic review/metrics only."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import traceback
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://mp.weixin.qq.com/s/TEMP-insights-exact-version'
METHOD = '围绕一条信息主线逐图展开，保留手机可读字号与准确角色。'


def seed(f, image):
    from easel_workbench.features.works.native_review import binding, instructions, receive
    from easel_workbench.features.production_insights.service import service
    business = SimpleNamespace(root=f['root'], store=f['box'].store, box=f['box'], _session=lambda value: {'profile_id': 'oil-pig'})
    frame = binding(business, {'turnId': 'TEMP-insights-version', 'sessionId': 'TEMP-insights-session', 'context': {'skill_id': 'oil-pig-poster'}})
    folder = Path(frame['product_directory']); folder.mkdir(parents=True)
    picture = folder / '成品.png'; picture.write_bytes(image)
    copy = folder / '标题与配文.txt'; copy.write_text('TEMP 制作复盘准确标题\n保留准确新闻、角色与手机阅读规范。', encoding='utf-8')
    style = {'writing': 'editorial-writing', 'visual': 'scene-visual', 'character': 'simple-pig', 'layout': 'page-roles'}
    turn = {'id': frame['version_id'], 'session_id': frame['session_id'], 'status': 'completed', 'hook_status': 'completed',
            'profile_id': 'oil-pig', 'runtime': 'codex', 'model': 'TEMP-synthetic-only', 'message': '请制作贴图，保持手机字号清晰。',
            'actual_prompt': '准确本轮制作输入；使用油猪·做贴图。', 'actual_prompt_sha256': 'a' * 64,
            'native_turn_id': 'TEMP-exact-native-turn', 'created_at': '2026-11-06T10:00:00+08:00', 'updated_at': '2026-11-06T10:00:01+08:00',
            'context': {'skill_id': 'oil-pig-poster', 'creation': {'intent': 'produce', 'format': 'poster', 'style': style, 'note': '旧新闻备注不能自动带进新制作'}},
            'output': '[成品](' + picture.as_posix() + ')\n[标题与配文](' + copy.as_posix() + ')', 'frozen_instructions': instructions(frame)}
    with f['box'].store.connect() as c:
        c.execute('INSERT INTO easel_chat_turns VALUES(?,?,?,?,?)', (turn['id'], turn['session_id'], 'TEMP-insights-operation', 'signature', json.dumps(turn, ensure_ascii=False)))
    receipt = receive(business, turn)
    assert receipt['status'] == 'completed' and receipt['whole_ready'], receipt
    turn['business_receipt'] = {'review_candidate': receipt}
    with f['box'].store.connect() as c:
        c.execute('UPDATE easel_chat_turns SET document=? WHERE id=?', (json.dumps(turn, ensure_ascii=False), turn['id']))
        c.execute("INSERT INTO toolbox_jobs(id,work_id,kind,text,candidate_id,files,scope,signature,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  ('TEMP-raw-feedback', frame['work_id'], 'feedback', '用户原话：这次角色表现非常满意，保留这个规范。', turn['id'], '[]', '[]', 'TEMP', 'completed', '2026-11-06'))
    hub = service(f['box']); hub.reviews.enqueue(turn, receipt)
    def answer(value, part):
        source = part['sources'][0]['source_id'] if part['sources'] else part['images'][0]['id']
        return {'summary': 'TEMP 合成复盘：准确制作流程可复用。', 'items': [{'title': '手机阅读与主线组织', 'lesson': METHOD,
                'category': 'process', 'source_ids': [source], 'basis': 'ai_suggestion'}]}
    hub.reviews.execute = answer
    for _ in range(40):
        if not hub.reviews.run_pending_once():
            break
    review = hub.reviews.view(frame['work_id'], turn['id'])
    assert review['status'] == 'completed' and len(review['items']) == 1, review
    hub.metrics.connected = lambda: True
    hub.metrics.fetch = lambda: {'loggedIn': True, 'coverage': {'articles': 1}, 'articles': [{
        'title': 'TEMP 准确发布标题', 'url': URL, 'structured_metrics': {'read_uv': 25, 'likes': 0, 'shares': None}}]}
    # Manual fixture registration bypasses ChatBusiness.finished's normal signal.
    native = getattr(f['box'], '_native_api', None)
    if native is not None:
        native.library.invalidate()
    return frame, hub


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('backend', 'native', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(); backend, native, out = args.backend.resolve(), args.native.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    spec = importlib.util.spec_from_file_location('insights_browser_helper', ROOT / 'tests/workbench_news_creation_browser.py')
    h = importlib.util.module_from_spec(spec); spec.loader.exec_module(h)
    helper, application, create_app = h.infrastructure(backend, native)
    from playwright.sync_api import sync_playwright, expect
    expect.set_options(timeout=20000)
    report = {'passed': False, 'checks': [], 'backend': h.frozen(backend, 'workbench-release.json'), 'native': h.frozen(native, 'native-manifest.json'),
              'real_model_calls': 0, 'real_platform_calls': 0, 'platform_writes': 0, 'production_data_access': False,
              'physical_device_tested': False, 'errors': [], 'screenshots': {}, 'harness_sha256': h.sha(__file__)}
    def check(layout, name):
        report['checks'].append({'layout': layout, 'name': name, 'passed': True}); print('PASS', layout, name, flush=True)
    try:
      with patch.object(application, 'create_app', create_app), sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True, args=['--ignore-certificate-errors'])
        for layout, width, height, mobile, theme in h.LAYOUTS:
          with helper.isolated(native, h.IMAGE) as f:
            frame, hub = seed(f, h.IMAGE); article = h.seed_news(f)
            context = browser.new_context(ignore_https_errors=True, viewport={'width': width, 'height': height}, is_mobile=mobile, has_touch=mobile, service_workers='block')
            context.add_cookies([{'name': '__Host-desk_session', 'value': 'fixture-owner', 'url': f['origin'], 'secure': True, 'httpOnly': True, 'sameSite': 'Strict'}])
            context.add_init_script('localStorage.setItem("native:theme",' + json.dumps(theme) + ')')
            page = context.new_page(); page.set_default_timeout(30000)
            page.on('pageerror', lambda error: report['errors'].append(str(error)))
            def guard(route):
                assert urlsplit(route.request.url).hostname in ('localhost', '127.0.0.1'), 'TEMP browser cannot access external or production services'
                route.continue_()
            page.route('**/*', guard)
            def shot(name):
                file = out / (layout + '-' + name + '.png'); page.screenshot(path=str(file)); report['screenshots'][file.name] = h.sha(file)
            h.goto(page, f['origin'], '/works?' + urlencode({'path': 'workbench-' + frame['work_id'] + '/' + frame['version_id']}))
            details = page.locator('details').filter(has=page.locator('summary', has_text='版本与操作')).first
            expect(details).to_be_visible(); details.locator('summary').first.click()
            launcher = page.get_by_role('button', name='制作复盘', exact=True); expect(launcher).to_be_visible(); launcher.click()
            drawer = page.get_by_role('dialog', name='制作复盘', exact=True); expect(drawer).to_be_visible()
            expect(drawer.get_by_text('手机阅读与主线组织', exact=True)).to_be_visible()
            drawer.get_by_role('button', name='同意，待实施', exact=True).click()
            expect(drawer.locator('.ew-insight-item > small')).to_contain_text('同意，待实施')
            assert hub.reviews.view(frame['work_id'], frame['version_id'])['items'][0]['status'] == 'approved'
            shot('review-approved')
            assert drawer.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1')
            check(layout, 'original content detail and Drawer perform an exact per-item approval through authenticated HTTP')
            drawer.get_by_role('button', name='优秀模板', exact=True).click()
            drawer.get_by_role('textbox', name='模板名称', exact=True).fill('TEMP 已确认的优秀模板')
            drawer.get_by_role('button', name='以已同意建议为初稿', exact=True).click()
            expect(drawer.get_by_role('textbox', name='制作方法与图片规范', exact=True)).to_have_value(METHOD)
            drawer.get_by_role('checkbox', name='手机阅读与主线组织', exact=False).check()
            drawer.get_by_label('我已核对，并确认这是可复用的优秀制作模板', exact=True).check()
            drawer.get_by_role('button', name='确认保存模板', exact=True).click()
            expect(drawer.get_by_text('已保存“TEMP 已确认的优秀模板”，可在制作内容时选择。', exact=True)).to_be_visible()
            templates = hub.templates.list('oil-pig', 'poster'); assert len(templates) == 1 and templates[0]['available']
            assert not hub.templates.list('oil-pig', 'article')
            assert hub.reviews.view(frame['work_id'], frame['version_id'])['items'][0]['status'] == 'applied'
            shot('template-confirmed')
            assert drawer.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1')
            check(layout, 'human confirmation creates one immutable exact-version template with approved review provenance')
            drawer.get_by_role('button', name='发布数据', exact=True).click()
            drawer.get_by_role('textbox', name='已发布的微信公众号文章链接', exact=True).fill(URL)
            drawer.get_by_role('button', name='关联此准确版本', exact=True).click()
            expect(drawer.get_by_role('link', name='查看微信公众号文章', exact=True)).to_be_visible()
            drawer.get_by_role('button', name='刷新发布数据', exact=True).click()
            expect(drawer.get_by_text('25', exact=True)).to_be_visible()
            expect(drawer.get_by_text('0', exact=True)).to_be_visible()
            shot('publication-metrics')
            assert drawer.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1')
            check(layout, 'manual publication URL and read-only synthetic statistics preserve true zero versus missing')
            drawer.get_by_role('button', name='技能总记录', exact=True).click()
            expect(drawer.get_by_text('用户原话：这次角色表现非常满意，保留这个规范。', exact=True)).to_be_visible()
            shot('master')
            report.setdefault('geometry', {})[layout] = drawer.evaluate('(n)=>({width:n.clientWidth,scrollWidth:n.scrollWidth,overflows:[...n.querySelectorAll("*")].filter(x=>x.scrollWidth>x.clientWidth+1).map(x=>({tag:x.tagName,cls:x.className,width:x.clientWidth,scrollWidth:x.scrollWidth,text:x.textContent.slice(0,180)})).slice(0,30)})')
            assert drawer.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            drawer.get_by_role('button', name='关闭', exact=True).click(); expect(drawer).not_to_be_visible()
            expect(launcher).to_be_focused()
            check(layout, 'per-skill master preserves verbatim feedback; drawer closes to launcher without horizontal overflow')
            h.goto(page, f['origin'], '/news/a/' + article)
            page.get_by_role('button', name='制作内容', exact=True).click()
            creation = page.get_by_role('dialog', name='制作内容', exact=True)
            creation.get_by_role('button', name='贴图', exact=True).click()
            expect(creation.get_by_role('button', name='优秀制作模板', exact=True)).to_contain_text('不使用优秀模板')
            h.choose(page, creation, '优秀制作模板', 'TEMP 已确认的优秀模板', expect)
            expect(creation.get_by_role('button', name='角色呈现', exact=True)).to_contain_text('简笔小猪侠')
            template_detail = creation.locator('details').filter(has=page.locator('summary', has_text='模板方法与参考'))
            template_detail.locator('summary').click()
            expect(template_detail.get_by_text(METHOD, exact=True)).to_be_visible()
            assert creation.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1')
            assert not f['adapter'].requests, 'Template selection must not trigger production'
            shot('template-selection')
            check(layout, 'original creation select applies a compatible template without starting a new task or changing article skill')
            context.close()
        browser.close()
        assert not report['errors'], report['errors']; report['passed'] = True
    except Exception as error:
        report['error'] = repr(error)
        report['traceback'] = traceback.format_exc()
    finally:
        (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'error': report.get('error')}, ensure_ascii=False))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
