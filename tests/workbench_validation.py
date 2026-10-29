"""Candidate-only acceptance using TEMP HTTPS, fake native RPC and real files.

No production selector, model process, publication or business DB is touched.
The legacy project supplies existing test fixtures, never the modules under test.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import copy
import hashlib
import importlib
from importlib.abc import MetaPathFinder
import json
import os
from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

PROJECT=Path(__file__).resolve().parents[1]
LEGACY=Path('D:/Projects/ai-news-desk')
RUNTIME_ROOT=PROJECT
BACKEND_SELECTION=None
NAMESPACE_ISOLATION=False
LEGACY_MODULE_NAMES=set()


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def setup_runtime(backend=None):
    global RUNTIME_ROOT,BACKEND_SELECTION,LEGACY_MODULE_NAMES
    RUNTIME_ROOT=Path(backend).resolve() if backend else PROJECT
    if backend:
        manifest=RUNTIME_ROOT/'workbench-release.json'
        document=json.loads(manifest.read_text(encoding='utf-8'))
        for relative,expected in document['files'].items():
            member=(RUNTIME_ROOT/relative).resolve()
            assert member.is_relative_to(RUNTIME_ROOT) and sha(member)==expected,relative
        BACKEND_SELECTION={'release':document['release'],'manifest_sha256':sha(manifest)}
    os.environ['AI_DESK_PROJECT_ROOT']=str(LEGACY)
    sys.path.insert(0,str(RUNTIME_ROOT))
    baseline=json.loads((PROJECT/'docs/workbench/import-baseline.json').read_text(encoding='utf-8'))
    LEGACY_MODULE_NAMES={Path(m).parts[0].removesuffix('.py') for m in baseline['files'] if m.endswith('.py') and not m.startswith('vendor/')}
    for member in baseline['files']:
        if member.endswith('.py') and not member.startswith(('vendor/','scripts/')):
            name=member[:-3].replace('/','.')
            module=importlib.import_module('easel_workbench.runtime.'+name)
            assert Path(module.__file__).resolve().is_relative_to(RUNTIME_ROOT/'easel_workbench/runtime')
            sys.modules[name]=module
    sys.path.insert(0,str(LEGACY/'tests'))


@contextmanager
def namespace_guard(enabled):
    audit={'enabled':enabled,'forbidden_import_attempts':[],'flat_aliases_before':0,'flat_aliases_during':0,'passed':not enabled}
    if not enabled:
        yield audit
        return
    removed={name:module for name,module in list(sys.modules.items()) if name.split('.')[0] in LEGACY_MODULE_NAMES}
    audit['flat_aliases_before']=len(removed)
    for name in removed:del sys.modules[name]
    class RefuseLegacy(MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if fullname.split('.')[0] in LEGACY_MODULE_NAMES:
                audit['forbidden_import_attempts'].append(fullname)
                raise ModuleNotFoundError('Legacy flat runtime import prohibited during namespace acceptance: '+fullname)
            return None
    finder=RefuseLegacy();sys.meta_path.insert(0,finder)
    try:
        assert not any(n.split('.')[0] in LEGACY_MODULE_NAMES for n in sys.modules)
        yield audit
        aliases=[n for n in sys.modules if n.split('.')[0] in LEGACY_MODULE_NAMES]
        audit['flat_aliases_during']=len(aliases)
        audit['passed']=not aliases and not audit['forbidden_import_attempts']
        assert audit['passed'],audit
    finally:
        sys.meta_path.remove(finder)
        sys.modules.update(removed)


def fingerprints():
    return {p.relative_to(RUNTIME_ROOT).as_posix():sha(p) for p in sorted((RUNTIME_ROOT/'easel_workbench').rglob('*'))
            if p.is_file() and '__pycache__' not in p.parts and p.suffix in ('.py','.json','.js','.mjs')}


def candidate(path):
    directory=Path(path).resolve()
    manifest=json.loads((directory/'native-manifest.json').read_text(encoding='utf-8'))
    assert manifest['architecture'] in ('easel-workbench-extension','easel-responsive-ui')
    for relative,expected in manifest['files'].items():
        member=(directory/relative).resolve()
        assert member.is_relative_to(directory) and sha(member)==expected,relative
    return directory,manifest


def contract_tests(out):
    names=['test_poster_rpc','test_production_retry','test_production_outcome','test_creator_runtime',
           'test_creator_pipeline','test_creative_recipes','test_work_review','test_completion_service',
           'test_completion_api','test_easel_connections','test_simplify_workbench','test_form_auth',
           'test_distribution_auto_api','test_native_preview']
    suite=unittest.defaultTestLoader.loadTestsFromNames(names)
    # This historical fixture predates notification retirement. Keep every
    # outcome assertion and replace only its obsolete expectation of a new
    # notification row with the current no-new-notifications contract.
    from test_production_outcome import OutcomeTests
    class RetiredNotificationOutcome(OutcomeTests):
        def test_terminal_reply_without_products_is_not_review(self):
            work=self.finish('原文无法读取，贴图与配文暂未制作。')
            self.assertEqual(work['state'],'error');self.assertFalse(work['review_needed'])
            self.assertIsNone(work['latest_version']);self.assertEqual(work['versions'][0]['status'],'error')
            self.assertEqual(work['history'][0]['reply'],'原文无法读取，贴图与配文暂未制作。')
            with self.box.store.connect() as c:
                self.assertIsNone(c.execute("SELECT status FROM notification_events WHERE task_id='work'").fetchone())
            with self.assertRaises(ValueError):self.box.action('work',{'id':'accept','kind':'accept','candidate_id':'work','scope':['images']})
            with self.assertRaises(ValueError):self.box.retry('work')
    def flatten(item):
        for case in item:
            if isinstance(case,unittest.TestSuite):yield from flatten(case)
            else:yield case
    cases=[case for case in flatten(suite) if not case.id().endswith('OutcomeTests.test_terminal_reply_without_products_is_not_review')]
    cases.append(RetiredNotificationOutcome('test_terminal_reply_without_products_is_not_review'))
    suite=unittest.TestSuite(cases)
    with (out/'contracts.log').open('w',encoding='utf-8') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    report={'passed':result.wasSuccessful(),'tests':result.testsRun,'modules':names,
            'failures':[str(t) for t,_ in result.failures],'errors':[str(t) for t,_ in result.errors],
            'real_AI_calls':0,'real_platform_writes':0,'temporary_business_state_only':True}
    (out/'contracts.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)
    assert result.wasSuccessful(),report


def simulate_execution(f,jid,image,records):
    from easel_workbench.runtime import poster_executor,task_runtime,bridge
    from easel_workbench.runtime.production_style import DIMENSIONS
    from easel_workbench.runtime.semantic_style import applicability
    from learning_browser import artifact

    box=f['box'];native_calls=[];rollout=f['root']/('synthetic-'+jid+'.jsonl');rollout.touch()
    with box.store.connect() as c:
        job=dict(c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(jid,)).fetchone())
        format=c.execute('SELECT format FROM toolbox_work_options WHERE work_id=?',(job['work_id'],)).fetchone()[0]
        before=json.loads(c.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?',(jid,)).fetchone()[0])
    title='合成'+('文章' if format=='article' else '贴图')+'：保留来源与边界'
    body='这是一份隔离流程验收成品，由测试程序写入，未调用真实模型。\n\n完整原始材料与版本关系应保留。'
    def deliver():
        if format=='poster':
            artifact(box,jid,'封面.png',image,'image/png')
            artifact(box,jid,'标题与配文.txt',title+'\n'+body,'text/plain')
            text_name='标题与配文.txt'
        else:
            text_name='文章正文.md'
            artifact(box,jid,text_name,'# '+title+'\n\n'+body,'text/markdown')
            artifact(box,jid,'文章交付.json',json.dumps({'schema_version':1,'article_type':'general','title':title,
                'body_file':text_name,'sources':[]},ensure_ascii=False),'application/json')
        creation=before['creation_options'];readable=bool(creation.get('recipe'))
        active=applicability(creation)
        required=before['learning_snapshot']['required_evidence']
        assert required,'Expected real frozen requirements'
        ids=[r['id'] for r in required]
        def refs(dimension):
            name='封面.png' if format=='poster' and dimension in ('image','style') else text_name
            path=box.root/'data/artifacts'/jid/name
            if name.endswith('.png'):anchor={'type':'region','x':0,'y':0,'width':1,'height':1}
            else:
                text=path.read_text(encoding='utf-8');quote=text.splitlines()[0]
                anchor={'type':'text','start':0,'end':len(quote),'quote':quote}
            return [{'artifact_name':name,'location':'合成文件中的实际位置','sha256':sha(path),'anchor':anchor}]
        dimensions=[]
        for key in DIMENSIONS:
            enabled=active[key]['applicable']
            dimensions.append({'id':key,'applicable':enabled,'intent':None if readable or not enabled else creation['resolved_intent'][key],
                'outcome':'applied' if enabled else 'not_applicable','reason':'合成验收依实际冻结输入建立文件位置证据。',
                'basis_ids':[next((r['id'] for r in required if r.get('dimension')==key),ids[0])] if enabled else [],
                'deliverables':refs(key) if enabled else []})
        responses=[{'basis_id':r['id'],'dimension':r.get('dimension') if r.get('dimension') in DIMENSIONS else 'style',
                    'outcome':'applied','reason':'合成执行回执，仅验证文件与版本合同。','deliverables':refs(r.get('dimension'))} for r in required]
        design={'schema_version':2,'basis':'execution','dimensions':dimensions,'responses':responses}
        if readable:design['control_mode']='readable_prompt'
        artifact(box,jid,'设计说明.json',json.dumps(design,ensure_ascii=False),'application/json')

    class FakeRPC:
        def __init__(self,on_event=None):self.process=type('Process',(),{'poll':lambda self:None})()
        def call(self,method,params,timeout=None):
            native_calls.append((method,copy.deepcopy(params)))
            if method=='thread/start':return {'thread':{'id':'synthetic-native-'+job['work_id'],'cwd':str(poster_executor.PROJECT),'path':str(rollout)}}
            if method=='thread/resume':return {'thread':{'id':params['threadId'],'cwd':str(poster_executor.PROJECT)}}
            if method=='thread/queue/list':return {'data':[]}
            if method=='turn/start':
                assert params['clientUserMessageId']==jid
                deliver()
                return {'turn':{'id':'synthetic-turn-'+jid,'status':'completed','items':[{'type':'agentMessage','text':'隔离合成执行完成，实际文件已写入 TEMP；未调用真实模型。'}]}}
            raise AssertionError(method)
        def close(self):pass
    executor=poster_executor.Executor(box,factory=FakeRPC,rollout=lambda:rollout)
    path=task_runtime.ensure_target(box,jid,FakeRPC,lambda:rollout)
    # capture_artifacts is real. Its filesystem root is confined to the TEMP
    # fixture, so apply_locked_text cannot write to the production authority.
    with patch.object(bridge,'ROOT',f['root']):executor.dispatch(job,path)
    with box.store.connect() as c:
        saved=dict(c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(jid,)).fetchone())
        assert saved['status']=='completed',saved.get('error')
        after=json.loads(c.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?',(jid,)).fetchone()[0])
        assert before==after,'Frozen instructions changed while executing'
        run=json.loads(c.execute('SELECT document FROM creator_task_runs WHERE id=?',(jid,)).fetchone()[0])
        call=json.loads(c.execute('SELECT document FROM creator_model_calls WHERE id=?',(run['model_call_id'],)).fetchone()[0])
        assert call['status']=='completed'
    sent=next(p for m,p in native_calls if m=='turn/start')
    assert sent['input'][0]['text']=='[AI_NEWS_DESK_REQUEST:'+jid+']\n'+before['execution_prompt']['body']
    from easel_workbench.runtime import production_retry
    with box.store.connect() as c:
        assert production_retry.frozen_inputs(c,saved)==sent['input']
    record={'job_id':jid,'work_id':job['work_id'],'kind':job['kind'],'format':format,
            'turn_id':saved['turn_id'],'frozen_input_sha256':hashlib.sha256(sent['input'][0]['text'].encode()).hexdigest(),
            'rpc_methods':[m for m,_ in native_calls],'real_AI_call':False,'simulation':'private fake native RPC; real TEMP files and real executor'}
    records.append(record)
    return title


def browser_tests(native,out):
    from playwright.sync_api import sync_playwright,expect
    import native_browser as h
    from creator_browser import prepare_project
    from creator_acceptance_fixture import seed
    # Capture the fixture helper while aliases are still available. It writes
    # only passed TEMP paths and makes no imports inside its function body.
    from learning_browser import artifact as _captured_artifact
    h.candidate_directory=candidate
    h.BACKEND={'kind':'easel-namespaced-extension','directory':str(RUNTIME_ROOT/'easel_workbench/runtime')}
    from easel_workbench.application import create_app as composition
    h.create_app=lambda store,auth,box,root,studio:composition(root=root,store=store,auth=auth,box=box,studio=studio)
    native,manifest=candidate(native)
    report={'passed':False,'native':{'release':manifest['release'],'manifest_sha256':sha(native/'native-manifest.json')},
            'checks':[],'errors':[],'simulated_executions':[],'real_AI_calls':0,'real_platform_writes':0,'physical_mobile_device_tested':False}
    def check(profile,name):report['checks'].append({'profile':profile,'check':name,'passed':True})
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
            image=h.poster_bytes(browser)
            with patch.object(h,'prepare_project',prepare_project),h.isolated_service(native,manifest,image) as f:
                seed(f,image)
                from test_completion_service import FixtureRuntime
                distribution=f['box'].completion.distribution
                distribution.runtime=FixtureRuntime()
                connection=distribution.command({'operation_id':'synthetic-browser-target','action':'connection-save',
                    'platform':'wechat_article','account':'合成验收账号','label':'合成草稿交付目标'},actor='owner')['result']['connection']
                profile=f['box'].creator.detail('profile','oil-pig')
                f['box'].creator.command({'id':'synthetic-bind-target','action':'bind-account','profile_id':'oil-pig',
                    'base_revision':profile['revision'],'connection_id':connection['id']})
                state=h.authenticate(browser,f,out,report['errors'])
                with namespace_guard(NAMESPACE_ISOLATION) as isolation:
                    report['namespace_isolation']=isolation
                    for profile in ('windows-1280','android-390'):
                        mobile=profile.startswith('android');context=browser.new_context(ignore_https_errors=True,storage_state=state,
                            color_scheme='dark' if mobile else 'light',**h.PROFILES[profile]);context.add_init_script(h.AUDIT_SCRIPT)
                        context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(f['origin']+'/') or route.request.url.startswith(('data:','blob:')) else route.abort())
                        page=context.new_page();page.set_default_timeout(20000);page.on('pageerror',lambda e:report['errors'].append(str(e)))
                        pending_requests={};network=[]
                        page.on('request',lambda request:pending_requests.__setitem__(id(request),{'method':request.method,'path':request.url.removeprefix(f['origin']),'at':time.time()}))
                        page.on('requestfinished',lambda request:pending_requests.pop(id(request),None))
                        page.on('requestfailed',lambda request:pending_requests.pop(id(request),None))
                        page.on('response',lambda response:network.append({'method':response.request.method,'path':response.url.removeprefix(f['origin']),'status':response.status,'at':time.time()}))
                        def go(path):
                            if page.url.startswith(f['origin']):
                                page.wait_for_function("()=>!document.querySelector('dialog[open]')&&!history.state?.nativeLayer")
                            h.ready(page,f['origin'],path)
                        def post(path,action):
                            with page.expect_response(lambda r:path in r.url and r.request.method=='POST') as r:action()
                            assert r.value.status==200,r.value.text()
                            return r.value.json()
                        try:
                            for format in ('poster','article'):
                                endpoint='/articles' if format=='article' else '/posters'
                                title='合成制作 '+format+' '+profile
                                go(endpoint+'/new?draft=full-flow-'+format+'-'+profile)
                                page.get_by_label('主题',exact=True).fill(title)
                                material='隔离原始材料：解释一个实际问题；保留来源、限制条件和本次明确要求。'
                                page.get_by_label('素材与目标',exact=True).fill(material)
                                preview=post('/api/creative/preview',lambda:page.get_by_role('button',name='查看制作方案',exact=True).click())
                                created=post('/api/works',lambda:page.get_by_role('button',name='确认并开始制作',exact=True).click())
                                wid=created.get('work_id') or created['id']
                                expect(page.get_by_role('heading',level=1,name=title,exact=True)).to_be_visible()
                                actual=simulate_execution(f,wid,image,report['simulated_executions'])
                                go(endpoint+'/'+wid)
                                expect(page.get_by_role('heading',level=1,name=actual,exact=True)).to_be_visible()
                                expect(page.get_by_text('完整原始材料与版本关系应保留。',exact=False).first).to_be_visible()
                                if format=='poster':expect(page.locator('.ew-work-preview img').first).to_be_visible()
                                with f['store'].connect() as c:
                                    doc=json.loads(c.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?',(wid,)).fetchone()[0])
                                    assert doc['execution_prompt']['body']==preview['execution_prompt']['body']
                                check(profile,format+'-preview-confirm-frozen-native-simulation-real-files')
                                if mobile:page.locator('#easel-main').get_by_role('button',name='对话',exact=True).click()
                                page.get_by_label('发送方式',exact=True).select_option('change')
                                page.get_by_label('对话输入',exact=True).fill('仅修改当前版本，补充来源限制的说明。')
                                post('/api/creative/preview',lambda:page.get_by_role('button',name='查看修改方案',exact=True).click())
                                changed=post('/actions',lambda:page.get_by_role('button',name='确认并开始制作',exact=True).click())
                                child=changed['id'];assert child!=wid
                                simulate_execution(f,child,image,report['simulated_executions'])
                                go(endpoint+'/'+wid+'?version='+child)
                                if mobile:page.locator('#easel-main').get_by_role('button',name='对话',exact=True).click()
                                page.get_by_label('发送方式',exact=True).select_option('feedback')
                                page.get_by_label('对话输入',exact=True).fill('反馈只记录，绑定本次合成修改版本。')
                                post('/actions',lambda:page.get_by_role('button',name='发送',exact=True).click())
                                with f['store'].connect() as c:
                                    row=c.execute("select candidate_id,status from toolbox_jobs where work_id=? and kind='feedback' order by rowid desc",(wid,)).fetchone()
                                    assert row['candidate_id']==child and row['status']=='completed'
                                check(profile,format+'-version-change-native-simulation-and-local-feedback')
                                if mobile:page.locator('#easel-main').get_by_role('button',name='成品',exact=True).click()
                                page.get_by_role('button',name='采纳并完成',exact=True).click()
                                modal=page.get_by_role('dialog')
                                if format=='article':
                                    modal.get_by_label('采纳后').select_option('distribute')
                                    modal.get_by_label('合成草稿交付目标').select_option('draft')
                                ack=modal.get_by_label('我已核对当前检查修订，确认保留这版')
                                if ack.count():ack.check()
                                adopted=post('/actions',lambda:modal.get_by_role('button',name='确认采纳并完成',exact=True).click())
                                expect(modal).not_to_be_visible(timeout=20000)
                                with f['store'].connect() as c:
                                    row=c.execute("select candidate_id,status from toolbox_jobs where work_id=? and kind='accept' order by rowid desc",(wid,)).fetchone()
                                    assert row['candidate_id']==child and row['status']=='completed'
                                    if format=='article':
                                        deliveries=[json.loads(row[0]) for row in c.execute('select document from distribution_deliveries')]
                                        selected=[d for d in deliveries if d['connection_id']==connection['id'] and d['status']=='queued']
                                        assert selected and selected[-1]['action']=='draft',deliveries
                                check(profile,format+'-adoption-exact-child-and-archive-authority')
                                page.screenshot(path=str(out/(profile+'-'+format+'-complete.png')),animations='disabled')
                            go('/posters/new?draft=authentication-'+profile)
                            page.get_by_label('素材与目标',exact=True).fill('401 后仍须保留的原字长草稿。'*200)
                            box=page.get_by_label('素材与目标',exact=True)
                            assert box.evaluate('(e)=>e.scrollHeight>e.clientHeight')
                            page.route('**/api/creator/bootstrap',lambda route:route.fulfill(status=401,content_type='application/json',body='{"error":"authentication_required"}'))
                            page.reload();expect(page.get_by_text('登录已过期，草稿保留。',exact=False).first).to_be_visible()
                            assert page.evaluate("()=>Object.values(localStorage).some(v=>v.includes('401 后仍须保留'))")
                            page.unroute('**/api/creator/bootstrap');page.reload();expect(page.get_by_label('素材与目标',exact=True)).to_have_value('401 后仍须保留的原字长草稿。'*200)
                            check(profile,'401-and-long-draft-scroll-preserved')
                            if mobile:page.get_by_role('button',name='打开工作导航',exact=True).click()
                            page.get_by_role('button',name='切换浅色' if mobile else '切换深色',exact=True).click()
                            if mobile:page.get_by_role('button',name='关闭工作导航',exact=True).click()
                            expect(page.get_by_label('素材与目标',exact=True)).to_have_value('401 后仍须保留的原字长草稿。'*200)
                            check(profile,'theme-change-retains-active-long-draft')
                            go('/toolbox')
                            if mobile:
                                page.get_by_role('button',name='打开工作导航',exact=True).click();page.go_back()
                                expect(page.get_by_role('button',name='关闭工作导航',exact=True)).not_to_be_visible()
                                check(profile,'browser-back-closes-mobile-drawer')
                            audit=h.audit(page);assert not audit['csp'] and not audit['boundary'],audit
                        except Exception as exc:
                            report['errors'].append({'profile':profile,'error':repr(exc)})
                            (out/(profile+'-network.json')).write_text(json.dumps({'pending':list(pending_requests.values()),'responses':network},ensure_ascii=False,indent=2),encoding='utf-8')
                            page.screenshot(path=str(out/(profile+'-failed.png')));raise
                        finally:context.close()
            browser.close()
        report['passed']=not report['errors']
    finally:
        report['evidence']={p.name:sha(p) for p in out.glob('*.png')}
        (out/'execution-browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'errors':report['errors']},ensure_ascii=False),flush=True)


def upgrade_tests(native,out):
    from playwright.sync_api import sync_playwright,expect
    import native_browser as h
    from creator_browser import prepare_project
    import shutil
    new,manifest=candidate(native)
    from easel_workbench.application import create_app as composition
    h.create_app=lambda store,auth,box,root,studio:composition(root=root,store=store,auth=auth,box=box,studio=studio)
    previous=json.loads((LEGACY/'data/active-native.json').read_text(encoding='utf-8'))
    old,old_manifest=candidate(LEGACY/'native-releases'/previous['release'])
    current={'release':manifest['release'],'manifest_sha256':sha(new/'native-manifest.json')}
    report={'passed':False,'native':current,'previous':previous,'checks':[],'real_AI_calls':0,'real_platform_writes':0}
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
            image=h.poster_bytes(browser)
            with patch.object(h,'prepare_project',prepare_project),h.isolated_service(new,manifest,image) as f:
                shutil.copytree(old,f['root']/'native-releases'/old_manifest['release'])
                pointer=f['root']/'data/active-native.json';pointer.write_text(json.dumps(previous),encoding='utf-8')
                state=h.authenticate(browser,f,out,[])
                for profile in ('windows-1280','android-390'):
                    context=browser.new_context(ignore_https_errors=True,storage_state=state,**h.PROFILES[profile]);page=context.new_page()
                    pointer.write_text(json.dumps(previous),encoding='utf-8')
                    h.ready(page,f['origin'],'/posters/new?draft=upgrade-'+profile)
                    text='跨项目在线升级后仍保留这份原字草稿。'+profile
                    page.get_by_label('素材与目标',exact=True).fill(text);page.locator('h1').last.click()
                    page.wait_for_function('()=>!!navigator.serviceWorker.controller');page.wait_for_load_state('networkidle')
                    page.get_by_label('素材与目标',exact=True).dispatch_event('compositionstart')
                    pointer.write_text(json.dumps(current),encoding='utf-8');page.evaluate("()=>window.dispatchEvent(new Event('focus'))")
                    page.wait_for_timeout(500)
                    assert page.locator('meta[name=native-release]').get_attribute('content')==previous['release']
                    report['checks'].append(profile+' simulated IME composition defers online upgrade')
                    page.get_by_label('素材与目标',exact=True).dispatch_event('compositionend')
                    page.evaluate("()=>window.dispatchEvent(new Event('focus'))")
                    page.wait_for_function("r=>document.querySelector('meta[name=native-release]')?.content===r",arg=current['release'],timeout=45000)
                    expect(page.get_by_label('素材与目标',exact=True)).to_have_value(text,timeout=20000)
                    report['checks'].append(profile+' online upgrade preserves original draft')
                    page.wait_for_function('()=>!!navigator.serviceWorker.controller');context.set_offline(True);page.reload(wait_until='domcontentloaded')
                    expect(page.get_by_role('heading',name='保留的本机输入')).to_be_visible(timeout=35000)
                    report['checks'].append(profile+' offline boot after upgrade')
                    context.set_offline(False);page.reload(wait_until='domcontentloaded');expect(page.get_by_label('素材与目标',exact=True)).to_have_value(text,timeout=35000)
                    report['checks'].append(profile+' reconnection preserves original draft')
                    context.close()
            browser.close()
        report['passed']=True
    finally:
        (out/'upgrade.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False),flush=True)


def surface_tests(native,out):
    import native_browser as h
    from easel_workbench.application import create_app as composition
    import easel_workbench_browser
    h.candidate_directory=candidate
    h.BACKEND={'kind':'easel-namespaced-extension','directory':str(RUNTIME_ROOT/'easel_workbench/runtime')}
    h.create_app=lambda store,auth,box,root,studio:composition(root=root,store=store,auth=auth,box=box,studio=studio)
    target=out/'surfaces';target.mkdir(exist_ok=True)
    easel_workbench_browser.run(argparse.Namespace(candidate=native,backend='',evidence=str(target),
        profiles='windows-1280,android-390',headed=False,browser='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--native',required=True);p.add_argument('--output',required=True)
    p.add_argument('--backend',help='Frozen release directory containing easel_workbench and easel')
    p.add_argument('--isolate-namespace',action='store_true',help='Reject all legacy flat runtime imports during actual browser workflows')
    p.add_argument('--mode',choices=('contracts','browser','surfaces','upgrade','all'),default='all')
    args=p.parse_args();out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    # Clear fixture-loader options before importing the historical harness.
    sys.argv=[sys.argv[0]];setup_runtime(args.backend);NAMESPACE_ISOLATION=args.isolate_namespace
    initial=fingerprints();(out/'source-inputs.json').write_text(json.dumps(initial,indent=2),encoding='utf-8')
    if args.mode in ('contracts','all'):contract_tests(out)
    if args.mode in ('browser','all'):browser_tests(args.native,out)
    if args.mode in ('surfaces','all'):surface_tests(args.native,out)
    if args.mode in ('upgrade','all'):upgrade_tests(args.native,out)
    assert initial==fingerprints(),'Runtime sources changed during acceptance; rerun against the final frozen candidate'
    if BACKEND_SELECTION:
        manifest=RUNTIME_ROOT/'workbench-release.json'
        assert sha(manifest)==BACKEND_SELECTION['manifest_sha256']
        for relative,expected in json.loads(manifest.read_text(encoding='utf-8'))['files'].items():
            assert sha(RUNTIME_ROOT/relative)==expected,relative
    native_dir,native_manifest=candidate(args.native)
    summary={'passed':True,'mode':args.mode,'python':sys.executable,'python_version':sys.version,
        'native':{'release':native_manifest['release'],'manifest_sha256':sha(native_dir/'native-manifest.json')},
        'backend':BACKEND_SELECTION or str(RUNTIME_ROOT),'runtime_inputs_sha256':sha(out/'source-inputs.json'),
        'harness_sha256':sha(__file__),'real_AI_calls':0,'real_platform_writes':0,
        'mobile_validation':'browser simulation','source_stable_throughout_run':True}
    (out/'validation.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
