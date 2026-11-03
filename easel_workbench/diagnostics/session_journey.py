"""Frozen zero-model browser acceptance of session creation and recovery.

The same module is used by deployment acceptance and the external daily worker.
All business writes are in a new TEMP application; no production session, model
or platform is contacted. Faults use the actual admission gate, network loss,
and a bounded worker barrier. The application source/DOM/CSS are never replaced.
"""
from __future__ import annotations

if __name__ == '__main__' and not __package__:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))

import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit
from unittest.mock import patch
import uuid


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def read(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def verify_package(directory, filename):
    directory=Path(directory).resolve();manifest=read(directory/filename)
    for name,digest in manifest['files'].items():
        raw=directory/name;member=raw.resolve()
        if raw.is_symlink() or not member.is_relative_to(directory) or sha(member)!=digest:
            raise ValueError('immutable_journey_member_changed')
    return manifest


@contextmanager
def temporary_app(backend,native):
    """Only setup for this diagnostic: a real app and a no-model sentinel."""
    import uvicorn
    from easel import harnesses
    from easel.harnesses.codex import CodexAdapter
    from easel_workbench.application import create_app
    from easel_workbench.runtime.desk import Store
    from easel_workbench.runtime.toolbox_store import Toolbox
    from easel_workbench.runtime.studio_service import StudioService
    from easel_workbench.skill_catalog import ProjectSkillCatalog
    class NoModel:
        descriptor=CodexAdapter.descriptor
        def __init__(self):self.requests=[]
        async def run(self,request,*args,**kwargs):
            self.requests.append(request)
            raise AssertionError('browser journey must not run a model')
    sentinel=NoModel()
    with tempfile.TemporaryDirectory(prefix='easel-session-journey-',ignore_cleanup_errors=True) as temporary:
        root=Path(temporary).resolve()
        for skill in ProjectSkillCatalog(backend).entries():
            shutil.copytree(backend/'skills/builtin'/skill['id'],root/'skills/builtin'/skill['id'])
        shutil.copytree(backend/'skills/shared/workbench',root/'skills/shared/workbench')
        workspace=root/'agents/workspace';workspace.mkdir(parents=True)
        (workspace/'AGENTS.md').write_text('TEMP zero-model session creation acceptance.',encoding='utf-8')
        selected={'release':native.name,'manifest_sha256':sha(native/'native-manifest.json')}
        shutil.copytree(native,root/'native-releases'/native.name)
        (root/'data').mkdir();(root/'data/active-native.json').write_text(json.dumps(selected),encoding='utf-8')
        state=root/'.local/workbench-deployment';state.mkdir(parents=True)
        def admit(ready):
            temporary=state/'admission.json.new'
            temporary.write_text(json.dumps({'workers':ready}),encoding='utf-8');os.replace(temporary,state/'admission.json')
        admit(True)
        store=Store(root/'data/desk.sqlite');box=Toolbox(store,root)
        project=root/'studio-project';project.mkdir();studio=StudioService(box,project=project,root=root)
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];origin=f'https://localhost:{port}'
        class Auth:
            data={'origin':origin,'host':f'localhost:{port}','secret':'J'*32}
            expired=False
            def session(self,token):return {'csrf':'fixture','until':9999999999} if token=='fixture-owner' and not self.expired else None
        with patch.dict(os.environ,{'EASEL_WORKBENCH_ADMISSION':'1'}),patch.object(harnesses,'adapter',lambda runtime:sentinel):
            app=create_app(store=store,auth=Auth(),box=box,root=root,studio=studio)
            openssl=shutil.which('openssl') or 'C:/Program Files/Git/usr/bin/openssl.exe'
            subprocess.run([openssl,'req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(root/'key.pem'),
                '-out',str(root/'cert.pem'),'-days','1','-subj','/CN=localhost'],check=True,capture_output=True)
            server=uvicorn.Server(uvicorn.Config(app,ssl_keyfile=str(root/'key.pem'),ssl_certfile=str(root/'cert.pem'),
                access_log=False,log_level='error',timeout_graceful_shutdown=3))
            def serve():
                with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:runner.run(server.serve(sockets=[sock]))
            thread=threading.Thread(target=serve,daemon=True);thread.start();deadline=time.monotonic()+25
            while not server.started:
                if not thread.is_alive() or time.monotonic()>deadline:raise AssertionError('TEMP browser app startup failed')
                time.sleep(.02)
            value=SimpleNamespace(root=root,origin=origin,app=app,store=store,admit=admit,model=sentinel)
            try:yield value
            finally:
                admit(True);server.should_exit=True;thread.join(timeout=8)
                if thread.is_alive():server.force_exit=True;thread.join(timeout=3)
                sock.close()


