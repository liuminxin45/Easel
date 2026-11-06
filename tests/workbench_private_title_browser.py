"""Frozen UI title wiring with TEMP sessions and a fake Agent only."""
import argparse,hashlib,importlib.util,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 p=argparse.ArgumentParser()
 for k in ('native','backend','out'):p.add_argument('--'+k,type=Path,required=True)
 a=p.parse_args();native,backend,out=a.native.resolve(),a.backend.resolve(),a.out.resolve();out.mkdir(parents=True,exist_ok=True)
 sys.path.insert(0,str(backend));spec=importlib.util.spec_from_file_location('title_fixture',ROOT/'tests/workbench_native_browser.py');h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h);h.ROOT=backend
 from playwright.sync_api import sync_playwright,expect
 expect.set_options(timeout=15000)
 report={'passed':False,'checks':[],'native':native.name,'backend':backend.name,'real_AI_calls':0,'production_data_access':False,'physical_mobile_device_tested':False,'harness_sha256':sha(__file__)}
 def check(name,ok=True):report['checks'].append({'name':name,'passed':bool(ok)});assert ok,name
 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
   with h.isolated(native,b'TEMP unused image') as f:
    chat=f['app'].state.chat;admissions=f['app'].state.chat_admissions;original=admissions.business.prepare
    def prepare(value):
     if value['sessionId']=='workbench-title-fail':raise ValueError('TEMP preparation failure')
     return original(value)
    admissions.business.prepare=prepare
    for sid in ('workbench-title-url','workbench-title-fail'):chat.create_session({'id':'create-'+sid,'session_id':sid,'profile_id':'oil-pig'})
    context=browser.new_context(ignore_https_errors=True,viewport={'width':390,'height':844},is_mobile=True,has_touch=True,service_workers='block');f['close_clients']=context.close
    context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}]);page=context.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
    for sid,expected in [('workbench-title-url','owner/repository'),('workbench-title-fail','owner/repository')]:
     page.goto(f['origin']+'/native/?path=%2Fchat%2F'+sid);box=page.get_by_role('textbox',name='对话输入',exact=True);expect(box).to_be_enabled();box.fill('https://github.com/owner/repository');box.press('Enter')
     page.wait_for_function("async sid=>{const d=await(await fetch('/api/chat/sessions/'+sid)).json();return ['completed','failed'].includes(d.session?.messages?.at(-1)?.status)}",arg=sid)
     page.wait_for_function("sid=>!JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid))?.pending",arg=sid)
     data=page.request.get(f['origin']+'/api/chat/sessions/'+sid).json();check(sid+' saves official-plus-URL title',data['session']['title']==expected)
     check(sid+' ends with actual expected receipt',data['session']['messages'][-1]['status']==('failed' if sid.endswith('fail') else 'completed'))
     with chat.store.connect() as c:
      s=chat._session(c,sid);s.update(title='新对话',title_source='automatic',revision=s['revision']+1);chat._put_session(c,s)
     page.reload();page.get_by_role('button',name='打开导航',exact=True).tap();expect(page.locator('.session-item-title',has_text=expected)).to_be_visible();check(sid+' repairs existing placeholder from original history')
     if sid.endswith('url'):
      trigger=page.get_by_role('button',name='会话操作：owner/repository',exact=True);trigger.focus();page.keyboard.press('Enter');page.get_by_role('dialog',name='会话操作',exact=True).get_by_role('button',name='重命名',exact=True).click();rename=page.locator('.session-rename-input');rename.fill('手动标题');rename.press('Enter');expect(page.locator('.session-item-title',has_text='手动标题')).to_be_visible();page.locator('.sidebar-backdrop').tap(position={'x':375,'y':120});box.fill('请继续讨论');box.press('Enter');page.wait_for_function("sid=>!JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid))?.pending",arg=sid)
      check('later messages preserve explicit manual title',page.request.get(f['origin']+'/api/chat/sessions/'+sid).json()['session']['title']=='手动标题')
    check('no browser JavaScript errors',not errors);check('failed preparation never calls Agent',len(f['adapter'].requests)==2)
    page.screenshot(path=str(out/'mobile-title.png'));report['passed']=True;report['errors']=errors
   browser.close()
 except Exception as e:report['error']=repr(e)
 finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'error':report.get('error')}));return 0 if report['passed'] else 1
if __name__=='__main__':raise SystemExit(main())
