"""Frozen native pair + TEMP HTTPS + actual Edge; no model/platform execution."""
from __future__ import annotations
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from urllib.parse import urlencode, urlsplit, parse_qs

ROOT=Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def seed(fixture):
    from easel_workbench.features.distribution.service import DistributionService
    box=fixture['box'];studio=box.studio;service=DistributionService(box)
    files=fixture['root']/'data'/'lazy-acceptance';files.mkdir(parents=True)
    with box.store.connect() as c:
        for index in range(56):
            wid=f'work-{index:03d}'
            c.execute('INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)',(wid,None,f'TEMP Work {index:03d}','TEMP retained material','2026-11-01','2026-11-03'))
        for jid,kind,title in [('version-old','create','TEMP exact older version'),('version-new','change','TEMP exact latest version')]:
            c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,files,scope,signature,status,created_at,finished_at,reply) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (jid,'work-055',kind,'TEMP frozen input','[]','[]',jid,'completed','2026-11-03','2026-11-03','TEMP response'))
            path=files/(jid+'.txt');path.write_text(title+'\n\nTEMP exact body '+jid,encoding='utf-8')
            c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)',('artifact-'+jid,jid,'标题与配文.txt',str(path),'text/plain'))
        service._put(c,'connections',{'id':'account-lazy','platform':'wechat','account':'TEMP account','label':'TEMP account','enabled':True,'revision':1})
        service._put(c,'deliveries',{'id':'delivery-lazy','work_id':'work-055','revision_id':'revision-lazy','approval_id':'approval-lazy','batch_id':'batch-lazy',
            'connection_id':'account-lazy','account':'TEMP account','platform':'wechat','status':'unknown','error':None,'result':{'reason':'TEMP exact full receipt','original':'TEMP_FULL_DELIVERY_BODY'}})
        studio._put(c,'publications',{'id':'publication-lazy','work_id':'work-055','version_id':'version-old','title':'TEMP publication ledger','account':'TEMP account',
            'channel_id':'wechat','status':'published','url':'https://example.invalid/lazy','published_at':'2026-11-03T10:00:00+08:00','body':'TEMP_FULL_PUBLICATION_BODY','source_snapshot':{'input':'TEMP original source'}},True)


