"""Real TEMP backend / frozen frontend official profile and skill contracts.

Only the model adapter is synthetic. Authentication, original components,
configuration vault, revision conflicts, chat admission/SSE/question receipts,
file registration, and SQLite persistence use the selected backend unchanged.
No production account, model, credential, or publication is used.
"""
import argparse
import asyncio
import importlib.util
import json
import re
import shutil
import sys
import uuid
from pathlib import Path
from urllib.parse import urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]


async def skill_run(self, request, emit, ask, bind):
    if '## 本轮冻结输入\n' not in request.prompt:
        return await self.original_run(request, emit, ask, bind)
    payload = json.JSONDecoder().raw_decode(request.prompt.split('## 本轮冻结输入\n')[-1])[0]
    if payload['session_task'] != 'native':
        return await self.original_run(request, emit, ask, bind)
    assert payload['authorization']['publish'] is False
    assert payload['selected_skills'][0]['id'] == 'ai-image-gen'
    self.requests.append(request)
    native = request.native_id or 'TEMP-official-'+request.session_key
    bind(native)
    request.on_native_turn(native, 'TEMP-official-turn-'+str(len(self.requests)))
    if 'TEMP_QUESTION' in request.prompt:
        answer = await ask([{'questionId': 'official-confirm', 'header': 'TEMP 执行核对',
                            'question': '保留原输入并继续？', 'multiSelect': False,
                            'options': [{'label': '保留原输入', 'description': '仅 TEMP 假执行器'}]}])
        assert answer == {'official-confirm': ['保留原输入']}, answer
    folder = Path(payload['output_directory'])/'products'
    folder.mkdir(parents=True, exist_ok=True)
    (folder/'TEMP-官方技能.png').write_bytes(self.image)
    emit('token', 'TEMP 官方技能实际回执完成。')
    await asyncio.sleep(.1)


