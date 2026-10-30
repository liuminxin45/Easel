"""Authenticated host adapters for the original Easel page protocols.

Native presentation and native handlers are shared with ``web.app``. This layer
only supplies server-owned repositories, exact-version links and the private
operation boundary. The outer application owns authentication, CSRF and admission.
"""
from __future__ import annotations

import asyncio
import copy
import datetime as dt
import hashlib
import inspect
import json
import os
import re
import shutil
import subprocess
import threading
import tempfile
import time
from pathlib import Path
from urllib.parse import unquote

from fastapi import HTTPException
from starlette.responses import FileResponse, JSONResponse, Response

from easel.web_services.outputs import create_outputs_context
from easel.web_services.planning import create_planning_context
from easel_workbench.runtime.desk import stamp
from easel_workbench.runtime.toolbox_store import ident, pack


PROFILE_FILES = {'identity.md': 'identity', 'style.md': 'voice',
                 'audience.md': 'audience', 'preferences.md': 'boundaries'}
EXTRA_PROFILE_FILES = {'platforms.md', 'memory.md'}
WRITE_METHODS = {'POST', 'PUT', 'PATCH', 'DELETE'}

# These exact protocols already belong to the authenticated host. Ordinary
# output directories named images/accounts/jobs still use native media serving.
HOST_DISPLAY_IMAGE = re.compile(r'/api/media/images/([A-Za-z0-9_-]{1,128})/([a-f0-9]{64})/(original|thumb-256)')
HOST_MEDIA_JOB = re.compile(r'/api/media/jobs/([A-Za-z0-9_-]+)(/transcript)?')
HOST_ACCOUNT_QR = re.compile(r'/api/(?:platform-accounts|media/accounts)/([A-Za-z0-9_-]+)/qr')


def is_host_media_protocol(path):
    return path == '/api/media/accounts' or any(pattern.fullmatch(path) for pattern in (
        HOST_DISPLAY_IMAGE, HOST_MEDIA_JOB, HOST_ACCOUNT_QR))

# A server-owned capability, never a request/response header supplied by a client.
# HTML keeps the same opaque-origin script sandbox as the original OutputsPage.
_HTML_PREVIEW = object()
HTML_PREVIEW_CSP = (
    "default-src 'none'; sandbox allow-scripts; frame-ancestors 'self'; "
    "script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
    "img-src data: blob:; media-src data: blob:; font-src data:; "
    "connect-src 'none'; form-action 'none'; base-uri 'none'; "
    "frame-src 'none'; object-src 'none'; worker-src 'none'"
)


class _HtmlPreviewFileResponse(FileResponse):
    async def __call__(self, scope, receive, send):
        # A preview is one complete HTML document. FileResponse otherwise makes
        # late range-error responses after the outer security policy has run.
        scope = {**scope, 'headers': [(key, value) for key, value in scope['headers']
                                    if key.lower() not in (b'range', b'if-range')]}
        await super().__call__(scope, receive, send)


def is_html_preview_response(response):
    """Recognize only a successful HTML response created after output validation."""
    return (
        getattr(response, '_easel_html_preview', None) is _HTML_PREVIEW
        and response.status_code == 200
        and response.headers.get('content-type', '').split(';', 1)[0] == 'text/html'
        and response.headers.get('content-security-policy') == HTML_PREVIEW_CSP
        and not response.headers.get('content-disposition', '').lower().startswith('attachment')
    )


def _protect_html_preview(response, *, preview):
    if response.headers.get('content-type', '').split(';', 1)[0] == 'text/html':
        # These restrictions also apply when HTML is opened in a new tab or
        # downloaded. No network, parent DOM, cookies, forms or nested frames.
        if isinstance(response, FileResponse):
            response = _HtmlPreviewFileResponse(
                response.path, status_code=response.status_code,
                headers=dict(response.headers), media_type=response.media_type,
                background=response.background, stat_result=response.stat_result)
        response.headers['Content-Security-Policy'] = HTML_PREVIEW_CSP
        response.headers['Cache-Control'] = 'private, no-store'
        response.headers['Accept-Ranges'] = 'none'
        if isinstance(response, FileResponse) and response.stat_result is None:
            # The outer HEAD response omits the body before FileResponse.__call__.
            response.stat_result = Path(response.path).stat()
            response.set_stat_headers(response.stat_result)
        if preview:
            response._easel_html_preview = _HTML_PREVIEW
        else:
            response.headers['Content-Disposition'] = 'attachment'
    return response


