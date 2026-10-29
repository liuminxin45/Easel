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

POLICY_PATH = '规范/创作策略.json'
CONDITIONS = {'format', 'channel', 'topic', 'work_id', 'version_id', 'purpose', 'content_type', 'visual_role', 'column'}
RELATIONSHIPS = ('different_conditions', 'composable', 'mutually_exclusive', 'insufficient_evidence')
TERMINAL = {'completed', 'failed', 'blocked', 'cancelled'}
TEXT_SUFFIXES = {'.md', '.json', '.txt', '.html', '.csv'}
MEDIA_SUFFIXES = {'.png', '.jpg', '.jpeg', '.gif', '.webp', '.pdf', '.mp4', '.webm', '.mp3'}
SECRET_NAME = re.compile(r'(?:^|[._-])(?:credentials?|secrets?|cookies?|tokens?|passwords?|\.env)(?:[._-]|$)', re.I)
SECRET_TEXT = re.compile(r'(?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|session[_-]?cookie)[\"\']?\s*[=:]\s*[\"\']?[A-Za-z0-9_+/=-]{6,}|\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,})', re.I)
FORBIDDEN_PARTS = {'obsidian', 'llm-wiki', 'wiki', '.obsidian', '.git', '.runtime', 'node_modules', '__pycache__'}


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha(value):
    return hashlib.sha256(value).hexdigest()


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise ValueError('学习记录标识无效')
    return value


def bounded(value, limit=10000, required=False):
    if not isinstance(value, str) or len(value) > limit or required and not value.strip():
        raise ValueError('学习内容为空或超过长度限制')
    if SECRET_TEXT.search(value):
        raise ValueError('不能将凭据或秘密写入学习记录')
    return value


