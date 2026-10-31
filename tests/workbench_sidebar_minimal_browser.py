"""Minimal-sidebar regression on real frozen UI/TEMP backend; no business POST."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from urllib.parse import urlencode, urlsplit

ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
FOCUS="""el=>{const nodes=[...el.querySelectorAll('button,[href],input,select,textarea,[tabindex]')].filter(n=>n.tabIndex>=0&&!n.matches(':disabled')&&!n.closest('[inert]')&&n.getClientRects().length&&getComputedStyle(n).visibility!=='hidden');return {count:nodes.length,first:nodes[0]===document.activeElement,last:nodes.at(-1)===document.activeElement,inside:el.contains(document.activeElement),original:!!document.activeElement.closest('.sidebar'),active:document.activeElement.outerHTML.slice(0,600)}}"""

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('native','backend','out'):parser.add_argument('--'+name,required=True,type=Path)
    parser.add_argument('--source-root',type=Path,default=ROOT)
    args=parser.parse_args();native,backend,out=[getattr(args,key).resolve() for key in ('native','backend','out')];out.mkdir(parents=True,exist_ok=True)
    for folder,name in ((native,'native-manifest.json'),(backend,'workbench-release.json')):
        manifest=read(folder/name);assert all(sha(folder/path)==digest for path,digest in manifest['files'].items())
    inputs=read(native/'build-inputs.json')['inputs'];component='web/frontend/src/components/ResponsiveSidebar.tsx'
    source_root=args.source_root.resolve();assert all(sha(source_root/path)==digest for path,digest in inputs.items()), 'Isolated source differs from compiled inputs'
    sys.path.insert(0,str(backend));spec=importlib.util.spec_from_file_location('minimal_sidebar_fixture',ROOT/'tests/workbench_native_browser.py');fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture);fixture.ROOT=backend
    from playwright.sync_api import sync_playwright,expect
    expect.set_options(timeout=12000)
    report={'passed':False,'native':{'release':native.name,'manifest_sha256':sha(native/'native-manifest.json')},'backend':{'release':backend.name,'manifest_sha256':sha(backend/'workbench-release.json')},
        'source':{'head_observed':subprocess.check_output(['git','-C',str(source_root),'rev-parse','HEAD'],text=True).strip(),'compiled_source_root':str(source_root),'all144_isolated_build_inputs_verified':len(inputs)==144,'harness_sha256':sha(__file__),'fixture_sha256':sha(ROOT/'tests/workbench_native_browser.py'),'build_inputs_sha256':sha(native/'build-inputs.json'),'responsive_sidebar_sha256':inputs[component]},
        'checks':[],'screenshots':{},'requests':[],'blocked_requests':[],'application_source_injected':False,'DOM_or_CSS_mocked':False,
        'real_AI_calls':0,'real_platform_writes':0,'physical_mobile_device_tested':False,'production_data_access':False,'not_applicable':['Desktop sidebar is always visible; desktop frames are layout/focus states, not a simulated closed drawer.']}
    def mark(case,name,passed,**data):report['checks'].append({'case':case,'name':name,'passed':bool(passed),**data});print(('PASS' if passed else 'FAIL')+' '+case+' '+name,flush=True)
    def shot(page,case,state):
        name=case+'-'+state+'.png';page.screenshot(path=str(out/name));report['screenshots'][name]={'sha256':sha(out/name),'case':case,'state':state}
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
            with fixture.isolated(native,b'TEMP unused image') as f:
                f['close_clients']=lambda:[context.close() for context in browser.contexts]
                for width,theme in ((320,'light'),(390,'dark'),(1440,'light')):
                    case=f'{width}-{theme}';narrow=width<760;errors=[]
                    context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':844 if narrow else 900},is_mobile=narrow,has_touch=narrow,color_scheme=theme,service_workers='block')
                    context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}]);context.add_init_script('localStorage.setItem("native:theme",'+json.dumps(theme)+');localStorage.setItem("easel_theme",'+json.dumps(theme)+')')
                    def intercept(route):
                        req=route.request;url=urlsplit(req.url);row={'case':case,'method':req.method,'path':url.path};report['requests'].append(row)
                        if url.hostname not in ('localhost','127.0.0.1'):report['blocked_requests'].append(row);return route.abort()
                        if req.method not in ('GET','HEAD','OPTIONS'):
                            if url.path=='/api/usage/events':return route.fulfill(status=200,json={'accepted':0})
                            report['blocked_requests'].append(row);return route.fulfill(status=405,json={'error':'TEMP no business mutation'})
                        route.continue_()
                    context.route('**/*',intercept);page=context.new_page();page.on('pageerror',lambda error:errors.append(str(error)))
                    try:
                        page.goto(f['origin']+'/native/?'+urlencode({'path':'/toolbox'}),wait_until='domcontentloaded');expect(page.locator('.sidebar-panel > .sidebar')).to_have_count(1);expect(page.locator('.sidebar-nav .nav-item')).to_have_count(6)
                        panel=page.locator('.sidebar-panel');trigger=page.get_by_role('button',name='打开导航',exact=True)
                        def open_drawer():
                            trigger.tap();expect(panel).to_have_attribute('aria-modal','true')
                            page.wait_for_function("()=>{const p=document.querySelector('.sidebar-panel.is-open');return p&&Math.abs(p.getBoundingClientRect().left)<.1&&p.getAnimations().every(a=>a.playState!=='running')}")
                        mark(case,'R1 extra header/close/hidden brand DOM is absent',page.locator('.sidebar-mobile-header,.sidebar-close,.mobile-nav-bar > span').count()==0)
                        page.evaluate('window.__originalSidebar=document.querySelector(".sidebar-panel > .sidebar")')
                        if narrow:
                            expect(trigger).to_be_visible();box=trigger.bounding_box();expect(panel).to_have_attribute('inert','')
                            mark(case,'R1 closed drawer and44px floating opener',box['width']>=44 and box['height']>=44 and panel.get_attribute('aria-hidden')=='true',trigger_box=box);shot(page,case,'closed')
                            open_drawer();expect(trigger).to_have_attribute('aria-expanded','true')
                            focus=panel.evaluate(FOCUS);geometry=panel.evaluate('el=>{const s=el.querySelector(":scope > .sidebar"),p=el.getBoundingClientRect(),r=s.getBoundingClientRect();return {panelTop:p.top,panelLeft:p.left,sidebarLeft:r.left,sidebarRight:r.right,sidebarTop:r.top,sidebarWidth:r.width,firstChildIsOriginal:el.firstElementChild===s}}')
                            mark(case,'R1 original sidebar begins at top0 without extra row',abs(geometry['panelTop'])<=1 and abs(geometry['sidebarTop'])<=1 and abs(geometry['sidebarLeft'])<=1 and geometry['sidebarRight']<=width+1 and geometry['firstChildIsOriginal'],geometry=geometry)
                            mark(case,'R2 opening focuses original first available control',focus['first'] and focus['original'] and focus['count']>1,focus=focus);shot(page,case,'open')
                            page.keyboard.press('Shift+Tab');reverse=panel.evaluate(FOCUS);page.keyboard.press('Tab');forward=panel.evaluate(FOCUS)
                            mark(case,'R2 bidirectional keyboard trap',reverse['last'] and forward['first'] and reverse['inside'] and forward['inside'],reverse=reverse,forward=forward)
                            page.keyboard.press('Escape');expect(trigger).to_have_attribute('aria-expanded','false');expect(trigger).to_be_focused();mark(case,'R2 Escape closes and returns focus',panel.get_attribute('inert') is not None)
                            open_drawer();page.touchscreen.tap(width-6,400);expect(trigger).to_have_attribute('aria-expanded','false');expect(trigger).to_be_focused();mark(case,'R2 backdrop closes and returns focus',panel.get_attribute('inert') is not None)
                            open_drawer();before=page.url;panel.locator('.sidebar-nav .nav-item[aria-current="page"]').click();expect(trigger).to_have_attribute('aria-expanded','false');expect(trigger).to_be_focused()
                            mark(case,'R2 same-page native navigation closes and returns focus',page.url==before and panel.get_attribute('inert') is not None)
                            mark(case,'R1 exactly the same original sidebar remains mounted',page.evaluate('document.querySelectorAll(".sidebar-panel > .sidebar").length===1&&window.__originalSidebar===document.querySelector(".sidebar-panel > .sidebar")'))
                        else:
                            sidebar=panel.locator(':scope > .sidebar');expect(sidebar).to_be_visible();shot(page,case,'desktop-layout')
                            geometry=sidebar.bounding_box();mark(case,'R3 desktop original sidebar stays264px and nonmodal',abs(geometry['width']-264)<=1 and panel.get_attribute('aria-modal') is None and panel.get_attribute('inert') is None and not trigger.is_visible(),geometry=geometry)
                            sidebar.locator('button').first.focus();shot(page,case,'desktop-native-focus');mark(case,'R3 desktop original control remains focusable',panel.evaluate(FOCUS)['original'])
                        mark(case,'no page errors, business POST or model call',not errors and not f['adapter'].requests and not any(row['case']==case for row in report['blocked_requests']),errors=errors)
                    except Exception as error:mark(case,'scenario completed',False,error=repr(error));shot(page,case,'failure')
                    finally:context.close()
            browser.close()
        report['passed']=len({row['case'] for row in report['checks']})==3 and all(row['passed'] for row in report['checks'])
    except Exception as error:report['error']=repr(error)
    finally:
        report['runtime_modules']={name:{'file':str(Path(value.__file__).resolve()),'sha256':sha(value.__file__)} for name,value in list(sys.modules.items()) if (name=='easel' or name.startswith('easel.') or name=='easel_workbench' or name.startswith('easel_workbench.')) and getattr(value,'__file__',None)}
        report['module_roots_valid']=all(Path(value['file']).is_relative_to(backend) for value in report['runtime_modules'].values());report['passed']&=report['module_roots_valid']
        shutil.copy2(__file__,out/'harness.py');(out/'report.json').write_bytes(json.dumps(report,ensure_ascii=False,indent=2).encode('utf-8'))
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'screenshots':len(report['screenshots']),'error':report.get('error')}));return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
