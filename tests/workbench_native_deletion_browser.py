"""Real Edge / native UI delete controls against isolated historical storage."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parents[1]


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    for name in ('native','backend','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();native,backend,out=args.native.resolve(),args.backend.resolve(),args.out.resolve()
    out.mkdir(parents=True,exist_ok=True)
    for directory,manifest in ((native,'native-manifest.json'),(backend,'workbench-release.json')):
        metadata=json.loads((directory/manifest).read_text(encoding='utf-8'))
        assert all(sha(directory/name)==digest for name,digest in metadata['files'].items())
    sys.path.insert(0,str(backend))
    spec=importlib.util.spec_from_file_location('deletion_browser_fixture',ROOT/'tests/workbench_native_browser.py')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    from playwright.sync_api import sync_playwright,expect
    report={'passed':False,'backend_sha256':sha(backend/'workbench-release.json'),
        'native_sha256':sha(native/'native-manifest.json'),'checks':[],'page_errors':[],
        'physical_mobile_device_tested':False,'real_AI_calls':0,'real_platform_writes':0}
    def mark(case,name):report['checks'].append({'case':case,'name':name,'passed':True})
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
            for case,width,height,theme in [('desktop-light',1280,900,'light'),('mobile-light',390,844,'light'),('mobile-dark',390,844,'dark')]:
                with helper.isolated(native,b'TEMP no model generation') as fixture:
                    folder='TEMP-delete-'+case
                    source=fixture['root']/'outputs'/folder/'original.txt';source.parent.mkdir(parents=True);source.write_text('TEMP original bytes '+case,encoding='utf-8')
                    profile=fixture['box'].creator.command({'id':'delete-profile-'+case,'action':'profile-save','base_revision':0,
                        'document':{'name':'删除验收 '+case,'identity':'TEMP original profile '+case}})['result']['profile']
                    fixture['box']._native_api.library.rebuild(lock_timeout=10)
                    context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':height},is_mobile=width<600,has_touch=width<600)
                    context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':fixture['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
                    context.add_init_script('localStorage.setItem("native:theme",'+json.dumps(theme)+')')
                    page=context.new_page();page.set_default_timeout(20000)
                    page.on('pageerror',lambda error:report['page_errors'].append(str(error)))
                    try:
                        def goto(path):page.goto(fixture['origin']+'/native/?'+urlencode({'path':path}),wait_until='domcontentloaded')
                        goto('/works')
                        card=page.locator('.gcard').filter(has=page.get_by_text(folder,exact=True))
                        expect(card).to_be_visible()
                        if width>=600:card.hover()
                        delete=card.locator('.gcard-del');expect(delete).to_be_visible()
                        if width<600:assert delete.bounding_box()['width']>=44 and delete.bounding_box()['height']>=44
                        page.screenshot(path=str(out/(case+'-library-before.png')),full_page=True)
                        page.once('dialog',lambda dialog:dialog.accept())
                        with page.expect_response(lambda response:response.request.method=='DELETE' and '/api/output/' in response.url) as pending:
                            delete.click()
                        assert pending.value.status==200
                        expect(card).to_have_count(0)
                        assert source.read_text(encoding='utf-8')=='TEMP original bytes '+case
                        archives=list((fixture['root']/'data/library-deletions').rglob('original.txt'))
                        assert len(archives)==1 and archives[0].read_bytes()==source.read_bytes()
                        mark(case,'original gallery deletion removes the active project and archives its exact bytes')
                        page.reload(wait_until='domcontentloaded');expect(card).to_have_count(0)
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                        mark(case,'reload preserves deletion without horizontal overflow')
                        goto('/toolbox?section=profiles&item='+profile['id'])
                        expect(page.get_by_role('heading',name=profile['name'],exact=True)).to_be_visible()
                        expect(page.get_by_role('button',name=re.compile('抓取公众号数据'))).to_be_visible()
                        button=page.get_by_role('button',name=re.compile('删除画像'));expect(button).to_be_enabled()
                        page.screenshot(path=str(out/(case+'-profile-before.png')),full_page=True)
                        page.once('dialog',lambda dialog:dialog.accept())
                        with page.expect_response(lambda response:response.request.method=='DELETE' and '/api/persona/' in response.url) as pending:
                            button.click()
                        assert pending.value.status==200
                        expect(page.get_by_role('heading',name=profile['name'],exact=True)).to_have_count(0)
                        historical=fixture['box'].creator.detail('profile',profile['id'])
                        assert historical['active'] is False and historical['identity']==profile['identity']
                        assert any(item['revision']==profile['revision'] for item in historical['history'])
                        mark(case,'native profile deletion retains historical revisions and the explicit import action')
                        goto('/toolbox?section=profiles&item=oil-pig')
                        expect(page.get_by_role('heading',name='油猪大侠',exact=True)).to_be_visible()
                        expect(page.get_by_role('button',name=re.compile('删除画像'))).to_have_count(0)
                        assert not fixture['adapter'].requests
                        mark(case,'only builtin profile is protected and deletion never starts a model')
                        page.screenshot(path=str(out/(case+'-profile-after.png')),full_page=True)
                    except Exception:
                        page.screenshot(path=str(out/(case+'-failure.png')),full_page=True)
                        (out/(case+'-failure.txt')).write_text(page.locator('body').inner_text(),encoding='utf-8')
                        raise
                    finally:context.close()
            browser.close()
        assert not report['page_errors'];report['passed']=True
    except Exception as error:report['error']=repr(error)
    finally:
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'error':report.get('error')}))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
