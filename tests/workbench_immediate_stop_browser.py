"""Actual frozen UI/HTTPS/TEMP DB. The only substitute is the Agent executor."""
import argparse,asyncio,importlib.util,json,sys,hashlib,time
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]

def main():
 p=argparse.ArgumentParser()
 for name in ('backend','native','out'):p.add_argument('--'+name,type=Path,required=True)
 args=p.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
 spec=importlib.util.spec_from_file_location('stop_browser_infra',ROOT/'tests/workbench_news_creation_browser.py');h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
 helper,application,create_app=h.infrastructure(args.backend.resolve(),args.native.resolve())
 from playwright.sync_api import sync_playwright,expect
 from easel.harnesses.base import HarnessError
 expect.set_options(timeout=30000)
 report={'passed':False,'checks':[],'backend':h.frozen(args.backend,'workbench-release.json'),'native':h.frozen(args.native,'native-manifest.json'),'errors':[],'screenshots':{},'real_model_calls':0,'production_data_access':False,'physical_device_tested':False}
 try:
  with patch.object(application,'create_app',create_app),sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
   with helper.isolated(args.native.resolve(),h.IMAGE) as f:
    adapter=f['adapter'];adapter.mode='unknown'
    async def run(request,emit,ask,bind):
     adapter.requests.append(request);number=len(adapter.requests);native=request.native_id or 'temp-native-'+request.session_key
     request.on_execution_receipt({'kind':'codex_stop_ready'})
     attached={'pid':1000+number,'process_token':format(number,'032x')}
     request.on_execution_receipt({'kind':'codex_process_attached',**attached})
     request.on_execution_receipt({'kind':'codex_dispatching'})
     bind(native);request.on_native_turn(native,'temp-turn-'+str(number));emit('token','TEMP 已受理，仅为隔离执行。')
     if adapter.mode=='complete':emit('token','新的明确消息已完成。');return
     await request.stop_event.wait()
     request.on_execution_receipt({'kind':'codex_process_closed',**attached,'returncode':1,'tree_closed':True})
     raise HarnessError('TEMP 停止原生回执丢失，本地执行已确认关闭')
    adapter.run=run
    for layout,width,height,mobile,theme in h.LAYOUTS:
     adapter.mode='unknown'
     context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':height},is_mobile=mobile,has_touch=mobile,service_workers='block')
     context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
     context.add_init_script('localStorage.setItem("native:theme",'+json.dumps(theme)+')')
     page=context.new_page();page.set_default_timeout(30000);page.on('pageerror',lambda error:report['errors'].append(str(error)))
     h.goto(page,f['origin'],'/chat?fresh=1')
     page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.startsWith('/chat/')")
     sid=parse_qs(urlsplit(page.url).query)['path'][0].split('/chat/')[1].split('?')[0]
     composer=page.get_by_role('textbox',name='对话输入',exact=True);expect(composer).to_be_visible()
     before=len(adapter.requests);composer.fill('TEMP 发消息后立即停止');composer.press('Enter')
     stop=page.locator('button[title="停止生成"]');expect(stop).to_be_visible()
     deadline=time.monotonic()+30
     while len(adapter.requests)==before:
      assert time.monotonic()<deadline,'TEMP native adapter must be entered for this scenario';page.wait_for_timeout(25)
     stop.click()
     page.wait_for_function("sid=>{const d=JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid));return d&&!d.pending}",arg=sid)
     receipt=page.request.get(f['origin']+'/api/chat/last/'+sid).json()
     assert receipt.get('execution_status')=='unknown' and receipt.get('execution_closed') and len(adapter.requests)==before+1,receipt
     composer.fill('TEMP 后写草稿');expect(page.get_by_role('button',name='发送',exact=True)).to_be_enabled()
     expect(page.get_by_role('status',name='会话恢复',exact=True)).to_have_count(0)
     page.reload(wait_until='domcontentloaded');expect(composer).to_have_value('TEMP 后写草稿')
     expect(page.get_by_role('button',name='发送',exact=True)).to_be_enabled()
     adapter.mode='complete';composer.press('Enter')
     page.wait_for_function("sid=>!JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid)).pending",arg=sid)
     latest=page.request.get(f['origin']+'/api/chat/last/'+sid).json()
     assert latest['execution_status']=='completed' and len(adapter.requests)==before+2
     assert adapter.requests[-1].session_key!=adapter.requests[-2].session_key
     old=page.request.get(f['origin']+'/api/chat/last/'+sid+'?turn_id='+receipt['turn_id']).json()
     assert old['execution_status']=='unknown' and old['execution_closed']
     expect(page.get_by_role('status',name='本轮状态',exact=True)).to_be_visible()
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
     image=out/(layout+'.png');page.screenshot(path=str(image));report['screenshots'][image.name]=h.sha(image)
     report['checks'].append({'layout':layout,'passed':True,'checks':['immediate stop','unknown preserved with closure','composer unlocked','draft survives reload','next explicit message new native key','old receipt unchanged','no recovery banner','no horizontal overflow']})
     print('PASS',layout,flush=True);context.close()
   browser.close()
  assert not report['errors'];report['passed']=True
 except Exception as error:
  import traceback
  report.update(error=repr(error),traceback=traceback.format_exc())
 finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'passed':report['passed'],'layouts':len(report['checks']),'error':report.get('error')},ensure_ascii=False));return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
