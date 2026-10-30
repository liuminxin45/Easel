"""Actual Windows Edge against TEMP HTTPS: permissions and upstream chat lifecycle."""
import argparse
import asyncio
import importlib.util
import json
from pathlib import Path
import sys
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('native_browser',Path(__file__).with_name('workbench_native_browser.py'))
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)


async def alignment_run(self,request,emit,ask,bind):
    self.requests.append(request)
    native=request.native_id or 'temp-native-'+request.session_key
    bind(native);request.on_native_turn(native,'temp-turn-'+str(len(self.requests)))
    emit('activity','TEMP 第一步');emit('activity','TEMP 第二步')
    if 'REQUEST_PERMISSION' in request.prompt:
        answer=await ask([{'questionId':'permission','header':'执行授权','question':'TEMP PowerShell 操作授权（假执行器，无系统命令）',
                          'options':[{'label':'允许本次'},{'label':'拒绝'}]}])
        self.answers.append(answer)
        await asyncio.sleep(1.5)
    emit('activity','TEMP 第三步')
    emit('token','TEMP 回复完成。')


def main():
    p=argparse.ArgumentParser();p.add_argument('--native',required=True);p.add_argument('--out',required=True);p.add_argument('--headed',action='store_true');p.add_argument('--backend');args=p.parse_args()
    if args.backend:
        backend=Path(args.backend).resolve();sys.path.insert(0,str(backend))
        manifest=json.loads((backend/'workbench-release.json').read_text(encoding='utf-8'))
        assert all(h.sha(backend/name)==digest for name,digest in manifest['files'].items())
    from playwright.sync_api import sync_playwright,expect
    out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True);native=Path(args.native).resolve()
    report={'passed':False,'checks':[],'real_AI_calls':0,'real_platform_writes':0,'physical_mobile_device_tested':False,'harness_sha256':h.sha(__file__),'native':{'release':native.name,'manifest_sha256':h.sha(native/'native-manifest.json')}}
    if args.backend:report['backend']={'directory':str(backend),'manifest_sha256':h.sha(backend/'workbench-release.json')}
    def check(profile,name):report['checks'].append({'profile':profile,'check':name,'passed':True});print('PASS',profile,name,flush=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=not args.headed,args=['--ignore-certificate-errors'])
            page=browser.new_page();page.set_content('TEMP');image=page.screenshot();page.close()
            with h.isolated(native,image) as f:
                f['close_clients']=lambda:[context.close() for context in browser.contexts]
                f['adapter'].answers=[];f['adapter'].run=alignment_run.__get__(f['adapter'])
                for profile,width,mobile in [('windows',1280,False),('mobile-simulated',390,True)]:
                    context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':900},is_mobile=mobile,has_touch=mobile,color_scheme='light')
                    context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
                    page=context.new_page();page.set_default_timeout(20000);errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                    def menu():
                        if mobile:page.get_by_role('button',name='打开工作导航').click()
                    def chat_again(sid):
                        menu();page.locator('.session-item').filter(has=page.locator('.session-item-title')).filter(has_text=title).first.click()
                        expect(page.get_by_role('textbox',name='对话输入')).to_be_visible()
                    page.goto(f['origin']+'/native/?'+urlencode({'path':'/chat?fresh=1'}));page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.startsWith('/chat/')")
                    sid=page.evaluate("decodeURIComponent(new URLSearchParams(location.search).get('path').slice(6))")
                    textarea=page.get_by_role('textbox',name='对话输入')
                    expect(page.get_by_text('Enter 发送 · Shift+Enter 换行',exact=True)).to_be_visible()
                    page.get_by_role('button',name='看看能做什么').click();panel=page.get_by_role('dialog',name='能做的都在这');expect(panel).to_be_visible()
                    panel.get_by_placeholder('搜索…').fill('生成贴图');expect(panel.get_by_role('button').filter(has_text='生成贴图')).to_have_count(1)
                    panel.get_by_role('button').filter(has_text='生成贴图').click();expect(textarea).to_have_value('帮我生成贴图');assert not f['adapter'].requests if profile=='windows' else True
                    page.get_by_role('button',name='移除所选技能').click()
                    check(profile,'official brush filters actual skills and prefills without execution')
                    textarea.fill('REQUEST_PERMISSION '+profile);textarea.press('Shift+Enter');expect(textarea).to_have_value('REQUEST_PERMISSION '+profile+'\n');textarea.press('Enter')
                    card=page.locator('.question-card');expect(card).to_be_visible(timeout=20000);expect(page.locator('.live-activity')).to_contain_text('TEMP 第二步')
                    expect(page.locator('summary').filter(has_text='执行过程')).to_have_count(0)
                    title=page.request.get(f['origin']+'/api/chat/sessions/'+sid).json()['session']['title'];assert title not in ('新对话','New Chat')
                    check(profile,'first message names the session; streaming shows latest activity without completed collapse')
                    count=len(f['adapter'].requests);menu();page.get_by_role('button',name='内容库',exact=True).click();expect(page.get_by_role('heading',name='内容库',exact=True)).to_be_visible();chat_again(sid)
                    expect(card).to_be_visible(timeout=20000);assert len(f['adapter'].requests)==count
                    check(profile,'pending permission survives view switches without a new native turn')
                    page.reload();expect(card).to_be_visible(timeout=20000);assert len(f['adapter'].requests)==count
                    check(profile,'refresh restores only the live question from the original turn')
                    decision='允许本次' if profile=='windows' else '拒绝'
                    if profile=='windows':
                        def lose_ack(route):route.fetch();route.abort('failed')
                        page.route('**/api/chat/question/answer',lose_ack)
                    card.get_by_role('button',name=decision,exact=True).click();card.get_by_role('button',name='提交',exact=True).click();expect(card).to_have_count(0)
                    h.wait_history(page,f['origin'],sid)
                    expect(textarea).to_be_enabled();expect(page.get_by_text('提交失败',exact=True)).to_have_count(0)
                    assert f['adapter'].answers[-1]=={'permission':[decision]}
                    check(profile,'permission response is accepted once, including lost HTTP acknowledgement')
                    summary=page.locator('summary').filter(has_text='执行过程');expect(summary).to_have_count(1)
                    assert not summary.locator('..').evaluate('e=>e.open');summary.click();assert summary.locator('..').evaluate('e=>e.open');summary.click()
                    menu();page.get_by_role('button',name='内容库',exact=True).click();chat_again(sid)
                    page.evaluate("()=>{window.__questionFlashes=0;new MutationObserver(ms=>{for(const m of ms)for(const n of m.addedNodes)if(n.nodeType===1&&(n.matches?.('.question-card')||n.querySelector?.('.question-card')))window.__questionFlashes++}).observe(document.body,{childList:true,subtree:true})}")
                    page.wait_for_timeout(5500);assert page.evaluate('window.__questionFlashes')==0;expect(card).to_have_count(0);assert len(f['adapter'].requests)==count
                    check(profile,'completed process collapses; answered permission never flashes on return')
                    menu();page.get_by_role('button',name='切换深色').click()
                    if mobile:page.get_by_role('button',name='关闭工作导航').click()
                    raw='保留长草稿\n'*250;textarea.fill(raw);page.reload();expect(textarea).to_have_value(raw)
                    page.wait_for_function("raw=>{const e=document.querySelector('textarea[aria-label=\"对话输入\"]');return e?.value===raw&&e.clientHeight>0&&e.scrollHeight>e.clientHeight}",arg=raw)
                    textarea.evaluate('e=>e.scrollTop=e.scrollHeight');assert textarea.evaluate('e=>e.scrollTop>0')
                    assert not errors,errors
                    page.screenshot(path=str(out/(profile+'-chat.png')),full_page=True,animations='disabled')
                    check(profile,'dark theme and long raw draft survive reload with usable internal scrolling')
                    context.close()
            browser.close()
        if args.backend:
            modules={name:str(Path(module.__file__).resolve()) for name,module in sys.modules.items() if (name=='easel' or name.startswith('easel.') or name=='easel_workbench' or name.startswith('easel_workbench.')) and getattr(module,'__file__',None)}
            assert modules and all(Path(path).is_relative_to(backend) for path in modules.values()),modules
            report.update(module_count=len(modules),module_roots_valid=True)
        report['passed']=True
    except Exception as error:
        report['error']=repr(error);raise
    finally:
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'error':report.get('error')},ensure_ascii=True),flush=True)

if __name__=='__main__':main()
