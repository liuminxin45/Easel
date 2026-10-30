"""Cross-page interaction latency checks on TEMP HTTPS data in Windows Edge."""
import argparse
import importlib.util
import json
import re
import time
from pathlib import Path
import sys
from urllib.parse import urlencode,urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('interaction_browser_fixture',Path(__file__).with_name('workbench_native_browser.py'))
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--native',required=True);parser.add_argument('--out',required=True);parser.add_argument('--backend');args=parser.parse_args()
    if args.backend:sys.path.insert(0,str(Path(args.backend).resolve()))
    from playwright.sync_api import sync_playwright,expect
    from easel_workbench.runtime.content_studio import save_text
    expect.set_options(timeout=15000)
    out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True);native=Path(args.native).resolve()
    report={'passed':False,'checks':[],'real_AI_calls':0,'real_platform_writes':0,'physical_mobile_device_tested':False,'harness_sha256':h.sha(__file__),'native':{'release':native.name,'manifest_sha256':h.sha(native/'native-manifest.json')}}
    if args.backend:report['backend']={'directory':str(Path(args.backend).resolve()),'manifest_sha256':h.sha(Path(args.backend)/'workbench-release.json')}
    def mark(profile,name):report['checks'].append({'profile':profile,'check':name});print('PASS',profile,name,flush=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
            image_page=browser.new_page();image_page.set_content('TEMP synthetic image');image=image_page.screenshot();image_page.close()
            with h.isolated(native,image) as f:
                f['close_clients']=lambda:[context.close() for context in browser.contexts]
                save_text(f['box'],'calendar-work',{'id':'calendar-work','title':'TEMP 日历作品','body':'TEMP 用户冻结原文','format':'article'},new=True)
                for profile,width,mobile in [('desktop',1280,False),('mobile-simulated',390,True)]:
                    context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':900},is_mobile=mobile,has_touch=mobile)
                    context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
                    page=context.new_page();page.set_default_timeout(15000);errors=[];posts=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    page.on('request',lambda request:posts.append({'path':urlsplit(request.url).path,'body':request.post_data_json}) if request.method=='POST' and request.post_data else None)
                    def go(path):page.goto(f['origin']+'/native/?'+urlencode({'path':path}),wait_until='domcontentloaded')
                    def hold(path):
                        waiting=[]
                        def handler(route):
                            if route.request.method=='POST':waiting.append(route)
                            else:route.continue_()
                        page.route('**'+path,handler);return waiting,handler
                    def read_hold(path):
                        waiting=[]
                        def handler(route):
                            if route.request.method=='GET':waiting.append(route)
                            else:route.fallback()
                        page.route('**'+path,handler);return waiting,handler
                    def release_reads(rows,pattern,handler):
                        page.unroute('**'+pattern,handler)
                        for route in rows:
                            try:route.continue_()
                            except Exception:pass
                    def busy(button):
                        expect(button).to_have_attribute('aria-busy','true');expect(button).to_be_disabled();assert page.locator('.notice-error').count()==0
                        button.evaluate('element=>{element.click();element.click()}')
                    def pending_read(rows):
                        deadline=time.monotonic()+5
                        while not rows and time.monotonic()<deadline:page.wait_for_timeout(20)
                        assert rows,'background verification must be held independently of the accepted write'

                    go('/toolbox?section=profiles&item=oil-pig')
                    name=page.get_by_role('textbox',name='名称',exact=True);expect(name).to_be_visible();name.fill('TEMP 交互画像 '+profile)
                    waiting,handler=hold('/api/creator/commands');reads,reader=read_hold('/api/creator/bootstrap');button=page.get_by_role('button',name='保存画像',exact=True);button.click();busy(button)
                    assert len(waiting)==1;mark(profile,'profile click immediately shows busy feedback without red text or double submission')
                    response=waiting[0].fetch();assert response.ok,response.text();waiting[0].fulfill(response=response)
                    expect(button).to_be_enabled();expect(page.get_by_role('heading',name='TEMP 交互画像 '+profile,exact=True)).to_be_visible();assert reads,'bootstrap refresh must still be held'
                    assert page.locator('.notice-error').count()==0;page.screenshot(path=str(out/(profile+'-profile-accepted.png')),full_page=True)
                    mark(profile,'exact profile acknowledgement updates the view and releases save before list refresh')
                    page.unroute('**/api/creator/commands',handler);release_reads(reads,'/api/creator/bootstrap',reader)

                    waiting,handler=hold('/api/creator/commands');name.fill('TEMP rejected '+profile);button.click();busy(button)
                    waiting[0].fulfill(status=400,content_type='application/json',body=json.dumps({'error':'TEMP 名称校验失败'},ensure_ascii=False))
                    expect(page.get_by_role('alert').filter(has_text='TEMP 名称校验失败')).to_be_visible();expect(button).to_be_enabled();expect(name).to_have_value('TEMP rejected '+profile)
                    mark(profile,'definite validation rejection remains visible and preserves editable input')
                    page.unroute('**/api/creator/commands',handler)

                    go('/toolbox?section=skills&item=content-writing')
                    page.get_by_role('button',name='编辑方法，另存候选',exact=True).click();reason=page.get_by_role('textbox',name='修改理由',exact=True);reason.fill('TEMP interaction '+profile)
                    prompt=page.get_by_role('textbox',name='完整技能提示词',exact=True);prompt.fill(prompt.input_value()+'\nTEMP interaction '+profile)
                    waiting,handler=hold('/api/creator/commands');reads,reader=read_hold('/api/creator/bootstrap');save=page.get_by_role('button',name='保存候选修订',exact=True);save.click();busy(save)
                    assert len(waiting)==1;response=waiting[0].fetch();assert response.ok,response.text();version=response.json()['result']['skill']['version'];waiting[0].fulfill(response=response)
                    page.wait_for_function("version=>new URL(new URLSearchParams(location.search).get('path'),'https://native.invalid').searchParams.get('version')===String(version)",arg=version)
                    expect(save).not_to_be_visible();assert reads;assert page.locator('.notice-error').count()==0
                    mark(profile,'skill draft acknowledges and closes its form while bootstrap reload remains pending')
                    page.unroute('**/api/creator/commands',handler);release_reads(reads,'/api/creator/bootstrap',reader)

                    go('/toolbox?section=calendar')
                    page.get_by_role('combobox',name='排期作品',exact=True).select_option('calendar-work')
                    page.get_by_label('排期时间',exact=True).fill('2026-11-05T10:30');waiting,handler=hold('/api/easel/commands');reads,reader=read_hold('/api/easel/plans');save=page.get_by_role('button',name='保存排期',exact=True);save.click();busy(save)
                    assert len(waiting)==1;response=waiting[0].fetch();assert response.ok,response.text();waiting[0].fulfill(response=response)
                    expect(page.get_by_label('排期时间',exact=True)).to_have_value('');assert reads;assert page.locator('.notice-error').count()==0
                    mark(profile,'calendar save ends at acknowledgement and projects the exact plan without waiting for GET')
                    page.unroute('**/api/easel/commands',handler);release_reads(reads,'/api/easel/plans',reader)

                    go('/settings?panel=more')
                    page.get_by_role('button',name='清空统计',exact=True).click();dialog=page.get_by_role('dialog',name='清空操作统计？',exact=True);waiting,handler=hold('/api/usage/clear');reads,reader=read_hold('/api/usage/summary');confirm=dialog.get_by_role('button',name='确认清空统计',exact=True);confirm.click();busy(confirm)
                    assert len(waiting)==1;response=waiting[0].fetch();assert response.ok,response.text();waiting[0].fulfill(response=response)
                    expect(dialog).not_to_be_visible();assert reads;assert page.locator('.notice-error').count()==0
                    mark(profile,'statistics confirmation closes after write acknowledgement while its independent read is pending')
                    page.unroute('**/api/usage/clear',handler);release_reads(reads,'/api/usage/summary',reader)

                    toggle=page.get_by_role('button',name=re.compile('^(暂停记录|开始记录)$'));expect(toggle).to_be_visible();next_label='开始记录' if toggle.inner_text().strip()=='暂停记录' else '暂停记录';waiting,handler=hold('/api/usage/settings');reads,reader=read_hold('/api/usage/summary');toggle.click();busy(toggle)
                    assert len(waiting)==1;response=waiting[0].fetch();assert response.ok,response.text();waiting[0].fulfill(response=response)
                    expect(page.get_by_role('button',name=next_label,exact=True)).to_be_enabled();pending_read(reads);assert page.locator('.notice-error').count()==0
                    mark(profile,'statistics toggle shows the acknowledged setting without waiting for summary reads')
                    page.unroute('**/api/usage/settings',handler);release_reads(reads,'/api/usage/summary',reader)

                    go('/news');page.get_by_role('button',name='数据源',exact=True).click();dialog=page.get_by_role('dialog',name='数据源',exact=True)
                    label='TEMP 来源 '+profile;dialog.get_by_label('名称',exact=True).fill(label);dialog.get_by_label('订阅地址',exact=True).fill('https://example.invalid/rss')
                    waiting,handler=hold('/api/collection/sources');reads,reader=read_hold('/api/collection/sources');dialog.get_by_role('button',name='添加来源',exact=True).click()
                    expect(dialog.locator('form')).to_have_attribute('aria-busy','true');assert len(waiting)==1;submitted=waiting.pop(0);response=submitted.fetch();assert response.ok,response.text()
                    source=response.json();assert source['source']['label']==label;submitted.fulfill(response=response)
                    row=dialog.locator('.trend-manager-row').filter(has_text=label)
                    try:expect(row).to_have_count(1)
                    except BaseException:
                        page.screenshot(path=str(out/(profile+'-source-failure.png')),full_page=True);report['source_debug']={'ack':source,'body':page.locator('body').inner_text(),'url':page.url,'errors':errors};raise
                    expect(dialog.get_by_role('button',name='添加来源',exact=True)).to_be_enabled();assert reads
                    row.get_by_role('button',name='停用'+label,exact=True).click();expect(dialog.locator('form')).to_have_attribute('aria-busy','true');assert len(waiting)==1;submitted=waiting.pop(0);response=submitted.fetch();assert response.ok,response.text();submitted.fulfill(response=response)
                    expect(row.get_by_role('button',name='启用'+label,exact=True)).to_be_enabled()
                    row.get_by_role('button',name='删除'+label,exact=True).click();row.get_by_role('button',name='确认删除',exact=True).click();expect(dialog.locator('form')).to_have_attribute('aria-busy','true');assert len(waiting)==1;submitted=waiting.pop(0);response=submitted.fetch();assert response.ok,response.text();submitted.fulfill(response=response)
                    expect(row).to_have_count(0);assert page.locator('.notice-error').count()==0
                    mark(profile,'source add, toggle and delete project exact acknowledgements without waiting for source-list reads')
                    page.unroute('**/api/collection/sources',handler);release_reads(reads,'/api/collection/sources',reader);dialog.get_by_role('button',name='关闭',exact=True).click()
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');assert not errors,errors;assert not f['adapter'].requests
                    page.screenshot(path=str(out/(profile+'-settings.png')),full_page=True);mark(profile,'cross-page actions have no JavaScript errors or horizontal overflow and do not call a model')
                    page.unroute_all(behavior='ignoreErrors');context.close()
            browser.close()
        if args.backend:
            backend=Path(args.backend).resolve();manifest=json.loads((backend/'workbench-release.json').read_text(encoding='utf-8'))
            modules={name:str(Path(module.__file__).resolve()) for name,module in sys.modules.items() if (name=='easel' or name.startswith('easel.') or name=='easel_workbench' or name.startswith('easel_workbench.')) and getattr(module,'__file__',None)}
            assert modules and all(Path(path).is_relative_to(backend) for path in modules.values())
            assert all(h.sha(backend/name)==digest for name,digest in manifest['files'].items());report.update(module_roots_valid=True,module_count=len(modules))
        report['passed']=True
    except BaseException as error:
        report['error']=repr(error)
        if 'page' in locals():
            try:page.screenshot(path=str(out/'failure.png'),full_page=True)
            except Exception:pass
        raise
    finally:
        report['evidence']={p.name:h.sha(p) for p in out.glob('*.png')};(out/'cross-page-browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');(out/'harness.py').write_bytes(Path(__file__).read_bytes());print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'error':report.get('error')},ensure_ascii=True),flush=True)

if __name__=='__main__':main()
