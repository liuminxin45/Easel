"""Frozen Easel skill UI and ordinary chat, actual Edge + TEMP HTTPS only."""
from __future__ import annotations
import argparse,asyncio,base64,hashlib,importlib.util,json,sys,time
from pathlib import Path
from urllib.parse import urlencode,urlsplit,parse_qs
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
IMAGE=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aJ1kAAAAASUVORK5CYII=')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()

async def ordinary_run(self,request,emit,ask,bind):
    assert '## 本轮冻结输入' not in request.prompt,'ordinary native skills must not use the retired private orchestration'
    self.requests.append(request)
    number=len(self.requests);native=request.native_id or 'TEMP-native-'+request.session_key
    bind(native);request.on_native_turn(native,'TEMP-native-turn-'+str(number))
    folder=Path(request.cwd)/'outputs'/'TEMP-native-skills'/('run-'+str(number));folder.mkdir(parents=True,exist_ok=True)
    image=folder/'成品.png';image.write_bytes(IMAGE)
    body=folder/'正文.md';body.write_text('# TEMP ordinary result '+str(number)+'\n\nTEMP_ORIGINAL_TEXT_'+str(number),encoding='utf-8')
    await asyncio.sleep(.1)
    emit('token','TEMP_ORIGINAL_TEXT_'+str(number)+'\n\n![成品](/api/media/TEMP-native-skills/run-'+str(number)+'/成品.png)\n\n[正文]('+body.as_posix()+')')


