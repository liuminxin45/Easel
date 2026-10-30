"""Actual Windows Edge + simulated mobile, TEMP server, no model/install calls."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--native',required=True);parser.add_argument('--out',required=True);parser.add_argument('--backend');args=parser.parse_args()
    backend=Path(args.backend).resolve() if args.backend else ROOT
    sys.path.insert(0,str(backend))
    from workbench_native_browser import isolated
    from easel import harnesses
    from easel_workbench.runtime.connection_environment import service as environment_service,RECIPES
    from playwright.sync_api import sync_playwright,expect
    out=Path(args.out).resolve();out.mkdir(parents=True,exist_ok=True);native=Path(args.native).resolve()
    report={'passed':False,'backend':str(backend),'native':str(native),'checks':[],'real_model_calls':0,'real_installations':0,'real_platform_writes':0,'physical_mobile_device_tested':False}
    labels={'api':'仅聊天模式','codex':'Codex','openclaw':'OpenClaw','opencode':'OpenCode','acp':'通用 ACP'}
    def describe(runtime):return {'id':runtime,'label':labels[runtime],'installed':True,'protocol':'TEMP synthetic detection','install_hint':'TEMP'}
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
            with isolated(native,b'TEMP unused image') as f,patch.object(harnesses,'describe',describe):
                environment=environment_service(f['box']);installed=set()
                def check():
                    with f['box'].store.connect() as c:jobs=[json.loads(row[0]) for row in c.execute('SELECT document FROM media_install_jobs')]
                    tools=[{'id':key,'name':spec['name'],'state':'ok' if key in installed else 'missing','version':'TEMP' if key in installed else None,'installable':True,'group':spec['group']} for key,spec in RECIPES.items()]
                    tools.extend([{'id':key,'name':key,'state':'ok','version':version,'installable':False,'group':'rm'} for key,version in [('node','24.19.0'),('python','3.14.7')]])
                    return {'host':'TEMP','system':'Windows','tools':tools,'jobs':jobs}
                def run(jid):
                    with f['box'].store.connect() as c:
                        job=json.loads(c.execute('SELECT document FROM media_install_jobs WHERE id=?',(jid,)).fetchone()[0]);installed.add(job['recipe']);job.update(state='ok',lines=['TEMP fake installer; no subprocess'],finished_at='TEMP');c.execute('UPDATE media_install_jobs SET document=? WHERE id=?',(json.dumps(job),jid))
                async def native_models(runtime):return {'runtime':runtime,'models':[{'id':'TEMP-native-model','label':'TEMP-native-model','default':True}]}
                with patch.object(environment,'check',check),patch.object(environment,'run',run),patch.object(f['app'].state.settings,'native_models',native_models):
                    for profile,width,mobile in [('desktop',1365,False),('mobile',390,True)]:
                        context=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':900},is_mobile=mobile,has_touch=mobile,color_scheme='dark' if mobile else 'light')
                        context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
                        page=context.new_page();page.set_default_timeout(20000);errors=[];page.on('pageerror',lambda error:errors.append(str(error)))
                        headers={'X-CSRF-Token':'fixture','Origin':f['origin']}
                        def mark(name):report['checks'].append({'profile':profile,'check':name,'passed':True});print('PASS',profile,name,flush=True)
                        page.goto(f['origin']+'/native/?path=/settings')
                        dialog=page.get_by_role('dialog',name='设置',exact=True);expect(dialog).to_be_visible()
                        expect(page.get_by_role('button',name='执行引擎',exact=True)).to_be_enabled()
                        if profile!='mobile':expect(page.locator('.sidebar-status-text')).to_contain_text('codex CLI 已安装')
                        for name in ['对话与脚本','语音转写','配音','生图','视频','音乐']:expect(dialog.get_by_role('button',name=name,exact=True)).to_be_visible()
                        mark('official three-section settings and six model tabs render')
                        # Native catalog is a synthetic read; saving uses real revision/operation ledgers.
                        page.get_by_role('button',name='拉取模型',exact=True).first.click();expect(page.get_by_role('button',name='原生模型',exact=True)).to_be_visible()
                        expect(page.get_by_role('button',name='拉取模型',exact=True).first).to_be_visible()
                        mark('native model listing through authenticated private port')
                        page.screenshot(path=str(out/(profile+'-models.png')))
                        old=f['app'].state.chat.create_session({'id':'old-'+profile,'session_id':'old-'+profile})['session']
                        page.get_by_role('button',name='执行引擎',exact=True).click();page.get_by_role('option',name='仅聊天模式',exact=True).click()
                        page.get_by_role('button',name='保存底座',exact=True).click();expect(dialog.get_by_text('已保存，请新建对话；旧对话仍保留在原底座，不迁移历史。')).to_be_visible()
                        expect(dialog.get_by_role('textbox',name='本地 / 内网 API 直连 模型',exact=True)).to_be_visible()
                        if mobile:assert dialog.get_by_role('textbox',name='本地 / 内网 API 直连 API 地址',exact=True).bounding_box()['width']>=280
                        page.screenshot(path=str(out/(profile+'-api-preview.png')))
                        dialog.get_by_role('textbox',name='本地 / 内网 API 直连 模型',exact=True).fill('TEMP-api-model')
                        dialog.get_by_role('textbox',name='本地 / 内网 API 直连 API 地址',exact=True).fill('http://127.0.0.1:12345/v1')
                        dialog.locator('input[type=password]').first.fill('TEMP-private-draft-key')
                        assert not page.evaluate("Object.values(localStorage).some(value=>value.includes('TEMP-private-draft-key'))")
                        dialog.get_by_role('button',name='保存配置',exact=True).click();expect(dialog.get_by_text('✓ 已保存',exact=False).first).to_be_visible()
                        mark('API provider saved without key in browser persistence')
                        new=f['app'].state.chat.create_session({'id':'new-'+profile,'session_id':'new-'+profile})['session']
                        assert old['runtime']=='codex' and new['runtime']=='api'
                        assert f['app'].state.chat.history(old['id'])['session']['runtime']=='codex'
                        headers['X-CSRF-Token']=page.request.get(f['origin']+'/api/config').json()['csrf']
                        rejected=page.request.post(f['origin']+'/api/chat/plan',headers=headers,data={'id':'blocked-'+profile,'sessionId':new['id'],'turnId':'blocked-'+profile,'message':'TEMP','context':{'skill_id':'content-production','action_id':'poster'}})
                        assert rejected.status in (400,409),rejected.text()
                        mark('new settings preserve old sessions and API rejects tool production')
                        # Return to Codex so both viewport scenarios start with the native UI.
                        page.get_by_role('button',name='执行引擎',exact=True).click();page.get_by_role('option',name='Codex',exact=True).click();page.get_by_role('button',name='保存底座',exact=True).click()
                        expect(dialog.get_by_text('已保存，请新建对话；旧对话仍保留在原底座，不迁移历史。')).to_be_visible()
                        dialog.get_by_role('button',name='环境安装',exact=False).click();expect(dialog.locator('[data-tool=python]')).to_be_visible()
                        assert dialog.locator('[data-tool=python] button').is_disabled();assert dialog.locator('[data-tool=node] button').is_disabled()
                        if 'ffmpeg' not in installed:dialog.locator('[data-tool=ffmpeg] button').click()
                        expect(dialog.locator('[data-tool=ffmpeg]')).to_have_attribute('data-state','ok')
                        page.reload();expect(page.get_by_role('dialog',name='设置',exact=True).locator('[data-tool=ffmpeg]')).to_have_attribute('data-state','ok')
                        mark('environment installation receipt survives reload; fixed runtimes cannot be replaced')
                        if mobile:assert page.locator('[data-tool=ffmpeg]').bounding_box()['width']>=150
                        page.screenshot(path=str(out/(profile+'-environment.png')))
                        page.get_by_role('dialog',name='设置',exact=True).get_by_role('button',name='更多设置',exact=True).click();expect(page.get_by_role('heading',name='使用与路径',exact=True)).to_be_visible();expect(page.get_by_text('网关参数（端口 / 绑定 / 会话）',exact=False)).to_be_visible()
                        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                        page.screenshot(path=str(out/(profile+'-more.png')))
                        mark('usage and explicit placeholders retained, with no viewport overflow')
                        page.get_by_role('button',name='清空统计',exact=True).click()
                        expect(page.get_by_role('dialog',name='清空操作统计？',exact=True)).to_be_visible()
                        page.keyboard.press('Escape')
                        expect(page.get_by_role('dialog',name='清空操作统计？',exact=True)).not_to_be_visible()
                        expect(page.get_by_role('dialog',name='设置',exact=True)).to_be_visible()
                        mark('Escape dismisses the inner confirmation without closing settings')
                        assert not errors,errors
                        context.close()
            browser.close()
        if args.backend:
            manifest=json.loads((backend/'workbench-release.json').read_text(encoding='utf-8'))
            assert all(sha(backend/member)==digest for member,digest in manifest['files'].items())
        report['passed']=True
    except BaseException as error:
        report['error']=repr(error)
        if 'page' in locals():
            try:report['body']=page.locator('body').inner_text();page.screenshot(path=str(out/'failure.png'),full_page=True)
            except Exception:pass
        raise
    finally:
        report['screenshots']={p.name:sha(p) for p in out.glob('*.png')}
        (out/'browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
