"""TEMP HTTPS browser acceptance of the actual native Easel chat service.

The real owner routes, session store, skills, plans, file registration and
version business hooks run. Only harnesses.adapter inference is synthetic.
No production database, selector, model process or platform write is used.
"""
from __future__ import annotations
import argparse
import asyncio
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit,parse_qs,urlencode
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class SyntheticAdapter:
    def __init__(self,image):self.image=image;self.requests=[];self.prefix_next=False
    async def run(self,request,emit,ask,bind):
        from easel.harnesses.base import HarnessError
        self.requests.append(request)
        native=request.native_id or 'temp-native-'+request.session_key
        bind(native);request.on_native_turn(native,'temp-native-turn-'+str(len(self.requests)))
        emit('thinking','TEMP 假执行器核对准确输入。')
        if '## 本轮冻结输入\n' not in request.prompt or json.JSONDecoder().raw_decode(request.prompt.split('## 本轮冻结输入\n')[-1])[0]['session_task']=='discuss':emit('token','TEMP 原生会话实际事件：')
        await asyncio.sleep(.25)
        if 'UNKNOWN_RECEIPT' in request.prompt:
            raise HarnessError('TEMP 模拟已发送但回执未知；禁止重发')
        if 'HOLD_FOR_REFRESH' in request.prompt:await asyncio.sleep(2)
        if '## 本轮冻结输入\n' not in request.prompt:
            emit('token','这是隔离讨论输出，未调用模型。');return
        payload=json.JSONDecoder().raw_decode(request.prompt.split('## 本轮冻结输入\n')[-1])[0]
        if payload['session_task']=='discuss':emit('token','这是隔离讨论输出，未调用模型。');return
        folder=Path(payload['output_directory']);folder.mkdir(parents=True,exist_ok=True)
        assert folder.is_relative_to(request.cwd),folder
        format=payload['session_task'] if payload['session_task'] in ('poster','article') else (payload.get('work') or {}).get('format','poster')
        if format=='article':
            body=folder/'正文.md';body.write_text('# TEMP 文章标题\n\n这是实际 TEMP 文件，保留准确来源与边界。',encoding='utf-8')
            product=folder/'文章交付.json';product.write_text(json.dumps({'schema_version':1,'article_type':'general','title':'TEMP 文章标题','body_file':'正文.md','sources':[]},ensure_ascii=False),encoding='utf-8')
            paths=[product,body]
        else:
            product=folder/'成品.png';product.write_bytes(self.image)
            copy=folder/'标题与配文.txt';copy.write_text('TEMP 贴图标题\n\n这是隔离假执行器写入的真实文件，不代表真实模型质量。',encoding='utf-8');paths=[product,copy]
        emit('activity','TEMP fileChange：已写入准确本轮输出目录')
        if self.prefix_next:emit('token','TEMP 说明：以下是准确本轮交付文件。\n');self.prefix_next=False
        result=json.dumps({'deliverables':[str(path) for path in paths],'production_result':{'schema_version':1,'status':'completed'}},ensure_ascii=False)
        emit('token',result[:30]);emit('token',result[30:])


