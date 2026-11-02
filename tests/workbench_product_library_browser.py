"""Actual Edge, native components and TEMP HTTP; only model work is synthetic."""
from __future__ import annotations
import argparse,asyncio,hashlib,importlib.util,json,shutil,sys,threading
from pathlib import Path
from urllib.parse import parse_qs,urlsplit,quote

ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser()
    for key in ('native','backend','out'):parser.add_argument('--'+key,type=Path,required=True)
    args=parser.parse_args();native,backend,out=args.native.resolve(),args.backend.resolve(),args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((native/'native-manifest.json').read_bytes());assert all(sha(native/name)==value for name,value in manifest['files'].items())
    package=json.loads((backend/'workbench-release.json').read_bytes()) if (backend/'workbench-release.json').exists() else None
    if package:assert all(sha(backend/name)==value for name,value in package['files'].items())
    sys.path.insert(0,str(backend));spec=importlib.util.spec_from_file_location('product_library_fixture',ROOT/'tests/workbench_native_browser.py');helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    from playwright.sync_api import sync_playwright,expect
    report={'passed':False,'checks':[],'native':{'release':manifest['release'],'manifest_sha256':sha(native/'native-manifest.json')},'backend':{'directory':str(backend),'manifest_sha256':sha(backend/'workbench-release.json') if package else None},'harness_sha256':sha(__file__),'screenshots':{},'real_AI_calls':0,'platform_writes':0,'physical_mobile_device_tested':False}
    def check(profile,name,value=True):
        report['checks'].append({'profile':profile,'name':name,'passed':bool(value)});assert value,name
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
            for label,width,theme in [('desktop',1280,'light'),('mobile-360',360,'dark'),('mobile-390',390,'dark'),('mobile-430',430,'light')]:
                with helper.isolated(native,(ROOT/'web/static/easel-icon.png').read_bytes()) as f:
                    from easel_workbench.runtime.auth_totp import token_hash
                    f['auth'].lock=threading.RLock();f['auth'].data['sessions']={token_hash('fixture-owner'):{'csrf':'fixture','until':9999999999}}
                    adapter=f['adapter'];outputs=[]
                    async def run(request,emit,ask,bind):
                        adapter.requests.append(request);bind('TEMP-library');request.on_native_turn('TEMP-library','TEMP-turn')
                        value=json.JSONDecoder().raw_decode(request.prompt.split('## 本轮冻结输入\n')[-1])[0]
                        folder=Path(value['output_directory']);folder.mkdir(parents=True,exist_ok=True)
                        images=[folder/(str(index)+'-成品.png') for index in range(1,4)]
                        for image in images:image.write_bytes(adapter.image)
                        copy=folder/'标题与配文.txt';copy.write_text('AI调用量大，怎样判断有没有用？\n\nTEMP 分开的准确配文。',encoding='utf-8')
                        assets=folder/'assets';assets.mkdir()
                        for index in range(13):(assets/('过程-'+str(index)+'.txt')).write_text('未交付过程材料',encoding='utf-8')
                        outputs.extend([*images,copy]);emit('token','\n\n'.join(['TEMP 原字说明。'*8]*12)+'\n\n'+'\n\n'.join('![成图](/'+path.as_posix()+')' for path in images)+'\n\n[标题与配文](/'+quote(copy.as_posix(),safe='/:')+')')
                        await asyncio.sleep(.1)
                    adapter.run=run
                    context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':900},is_mobile=width<600,has_touch=width<600,color_scheme=theme,accept_downloads=True)
                    context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
                    page=context.new_page();page.set_default_timeout(25000);errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                    try:
                        page.goto(f['origin']+'/native/chat?fresh=1',wait_until='domcontentloaded');page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.startsWith('/chat/')")
                        sid=parse_qs(urlsplit(page.url).query)['path'][0].split('/chat/')[1].split('?')[0]
                        composer=page.get_by_role('textbox',name='对话输入',exact=True);composer.fill('/生成贴图 TEMP 精确制作')
                        expect(page.get_by_role('menuitem',name='/生成贴图',exact=False)).to_be_visible();composer.press('Enter');page.get_by_role('button',name='发送',exact=True).click()
                        history=helper.wait_history(page,f['origin'],sid,files=True);message=history['session']['messages'][-1];tid=message['turnId'];wid=message['work']['work_id']
                        with f['box'].store.connect() as c:job=dict(c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(tid,)).fetchone())
                        check(label,'URI-spelled Markdown registers only three images and copy',job['status']=='completed' and len(message['output_files'])==4 and len(adapter.requests)==1)
                        expect(page.get_by_role('button',name='查看产物',exact=True)).to_have_count(0);expect(page.locator('.chat-linked-works')).to_have_count(0)
                        link=helper.turn_view(page,history).get_by_role('link',name='内容库 › 本版产物',exact=True);expect(link).to_be_visible()
                        check(label,'only a native output hyperlink connects chat to the exact version','workbench-'+wid+'/'+tid in link.get_attribute('href'))
                        if width<600:
                            # The old check required the very top bar the user rejected.
                            # The actual floating opener must stay reachable without reserving a row.
                            opener=page.get_by_role('button',name='打开导航',exact=True)
                            expect(opener).to_be_visible()
                            check(label,'mobile uses no reserved top bar and retains a reachable floating drawer opener',
                                page.locator('.mobile-nav-bar').count()==0 and opener.evaluate("el=>{const r=el.getBoundingClientRect();return getComputedStyle(el).position==='fixed'&&r.left>=0&&r.right<=innerWidth&&r.top>=0&&r.bottom<=innerHeight&&el.contains(document.elementFromPoint(r.left+r.width/2,r.top+r.height/2))}"))
                            check(label,'messages and original send control remain reachable with the floating opener',
                                page.locator('.chat-messages').bounding_box()['height']>0 and page.get_by_role('button',name='发送',exact=True).is_visible())
                        copy_link=helper.turn_view(page,history).get_by_role('link',name='标题与配文',exact=True)
                        check(label,'the shared formatter opens text in the native registered-file preview',copy_link.get_attribute('href').startswith('#/outputs/__workbench__/'))
                        copy_link.click();expect(page.locator('.drawer-body')).to_contain_text('TEMP 分开的准确配文。')
                        page.get_by_role('button',name='关闭预览',exact=True).click()
                        page.goto(f['origin']+'/native/chat/'+sid,wait_until='domcontentloaded')
                        link=helper.turn_view(page,history).get_by_role('link',name='内容库 › 本版产物',exact=True)
                        link.click();expect(page.locator('.gallery-page')).to_be_visible();expect(page.locator('.gallery-grid').first.locator('.gcard')).to_have_count(4)
                        expect(page.get_by_text('成品 · 4',exact=True)).to_be_visible();expect(page.locator('.ew-work')).to_have_count(0);expect(page.get_by_role('button',name='复制图文',exact=True)).to_have_count(0)
                        check(label,'shared breadcrumbs keep the library label on one line',page.locator('.gallery-breadcrumbs > .crumb').evaluate('element=>element.getBoundingClientRect().height<=parseFloat(getComputedStyle(element).lineHeight)*1.1'))
                        operations=page.locator('details').filter(has=page.locator('summary',has_text='版本与操作')).first
                        check(label,'native gallery is the only browser and lifecycle controls start collapsed',not operations.evaluate('element=>element.open'))
                        page.locator('.gcard').filter(has_text='1-成品.png').click();expect(page.get_by_role('link',name='下载原图',exact=True)).to_be_visible()
                        with page.expect_download() as downloaded:page.get_by_role('link',name='下载原图',exact=True).click()
                        check(label,'native file preview downloads the exact registered bytes',sha(downloaded.value.path())==sha(outputs[0]))
                        page.locator('.drawer-header .icon-btn').click();operations.locator('summary').first.click();expect(page.get_by_role('button',name='修改这版',exact=True)).to_be_visible()
                        expect(page.get_by_text('已生成 · 待独立检查',exact=True)).to_be_visible();expect(page.get_by_role('button',name='复制图文',exact=True)).to_have_count(0)
                        page.get_by_role('button',name='不采纳',exact=True).click();dialog=page.get_by_role('dialog',name='不采纳 v01',exact=True);expect(dialog).to_be_visible()
                        reason='TEMP 保留不采纳原话 '+label;dialog.get_by_label('决定说明 · 可不填',exact=True).fill(reason);dialog.get_by_role('button',name='确认不采纳',exact=True).click();expect(dialog).to_have_count(0)
                        with f['box'].store.connect() as c:raw=c.execute("SELECT text FROM toolbox_jobs WHERE candidate_id=? AND kind='reject'",(tid,)).fetchone()[0]
                        check(label,'rejection records the exact parent and raw text without production',raw==reason and len(adapter.requests)==1)
                        page.get_by_role('button',name='修改这版',exact=True).click();page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.includes('action=change')")
                        path=parse_qs(urlsplit(page.url).query)['path'][0];query=parse_qs(urlsplit(path).query)
                        check(label,'modification returns to the native chat with the exact parent and frozen skill',query['work']==[wid] and query['version']==[tid] and len(adapter.requests)==1)
                        expect(page.get_by_role('textbox',name='对话输入',exact=True)).to_be_visible()
                        if width<600:
                            page.set_viewport_size({'width':width,'height':520});page.get_by_role('textbox',name='对话输入',exact=True).focus()
                            check(label,'short viewport keeps the complete composer and send control reachable',page.get_by_role('button',name='发送',exact=True).bounding_box()['y']+page.get_by_role('button',name='发送',exact=True).bounding_box()['height']<=520)
                            page.set_viewport_size({'width':width,'height':900})
                        page.goto(f['origin']+'/native/?path='+quote('/works/'+wid+'?version='+tid,safe=''),wait_until='domcontentloaded');expect(page.locator('.gallery-grid').first.locator('.gcard')).to_have_count(4)
                        page.reload(wait_until='domcontentloaded');expect(page.locator('.gallery-grid').first.locator('.gcard')).to_have_count(4)
                        check(label,'old version URLs and refresh use the same native gallery without rerunning',len(adapter.requests)==1 and not errors and page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1'))
                        filename=label+'-native-library.png';page.screenshot(path=str(out/filename),full_page=True);report['screenshots'][filename]=sha(out/filename)
                    except Exception:
                        report['failure_body']=page.locator('body').inner_text();page.screenshot(path=str(out/'failure.png'),full_page=True);raise
                    finally:context.close()
            browser.close()
        report['passed']=True
    except Exception as error:
        import traceback
        report.update(error=repr(error),traceback=traceback.format_exc())
    finally:
        report['module_roots_valid']=all(Path(module.__file__).resolve().is_relative_to(backend) for name,module in list(sys.modules.items()) if (name=='easel' or name.startswith('easel.') or name=='easel_workbench' or name.startswith('easel_workbench.')) and getattr(module,'__file__',None))
        report['passed'] &= report['module_roots_valid'];shutil.copy2(__file__,out/'harness.py');(out/'product-library-browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'error':report.get('error')},ensure_ascii=True),flush=True)
    return 0 if report['passed'] else 1

if __name__=='__main__':raise SystemExit(main())
