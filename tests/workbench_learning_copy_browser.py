"""Actual Edge with isolated data and a fake clipboard; never calls a real model."""
import argparse, importlib.util, json, sys
from pathlib import Path
from urllib.parse import urlencode

ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
for key in ('native','backend','out'):parser.add_argument('--'+key,type=Path,required=True)
args=parser.parse_args();sys.path.insert(0,str(args.backend.resolve()))
spec=importlib.util.spec_from_file_location('learning_fixture',ROOT/'tests/workbench_native_browser.py')
helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
from playwright.sync_api import sync_playwright,expect

args.out.mkdir(parents=True,exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
    with helper.isolated(args.native.resolve(),(ROOT/'web/static/easel-icon.png').read_bytes()) as f:
        folder=f['root']/'data'/'artifacts'/'copy-test';folder.mkdir(parents=True)
        path=folder/'title.txt';path.write_text('测试标题\n\n正文第一段\n\n第二段  ',encoding='utf8')
        with f['box'].store.connect() as c:
            c.execute('INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)',('copy-work',None,'测试作品','原素材','2026-11-01','2026-11-03'))
            c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,files,scope,signature,status,created_at,finished_at,reply) VALUES(?,?,?,?,?,?,?,?,?,?,?)',('copy-turn','copy-work','create','输入','[]','[]','copy-turn','completed','2026-11-03','2026-11-03','完成'))
            c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)',('copy-file','copy-turn','标题与配文.txt',str(path),'text/plain'))
        f['box']._native_api.library.rebuild(lock_timeout=10)
        for name,width in [('desktop',1280),('mobile',390)]:
            context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':900},is_mobile=width<600,has_touch=width<600)
            context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
            page=context.new_page();page.set_default_timeout(30000)
            page.add_init_script("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.__copiedText=text}}})")
            rows=page.request.get(f['origin']+'/api/skills').json()
            assert {'oil-pig-learn-poster','oil-pig-learn-article'} <= {v['name'] for v in rows}
            page.goto(f['origin']+'/native/?'+urlencode({'path':'/works?'+urlencode({'path':'__workbench__/copy-file/标题与配文.txt'})}),wait_until='domcontentloaded')
            expect(page.get_by_role('button',name='复制标题',exact=True)).to_be_visible()
            page.get_by_role('button',name='复制标题',exact=True).click();assert page.evaluate('window.__copiedText')=='测试标题'
            page.get_by_role('button',name='复制正文',exact=True).click();assert page.evaluate('window.__copiedText')=='正文第一段\n\n第二段  '
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            page.goto(f['origin']+'/native/?'+urlencode({'path':'/toolbox?section=skills'}),wait_until='domcontentloaded')
            expect(page.get_by_text('油猪·学习贴图',exact=True)).to_be_visible()
            expect(page.get_by_text('油猪·学习文章',exact=True)).to_be_visible()
            page.screenshot(path=str(args.out/(name+'.png')),full_page=True)
            context.close()
    browser.close()
(args.out/'report.json').write_text(json.dumps({'passed':True,'layouts':['desktop','mobile'],'real_model_calls':0},ensure_ascii=False),encoding='utf8')
