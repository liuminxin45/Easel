"""One authenticated, bounded helper lease for automatically authorized checks.

Only poll() returns a check ticket, and only to the anonymous relay capability.
The outbox never stores raw tickets, account data, helper URLs or job reports.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import pathlib
import re
import secrets
import uuid

from easel_workbench.runtime.distribution_runtime import DPAPIVault
from easel_workbench.runtime.toolbox_store import ident, pack

LEASE_SECONDS = 180
TASK_SECONDS = 180
LAUNCH_COOLDOWN_SECONDS = 900
_TOKEN = re.compile(r'[A-Za-z0-9_-]{43}\Z')
_LIVE = {'launch_requested', 'connected'}


class RelayUnauthorized(PermissionError):
    pass


class RelayUnavailable(RuntimeError):
    pass


def _time(value):
    result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('自动检测时间需要时区')
    return result.astimezone(dt.timezone.utc)


def _hash(value):
    return hashlib.sha256(value.encode('ascii')).hexdigest()


class AutoCheckRelay:
    def __init__(self, box, checks, *, clock=None, vault=None, launcher=None, authorizer=None):
        self.box, self.checks = box, checks
        self.store = box.store
        self.root = pathlib.Path(box.root).resolve()
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        self.vault = vault if vault is not None else DPAPIVault(self.root)
        self.launcher = launcher
        # Tests may inject an explicit fixture-only authorization source. The
        # production default independently checks durable monitor authorization.
        self._authorizer = authorizer
        with self.store.connect() as sql:
            sql.executescript('''
CREATE TABLE IF NOT EXISTS distribution_check_relay_state(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distribution_check_relay_leases(id TEXT PRIMARY KEY,ticket_sha256 TEXT NOT NULL,ticket_ref TEXT NOT NULL,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distribution_check_relay_outbox(check_id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS distribution_check_relay_single_lease ON distribution_check_relay_leases((1)) WHERE json_extract(document,'$.phase') IN ('launch_requested','connected');
CREATE UNIQUE INDEX IF NOT EXISTS distribution_check_relay_single_task ON distribution_check_relay_outbox((1)) WHERE json_extract(document,'$.status')='inflight';
''')
            sql.execute('INSERT OR IGNORE INTO distribution_check_relay_state VALUES(?,?)',
                        ('global', pack({'enabled': False, 'last_launch_at': None, 'next_launch_at': None})))

    def _now(self):
        value = self.clock()
        if not isinstance(value, dt.datetime) or value.tzinfo is None:
            raise ValueError('自动检测时钟需要带时区')
        return value.astimezone(dt.timezone.utc)

    def _state(self, sql):
        return json.loads(sql.execute("SELECT document FROM distribution_check_relay_state WHERE id='global'").fetchone()['document'])

    def _save_state(self, sql, state):
        sql.execute("UPDATE distribution_check_relay_state SET document=? WHERE id='global'", (pack(state),))

    def _enabled(self, sql, state):
        if state['enabled'] is not True:
            return False
        try:
            row = sql.execute("SELECT document FROM distribution_check_monitor_state WHERE id='global'").fetchone()
        except Exception:
            return self._authorizer is not None
        return bool(row and json.loads(row['document']).get('enabled') is True)

    def _eligible(self, sql, check_id, ticket=None):
        try:
            ident(check_id)
            if self._authorizer is not None:
                allowed = self._authorizer(check_id)
            else:
                from easel_workbench.runtime.distribution_check_monitor import is_auto_authorized
                allowed = is_auto_authorized(self.box, check_id, clock=self.clock)
            if allowed is not True:
                return None
            row = self.checks._row(sql, check_id, False)
            document = json.loads(row['document']) if row else None
            if not document or document['status'] not in ('pending', 'running') or _time(document['expires_at']) <= self._now():
                return None
        except Exception:
            return None
        # An authorized task with temporarily unavailable DPAPI must stay
        # pending, rather than be silently cancelled as though authorization
        # had been withdrawn. Its caller can retry this read-only recovery.
        try:
            original = self.checks._ticket(row)
        except Exception:
            raise RelayUnavailable('自动检测凭据暂不可恢复') from None
        if ticket is not None and (not isinstance(ticket, str) or not _TOKEN.fullmatch(ticket) or not hmac.compare_digest(ticket, original)):
            return None
        return {'check_id': check_id, 'readonly_ticket': original, 'expires_at': document['expires_at']}

    def _leases(self, sql):
        return [(row, json.loads(row['document'])) for row in sql.execute('SELECT * FROM distribution_check_relay_leases ORDER BY rowid')]

    def _save_lease(self, sql, lease):
        sql.execute('UPDATE distribution_check_relay_leases SET document=? WHERE id=?', (pack(lease), lease['relay_id']))

    def _outbox(self, sql):
        return [json.loads(row['document']) for row in sql.execute('SELECT document FROM distribution_check_relay_outbox ORDER BY rowid')]

    def _save_task(self, sql, task):
        sql.execute('UPDATE distribution_check_relay_outbox SET document=? WHERE check_id=?', (pack(task), task['check_id']))

    def _revoke(self, sql, now, reason='disabled'):
        for _, lease in self._leases(sql):
            if lease['phase'] in _LIVE:
                lease.update(phase='revoked', revoked_at=now.isoformat(), current_check_id=None)
                self._save_lease(sql, lease)
        for task in self._outbox(sql):
            if task['status'] in ('queued', 'inflight'):
                task.update(status='cancelled', finished_at=now.isoformat(), code=reason)
                self._save_task(sql, task)

    def set_generation(self, generation):
        """Server-only helper deployment boundary; never launches or begins jobs.

        A new generation fences old browser code, including a pre-generation
        installation. Repeated factories/processes using the same generation
        leave the current lease and its cooldown unchanged.
        """
        if not isinstance(generation, str) or not re.fullmatch(r'[A-Za-z0-9._-]{1,80}', generation):
            raise ValueError('自动检测辅助页版本无效')
        with self.store.connect() as sql:
            sql.execute('BEGIN IMMEDIATE')
            state = self._state(sql)
            if state.get('helper_generation') != generation:
                self._revoke(sql, self._now(), reason='helper_generation_changed')
                state.update(helper_generation=generation, next_launch_at=None)
                self._save_state(sql, state)
        return self.status()

    def _refresh(self, sql, now):
        for _, lease in self._leases(sql):
            if lease['phase'] in _LIVE and _time(lease['expires_at']) <= now:
                lease.update(phase='expired', current_check_id=None)
                self._save_lease(sql, lease)
        for task in self._outbox(sql):
            if task['status'] not in ('queued', 'inflight'):
                continue
            eligible = self._eligible(sql, task['check_id'])
            deadline = task.get('task_expires_at')
            if eligible and (not deadline or _time(deadline) > now):
                continue
            row = self.checks._row(sql, task['check_id'], False)
            source = json.loads(row['document']) if row else {}
            terminal = source.get('status')
            status = terminal if terminal in ('completed', 'failed', 'expired') else 'expired' if deadline and _time(deadline) <= now else 'cancelled'
            task.update(status=status, finished_at=now.isoformat(), code='no_longer_authorized')
            self._save_task(sql, task)

    def _active(self, sql, now):
        return next(((row, lease) for row, lease in self._leases(sql)
                     if lease['phase'] in _LIVE and _time(lease['expires_at']) > now), None)

    def status(self):
        now = self._now()
        with self.store.connect() as sql:
            state = self._state(sql)
            enabled = self._enabled(sql, state)
            active = self._active(sql, now)
            leases = self._leases(sql)
            latest = leases[-1][1] if leases else None
            queued = any(task['status'] == 'queued' for task in self._outbox(sql))
        if not enabled:
            phase = 'disabled'
        elif active:
            phase = active[1]['phase']
        elif queued and state['next_launch_at'] and _time(state['next_launch_at']) > now:
            phase = 'cooldown'
        elif queued:
            phase = 'queued' if self.launcher is not None else 'not_configured'
        else:
            phase = 'idle'
        return {'phase': phase, 'connected': bool(enabled and active and active[1]['phase'] == 'connected' and active[1].get('confirmed_at')),
                'enabled': enabled, 'last_seen': latest.get('last_seen_at') if latest else None,
                'lease_expires': active[1]['expires_at'] if active else latest.get('expires_at') if latest else None,
                'last_launch_at': state['last_launch_at'], 'next_launch_at': state['next_launch_at']}

    def launch_or_reuse(self, private_receipt):
        if not isinstance(private_receipt, dict):
            return {'status': 'failed', 'code': 'invalid_receipt'}
        check_id, ticket = private_receipt.get('check_id'), private_receipt.get('readonly_ticket')
        with self.store.connect() as sql:
            sql.execute('BEGIN IMMEDIATE')
            now = self._now();self._refresh(sql, now)
            if self._eligible(sql, check_id, ticket) is None or not isinstance(ticket, str) or not _TOKEN.fullmatch(ticket):
                return {'status': 'failed', 'code': 'not_automatically_authorized'}
            old = sql.execute('SELECT document FROM distribution_check_relay_outbox WHERE check_id=?', (check_id,)).fetchone()
            if not old:
                document = {'check_id': check_id, 'status': 'queued', 'queued_at': now.isoformat(),
                            'relay_id': None, 'assigned_at': None, 'task_expires_at': None, 'finished_at': None}
                sql.execute('INSERT INTO distribution_check_relay_outbox VALUES(?,?)', (check_id, pack(document)))
            active = self._active(sql, now)
            enabled = self._enabled(sql, self._state(sql))
            if active and enabled and active[1]['phase'] == 'connected' and active[1].get('confirmed_at'):
                return {'status': 'reused'}
        outcome = self._ensure_launch()
        return outcome or {'status': 'queued'}

    def _ensure_launch(self):
        private = None
        with self.store.connect() as sql:
            sql.execute('BEGIN IMMEDIATE')
            now = self._now();state = self._state(sql);self._refresh(sql, now)
            if not self._enabled(sql, state):
                return None
            if self._active(sql, now):
                return None
            tasks = [task for task in self._outbox(sql) if task['status'] == 'queued']
            if not tasks:
                return None
            if self.launcher is None:
                return {'status': 'queued', 'code': 'not_configured'}
            if state['next_launch_at'] and _time(state['next_launch_at']) > now:
                return {'status': 'queued', 'code': 'launch_cooldown'}
            relay_id, ticket = 'relay-' + uuid.uuid4().hex, secrets.token_urlsafe(32)
            try:
                reference = self.vault.put('auto-relay-' + relay_id, {'ticket': ticket})
            except Exception:
                return {'status': 'failed', 'code': 'credential_store_unavailable'}
            if not isinstance(reference, str) or not re.fullmatch(r'vault:[A-Za-z0-9_-]{1,128}', reference):
                return {'status': 'failed', 'code': 'credential_store_unavailable'}
            lease = {'relay_id': relay_id, 'phase': 'launch_requested', 'created_at': now.isoformat(),
                     'expires_at': (now + dt.timedelta(seconds=LEASE_SECONDS)).isoformat(), 'last_seen_at': None,
                     'confirmed_at': None, 'current_check_id': None}
            sql.execute('INSERT INTO distribution_check_relay_leases VALUES(?,?,?,?)', (relay_id, _hash(ticket), reference, pack(lease)))
            state.update(last_launch_at=now.isoformat(), next_launch_at=(now+dt.timedelta(seconds=LAUNCH_COOLDOWN_SECONDS)).isoformat())
            self._save_state(sql, state)
            private = (relay_id, ticket)
        # A crash after this commit is intentionally an unknown launch. A new
        # process cannot reopen it every tick; only expiry AND cooldown recover.
        try:
            reply = self.launcher(*private)
            if reply is False or isinstance(reply, dict) and reply.get('status') in ('failed', 'not_configured'):
                raise RelayUnavailable('辅助页启动请求未被接受')
        except Exception:
            with self.store.connect() as sql:
                sql.execute('BEGIN IMMEDIATE')
                row = sql.execute('SELECT document FROM distribution_check_relay_leases WHERE id=?', (private[0],)).fetchone()
                current = json.loads(row['document'])
                if current['phase'] == 'launch_requested':
                    current['phase'] = 'launch_failed';self._save_lease(sql, current)
                    return {'status': 'failed', 'code': 'launch_failed'}
                if current['phase'] == 'connected':
                    return {'status': 'reused'}
            return {'status': 'failed', 'code': 'launch_failed'}
        return {'status': 'launch_requested'}

    def maintain(self, enabled):
        if type(enabled) is not bool:
            raise ValueError('自动检测启用状态无效')
        with self.store.connect() as sql:
            sql.execute('BEGIN IMMEDIATE')
            now = self._now();state = self._state(sql);state['enabled'] = enabled;self._save_state(sql, state)
            self._refresh(sql, now)
            if not self._enabled(sql, state):
                self._revoke(sql, now)
        if enabled:
            self._ensure_launch()
        return self.status()

    def _authenticate(self, sql, relay_id, ticket, now):
        valid_id = isinstance(relay_id, str) and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', relay_id)
        row = sql.execute('SELECT * FROM distribution_check_relay_leases WHERE id=?', (relay_id,)).fetchone() if valid_id else None
        shape = isinstance(ticket, str) and _TOKEN.fullmatch(ticket)
        candidate = _hash(ticket) if shape else '0'*64
        expected = row['ticket_sha256'] if row else 'f'*64
        matched = hmac.compare_digest(candidate, expected)
        lease = json.loads(row['document']) if row else None
        if not matched or not shape or not lease or lease['phase'] not in _LIVE or _time(lease['expires_at']) <= now:
            raise RelayUnauthorized('自动检测辅助页授权无效或已过期')
        return lease

    def poll(self, relay_id, ticket, current_check_id=None):
        if current_check_id is not None:
            ident(current_check_id)
        denied = False
        with self.store.connect() as sql:
            sql.execute('BEGIN IMMEDIATE')
            now = self._now();lease = self._authenticate(sql, relay_id, ticket, now)
            state = self._state(sql)
            if not self._enabled(sql, state):
                self._revoke(sql, now);denied = True
            else:
                self._refresh(sql, now)
                lease.update(phase='connected', confirmed_at=lease.get('confirmed_at') or now.isoformat(),
                             last_seen_at=now.isoformat(), expires_at=(now+dt.timedelta(seconds=LEASE_SECONDS)).isoformat())
                tasks = self._outbox(sql)
                current = next((task for task in tasks if task['status']=='inflight' and task.get('relay_id')==relay_id), None)
                if current is None:
                    current = next((task for task in tasks if task['status']=='queued'), None)
                    if current:
                        receipt = self._eligible(sql, current['check_id'])
                        if receipt:
                            deadline = min(_time(receipt['expires_at']), now+dt.timedelta(seconds=TASK_SECONDS))
                            current.update(status='inflight', relay_id=relay_id, assigned_at=now.isoformat(), task_expires_at=deadline.isoformat())
                            self._save_task(sql, current)
                        else:
                            current = None
                task = None
                if current:
                    receipt = self._eligible(sql, current['check_id'])
                    if receipt:
                        task = {key: receipt[key] for key in ('check_id', 'readonly_ticket')}
                lease['current_check_id'] = task['check_id'] if task else None
                self._save_lease(sql, lease)
                response = {'accepted': True, 'enabled': True, 'lease_expires': lease['expires_at'],
                            'poll_after_seconds': 15, 'task': task}
        if denied:
            raise RelayUnauthorized('自动检测辅助页授权无效或已过期')
        return response
