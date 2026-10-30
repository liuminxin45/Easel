"""Original Easel menus + native methods + private extensions, TEMP inference."""
import argparse
import asyncio
import importlib.util
import json
import re
from pathlib import Path
import shutil
import sys
import time
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('native_skill_browser',Path(__file__).with_name('workbench_native_browser.py'))
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)


async def native_run(self,request,emit,ask,bind):
    payload=json.JSONDecoder().raw_decode(request.prompt.split('## 本轮冻结输入\n')[-1])[0]
    if payload['session_task']!='native':return await self.original_run(request,emit,ask,bind)
    self.requests.append(request);native=request.native_id or 'native-fixture-'+request.session_key
    bind(native);request.on_native_turn(native,'native-fixture-turn-'+str(len(self.requests)))
    sid=payload['selected_skills'][0]['id'];emit('activity','TEMP 原生技能：'+sid)
    assert payload['authorization']['publish'] is False
    if sid=='ai-image-gen':emit('token','TEMP：生图通道尚未配置，请先补齐配置。');return
    folder=Path(payload['output_directory'])/'products';folder.mkdir(parents=True)
    if sid=='card-quote':
        (folder/'金句卡.png').write_bytes(self.image)
        (folder/'配文.txt').write_text('TEMP 原生金句卡配文',encoding='utf-8')
    else:(folder/'素材清单.csv').write_text('name,status\nTEMP,ready\n',encoding='utf-8')
    emit('token','TEMP 原生技能已按本轮冻结方法完成，实际文件已保存。')
    await asyncio.sleep(.1)


