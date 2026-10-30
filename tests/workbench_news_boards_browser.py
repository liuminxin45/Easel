"""Frozen backend, TEMP data and Windows Edge: read-only entry and bounded boards."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from urllib.parse import urlencode, urlsplit

ROOT=Path(__file__).resolve().parents[1]

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser()
    for field in ('native','backend','out'):parser.add_argument('--'+field,required=True)
    args=parser.parse_args();native=Path(args.native).resolve();backend=Path(args.backend).resolve();out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True)
    sys.path.insert(0,str(ROOT));sys.path.insert(0,str(backend))
    spec=importlib.util.spec_from_file_location('board_fixture',ROOT/'tests/workbench_native_browser.py')
    h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
    from playwright.sync_api import sync_playwright,expect
    manifest=json.loads((native/'native-manifest.json').read_text(encoding='utf8'))
    frozen=json.loads((backend/'workbench-release.json').read_text(encoding='utf8'))
    assert all(sha(backend/name)==digest for name,digest in frozen['files'].items())
    report={'passed':False,'native':{'release':manifest['release'],'manifest_sha256':sha(native/'native-manifest.json')},'backend':{'directory':str(backend),'manifest_sha256':sha(backend/'workbench-release.json')},'checks':[],'real_AI_calls':0,'real_platform_writes':0,'physical_device_tested':False,'screenshots':{}}
    def check(name):report['checks'].append({'check':name,'passed':True});print('PASS',name,flush=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
            with h.isolated(native,b'TEMP unused image') as f:
                f['close_clients']=lambda:[context.close() for context in browser.contexts]
                collection=f['app'].state.collection;store=f['box'].store
                source_ids=list(collection.registry.baseline());disabled=source_ids[-1];selected_source=source_ids[1]
                collection.registry.update({'operation_id':'disable-fixture','action':'toggle','source_id':disabled,'expected_revision':0,'enabled':False})
                (f['root']/'data/collection-config.json').write_text('{"enabled":true}',encoding='utf8')
                for source in source_ids[:-1]:
                    store.ingest({'schema_version':1,'source_job':source,'feed_id':collection.registry.baseline()[source]['feed'],'run_id':'bounded-boards','run_at':'2026-10-30T08:00:00Z','final_text':'TEMP','articles':[{'title':f'TEMP bounded {index+1:02d} '+source,'body':'TEMP stored body.','url':f'https://example.com/{source}/{index}','source_order':index+1,'hot':'真实热度' if index%2 else ''} for index in range(30)]})
                before=collection.status()
                for theme in ('light','dark'):
                    for profile,width,mobile in [('desktop',1440,False),('mobile',390,True)]:
                        context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':1000},is_mobile=mobile,has_touch=mobile,color_scheme=theme)
                        context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
                        page=context.new_page();page.set_default_timeout(20000);errors=[];writes=[]
                        page.on('pageerror',lambda error:errors.append(str(error)))
                        page.on('request',lambda request:writes.append(request.url) if request.method=='POST' and '/api/collection/runs' in request.url else None)
                        page.add_init_script('localStorage.setItem("native-theme",'+json.dumps(theme)+')')
                        page.goto(f['origin']+'/native/?'+urlencode({'path':'/news?sources='+selected_source}),wait_until='domcontentloaded')
                        listing=page.get_by_role('region',name=collection.registry.baseline()[selected_source]['name']+'热点列表',exact=True)
                        expect(listing.locator('.trend-item')).to_have_count(30)
                        expect(page.get_by_role('button',name='刷新',exact=True)).to_be_enabled()
                        assert not writes and collection.status()['active_runs']==before['active_runs']
                        metrics=listing.evaluate('e=>({height:e.clientHeight,total:e.scrollHeight,row:e.querySelector(".trend-item").getBoundingClientRect().height,overflow:getComputedStyle(e).overflowY})')
                        assert abs(metrics['height']-15*metrics['row'])<=2,metrics
                        assert metrics['total']>metrics['height'] and metrics['overflow']=='auto'
                        listing.focus();page.keyboard.press('PageDown');page.wait_for_function('()=>document.querySelector(".trend-list").scrollTop>0')
                        listing.evaluate('e=>e.scrollTop=e.scrollHeight');last=listing.locator('.trend-title').last
                        expect(last).to_be_visible();last.click();expect(page.locator('.native-news-reading')).to_be_visible()
                        stored=page.evaluate('history.state.nativeNavigation.returnTo.position.regions')
                        assert stored['news:'+selected_source]['top']>0
                        page.get_by_role('button',name='返回热点',exact=True).click();expect(listing.locator('.trend-item')).to_have_count(30)
                        page.wait_for_function('expected=>Math.abs(document.querySelector(".trend-list").scrollTop-expected)<2',arg=stored['news:'+selected_source]['top'])
                        page.screenshot(path=str(out/(profile+'-'+theme+'-radar.png')),full_page=True)
                        assert not writes
                        check(profile+' '+theme+': entry does not collect; 15 visible rows, keyboard scroll and detail return preserve all 30 items')
                        def studio(route):
                            response=route.fetch();data=response.json();template=next(iter(data['works']),{'format':'poster','updated_at':'2026-10-30T08:00:00Z'})
                            data['works']=[{**template,'id':'board-'+str(i),'title':'TEMP board item '+str(i),'state':'draft','review_needed':True,'pending':[],'thumbnail':None} for i in range(30)]
                            route.fulfill(response=response,json=data)
                        page.route('**/api/studio/bootstrap',studio)
                        page.goto(f['origin']+'/native/?path=/toolbox',wait_until='domcontentloaded')
                        boards=page.locator('.dash-card-list');expect(boards).to_have_count(4)
                        expect(boards.nth(0).locator('.dash-trend-group')).to_have_count(len(source_ids)-1)
                        for index in range(4):
                            board=boards.nth(index)
                            if index:expect(board.locator('.ew-list-button')).to_have_count(30)
                            size=board.evaluate('e=>({height:e.clientHeight,total:e.scrollHeight,overflow:getComputedStyle(e).overflowY})')
                            assert size['height']<=361 and size['total']>size['height'] and size['overflow']=='auto',size
                            board.focus();page.keyboard.press('PageDown');page.wait_for_function('i=>document.querySelectorAll(".dash-card-list")[i].scrollTop>0',arg=index)
                        page.screenshot(path=str(out/(profile+'-'+theme+'-dashboard.png')),full_page=True)
                        assert not writes and not errors,(writes,errors)
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                        check(profile+' '+theme+': all four dashboard boards cap at 360px and retain their full lists')
                        if profile=='desktop' and theme=='light':
                            page.goto(f['origin']+'/native/?'+urlencode({'path':'/news?sources='+selected_source}))
                            with page.expect_response(lambda response:response.request.method=='POST' and response.url.endswith('/api/collection/runs')) as accepted:
                                page.get_by_role('button',name='刷新',exact=True).click()
                            assert accepted.value.ok,accepted.value.text()
                            page.wait_for_function('()=>document.querySelector(".trend-actions button:last-child").disabled')
                            status=collection.status();run=status['active_runs'][0]
                            assert {task['source_id'] for task in run['tasks']}==set(source_ids)-{disabled}
                            with store.connect() as connection:
                                assert all(row[0]==1 for row in connection.execute('SELECT force FROM collection_tasks WHERE status="queued"'))
                                collection_ids=[row[0] for row in connection.execute('SELECT id FROM collection_tasks')]
                            assert len(writes)==1
                            for task in run['tasks']:
                                with store.connect() as connection:connection.execute('UPDATE collection_tasks SET status="completed",phase="completed",finished_at=? WHERE id=?',('2026-10-30T09:00:00Z',task['id']))
                            page.get_by_role('button',name='刷新',exact=True).wait_for(state='visible',timeout=40000)
                            with page.expect_response(lambda response:response.request.method=='POST' and response.url.endswith('/api/collection/runs')) as accepted:
                                page.get_by_role('button',name='刷新',exact=True).click()
                            assert accepted.value.ok,accepted.value.text()
                            with store.connect() as connection:
                                after=[row[0] for row in connection.execute('SELECT id FROM collection_tasks')]
                            assert len(set(after)-set(collection_ids))==len(source_ids)-1
                            check('Manual refresh immediately queues all enabled sources with force=1 despite selecting only one; a later click starts a fresh collection')
                            with store.connect() as connection:connection.execute('UPDATE collection_tasks SET status="completed",phase="completed" WHERE status="queued"')
                        context.close()
                assert not f['adapter'].requests
                assert all(sha(backend/name)==digest for name,digest in frozen['files'].items())
            browser.close()
        report['passed']=True
    except BaseException as error:
        report['error']=repr(error)
        raise
    finally:
        report['screenshots']={p.name:sha(p) for p in out.glob('*.png')}
        (out/'browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
        print(json.dumps(report,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
