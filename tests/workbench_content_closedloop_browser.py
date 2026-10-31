"""Real TEMP browser loop: scheduled news, saved topic, poster, revision, decisions.

The actual collection scheduler/worker, native session, frozen production input,
independent-check queue, adoption gate and byte-verified project archive run.
Only inference and external inspection are synthetic. No application source,
DOM, production database, real AI, Git push or platform publication is replaced
or exercised. Responsive mobile is an Edge simulation, not a physical device.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import datetime as dt
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import re
import shutil
import sys
import threading
import time
from urllib.parse import parse_qs, urlencode, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@contextmanager
def rss_server(title):
    """Actual bounded HTTP transport for the real generic RSS collector."""
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            requests.append(self.path)
            if self.path != '/news.xml':
                self.send_error(404)
                return
            body = ('<?xml version="1.0" encoding="UTF-8"?><rss version="2.0"><channel>'
                    '<title>TEMP closed loop source</title><item><guid>closedloop-exact-news</guid>'
                    '<title>' + title + '</title><link>https://example.com/temp-closedloop-news</link>'
                    '<description>TEMP 原始 RSS 说明；通用来源目前仅登记标题与链接。</description>'
                    '</item></channel></rss>').encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/rss+xml; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {'url': 'http://127.0.0.1:' + str(server.server_port) + '/news.xml', 'requests': requests}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('native', 'backend', 'out'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--profiles', choices=('all', 'desktop', 'mobile'), default='all')
    args = parser.parse_args()
    native, backend, out = args.native.resolve(), args.backend.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    native_manifest = json.loads((native / 'native-manifest.json').read_text(encoding='utf-8'))
    assert all(sha(native / member) == digest for member, digest in native_manifest['files'].items())
    backend_manifest_path = backend / 'workbench-release.json'
    backend_manifest = json.loads(backend_manifest_path.read_text(encoding='utf-8')) if backend_manifest_path.exists() else None
    if backend_manifest:
        assert all(sha(backend / member) == digest for member, digest in backend_manifest['files'].items())
    else:
        assert backend == ROOT, 'Only the explicit development project root may omit a frozen manifest'
    sys.path.insert(0, str(backend))
    helper = load('closedloop_native_fixture', ROOT / 'tests/workbench_native_browser.py')
    from playwright.sync_api import sync_playwright, expect
    from easel_workbench.runtime.collection_worker import CollectionWorker
    from easel_workbench.runtime.auth_totp import token_hash
    from easel_workbench.runtime.learning_execution import run_review
    from easel_workbench.runtime.learning_service import POLICY_PATH
    from easel_workbench.runtime.learning_worker import LearningWorker
    from easel_workbench.runtime.local_operations import LocalOperations

    report = {'passed': False, 'profiles': args.profiles,
              'native': {'release': native_manifest['release'], 'manifest_sha256': sha(native / 'native-manifest.json')},
              'backend': {'directory': str(backend), 'mode': 'frozen' if backend_manifest else 'development_source',
                          'manifest_sha256': sha(backend_manifest_path) if backend_manifest else None},
              'harness_sha256': sha(__file__), 'fixture_sha256': sha(ROOT / 'tests/workbench_native_browser.py'),
              'checks': [], 'screenshots': {}, 'scenarios': [], 'real_AI_calls': 0, 'real_platform_writes': 0,
              'real_Git_writes': 0, 'physical_mobile_device_tested': False,
              'application_source_injected': False, 'DOM_or_CSS_mocked': False,
              'synthetic_quality_notice': 'Synthetic producer and independent inspector validate plumbing and exact evidence, not actual model or visual quality.'}

    def check(profile, name, value=True):
        report['checks'].append({'profile': profile, 'name': name, 'passed': bool(value)})
        assert value, name
        print('PASS', profile, name, flush=True)

    def screenshot(page, name):
        page.screenshot(path=str(out / name), full_page=True)
        report['screenshots'][name] = sha(out / name)

    page = None
    runtime_start = {}
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
                                                 headless=True, args=['--ignore-certificate-errors'])
            profiles = [('desktop', 1440, 'light'), ('mobile', 390, 'dark')]
            for profile, width, theme in profiles:
                if args.profiles not in ('all', profile):
                    continue
                title = 'TEMP ' + profile + ' 热点：准确来源贯穿贴图修改与采纳'
                scenario = {'profile': profile, 'source_title': title, 'requests': [], 'errors': [], 'review_calls': [], 'productions': [],
                            'console_errors': [], 'failed_requests': []}
                report['scenarios'].append(scenario)
                with rss_server(title) as rss, helper.isolated(native, (ROOT / 'web/static/easel-icon.png').read_bytes()) as fixture:
                    box, app, origin = fixture['box'], fixture['app'], fixture['origin']
                    # The shared chat fixture authenticates ordinary routes by
                    # session(). Signed image reads additionally consult the
                    # same owner's hashed session registry under its lock.
                    # Supply that real Auth surface in TEMP rather than bypass
                    # image_delivery.read_session/authorize or their signature.
                    fixture['auth'].lock = threading.RLock()
                    fixture['auth'].data['sessions'] = {token_hash('fixture-owner'): {'csrf': 'fixture', 'until': 9999999999}}
                    assert fixture['root'] != ROOT and fixture['root'].is_relative_to(Path(__import__('tempfile').gettempdir()).resolve())
                    assert app.state.studio.project.resolve().is_relative_to(fixture['root'])
                    assert not (app.state.studio.project / '.git').exists()
                    policy = app.state.studio.project / POLICY_PATH
                    policy.parent.mkdir(parents=True, exist_ok=True)
                    policy.write_text(json.dumps({'schema_version': 2, 'revision': 1, 'methods': [], 'profiles': []}), encoding='utf-8')
                    # Only the new RSS source can execute in this isolated root.
                    collection = app.state.collection
                    for source_id, source in collection.registry.entries().items():
                        collection.registry.update({'operation_id': 'temp-disable-' + source_id, 'action': 'toggle',
                                                    'source_id': source_id, 'expected_revision': source['revision'], 'enabled': False})
                    (fixture['root'] / 'data/collection-config.json').write_text('{"enabled":true}', encoding='utf-8')
                    (fixture['root'] / 'data/automation-enabled.json').write_text('{"local_io":true}', encoding='utf-8')
                    now = [dt.datetime.now(dt.timezone(dt.timedelta(hours=8)))]
                    collection.clock = lambda: now[0]
                    adapter = fixture['adapter']

                    async def run(request, emit, ask, bind):
                        adapter.requests.append(request)
                        native_id = request.native_id or 'temp-native-' + request.session_key
                        bind(native_id)
                        request.on_native_turn(native_id, 'temp-native-turn-' + str(len(adapter.requests)))
                        payload = json.JSONDecoder().raw_decode(request.prompt.split('## 本轮冻结输入\n')[-1])[0] if '## 本轮冻结输入\n' in request.prompt else {}
                        if payload.get('session_task', 'discuss') == 'discuss':
                            emit('token', 'TEMP 选题讨论：围绕准确来源说明具体变化、适用对象和不确定边界。')
                            return
                        folder = Path(payload['output_directory']).resolve()
                        assert folder.is_relative_to(fixture['root'])
                        folder.mkdir(parents=True, exist_ok=True)
                        ordinal = len(scenario['productions']) + 1
                        image, copy = folder / '成品.png', folder / '标题与配文.txt'
                        image.write_bytes((ROOT / ('web/static/easel-icon.png' if ordinal == 1 else 'web/static/easel-icon-transparent.png')).read_bytes())
                        copy.write_text('TEMP 第' + str(ordinal) + '版贴图标题\n\nTEMP 准确来源与适用边界；' + ('原始制作。' if ordinal == 1 else '仅按本次明确意见修改。'), encoding='utf-8')
                        scenario['productions'].append({'task': payload['session_task'], 'payload': payload,
                                                        'files': {str(path): sha(path) for path in (image, copy)}})
                        emit('activity', 'TEMP 假执行器已写入真实独立版本文件。')
                        await asyncio.sleep(.15)
                        emit('token', json.dumps({'deliverables': [str(image), str(copy)], 'production_result': {'schema_version': 1, 'status': 'completed'}}, ensure_ascii=False))

                    adapter.run = run
                    context = browser.new_context(ignore_https_errors=True, viewport={'width': width, 'height': 960},
                                                  is_mobile=width < 600, has_touch=width < 600, color_scheme=theme,
                                                  accept_downloads=True)
                    def close_clients():
                        if sys.exc_info()[0] is not None:
                            try:
                                report['failure_page'] = {'url': page.url, 'body': page.locator('body').inner_text()}
                                screenshot(page, 'failure.png')
                            except Exception:
                                pass
                        context.close()
                    fixture['close_clients'] = close_clients
                    context.add_cookies([{'name': '__Host-desk_session', 'value': 'fixture-owner', 'url': origin,
                                          'secure': True, 'httpOnly': True, 'sameSite': 'Strict'}])
                    page = context.new_page()
                    page.set_default_timeout(20000)
                    page.on('pageerror', lambda error: scenario['errors'].append(str(error)))
                    page.on('console', lambda message: scenario['console_errors'].append(message.text) if message.type == 'error' else None)
                    page.on('requestfailed', lambda request: scenario['failed_requests'].append({'url': request.url, 'failure': request.failure}))
                    page.on('request', lambda request: scenario['requests'].append({'method': request.method, 'path': urlsplit(request.url).path,
                                                                                   'body': request.post_data_json if request.method == 'POST' and request.post_data and 'json' in request.headers.get('content-type', '') else None}))

                    def visit(path):
                        page.goto(origin + '/native/?' + urlencode({'path': path}), wait_until='domcontentloaded')

                    def get(path):
                        response = page.request.get(origin + path)
                        assert response.ok, response.text()
                        return response.json()

                    def posts(path):
                        return [request for request in scenario['requests'] if request['method'] == 'POST' and request['path'] == path]

                    def read_turn(turn_id):
                        with box.store.connect() as connection:
                            return json.loads(connection.execute('SELECT document FROM easel_chat_turns WHERE id=?', (turn_id,)).fetchone()[0])

                    visit('/news')
                    page.get_by_role('button', name='数据源', exact=True).click()
                    manager = page.get_by_role('dialog', name='数据源', exact=True)
                    manager.get_by_label('名称', exact=True).fill('TEMP 自动采集闭环 ' + profile)
                    manager.get_by_label('订阅地址', exact=True).fill(rss['url'])
                    with page.expect_response(lambda response: response.request.method == 'POST' and urlsplit(response.url).path == '/api/trends/manage') as added:
                        manager.get_by_role('button', name='添加来源', exact=True).click()
                    assert added.value.ok, added.value.text()
                    source_id = added.value.json()['id']
                    expect(manager.locator('.trend-manager-row').filter(has_text='TEMP 自动采集闭环 ' + profile)).to_have_count(1)
                    page.keyboard.press('Escape')
                    worker = CollectionWorker(collection)
                    try:
                        worker.tick()  # Initialize the actual next scheduled slot.
                        check(profile, 'opening news and registering a source does not perform an implicit collection',
                              not rss['requests'] and not posts('/api/collection/runs') and not collection.status()['active_runs'])
                        now[0] += dt.timedelta(seconds=301)
                        deadline = time.monotonic() + 20
                        while True:
                            worker.tick()
                            with box.store.connect() as connection:
                                task = connection.execute('SELECT * FROM collection_tasks WHERE source_id=? ORDER BY rowid DESC LIMIT 1', (source_id,)).fetchone()
                            if task and task['status'] in ('completed', 'failed', 'blocked', 'partial'):
                                break
                            assert time.monotonic() < deadline, 'Real scheduled RSS collection did not finish'
                            page.wait_for_timeout(50)
                        task = dict(task)
                        with box.store.connect() as connection:
                            runs = [dict(row) for row in connection.execute('SELECT * FROM collection_runs')]
                        check(profile, 'real automatic scheduler and worker collect local RSS once without a browser refresh command',
                              task['status'] == 'completed' and task['inserted'] == 1 and task['force'] == 0
                              and len(rss['requests']) == 1 and runs[-1]['trigger'] == 'scheduled' and not posts('/api/collection/runs'))
                    finally:
                        worker.close()
                    listing = get('/api/news?' + urlencode({'source': source_id}))
                    article = next(item for item in listing['items'] if item['title'] == title)
                    source_article = get('/api/news/' + article['id'])
                    scenario['collection'] = {'task': task, 'runs': runs, 'http_requests': rss['requests'], 'source_id': source_id,
                                              'article': source_article}
                    visit('/news?' + urlencode({'sources': source_id}))
                    row = page.locator('.trend-item').filter(has=page.locator('.trend-title', has_text=title))
                    expect(row).to_have_count(1)
                    screenshot(page, profile + '-01-collected-news.png')
                    with page.expect_response(lambda response: response.request.method == 'POST' and urlsplit(response.url).path == '/api/ideas') as saved:
                        row.get_by_role('button', name='收藏选题：' + title, exact=True).click()
                    assert saved.value.ok, saved.value.text()
                    idea = next(idea for idea in get('/api/ideas') if idea['title'] == title)
                    check(profile, 'saving the selected collected headline persists its precise article ID', idea.get('source_id') == article['id'])
                    visit('/toolbox?section=research&pane=topics')
                    card = page.locator('.idea-card').filter(has=page.locator('.idea-title', has_text=title))
                    expect(card).to_be_visible()
                    screenshot(page, profile + '-02-saved-topic.png')
                    before_topic = len(adapter.requests)
                    card.get_by_role('button', name='做内容', exact=True).click()
                    page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.startsWith('/chat/')")
                    sid = parse_qs(urlsplit(page.url).query)['path'][0].split('/chat/')[1].split('?')[0]
                    discussion = helper.wait_history(page, origin, sid)
                    discussion_turn = discussion['session']['messages'][-1]['turnId']
                    discussion_document = read_turn(discussion_turn)
                    discussion_source = json.JSONDecoder().raw_decode(discussion_document['actual_prompt'].split('## 本轮冻结输入\n')[-1])[0]['source_article']
                    check(profile, 'saved-topic use creates one actual discussion in the selected profile with original source provenance',
                          len(adapter.requests) == before_topic + 1 and discussion['session']['profile_id'] == 'oil-pig'
                          and discussion_source['id'] == article['id']
                          and discussion_source['body'] == source_article['body']
                          and bool(discussion_source['provenance']))
                    page.wait_for_function("sid=>!JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid)||'{}').pending", arg=sid)
                    composer = page.get_by_role('textbox', name='对话输入', exact=True)
                    expect(page.get_by_text('本轮带入所选新闻的原始来源', exact=True)).to_be_visible()
                    original = 'TEMP 明确制作：沿用所选热点准确来源，保留适用边界。'
                    composer.fill('/生成贴图 ' + original)
                    expect(page.get_by_role('menuitem', name='/生成贴图', exact=False)).to_be_visible()
                    expect(page.get_by_role('button', name='发送', exact=True)).to_be_enabled()
                    composer.press('Enter')
                    expect(page.get_by_text('生成贴图 · v', exact=False)).to_be_visible()
                    expect(composer).to_have_value(original)
                    attachment = b'TEMP ORIGINAL ATTACHMENT: exact retained production evidence.'
                    page.locator('input[type=file]').set_input_files({'name': 'TEMP原始素材.txt', 'mimeType': 'text/plain', 'buffer': attachment})
                    page.get_by_role('button', name='发送', exact=True).click()
                    v1_history = helper.wait_history(page, origin, sid, discussion_turn, files=True)
                    v1_message = v1_history['session']['messages'][-1]
                    v1 = read_turn(v1_message['turnId'])
                    wid, v1_id = v1['work']['work_id'], v1['id']
                    scenario.update(session_id=sid, work_id=wid, v1_id=v1_id)
                    payload1 = scenario['productions'][0]['payload']
                    check(profile, 'poster V1 freezes the collected source, raw instruction, exact profile and skills, and actual attachment',
                          v1['hook_status'] == 'completed' and v1['snapshot']['task'] == 'poster'
                          and payload1['source_article']['id'] == article['id'] and payload1['source_article']['body'] == source_article['body']
                          and payload1['source_article']['provenance'] == discussion_source['provenance']
                          and v1['message'] == original and v1['snapshot']['profile']['id'] == 'oil-pig' and len(v1['attachments']) == 1)
                    page.wait_for_function("sid=>!JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid)||'{}').pending", arg=sid)
                    helper.turn_view(page, v1_history).get_by_role('button', name='查看产物', exact=True).click()
                    expect(page.get_by_role('button', name='不采纳', exact=True)).to_be_visible()
                    screenshot(page, profile + '-03-v1-preview.png')

                    # Test the real adoption guard before any synthetic review.
                    before_guard = len(adapter.requests)
                    page.get_by_role('button', name='采纳并完成', exact=True).click()
                    adopt = page.get_by_role('dialog').filter(has=page.get_by_role('button', name='确认采纳并完成', exact=True))
                    confirm = adopt.get_by_role('button', name='确认采纳并完成', exact=True)
                    expect(confirm).to_be_visible()
                    expect(confirm).to_be_disabled()
                    screenshot(page, profile + '-04-unreviewed-adoption-blocked.png')
                    page.keyboard.press('Escape')
                    check(profile, 'merely having actual image and copy files cannot bypass the independent adoption gate', len(adapter.requests) == before_guard)
                    before_reject = len(adapter.requests)
                    page.get_by_role('button', name='不采纳', exact=True).click()
                    reject = page.get_by_role('dialog').filter(has=page.get_by_role('button', name='确认不采纳', exact=True))
                    rejection = 'TEMP 不采纳 V1 原话：主体需要更突出；暂不采用本版。'
                    reject.get_by_label('决定说明 · 可不填', exact=True).fill(rejection)
                    screenshot(page, profile + '-05-reject-v1-dialog.png')
                    with page.expect_response(lambda response: response.request.method == 'POST' and urlsplit(response.url).path == '/api/works/' + wid + '/actions') as rejected:
                        reject.get_by_role('button', name='确认不采纳', exact=True).click()
                    assert rejected.value.ok, rejected.value.text()
                    reject_id = rejected.value.json()['id']
                    expect(reject).not_to_be_visible()
                    work = get('/api/works/' + wid)
                    with box.store.connect() as connection:
                        reject_job = dict(connection.execute('SELECT * FROM toolbox_jobs WHERE id=?', (reject_id,)).fetchone())
                    check(profile, 'actual reject confirmation persists exact V1 and raw reason locally without another model request',
                          reject_job['kind'] == 'reject' and reject_job['candidate_id'] == v1_id and reject_job['text'] == rejection
                          and reject_job['status'] == 'completed' and work['decision']['id'] == reject_id
                          and len(adapter.requests) == before_reject and all(sha(path) == digest for path, digest in scenario['productions'][0]['files'].items()))

                    page.get_by_role('button', name='修改这版', exact=True).click()
                    page.wait_for_function("()=>new URLSearchParams(location.search).get('path')?.includes('action=change')")
                    destination = parse_qs(urlsplit(page.url).query)['path'][0]
                    binding = parse_qs(urlsplit(destination).query)
                    check(profile, 'modify rejected V1 navigates the same session with exact parent, work and frozen skill version',
                          urlsplit(destination).path == '/chat/' + sid and binding['work'] == [wid] and binding['version'] == [v1_id]
                          and binding['skill'] == ['content-production']
                          and binding['skill_version'] == [str(next(skill['version'] for skill in v1['snapshot']['skills'] if skill['id'] == 'content-production'))])
                    page.wait_for_function("sid=>JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid)||'{}').command?.action_id==='change'", arg=sid)
                    modification = 'TEMP 只修改 V1：主体放大，减少背景细节；原图和原始来源保留。'
                    composer = page.get_by_role('textbox', name='对话输入', exact=True)
                    composer.fill(modification)
                    expect(page.get_by_role('button', name='发送', exact=True)).to_be_enabled()
                    page.get_by_role('button', name='发送', exact=True).click()
                    v2_history = helper.wait_history(page, origin, sid, v1_id, files=True)
                    v2_message = v2_history['session']['messages'][-1]
                    v2 = read_turn(v2_message['turnId'])
                    v2_id = v2['id']
                    scenario['v2_id'] = v2_id
                    payload2 = scenario['productions'][1]['payload']
                    check(profile, 'actual modification creates separate V2 with exact parent and inherited source, profile and skill snapshot',
                          v2['snapshot']['task'] == 'change' and v2['work']['work_id'] == wid and v2['work']['parent_version_id'] == v1_id
                          and v2['snapshot']['profile'] == v1['snapshot']['profile']
                          and [(skill['id'], skill['version']) for skill in v2['snapshot']['skills']] == [(skill['id'], skill['version']) for skill in v1['snapshot']['skills']]
                          and payload2['source_article'] == payload1['source_article'] and v2['message'] == modification
                          and v2_id != v1_id and all(sha(path) == digest for path, digest in scenario['productions'][0]['files'].items()))

                    def no_analysis(*args, **kwargs):
                        raise AssertionError('Only the explicit synthetic independent product check is allowed')

                    def inspector(service, request):
                        scenario['review_calls'].append({'job_id': request['job_id'], 'required_evidence_ids': [basis['id'] for basis in request['required_evidence']],
                                                         'artifacts': [{key: item[key] for key in ('artifact_name', 'sha256', 'mime')} for item in request['artifacts']]})
                        files = {item['artifact_name']: item for item in request['artifacts']}
                        findings = []
                        for basis in request['required_evidence']:
                            name = '成品.png' if basis.get('dimension') in ('image', 'style', 'main_style') else '标题与配文.txt'
                            actual = files[name]
                            assert sha(actual['path']) == actual['sha256']
                            anchor = {'type': 'region', 'x': 0, 'y': 0, 'width': 1, 'height': 1} if name.endswith('.png') else {'type': 'text', 'start': 0, 'end': 4, 'quote': actual['content'][:4]}
                            findings.append({'basis_id': basis['id'], 'status': 'pass', 'message': 'TEMP synthetic external inspection; protocol evidence only.',
                                             'artifact_name': name, 'sha256': actual['sha256'], 'location': 'TEMP actual original bytes', 'anchor': anchor})
                        return {'checker': 'synthetic', 'summary': 'TEMP fake independent inspection; no real AI or visual quality claim.', 'findings': findings}

                    review_worker = LearningWorker(app.state.learning, runner=no_analysis,
                                                   production_review=lambda service, task: run_review(service, task, runner=inspector),
                                                   batch_runner=no_analysis, distillation_runner=no_analysis)
                    for _ in range(30):
                        result = review_worker.process_one()
                        if result is None:
                            break
                    with box.store.connect() as connection:
                        review_run = app.state.learning.read_run(connection, v2_id)
                        quality = review_run['quality']
                        queued = connection.execute('SELECT status FROM learning_analysis_queue WHERE id=?', ('review-' + v2_id,)).fetchone()
                    scenario['quality'] = quality
                    check(profile, 'real independent review queue validates precise V2 artifact hashes and anchored findings before adoption',
                          quality['status'] == 'ready' and not quality['objective_missing'] and queued['status'] == 'completed'
                          and any(call['job_id'] == v2_id for call in scenario['review_calls']))
                    page.wait_for_function("sid=>!JSON.parse(localStorage.getItem('toolbox:draft:chat:'+sid)||'{}').pending", arg=sid)
                    helper.turn_view(page, v2_history).get_by_role('button', name='查看产物', exact=True).click()
                    expect(page.get_by_role('button', name='采纳并完成', exact=True)).to_be_visible()
                    screenshot(page, profile + '-06-v2-reviewed-preview.png')
                    download_link = page.locator('.ew-preview-image').get_by_role('link', name=re.compile('下载原件$'))
                    image_artifact = next(item for item in v2_message['output_files'] if item['mime'].startswith('image/'))
                    scenario['download_attempt'] = {'href': download_link.get_attribute('href'), 'artifact_id': image_artifact['id']}
                    with page.expect_download() as downloading:
                        download_link.click()
                    download = downloading.value
                    scenario['download_attempt'].update(url=download.url, failure=download.failure())
                    assert scenario['download_attempt']['failure'] is None, scenario['download_attempt']
                    download_path = out / (profile + '-v2-downloaded-product.png')
                    download.save_as(str(download_path))
                    check(profile, 'actual browser download returns the exact selected V2 original bytes',
                          image_artifact['id'] in download.url
                          and sha(download_path) == sha(box.file(image_artifact['id'])[1])
                          and sha(download_path) == next(digest for path, digest in scenario['productions'][1]['files'].items() if path.endswith('成品.png')))
                    scenario['download'] = {'url': download.url, 'artifact_id': image_artifact['id'], 'version_id': v2_id,
                                            'path': str(download_path), 'sha256': sha(download_path),
                                            'suggested_filename': download.suggested_filename,
                                            'scope': 'Actual Edge download event and bytes; physical WebToApp download manager not tested.'}
                    page.get_by_role('button', name='采纳并完成', exact=True).click()
                    adopt = page.get_by_role('dialog').filter(has=page.get_by_role('button', name='确认采纳并完成', exact=True))
                    expect(adopt.get_by_role('combobox', name='采纳后', exact=True)).to_have_value('archive')
                    adoption_note = 'TEMP 明确采纳 V2 的图片与配文，仅归档，不授权平台发布。'
                    adopt.get_by_label('采纳说明', exact=True).fill(adoption_note)
                    confirm = adopt.get_by_role('button', name='确认采纳并完成', exact=True)
                    expect(confirm).to_be_enabled()
                    screenshot(page, profile + '-07-accept-v2-dialog.png')
                    before_accept = len(adapter.requests)
                    with page.expect_response(lambda response: response.request.method == 'POST' and urlsplit(response.url).path == '/api/works/' + wid + '/actions') as accepted:
                        confirm.click()
                    assert accepted.value.ok, accepted.value.text()
                    accept_id = accepted.value.json()['id']
                    expect(adopt).not_to_be_visible()
                    completion = app.state.completion.process(accept_id)
                    check(profile, 'actual browser adoption binds exact V2, scopes and fresh completion preview without a model call',
                          completion['version_id'] == v2_id and completion['mode'] == 'archive'
                          and set(completion['scope']) == {'images', 'copy'} and completion['archive']['status'] == 'verified'
                          and len(adapter.requests) == before_accept)
                    archive = Path(completion['archive']['path'])
                    manifest = json.loads((archive / '完成清单.json').read_text(encoding='utf-8'))
                    check(profile, 'completion snapshot contains immutable actual adopted bytes, raw history and original attachment',
                          archive.is_relative_to(fixture['root'] / 'data/completions') and manifest['work_id'] == wid and manifest['version_id'] == v2_id
                          and all(sha(archive / entry['path']) == entry['sha256'] for entry in manifest['files'])
                          and any(entry['path'].startswith('原始附件/') and (archive / entry['path']).read_bytes() == attachment for entry in manifest['files'])
                          and rejection in (archive / '完整过程.json').read_text(encoding='utf-8')
                          and modification in (archive / '完整过程.json').read_text(encoding='utf-8'))
                    local_worker = LocalOperations(box, project=app.state.studio.project)
                    local_results = []
                    for _ in range(30):
                        result = local_worker.process_one()
                        if result is None:
                            break
                        local_results.append(result)
                    completion = app.state.completion.get(wid)['latest']
                    project_archive = completion['project_archive']
                    project_path = Path(project_archive['path']) if project_archive.get('path') else Path('/')
                    check(profile, 'real local operations archive the adopted bytes in the TEMP content project with a verified receipt',
                          project_archive['status'] == 'verified' and project_path.is_relative_to(app.state.studio.project)
                          and sha(project_path / '完成清单.json') == sha(archive / '完成清单.json')
                          and all(sha(project_path / entry['path']) == entry['sha256'] for entry in manifest['files']))
                    before_refresh = {'calls': len(adapter.requests), 'stream_posts': len(posts('/api/chat/stream')),
                                      'action_posts': len(posts('/api/works/' + wid + '/actions')), 'completion_count': len(app.state.completion.get(wid)['items'])}
                    page.reload(wait_until='domcontentloaded')
                    expect(page.get_by_role('button', name='采纳并完成', exact=True)).to_be_visible()
                    page.wait_for_timeout(600)
                    work = get('/api/works/' + wid)
                    check(profile, 'refresh preserves final adoption, earlier rejection and both versions without duplicate execution or decision',
                          work['decision']['id'] == accept_id and work['decision']['candidate_id'] == v2_id
                          and {version['id'] for version in work['versions']} == {v1_id, v2_id}
                          and len(adapter.requests) == before_refresh['calls'] == 3
                          and len(posts('/api/chat/stream')) == before_refresh['stream_posts'] == 3
                          and len(posts('/api/works/' + wid + '/actions')) == before_refresh['action_posts'] == 2
                          and len(app.state.completion.get(wid)['items']) == before_refresh['completion_count'] == 1)
                    check(profile, 'all source and version files remain intact and no publication or platform delivery is created',
                          all(sha(path) == digest for production in scenario['productions'] for path, digest in production['files'].items())
                          and not completion['publications'] and not app.state.completion.distribution.bootstrap()['deliveries']
                          and not (app.state.studio.project / '.git').exists() and not scenario['errors'])
                    check(profile, 'actual final viewport uses requested theme and has no horizontal page overflow',
                          page.evaluate('()=>document.documentElement.dataset.theme') == theme
                          and page.evaluate('()=>document.documentElement.scrollWidth<=innerWidth+1'))
                    screenshot(page, profile + '-08-completed-archive.png')
                    scenario.update(decisions={'rejection_id': reject_id, 'adoption_id': accept_id}, completion=completion,
                                    archive_manifest=manifest, local_results=local_results, actual_model_adapter_calls=len(adapter.requests))
                    context.close()
            browser.close()
        assert sha(__file__) == report['harness_sha256'], 'Harness source changed during acceptance'
        assert sha(ROOT / 'tests/workbench_native_browser.py') == report['fixture_sha256'], 'Shared fixture changed during acceptance'
        report['passed'] = True
    except Exception as error:
        report['error'] = repr(error)
        import traceback
        report['traceback'] = traceback.format_exc()
        if page is not None:
            try:
                report['failure_page'] = {'url': page.url, 'body': page.locator('body').inner_text()}
                screenshot(page, 'failure.png')
            except Exception:
                pass
    finally:
        report['runtime_modules'] = {name: {'file': str(Path(module.__file__).resolve()), 'sha256': sha(module.__file__)}
                                     for name, module in list(sys.modules.items())
                                     if (name == 'easel' or name.startswith('easel.') or name == 'easel_workbench' or name.startswith('easel_workbench.')) and getattr(module, '__file__', None)}
        report['module_roots_valid'] = bool(report['runtime_modules']) and all(Path(item['file']).is_relative_to(backend) for item in report['runtime_modules'].values())
        report['passed'] &= report['module_roots_valid']
        if backend_manifest:
            report['backend_files_valid'] = all(sha(backend / member) == digest for member, digest in backend_manifest['files'].items())
            report['passed'] &= report['backend_files_valid']
        shutil.copy2(__file__, out / 'harness.py')
        (out / 'content-closedloop-browser.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'error': report.get('error')}), flush=True)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
