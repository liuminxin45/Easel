"""Private business receipts around Easel's actual Codex harness.

This service owns no native transport. CodexAdapter and harnesses.rpc.connection
own execution, native questions, interruption and reusable session connections.
HTTP forwarding only subscribes to durable events; reconnecting never runs an
accepted turn again.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import inspect
import json
import re
import time
import uuid
from pathlib import Path

from easel import harnesses
from easel.direct_api import read_settings
from easel.harnesses import store as harness_store
from easel.harnesses.base import HarnessError, RunRequest
from easel.harnesses.rpc import close_sessions
from easel.harnesses.workspace import harness_instructions
from easel.runtime_env import proxy_environment, web_environment
from .paths import owned_output_path


TERMINAL = frozenset(('completed', 'stopped', 'failed', 'unknown'))


class ChatConflict(ValueError):
    pass


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def sha(value):
    return hashlib.sha256(value if isinstance(value, bytes) else packed(value).encode('utf-8')).hexdigest()


def identity(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', value):
        raise ValueError('对话标识无效')
    return value


def text(value, limit, required=False):
    if not isinstance(value, str) or len(value) > limit or '\x00' in value or required and not value.strip():
        raise ValueError('对话文字为空或过长')
    return value


def now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


class ChatService:
    def __init__(self, box, *, root=None, on_accept=None, on_started=None, on_finish=None, timeout=1800):
        self.box, self.store = box, box.store
        self.root = Path(root or box.root).resolve()
        self.outputs = owned_output_path(self.root,'outputs')
        self.sessions_dir = owned_output_path(self.root,'outputs/_sessions')
        self.on_finish = on_finish
        self.on_started = on_started
        self.on_accept = on_accept
        self.timeout = timeout
        self._tasks = {}
        self._questions = {}
        self._stop_requested = set()
        self._closing = False
        with self.store.connect() as c:
            for statement in (
                'CREATE TABLE IF NOT EXISTS easel_chat_sessions(id TEXT PRIMARY KEY,document TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS easel_chat_turns(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,operation_id TEXT UNIQUE NOT NULL,signature TEXT NOT NULL,document TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS easel_chat_operations(id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL)',
            ):
                c.execute(statement)

    def _session(self, c, session_id):
        row = c.execute('SELECT document FROM easel_chat_sessions WHERE id=?', (identity(session_id),)).fetchone()
        if not row:
            raise ValueError('找不到这份 Easel 对话')
        return json.loads(row[0])

    def _turn(self, c, turn_id):
        row = c.execute('SELECT document FROM easel_chat_turns WHERE id=?', (identity(turn_id),)).fetchone()
        if not row:
            raise ValueError('找不到准确的对话回合')
        return json.loads(row[0])

    def _put_session(self, c, session):
        c.execute('INSERT INTO easel_chat_sessions VALUES(?,?) ON CONFLICT(id) DO UPDATE SET document=excluded.document',
                  (session['id'], packed(session)))

    def _put_turn(self, c, turn):
        c.execute('UPDATE easel_chat_turns SET document=? WHERE id=?', (packed(turn), turn['id']))

    def _metadata_path(self, session_id):
        return owned_output_path(self.root,Path('outputs/_sessions/workbench')/(hashlib.sha256(session_id.encode()).hexdigest()+'.json'))

    def _save_metadata(self, session_id):
        harness_store.write_json(self._metadata_path(session_id), self.history(session_id))

    def _save_last(self, turn):
        safe = re.sub(r'[^A-Za-z0-9_.-]', '_', 'web:' + turn['session_id'])[:120]
        if len('web:' + turn['session_id']) > 120:
            safe = safe[:95] + '-' + hashlib.sha256(turn['session_id'].encode()).hexdigest()[:24]
        harness_store.write_json(owned_output_path(self.root,Path('outputs/_sessions')/(safe+'.json')), {
            'status': 'done' if turn['status'] in TERMINAL else 'running',
            'text': turn.get('output', ''), 'turn_id': turn['id'], 'runtime': 'codex',
            'at': turn['updated_at'], 'clean_end': turn['status'] == 'completed',
            'stop_reason': turn['status'] if turn['status'] in TERMINAL else None,
        })

    def _command(self, action, value, session_id=None):
        if not isinstance(value, dict):
            raise ValueError('对话操作格式无效')
        operation = identity(value.get('operation_id') or value.get('id'))
        signature = sha({'action': action, 'session_id': session_id, 'value': value})
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            previous = c.execute('SELECT signature,result FROM easel_chat_operations WHERE id=?', (operation,)).fetchone()
            if previous:
                if previous['signature'] != signature:
                    raise ChatConflict('同一操作不能修改对话内容')
                return json.loads(previous['result'])
            if action == 'create':
                owned_output_path(self.root,'outputs/_sessions')
                session_id = identity(value.get('session_id') or value.get('sessionId') or 'workbench-' + uuid.uuid4().hex)
                if c.execute('SELECT 1 FROM easel_chat_sessions WHERE id=?', (session_id,)).fetchone():
                    raise ChatConflict('此对话已经存在')
                if harness_store.binding(self.sessions_dir, session_id):
                    raise ChatConflict('此原生会话已有绑定，请保留原历史并新建对话')
                profile_id = identity(value.get('profile_id') or 'oil-pig')
                persona = value.get('persona')
                if persona is not None:
                    text(persona, 200, True)
                session = {'id': session_id, 'title': text(value.get('title', '新对话'), 200, True),
                           'title_source': 'manual' if value.get('title') not in (None, '新对话', 'New Chat') else 'default',
                           'profile_id': profile_id, 'persona': persona, 'runtime': 'codex',
                           'created': int(time.time() * 1000), 'updated': now(), 'sessionKey': session_id,
                           'revision': 1, 'archived': False, 'pendingTurnId': None}
            else:
                session = self._session(c, session_id)
                expected = value.get('expected_revision')
                if type(expected) is not int or expected != session['revision']:
                    raise ChatConflict('对话已有新修订，请重新核对')
                if value.get('profile_id', session['profile_id']) != session['profile_id']:
                    raise ChatConflict('已有对话保持原画像；切换画像请新建对话')
                if action == 'rename':
                    session['title'] = text(value.get('title'), 200, True)
                    session['title_source'] = 'manual'
                elif action == 'auto-title':
                    if session.get('title_source') == 'manual' or session['title'] not in ('新对话', 'New Chat'):
                        raise ChatConflict('保留已经命名的对话')
                    # Old clients did not record title provenance. Their operation receipts
                    # distinguish an untouched placeholder from an explicit manual rename.
                    operations = c.execute('SELECT result FROM easel_chat_operations').fetchall()
                    for row in operations:
                        old = json.loads(row[0]).get('session', {})
                        if old.get('id') == session_id and old.get('revision', 1) > 1:
                            raise ChatConflict('历史对话有手动操作，保留原名')
                    if not c.execute('SELECT 1 FROM easel_chat_turns WHERE session_id=?', (session_id,)).fetchone():
                        raise ChatConflict('空对话不自动命名')
                    session.update(title=text(value.get('title'), 200, True), title_source='automatic')
                else:
                    if session.get('pendingTurnId'):
                        raise ChatConflict('这份对话尚有运行或待核对回合，不能归档')
                    if type(value.get('archived', True)) is not bool:
                        raise ValueError('归档开关无效')
                    session['archived'] = value.get('archived', True)
                session.update(revision=session['revision'] + 1, updated=now())
            self._put_session(c, session)
            result = {'session': copy.deepcopy(session)}
            c.execute('INSERT INTO easel_chat_operations VALUES(?,?,?)', (operation, signature, packed(result)))
        self._save_metadata(session_id)
        return result

    def create_session(self, value):
        return self._command('create', value)

    def rename_session(self, session_id, value):
        return self._command('rename', value, session_id)

    def archive_session(self, session_id, value):
        return self._command('archive', value, session_id)

    def list_sessions(self):
        with self.store.connect() as c:
            items = [json.loads(row[0]) for row in c.execute('SELECT document FROM easel_chat_sessions ORDER BY rowid DESC')]
        return {'sessions': items}

    def get_turn(self, turn_id, *, private=False):
        with self.store.connect() as c:
            turn = self._turn(c, turn_id)
        if turn['status'] not in TERMINAL and turn_id not in self._tasks:
            turn.update(status='unknown', delivery_state='unknown', recovery='核对原生会话；不会自动重发。')
        if not private:
            turn['skill_refs'] = [{'id': skill['id'], 'version': skill['version']}
                                  for skill in turn.get('snapshot', {}).get('skills', [])]
            for field in ('actual_prompt', 'frozen_instructions', 'snapshot', 'request_signature'):
                turn.pop(field, None)
        return turn

    def history(self, session_id):
        with self.store.connect() as c:
            session = self._session(c, session_id)
            turns = [json.loads(row[0]) for row in c.execute('SELECT document FROM easel_chat_turns WHERE session_id=? ORDER BY rowid', (session_id,))]
        messages, linked = [], []
        for turn in turns:
            messages.append({'id': turn['id'] + '-user', 'role': 'user', 'content': turn['message'], 'timestamp': turn['created_at'],
                             'attachments': copy.deepcopy(turn.get('attachments', []))})
            messages.append({'id': turn['id'], 'role': 'assistant', 'content': turn.get('output', ''),
                             'timestamp': turn['updated_at'], 'status': self.get_turn(turn['id'])['status'],
                             'runtime': 'codex', 'thinking': turn.get('thinking', ''), 'activity': turn.get('activity', ''), 'turnId': turn['id']})
            if turn.get('work') and turn['work'] not in linked:
                linked.append(copy.deepcopy(turn['work']))
        session['messages'] = messages
        return {'session': session, 'linked_works': linked}

    def last(self, session_id):
        with self.store.connect() as c:
            session = self._session(c, session_id)
            row = c.execute('SELECT id FROM easel_chat_turns WHERE session_id=? ORDER BY rowid DESC LIMIT 1', (session_id,)).fetchone()
        if not row:
            return {'session_id': session['id'], 'status': 'idle', 'output': '', 'text': ''}
        turn = self.get_turn(row[0])
        return {**turn, 'execution_status': turn['status'],
                'status': 'done' if turn['status'] in TERMINAL else 'running',
                'text': turn.get('output', ''), 'turn_id': turn['id'],
                'clean_end': turn['status'] == 'completed',
                'stop_reason': turn['status'] if turn['status'] in TERMINAL else None}

    def receipt(self, value):
        """Check the original HTTP operation before recompiling current defaults."""
        if not isinstance(value, dict):
            raise ValueError('对话请求格式无效')
        operation = identity(value.get('operation_id') or value.get('id') or value.get('turnId'))
        turn_id = identity(value.get('turn_id') or value.get('turnId') or operation)
        with self.store.connect() as c:
            row = c.execute('SELECT document FROM easel_chat_turns WHERE operation_id=? OR id=?', (operation, turn_id)).fetchone()
        if row:
            previous = json.loads(row[0])
            if previous['request_signature'] != sha(value):
                raise ChatConflict('同一回合不能更改已经冻结的消息、技能或输入')
            return self.get_turn(previous['id'])
        return None

    async def submit(self, value, *, snapshot, actual_prompt, work=None, frozen_instructions=None):
        if self._closing:
            raise ChatConflict('服务正在关闭，请保留草稿')
        if not isinstance(value, dict):
            raise ValueError('对话请求格式无效')
        old = self.receipt(value)
        if old is not None:
            return old
        session_id = identity(value.get('session_id') or value.get('sessionId'))
        operation = identity(value.get('operation_id') or value.get('id') or value.get('turnId'))
        turn_id = identity(value.get('turn_id') or value.get('turnId') or operation)
        message = text(value.get('message', ''), 160000)
        if not message.strip() and not (isinstance(value.get('attachments'), list) and value['attachments']):
            raise ValueError('请输入消息或添加素材')
        actual_prompt = text(actual_prompt, 1024 * 1024, True)
        from .runtime.task_runtime import validated_snapshot
        frozen = validated_snapshot(snapshot, snapshot.get('task'))
        environment = self._environment()
        config = harness_store.settings(self.outputs, environment)
        model = config['models'].get('codex', '')
        if frozen_instructions is None:
            frozen_instructions = harness_instructions(RunRequest(actual_prompt, self.root, environment, model=model))
        frozen_instructions = text(frozen_instructions, 1024 * 1024, True)
        context = value.get('context', {})
        if not isinstance(context, dict) or set(context) - {'skill_id', 'version', 'action_id', 'profile_id', 'plan_token', 'work_id', 'parent_version_id', 'trial', 'article_id', 'article_mode', 'skill_revision'}:
            raise ValueError('对话启动上下文无效')
        if 'trial' in context and type(context['trial']) is not bool:
            raise ValueError('技能试用标记必须为布尔值')
        if ('work_id' in context) != ('parent_version_id' in context):
            raise ValueError('修改作品与父版本必须同时指定')
        for field in ('work_id', 'parent_version_id'):
            if field in context:
                identity(context[field])
        signature = sha({'value': value, 'snapshot': frozen, 'actual_prompt': actual_prompt, 'work': work, 'frozen_instructions': frozen_instructions})
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT signature,document FROM easel_chat_turns WHERE operation_id=? OR id=?', (operation, turn_id)).fetchone()
            if old:
                if json.loads(old['document'])['request_signature'] != sha(value):
                    raise ChatConflict('同一回合不能更改已经冻结的消息、技能或输入')
                return self.get_turn(json.loads(old['document'])['id'])
            session = self._session(c, session_id)
            if session.get('archived') or session.get('pendingTurnId'):
                raise ChatConflict('此对话已经归档或仍有回合运行／待核对；没有重复发送')
            if frozen['profile']['id'] != session['profile_id'] or context.get('profile_id', session['profile_id']) != session['profile_id']:
                raise ChatConflict('对话、技能和作品必须使用同一画像')
            initial_title = value.get('initial_title')
            if initial_title is not None:
                text(initial_title, 200, True)
                first = not c.execute('SELECT 1 FROM easel_chat_turns WHERE session_id=?', (session_id,)).fetchone()
                legacy_manual = 'title_source' not in session and any(
                    (old := json.loads(row[0]).get('session', {})).get('id') == session_id and old.get('revision', 1) > 1
                    for row in c.execute('SELECT result FROM easel_chat_operations'))
                if first and not legacy_manual and session.get('title_source', 'default') == 'default' and session['title'] in ('新对话', 'New Chat'):
                    session.update(title=initial_title, title_source='automatic')
            turn = {'id': turn_id, 'operation_id': operation, 'session_id': session_id, 'runtime': 'codex',
                    'message': message, 'context': copy.deepcopy(context), 'snapshot': frozen,
                    'actual_prompt': actual_prompt, 'actual_prompt_sha256': hashlib.sha256(actual_prompt.encode()).hexdigest(),
                    'frozen_instructions': frozen_instructions, 'instructions_sha256': hashlib.sha256(frozen_instructions.encode()).hexdigest(),
                    'model': model, 'request_signature': sha(value),
                    'cwd': str(self.root), 'session_key': session_id, 'runner': 'easel.harnesses.codex.CodexAdapter',
                    'status': 'accepted', 'delivery_state': 'not_started', 'created_at': now(), 'updated_at': now(),
                    'output': '', 'thinking': '', 'activity': '', 'attachments': copy.deepcopy(value.get('attachments') or []),
                    'native_id': '', 'work': copy.deepcopy(work), 'hook_status': 'not_started'}
            if self.on_accept:
                accepted = self.on_accept(c, turn)
                if inspect.isawaitable(accepted):
                    if inspect.iscoroutine(accepted):
                        accepted.close()
                    raise ValueError('受理记录必须在当前本地事务同步完成')
                if accepted is not None:
                    turn['accept_receipt'] = accepted
            c.execute('INSERT INTO easel_chat_turns VALUES(?,?,?,?,?)', (turn_id, session_id, operation, signature, packed(turn)))
            session.update(pendingTurnId=turn_id, updated=now(), revision=session['revision'] + 1)
            self._put_session(c, session)
        started = asyncio.Event()
        task = asyncio.create_task(self._run(turn_id, environment, started))
        self._tasks[turn_id] = task
        task.add_done_callback(lambda completed: self._tasks.pop(turn_id, None))
        self._save_metadata(session_id)
        await started.wait()
        return self.get_turn(turn_id)

    def _environment(self):
        environment = read_settings(self.root / '.env')
        environment = proxy_environment(web_environment(environment), 'localhost,127.0.0.1,::1')
        environment.update(EASEL_AGENT_RUNTIME='codex', EASEL_ROOT=str(self.root))
        return environment

    def _event_path(self, turn_id):
        return owned_output_path(self.root,Path('outputs/_sessions/jobs')/(identity(turn_id)+'.jsonl'))

    def read_events(self, turn_id, after=0):
        self.get_turn(turn_id)
        if type(after) is not int or after < 0:
            raise ValueError('事件位置无效')
        path = self._event_path(turn_id)
        if not path.is_file():
            return []
        events = []
        with path.open('rb') as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except (ValueError, UnicodeError):
                    continue
                if type(event.get('id')) is int and event['id'] > after:
                    events.append(event)
        return events

    async def events(self, turn_id, after=0):
        cursor = after
        while True:
            for event in self.read_events(turn_id, cursor):
                cursor = event['id']
                yield event
                if event['event'] == 'done':
                    return
            turn = self.get_turn(turn_id)
            if turn['status'] in TERMINAL and turn_id not in self._tasks:
                return
            await asyncio.sleep(0.1)

    def questions(self, session_id):
        with self.store.connect() as c:
            self._session(c, session_id)
        return {'questions': [{k: copy.deepcopy(v) for k, v in record.items() if k not in ('future', 'close')}
                              for record in self._questions.values() if record['session_id'] == session_id and not record['future'].done()]}

    def question_status(self, question_id, session_id=None, turn_id=None):
        identity(question_id)
        record = self._questions.get(question_id)
        if record:
            if session_id and record['session_id'] != session_id or turn_id and record['turn_id'] != turn_id:
                raise ChatConflict('问题与会话或回合不一致')
            status = record['status']
            if status == 'pending' and record['future'].done():
                status = 'expired'
            return {'status': status}
        # Terminal states live with the existing turn receipt, not a second queue.
        filters, parameters = [], []
        if session_id:
            filters.append('session_id=?'); parameters.append(session_id)
        if turn_id:
            filters.append('id=?'); parameters.append(turn_id)
        with self.store.connect() as c:
            rows = c.execute('SELECT document FROM easel_chat_turns' + (' WHERE ' + ' AND '.join(filters) if filters else ''), parameters).fetchall()
        for row in rows:
            turn = json.loads(row[0])
            for question in turn.get('questions', []):
                if question['id'] == question_id:
                    if turn_id and turn['id'] != turn_id:
                        raise ChatConflict('问题与回合不一致')
                    status = question['status']
                    return {'status': 'expired' if status == 'pending' else status}
        return {'status': 'closed'}

    def answer(self, question_id, answers, session_id, turn_id=None):
        record = self._questions.get(identity(question_id))
        if record and (record['session_id'] != session_id or turn_id and record['turn_id'] != turn_id):
            raise ChatConflict('此问题不属于当前运行回合，未提交回答')
        if not record or record['future'].done():
            status = self.question_status(question_id, session_id, turn_id)['status']
            return {'ok': False, 'answered': False, 'expired': True, 'status': status, 'error': '此问题已处理或关闭'}
        if not isinstance(answers, dict):
            raise ValueError('回答格式无效')
        ids = {q['questionId'] for q in record['questions']}
        if set(answers) != ids:
            raise ValueError('请回答本轮准确的问题')
        for key, items in answers.items():
            if not isinstance(items, list) or not items or len(items) > 10:
                raise ValueError('回答格式无效')
            for item in items:
                text(item, 10000, True)
            if key == 'permission' and items not in (['允许本次'], ['拒绝']):
                raise ValueError('请选择本次允许或拒绝')
        record['future'].set_result(copy.deepcopy(answers))
        record['close']('answered')
        return {'ok': True, 'answered': True, 'id': question_id, 'status': 'answered'}

    async def stop(self, session_id, turn_id=None):
        with self.store.connect() as c:
            session = self._session(c, session_id)
        active = session.get('pendingTurnId')
        if turn_id is not None and turn_id != active:
            raise ChatConflict('停止操作不属于当前回合')
        task = self._tasks.get(active)
        if not task or task.done():
            return {'stopped': False}
        with self.store.connect() as c:
            current = self._turn(c, active)
        if current['status'] in TERMINAL:
            return {'stopped': False}  # native completion and business hooks are separate
        self._stop_requested.add(active)
        if not task.cancelling():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        state = self.get_turn(active)
        return {'stopped': state['status'] == 'stopped', 'status': state['status']}

    async def close(self):
        self._closing = True
        tasks = list(self._tasks.values())
        for task in tasks:
            if not task.done() and not task.cancelling():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        for session in self.list_sessions()['sessions']:
            await close_sessions(session['id'])

    async def _run(self, turn_id, environment, started):
        started.set()
        with self.store.connect() as c:
            turn = self._turn(c, turn_id)
        sequence = 0
        last_flush = 0.0
        path = self._event_path(turn_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        started_hook_task = None
        secret_values = [value for key, value in environment.items()
                         if any(marker in key.upper() for marker in ('KEY', 'TOKEN', 'SECRET', 'PASSWORD'))
                         and isinstance(value, str) and len(value) >= 4]

        def scrub(value):
            result = str(value)
            for secret in secret_values:
                result = result.replace(secret, '***')
            return result

        def persist():
            turn['updated_at'] = now()
            with self.store.connect() as c:
                self._put_turn(c, turn)
            self._save_last(turn)

        def emit(kind, value):
            nonlocal sequence, last_flush
            value = scrub(value)
            if kind in ('token', 'thinking'):
                turn['output' if kind == 'token' else 'thinking'] += value
            elif kind == 'activity':
                turn['activity'] = (turn.get('activity', '') + '\n' + value).lstrip('\n')
            sequence += 1
            event = {'id': sequence, 'event': kind, 'data': value}
            with path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(event, ensure_ascii=False) + '\n')
                stream.flush()
            current = time.monotonic()
            if current - last_flush >= 0.5:
                persist()
                last_flush = current

        def bind(native_id):
            owned_output_path(self.root,'outputs/_sessions')
            harness_store.bind(self.sessions_dir, turn['session_id'], 'codex', native_id)
            turn['native_id'] = native_id
            persist()

        async def observe_started(awaitable):
            try:
                await awaitable
                turn['start_hook_status'] = 'completed'
            except Exception as error:
                turn.update(start_hook_status='failed', start_hook_error_type=type(error).__name__)

        def native_turn(thread_id, native_turn_id):
            nonlocal started_hook_task
            if turn['native_id'] != thread_id:
                raise HarnessError('实际回合与已绑定的原生会话不一致')
            turn.update(native_turn_id=native_turn_id, status='running', delivery_state='accepted', native_started_at=now())
            persist()
            if self.on_started:
                try:
                    result = self.on_started(copy.deepcopy(turn))
                    if inspect.isawaitable(result):
                        turn['start_hook_status'] = 'pending'
                        started_hook_task = asyncio.create_task(observe_started(result))
                    else:
                        turn['start_hook_status'] = 'completed'
                except Exception as error:
                    turn.update(start_hook_status='failed', start_hook_error_type=type(error).__name__)

        def native_interrupt(thread_id, native_turn_id):
            if turn['native_id'] != thread_id or turn.get('native_turn_id') != native_turn_id:
                raise HarnessError('停止回执与本轮原生会话不一致')
            turn.update(interrupt_confirmed=True, interrupt_confirmed_at=now())
            persist()

        async def ask(questions):
            identifier = 'harness_' + uuid.uuid4().hex
            future = asyncio.get_running_loop().create_future()
            safe_questions = json.loads(scrub(json.dumps(questions, ensure_ascii=False)))
            question = {'id': identifier, 'session_id': turn['session_id'], 'turn_id': turn_id,
                        'status': 'pending', 'questions': safe_questions,
                        'expiresAtMs': int((time.time() + self.timeout) * 1000)}
            turn.setdefault('questions', []).append(question)
            def close_question(status):
                if question['status'] != 'pending':
                    return
                question['status'] = status
                record['status'] = status
                emit('question_closed', json.dumps({'id': identifier, 'status': status}, ensure_ascii=False))
                persist()
            record = {**question, 'future': future, 'close': close_question}
            self._questions[identifier] = record
            try:
                emit('question', json.dumps(question, ensure_ascii=False))
                persist()
                return await asyncio.wait_for(future, self.timeout)
            finally:
                close_question('expired' if turn_id not in self._stop_requested else 'stopped')
                self._questions.pop(identifier, None)

        try:
            owned_output_path(self.root,'outputs/_sessions')
            record = harness_store.binding(self.sessions_dir, turn['session_id'])
            if record and record['runtime'] != 'codex':
                raise HarnessError('此会话属于其他底座，不能替换其历史')
            native_id = record.get('native_id', '')
            harness_store.bind(self.sessions_dir, turn['session_id'], 'codex', native_id)
            turn.update(status='submitting', delivery_state='submission_pending')
            persist()
            emit('activity', '已收到，正在连接 Codex…')
            request = RunRequest(turn['actual_prompt'], self.root, environment, native_id,
                                 turn['model'], 'workspace-write', self.timeout,
                                 session_key=turn['session_id'], codex_auto_approve=False,
                                 on_native_turn=native_turn, on_native_interrupt=native_interrupt,
                                 frozen_instructions=turn['frozen_instructions'])
            await asyncio.wait_for(harnesses.adapter('codex').run(request, emit, ask, bind), self.timeout)
            turn.update(status='completed', delivery_state='accepted')
        except asyncio.CancelledError:
            confirmed = turn_id in self._stop_requested and turn.get('interrupt_confirmed') is True
            turn.update(status='stopped' if confirmed else 'unknown',
                        delivery_state='interrupted' if confirmed else 'unknown')
            emit('activity', '已停止' if confirmed else '未取得明确停止回执，原回合等待核对；不会自动重发。')
        except (HarnessError, asyncio.TimeoutError) as error:
            turn.update(status='unknown', delivery_state='unknown', error=scrub(str(error)) if isinstance(error, HarnessError) else 'Codex 本轮超时，等待核对原回合。')
            emit('error', turn['error'])
        except Exception as error:
            turn.update(status='unknown', delivery_state='unknown', error='Codex 执行或结果记录异常，请核对原回合。', error_type=type(error).__name__)
            emit('error', turn['error'])
        finally:
            if started_hook_task:
                await asyncio.gather(started_hook_task, return_exceptions=True)
            persist()
            if self.on_finish:
                turn['hook_status'] = 'pending'
                persist()
                try:
                    receipt = self.on_finish(copy.deepcopy(turn))
                    if inspect.isawaitable(receipt):
                        receipt = await receipt
                    turn.update(hook_status='completed', business_receipt=receipt)
                except Exception as error:
                    turn.update(hook_status='failed', hook_error_type=type(error).__name__,
                                hook_error='模型原回执已保留，作品记录待核对；没有重跑模型。')
                except asyncio.CancelledError:
                    turn.update(hook_status='unknown', hook_error='模型原回执已保留，作品记录中断待核对；没有重跑模型。')
            persist()
            with self.store.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                session = self._session(c, turn['session_id'])
                if session.get('pendingTurnId') == turn_id and turn['status'] in ('completed', 'stopped', 'failed'):
                    session.update(pendingTurnId=None, updated=now(), revision=session['revision'] + 1)
                    self._put_session(c, session)
            sequence += 1
            with path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'id': sequence, 'event': 'done', 'data': {'sessionKey': turn['session_id']}}, ensure_ascii=False) + '\n')
            self._save_metadata(turn['session_id'])
            self._stop_requested.discard(turn_id)
