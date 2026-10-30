"""Actual Windows Edge, TEMP HTTPS data, generic source transports and visual parity."""
import argparse
from contextlib import contextmanager
from functools import partial
import http.server
import importlib.util
import json
from pathlib import Path
import sys
import threading
import uuid
from urllib.parse import urlencode,urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('native_browser',Path(__file__).with_name('workbench_native_browser.py'))
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)


@contextmanager
def reference_server(directory):
    class Handler(http.server.SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
    server=http.server.ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(directory)))
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:yield 'http://127.0.0.1:'+str(server.server_port)
    finally:server.shutdown();server.server_close();thread.join()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--native',required=True);parser.add_argument('--out',required=True);parser.add_argument('--backend');parser.add_argument('--functional-only',action='store_true');args=parser.parse_args()
    if args.backend:
        backend=Path(args.backend).resolve();sys.path.insert(0,str(backend))
        backend_manifest=json.loads((backend/'workbench-release.json').read_text(encoding='utf-8'))
        assert all(h.sha(backend/name)==digest for name,digest in backend_manifest['files'].items())
    from playwright.sync_api import sync_playwright,expect
    from easel_workbench.runtime.collection_worker import CollectionWorker
    from easel_workbench.runtime.source_registry import SourceRegistry
    native=Path(args.native).resolve();out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
    report={'passed':False,'checks':[],'real_model_calls':0,'real_platform_writes':0,'physical_mobile_device_tested':False,'screenshots':{}}
    try:
        with sync_playwright() as pw,reference_server(ROOT/'web/frontend/dist') as reference:
            browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
            blank=browser.new_page();blank.set_content('TEMP');image=blank.screenshot();blank.close()
            with h.isolated(native,image) as f:
                f['close_clients']=lambda:[c.close() for c in browser.contexts]
                collection=f['app'].state.collection;registry=collection.registry;store=f['box'].store
                (f['root']/'data/collection-config.json').write_text('{"enabled":true}',encoding='utf-8')
                groups=[]
                for source,meta in registry.baseline().items():
                    if meta.get('kind')=='periodical':continue
                    articles=[{'title':f'TEMP 第 {i+1} 条 · '+meta['name'],'body':'TEMP 来源正文，验证站内阅读。','url':'https://example.com/'+source+'/'+str(i),'hot':'来源提供的热度','source_order':i+1,'fetched_at':'2026-10-30T08:00:00Z'} for i in range(5)]
                    store.ingest({'schema_version':1,'source_job':source,'feed_id':meta['feed'],'run_id':'visual-fixture','run_at':'2026-10-30T08:00:00Z','final_text':'TEMP '+source,'articles':articles})
                    listing=store.article_day(source=source)
                    groups.append({'platform':source,'label':meta['name'],'ok':True,'fetched_at':'2026-10-30T08:00:00Z','stale':False,'items':[{'id':row['id'],'title':row['title'],'url':row['url'],'hot':row.get('hot') or ''} for row in listing['items']]})
                sources=[{'id':key,'label':meta['name'],'type':'python','default':not meta.get('kind')=='periodical','refresh_seconds':300} for key,meta in registry.baseline().items()]
                for theme in (() if args.functional_only else ('light','dark')):
                    for profile,width,mobile in [('windows',1280,False),('mobile-simulated',390,True)]:
                        context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':900},is_mobile=mobile,has_touch=mobile,color_scheme=theme)
                        context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
                        page=context.new_page();page.set_default_timeout(20000);errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                        page.add_init_script("localStorage.setItem('native-theme',"+json.dumps(theme)+")")
                        selected=','.join(g['platform'] for g in groups)
                        page.goto(f['origin']+'/native/?'+urlencode({'path':'/news?sources='+selected}),wait_until='domcontentloaded')
                        expect(page.locator('.trend-col')).to_have_count(len(groups))
                        expect(page.locator('.trend-item')).to_have_count(sum(len(g['items']) for g in groups))
                        page.evaluate('theme=>{document.documentElement.dataset.theme=theme;document.documentElement.dataset.nativeTheme=theme}',theme)
                        page.mouse.move(0,0)
                        page.screenshot(path=str(out/(profile+'-'+theme+'-native.png')),full_page=True)
                        bounds=page.locator('.trends-page').bounding_box();bounds['height']=min(bounds['height'],900-bounds['y']);page.screenshot(path=str(out/(profile+'-'+theme+'-native-radar.png')),clip=bounds)
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                        if mobile:
                            assert page.locator('.trend-use').first.evaluate('e=>getComputedStyle(e).opacity')=='1'
                        chip=page.locator('.trend-platforms .chip').first;chip.click();expect(page.locator('.trend-col')).to_have_count(len(groups)-1);chip.click();expect(page.locator('.trend-col')).to_have_count(len(groups))
                        title=page.locator('.trend-title').filter(has_text='TEMP 第 1 条').last;title.scroll_into_view_if_needed()
                        title.click()
                        before_scroll=page.evaluate('history.state.nativeNavigation.returnTo.position')
                        expect(page.locator('.native-news-reading')).to_be_visible();expect(page.locator('.ew-reading')).to_contain_text('TEMP 来源正文')
                        page.get_by_role('button',name='返回热点',exact=True).click();expect(page.locator('.trend-col')).to_have_count(len(groups));expect(page.locator('.trend-platforms .chip.active')).to_have_count(len(groups))
                        try:page.wait_for_function('previous=>{const viewport=document.querySelector(".ew-page"),anchor=previous.anchor&&[...viewport.querySelectorAll("[data-native-anchor]")].find(e=>e.dataset.nativeAnchor===previous.anchor.id);const requested=anchor?viewport.scrollTop+anchor.getBoundingClientRect().top-viewport.getBoundingClientRect().top-previous.anchor.offset:previous.top;return Math.abs(viewport.scrollTop-Math.max(0,Math.min(viewport.scrollHeight-viewport.clientHeight,requested)))<4}',arg=before_scroll)
                        except Exception:
                            report['scroll_failure']={'before':before_scroll,'after':page.locator('.ew-page').evaluate('e=>e.scrollTop'),'state':page.evaluate('history.state'),'entries':page.evaluate('sessionStorage.getItem("native:navigation:v1")')}
                            raise
                        if theme=='light' and not mobile:
                            for _ in groups:page.locator('.trend-platforms .chip.active').first.click()
                            expect(page.locator('.trend-col')).to_have_count(0);expect(page.get_by_text('请选择上方的数据源查看热点。',exact=True)).to_be_visible()
                            for group in groups:page.locator('.trend-platforms .chip').filter(has_text=group['label']).click()
                            expect(page.locator('.trend-col')).to_have_count(len(groups))
                        page.get_by_role('button',name='数据源',exact=True).click();expect(page.get_by_role('dialog',name='数据源')).to_be_visible()
                        page.get_by_role('dialog',name='数据源').screenshot(path=str(out/(profile+'-'+theme+'-manager.png')))
                        page.keyboard.press('Escape');expect(page.get_by_role('dialog',name='数据源')).not_to_be_visible()
                        assert not errors,errors
                        report['checks'].append(profile+' '+theme+': layout, multi-select, internal reading, return state, source dialog, no overflow')
                        context.close()

                        refcontext=browser.new_context(viewport={'width':width,'height':900},is_mobile=mobile,has_touch=mobile,color_scheme=theme)
                        refpage=refcontext.new_page();refpage.add_init_script("localStorage.setItem('easel_onboarding_seen','1')")
                        def route(route):
                            path=urlsplit(route.request.url).path
                            value={'sources':sources,'warnings':[],'version':1} if path.endswith('/trends/sources') else {'trends':groups,'warnings':[],'updated':0,'version':1} if path.endswith('/trends') else {'gateway':True,'personas':[],'runtime':'codex'} if path.endswith('/status') else {'modelConfigured':True} if path.endswith('/settings/bootstrap') else []
                            route.fulfill(json=value)
                        refpage.route('**/api/**',route);refpage.goto(reference,wait_until='domcontentloaded')
                        refpage.get_by_role('button',name='热点雷达 →',exact=True).click()
                        expect(refpage.locator('.trend-col')).to_have_count(len(groups))
                        refpage.evaluate('theme=>document.documentElement.dataset.theme=theme',theme)
                        refpage.mouse.move(0,0)
                        bounds=refpage.locator('.trends-page').bounding_box();bounds['height']=min(bounds['height'],900-bounds['y']);refpage.screenshot(path=str(out/(profile+'-'+theme+'-reference-radar.png')),clip=bounds)
                        refcontext.close()
                # Exercise the actual private HTTP authorization and manager form.
                context=browser.new_context(ignore_https_errors=True,viewport={'width':1280,'height':900})
                context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
                page=context.new_page();page.set_default_timeout(20000)
                csrf=page.request.get(f['origin']+'/api/config').json()['csrf']
                headers={'Origin':f['origin'],'X-CSRF-Token':csrf}
                rejected=page.request.post(f['origin']+'/api/collection/sources',data={'operation_id':'no-csrf','action':'add','label':'denied','type':'rss','url':'https://example.com/rss'})
                assert rejected.status==403
                for source,row in registry.entries().items():
                    response=page.request.post(f['origin']+'/api/collection/sources',headers=headers,data={'operation_id':uuid.uuid4().hex,'action':'toggle','source_id':source,'expected_revision':row['revision'],'enabled':False})
                    assert response.ok,response.text()
                (ROOT/'web/frontend/dist/news-test-rss.xml').write_text('<rss version="2.0"><channel><title>TEMP</title><item><guid>rss-ui</guid><title>TEMP RSS UI headline</title><link>https://example.com/rss-ui</link></item></channel></rss>',encoding='utf-8')
                page.goto(f['origin']+'/native/?'+urlencode({'path':'/news'}),wait_until='domcontentloaded')
                page.get_by_role('button',name='数据源',exact=True).click()
                dialog=page.get_by_role('dialog',name='数据源');expect(dialog).to_be_visible()
                dialog.get_by_label('名称',exact=True).fill('TEMP RSS UI')
                dialog.get_by_label('订阅地址',exact=True).fill(reference+'/news-test-rss.xml')
                with page.expect_response(lambda response:response.request.method=='POST' and response.url.endswith('/api/collection/sources')) as addition:
                    dialog.get_by_role('button',name='添加来源',exact=True).click()
                response=addition.value
                assert response.ok,response.text()
                try:expect(dialog.locator('.trend-manager-row').filter(has_text='TEMP RSS UI')).to_have_count(1,timeout=20000)
                except BaseException:
                    report['addition_debug']={'response':response.json(),'body':page.locator('body').inner_text()}
                    raise
                identifier=next(key for key,row in registry.entries().items() if row['label']=='TEMP RSS UI')
                page.keyboard.press('Escape');expect(page.locator('.trend-platforms .chip.active')).to_have_count(1)
                page.get_by_role('button',name='刷新',exact=True).evaluate('button=>{button.click();button.click()}')
                expect(page.get_by_text('排队中',exact=False).first).to_be_visible()
                task=collection.claim('TEMP-browser-owner')
                assert task and task['source_id']==identifier
                with store.connect() as connection:assert connection.execute('SELECT count(*) FROM collection_tasks WHERE source_id=?',(identifier,)).fetchone()[0]==1
                worker=CollectionWorker(collection)
                try:result=worker.execute(task)
                finally:worker.close()
                assert result['status']=='completed' and result['inserted']==1,result
                collection.finish(task['id'],task['lease_token'],result)
                headline=page.locator('.trend-title').filter(has_text='TEMP RSS UI headline');expect(headline).to_be_visible(timeout=30000)
                headline.click();expect(page.locator('.ew-reading')).to_contain_text('来源仅提供标题／链接')
                article=store.article_day(source=identifier)['items'][0]
                page.get_by_role('button',name='返回热点',exact=True).click()
                page.get_by_role('button',name='数据源',exact=True).click();dialog=page.get_by_role('dialog',name='数据源')
                row=dialog.locator('.trend-manager-row').filter(has_text='TEMP RSS UI')
                row.get_by_role('button',name='停用TEMP RSS UI',exact=True).click();expect(row.get_by_role('button',name='启用TEMP RSS UI',exact=True)).to_be_visible()
                row.get_by_role('button',name='启用TEMP RSS UI',exact=True).click();expect(row.get_by_role('button',name='停用TEMP RSS UI',exact=True)).to_be_visible()
                row.get_by_role('button',name='删除TEMP RSS UI',exact=True).click();row.get_by_role('button',name='确认删除',exact=True).click()
                expect(dialog.locator('.trend-manager-row').filter(has_text='TEMP RSS UI')).to_have_count(0)
                assert store.detail(article['id'])['body']==article['body']
                page.keyboard.press('Escape')
                report['checks'].append('Actual private API and UI: CSRF rejection, RSS add, rapid refresh, real local RSS transport, durable queue, title-only reading, toggle/delete retaining history')
                # A server commit followed by a dropped response retains the exact operation.
                page.get_by_role('button',name='数据源',exact=True).click();dialog=page.get_by_role('dialog',name='数据源')
                dialog.get_by_label('名称',exact=True).fill('TEMP lost acknowledgement')
                dialog.get_by_label('订阅地址',exact=True).fill(reference+'/news-test-rss.xml')
                dropped=[]
                def hold_receipt(route):route.abort()
                def lose_response(route):
                    if route.request.method!='POST':return route.continue_()
                    response=route.fetch();assert response.ok,response.text();dropped.append(route.request.post_data_json);route.abort()
                page.route('**/api/collection/sources',lose_response)
                page.route('**/api/operations/*',hold_receipt)
                dialog.get_by_role('button',name='添加来源',exact=True).click()
                page.wait_for_function('()=>JSON.parse(localStorage.getItem("toolbox:draft:native:pending:collection:sources")||"{}").operation?.uncertain===true')
                page.unroute('**/api/collection/sources',lose_response)
                assert len(dropped)==1
                operation_id=dropped[0]['operation_id']
                receipt=page.request.get(f['origin']+'/api/operations/'+operation_id+'?'+urlencode({'path':'/api/collection/sources'})).json()
                assert receipt['state']=='received' and receipt['result']['id']!=operation_id
                page.unroute('**/api/operations/*',hold_receipt)
                manual=dialog.get_by_role('button',name='核对原操作',exact=True)
                if manual.count():manual.click()
                page.wait_for_function('()=>!JSON.parse(localStorage.getItem("toolbox:draft:native:pending:collection:sources")||"{}").operation')
                # Receipt recovery must reread the manager; allow the bounded transport deadline.
                try:expect(dialog.locator('.trend-manager-row').filter(has_text='TEMP lost acknowledgement')).to_have_count(1,timeout=20000)
                except BaseException:
                    report['lost_debug']={'receipt':receipt,'body':page.locator('body').inner_text(),'pending':page.evaluate('localStorage.getItem("toolbox:draft:native:pending:collection:sources")')}
                    page.screenshot(path=str(out/'lost-response.png'),full_page=True)
                    raise
                assert sum(row['label']=='TEMP lost acknowledgement' for row in registry.entries().values())==1
                assert len(dropped)==1
                report['checks'].append('Lost response: read-only receipt recovery retains the original operation and creates no duplicate source')
                assert not f['adapter'].requests,'reading and toggling must not call models'
                if args.backend:
                    modules={name:str(Path(module.__file__).resolve()) for name,module in sys.modules.items() if (name=='easel' or name.startswith('easel.') or name=='easel_workbench' or name.startswith('easel_workbench.')) and getattr(module,'__file__',None)}
                    assert modules and all(Path(path).is_relative_to(backend) for path in modules.values()),modules
                    assert all(h.sha(backend/name)==digest for name,digest in backend_manifest['files'].items())
                    report.update(backend=backend.name,backend_modules_verified=len(modules))
                report['passed']=True
            browser.close()
    except BaseException as error:
        report['error']=repr(error)
        if 'page' in locals():
            try:report['page']={'url':page.url,'body':page.locator('body').inner_text()};page.screenshot(path=str(out/'failure.png'),full_page=True)
            except Exception:pass
        raise
    finally:
        report['screenshots']={p.name:h.sha(p) for p in out.glob('*.png')}
        (out/'news-browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