def session_count(f):
    with f.store.connect() as c:return c.execute('SELECT count(*) FROM easel_chat_sessions').fetchone()[0]


def session_path(page):
    return parse_qs(urlsplit(page.url).query).get('path',[''])[0]


def wait_session(page):
    try:
        page.wait_for_function(r"()=>/^\/chat\/[^/?]+/.test(new URLSearchParams(location.search).get('path')||'')",timeout=25000)
    except BaseException:
        # Preserve the failing observable state before fixture cleanup. These
        # are TEMP operation identifiers only; never dump browser credentials,
        # complete localStorage, drafts, message text or attachment contents.
        try:
            out=getattr(page,'_journey_evidence_dir',None)
            if out:
                name='navigation-failure-'+uuid.uuid4().hex[:8]
                flows=page.evaluate("()=>Object.keys(localStorage).filter(k=>k.startsWith('toolbox:draft:session-open:')).map(k=>{const v=JSON.parse(localStorage.getItem(k));return {flow_id:v.flow_id,operation_id:v.operation_id,phase:v.phase,session_id:v.session_id}})")
                Path(out,name+'.json').write_text(json.dumps({'url':page.url,'flows':flows},ensure_ascii=False,indent=2),encoding='utf-8')
                page.screenshot(path=str(Path(out,name+'.png')))
        except Exception:
            pass
        raise
    path=session_path(page);sid=path.split('/chat/',1)[1].split('?',1)[0]
    from playwright.sync_api import expect
    expect(page.locator('.chat-page')).to_be_visible()
    return sid


