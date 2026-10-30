"""Real Edge mobile reflow audit against immutable UI and a TEMP owner server.

The original native fixture supplies authentication/storage/routes. Only synthetic
data and explicit synthetic account/installation/model-discovery dependencies are
used. This runner never submits inference, installs software or writes a platform.
Inventory states are reported individually; a smoke run is not full acceptance.
"""
from __future__ import annotations

import argparse
import copy
import io
from contextlib import ExitStack
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import wave
from urllib.parse import urlencode, urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
MARK = 'MOBILE_AUDIT'
LONG = MARK + ' 窄屏已有数据：保留准确版本、原始反馈和未发送输入。' * 5


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def load_fixture(backend):
    sys.path.insert(0, str(backend))
    spec = importlib.util.spec_from_file_location('mobile_audit_native_fixture', ROOT / 'tests/workbench_native_browser.py')
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    fixture.ROOT = backend
    return fixture


def seed(fixture, image, video):
    """Materialize real TEMP records/files; no agent task is dispatched."""
    from easel_workbench.runtime.native_api import NativeApi
    box, root = fixture['box'], fixture['root']
    native = NativeApi(box)
    box._native_api = native
    native._save_ideas([{'id': 'mobile-topic-' + str(n), 'title': LONG + str(n),
                         'note': LONG, 'source': 'TEMP only', 'status': state}
                        for n, state in enumerate(('pending', 'doing', 'done'))])
    today = dt.date.today().isoformat()
    native._save_schedule([{'id': 'mobile-plan-' + str(n), 'title': LONG + str(n),
                            'date': today, 'time': '12:30', 'platform': '公众号',
                            'status': 'scheduled', 'note': LONG, 'kind': 'event' if n == 0 else 'content',
                            'source': 'manual', 'url': 'https://example.test/temp', 'event_type': '行业', 'end_date': today}
                           for n in range(8)])
    collection = fixture['app'].state.collection
    source, config = next(iter(collection.registry.baseline().items()))
    box.store.ingest({'schema_version': 1, 'source_job': source, 'feed_id': config['feed'],
                     'run_id': 'mobile-audit', 'run_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                     'final_text': 'TEMP only', 'articles': [
                         {'title': LONG + str(n), 'body': LONG, 'url': 'https://example.test/mobile/' + str(n), 'source_order': n}
                         for n in range(1, 21)]})
    folder = root / 'outputs' / 'MOBILE_AUDIT 已有素材与长文件名'
    folder.mkdir(parents=True)
    (folder / '封面.png').write_bytes(image)
    (folder / '正文.md').write_text('# ' + LONG + '\n\n' + LONG, encoding='utf-8')
    (folder / '排版.html').write_text('<!doctype html><meta name="viewport" content="width=device-width"><h1>' + LONG + '</h1>', encoding='utf-8')
    (folder / '合成视频.webm').write_bytes(video)
    sound = io.BytesIO()
    with wave.open(sound, 'wb') as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(8000)
        wav.writeframes(b'\x00\x00' * 1600)
    (folder / '合成音频.wav').write_bytes(sound.getvalue())
    work = 'mobile-audit-work'
    box.create({'id': work, 'title': LONG, 'material': LONG, 'format': 'poster', 'files': []})
    artifact = root / 'data/artifacts/mobile-audit-image.png'
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(image)
    copy = root / 'data/artifacts/mobile-audit-copy.txt'
    copy.write_text(LONG + '\n\n' + LONG, encoding='utf-8')
    video_file = root / 'data/artifacts/mobile-audit-video.webm'
    video_file.write_bytes(video)
    audio_file = root / 'data/artifacts/mobile-audit-audio.wav'
    audio_file.write_bytes(sound.getvalue())
    with box.store.connect() as c:
        c.execute('UPDATE toolbox_jobs SET status=?,reply=?,finished_at=? WHERE id=?',
                  ('completed', LONG + '\nTEMP seeded complete files; no inference.', dt.datetime.now(dt.timezone.utc).isoformat(), work))
        c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)', ('mobile-audit-image', work, '封面.png', str(artifact), 'image/png'))
        c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)', ('mobile-audit-copy', work, '标题与配文.txt', str(copy), 'text/plain'))
        c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)', ('mobile-audit-video', work, '合成视频.webm', str(video_file), 'video/webm'))
        c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)', ('mobile-audit-audio', work, '合成音频.wav', str(audio_file), 'audio/wav'))
    article = 'mobile-audit-article'
    box.create({'id': article, 'title': LONG, 'material': LONG, 'format': 'article', 'files': []})
    article_folder = root / 'data/artifacts/mobile-audit-article'
    article_folder.mkdir()
    article_body = article_folder / '正文.md'
    article_body.write_text('# ' + LONG + '\n\n' + LONG, encoding='utf-8')
    article_receipt = article_folder / '文章交付.json'
    article_receipt.write_text(json.dumps({'schema_version': 1, 'article_type': 'general', 'title': LONG,
                                         'body_file': '正文.md', 'sources': []}, ensure_ascii=False), encoding='utf-8')
    with box.store.connect() as c:
        c.execute('UPDATE toolbox_jobs SET status=?,reply=?,finished_at=? WHERE id=?',
                  ('completed', LONG, dt.datetime.now(dt.timezone.utc).isoformat(), article))
        c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)', ('mobile-audit-article-body', article, '正文.md', str(article_body), 'text/markdown'))
        c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)', ('mobile-audit-article-receipt', article, '文章交付.json', str(article_receipt), 'application/json'))
    session = fixture['app'].state.chat.create_session({'id': 'mobile-audit-session', 'profile_id': 'oil-pig'})['session']
    creator = fixture['app'].state.creator
    profile = next(p for p in creator.bootstrap()['profiles'] if p['id'] == 'oil-pig')
    creator.command({'id': 'mobile-profile-seed', 'action': 'profile-save', 'profile_id': profile['id'],
                     'base_revision': profile['revision'], 'document': {key: LONG for key in ('identity', 'audience', 'voice', 'boundaries')}})
    detail = creator.detail('skill', 'content-writing')
    candidate = creator.command({'id': 'mobile-skill-seed', 'action': 'skill-draft', 'skill_id': detail['id'],
                                 'base_version': detail['version'], 'prompt': detail['prompt'] + '\n\n' + LONG,
                                 'reason': LONG, 'conditions': {'description': LONG}, 'evidence_refs': []})['result']['skill']
    return {'work': work, 'version': work, 'article': article, 'session': session['id'], 'skill': detail['id'], 'skill_version': candidate['version'],
            'image_path': '__workbench__/mobile-audit-image/封面.png',
            'topics': 3, 'calendar_items': 8, 'news_items': 20, 'output_folder': str(folder)}


