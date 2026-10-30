"""Windows Edge: TEMP topic board and one native synthetic discussion per click."""
import argparse
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlencode,urlsplit,parse_qs

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('native_fixture',Path(__file__).with_name('workbench_native_browser.py'))
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--native',required=True);parser.add_argument('--out',required=True);args=parser.parse_args()
    from playwright.sync_api import sync_playwright,expect
    native=Path(args.native).resolve();out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
    report={'passed':False,'real_AI_calls':0,'real_platform_writes':0,'physical_mobile_device_tested':False,'checks':[],'native':{'release':native.name,'manifest_sha256':h.sha(native/'native-manifest.json')}}
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
            blank=browser.new_page();blank.set_content('TEMP');image=blank.screenshot();blank.close()
            with h.isolated(native,image) as f:
                context=browser.new_context(ignore_https_errors=True,viewport={'width':1440,'height':960})
                context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
                page=context.new_page();page.set_default_timeout(20000);errors=[]
                page.on('pageerror',lambda error:errors.append(str(error)))
                def visit(path):page.goto(f['origin']+'/native/?'+urlencode({'path':path}),wait_until='domcontentloaded')
                def check(name):report['checks'].append({'name':name,'passed':True})
                visit('/toolbox')
                page.locator('.dash-trend-title').first.click()
                page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.startsWith('/chat/')")
                sid=parse_qs(urlsplit(page.url).query)['path'][0].split('/chat/')[1]
                history=h.wait_history(page,f['origin'],sid)
                assert len(f['adapter'].requests)==1
                prompt=history['session']['messages'][0]['content']
                assert '2-3 个差异化' in prompt and 'TEMP 新闻来源' in prompt
                assert history['session']['profile_id']=='oil-pig'
                assert page.get_by_role('button',name='上一篇',exact=True).count()==0
                page.reload();expect(page.get_by_role('textbox',name='对话输入')).to_be_visible();page.wait_for_timeout(600)
                assert len(f['adapter'].requests)==1
                with f['box'].store.connect() as c:assert c.execute('SELECT count(*) FROM toolbox_jobs').fetchone()[0]==0
                check('dashboard click starts one native discussion with original prompt; reload does not replay or produce')
                visit('/toolbox?section=research&pane=topics')
                expect(page.get_by_role('heading',name='选题库',exact=True)).to_be_visible()
                assert page.locator('.ew-topbar').is_hidden()
                assert page.get_by_role('button',name='返回',exact=True).count()==0
                assert page.locator('.kanban-col').count()==3
                page.screenshot(path=str(out/'topics-empty.png'))
                page.get_by_role('button',name='+ 新建选题',exact=True).click()
                modal=page.locator('.modal');expect(modal).to_be_visible()
                fields=modal.locator('.field');fields.nth(0).fill('TEMP 看板选题');fields.nth(1).fill('原始备注');fields.nth(2).fill('手动灵感')
                page.screenshot(path=str(out/'topic-new.png'))
                modal.get_by_role('button',name='保存',exact=True).click()
                expect(page.locator('.idea-title',has_text='TEMP 看板选题')).to_be_visible()
                page.reload();expect(page.locator('.idea-title',has_text='TEMP 看板选题')).to_be_visible()
                card=page.locator('.idea-card',has_text='TEMP 看板选题')
                card.get_by_title('推进状态').click()
                expect(page.locator('.kanban-col').nth(1).locator('.idea-title')).to_have_text('TEMP 看板选题')
                card.hover();card.get_by_title('编辑',exact=True).click();fields=page.locator('.modal .field');expect(fields.nth(1)).to_have_value('原始备注');fields.nth(0).fill('TEMP 修改后选题');page.locator('.modal').get_by_role('button',name='保存',exact=True).click()
                card=page.locator('.idea-card',has_text='TEMP 修改后选题');expect(card).to_be_visible()
                card.get_by_role('button',name='排期',exact=True).click();expect(page.get_by_text('已加入日历（今天）',exact=True)).to_be_visible()
                card.get_by_role('button',name='做内容',exact=True).click();page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.startsWith('/chat/')")
                sid=parse_qs(urlsplit(page.url).query)['path'][0].split('/chat/')[1];h.wait_history(page,f['origin'],sid);assert len(f['adapter'].requests)==2
                visit('/toolbox?section=research&pane=topics');card=page.locator('.idea-card',has_text='TEMP 修改后选题');card.hover();card.get_by_title('删除',exact=True).click();expect(page.get_by_text('TEMP 修改后选题',exact=True)).to_have_count(0)
                check('upstream board and modal create edit advance schedule use delete; persistence survives reload')
                for width,theme in [(1440,'dark'),(390,'light'),(390,'dark')]:
                    page.set_viewport_size({'width':width,'height':844});page.evaluate('theme=>document.documentElement.dataset.theme=theme',theme)
                    page.screenshot(path=str(out/f'topics-{width}-{theme}.png'))
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                check('desktop and simulated narrow viewport in both themes have no horizontal overflow')
                assert not errors,errors
                report['errors']=errors;report['passed']=True
                context.close()
            browser.close()
    finally:
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
