"""Frozen news-to-native-chat acceptance in actual Edge and TEMP HTTPS.

The real owner API, SQLite, manifest copies, native chat and content index run.
Only the Agent executor is synthetic; no production database or model is used.
"""
from __future__ import annotations

import argparse,asyncio,base64,datetime,hashlib,importlib.util,json,re,shutil,sys,time
from pathlib import Path
from urllib.parse import parse_qs,urlencode,urlsplit
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
IMAGE=base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aJ1kAAAAASUVORK5CYII=')
BODY='第一自然段：这是隔离新闻的准确原始文本，描述新闻事实。\n\n第二自然段：这段保留背景、原始来源和未确认的边界。\n\n第三自然段：选择讨论不应自动制作，制作必须绑定显式动作。'
TITLE='TEMP_NEWS_CREATION：一条用于核验新闻讨论与同会话创作的完整长标题'
LAYOUTS=[('desktop-light',1280,900,False,'light'),('mobile-390-light',390,844,True,'light'),('mobile-390-dark',390,844,True,'dark'),('mobile-320-light',320,780,True,'light'),('mobile-320-dark',320,780,True,'dark')]

def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def frozen(directory,name):
    manifest=read(directory/name)
    for member,digest in manifest['files'].items():assert sha(directory/member)==digest,member
    return {'release':directory.name,'manifest_sha256':sha(directory/name)}

def goto(page,origin,path):page.goto(origin+'/native/?'+urlencode({'path':path}),wait_until='domcontentloaded')

def session_id(page):
    path=parse_qs(urlsplit(page.url).query).get('path',[''])[0]
    assert path.startswith('/chat/'),page.url
    return path.split('/chat/',1)[1].split('?',1)[0]

def wait_new_call(page,adapter,before):
    end=time.monotonic()+20
    while len(adapter.requests)==before and time.monotonic()<end:page.wait_for_timeout(50)
    assert len(adapter.requests)==before+1,'Expected precisely one new native Agent admission'

def turn_document(f,turn_id):
    with f['box'].store.connect() as c:
        row=c.execute('SELECT document FROM easel_chat_turns WHERE id=?',(turn_id,)).fetchone()
    assert row;return json.loads(row[0])

def material_files(f,turn_id):
    manifest=f['root']/'outputs/_sessions/inputs'/turn_id/'manifest.json'
    assert manifest.is_file(),'Creation must save actual admitted material manifest'
    value=read(manifest)
    for item in value['material_manifest']['files']:
        path=Path(item['path']);path=path if path.is_absolute() else f['root']/path
        assert path.resolve().is_relative_to(f['root']) and path.is_file()
        assert sha(path)==item['sha256'] and path.stat().st_size==item['size']
    return value

async def fake_run(self,request,emit,ask,bind):
    """Actual native callback contract, with real isolated output files."""
    from easel.harnesses.base import HarnessError
    self.requests.append(request);number=len(self.requests)
    native=request.native_id or 'TEMP-news-native-'+request.session_key
    bind(native);request.on_native_turn(native,'TEMP-news-turn-'+str(number))
    await asyncio.sleep(.15)
    if 'TEMP_NEWS_UNKNOWN' in request.prompt:raise HarnessError('TEMP admitted request receipt unknown; never replay')
    production='content-production' in request.prompt
    if not production:
        emit('token','TEMP 仅讨论：原新闻的事实、切入角度与表达边界，没有制作文件。');return
    folder=Path(request.cwd)/'outputs/TEMP-news-created'/('run-'+str(number));folder.mkdir(parents=True,exist_ok=True)
    body=folder/'正文.md';body.write_text('# TEMP_NEWS_PRODUCT_'+str(number)+'\n\n'+BODY,encoding='utf-8')
    emit('activity','TEMP native executor wrote separately versioned files')
    media=''
    if '根据明确选择制作贴图' in request.prompt:
        image=folder/'贴图.png';image.write_bytes(IMAGE)
        media='\n\n![贴图](/api/media/TEMP-news-created/run-'+str(number)+'/贴图.png)'
    emit('token','TEMP_NEWS_PRODUCT_'+str(number)+media+'\n\n[正文]('+body.as_posix()+')')