def main():
    parser=argparse.ArgumentParser()
    for key in ('native','backend','out'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();native=args.native.resolve();backend=args.backend.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    native_manifest=json.loads((native/'native-manifest.json').read_bytes());backend_manifest=json.loads((backend/'workbench-release.json').read_bytes())
    for directory,manifest in [(native,native_manifest),(backend,backend_manifest)]:
        assert all(sha(directory/name)==digest for name,digest in manifest['files'].items()),str(directory)+' failed frozen byte verification'
    sys.path.insert(0,str(backend))
    spec=importlib.util.spec_from_file_location('private_lazy_fixture',ROOT/'tests/workbench_native_browser.py');helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper);helper.ROOT=backend
    from playwright.sync_api import sync_playwright,expect
    report={'passed':False,'native':{'directory':str(native),'manifest_sha256':sha(native/'native-manifest.json')},'backend':{'directory':str(backend),'manifest_sha256':sha(backend/'workbench-release.json')},
        'harness_sha256':sha(__file__),'fixture_sha256':sha(ROOT/'tests/workbench_native_browser.py'),'checks':[],'screenshots':{},'requests':{},'real_model_calls':0,'platform_writes':0,'physical_device_tested':False}
    def check(profile,name,value=True):
        report['checks'].append({'profile':profile,'name':name,'passed':bool(value)})
        assert value,name
        print('PASS',profile,name,flush=True)
    try:
        with sync_playwright() as playwright:
            browser=playwright.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
            for label,width in [('mobile-390',390),('desktop-1280',1280)]:
                with helper.isolated(native,b'TEMP unused image; no model is allowed') as f:
                    seed(f)
                    context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':900},is_mobile=width<600,has_touch=width<600,color_scheme='light')
                    context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
                    page=context.new_page();page.set_default_timeout(25000);requests=[];errors=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    def requested(request):
                        target=urlsplit(request.url)
                        if target.path.startswith('/api/'):requests.append({'method':request.method,'path':target.path,'query':parse_qs(target.query)})
                    page.on('request',requested)
                    def count(path):return sum(row['method']=='GET' and row['path']==path for row in requests)
                    def disclosure(title):return page.locator('details').filter(has=page.locator('summary').filter(has_text=title)).first
                    def toggle(details):details.locator(':scope > summary').click()
                    page.goto(f['origin']+'/native/?'+urlencode({'path':'/toolbox?section=publish&work=work-055&version=version-old'}),wait_until='domcontentloaded')
                    details=disclosure('交付记录');expect(details).to_be_visible();page.wait_for_timeout(350)
                    check(label,'closed delivery does not request work, studio or distribution data',not any(row['path'].startswith(('/api/distribution/','/api/works','/api/studio/bootstrap')) for row in requests))
                    toggle(details)
                    body=details.locator('textarea').first;expect(body).to_have_value('TEMP exact body version-old')
                    expect(details.get_by_role('combobox',name='交付版本')).to_have_value('version-old')
                    check(label,'opening delivery reads summary plus the exact requested older version',any(row['path']=='/api/distribution/bootstrap' and row['query'].get('view')==['summary'] for row in requests) and count('/api/works/work-055/versions/version-old/view')==1 and count('/api/works/work-055/versions/version-new/view')==0)
                    check(label,'no legacy full work or studio tree is requested',count('/api/studio/bootstrap')==0 and not any(row['path']=='/api/works' and row['query'].get('view')!=['summary'] or row['path']=='/api/works/work-055' for row in requests))
                    draft='TEMP unsent channel text '+label;body.fill(draft)
                    expect(details.get_by_text('TEMP_FULL_DELIVERY_BODY',exact=False)).to_have_count(0)
                    details.get_by_role('button',name='实际回执记录',exact=True).click();drawer=page.get_by_role('dialog',name='实际回执记录',exact=True);expect(drawer).to_contain_text('TEMP_FULL_DELIVERY_BODY')
                    check(label,'only opening the receipt drawer reads the exact full delivery',count('/api/distribution/deliveries/delivery-lazy')==1)
                    drawer.get_by_role('button',name='关闭',exact=True).click()
                    ledger=disclosure('发布台账');toggle(ledger);expect(ledger.get_by_text('TEMP publication ledger',exact=True)).to_be_visible()
                    check(label,'the ledger requests only publication summaries',any(row['path']=='/api/studio/bootstrap' and row['query'].get('view')==['publications'] for row in requests) and count('/api/studio/publications/publication-lazy')==0)
                    ledger.get_by_role('button',name='台账与来源',exact=True).click();drawer=page.get_by_role('dialog',name='台账与来源',exact=True);expect(drawer).to_contain_text('TEMP_FULL_PUBLICATION_BODY');drawer.get_by_role('button',name='关闭',exact=True).click()
                    check(label,'the full publication is read only by its exact record drawer',count('/api/studio/publications/publication-lazy')==1)
                    toggle(details);page.wait_for_timeout(250);before=count('/api/distribution/bootstrap');page.wait_for_timeout(5400)
                    check(label,'closing delivery stops its five second poll',count('/api/distribution/bootstrap')==before)
                    toggle(details);expect(body).to_have_value(draft)
                    check(label,'reopening retains the exact unsent channel draft')
                    page.screenshot(path=str(out/(label+'-delivery.png')),full_page=True)
                    report['screenshots'][label+'-delivery']={'path':str(out/(label+'-delivery.png')),'sha256':sha(out/(label+'-delivery.png'))}
                    start=len(requests);page.goto(f['origin']+'/native/?'+urlencode({'path':'/toolbox?section=skills&pane=experience&profile=oil-pig'}),wait_until='domcontentloaded')
                    picker=disclosure('限定作品');expect(picker).to_be_visible();page.wait_for_timeout(250)
                    check(label,'experience does not fetch its optional work list before expansion',not any(row['path']=='/api/works' for row in requests[start:]))
                    toggle(picker);expect(picker.locator('input[type=checkbox]')).to_have_count(50);first=picker.locator('input[type=checkbox]').first;first.check();first_label=first.locator('..').inner_text()
                    picker.get_by_role('button',name='加载更多作品',exact=True).click();expect(picker.locator('input[type=checkbox]')).to_have_count(56)
                    expect(picker.locator('label').filter(has_text=first_label).locator('input')).to_be_checked();toggle(picker);toggle(picker);expect(picker.locator('label').filter(has_text=first_label).locator('input')).to_be_checked()
                    check(label,'work pagination preserves selection and every request stays profile-scoped at fifty',all(row['query'].get('view')==['summary'] and row['query'].get('limit')==['50'] and row['query'].get('profile_id')==['oil-pig'] for row in requests[start:] if row['path']=='/api/works'))
                    page.screenshot(path=str(out/(label+'-experience.png')),full_page=True);report['screenshots'][label+'-experience']={'path':str(out/(label+'-experience.png')),'sha256':sha(out/(label+'-experience.png'))}
                    check(label,'no model, business write or page error occurs',not f['adapter'].requests and not errors and not any(row['method'] not in ('GET','HEAD','OPTIONS') and row['path'].startswith(('/api/distribution/commands','/api/studio/commands','/api/creator/commands','/api/chat/submit')) for row in requests))
                    check(label,'the viewport remains horizontally bounded',page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
                    report['requests'][label]=requests;context.close()
            browser.close()
        report['passed']=True
    finally:
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0


if __name__=='__main__':raise SystemExit(main())
