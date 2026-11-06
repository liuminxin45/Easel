"""Actual Easel skill cards/Drawer and private method selection in TEMP HTTPS.

All imported methods and metadata below are synthetic fixtures. This test never
uses production data, GitHub, a real Agent or a publishing account.
"""
from __future__ import annotations
import argparse,hashlib,importlib.util,json,shutil,time
from pathlib import Path
from urllib.parse import parse_qs,urlsplit
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
METHODS=[('local-temp-writer','writing','写作与叙事',['writing'],'油猪·隔离写作方法',1200),
         ('local-temp-polish','polish','润色与去 AI 味',['polish'],'油猪·隔离中文润色',2400),
         ('local-temp-layout','layout','排版与格式',['layout'],'油猪·隔离文章排版',None),
         ('local-temp-publish','publish','草稿与发布工具',[],'油猪·隔离待配置发布',100)]


def seed_library(root):
    """Seed before create_app; Star cache is fresh so no background network."""
    home=root/'.local/third-party-skills';home.mkdir(parents=True,exist_ok=True)
    sources=[];skills=[];stars={};commit='a'*40
    for sid,category,label,stages,name,count in METHODS:
        repo='temp-fixture/'+category;directory='packages/'+repo+'/'+commit
        package=home/directory;package.mkdir(parents=True,exist_ok=True)
        raw='---\nname: '+sid+'\ndescription: TEMP fixture method\n---\n\n# '+name+'\n\nTEMP_SELECTED_METHOD_'+category+'。按需读取 references/rules.txt。\n'
        (package/'SKILL.md').write_text(raw,encoding='utf-8')
        (package/'references').mkdir();(package/'references/rules.txt').write_text('TEMP exact '+category+' resource',encoding='utf-8')
        files={file.relative_to(package).as_posix():hashlib.sha256(file.read_bytes()).hexdigest() for file in package.rglob('*') if file.is_file()}
        sources.append({'repository':repo,'commit':commit,'directory':directory,'files':files,'license_paths':[]})
        blocked='需配置：TEMP 发布通道与明确交付授权' if category=='publish' else ''
        skills.append({'id':sid,'repository':repo,'commit':commit,'entry':'SKILL.md','original_name':'temp-original-'+category,'display_name':name,'description':'TEMP 隔离测试方法。','layer':'publish' if category=='publish' else 'produce','category':category,'category_label':label,'stages':stages,'tags':['隔离验收'],'installed':True,'validation_state':'source_checked','requirements':['TEMP 发布通道'] if blocked else [],'execution_blocked':blocked})
        native=root/'skills/builtin'/sid;native.mkdir(parents=True)
        (native/'SKILL.md').write_text('---\nname: '+sid+'\ndescription: TEMP wrapper\nlayer: '+skills[-1]['layer']+'\n---\n\nTEMP native discovery wrapper.\n',encoding='utf-8')
        if count is not None:stars[repo]={'count':count,'checked_at':time.time(),'etag':'temp-etag'}
    (home/'catalog.json').write_text(json.dumps({'schema':1,'revision':'temp-library-exact-revision','sources':sources,'skills':skills,'installed_at':time.time()},ensure_ascii=False),encoding='utf-8')
    (home/'stars.json').write_text(json.dumps({'checked_at':time.time(),'sources':stars}),encoding='utf-8')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('backend','native','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--worktree',action='store_true',help='Explicit source-tree probe; does not claim a frozen backend')
    args=parser.parse_args();backend,native,out=args.backend.resolve(),args.native.resolve(),args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('local_library_browser_helper',ROOT/'tests/workbench_news_creation_browser.py')
    h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
    helper,application,create_app=h.infrastructure(backend,native)
    def with_library(*a,**kw):seed_library(Path(kw['root']));return create_app(*a,**kw)
    from playwright.sync_api import sync_playwright,expect
    expect.set_options(timeout=30000)
    binding={'worktree':True,'root':str(backend)} if args.worktree else h.frozen(backend,'workbench-release.json')
    report={'passed':False,'checks':[],'backend':binding,'native':h.frozen(native,'native-manifest.json'),'physical_device_tested':False,'production_data_access':False,'real_model_calls':0,'platform_writes':0,'errors':[],'screenshots':{}}
    def mark(case,name):report['checks'].append({'case':case,'name':name,'passed':True});print('PASS',case,name,flush=True)
    try:
      with patch.object(application,'create_app',with_library),patch.object(helper.SyntheticAdapter,'run',h.fake_run),sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
        for case,width,height,mobile,theme in h.LAYOUTS:
          with helper.isolated(native,h.IMAGE) as f:
            article=h.seed_news(f);context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':height},is_mobile=mobile,has_touch=mobile,service_workers='block')
            context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
            context.add_init_script('localStorage.setItem("native:theme",'+json.dumps(theme)+')')
            page=context.new_page();page.set_default_timeout(30000);requests=[]
            page.on('pageerror',lambda error:report['errors'].append(str(error)))
            page.on('request',lambda request:requests.append({'path':urlsplit(request.url).path,'method':request.method}))
            def guard(route):
                assert urlsplit(route.request.url).hostname in ('localhost','127.0.0.1'),'Isolated browser must not reach external services'
                route.continue_()
            page.route('**/*',guard)
            def shot(name):
                file=out/(case+'-'+name+'.png');page.screenshot(path=str(file));report['screenshots'][file.name]=h.sha(file)
            h.goto(page,f['origin'],'/toolbox?section=skills')
            expect(page.locator('.skills-page[data-catalog-state="ready"]')).to_be_visible()
            expect(page.get_by_text('油猪·隔离写作方法',exact=True)).to_be_visible()
            assert not any(r['path'].startswith('/api/skill/') for r in requests),'Library must not fetch bodies before opening a card'
            assert not f['adapter'].requests
            controls=page.locator('.ew-local-skill-controls')
            h.choose(page,controls,'技能来源','本次导入',expect)
            expect(page.locator('.skill-card')).to_have_count(4)
            writer=page.locator('.skill-card').filter(has_text='油猪·隔离写作方法')
            expect(writer.locator('.ew-local-skill-stars')).to_have_text('★ 1,200')
            expect(page.locator('.skill-card').filter(has_text='油猪·隔离文章排版').locator('.ew-local-skill-stars')).to_have_text('★ —')
            assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
            h.choose(page,controls,'技能细分类','润色与去 AI 味',expect)
            expect(page.locator('.skill-card')).to_have_count(1)
            expect(page.locator('.skill-card-name')).to_have_text('油猪·隔离中文润色')
            h.choose(page,controls,'技能细分类','全部细分类',expect)
            h.choose(page,controls,'技能排序','仓库 Star 从高到低',expect)
            expect(page.locator('.skill-card-name').first).to_have_text('油猪·隔离中文润色')
            page.get_by_placeholder('搜索技能名或描述…').fill('temp-original-writing')
            expect(page.locator('.skill-card')).to_have_count(1)
            page.get_by_role('button',name='清除',exact=True).click()
            mark(case,'native cards support private source/category/original-name filters and repository Star sorting without body requests')
            shot('catalog')
            writer.click();detail=page.get_by_role('dialog',name='油猪·隔离写作方法',exact=True)
            expect(detail).to_be_visible();expect(detail.locator('.skill-body-md')).to_contain_text('TEMP_SELECTED_METHOD_writing')
            expect(detail.get_by_role('link',name='temp-fixture/writing',exact=True)).to_have_attribute('href','https://github.com/temp-fixture/writing')
            expect(detail.get_by_text('仓库关注数，非单技能使用人数',exact=True)).to_be_visible()
            expect(detail.get_by_text('源码：aaaaaaaaaaaa',exact=True)).to_be_visible()
            assert page.locator('.drawer-overlay').count()==1
            assert detail.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1')
            assert not f['adapter'].requests
            shot('skill-detail');detail.get_by_role('button',name='关闭',exact=True).click()
            page.locator('.skill-card').filter(has_text='油猪·隔离待配置发布').click()
            blocked=page.get_by_role('dialog',name='油猪·隔离待配置发布',exact=True)
            expect(blocked.get_by_text('需配置：TEMP 发布通道与明确交付授权',exact=True).last).to_be_visible()
            blocked.get_by_placeholder('输入内容，例如主题 / 素材 / 要求…').fill('不应真正执行')
            expect(blocked.get_by_role('button',name='执行',exact=True)).to_be_disabled()
            assert not f['adapter'].requests
            blocked.get_by_role('button',name='关闭',exact=True).click()
            mark(case,'original Drawer reads one selected body, shows source/time/revision and prevents unconfigured execution')
            h.goto(page,f['origin'],'/news/a/'+article)
            page.get_by_role('button',name='制作内容',exact=True).click();creation=page.get_by_role('dialog',name='制作内容',exact=True)
            creation.get_by_role('button',name='贴图',exact=True).click()
            selection=creation.get_by_role('region',name='辅助技能选择',exact=True)
            expect(selection.get_by_role('button',name='写作方法技能',exact=True)).to_contain_text('沿用油猪写法')
            expect(selection.get_by_role('button',name='排版技能',exact=True)).to_have_count(0)
            h.choose(page,creation,'写作方法技能','油猪·隔离写作方法',expect)
            h.choose(page,creation,'润色技能','油猪·隔离中文润色',expect)
            assert not f['adapter'].requests
            assert not any(r['method']=='POST' and r['path'].startswith('/api/chat/') for r in requests)
            assert creation.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1')
            selection.scroll_into_view_if_needed();shot('method-selection')
            creation.get_by_role('button',name='文章',exact=True).click()
            expect(creation.get_by_role('button',name='排版技能',exact=True)).to_be_visible()
            h.choose(page,creation,'排版技能','油猪·隔离文章排版',expect)
            assert not f['adapter'].requests
            mark(case,'original production Drawer selects one method per stage without execution and keeps article layout separate')
            if case=='desktop-light':
                creation.get_by_role('button',name='贴图',exact=True).click()
                expect(creation.get_by_role('button',name='写作方法技能',exact=True)).to_contain_text('油猪·隔离写作方法')
                creation.get_by_role('textbox',name='补充要求',exact=True).fill('TEMP_NATIVE_POSTER 本次原字要求')
                start=creation.get_by_role('button',name='开始制作贴图',exact=True);expect(start).to_be_enabled();start.click()
                page.wait_for_function('()=>new URLSearchParams(location.search).get("path")?.startsWith("/chat/")')
                sid=parse_qs(urlsplit(page.url).query)['path'][0].split('/chat/',1)[1].split('?',1)[0]
                history=helper.wait_history(page,f['origin'],sid);turn_id=history['session']['messages'][-1]['turnId']
                turn=h.turn_document(f,turn_id)
                assert turn['context']['creation']['auxiliary_skills']=={'writing':'local-temp-writer','polish':'local-temp-polish'}
                assert turn['context']['creation']['auxiliary_revision']=='temp-library-exact-revision'
                assert len(f['adapter'].requests)==1
                prompt=turn['actual_prompt'];assert '本轮明确选定的辅助技能' in prompt and 'TEMP_SELECTED_METHOD_writing' not in prompt
                manifests=list((f['root']/'outputs/_sessions/local-skill-inputs'/turn_id).glob('*/manifest.json'));assert len(manifests)==1
                frozen=json.loads(manifests[0].read_text(encoding='utf-8'))
                assert {item['stage'] for item in frozen['selection']}=={'writing','polish'}
                for name,digest in frozen['files'].items():assert h.sha(manifests[0].parent/name)==digest
                assert not any('local-temp-layout' in name for name in frozen['files'])
                mark(case,'one native admission receives exact selected method/resource snapshots without article-layout leakage')
            context.close()
        browser.close();assert not report['errors'];report['passed']=True
    except BaseException as error:
        report['error']=repr(error)
        if 'page' in locals():
            try:report['failure_page']={'url':page.url,'body':page.locator('body').inner_text()};page.screenshot(path=str(out/'failure.png'),full_page=True)
            except Exception:pass
    finally:
        shutil.copy2(__file__,out/'harness.py');(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'error':report.get('error')}),flush=True)
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
