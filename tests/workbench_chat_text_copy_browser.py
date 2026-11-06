"""Actual Edge/TEMP native chat; only clipboard endpoints are synthetic."""
import argparse,hashlib,importlib.util,json,sys,time
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
TITLE='想学大厂AI工程实践不用再挨个追更新'
BODY='做 AI Coding，大家都在摸索怎么把它真正用进工程。\n\n这些文章散落在公众号、技术社区和各家公司的团队网站里。\n\n所以我把这些技术博客整理到一个看板里，可以按公司和主题查找。\n\n目前收录以具体团队为准，采集可能有延迟。\n\n看板地址：https://liuminxin45.github.io/ai-engineering-radar/?source=公众号&view=all\n\n保留 <字样>、& 符号和完整段落。'
SID='TEMP-copy-chat'

def seed(f):
 chat=f['app'].state.chat
 chat.create_session({'id':'TEMP-copy-create','session_id':SID,'profile_id':'oil-pig'})
 output='### 标题\n\n```text\n'+TITLE+'\n```\n\n### 正文\n\n```text\n'+BODY+'\n```\n\n### 执行示例\n\n```python\nprint("不是配文")\n```'
 turn={'id':'TEMP-copy-turn','session_id':SID,'operation_id':'TEMP-copy-turn','created_at':'2026-11-06T12:00:00Z','updated_at':'2026-11-06T12:00:01Z','status':'completed','hook_status':'completed','message':'请展示已有标题和正文。','output':output,'context':{},'runtime':'codex'}
 with f['box'].store.connect() as c:
  session=chat._session(c,SID);session['title']='TEMP 标题与正文点按复制';chat._put_session(c,session)
  c.execute('INSERT INTO easel_chat_turns VALUES(?,?,?,?,?)',(turn['id'],SID,turn['id'],'TEMP-signature',json.dumps(turn,ensure_ascii=False)))