def main():
    global h
    parser = argparse.ArgumentParser()
    parser.add_argument('--native', required=True, type=Path)
    parser.add_argument('--backend', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--profiles', choices=['all', 'desktop', 'mobile'], default='all')
    args = parser.parse_args()
    native, backend, out = args.native.resolve(), args.backend.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(backend))
    # The fixture's SyntheticAdapter imports its descriptor at class definition.
    # Select the backend before loading it, or a frozen run could silently mix source modules.
    spec = importlib.util.spec_from_file_location('official_ui_temp_fixture', ROOT/'tests/workbench_native_browser.py')
    h = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(h)
    h.ROOT = backend
    from playwright.sync_api import sync_playwright, expect
    expect.set_options(timeout=30000)
    before = {'native': h.sha(native/'native-manifest.json'),
              'backend': h.sha(backend/'workbench-release.json') if (backend/'workbench-release.json').exists() else None}
    report = {'passed': False, 'checks': [], 'real_AI_calls': 0, 'real_platform_writes': 0,
              'physical_device_tested': False, 'native': str(native), 'backend': str(backend),
              'manifests': before, 'harness_sha256': h.sha(__file__)}

    def check(profile, text):
        report['checks'].append({'profile': profile, 'check': text, 'passed': True})
        print('PASS', profile, text, flush=True)

    def goto(page, f, path):
        page.goto(f['origin']+'/native/?'+urlencode({'path': path}), wait_until='domcontentloaded')

    def profile_checks(page, f, profile, requests):
        form = {'name': ' TEMP-'+profile+'-原生画像 ', 'platforms': ['公众号'], 'accountStage': '已有账号',
                'links': {'公众号': 'https://example.test/'+profile+'?raw=1'},
                'direction': ' 原始方向 '+profile+' ', 'reason': '原始经历\n第二行 ',
                'goal': ' 原始目标 ', 'formats': ' 图文 ', 'likes': '原始对标\n保留换行',
                'tone': '干货实用', 'avoid': ' 不扩大授权\n原文保留 '}
        initial = page.request.get(f['origin']+'/api/creator/bootstrap').json()
        goto(page, f, '/toolbox?section=profiles&item=new')
        modal = page.locator('.overlay .modal').filter(has=page.get_by_role('heading', name='配置账号画像', exact=True))
        expect(modal).to_be_visible()
        modal.get_by_placeholder('如：科技数码达人').fill(form['name'])
        modal.get_by_role('button', name='公众号', exact=True).click()
        modal.get_by_role('button', name='已有账号', exact=True).click()
        modal.get_by_role('button', name='下一步', exact=True).click()
        modal.get_by_placeholder('https://…').fill(form['links']['公众号'])
        page.screenshot(path=str(out/(profile+'-wizard-links.png')), animations='disabled')
        modal.get_by_role('button', name='下一步', exact=True).click()
        modal.get_by_placeholder('如：平价护肤测评').fill(form['direction'])
        modal.locator('textarea').fill(form['reason'])
        modal.get_by_placeholder('涨粉 / 变现 / 个人品牌 / 引流私域').fill(form['goal'])
        modal.get_by_placeholder('图文 / 短视频 / 中长视频 / 长文').fill(form['formats'])
        modal.get_by_role('button', name='下一步', exact=True).click()
        modal.locator('textarea').first.fill(form['likes'])
        modal.get_by_role('button', name='干货实用', exact=True).click()
        modal.get_by_placeholder('如：不接医疗功效、不做虚假宣传').fill(form['avoid'])
        modal.get_by_role('button', name='上一步', exact=True).click()
        expect(modal.get_by_placeholder('如：平价护肤测评')).to_have_value(form['direction'])
        expect(modal.locator('textarea')).to_have_value(form['reason'])
        modal.get_by_role('button', name='下一步', exact=True).click()
        expect(modal.locator('textarea').first).to_have_value(form['likes'])
        page.wait_for_function("()=>JSON.parse(localStorage.getItem('toolbox:draft:creator:profile:wizard')||'null')")
        draft = page.evaluate("()=>JSON.parse(localStorage.getItem('toolbox:draft:creator:profile:wizard'))")
        # DraftRepository may envelope its document; assert the exact raw form, not guessed storage shape.
        assert json.dumps(form, ensure_ascii=False, sort_keys=True) in json.dumps(draft, ensure_ascii=False, sort_keys=True)
        modal.get_by_role('button', name='×', exact=True).click()
        expect(modal).to_have_count(0)
        assert not [r for r in requests if r['method']=='POST' and r['path']=='/api/profile/build']
        goto(page, f, '/toolbox?section=profiles&item=new')
        expect(modal.get_by_placeholder('如：不接医疗功效、不做虚假宣传')).to_have_value(form['avoid'])
        expect(modal.locator('textarea').first).to_have_value(form['likes'])
        page.screenshot(path=str(out/(profile+'-wizard-reopened.png')), animations='disabled')
        with page.expect_response(lambda r: urlsplit(r.url).path=='/api/profile/build' and r.request.method=='POST') as built:
            modal.get_by_role('button', name='生成画像', exact=True).click()
        assert built.value.ok, built.value.text()
        result = built.value.json()
        assert result['created'] and result['async'] is False and result['name'].startswith('profile-')
        assert result['name'] != form['name'].strip()
        page.wait_for_function('(id)=>new URLSearchParams(new URLSearchParams(location.search).get("path").split("?")[1]).get("item")===id', arg=result['name'])
        assert len([r for r in requests if r['method']=='POST' and r['path']=='/api/profile/build']) == 1
        current = page.request.get(f['origin']+'/api/creator/bootstrap').json()
        assert len(current['profiles']) == len(initial['profiles'])+1
        saved = next(p for p in current['profiles'] if p['id']==result['name'])
        assert saved['name']==form['name'].strip()
        with f['box'].store.connect() as c:
            row = c.execute("SELECT content FROM native_profile_documents WHERE profile_id=? AND filename='onboarding.json'", (result['name'],)).fetchone()
        assert row and json.loads(row[0]) == form
        assert page.evaluate("()=>localStorage.getItem('toolbox:draft:creator:profile:wizard')") is None
        assert not f['adapter'].requests
        check(profile, 'four original wizard steps, backward navigation, exact draft reopen, one stable-ID submission, raw SQLite form, no model call')

    def skill_checks(page, f, profile, requests):
        settings = f['app'].state.settings
        env_path = f['root']/'.env'
        env_before = env_path.read_bytes() if env_path.exists() else None
        secret = lambda suffix: 'TEMP-official-'+profile+'-'+suffix+'-0123456789'
        headers = {'Origin': f['origin'], 'X-CSRF-Token': page.request.get(f['origin']+'/api/config').json()['csrf']}

        def current():
            response = page.request.get(f['origin']+'/api/skill/ai-image-gen')
            assert response.ok, response.text()
            return response.json()

        def update(value, revision):
            operation = 'TEMP-official-'+str(uuid.uuid4())
            response = page.request.post(f['origin']+'/api/env', headers={**headers, 'X-Operation-Id': operation},
                                         data={'id': operation, 'expected_revision': revision,
                                               'updates': {'IMG_API_KEY': value, 'IMG_BASE_URL': 'https://example.test/v1'}})
            assert response.ok, response.text()
            return current()['configuration_revision']

        def open_skill():
            goto(page, f, '/toolbox?section=skills')
            page.get_by_placeholder('搜索技能名或描述…').fill('ai-image-gen')
            page.locator('.skill-card').filter(has=page.get_by_text('AI 生图',exact=True)).click()
            drawer = page.locator('.drawer').filter(has=page.locator('.skill-detail-rawname').filter(has_text=re.compile('^ai-image-gen$')))
            expect(drawer.get_by_role('button', name='执行', exact=True)).to_be_visible()
            return drawer

        initial = current()
        assert initial['needsApi'] and not initial['apiConfigured'], 'TEMP environment unexpectedly preconfigured'
        drawer = open_skill()
        expect(drawer.get_by_role('button', name='执行', exact=True)).to_be_disabled()
        key_input = drawer.locator('.provider-block input[type="password"]').first
        expect(key_input).to_be_visible()
        # First write captures revision 0 as immutable baseline 1, then appends 2.
        # Later writes append exactly one revision to their viewed parent.
        viewed_revision = current()['configuration_revision']
        key_input.fill(secret('A'))
        drawer.get_by_placeholder('请输入 IMG_BASE_URL').fill('https://example.test/v1')
        with page.expect_response(lambda r: urlsplit(r.url).path=='/api/env' and r.request.method=='POST') as saved:
            drawer.get_by_role('button', name='保存到 .env', exact=True).click()
        assert saved.value.ok, saved.value.text()
        expect(key_input).to_have_value('')
        expect(drawer.get_by_text('已保存 ✓',exact=True)).to_be_visible()
        revision_a = current()['configuration_revision']
        assert revision_a == (2 if viewed_revision==0 else viewed_revision+1), {'viewed':viewed_revision,'saved':revision_a}
        assert settings.environment()['IMG_API_KEY']==secret('A')
        revision_b = update(secret('B'), revision_a)
        key_input.fill(secret('C'))
        with page.expect_response(lambda r: urlsplit(r.url).path=='/api/env' and r.request.method=='POST') as stale:
            drawer.get_by_role('button', name='保存到 .env', exact=True).click()
        assert stale.value.status == 409
        expect(key_input).to_have_value(secret('C'))
        assert settings.environment()['IMG_API_KEY']==secret('B')
        drawer.get_by_role('button', name='关闭', exact=True).click()
        drawer = open_skill()
        key_input = drawer.locator('.provider-block input[type="password"]').first
        key_input.fill(secret('C'))
        with page.expect_response(lambda r: urlsplit(r.url).path=='/api/env' and r.request.method=='POST') as saved:
            drawer.get_by_role('button', name='保存到 .env', exact=True).click()
        assert saved.value.ok
        expect(key_input).to_have_value('')
        expect(drawer.get_by_text('已保存 ✓',exact=True)).to_be_visible()
        revision_c = current()['configuration_revision']
        assert revision_c == revision_b+1
        assert (env_path.read_bytes() if env_path.exists() else None) == env_before
        assert all(secret(s) not in json.dumps(current()) for s in ['A','B','C'])
        check(profile, 'original API editor uses actual vault revisions; stale visible parent rejects 409 and preserves typed input; no .env overwrite or secret echo')

        first = 'TEMP_QUESTION 原始技能输入\n第二行：不扩大授权'
        drawer.get_by_placeholder('输入内容，例如主题 / 素材 / 要求…').fill(first)
        with page.expect_response(lambda r: urlsplit(r.url).path=='/api/chat/submit' and r.request.method=='POST') as accepted:
            drawer.get_by_role('button', name='执行', exact=True).click()
        assert accepted.value.status == 202, accepted.value.text()
        question = drawer.locator('.question-card')
        expect(question).to_be_visible(timeout=90000)
        revision_d = update(secret('D'), revision_c)
        question.get_by_role('button').filter(has=page.locator('strong', has_text='保留原输入')).click()
        question.get_by_role('button', name='提交', exact=True).click()
        expect(drawer.locator('.skill-result')).to_contain_text('TEMP 官方技能实际回执完成。', timeout=60000)
        assert len(f['adapter'].requests)==1
        assert f['adapter'].requests[0].env['IMG_API_KEY']==secret('C')
        assert len([r for r in requests if r['method']=='POST' and r['path']=='/api/chat/submit']) == 1
        assert len([r for r in requests if r['method']=='POST' and r['path']=='/api/chat/question/answer']) == 1
        assert '/toolbox' in page.evaluate('new URLSearchParams(location.search).get("path")')
        page.screenshot(path=str(out/(profile+'-actual-skill-result.png')), animations='disabled')
        second = 'TEMP_SECOND 显式新一次执行'
        drawer.get_by_placeholder('输入内容，例如主题 / 素材 / 要求…').fill(second)
        with page.expect_response(lambda r: urlsplit(r.url).path=='/api/chat/submit' and r.request.method=='POST') as accepted:
            drawer.get_by_role('button', name='执行', exact=True).click()
        assert accepted.value.status == 202
        expect(drawer.locator('.skill-result')).to_contain_text('TEMP 官方技能实际回执完成。', timeout=60000)
        assert len(f['adapter'].requests)==2 and f['adapter'].requests[1].env['IMG_API_KEY']==secret('D')
        with f['box'].store.connect() as c:
            turns = [json.loads(row[0]) for row in c.execute('SELECT document FROM easel_chat_turns ORDER BY rowid')]
            artifacts = [dict(row) for row in c.execute('SELECT task_id,name,path FROM artifacts ORDER BY rowid')]
        assert len(turns)==2
        for turn, message, revision in zip(turns, [first,second], [revision_c,revision_d]):
            assert turn['message']==message and turn['status']=='completed' and turn['hook_status']=='completed'
            assert turn['snapshot']['task']=='native' and turn['snapshot']['active_skill_ids']==['ai-image-gen']
            assert turn['execution_settings']['revision']==revision
            assert turn['snapshot']['skills'][0]['source_revision']==turn['context']['skill_revision']
            files=[row for row in artifacts if row['task_id']==turn['id']]
            assert len(files)==1 and files[0]['name']=='TEMP-官方技能.png'
            assert Path(files[0]['path']).read_bytes()==f['adapter'].image
        drawer.get_by_role('button', name='关闭', exact=True).click()
        open_skill()
        page.wait_for_timeout(1200)
        assert len(f['adapter'].requests)==2
        assert len([r for r in requests if r['method']=='POST' and r['path']=='/api/chat/submit']) == 2
        assert any(r['path'].startswith('/api/chat/jobs/') and r['path'].endswith('/stream') for r in requests)
        check(profile, 'actual SessionRuntime 202/SSE/question answer/file hook, one submission per explicit run, immutable configuration C then fresh D, reopen never replays')

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True,
                                         args=['--ignore-certificate-errors'])
            image_page = browser.new_page(); image_page.set_content('<h1>TEMP original UI output</h1>')
            image = image_page.screenshot(); image_page.close()
            for profile, width, mobile in [('desktop',1280,False), ('mobile',390,True)]:
                if args.profiles != 'all' and profile != args.profiles: continue
                with h.isolated(native, image) as f:
                    f['close_clients'] = lambda: [context.close() for context in browser.contexts]
                    for folder in (backend/'skills/builtin').iterdir():
                        if folder.is_dir() and (folder/'SKILL.md').is_file():
                            shutil.copytree(folder, f['root']/'skills/builtin'/folder.name, dirs_exist_ok=True,
                                            ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
                    shutil.copytree(backend/'skills/shared',f['root']/'skills/shared',dirs_exist_ok=True,
                                    ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
                    f['adapter'].original_run = f['adapter'].run
                    f['adapter'].run = skill_run.__get__(f['adapter'])
                    context = browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':900},
                                                  is_mobile=mobile,has_touch=mobile,color_scheme='dark' if mobile else 'light')
                    context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],
                                         'secure':True,'httpOnly':True,'sameSite':'Strict'}])
                    page=context.new_page();page.set_default_timeout(30000)
                    requests=[];errors=[]
                    page.on('request',lambda r:requests.append({'path':urlsplit(r.url).path,'method':r.method}))
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    try:
                        profile_checks(page,f,profile,requests)
                        skill_checks(page,f,profile,requests)
                    except Exception:
                        page.screenshot(path=str(out/(profile+'-failure.png')),animations='disabled')
                        with f['box'].store.connect() as c:
                            exists=c.execute("SELECT 1 FROM sqlite_master WHERE name='easel_chat_turns'").fetchone()
                            turns=[json.loads(row[0]) for row in c.execute('SELECT document FROM easel_chat_turns')] if exists else []
                        diagnostic={'requests':requests,'page_errors':errors,'adapter_count':len(f['adapter'].requests),
                                    'adapter_markers':['TEMP_QUESTION' in request.prompt for request in f['adapter'].requests],
                                    'turns':[{key:turn.get(key) for key in ['id','session_id','status','error','error_type','delivery_state','questions','hook_status','hook_error_type'] } for turn in turns]}
                        (out/(profile+'-diagnostic.json')).write_text(json.dumps(diagnostic,ensure_ascii=False,indent=2),encoding='utf-8')
                        raise
                    assert not errors,errors
                    context.close()
            browser.close()
        loaded=[Path(module.__file__).resolve() for name,module in sys.modules.items()
                if (name=='easel' or name.startswith('easel.') or name=='easel_workbench' or name.startswith('easel_workbench.'))
                and getattr(module,'__file__',None)]
        assert loaded and all(path.is_relative_to(backend) for path in loaded)
        assert before['native']==h.sha(native/'native-manifest.json')
        if before['backend']:assert before['backend']==h.sha(backend/'workbench-release.json')
        report['module_roots_valid']=True;report['passed']=True
    except Exception as error:
        report['error']=repr(error)
        raise
    finally:
        report['evidence']={p.name:h.sha(p) for p in out.glob('*.png')}
        (out/'browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'error':report.get('error')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