def infrastructure(backend,native):
    """Load exact frozen backend; never silently import current product source."""
    sys.path.insert(0,str(backend))
    spec=importlib.util.spec_from_file_location('news_creation_fixture',ROOT/'tests/workbench_native_browser.py')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper);helper.ROOT=backend
    import easel_workbench.application as application
    original=application.create_app
    def native_app(*args,**kwargs):
        root=Path(kwargs['root']);(root/'config').mkdir(exist_ok=True)
        shutil.copy2(backend/'config/workbench-skills.json',root/'config/workbench-skills.json')
        assert read(root/'config/workbench-skills.json')['mode']=='easel-native'
        return original(*args,**kwargs)
    return helper,application,native_app

def seed_news(f):
    from easel_workbench.runtime.desk import SOURCES,article_identity
    source=next(iter(SOURCES));article={'title':TITLE,'body':BODY,'url':'https://example.com/temp-news-creation'}
    f['box'].store.ingest({'schema_version':1,'source_job':source,'feed_id':SOURCES[source]['feed'],'run_id':'news-creation-browser','run_at':datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat(),'final_text':BODY,'articles':[article]})
    return article_identity(source,article)


def choose(page,drawer,label,name,expect):
    drawer.get_by_role('button',name=label,exact=True).click()
    menu=page.get_by_role('listbox',name=label,exact=True);expect(menu).to_be_visible()
    assert menu.evaluate('(n)=>{const r=n.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth+1&&r.top>=0&&r.bottom<=innerHeight+1}')
    menu.get_by_role('option',name=name,exact=True).click()
    expect(drawer.get_by_role('button',name=label,exact=True)).to_contain_text(name)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('backend','native','out'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--allow-manual-close',action='store_true',help='Exploratory old-candidate probe only; never final acceptance')
    args=parser.parse_args();backend=args.backend.resolve();native=args.native.resolve();out=args.out.resolve();out.mkdir(parents=True,exist_ok=True)
    binding=frozen(backend,'workbench-release.json');native_binding=frozen(native,'native-manifest.json')
    helper,application,native_app=infrastructure(backend,native)
    from playwright.sync_api import sync_playwright,expect
    report={'passed':False,'backend':binding,'native':native_binding,'checks':[],'screenshots':{},'requests':{},'page_errors':[],'manual_post_submit_drawer_closures':[],'exploratory_manual_close_allowed':args.allow_manual_close,'real_model_calls':0,'platform_writes':0,'production_data_access':False,'physical_device_tested':False,'harness_sha256':sha(__file__),'fixture_sha256':sha(ROOT/'tests/workbench_native_browser.py')}
    catalog=read(backend/'skills/shared/workbench/规范/创作方案/目录.json');entries={item['id']:item for item in catalog['components']}
    def mark(case,name,**details):report['checks'].append({'case':case,'check':name,'passed':True,**details});print('PASS',case,name,flush=True)
    try:
      with patch.object(helper.SyntheticAdapter,'run',fake_run),patch.object(application,'create_app',native_app),sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
        for case,width,height,mobile,theme in LAYOUTS:
          with helper.isolated(native,IMAGE) as f:
            article=seed_news(f);context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':height},is_mobile=mobile,has_touch=mobile,service_workers='block')
            context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}]);context.add_init_script('localStorage.setItem("native:theme",'+json.dumps(theme)+');')
            page=context.new_page();page.set_default_timeout(30000);requests=[];report['requests'][case]=requests
            page.on('pageerror',lambda error:report['page_errors'].append(str(error)))
            def guard(route):
                assert urlsplit(route.request.url).hostname in ('localhost','127.0.0.1'),'TEMP browser cannot access production or external services'
                route.continue_()
            page.route('**/*',guard)
            def requested(req):
                path=urlsplit(req.url).path
                if path.startswith('/api/'):
                    row={'path':path,'method':req.method}
                    if req.method=='POST' and req.post_data:
                        try:row['body']=req.post_data_json
                        except Exception:pass
                    requests.append(row)
            page.on('request',requested)
            def shot(name):
                page.evaluate('()=>Promise.all(document.getAnimations().filter(a=>a.effect?.getTiming().iterations!==Infinity).map(a=>a.finished.catch(()=>{})))')
                file=out/(case+'-'+name+'.png');page.screenshot(path=str(file));report['screenshots'][file.name]=sha(file)
            def creation_drawer(format):
                page.get_by_role('button',name='制作内容',exact=True).click();drawer=page.get_by_role('dialog',name='制作内容',exact=True);expect(drawer).to_be_visible();drawer.get_by_role('button',name=format,exact=True).click();return drawer
            def post_bodies():return [r['body'] for r in requests if r['path']=='/api/chat/submit' and r['method']=='POST']
            def close_finished_drawer(stage):
                drawer=page.get_by_role('dialog',name='制作内容',exact=True)
                if not args.allow_manual_close:
                    expect(drawer).not_to_be_visible(timeout=5000)
                    return
                if drawer.count() and drawer.is_visible():
                    report.setdefault('manual_post_submit_drawer_closures',[]).append({'case':case,'stage':stage})
                    drawer.get_by_role('button',name='关闭',exact=True).click()
            def current_context(profile):
                response=page.request.get(f['origin']+'/api/news/'+article+'/creation-context?profile_id='+profile);assert response.ok,response.text();return response.json()
            try:
                goto(page,f['origin'],'/news/a/'+article);expect(page.locator('.ew-news-prose > p')).to_have_count(3)
                assert page.locator('.ew-news-prose > p').all_text_contents()==BODY.split('\n\n')
                assert page.locator('.ew-news-prose pre').count()==0
                expect(page.get_by_role('button',name='讨论怎么写',exact=True)).to_be_enabled()
                geometry=page.locator('.ew-news-actions').evaluate('(n)=>{const r=n.getBoundingClientRect();return {top:r.top,bottom:r.bottom,height:r.height,viewport:innerHeight,buttons:[...n.querySelectorAll("button")].map(b=>({name:b.textContent,height:b.getBoundingClientRect().height}))}}')
                assert all(0<item['height']<=72 for item in geometry['buttons']),geometry
                if mobile:
                    assert geometry['height']<=180 and abs(geometry['bottom']-height)<=2,geometry
                    expect(page.locator('.ew-news-article h1')).to_be_in_viewport()
                report.setdefault('reading_geometry',{})[case]=geometry
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');shot('reading')
                page.get_by_role('button',name='采集记录',exact=True).click();record=page.get_by_role('dialog',name='采集记录',exact=True);expect(record.locator('.ew-news-raw')).to_have_text(BODY)
                assert page.locator('.drawer-overlay').count()==1;record.get_by_role('button',name='关闭',exact=True).click();mark(case,'real news body uses natural paragraphs; raw collection remains in official Drawer')
                page.get_by_role('button',name='讨论怎么写',exact=True).evaluate('(b)=>{b.click();b.click()}')
                page.wait_for_function('()=>new URLSearchParams(location.search).get("path")?.startsWith("/chat/")')
                sid=session_id(page);history=helper.wait_history(page,f['origin'],sid);discussion=history['session']['messages'][-1];profile=history['session']['profile_id']
                assert len(f['adapter'].requests)==1 and len(post_bodies())==1
                submitted=post_bodies()[-1];assert submitted['context']['creation']['intent']=='discuss' and not submitted['context'].get('skill_id')
                assert not list((f['root']/'outputs').glob('TEMP-news-created/run-*'))
                assert history['session']['source_article_id']==article
                assert history['session']['title']==TITLE,'News session must use the selected headline, not a generic discussion instruction'
                mark(case,'double-click discussion admits once, uses ordinary native chat and produces no files')
                before=current_context(profile);drawer=creation_drawer('贴图');available=before['components']
                style={slot:next(item['id'] for item in values if item['available']) for slot,values in available.items()}
                assert all(any(item['available'] and item['id']==cid for item in available[slot]) for slot,cid in [('character','simple-pig'),('character','wuxia-pig')])
                style['character']='simple-pig'
                for slot,label in [('writing','写法'),('visual','画面风格'),('character','角色呈现'),('layout','画面与结构')]:choose(page,drawer,label,entries[style[slot]]['name'],expect)
                drawer.get_by_label('补充要求',exact=True).fill('TEMP 保存后继续核对；原话不改。')
                drawer.get_by_role('button',name='保存为画像默认',exact=True).click();expect(drawer.get_by_text('已保存为画像默认，本次尚未开始制作。',exact=True)).to_be_visible()
                saved=current_context(profile);assert saved['defaults']['poster']==style and saved['profile_revision']==before['profile_revision']+1
                assert len(f['adapter'].requests)==1
                # Save consecutively in this very Drawer, without stale revision errors.
                drawer.get_by_role('button',name='保存为画像默认',exact=True).click()
                expect(drawer.get_by_text('已保存为画像默认，本次尚未开始制作。',exact=True)).to_be_visible()
                saved=current_context(profile);assert saved['profile_revision']==before['profile_revision']+2
                drawer.get_by_role('button',name='关闭',exact=True).click();drawer=creation_drawer('贴图')
                for slot,label in [('writing','写法'),('visual','画面风格'),('character','角色呈现'),('layout','画面与结构')]:expect(drawer.get_by_role('button',name=label,exact=True)).to_contain_text(entries[style[slot]]['name'])
                note='TEMP 精确草稿 '+case+'\n此备注仅本次。';drawer.get_by_label('补充要求',exact=True).fill(note);drawer.get_by_role('button',name='关闭',exact=True).click();page.reload(wait_until='domcontentloaded');drawer=creation_drawer('贴图');expect(drawer.get_by_label('补充要求',exact=True)).to_have_value(note)
                mark(case,'explicit consecutive default saves advance profile revisions; reopening and reload preserve the exact draft')
                # Per-request override must not alter saved profile defaults.
                choose(page,drawer,'角色呈现',entries['wuxia-pig']['name'],expect)
                expect(drawer.locator('img.ew-news-style-preview').first).to_be_visible()
                page.wait_for_function('()=>[...document.querySelectorAll("img.ew-news-style-preview")].every(n=>n.complete&&n.naturalWidth>0)')
                shot('poster-settings')
                start=len(post_bodies());drawer.get_by_role('button',name='开始制作贴图',exact=True).evaluate('(b)=>{b.click();b.click()}')
                history=helper.wait_history(page,f['origin'],sid,discussion['turnId']);poster=history['session']['messages'][-1];assert session_id(page)==sid
                assert len(post_bodies())==start+1 and len(f['adapter'].requests)==2
                submitted=post_bodies()[-1];assert submitted['context']['skill_id']=='content-production' and submitted['context']['action_id']=='native'
                assert submitted['context']['creation']['format']=='poster' and submitted['context']['creation']['style']['character']=='wuxia-pig'
                assert current_context(profile)['defaults']['poster']==style
                package=material_files(f,poster['turnId']);assert package['creation']['note']==note
                copied=package['material_manifest']['files'];expect_hashes={a['sha256'] for a in entries['wuxia-pig'].get('assets',[]) if a.get('required',True)}
                assert expect_hashes and expect_hashes<={i['sha256'] for i in copied}
                sent_materials=json.JSONDecoder().raw_decode(f['adapter'].requests[-1].prompt.split('## 本轮附件\n')[-1])[0]
                actual_paths={Path(item['path']).resolve() for item in sent_materials}
                assert all((f['root']/i['path']).resolve() in actual_paths for i in copied)
                assert turn_document(f,poster['turnId'])['context']['creation']['style']['character']=='wuxia-pig'
                review=page.request.get(f['origin']+'/api/chat/turns/'+poster['turnId']+'/creation');assert review.ok and all('path' not in i for i in review.json()['material_manifest']['files'])
                mark(case,'same-session poster explicitly invokes native content-production once with exact reference copies and isolated style override',reference_sha256=sorted(expect_hashes))
                close_finished_drawer('poster')
                # The next format shares this same news conversation but has its own draft.
                drawer=creation_drawer('文章');expect(drawer.get_by_role('button',name='设置配图风格',exact=True)).to_be_visible()
                assert drawer.get_by_role('button',name='角色呈现',exact=True).count()==0
                writing=next(item for item in available['writing'] if item['available']);choose(page,drawer,'写法',writing['name'],expect)
                drawer.get_by_label('补充要求',exact=True).fill('TEMP 文章只写正文 '+case);shot('article-settings');drawer.get_by_role('button',name='开始写文章',exact=True).click()
                history=helper.wait_history(page,f['origin'],sid,poster['turnId']);article_turn=history['session']['messages'][-1];assert session_id(page)==sid
                assert len(f['adapter'].requests)==3 and post_bodies()[-1]['context']['creation']['format']=='article'
                package=material_files(f,article_turn['turnId']);assert package['creation']['style']=={'writing':writing['id']}
                assert not any(i['role'] in ('identity','reference') for i in package['material_manifest']['files'])
                mark(case,'same conversation switches to explicit article production; optional illustration settings remain absent')
                close_finished_drawer('article')
                drawer=creation_drawer('贴图');choose(page,drawer,'角色呈现',entries['simple-pig']['name'],expect)
                drawer.get_by_label('补充要求',exact=True).fill('TEMP 简笔小猪准确身份参考 '+case)
                drawer.get_by_role('button',name='开始制作贴图',exact=True).click()
                history=helper.wait_history(page,f['origin'],sid,article_turn['turnId']);simple_turn=history['session']['messages'][-1]
                assert session_id(page)==sid and len(f['adapter'].requests)==4
                simple_package=material_files(f,simple_turn['turnId'])
                simple_hashes={a['sha256'] for a in entries['simple-pig'].get('assets',[]) if a.get('required',True)}
                assert simple_hashes and simple_hashes<={i['sha256'] for i in simple_package['material_manifest']['files']}
                assert simple_package['creation']['style']['character']=='simple-pig' and current_context(profile)['defaults']['poster']==style
                mark(case,'simple-pig selection binds its separate canonical reference hashes without overwriting precise wuxia history',reference_sha256=sorted(simple_hashes))
                close_finished_drawer('simple-pig')
                # Inspect exact previous material through the read-only original Drawer.
                page.get_by_role('button',name='本轮创作设置',exact=True).last.click();review_drawer=page.get_by_role('dialog',name='本轮创作设置',exact=True);expect(review_drawer.get_by_text('本轮参考材料',exact=True)).to_be_visible();shot('turn-materials');review_drawer.get_by_role('button',name='关闭',exact=True).click()
                goto(page,f['origin'],'/works?path=TEMP-news-created/run-3/正文.md');expect(page.get_by_text('TEMP_NEWS_PRODUCT_3',exact=False).first).to_be_visible();shot('library-product')
                mark(case,'new actual Agent output is indexed and previewed through the original content library')
                goto(page,f['origin'],'/news/a/'+article);expect(page.get_by_role('button',name='继续讨论',exact=True)).to_be_enabled();before_calls=len(f['adapter'].requests);page.get_by_role('button',name='继续讨论',exact=True).click();expect(page.get_by_role('textbox',name='对话输入')).to_be_visible();assert session_id(page)==sid and len(f['adapter'].requests)==before_calls
                # Send a truly admitted unknown receipt, then reload and revisit without replay.
                drawer=creation_drawer('贴图');drawer.get_by_label('补充要求',exact=True).fill('TEMP_NEWS_UNKNOWN');drawer.get_by_role('button',name='开始制作贴图',exact=True).click();wait_new_call(page,f['adapter'],before_calls)
                end=time.monotonic()+20
                unknown_tid=post_bodies()[-1]['turnId']
                while time.monotonic()<end:
                    state=turn_document(f,unknown_tid)
                    if state.get('status')=='unknown':break
                    page.wait_for_timeout(100)
                assert state['status']=='unknown','Synthetic admitted failure must remain an unknown receipt'
                admitted=len(f['adapter'].requests);page.reload(wait_until='domcontentloaded');expect(page.get_by_role('textbox',name='对话输入')).to_be_visible();page.wait_for_timeout(400)
                goto(page,f['origin'],'/news/a/'+article);open_button=page.get_by_role('button',name=re.compile(r'^(查看会话|继续讨论)$'))
                expect(open_button).to_be_enabled();open_button.click();expect(page.get_by_role('textbox',name='对话输入')).to_be_visible();assert session_id(page)==sid
                assert len(f['adapter'].requests)==admitted and len(post_bodies())==5
                assert not any(r['method']=='POST' and r['path'] in ('/api/chat/plan','/api/creative/commands') for r in requests)
                assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');shot('unknown-preserved')
                mark(case,'unknown admitted operation survives reload/news return without replay or a new conversation')
            except BaseException as error:
                report['failure']={'case':case,'type':type(error).__name__,'message':str(error)[:4000]}
                try:shot('failure');(out/(case+'-failure-body.txt')).write_text(page.locator('body').inner_text(),encoding='utf-8')
                except Exception:pass
                raise
            finally:context.close()
        browser.close()
      assert not report['page_errors']
      if not args.allow_manual_close:assert not report['manual_post_submit_drawer_closures']
      report['passed']=True
    finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return 0

if __name__=='__main__':raise SystemExit(main())