@contextmanager
def isolated(native,image):
    import uvicorn
    from easel import harnesses
    from easel_workbench.application import create_app
    from easel_workbench.skill_catalog import ProjectSkillCatalog
    from easel_workbench.runtime.desk import Store,SOURCES
    from easel_workbench.runtime.toolbox_store import Toolbox
    from easel_workbench.runtime.studio_service import StudioService
    with tempfile.TemporaryDirectory(prefix='easel-native-chat-browser-',ignore_cleanup_errors=True) as temporary:
        root=Path(temporary).resolve()
        for skill in ProjectSkillCatalog(ROOT).entries():shutil.copytree(ROOT/'skills/builtin'/skill['id'],root/'skills/builtin'/skill['id'])
        shutil.copytree(ROOT/'skills/shared/workbench',root/'skills/shared/workbench')
        workspace=root/'agents/workspace';workspace.mkdir(parents=True)
        (workspace/'AGENTS.md').write_text('TEMP shared Easel workspace only.',encoding='utf-8')
        manifest=json.loads((native/'native-manifest.json').read_text(encoding='utf-8'));release=manifest['release']
        shutil.copytree(native,root/'native-releases'/release)
        data=root/'data';data.mkdir()
        (data/'active-native.json').write_text(json.dumps({'release':release,'manifest_sha256':sha(native/'native-manifest.json')}),encoding='utf-8')
        store=Store(data/'desk.sqlite');box=Toolbox(store,root)
        studio_project=root/'studio-project';studio_project.mkdir()
        studio=StudioService(box,project=studio_project,root=root)
        source=next(iter(SOURCES))
        store.ingest({'schema_version':1,'source_job':source,'feed_id':'aihot','run_id':'native-news','run_at':'2026-10-30T08:30:00+08:00','final_text':'TEMP','articles':[{'title':'TEMP 新闻来源','body':'完整新闻原字。保留素材、来源和未确认状态。','url':'https://example.com/native-easel'}]})
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];origin=f'https://localhost:{port}'
        class Auth:
            data={'origin':origin,'host':f'localhost:{port}','secret':'A'*32}
            expired=False
            def session(self,token):return {'csrf':'fixture','until':9999999999} if token=='fixture-owner' and not self.expired else None
        auth=Auth();adapter=SyntheticAdapter(image)
        application=create_app(store=store,auth=auth,box=box,root=root,studio=studio)
        openssl='C:/Program Files/Git/usr/bin/openssl.exe'
        subprocess.run([openssl,'req','-x509','-newkey','rsa:2048','-nodes','-keyout',str(root/'key.pem'),'-out',str(root/'cert.pem'),'-days','1','-subj','/CN=localhost'],check=True,capture_output=True)
        server=uvicorn.Server(uvicorn.Config(application,ssl_keyfile=str(root/'key.pem'),ssl_certfile=str(root/'cert.pem'),access_log=False,log_level='error',timeout_graceful_shutdown=3))
        def serve():
            with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:runner.run(server.serve(sockets=[sock]))
        with patch.object(harnesses,'adapter',lambda runtime:adapter):
            thread=threading.Thread(target=serve,daemon=True);thread.start();deadline=time.monotonic()+20
            while not server.started:
                assert thread.is_alive() and time.monotonic()<deadline,'TEMP server did not start';time.sleep(.05)
            fixture={'root':root,'origin':origin,'auth':auth,'adapter':adapter,'app':application,'box':box,'source':source}
            try:yield fixture
            finally:
                if fixture.get('close_clients'):fixture['close_clients']()
                server.should_exit=True;thread.join(timeout=10)
                if thread.is_alive():server.force_exit=True;thread.join(timeout=5)
                sock.close()


def wait_history(page,origin,sid,previous_turn=None,files=False):
    deadline=time.monotonic()+20
    while time.monotonic()<deadline:
        result=page.request.get(origin+'/api/chat/sessions/'+sid).json()
        last=(result['session'].get('messages') or [{}])[-1]
        if last.get('role')=='assistant' and last.get('turnId')!=previous_turn and last.get('status')=='completed' and (not files or last.get('output_files')):
            return result
        page.wait_for_timeout(100)
    raise AssertionError({'reason':'accurate native turn did not finish','history':result})


def turn_view(page,history):
    # Official ChatPage renders one direct wrapper per history message. Wait
    # inside this exact turn so a previous product cannot satisfy readiness.
    return page.locator('.chat-thread > div').nth(len(history['session']['messages'])-1)


