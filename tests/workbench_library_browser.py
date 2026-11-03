"""Frozen real HTTPS/file/index acceptance; no production data or model calls."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,os,sys,time
from urllib.parse import urlencode,urlsplit,parse_qs

ROOT=Path(__file__).resolve().parents[1]
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--backend',type=Path,required=True);parser.add_argument('--native',type=Path,required=True);parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args();backend=args.backend.resolve();native=args.native.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    for directory,name in ((backend,'workbench-release.json'),(native,'native-manifest.json')):
        manifest=json.loads((directory/name).read_text(encoding='utf-8'))
        assert all(sha(directory/path)==digest for path,digest in manifest['files'].items())
    sys.path.insert(0,str(backend))
    spec=importlib.util.spec_from_file_location('library_fixture',ROOT/'tests/workbench_native_browser.py');fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture);fixture.ROOT=backend
    from easel_workbench.features.works.library_index import LibraryIndex
    from PIL import Image
    from playwright.sync_api import sync_playwright,expect
    report={'passed':False,'backend':{'release':backend.name,'manifest_sha256':sha(backend/'workbench-release.json')},'native':{'release':native.name,'manifest_sha256':sha(native/'native-manifest.json')},'checks':[],'screenshots':{},'page_errors':[],'requests':[],'real_model_calls':0,'production_data_access':False,'physical_device_tested':False}
    def mark(case,name,**details):report['checks'].append({'case':case,'name':name,'passed':True,**details});print('PASS '+case+' '+name,flush=True)
    try:
        with sync_playwright() as pw,fixture.isolated(native,b'TEMP unused model image') as f:
            api=f['box']._native_api;api.library.close()
            root=f['root'];outputs=root/'outputs';outputs.mkdir(exist_ok=True)
            for i in range(1005):
                folder=outputs/f'project-{i:04d}';folder.mkdir();file=folder/'notes.md';file.write_text('TEMP source '+str(i),encoding='utf-8');os.utime(file,(1700000000+i,1700000000+i))
            preview=outputs/'preview-project';preview.mkdir();text=preview/'notes.md';text.write_text('# ONLY_ON_DEMAND\n\n'+('TEMP exact original. '*25000),encoding='utf-8')
            Image.new('RGB',(2200,1400),'#267b88').save(preview/'cover.png');(preview/'video.mp4').write_bytes(b'TEMP no metadata preload')
            (preview/'.easel.json').write_text(json.dumps({'title':'TEMP 预览项目','cover':'cover.png','kind':'poster'},ensure_ascii=False),encoding='utf-8')
            api.library=LibraryIndex(root,api._build_library,api._library_revision);api.library.rebuild()
            browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
            for case,width,height,mobile,theme in [('desktop-light',1280,900,False,'light'),('mobile-dark',390,844,True,'dark'),('mobile-small-light',360,780,True,'light'),('landscape-light',844,390,True,'light')]:
                context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':height},is_mobile=mobile,has_touch=mobile,service_workers='block')
                context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}]);context.add_init_script('localStorage.setItem("native:theme",'+json.dumps(theme)+');')
                page=context.new_page();page.set_default_timeout(20000);page.on('pageerror',lambda error:report['page_errors'].append(str(error)))
                requests=[]
                def guard(route):
                    req=route.request;path=urlsplit(req.url).path;requests.append(path);report['requests'].append({'case':case,'path':path,'method':req.method})
                    assert urlsplit(req.url).hostname in ('localhost','127.0.0.1')
                    if req.method not in ('GET','HEAD','OPTIONS') and path not in ('/api/usage/events','/api/diagnostics/client-operation'):route.abort();return
                    route.continue_()
                page.route('**/*',guard)
                try:
                    with page.expect_response(lambda r:urlsplit(r.url).path=='/api/library/items') as first:
                        page.goto(f['origin']+'/native/?'+urlencode({'path':'/works'}),wait_until='domcontentloaded')
                    response=first.value;body=response.json();assert response.status==200 and len(body['items'])==50 and len(response.body())<100000
                    expect(page.locator('.gcard')).to_have_count(50);expect(page.get_by_text('正在打开',exact=False)).to_have_count(0)
                    assert '/api/outputs' not in requests and not any(p.startswith('/api/output/') for p in requests)
                    assert not any(p.endswith('.mp4') for p in requests)
                    mark(case,'first page is 50 summaries without full tree, bodies or video metadata',bytes=len(response.body()))
                    page.get_by_role('button',name='加载更多',exact=True).click();expect(page.locator('.gcard')).to_have_count(100)
                    assert page.locator('.gcard-name').all_text_contents().__len__()==100
                    mark(case,'next cursor appends one page')
                    search=page.get_by_role('searchbox',name='搜索内容');search.fill('TEMP 预览项目');expect(page.locator('.gcard')).to_have_count(1)
                    page.locator('.gcard').click();expect(page.locator('.gcard-name').filter(has_text='notes.md')).to_be_visible()
                    assert not any(p.startswith('/api/output/') for p in requests)
                    page.locator('.gcard').filter(has=page.locator('.gcard-name',has_text='notes.md')).click();expect(page.get_by_text('ONLY_ON_DEMAND',exact=False).first).to_be_visible()
                    assert any(p.endswith('/preview-project/notes.md') and p.startswith('/api/output/') for p in requests)
                    mark(case,'search and directory open load only that level; file body is on demand')
                    page.get_by_role('button',name='关闭预览',exact=True).click()
                    page.screenshot(path=str(out/(case+'-project.png')));report['screenshots'][case+'-project.png']=sha(out/(case+'-project.png'))
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    with page.expect_response(lambda r:urlsplit(r.url).path=='/api/library/items') as home_read:
                        page.goto(f['origin']+'/native/?'+urlencode({'path':'/toolbox'}),wait_until='domcontentloaded')
                    home=home_read.value.json();assert home['total']==1006 and len(home['items'])==50
                    expect(page.locator('.dash-output')).to_have_count(5)
                    expect(page.get_by_text('正在打开',exact=False)).to_have_count(0)
                    assert '/api/outputs' not in requests
                    mark(case,'dashboard reuses bounded summary and true total without full tree')
                    # Direct links resolve a stable path without requesting all roots.
                    page.goto(f['origin']+'/native/?'+urlencode({'path':'/works?path=preview-project/notes.md'}),wait_until='domcontentloaded')
                    expect(page.get_by_text('ONLY_ON_DEMAND',exact=False).first).to_be_visible()
                    assert '/api/outputs' not in requests
                    mark(case,'old direct file path resolves without full tree')
                finally:context.close()
            assert not f['adapter'].requests
            browser.close()
        assert not report['page_errors'];report['passed']=True
    finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks'])}))


if __name__=='__main__':main()