def main():
    p=argparse.ArgumentParser();p.add_argument('--native',required=True);p.add_argument('--out',required=True);p.add_argument('--backend');args=p.parse_args()
    if args.backend:sys.path.insert(0,str(Path(args.backend).resolve()))
    from playwright.sync_api import sync_playwright,expect
    native=Path(args.native).resolve();out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
    report={'passed':False,'checks':[],'real_AI_calls':0,'real_platform_writes':0,'physical_device_tested':False,
            'native':{'release':native.name,'manifest_sha256':h.sha(native/'native-manifest.json')},'harness_sha256':h.sha(__file__)}
    if args.backend:report['backend']={'directory':str(Path(args.backend).resolve()),'manifest_sha256':h.sha(Path(args.backend)/'workbench-release.json')}
    def check(profile,text):report['checks'].append({'profile':profile,'check':text,'passed':True});print('PASS',profile,text,flush=True)
    def wait_history(page,origin,sid,prior=None,files=False):
        deadline=time.monotonic()+90
        while time.monotonic()<deadline:
            result=page.request.get(origin+'/api/chat/sessions/'+sid).json()
            last=(result['session'].get('messages') or [{}])[-1]
            if last.get('role')=='assistant' and last.get('turnId')!=prior and last.get('status')=='completed' and (not files or last.get('output_files')):return result
            if last.get('status') in ('failed','unknown','stopped'):raise AssertionError(last)
            page.wait_for_timeout(150)
        raise AssertionError(result)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
            page=browser.new_page();page.set_content('<h1>TEMP original Easel card</h1>');image=page.screenshot();page.close()
            with h.isolated(native,image) as f:
                f['close_clients']=lambda:[context.close() for context in browser.contexts]
                for folder in (ROOT/'skills/builtin').iterdir():
                    if folder.is_dir() and (folder/'SKILL.md').is_file() and not (f['root']/'skills/builtin'/folder.name).exists():
                        shutil.copytree(folder,f['root']/'skills/builtin'/folder.name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
                shutil.copytree(ROOT/'skills/shared',f['root']/'skills/shared',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
                f['adapter'].original_run=f['adapter'].run;f['adapter'].run=native_run.__get__(f['adapter'])
                for profile,width,mobile in [('windows',1280,False),('mobile-simulated',390,True)]:
                    context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':900},is_mobile=mobile,has_touch=mobile,color_scheme='dark' if mobile else 'light')
                    context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
                    page=context.new_page();page.set_default_timeout(30000);errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                    page.goto(f['origin']+'/native/?'+urlencode({'path':'/chat?fresh=1'}));page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.startsWith('/chat/')")
                    sid=page.evaluate("decodeURIComponent(new URLSearchParams(location.search).get('path').slice(6))")
                    textarea=page.get_by_role('textbox',name='对话输入')
                    def choose(tab,query):
                        page.get_by_role('button',name='看看能做什么',exact=True).click();panel=page.get_by_role('dialog',name='能做的都在这')
                        for label in ('做内容 · 要成品','做运营 · 要动作','工作台扩展'):expect(panel.get_by_role('button',name=label,exact=True)).to_be_visible(timeout=30000)
                        panel.get_by_role('button',name=tab,exact=True).click();panel.get_by_placeholder('搜索…').fill(query)
                        labels={'card-quote':'金句卡 / 数据卡','asset-manager':'产物管理','ai-image-gen':'AI 生图'}
                        label=labels.get(query,query)
                        item=panel.locator('.brush-item:not(.brush-item-pipe)').filter(has=page.locator('.brush-il').filter(has_text=re.compile('^'+re.escape(label)+'$')))
                        expect(item).to_have_count(1,timeout=30000)
                        if query=='card-quote':page.screenshot(path=str(out/(profile+'-brush.png')),full_page=True,animations='disabled')
                        item.click()
                    rows=page.request.get(f['origin']+'/api/skills').json()
                    assert len(rows)==123 and sum(row.get('origin')=='easel' for row in rows)==115
                    assert all(row['validation_state']=='not_tested' for row in rows if row.get('origin')=='easel')
                    check(profile,'123 project-local skills include all 115 native methods and 8 private additions')
                    prior=None
                    for skill,tab,text in [('card-quote','做内容 · 要成品','TEMP 做一张金句卡'),('asset-manager','做运营 · 要动作','TEMP 整理本轮素材清单')]:
                        before=len(f['adapter'].requests);choose(tab,skill);assert len(f['adapter'].requests)==before
                        textarea.fill(text);expect(page.get_by_role('button',name='发送',exact=True)).to_be_enabled(timeout=30000);textarea.press('Enter')
                        history=wait_history(page,f['origin'],sid,prior,files=True);turn=history['session']['messages'][-1];prior=turn['turnId']
                        with f['box'].store.connect() as c:stored=json.loads(c.execute('SELECT document FROM easel_chat_turns WHERE id=?',(prior,)).fetchone()[0])
                        assert stored['snapshot']['task']=='native' and stored['snapshot']['active_skill_ids']==[skill],{'requested':skill,'snapshot_task':stored['snapshot']['task'],'selected':stored['snapshot'].get('active_skill_ids')}
                        assert stored['context']['skill_revision']==stored['snapshot']['skills'][0]['source_revision']
                        assert stored.get('work') is None and stored['hook_status']=='completed'
                        expect(page.get_by_role('region',name='对话产物预览').last).to_be_visible(timeout=30000)
                        assert len(f['adapter'].requests)==before+1
                        check(profile,skill+' uses its frozen native method and registered actual files without a private production plan')
                    choose('做内容 · 要成品','ai-image-gen');textarea.fill('TEMP 检查尚未配置的生图服务');textarea.press('Enter')
                    history=wait_history(page,f['origin'],sid,prior);assert not history['session']['messages'][-1]['output_files']
                    expect(page.get_by_text('TEMP：生图通道尚未配置，请先补齐配置。',exact=True)).to_be_visible(timeout=30000)
                    check(profile,'missing media configuration is explicit and creates no fictional artifact')
                    choose('工作台扩展','生成贴图');textarea.fill('TEMP 工作台扩展贴图');textarea.press('Enter')
                    history=wait_history(page,f['origin'],sid,history['session']['messages'][-1]['turnId'],files=True)
                    with f['box'].store.connect() as c:stored=json.loads(c.execute('SELECT document FROM easel_chat_turns WHERE id=?',(history['session']['messages'][-1]['turnId'],)).fetchone()[0])
                    assert stored['snapshot']['task']=='poster' and stored['work']['work_id']
                    check(profile,'private poster production remains a separate additional capability with its original work/version contract')
                    page.goto(f['origin']+'/native/?'+urlencode({'path':'/works'}));expect(page.get_by_role('heading',name='近期 Easel 原生产物',exact=True)).to_be_visible(timeout=30000)
                    expect(page.get_by_role('heading',name='TEMP 做一张金句卡',exact=True).first).to_be_visible(timeout=30000)
                    page.screenshot(path=str(out/(profile+'-library.png')),full_page=True,animations='disabled')
                    assert not errors,errors
                    check(profile,'native outputs and private works coexist in the content library')
                    before=len(f['adapter'].requests)
                    page.goto(f['origin']+'/native/?'+urlencode({'path':'/toolbox?section=skills'}))
                    expect(page.locator('.skill-card')).to_have_count(123,timeout=30000)
                    page.get_by_placeholder('搜索技能名或描述…').fill('card-quote')
                    page.locator('.skill-card').filter(has=page.locator('.skill-card-rawname').filter(has_text=re.compile('^card-quote$'))).click()
                    expect(page.get_by_text('Easel 原生技能，执行时冻结准确源码与依赖版本。',exact=True)).to_be_visible(timeout=30000)
                    page.get_by_placeholder('输入内容，例如主题 / 素材 / 要求…').fill('TEMP 从技能库带入对话')
                    page.get_by_role('button',name='带入对话',exact=True).click()
                    page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.startsWith('/chat/')")
                    expect(page.get_by_role('textbox',name='对话输入')).to_have_value('TEMP 从技能库带入对话',timeout=30000)
                    assert len(f['adapter'].requests)==before
                    check(profile,'the full skill library opens original documentation and carries the exact native selection into a new chat without sending')
                    context.close()
            browser.close()
        if args.backend:
            backend=Path(args.backend).resolve();modules=[Path(module.__file__).resolve() for name,module in sys.modules.items() if (name=='easel' or name.startswith('easel.') or name=='easel_workbench' or name.startswith('easel_workbench.')) and getattr(module,'__file__',None)]
            assert modules and all(path.is_relative_to(backend) for path in modules);report['module_roots_valid']=True
        report['passed']=True
    except Exception as error:report['error']=repr(error);raise
    finally:
        report['evidence']={path.name:h.sha(path) for path in out.glob('*.png')}
        (out/'browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'error':report.get('error')},ensure_ascii=True),flush=True)

if __name__=='__main__':main()
