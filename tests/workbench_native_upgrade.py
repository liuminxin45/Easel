"""Online native-chat upgrade and offline draft recovery, all state in TEMP."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import shutil
import sys
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--native',required=True);parser.add_argument('--out',required=True);parser.add_argument('--backend');parser.add_argument('--previous');args=parser.parse_args()
    if args.backend:sys.path.insert(0,str(Path(args.backend).resolve()))
    else:sys.path.insert(0,str(ROOT))
    spec=importlib.util.spec_from_file_location('native_chat_browser',Path(__file__).with_name('workbench_native_browser.py'));h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
    from playwright.sync_api import sync_playwright,expect
    native=Path(args.native).resolve();current=json.loads((native/'native-manifest.json').read_text(encoding='utf-8'))
    previous=Path(args.previous).resolve() if args.previous else ROOT/'native-releases'/json.loads((ROOT/'data/active-native.json').read_text(encoding='utf-8'))['release']
    old=json.loads((previous/'native-manifest.json').read_text(encoding='utf-8'));out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
    report={'passed':False,'native':{'release':current['release'],'manifest_sha256':sha(native/'native-manifest.json')},'previous':{'release':old['release'],'manifest_sha256':sha(previous/'native-manifest.json')},'backend':{'directory':args.backend or str(ROOT),'manifest_sha256':sha(Path(args.backend)/'workbench-release.json') if args.backend else None},'checks':[],'real_AI_calls':0,'real_platform_writes':0,'physical_device_tested':False,'harness_sha256':sha(__file__),'fixture_sha256':sha(Path(__file__).with_name('workbench_native_browser.py'))}
    def stage(page,profile,name):
        info=page.evaluate('()=>({url:location.href,release:document.querySelector(\"meta[name=native-release]\")?.content,navigation:history.state?.nativeNavigation?.path})');report.setdefault('stages',[]).append({'profile':profile,'stage':name,**info});print('STAGE',profile,name,json.dumps(info),flush=True)
    def check(profile,name):report['checks'].append({'profile':profile,'check':name,'passed':True});print('PASS',profile,name,flush=True)
    try:
        assert current['release']!=old['release']
        assert all(sha(previous/file)==digest for file,digest in old['files'].items())
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
            p=browser.new_page();p.set_content('TEMP');image=p.screenshot();p.close()
            with h.isolated(native,image) as f:
                f['close_clients']=lambda:[context.close() for context in browser.contexts]
                shutil.copytree(previous,f['root']/'native-releases'/old['release'])
                pointer=f['root']/'data/active-native.json'
                for profile,width,mobile in [('desktop',1280,False),('mobile',390,True)]:
                    pointer.write_text(json.dumps(report['previous']),encoding='utf-8')
                    context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':900},is_mobile=mobile,has_touch=mobile)
                    context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}]);page=context.new_page();page.set_default_timeout(20000)
                    path='/posters/new?draft=upgrade-native-'+profile;page.goto(f['origin']+'/native/?'+urlencode({'path':path}),wait_until='domcontentloaded')
                    textarea=page.get_by_role('textbox',name=re.compile('^(素材与目标|对话输入)$'));expect(textarea).to_be_visible(timeout=30000)
                    raw='  在线升级仍保留全部原字。\n第二行 '+profile+'  ';textarea.fill(raw);page.locator('.chat-hero-title,h1').last.click()
                    page.wait_for_function('raw=>Object.entries(localStorage).some(([k,v])=>k.startsWith("toolbox:draft:")&&[JSON.parse(v).text,JSON.parse(v).material].includes(raw))',arg=raw)
                    original_keys=page.evaluate('raw=>Object.entries(localStorage).filter(([k,v])=>k.startsWith("toolbox:draft:")&&[JSON.parse(v).text,JSON.parse(v).material].includes(raw)).map(([k])=>k)',raw)
                    page.wait_for_function('()=>!!navigator.serviceWorker.controller');page.wait_for_load_state('networkidle')
                    textarea.dispatch_event('compositionstart');pointer.write_text(json.dumps(report['native']),encoding='utf-8');page.evaluate("()=>window.dispatchEvent(new Event('focus'))");page.wait_for_timeout(500)
                    assert page.locator('meta[name=native-release]').get_attribute('content')==old['release'];check(profile,'IME composition defers the online upgrade')
                    textarea.dispatch_event('compositionend');page.evaluate("()=>window.dispatchEvent(new Event('focus'))")
                    page.wait_for_function("release=>document.querySelector('meta[name=native-release]')?.content===release",arg=current['release'],timeout=45000)
                    current_input=page.get_by_role('textbox',name='对话输入',exact=True);expect(current_input).to_have_value(raw,timeout=30000)
                    assert page.evaluate('({keys,raw})=>keys.every(key=>{const v=JSON.parse(localStorage.getItem(key));return !!v&&[v.text,v.material].includes(raw)})',{'keys':original_keys,'raw':raw})
                    assert not f['adapter'].requests;check(profile,'upgrade retains the exact raw draft and its original input keys')
                    page.wait_for_function("async release=>{const reg=await navigator.serviceWorker.getRegistration('/native/');if(!reg?.active||reg.installing||reg.waiting)return false;const cache=await caches.open('native-shell-'+release);const response=await cache.match('/native/');return !!response&&(await response.text()).includes(release)}",arg=current['release'],timeout=30000);page.wait_for_function("release=>new Promise(resolve=>{const channel=new MessageChannel(),timer=setTimeout(()=>resolve(false),400);channel.port1.onmessage=event=>{clearTimeout(timer);resolve(event.data?.release===release&&event.data?.shell_ready===true)};if(!navigator.serviceWorker.controller){clearTimeout(timer);resolve(false);return}navigator.serviceWorker.controller.postMessage({type:'NATIVE_VERSION'},[channel.port2])})",arg=current['release'],timeout=30000);stage(page,profile,'before-offline');context.set_offline(True);page.reload(wait_until='domcontentloaded')
                    expect(page.get_by_role('heading',name='保留的本机输入')).to_be_visible(timeout=35000);stage(page,profile,'offline')
                    assert page.evaluate('raw=>Object.entries(localStorage).filter(([k])=>k.startsWith("toolbox:draft:")).some(([k,v])=>JSON.stringify(JSON.parse(v).text)===JSON.stringify(raw))',raw)
                    page.screenshot(path=str(out/(profile+'-offline.png')),full_page=True);check(profile,'offline shell exposes retained native chat inputs without caching business JSON')
                    context.set_offline(False);page.reload(wait_until='domcontentloaded');stage(page,profile,'reconnected');expect(page.get_by_role('textbox',name='对话输入',exact=True)).to_have_value(raw,timeout=35000)
                    assert not f['adapter'].requests;check(profile,'reconnection restores the same raw native draft without sending a model turn')
                    context.close()
            browser.close()
        assert len(report['checks'])==8
        assert sha(__file__)==report['harness_sha256'] and sha(Path(__file__).with_name('workbench_native_browser.py'))==report['fixture_sha256']
        if args.backend:
            selected=Path(args.backend).resolve();modules={name:str(Path(module.__file__).resolve()) for name,module in sys.modules.items() if (name=='easel' or name.startswith('easel.') or name=='easel_workbench' or name.startswith('easel_workbench.')) and getattr(module,'__file__',None)}
            assert modules and all(Path(path).is_relative_to(selected) for path in modules.values()),modules
            assert all(sha(selected/member)==digest for member,digest in json.loads((selected/'workbench-release.json').read_text(encoding='utf-8'))['files'].items())
            report.update(module_count=len(modules),module_roots_valid=True)
        report['passed']=True
    except BaseException as error:
        report['error']=repr(error)
        if 'page' in locals():
            try:
                report['diagnostics']=page.evaluate('''async()=>{const registration=await navigator.serviceWorker.getRegistration('/native/');const controller=navigator.serviceWorker.controller;let worker=null;if(controller)worker=await new Promise(resolve=>{const channel=new MessageChannel(),timer=setTimeout(()=>resolve(null),1500);channel.port1.onmessage=event=>{clearTimeout(timer);resolve(event.data)};controller.postMessage({type:'NATIVE_VERSION'},[channel.port2])});return {release:document.querySelector('meta[name=native-release]')?.content,hidden:document.hidden,version:await fetch('/native/version',{cache:'no-store'}).then(r=>r.json()).catch(()=>null),worker,active:registration?.active?.state,waiting:registration?.waiting?.state,installing:registration?.installing?.state,caches:await caches.keys()}}''')
                page.screenshot(path=str(out/'failure.png'),full_page=True)
            except Exception:pass
        raise
    finally:
        (out/'harness.py').write_bytes(Path(__file__).read_bytes());report['evidence']={path.name:sha(path) for path in out.glob('*.png')};(out/'upgrade.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
