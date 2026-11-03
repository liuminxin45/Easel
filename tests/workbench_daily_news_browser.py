"""Real TEMP HTTP/SQLite acceptance of the immutable daily-news UI.

No HTTP result, application clock, DOM, CSS or model is mocked. Only collection
status/config are fixed TEMP inputs; real ingestion, day query and native pages run.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit

ROOT=Path(__file__).resolve().parents[1]
TZ=dt.timezone(dt.timedelta(hours=8))


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--native',required=True,type=Path)
 parser.add_argument('--backend',required=True,type=Path)
 parser.add_argument('--out',required=True,type=Path)
 args=parser.parse_args();native=args.native.resolve();backend=args.backend.resolve();out=args.out.resolve()
 out.mkdir(parents=True,exist_ok=True)
 for directory,name in [(native,'native-manifest.json'),(backend,'workbench-release.json')]:
  assert all(sha(directory/path)==digest for path,digest in read(directory/name)['files'].items())
 assert all(sha(ROOT/path)==digest for path,digest in read(native/'build-inputs.json')['inputs'].items())
 sys.path.insert(0,str(backend))
 spec=importlib.util.spec_from_file_location('daily_news_fixture',ROOT/'tests/workbench_native_browser.py')
 fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture);fixture.ROOT=backend
 from playwright.sync_api import sync_playwright,expect
 from easel_workbench.runtime.native_api import NativeApi
 from easel_workbench.runtime.desk import SOURCES
 report={'passed':False,'backend':{'release':backend.name,'manifest_sha256':sha(backend/'workbench-release.json')},
  'native':{'release':native.name,'manifest_sha256':sha(native/'native-manifest.json')},
  'checks':[],'screenshots':{},'requests':[],'blocked_requests':[],'page_errors':[],
  'real_AI_calls':0,'production_data_access':False,'physical_mobile_device_tested':False,
  'application_source_injected':False,'DOM_or_CSS_mocked':False,'HTTP_response_mocked':False}

 def mark(name,passed,**extra):
  report['checks'].append({'name':name,'passed':bool(passed),**extra})
  print(('PASS ' if passed else 'FAIL ')+name,flush=True)

 try:
  with sync_playwright() as pw:
   browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
   with fixture.isolated(native,b'TEMP unused image') as f:
    keys=list(SOURCES)[:2];source,empty_source=keys
    labels={source:'TEMP 当日来源',empty_source:'TEMP 空来源'}
    definitions={key:{'id':key,'enabled':True,'label':labels[key],'name':labels[key],'default':True,'type':'python'} for key in keys}
    sources=[{'id':key,'label':labels[key],'enabled':True,'default':True,'type':'python','refresh_seconds':30} for key in keys]
    state={'outcome':'failed'}
    api=NativeApi(f['box']);f['box']._native_api=api
    api._collection_service=SimpleNamespace(definitions=lambda:definitions,
     registry=SimpleNamespace(public=lambda:{'version':1,'sources':sources,'warnings':[]}),
     status=lambda:{'enabled':True,'sources':[{'id':key,'last_task':{'status':state['outcome'],'warnings':['TEMP 36kr-quick 本轮读取不完整；见阶段记录'],'error':'TEMP 本轮采集不完整，已保留实际结果'}} for key in keys]})
    store=f['box'].store;now=dt.datetime.now(TZ);today=now.date().isoformat();yesterday=now-dt.timedelta(days=1)

    def ingest(count,start,when,run):
     return store.ingest({'schema_version':1,'source_job':source,'feed_id':SOURCES[source]['feed'],
      'run_id':run,'run_at':when.isoformat(),'final_text':'TEMP '+run,
      'articles':[{'title':('TEMP 昨日旧条目' if run=='yesterday' else f'TEMP 当天条目 {i:02d}'),
        'body':f'TEMP 准确原文 {i:02d}，本次不执行制作。','url':f'https://example.test/daily/{run}/{i}'} for i in range(start,start+count)]})

    ingest(1,0,yesterday,'yesterday')
    scenarios=[('empty',0,'failed'),('partial-five',5,'partial'),('failed-after-five',5,'failed'),('thirty-five',35,'partial')]
    for scenario,count,outcome in scenarios:
     state['outcome']=outcome
     if scenario=='partial-five':ingest(5,0,now,'five')
     if scenario=='thirty-five':ingest(30,5,now,'thirty-more')
     for label,width,height,touch in [('desktop',1280,900,False),('mobile',390,844,True)]:
      case=label+'-'+scenario
      context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':height},is_mobile=touch,has_touch=touch,service_workers='block')
      context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
      page=context.new_page();page.set_default_timeout(20000)
      page.on('pageerror',lambda error:report['page_errors'].append(str(error)))
      def guard(route):
       request=route.request;url=urlsplit(request.url);row={'case':case,'path':url.path,'method':request.method};report['requests'].append(row)
       if url.hostname not in ('localhost','127.0.0.1') or request.method not in ('GET','HEAD','OPTIONS'):
        report['blocked_requests'].append(row);route.abort();return
       route.continue_()
      context.route('**/*',guard)
      try:
       response=context.request.get(f['origin']+'/api/trends?limit=1000');assert response.status==200
       data=response.json();assert data['day']==today and data['timezone']=='Asia/Shanghai'
       assert len(data['trends'])==(1 if count else 0)
       assert sum(len(g['items']) for g in data['trends'])==count
       assert all(g['platform']!=empty_source and not g['error'] and not g['stale'] and not g['warnings'] for g in data['trends'])
       mark(case+' real daily HTTP returns only today/nonempty sources',True,items=count,latest_task=outcome)
       for name,path,selector,rows in [('dashboard','/toolbox','.dash-page','.dash-trend-item'),('radar','/news','.trends-page','.trend-item')]:
        with page.expect_response(lambda response:urlsplit(response.url).path=='/api/trends') as read_response:
         result=page.goto(f['origin']+'/native/?'+urlencode({'path':path}),wait_until='domcontentloaded')
        # Wait for the actual JSON body. Playwright's finished() creates a
        # competing target-close task which can leak noisy teardown warnings.
        assert read_response.value.json()['day']==today
        page.evaluate('async()=>{for(let n=0;n<4;n++)await new Promise(requestAnimationFrame)}')
        assert result.status==200;expect(page.locator(selector)).to_be_visible()
        expect(page.locator(rows)).to_have_count(min(3,count) if name=='dashboard' else count)
        expect(page.get_by_text('TEMP 昨日旧条目',exact=False)).to_have_count(0)
        expect(page.locator('.dash-trend-plat' if name=='dashboard' else '.trend-col-head').filter(has_text='TEMP 空来源')).to_have_count(0)
        for forbidden in ['本轮读取不完整','本轮采集不完整','暂用上次结果','暂无热点','采集成功，暂无热点','该数据源暂时不可用','过期缓存','缓存已过期']:
         expect(page.locator(selector).get_by_text(forbidden,exact=False)).to_have_count(0)
        if name=='dashboard':
         panel=page.locator('.dash-card').filter(has=page.locator('.dash-card-head',has_text='今日热点'))
         expect(panel).to_be_visible()
         if not count:expect(panel.locator('.dash-trend-group,.dash-empty')).to_have_count(0)
        else:
         expect(page.locator('.trend-grid')).to_have_count(1)
         expect(page.locator('.trend-col')).to_have_count(1 if count else 0)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),'Horizontal overflow'
        image=out/(case+'-'+name+'.png');page.screenshot(path=str(image));report['screenshots'][image.name]=sha(image)
        mark(case+' '+name+' exact visible rows and quiet empty panel',True,rows=min(3,count) if name=='dashboard' else count)
        if name=='radar' and scenario=='partial-five':
         page.locator('.trend-title').first.click()
         expect(page.locator('.ew-news-reading')).to_be_visible()
         expect(page.get_by_text('TEMP 准确原文',exact=False)).to_be_visible()
         mark(case+' actual article link opens original record without making content',True)
      except Exception as error:
       mark(case+' scenario completed',False,error=repr(error))
       page.screenshot(path=str(out/(case+'-failure.png')))
      finally:context.close()
    report['real_AI_calls']=len(f['adapter'].requests)
   browser.close()
  report['runtime_modules']={name:{'file':str(Path(module.__file__).resolve()),'sha256':sha(module.__file__)} for name,module in list(sys.modules.items()) if (name=='easel' or name.startswith('easel.') or name=='easel_workbench' or name.startswith('easel_workbench.')) and getattr(module,'__file__',None)}
  report['module_roots_valid']=all(Path(row['file']).is_relative_to(backend) for row in report['runtime_modules'].values())
  report['passed']=bool(report['checks']) and all(row['passed'] for row in report['checks']) and report['module_roots_valid'] and not report['page_errors'] and not report['blocked_requests'] and not report['real_AI_calls']
 finally:
  shutil.copy2(__file__,out/'harness.py');(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
 print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'screenshots':len(report['screenshots'])}))
 return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
