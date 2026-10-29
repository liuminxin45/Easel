"""Durable scheduling for read-only account checks, independent of phone tabs.

The runtime must maintain one short-leased helper page and enqueue each check
for that page. This engine does not open browsers, import accounts or publish.
It reserves every launch durably before the runtime call and never replays an
uncertain launch. Only the existing CheckService handles report tickets/results.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import json
import re
import sqlite3
import uuid

from easel_workbench.runtime.distribution_checks import CheckService, PLATFORMS, _plain_text
from easel_workbench.runtime.distribution_catalog import IMPORTABLE_PROVIDERS, identity_metadata
from easel_workbench.runtime.distribution_service import DistributionConflict
from easel_workbench.runtime.toolbox_store import ident, pack


SUCCESS_INTERVAL = 300
BACKOFF_SECONDS = (15, 45, 120, 300, 900)
ACTIVE_CHECK_STATES = {'pending', 'running'}
RUNTIME_STATES = {'unknown', 'ready', 'active', 'idle', 'disabled', 'offline', 'expired', 'connected',
    'waiting_helper', 'waiting_browser', 'launch_requested', 'cooldown', 'queued', 'reused', 'failed',
    'not_configured', 'not_installed', 'needs_pairing', 'helper_online', 'helper_offline', 'unavailable'}
MESSAGES = {
    'scheduled': '等待后台开始只读账号检测。',
    'launch_requested': '后台已请求电脑执行本轮只读检测。',
    'page_ready': '自动检测辅助页已就绪。',
    'extension_started': '正在读取同步助手中的登录账号。',
    'launch_uncertain': '本轮启动回执待核对，正在等待原检测结果。',
    'recovering': '正在恢复原检测任务，没有重新打开浏览器页面。',
    'waiting_next': '本轮检测完成，后台会按计划刷新。',
    'retry_wait': '本轮检测未完成，后台将自动重试。',
    'disabled': '自动检测已暂停，最近成功结果仍保留。',
}
ERROR_MESSAGES = {
    'check_expired': '本轮只读检测已过期。',
    'launch_failed': '电脑辅助页未能接收本轮检测。',
    'launch_uncertain': '启动回执暂不明确，保留原检测等待结果。',
    'check_begin_unavailable': '本轮检测凭据暂不可恢复，稍后继续核对原操作。',
    'check_status_unavailable': '原检测状态暂不可读取，稍后继续核对。',
    'invalid_check_result': '本轮没有取得可核对的观察结果。',
    'extension_unavailable': '电脑暂未检测到同步助手。',
    'extension_timeout': '同步助手暂未返回检测结果。',
    'extension_failed': '同步助手账号读取未完成。',
    'invalid_response': '同步助手返回的账号结果暂不可核对。',
    'network_error': '检测页与后台连接暂不可用。',
    'page_failed': '电脑检测页未完成本轮操作。',
    'unknown': '本轮只读账号检测未完成。',
}


class MonitorConflict(DistributionConflict):
    pass


class LeaseLost(RuntimeError):
    pass


def _now(clock=None):
    result = clock() if clock else dt.datetime.now(dt.timezone.utc)
    if not isinstance(result, dt.datetime) or result.tzinfo is None:
        raise ValueError('自动检测时钟需要明确时区')
    return result.astimezone(dt.timezone.utc)


def _time(value):
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('自动检测时间需要明确时区')
    return parsed.astimezone(dt.timezone.utc)


def _expired(value, now):
    try:
        return _time(value) <= now
    except (TypeError, ValueError, AttributeError):
        return True


def is_auto_authorized(box, check_id, *, clock=None):
    """Server-only relay guard. Manual CheckService.begin is never sufficient."""
    try:
        ident(check_id)
        now = _now(clock)
        with box.store.connect() as c:
            c.execute('BEGIN')
            if len(list(c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name IN ('distribution_check_monitor_state','distribution_check_monitor_authorizations','distribution_checks')"))) != 3:
                return False
            row = c.execute("SELECT document FROM distribution_check_monitor_state WHERE id='global'").fetchone()
            authorization = c.execute('SELECT * FROM distribution_check_monitor_authorizations WHERE check_id=?', (check_id,)).fetchone()
            check = c.execute('SELECT document FROM distribution_checks WHERE id=?', (check_id,)).fetchone()
        if not row or not authorization or not check:
            return False
        state = json.loads(row['document'])
        job = json.loads(check['document'])
        return bool(state.get('enabled') is True and state.get('current_check_id') == check_id
            and state.get('current_operation_id') == authorization['operation_id']
            and state.get('monitor_epoch') == authorization['monitor_epoch']
            and state.get('authorization_revision') == authorization['authorization_revision']
            and job.get('status') in ACTIVE_CHECK_STATES and not _expired(job.get('expires_at'), now)
            and not _expired(authorization['expires_at'], now))
    except (ValueError, TypeError, KeyError, AttributeError, OSError, sqlite3.Error):
        return False


def _observation(value):
    if not isinstance(value, dict) or value.get('source') != 'browser_extension' or not isinstance(value.get('accounts'), list):
        return None
    accounts = []
    for row in value['accounts'][:100]:
        if not isinstance(row, dict):
            continue
        platform, account = row.get('platform'), row.get('account')
        if not isinstance(platform, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', platform) or _plain_text(account) is None:
            continue
        name = PLATFORMS.get(platform) or _plain_text(row.get('name')) or platform
        accounts.append({'platform': platform, 'account': account, 'name': name, 'reported_authenticated': True,
                         'verified': False, 'can_import': platform in IMPORTABLE_PROVIDERS and bool(account.strip()), **identity_metadata(row)})
    return {'status': 'observed', 'source': 'browser_extension', 'check_id': value.get('check_id'),
            'accounts': accounts, 'checked_at': value.get('checked_at'), 'verified': False}


def _check(value):
    if not isinstance(value, dict) or not isinstance(value.get('check_id'), str):
        raise ValueError('检测状态格式无效')
    result = {key: copy.deepcopy(value.get(key)) for key in ('check_id', 'status', 'phase', 'created_at', 'updated_at', 'expires_at',
        'completed_at', 'page_ready_at', 'extension_started_at', 'result_received_at', 'failed_at', 'last_event_at', 'observation_id', 'error_code')}
    ident(result['check_id'])
    if result['status'] not in {'pending', 'running', 'completed', 'failed', 'expired'}:
        raise ValueError('检测状态格式无效')
    result['observation'] = _observation(value.get('observation'))
    result['verified'] = False
    return result


class CheckMonitor:
    def __init__(self, box, runtime=None, *, checks=None, clock=None):
        self.box, self.store = box, box.store
        self.runtime = runtime
        self.clock = clock
        self.checks = checks if checks is not None else CheckService(box, clock=clock)
        at = _now(clock).isoformat()
        document = {'enabled': True, 'phase': 'scheduled', 'monitor_epoch': uuid.uuid4().hex, 'authorization_revision': 1,
            'settings_revision': 1, 'success_interval_seconds': SUCCESS_INTERVAL, 'cycle': 0,
            'current_check_id': None, 'current_operation_id': None, 'current_check': None, 'launch_state': None,
            'last_check_id': None, 'last_check_at': None, 'last_finished_at': None, 'last_success_at': None,
            'last_success_observation': None, 'last_check': None, 'next_check_at': at, 'retry_count': 0,
            'last_error': None, 'created_at': at, 'updated_at': at, 'runtime': {'status': 'unknown'}}
        with self.store.connect() as c:
            c.executescript('''
CREATE TABLE IF NOT EXISTS distribution_check_monitor_state(id TEXT PRIMARY KEY,document TEXT NOT NULL,lease_owner TEXT,lease_token TEXT,lease_until TEXT,heartbeat_at TEXT);
CREATE TABLE IF NOT EXISTS distribution_check_monitor_operations(operation_id TEXT PRIMARY KEY,signature TEXT NOT NULL,actor TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distribution_check_monitor_authorizations(check_id TEXT PRIMARY KEY,operation_id TEXT NOT NULL,monitor_epoch TEXT NOT NULL,authorization_revision INTEGER NOT NULL,created_at TEXT NOT NULL,expires_at TEXT NOT NULL);
''')
            c.execute("INSERT OR IGNORE INTO distribution_check_monitor_state VALUES('global',?,NULL,NULL,NULL,NULL)", (pack(document),))

    def _read(self, c):
        row = c.execute("SELECT * FROM distribution_check_monitor_state WHERE id='global'").fetchone()
        return row, json.loads(row['document'])

    @staticmethod
    def _save(c, state):
        c.execute("UPDATE distribution_check_monitor_state SET document=? WHERE id='global'", (pack(state),))

    def _runtime_status(self):
        fallback = {'status': 'not_configured' if self.runtime is None else 'unknown'}
        method = getattr(self.runtime, 'status', None)
        if not callable(method):
            return fallback
        try:
            supplied = method()
            if not isinstance(supplied, dict):
                return fallback
            result = {}
            for key in ('status', 'state', 'phase'):
                if supplied.get(key) in RUNTIME_STATES:
                    result[key] = supplied[key]
            if 'status' not in result and 'phase' in result:
                result['status'] = result['phase']
            for key in ('enabled', 'connected', 'helper_live', 'helper_online'):
                if type(supplied.get(key)) is bool:
                    result[key] = supplied[key]
            aliases = {'last_seen': 'last_seen_at', 'lease_expires': 'lease_until'}
            for key in ('heartbeat_at', 'last_seen_at', 'lease_until', 'helper_lease_until', 'last_launch_at', 'launch_cooldown_until',
                        'next_launch_at', 'last_seen', 'lease_expires'):
                value = supplied.get(key)
                if isinstance(value, str):
                    try:
                        target = aliases.get(key, key)
                        if target not in result:
                            result[target] = _time(value).isoformat()
                    except ValueError:
                        pass
            for key in ('pending_count', 'queued_count'):
                if type(supplied.get(key)) is int and 0 <= supplied[key] <= 10000:
                    result[key] = supplied[key]
            return result or fallback
        except Exception:
            return fallback

    def _public(self, row, state, runtime=None):
        now = _now(self.clock)
        result = {key: copy.deepcopy(state.get(key)) for key in ('enabled', 'phase', 'current_check_id', 'current_check', 'last_check_id',
            'last_check_at', 'last_finished_at', 'last_success_at', 'last_success_observation', 'last_check', 'next_check_at',
            'retry_count', 'last_error', 'settings_revision', 'created_at', 'updated_at')}
        online = bool(row['heartbeat_at'] and row['lease_until'] and not _expired(row['lease_until'], now))
        result.update(schema_version=1, server_now=now.isoformat(),
            message=MESSAGES.get(result['phase'], MESSAGES['recovering']),
            error_code=state['last_error']['code'] if state.get('last_error') else None,
            next_retry_at=state.get('next_check_at') if state['phase'] in ('retry_wait', 'recovering') else None,
            retry_allowed=bool(state['enabled'] and not state.get('current_operation_id')),
            settings={'success_interval_seconds': state['success_interval_seconds'], 'backoff_seconds': list(BACKOFF_SECONDS)},
            worker={'id': row['lease_owner'], 'last_seen_at': row['heartbeat_at'], 'lease_until': row['lease_until'], 'online': online,
                'state': 'active' if online and state.get('current_operation_id') else 'idle' if online else 'offline'},
            runtime=copy.deepcopy(runtime if runtime is not None else state.get('runtime', {'status': 'unknown'})))
        return result

    def status(self):
        runtime = self._runtime_status()
        with self.store.connect() as c:
            row, state = self._read(c)
        return self._public(row, state, runtime)

    def _fresh(self, state, now):
        if not state.get('last_success_at') or state.get('last_success_observation') is None:
            return False
        try:
            age = (now - _time(state['last_success_at'])).total_seconds()
            return 0 <= age < state['success_interval_seconds']
        except ValueError:
            return False

    def command(self, value, actor='owner'):
        if actor != 'owner':
            raise PermissionError('自动检测设置仅由工作台所有者修改')
        if not isinstance(value, dict):
            raise ValueError('自动检测命令需要JSON对象')
        value = copy.deepcopy(value)
        operation_id = ident(value.get('operation_id') or value.get('id'))
        value.pop('id', None)
        value['operation_id'] = operation_id
        action = value.get('action')
        fields = {'set-enabled': {'enabled'}, 'settings': {'success_interval_seconds'}, 'ensure': set(), 'check-now': set()}
        if action not in fields or set(value) - ({'operation_id', 'action'} | fields[action]):
            raise ValueError('自动检测命令不接收其他业务操作')
        if action == 'set-enabled' and type(value.get('enabled')) is not bool:
            raise ValueError('自动检测开关无效')
        if action == 'settings' and (type(value.get('success_interval_seconds')) is not int or not 300 <= value['success_interval_seconds'] <= 3600):
            raise ValueError('成功刷新间隔需要为300到3600秒')
        signature = hashlib.sha256(pack({'value': value, 'actor': actor}).encode()).hexdigest()
        runtime = self._runtime_status()
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM distribution_check_monitor_operations WHERE operation_id=?', (operation_id,)).fetchone()
            if old:
                if old['signature'] != signature or old['actor'] != actor:
                    raise MonitorConflict('同一自动检测操作不能覆盖不同内容')
                return json.loads(old['result'])
            row, state = self._read(c)
            now = _now(self.clock)
            active = bool(state.get('current_operation_id'))
            if action == 'set-enabled':
                changed = state['enabled'] != value['enabled']
                if changed:
                    state.update(enabled=value['enabled'], settings_revision=state['settings_revision'] + 1,
                                 authorization_revision=state['authorization_revision'] + 1)
                    if not state['enabled']:
                        state.update(phase='disabled', next_check_at=None)
                    elif not active:
                        state.update(phase='scheduled', next_check_at=now.isoformat())
            elif action == 'settings':
                state.update(success_interval_seconds=value['success_interval_seconds'], settings_revision=state['settings_revision'] + 1)
                if state['enabled'] and not active and state['phase'] == 'waiting_next' and state.get('last_success_at'):
                    state['next_check_at'] = (_time(state['last_success_at']) + dt.timedelta(seconds=state['success_interval_seconds'])).isoformat()
            elif action == 'check-now':
                if not state['enabled']:
                    raise ValueError('请先开启自动检测')
                if not active:
                    state.update(phase='scheduled', next_check_at=now.isoformat())
            elif action == 'ensure' and state['enabled'] and not active and not self._fresh(state, now):
                backing_off = state['phase'] in ('retry_wait', 'recovering') and state.get('next_check_at') and not _expired(state['next_check_at'], now)
                if not backing_off:
                    state.update(phase='scheduled', next_check_at=now.isoformat())
            state.update(updated_at=now.isoformat(), runtime=runtime)
            self._save(c, state)
            result = {'operation_id': operation_id, 'action': action, 'status': 'completed', 'result': self._public(row, state, runtime)}
            c.execute('INSERT INTO distribution_check_monitor_operations VALUES(?,?,?,?,?)', (operation_id, signature, actor, pack(result), now.isoformat()))
        return result

    def _acquire(self, worker_id, lease_seconds):
        ident(worker_id)
        if type(lease_seconds) is not int or not 5 <= lease_seconds <= 120:
            raise ValueError('自动检测执行租约无效')
        now = _now(self.clock)
        token = uuid.uuid4().hex
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row, _ = self._read(c)
            if row['lease_owner'] and row['lease_owner'] != worker_id and row['lease_until'] and not _expired(row['lease_until'], now):
                return None
            c.execute("UPDATE distribution_check_monitor_state SET lease_owner=?,lease_token=?,lease_until=?,heartbeat_at=? WHERE id='global'",
                (worker_id, token, (now + dt.timedelta(seconds=lease_seconds)).isoformat(), now.isoformat()))
        return worker_id, token

    def _change(self, lease, callback):
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row, state = self._read(c)
            now = _now(self.clock)
            if row['lease_owner'] != lease[0] or row['lease_token'] != lease[1] or _expired(row['lease_until'], now):
                raise LeaseLost('自动检测执行租约已转移')
            result = callback(c, state, now)
            state['updated_at'] = now.isoformat()
            self._save(c, state)
            return result

    @staticmethod
    def _error(state, code, now):
        code = code if code in ERROR_MESSAGES else 'unknown'
        state['last_error'] = {'code': code, 'message': ERROR_MESSAGES[code], 'at': now.isoformat()}

    def _failure(self, state, code, now, *, clear=True):
        self._error(state, code, now)
        state['retry_count'] += 1
        delay = BACKOFF_SECONDS[min(state['retry_count'] - 1, len(BACKOFF_SECONDS) - 1)]
        state.update(phase='retry_wait' if state['enabled'] else 'disabled',
                     next_check_at=(now + dt.timedelta(seconds=delay)).isoformat() if state['enabled'] else None)
        if clear:
            state.update(current_check_id=None, current_operation_id=None, current_check=None, launch_state=None)
        else:
            state['phase'] = 'recovering' if state['enabled'] else 'disabled'

    def _apply_check(self, lease, value):
        job = _check(value)
        def apply(c, state, now):
            if state.get('current_check_id') not in (None, job['check_id']):
                raise LeaseLost('自动检测任务已经更新')
            state.update(current_check_id=job['check_id'], current_check=job, last_check_id=job['check_id'],
                         last_check_at=job.get('created_at'))
            if job['status'] == 'completed':
                state.update(last_check=job, last_finished_at=job.get('completed_at') or now.isoformat())
                if job['observation'] is None:
                    self._failure(state, 'invalid_check_result', now)
                else:
                    success_at = job.get('completed_at') or now.isoformat()
                    state.update(last_success_at=success_at, last_success_observation=job['observation'],
                        retry_count=0, last_error=None, phase='waiting_next' if state['enabled'] else 'disabled',
                        next_check_at=(_time(success_at) + dt.timedelta(seconds=state['success_interval_seconds'])).isoformat() if state['enabled'] else None,
                        current_check_id=None, current_operation_id=None, current_check=None, launch_state=None)
            elif job['status'] in ('failed', 'expired'):
                state.update(last_check=job, last_finished_at=job.get('completed_at') or now.isoformat())
                self._failure(state, 'check_expired' if job['status'] == 'expired' else job.get('error_code') or 'unknown', now)
            elif not state['enabled']:
                state['phase'] = 'disabled'
            elif state.get('launch_state') == 'uncertain' and job['phase'] == 'launch_requested':
                state['phase'] = 'launch_uncertain'
            else:
                state['phase'] = job['phase'] if job['phase'] in MESSAGES else 'recovering'
            return bool(state.get('current_check_id'))
        return self._change(lease, apply)

    def _plan(self, lease):
        def plan(c, state, now):
            if state.get('current_check_id'):
                if state['enabled'] and state.get('launch_state') is None:
                    return 'begin', state['current_operation_id']
                return 'poll', state['current_check_id']
            if not state['enabled']:
                state['phase'] = 'disabled'
                return None
            if state.get('next_check_at') and not _expired(state['next_check_at'], now):
                return None
            if not state.get('current_operation_id'):
                state['cycle'] += 1
                state['current_operation_id'] = 'auto-check-' + state['monitor_epoch'] + '-' + str(state['cycle'])
                state.update(phase='launch_requested', next_check_at=None, launch_state=None)
            return 'begin', state['current_operation_id']
        return self._change(lease, plan)

    def _reserve_launch(self, lease, private):
        job = _check(private)
        def reserve(c, state, now):
            if not state['enabled'] or state.get('launch_state') is not None or state.get('current_check_id') != job['check_id']:
                return False
            if not isinstance(private.get('readonly_ticket'), str):
                raise ValueError('原检测凭据暂不可恢复')
            c.execute('INSERT OR REPLACE INTO distribution_check_monitor_authorizations VALUES(?,?,?,?,?,?)',
                (job['check_id'], state['current_operation_id'], state['monitor_epoch'], state['authorization_revision'], now.isoformat(), job['expires_at']))
            state['launch_state'] = 'reserved'
            return True
        return self._change(lease, reserve)

    def authorized_receipt(self, check_id):
        """Server-only DPAPI recovery, exclusively for the current auto check."""
        if not is_auto_authorized(self.box, check_id, clock=self.clock):
            raise PermissionError('本轮自动检测授权已失效')
        with self.store.connect() as c:
            _, state = self._read(c)
            operation_id = state['current_operation_id']
        result = self.checks.begin(operation_id, actor='owner')
        if result.get('check_id') != check_id or not is_auto_authorized(self.box, check_id, clock=self.clock):
            raise PermissionError('本轮自动检测授权已失效')
        return result

    def tick(self, worker_id, lease_seconds=30):
        """One bounded scheduler step; caller owns the independent worker loop."""
        lease = self._acquire(worker_id, lease_seconds)
        if lease is None:
            return self.status()
        try:
            with self.store.connect() as c:
                _, state = self._read(c)
            maintain = getattr(self.runtime, 'maintain', None)
            if callable(maintain):
                try:
                    maintain(state['enabled'])
                except Exception:
                    pass
            plan = self._plan(lease)
            if plan is None:
                return self.status()
            action, key = plan
            if action == 'poll':
                try:
                    self._apply_check(lease, self.checks.status(key))
                except LeaseLost:
                    raise
                except Exception:
                    def unavailable(c, state, now):
                        if state.get('current_check') and _expired(state['current_check'].get('expires_at'), now):
                            state.update(last_check=state['current_check'], last_finished_at=now.isoformat())
                            self._failure(state, 'check_expired', now)
                        else:
                            self._error(state, 'check_status_unavailable', now)
                            state['phase'] = 'recovering' if state['enabled'] else 'disabled'
                    self._change(lease, unavailable)
            else:
                try:
                    private = self.checks.begin(key, actor='owner')
                except Exception:
                    self._change(lease, lambda c, state, now: self._failure(state, 'check_begin_unavailable', now, clear=False))
                    return self.status()
                if not self._apply_check(lease, private):
                    return self.status()
                if self._reserve_launch(lease, private):
                    launch = getattr(self.runtime, 'launch_or_reuse', None)
                    try:
                        result = launch(private) if callable(launch) else {'status': 'failed'}
                    except Exception:
                        result = {'status': 'uncertain'}
                    outcome = result.get('status') if isinstance(result, dict) else None
                    if outcome == 'failed':
                        self.checks.fail_launch(private['check_id'], code='launch_failed')
                    def dispatched(c, state, now):
                        if outcome in ('queued', 'reused', 'launch_requested'):
                            state['launch_state'] = 'submitted'
                        elif outcome == 'failed':
                            state['launch_state'] = 'failed'
                        else:
                            state['launch_state'] = 'uncertain'
                            state['phase'] = 'launch_uncertain'
                            self._error(state, 'launch_uncertain', now)
                    self._change(lease, dispatched)
                    self._apply_check(lease, self.checks.status(private['check_id']))
        except LeaseLost:
            pass
        finally:
            try:
                runtime = self._runtime_status()
                self._change(lease, lambda c, state, now: state.update(runtime=runtime))
            except LeaseLost:
                pass
        return self.status()


# Convenient explicit name for callers that already use CheckService terminology.
CheckMonitorService = CheckMonitor
