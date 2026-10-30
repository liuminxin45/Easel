"""Windows Edge dropdown regression, TEMP application and synthetic profile data only."""
from __future__ import annotations
import argparse,hashlib,json,re,sys
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--native',required=True);parser.add_argument('--backend',required=True);parser.add_argument('--out',required=True);args=parser.parse_args()
    native,backend,out=map(lambda p:Path(p).resolve(),[args.native,args.backend,args.out]);out.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(backend))
    from workbench_native_browser import isolated
    from easel import harnesses
    from playwright.sync_api import sync_playwright,expect
    manifest=json.loads((native/'native-manifest.json').read_text(encoding='utf-8'))
    report={'passed':False,'native':{'release':manifest['release'],'manifest_sha256':sha(native/'native-manifest.json')},
            'backend':{'directory':str(backend),'manifest_sha256':sha(backend/'workbench-release.json')},
            'real_AI_calls':0,'real_platform_writes':0,'physical_device_tested':False,'checks':[],
            'probe_sha256':sha(__file__),'fixture_sha256':sha(Path(__file__).with_name('workbench_native_browser.py'))}
    def mark(profile,name):
        report['checks'].append({'profile':profile,'check':name,'passed':True});print('PASS',profile,name,flush=True)
    def surface(page,menu):
        expect(menu).to_be_visible()
        result=menu.evaluate('''el=>{const r=el.getBoundingClientRect(),s=getComputedStyle(el),v=visualViewport;return {background:s.backgroundColor,border:s.borderTopWidth,zIndex:s.zIndex,shadow:s.boxShadow,top:r.top,bottom:r.bottom,left:r.left,right:r.right,width:r.width,height:r.height,scrollHeight:el.scrollHeight,clientHeight:el.clientHeight,viewportWidth:v.width,viewportHeight:v.height}}''')
        assert result['background']!='rgba(0, 0, 0, 0)' and result['background']!='transparent',result
        assert result['border']=='1px' and int(result['zIndex'])>=1000 and result['shadow']!='none',result
        assert result['top']>=7 and result['left']>=7 and result['right']<=result['viewportWidth']-7 and result['bottom']<=result['viewportHeight']-7,result
        assert result['height']<=321,result
        return result
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
            with isolated(native,b'TEMP unused image') as f,patch.object(harnesses,'describe',lambda runtime:{'id':runtime,'label':runtime,'installed':True,'protocol':'TEMP','install_hint':'TEMP'}):
                async def models(runtime):return {'runtime':runtime,'models':[{'id':'TEMP-model','label':'TEMP-model','default':True}]}
                with patch.object(f['app'].state.settings,'native_models',models):
                    for profile,width,height,mobile,theme in [('desktop-light',1365,900,False,'light'),('desktop-dark',1365,900,False,'dark'),('mobile-light',390,844,True,'light'),('mobile-dark',390,844,True,'dark')]:
                        context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':height},is_mobile=mobile,has_touch=mobile,color_scheme=theme)
                        context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
                        page=context.new_page();page.set_default_timeout(15000);errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                        def profiles(route):
                            response=route.fetch();data=response.json()
                            data['profiles'].extend({'id':f'TEMP-role-{i}','name':f'TEMP 验收角色 {i} '+('很长的角色名称用于验证换行和菜单宽度'*3 if i==10 else '')} for i in range(24))
                            route.fulfill(response=response,json=data)
                        page.route('**/api/creator/bootstrap',profiles)
                        try:
                            page.goto(f['origin']+'/native/',wait_until='domcontentloaded')
                            page.evaluate('(theme)=>{localStorage.setItem("easel-theme",theme);document.documentElement.dataset.theme=theme}',theme)
                            if mobile:page.get_by_role('button',name='打开工作导航',exact=True).click()
                            trigger=page.get_by_role('button',name='选择用户画像',exact=True);expect(trigger).to_be_visible()
                            trigger.click();menu=page.get_by_role('listbox',name='选择用户画像',exact=True)
                            expect(menu.get_by_role('option').filter(has_text='TEMP 验收角色 23')).to_have_count(1)
                            info=surface(page,menu)
                            assert info['scrollHeight']>info['clientHeight'];mark(profile,'role menu is opaque, themed, scrollable and bounded')
                            assert menu.get_by_role('option').first.evaluate('el=>el.getBoundingClientRect().height')>=(44 if mobile else 36)
                            if mobile:
                                before=menu.evaluate('el=>el.scrollTop');box=menu.bounding_box()
                                session=context.new_cdp_session(page)
                                session.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':box['x']+100,'y':box['y']+box['height']-40}]})
                                session.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':box['x']+100,'y':box['y']+50}]})
                                session.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]});page.wait_for_timeout(250)
                                expect(menu).to_be_visible();assert menu.evaluate('el=>el.scrollTop')>before;mark(profile,'touch scroll retains menu and does not select a role')
                            page.screenshot(path=str(out/(profile+'-role.png')))
                            page.keyboard.press('Escape');expect(menu).to_have_count(0);expect(trigger).to_be_focused()
                            trigger.press('ArrowDown');expect(menu).to_be_visible();page.keyboard.press('End');assert page.evaluate('document.activeElement.textContent').startswith('+ 新建画像')
                            page.keyboard.press('Home');page.keyboard.press('ArrowDown');assert page.evaluate('document.activeElement.getAttribute("role")')=='option'
                            page.keyboard.press('Tab');expect(menu).to_have_count(0);mark(profile,'Escape, arrows, Home, End and Tab work without changing roles')
                            trigger.click();page.locator('.sidebar h1').click();expect(menu).to_have_count(0);mark(profile,'pointer outside closes the menu')
                            # A bottom-right anchor checks upward placement using the real shared component.
                            trigger.evaluate('el=>{el.style.position="fixed";el.style.top="auto";el.style.bottom="12px";el.style.left="auto";el.style.right="8px";el.style.width="180px";el.style.zIndex="200"}')
                            trigger.click();info=surface(page,menu);assert info['bottom']<trigger.bounding_box()['y'];mark(profile,'bottom-right menu opens upward and stays on screen')
                            page.keyboard.press('Escape')
                            page.goto(f['origin']+'/native/?path=/settings',wait_until='domcontentloaded')
                            page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                            dialog=page.get_by_role('dialog',name='设置',exact=True);expect(dialog).to_be_visible()
                            engine=dialog.get_by_role('button',name='执行引擎',exact=True);engine.click();choices=page.get_by_role('listbox',name='执行引擎',exact=True);surface(page,choices)
                            assert choices.get_by_role('option').count()==5
                            option=choices.get_by_role('option').filter(has_text=re.compile('opencode',re.I));option.click();expect(choices).to_have_count(0);expect(engine).to_contain_text(re.compile('opencode',re.I))
                            engine.click();choices.get_by_role('option',name=re.compile('^codex(?: 当前)?$',re.I)).click()
                            # No save: engine preview must not change server configuration.
                            page.screenshot(path=str(out/(profile+'-settings.png')))
                            mark(profile,'settings engine portal has opaque surface and selection feedback')
                            page.keyboard.press('Escape')
                            page.goto(f['origin']+'/native/?path=/news',wait_until='domcontentloaded')
                            page.evaluate('(theme)=>document.documentElement.dataset.theme=theme',theme)
                            page.get_by_role('button',name='数据源',exact=True).click()
                            native_dialog=page.locator('dialog.trend-manager');expect(native_dialog).to_be_visible()
                            native_dialog.get_by_role('button',name='接入方式',exact=True).click()
                            protocol=page.get_by_role('listbox',name='接入方式',exact=True);surface(page,protocol)
                            assert protocol.evaluate('el=>!!el.closest("dialog[open]")')
                            page.screenshot(path=str(out/(profile+'-native-dialog.png')))
                            page.keyboard.press('Escape');expect(protocol).to_have_count(0);expect(native_dialog).to_be_visible()
                            mark(profile,'native dialog menu stays above its backdrop and Escape closes only the menu')
                            page.keyboard.press('Escape');expect(native_dialog).not_to_be_visible()
                            assert not f['adapter'].requests
                            assert not errors,errors
                        except BaseException:
                            page.screenshot(path=str(out/(profile+'-failure.png')),full_page=True)
                            raise
                        finally:context.close()
            browser.close()
        report['passed']=True
    except BaseException as error:
        report['error']=repr(error);raise
    finally:
        report['evidence']={p.name:sha(p) for p in out.glob('*.png')}
        (out/'browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'error':report.get('error')},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