def run(backend,native,out,*,mode='full'):
    backend=Path(backend).resolve();native=Path(native).resolve();out=Path(out).resolve();out.mkdir(parents=True,exist_ok=True)
    verify_package(backend,'workbench-release.json');verify_package(native,'native-manifest.json')
    report={'schema':1,'passed':False,'binding':{'runtime':{'release':backend.name,'manifest_sha256':sha(backend/'workbench-release.json')},
        'native':{'release':native.name,'manifest_sha256':sha(native/'native-manifest.json')}},'checks':[],'screenshots':{},
        'page_errors':[],'blocked_requests':[],'requests':[],'real_model_calls':0,'production_data_access':False,
        'physical_device_tested':False,'HTTP_response_mocked':False,'DOM_or_CSS_mocked':False,
        'faults':['real TEMP admission gate','abort response after committed create','accepted-worker barrier','seed persisted legacy intent'],
        'UI_clock_advanced_in_timeout_case':mode=='full'}
    def mark(case,name,**extra):
        report['checks'].append({'case':case,'name':name,'passed':True,**extra});print('PASS '+case+' '+name,flush=True)
    def shot(page,case):
        name=case+'.png';page.screenshot(path=str(out/name));report['screenshots'][name]=sha(out/name)
    def page_context(browser,f,profile,*,storage=None,seed=None):
        name,width,height,touch,theme=profile
        context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':height},is_mobile=touch,
            has_touch=touch,service_workers='block',**({'storage_state':storage} if storage else {}))
        context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f.origin,'secure':True,'httpOnly':True,'sameSite':'Strict'}])
        context.add_init_script("localStorage.setItem('native:theme',"+json.dumps(theme)+");")
        if seed:
            context.add_init_script("if(!localStorage.getItem('TEMP-journey-seeded')){"+
                ''.join('localStorage.setItem('+json.dumps(k)+','+json.dumps(json.dumps(v,ensure_ascii=False))+');' for k,v in seed.items())+
                "localStorage.setItem('TEMP-journey-seeded','1');}")
        page=context.new_page();page._journey_evidence_dir=out;page.set_default_timeout(20000);page.on('pageerror',lambda error:report['page_errors'].append(str(error)))
        allowed={'/api/chat/sessions','/api/usage/events','/api/usage','/api/diagnostics/client-operation','/api/diagnostics/operations'}
        def guard(route):
            request=route.request;target=urlsplit(request.url)
            report['requests'].append({'path':target.path,'method':request.method})
            if (target.hostname not in ('localhost','127.0.0.1') or request.method not in ('GET','HEAD','OPTIONS')
                    and target.path not in allowed and not (target.path.startswith('/api/chat/sessions/operations/') and target.path.endswith('/resolve'))):
                report['blocked_requests'].append({'path':target.path,'method':request.method});route.abort();return
            route.continue_()
        context.route('**/*',guard)
        return context,page
    profiles=[('desktop-light',1280,900,False,'light'),('mobile-dark',390,844,True,'dark')]
    if mode=='full':profiles += [('mobile-small-light',360,780,True,'light'),('mobile-wide-dark',430,932,True,'dark'),('mobile-landscape-light',844,390,True,'light')]
    try:
        from playwright.sync_api import sync_playwright,expect
        with sync_playwright() as pw,temporary_app(backend,native) as f:
            browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
            fresh=f.origin+'/native/?'+urlencode({'path':'/chat?fresh=1'})
            for profile in profiles:
                name=profile[0]
                # A real middleware refusal is definitely unaccepted, then the
                # same browser must recover without clearing its local storage.
                context,page=page_context(browser,f,profile);before=session_count(f);refused=[]
                try:
                    f.admit(False)
                    def admitted_response(response):
                        if urlsplit(response.url).path=='/api/chat/sessions' and response.request.method=='POST' and response.status==503:
                            refused.append(response.json());f.admit(True)
                    page.on('response',admitted_response);page.goto(fresh,wait_until='domcontentloaded');sid=wait_session(page)
                    assert refused and refused[0].get('operation_state')=='not_accepted'
                    assert session_count(f)==before+1
                    mark(name,'real unaccepted503 recovers to one exact session',session_id=sid);shot(page,name+'-503-recovered')
                finally:f.admit(True);context.close()
                # Discard a real successful response after the actual transaction.
                context,page=page_context(browser,f,profile);before=session_count(f);lost=[]
                try:
                    def lose(route):
                        if route.request.method=='POST' and not lost:
                            answer=route.fetch();body=answer.json();lost.append(body);route.abort('connectionreset')
                        else:route.continue_()
                    page.route('**/api/chat/sessions',lose);page.goto(fresh,wait_until='domcontentloaded');sid=wait_session(page)
                    assert lost and sid==(lost[0].get('session') or lost[0].get('result',{}).get('session',{}))['id']
                    assert session_count(f)==before+1
                    mark(name,'lost committed response opens original session without duplicate',session_id=sid)
                finally:context.close()
                # Retained legacy unknown state is repaired by the real resolve
                # transaction; the old delayed command must remain prohibited.
                operation=str(uuid.uuid4());request={'action':'create','profile_id':'oil-pig','id':operation}
                seed={'toolbox:draft:native:pending:chat:create':{'operation':{'scope':'chat:create','path':'/api/chat/sessions','id':operation,'body':request,'uncertain':True}}}
                context,page=page_context(browser,f,profile,seed=seed);before=session_count(f)
                try:
                    page.goto(fresh,wait_until='domcontentloaded');sid=wait_session(page)
                    csrf=context.request.get(f.origin+'/api/config').json()['csrf']
                    late=context.request.post(f.origin+'/api/chat/sessions',data=request,headers={'Origin':f.origin,'X-CSRF-Token':csrf,'X-Operation-ID':operation})
                    assert late.status in (400,409) and session_count(f)==before+1
                    with f.store.connect() as c:
                        sealed=c.execute('SELECT state FROM easel_chat_creation_intents WHERE id=?',(operation,)).fetchone()
                        assert sealed and sealed[0]=='sealed_not_accepted'
                    mark(name,'old pending resolves safely and a delayed original cannot create',session_id=sid)
                finally:context.close()
                # Pause the actual metadata worker after durable acceptance.
                original=f.app.state.chat.create_session;gate=threading.Event();entered=threading.Event()
                def hold(value):entered.set();assert gate.wait(25),'TEMP creation gate timed out';return original(value)
                f.app.state.chat.create_session=hold
                context,page=page_context(browser,f,profile);before=session_count(f)
                try:
                    page.goto(fresh,wait_until='domcontentloaded');expect(page.locator('.ew-session-open-card')).to_be_visible()
                    assert page.locator('html').get_attribute('data-theme')==profile[4]
                    expect(page.get_by_text('连接暂时中断，正在恢复操作状态。输入已保留。',exact=True)).to_have_count(0)
                    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                    for button in page.locator('.ew-session-open-actions .btn').all():
                        assert button.bounding_box()['height']>=44
                    assert entered.is_set();storage=context.storage_state();url=page.url
                    shot(page,name+'-accepted-card');context.close();gate.set()
                    context,page=page_context(browser,f,profile,storage=storage);page.goto(url,wait_until='domcontentloaded');sid=wait_session(page)
                    assert session_count(f)==before+1
                    mark(name,'closing WebView context and reopening preserved intent opens same accepted session',session_id=sid)
                finally:gate.set();f.app.state.chat.create_session=original;context.close()
                if mode=='full':
                    original=f.app.state.chat.create_session;gate=threading.Event();entered=threading.Event()
                    def hold_leave(value):entered.set();assert gate.wait(25),'TEMP leave gate timed out';return original(value)
                    f.app.state.chat.create_session=hold_leave
                    context,page=page_context(browser,f,profile);before=session_count(f)
                    try:
                        page.goto(fresh,wait_until='domcontentloaded');expect(page.locator('.ew-session-open-card')).to_be_visible()
                        page.get_by_role('button',name='返回工作台',exact=True).click();gate.set()
                        page.wait_for_function("()=>Object.keys(localStorage).some(k=>k.startsWith('toolbox:draft:session-open:')&&JSON.parse(localStorage.getItem(k)).session_id)")
                        assert session_path(page)=='/toolbox' and session_count(f)==before+1
                        mark(name,'late completion does not steal navigation after leaving')
                    finally:gate.set();f.app.state.chat.create_session=original;context.close()
                    context,page=page_context(browser,f,profile)
                    try:
                        page.clock.install()
                        page.route('**/api/chat/sessions',lambda route:route.abort('connectionreset') if route.request.method=='POST' else route.continue_())
                        page.goto(fresh,wait_until='domcontentloaded');page.clock.run_for(1000)
                        expect(page.locator('.ew-session-open-card')).to_be_visible()
                        page.clock.run_for(31000)
                        expect(page.get_by_role('heading',name='暂时无法确认创建结果',exact=True)).to_be_visible()
                        assert page.locator('html').get_attribute('data-theme')==profile[4]
                        expect(page.get_by_text('连接暂时中断，正在恢复操作状态。输入已保留。',exact=True)).to_have_count(0)
                        expect(page.locator('.ew-session-open-icon.is-working')).to_have_count(0)
                        page.get_by_role('button',name='查看详情',exact=True).click()
                        expect(page.get_by_role('dialog',name='对话创建记录')).to_be_visible();page.keyboard.press('Escape')
                        expect(page.get_by_role('dialog',name='对话创建记录')).to_have_count(0)
                        shot(page,name+'-unknown-30s');mark(name,'bounded unknown state stops spinner and original Drawer handles keyboard')
                    finally:context.close()
            report['real_model_calls']=len(f.model.requests);browser.close()
        report['runtime_modules']={name:{'file':str(Path(module.__file__).resolve()),'sha256':sha(module.__file__)} for name,module in list(sys.modules.items()) if (name=='easel' or name.startswith('easel.') or name=='easel_workbench' or name.startswith('easel_workbench.')) and getattr(module,'__file__',None)}
        report['module_roots_valid']=all(Path(v['file']).is_relative_to(backend) for v in report['runtime_modules'].values())
        report['passed']=bool(report['checks']) and not report['real_model_calls'] and not report['page_errors'] and not report['blocked_requests'] and report['module_roots_valid']
    except BaseException as error:
        report['error_type']=type(error).__name__
        # Test-only diagnostics contain no actual user data, but still keep the
        # operator report to fixed metadata rather than exception payloads.
        print('FAIL '+type(error).__name__,flush=True)
        raise
    finally:
        (out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend',required=True,type=Path);parser.add_argument('--native',required=True,type=Path)
    parser.add_argument('--out',required=True,type=Path);parser.add_argument('--mode',choices=('full','daily'),default='full')
    args=parser.parse_args();result=run(args.backend,args.native,args.out,mode=args.mode)
    print(json.dumps({'passed':result['passed'],'checks':len(result['checks']),'real_model_calls':result['real_model_calls']}))
    return 0 if result['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