def supports(path, method=None):
    """Pure route ownership check used before the outer legacy-route guard."""
    if is_host_media_protocol(path):
        return False
    routes = (
        r'/api/native/operations/[A-Za-z0-9_-]+', r'/api/upload',
        r'/api/outputs', r'/api/output-context', r'/api/(?:output|media)/.+',
        r'/api/artifacts/archive', r'/api/personas', r'/api/persona/[^/]+(?:/(?:files|file))?',
        r'/api/ideas(?:/[A-Za-z0-9_-]+)?', r'/api/schedule(?:/(?:context|[A-Za-z0-9_-]+))?',
        r'/api/trends(?:/(?:sources|manage))?', r'/api/publishing-policy',
        r'/api/manual-publish/[a-z-]+/export',
        r'/api/analytics(?:/[^/]+)?', r'/api/accounts(?:/[a-z-]+(?:/(?:whoami|credentials|mp-login(?:/status)?))?)?',
        r'/api/login/[a-z-]+(?:/(?:status|sms))?', r'/api/logout/[a-z-]+',
    )
    return (method is None or method in {'GET', 'HEAD', 'POST', 'PUT', 'DELETE', 'PATCH'}) and any(
        re.fullmatch(pattern, path) for pattern in routes)


def _seconds(value):
    try:
        return int(dt.datetime.fromisoformat(str(value).replace('Z', '+00:00')).timestamp())
    except (ValueError, TypeError):
        return 0


