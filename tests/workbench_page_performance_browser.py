"""Frozen TEMP browser proof of slow startup telemetry; no production writes."""
from pathlib import Path
from unittest.mock import patch
import argparse,importlib.util,json,sys,tempfile,time
from urllib.parse import urlencode,urlsplit

ROOT=Path(__file__).resolve().parents[1]


def main():
    parser=argparse.ArgumentParser()
    for key in ('backend','native','out'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();backend=args.backend.resolve();native=args.native.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('perf_news_fixture',ROOT/'tests/workbench_news_creation_browser.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    binding=module.frozen(backend,'workbench-release.json');native_binding=module.frozen(native,'native-manifest.json')
    helper,application,native_app=module.infrastructure(backend,native)
    from easel_workbench.diagnostics import page_performance
    from playwright.sync_api import sync_playwright,expect
    report={'passed':False,'backend':binding,'native':native_binding,'checks':[],'real_model_calls':0,'physical_device_tested':False,'production_data_access':False}
    try:
        with tempfile.TemporaryDirectory(prefix='easel-page-perf-') as temporary:
          sink=page_performance.Sink(Path(temporary)/'logs')
          try:
            with patch.object(page_performance,'_sink',sink),patch.object(application,'create_app',native_app),sync_playwright() as pw:
              browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
              with helper.isolated(native,module.IMAGE) as f:
                context=browser.new_context(ignore_https_errors=True,service_workers='block');page=context.new_page();page.set_default_timeout(30000)
                page.route('**/*',lambda route:route.continue_() if urlsplit(route.request.url).hostname in ('localhost','127.0.0.1') else route.abort())
                page.goto(f['origin']+'/native/login',wait_until='domcontentloaded')
                page.wait_for_function("() => {try{return JSON.parse(sessionStorage.getItem('workbench:page-performance:v1')||'null')?.rows?.length>0}catch{return false}}",timeout=30000)
                context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}]);requests=[]
                page.on('request',lambda req:requests.append((req.method,urlsplit(req.url).path)))
                page.goto(f['origin']+'/native/',wait_until='domcontentloaded');deadline=time.monotonic()+25
                while not any(method=='POST' and path=='/api/diagnostics/page-performance' for method,path in requests) and time.monotonic()<deadline:page.wait_for_timeout(100)
                assert any(method=='POST' and path=='/api/diagnostics/page-performance' for method,path in requests),'pre-login observation was not sent after authentication'
                assert not f['adapter'].requests;report['checks'].append({'layout':'login','pre_auth_buffer_sent_after_login':True,'real_model_calls':0});context.close()
              for label,width,mobile in [('desktop',1280,False),('mobile',390,True)]:
                sink.queue.join();before=sum(len(json.loads(line)['events']) for path in (Path(temporary)/'logs').glob('*.jsonl') for line in path.read_text(encoding='utf8').splitlines())
                with helper.isolated(native,module.IMAGE) as f:
                  context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':844},is_mobile=mobile,has_touch=mobile,service_workers='block')
                  context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}]);page=context.new_page();page.set_default_timeout(30000);delayed=set();requests=[]
                  def route_handler(route):
                    url=urlsplit(route.request.url)
                    assert url.hostname in ('localhost','127.0.0.1'),'external request prohibited'
                    for component in ('host','ui'):
                        if '/assets/'+component+'-' in url.path and url.path.endswith('.js') and component not in delayed:
                            delayed.add(component);time.sleep(3.3)
                    route.continue_()
                  page.route('**/*',route_handler)
                  page.on('request',lambda req:requests.append((req.method,urlsplit(req.url).path)))
                  response=page.goto(f['origin']+'/native/?'+urlencode({'path':'/toolbox'}),wait_until='domcontentloaded');document_trace=response.headers.get('x-desk-trace','')
                  expect(page.locator('.native-host')).to_be_visible(timeout=30000)
                  page.wait_for_function("() => performance.now() > 4000 && document.querySelector('.native-host')",timeout=30000)
                  deadline=time.monotonic()+20
                  while not any(method=='POST' and path=='/api/diagnostics/page-performance' for method,path in requests) and time.monotonic()<deadline:page.wait_for_timeout(100)
                  assert delayed=={'host','ui'} and any(method=='POST' and path=='/api/diagnostics/page-performance' for method,path in requests),'startup telemetry did not reach server'
                  page.wait_for_timeout(1000);page.evaluate("window.dispatchEvent(new Event('pagehide'))");page.wait_for_timeout(1000)
                  sink.queue.join();files=list((Path(temporary)/'logs').glob('*.jsonl'));assert files
                  events=[item for path in sorted(files) for line in path.read_text(encoding='utf8').splitlines() for item in json.loads(line)['events']][before:]
                  slow=[event for event in events if event.get('kind')=='slow' and event.get('metric')=='boot' and event.get('duration_ms',0)>=3000]
                  loading=[event for event in events if event.get('kind')=='slow' and event.get('metric')=='loading' and event.get('duration_ms',0)>=3000]
                  assert slow and all('?' not in json.dumps(event) for event in slow)
                  assert len(document_trace)==16 and slow[-1].get('trace')==document_trace,'document trace did not match server response'
                  assert loading,'visible loading-card wait was not recorded'
                  assert not f['adapter'].requests
                  overhead=page.evaluate("""() => {const times=[];for(let i=0;i<200;i++){const t=performance.now();window.dispatchEvent(new CustomEvent('workbench:performance-request',{detail:{path:'/api/chat/private?secret=x',duration:1200,status:503,trace:'aaaaaaaaaaaaaaaa'}}));times.push(performance.now()-t)}times.sort((a,b)=>a-b);const raw=sessionStorage.getItem('workbench:page-performance:v1')||'';return {p95:times[189],bytes:new TextEncoder().encode(raw).length,count:JSON.parse(raw).rows.length,secret:raw.includes('secret=x')}}""")
                  assert overhead['p95']<5 and overhead['bytes']<=65536 and overhead['count']<=100 and not overhead['secret'],overhead
                  report['checks'].append({'layout':label,'slow_boot_recorded':True,'duration_ms':slow[-1]['duration_ms'],'loading_ms':loading[-1]['duration_ms'],'event_p95_ms':overhead['p95'],'queue_bytes':overhead['bytes'],'real_model_calls':0})
                  context.close()
              browser.close()
          finally:sink.close()
        report['passed']=True
    finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps(report,ensure_ascii=False));return 0


if __name__=='__main__':raise SystemExit(main())