def main():
    parser=argparse.ArgumentParser()
    for key in ('native','backend','out'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();native=args.native.resolve();backend=args.backend.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    for directory,name in ((native,'native-manifest.json'),(backend,'workbench-release.json')):
        manifest=json.loads((directory/name).read_text(encoding='utf-8'));assert all(sha(directory/path)==digest for path,digest in manifest['files'].items())
    sys.path.insert(0,str(backend))
    spec=importlib.util.spec_from_file_location('native_skills_fixture',ROOT/'tests/workbench_native_browser.py');helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper);helper.ROOT=backend
    from playwright.sync_api import sync_playwright,expect
    report={'passed':False,'backend':{'release':backend.name,'manifest_sha256':sha(backend/'workbench-release.json')},'native':{'release':native.name,'manifest_sha256':sha(native/'native-manifest.json')},'checks':[],'page_errors':[],'screenshots':{},'requests':{},'harness_sha256':sha(__file__),'fixture_sha256':sha(ROOT/'tests/workbench_native_browser.py'),'real_model_calls':0,'platform_writes':0,'production_data_access':False,'physical_device_tested':False}
    def check(case,label):report['checks'].append({'case':case,'check':label,'passed':True});print('PASS '+case+' '+label,flush=True)
    def goto(page,f,path):page.goto(f['origin']+'/native/?'+urlencode({'path':path}),wait_until='domcontentloaded')
    try:
      with patch.object(helper.SyntheticAdapter,'run',ordinary_run),sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
        for case,width,height,mobile,theme in [('desktop-light',1280,900,False,'light'),('mobile-dark',390,844,True,'dark')]:
          with helper.isolated(native,IMAGE) as f:
            context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':height},is_mobile=mobile,has_touch=mobile,service_workers='block')
            context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}]);context.add_init_script('localStorage.setItem("native:theme",'+json.dumps(theme)+');')
            page=context.new_page();page.set_default_timeout(30000);requests=[]
            page.on('pageerror',lambda error:report['page_errors'].append(str(error)))
            def requested(req):
                target=urlsplit(req.url)
                if target.path.startswith('/api/'):
                    row={'method':req.method,'path':target.path}
                    if req.method=='POST' and req.post_data:
                        try:
                            row['body']=req.post_data_json
                            if target.path=='/api/env' and isinstance(row['body'],dict):row['body']={**row['body'],'updates':{key:'[TEMP redacted]' for key in row['body'].get('updates',{})}}
                        except Exception:pass
                    requests.append(row)
            page.on('request',requested)
            try:
                goto(page,f,'/toolbox?section=skills')
                search=page.get_by_role('textbox',name='搜索技能');
                if search.count()==0:search=page.get_by_placeholder('搜索技能名或描述…')
                expect(page.locator('.skill-card').first).to_be_visible()
                assert page.get_by_role('button',name='整理经验',exact=True).count()==0
                for label in ['版本与试用','本次技能动作','确认适用范围并发布']:assert page.get_by_text(label,exact=True).count()==0
                search.fill('content-production');expect(page.locator('.skill-card')).to_have_count(1);page.locator('.skill-card').click()
                drawer=page.get_by_role('dialog');expect(drawer).to_be_visible();expect(drawer.locator('.skill-detail-rawname')).to_have_text('content-production')
                box=page.locator('.drawer-overlay').bounding_box();assert box and abs(box['width']-width)<2 and box['x']==0
                for label in ['项目技能','版本与试用','本次技能动作','确认本次制作']:assert drawer.get_by_text(label,exact=True).count()==0
                raw='  TEMP exact skill input '+case+'\n第二行原文  ';field=drawer.get_by_placeholder('输入内容，例如主题 / 素材 / 要求…');field.fill(raw)
                with page.expect_response(lambda r:urlsplit(r.url).path=='/api/skill' and r.request.method=='POST') as sent:drawer.get_by_role('button',name='执行',exact=True).click()
                assert sent.value.status==200,sent.value.text();expect(drawer.locator('.skill-result')).to_contain_text('TEMP_ORIGINAL_TEXT_1');expect(field).to_have_value(raw)
                sends=[r for r in requests if r['method']=='POST' and r['path']=='/api/skill'];assert len(sends)==1 and sends[0]['body']['skill']=='content-production' and sends[0]['body']['input']==raw.strip()
                assert len(f['adapter'].requests)==1
                check(case,'ordinary project card uses the full original drawer, exact input, one original skill POST and actual result')
                screenshot=out/(case+'-skill.png');page.screenshot(path=str(screenshot));report['screenshots'][screenshot.name]=sha(screenshot)
                drawer.get_by_role('button',name='关闭',exact=True).click()
                for path in ['/toolbox?section=skills&pane=experience','/toolbox?section=skills&item=content-production&trial=1&version=2']:
                    goto(page,f,path);expect(page.locator('.skill-card').first).to_be_visible();assert page.get_by_role('dialog').count()==0;assert page.get_by_role('button',name='整理经验',exact=True).count()==0
                assert page.request.get(f['origin']+'/api/skill/experience-distillation').status==404
                check(case,'retired experience/version routes cannot mount overlays and the removed skill is absent')
                goto(page,f,'/toolbox?section=skills');search=page.get_by_placeholder('搜索技能名或描述…');search.fill('ai-image-gen');expect(page.locator('.skill-card')).to_have_count(1);page.locator('.skill-card').click()
                drawer=page.get_by_role('dialog');expect(drawer.locator('.skill-detail-rawname')).to_have_text('ai-image-gen');secret=drawer.locator('input[type=password]').first;expect(secret).to_be_visible();secret.fill('TEMP-local-browser-key-'+case)
                with page.expect_response(lambda r:urlsplit(r.url).path=='/api/env' and r.request.method=='POST') as configured:drawer.get_by_role('button',name='保存到 .env',exact=True).click()
                assert configured.value.status==200,configured.value.text();expect(drawer.get_by_text('已保存 ✓',exact=True)).to_be_visible()
                assert 'TEMP-local-browser-key-'+case not in drawer.inner_text()
                assert len(f['adapter'].requests)==1
                check(case,'original API configuration dialog saves through the host vault without exposing secrets or starting an Agent')
                screenshot=out/(case+'-configuration.png');page.screenshot(path=str(screenshot));report['screenshots'][screenshot.name]=sha(screenshot)
                drawer.get_by_role('button',name='关闭',exact=True).click()
                goto(page,f,'/chat?fresh=1');page.wait_for_function('()=>new URLSearchParams(location.search).get("path")?.startsWith("/chat/")')
                sid=parse_qs(urlsplit(page.url).query)['path'][0].split('/chat/')[1].split('?')[0]
                composer=page.get_by_role('textbox',name='对话输入');expect(composer).to_be_visible();composer.fill('/content-production TEMP chat source '+case)
                item=page.get_by_role('menuitem',name='/content-production',exact=True);expect(item).to_be_visible();item.click()
                expect(page.locator('[data-chat-command]')).to_contain_text('content-production')
                before=len(f['adapter'].requests);page.get_by_role('button',name='发送',exact=True).click();history=helper.wait_history(page,f['origin'],sid)
                assert len(f['adapter'].requests)==before+1;expect(page.locator('.chat-thread')).to_contain_text('TEMP_ORIGINAL_TEXT_2')
                submit=[r for r in requests if r['path']=='/api/chat/submit' and r['method']=='POST'][-1]['body'];ctx=submit['context'];assert ctx['skill_id']=='content-production' and ctx['action_id']=='native'
                for key in ['version','trial','plan_token','work_id','parent_version_id']:assert key not in ctx
                assert 'TEMP chat source '+case in submit['message']
                composer.fill('请修改刚才的贴图，保留原文件并另存。 TEMP edit '+case);page.get_by_role('button',name='发送',exact=True).click();helper.wait_history(page,f['origin'],sid,history['session']['messages'][-1]['turnId'])
                expect(page.locator('.chat-thread')).to_contain_text('TEMP_ORIGINAL_TEXT_3');assert len(f['adapter'].requests)==3
                check(case,'original slash menu sends a generic native skill and a later modification creates separate actual files')
                api=f['box']._native_api;api._build_library()
                start=len(requests);goto(page,f,'/works?path=TEMP-native-skills/run-3/正文.md');expect(page.get_by_text('TEMP_ORIGINAL_TEXT_3',exact=False).first).to_be_visible()
                assert not any(r['path']=='/api/outputs' for r in requests[start:]);assert any(r['path'].startswith('/api/output/') for r in requests[start:])
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                check(case,'actual revised file is previewed in the original indexed content library without a full-tree request')
                screenshot=out/(case+'-output.png');page.screenshot(path=str(screenshot));report['screenshots'][screenshot.name]=sha(screenshot)
                forbidden=['/api/chat/plan','/api/creator/commands','/api/creative/commands'];assert not any(r['method']=='POST' and r['path'] in forbidden for r in requests)
                with f['box'].store.connect() as c:
                    assert c.execute('SELECT count(*) FROM creator_task_runs').fetchone()[0]==0
                    assert c.execute('SELECT count(*) FROM creator_skill_versions').fetchone()[0]==0
                check(case,'no private skill plan, registry version, experience command or business task snapshot was generated')
                report['requests'][case]=requests
            finally:context.close()
        browser.close()
      assert not report['page_errors'];report['passed']=True
    finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0

if __name__=='__main__':raise SystemExit(main())