def synthetic_reads(f, ids):
    """Explicit, UI-only read fixtures for states that must not start a producer."""
    history = f['app'].state.chat.history(ids['session'])
    session = history['session']
    session.update(title=LONG, message_count=2)
    artifact = {'id': 'mobile-audit-image', 'name': '封面.png', 'mime': 'image/png', 'url': '/api/files/mobile-audit-image'}
    session['messages'] = [
        {'role': 'user', 'content': LONG, 'timestamp': 1793380000},
        {'id': 'mobile-audit-turn', 'turnId': 'mobile-audit-turn', 'role': 'assistant', 'content': LONG,
         'timestamp': 1793380000, 'status': 'completed', 'thinking': LONG, 'activity': LONG,
         'output_files': [artifact, {'id': 'mobile-audit-copy', 'name': '标题与配文.txt', 'mime': 'text/plain', 'url': '/api/files/mobile-audit-copy'},
                          {'id': 'mobile-audit-video', 'name': '合成视频.webm', 'mime': 'video/webm', 'url': '/api/files/mobile-audit-video'},
                          {'id': 'mobile-audit-audio', 'name': '合成音频.wav', 'mime': 'audio/wav', 'url': '/api/files/mobile-audit-audio'}],
         'questions': [{'id': 'mobile-audit-question', 'status': 'pending', 'expiresAtMs': 9999999999999,
                        'questions': [{'questionId': 'mobile-q1', 'header': 'TEMP 原生问题', 'question': LONG,
                                       'options': [{'label': '选项一', 'description': LONG}, {'label': '选项二', 'description': LONG}], 'multiSelect': True}]}]},
    ]
    work = f['box'].work(ids['work'])
    draft = copy.deepcopy(work)
    draft.update(id='mobile-audit-draft', versions=[], latest_version=None, pending=[], history=[], state='draft')
    draft['draft'].update(title=LONG, material=LONG, guidance=LONG)
    connection = {'id': 'mobile-audit-account', 'platform': 'wechat-oa', 'account': LONG[:70], 'label': LONG[:70],
                  'enabled': True, 'revision': 1, 'secret_configured': False,
                  'capabilities': {a: {'status': 'available', 'verified': True, 'account': LONG[:70], 'reason': 'TEMP fixture only'} for a in ('draft', 'publish', 'verify')}}
    revision = {'id': 'mobile-audit-revision', 'hash': '1' * 64, 'work_id': ids['work'], 'version_id': ids['version'],
                'connection_id': connection['id'], 'connection_revision': 1, 'platform': 'wechat-oa', 'account': connection['account'],
                'title': LONG, 'body': LONG, 'content_kind': 'article', 'asset_manifest': [], 'valid': True}
    publication = {'id': 'mobile-audit-publication', 'work_id': ids['work'], 'version_id': ids['version'], 'title': LONG,
                   'body': LONG, 'channel_id': 'wechat-oa', 'account': connection['account'], 'status': 'published',
                   'url': 'https://example.test/MOBILE_AUDIT/published', 'published_at': dt.datetime.now(dt.timezone.utc).isoformat(), 'revision': 1}
    studio = f['app'].state.studio.bootstrap()
    studio.update(publications=[publication], comments=[{'id': 'mobile-comment', 'publication_id': publication['id'], 'text': LONG, 'author': 'TEMP'}],
                  metrics=[{'id': 'mobile-metric', 'publication_id': publication['id'], 'window': 'custom', 'observed_at': publication['published_at'], 'values': {'views': 123, 'likes': 11}}],
                  analyses=[{'id': 'mobile-analysis', 'publication_id': publication['id'], 'question': LONG, 'status': 'completed', 'work_id': ids['work'], 'version_id': ids['version']}])
    distribution = {'schema_version': 1, 'platforms': [{'id': 'wechat-oa', 'name': '公众号', 'channel_id': 'wechat-oa', 'content_kinds': ['article']}],
                    'connections': [connection], 'revisions': [revision], 'approvals': [], 'batches': [], 'attempts': [], 'publications': [publication],
                    'runner': {'runtime': {'status': 'fixture_only'}, 'instances': []},
                    'deliveries': [{'id': 'mobile-delivery-' + state, 'work_id': ids['work'], 'account': connection['account'], 'platform': 'wechat-oa',
                                    'status': state, 'error': LONG if state != 'queued' else None, 'result': {'reason': LONG}}
                                   for state in ('queued', 'failed', 'unknown')]}
    experience = {'id': 'mobile-audit-experience', 'status': 'completed', 'result': {'analysis': {'summary': LONG, 'suggestions': [{'name': 'TEMP 建议', 'instructions': [LONG], 'reason': LONG}]},
                  'skill_id': ids['skill'], 'version': ids['skill_version'], 'profile_proposal_id': 'mobile-audit-proposal'}}
    proposal = {'id': 'mobile-audit-proposal', 'status': 'candidate', 'base_revision': 1,
                'fields': {'identity': LONG}, 'before': {'identity': LONG + ' 修改前'}, 'reasons': {'identity': LONG}, 'source_members': [LONG]}
    options = {'work_id': ids['work'], 'version_id': ids['version'], 'format': 'poster',
               'required_scopes': ['images', 'copy'], 'available_scopes': ['images', 'copy'], 'whole_ready': True,
               'creator': {'id': 'oil-pig', 'name': '油猪大侠', 'account_ids': [connection['id']]},
               'default': {'mode': 'archive', 'targets': [], 'manual_publications': []},
               'targets': [{'connection_id': connection['id'], 'platform': connection['platform'], 'channel_id': 'wechat-oa',
                            'account': connection['account'], 'label': connection['label'],
                            'actions': [{'action': 'draft', 'available': True, 'reason': 'TEMP fixture'}, {'action': 'publish', 'available': True, 'reason': 'TEMP fixture'}]}],
               'manual_channels': [{'id': 'wechat-oa', 'name': '公众号'}, {'id': 'xiaohongshu', 'name': '小红书'}], 'history': []}
    return {'/api/chat/sessions/' + ids['session']: history,
            '/api/chat/products/mobile-audit-turn': {'work_id': ids['work'], 'version_id': ids['version'], 'session_id': ids['session'], 'can_adopt': True, 'files': [artifact], 'text_blocks': [{'label': 'TEMP 配文', 'text': LONG}]},
            '/api/works/mobile-audit-draft': draft,
            '/api/studio/bootstrap': studio, '/api/distribution/bootstrap': distribution,
            '/api/works/' + ids['work'] + '/versions/' + ids['version'] + '/completion-options': options,
            '/api/creator/experience/mobile-audit-experience': experience,
            '/api/creator/profile-proposals/mobile-audit-proposal': proposal}, revision