def atomic_bytes(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def original_mime(path):
    guessed = mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
    if not guessed.startswith('image/'):
        return guessed
    try:
        from PIL import Image
        with Image.open(path) as source:
            source.verify()
            return Image.MIME.get(source.format, 'application/octet-stream')
    except Exception:
        return 'application/octet-stream'


class LearningConflict(ValueError):
    pass


class LearningService:
    def __init__(self, box, studio=None, root=None, project=None, clock=None):
        self.box = box
        self.store = box.store
        self.studio = studio or getattr(box, 'studio', None)
        self.root = Path(root or box.root).resolve()
        self.project = Path(project if project is not None else getattr(self.studio, 'project', self.root / 'content-project')).resolve()
        self.state = self.root / 'data' / 'learning'
        self.clock = clock or time.time
        self.wake_event = threading.Event()
        with self.store.connect() as c:
            c.executescript('''
CREATE TABLE IF NOT EXISTS learning_evidence(id TEXT PRIMARY KEY,sha256 TEXT NOT NULL UNIQUE,document TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learning_evidence_search(id TEXT PRIMARY KEY,sha256 TEXT NOT NULL,body TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learning_proposals(id TEXT PRIMARY KEY,document TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learning_runs(id TEXT PRIMARY KEY,document TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learning_operations(operation_id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learning_analysis_queue(id TEXT PRIMARY KEY,kind TEXT NOT NULL,status TEXT NOT NULL,priority INTEGER NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL,started_at TEXT,finished_at TEXT,owner TEXT,lease_token TEXT,lease_until REAL,result TEXT,error TEXT);
CREATE INDEX IF NOT EXISTS learning_queue_ready ON learning_analysis_queue(status,priority,created_at);
CREATE TABLE IF NOT EXISTS learning_index_state(id TEXT PRIMARY KEY,document TEXT NOT NULL);
''')
            from easel_workbench.runtime.batch_learning import BatchLearning
            self.batch = BatchLearning(self)
            self.batch.migrate(c)
            from easel_workbench.runtime.creative_recipes import CreativeRecipes
            CreativeRecipes(self).initialize(c)

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

    def policy(self):
        path = self._safe_path(POLICY_PATH)
        raw = path.read_bytes() if path.is_file() else None
        document = json.loads(raw.decode('utf-8-sig')) if raw is not None else {'schema_version': 2, 'revision': 0, 'methods': [], 'profiles': []}
        for collection in ('methods','profiles'):
            for entry in document.get(collection,[]):
                if entry.get('prompt_file'):
                    content=self._safe_path(entry['prompt_file']).read_bytes()
                    if sha(content)!=entry.get('prompt_sha256'):raise LearningConflict('风格提示词原件已变化，请核对修订后继续')
                    from easel_workbench.runtime.creative_policy_files import instructions_from_file
                    entry['instructions']=instructions_from_file(entry,content)
        self._validate_policy(document)
        return {'path': POLICY_PATH, 'revision': sha(raw) if raw is not None else None,
                'revision_number': document['revision'], 'available': raw is not None, 'document': document}

    def _conditions(self, value):
        if not isinstance(value, dict) or set(value) - CONDITIONS:
            raise ValueError('适用条件仅支持明确的格式、渠道、主题、作品、版本、用途或图像角色')
        for item in value.values():
            if not (isinstance(item, str) and item.strip() or isinstance(item, list) and item and all(isinstance(x, str) and x.strip() for x in item)):
                raise ValueError('每个适用条件需要文本或文本列表')
        return value

    def _validate_entry(self, entry):
        if not isinstance(entry, dict):
            raise ValueError('策略条目无效')
        identity(entry.get('id'))
        bounded(entry.get('name', ''), 500, True)
        self._conditions(entry.get('conditions', {}))
        instructions = entry.get('instructions')
        if instructions is None and entry.get('prompt_file'):
            data=self._safe_path(entry['prompt_file']).read_bytes()
            if sha(data)!=entry.get('prompt_sha256'):raise LearningConflict('提示词文件指纹不一致')
            from easel_workbench.runtime.creative_policy_files import instructions_from_file
            instructions=instructions_from_file(entry,data)
        if not isinstance(instructions, list) or not 1 <= len(instructions) <= 40:
            raise ValueError('策略需要逐项实际指令')
        for instruction in instructions:
            bounded(instruction, 10000, True)
        if entry.get('status', 'confirmed') not in ('confirmed', 'candidate', 'retired'):
            raise ValueError('策略状态无效')
        if not isinstance(entry.get('evidence_refs', []), list):
            raise ValueError('策略证据引用无效')
        for ref in entry.get('evidence_refs', []):
            if isinstance(ref, str):
                if not ref.startswith('ev-'):
                    self._safe_path(ref)
            elif isinstance(ref, dict) and isinstance(ref.get('path'), str):
                self._safe_path(ref['path'])
            else:
                raise ValueError('策略证据须引用索引ID或项目原件')
        for key in ('excludes', 'requires'):
            if not isinstance(entry.get(key, []), list) or any(not isinstance(item, str) for item in entry.get(key, [])):
                raise ValueError('策略关系无效')
        if 'intent' in entry:
            from easel_workbench.runtime.semantic_style import intent
            intent(entry['intent'])
        if type(entry.get('priority', 0)) is not int or not 0 <= entry.get('priority', 0) <= 100:
            raise ValueError('策略优先级无效')
        if type(entry.get('revision', 1)) is not int or entry.get('revision', 1) < 1:
            raise ValueError('策略条目修订号无效')

    def _validate_policy(self, document):
        if not isinstance(document, dict) or document.get('schema_version') != 2 or type(document.get('revision')) is not int or document['revision'] < 0:
            raise ValueError('创作策略需要schema_version 2和明确修订号')
        for key in ('methods', 'profiles'):
            rows = document.get(key)
            if not isinstance(rows, list) or len(rows) > 1000:
                raise ValueError('创作策略集合无效')
            for row in rows:
                self._validate_entry(row)
            if len({row['id'] for row in rows}) != len(rows):
                raise ValueError('策略ID不能重复')
        all_ids = [row['id'] for row in document['methods'] + document['profiles']]
        if len(set(all_ids)) != len(all_ids):
            raise ValueError('方法与主风格必须使用不同ID')
        if len(packed(document)) > 2_000_000 or SECRET_TEXT.search(packed(document)):
            raise ValueError('策略过长或包含秘密')

    def _all(self, c, table):
        return [json.loads(row['document']) for row in c.execute('SELECT document FROM ' + table + ' ORDER BY rowid')]

    def _get(self, c, table, key, required=True):
        row = c.execute('SELECT document FROM ' + table + ' WHERE id=?', (key,)).fetchone()
        if not row and required:
            raise ValueError('找不到对应学习记录')
        return json.loads(row['document']) if row else None

    def _put(self, c, table, document):
        document = copy.deepcopy(document)
        if table == 'learning_evidence':
            previous=self._get(c,table,document['id'],False)
            if previous and {k:v for k,v in previous.items() if k!='updated_at'}=={k:v for k,v in document.items() if k!='updated_at'}:
                return previous
            document['updated_at']=stamp()
            c.execute('INSERT INTO learning_evidence VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET sha256=excluded.sha256,document=excluded.document,updated_at=excluded.updated_at', (document['id'], document['sha256'], packed(document), document['updated_at']))
        else:
            document['updated_at'] = stamp()
            c.execute('INSERT OR REPLACE INTO ' + table + ' VALUES(?,?,?)', (document['id'], packed(document), document['updated_at']))
        return document

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

    def _run_summary(self, row):
        result = {key: copy.deepcopy(value) for key, value in row.items() if key not in ('snapshot', 'review', 'quality')}
        snapshot = row.get('snapshot', {})
        result.update(snapshot_revision=snapshot.get('revision_token'), main_profile_id=snapshot.get('main_profile_id'),
                      selected_ids=[item['id'] for item in snapshot.get('selected', [])],
                      unresolved_conflicts=sum(not item.get('resolved') for item in snapshot.get('conflicts', [])))
        quality = row.get('quality', {})
        result['quality'] = {key: quality[key] for key in ('status', 'checked') if key in quality}
        result['quality'].update(objective_missing_count=len(quality.get('objective_missing', [])),
                                 subjective_disagreements_count=len(quality.get('subjective_disagreements', [])))
        return result

    def bootstrap(self):
        policy = self.policy()
        with self.store.connect() as c:
            evidence = self._all(c, 'learning_evidence')
            proposals = self._all(c, 'learning_proposals')
            runs = self._all(c, 'learning_runs')
            coverage = self._coverage(c)
            batch_status = self.batch.status(c)
        issues = []
        if not policy['available']:
            issues.append({'id': 'missing-policy', 'kind': 'missing_policy', 'title': '创作策略原件尚不存在', 'reason': '不会从历史研究或缓存创建长期规则'})
        if coverage['status'] == 'not_indexed':
            issues.append({'id': 'history-not-indexed', 'kind': 'coverage', 'title': '历史证据待建立索引', 'reason': '尚未索引不等于已完成历史学习'})
        for row in evidence:
            if row.get('current') and not row['available']:
                issues.append({'id': 'missing-' + row['id'], 'kind': 'missing_original', 'entity_id': row['id'], 'title': row['title'], 'reason': row['missing_reason']})
            findings = row.get('preprocessing', {}).get('findings', [])
            if row.get('current') and findings:
                issues.append({'id': 'checks-' + row['id'], 'kind': 'structured_check', 'entity_id': row['id'],
                               'title': row['title'], 'reason': '程序提取了' + str(len(findings)) + '项结构化失败，未将其冒充审美结论或用户偏好',
                               'authority': 'program_preprocessing', 'occurrences': row.get('source_count', 1), 'finding_count': len(findings)})
        for run in runs:
            for conflict in run.get('snapshot', {}).get('conflicts', []):
                if not conflict.get('resolved'):
                    issues.append({'id': run['id'] + '-' + conflict['id'], 'kind': 'style_conflict', 'entity_id': run['id'], 'title': '本轮风格条件待判断', 'reason': conflict['reason']})
        return {'schema_version': 2, 'policy': {k: v for k, v in policy.items() if k != 'document'}, 'coverage': coverage,
                'processing': coverage['processing'], 'batch_learning': batch_status,
                'evidence': [self._evidence_summary(row) for row in sorted(evidence, key=lambda row: row['updated_at'], reverse=True)[:30]], 'evidence_total': len(evidence),
                'methods': policy['document']['methods'], 'profiles': policy['document']['profiles'],
                'issues': issues,
                'proposals': [{key: value for key, value in row.items() if key not in ('before_bytes', 'after_bytes', 'analysis')} for row in proposals],
                'runs': [self._run_summary(row) for row in runs]}

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

    def detail(self, kind, key):
        mapping = {'evidence': 'learning_evidence', 'proposal': 'learning_proposals', 'run': 'learning_runs',
                   'cycle': 'learning_batch_cycles', 'batch': 'learning_batches'}
        with self.store.connect() as c:
            if kind == 'evidence':
                item = self.evidence_content(c, key)
                item['text']=item.get('content')
            elif kind in mapping:
                item = self._get(c, mapping[kind], key)
                if kind == 'batch':
                    # Internal exact-byte attachment paths are not web DTOs.
                    for source in item.get('frozen_sources', []):
                        for image in source.get('images', []):
                            image.pop('path', None)
            elif kind in ('method', 'profile', 'issue'):
                rows = self.bootstrap()[{'method': 'methods', 'profile': 'profiles', 'issue': 'issues'}[kind]]
                item = next((row for row in rows if row['id'] == key), None)
                if item is None:
                    raise ValueError('找不到对应学习记录')
            else:
                raise ValueError('学习详情类型无效')
        return {'schema_version': 2, 'kind': kind, 'item': item}

    def _enqueue(self, c, key, kind, payload, priority):
        c.execute('INSERT OR IGNORE INTO learning_analysis_queue(id,kind,status,priority,payload,created_at) VALUES(?,?,?,?,?,?)', (key, kind, 'queued', priority, packed(payload), stamp()))
        row = dict(c.execute('SELECT * FROM learning_analysis_queue WHERE id=?', (key,)).fetchone())
        row['payload'] = json.loads(row['payload'])
        return row

    def enqueue_review(self, c, jid):
        identity(jid)
        if self.read_run(c, jid) is None:
            return None
        task = self._enqueue(c, 'review-' + jid, 'production_review', {'job_id': jid}, 100)
        self.wake_event.set()
        return task

    def read_run(self, c, jid):
        return self._get(c, 'learning_runs', jid, False)

    def clone_run(self, c, oldjid, newjid):
        identity(oldjid)
        identity(newjid)
        original = self.read_run(c, oldjid)
        if original is None:
            return None
        existing = self.read_run(c, newjid)
        if existing:
            if existing.get('origin_job_id') != oldjid or existing['snapshot'] != original['snapshot']:
                raise LearningConflict('内部修正任务已有不同的冻结学习来源')
            return existing
        return self._put(c, 'learning_runs', {'id': newjid, 'job_id': newjid, 'kind': 'production', 'work_id': original['work_id'],
                                             'version_id': original.get('version_id'), 'origin_job_id': oldjid, 'status': 'frozen',
                                             'snapshot': copy.deepcopy(original['snapshot']), 'created_at': stamp(),
                                             'quality': {'status': 'pending', 'checked': False}})

    def update_run(self, c, jid, patch):
        if not isinstance(patch, dict) or set(patch) - {'status', 'quality', 'review', 'correction', 'error', 'finished_at', 'review_task_id'}:
            raise ValueError('运行更新不能改写冻结选择和原始输入')
        run = self.read_run(c, jid)
        if run is None:
            raise ValueError('此制作任务没有学习冻结记录')
        run.update(copy.deepcopy(patch))
        return self._put(c, 'learning_runs', run)

    def _proposal(self, c, value):
        kind = value.get('kind')
        if kind not in ('method', 'profile', 'policy'):
            raise ValueError('提案类型无效')
        document = copy.deepcopy(value.get('document'))
        if kind == 'policy':
            self._validate_policy(document)
        else:
            self._validate_entry(document)
            document['status'] = 'candidate'
        refs = value.get('evidence_refs', document.get('evidence_refs', []))
        if not isinstance(refs, list) or len(refs) > 100:
            raise ValueError('提案证据无效')
        item = {'id': value['operation_id'], 'title': bounded(value.get('title', document.get('name', '策略调整')), 500, True),
                'kind': kind, 'status': 'candidate', 'document': document, 'reason': bounded(value.get('reason', ''), 20000, True),
                'evidence_refs': refs, 'revision': 1, 'created_at': stamp(), 'origin': 'explicit_proposal'}
        return self._put(c, 'learning_proposals', item)

    def _disjoint(self, left, right):
        for key in left.keys() & right.keys():
            if key == 'topic':
                # Different topic words can describe the same title/material;
                # their mere spelling is insufficient proof of disjoint scope.
                continue
            a = set(left[key] if isinstance(left[key], list) else [left[key]])
            b = set(right[key] if isinstance(right[key], list) else [right[key]])
            if not a & b:
                return True
        return False

    def relationship(self, a, b):
        if self._disjoint(a.get('conditions', {}), b.get('conditions', {})):
            return 'different_conditions'
        if b['id'] in a.get('excludes', []) or a['id'] in b.get('excludes', []):
            return 'mutually_exclusive'
        group_a, group_b = a.get('compatibility_group'), b.get('compatibility_group')
        if group_a and group_a == group_b:
            return 'composable'
        if a.get('dimension') and a.get('dimension') == b.get('dimension') and a.get('conditions', {}) == b.get('conditions', {}):
            return 'mutually_exclusive'
        if a.get('dimension') != b.get('dimension'):
            return 'composable'
        return 'insufficient_evidence'

    def _preview(self, c, value):
        item = self._get(c, 'learning_proposals', value.get('proposal_id'))
        if item['status'] not in ('candidate', 'preview'):
            raise LearningConflict('该提案不能再次预览确认')
        policy = self.policy()
        if value.get('expected_revision') != policy['revision']:
            raise LearningConflict('创作策略原件已变化，请重新核对差异')
        path = self._safe_path(POLICY_PATH)
        before_raw = path.read_bytes() if path.is_file() else None
        document = copy.deepcopy(policy['document'])
        relations = []
        if item['kind'] == 'policy':
            document = copy.deepcopy(item['document'])
        else:
            entry = {**copy.deepcopy(item['document']), 'status': 'confirmed'}
            entry['evidence_refs'] = item['evidence_refs']
            collection = 'methods' if item['kind'] == 'method' else 'profiles'
            previous = next((row for row in document[collection] if row['id'] == entry['id']), None)
            entry['revision'] = previous.get('revision', 1) + 1 if previous else 1
            for old in document[collection]:
                if old['id'] != entry['id'] and old.get('status', 'confirmed') != 'retired':
                    relations.append({'id': old['id'], 'relationship': self.relationship(entry, old)})
            document[collection] = [row for row in document[collection] if row['id'] != entry['id']] + [entry]
        document['revision'] = policy['revision_number'] + 1
        document['updated_at'] = stamp()
        self._validate_policy(document)
        from easel_workbench.runtime.creative_policy_files import canonical_policy
        document,prompt_files=canonical_policy(document)
        after_raw = (json.dumps(document, ensure_ascii=False, indent=2) + '\n').encode()
        before_text = before_raw.decode('utf-8-sig') if before_raw is not None else ''
        item.update(status='preview', revision=item['revision'] + 1, before_revision=policy['revision'],
                    before_bytes=base64.b64encode(before_raw).decode() if before_raw is not None else None,
                    after_bytes=base64.b64encode(after_raw).decode(), after_revision=sha(after_raw),
                    diff='\n'.join(difflib.unified_diff(before_text.splitlines(), after_raw.decode().splitlines(), fromfile='当前创作策略', tofile='确认后创作策略', lineterm='')),
                    relationships=relations, relationship=next((row['relationship'] for row in relations if row['relationship'] in ('mutually_exclusive', 'insufficient_evidence')), 'different_conditions' if relations and all(row['relationship'] == 'different_conditions' for row in relations) else 'composable'))
        item['prompt_files']=prompt_files
        if item['kind'] in ('method','profile'):
            old=next((row for row in policy['document']['methods']+policy['document']['profiles'] if row['id']==item['document']['id']),None)
            before_prompt='\n'.join(old.get('instructions',[])) if old else ''
            component_id=item['document'].get('recipe_component_id')
            if component_id and not old:
                from easel_workbench.runtime.creative_recipes import CreativeRecipes
                component=next((row for row in CreativeRecipes(self).catalog()['components'] if row['id']==component_id),None)
                if not component:raise ValueError('提示词组件不存在')
                before_prompt=component['prompt']
            after_prompt='\n'.join(item['document']['instructions'])
            item['prompt_before']=before_prompt;item['prompt_after']=after_prompt
            item['prompt_diff']='\n'.join(difflib.unified_diff(before_prompt.splitlines(),after_prompt.splitlines(),fromfile='当前提示词',tofile='确认后提示词',lineterm=''))
            return self._put(c, 'learning_proposals', item)
        item['prompt_diff']='\n'.join(difflib.unified_diff(
            ('\n\n'.join('\n'.join(row.get('instructions',[])) for row in policy['document']['methods']+policy['document']['profiles'])).splitlines(),
            ('\n'.join(prompt_files.values())).splitlines(),fromfile='当前风格提示词',tofile='确认后风格提示词',lineterm=''))
        return self._put(c, 'learning_proposals', item)

    def _apply(self, c, value, revert=False):
        item = self._get(c, 'learning_proposals', value.get('proposal_id'))
        expected_status = 'confirmed' if revert else 'preview'
        if item['status'] != expected_status:
            raise LearningConflict('必须先预览差异再明确确认；撤销仅作用于已确认且未被覆盖的版本')
        expected = item['after_revision' if revert else 'before_revision']
        if value.get('expected_revision') != expected:
            raise LearningConflict('确认修订与预览差异不一致')
        raw = base64.b64decode(item['before_bytes']) if revert and item['before_bytes'] is not None else None if revert else base64.b64decode(item['after_bytes'])
        path = self._safe_path(POLICY_PATH)
        journal = self.state / 'journal' / (value['operation_id'] + '.json')
        target_sha = sha(raw) if raw is not None else None
        current = sha(path.read_bytes()) if path.is_file() else None
        intent = json.loads(journal.read_text(encoding='utf-8')) if journal.exists() else None
        if intent and (intent['signature'] != value['_signature'] or intent['target_sha'] != target_sha):
            raise LearningConflict('策略恢复记录与原操作不一致')
        if current != expected and not (intent and current == target_sha):
            raise LearningConflict('权威原件已有其它修改，不能覆盖；请重新预览')
        if not intent:
            atomic_bytes(journal, packed({'signature': value['_signature'], 'target_sha': target_sha, 'path': POLICY_PATH}).encode())
        if raw is None:
            if path.exists():
                path.unlink()
        else:
            if not revert:
                for relative,content in item.get('prompt_files',{}).items():
                    target=self._safe_path(relative);data=content.encode('utf-8')
                    if target.exists() and target.read_bytes()!=data:raise LearningConflict('版本化提示词文件出现不同字节，未覆盖')
                    if not target.exists():atomic_bytes(target,data)
            atomic_bytes(path, raw)
        item.update(status='reverted' if revert else 'confirmed', revision=item['revision'] + 1,
                    **({'reverted_at': stamp(), 'revert_operation_id': value['operation_id']} if revert else {'confirmed_at': stamp(), 'confirm_operation_id': value['operation_id']}))
        return self._put(c, 'learning_proposals', item)

    def command(self, value):
        if not isinstance(value, dict):
            raise ValueError('学习操作无效')
        value = copy.deepcopy(value)
        bounded(packed(value), 2_000_000, True)
        oid = identity(value.get('operation_id'))
        signature = packed({k: v for k, v in value.items() if k not in ('id', '_signature')})
        value['_signature'] = signature
        action = value.get('action')
        journal = self.state / 'journal' / (oid + '.json')
        with locked(self.state / 'commands.lock', timeout=20):
            with self.store.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                old = c.execute('SELECT signature,result FROM learning_operations WHERE operation_id=?', (oid,)).fetchone()
                if old:
                    if old['signature'] != signature:
                        raise LearningConflict('同一学习操作标识不能用于不同内容')
                    if journal.exists():
                        journal.unlink()
                    return json.loads(old['result'])
                if action == 'index-refresh':
                    result = {'coverage': self._index(c)}
                elif action == 'evidence-update':
                    item = self._get(c, 'learning_evidence', value.get('evidence_id'))
                    if value.get('expected_revision') != item['revision']:
                        raise LearningConflict('证据分类已变化，请核对最新版本')
                    classification = copy.deepcopy(value.get('classification'))
                    if not isinstance(classification, dict) or classification.get('scope') not in ('work', 'round', 'conditional', 'global', 'unknown'):
                        raise ValueError('分类范围无效')
                    bounded(classification.get('kind', ''), 100, True)
                    bounded(classification.get('reason', ''), 10000, True)
                    self._conditions(classification.get('conditions', {}))
                    item.update(classification=classification, revision=item['revision'] + 1)
                    result = {'evidence': self._put(c, 'learning_evidence', item)}
                elif action in ('analyze-evidence', 'analysis-start'):
                    evidence_id = value.get('evidence_id')
                    if evidence_id:
                        item = self._get(c, 'learning_evidence', evidence_id)
                        original = self.evidence_content(c, evidence_id)
                        if not original['available']:
                            raise LearningConflict(original['missing_reason'])
                    cycle = self.batch.start(c, oid, evidence_id=evidence_id)
                    result = {'cycle': cycle, 'task': {'id': cycle['id'], 'kind': 'learning_cycle', 'status': cycle['status']},
                              'batch_learning': self.batch.status(c)}
                elif action in ('analysis-settings', 'analysis-pause', 'analysis-resume'):
                    changes = value.get('settings', {}) if action == 'analysis-settings' else {'paused': action == 'analysis-pause'}
                    state = self.batch.update_settings(c, changes, value.get('expected_revision'))
                    result = {'settings': state, 'processing': self.processing_status(c), 'batch_learning': self.batch.status(c)}
                elif action == 'proposal-create':
                    result = {'proposal': self._proposal(c, value)}
                elif action == 'proposal-preview':
                    result = {'proposal': self._preview(c, value)}
                elif action in ('proposal-confirm', 'proposal-revert'):
                    result = {'proposal': self._apply(c, value, action == 'proposal-revert')}
                elif action == 'proposal-dismiss':
                    item = self._get(c, 'learning_proposals', value.get('proposal_id'))
                    if item['status'] not in ('candidate', 'preview') or value.get('expected_proposal_revision') != item['revision']:
                        raise LearningConflict('提案状态或修订已变化')
                    item.update(status='dismissed', revision=item['revision'] + 1)
                    result = {'proposal': self._put(c, 'learning_proposals', item)}
                else:
                    raise ValueError('不支持的学习操作')
                receipt = {'operation_id': oid, 'action': action, 'status': 'completed', 'result': result}
                c.execute('INSERT INTO learning_operations VALUES(?,?,?,?)', (oid, signature, packed(receipt), stamp()))
            if journal.exists():
                journal.unlink()
        self.wake_event.set()
        return receipt

    def _match(self, conditions, context):
        for key, wanted in conditions.items():
            actual = context.get(key)
            allowed = wanted if isinstance(wanted, list) else [wanted]
            actual_values = actual if isinstance(actual, list) else [actual]
            if key == 'topic':
                # A work title/material is routing evidence, never a rigid tag.
                # This bounded lexical match is visible in snapshot conditions;
                # it does not infer popularity, causal effects or approval.
                def topic_match(value, expected):
                    if not isinstance(value, str):
                        return False
                    normalized = value.casefold()
                    if expected in ('工具合集', 'tool_collection') and re.search(r'(?:不做|不要|不是|不采用)\s*(?:工具合集|tool_collection)', normalized):
                        return False
                    if expected.casefold() in normalized:
                        return True
                    if expected in ('工具合集', 'tool_collection'):
                        subject = bool(re.search(r'工具|项目|开源|github', normalized))
                        collection = bool(re.search(r'合集|清单|精选|推荐|盘点|[0-9一二三四五六七八九十]+[个款项种]', normalized))
                        rejected = bool(re.search(r'(?:不做|不要|不是|不采用)\s*(?:工具合集|tool_collection)', normalized))
                        return subject and collection and not rejected
                    return False
                if any(topic_match(item, expected) for item in actual_values for expected in allowed):
                    continue
                return False
            if not any(item in allowed for item in actual_values):
                return False
        return True

    def _required_ref(self, c, ref):
        key = ref if isinstance(ref, str) and ref.startswith('ev-') else None
        if key:
            try:
                row = self.evidence_content(c, key)
                return {k: row.get(k) for k in ('id', 'sha256', 'source', 'available', 'missing_reason', 'content', 'content_is_original', 'verified_source', 'binary_original')}
            except ValueError:
                return {'id': key, 'available': False, 'missing_reason': '索引ID没有对应原件'}
        path = ref if isinstance(ref, str) else ref.get('path')
        try:
            target = self._safe_path(path)
            raw = target.read_bytes()
            if target.suffix.lower() in TEXT_SUFFIXES and SECRET_TEXT.search(raw.decode('utf-8-sig', errors='replace')):
                raise ValueError('秘密不进入冻结证据')
            return {'id': 'ev-' + sha(raw), 'kind': 'source_reference', 'source': {'kind': 'file', 'path': path}, 'sha256': sha(raw), 'available': True,
                    'content': raw.decode('utf-8-sig') if target.suffix.lower() in TEXT_SUFFIXES else None, 'content_is_original': True}
        except (ValueError, OSError):
            return {'id': 'missing-' + sha(str(path).encode())[:32], 'source': {'kind': 'file', 'path': path}, 'available': False, 'missing_reason': '所引权威原件不可访问'}

    def resolve(self, connection, wid, vid=None, creation=None, context=None):
        creation = copy.deepcopy(creation or {})
        context = copy.deepcopy(context or {})
        with self.store.connect() if connection is None else contextlib.nullcontext(connection) as c:
            policy = self.policy()
            document = policy['document']
            # Only semantic selectors are accepted. Arbitrary numeric style weights
            # neither confirm a research method nor resolve a contradiction.
            selection = {}
            for layer in (context.get('learning'), creation.get('learning')):
                if isinstance(layer, dict):
                    if layer.get('snapshot_id') or 'required_evidence' in layer:
                        # Studio context carries the resolved snapshot for
                        # display; it is not another user-selection layer.
                        continue
                    selection.update(layer)
            # The semantic creative contract uses these names; older frozen
            # versions remain readable without becoming a parallel source.
            for modern, legacy in (('profile_id', 'selected_profile_id'), ('include_ids', 'selected_method_ids'), ('exclude_ids', 'excluded_ids'), ('conflict_choices', 'conflict_resolutions')):
                if modern in selection:
                    selection[legacy] = selection[modern]
            for key in ('selected_method_ids', 'trial_method_ids', 'excluded_ids'):
                if not isinstance(selection.get(key, []), list) or any(not isinstance(v, str) for v in selection.get(key, [])):
                    raise ValueError('本轮学习策略选择无效')
            proposals = self._all(c, 'learning_proposals')
            candidate_ids = {row['id'] for row in proposals if row['status'] in ('candidate', 'preview') and row['kind'] == 'method'}
            candidate_ids.update(row['id'] for row in document['methods'] + document['profiles'] if row.get('status') == 'candidate')
            selected_candidates = [key for key in selection.get('selected_method_ids', []) if key in candidate_ids]
            if selection.get('selected_profile_id') in candidate_ids:
                selected_candidates.append(selection['selected_profile_id'])
            trial = list(dict.fromkeys([*selection.get('trial_method_ids', []), *selected_candidates]))
            if len(trial) > 2:
                raise ValueError('本次最多试用两项候选方法')
            workspace = creation.get('workspace', {})
            effective = context.get('effective', {})
            conditions = {'work_id': wid, 'version_id': vid, 'format': context.get('format', creation.get('format', 'poster')),
                          'channel': workspace.get('channel', effective.get('channel', context.get('channel', {}).get('id') if isinstance(context.get('channel'), dict) else context.get('channel')))}
            supplied = selection.get('conditions', {})
            self._conditions(supplied)
            conditions.update({key: value for key, value in supplied.items() if key not in ('work_id', 'version_id')})
            if selection.get('topic'):
                conditions['topic'] = bounded(selection['topic'], 10000, True)
            if selection.get('goal'):
                conditions['purpose'] = bounded(selection['goal'], 5000, True)
            for key in CONDITIONS - {'work_id', 'version_id', 'format', 'channel'}:
                if key in context:
                    conditions[key] = context[key]
            requested_profile = next((row for row in document['profiles'] if row['id'] == selection.get('selected_profile_id')), None)
            if requested_profile and 'visual_role' not in conditions:
                image_intent = creation.get('intent', {}).get('image') or requested_profile.get('intent', {}).get('image')
                role = {'scene': 'illustrative_scene', 'scene_diagram': 'illustrative_scene', 'typographic': 'typographic_cover', 'diagram': 'information_diagram'}.get(image_intent)
                if role:
                    conditions['visual_role'] = role
            rows = [('method', row) for row in document['methods']] + [('profile', row) for row in document['profiles']]
            candidates = proposals
            for proposal in candidates:
                if proposal['status'] in ('candidate', 'preview') and proposal['kind'] == 'method':
                    entry = {**proposal['document'], 'id': proposal['id'], 'status': 'candidate', 'evidence_refs': proposal['evidence_refs']}
                    rows.append(('method', entry))
            known = {row['id'] for _, row in rows}
            requested = set(selection.get('selected_method_ids', [])) | set(trial)
            profile_id = selection.get('selected_profile_id')
            if profile_id:
                requested.add(profile_id)
            if requested - known:
                raise ValueError('所选方法或风格已不存在，请重新核对')
            if profile_id and selection.get('profile_revision') is not None:
                profile = next((row for kind, row in rows if kind == 'profile' and row['id'] == profile_id), None)
                if not profile or selection['profile_revision'] != profile.get('revision', 1):
                    raise LearningConflict('所选主风格修订已变化，请核对最新条件')
            selected, excluded, conflicts = [], [], []
            explicit_excluded = set(selection.get('excluded_ids', []))
            profiles = []
            for kind, row in rows:
                rid = row['id']
                reason = None
                if row.get('status') == 'retired':
                    reason = '已退役，保留历史不参与本轮'
                elif rid in explicit_excluded:
                    reason = '本次明确不采用'
                elif row.get('status') == 'candidate' and rid not in trial:
                    reason = '候选尚未获长期确认，本轮也未明确试用'
                elif not self._match(row.get('conditions', {}), conditions):
                    reason = '适用条件与本篇不符或缺少条件证据'
                elif kind == 'method' and row.get('selection', 'automatic') == 'explicit' and rid not in requested:
                    reason = '该方法需本轮明确选择'
                if reason:
                    excluded.append({'id': rid, 'kind': kind, 'name': row['name'], 'reason': reason})
                    if rid in requested and rid not in explicit_excluded and row.get('status') != 'retired':
                        conflicts.append({'id': 'applicability-' + rid, 'kind': 'insufficient_evidence', 'ids': [rid], 'resolved': False,
                                          'reason': '本轮明确纳入项尚不满足适用条件：' + row['name'] + '；需补充条件或取消纳入'})
                else:
                    entry = {**copy.deepcopy(row), 'kind': kind, 'trial': row.get('status') == 'candidate',
                             'reason': '本轮明确试用候选' if rid in trial else '本轮明确选择' if rid in requested else '与本篇条件匹配的已确认策略'}
                    if kind == 'profile':
                        profiles.append(entry)
                    else:
                        selected.append(entry)
            if profile_id:
                chosen_profiles = [row for row in profiles if row['id'] == profile_id]
                for row in profiles:
                    if row['id'] != profile_id:
                        excluded.append({'id': row['id'], 'kind': 'profile', 'name': row['name'], 'reason': '本轮明确选择其它主风格，保留此风格适用条件'})
                profiles = chosen_profiles
            elif len(profiles) > 1:
                # A specific condition can refine a general profile only when the
                # canonical entry explicitly declares that relationship.
                refinements = [row for row in profiles if set(row.get('refines', [])) >= {other['id'] for other in profiles if other['id'] != row['id']}]
                if len(refinements) == 1:
                    winner = refinements[0]
                    for row in profiles:
                        if row['id'] != winner['id']:
                            excluded.append({'id': row['id'], 'kind': 'profile', 'name': row['name'], 'reason': '已确认的条件风格明确细化此基线：' + winner['name']})
                    profiles = [winner]
                else:
                    conflicts.append({'id': 'main-profile', 'kind': 'main_style', 'ids': [row['id'] for row in profiles], 'resolved': False,
                                      'reason': '多个主风格同时适用，需明确选择；不能按时间、指标或优先级猜测'})
            selected.extend(profiles)
            resolutions = selection.get('conflict_resolutions', {})
            if not isinstance(resolutions, dict):
                raise ValueError('冲突选择需要明确的冲突ID和采用方法ID')
            for index, left in enumerate(list(selected)):
                for right in list(selected)[index + 1:]:
                    if left['kind'] == right['kind'] == 'profile':
                        continue
                    relation = self.relationship(left, right)
                    if relation not in ('mutually_exclusive', 'insufficient_evidence'):
                        continue
                    cid = 'conflict-' + sha('|'.join(sorted([left['id'], right['id']])).encode())[:20]
                    pick = resolutions.get(cid)
                    resolved = pick in (left['id'], right['id'])
                    conflicts.append({'id': cid, 'kind': relation, 'ids': [left['id'], right['id']], 'resolved': resolved,
                                      'selected_id': pick if resolved else None, 'reason': '本轮条件重叠且指令可能相反，需明确采用项或补充条件'})
                    if resolved:
                        loser = right if pick == left['id'] else left
                        if loser in selected:
                            selected.remove(loser)
                            excluded.append({'id': loser['id'], 'kind': loser['kind'], 'name': loser['name'], 'reason': '本轮明确冲突选择采用：' + pick})
            selected_ids = {row['id'] for row in selected}
            for row in selected:
                dependencies = set(row.get('requires', [])) - selected_ids
                if dependencies:
                    conflicts.append({'id': 'requires-' + row['id'], 'kind': 'insufficient_evidence', 'ids': [row['id'], *sorted(dependencies)], 'resolved': False,
                                      'reason': '所选方法的必要配合项未纳入或条件不匹配：' + '、'.join(sorted(dependencies))})
            required, source_evidence = [], []
            for row in selected:
                references = [self._required_ref(c, ref) for ref in row.get('evidence_refs', [])]
                dimensions = {'visual': 'image', 'copy': 'text', 'expression': 'text', 'main_style': 'tone', 'review': 'style'}
                canonical = any(entry['id'] == row['id'] for entry in document['methods'] + document['profiles'])
                strategy_source = {'kind': 'canonical_strategy', 'path': POLICY_PATH, 'sha256': policy['revision'], 'entry_id': row['id'],
                                   'collection': 'methods' if row['kind'] == 'method' else 'profiles'} if canonical else {
                                       'kind': 'database', 'table': 'learning_proposals', 'record_id': row['id'], 'field': 'document'}
                required.append({'id': row['id'], 'kind': 'strategy_execution', 'dimension': dimensions.get(row.get('dimension'), row.get('dimension', 'style')),
                                 'text': '\n'.join(row['instructions']), 'conditions': copy.deepcopy(row.get('conditions', {})),
                                 'status': row.get('status', 'confirmed'), 'trial': row['trial'], 'available': True,
                                 'source': strategy_source,
                                 'source_evidence_ids': list(dict.fromkeys(item['id'] for item in references)),
                                 'reason': row['reason']})
                for item in references:
                    if item not in source_evidence:
                        source_evidence.append(item)
            annotations = context.get('_learning_annotations', [])
            if not isinstance(annotations, list):
                raise ValueError('本轮批注证据无效')
            for annotation in annotations:
                if not isinstance(annotation, dict) or not annotation.get('id'):
                    raise ValueError('本轮批注必须有明确标识')
                required.append({'id': annotation['id'], 'kind': 'current_annotation', 'source': {'kind': 'database', 'table': 'toolbox_review_notes', 'record_id': annotation['id'], 'field': 'document', 'work_id': wid, 'version_id': vid},
                                 'sha256': sha(packed(annotation).encode()), 'available': True, 'annotation': copy.deepcopy(annotation)})
            preferences = context.get('_learning_preference_evidence', [])
            if not isinstance(preferences, list):
                raise ValueError('历史偏好证据无效')
            included_preferences = []
            for note in preferences:
                if not isinstance(note, dict) or not note.get('id') or note.get('deleted'):
                    continue
                scope = note.get('scope')
                source_work = note.get('work_id')
                source_format = note.get('format')
                if scope == 'format' and source_format is None and source_work and self._table_exists(c, 'toolbox_work_options'):
                    found = c.execute('SELECT format FROM toolbox_work_options WHERE work_id=?', (source_work,)).fetchone()
                    source_format = found['format'] if found else None
                relevant = scope == 'global' or scope == 'work' and source_work == wid or scope == 'format' and source_format == conditions.get('format')
                if not relevant or not self._match(note.get('conditions', {}), conditions):
                    continue
                if note['id'] in {annotation['id'] for annotation in annotations}:
                    continue
                included_preferences.append(note)
                required.append({'id': note['id'], 'kind': 'scoped_preference_evidence', 'scope': scope,
                                 'source': {'kind': 'database', 'table': 'toolbox_review_notes', 'record_id': note['id'], 'field': 'document', 'work_id': source_work, 'version_id': note.get('candidate_id')},
                                 'sha256': sha(packed(note).encode()), 'available': True, 'annotation': copy.deepcopy(note),
                                 'reason': '原始意见按其明确范围与本篇条件相关；不自动覆盖长期策略或当前指令'})
            intent_evidence = context.get('_learning_intent_evidence', [])
            if not isinstance(intent_evidence, list):
                raise ValueError('本轮实际意图证据无效')
            for intent in intent_evidence:
                if not isinstance(intent, dict) or not intent.get('id') or not intent.get('dimension'):
                    raise ValueError('本轮意图证据需要准确标识和维度')
                bounded(intent.get('text', ''), 100000, True)
                required.append({**copy.deepcopy(intent), 'kind': intent.get('kind', 'semantic_intent'), 'available': True,
                                 'sha256': sha(packed(intent).encode()), 'source': {'kind': 'current_creation_intent', 'id': intent['id']}})
            raw_feedback = context.get('_learning_raw_feedback', [])
            for asset in context.get('_learning_recipe_assets',[]):
                if not asset.get('available'):continue
                identity='recipe-asset-'+asset['sha256'][:32]
                if any(item['id']==identity for item in source_evidence):continue
                source_evidence.append({'id':identity,'kind':'recipe_reference','available':True,'content':None,'sha256':asset['sha256'],
                    'source':{'kind':'file','path':asset['path']},'role':asset.get('role'),'label':asset.get('label')})
                required.append({'id':identity,'kind':'recipe_reference','dimension':'image','available':True,'text':'按用途使用真实参考：'+asset.get('label',asset['path']),
                    'source_evidence_ids':[identity],'sha256':asset['sha256'],'source':{'kind':'file','path':asset['path']}})
            if not isinstance(raw_feedback, list):
                raise ValueError('本作品原始反馈列表无效')
            seen_feedback = set()
            for original in raw_feedback:
                if not isinstance(original, dict) or not isinstance(original.get('id'), str) or not original['id'].startswith('raw-') or original['id'] in seen_feedback:
                    raise ValueError('原始反馈需要准确且唯一的操作标识')
                seen_feedback.add(original['id'])
                bounded(original.get('text', ''), 2_000_000)
                evidence = {**copy.deepcopy(original), 'kind': 'raw_user_feedback', 'available': True,
                            'content': original.get('text', ''), 'content_is_original': True,
                            'sha256': sha(packed(original).encode()), 'refinement_status': 'unrefined',
                            'reason': '未提炼，仅本作品相关版本链；历史决定不是本轮强制偏好，逐条说明适用或未用原因'}
                evidence.setdefault('source', {'kind': 'local_feedback_record', 'operation_id': original['id'][4:], 'work_id': wid})
                required.append(copy.deepcopy(evidence))
                source_evidence.append(copy.deepcopy(evidence))
            missing = [row for row in source_evidence if not row.get('available')]
            if missing:
                conflicts.append({'id': 'missing-evidence', 'kind': 'insufficient_evidence', 'ids': [], 'resolved': False,
                                  'reason': '所选方法引用原件缺失；不得编造原话或声称已经核对'})
            override_layers = []
            for scope, source in (('work', context.get('settings', {}).get('overrides', {})), ('round', context.get('settings', {}).get('round', {})), ('current_round', effective), ('request', workspace)):
                if not isinstance(source, dict):
                    continue
                text = source.get('style_guidance') or source.get('instructions')
                if text:
                    override_layers.append({'scope': scope, 'instructions': bounded(text, 100000, True) if isinstance(text, str) else '\n'.join(text)})
            for annotation in annotations:
                note = annotation.get('note')
                if note:
                    override_layers.append({'scope': 'current_annotation', 'annotation_id': annotation['id'], 'instructions': bounded(note, 10000, True)})
            for intent in intent_evidence:
                override_layers.append({'scope': 'current_request' if intent.get('kind') == 'current_request' else 'resolved_semantic_intent', 'evidence_id': intent['id'], 'dimension': intent['dimension'],
                                        'provenance': copy.deepcopy(intent.get('provenance')), 'instructions': intent['text']})
            work_context = None
            if wid and self._table_exists(c, 'toolbox_works'):
                work = c.execute('SELECT id,title,material FROM toolbox_works WHERE id=?', (wid,)).fetchone()
                if work:
                    work_context = {'id': work['id'], 'title': work['title'], 'material': work['material'], 'source': {'kind': 'database', 'table': 'toolbox_works', 'record_id': wid}}
            direct = context.get('_learning_direct_context')
            if direct is not None:
                if not isinstance(direct, dict):
                    raise ValueError('直接回合的明确关联原件无效')
                for field in ('request', 'material'):
                    content = direct.get(field, '')
                    if not content:
                        continue
                    bounded(content, 2_000_000, True)
                    source_evidence.append({'id': 'direct-' + field + '-' + sha(content.encode())[:32], 'kind': 'bound_direct_input',
                                            'content': content, 'content_is_original': True, 'available': True, 'sha256': sha(content.encode()),
                                            'source': {'kind': 'bound_direct_context', 'binding_id': direct.get('binding_id'), 'field': field, 'actor': 'user',
                                                       'authority': 'explicitly_bound_current_turn_original'}})
                if work_context is None:
                    work_context = {'id': wid, 'title': direct.get('title', ''), 'material': direct.get('material', ''),
                                    'source': {'kind': 'bound_direct_context', 'binding_id': direct.get('binding_id'), 'actor': 'user'}}
            instructions = ['当前作品、当前回合和用户明确指令优先于条件风格；冲突要逐项保留并请明确选择。',
                            '候选分析仅供本轮所选试用；不写回长期规范，不以新时间、高流量或点赞覆盖既有风格。']
            unresolved = any(not row['resolved'] for row in conflicts)
            blocked_ids = {rid for conflict in conflicts if not conflict['resolved'] for rid in conflict.get('ids', [])}
            for row in selected:
                if row['id'] not in blocked_ids:
                    instructions.append(row['name'] + '：' + '\n'.join(row['instructions']))
            for row in override_layers:
                if row['scope'] == 'resolved_semantic_intent':
                    instructions.append('本轮生效意图（依据' + row['evidence_id'] + '，保留所列provenance，不推定全部来自用户）：' + row['instructions'])
                else:
                    instructions.append('当前明确指令（' + row['scope'] + '，优先）：' + row['instructions'])
            if included_preferences:
                instructions.append('读取required_evidence中按范围纳入的历史用户原话，结合本篇条件逐项说明采用或不采用理由；历史意见不自动升为长期策略，不以时间排序覆盖当前指令。')
            if raw_feedback:
                instructions.append('读取raw_user_feedback的完整原话、版本范围和决定历史：这些尚未提炼，仅限本作品相关版本链。逐条说明本次适用或未用原因；撤回、替代和相反意见保留身份，不能全部叠成强制要求。采纳不代表所有维度都好，不采纳也不代表所有维度都差；未填原因即未给出具体原因，不补造原话，不提升长期规则。')
            if unresolved:
                instructions.append('存在未解冲突：先保留冲突并明确适用条件，不得自动忽略或宣称已经执行相反的全部方法。')
            semantic_selection = {key: value for key, value in selection.items() if key not in ('revision_token', 'selected_method_ids', 'selected_profile_id', 'excluded_ids', 'conflict_resolutions')}
            semantic_selection.update(profile_id=profile_id, include_ids=selection.get('selected_method_ids', []), exclude_ids=selection.get('excluded_ids', []), conflict_choices=selection.get('conflict_resolutions', {}))
            token = sha(packed({'policy': policy['revision'], 'conditions': {key: value for key, value in conditions.items() if key not in ('work_id', 'version_id')},
                               'selection': semantic_selection, 'selected_ids': [row['id'] for row in selected],
                               'overrides': override_layers, 'evidence': required,
                               'sources': [{key: value for key, value in row.items() if key != 'content'} for row in source_evidence]}).encode())
            expected = creation.get('learning_revision') or selection.get('revision_token')
            if expected and expected != token:
                raise LearningConflict('学习策略或证据在确认后变化，请重新核对；未提交制作')
            result = {'schema_version': 2, 'snapshot_id': 'snapshot-' + token, 'revision_token': token,
                      'policy': {key: policy[key] for key in ('path', 'revision', 'revision_number', 'available')},
                      'work_id': wid, 'version_id': vid, 'conditions': conditions, 'selected': selected, 'excluded': excluded,
                      'conflicts': conflicts, 'decision_required': unresolved, 'required_evidence': required,
                      'source_evidence': source_evidence, 'profile': copy.deepcopy(profiles[0]) if len(profiles) == 1 else None,
                      'max_trial_candidates': 2, 'main_profile_id': profiles[0]['id'] if len(profiles) == 1 else None,
                      'main_style_reason': profiles[0]['reason'] if len(profiles) == 1 else '本轮主风格尚待明确' if profiles else '没有已确认且条件匹配的主风格',
                      'override_layers': override_layers, 'work_context': work_context, 'instructions': '\n\n'.join(instructions)}
            return result

    def freeze(self, connection, wid, jid, vid=None, creation=None, context=None):
        identity(jid)
        with self.store.connect() if connection is None else contextlib.nullcontext(connection) as c:
            existing = self.read_run(c, jid)
            if existing:
                if existing['work_id'] != wid or existing.get('version_id') != vid:
                    raise LearningConflict('同一制作任务不能改绑学习快照')
                return existing['snapshot']
            if not self.policy()['available']:
                return None
            snapshot = self.resolve(c, wid, vid, creation, context)
            self._put(c, 'learning_runs', {'id': jid, 'kind': 'production', 'work_id': wid, 'version_id': vid, 'job_id': jid,
                                         'status': 'needs_decision' if snapshot['decision_required'] else 'frozen', 'snapshot': snapshot,
                                         'created_at': stamp(), 'quality': {'status': 'pending', 'checked': False}})
            return snapshot

    def claim_task(self, owner, lease_seconds=300):
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            flags = self.batch.runtime_flags()
            if flags.get('cutover_paused') is True:
                return None
            # Do not automatically reclaim an expired running AI call. The old
            # process could still be alive; unknown receipt is a visible blocker.
            # Retiring automatic learning does not hide an expired legacy call.
            # Mark its receipt unknown/blocked without reclaiming or resending it.
            gate = ""
            expired = c.execute("SELECT payload,kind FROM learning_analysis_queue WHERE status='running' AND lease_until<?" + gate, (self.clock(),)).fetchall()
            c.execute("UPDATE learning_analysis_queue SET status='blocked',error='学习进程回执待核对，未自动重放',finished_at=? WHERE status='running' AND lease_until<?" + gate, (stamp(), self.clock()))
            for old in expired:
                self._finish_history_budget(c, old)
                if old['kind'] == 'batch_analysis':
                    self.batch.reconcile_expired(c, old)
                if old['kind'] == 'evidence_analysis':
                    evidence = self._get(c, 'learning_evidence', json.loads(old['payload'])['evidence_id'])
                    evidence['analysis_status'] = 'blocked'
                    self._put(c, 'learning_evidence', evidence)
            busy = self.batch.busy(c)
            where = " AND kind='production_review'" if busy else ''
            self.batch.sync_sources(c)
            self.batch.admit_scheduled(c)
            if self.batch.settings(c)['paused']:
                where += " AND (kind<>'batch_analysis' OR coalesce(json_extract(payload,'$.manual'),0)=1)"
            where += " AND kind<>'evidence_analysis'"
            if flags.get('batch_learning') is False:
                # An explicit compatibility rollback gate also stops already
                # queued manual packs. Their identities and inputs stay intact.
                where += " AND kind<>'batch_analysis'"
            elif not self.batch.runtime_enabled():
                where += " AND (kind<>'batch_analysis' OR coalesce(json_extract(payload,'$.manual'),0)=1)"
            row = c.execute("SELECT * FROM learning_analysis_queue WHERE status='queued'" + where + ' ORDER BY priority DESC,created_at,rowid LIMIT 1').fetchone()
            if not row:
                return None
            token = uuid.uuid4().hex
            c.execute("UPDATE learning_analysis_queue SET status='running',owner=?,lease_token=?,lease_until=?,started_at=? WHERE id=? AND status='queued'", (owner, token, self.clock() + lease_seconds, stamp(), row['id']))
            result = dict(c.execute('SELECT * FROM learning_analysis_queue WHERE id=?', (row['id'],)).fetchone())
            result['payload'] = json.loads(result['payload'])
            if result['kind'] == 'evidence_analysis':
                item = self._get(c, 'learning_evidence', result['payload']['evidence_id'])
                item['analysis_status'] = 'running'
                self._put(c, 'learning_evidence', item)
            return result

    def finish_task(self, key, token, result):
        if not isinstance(result, dict) or result.get('status', 'completed') not in TERMINAL:
            raise ValueError('学习分析回执无效')
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            task = c.execute('SELECT * FROM learning_analysis_queue WHERE id=?', (key,)).fetchone()
            if not task or task['status'] != 'running' or task['lease_token'] != token:
                raise LearningConflict('学习任务租约已变化，不能覆盖新回执')
            status = result.get('status', 'completed')
            c.execute('UPDATE learning_analysis_queue SET status=?,finished_at=?,result=?,error=? WHERE id=?', (status, stamp(), packed(result), result.get('error'), key))
            payload = json.loads(task['payload'])
            self._finish_history_budget(c, task)
            if task['kind'] == 'evidence_analysis':
                item = self._get(c, 'learning_evidence', payload['evidence_id'])
                item.update(analysis_status=status, analysis_id=key)
                self._put(c, 'learning_evidence', item)
                if status == 'completed':
                    analysis = result.get('analysis', {})
                    if not isinstance(analysis, dict):
                        raise ValueError('学习结果无效')
                    item['analysis'] = {**copy.deepcopy(analysis), 'status': 'candidate', 'authority': 'ai_analysis_not_original_quote'}
                    item.setdefault('classification', {'kind': analysis.get('classification', 'unknown'), 'scope': analysis.get('scope', 'unknown'),
                                                       'reason': analysis.get('summary', '待核对的AI分类'), 'status': 'candidate'})
                    item['revision'] += 1
                    self._put(c, 'learning_evidence', item)
                    # An AI answer is always a candidate, even if it says that a
                    # style is popular, successful, "approved" or newer.
                    for index, suggestion in enumerate(analysis.get('suggestions', [])[:20]):
                        if not isinstance(suggestion, dict):
                            continue
                        document = copy.deepcopy(suggestion)
                        document.setdefault('id', 'candidate-' + sha((key + str(index)).encode())[:32])
                        document.setdefault('name', '待核对的方法候选')
                        document.setdefault('conditions', {})
                        document.setdefault('instructions', [analysis.get('summary', '请核对原件后完善此候选')])
                        document.update(status='candidate', evidence_refs=[item['id']])
                        self._validate_entry(document)
                        pid = 'proposal-' + sha((key + str(index)).encode())[:32]
                        self._put(c, 'learning_proposals', {'id': pid, 'title': document['name'], 'kind': 'method', 'status': 'candidate',
                                                          'document': document, 'reason': bounded(suggestion.get('reason', analysis.get('summary', '基于原件的候选分析')), 20000, True),
                                                          'evidence_refs': [item['id']], 'revision': 1, 'created_at': stamp(), 'origin': 'ai_analysis',
                                                          'analysis': analysis, 'analysis_id': key})
            return {'id': key, 'status': status}
