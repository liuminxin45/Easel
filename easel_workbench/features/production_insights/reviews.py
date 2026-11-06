"""Durable, source-bound post-delivery reviews, separate from skill management.

SQLite is authoritative. Markdown is a readable projection. No runtime operation
edits SKILL.md; unknown inference receipts are reconciled, never resubmitted.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid

from easel_workbench.runtime.desk import stamp
from easel_workbench.runtime.feedback_ledger import atomic, locked
from . import contracts

SKILLS = {'oil-pig-poster': '油猪·做贴图', 'oil-pig-article': '油猪·做文章'}
TABLE = 'production_insight_reviews'
LABELS = {'pending': '待核销', 'approved': '同意，待实施', 'rejected': '不采纳', 'applied': '已落地'}
CHUNK = 48000


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def ensure(c):
    c.execute('CREATE TABLE IF NOT EXISTS '+TABLE+'(id TEXT PRIMARY KEY,work_id TEXT NOT NULL,skill_id TEXT NOT NULL,status TEXT NOT NULL,document TEXT NOT NULL,updated_at TEXT NOT NULL)')
    c.execute('CREATE INDEX IF NOT EXISTS production_insight_work ON '+TABLE+'(work_id,id)')
    c.execute('CREATE TABLE IF NOT EXISTS production_insight_operations(id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS production_insight_state(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    if not c.execute("SELECT 1 FROM production_insight_state WHERE key='feedback_rowid'").fetchone():
        exists = c.execute("SELECT 1 FROM sqlite_master WHERE name='toolbox_jobs'").fetchone()
        latest = c.execute('SELECT coalesce(max(rowid),0) FROM toolbox_jobs').fetchone()[0] if exists else 0
        c.execute('INSERT INTO production_insight_state VALUES(?,?)', ('feedback_rowid', str(latest)))


def _text(value, maximum, required=False):
    if not isinstance(value, str) or len(value) > maximum or required and not value.strip():
        raise ValueError('复盘输入无效')
    return value


class Service:
    def __init__(self, box, *, execute=None, allowed=None):
        self.box, self.store = box, box.store
        self.root = Path(box.root).resolve()
        self.directory = self.root / 'data/production-insights'
        self.execute = execute or self._execute
        self.allowed = allowed or (lambda: True)
        with self.store.connect() as c:
            ensure(c)

    def _row(self, c, work_id, version_id):
        row = c.execute('SELECT document FROM '+TABLE+' WHERE id=? AND work_id=?', (version_id, work_id)).fetchone()
        if not row:
            raise ValueError('此版本尚无制作复盘')
        return json.loads(row[0])

    def _put(self, c, value):
        value['updated_at'] = stamp()
        c.execute('UPDATE '+TABLE+' SET status=?,document=?,updated_at=? WHERE id=?',
                  (value['status'], packed(value), value['updated_at'], value['version_id']))

    def enqueue(self, turn, receipt, c=None):
        """Called within the exact delivery transaction, not by page polling."""
        if (turn.get('status') != 'completed' or receipt.get('status') != 'completed'
                or receipt.get('whole_ready') is not True or receipt.get('skill_id') not in SKILLS):
            return None
        if receipt.get('version_id') != turn.get('id') or receipt.get('session_id') != turn.get('session_id'):
            raise ValueError('复盘须绑定准确制作回合')
        if not turn.get('native_turn_id') and (turn.get('execution_identity') or {}).get('kind') not in ('jsonrpc_request', 'cli_result_sha256'):
            raise ValueError('复盘缺少准确原生制作回执')
        if c is None:
            with self.store.connect() as owned:
                owned.execute('BEGIN IMMEDIATE')
                return self.enqueue(turn, receipt, c=owned)
        ensure(c)
        identity = contracts.digest({'receipt': receipt, 'prompt': turn.get('actual_prompt_sha256'), 'output': turn.get('output')})
        old = c.execute('SELECT document FROM '+TABLE+' WHERE id=?', (turn['id'],)).fetchone()
        if old:
            value = json.loads(old[0])
            if value['identity'] != identity:
                raise ValueError('制作复盘的准确版本不能替换')
            return {'id': value['version_id'], 'status': value['status']}
        if not c.execute('SELECT 1 FROM artifacts WHERE task_id=?', (turn['id'],)).fetchone():
            raise ValueError('没有真实成品，不创建制作复盘')
        value = {'schema': 1, 'version_id': turn['id'], 'work_id': receipt['work_id'], 'skill_id': receipt['skill_id'],
                 'profile_id': receipt.get('profile_id'), 'profile_revision': receipt.get('profile_revision'),
                 'session_id': turn['session_id'], 'identity': identity, 'receipt': receipt,
                 'status': 'queued', 'created_at': stamp(), 'updated_at': stamp(), 'items': [], 'events': [],
                 'target_turn': {k: turn.get(k) for k in ('id', 'session_id', 'created_at', 'message', 'actual_prompt',
                    'frozen_instructions', 'actual_prompt_sha256', 'output', 'native_turn_id', 'execution_settings', 'model', 'runtime')}}
        c.execute('INSERT INTO '+TABLE+' VALUES(?,?,?,?,?,?)',
                  (value['version_id'], value['work_id'], value['skill_id'], value['status'], packed(value), value['updated_at']))
        return {'id': value['version_id'], 'status': value['status']}

    def _feedback(self, c, version_id):
        return [dict(row) for row in c.execute("SELECT id,kind,text,scope,created_at FROM toolbox_jobs WHERE candidate_id=? AND kind IN ('accept','reject','feedback') ORDER BY rowid", (version_id,))]

    def view(self, work_id, version_id):
        with self.store.connect() as c:
            row = c.execute('SELECT document FROM '+TABLE+' WHERE id=? AND work_id=?', (version_id, work_id)).fetchone()
            if not row:
                return {'version_id': version_id, 'work_id': work_id, 'status': 'not_requested', 'items': [], 'feedback': []}
            value = json.loads(row[0]); feedback = self._feedback(c, version_id)
        return {k: value[k] for k in ('schema', 'version_id', 'work_id', 'skill_id', 'profile_id', 'session_id',
                'status', 'created_at', 'updated_at', 'items', 'events', 'summary', 'error', 'coverage', 'parts_completed', 'parts_total') if k in value} | {
            'feedback': feedback,
            'sources': [{k: source[k] for k in ('id', 'kind', 'name', 'sha256', 'characters', 'bytes', 'inspected') if k in source}
                        for source in value.get('sources', [])],
            'notice': 'AI 建议仅供逐条核销；同意不等于已修改技能。原始反馈独立保留。'}

    def source(self, work_id, version_id, source_id):
        with self.store.connect() as c:
            value = self._row(c, work_id, version_id)
        source = next((item for item in value.get('sources', []) if item['id'] == source_id), None)
        if source is None:
            raise ValueError('复盘来源不存在')
        result = {k: v for k, v in source.items() if k not in ('path', 'text_path')}
        if source.get('text_path'):
            result['text'] = self._source_text(source)
        return result

    def _source_text(self, source):
        path = Path(source['text_path'])
        if not path.resolve().is_relative_to(self.directory/'sources') or path.is_symlink():
            raise ValueError('复盘冻结来源路径无效')
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source['sha256']:
            raise ValueError('复盘冻结来源字节已变化')
        return raw.decode('utf-8')

    def _part_sources(self, value, part):
        lookup = {item['id']: item for item in value['sources']}
        return [{**item, 'text': self._source_text(lookup[item['source_id']])[item['offset']:item['offset']+CHUNK]}
                for item in part['sources']]

    def operation_result(self, operation_id):
        with self.store.connect() as c:
            row = c.execute('SELECT result FROM production_insight_operations WHERE id=?', (operation_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def decide(self, work_id, version_id, value):
        operation = _text(value.get('operation_id'), 160, True)
        item_id = _text(value.get('item_id') or value.get('id'), 100, True)
        decision = value.get('decision'); note = _text(value.get('note', ''), 4000)
        if decision not in ('approve', 'reject', 'applied'):
            raise ValueError('复盘核销决定无效')
        evidence = self._applied_evidence(work_id, version_id, item_id, value.get('evidence')) if decision == 'applied' else None
        signature = contracts.digest({'work': work_id, 'version': version_id, 'value': value})
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT signature,result FROM production_insight_operations WHERE id=?', (operation,)).fetchone()
            if old:
                if old['signature'] != signature:
                    raise ValueError('同一核销操作不能改变决定')
                return json.loads(old['result'])
            document = self._row(c, work_id, version_id)
            item = next((item for item in document.get('items', []) if item['id'] == item_id), None)
            if item is None:
                raise ValueError('待核销条目不存在')
            if item['status'] == 'applied':
                raise ValueError('已落地条目不能覆写；请新增后续意见')
            if decision == 'applied' and item['status'] != 'approved':
                raise ValueError('条目须先明确同意，再按真实证据核销落地')
            item['status'] = {'approve': 'approved', 'reject': 'rejected', 'applied': 'applied'}[decision]
            event = {'id': operation, 'item_id': item_id, 'decision': decision, 'note': note, 'at': stamp()}
            if evidence:
                event['evidence'] = evidence; item['applied_evidence'] = evidence
            document['events'].append(event); self._put(c, document)
            result = {'operation_id': operation, 'version_id': version_id, 'item_id': item_id, 'status': item['status']}
            c.execute('INSERT INTO production_insight_operations VALUES(?,?,?,?)', (operation, signature, packed(result), stamp()))
        self.project(document['skill_id'])
        return result

    def _applied_evidence(self, work_id, version_id, item_id, evidence):
        if not isinstance(evidence, dict):
            raise ValueError('已落地必须提供可核验的模板或技能提交证据')
        if evidence.get('type') == 'template':
            from .templates import Service as Templates
            with self.store.connect() as c:
                review = self._row(c, work_id, version_id)
            template = Templates(self.box).get(evidence.get('template_id'), review['profile_id'], review['receipt']['format'], evidence.get('revision'))
            if template.get('source_version_id') != version_id or template.get('source_work_id') != work_id:
                raise ValueError('优秀模板不是此准确版本的落地证据')
            ids = template.get('review_item_ids', [])
            if item_id not in ids:
                raise ValueError('优秀模板未明确吸收此复盘条目')
            return evidence
        if evidence.get('type') != 'skill_commit':
            raise ValueError('落地证据类型无效')
        commit = evidence.get('commit', ''); sha = evidence.get('sha256', '')
        if not re.fullmatch(r'[0-9a-f]{40}', commit) or not re.fullmatch(r'[0-9a-f]{64}', sha):
            raise ValueError('技能提交证据不完整')
        with self.store.connect() as c:
            review = self._row(c, work_id, version_id)
        path = 'skills/builtin/'+review['skill_id']+'/SKILL.md'
        run = lambda args: subprocess.run(['git', '-C', str(self.root), *args], capture_output=True, timeout=10, check=True)
        try:
            run(['merge-base', '--is-ancestor', commit, 'HEAD'])
            changed = run(['diff-tree', '--no-commit-id', '--name-only', '-r', commit]).stdout.decode().splitlines()
            raw = run(['show', commit+':'+path]).stdout
            message = run(['show', '-s', '--format=%B', commit]).stdout.decode('utf-8')
            if path not in changed or item_id not in message or hashlib.sha256(raw).hexdigest() != sha or (self.root/path).read_bytes() != raw:
                raise ValueError('技能提交未包含此条目对应的准确当前技能修改')
        except (subprocess.SubprocessError, OSError):
            raise ValueError('无法核对技能提交；条目仍为待实施') from None
        return {'type': 'skill_commit', 'commit': commit, 'sha256': sha, 'path': path}

    def mark_template_applied(self, template):
        """Called after a confirmed immutable template is actually committed.

        Each item retains its own deterministic receipt, so a process exit
        between the template commit and this projection is safely recoverable.
        """
        results = []
        for item_id in template.get('review_item_ids', []):
            evidence = {'type': 'template', 'template_id': template['id'], 'revision': template['revision']}
            operation = 'template-review-'+contracts.digest({'template': template['id'], 'revision': template['revision'], 'item': item_id})[:32]
            results.append(self.decide(template['source_work_id'], template['source_version_id'], {
                'operation_id': operation, 'item_id': item_id, 'decision': 'applied',
                'note': '用户确认优秀模板时明确吸收此条建议；未修改技能源文件。', 'evidence': evidence}))
        return results

    def master(self, skill_id):
        if skill_id not in SKILLS:
            raise ValueError('不支持此技能的制作复盘')
        text = self.project(skill_id)
        return {'skill_id': skill_id, 'name': SKILLS[skill_id], 'text': text,
                'path': 'data/production-insights/'+skill_id+'.md'}

    def refresh_feedback(self):
        """Incremental raw feedback projection; never invokes the model."""
        self.directory.mkdir(parents=True, exist_ok=True)
        with locked(self.directory/'feedback-refresh.lock', timeout=.01):
            with self.store.connect() as c:
                lower = int(c.execute("SELECT value FROM production_insight_state WHERE key='feedback_rowid'").fetchone()[0])
                upper = c.execute('SELECT coalesce(max(rowid),0) FROM toolbox_jobs').fetchone()[0]
                if upper <= lower:
                    return 0
                skills = [row[0] for row in c.execute('SELECT DISTINCT r.skill_id FROM toolbox_jobs j JOIN '+TABLE+" r ON r.id=j.candidate_id WHERE j.rowid>? AND j.rowid<=? AND j.kind IN ('accept','reject','feedback')", (lower, upper))]
            for skill_id in skills:
                self.project(skill_id)
            with self.store.connect() as c:
                c.execute("UPDATE production_insight_state SET value=? WHERE key='feedback_rowid'", (str(upper),))
            return len(skills)

    def project(self, skill_id):
        if skill_id not in SKILLS:
            raise ValueError('不支持此技能的制作复盘')
        self.directory.mkdir(parents=True, exist_ok=True)
        with locked(self.directory / 'master.lock'):
            with self.store.connect() as c:
                rows = [json.loads(row[0]) for row in c.execute('SELECT document FROM '+TABLE+' WHERE skill_id=? ORDER BY rowid', (skill_id,))]
                feedback = {row['version_id']: self._feedback(c, row['version_id']) for row in rows}
            lines = ['# '+SKILLS[skill_id]+' · 制作复盘总记录', '', '这是私有业务记录，不是已生效技能。AI建议与用户原始反馈分别记录；核销按真实落地证据进行。', '']
            for row in rows:
                lines += ['## '+row['version_id'], '', '- 作品：'+row['work_id'], '- 会话：'+row['session_id'], '- 状态：'+row['status'], '']
                if row.get('summary'):
                    lines += [row['summary'], '']
                for item in row.get('items', []):
                    lines += ['### '+item['title'], '', '- ID：'+item['id'], '- 核销：'+LABELS[item['status']],
                              '- 依据：'+item['basis'], '- 来源：'+', '.join(item['source_ids']), '', item['lesson'], '']
                for item in feedback[row['version_id']]:
                    lines += ['### 用户原始反馈 '+item['id'], '', '类型：'+item['kind']+'；范围：'+item['scope'], '', item['text'], '']
                for event in row.get('events', []):
                    lines += ['- 核销记录 '+event['id']+'：'+event['decision']+'；'+event['note']+'；'+event['at']]
                    if event.get('evidence'):
                        lines += ['  落地证据：'+packed(event['evidence'])]
                lines += ['']
            text = '\n'.join(lines)
            path = self.directory/(skill_id+'.md')
            if not path.exists() or path.read_text(encoding='utf-8') != text:
                atomic(path, text)
            return text

    def _freeze(self, value):
        sources = []; seen = set(); turns = []
        def add(identity, kind, name, text=None, **extra):
            if identity in seen:
                return
            seen.add(identity)
            item = {'id': identity, 'kind': kind, 'name': name, **extra}
            if text is not None:
                item.update(text=text, characters=len(text), sha256=hashlib.sha256(text.encode()).hexdigest())
            sources.append(item)
        with self.store.connect() as c:
            if c.execute("SELECT 1 FROM sqlite_master WHERE name='easel_chat_turns'").fetchone():
                for row in c.execute('SELECT document FROM easel_chat_turns WHERE session_id=? ORDER BY rowid', (value['session_id'],)):
                    turn = json.loads(row[0])
                    selected = (turn.get('context') or {}).get('skill_id')
                    # Article production and the separate learning skills do
                    # not supply a poster skill's review corpus, or vice versa.
                    if selected in (*SKILLS, 'oil-pig-learn-poster', 'oil-pig-learn-article') and selected != value['skill_id']:
                        continue
                    turns.append(turn)
                    if turn['id'] == value['version_id']:
                        break
            if not any(turn['id'] == value['version_id'] for turn in turns):
                turns.append(value['target_turn'])
            for turn in turns:
                for field in ('message', 'actual_prompt', 'frozen_instructions', 'output'):
                    text = turn.get(field)
                    if isinstance(text, str) and text:
                        add('turn:'+turn['id']+':'+field, 'user' if field == 'message' else 'assistant' if field == 'output' else 'frozen_input', field, text)
            for feedback in self._feedback(c, value['version_id']):
                add('feedback:'+feedback['id'], 'user_feedback', feedback['kind'], packed(feedback))
            files = [dict(row) for row in c.execute('SELECT id,name,path,mime FROM artifacts WHERE task_id=? ORDER BY rowid', (value['version_id'],))]
        for file in files:
            path = Path(file['path'])
            if not path.is_file() or path.is_symlink() or not path.resolve().is_relative_to(self.root/'data/artifacts'):
                raise ValueError('准确成品原件不存在或离开产物存储')
            size = path.stat().st_size
            if size > 20*1024*1024 or (file['mime'].startswith('text/') or file['mime'] == 'application/json') and size > 2*1024*1024:
                with path.open('rb') as stream:
                    sha = hashlib.file_digest(stream, 'sha256').hexdigest()
                add('file:'+file['id'], 'file', file['name'], bytes=size, sha256=sha, inspected=False)
                continue
            raw = path.read_bytes(); sha = hashlib.sha256(raw).hexdigest()
            if file['mime'].startswith('text/') or file['mime'] == 'application/json':
                try:
                    text = raw.decode('utf-8-sig')
                except UnicodeError:
                    add('file:'+file['id'], 'file', file['name'], bytes=size, sha256=sha, inspected=False)
                else:
                    add('file:'+file['id'], 'product_text', file['name'], text, bytes=size, inspected=True)
            elif file['mime'].startswith('image/') and size <= 20*1024*1024:
                add('file:'+file['id'], 'image', file['name'], bytes=size, sha256=sha, path=str(path), inspected=True)
            else:
                add('file:'+file['id'], 'file', file['name'], bytes=size, sha256=sha, inspected=False)
        chunks = []; current = []; length = 0
        for source in sources:
            text = source.get('text')
            if text is None:
                continue
            for index in range(0, max(len(text), 1), CHUNK):
                part = {'source_id': source['id'], 'kind': source['kind'], 'name': source['name'],
                        'offset': index, 'total_characters': len(text), 'text': text[index:index+CHUNK]}
                if current and length+len(part['text']) > CHUNK:
                    chunks.append({'sources': current, 'images': []}); current = []; length = 0
                current.append(part); length += len(part['text'])
        if current:
            chunks.append({'sources': current, 'images': []})
        images = [item for item in sources if item['kind'] == 'image']
        for index in range(0, len(images), 4):
            chunks.append({'sources': [], 'images': images[index:index+4]})
        if not chunks:
            raise ValueError('没有可复盘的制作资料')
        # Conversation text is immutable disk evidence, requested only by the
        # current bounded inference part or an explicit detail view. SQLite
        # keeps references rather than several full copies of a long session.
        for source in sources:
            if 'text' not in source:
                continue
            text = source.pop('text')
            path = self.directory/'sources'/(contracts.digest({'id': source['id'], 'sha256': source['sha256']})+'.txt')
            if path.exists():
                if hashlib.sha256(path.read_bytes()).hexdigest() != source['sha256']:
                    raise ValueError('复盘已冻结来源不能覆写')
            else:
                atomic(path, text)
            source['text_path'] = str(path)
        for chunk in chunks:
            for item in chunk['sources']:
                item.pop('text')
            chunk.update(receipt_id=uuid.uuid4().hex, status='queued')
        value.update(sources=sources, parts=chunks, parts_total=len(chunks), parts_completed=0,
                     coverage={'conversation_turns': len(turns), 'text_characters': sum(item.get('characters',0) for item in sources),
                               'images_supplied': len(images), 'files_not_inspected': [item['id'] for item in sources if item.get('inspected') is False]})
        target = value['target_turn']
        models = (target.get('execution_settings') or {}).get('models') or {}
        review_model = target.get('model') if target.get('runtime') == 'codex' else models.get('codex')
        if review_model is not None and (not isinstance(review_model, str) or len(review_model) > 200):
            raise ValueError('冻结的复盘模型配置无效')
        value['target_turn'] = {k: target.get(k) for k in ('id', 'runtime', 'model')}
        value['review_model'] = review_model
        return value

    def _execute(self, value, part):
        from easel_workbench import readonly_runner
        from easel_workbench.runtime import task_runtime
        from easel_workbench.runtime.readonly_codex import command
        binding = contracts.snapshot({'id': value['profile_id'], 'revision': value['profile_revision']})
        payload = {'version_id': value['version_id'], 'skill_id': value['skill_id'], 'sources': self._part_sources(value, part),
                   'images': [{k: v for k, v in item.items() if k != 'path'} for item in part['images']]}
        prompt = contracts.INTRO+'\n\n本次仅资料：\n'+packed(payload)
        folder = self.directory/'calls'/part['receipt_id']; folder.mkdir(parents=True, exist_ok=True)
        schema_path = folder/'schema.json'
        if not schema_path.exists():
            atomic(schema_path, contracts.SCHEMA)
        call = 'production-review-'+part['receipt_id']
        task_runtime.begin_call(self.box, 'production_review', payload, prompt, operation_id=call, snapshot=binding,
                                task_id=value['version_id'])
        args = command(folder)
        model = value.get('review_model')
        args = [*args[:-1], *(['--model', model] if model and model.strip() else []), '-c', 'model_reasoning_effort="low"']
        for image in part['images']:
            path = Path(image['path'])
            if hashlib.sha256(path.read_bytes()).hexdigest() != image['sha256']:
                task_runtime.finish_call(self.box, call, 'not_started', error='准确成品字节发生变化')
                raise ValueError('准确成品字节发生变化')
            args += ['--image', str(path)]
        args += ['-']
        try:
            result = readonly_runner.run(binding, args, input=prompt, cwd=folder, timeout=420, runtime_root=self.root,
                                         task_id=value['version_id'], receipt_id=part['receipt_id'], env=dict(os.environ))
            answer = json.loads((folder/'answer.json').read_text(encoding='utf-8'))
            task_runtime.finish_call(self.box, call, 'completed', {'model_output': answer, 'execution_receipt': result.execution_receipt})
            return answer
        except BaseException as error:
            receipt = self._receipt(part)
            status = 'not_started' if receipt and receipt.get('status') == 'not_started' else 'unknown' if isinstance(error, (ConnectionError, TimeoutError)) or not receipt or receipt.get('status') in ('preparing', 'accepted', 'unknown') else 'failed'
            task_runtime.finish_call(self.box, call, status, error=type(error).__name__)
            raise

    def _receipt(self, part):
        path = self.root/'data/readonly-receipts'/(part['receipt_id']+'.json')
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return None

    def _settle_recovered_call(self, part, receipt, error=None):
        """A dead worker must not leave its observation marked as executing.

        This only reconciles the pre-existing exact call. It never creates a
        call or retries transport. Unknown remains distinct from not started.
        """
        call_id = 'production-review-'+part['receipt_id']
        with self.store.connect() as c:
            if not c.execute("SELECT 1 FROM sqlite_master WHERE name='creator_model_calls'").fetchone():
                return
            row = c.execute('SELECT document FROM creator_model_calls WHERE id=?', (call_id,)).fetchone()
        if not row:
            return
        current = json.loads(row[0])
        status = (receipt or {}).get('status')
        terminal = status if status in ('completed', 'not_started', 'failed') else 'unknown'
        # Preserve a definitive observation if its secondary file went missing.
        if current.get('status') == 'completed' and terminal != 'completed':
            return
        from easel_workbench.runtime.task_runtime import finish_call
        result = {'execution_receipt': receipt} if receipt else None
        if status == 'completed':
            try:
                result['model_output'] = json.loads(receipt['model_output_text'])
            except (KeyError, ValueError, TypeError):
                result['model_output_text'] = receipt.get('model_output_text')
        finish_call(self.box, call_id, terminal, result=result,
                    error=type(error).__name__ if error else None)

    def _validate(self, answer, part):
        if not isinstance(answer, dict) or not isinstance(answer.get('items'), list) or len(answer['items']) > 12:
            raise ValueError('复盘模型结果结构无效')
        _text(answer.get('summary'), 6000)
        ids = {item['source_id'] for item in part['sources']} | {item['id'] for item in part['images']}
        user_ids = {item['source_id'] for item in part['sources'] if item['kind'] in ('user', 'user_feedback')}
        for item in answer['items']:
            _text(item.get('title'), 200, True); _text(item.get('lesson'), 6000, True)
            if item.get('category') not in ('process', 'writing', 'visual', 'avoid', 'template') or item.get('basis') not in ('explicit_user_feedback', 'production_evidence', 'ai_suggestion'):
                raise ValueError('复盘建议类型无效')
            refs = item.get('source_ids')
            if not isinstance(refs, list) or not refs or not all(isinstance(ref, str) and ref in ids for ref in refs):
                raise ValueError('复盘建议引用了未提供的来源')
            if item['basis'] == 'explicit_user_feedback' and not user_ids.intersection(refs):
                raise ValueError('用户评价缺少用户原文依据')
        return answer

    def _finish_part(self, value, part, answer):
        answer = self._validate(answer, part)
        part.update(status='completed', answer=answer)
        value['parts_completed'] = sum(item['status'] == 'completed' for item in value['parts'])
        if value['parts_completed'] == len(value['parts']):
            items = []; seen = set(); summaries = []
            for chunk in value['parts']:
                summaries.append(chunk['answer']['summary'])
                for item in chunk['answer']['items']:
                    identity = contracts.digest({'version': value['version_id'], 'lesson': item['lesson'], 'category': item['category']})[:24]
                    if identity not in seen:
                        seen.add(identity); items.append({**item, 'id': 'review-'+identity, 'status': 'pending'})
            value.update(items=items, summary='\n\n'.join(summaries), status='completed')
        else:
            value['status'] = 'queued'

    def run_pending_once(self):
        """One bounded part per call. Lock covers transport; no parallel sender."""
        self.directory.mkdir(parents=True, exist_ok=True)
        with locked(self.directory/'worker.lock', timeout=.01):
            if not self.allowed():
                return False
            with self.store.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                has_turns = c.execute("SELECT 1 FROM sqlite_master WHERE name='easel_chat_turns'").fetchone()
                # A slow or failed finish hook for one product must not prevent
                # already committed products later in the queue being reviewed.
                ready = (" AND (NOT EXISTS(SELECT 1 FROM easel_chat_turns t WHERE t.id=r.id) OR "
                         "(SELECT json_extract(t.document,'$.hook_status') FROM easel_chat_turns t WHERE t.id=r.id) IS NULL OR "
                         "(SELECT json_extract(t.document,'$.hook_status') FROM easel_chat_turns t WHERE t.id=r.id)='completed')") if has_turns else ''
                row = c.execute("SELECT r.document FROM "+TABLE+" r WHERE r.status IN ('queued','running')"+ready+" ORDER BY r.rowid LIMIT 1").fetchone()
                if not row:
                    # Reconcile an original receipt that became definitive. An
                    # unknown request is never sent again under another identity.
                    candidates = c.execute("SELECT document FROM "+TABLE+" WHERE status='unknown' ORDER BY rowid").fetchall()
                    for candidate in candidates:
                        current = json.loads(candidate[0])
                        pending = next((item for item in current.get('parts', []) if item['status'] == 'unknown'), None)
                        receipt = self._receipt(pending) if pending else None
                        if receipt and receipt.get('status') == 'completed':
                            row = candidate; current['status'] = 'running'; pending['status'] = 'running'
                            row = (packed(current),); break
                    if not row:
                        return False
                value = json.loads(row[0])
                # Delivery registration runs inside the existing finish hook.
                # Its success must be durable before a background read starts.
                target = c.execute('SELECT document FROM easel_chat_turns WHERE id=?', (value['version_id'],)).fetchone() if c.execute("SELECT 1 FROM sqlite_master WHERE name='easel_chat_turns'").fetchone() else None
                if target:
                    saved_turn = json.loads(target[0])
                    if 'hook_status' in saved_turn and saved_turn['hook_status'] != 'completed':
                        return False
                if 'parts' not in value:
                    try:
                        value = self._freeze(value)
                    except Exception as error:
                        value.update(status='blocked', error='复盘资料未能冻结：'+str(error)[:500])
                        self._put(c, value)
                preparation_failed = value['status'] == 'blocked'
                if not preparation_failed:
                    part = next(item for item in value['parts'] if item['status'] != 'completed')
                    recovering = part['status'] == 'running'
                    if not recovering:
                        if not self.allowed():
                            return False
                        part['status'] = 'running'; value['status'] = 'running'; self._put(c, value)
            if preparation_failed:
                self.project(value['skill_id'])
                return True
            if not recovering and not self.allowed():
                # Claim was durable (visible to deployment's second idle
                # check), but no model transport has been attempted yet.
                # Retain its original receipt identity for the future sender.
                if self._receipt(part) is None:
                    part['status'] = 'queued'; value['status'] = 'queued'
                    with self.store.connect() as c:
                        c.execute('BEGIN IMMEDIATE'); self._put(c, value)
                    return False
                # An existing receipt is never converted to a fresh queue item.
                recovering = True
            try:
                if recovering:
                    receipt = self._receipt(part)
                    if receipt and receipt.get('status') == 'completed':
                        answer = json.loads(receipt['model_output_text'])
                        self._settle_recovered_call(part, receipt)
                    elif receipt and receipt.get('status') in ('not_started', 'failed'):
                        raise ValueError('原复盘请求确认未启动或已失败；原记录保留，未重新调用模型')
                    else:
                        raise ConnectionError('复盘进程曾中断，原请求未自动重发')
                else:
                    answer = self.execute(value, part)
                self._finish_part(value, part, answer)
            except Exception as error:
                receipt = self._receipt(part)
                if recovering:
                    self._settle_recovered_call(part, receipt, error)
                value['status'] = 'unknown' if isinstance(error, (ConnectionError, TimeoutError)) or receipt and receipt.get('status') in ('accepted', 'unknown', 'preparing') else 'blocked'
                part['status'] = value['status']; value['error'] = str(error)[:500]
            with self.store.connect() as c:
                c.execute('BEGIN IMMEDIATE'); self._put(c, value)
            self.project(value['skill_id'])
            return True

    def background(self, stop):
        while not stop.is_set():
            try:
                worked = self.run_pending_once()
            except Exception:
                worked = False
            stop.wait(1 if worked else 30)


def service(box):
    """One schema initialization before any delivery transaction opens."""
    instance = getattr(box, '_production_insight_reviews', None)
    if instance is None:
        instance = Service(box)
        box._production_insight_reviews = instance
    return instance