class NativeApi:
    """One compatibility adapter per private application, never another writer."""

    def __init__(self, box):
        self.box, self.store, self.root = box, box.store, Path(box.root).resolve()
        from easel_workbench.runtime.easel_frontend import service
        self.frontend = service(box)
        self._write_lock = asyncio.Lock()
        self._repository_lock = threading.RLock()
        self._operation = ''
        with self.store.connect() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS native_profile_documents(
                profile_id TEXT NOT NULL, filename TEXT NOT NULL, revision INTEGER NOT NULL,
                content TEXT NOT NULL, PRIMARY KEY(profile_id,filename,revision))''')
        self.outputs = create_outputs_context(self.root)
        self.planning = create_planning_context(
            self.root, scripts=Path(__file__).resolve().parents[2] / 'skills/shared/scripts',
            read_ideas=self._ideas, write_ideas=self._save_ideas,
            read_schedule=self._schedule, write_schedule=self._save_schedule,
            lock=self._repository_lock)

    def receipt(self, operation):
        with self.store.connect() as c:
            row = c.execute('SELECT result FROM easel_ui_operations WHERE id=?', (ident(operation),)).fetchone()
        if row:
            value = json.loads(row['result'])
            if value.get('native_protocol'):
                return {key: value.get(key) for key in ('id', 'state', 'result')}
        return {'id': operation, 'state': 'unavailable', 'result': None}

    async def _mutate(self, request, body, action):
        # The original request identity is checked before deriving any revision.
        operation = ident(request.headers.get('x-operation-id'))
        fields = dict(body)
        signature = hashlib.sha256(pack({'method': request.method, 'path': request.url.path,
                                         'body': fields}).encode()).hexdigest()
        async with self._write_lock:
            with self.store.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                previous = c.execute('SELECT signature,result FROM easel_ui_operations WHERE id=?', (operation,)).fetchone()
                if previous:
                    if previous['signature'] != signature:
                        raise HTTPException(409, '同一操作不能改变内容')
                    saved = json.loads(previous['result'])
                    if not saved.get('native_protocol'):
                        raise HTTPException(409, '操作标识已用于其他流程')
                    if saved['state'] != 'completed':
                        raise HTTPException(409, '原操作结果尚未核对；不会自动重新执行')
                    return saved['result']
                self._require_admission()
                pending = {'id': operation, 'native_protocol': True, 'state': 'unavailable', 'result': None}
                c.execute('INSERT INTO easel_ui_operations VALUES(?,?,?)', (operation, signature, pack(pending)))
            self._operation = operation
            try:
                result = action(fields)
                if inspect.isawaitable(result):
                    result = await result
                if isinstance(result, Response):
                    raise HTTPException(400, '此操作不能以文件回执保存')
                saved = {**pending, 'state': 'completed', 'result': result}
            except (HTTPException, ValueError) as error:
                saved = {**pending, 'state': 'rejected',
                         'result': {'detail': str(error.detail if isinstance(error, HTTPException) else error)}}
                with self.store.connect() as c:
                    c.execute('UPDATE easel_ui_operations SET result=? WHERE id=?', (pack(saved), operation))
                raise
            finally:
                self._operation = ''
            with self.store.connect() as c:
                c.execute('UPDATE easel_ui_operations SET result=? WHERE id=?', (pack(saved), operation))
            return result

    def _require_admission(self):
        state = self.root / '.local/workbench-deployment'
        controlled = (state / 'admission.json').exists() or os.environ.get('EASEL_WORKBENCH_ADMISSION') == '1'
        if controlled:
            try:
                admitted = json.loads((state / 'admission.json').read_text(encoding='utf-8')).get('workers') is True
            except (OSError, ValueError, AttributeError):
                admitted = False
            if not admitted or (state / 'paused').exists():
                raise HTTPException(503, '服务切换中，原输入和操作身份已保留')
        for path in (state / 'cutover.json', self.root / 'data/migration-owner.json'):
            if not path.exists():
                continue
            try:
                document = json.loads(path.read_text(encoding='utf-8'))
                if Path(document['target_root']).resolve() != self.root:
                    raise HTTPException(503, '当前目录不是已授权业务写入者')
                if path.name == 'cutover.json' and document.get('phase') != 'live':
                    raise HTTPException(503, '迁移尚未进入业务写入阶段')
            except (OSError, ValueError, KeyError, TypeError):
                raise HTTPException(503, '业务写入身份暂不可核对') from None

    async def _upload(self, request):
        from email import policy
        from email.parser import BytesParser
        content_type = request.headers.get('content-type', '')
        if not content_type.lower().startswith('multipart/form-data;') or any(char in content_type for char in '\r\n\x00'):
            raise HTTPException(415, '附件需要 multipart/form-data')
        raw_body = await request.body()
        if len(raw_body) > 50 * 1024 * 1024:
            raise HTTPException(413, '单次附件请求需在50MB以内')
        message = BytesParser(policy=policy.default).parsebytes(
            b'Content-Type: ' + content_type.encode('ascii') + b'\r\nMIME-Version: 1.0\r\n\r\n' + raw_body)
        if not message.is_multipart() or message.defects:
            raise HTTPException(400, '附件表单格式无效')
        scope = None
        payloads = []
        for part in message.iter_parts():
            name = part.get_param('name', header='content-disposition')
            raw = part.get_payload(decode=True)
            if not isinstance(raw, bytes):
                raise HTTPException(400, '附件格式无效')
            if name == 'sessionId' and part.get_filename() is None:
                if scope is not None:
                    raise HTTPException(400, '会话标识不能重复')
                scope = ident(raw.decode('utf-8'))
            elif name == 'files':
                if not 0 < len(raw) <= 20 * 1024 * 1024:
                    raise HTTPException(413, '每个附件需在20MB以内')
                payloads.append((part.get_filename() or 'file', raw))
            else:
                raise HTTPException(400, '附件表单含有不支持的字段')
        if scope is None or not 1 <= len(payloads) <= 16:
            raise HTTPException(400, '请选择1至16个附件及准确会话')
        proof = {'sessionId': scope, 'files': [{'name': name, 'sha256': hashlib.sha256(raw).hexdigest()}
                                             for name, raw in payloads]}
        def save(_):
            with self.store.connect() as c:
                table = c.execute("SELECT 1 FROM sqlite_master WHERE name='easel_chat_sessions'").fetchone()
                if not table or not c.execute('SELECT 1 FROM easel_chat_sessions WHERE id=?', (scope,)).fetchone():
                    raise HTTPException(404, '原生会话不存在')
            saved = []
            for index, (name, raw) in enumerate(payloads):
                file_id = 'native-upload-' + hashlib.sha256((self._operation + ':' + str(index)).encode()).hexdigest()[:32]
                value = self.box.upload(file_id, name, raw)
                saved.append({'id': value['id'], 'name': value['name'], 'path': value['id']})
            return {'ok': True, 'files': saved}
        return await self._mutate(request, proof, save)

    def _collection(self):
        if not getattr(self, '_collection_service', None):
            from easel_workbench.runtime.collection_service import CollectionService
            self._collection_service = CollectionService(self.store, self.root)
        return self._collection_service

    def analytics_context(self):
        if not getattr(self, '_analytics', None):
            from easel.web_services.analytics import create_analytics_context
            from easel_workbench.runtime.easel_accounts import service as accounts_service
            from easel_workbench.runtime.connection_environment import service as environment_service
            from easel_workbench.runtime.easel_connection_support import safe_env
            accounts = accounts_service(self.box)
            native = accounts.native_context()
            environment = environment_service(self.box)
            def guard(platform):
                self._require_admission()
                if not environment.python.is_file():
                    raise HTTPException(400, '请先在设置中安装平台连接依赖')
            self._analytics = create_analytics_context(
                self.root, native, scripts=Path(__file__).resolve().parents[2] / 'skills/shared/scripts',
                environment=lambda: safe_env(environment.child_environment(), self.root),
                python=environment.python, guard=guard)
            accounts._native_analytics_context = self._analytics
        return self._analytics

    def _invalidate_analytics(self, accounts):
        # The original native service deduplicates by platform. A private
        # account switch must not join a task started for its previous identity.
        previous = getattr(self, '_analytics', None)
        if previous is not None:
            previous._stop_analytics_on_shutdown()
            self._analytics = None
        if getattr(accounts, '_native_analytics_context', None) is previous:
            accounts._native_analytics_context = None

    def _prepare_account_login(self, accounts, platform):
        previous = accounts._native_session(platform)
        before = (previous['id'], previous.get('_profile_generation', 0)) if previous else None
        accounts.prepare_native_login(platform, self._operation)
        current = accounts._native_session(platform)
        after = (current['id'], current.get('_profile_generation', 0)) if current else None
        if after != before:
            self._invalidate_analytics(accounts)

    def _trends(self, request):
        collection = self._collection()
        definitions = collection.definitions()
        status = {row['id']: row for row in collection.status().get('sources', [])}
        available = {key: value for key, value in definitions.items() if value['enabled']}
        requested = request.query_params.get('platforms')
        selected = list(available) if requested is None else list(dict.fromkeys(
            key for key in requested.split(',') if key in available))
        limit = max(1, min(int(request.query_params.get('limit', '1000')), 1000))
        groups = []
        for key in selected:
            rows = self.store.article_day(source=key)['items']
            latest = status.get(key, {}).get('last_task') or {}
            failed = latest.get('status') == 'failed'
            busy = latest.get('status') in {'queued', 'running'}
            groups.append({'platform': key, 'label': available[key]['label'], 'ok': not failed,
                           'status': 'stale' if failed and rows else 'error' if failed else 'fresh',
                           'stale': (failed or busy) and bool(rows), 'fetched_at': rows[0].get('run_at') if rows else None,
                           'last_attempt_at': _seconds(latest.get('created_at')),
                           'error': {'code': 'busy', 'message': '正在采集，先显示已保存结果'} if busy else
                                    {'code': 'collection_failed', 'message': str(latest.get('error') or '上次采集未完成')} if failed else None,
                           'items': [{'id': item['id'], 'title': item['title'], 'hot': str(item.get('hot') or ''),
                                      'url': item.get('url', ''), 'published_at': item.get('published_at'),
                                      'heat': {'value': None, 'text': str(item.get('hot') or ''), 'unit': ''}}
                                     for item in rows[:limit]]})
        return {'version': 1, 'trends': groups, 'updated': int(time.time()), 'warnings': []}

    def _ideas(self):
        return [{**item, 'created': item.get('created', _seconds(item.get('created_at')))}
                for item in self.frontend.topics()['items']]

    def _save_ideas(self, items):
        self._save_records('easel_topics', 'easel_topic_history', items)

    def _schedule(self):
        answer = []
        for item in self.frontend.plans()['items']:
            if item.get('deleted'):
                continue
            if item.get('native_schedule'):
                answer.append({**item['native_schedule'], 'id': item['id'], 'revision': item['revision']})
                continue
            when = str(item.get('scheduled_at') or '')
            answer.append({'id': item['id'], 'revision': item['revision'], 'title': item.get('title', ''),
                           'date': when[:10], 'time': when[11:16], 'note': item.get('note', ''),
                           'status': 'draft' if item.get('status') == 'cancelled' else 'scheduled',
                           'platform': '', 'kind': 'content', 'source': 'manual', 'url': '',
                           'work_id': item.get('work_id'), 'version_id': item.get('version_id')})
        return answer

    def _save_schedule(self, items):
        self._save_records('easel_plans', 'easel_plan_history', items, schedule=True)

    def _save_records(self, table, history, items, *, schedule=False):
        # Normalization/CRUD is performed by the shared original handlers. The
        # repository only versions the resulting records and keeps tombstones.
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = {row['id']: json.loads(row['document']) for row in c.execute(f'SELECT * FROM {table}')}
            present = {ident(item['id']) for item in items}
            changes = []
            for item in items:
                key = ident(item['id']); previous = old.get(key, {})
                if schedule:
                    old_projection = next((x for x in self._schedule() if x['id'] == key), None)
                    if old_projection and all(old_projection.get(k) == v for k, v in item.items()):
                        continue
                    native = {k: v for k, v in item.items() if k not in {'revision', 'work_id', 'version_id'}}
                    document = {**previous, 'id': key, 'native_schedule': native, 'title': item['title'],
                                'note': item.get('note', ''), 'automatic_publication': False,
                                'scheduled_at': item['date'] + 'T' + (item.get('time') or '00:00') + ':00+08:00',
                                'status': previous.get('status', 'planned')}
                else:
                    if previous and all(previous.get(k) == v for k, v in item.items() if k != 'revision'):
                        continue
                    document = {**previous, **{k: v for k, v in item.items() if k != 'revision'}, 'deleted': False}
                document.update(revision=previous.get('revision', 0) + 1,
                                created_at=previous.get('created_at', stamp()), updated_at=stamp())
                changes.append(document)
            for key, previous in old.items():
                if key not in present and not previous.get('deleted'):
                    changes.append({**previous, 'deleted': True, 'revision': previous['revision'] + 1, 'updated_at': stamp()})
            for document in changes:
                raw = pack(document)
                c.execute(f'INSERT INTO {table} VALUES(?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document', (document['id'], raw))
                c.execute(f'INSERT INTO {history} VALUES(?,?,?)', (document['id'], document['revision'], raw))

    def _profiles(self):
        return self.box.creator.bootstrap()['profiles']

    def _profile(self, name):
        profiles = self._profiles()
        exact = [value for value in profiles if value['id'] == name]
        matches = exact or [value for value in profiles if value['name'] == name]
        if len(matches) != 1:
            raise HTTPException(409 if matches else 404, '画像名称不唯一，请使用准确画像标识' if matches else '画像不存在')
        return matches[0]

    def _profile_files(self, name):
        profile = self._profile(name)
        files = [{'filename': filename, 'content': profile.get(field, '')} for filename, field in PROFILE_FILES.items()]
        with self.store.connect() as c:
            for filename in sorted(EXTRA_PROFILE_FILES):
                row = c.execute('''SELECT content FROM native_profile_documents
                    WHERE profile_id=? AND filename=? AND revision<=? ORDER BY revision DESC LIMIT 1''',
                    (profile['id'], filename, profile['revision'])).fetchone()
                files.append({'filename': filename, 'content': row['content'] if row else ''})
        return {'name': profile['id'], 'display_name': profile['name'], 'revision': profile['revision'], 'files': files}

    def _save_profile_file(self, name, fields):
        profile = self._profile(name)
        filename, content = fields.get('filename'), fields.get('content')
        if filename not in set(PROFILE_FILES) | EXTRA_PROFILE_FILES or not isinstance(content, str) or len(content) > 12000 or '\x00' in content:
            raise HTTPException(400, '画像文件或正文无效')
        if type(fields.get('expected_revision')) is not int or fields['expected_revision'] != profile['revision']:
            raise HTTPException(409, '画像已有新修订，请重新核对')
        document = {PROFILE_FILES[filename]: content} if filename in PROFILE_FILES else {}
        result = self.box.creator.command({'id': 'native-profile-' + self._operation, 'action': 'profile-save',
                                          'profile_id': profile['id'], 'base_revision': profile['revision'], 'document': document})
        saved = result['result']['profile']
        if filename in EXTRA_PROFILE_FILES:
            with self.store.connect() as c:
                c.execute('INSERT INTO native_profile_documents VALUES(?,?,?,?)', (profile['id'], filename, saved['revision'], content))
        return {'ok': True, 'revision': saved['revision']}

    def _work_tree(self):
        result = []
        for work in self.box.works()['items']:
            full = self.box.work(work['id']); versions = []
            for version in full.get('versions', []):
                children = []
                for artifact in version.get('artifacts', []):
                    try:
                        value, path = self.box.file(artifact['id'])
                    except ValueError:
                        continue
                    children.append({'type': 'file', 'name': value['name'],
                                     'path': '__workbench__/' + artifact['id'] + '/' + value['name'],
                                     'kind': self.outputs._file_kind(value['name']),
                                     'mtime': int(path.stat().st_mtime), 'size': path.stat().st_size})
                if children:
                    versions.append({'type': 'dir', 'name': version.get('label', version['id']),
                                     'path': 'workbench-' + work['id'] + '/' + version['id'],
                                     'children': children, 'fileCount': len(children),
                                     'mtime': max(child['mtime'] for child in children),
                                     'meta': {'work_id': work['id'], 'version_id': version['id']}})
            if versions:
                latest = versions[-1]
                files = [child for version in versions for child in version['children']]
                cover = next((item['path'] for item in reversed(files) if item['kind'] == 'image'), '')
                result.append({'type': 'dir', 'name': work['title'], 'path': 'workbench-' + work['id'],
                               'mtime': max(item['mtime'] for item in versions), 'children': versions,
                               'fileCount': len(files), 'meta': {'title': work['title'], 'kind': full.get('format', 'poster'),
                               'work_id': work['id'], 'version_id': latest['meta']['version_id'], 'cover': cover}})
        return result

    def _native_tree(self):
        """Project the existing registered native library into original nodes."""
        with self.store.connect() as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='easel_chat_turns'").fetchone():
                return []
        from easel_workbench.upstream_skills import UpstreamSkills
        groups = {}
        for item in UpstreamSkills(self.root, self.box.creator).library()['items']:
            sid, tid = item['session_id'], item['turn_id']
            children = []
            for artifact in item['files']:
                try:
                    value, path = self.box.file(artifact['id'])
                except ValueError:
                    continue
                children.append({'type': 'file', 'name': value['name'],
                                 'path': '__workbench__/' + value['id'] + '/' + value['name'],
                                 'kind': self.outputs._file_kind(value['name']),
                                 'mtime': int(path.stat().st_mtime), 'size': path.stat().st_size})
            if not children:
                continue
            group = groups.setdefault(sid, {'type': 'dir', 'name': '原生对话 · ' + sid,
                'path': 'native-session-' + sid, 'children': [], 'fileCount': 0, 'mtime': 0,
                'meta': {'title': item['title'], 'session_id': sid}})
            turn = {'type': 'dir', 'name': '回合 · ' + tid, 'path': group['path'] + '/' + tid,
                    'children': children, 'fileCount': len(children),
                    'mtime': max(child['mtime'] for child in children),
                    'meta': {'title': item['title'], 'session_id': sid, 'turn_id': tid}}
            group['children'].append(turn)
            group['fileCount'] += len(children)
            group['mtime'] = max(group['mtime'], turn['mtime'])
            if not group['meta'].get('cover'):
                cover = next((child['path'] for child in children if child['kind'] == 'image'), None)
                if cover:
                    group['meta']['cover'] = cover
        return list(groups.values())

    def _registered_file(self, relative):
        match = re.fullmatch(r'__workbench__/([A-Za-z0-9_-]+)/([^/]+)', relative)
        if not match:
            return None
        value, path = self.box.file(match[1])
        if value['name'] != match[2]:
            raise HTTPException(404, '文件不存在')
        return value, path

    async def _file(self, relative, media=False, *, preview=False):
        registered = self._registered_file(relative)
        if registered:
            value, path = registered
            if media:
                response = FileResponse(path, media_type=value['mime'], headers={'Cache-Control': 'private, no-store'})
                return _protect_html_preview(response, preview=preview)
            kind = self.outputs._file_kind(value['name'])
            return {'path': relative, 'kind': kind, 'isBinary': kind != 'text',
                    'content': path.read_text(encoding='utf-8') if kind == 'text' else ''}
        parts = Path(relative.replace('\\', '/')).parts
        if not parts or any(part in {'.', '..'} for part in parts):
            raise HTTPException(403, '非法路径')
        if parts[0].startswith(('_', '.')):
            # Only the current native QR image is exposed from system output.
            if not (media and parts[0] == '_login' and len(parts) == 2 and
                    re.fullmatch(r'(?:xiaohongshu|douyin|kuaishou|weixin-channels|zhihu|bilibili|wechat-oa-mp)\.png', parts[1])):
                raise HTTPException(403, '系统资料不在内容库展示范围')
        resolved = self.outputs._safe_output_path(relative)
        actual_parts = resolved.relative_to((self.root / 'outputs').resolve()).parts
        if actual_parts[0].startswith(('_', '.')) and actual_parts != parts:
            raise HTTPException(403, '系统资料不能经目录别名展示')
        response = await (self.outputs.api_media(relative) if media else self.outputs.api_output(relative))
        return _protect_html_preview(response, preview=preview) if media else response

    def _export_package(self, platform, fields):
        from easel.manual_publish import build_package
        for key in ('title', 'body', 'tags'):
            if not isinstance(fields.get(key, ''), str):
                raise HTTPException(400, '稿件字段格式无效')
        media = fields.get('media', [])
        if not isinstance(media, list) or len(media) > 32 or any(not isinstance(item, str) for item in media):
            raise HTTPException(400, '请选择最多32个准确媒体文件')
        sources = []
        for relative in media:
            registered = self._registered_file(relative)
            if registered:
                _, path = registered
            else:
                parts = Path(relative.replace('\\', '/')).parts
                if not parts or any(part.startswith(('_', '.')) for part in parts):
                    raise HTTPException(403, '不能导出系统文件')
                path = self.outputs._safe_output_path(relative)
                if path.relative_to((self.root / 'outputs').resolve()).parts[0].startswith(('_', '.')):
                    raise HTTPException(403, '不能经目录别名导出系统文件')
            with path.open('rb') as source:
                source_sha = hashlib.file_digest(source, 'sha256').hexdigest()
            sources.append((path, source_sha))
        # The native builder still owns validation, archive contents and the
        # reviewed/manual-submission contract. TEMP only resolves host file refs.
        with tempfile.TemporaryDirectory(prefix='easel-native-export-') as directory:
            output = Path(directory)
            (output / 'media').mkdir()
            references = []
            for index, (path, source_sha) in enumerate(sources, 1):
                reference = 'media/' + str(index).zfill(2) + '_' + path.name
                shutil.copy2(path, output / reference)
                with (output / reference).open('rb') as copied:
                    if hashlib.file_digest(copied, 'sha256').hexdigest() != source_sha:
                        raise HTTPException(409, '媒体文件已变化，请重新核对当前版本')
                references.append(reference)
            if platform == 'wechat-oa':
                from easel_workbench.runtime.connection_environment import service as environment_service
                from easel_workbench.runtime.easel_connection_support import safe_env
                environment = environment_service(self.box)
                if not environment.python.is_file():
                    raise HTTPException(400, '请在设置中安装公众号 Markdown 排版依赖')
                payload = {'outputs': str(output), 'platform': platform, 'title': fields.get('title', ''),
                           'body': fields.get('body', ''), 'tags': fields.get('tags', ''),
                           'media': references, 'reviewed': fields.get('reviewed')}
                completed = subprocess.run([str(environment.python), str(Path(__file__).with_name('native_package_worker.py'))],
                    input=pack(payload), capture_output=True, text=True, encoding='utf-8', timeout=90,
                    env=safe_env(environment.child_environment(), self.root),
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                if completed.returncode:
                    raise HTTPException(400, '公众号稿件包未生成，请核对设置中的 Markdown 排版依赖和本轮输入')
                package = (output / json.loads(completed.stdout)['path']).resolve()
                if output.resolve() not in package.parents or not package.is_file() or package.suffix != '.zip':
                    raise HTTPException(400, '稿件包回执不能核对')
            else:
                package = build_package(output, platform, fields.get('title', ''), fields.get('body', ''),
                                        fields.get('tags', ''), references, fields.get('reviewed'))
            identifier = 'native-export-' + hashlib.sha256(self._operation.encode()).hexdigest()[:32]
            result = self.box.register_file(identifier, package.name, package)
        return {'path': '__workbench__/' + result['id'] + '/' + result['name'],
                'filename': result['name'], 'published': False}

    async def dispatch(self, path, request, body):
        method = request.method
        if path == '/api/upload' and method == 'POST':
            return await self._upload(request)
        receipt = re.fullmatch(r'/api/native/operations/([A-Za-z0-9_-]+)', path)
        if receipt and method == 'GET':
            return self.receipt(receipt[1])
        if path == '/api/outputs' and method == 'GET':
            native = await asyncio.to_thread(self.outputs.api_outputs)
            registered = self._native_tree()
            sessions = {item['meta']['session_id'] for item in registered}
            native = [item for item in native if item['path'] not in sessions]
            return sorted(native + self._work_tree() + registered, key=lambda item: item.get('mtime', 0), reverse=True)
        if path == '/api/artifacts/archive' and method == 'GET':
            relative = request.query_params.get('path', '')
            if self._registered_file(relative):
                return {'paths': []}
            if not relative or Path(relative.replace('\\', '/')).parts[0].startswith(('_', '.')):
                raise HTTPException(403, '系统资料不在内容库展示范围')
            return await asyncio.to_thread(self.outputs.api_artifact_archive, relative)
        if path == '/api/output-context' and method == 'GET':
            wanted = request.query_params.get('path', '')
            for item in self._work_tree():
                for candidate in (item, *item['children']):
                    if candidate['path'] == wanted:
                        return {key: candidate['meta'][key] for key in ('work_id', 'version_id')}
            return {}
        file_match = re.fullmatch(r'/api/(output|media)/(.+)', path)
        if file_match and method in {'GET', 'HEAD'}:
            return await self._file(unquote(file_match[2]), file_match[1] == 'media',
                                    preview=request.query_params.get('download') != '1')
        if file_match and method == 'DELETE':
            raise HTTPException(403, '原件与历史版本保留，请在准确作品版本中归档')
        if path == '/api/personas' and method == 'GET':
            return [{'name': item['id'], 'display_name': item['name'], 'description': item['identity']}
                    for item in self._profiles() if item.get('active', True)]
        persona = re.fullmatch(r'/api/persona/([^/]+)(?:/(files|file))?', path)
        if persona:
            name = unquote(persona[1])
            if method == 'GET':
                return self._profile_files(name) if persona[2] == 'files' else {
                    'name': self._profile(name)['id'], 'content': '\n\n'.join(item['content'] for item in self._profile_files(name)['files'])}
            if method == 'PUT' and persona[2] == 'file':
                return await self._mutate(request, body, lambda fields: self._save_profile_file(name, fields))
            if method == 'DELETE':
                raise HTTPException(403, '画像历史须保留；请在画像扩展中停用')
        if path == '/api/ideas' or path.startswith('/api/ideas/'):
            if method == 'GET' and path == '/api/ideas':
                return await self.planning.api_ideas_list()
            key = path.removeprefix('/api/ideas/') if path != '/api/ideas' else None
            async def idea(fields):
                if method == 'DELETE' and key:
                    return await self.planning.api_ideas_delete(ident(key))
                req = self.planning.IdeaItem(**fields)
                return await (self.planning.api_ideas_update(ident(key), req) if key else self.planning.api_ideas_create(req))
            if method in {'POST', 'PUT', 'DELETE'}:
                return await self._mutate(request, body, idea)
        if path == '/api/schedule/context' and method == 'GET':
            # Use the original calendar script on an immutable TEMP projection;
            # do not introduce another calendar algorithm or business writer.
            with tempfile.TemporaryDirectory(prefix='easel-native-calendar-') as directory:
                output = Path(directory)
                (output / '_schedule.json').write_text(pack(self._schedule()), encoding='utf-8')
                context = create_planning_context(self.root, outputs=output,
                    scripts=Path(__file__).resolve().parents[2] / 'skills/shared/scripts')
                return await context.api_schedule_context(int(request.query_params.get('days', '14')))
        if path == '/api/schedule' or path.startswith('/api/schedule/'):
            if method == 'GET' and path == '/api/schedule':
                return await self.planning.api_schedule_list()
            key = path.removeprefix('/api/schedule/') if path != '/api/schedule' else None
            async def schedule(fields):
                if method == 'DELETE' and key:
                    return await self.planning.api_schedule_delete(ident(key))
                req = self.planning.ScheduleItem(**fields)
                return await (self.planning.api_schedule_update(ident(key), req) if key else self.planning.api_schedule_create(req))
            if method in {'POST', 'PUT', 'DELETE'}:
                return await self._mutate(request, body, schedule)
        if path == '/api/trends' and method == 'GET':
            return self._trends(request)
        if path in ('/api/trends/sources', '/api/trends/manage'):
            collection = self._collection()
            if method == 'GET':
                document = collection.registry.public()
                if path.endswith('/sources'):
                    document['sources'] = [item for item in document['sources'] if item.get('enabled')]
                return document
            if method == 'POST' and path.endswith('/manage'):
                def update_source(fields):
                    values = dict(fields)
                    source = values.pop('source_id', None) or values.pop('id', None)
                    if source:
                        current = collection.registry.entries().get(source)
                        if not current:
                            raise HTTPException(404, '数据源不存在')
                        values.update(source_id=source, expected_revision=values.get('expected_revision', current['revision']))
                    values['operation_id'] = 'native-source-' + self._operation
                    result = collection.registry.update(values)
                    return {'ok': True, 'id': result.get('source_id') or result.get('id')}
                return await self._mutate(request, body, update_source)
        if path == '/api/publishing-policy' and method == 'GET':
            return {'mode': 'manual', 'automaticSubmission': False, 'manualExport': True,
                    'platforms': ['xiaohongshu', 'douyin', 'kuaishou', 'weixin-channels', 'zhihu', 'bilibili', 'wechat-oa']}
        export = re.fullmatch(r'/api/manual-publish/([a-z-]+)/export', path)
        if export and method == 'POST':
            return await self._mutate(request, body, lambda fields: self._export_package(export[1], fields))
        if path == '/api/analytics/platforms' and method == 'GET':
            return await self.analytics_context().api_analytics_platforms()
        if path.startswith('/api/analytics/') and method == 'GET':
            self._require_admission()
            return await self.analytics_context().api_analytics(path.rsplit('/', 1)[-1])
        return await self._accounts(path, request, body)

    async def _accounts(self, path, request, body):
        from easel_workbench.runtime.easel_accounts import service
        accounts = service(self.box)
        native = accounts.native_context()
        method = request.method
        if path == '/api/accounts' and method == 'GET':
            return await native.api_accounts()
        match = re.fullmatch(r'/api/(accounts|login|logout)/([a-z-]+)(?:/(.*))?', path)
        if not match:
            return None
        group, platform, suffix = match.groups()
        if platform not in native.LOGIN_RUNNERS:
            raise HTTPException(404, '未知平台')
        if method == 'GET':
            if group == 'login' and suffix == 'status':
                return await native.api_login_status(platform)
            if group == 'accounts' and suffix == 'mp-login/status':
                return await native.api_mp_login_status(platform)
            if group == 'accounts' and suffix == 'whoami':
                self._require_admission()
                result = await native.api_account_whoami(platform, request.query_params.get('force') == 'true')
                accounts.record_native_observation(platform, result)
                return result
            if group == 'accounts' and suffix == 'credentials':
                return {'configured': False, 'appIdMasked': '', 'name': '', 'author': ''}
        if method == 'POST':
            async def command(fields):
                if group == 'logout':
                    self._invalidate_analytics(accounts)
                    result = await native.api_logout(platform)
                    accounts.record_native_logout(platform)
                    return result
                if group == 'accounts' and suffix == 'mp-login':
                    self._prepare_account_login(accounts, platform)
                    return await native.api_mp_login_start(platform)
                if group == 'login' and not suffix:
                    self._prepare_account_login(accounts, platform)
                    return await native.api_login_start(platform)
                if group == 'login' and suffix == 'sms':
                    return await native.api_login_sms(platform, native.SmsCodeRequest(code=fields.get('code', '')))
                raise HTTPException(405, '此账号动作请使用原扫码流程')
            return await self._mutate(request, body, command)
        return None


async def handle(box, path, request, value=None):
    """Return a native response, or ``None`` for another application route."""
    if not supports(path, request.method):
        return None
    if not getattr(box, '_native_api', None):
        box._native_api = NativeApi(box)
    try:
        result = await box._native_api.dispatch(path, request, value or {})
        if result is None or isinstance(result, Response):
            return result
        return JSONResponse(result, headers={'Cache-Control': 'no-store'})
    except HTTPException as error:
        return JSONResponse({'detail': error.detail}, status_code=error.status_code,
                            headers={'Cache-Control': 'no-store'})
    except (ValueError, TypeError) as error:
        return JSONResponse({'detail': str(error)}, status_code=409 if '修订' in str(error) else 400,
                            headers={'Cache-Control': 'no-store'})
