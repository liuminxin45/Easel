"""TEMP HTTPS account UX against Windows Edge with a synthetic platform runner."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('account_browser_fixture',Path(__file__).with_name('workbench_native_browser.py'))
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)


def main():
    p=argparse.ArgumentParser();p.add_argument('--native',required=True);p.add_argument('--out',required=True);p.add_argument('--backend');args=p.parse_args()
    if args.backend:sys.path.insert(0,str(Path(args.backend).resolve()))
    from playwright.sync_api import sync_playwright,expect
    expect.set_options(timeout=15000)
    out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True);native=Path(args.native).resolve()
    report={'passed':False,'checks':[],'real_AI_calls':0,'real_platform_writes':0,'physical_mobile_device_tested':False,'harness_sha256':h.sha(__file__),'native':{'release':native.name,'manifest_sha256':h.sha(native/'native-manifest.json')}}
    if args.backend:report['backend']={'directory':str(Path(args.backend).resolve()),'manifest_sha256':h.sha(Path(args.backend)/'workbench-release.json')}
    def check(profile,name):report['checks'].append({'profile':profile,'check':name});print('PASS',profile,name,flush=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
            image_page=browser.new_page();image_page.set_content('<p>TEMP synthetic QR image</p>');image=image_page.screenshot();image_page.close()
            with h.isolated(native,image) as f:
                f['close_clients']=lambda:[c.close() for c in browser.contexts]
                runner_calls=[];finish=threading.Event();accounts=f['app'].state.easel_accounts
                def runner(payload):
                    runner_calls.append({'id':payload['session']['id'],'action':payload['action']})
                    if payload['action']=='login':
                        directory=Path(payload['directory']);directory.mkdir(parents=True,exist_ok=True)
                        (directory/'qr.png').write_bytes(image)
                        (directory/'login.json').write_text(json.dumps({'state':'qr_ready'}),encoding='utf-8')
                        assert finish.wait(30),'TEMP login was not released'
                    return {'loggedIn':True,'provider_user_id':'temp-uid-'+payload['session']['id'],'name':'TEMP synthetic account'}
                accounts.runner=runner
                def close_clients():
                    finish.set()
                    for context in browser.contexts:context.close()
                    for thread in threading.enumerate():
                        if thread.name.startswith('account-'):thread.join(timeout=2)
                f['close_clients']=close_clients
                for profile,width,mobile in [('windows',1280,False),('mobile-simulated',390,True)]:
                    finish.clear();before=len(runner_calls)
                    context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':900},is_mobile=mobile,has_touch=mobile)
                    context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
                    page=context.new_page();page.set_default_timeout(15000);errors=[];requests=[];polls=[]
                    page.on('pageerror',lambda error:errors.append(str(error)))
                    def request_seen(request):
                        if urlsplit(request.url).path=='/api/platform-accounts':
                            if request.method=='POST':requests.append(request.post_data_json)
                            else:polls.append(time.monotonic())
                    page.on('request',request_seen)
                    page.goto(f['origin']+'/native/?path=%2Ftoolbox%3Fsection%3Ddistribution%26pane%3Dconnections',wait_until='domcontentloaded')
                    card=page.locator('.account-card').filter(has=page.get_by_role('heading',name='微信公众号',exact=True))
                    expect(card).to_be_visible()
                    # Let the server accept login, but lose that exact HTTP response.
                    lost=[];receipt_reads=[]
                    def receipt_status(route):
                        identity=urlsplit(route.request.url).path.rsplit('/',1)[-1];receipt_reads.append(identity)
                        if len(receipt_reads)<=2:route.fulfill(status=200,content_type='application/json',body=json.dumps({'id':identity,'state':'waiting'}))
                        else:route.continue_()
                    page.route('**/api/operations/**',receipt_status)
                    def drop_receipt(route):
                        body=route.request.post_data_json or {}
                        if body.get('action')=='login' and not lost:
                            lost.append(body['id']);route.fetch();page.wait_for_timeout(650)
                            assert page.get_by_text('原操作回执待核对。保留原输入与操作身份。',exact=True).count()==0
                            route.abort('failed')
                        else:route.continue_()
                    page.route('**/api/platform-accounts',drop_receipt)
                    card.get_by_role('button',name='重新扫码登录' if profile=='mobile-simulated' else '扫码登录',exact=True).click()
                    dialog=page.get_by_role('dialog',name='微信公众号 · 扫码登录')
                    expect(page.get_by_text('连接暂时中断，正在恢复操作状态。输入已保留。',exact=True).first).to_be_visible()
                    assert page.locator('.notice-error').filter(has_text='连接').count()==0
                    expect(dialog.get_by_alt_text('平台登录二维码')).to_be_visible()
                    assert len([r for r in requests if r['action']=='login'])==1
                    assert len(runner_calls)==before+1
                    assert page.get_by_role('button',name='核对原操作',exact=True).count()==0
                    assert page.locator('.notice-error').filter(has_text='回执').count()==0
                    check(profile,'lost acknowledgement automatically recovers with one login POST and one runner')
                    page.screenshot(path=str(out/(profile+'-qr.png')),full_page=True)
                    expect(page.locator('.account-card').filter(has=page.get_by_role('heading',name='微信视频号',exact=True)).get_by_role('button',name='扫码登录',exact=True)).to_be_enabled()
                    check(profile,'another account stays usable while this account waits for scan')
                    dialog.get_by_role('button',name='关闭',exact=True).click();card.get_by_role('button',name='查看登录进度',exact=True).click();expect(dialog.get_by_alt_text('平台登录二维码')).to_be_visible()
                    page.reload(wait_until='domcontentloaded');expect(card.get_by_role('button',name='查看登录进度',exact=True)).to_be_visible();card.get_by_role('button',name='查看登录进度',exact=True).click();expect(dialog.get_by_alt_text('平台登录二维码')).to_be_visible()
                    assert len([r for r in requests if r['action']=='login'])==1 and len(runner_calls)==before+1
                    check(profile,'closing and reloading reconnects to original login without a new request')
                    finish.set();expect(dialog.get_by_text('登录成功',exact=True)).to_be_visible();page.screenshot(path=str(out/(profile+'-connected.png')),full_page=True)
                    check(profile,'polled login completion appears without manual confirmation')
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    assert not errors,errors
                    assert not f['adapter'].requests
                    check(profile,'no JavaScript errors or horizontal overflow; no model execution')
                    report.setdefault('observations',{})[profile]={'login_posts':len([r for r in requests if r['action']=='login']),'synthetic_runner_calls':len(runner_calls)-before,'poll_intervals_ms':[round((b-a)*1000) for a,b in zip(polls,polls[1:])],'lost_operation_id':lost[0]}
                    page.unroute('**/api/platform-accounts',drop_receipt);page.unroute('**/api/operations/**',receipt_status);context.close()
                finish.set()
            browser.close()
        if args.backend:
            backend=Path(args.backend).resolve();manifest=json.loads((backend/'workbench-release.json').read_text(encoding='utf-8'))
            assert all(h.sha(backend/name)==digest for name,digest in manifest['files'].items())
            modules={name:str(Path(module.__file__).resolve()) for name,module in sys.modules.items() if (name=='easel' or name.startswith('easel.') or name=='easel_workbench' or name.startswith('easel_workbench.')) and getattr(module,'__file__',None)}
            assert modules and all(Path(path).is_relative_to(backend) for path in modules.values())
            report.update(module_roots_valid=True,module_count=len(modules))
        report['passed']=True
    except BaseException as error:
        report['error']=repr(error)
        if 'page' in locals():
            try:page.screenshot(path=str(out/'failure.png'),full_page=True)
            except Exception:pass
        raise
    finally:
        (out/'harness.py').write_bytes(Path(__file__).read_bytes());report['evidence']={p.name:h.sha(p) for p in out.glob('*.png')};(out/'operations-browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'error':report.get('error')},ensure_ascii=True),flush=True)

if __name__=='__main__':main()


