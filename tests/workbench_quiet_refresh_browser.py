"""Real timed background GETs, immutable bundle, two parallel Edge viewports.

Only TEMP GET responses are synthetic. No application module, DOM, CSS, clock,
or timer is replaced. MutationObserver/interval scripts only observe DOM geometry.
"""
from __future__ import annotations
import argparse
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.parse import urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]
TASK = '/api/creator/experience/TEMP-quiet-refresh'
ERROR = 'TEMP_QUIET_READ_FAILURE'
NEWS_ERROR = 'TEMP_NEWS_READ_FAILURE'
RAW = '  TEMP 未发送原字\n第二行保持空格  '


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


MONITOR = """({root,anchor,error,forbidden})=>{
 const host=document.querySelector(root),target=anchor.startsWith('@')?[...host.querySelectorAll('h3')].find(e=>e.textContent===anchor.slice(1)):document.querySelector(anchor),title=host.querySelector('.page-title');
 const state={samples:[],events:[],baseline:null,lastError:null,forbiddenSeen:[],started:performance.now()};
 const sample=()=>{const bad=[...host.querySelectorAll('[role=status],.interaction-status')].map(e=>e.textContent.trim()).filter(t=>forbidden.some(v=>t.includes(v)));
 const errors=[...host.querySelectorAll('.notice-error,[role=alert]')].filter(e=>e.textContent.includes(error));
 const a=target.getBoundingClientRect(),t=title.getBoundingClientRect();
 const row={at:performance.now(),scrollTop:host.scrollTop,anchorTop:a.top,titleTop:t.top,error:errors.some(e=>e.getClientRects().length),forbidden:bad};
 state.samples.push(row);if(bad.length)state.forbiddenSeen.push(row);
 if(row.error!==state.lastError){state.events.push({at:row.at,error:row.error});state.lastError=row.error}return row};
 window.__quietAudit=state;window.__quietSample=sample;sample();
 const observer=new MutationObserver(sample);observer.observe(host,{subtree:true,childList:true,characterData:true});
 const timer=setInterval(sample,50);window.__quietStop=()=>{clearInterval(timer);observer.disconnect();return sample()};
 return state.samples[0];
}"""


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', required=True, type=Path)
    parser.add_argument('--backend', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--only', choices=('all', 'news', 'resource'), default='all')
    parser.add_argument('--source-root', type=Path, default=ROOT, help='Immutable exact build-input snapshot when other tasks edit the shared checkout')
    args = parser.parse_args()
    native, backend, out = args.native.resolve(), args.backend.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    for directory, name in [(native, 'native-manifest.json'), (backend, 'workbench-release.json')]:
        manifest = read(directory / name)
        assert all(sha(directory / path) == digest for path, digest in manifest['files'].items())
    inputs = read(native / 'build-inputs.json')['inputs']
    assert all(sha(args.source_root.resolve() / path) == digest for path, digest in inputs.items())
    sys.path.insert(0, str(backend))
    spec = importlib.util.spec_from_file_location('quiet_refresh_fixture', ROOT / 'tests/workbench_native_browser.py')
    fixture = importlib.util.module_from_spec(spec); spec.loader.exec_module(fixture); fixture.ROOT = backend
    from playwright.async_api import async_playwright, expect
    expect.set_options(timeout=15000)
    report = {'passed': False, 'native': {'release': native.name, 'manifest_sha256': sha(native / 'native-manifest.json')},
        'backend': {'release': backend.name, 'manifest_sha256': sha(backend / 'workbench-release.json')},
        'source': {'head': subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
                   'harness_sha256': sha(__file__), 'fixture_sha256': sha(ROOT / 'tests/workbench_native_browser.py'),
                   'build_inputs_sha256': sha(native / 'build-inputs.json')},
        'checks': [], 'requests': [], 'screenshots': {}, 'observations': {}, 'blocked_requests': [],
        'execution_selection': args.only,
        'application_source_injected': False, 'DOM_or_CSS_mocked': False, 'application_clock_or_timers_patched': False,
        'real_AI_calls': 0, 'real_platform_writes': 0, 'real_installations': 0, 'production_data_access': False,
        'physical_mobile_device_tested': False,
        'not_browser_tested': ['Unknown operation receipt warnings are separately covered by root unit regressions; this runner does not invent a real mutation.']}

    def mark(case, name, passed, **data):
        report['checks'].append({'case': case, 'name': name, 'passed': bool(passed), **data})
        print(('PASS' if passed else 'FAIL') + ' ' + case + ' ' + name, flush=True)

    async def shot(page, case, stage):
        name = case + '-' + stage + '.png'; await page.screenshot(path=str(out / name))
        report['screenshots'][name] = {'sha256': sha(out / name), 'case': case, 'stage': stage}

    async def wait_for(predicate, seconds=45):
        deadline = time.monotonic() + seconds
        while not predicate():
            assert time.monotonic() < deadline, 'Timed out waiting for actual background request'
            await asyncio.sleep(.05)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True, args=['--ignore-certificate-errors'])
        with fixture.isolated(native, b'TEMP unused image') as f:
            payload = {'id': 'TEMP-quiet-refresh', 'status': 'completed', 'result': {'analysis': {'summary': 'TEMP completed read-only task result',
                'suggestions': [{'name': f'TEMP stable anchor {i:02}', 'instructions': ['TEMP 原始完整结果，保留位置与草稿。\n' * 6], 'reason': 'TEMP synthetic read only'} for i in range(12)]}}}

            async def run_resource(width):
                case = f'{width}-resource'; state = {'mode': 'normal', 'normal': [], 'failure': [], 'recovery': [], 'expired': [], 'holds': []}
                context = await browser.new_context(ignore_https_errors=True, viewport={'width': width, 'height': 844 if width == 390 else 900}, is_mobile=width == 390, has_touch=width == 390, service_workers='block')
                await context.add_cookies([{'name': '__Host-desk_session', 'value': 'fixture-owner', 'url': f['origin'], 'secure': True, 'httpOnly': True, 'sameSite': 'Strict'}])
                await context.add_init_script('localStorage.setItem("toolbox:draft:easel:reference",'+json.dumps(json.dumps({'text': '', 'goal': '', 'task_id': 'TEMP-quiet-refresh'}))+')')
                page = await context.new_page(); errors = []; page.on('pageerror', lambda error: errors.append(str(error)))

                async def route_request(route):
                    request = route.request; url = urlsplit(request.url); row = {'case': case, 'path': url.path, 'method': request.method, 'at': time.monotonic()}; report['requests'].append(row)
                    if url.hostname not in ('localhost', '127.0.0.1'): report['blocked_requests'].append(row); return await route.abort()
                    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
                        if url.path == '/api/usage/events': return await route.fulfill(status=200, json={'accepted': 0})
                        report['blocked_requests'].append(row); return await route.fulfill(status=405, json={'error': 'TEMP no mutations'})
                    if url.path != TASK: return await route.continue_()
                    mode = state['mode']; row['mode'] = mode
                    if mode == 'expired':
                        state['expired'].append(row); return await route.fulfill(status=401, json={'error': '登录已过期，输入已保留。'})
                    if mode == 'failure':
                        state['failure'].append(row); return await route.fulfill(status=503, json={'error': ERROR})
                    before = await page.evaluate('window.__quietSample?.()||null')
                    await asyncio.sleep(.2)
                    during = await page.evaluate('window.__quietSample?.()||null')
                    await asyncio.sleep(.2)
                    state['holds'].append({'mode': mode, 'before': before, 'during': during, 'elapsed_ms': (time.monotonic()-row['at'])*1000})
                    await route.fulfill(json=payload)
                    state['normal' if mode == 'normal' else 'recovery'].append(row)

                await context.route('**/*', route_request)
                try:
                    await page.goto(f['origin']+'/native/?'+urlencode({'path':'/toolbox?section=research&pane=breakdown'}), wait_until='domcontentloaded')
                    anchor = page.get_by_role('heading', name='TEMP stable anchor 08', exact=True); await expect(anchor).to_be_visible()
                    await page.locator('.breakdown-page textarea').fill(RAW)
                    await anchor.scroll_into_view_if_needed()
                    await page.evaluate('async()=>{for(let i=0;i<8;i++)await new Promise(requestAnimationFrame)}')
                    baseline = await page.evaluate(MONITOR, {'root': '.breakdown-page', 'anchor': '@TEMP stable anchor 08', 'error': ERROR, 'forbidden':['正在刷新','正在处理']})
                    await wait_for(lambda: len(state['normal']) >= 3, 75)
                    normal_end = await page.evaluate('window.__quietSample()'); normal_audit = await page.evaluate('window.__quietAudit')
                    drift = max(max(abs(s[k]-baseline[k]) for k in ('anchorTop','titleTop','scrollTop')) for s in normal_audit['samples'])
                    intervals = [state['normal'][i]['at']-state['normal'][i-1]['at'] for i in range(1,3)]
                    mark(case, 'two actual unchanged-data30s polls preserve top/content anchors and scroll', drift <= 1 and all(value >= 29 for value in intervals), baseline=baseline, after=normal_end, max_drift=drift, intervals=intervals, visibility=await page.evaluate('document.visibilityState'))
                    mark(case, 'normal held GETs never mount refreshing or processing banner', not normal_audit['forbiddenSeen'], held_gets=state['holds'])
                    await shot(page, case, 'normal-after-two-polls')
                    state['mode'] = 'failure'
                    error = page.locator('.notice-error').filter(has_text=ERROR)
                    await expect(error).to_be_visible(timeout=45000); await error.scroll_into_view_if_needed()
                    mark(case, 'persistent actual503 reads render their genuine error', len(state['failure']) >= 2 and await error.is_visible(), failed_requests=len(state['failure']))
                    await shot(page, case, 'error')
                    await page.evaluate('window.__quietAudit.events=[];window.__quietAudit.lastError=true')
                    state['mode'] = 'recovery'
                    await wait_for(lambda: bool(state['recovery']), 45)
                    await expect(error).to_have_count(0)
                    recovery_hold = [x for x in state['holds'] if x['mode'] == 'recovery']
                    mark(case, 'retry hold retains the same visible error until successful response', bool(recovery_hold) and all(h['before'] and h['during'] and h['before']['error'] and h['during']['error'] for h in recovery_hold), holds=recovery_hold)
                    events = await page.evaluate('window.__quietAudit.events')
                    mark(case, 'successful recovery removes the error once without flicker', len([e for e in events if not e['error']]) == 1 and not any(e['error'] for e in events), transitions=events)
                    await shot(page, case, 'recovered')
                    state['mode'] = 'expired'
                    await wait_for(lambda: bool(state['expired']), 45)
                    await expect(page.get_by_text('登录已过期，草稿保留。', exact=False)).to_be_visible()
                    draft = await page.evaluate('JSON.parse(localStorage.getItem("toolbox:draft:easel:reference")||"{}")')
                    mark(case, 'actual401 stays visible and retains the exact unsent draft without POST', draft.get('text') == RAW and not any(x['case']==case for x in report['blocked_requests']), draft=draft)
                    await shot(page, case, 'expired-draft-retained')
                    mark(case, 'no page errors or model requests', not errors and not f['adapter'].requests, errors=errors)
                except Exception as error:
                    mark(case, 'scenario completed', False, error=repr(error)); await shot(page, case, 'failure')
                finally:
                    report['observations'][case] = state
                    if not page.is_closed():
                        try: await page.evaluate('window.__quietStop?.()')
                        except Exception: pass
                    await context.close()

            async def run_news(width):
                case=f'{width}-news'; state={'mode':'normal','gets':[],'holds':[]}
                context=await browser.new_context(ignore_https_errors=True,viewport={'width':width,'height':844 if width==390 else 900},service_workers='block')
                await context.add_cookies([{'name':'__Host-desk_session','value':'fixture-owner','url':f['origin'],'secure':True,'httpOnly':True,'sameSite':'Strict'}])
                page=await context.new_page(); source={'id':'temp-busy','label':'TEMP busy source','type':'http','default':True,'refresh_seconds':30}
                group={'platform':source['id'],'label':source['label'],'ok':False,'status':'stale','stale':True,'fetched_at':'2026-10-30T08:00:00Z','last_attempt_at':1793400000,'error':{'code':'busy','message':'TEMP genuine busy group'},'items':[{'id':str(i),'title':f'TEMP unchanged news {i}','hot':'','url':'https://example.test/TEMP','published_at':None,'heat':{'value':None,'text':'','unit':''}} for i in range(12)]}
                async def route_request(route):
                    request=route.request;url=urlsplit(request.url)
                    if url.hostname not in ('localhost','127.0.0.1'):return await route.abort()
                    if request.method not in ('GET','HEAD','OPTIONS'):
                        if url.path=='/api/usage/events':return await route.fulfill(status=200,json={'accepted':0})
                        report['blocked_requests'].append({'case':case,'path':url.path,'method':request.method});return await route.fulfill(status=405,json={'error':'TEMP no mutations'})
                    if url.path=='/api/trends/sources':return await route.fulfill(json={'version':1,'sources':[source],'warnings':[]})
                    if url.path!='/api/trends':return await route.continue_()
                    state['gets'].append({'at':time.monotonic(),'mode':state['mode']})
                    if state['mode']=='failure':return await route.fulfill(status=500,json={'error':NEWS_ERROR,'detail':NEWS_ERROR})
                    await asyncio.sleep(.2);during=await page.evaluate('window.__quietSample?.()||null');await asyncio.sleep(.2);state['holds'].append(during)
                    return await route.fulfill(json={'version':1,'trends':[group],'updated':1793400000,'warnings':[]})
                await context.route('**/*',route_request)
                try:
                    await page.goto(f['origin']+'/native/?'+urlencode({'path':'/news'}),wait_until='domcontentloaded')
                    await expect(page.locator('.trend-col')).to_be_visible();await expect(page.get_by_text('TEMP genuine busy group',exact=False)).to_be_visible()
                    await page.evaluate('async()=>{for(let i=0;i<6;i++)await new Promise(requestAnimationFrame)}')
                    baseline=await page.evaluate(MONITOR,{'root':'.trends-page','anchor':'.trend-grid','error':NEWS_ERROR,'forbidden':['正在读取已采集热点']})
                    start=len(state['gets']);await wait_for(lambda:len(state['holds'])>=start+2,15)
                    audit=await page.evaluate('window.__quietAudit');drift=max(max(abs(s[k]-baseline[k]) for k in ('anchorTop','titleTop','scrollTop')) for s in audit['samples'])
                    mark(case,'two actual busygroup retries keep header/grid anchors and no cyclic loading row',drift<=1 and not audit['forbiddenSeen'],max_drift=drift,gets=state['gets'],holds=state['holds'])
                    mark(case,'genuine group busy state remains visible',await page.get_by_text('TEMP genuine busy group',exact=False).is_visible())
                    await shot(page,case,'busy-after-two-polls');state['mode']='failure'
                    await expect(page.locator('.notice-error').filter(has_text=NEWS_ERROR)).to_be_visible(timeout=15000)
                    mark(case,'genuine news HTTP failure is still visible',await page.locator('.notice-error').filter(has_text=NEWS_ERROR).is_visible())
                    await shot(page,case,'error')
                except Exception as error:
                    mark(case,'scenario completed',False,error=repr(error));await shot(page,case,'failure')
                finally:
                    report['observations'][case]=state;await context.close()

            jobs=[]
            if args.only in ('all','resource'): jobs.extend(run_resource(width) for width in (390,1440))
            if args.only in ('all','news'): jobs.extend(run_news(width) for width in (390,1440))
            await asyncio.gather(*jobs)
            report['real_AI_calls']=len(f['adapter'].requests)
        await browser.close()
    report['passed']=bool(report['checks']) and all(check['passed'] for check in report['checks']) and report['real_AI_calls']==0 and not report['blocked_requests']
    report['runtime_modules']={name:{'file':str(Path(value.__file__).resolve()),'sha256':sha(value.__file__)} for name,value in list(sys.modules.items()) if (name=='easel' or name.startswith('easel.') or name=='easel_workbench' or name.startswith('easel_workbench.')) and getattr(value,'__file__',None)}
    report['module_roots_valid']=all(Path(value['file']).is_relative_to(backend) for value in report['runtime_modules'].values())
    report['passed'] &= report['module_roots_valid']
    shutil.copy2(__file__,out/'harness.py');(out/'report.json').write_bytes(json.dumps(report,ensure_ascii=False,indent=2).encode('utf-8'))
    print(json.dumps({'passed':report['passed'],'checks':len(report['checks']),'screenshots':len(report['screenshots'])}))
    return 0 if report['passed'] else 1


if __name__=='__main__':
    raise SystemExit(asyncio.run(main()))
