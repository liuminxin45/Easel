"""Real touch input against frozen UI and TEMP metadata; no model/platform writes."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sha=lambda path:hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser()
    for name in ('native','backend','out'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();native,backend,out=args.native.resolve(),args.backend.resolve(),args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    for folder,name in [(native,'native-manifest.json'),(backend,'workbench-release.json')]:
        manifest=json.loads((folder/name).read_text(encoding='utf8'));assert all(sha(folder/p)==digest for p,digest in manifest['files'].items())
    sys.path.insert(0,str(backend))
    spec=importlib.util.spec_from_file_location('sidebar_touch_fixture',ROOT/'tests/workbench_native_browser.py');helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper);helper.ROOT=backend
    from playwright.sync_api import sync_playwright,expect
    expect.set_options(timeout=12000)
    report={'passed':False,'checks':[],'screenshots':{},'real_AI_calls':0,'real_platform_writes':0,'physical_mobile_device_tested':False,'production_data_access':False,'application_source_injected':False,
            'native':{'release':native.name,'manifest_sha256':sha(native/'native-manifest.json')},'backend':{'release':backend.name,'manifest_sha256':sha(backend/'workbench-release.json')},'harness_sha256':sha(__file__)}
    def check(name,condition=True):
        report['checks'].append({'name':name,'passed':bool(condition)});print(name+': '+str(bool(condition)),flush=True);assert condition,name
    def shot(page,name):
        page.screenshot(path=str(out/name));report['screenshots'][name]=sha(out/name)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
            with helper.isolated(native,b'TEMP unused image') as f:
                chat=f['app'].state.chat
                for i in range(35):
                    sid='workbench-touch-'+str(i);chat.create_session({'id':'create-touch-'+str(i),'session_id':sid,'profile_id':'oil-pig','title':'TEMP 会话 '+str(i)})
                    tid='touch-turn-'+str(i);turn={'id':tid,'session_id':sid,'message':'TEMP 原始消息','output':'TEMP 原回复','created_at':'2026-11-06T00:00:00+00:00','updated_at':'2026-11-06T00:00:01+00:00','status':'completed','delivery_state':'accepted','hook_status':'completed','runtime':'codex','context':{},'attachments':[]}
                    with chat.store.connect() as c:c.execute('INSERT INTO easel_chat_turns VALUES(?,?,?,?,?)',(tid,sid,tid,'TEMP-metadata',json.dumps(turn)))
                context=browser.new_context(ignore_https_errors=True,viewport={'width':390,'height':844},is_mobile=True,has_touch=True,service_workers='block')
                f['close_clients']=lambda:[c.close() for c in browser.contexts]
                context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
                page=context.new_page();page.set_default_timeout(15000);errors=[];commands=[];report['errors']=errors
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.on('request',lambda request:commands.append(request.post_data_json) if request.method=='POST' and request.url.endswith('/api/chat/sessions') else None)
                page.goto(f['origin']+'/native/?path=%2Ftoolbox');expect(page.get_by_role('button',name='打开导航',exact=True)).to_be_visible()
                route=lambda:page.evaluate("new URL(location.href).searchParams.get('path')")
                panel=page.get_by_role('dialog',name='主导航',exact=True)
                menu=page.get_by_role('dialog',name='会话操作',exact=True)
                def sidebar():
                    if not panel.is_visible():page.get_by_role('button',name='打开导航',exact=True).tap()
                    expect(panel).to_be_visible()
                def row(title):return panel.locator('.session-item').filter(has=page.locator('.session-item-title',has_text=title))
                cdp=context.new_cdp_session(page)
                def begin(item):
                    item.scroll_into_view_if_needed();page.wait_for_timeout(180);box=item.bounding_box();x,y=box['x']+50,box['y']+box['height']/2
                    cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x,'y':y,'id':1}]});return x,y
                def end():cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
                def hold(item):
                    begin(item);page.wait_for_timeout(560);expect(menu).to_be_visible();end();page.wait_for_timeout(120);expect(menu).to_be_visible()
                sidebar();item=row('TEMP 会话 34');expect(item).to_be_visible();check('mobile removes inline action buttons rather than leaving hidden hover controls',item.locator('.session-actions').count()==0)
                shot(page,'390-clean-sidebar.png')
                before=route();hold(item);check('long press does not navigate or generate a ghost click',route()==before and panel.is_visible())
                expect(menu.get_by_role('button',name='重命名',exact=True)).to_be_visible();shot(page,'390-menu-light.png')
                report['before_escape']=page.evaluate("()=>({active:document.activeElement?.tagName,modal:document.activeElement?.closest('[aria-modal=true]')?.className,nested:!!document.querySelector('.sidebar-panel .drawer-overlay'),expanded:document.querySelector('.sidebar-toggle')?.getAttribute('aria-expanded')})")
                page.keyboard.press('Escape');expect(menu).to_have_count(0);report['after_escape']=page.evaluate("()=>({active:document.activeElement?.tagName,expanded:document.querySelector('.sidebar-toggle')?.getAttribute('aria-expanded')})");check('Escape closes only nested menu',panel.is_visible())
                hold(item);page.go_back();expect(menu).to_have_count(0);check('Back closes menu before sidebar and keeps route',panel.is_visible() and route()==before)
                hold(item);page.locator('.sidebar-backdrop').tap(position={'x':375,'y':600});expect(menu).to_have_count(0);expect(panel).not_to_be_visible();check('closing sidebar also removes its menu and modal layer',True);sidebar()
                item.get_by_role('button',name='会话操作：TEMP 会话 34',exact=True).focus();page.keyboard.press('Shift+F10');expect(menu).to_be_visible()
                check('keyboard menu shortcut reuses accessible entry',True)
                page.keyboard.press('Tab');check('focus stays inside menu',menu.evaluate('el=>el.contains(document.activeElement)'))
                menu.get_by_role('button',name='重命名',exact=True).click();rename=panel.locator('.session-rename-input');expect(rename).to_be_focused();rename.fill('TEMP 原生重命名');rename.press('Enter')
                item=row('TEMP 原生重命名');expect(item).to_be_visible();check('rename uses original editor and one revision-bound command',len([c for c in commands if c.get('action')=='rename'])==1)
                hold(item);menu.get_by_role('button',name='归档',exact=True).tap()
                page.wait_for_function("()=>Array.from(document.querySelectorAll('.session-item-title')).every(el=>el.textContent!=='TEMP 原生重命名')")
                panel.locator('.archived-header').click();item=row('TEMP 原生重命名');expect(item).to_be_visible();hold(item)
                menu.get_by_role('button',name='取消归档',exact=True).tap()
                expect(panel.locator('.archived-header')).to_have_count(0)
                check('archive and unarchive share original commands',[(c.get('session_id'),c.get('archived')) for c in commands if c.get('action')=='archive']==[('workbench-touch-34',True),('workbench-touch-34',False)])
                item=row('TEMP 原生重命名');item.scroll_into_view_if_needed();scroll_before=panel.locator('.sidebar-section').evaluate('el=>el.scrollTop');x,y=begin(item)
                page.wait_for_timeout(70);cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':x,'y':y-90,'id':1}]});page.wait_for_timeout(530);end();expect(menu).to_have_count(0)
                check('vertical drag scrolls natively and cancels long press without navigation',route()==before and panel.locator('.sidebar-section').evaluate('el=>el.scrollTop')>scroll_before)
                item=row('TEMP 原生重命名');begin(item);page.wait_for_timeout(80);cdp.send('Input.dispatchTouchEvent',{'type':'touchCancel','touchPoints':[]});page.wait_for_timeout(500);expect(menu).to_have_count(0);check('native pointer cancellation does not open a menu',True)
                item.get_by_role('button',name='会话操作：TEMP 原生重命名',exact=True).focus();page.keyboard.press('Enter');expect(menu).to_be_visible();page.keyboard.press('Escape');expect(menu).to_have_count(0)
                check('screen-reader/keyboard action has a named operable button',True)
                panel.locator('.theme-toggle').click();hold(item);shot(page,'390-menu-dark.png');page.keyboard.press('Escape')
                hold(item);page.once('dialog',lambda dialog:dialog.dismiss());menu.get_by_role('button',name='删除',exact=True).tap();expect(menu).to_have_count(0);page.wait_for_timeout(150)
                check('delete cancellation sends no delete command',not any(c.get('action')=='delete' for c in commands))
                hold(item);page.once('dialog',lambda dialog:dialog.accept());menu.get_by_role('button',name='删除',exact=True).tap();expect(item).to_have_count(0)
                check('confirmed delete uses existing exact-session command once',len([c for c in commands if c.get('action')=='delete' and c.get('session_id')=='workbench-touch-34'])==1)
                other=row('TEMP 会话 33');other.tap();expect(panel).not_to_be_visible();check('ordinary tap still opens the session and closes drawer',route()=='/chat/workbench-touch-33')
                context.close()
                desktop=browser.new_context(ignore_https_errors=True,viewport={'width':1280,'height':900},service_workers='block')
                desktop.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}]);page=desktop.new_page();page.goto(f['origin']+'/native/?path=%2Ftoolbox')
                item=page.locator('.session-item').filter(has=page.locator('.session-item-title',has_text='TEMP 会话 33'));item.hover();expect(item.locator('.session-actions')).to_be_visible();check('desktop retains native three hover actions',item.locator('.session-act').count()==3 and item.locator('.ew-session-menu-trigger').count()==0)
                shot(page,'1280-native-sidebar.png');check('menu operations never call an Agent',len(f['adapter'].requests)==0);check('no mobile JavaScript errors',not errors)
                desktop.close();report['passed']=all(c['passed'] for c in report['checks'])
            browser.close()
    except Exception as error:
        report['error']=repr(error)
        try:page.screenshot(path=str(out/'failure.png'))
        except Exception:pass
    finally:
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'error':report.get('error')},ensure_ascii=False));return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
