"""Durable bounded retries for positively unsent production requests.

The dispatch_started marker remains the authority. This ledger cannot turn an
unknown write into a new send, and initialization never queues historical errors.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import uuid

from easel_workbench.runtime.studio_service import StudioConflict
from easel_workbench.runtime.toolbox_store import ident, pack


DELAYS = (30, 60, 120)
MAX_AUTO_RETRIES = 3
AUTOMATIC_KINDS = {'create', 'change'}
MESSAGES = {
    'codex_target_unavailable': '固定 Codex 制作会话暂不可用，制作尚未发送。',
    'codex_connection_unavailable': '连接 Codex 失败，制作尚未发送。',
    'codex_timeout': '连接 Codex 超时，制作尚未发送。',
    'codex_not_sent': '请求未写入 Codex，制作尚未发送。',
    'codex_request_rejected': 'Codex 未接受发送准备请求，制作尚未发送。',
    'codex_configuration_invalid': 'Codex 制作连接设置需要核对，制作尚未发送。',
    'input_unavailable': '本次冻结输入或附件无法读取，请核对素材文件。',
    'submission_unknown': '已开始向 Codex 提交，结果尚未确认；正在核对原任务。',
    'codex_send_failed': '发送到 Codex 失败，制作尚未发送。',
}


def clock_now(value=None):
    value = value() if callable(value) else value
    value = value or dt.datetime.now(dt.timezone.utc)
    if not isinstance(value, dt.datetime) or value.tzinfo is None:
        raise ValueError('重试时钟需要明确时区')
    return value.astimezone(dt.timezone.utc)


def _time(value):
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('重试时间需要明确时区')
    return parsed.astimezone(dt.timezone.utc)


def initialize(connection):
    connection.executescript('''
CREATE TABLE IF NOT EXISTS toolbox_dispatch_retries(job_id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_dispatch_retry_operations(operation_id TEXT PRIMARY KEY,job_id TEXT NOT NULL,signature TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL);
''')


def read(connection, jid):
    if connection is None:
        return None
    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='toolbox_dispatch_retries'").fetchone():
        return None
    row = connection.execute('SELECT document FROM toolbox_dispatch_retries WHERE job_id=?', (jid,)).fetchone()
    return json.loads(row[0]) if row else None


def _new(job, at):
    return {'job_id': job['id'], 'cycle': 1, 'revision': 0, 'attempt_count': 0, 'auto_retry_count': 0,
            'automatic_enabled': job['kind'] in AUTOMATIC_KINDS, 'next_retry_at': None, 'retry_exhausted': False,
            'phase': 'idle', 'error_code': None, 'inputs': None,
            'job_signature': hashlib.sha256(job.get('signature', '').encode()).hexdigest(),
            'created_at': at.isoformat(), 'updated_at': at.isoformat(), 'history': []}


def _save(connection, state, event, at, **fields):
    state['revision'] += 1
    state['updated_at'] = at.isoformat()
    state['history'].append({'event': event, 'at': at.isoformat(), 'cycle': state['cycle'],
                             'attempt_count': state['attempt_count'], **fields})
    connection.execute('INSERT OR REPLACE INTO toolbox_dispatch_retries VALUES(?,?)', (state['job_id'], pack(state)))


def due(connection, job, at=None):
    state = read(connection, job['id'])
    if not state or not state.get('next_retry_at'):
        return True
    return _time(state['next_retry_at']) <= clock_now(at)


def begin_attempt(connection, job, at=None):
    """Reserve before setup; even a crashed attempt keeps its consumed allowance."""
    at = clock_now(at)
    fresh = connection.execute('SELECT * FROM toolbox_jobs WHERE id=?', (job['id'],)).fetchone()
    if not fresh or fresh['dispatch_started'] or fresh['status'] not in ('queued', 'dispatching'):
        return False
    state = read(connection, job['id']) or _new(dict(fresh), at)
    if state.get('next_retry_at') and _time(state['next_retry_at']) > at:
        return False
    if state['attempt_count'] and not state['automatic_enabled']:
        unsent_failure(connection,dict(fresh),'codex_connection_unavailable',automatic=False,at=at)
        return False
    if state['attempt_count'] >= 1 + MAX_AUTO_RETRIES:
        unsent_failure(connection,dict(fresh),'codex_connection_unavailable',at=at)
        return False
    state.update(attempt_count=state['attempt_count'] + 1, next_retry_at=None, phase='sending',attempt_token=uuid.uuid4().hex)
    state['auto_retry_count'] = min(MAX_AUTO_RETRIES, max(0, state['attempt_count'] - 1))
    _save(connection, state, 'attempt_started', at)
    connection.execute("UPDATE toolbox_jobs SET status='dispatching',finished_at=NULL WHERE id=?", (job['id'],))
    return state['attempt_token']


def frozen_inputs(connection, job, inputs=None, at=None):
    state = read(connection, job['id'])
    if state and state.get('inputs') is not None:
        if state['job_signature'] != hashlib.sha256(job.get('signature', '').encode()).hexdigest():
            raise StudioConflict('原任务输入已变化，不能重新发送')
        return copy.deepcopy(state['inputs'])
    if inputs is not None and state:
        state['inputs'] = copy.deepcopy(inputs)
        state['input_hash'] = hashlib.sha256(pack(inputs).encode()).hexdigest()
        _save(connection, state, 'input_frozen', clock_now(at))
    return copy.deepcopy(inputs)


def unsent_failure(connection, job, code, *, automatic=True, at=None):
    at = clock_now(at)
    fresh = connection.execute('SELECT * FROM toolbox_jobs WHERE id=?', (job['id'],)).fetchone()
    if not fresh or fresh['dispatch_started'] or fresh['queue_id'] or fresh['turn_id']:
        raise StudioConflict('已有发送记录，不能自动重新发送')
    state = read(connection, job['id']) or _new(dict(fresh), at)
    code = code if code in MESSAGES else 'codex_send_failed'
    state['error_code'] = code
    enabled = bool(automatic and state['automatic_enabled'] and state['attempt_count'] <= MAX_AUTO_RETRIES)
    state['retry_exhausted'] = bool(automatic and state['automatic_enabled'] and state['attempt_count'] > MAX_AUTO_RETRIES)
    state.update(phase='retry_wait' if enabled else 'exhausted' if state['retry_exhausted'] else 'failed',
                 next_retry_at=(at + dt.timedelta(seconds=DELAYS[max(0, state['attempt_count'] - 1)])).isoformat() if enabled else None)
    _save(connection, state, 'unsent_failure', at, error_code=code, next_retry_at=state['next_retry_at'])
    connection.execute('UPDATE toolbox_jobs SET status=?,error=?,finished_at=? WHERE id=?',
        ('queued' if enabled else 'error', MESSAGES[code], None if enabled else at.isoformat(), job['id']))
    if state['retry_exhausted']:
        connection.execute('INSERT OR IGNORE INTO notification_events(event_key,kind,status,article_id,task_id) VALUES(?,?,?,?,?)',
            ('toolbox-dispatch:'+job['id']+':cycle:'+str(state['cycle']),'toolbox','error',None,job['id']))


def submitted(connection, jid, *, unknown=False, at=None):
    state = read(connection, jid)
    if state:
        state.update(phase='unknown' if unknown else 'submitted', next_retry_at=None, retry_exhausted=False,
                     error_code='submission_unknown' if unknown else None)
        _save(connection, state, 'submission_unknown' if unknown else 'submitted', clock_now(at))


def recovery(job, connection, *, outcome=None, now=None):
    """Read-only public view. No prompts, raw errors, markers or private inputs."""
    if not job:
        return None
    job = dict(job)
    status = job.get('status')
    if status == 'completed' and not (outcome and outcome.get('status') in ('blocked', 'error')):
        return None
    at = clock_now(now)
    state = read(connection, job['id']) or {}
    sent = bool(job.get('dispatch_started') or job.get('queue_id') or job.get('turn_id'))
    code = state.get('error_code')
    production = bool(outcome and outcome.get('status') in ('blocked', 'error') or sent and status in ('blocked', 'error') and job.get('turn_id') and job.get('finished_at'))
    uncertain = status in ('uncertain', 'needs_desktop', 'parked') or sent and status in ('blocked','error') and not production
    input_failed = not sent and status == 'error' and code == 'input_unavailable'
    if uncertain:
        kind, send_state, phase, action = 'uncertain', 'unknown', 'unknown', 'reconcile'
        code, message = 'submission_unknown', MESSAGES['submission_unknown']
        if status in ('error','blocked'):
            message='已开始向 Codex 提交，结果尚未确认；请核对原任务。'
    elif production or input_failed:
        kind, send_state, phase, action = 'production', 'submitted' if sent else 'not_sent', 'production_failed', 'edit_materials'
        code = (outcome or {}).get('code') or code or 'production_incomplete'
        message = (outcome or {}).get('message') or '制作或交付未完成，请查看制作说明。'
    elif sent:
        kind, send_state, phase, action, code, message = 'dispatch', 'submitted', 'submitted', None, None, '已交给 Codex，等待原任务完成。'
    else:
        kind, send_state = 'dispatch', 'not_sent'
        waiting = status == 'queued' and bool(state.get('next_retry_at'))
        phase = 'retry_wait' if waiting else 'exhausted' if status == 'error' and state.get('retry_exhausted') else 'failed' if status == 'error' else 'sending' if status == 'dispatching' else 'idle'
        action = 'resend' if phase in ('retry_wait', 'failed', 'exhausted') else None
        code = code or ('codex_send_failed' if status == 'error' else None)
        message = MESSAGES.get(code, '正在连接 Codex。' if phase == 'sending' else '等待发送到 Codex。')
    from .native_continuation import continuation
    followup=continuation(connection,job) if production else None
    return {'can_continue':bool(followup),'continuation':followup,'job_id': job['id'], 'failure_kind': kind, 'send_state': send_state, 'phase': phase, 'status': phase,
            'can_retry': not sent and not input_failed and (status == 'error' or phase == 'retry_wait'),
            'attempt_count': state.get('attempt_count', 0), 'auto_retry_count': state.get('auto_retry_count', 0),
            'max_auto_retries': MAX_AUTO_RETRIES, 'next_retry_at': state.get('next_retry_at') if phase == 'retry_wait' else None,
            'retry_exhausted': bool(state.get('retry_exhausted')), 'revision': state.get('revision', 0),
            'server_now': at.isoformat(), 'automatic_enabled': bool(state.get('automatic_enabled', False)),
            'action': action, 'error_code': code, 'message': message}


def manual_retry(box, jid, operation_id=None, expected_retry_revision=None):
    ident(jid)
    explicit = operation_id is not None
    operation = ident(operation_id) if explicit else 'legacy-retry-' + hashlib.sha256(jid.encode()).hexdigest()
    if explicit and (type(expected_retry_revision) is not int or expected_retry_revision < 0):
        raise ValueError('重试需要当前恢复修订号')
    signature = hashlib.sha256(pack({'job_id': jid, 'expected_retry_revision': expected_retry_revision}).encode()).hexdigest()
    with box.store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        old = c.execute('SELECT * FROM toolbox_dispatch_retry_operations WHERE operation_id=?', (operation,)).fetchone()
        if old:
            if old['job_id'] != jid or old['signature'] != signature:
                raise StudioConflict('同一重试操作不能覆盖不同请求')
            return json.loads(old['result'])
        row = c.execute('SELECT * FROM toolbox_jobs WHERE id=?', (jid,)).fetchone()
        if not row:
            raise ValueError('任务不存在')
        job = dict(row)
        safe = recovery(job, c)
        state = read(c, jid)
        revision = state['revision'] if state else 0
        if explicit and expected_retry_revision != revision:
            raise StudioConflict('任务恢复状态已变化，请刷新后核对')
        if job['dispatch_started'] or job['queue_id'] or job['turn_id']:
            raise ValueError('已发送或结果不明的任务不能重新发送，请核对原任务')
        if job['status'] == 'error' and safe['can_retry']:
            at = clock_now()
            if state:
                state.update(cycle=state['cycle'] + 1, attempt_count=0, auto_retry_count=0, next_retry_at=None,
                             retry_exhausted=False, phase='idle', error_code=None,attempt_token=None)
            else:
                state = _new(job, at)
            _save(c, state, 'manual_retry', at, operation_id=operation)
            c.execute("UPDATE toolbox_jobs SET status='queued',error=NULL,finished_at=NULL WHERE id=?", (jid,))
        elif job['status'] == 'queued' and state and state.get('next_retry_at'):
            state['next_retry_at'] = clock_now().isoformat()
            _save(c, state, 'retry_expedited', clock_now(), operation_id=operation)
        elif job['status'] != 'queued':
            raise ValueError('此任务不能重试发送，请查看实际制作或输入问题')
        row = dict(c.execute('SELECT * FROM toolbox_jobs WHERE id=?', (jid,)).fetchone())
        projected = {key: row[key] for key in ('id', 'work_id', 'kind', 'status', 'turn_id', 'created_at', 'error')}
        projected['recovery'] = recovery(row, c)
        result = {**projected, 'operation_id': operation, 'job': projected, 'recovery': projected['recovery'],
                  'result': {'job': projected, 'recovery': projected['recovery']}}
        c.execute('INSERT INTO toolbox_dispatch_retry_operations VALUES(?,?,?,?,?)', (operation, jid, signature, pack(result), clock_now().isoformat()))
        return result
