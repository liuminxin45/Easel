"""Evidence-indexed creative learning, with one canonical strategy document.

SQLite contains provenance, candidate proposals, queue receipts and immutable
execution snapshots. Only an explicit preview/confirm can change project policy.
Importing or constructing this service never starts a process or calls an AI.
"""
from __future__ import annotations

import base64
import contextlib
import copy
import datetime as dt
import difflib
import hashlib
import json
import mimetypes
import math
import os
from pathlib import Path
import re
import time
import threading
import uuid

from easel_workbench.runtime.feedback_ledger import locked

from easel_workbench.features.evidence.records import POLICY_PATH, CONDITIONS, RELATIONSHIPS, TERMINAL, TEXT_SUFFIXES, MEDIA_SUFFIXES, SECRET_NAME, SECRET_TEXT, FORBIDDEN_PARTS, packed, sha, stamp, identity, bounded, atomic_bytes, original_mime, LearningConflict

class EvidenceIndex:
    def __init__(self, *, store, project, records, wake_event, enqueue):
        self.store=store
        self.project=project
        self._all=records._all
        self._get=records._get
        self._put=records._put
        self.wake_event=wake_event
        self._enqueue=enqueue
        self.batch=None

    def _safe_path(self, relative):
        if not isinstance(relative, str) or '\\' in relative or Path(relative).is_absolute():
            raise ValueError('学习证据路径无效')
        parts = Path(relative).parts
        if not parts or '..' in parts or any(part.lower() in FORBIDDEN_PARTS or SECRET_NAME.search(part) for part in parts):
            raise ValueError('该位置不属于创作学习范围')
        if parts[0] not in ('内容', '资料', '规范'):
            raise ValueError('只能引用内容、研究样本或现行规范原件')
        if parts[0] == '资料' and (len(parts) < 2 or parts[1] != '风格研究'):
            raise ValueError('该资料不属于学习证据范围')
        path = self.project / relative
        for item in (path, *path.parents):
            if item == self.project:
                break
            if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
                raise ValueError('不索引链接目录或文件')
        if not path.resolve().is_relative_to(self.project):
            raise ValueError('证据必须位于内容项目内')
        return path

    def _search_text(self,c,evidence,body):
        if not isinstance(body,str) or len(body)>8*1024*1024:return
        c.execute('INSERT INTO learning_evidence_search VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET sha256=excluded.sha256,body=excluded.body WHERE sha256<>excluded.sha256 OR body<>excluded.body',
                  (evidence['id'],evidence['sha256'],body))

    def _table_exists(self, c, name):
        return bool(c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone())

    def _metadata_file(self, path):
        relative = path.relative_to(self.project).as_posix()
        self._safe_path(relative)
        size = path.stat().st_size
        if path.suffix.lower() not in TEXT_SUFFIXES:
            # Hash complete media bytes without loading a movie into memory.
            with path.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        else:
            if size > 8 * 1024 * 1024:
                raise ValueError('文字原件超过索引安全范围，待单独核对')
            raw = path.read_bytes()
            digest = sha(raw)
            text = raw.decode('utf-8-sig', errors='replace')
            if SECRET_TEXT.search(text):
                raise ValueError('原件包含疑似秘密，不进入学习索引')
        return digest, {'kind': 'file', 'path': relative}, size

    def _upsert_evidence(self, c, kind, title, raw_sha, source, size=0, available=True, missing_reason=None):
        key = 'ev-' + raw_sha
        old = self._get(c, 'learning_evidence', key, False)
        locator_key = packed(source)
        locators = copy.deepcopy(old.get('locators', [])) if old else []
        # Current locators are rebuilt on each completed index, preserving the old
        # references for an honest unavailable historical record.
        if all(packed(row) != locator_key for row in locators):
            locators.append(source)
        now = stamp()
        roles = sorted({locator.get('actor', 'source_record') for locator in locators})
        document = {**(old or {}), 'id': key, 'kind': old.get('kind', kind) if old else kind,
                    'title': title if old and old.get('title')=='用户提供原件' and title!='用户提供原件' else old.get('title', title) if old else title, 'source': old.get('source', source) if old else source,
                    'sha256': raw_sha, 'size': size, 'locators': locators, 'source_count': len(locators),
                    'source_roles': roles, 'has_user_guidance': 'user' in roles,
                    'available': available or bool(old and old.get('available')), 'current': True,
                    'missing_reason': missing_reason, 'analysis_status': old.get('analysis_status', 'pending') if old else ('pending' if available else 'blocked'),
                    'revision': old.get('revision', 1) if old else 1, 'created_at': old.get('created_at', now) if old else now}
        return self._put(c, 'learning_evidence', document)

    def _file_candidates(self):
        paths = set()
        folder = self.project / '资料' / '风格研究'
        if folder.is_dir():
            paths.update(path for path in folder.rglob('*') if path.is_file() and path.suffix.lower() in TEXT_SUFFIXES | MEDIA_SUFFIXES)
        folder = self.project / '内容'
        if folder.is_dir():
            for path in folder.rglob('*'):
                if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES | MEDIA_SUFFIXES:
                    continue
                # All article dossiers, full personal feedback, adopted examples,
                # version reviews, check contracts and original guidance remain
                # in their original article directory.
                tokens = ('内容档案', '反馈', '指导', '原话', '用户', '讨论', '学习', '复盘', '检查', '认可', '采纳记录', '标题比较', '风格权重', '批注', '修改记录')
                if any(token in path.name or any(token in parent.name for parent in path.relative_to(folder).parents if str(parent) != '.') for token in tokens):
                    paths.add(path)
        folder = self.project / '规范'
        if folder.is_dir():
            paths.update(path for path in folder.glob('*.md') if any(token in path.name for token in ('写作', '认可例段', '图片', '贴图')))
        return sorted(paths, key=lambda path: path.as_posix())

    def _source_rows(self, c):
        if self._table_exists(c, 'toolbox_jobs'):
            internal = {row[0] for row in c.execute('SELECT child_job_id FROM learning_correction_links')} if self._table_exists(c, 'learning_correction_links') else set()
            for row in c.execute("SELECT id,work_id,candidate_id,kind,text,scope FROM toolbox_jobs WHERE work_id IS NOT NULL AND kind IN ('change','feedback','accept','reject')"):
                if row['text'].strip() or row['kind'] in ('accept', 'reject'):
                    automatic = row['id'] in internal
                    yield 'ai_internal_correction' if automatic else 'work_decision' if row['kind'] in ('accept', 'reject') and not row['text'].strip() else 'work_feedback', 'AI内部修正过程（候选）' if automatic else '作品修改与评审原话', row['text'].encode(), {
                        'kind': 'database', 'table': 'toolbox_jobs', 'record_id': row['id'], 'field': 'text', 'work_id': row['work_id'], 'version_id': row['candidate_id'],
                        'actor': 'assistant' if automatic else 'user', 'authority': 'process_candidate_not_user_feedback' if automatic else 'bound_user_action',
                        'action_kind': row['kind'], 'approval_scope': json.loads(row['scope'] or '{}') if row['kind'] == 'accept' and not automatic else None}
        if self._table_exists(c, 'toolbox_review_notes'):
            for row in c.execute('SELECT id,work_id,candidate_id,document FROM toolbox_review_notes'):
                document = json.loads(row['document'])
                yield 'annotation', '作品版本批注', packed(document).encode(), {'kind': 'database', 'table': 'toolbox_review_notes', 'record_id': row['id'], 'field': 'document', 'work_id': row['work_id'], 'version_id': row['candidate_id'], 'actor': 'user'}
        if self._table_exists(c, 'toolbox_direct_turns'):
            for row in c.execute("SELECT id,work_id,candidate_id,turn_id,request FROM toolbox_direct_turns WHERE work_id<>'' AND turn_id<>''"):
                # Read only the explicitly persisted, bound request. Never open
                # its transcript path or scan any unbound conversation.
                yield 'direct_turn', '明确关联作品的直接回合原话', row['request'].encode(), {'kind': 'database', 'table': 'toolbox_direct_turns', 'record_id': row['id'], 'field': 'request', 'work_id': row['work_id'], 'version_id': row['candidate_id'], 'turn_id': row['turn_id'], 'actor': 'user'}
        if self._table_exists(c, 'studio_records'):
            publications = {row['id']: json.loads(row['document']) for row in c.execute("SELECT id,document FROM studio_records WHERE category='publications'")}
            for row in c.execute("SELECT category,id,document FROM studio_records WHERE category IN ('metrics','comments')"):
                document = json.loads(row['document'])
                publication = publications.get(document.get('publication_id'))
                if not publication or not publication.get('work_id') or not publication.get('version_id'):
                    continue
                yield 'reader_comment' if row['category'] == 'comments' else 'publication_metric', '发布原评论' if row['category'] == 'comments' else '发布指标原始口径', row['document'].encode(), {'kind': 'database', 'table': 'studio_records', 'category': row['category'], 'record_id': row['id'], 'field': 'document', 'work_id': publication['work_id'], 'version_id': publication['version_id'], 'publication_id': publication['id'], 'actor': 'reader' if row['category'] == 'comments' else 'measurement', 'authority': 'observed_evidence_not_user_approval'}

    def _index(self, c):
        watch_fingerprint = self.watch_fingerprint()
        before = self._all(c, 'learning_evidence')
        seen=set()
        errors = []
        count = 0
        for path in self._file_candidates():
            try:
                digest, source, size = self._metadata_file(path)
                kind = 'sample' if source['path'].startswith('资料/') else 'check_case' if '检查' in path.name else 'work_dossier' if path.name == '内容档案.md' else 'guidance'
                title=path.stem
                if path.name=='用户提供原件.md' and source['path'].startswith('资料/风格研究/工作台导入/'):
                    with path.open('rb') as original:head=original.read(65536).decode('utf-8-sig',errors='replace')
                    heading=re.search(r'^#\s+([^\r\n]+)',head,re.M)
                    if heading:title=heading.group(1).strip()[:200] or title
                item=self._upsert_evidence(c, kind, title, digest, source, size);seen.add(item['id'])
                if path.suffix.lower() in TEXT_SUFFIXES:self._search_text(c,item,path.read_text(encoding='utf-8-sig',errors='replace'))
                count += 1
            except (ValueError, OSError):
                errors.append({'kind': 'excluded_or_unavailable', 'path': path.relative_to(self.project).as_posix(), 'reason': '原件不可访问、链接目录或含疑似秘密，未读取进学习证据'})
        for kind, title, raw, source in self._source_rows(c):
            if SECRET_TEXT.search(raw.decode('utf-8', errors='replace')):
                errors.append({'kind': 'excluded_secret', 'record_id': source['record_id'], 'reason': '原记录含疑似秘密，未进入学习证据'})
                continue
            item=self._upsert_evidence(c, kind, title, sha(raw), source, len(raw));seen.add(item['id'])
            self._search_text(c,item,raw.decode('utf-8-sig',errors='replace'))
            count += 1
        # Local links in the sample index and manifests provide explicit missing
        # original records; missing bytes never become an invented quote.
        for row in self._all(c, 'learning_evidence'):
            if row['id'] not in seen or not row.get('current') or row['source'].get('kind') != 'file' or not row['source']['path'].startswith('资料/风格研究/') or Path(row['source']['path']).suffix != '.md':
                continue
            try:
                path = self._safe_path(row['source']['path'])
                text = path.read_text(encoding='utf-8-sig')
                for link in re.findall(r'\]\(([^)]+)\)', text):
                    from urllib.parse import unquote
                    link = unquote(link.strip('<>').split('#', 1)[0])
                    if not link or re.match(r'^[a-z]+:', link, re.I):
                        continue
                    target = (path.parent / link).resolve()
                    if not target.is_relative_to(self.project):
                        continue
                    relative = target.relative_to(self.project).as_posix()
                    if target.exists():
                        continue
                    try:
                        self._safe_path(relative)
                    except ValueError:
                        continue
                    source = {'kind': 'file', 'path': relative, 'referenced_by': row['source']['path']}
                    missing=self._upsert_evidence(c, 'missing_original', target.name, sha(('missing:' + relative).encode()), source, available=False, missing_reason='索引或研究记录引用了此原件，但当前检出没有原始字节');seen.add(missing['id'])
            except (OSError, ValueError):
                continue
        for row in before:
            if row['id'] not in seen:
                row.update(current=False,available=False,missing_reason='原件已变化或不再可访问；历史索引不代表当前原件')
                self._put(c,'learning_evidence',row)
        state = {'status': 'indexed', 'last_indexed_at': stamp(), 'source_items': count, 'errors': errors,
                 'history_metadata_complete': True, 'history_analysis_complete': False,
                 'excluded_sources': ['Obsidian', 'LLM-Wiki', '未绑定聊天', '凭据与秘密', '个人笔记与Idea']}
        c.execute("INSERT OR REPLACE INTO learning_index_state VALUES('coverage',?)", (packed(state),))
        watch = c.execute("SELECT document FROM learning_index_state WHERE id='file-watch'").fetchone()
        watch_state = json.loads(watch['document']) if watch else {'generation': 0}
        watch_state.update(fingerprint=watch_fingerprint, indexed_at=stamp())
        c.execute("INSERT OR REPLACE INTO learning_index_state VALUES('file-watch',?)", (packed(watch_state),))
        # Indexing records facts only; model work is frozen by a unified cycle.
        return self._coverage(c)

    def _coverage(self, c):
        state = c.execute("SELECT document FROM learning_index_state WHERE id='coverage'").fetchone()
        meta = json.loads(state['document']) if state else {'status': 'not_indexed', 'last_indexed_at': None, 'errors': [], 'history_metadata_complete': False}
        rows = self._all(c, 'learning_evidence')
        current = [row for row in rows if row.get('current')]
        by_source = {}
        for row in current:
            key = row['kind']
            part = by_source.setdefault(key, {'indexed': 0, 'analyzed': 0, 'pending': 0, 'missing': 0})
            part['indexed'] += 1
            part['analyzed'] += row['analysis_status'] == 'completed'
            part['pending'] += row['available'] and row['analysis_status'] in ('pending', 'running')
            part['preprocessed'] = part.get('preprocessed', 0) + (row['analysis_status'] == 'preprocessed')
            part['missing'] += not row['available']
        pending = sum(row['available'] and row['analysis_status'] in ('pending', 'running') for row in current)
        return {**meta, 'total': len(current), 'indexed': len(current), 'historical_indexed': len(rows),
                'analyzed': sum(row['analysis_status'] == 'completed' for row in current), 'preprocessed': sum(row['analysis_status'] == 'preprocessed' for row in current), 'pending': pending,
                'failed': sum(row['analysis_status'] == 'failed' for row in current), 'blocked': sum(row['analysis_status'] == 'blocked' for row in current), 'missing': sum(not row['available'] for row in current),
                'duplicates': sum(max(0, row['source_count'] - 1) for row in current), 'by_source': by_source,
                'history_analysis_complete': bool(meta.get('history_metadata_complete')) and all(row['analysis_status'] in ('completed', 'preprocessed') for row in current),
                'processing': self.processing_status(c)}

    def _processing_state(self, c):
        return self.batch.settings(c)

    def _save_processing(self, c, state):
        c.execute("INSERT OR REPLACE INTO learning_index_state VALUES('batch-settings',?)", (packed(state),))

    def processing_status(self, connection=None):
        with self.store.connect() if connection is None else contextlib.nullcontext(connection) as c:
            state = self.batch.settings(c)
            return {**state, 'state': 'paused' if state['paused'] else 'ready',
                    'next_analysis_at': self.batch.next_time(c), 'scope': 'batch_learning',
                    'manual_analysis_available': True, 'current_analysis_finishes_before_pause': True,
                    'message': '自动学习已暂停；当前一包结束后停止，仍可手动整理，制作核验继续。' if state['paused'] else
                               '北京时间每日' + state['local_time'] + '统一整理；制作与交付核验优先。'}

    def _finish_history_budget(self, c, task):
        # Kept for old in-flight receipts. A new cycle owns the real call budget.
        return None

    def index_database(self, connection=None):
        """Mutation hook for bound feedback/review/direct/publication events.

        Call inside the existing business transaction after its original row is
        persisted. This does not rescan the repository or call AI, and queue IDs
        deduplicate repeated delivery of the same event/source bytes.
        """
        with self.store.connect() if connection is None else contextlib.nullcontext(connection) as c:
            indexed, excluded = 0, 0
            for kind, title, raw, source in self._source_rows(c):
                if SECRET_TEXT.search(raw.decode('utf-8', errors='replace')):
                    excluded += 1
                    continue
                item = self._upsert_evidence(c, kind, title, sha(raw), source, len(raw))
                self._search_text(c,item,raw.decode('utf-8-sig',errors='replace'))
                indexed += 1
            self.wake_event.set()
            return {'indexed': indexed, 'excluded': excluded}

    def watch_fingerprint(self):
        """Low-cost metadata watch; no body/transcript/credential reads."""
        relatives = {'资料/风格研究/样本索引.md', '资料/风格研究/用户指导记录索引.md', '资料/风格研究/反馈检查案例.json', POLICY_PATH}
        folder = self.project / '内容'
        if folder.is_dir():
            for child in folder.iterdir():
                if not child.is_dir() or child.is_symlink() or getattr(child, 'is_junction', lambda: False)():
                    continue
                for name in ('反馈.md', '进度.md'):
                    relatives.add((child / name).relative_to(self.project).as_posix())
        signatures = []
        for relative in sorted(relatives):
            try:
                path = self._safe_path(relative)
                info = path.stat()
                signatures.append((relative, info.st_mtime_ns, info.st_size))
            except (OSError, ValueError):
                signatures.append((relative, None, None))
        return sha(packed({'index_version':3,'signatures':signatures}).encode())

    def queue_index_refresh(self, fingerprint=None):
        fingerprint = fingerprint or self.watch_fingerprint()
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            flags = self.batch.runtime_flags()
            if flags.get('cutover_paused') is True:
                return None
            previous = c.execute("SELECT document FROM learning_index_state WHERE id='file-watch'").fetchone()
            state = json.loads(previous['document']) if previous else {'generation': 0}
            if state.get('fingerprint') == fingerprint:
                return None
            generation = state.get('generation', 0) + 1
            key = 'index-' + sha((fingerprint + ':' + str(generation)).encode())
            # Metadata refresh precedes the historical analysis backlog, while
            # production review remains first and active production fences both.
            task = self._enqueue(c, key, 'index_refresh', {'fingerprint': fingerprint}, 50)
            state.update(fingerprint=fingerprint, generation=generation, task_id=key, detected_at=stamp())
            c.execute("INSERT OR REPLACE INTO learning_index_state VALUES('file-watch',?)", (packed(state),))
            self.wake_event.set()
            return task

    def list_evidence(self, query='', kind='', page=1, page_size=30):
        bounded(query, 500)
        bounded(kind, 100)
        page = max(1, min(10000, int(page)))
        page_size = max(1, min(100, int(page_size)))
        clauses, values = [], []
        if kind:
            clauses.append("json_extract(document,'$.kind')=?")
            values.append(kind)
        if query:
            clauses.append("(coalesce(json_extract(document,'$.title'),'') LIKE ? ESCAPE '\\' OR coalesce(json_extract(document,'$.source.path'),'') LIKE ? ESCAPE '\\' OR coalesce(json_extract(document,'$.classification.reason'),'') LIKE ? ESCAPE '\\' OR id IN (SELECT s.id FROM learning_evidence_search s WHERE s.body LIKE ? ESCAPE '\\' AND s.sha256=learning_evidence.sha256))")
            pattern = '%' + query.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_') + '%'
            values.extend([pattern] * 4)
        where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
        with self.store.connect() as c:
            total = c.execute('SELECT count(*) FROM learning_evidence' + where, values).fetchone()[0]
            items = [json.loads(row['document']) for row in c.execute('SELECT document FROM learning_evidence' + where + ' ORDER BY updated_at DESC,rowid DESC LIMIT ? OFFSET ?', (*values, page_size, (page - 1) * page_size))]
            kinds = [row[0] for row in c.execute("SELECT DISTINCT json_extract(document,'$.kind') FROM learning_evidence ORDER BY 1")]
            return {'items': [self._evidence_summary(item) for item in items], 'total': total, 'page': page, 'page_size': page_size,
                    'has_more': page * page_size < total, 'kinds': kinds, 'coverage': self._coverage(c)}

    def _evidence_summary(self, row):
        result = {key: copy.deepcopy(value) for key, value in row.items() if key != 'analysis'}
        if row.get('analysis'):
            result['analysis_summary'] = row['analysis'].get('summary', '')[:1000]
        return result

    def _read_locator(self, c, source):
        if source.get('kind') == 'file':
            path = self._safe_path(source['path'])
            if not path.is_file():
                raise LearningConflict('原件缺失，不能将索引说明当作原话')
            raw = path.read_bytes()
            if path.suffix.lower() not in TEXT_SUFFIXES:
                return raw, None
            content = raw.decode('utf-8-sig', errors='replace')
        else:
            table, field = source.get('table'), source.get('field')
            allowed = {'toolbox_jobs': 'text', 'toolbox_review_notes': 'document', 'toolbox_direct_turns': 'request', 'studio_records': 'document'}
            if table not in allowed or field != allowed[table]:
                raise ValueError('不允许读取该数据库证据')
            if table == 'studio_records':
                if source.get('category') not in ('metrics', 'comments'):
                    raise ValueError('不允许读取该类记录')
                row = c.execute('SELECT document FROM studio_records WHERE category=? AND id=?', (source['category'], source['record_id'])).fetchone()
            else:
                row = c.execute('SELECT ' + field + ' FROM ' + table + ' WHERE id=?', (source['record_id'],)).fetchone()
            if not row:
                raise LearningConflict('数据库权威原记录已不可访问')
            content = row[0]
            # JSON source hashes reflect exactly the authoritative row bytes.
            if table == 'toolbox_review_notes':
                content = packed(json.loads(content))
            raw = content.encode()
        if SECRET_TEXT.search(content):
            raise ValueError('原件包含疑似秘密，不进入学习内容')
        return raw, content

    def evidence_content(self, c, key):
        row = self._get(c, 'learning_evidence', key)
        for locator in row['locators']:
            try:
                if locator.get('kind') == 'file' and Path(locator['path']).suffix.lower() not in TEXT_SUFFIXES:
                    path = self._safe_path(locator['path'])
                    with path.open('rb') as stream:
                        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                    if digest != row['sha256']:
                        continue
                    return {**row, 'available': True, 'content': None, 'content_is_original': True, 'verified_source': locator,
                            'binary_original': True, 'missing_reason': None,
                            'mime': original_mime(path),
                            'original_url': '/api/learning/evidence/' + row['id'] + '/original'}
                raw, content = self._read_locator(c, locator)
                if sha(raw) == row['sha256']:
                    return {**row, 'available': True, 'content': content, 'content_is_original': True, 'verified_source': locator,
                            'binary_original': content is None, 'missing_reason': None}
            except (ValueError, OSError):
                continue
        return {**row, 'available': False, 'content': None, 'content_is_original': False,
                'missing_reason': '未找到与索引SHA-256一致的权威原件；不引用缓存或分析冒充原话'}

    def original_file(self, key):
        """Authenticated HTTP caller may stream this exact, verified original.

        This descriptor is internal, never returned by bootstrap/detail. The
        HTTP layer still owns authentication, nosniff and Content-Disposition.
        """
        with self.store.connect() as c:
            row = self._get(c, 'learning_evidence', key)
            for locator in row['locators']:
                if locator.get('kind') != 'file':
                    continue
                try:
                    path = self._safe_path(locator['path'])
                    with path.open('rb') as stream:
                        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                    if digest != row['sha256']:
                        continue
                    if path.suffix.lower() in TEXT_SUFFIXES:
                        bounded(path.read_text(encoding='utf-8-sig'), 8 * 1024 * 1024)
                    return {'path': path, 'name': path.name, 'mime': original_mime(path), 'sha256': digest, 'source': copy.deepcopy(locator)}
                except (OSError, ValueError):
                    continue
        raise LearningConflict('原始文件缺失或字节已变化，不能用派生分析替代原件')
