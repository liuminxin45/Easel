"""PR197/198 frozen UI regression: real Edge, TEMP HTTPS/data and fake Agent only."""
from __future__ import annotations
import argparse,base64,hashlib,importlib.util,json,shutil,sys
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlencode,urlsplit,parse_qs
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
IMAGE=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aJ1kAAAAASUVORK5CYII=')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()

async def fake_run(self,request,emit,ask,bind):
    self.requests.append(request)
    native=request.native_id or 'TEMP-pr-'+request.session_key
    bind(native);request.on_native_turn(native,'TEMP-pr-turn-'+str(len(self.requests)))
    emit('token','TEMP 原生热点调用已完成；无真实模型或平台操作。')

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('native','backend','out'):parser.add_argument('--'+key,required=True,type=Path)
    args=parser.parse_args();native=args.native.resolve();backend=args.backend.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    for directory,name in ((native,'native-manifest.json'),(backend,'workbench-release.json')):
        manifest=json.loads((directory/name).read_text(encoding='utf-8'));assert all(sha(directory/name)==digest for name,digest in manifest['files'].items())
    sys.path.insert(0,str(backend))
    fixture_path=ROOT/'tests/workbench_native_browser.py'
    spec=importlib.util.spec_from_file_location('user_pr_fixture',fixture_path);helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper);helper.ROOT=backend
    from playwright.sync_api import sync_playwright,expect
    import easel_workbench.application as application
    original_create_app=application.create_app
    def create_app(*args,**kwargs):
        root=Path(kwargs['root']);(root/'config').mkdir(exist_ok=True)
        shutil.copy2(backend/'config/workbench-skills.json',root/'config/workbench-skills.json')
        return original_create_app(*args,**kwargs)
    report={'passed':False,'checks':[],'screenshots':{},'requests':{},'page_errors':[],
        'backend':{'release':backend.name,'manifest_sha256':sha(backend/'workbench-release.json')},
        'native':{'release':native.name,'manifest_sha256':sha(native/'native-manifest.json')},
        'harness_sha256':sha(__file__),'fixture_sha256':sha(fixture_path),'real_model_calls':0,'production_writes':0,'physical_device_tested':False}
    def check(case,name,**evidence):
        report['checks'].append({'case':case,'name':name,'passed':True,**evidence});print('PASS '+case+' '+name,flush=True)
    def screenshot(page,case,name):
        target=out/(case+'-'+name+'.png');page.screenshot(path=str(target));report['screenshots'][target.name]=sha(target)
    def overflow(page):
        return page.evaluate('()=>({width:innerWidth,document:document.documentElement.scrollWidth,body:document.body.scrollWidth})')
    try:
      with patch.object(application,'create_app',create_app),patch.object(helper.SyntheticAdapter,'run',fake_run),sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
        for case,width,height,mobile,theme in [('desktop-light',1280,900,False,'light'),('desktop-dark',1280,900,False,'dark'),('mobile-dark',390,844,True,'dark'),('mobile-light',360,780,True,'light'),('landscape-dark',844,390,True,'dark')]:
          compact=width<=900 or width<=1100 and height<=500
          with helper.isolated(native,IMAGE) as f:
            from easel_workbench.runtime.native_api import NativeApi
            native_api=NativeApi(f['box']);f['box']._native_api=native_api
            native_api._save_ideas([{'id':'TEMP-idea-'+str(n),'title':'TEMP 长选题 '+('中文说明 '*12)+str(n),'status':'pending','source':'TEMP'} for n in range(10)])
            native_api._save_schedule([{'id':'TEMP-schedule-'+str(n),'title':'TEMP 长排期 '+('中文说明 '*12)+str(n),'date':datetime.now().date().isoformat(),'time':'12:30','platform':'公众号','status':'scheduled','kind':'content','source':'manual'} for n in range(10)])
            selected=[]
            for source,definition in list(f['app'].state.collection.registry.baseline().items())[:3]:
                selected.append(source)
                f['box'].store.ingest({'schema_version':1,'source_job':source,'feed_id':definition['feed'],'run_id':'TEMP-pr-ui-'+source,'run_at':datetime.now(timezone.utc).isoformat(),'final_text':'TEMP',
                    'articles':[{'title':f'TEMP {number:02d} '+('一句话中文完整热点标题 ' * 9),'body':'TEMP 原文。\n'+('完整采集正文与来源保持原样。\n'*100),'url':f'https://example.com/pr-ui/{source}/{number}','source_order':number} for number in range(1,51)]})
            context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':height},is_mobile=mobile,has_touch=mobile,service_workers='block')
            context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}]);context.add_init_script('localStorage.setItem("native:theme",'+json.dumps(theme)+');')
            page=context.new_page();page.set_default_timeout(25000);requests=[];report['requests'][case]=requests
            page.on('pageerror',lambda error:report['page_errors'].append(str(error)))
            def requested(req):
                if urlsplit(req.url).path.startswith('/api/'):
                    row={'path':urlsplit(req.url).path,'method':req.method}
                    if req.method=='POST' and req.post_data:
                        try:row['body']=req.post_data_json
                        except Exception:pass
                    requests.append(row)
            page.on('request',requested)
            def go(path):page.goto(f['origin']+'/native/?'+urlencode({'path':path}),wait_until='domcontentloaded')
            def news():
                go('/news?sources='+','.join(selected));expect(page.locator('.trend-item').first).to_be_visible();page.wait_for_function('()=>document.querySelector(".trends-page")?.getAttribute("aria-busy")==="false"')
            try:
                news()
                panels=page.locator('.trend-col');assert panels.count()>=1
                structure=panels.evaluate_all('els=>els.map(el=>({bodies:el.querySelectorAll(".content-panel-body").length,same:el.querySelector(".content-panel-body")===el.querySelector(".trend-list"),tab:el.querySelector(".content-panel-body").tabIndex}))')
                assert all(p['bodies']==1 and p['same'] and p['tab']==0 for p in structure)
                row=page.locator('.trend-item').first;title=row.locator('.trend-title');source_id=row.get_attribute('data-native-anchor').removeprefix('news:');title_text=title.inner_text()
                geometry=row.evaluate('el=>{const main=el.querySelector(".trend-main"),a=el.querySelector(".trend-title"),box=el.getBoundingClientRect(),r=a.getBoundingClientRect();return {row:box.width,main:main.getBoundingClientRect().width,title:r.width,right:r.right,edge:box.right}}')
                assert geometry['main']>geometry['row']*.65 and geometry['right']<=geometry['edge']+1
                check(case,'one keyboard-scrollable ContentPanel body and full-width titles',structure=structure,title_geometry=geometry)
                controls=page.locator('.trend-source-controls');chips=controls.locator('.chip')
                ys=chips.evaluate_all('els=>els.map(el=>el.getBoundingClientRect().top)');assert max(ys)-min(ys)<=2
                control_geometry=controls.evaluate('el=>({width:el.clientWidth,scroll:el.scrollWidth,overflow:getComputedStyle(el).overflowX})');assert control_geometry['overflow'] in ('auto','scroll')
                if control_geometry['scroll']>control_geometry['width']:
                    controls.evaluate('el=>el.scrollLeft=el.scrollWidth');assert controls.evaluate('el=>el.scrollLeft')>0;controls.evaluate('el=>el.scrollLeft=0')
                check(case,'source controls remain one horizontal scroll row',geometry=control_geometry)
                if not mobile:
                    row.hover();save=row.get_by_role('button',name='收藏选题：'+title_text,exact=True);expect(save).to_be_visible();save.focus();save.press('Enter')
                    expect(row.get_by_role('button',name='已收藏：'+title_text,exact=True)).to_be_visible()
                    posted=[r for r in requests if r['path']=='/api/ideas' and r['method']=='POST'];assert posted[-1]['body']['source_id']==source_id and posted[-1]['body']['title']==title_text
                    body=panels.first.locator('.content-panel-body');body.focus();body.press('PageDown');assert body.evaluate('el=>el.scrollTop')>0
                    check(case,'desktop hover and keyboard save preserve exact source identity; panel keyboard scroll works')
                else:
                    assert row.locator('.trend-item-actions').evaluate('el=>getComputedStyle(el).display')=='none'
                    check(case,'touch layouts hide hover actions without removing title navigation')
                news();screenshot(page,case,'news')
                scroller='.trends-page' if compact else '.trend-list'
                target=page.locator('.trend-item').nth(8);target.scroll_into_view_if_needed();page.wait_for_timeout(200)
                before=page.locator(scroller).first.evaluate('el=>el.scrollTop');assert before>20
                target_id=target.get_attribute('data-native-anchor').removeprefix('news:');target_title=target.locator('.trend-title').inner_text()
                target.locator('.trend-title').focus();target.locator('.trend-title').press('Enter')
                expect(page.locator('.ew-news-reading')).to_be_visible();expect(page.locator('.ew-news-reading')).to_contain_text(target_title)
                assert '/news/a/'+target_id in parse_qs(urlsplit(page.url).query)['path'][0]
                screenshot(page,case,'reading');assert max(overflow(page).values())<=width+2
                page.go_back();expect(page.locator('.trend-item').first).to_be_attached();page.wait_for_function('()=>document.querySelector(".trends-page")?.getAttribute("aria-busy")==="false"');page.wait_for_timeout(500)
                after=page.locator(scroller).first.evaluate('el=>el.scrollTop');assert abs(after-before)<=6,{'before':before,'after':after}
                check(case,'keyboard title opens original reading and browser return restores list position',before=before,after=after)
                page.locator('.trend-item').nth(8).locator('.trend-title').click();expect(page.locator('.ew-news-reading')).to_be_visible()
                count=len(f['adapter'].requests);page.get_by_role('button',name='做内容',exact=True).click();composer=page.get_by_role('textbox',name='对话输入');expect(composer).to_be_visible()
                page.wait_for_function('()=>new URLSearchParams(location.search).get("path")?.startsWith("/chat/")')
                sid=parse_qs(urlsplit(page.url).query)['path'][0].split('/chat/')[1].split('?')[0]
                helper.wait_history(page,f['origin'],sid);page.wait_for_timeout(300)
                submits=[r for r in requests if r['method']=='POST' and r['path']=='/api/chat/submit']
                assert len(submits)==1 and len(f['adapter'].requests)==count+1
                assert submits[0]['body']['context']['article_id']==target_id and target_title in submits[0]['body']['message']
                assert not any(r['method']=='POST' and r['path'] in ('/api/chat','/api/skill','/api/chat/plan') for r in requests)
                check(case,'one reading make-content click retains existing native execution exactly once with raw title and source identity')
                news();page.get_by_role('button',name='数据源',exact=True).click();dialog=page.get_by_role('dialog',name='数据源',exact=True);expect(dialog).to_be_visible();expect(dialog.get_by_text('添加来源',exact=True)).to_be_visible()
                box=dialog.bounding_box();assert box and box['width']<=width+1 and box['height']<=height+1
                assert dialog.evaluate('el=>el.scrollWidth<=el.clientWidth+2')
                screenshot(page,case,'sources');dialog.get_by_role('button',name='关闭',exact=True).click()
                go('/toolbox');expect(page.locator('.dash-card').first).to_be_visible();expect(page.locator('.dash-trend-title').first).to_be_visible()
                metrics=page.locator('.dash-card:not(.dash-card-wide) .content-panel-body').evaluate_all('els=>els.map(el=>({max:el.scrollHeight-el.clientHeight,overflow:getComputedStyle(el).overflowY,bodies:el.parentElement.querySelectorAll(".content-panel-body").length}))')
                assert all(m['bodies']==1 for m in metrics)
                if compact:assert all(m['max']<=2 or m['overflow']=='visible' for m in metrics)
                assert max(overflow(page).values())<=width+2
                screenshot(page,case,'dashboard');check(case,'long source dialog stays in viewport and dashboard has no duplicate or compact nested scrollers',panels=metrics)
                assert not report['page_errors'],report['page_errors']
            except Exception as error:
                report['failure']={'case':case,'type':type(error).__name__,'message':str(error)};screenshot(page,case,'failure');raise
            finally:context.close()
        browser.close();report['passed']=True
    finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')

if __name__=='__main__':main()
