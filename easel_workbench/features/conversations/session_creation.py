"""Durable creation of empty sessions, never model turns or publication work.

The old command ledger remains authoritative for completed results. This small
intake ledger supplies restartable metadata work and fences absent legacy IDs.
"""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import os

from easel.web_services.concurrency import run_sync
from .receipts import ChatConflict, identity, now, packed, sha, text


TABLE = 'easel_chat_creation_intents'
ACTIVE = ('accepted', 'running')


def emit_lifecycle(operation, state, *, session_id=None, error_type=None):
    from easel_workbench.runtime import server_logging as journal
    fields={'operation_ref':journal.reference(operation),'phase':state}
    if session_id:fields['resource_ref']=journal.reference(session_id)
    if error_type:fields['error_type']=error_type
    journal.emit('session_creation',**fields)


def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS easel_chat_creation_intents(
 id TEXT PRIMARY KEY,signature TEXT NOT NULL,request TEXT NOT NULL,
 session_id TEXT,state TEXT NOT NULL,settings TEXT,profile_revision TEXT,
 result TEXT,error_code TEXT,error_type TEXT,owner_pid INTEGER,
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL,projection_error TEXT)''')


def row(c, operation):
    value = c.execute('SELECT * FROM '+TABLE+' WHERE id=?', (operation,)).fetchone()
    return dict(value) if value else None


def original_signature(value):
    return sha({'action': 'create', 'session_id': None, 'value': value})


def guard(c, operation, signature):
    value = row(c, operation)
    if not value:
        return None
    if value['signature'] != signature:
        raise ChatConflict('同一操作不能修改对话内容')
    if value['state'] in ('sealed_not_accepted', 'rejected'):
        raise ChatConflict('原创建命令已结束且不会执行，请按原意图重新打开对话')
    return value


def complete(c, operation, result):
    c.execute('UPDATE '+TABLE+" SET state='completed',result=?,error_code=NULL,error_type=NULL,updated_at=? WHERE id=?",
              (packed(result), now(), operation))


def projection(c, operation, error_type):
    c.execute('UPDATE '+TABLE+' SET projection_error=?,updated_at=? WHERE id=?', (error_type, now(), operation))


def envelope(operation, state, *, result=None, code=None):
    value = {'protocol_version': 2, 'operation_id': operation, 'operation_state': state}
    if result is not None:
        value['result'] = result
        if isinstance(result, dict) and 'session' in result:
            value['session'] = result['session']
    if code:
        value['code'] = code
    return value


def read_receipt(c, operation):
    """No inserts, leases, recovery execution or metadata projection on GET."""
    old = c.execute('SELECT result FROM easel_chat_operations WHERE id=?', (operation,)).fetchone()
    if old:
        return envelope(operation, 'completed', result=json.loads(old[0]))
    value = row(c, operation)
    if not value:
        return envelope(operation, 'unresolved')
    return envelope(operation, value['state'], result=json.loads(value['result']) if value['result'] else None,
                    code=value['error_code'])


class SessionCreation:
    def __init__(self, chat):
        self.chat, self.store = chat, chat.store
        self.tasks = {}
        self.projection_tasks = {}
        self.projection_delays = (1, 5, 30)
        self.loop = None
        self.closing = False
        with self.store.connect() as c:
            initialize(c)

    @staticmethod
    def request(value):
        if not isinstance(value, dict) or set(value)-{'action', 'id', 'operation_id', 'session_id', 'sessionId', 'profile_id', 'persona', 'title','news_article_id','news_new_session'}:
            raise ValueError('新建对话请求格式无效')
        if value.get('action', 'create') != 'create':
            raise ValueError('仅支持核对新建对话')
        operation = identity(value.get('operation_id') or value.get('id'))
        identity(value.get('profile_id') or 'oil-pig')
        if value.get('session_id') or value.get('sessionId'):
            identity(value.get('session_id') or value.get('sessionId'))
        text(value.get('title', '新对话'), 200, True)
        if value.get('persona') is not None:
            text(value['persona'], 200, True)
        return operation, original_signature(value)

    def inspect(self, operation):
        with self.store.connect() as c:
            return read_receipt(c, identity(operation))

    def accept(self, value, validate_profile):
        operation, signature = self.request(value)
        with self.store.connect() as c:
            previous = c.execute('SELECT signature,result FROM easel_chat_operations WHERE id=?', (operation,)).fetchone()
            intent = row(c, operation)
        if previous:
            if previous['signature'] != signature:
                raise ChatConflict('同一操作不能修改对话内容')
            return envelope(operation, 'completed', result=json.loads(previous['result']))
        if intent:
            if intent['signature'] != signature:
                raise ChatConflict('同一操作不能修改对话内容')
            return self.inspect(operation)
        # The same accepted operation always retains this exact configuration.
        profile = validate_profile(value.get('profile_id') or 'oil-pig')
        settings = self.chat.settings.capture()
        target = identity(value.get('session_id') or value.get('sessionId') or
                          'workbench-' + hashlib.sha256(operation.encode()).hexdigest()[:32])
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            previous = c.execute('SELECT signature,result FROM easel_chat_operations WHERE id=?', (operation,)).fetchone()
            if previous:
                if previous['signature'] != signature:
                    raise ChatConflict('同一操作不能修改对话内容')
                return envelope(operation, 'completed', result=json.loads(previous['result']))
            existing = row(c, operation)
            if existing:
                if existing['signature'] != signature:
                    raise ChatConflict('同一操作不能修改对话内容')
                return envelope(operation, existing['state'], result=json.loads(existing['result']) if existing['result'] else None,
                                code=existing['error_code'])
            stamp = now()
            c.execute('INSERT INTO '+TABLE+'(id,signature,request,session_id,state,settings,profile_revision,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',
                      (operation, signature, packed(copy.deepcopy(value)), target, 'accepted', packed(settings),
                       str(profile.get('revision', '')) if isinstance(profile, dict) else '', stamp, stamp))
        emit_lifecycle(operation,'accepted',session_id=target)
        return envelope(operation, 'accepted')

    def resolve(self, operation, value):
        """Atomically seal absent legacy commands so late arrivals cannot run."""
        operation = identity(operation)
        request = value.get('request') if isinstance(value, dict) else None
        expected, signature = self.request(request)
        if expected != operation:
            raise ChatConflict('核对请求与原操作身份不一致')
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            previous = c.execute('SELECT signature,result FROM easel_chat_operations WHERE id=?', (operation,)).fetchone()
            intent = row(c, operation)
            if previous:
                if previous['signature'] != signature:
                    raise ChatConflict('同一操作不能修改对话内容')
                return envelope(operation, 'completed', result=json.loads(previous['result']))
            if intent:
                if intent['signature'] != signature:
                    raise ChatConflict('同一操作不能修改对话内容')
                return envelope(operation, intent['state'], result=json.loads(intent['result']) if intent['result'] else None,
                                code=intent['error_code'])
            stamp = now()
            c.execute('INSERT INTO '+TABLE+'(id,signature,request,state,error_code,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',
                      (operation, signature, packed(request), 'sealed_not_accepted', 'legacy_create_not_accepted', stamp, stamp))
        emit_lifecycle(operation,'sealed_not_accepted')
        return envelope(operation, 'sealed_not_accepted', code='legacy_create_not_accepted')

    def _running(self, operation):
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            intent = row(c, operation)
            if not intent or intent['state'] not in ACTIVE:
                return None
            c.execute('UPDATE '+TABLE+" SET state='running',owner_pid=?,updated_at=? WHERE id=?", (os.getpid(), now(), operation))
        emit_lifecycle(operation,'running',session_id=intent['session_id'])
        return json.loads(intent['request'])

    def _reject(self, operation, error):
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            receipt = read_receipt(c, operation)
            if receipt['operation_state'] == 'completed':
                return
            # This worker only creates metadata. A rolled-back command cannot
            # have started a model, publication, or another side effect.
            c.execute('UPDATE '+TABLE+" SET state='rejected',error_code=?,error_type=?,updated_at=? WHERE id=? AND state IN ('accepted','running')",
                      ('session_creation_rejected', type(error).__name__, now(), operation))
        emit_lifecycle(operation,'rejected',error_type=type(error).__name__)

    async def _process(self, operation):
        try:
            value = await run_sync(self._running, operation)
            if value is not None:
                await run_sync(self.chat.create_session, value)
        except Exception as error:
            try:
                await run_sync(self._reject, operation, error)
            except Exception:
                # Unavailable storage is not evidence of rejection. The durable
                # accepted row remains for restart recovery/diagnostics.
                pass

    def _kick(self, operation):
        if self.closing or operation in self.tasks:
            return
        task = asyncio.create_task(self._process(operation))
        self.tasks[operation] = task
        task.add_done_callback(lambda done: self.tasks.pop(operation, None) if self.tasks.get(operation) is done else None)

    async def receive(self, value, validate_profile, *, timeout=1.0):
        self.loop=asyncio.get_running_loop()
        receipt = await run_sync(self.accept, value, validate_profile)
        operation = receipt['operation_id']
        if receipt['operation_state'] in ACTIVE:
            self._kick(operation)
            task = self.tasks.get(operation)
            if task is not None:
                # Waiting for the HTTP response must never cancel accepted work.
                await asyncio.wait({task}, timeout=timeout)
            receipt = await run_sync(self.inspect, operation)
        return receipt

    def _recoverable(self):
        with self.store.connect() as c:
            active = [r[0] for r in c.execute('SELECT id FROM '+TABLE+" WHERE state IN ('accepted','running')")]
            projections = [tuple(r) for r in c.execute('SELECT id,session_id FROM '+TABLE+" WHERE state='completed' AND projection_error IS NOT NULL")]
        return active, projections

    def _repair_projection(self, operation, session_id):
        try:
            self.chat._save_metadata(session_id)
            with self.store.connect() as c:
                projection(c, operation, None)
        except Exception:
            return False
        emit_lifecycle(operation,'projection_repaired',session_id=session_id)
        return True

    async def _retry_projection(self, operation, session_id):
        for delay in self.projection_delays:
            await asyncio.sleep(delay)
            if self.closing:return
            if await run_sync(self._repair_projection,operation,session_id):return

    def _schedule_projection(self, operation, session_id):
        if self.closing or operation in self.projection_tasks:return
        task=asyncio.create_task(self._retry_projection(operation,session_id))
        self.projection_tasks[operation]=task
        task.add_done_callback(lambda done:self.projection_tasks.pop(operation,None) if self.projection_tasks.get(operation) is done else None)

    def projection_failed(self, operation, signature, request, result, settings, error_type):
        session_id=result['session']['id'];stamp=now()
        # Legacy direct callers may have a completed business receipt but no
        # intake row. Add only a completed projection marker, never new work.
        with self.store.connect() as c:
            c.execute('INSERT INTO '+TABLE+'(id,signature,request,session_id,state,settings,result,created_at,updated_at,projection_error) VALUES(?,?,?,?,?,?,?,?,?,?) '
                      'ON CONFLICT(id) DO UPDATE SET projection_error=excluded.projection_error,updated_at=excluded.updated_at',
                      (operation,signature,packed(request),session_id,'completed',packed(settings),packed(result),stamp,stamp,error_type))
        emit_lifecycle(operation,'projection_failed',session_id=session_id,error_type=error_type)
        try:loop=self.loop or asyncio.get_running_loop()
        except RuntimeError:return
        if not loop.is_closed():loop.call_soon_threadsafe(self._schedule_projection,operation,session_id)

    async def start(self):
        self.loop=asyncio.get_running_loop()
        self.closing = False
        active, projections = await run_sync(self._recoverable)
        for operation in active:
            self._kick(operation)
        for operation, session_id in projections:
            if not await run_sync(self._repair_projection, operation, session_id):
                self._schedule_projection(operation,session_id)

    async def close(self):
        self.closing = True
        for task in list(self.projection_tasks.values()):task.cancel()
        if self.projection_tasks:await asyncio.gather(*list(self.projection_tasks.values()),return_exceptions=True)
        if self.tasks:
            await asyncio.gather(*list(self.tasks.values()), return_exceptions=True)