def main():
 p=argparse.ArgumentParser()
 for name in ('backend','native','out'):p.add_argument('--'+name,type=Path,required=True)
 args=p.parse_args();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
 spec=importlib.util.spec_from_file_location('copy_browser_infra',ROOT/'tests/workbench_news_creation_browser.py');h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
 helper,application,create_app=h.infrastructure(args.backend.resolve(),args.native.resolve())
 from playwright.sync_api import sync_playwright,expect
 expect.set_options(timeout=30000)
 report={'passed':False,'checks':[],'backend':h.frozen(args.backend,'workbench-release.json'),'native':h.frozen(args.native,'native-manifest.json'),'screenshots':{},'errors':[],'real_model_calls':0,'production_data_access':False,'clipboard_endpoints':'synthetic writeText and execCommand; original DOM/event/selection/focus','physical_device_tested':False}
 def check(layout,name):report['checks'].append({'layout':layout,'name':name,'passed':True});print('PASS',layout,name,flush=True)
 try:
  with patch.object(application,'create_app',create_app),sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
   with helper.isolated(args.native.resolve(),h.IMAGE) as f:
    seed(f)
    for layout,width,height,mobile,theme in h.LAYOUTS:
     context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':height},is_mobile=mobile,has_touch=mobile,service_workers='block')
     context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
     context.add_init_script('''localStorage.setItem('native:theme',THEME);window.__copied=[];window.__copyMode='modern';Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:async value=>{if(window.__copyMode!=='modern')throw Error('TEMP clipboard denied');window.__copied.push(value)}}});document.execCommand=(name)=>{if(name!=='copy'||window.__copyMode==='failed')return false;const input=document.activeElement;if(!input||input.tagName!=='TEXTAREA'||input.selectionStart!==0||input.selectionEnd!==input.value.length)return false;window.__copied.push(input.value);return true};'''.replace('THEME',json.dumps(theme)))
     page=context.new_page();page.set_default_timeout(30000);page.on('pageerror',lambda error:report['errors'].append(str(error)))
     h.goto(page,f['origin'],'/chat/'+SID)
     title=page.locator('[data-ew-copy-target="标题"]');body=page.locator('[data-ew-copy-target="正文"]');expect(title).to_have_count(1);expect(body).to_have_count(1)
     press=lambda locator:locator.tap() if mobile else locator.click()
     press(title);page.wait_for_function('()=>window.__copied.length===1');assert page.evaluate('window.__copied[-1]??window.__copied.at(-1)')==TITLE
     press(body);page.wait_for_function('()=>window.__copied.length===2');assert page.evaluate('window.__copied.at(-1)')==BODY
     assert body.locator('code').inner_text().rstrip('\n')==BODY
     check(layout,'tap title/body copies the complete separate literal field, including offscreen text and URL')
     page.locator('[data-ew-copy-label="标题"]').click();page.wait_for_function('()=>window.__copied.length===3');assert page.evaluate('window.__copied.at(-1)')==TITLE
     body.focus();body.press('Enter');page.wait_for_function('()=>window.__copied.length===4');assert page.evaluate('window.__copied.at(-1)')==BODY
     body.press('Space');page.wait_for_function('()=>window.__copied.length===5')
     check(layout,'label tap and keyboard activation work without adding controls')
     before=page.evaluate('window.__copied.length')
     body.evaluate('''el=>{el.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,clientX:50,clientY:100}));el.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,clientX:100,clientY:160}));el.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,clientX:100,clientY:160}));el.dispatchEvent(new MouseEvent('click',{bubbles:true,button:0,detail:1}))}''')
     page.wait_for_timeout(50);assert page.evaluate('window.__copied.length')==before
     body.evaluate('''el=>{const range=document.createRange();range.selectNodeContents(el.querySelector('code'));getSelection().removeAllRanges();getSelection().addRange(range);el.dispatchEvent(new MouseEvent('click',{bubbles:true,button:0,detail:1}))}''')
     assert page.evaluate('window.__copied.length')==before;page.evaluate('getSelection().removeAllRanges()')
     plain=page.locator('.message-bubble.assistant pre:not([data-ew-copy-target])');press(plain);assert page.evaluate('window.__copied.length')==before
     body.evaluate("el=>el.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,clientX:50,clientY:100}))")
     page.wait_for_timeout(600)
     body.evaluate("el=>el.dispatchEvent(new MouseEvent('click',{bubbles:true,button:0,detail:1}))")
     assert page.evaluate('window.__copied.length')==before
     body.evaluate("el=>{const cursor=document.createElement('span');cursor.className='streaming-cursor';el.closest('.message-bubble').append(cursor);el.dispatchEvent(new MouseEvent('click',{bubbles:true,button:0,detail:0}));cursor.remove()}")
     assert page.evaluate('window.__copied.length')==before
     check(layout,'drag, long press, live cursor, selected text and ordinary code blocks do not copy')
     page.evaluate('window.__copyMode="compat"');press(body);page.wait_for_function('()=>window.__copied.length===6');assert page.evaluate('window.__copied.at(-1)')==BODY
     expect(body).to_be_focused();check(layout,'WebView compatibility path copies full content and restores focus')
     page.evaluate('window.__copyMode="failed"');press(title);expect(page.locator('[data-ew-copy-label="标题"]')).to_have_attribute('data-ew-copy-error','true');assert page.evaluate('window.__copied.length')==6
     page.evaluate('window.__copyMode="modern"');press(title);page.wait_for_function('()=>window.__copied.length===7');expect(page.locator('[data-ew-copy-label="标题"]')).to_have_attribute('data-ew-copy-feedback','已复制标题')
     check(layout,'clipboard denial displays a real error; a successful retry clears it')
     composer=page.get_by_role('textbox',name='对话输入');composer.fill('后写草稿必须保留');press(body);page.wait_for_function('()=>window.__copied.length===8');expect(composer).to_have_value('后写草稿必须保留')
     assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
     file=out/(layout+'.png');page.screenshot(path=str(file));report['screenshots'][file.name]=hashlib.sha256(file.read_bytes()).hexdigest()
     check(layout,'draft and page geometry remain intact; no model invocation or business write')
     context.close()
    assert not f['adapter'].requests
   browser.close()
  assert not report['errors'];report['passed']=True
 except Exception as error:
  import traceback
  report.update(error=repr(error),traceback=traceback.format_exc())
 finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'error':report.get('error')},ensure_ascii=False));return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