MEASURE = """element=>{
 const visible=e=>{const r=e.getBoundingClientRect(),s=getComputedStyle(e);return r.width>0&&r.height>0&&s.visibility!=='hidden'&&s.display!=='none'&&!e.closest('[inert]')};
 const name=e=>e.tagName.toLowerCase()+(e.id?'#'+e.id:'')+(typeof e.className==='string'?'.'+e.className.trim().replace(/\\s+/g,'.'):'');
 const boundedScroller=p=>{const s=getComputedStyle(p),r=p.getBoundingClientRect();return ['auto','scroll'].includes(s.overflowX)&&p.scrollWidth>p.clientWidth+1&&r.left>=-2&&r.right<=innerWidth+2};
 const scroller=e=>{for(let p=e.parentElement;p&&p!==document.body;p=p.parentElement){if(p.matches('.subnav-tabs,.tabbar,.settings-nav,.ew-table-wrap,.kanban,pre,textarea,[data-mobile-audit-horizontal]')&&boundedScroller(p))return name(p)}return null};
 const box=element.getBoundingClientRect(),style=getComputedStyle(element),overflow=[];
 for(const child of element.querySelectorAll('*')){if(!visible(child)||['STYLE','SCRIPT','OPTION'].includes(child.tagName))continue;const r=child.getBoundingClientRect(),s=getComputedStyle(child);
  if(r.right>innerWidth+2||r.left< -2){const scroll=child.closest('pre,textarea,[data-mobile-audit-horizontal]'),scrollHost=scroller(child);overflow.push({selector:name(child),left:Math.round(r.left),right:Math.round(r.right),width:Math.round(r.width),text:(child.innerText||'').slice(0,90),intentional_code_scroll:!!scroll&&boundedScroller(scroll),horizontal_scroll_container:scrollHost,reflow_handled:!!scrollHost});}
 }
 const controls=[...element.querySelectorAll('button,input,select,textarea,a[href]')].filter(visible),fieldOverflow=[];
 for(const input of element.querySelectorAll('input:not([type=checkbox]):not([type=radio]):not([type=hidden]):not([type=file]),select,textarea')){if(!visible(input))continue;const r=input.getBoundingClientRect(),p=input.parentElement.getBoundingClientRect(),modal=input.closest('.modal,.ew-dialog,.drawer,.settings-panel'),m=modal?.getBoundingClientRect();if(r.right>p.right+2||r.left<p.left-2||m&&(r.right>m.right+1||r.left<m.left-1))fieldOverflow.push({selector:name(input),type:input.type,left:r.left,right:r.right,width:r.width,parentLeft:p.left,parentRight:p.right,modalRight:m?.right,clientWidth:input.clientWidth,scrollWidth:input.scrollWidth})}
 return {viewport:{width:innerWidth,height:innerHeight},rootWidth:document.documentElement.scrollWidth,rootOverflow:document.documentElement.scrollWidth>innerWidth+1,
  surface:{left:box.left,right:box.right,top:box.top,bottom:box.bottom,width:box.width,height:box.height,clientWidth:element.clientWidth,scrollWidth:element.scrollWidth,clientHeight:element.clientHeight,scrollHeight:element.scrollHeight,overflowX:style.overflowX,overflowY:style.overflowY},
  overflow:overflow.slice(0,25),overflowCount:overflow.length,fieldOverflow,controlCount:controls.length,
  shortTouchControls:controls.filter(e=>{const r=e.getBoundingClientRect();return e.tagName==='BUTTON'&&(r.height<43.5||r.width<43.5)}).map(e=>{const r=e.getBoundingClientRect();return {selector:name(e),width:r.width,height:r.height,text:(e.innerText||e.getAttribute('aria-label')||e.title||'').slice(0,80)}}),
  activeElement:name(document.activeElement),text:(element.innerText||'').slice(0,500)};
}"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--native', required=True, type=Path)
    parser.add_argument('--backend', required=True, type=Path)
    parser.add_argument('--out', required=True, type=Path)
    parser.add_argument('--phase', choices=('smoke', 'full'), default='smoke')
    parser.add_argument('--widths', default='320,360,390,430')
    parser.add_argument('--height', type=int, default=844)
    parser.add_argument('--themes', default='light,dark')
    parser.add_argument('--landscape', action='store_true')
    parser.add_argument('--skip-settings', action='store_true', help='Skip deep settings cases owned by the dedicated runner; retain panel/nested-dialog integration smoke in every viewport.')
    parser.add_argument('--preflight-only', action='store_true', help='Verify authentic media authorization/decode/iframe contracts before the full matrix.')
    parser.add_argument('--only-surfaces', default='', help='Comma-separated surface IDs for a diagnostic subset; never implies full coverage.')
    args = parser.parse_args()
    native, backend, out = args.native.resolve(), args.backend.resolve(), args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    front, frozen = read(native / 'native-manifest.json'), read(backend / 'workbench-release.json')
    assert all(sha(native / p) == h for p, h in front['files'].items())
    assert all(sha(backend / p) == h for p, h in frozen['files'].items())
    report = {'passed': False, 'phase': args.phase, 'created_at': dt.datetime.now(dt.timezone.utc).isoformat(),
              'native': {'directory': str(native), 'release': front['release'], 'manifest_sha256': sha(native / 'native-manifest.json')},
              'backend': {'directory': str(backend), 'release': frozen['release'], 'manifest_sha256': sha(backend / 'workbench-release.json')},
              'script_sha256': sha(__file__), 'checks': [], 'findings': [], 'requests': [], 'page_errors': [],
              'real_AI_calls': 0, 'real_platform_writes': 0, 'real_installations': 0, 'physical_mobile_device_tested': False,
              'scope': 'actual Windows Edge, simulated touch viewport; TEMP backend and real TEMP file bytes; smoke is not all-surface acceptance'}
    report['dashboard_design'] = 'mobile-dashboard-single-scroll-v2'
    report['preflight_only'] = args.preflight_only
    report['only_surfaces'] = [value for value in args.only_surfaces.split(',') if value]
    report['source'] = {'head_at_start': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip(),
                        'build_inputs_sha256': sha(native / 'build-inputs.json'), 'build_inputs': read(native / 'build-inputs.json')}
    fixtures = load_fixture(backend)
    from playwright.sync_api import sync_playwright, expect
    expect.set_options(timeout=12000)
    try:
        with tempfile.TemporaryDirectory(prefix='mobile-audit-bootstrap-', dir=out) as bootstrap, ExitStack() as stack:
            for name in ('sources.json', 'usage_registry.json', 'collection_schedules.json'):
                source = backend / 'easel_workbench/runtime' / name
                if source.is_file():
                    shutil.copy2(source, Path(bootstrap) / name)
            os.environ['AI_DESK_PROJECT_ROOT'] = bootstrap
            os.environ['PYTHONIOENCODING'] = 'utf-8'
            os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
            os.environ.pop('AI_DESK_RELEASE', None)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(channel='msedge', headless=True, args=['--ignore-certificate-errors'])
                blank = browser.new_page(viewport={'width': 600, 'height': 400})
                blank.set_content('<h1>MOBILE_AUDIT TEMP 合成素材</h1><p>真实文件，无模型。</p>')
                image = blank.screenshot()
                encoder = ROOT / '.runtime/media-tools/bin/ffmpeg.exe'
                assert encoder.is_file(), 'Project-local ffmpeg is required only to generate the TEMP media fixture'
                encode_args = [str(encoder), '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                               'color=c=0x3268a8:s=160x90:r=10:d=0.4', '-an', '-c:v', 'libvpx',
                               '-threads', '1', '-deadline', 'realtime', '-f', 'webm', 'pipe:1']
                encoded = subprocess.run(encode_args, check=True, capture_output=True, timeout=20)
                video = encoded.stdout
                assert len(video) > 256
                encoder_version = subprocess.run([str(encoder), '-version'], check=True, capture_output=True, timeout=10).stdout.decode(errors='replace').splitlines()[0]
                report['media_fixture_encoder'] = {'path': str(encoder), 'sha256': sha(encoder), 'version': encoder_version, 'command': encode_args,
                                                    'video_bytes': len(video), 'video_sha256': hashlib.sha256(video).hexdigest()}
                blank.close()
                with fixtures.isolated(native, image) as fixture:
                    fixture['close_clients'] = lambda: [context.close() for context in browser.contexts]
                    # The original fixture predates signed image capabilities.
                    # Supply the actual AuthState lock/session-table contract,
                    # never intercept or bypass the image authorization route.
                    from easel_workbench.runtime.auth_totp import token_hash
                    fixture['auth'].lock = threading.RLock()
                    fixture['auth'].data['sessions'] = {token_hash('fixture-owner'): dict(fixture['auth'].session('fixture-owner'))}
                    report['auth_fixture'] = {'contract': 'AuthState lock + token_hash keyed session table; real signed image route', 'authorization_bypassed': False}
                    ids = seed(fixture, image, video)
                    report['seed'] = ids
                    report['fixture_assets'] = {p.relative_to(fixture['root']).as_posix(): sha(p)
                        for folder in (fixture['root'] / 'outputs', fixture['root'] / 'data/artifacts')
                        for p in folder.rglob('*') if p.is_file()}
                    reads, channel_revision = synthetic_reads(fixture, ids)
                    report['synthetic_read_fixtures'] = {path: hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest() for path, value in reads.items()}
                    account_spec = importlib.util.spec_from_file_location('mobile_audit_accounts', ROOT / 'tests/workbench_base_browser.py')
                    account_module = importlib.util.module_from_spec(account_spec)
                    account_spec.loader.exec_module(account_module)
                    account_context = fixture['app'].state.easel_accounts.native_context()
                    synthetic_accounts = account_module.SyntheticAccounts(account_context, image)
                    fake_process = SimpleNamespace(**{key: getattr(subprocess, key) for key in dir(subprocess) if not key.startswith('__')})
                    fake_process.Popen, fake_process.run = synthetic_accounts.start, synthetic_accounts.run
                    account_context.namespace['subprocess'] = fake_process
                    from easel import harnesses
                    stack.enter_context(patch.object(harnesses, 'describe', lambda runtime: {'id': runtime, 'label': runtime, 'installed': True, 'protocol': 'TEMP synthetic detection', 'install_hint': 'TEMP'}))
                    from easel_workbench.runtime.connection_environment import service as environment_service, RECIPES
                    environment = environment_service(fixture['box'])
                    stack.enter_context(patch.object(environment, 'check', lambda: {'host': 'TEMP', 'system': 'Windows', 'tools': [
                        {'id': key, 'name': item['name'], 'state': 'missing' if n % 2 else 'ok', 'version': 'MOBILE_AUDIT', 'installable': True, 'group': item['group'], 'desc': LONG}
                        for n, (key, item) in enumerate(RECIPES.items())], 'jobs': []}))
                    sizes = [(int(w), args.height) for w in args.widths.split(',')]
                    if args.landscape:
                        if (844, 390) not in sizes:
                            sizes.append((844, 390))
                    for width, height in sizes:
                        for theme in args.themes.split(','):
                            context = browser.new_context(ignore_https_errors=True, viewport={'width': width, 'height': height},
                                                          is_mobile=True, has_touch=True, color_scheme=theme)
                            context.add_cookies([{'name': '__Host-desk_session', 'value': 'fixture-owner', 'url': fixture['origin'], 'secure': True, 'httpOnly': True, 'sameSite': 'Strict'}])
                            publish = {'title': LONG, 'body': LONG + '\n\n' + LONG, 'platforms': ['xiaohongshu', 'wechat-oa'], 'overrides': {}, 'tags': 'TEMP,移动验收'}
                            context.add_init_script('if(window===window.top){localStorage.setItem("native:theme",' + json.dumps(theme) + ');localStorage.setItem("easel_theme",' + json.dumps(theme) + ');localStorage.setItem("easel_publish_draft",' + json.dumps(json.dumps(publish, ensure_ascii=False)) + ');}')
                            context.add_init_script('if(window===window.top){localStorage.setItem(' + json.dumps('toolbox:draft:chat:' + ids['session']) + ',' + json.dumps(json.dumps({'text': LONG, 'files': []}, ensure_ascii=False)) + ');localStorage.setItem("toolbox:draft:creator:experience",' + json.dumps(json.dumps({'profile_id': 'oil-pig', 'goal': LONG, 'skill_id': ids['skill'], 'task_id': 'mobile-audit-experience', 'work_ids': [ids['work']]}, ensure_ascii=False)) + ');localStorage.setItem("toolbox:draft:easel:reference",' + json.dumps(json.dumps({'text': LONG, 'goal': LONG, 'task_id': 'mobile-audit-experience'}, ensure_ascii=False)) + ');}')
                            page = context.new_page()
                            page.set_default_timeout(12000)
                            label = f'{width}x{height}-{theme}'
                            page.on('pageerror', lambda error: report['page_errors'].append({'case': label, 'error': str(error)}))
                            def guard(route):
                                request = route.request
                                path = urlsplit(request.url).path
                                if urlsplit(request.url).netloc != urlsplit(fixture['origin']).netloc:
                                    route.abort(); return
                                if request.method not in ('GET', 'HEAD'):
                                    if path in ('/api/accounts/wechat-oa/mp-login', '/api/logout/wechat-oa'):
                                        report['requests'].append({'case': label, 'path': path, 'method': request.method, 'TEMP_synthetic_account_process': True})
                                        route.continue_(); return
                                    if path.endswith('/completion-preview'):
                                        route.fulfill(status=200, json={'plan_hash': '2' * 64, 'summary': LONG + ' TEMP UI preview, no authorization',
                                                                       'whole_work': True, 'archive': {}, 'publications': [], 'warnings': []}); return
                                    if path == '/api/chat/question/status':
                                        route.fulfill(status=200, json={'questions': {'mobile-audit-question': {'status': 'pending'}}}); return
                                    if path == '/api/distribution/commands' and (request.post_data_json or {}).get('action') == 'channel-prepare':
                                        report['requests'].append({'case': label, 'path': path, 'method': request.method, 'synthetic_ui_only': True})
                                        route.fulfill(status=200, json={'id': (request.post_data_json or {}).get('id'), 'status': 'completed', 'result': {'revision': channel_revision}}); return
                                    report['requests'].append({'case': label, 'path': path, 'method': request.method, 'blocked': True})
                                    route.fulfill(status=409, json={'error': 'MOBILE_AUDIT read-only UI run; operation not executed'})
                                    return
                                if path in reads:
                                    route.fulfill(status=200, json=reads[path]); return
                                route.continue_()
                            page.route('**/*', guard)
                            preflight = context.request.get(fixture['origin'] + '/api/works/' + ids['work'])
                            assert preflight.ok, ('TEMP work API failed', preflight.status, preflight.text())
                            picture = next(file for version in preflight.json()['versions'] for file in version['artifacts'] if file['mime'].startswith('image/'))
                            signed = context.request.get(fixture['origin'] + picture['image_url'])
                            assert signed.status == 200 and signed.headers.get('content-type', '').startswith('image/')
                            assert hashlib.sha256(signed.body()).hexdigest() == hashlib.sha256(image).hexdigest()
                            report.setdefault('media_authorization_preflight', []).append({'case': label, 'status': signed.status,
                                'source_id': picture['id'], 'mime': signed.headers['content-type'], 'sha256': hashlib.sha256(signed.body()).hexdigest(),
                                'signed_route_used': True, 'authorization_bypassed': False})
                            def go(path):
                                page.goto(fixture['origin'] + '/native/?' + urlencode({'path': path}), wait_until='domcontentloaded')
                            def capture(surface, selector, state='populated', marker=None):
                                candidates = page.locator(selector)
                                target = next((candidates.nth(i) for i in range(candidates.count()) if candidates.nth(i).is_visible()), None)
                                if target is None:
                                    expect(candidates.first).to_be_visible()
                                    target = candidates.first
                                expect(target).to_be_visible()
                                deadline = time.monotonic() + 2
                                while target.evaluate("el=>el.getAnimations({subtree:true}).some(a=>a.playState==='running'&&a.effect.getTiming().iterations!==Infinity)") and time.monotonic() < deadline:
                                    page.wait_for_timeout(30)
                                if marker:
                                    expect(target).to_contain_text(marker)
                                if surface == 'dashboard.main':
                                    expect(target.locator('.dash-idea-title').first).to_contain_text(MARK)
                                    expect(target.locator('.dash-sched-title').first).to_contain_text(MARK)
                                    if width <= 900 or width <= 1100 and height <= 500:
                                        expect(target.locator('.dash-card-list')).to_have_count(0)
                                if surface == 'library.preview' and state in ('image', 'populated'):
                                    expect(target.locator('img')).to_be_visible()
                                    expect(target.locator('img')).to_have_js_property('complete', True)
                                    assert target.locator('img').evaluate('img=>img.complete&&img.naturalWidth>0'), 'real TEMP preview bytes did not load'
                                if surface == 'library.preview' and state in ('video', 'audio'):
                                    expect(target.locator(state)).to_be_visible()
                                if surface == 'work.completion':
                                    expect(target.locator('fieldset')).to_be_visible()
                                expanded = []
                                if args.phase == 'full':
                                    # Real summary activation also fires native onToggle
                                    # resource reads; setting the open attribute would
                                    # skip the interaction we need to verify.
                                    for _ in range(80):
                                        summaries = target.locator('details:not([open]) > summary')
                                        closed = next((summaries.nth(i) for i in range(summaries.count()) if summaries.nth(i).is_visible()), None)
                                        if closed is None:
                                            break
                                        label_text = closed.inner_text().strip()
                                        closed.click()
                                        expanded.append(label_text)
                                        page.wait_for_timeout(30)
                                resources = []
                                for index in range(target.locator('img').count()):
                                    img = target.locator('img').nth(index)
                                    if not img.is_visible():
                                        continue
                                    img.scroll_into_view_if_needed()
                                    expect(img).to_have_js_property('complete', True)
                                    resource = img.evaluate('img=>({src:img.currentSrc||img.src,complete:img.complete,width:img.naturalWidth,height:img.naturalHeight})')
                                    assert resource['width'] > 0 and resource['height'] > 0, ('image failed to decode', surface, resource)
                                    resources.append({'kind': 'image', **resource})
                                for tag in ('video', 'audio'):
                                    for index in range(target.locator(tag).count()):
                                        media = target.locator(tag).nth(index)
                                        if not media.is_visible():
                                            continue
                                        media.scroll_into_view_if_needed()
                                        media.evaluate('el=>el.load()')
                                        deadline = time.monotonic() + 10
                                        while media.evaluate('el=>el.readyState<1&&!el.error') and time.monotonic() < deadline:
                                            page.wait_for_timeout(50)
                                        resource = media.evaluate('el=>({src:el.currentSrc||el.src,readyState:el.readyState,error:el.error?{code:el.error.code,message:el.error.message}:null,duration:Number.isFinite(el.duration)?el.duration:null})')
                                        assert resource['readyState'] >= 1 and resource['error'] is None, ('media metadata failed to load', surface, resource)
                                        resources.append({'kind': tag, **resource})
                                for index in range(target.locator('iframe').count()):
                                    iframe = target.locator('iframe').nth(index)
                                    if iframe.is_visible():
                                        frame = iframe.content_frame
                                        expect(frame.locator('body')).to_contain_text(MARK)
                                        resources.append({'kind': 'iframe', 'src': iframe.get_attribute('src'), 'actual_document_marker': MARK})
                                target.evaluate("el=>{for(let p=el;p;p=p.parentElement){p.scrollTop=0;p.scrollLeft=0}for(const child of el.querySelectorAll('.drawer-body,.settings-main,.page-scroll')){child.scrollTop=0}window.scrollTo(0,0)}")
                                text = target.inner_text().strip()
                                assert len(text) >= 8, (surface, 'no meaningful rendered content', text)
                                metrics = target.evaluate(MEASURE)
                                if surface == 'chat.composer':
                                    metrics['scroll_geometry'] = target.evaluate("el=>[el,...el.querySelectorAll('*')].filter(x=>x.scrollLeft||x.scrollWidth>x.clientWidth+1).map(x=>({tag:x.tagName,class:x.className,scrollLeft:x.scrollLeft,scrollTop:x.scrollTop,clientWidth:x.clientWidth,scrollWidth:x.scrollWidth,left:x.getBoundingClientRect().left,overflowX:getComputedStyle(x).overflowX}))")
                                file = out / (label + '-' + surface.replace('.', '-') + '-' + state + '.png')
                                page.screenshot(path=str(file))
                                item = {'case': label, 'surface_id': surface, 'state': state, 'selector': selector,
                                        'rendered': True, 'content_verified': True, 'metrics': metrics,
                                        'loaded_resources': resources,
                                        'details_opened_by_ui': expanded,
                                        'screenshot': str(file), 'screenshot_sha256': sha(file),
                                        'passed': not metrics['rootOverflow'] and not metrics['fieldOverflow'] and not any(not x['reflow_handled'] for x in metrics['overflow'])}
                                if surface == 'calendar.form' and state == 'edit_event':
                                    dates = target.locator('input[type=date]')
                                    expect(dates).to_have_count(2)
                                    item['date_field_geometry'] = [dates.nth(i).evaluate("el=>{const r=el.getBoundingClientRect(),p=el.parentElement.getBoundingClientRect();return {value:el.value,top:r.top,bottom:r.bottom,left:r.left,right:r.right,height:r.height,parentTop:p.top,parentBottom:p.bottom,position:getComputedStyle(el).position}}") for i in range(2)]
                                    first, second = item['date_field_geometry']
                                    overlap_x = min(first['right'], second['right']) - max(first['left'], second['left'])
                                    overlap_y = min(first['bottom'], second['bottom']) - max(first['top'], second['top'])
                                    item['date_fields_do_not_overlap'] = overlap_x <= 1 or overlap_y <= 1
                                    item['passed'] = item['passed'] and item['date_fields_do_not_overlap']
                                if surface == 'publishing.delivery':
                                    # A top-of-page screenshot is insufficient evidence for
                                    # receipts farther down the expanded delivery ledger.
                                    # Bring each actual state row into view and retain its
                                    # own text, bounds and screenshot without executing it.
                                    ledger = target.locator('.ew-panel').filter(has=page.get_by_role('heading', name='交付与回执', exact=True))
                                    rows = ledger.locator('.ew-ledger-row')
                                    expect(rows).to_have_count(3)
                                    item['delivery_receipts'] = []
                                    for receipt_index, status_text in enumerate(('已入队', '执行失败', '回执待核对')):
                                        row = rows.nth(receipt_index)
                                        expect(row).to_contain_text(status_text)
                                        expect(row).to_contain_text(MARK)
                                        row.locator('strong').scroll_into_view_if_needed()
                                        receipt_file = out / (label + '-publishing-delivery-receipt-' + str(receipt_index) + '.png')
                                        page.screenshot(path=str(receipt_file))
                                        item['delivery_receipts'].append({'status': status_text, 'text': row.inner_text(),
                                            'metrics': row.evaluate(MEASURE), 'screenshot': str(receipt_file), 'screenshot_sha256': sha(receipt_file)})
                                if target.evaluate("el=>el.matches('dialog,.modal,.drawer,.brush-panel,.sidebar-panel,.settings-panel')"):
                                    controls = target.locator('button:not(:disabled),input:not(:disabled):not([type=hidden]),select:not(:disabled),textarea:not(:disabled),a[href]')
                                    visible = [controls.nth(i) for i in range(controls.count()) if controls.nth(i).is_visible()]
                                    if visible:
                                        visible[0].focus()
                                        page.keyboard.press('Shift+Tab')
                                        focus = target.evaluate("el=>{const active=document.activeElement;return {inside:el.contains(active),tag:active.tagName,selector:active.tagName.toLowerCase()+(typeof active.className==='string'?'.'+active.className.trim().replace(/\\s+/g,'.'):''),native_modal:el.tagName==='DIALOG',aria_modal:el.getAttribute('aria-modal'),required_modal:el.tagName==='DIALOG'||el.matches('.modal,.drawer,.settings-panel')||el.getAttribute('aria-modal')==='true'}}")
                                        # Chromium may put focus in browser chrome (body is
                                        # activeElement); that is not a background control leak.
                                        background_control = not focus['inside'] and focus['tag'] not in ('BODY', 'HTML')
                                        trapped = not background_control
                                        visible[-1].focus()
                                        visible[-1].scroll_into_view_if_needed()
                                        bounds = visible[-1].bounding_box()
                                        reachable = bool(bounds and bounds['y'] >= -1 and bounds['y'] + bounds['height'] <= height + 1)
                                        bottom = out / (label + '-' + surface.replace('.', '-') + '-' + state + '-last-control.png')
                                        page.screenshot(path=str(bottom))
                                        item['keyboard_scroll'] = {'reverse_tab_stays_inside': trapped, 'last_control_reachable': reachable,
                                                                    'focus_after_reverse_tab': focus,
                                                                    'last_control_bounds': bounds, 'screenshot': str(bottom), 'screenshot_sha256': sha(bottom),
                                                                    'method': 'real Shift+Tab plus browser focus/scrollIntoView; trusted touch gestures audited separately'}
                                        if not trapped and focus['required_modal']:
                                            item['passed'] = False
                                            report.setdefault('keyboard_observations', []).append({'case': label, 'surface_id': surface,
                                                'kind': 'reverse_tab_leaves_overlay', 'selector': selector, 'screenshot': str(bottom)})
                                        if not reachable:
                                            item['passed'] = False
                                        escape_supported = focus['native_modal'] or surface in ('skills.drawer', 'chat.brush', 'settings.panel') or target.evaluate("el=>el.matches('.sidebar-panel')&&el.getAttribute('aria-modal')==='true'")
                                        item['keyboard_scroll']['escape_supported'] = escape_supported
                                        if focus['required_modal'] and escape_supported:
                                            page.keyboard.press('Escape')
                                            try:
                                                expect(target).not_to_be_visible(timeout=3000)
                                                item['keyboard_scroll']['escape_dismissed'] = True
                                            except Exception:
                                                item['keyboard_scroll']['escape_dismissed'] = False
                                                item['passed'] = False
                                                report.setdefault('keyboard_observations', []).append({'case': label, 'surface_id': surface,
                                                    'kind': 'escape_did_not_dismiss', 'selector': selector, 'screenshot': str(bottom)})
                                        elif focus['required_modal']:
                                            item['keyboard_scroll']['escape_not_applicable'] = 'Original shared div-overlay has no Escape handler; preserve source behavior and verify its actual close control.'
                                            if surface != 'accounts.login':
                                                buttons = target.locator('button')
                                                close_button = next((buttons.nth(i) for i in range(buttons.count())
                                                    if buttons.nth(i).is_visible() and (buttons.nth(i).inner_text().strip() in ('×', '✕', '关闭', '取消')
                                                       or buttons.nth(i).get_attribute('aria-label') == '关闭' or buttons.nth(i).get_attribute('title') == '关闭')), None)
                                                assert close_button is not None, ('No actual source close button found', surface)
                                                close_button.click()
                                                try:
                                                    expect(target).not_to_be_visible(timeout=3000)
                                                    item['keyboard_scroll']['source_close_button_dismissed'] = True
                                                except Exception:
                                                    item['keyboard_scroll']['source_close_button_dismissed'] = False
                                                    item['passed'] = False
                                report['checks'].append(item)
                                (out / 'progress.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
                                if not item['passed']:
                                    layout_failed = metrics['rootOverflow'] or metrics['fieldOverflow'] or any(not x['reflow_handled'] for x in metrics['overflow'])
                                    report['findings'].append({'surface_id': surface, 'case': label, 'kind': 'horizontal_overflow_or_clipping' if layout_failed else 'keyboard_or_control_reachability', 'screenshot': str(file), 'metrics': metrics, 'keyboard_scroll': item.get('keyboard_scroll')})
                                print(('PASS ' if item['passed'] else 'REFLOW ') + label + ' ' + surface + ' ' + state, flush=True)
                                return target
                            def run(surface, path, selector, state='populated', marker=None, before=None):
                                if report['only_surfaces'] and surface not in report['only_surfaces']:
                                    return
                                try:
                                    go(path)
                                    if before:
                                        before()
                                    capture(surface, selector, state, marker)
                                except Exception as error:
                                    file = out / (label + '-' + surface.replace('.', '-') + '-failure.png')
                                    page.screenshot(path=str(file))
                                    report['checks'].append({'case': label, 'surface_id': surface, 'state': state, 'passed': False,
                                                             'rendered': False, 'error': str(error), 'screenshot': str(file), 'screenshot_sha256': sha(file)})
                                    print('ERROR ' + label + ' ' + surface + ' ' + str(error)[:160], flush=True)
                            if args.preflight_only:
                                run('work.preview', '/works/' + ids['work'] + '?version=' + ids['version'], '.ew-work', 'poster_resources', marker=MARK)
                                run('library.preview', '/works?' + urlencode({'path': 'MOBILE_AUDIT 已有素材与长文件名/排版.html'}), '.drawer-overlay .drawer', 'html_iframe',
                                    before=lambda: expect(page.frame_locator('.drawer iframe').locator('body')).to_contain_text(MARK))
                                run('library.preview', '/works?' + urlencode({'path': 'MOBILE_AUDIT 已有素材与长文件名/合成视频.webm'}), '.drawer-overlay .drawer', 'video')
                                run('library.preview', '/works?' + urlencode({'path': 'MOBILE_AUDIT 已有素材与长文件名/合成音频.wav'}), '.drawer-overlay .drawer', 'audio')
                                assert not fixture['adapter'].requests
                                context.close()
                                continue
                            run('dashboard.main', '/toolbox', '.dash-page', marker=MARK)
                            run('trends.main', '/news', '.trends-page', marker=MARK)
                            def source_manager(kind='rss'):
                                page.get_by_role('button', name='数据源', exact=True).click()
                                expect(page.locator('.trend-manager-form')).to_be_visible()
                                expect(page.locator('.trend-manager-row').first).to_be_visible()
                                if kind != 'rss':
                                    page.get_by_role('button', name='接入方式', exact=True).click()
                                    page.get_by_role('option', name='HTTP 接口' if kind == 'http' else 'Python 脚本', exact=True).click()
                                if kind == 'http':
                                    page.locator('.trend-manager-form details summary').click()
                                    page.get_by_role('button', name='请求方式', exact=True).click()
                                    page.get_by_role('option', name='POST', exact=True).click()
                                    page.get_by_role('textbox', name='请求正文', exact=True).fill(json.dumps({'text': LONG}, ensure_ascii=False))
                                elif kind == 'python':
                                    page.get_by_role('textbox', name='Python 采集代码', exact=True).fill('# TEMP layout fixture; never saved or executed\nmessage = ' + repr(LONG) + '\nprint(message)')
                            run('trends.sources', '/news', 'dialog.trend-manager', 'rss_form', marker='添加来源', before=source_manager)
                            if args.phase == 'full':
                                run('trends.sources', '/news', 'dialog.trend-manager', 'http_post_body', marker='请求正文', before=lambda: source_manager('http'))
                                run('trends.sources', '/news', 'dialog.trend-manager', 'python_editor', marker='Python 采集代码', before=lambda: source_manager('python'))
                            run('topics.kanban', '/toolbox?section=research&pane=topics', '.ideas-page', marker=MARK)
                            run('topics.form', '/toolbox?section=research&pane=topics', '.overlay .modal', 'new_topic', before=lambda: page.get_by_role('button', name='+ 新建选题', exact=True).click())
                            def edit_topic():
                                page.locator('.idea-card').first.get_by_title('编辑', exact=True).click()
                                expect(page.locator('.modal .field').first).to_have_value(LONG + '0')
                            run('topics.form', '/toolbox?section=research&pane=topics', '.overlay .modal', 'edit_existing_topic', before=edit_topic)
                            run('calendar.month', '/toolbox?section=calendar', '.calendar-page', marker=MARK)
                            run('calendar.form', '/toolbox?section=calendar', '.overlay .modal', 'edit_content', marker=MARK,
                                before=lambda: page.locator('.cal-event:not(.is-event)').filter(has_text=MARK).first.click())
                            run('calendar.form', '/toolbox?section=calendar', '.overlay .modal', 'edit_event', marker=MARK,
                                before=lambda: page.locator('.cal-event.is-event').first.click())
                            run('breakdown.main', '/toolbox?section=research&pane=breakdown', '.breakdown-page', 'long_input',
                                before=lambda: page.locator('.breakdown-page textarea').fill(LONG))
                            run('library.main', '/works', '.gallery-page', marker=MARK)
                            run('library.preview', '/works?' + urlencode({'path': ids['image_path']}), '.drawer-overlay .drawer')
                            run('library.preview', '/works?' + urlencode({'path': 'MOBILE_AUDIT 已有素材与长文件名/正文.md'}), '.drawer-overlay .drawer', 'markdown', marker=MARK,
                                before=lambda: expect(page.locator('.outputs-viewer-content')).to_contain_text(MARK))
                            run('library.preview', '/works?' + urlencode({'path': 'MOBILE_AUDIT 已有素材与长文件名/排版.html'}), '.drawer-overlay .drawer', 'html_iframe',
                                before=lambda: expect(page.frame_locator('.drawer iframe').locator('body')).to_contain_text(MARK))
                            run('library.preview', '/works?' + urlencode({'path': 'MOBILE_AUDIT 已有素材与长文件名/合成视频.webm'}), '.drawer-overlay .drawer', 'video')
                            run('library.preview', '/works?' + urlencode({'path': 'MOBILE_AUDIT 已有素材与长文件名/合成音频.wav'}), '.drawer-overlay .drawer', 'audio')
                            work_path = '/works/' + ids['work'] + '?version=' + ids['version']
                            run('work.preview', work_path, '.ew-work', marker=MARK)
                            run('work.preview', '/works/' + ids['article'] + '?version=' + ids['article'], '.ew-work', 'article', marker=MARK)
                            run('work.manual-text', work_path, 'dialog.ew-dialog', 'existing_text_edit',
                                before=lambda: page.get_by_role('button', name='使用自写文案', exact=True).click())
                            run('work.reject', work_path, 'dialog.ew-dialog', before=lambda: page.get_by_role('button', name='不采纳', exact=True).click())
                            run('work.completion', work_path, 'dialog.ew-dialog', 'archive_scope',
                                before=lambda: page.get_by_role('button', name='采纳并完成', exact=True).click())
                            def completion_mode(mode):
                                page.get_by_role('button', name='采纳并完成', exact=True).click()
                                mode_select = page.locator('dialog .ew-field').filter(has_text='采纳后').locator('select')
                                mode_select.select_option(mode)
                                if mode == 'manual_published':
                                    for _ in range(3):
                                        page.get_by_role('button', name='添加已发布记录', exact=True).click()
                                else:
                                    expect(page.locator('dialog .ew-field').filter(has_text=LONG[:70]).locator('select')).to_be_visible()
                            run('work.completion', work_path, 'dialog.ew-dialog', 'delivery_targets', before=lambda: completion_mode('distribute'))
                            run('work.completion', work_path, 'dialog.ew-dialog', 'manual_publication', before=lambda: completion_mode('manual_published'))
                            run('skills.catalog', '/toolbox?section=skills', '.skills-page')
                            run('profiles.main', '/toolbox?section=profiles', '.profile-page')
                            run('profiles.create', '/toolbox?section=profiles&item=new', '.profile-page')
                            run('accounts.main', '/toolbox?section=distribution&pane=connections', '.accounts-page', marker='微信公众号')
                            run('publishing.main', '/toolbox?section=publications', '.publishing-workspace', marker=MARK)
                            if not args.skip_settings:
                                for tab in ['对话与脚本', '语音转写', '配音', '生图', '视频', '音乐']:
                                    run('settings.channels', '/settings?panel=model', '.settings-panel', tab,
                                        before=lambda tab=tab: page.get_by_role('dialog', name='设置', exact=True).get_by_role('button', name=tab, exact=True).click())
                                run('settings.environment', '/settings?panel=env', '.settings-panel', marker='环境安装')
                                run('settings.usage', '/settings?panel=more', '.settings-panel', marker='使用与路径')
                                run('settings.clear-usage', '/settings?panel=more', 'dialog.ew-dialog', before=lambda: page.get_by_role('button', name='清空统计', exact=True).click())
                            else:
                                run('settings.panel', '/settings?panel=model', '.settings-panel', 'model_section', marker='设置')
                                run('settings.clear-usage', '/settings?panel=more', 'dialog.ew-dialog', 'confirm_text', before=lambda: page.get_by_role('button', name='清空统计', exact=True).click())
                            if args.phase == 'full':
                                chat_path = '/chat/' + ids['session']
                                run('chat.composer', chat_path, '.chat-page', 'raw_multiline_draft', marker=MARK)
                                def commands():
                                    expect(page.get_by_role('textbox', name='对话输入', exact=True)).to_have_value(LONG)
                                    page.get_by_role('button', name='看看能做什么', exact=True).click()
                                    expect(page.locator('.brush-item').first).to_be_visible()
                                    page.locator('.brush-close').click()
                                    page.get_by_role('textbox', name='对话输入', exact=True).fill('/')
                                run('chat.command-menu', chat_path, '[role=menu][aria-label="选择技能"]', 'slash_search', before=commands)
                                run('chat.brush', chat_path, '.brush-panel[role=dialog]',
                                    before=lambda: page.get_by_role('button', name='看看能做什么', exact=True).click())
                                run('chat.questions', chat_path, '.question-card', 'multiple_choice', marker=MARK)
                                run('chat.artifacts', chat_path, '.artifact-gallery', 'image', marker='创作产物')
                                def artifact_media(index, tag):
                                    gallery = page.locator('.artifact-gallery')
                                    expect(gallery).to_be_visible()
                                    for _ in range(index):
                                        gallery.get_by_role('button', name='下一个产物', exact=True).click()
                                    expect(gallery.locator(tag)).to_be_visible()
                                run('chat.artifacts', chat_path, '.artifact-gallery', 'video', before=lambda: artifact_media(2, 'video'))
                                run('chat.artifacts', chat_path, '.artifact-gallery', 'audio', before=lambda: artifact_media(3, 'audio'))
                                run('chat.execution-details', chat_path, '.chat-turn-outputs', 'seeded_product_receipt', marker=MARK)
                                run('trends.detail-alias', '/news/a/mobile-audit-news', '.trends-page', 'current_alias_behavior', marker=MARK)
                                run('calendar.day', '/toolbox?section=calendar', '.overlay .modal', 'day_list_many_items', marker=MARK,
                                    before=lambda: page.locator('.cal-more').first.click())
                                run('work.draft', '/works/mobile-audit-draft', '.ew-work', 'existing_draft_edit', marker=MARK)
                                run('work.discussion', work_path + '&discuss=1', '.ew-work-chat', 'raw_draft',
                                    before=lambda: page.get_by_role('textbox', name='对话输入', exact=True).fill(LONG))
                                def records():
                                    page.get_by_role('button', name='版本与记录', exact=True).click()
                                    page.locator('.ew-work-records details summary').first.click()
                                run('work.records', work_path, '.ew-work-records', 'history_expanded', marker=MARK, before=records)
                                def annotate():
                                    expect(page.locator('.ew-work-copy')).to_be_visible()
                                    page.locator('.ew-work-copy').evaluate("el=>{const range=document.createRange();range.selectNodeContents(el);const selection=getSelection();selection.removeAllRanges();selection.addRange(range)}")
                                    page.locator('.ew-work-copy').dispatch_event('mouseup')
                                    page.get_by_role('textbox', name='批注意见', exact=True).fill(LONG)
                                run('work.annotation', work_path, '.ew-annotation', 'long_annotation_input', marker=MARK, before=annotate)
                                run('drafts.local', '/posters?drafts=1', '.page-scroll', 'nonempty_local_inputs', marker=MARK)
                                skill_path = '/toolbox?section=skills&item=' + ids['skill'] + '&version=' + str(ids['skill_version'])
                                def open_skill():
                                    page.locator('.skill-card').first.click()
                                    expect(page.locator('.drawer .skill-body-md')).to_be_visible()
                                run('skills.drawer', '/toolbox?section=skills', '.drawer-overlay .drawer', 'official_skill', before=open_skill)
                                run('skills.version', skill_path, 'dialog.ew-dialog', 'candidate_edit', marker=MARK,
                                    before=lambda: page.get_by_role('button', name='编辑方法，另存候选', exact=True).click())
                                run('skills.publish', skill_path, 'dialog[aria-label="发布技能版本"]', 'publish_scope',
                                    before=lambda: page.get_by_role('button', name='确认适用范围并发布', exact=True).click())
                                run('skills.experience', '/toolbox?section=skills&pane=experience', 'dialog.ew-dialog', 'completed_task', marker=MARK)
                                def proposal():
                                    page.get_by_text('作者身份', exact=True).click()
                                    expect(page.get_by_text('确认此字段', exact=True)).to_be_visible()
                                run('skills.profile-proposal', '/toolbox?section=skills&pane=experience', 'dialog.ew-dialog', 'candidate_before_after', marker=MARK, before=proposal)
                                def bindings():
                                    page.get_by_text('工作台扩展 · 素材、执行技能与账号绑定', exact=True).click()
                                run('profiles.bindings', '/toolbox?section=profiles&item=oil-pig', 'details.workbench-extension', 'default_tasks_expanded', before=bindings)
                                def unsaved():
                                    page.get_by_role('button', name='✏️ 编辑资料', exact=True).click()
                                    field = page.locator('.profile-dim textarea').first
                                    field.fill(LONG + ' 原字编辑未保存')
                                    seen = []
                                    def dismiss(dialog):
                                        seen.append(dialog.message)
                                        dialog.dismiss()
                                    page.once('dialog', dismiss)
                                    page.get_by_role('button', name='← 全部画像', exact=True).click()
                                    assert seen and '未保存' in seen[0]
                                    expect(field).to_have_value(LONG + ' 原字编辑未保存')
                                    report.setdefault('browser_dialogs', []).append({'case': label, 'surface_id': 'profiles.unsaved-confirm', 'message': seen[0], 'dismissed': True})
                                run('profiles.unsaved-confirm', '/toolbox?section=profiles&item=oil-pig', '.profile-page', 'cancel_retains_exact_text', before=unsaved)
                                def delivery():
                                    page.get_by_text('工作台扩展 · 准确版本交付与回执', exact=True).click()
                                    page.get_by_role('combobox', name='交付账号', exact=True).select_option('mobile-audit-account')
                                publish_path = '/toolbox?section=publications&work=' + ids['work'] + '&version=' + ids['version']
                                run('publishing.delivery', publish_path, 'details.workbench-extension', 'queued_failed_unknown_receipts', marker=MARK, before=delivery)
                                def approve():
                                    delivery()
                                    page.get_by_role('button', name='冻结并核对渠道稿', exact=True).click()
                                    page.get_by_role('button', name='核对并批准这份渠道稿', exact=True).click()
                                run('publishing.approve', publish_path, 'dialog.ew-dialog', 'draft_action', marker=MARK, before=approve)
                                insight_path = '/toolbox?section=insights&publication=mobile-audit-publication'
                                run('insights.main', insight_path, '.page-scroll', 'publication_selected', marker=MARK)
                                run('insights.publication-edit', insight_path, 'dialog.ew-dialog', 'existing_link_time',
                                    before=lambda: page.get_by_role('button', name='补充真实发布链接与时间', exact=True).click())
                                # High-risk non-data surfaces use genuine fixture UI events.
                                deep_case = not report['only_surfaces'] and ((width == 320 and theme == 'light') or (width == 390 and theme == 'dark') or height == 390)
                                if deep_case:
                                    account_path = '/toolbox?section=distribution&pane=connections'
                                    def qr_login():
                                        card = page.locator('.account-card').filter(has=page.locator('.account-card-name', has_text='微信公众号'))
                                        # Each theme uses a fresh browser context but shares
                                        # the TEMP backend. Wait for the actual persisted
                                        # account state before choosing logout or login.
                                        expect(card.get_by_role('button', name=re.compile(r'^(登录|退出登录)$'))).to_be_visible()
                                        if card.get_by_role('button', name='退出登录', exact=True).count():
                                            page.once('dialog', lambda dialog: dialog.accept())
                                            card.get_by_role('button', name='退出登录', exact=True).click()
                                            expect(card.get_by_role('button', name='登录', exact=True)).to_be_visible()
                                        card.get_by_role('button', name='登录', exact=True).click()
                                        expect(page.locator('.modal img.qr-img')).to_be_visible()
                                        expect(page.locator('.modal img.qr-img')).to_have_js_property('complete', True)
                                        assert page.locator('.modal img.qr-img').evaluate('img=>img.complete&&img.naturalWidth>0')
                                    run('accounts.login', account_path, '.overlay .modal', 'qr_ready', marker='请扫码', before=qr_login)
                                    def logout_cancel():
                                        assert synthetic_accounts.current
                                        synthetic_accounts.finish('success', 'MOBILE_AUDIT TEMP synthetic success receipt')
                                        expect(page.locator('.modal')).to_contain_text('登录成功 ✅')
                                        page.locator('.modal').get_by_role('button', name='完成', exact=True).click()
                                        card = page.locator('.account-card').filter(has=page.locator('.account-card-name', has_text='微信公众号'))
                                        expect(card.get_by_role('button', name='退出登录', exact=True)).to_be_visible()
                                        seen = []
                                        def dismiss(dialog):
                                            seen.append(dialog.message)
                                            dialog.dismiss()
                                        page.once('dialog', dismiss)
                                        card.get_by_role('button', name='退出登录', exact=True).click()
                                        assert seen and '退出' in seen[0]
                                        report.setdefault('browser_dialogs', []).append({'case': label, 'surface_id': 'accounts.logout-confirm', 'message': seen[0], 'dismissed': True})
                                    try:
                                        logout_cancel()
                                        capture('accounts.logout-confirm', '.accounts-page', 'cancel_preserves_connection', '微信公众号')
                                    except Exception as error:
                                        report['checks'].append({'case': label, 'surface_id': 'accounts.logout-confirm', 'state': 'cancel_preserves_connection', 'passed': False, 'rendered': False, 'error': str(error)})
                                    run('host.route-errors', '/works/MOBILE_AUDIT_MISSING', '.page-scroll', 'missing_work_retry', marker='读取作品')
                                    def open_nav():
                                        expect(page.locator('.sidebar .nav-item')).to_have_count(6)
                                        opener = page.get_by_role('button', name='打开导航', exact=True)
                                        if opener.is_visible():
                                            opener.click()
                                        else:
                                            expect(page.locator('.sidebar')).to_be_visible()
                                    run('nav.sidebar', chat_path, '.sidebar-panel', 'open_or_desktop_expanded', before=open_nav)
                                    def selectors():
                                        open_nav()
                                        expect(page.locator('.sidebar .nav-item')).to_have_count(6)
                                        toggle = page.locator('.sidebar .theme-toggle')
                                        before = page.locator('html').get_attribute('data-theme')
                                        toggle.click()
                                        assert page.locator('html').get_attribute('data-theme') != before
                                        toggle.click()
                                        assert page.locator('html').get_attribute('data-theme') == before
                                    run('nav.selectors', chat_path, '.sidebar-panel', 'theme_switch_and_six_tools', before=selectors)
                                    def boot_loading():
                                        held = []
                                        handler = lambda route: held.append(route)
                                        page.route('**/api/config', handler)
                                        go('/toolbox')
                                        capture('host.boot', '.ew-loading', 'lazy_loading', '正在连接工作台')
                                        for route in held:
                                            route.continue_()
                                        page.unroute('**/api/config', handler)
                                    try:
                                        boot_loading()
                                    except Exception as error:
                                        report['checks'].append({'case': label, 'surface_id': 'host.boot', 'state': 'lazy_loading', 'passed': False, 'rendered': False, 'error': str(error)})
                                    def expired(route):
                                        route.fulfill(status=401, json={'error': 'MOBILE_AUDIT fixture session expired'})
                                    try:
                                        page.route('**/api/status', expired)
                                        run('host.session-notices', '/toolbox', '.native-host-notice', 'session_expired', marker='登录已过期')
                                    finally:
                                        page.unroute('**/api/status', expired)
                                    try:
                                        go('/toolbox')
                                        expect(page.locator('.dash-page')).to_be_visible()
                                        deadline = time.monotonic() + 8
                                        while not page.evaluate('!!navigator.serviceWorker?.controller') and time.monotonic() < deadline:
                                            page.wait_for_timeout(100)
                                        assert page.evaluate('!!navigator.serviceWorker?.controller'), 'TEMP worker did not acquire control within 8 seconds'
                                        page.wait_for_timeout(400)
                                        context.set_offline(True)
                                        page.reload(wait_until='domcontentloaded')
                                        assert page.locator('meta[name="native-release"]').get_attribute('content') == front['release']
                                        expect(page.locator('.ew-loading')).to_be_visible()
                                        expect(page.locator('.ew-loading')).to_contain_text('保留的本机输入')
                                        capture('host.offline-shell', '.native-host', 'current_shell_available')
                                    except Exception as error:
                                        report['checks'].append({'case': label, 'surface_id': 'host.offline-shell', 'state': 'current_shell_available', 'passed': False, 'rendered': False, 'error': str(error)})
                                    finally:
                                        context.set_offline(False)
                                    try:
                                        context.clear_cookies()
                                        page.goto(fixture['origin'] + '/native/login', wait_until='domcontentloaded')
                                        capture('host.login', '.ew-auth', 'idle', '登录创作工作台')
                                    except Exception as error:
                                        report['checks'].append({'case': label, 'surface_id': 'host.login', 'state': 'idle', 'passed': False, 'rendered': False, 'error': str(error)})
                            assert not fixture['adapter'].requests, 'UI audit submitted inference'
                            context.close()
                    browser.close()
            report['passed'] = bool(report['checks']) and all(item['passed'] for item in report['checks']) and not report['page_errors']
    finally:
        report['covered_surfaces'] = sorted({item['surface_id'] for item in report['checks'] if item.get('rendered')})
        inventory = read(ROOT / 'docs/workbench/MOBILE-COVERAGE-20261031.json')
        report['not_yet_covered_surfaces'] = sorted(set(inventory['acceptance']['required_private_surface_ids']) - set(report['covered_surfaces']))
        report['all_required_private_surfaces_covered'] = not report['not_yet_covered_surfaces']
        report['keyboard_scope'] = {'overlay_cycles_observed': True, 'all_observed_cycles_retained': not report.get('keyboard_observations'),
                                    'observations_are_not_layout_passes': True}
        report['completed_at'] = dt.datetime.now(dt.timezone.utc).isoformat()
        report['native_files'] = front['files']
        report['all_native_bytes_verified'] = all(sha(native / p) == h for p, h in front['files'].items())
        report['all_backend_bytes_verified'] = all(sha(backend / p) == h for p, h in frozen['files'].items())
        modules = {}
        for name, module in sys.modules.items():
            if name == 'easel' or name.startswith('easel.') or name == 'easel_workbench' or name.startswith('easel_workbench.'):
                filename = getattr(module, '__file__', None)
                if filename:
                    file = Path(filename).resolve()
                    modules[name] = {'file': str(file), 'sha256': sha(file), 'within_backend': file.is_relative_to(backend)}
        report['runtime_modules'] = modules
        report['module_roots_valid'] = bool(modules) and all(m['within_backend'] for m in modules.values())
        report['passed'] = report['passed'] and report['all_native_bytes_verified'] and report['all_backend_bytes_verified'] and report['module_roots_valid']
        report['evidence'] = {str(p): sha(p) for p in out.glob('*.png')}
        report['evidence'][str(Path(__file__))] = sha(__file__)
        (out / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'passed': report['passed'], 'checks': len(report['checks']), 'covered_surfaces': len(report['covered_surfaces']), 'report': str(out / 'report.json')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
