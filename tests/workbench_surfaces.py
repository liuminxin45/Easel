# Adapted from the legacy TEMP surface harness; action labels come from the live skill registry.
"""Functional Easel workbench checks on TEMP HTTPS, with no AI or publishing."""
import argparse,json,pathlib
from unittest.mock import patch
from playwright.sync_api import sync_playwright,expect
import native_browser as h
from creator_browser import prepare_project
from creator_acceptance_fixture import seed


def run(args):
    candidate,manifest=h.candidate_directory(args.candidate);out=pathlib.Path(args.evidence).resolve();out.mkdir(parents=True,exist_ok=True)
    checks=[];errors=[];report={'release':manifest['release'],'manifest_sha256':h.digest(candidate/'native-manifest.json'),'backend':h.BACKEND,'harness_sha256':h.digest(pathlib.Path(__file__)),
        'checks':checks,'errors':errors,'real_AI_calls':0,'real_platform_writes':0,'physical_device_tested':False,'scope':'functional desktop/mobile use; no pixel, display-resolution or OS-account tests'}
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path=args.browser,headless=not args.headed,args=['--ignore-certificate-errors'])
            raw=h.poster_bytes(browser)
            with patch.object(h,'prepare_project',prepare_project),h.isolated_service(candidate,manifest,raw) as f:
                ids=seed(f,raw);accounts=f['box'].easel_accounts;accounts.autostart=True;accounts.runner=lambda p:{'loggedIn':True,'provider_user_id':'synthetic-'+p['session']['id'],'name':'合成平台身份'}
                state=h.authenticate(browser,f,out,errors);origin=f['origin'];box=f['box'];entry=box.creator.detail('skill',box.creator.bootstrap()['task_policy']['poster']['entry_skills'][0]);poster_launch=next(a['label'] for a in entry['launch_actions'] if a['task']=='poster')
                for profile in args.profiles.split(','):
                    mobile=profile.startswith('android');context=browser.new_context(ignore_https_errors=True,storage_state=state,color_scheme='dark' if mobile else 'light',**h.PROFILES[profile])
                    context.add_init_script(h.AUDIT_SCRIPT)
                    context.route('**/*',lambda route:route.continue_() if route.request.url.startswith(origin+'/') or route.request.url.startswith(('data:','blob:')) else route.abort())
                    page=context.new_page();page.set_default_timeout(20000);page.on('pageerror',lambda e:errors.append(e.stack or str(e)))
                    def go(path):
                        if page.url.startswith(origin):page.wait_for_function("()=>!document.querySelector('dialog[open]')&&!history.state?.nativeLayer")
                        h.ready(page,origin,path)
                    def check(name):checks.append({'profile':profile,'check':name,'passed':True})
                    def post_response(path,action):
                        with page.expect_response(lambda r:path in r.url and r.request.method=='POST') as response:action()
                        assert response.value.status==200,response.value.text()
                        return response.value.json()
                    try:
                        go('/toolbox');expect(page.get_by_role('heading',name='今天，想创作点什么？')).to_be_visible()
                        if mobile:page.get_by_role('button',name='打开工作导航',exact=True).click()
                        nav=page.get_by_role('navigation',name='工作台导航')
                        assert nav.get_by_role('button').all_text_contents()==['工作台','对话','技能库','内容库','账号','画像']
                        if mobile:page.get_by_role('button',name='关闭工作导航',exact=True).click()
                        page.screenshot(path=str(out/(profile+'-home.png')),animations='disabled');check('six-entry-easel-shell-and-workbench')
                        go('/toolbox?section=skills');page.get_by_role('button',name='内容生产 content-production',exact=False).click()
                        expect(page.get_by_role('dialog',name='内容生产',exact=True)).to_be_visible()
                        page.get_by_role('button',name=poster_launch,exact=True).click()
                        material='合成输入：从读者的问题开始，保留准确来源，不提交真实模型。'
                        page.get_by_label('素材与目标',exact=True).fill(material)
                        page.get_by_label('主题',exact=True).fill('Easel 合成内容生产 '+profile)
                        with f['store'].connect() as c:before=c.execute('SELECT count(*) FROM toolbox_jobs').fetchone()[0]
                        preview=post_response('/api/creative/preview',lambda:page.get_by_role('button',name='查看制作方案',exact=True).click())
                        expect(page.get_by_role('dialog',name='确认本次制作方案')).to_be_visible()
                        with f['store'].connect() as c:assert c.execute('SELECT count(*) FROM toolbox_jobs').fetchone()[0]==before
                        assert 'content-production' in json.dumps(preview['execution_prompt'])
                        page.get_by_role('button',name='返回修改',exact=True).click();expect(page.get_by_label('素材与目标',exact=True)).to_have_value(material)
                        post_response('/api/creative/preview',lambda:page.get_by_role('button',name='查看制作方案',exact=True).click())
                        created=post_response('/api/works',lambda:page.get_by_role('button',name='确认并开始制作',exact=True).click())
                        wid=created.get('work_id') or created.get('id');assert wid,created
                        expect(page.get_by_role('heading',level=1,name='Easel 合成内容生产 '+profile)).to_be_visible()
                        with f['store'].connect() as c:
                            run=json.loads(c.execute('SELECT document FROM creator_task_runs WHERE id=?',(wid,)).fetchone()[0]);assert run['workflow']['entry_skills'][0]['id']=='content-production'
                            assert c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0]==0
                        check('content-production-skill-real-preview-freeze-and-existing-task-receipt')
                        go('/posters/new?draft=easel-title-only-'+profile);page.get_by_label('主题',exact=True).fill('只有标题也能开始 '+profile)
                        title_only=post_response('/api/creative/preview',lambda:page.get_by_role('button',name='查看制作方案',exact=True).click())
                        assert title_only['input']['title']=='只有标题也能开始 '+profile and not title_only['input']['material'];page.get_by_role('button',name='返回修改',exact=True).click();check('title-only-input-retains-original-production-contract')
                        go('/posters/new?draft=easel-file-only-'+profile)
                        page.locator('input[type=file]').set_input_files({'name':'synthetic-reference.png','mimeType':'image/png','buffer':raw})
                        file_only=post_response('/api/creative/preview',lambda:page.get_by_role('button',name='查看制作方案',exact=True).click())
                        assert file_only['input']['files'] and not file_only['input']['material'];page.get_by_role('button',name='返回修改',exact=True).click();check('attachment-only-input-retains-original-production-contract')
                        go('/articles/new?draft=easel-article-'+profile)
                        page.get_by_label('素材与目标',exact=True).fill('合成文章素材，确认写作和配图技能版本。')
                        article_preview=post_response('/api/creative/preview',lambda:page.get_by_role('button',name='查看制作方案',exact=True).click())
                        assert article_preview['input']['format']=='article';page.get_by_role('button',name='返回修改',exact=True).click();check('article-uses-same-production-skill')
                        go('/posters/'+ids['work']+'?version='+ids['response'])
                        if mobile:page.locator('#easel-main').get_by_role('button',name='对话',exact=True).click()
                        page.get_by_label('发送方式',exact=True).select_option('feedback')
                        page.get_by_label('对话输入',exact=True).fill('合成反馈原话：请保留来源。')
                        feedback=post_response('/actions',lambda:page.get_by_role('button',name='发送',exact=True).click())
                        with f['store'].connect() as c:
                            rows=c.execute("SELECT candidate_id,status FROM toolbox_jobs WHERE kind='feedback' AND text=?",('合成反馈原话：请保留来源。',)).fetchall()
                            assert rows[-1]['candidate_id']==ids['response'] and rows[-1]['status']=='completed'
                            assert c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0]==0
                        if mobile:page.locator('#easel-main').get_by_role('button',name='成品',exact=True).click()
                        page.get_by_role('button',name='不采纳',exact=True).click()
                        post_response('/actions',lambda:page.get_by_role('button',name='确认不采纳',exact=True).click())
                        with f['store'].connect() as c:
                            row=c.execute("SELECT candidate_id,status FROM toolbox_jobs WHERE work_id=? AND kind='reject' ORDER BY rowid DESC",(ids['work'],)).fetchone();assert row['candidate_id']==ids['response'] and row['status']=='completed'
                        expect(page.get_by_role('dialog')).not_to_be_visible();page.screenshot(path=str(out/(profile+'-work.png')),animations='disabled');check('version-bound-feedback-and-rejection-remain-local')
                        go('/articles/'+ids['article'])
                        if mobile:page.locator('#easel-main').get_by_role('button',name='成品',exact=True).click()
                        page.get_by_role('button',name='采纳并完成',exact=True).click()
                        approval=page.get_by_role('dialog');expect(approval.get_by_label('采纳后')).to_be_visible()
                        acknowledgement=approval.get_by_label('我已核对当前检查修订，确认保留这版')
                        if acknowledgement.count():acknowledgement.check()
                        post_response('/actions',lambda:approval.get_by_role('button',name='确认采纳并完成',exact=True).click())
                        expect(approval).not_to_be_visible()
                        with f['store'].connect() as c:
                            saved=c.execute("SELECT candidate_id,status FROM toolbox_jobs WHERE work_id=? AND kind='accept' ORDER BY rowid DESC",(ids['article'],)).fetchone();assert saved['status']=='completed'
                            assert c.execute('SELECT count(*) FROM creator_model_calls').fetchone()[0]==0
                        check('adoption-freezes-exact-version-and-archive-plan-without-a-model')
                        go('/toolbox?section=profiles&item=new')
                        page.get_by_label('名称',exact=True).fill('合成画像 '+profile)
                        page.get_by_label('作者身份',exact=True).fill('合成创作者身份')
                        saved=post_response('/api/creator/commands',lambda:page.get_by_role('button',name='保存画像',exact=True).click())
                        assert saved['result']['profile']['identity']=='合成创作者身份';check('easel-profile-edits-existing-versioned-service')
                        go('/toolbox?section=distribution&pane=connections')
                        page.get_by_label('连接名称',exact=True).fill('合成平台连接 '+profile)
                        post_response('/api/platform-accounts',lambda:page.get_by_role('button',name='添加账号连接',exact=True).click())
                        container=page.locator('.account-card').filter(has=page.get_by_role('heading',name='合成平台连接 '+profile,exact=True))
                        post_response('/api/platform-accounts',lambda:container.get_by_role('button',name='核对身份',exact=True).click())
                        expect(container.get_by_text('真实身份已核对',exact=True)).to_be_visible(timeout=20000);check('platform-connection-through-existing-isolated-adapter')
                        go('/toolbox?section=calendar');page.get_by_label('排期作品',exact=True).select_option(ids['work']);page.get_by_label('排期时间',exact=True).fill('2026-11-02T09:00')
                        plan=post_response('/api/easel/commands',lambda:page.get_by_role('button',name='保存排期',exact=True).click())
                        assert plan['result']['plan']['automatic_publication'] is False;check('calendar-record-is-not-publication-authority')
                        go('/toolbox?section=publications');expect(page.get_by_role('heading',name='准备渠道稿',exact=True)).to_be_visible();check('publishing-and-receipt-workspace')
                        go('/toolbox?section=insights');expect(page.get_by_label('准确发布实例')).to_be_visible();check('real-data-ledger-workspace')
                        go('/news');page.locator('.ew-news-row').first.click();expect(page.get_by_role('button',name='用内容生产技能制作')).to_be_visible();page.get_by_role('button',name='用内容生产技能制作').click()
                        expect(page.get_by_label('素材与目标',exact=True)).not_to_have_value('');check('collected-source-enters-content-production')
                        go('/settings');page.get_by_role('button',name='使用与路径',exact=True).click();expect(page.get_by_role('heading',name='使用与路径',exact=True)).to_be_visible();check('settings-and-approved-usage-controls')
                        go('/posters/new?draft=easel-offline-'+profile);page.get_by_label('素材与目标').fill('断网后继续编辑的原字草稿')
                        page.wait_for_function("()=>navigator.serviceWorker?.controller!==null")
                        context.set_offline(True);page.reload(wait_until='domcontentloaded');expect(page.get_by_role('heading',name='保留的本机输入')).to_be_visible(timeout=35000)
                        card=page.locator('section.ew-panel').filter(has=page.get_by_role('heading',name='easel-offline-'+profile,exact=True));card.get_by_role('button',name='继续编辑原输入').click()
                        expect(card.get_by_label('素材与目标')).to_have_value('断网后继续编辑的原字草稿');card.get_by_label('素材与目标').fill('离线追加后的原字草稿')
                        context.set_offline(False);page.reload(wait_until='domcontentloaded');expect(page.get_by_label('素材与目标',exact=True)).to_have_value('离线追加后的原字草稿',timeout=35000);check('offline-shell-and-original-input-editing')
                        audit=h.audit(page);assert not audit['csp'] and not audit['boundary'],audit
                        page.screenshot(path=str(out/(profile+'-compose.png')),animations='disabled')
                    except Exception as exc:
                        errors.append({'profile':profile,'error':repr(exc)});page.screenshot(path=str(out/(profile+'-failed.png')));raise
                    finally:context.close()
            browser.close()
        report['passed']=not errors
    finally:
        report.setdefault('passed',False);report['evidence']={p.name:h.digest(p) for p in out.glob('*.png')};(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({'passed':report['passed'],'checks':len(checks),'errors':errors},ensure_ascii=False))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--candidate',required=True);p.add_argument('--backend',required=True);p.add_argument('--evidence',required=True);p.add_argument('--profiles',default='windows-1280,android-390');p.add_argument('--headed',action='store_true');p.add_argument('--browser',default='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe');run(p.parse_args())