def direct_send_checks(browser,f,out,report,check,expect):
    """Only the changed send/parameter surfaces; no unrelated page matrix."""
    for profile,width,mobile in [('desktop',1280,False),('mobile',390,True)]:
        context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':900},is_mobile=mobile,has_touch=mobile)
        context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
        page=context.new_page();page.set_default_timeout(20000);errors=[];requests=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.on('request',lambda request:requests.append({'path':urlsplit(request.url).path,'method':request.method,'body':request.post_data_json if request.method=='POST' and request.post_data else None}))
        page.goto(f['origin']+'/native/chat?fresh=1',wait_until='domcontentloaded');page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.startsWith('/chat/')")
        sid=parse_qs(urlsplit(page.url).query)['path'][0].split('/chat/')[1].split('?')[0]
        textarea=page.get_by_role('textbox',name='对话输入');expect(textarea).to_be_visible()
        previous=None
        def choose(label,text):
            textarea.fill('/'+label+' '+text);expect(page.get_by_role('menuitem',name='/'+label,exact=False)).to_be_visible(timeout=20000);textarea.press('Enter');expect(page.get_by_text(label+' · v',exact=False)).to_be_visible();expect(textarea).to_have_value(text)
        def parameters(container,turn):
            panel=container.locator('details.chat-production-details').filter(has=page.locator('summary',has_text='制作参数')).last
            expect(panel.locator('summary').first).to_have_text('制作参数');panel.locator('summary').first.click()
            expect(panel.locator('p').filter(has_text='作品版本：'+turn['turnId'])).to_be_visible()
            exported=page.request.get(f['origin']+'/api/creative/prompts/'+turn['turnId']);assert exported.ok,exported.text()
            execution=exported.json()['execution_prompt'];snapshot=execution['creator_snapshot']
            expect(panel.locator('p').filter(has_text='画像：'+snapshot['profile']['name'])).to_be_visible()
            for skill in snapshot['skills']:expect(panel.locator('p').filter(has_text=skill['name']+' · v'+str(skill['version']))).to_be_visible()
            panel.get_by_text('完整实际制作指令',exact=True).click();panel.get_by_text('制作指令 SHA-256',exact=True).click()
            records=panel.locator('pre').all_text_contents();assert execution['body'] in records and execution['sha256'] in records
            with f['box'].store.connect() as c:saved=json.loads(c.execute('SELECT document FROM easel_chat_turns WHERE id=?',(turn['turnId'],)).fetchone()[0])
            assert execution['body']==saved['actual_prompt'] and execution['sha256']==saved['actual_prompt_sha256']
            assert [(s['id'],s['version']) for s in snapshot['skills']]==[(s['id'],s['version']) for s in saved['snapshot']['skills']]
            assert panel.evaluate('element=>element.scrollWidth<=element.clientWidth+1')
            panel.get_by_text('完整实际制作指令',exact=True).click();panel.get_by_text('制作指令 SHA-256',exact=True).click();panel.scroll_into_view_if_needed()
            page.screenshot(path=str(out/(profile+'-'+str(saved['snapshot']['task'])+'-parameters.png')))
            panel.locator('summary').first.click()
            return saved
        for format,label in [('poster','生成贴图'),('article','撰写文章')]:
            raw='本轮一次发送 '+format+' '+profile;choose(label,raw);before=len(f['adapter'].requests);start=len(requests);plan=None
            if format=='poster':
                held=[];handler=lambda route:held.append(route);page.route('**/api/chat/plan',handler)
                page.get_by_role('button',name='发送',exact=True).evaluate('button=>{button.click();button.click()}')
                deadline=time.monotonic()+10
                while not held and time.monotonic()<deadline:page.wait_for_timeout(30)
                assert len(held)==1 and len(f['adapter'].requests)==before
                expect(textarea).to_have_value(raw)
                response=held[0].fetch();assert response.ok,response.text();plan=response.json();held[0].fulfill(response=response);page.unroute('**/api/chat/plan',handler)
                check(profile,'rapid clicks retain input and share one plan and one production request')
            else:page.get_by_role('button',name='发送',exact=True).click()
            expect(page.get_by_role('dialog',name='确认本次制作方案')).not_to_be_visible()
            history=wait_history(page,f['origin'],sid,previous,files=True);turn=history['session']['messages'][-1];previous=turn['turnId']
            page.wait_for_function("sid=>!JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid)||'{}').pending",arg=sid)
            try:expect(page.locator('.artifact-gallery')).to_have_count(1 if format=='poster' else 2)
            except AssertionError:
                (out/'delivery-failure.json').write_text(json.dumps({'history':history,'body':page.locator('body').inner_text(),'errors':errors},ensure_ascii=False,indent=2),encoding='utf-8')
                page.screenshot(path=str(out/'delivery-failure.png'),full_page=True)
                raise
            sent=[request for request in requests[start:] if request['path']=='/api/chat/stream' and request['method']=='POST'];planned=[request for request in requests[start:] if request['path']=='/api/chat/plan' and request['method']=='POST']
            assert len(sent)==len(planned)==1 and len(f['adapter'].requests)==before+1
            assert sent[0]['body']['turnId']==planned[0]['body']['turnId']==turn['turnId']
            if plan:assert sent[0]['body']['context']['plan_token']==plan['plan_token']
            if format=='poster':assert not any(request['path'].startswith('/api/creative/prompts/') for request in requests),'parameters should load only on expansion'
            expect(page.locator('.artifact-gallery').last.locator('.artifact-count')).to_have_text('1 / 2')
            turn_view(page,history).get_by_role('button',name='查看产物',exact=True).click()
            expect(page.get_by_role('button',name='修改这版')).to_be_visible()
            saved=parameters(page.locator('.ew-work-preview'),turn)
            assert saved['snapshot']['task']==format and turn['business_status']=='completed'
            report['simulated_executions'].append({'profile':profile,'format':format,'turn_id':turn['turnId'],'snapshot_sha256':saved['snapshot']['snapshot_sha256'],'actual_file_ids':[file['id'] for file in turn['output_files']]})
            check(profile,format+' sends directly without a modal and exposes exact frozen parameters by the product')
            page.goto(f['origin']+'/native/chat/'+sid)
            expect(textarea).to_be_enabled()
        turn_view(page,history).get_by_role('button',name='查看产物',exact=True).click();expect(page.get_by_role('button',name='修改这版')).to_be_visible()
        parameters(page.locator('.ew-work-preview'),turn);check(profile,'work product view shows the same exact version parameters')
        page.get_by_role('button',name='修改这版').click();page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.includes('action=change')")
        textarea=page.get_by_role('textbox',name='对话输入');page.wait_for_function("sid=>JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid)||'{}').command?.action_id==='change'",arg=sid)
        textarea.fill('修改准确版本，一次发送 '+profile);page.get_by_role('button',name='发送',exact=True).click();expect(page.get_by_role('dialog',name='确认本次制作方案')).not_to_be_visible()
        history=wait_history(page,f['origin'],sid,previous,files=True);turn=history['session']['messages'][-1];previous=turn['turnId']
        page.wait_for_function("sid=>!JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid)||'{}').pending",arg=sid);expect(page.locator('.artifact-gallery')).to_have_count(3)
        turn_view(page,history).get_by_role('button',name='查看产物',exact=True).click();expect(page.get_by_role('button',name='修改这版')).to_be_visible()
        saved=parameters(page.locator('.ew-work-preview'),turn);assert saved['snapshot']['task']=='change'
        report['simulated_executions'].append({'profile':profile,'format':'change','turn_id':turn['turnId'],'snapshot_sha256':saved['snapshot']['snapshot_sha256'],'actual_file_ids':[file['id'] for file in turn['output_files']]})
        check(profile,'version modification sends once without a modal and keeps its exact parent')
        page.screenshot(path=str(out/(profile+'-direct-send.png')))
        page.goto(f['origin']+'/native/chat/'+sid);textarea=page.get_by_role('textbox',name='对话输入');expect(textarea).to_be_enabled();choose('生成贴图','UNKNOWN_RECEIPT '+profile)
        before=len(f['adapter'].requests);start=len(requests);page.get_by_role('button',name='发送',exact=True).click();status=page.get_by_role('status').filter(has_text='正在恢复原任务状态');expect(status.first).to_be_visible()
        pending=page.evaluate("sid=>JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid)).pending.turnId",sid)
        expect(page.get_by_role('button',name='核对原请求')).to_have_count(0);page.reload(wait_until='domcontentloaded');expect(status.first).to_be_visible()
        assert page.evaluate("sid=>JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid)).pending.turnId",sid)==pending and len(f['adapter'].requests)==before+1
        assert len([request for request in requests[start:] if request['path']=='/api/chat/stream' and request['method']=='POST'])==1
        expect(page.get_by_role('button',name='发送',exact=True)).to_be_disabled();expect(page.locator('.chat-turn-outputs').last.get_by_text('制作参数',exact=True)).to_have_count(0)
        check(profile,'unknown production receipt preserves the turn and never resends during automatic recovery or refresh')
        assert not errors,errors;context.close()
    assert len(report['checks'])==12


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--native',required=True);parser.add_argument('--out',required=True);parser.add_argument('--backend');parser.add_argument('--mode',choices=('all','direct-send'),default='all');args=parser.parse_args()
    if args.backend:
        backend=Path(args.backend).resolve();manifest=json.loads((backend/'workbench-release.json').read_text(encoding='utf-8'))
        assert all(sha(backend/member)==digest for member,digest in manifest['files'].items())
        sys.path.insert(0,str(backend))
    else:sys.path.insert(0,str(ROOT))
    from playwright.sync_api import sync_playwright,expect
    out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True);native=Path(args.native).resolve();manifest=json.loads((native/'native-manifest.json').read_text(encoding='utf-8'))
    assert all(sha(native/member)==digest for member,digest in manifest['files'].items())
    report={'passed':False,'native':{'release':manifest['release'],'manifest_sha256':sha(native/'native-manifest.json')},'backend':{'directory':args.backend or str(ROOT),'manifest_sha256':sha(Path(args.backend)/'workbench-release.json') if args.backend else None},'checks':[],'simulated_executions':[],'real_AI_calls':0,'real_platform_writes':0,'physical_mobile_device_tested':False,'mode':args.mode,'harness_sha256':sha(__file__)}
    def check(profile,name):
        report['checks'].append({'profile':profile,'check':name,'passed':True});print('PASS',profile,name,flush=True)
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
            image_page=browser.new_page(viewport={'width':600,'height':400});image_page.set_content('<div style="background:#eee;padding:40px">TEMP native product</div>');image=image_page.screenshot();image_page.close()
            with isolated(native,image) as f:
                f['close_clients']=lambda:[context.close() for context in browser.contexts]
                if args.mode=='direct-send':direct_send_checks(browser,f,out,report,check,expect)
                else:
                    for profile,width,mobile in [('desktop',1280,False),('mobile',390,True)]:
                        context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':900},is_mobile=mobile,has_touch=mobile,color_scheme='dark' if mobile else 'light')
                        context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
                        page=context.new_page();errors=[];page.set_default_timeout(20000);page.on('pageerror',lambda error:errors.append(str(error)));page.on('response',lambda response:print('HTTP',response.status,response.url,flush=True) if response.status>=400 else None);page.on('console',lambda message:print('CONSOLE',message.type,message.text,flush=True) if message.type=='error' else None)
                        before_create=len(f['adapter'].requests);page.goto(f['origin']+'/native/chat?fresh=1',wait_until='domcontentloaded');print('START',page.url,flush=True);page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.startsWith('/chat/')",timeout=20000)
                        textarea=page.get_by_role('textbox',name='对话输入');expect(textarea).to_be_visible(timeout=20000)
                        sid=parse_qs(urlsplit(page.url).query)['path'][0].split('/chat/')[1].split('?')[0];metadata=f['root']/'outputs/_sessions'/sid/'workbench.json'
                        assert list((f['root']/'outputs/_sessions').rglob('*')), 'session metadata missing'
                        assert len(f['adapter'].requests)==before_create, 'creating metadata must not start a model turn'
                        check(profile,'new chat persists server session before any send')
                        textarea.fill('IME原字');textarea.dispatch_event('keydown',{'key':'Enter','code':'Enter','isComposing':True,'keyCode':229});assert len(f['adapter'].requests)==before_create;expect(textarea).to_have_value('IME原字');check(profile,'IME confirmation does not send a native turn')
                        page.get_by_role('button',name='看看能做什么',exact=True).click();expect(page.get_by_role('dialog',name='能做的都在这')).to_be_visible();page.go_back();expect(page.get_by_role('dialog',name='能做的都在这')).not_to_be_visible();expect(textarea).to_have_value('IME原字');check(profile,'browser back closes the official brush menu and preserves input')
                        textarea.fill('先讨论本次目标 '+profile);textarea.press('Enter');expect(page.get_by_text('这是隔离讨论输出，未调用模型。',exact=False)).to_be_visible(timeout=20000)
                        page.wait_for_function("sid=>!JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid)||'{}').pending",arg=sid);expect(textarea).to_be_enabled(timeout=20000);check(profile,'default discussion uses native session and real token events')
                        for format,label in [('poster','生成贴图'),('article','撰写文章')]:
                            f['adapter'].prefix_next=(profile=='mobile' and format=='poster');before=len(f['adapter'].requests);prior=page.request.get(f['origin']+'/api/chat/sessions/'+sid).json()['session']['messages'][-1]['turnId'];textarea.fill('/'+label+'  原始'+label+'材料 '+profile+'  ');textarea.press('Enter')
                            expect(page.get_by_text(label+' · v',exact=False)).to_be_visible();expect(textarea).to_have_value(' 原始'+label+'材料 '+profile+'  ')
                        
                            if format=='poster':page.locator('input[type=file]').set_input_files({'name':'TEMP原始素材.txt','mimeType':'text/plain','buffer':b'Original TEMP evidence bytes'})
                            expect(page.get_by_role('button',name='发送',exact=True)).to_be_enabled(timeout=20000);textarea.press('Enter');expect(page.get_by_role('dialog',name='确认本次制作方案')).not_to_be_visible();expect(textarea).to_have_value('',timeout=20000)
                            history=wait_history(page,f['origin'],sid,prior,files=True);turn=history['session']['messages'][-1]
                            expect(turn_view(page,history).get_by_role('region',name='对话产物预览')).to_be_visible(timeout=20000);expect(turn_view(page,history).get_by_role('button',name='查看产物',exact=True)).to_be_visible(timeout=20000);page.wait_for_function("sid=>!JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid)||'{}').pending",arg=sid);expect(textarea).to_be_enabled(timeout=20000)
                            assert turn['output_files'] and turn['business_status']=='completed',turn
                            with f['box'].store.connect() as c:
                                saved=json.loads(c.execute('SELECT document FROM easel_chat_turns WHERE id=?',(turn['turnId'],)).fetchone()[0])
                            assert saved['hook_status']=='completed',saved
                            assert saved['snapshot']['task']==format
                            if format=='poster':assert 'outputs' in str(f['adapter'].requests[-1].prompt) and 'materials' in str(f['adapter'].requests[-1].prompt)
                            assert f['adapter'].requests[-1].native_id=='temp-native-'+sid
                            for file in turn['output_files']:assert page.request.get(f['origin']+'/api/files/'+file['id']).ok
                            if format=='poster':
                                expect(page.locator('.artifact-gallery img').last).to_be_visible(timeout=20000)
                                page.wait_for_function('()=>Array.from(document.querySelectorAll(".artifact-gallery img")).every(i=>i.complete&&i.naturalWidth>0)')
                            check(profile,format+' slash action sends the exact frozen plan once and shows actual files in the same chat')
                            report['simulated_executions'].append({'profile':profile,'format':format,'turn_id':turn['turnId'],'work':saved['work'],'snapshot_sha256':saved['snapshot']['snapshot_sha256'],'actual_file_ids':[file['id'] for file in turn['output_files']]})
                        assert len(history['linked_works'])==2
                        page.screenshot(path=str(out/(profile+'-native-products.png')),full_page=True)
                        # Production version details must return to this same native session.
                        turn_view(page,history).get_by_role('button',name='查看产物',exact=True).click();expect(page.get_by_role('button',name='修改这版')).to_be_visible(timeout=20000)
                        if mobile:page.locator('.ew-work-tabs').get_by_role('button',name='对话',exact=True).click()
                        page.get_by_text('本轮操作与技能',exact=True).click();page.get_by_label('发送方式',exact=True).select_option('feedback');feedback='只记录这版原话：背景太乱 '+profile
                        page.get_by_role('textbox',name='对话输入').fill(feedback);before_feedback=len(f['adapter'].requests)
                        with page.expect_response(lambda response:'/actions' in response.url and response.request.method=='POST') as recorded:page.get_by_role('button',name='发送',exact=True).click()
                        assert recorded.value.status==200 and len(f['adapter'].requests)==before_feedback
                        with f['box'].store.connect() as c:row=c.execute('SELECT candidate_id,status FROM toolbox_jobs WHERE kind=? AND text=?',('feedback',feedback)).fetchone()
                        assert row['candidate_id']==turn['turnId'] and row['status']=='completed'
                        check(profile,'native version feedback records exact raw words locally without a model turn')
                        if mobile:page.locator('.ew-work-tabs').get_by_role('button',name='成品',exact=True).click()
                        page.get_by_role('button',name='修改这版').click();page.wait_for_function("id=>new URLSearchParams(location.search).get('path')?.startsWith('/chat/'+id+'?')",arg=sid,timeout=20000)
                        assert 'action=change' in parse_qs(urlsplit(page.url).query)['path'][0] and 'version=' in parse_qs(urlsplit(page.url).query)['path'][0]
                        textarea=page.get_by_role('textbox',name='对话输入');expect(textarea).to_be_visible();textarea.fill('只改这一版，原版保留 '+profile);textarea.press('Enter')
                        expect(page.get_by_role('dialog',name='确认本次制作方案')).not_to_be_visible()
                        expect(textarea).to_be_enabled(timeout=20000)
                        page.wait_for_function('()=>document.querySelectorAll(".chat-turn-outputs").length>=3')
                        changed=wait_history(page,f['origin'],sid,turn['turnId'],files=True);last=changed['session']['messages'][-1]
                        with f['box'].store.connect() as c:saved=json.loads(c.execute('SELECT document FROM easel_chat_turns WHERE id=?',(last['turnId'],)).fetchone()[0])
                        assert saved['snapshot']['task']=='change' and saved['hook_status']=='completed' and last['business_status']=='completed',saved
                        page.wait_for_function("sid=>!JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid)||'{}').pending",arg=sid)
                        check(profile,'exact native version modification stays in same session and creates a separate version')
                        report['simulated_executions'].append({'profile':profile,'format':'change','turn_id':last['turnId'],'work':saved['work'],'snapshot_sha256':saved['snapshot']['snapshot_sha256'],'actual_file_ids':[file['id'] for file in last['output_files']]})
                        # Refresh an active real service job: browser only reconnects GET.
                        page.goto(f['origin']+'/native/chat/'+sid);textarea=page.get_by_role('textbox',name='对话输入');expect(textarea).to_be_enabled(timeout=20000)
                        prior=changed['session']['messages'][-1]['turnId'];before=len(f['adapter'].requests);textarea.fill('HOLD_FOR_REFRESH '+profile);expect(page.get_by_role('button',name='发送',exact=True)).to_be_enabled(timeout=20000);textarea.press('Enter');expect(textarea).to_have_value('',timeout=20000);page.reload(wait_until='domcontentloaded')
                        textarea=page.get_by_role('textbox',name='对话输入');wait_history(page,f['origin'],sid,prior);page.wait_for_function("sid=>!JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid)||'{}').pending",arg=sid);expect(textarea).to_be_enabled(timeout=20000);assert len(f['adapter'].requests)==before+1
                        check(profile,'refresh reconnects existing native turn without a duplicate submission')
                        textarea.fill('  未发送长草稿\n'+('原字保留 '+profile+'\n')*250);raw=textarea.input_value();page.reload(wait_until='domcontentloaded');textarea=page.get_by_role('textbox',name='对话输入');expect(textarea).to_have_value(raw,timeout=20000)
                        page.wait_for_function("()=>{const e=document.querySelector('textarea[aria-label=\"对话输入\"]');return e&&e.scrollHeight>e.clientHeight}");page.get_by_role('textbox',name='对话输入').evaluate('(e)=>{e.scrollTop=e.scrollHeight}');assert textarea.evaluate('e=>e.scrollHeight>e.clientHeight')
                        check(profile,'long raw draft survives reload and scrolls inside the native composer')
                        textarea.fill('UNKNOWN_RECEIPT '+profile);before=len(f['adapter'].requests);page.get_by_role('button',name='发送',exact=True).click()
                        status=page.get_by_role('status').filter(has_text='正在恢复原任务状态');expect(status.first).to_be_visible(timeout=20000);expect(page.get_by_role('button',name='核对原请求')).to_have_count(0);page.reload(wait_until='domcontentloaded');expect(status.first).to_be_visible(timeout=20000)
                        assert len(f['adapter'].requests)==before+1
                        check(profile,'unknown native receipt stays blocked during automatic recovery and refresh without replay')
                        page.screenshot(path=str(out/(profile+'-unknown-receipt.png')),full_page=True)
                        # Existing domain pages remain real authenticated views.
                        before_pages=len(f['adapter'].requests)
                        # The official dashboard greeting follows local time;
                        # the selected profile opens its named detail page.
                        for route,heading in [('/toolbox',re.compile(r'^(?:夜深了|上午好|中午好|下午好|晚上好) 👋$')),('/works','内容库'),('/toolbox?section=profiles','油猪大侠'),('/settings','设置'),('/toolbox?section=skills','技能库')]:
                            page.goto(f['origin']+'/native/?'+urlencode({'path':route}),wait_until='domcontentloaded');expect(page.get_by_role('heading',name=heading,exact=True).first).to_be_visible(timeout=20000)
                        page.locator('.skill-card').filter(has=page.locator('.skill-card-rawname',has_text='content-production')).click();expect(page.get_by_role('button',name='版本与试用',exact=True)).to_be_visible(timeout=20000);page.get_by_role('button',name='版本与试用',exact=True).click();expect(page.get_by_role('combobox',name='技能版本')).to_be_visible(timeout=20000)
                        page.goto(f['origin']+'/native/?'+urlencode({'path':'/toolbox?section=skills'}));page.get_by_role('button',name='整理经验',exact=True).click();expect(page.get_by_role('heading',name='整理经验',exact=True)).to_be_visible(timeout=20000)
                        assert len(f['adapter'].requests)==before_pages
                        check(profile,'native skills retain version trial experience and existing domain page entry points')
                        assert not errors,errors
                        context.close()
                    # Fresh browser follows old new-work links by copying inputs to a true session.
                    context=browser.new_context(ignore_https_errors=True,viewport={'width':1280,'height':900});context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}]);page=context.new_page()
                    page.goto(f['origin']+'/native/?path=%2Farticles%2Fnew');page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.startsWith('/chat/')",timeout=20000);expect(page.get_by_text('撰写文章 · v',exact=False)).to_be_visible(timeout=20000);check('desktop','legacy new article link creates native session with exact article action')
                    # A news link copies the old raw draft, then explicitly trials a candidate.
                    with f['box'].store.connect() as c:aid=c.execute('SELECT id FROM articles LIMIT 1').fetchone()[0]
                    original=f['box'].creator.detail('skill','content-production');candidate=f['box'].creator.command({'id':'native-browser-trial','action':'skill-draft','skill_id':'content-production','base_version':original['version'],'prompt':original['prompt']+'\nTEMP明确候选试用。','reason':'仅TEMP浏览器验收，不发布。'})['result']['skill']
                    oldkey='new:news:'+aid;oldinput={'title':' 原始旧题目 ','material':' 第一行原字\n第二行原字 ','guidance':' 原始制作要求 ','files':[]}
                    page.evaluate('a=>localStorage.setItem("toolbox:draft:"+a.key,JSON.stringify(a.value))',{'key':oldkey,'value':oldinput})
                    target='/posters/new?'+urlencode({'article':aid,'draft':oldkey,'skill':'content-production','skill_version':candidate['version'],'trial':'1'})
                    before_news=len(f['adapter'].requests);page.goto(f['origin']+'/native/?'+urlencode({'path':target}));page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.startsWith('/chat/')")
                    news_sid=parse_qs(urlsplit(page.url).query)['path'][0].split('/chat/')[1];textarea=page.get_by_role('textbox',name='对话输入');expect(textarea).to_have_value(' 原始旧题目 \n\n 第一行原字\n第二行原字 \n\n 原始制作要求 ');expect(page.get_by_text('本轮带入所选新闻的原始来源',exact=True)).to_be_visible();assert len(f['adapter'].requests)==before_news
                    assert page.evaluate('key=>JSON.parse(localStorage.getItem("toolbox:draft:"+key)).material',oldkey)==oldinput['material']
                    page.get_by_role('button',name='发送',exact=True).click();expect(page.get_by_role('dialog',name='确认本次制作方案')).not_to_be_visible()
                    news_history=wait_history(page,f['origin'],news_sid,files=True);news_turn=news_history['session']['messages'][-1]
                    with f['box'].store.connect() as c:news_saved=json.loads(c.execute('SELECT document FROM easel_chat_turns WHERE id=?',(news_turn['turnId'],)).fetchone()[0])
                    assert next(skill['version'] for skill in news_saved['snapshot']['skills'] if skill['id']=='content-production')==candidate['version'] and news_saved['snapshot']['trial']
                    payload=json.JSONDecoder().raw_decode(news_saved['actual_prompt'].split('## 本轮冻结输入\n')[-1])[0];assert payload['source_article']['id']==aid and payload['source_article']['url']=='https://example.com/native-easel' and payload['source_article']['provenance']
                    report['simulated_executions'].append({'profile':'desktop','format':'poster-trial-news','turn_id':news_turn['turnId'],'work':news_saved['work'],'snapshot_sha256':news_saved['snapshot']['snapshot_sha256'],'actual_file_ids':[file['id'] for file in news_turn['output_files']]})
                    page.wait_for_function("sid=>!JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid)||'{}').pending",arg=news_sid)
                    check('desktop','legacy news draft is preserved while native explicit candidate freezes actual source provenance')
                    # Expiry preserves user input and never invokes another model.
                    textarea=page.get_by_role('textbox',name='对话输入');textarea.fill('  401仍须保留原字  ');before=len(f['adapter'].requests);f['auth'].expired=True;textarea.press('Enter');expect(page.get_by_role('alert').filter(has_text='登录已过期，输入已保留。')).to_be_visible(timeout=20000);assert len(f['adapter'].requests)==before
                    assert page.evaluate('Object.entries(localStorage).some(([k,v])=>k.includes("draft")&&v.includes("401仍须保留原字"))')
                    check('desktop','owner 401 preserves exact draft and makes no model call')
                    context.close()
            browser.close()
        assert len(report['simulated_executions'])==(6 if args.mode=='direct-send' else 7),report['simulated_executions']
        assert sha(__file__)==report['harness_sha256'],'Browser harness changed during run'
        if args.backend:
            modules={name:str(Path(module.__file__).resolve()) for name,module in sys.modules.items() if (name=='easel' or name.startswith('easel.') or name=='easel_workbench' or name.startswith('easel_workbench.')) and getattr(module,'__file__',None)}
            assert modules and all(Path(path).is_relative_to(backend) for path in modules.values()),modules
            assert all(sha(backend/member)==digest for member,digest in json.loads((backend/'workbench-release.json').read_text(encoding='utf-8'))['files'].items())
            report.update(module_count=len(modules),module_roots_valid=True)
        report['passed']=True
    except BaseException as error:
        report['error']=repr(error)
        if 'page' in locals():
            try:report['page']={'url':page.url,'body':page.locator('body').inner_text(),'pageerrors':errors if 'errors' in locals() else []};page.screenshot(path=str(out/'failure.png'),full_page=True)
            except Exception:pass
        raise
    finally:
        (out/'harness.py').write_bytes(Path(__file__).read_bytes())
        report['evidence']={path.name:sha(path) for path in out.glob('*.png')}
        (out/'native-browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
