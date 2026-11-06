"""Real Edge and TEMP HTTPS; native UI, actual receipts, synthetic model only."""
import argparse,asyncio,base64,importlib.util,json,sys
from pathlib import Path
from urllib.parse import urlencode,parse_qs,urlsplit
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
for key in ('native','backend','out'):parser.add_argument('--'+key,type=Path,required=True)
args=parser.parse_args();sys.path.insert(0,str(args.backend.resolve()))
spec=importlib.util.spec_from_file_location('review_browser_fixture',ROOT/'tests/workbench_native_browser.py')
h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h);h.ROOT=args.backend.resolve()
from easel_workbench.features.works.native_review import MARKER
from playwright.sync_api import sync_playwright,expect
PNG=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAIAAAACCAYAAABytg0kAAAAEUlEQVR4nGM4XDHxPwgzwBgAYwQLLfOeIwgAAAAASUVORK5CYII=')
args.out.mkdir(parents=True,exist_ok=True);checks=[]
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
    for layout,width in [('desktop',1280),('mobile',390)]:
        with h.isolated(args.native.resolve(),PNG) as f:
            calls=[]
            async def run(request,emit,ask,bind):
                calls.append(request);bind('TEMP-native');request.on_native_turn('TEMP-native','TEMP-'+str(len(calls)))
                frame=json.JSONDecoder().raw_decode(request.prompt.rsplit(MARKER,1)[1])[0]
                folder=Path(frame['product_directory']);folder.mkdir(parents=True,exist_ok=True)
                image=folder/'成品.png';image.write_bytes(PNG)
                copy=folder/'标题与配文.txt';copy.write_text('准确标题\n完整配文',encoding='utf8')
                emit('token','[成图]('+image.as_posix()+')\n[配文]('+copy.as_posix()+')')
            f['adapter'].run=run
            context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':900},is_mobile=width<600,has_touch=width<600)
            context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
            page=context.new_page();page.set_default_timeout(30000)
            page.goto(f['origin']+'/native/?'+urlencode({'path':'/chat?fresh=1'}),wait_until='domcontentloaded')
            page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.startsWith('/chat/')")
            sid=parse_qs(urlsplit(page.url).query)['path'][0].split('/chat/')[1].split('?')[0]
            composer=page.get_by_role('textbox',name='对话输入',exact=True)
            composer.fill('/油猪·做贴图');expect(page.get_by_role('menuitem',name='/油猪·做贴图',exact=False)).to_be_visible();composer.press('Enter')
            composer.fill('制作贴图');page.get_by_role('button',name='发送',exact=True).click()
            expect(page.get_by_text('这版你想采纳、继续修改，还是暂不采纳？',exact=False)).to_be_visible(timeout=60000)
            composer.fill('采纳这版');page.get_by_role('button',name='发送',exact=True).click()
            expect(page.get_by_text('已标记此版本为“已采纳”。',exact=True)).to_be_visible(timeout=60000)
            assert len(calls)==1
            page.reload(wait_until='domcontentloaded')
            expect(page.get_by_text('已标记此版本为“已采纳”。',exact=True)).to_be_visible()
            composer.fill('修改这版，标题更具体');page.get_by_role('button',name='发送',exact=True).click()
            expect(page.get_by_text('这版你想采纳、继续修改，还是暂不采纳？',exact=False).last).to_be_visible(timeout=60000)
            composer.fill('不采纳这版，保留原件');page.get_by_role('button',name='发送',exact=True).click()
            expect(page.get_by_text('已标记此版本为“未采纳”，原文件保留。',exact=True)).to_be_visible(timeout=60000)
            assert len(calls)==2
            with f['box'].store.connect() as c:
                assert c.execute("SELECT count(*) FROM toolbox_jobs WHERE kind IN ('accept','reject')").fetchone()[0]==2
                assert c.execute("SELECT candidate_id FROM toolbox_jobs WHERE kind='change'").fetchone()[0]
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.screenshot(path=str(args.out/(layout+'.png')),full_page=True);checks.append(layout);context.close()
    browser.close()
(args.out/'report.json').write_text(json.dumps({'passed':True,'layouts':checks,'real_model_calls':0,'physical_device_tested':False}),encoding='utf8')
