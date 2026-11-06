"""TEMP HTTPS tests of the actual preset Drawer; no model or production IO."""
import argparse,importlib.util,json,sys
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def main():
    p=argparse.ArgumentParser()
    for name in ('backend','native','out'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();backend,native,out=a.backend.resolve(),a.native.resolve(),a.out.resolve();out.mkdir(parents=True,exist_ok=True)
    spec=importlib.util.spec_from_file_location('preset_browser_helper',ROOT/'tests/workbench_news_creation_browser.py')
    h=importlib.util.module_from_spec(spec);spec.loader.exec_module(h)
    helper,application,create_app=h.infrastructure(backend,native)
    from playwright.sync_api import sync_playwright,expect
    report={'passed':False,'checks':[],'backend':h.frozen(backend,'workbench-release.json'),'native':h.frozen(native,'native-manifest.json'),'physical_device_tested':False,'production_data_access':False,'real_model_calls':0,'errors':[]}
    def check(layout,name):report['checks'].append({'layout':layout,'name':name,'passed':True})
    try:
      with patch.object(application,'create_app',create_app),sync_playwright() as pw:
        browser=pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True,args=['--ignore-certificate-errors'])
        for layout,width,height,mobile,theme in h.LAYOUTS:
          with helper.isolated(native,h.IMAGE) as f:
            article=h.seed_news(f);ctx=browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':height},is_mobile=mobile,has_touch=mobile,service_workers='block')
            ctx.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
            ctx.add_init_script('localStorage.setItem("native:theme",'+json.dumps(theme)+')')
            page=ctx.new_page();page.on('pageerror',lambda e:report['errors'].append(str(e)))
            h.goto(page,f['origin'],'/news/a/'+article)
            page.get_by_role('button',name='制作内容',exact=True).click()
            drawer=page.get_by_role('dialog',name='制作内容',exact=True);drawer.get_by_role('button',name='贴图',exact=True).click()
            expect(drawer.get_by_role('button',name='已确认的风格组合',exact=True)).to_contain_text('清楚的解释型海报')
            expect(drawer.get_by_role('button',name='开始制作贴图',exact=True)).to_be_enabled()
            assert not f['adapter'].requests
            check(layout,'default preset fills all four slots without sending')
            note='仅当前新闻的补充，不继承旧新闻要求';drawer.get_by_role('textbox',name='补充要求',exact=True).fill(note)
            # Add completed server history AFTER this drawer was loaded: restore must perform a fresh GET.
            style={'writing':'editorial-writing','visual':'scene-visual','character':'simple-pig','layout':'page-roles'}
            turn={'id':'temp-last-poster','profile_id':'oil-pig','status':'completed','updated_at':'2026-11-06T12:00:00Z','context':{'creation':{'intent':'produce','format':'poster','style':style,'note':'old secret note'},'article_id':'old-news'}}
            with f['box'].store.connect() as c:
                before=c.execute("SELECT document FROM creator_profiles WHERE id='oil-pig'").fetchone()[0]
                c.execute('INSERT INTO easel_chat_turns VALUES(?,?,?,?,?)',('temp-last-poster','temp-old-session','temp-old-operation','temp-signature',json.dumps(turn)))
            h.choose(page,drawer,'角色呈现','精致武侠小猪',expect)
            restore=drawer.get_by_role('button',name='恢复上次贴图风格',exact=True);restore.click()
            expect(drawer.get_by_role('button',name='角色呈现',exact=True)).to_contain_text('简笔小猪侠')
            expect(drawer.get_by_role('button',name='已确认的风格组合',exact=True)).to_contain_text('油猪大侠 · 简笔场景')
            expect(drawer.get_by_role('textbox',name='补充要求',exact=True)).to_have_value(note)
            check(layout,'fresh server history restores only four choices and preserves this note')
            drawer.get_by_role('button',name='恢复默认预设',exact=True).click()
            expect(drawer.get_by_role('button',name='角色呈现',exact=True)).to_contain_text('按主题选择角色与素材')
            expect(drawer.get_by_role('textbox',name='补充要求',exact=True)).to_have_value(note)
            assert drawer.evaluate('(n)=>n.scrollWidth<=n.clientWidth+1')
            geometry=drawer.locator('.ew-news-preset-actions button').evaluate_all('(buttons)=>buttons.map(b=>{const r=b.getBoundingClientRect();return {height:r.height,width:r.width}})')
            assert all(v['height']>=44 for v in geometry)
            assert not f['adapter'].requests
            with f['box'].store.connect() as c:assert c.execute("SELECT document FROM creator_profiles WHERE id='oil-pig'").fetchone()[0]==before
            check(layout,'restore default keeps inputs, original controls and zero execution/profile writes')
            drawer.locator('.ew-news-preset-actions').scroll_into_view_if_needed();page.screenshot(path=str(out/(layout+'.png')))
            drawer.get_by_role('button',name='关闭',exact=True).click();page.get_by_role('button',name='制作内容',exact=True).click();drawer=page.get_by_role('dialog',name='制作内容',exact=True)
            drawer.get_by_role('button',name='文章',exact=True).click();expect(drawer.get_by_role('button',name='恢复上次贴图风格',exact=True)).to_have_count(0)
            check(layout,'poster shortcuts do not change article form')
            ctx.close()
        browser.close()
        assert not report['errors'];report['passed']=True
    except Exception as exc:report['error']=repr(exc)
    finally:(out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'error':report.get('error')}))
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
