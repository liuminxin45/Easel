"""One-use, read-only account observations delegated by an authenticated owner.

The HTTP layer authenticates begin/status/fail_launch and enforces same-origin
reports. A report ticket grants only bounded metadata submission for one check;
it cannot read a job, import an account, open a publisher, or elevate capability.
Only begin()'s server-internal receipt contains a raw ticket. HTTP clients must
receive status(check_id), never that internal receipt.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import hmac
import json
import pathlib
import re
import secrets
import uuid
from urllib.parse import quote

from easel_workbench.runtime.distribution_runtime import DPAPIVault
from easel_workbench.runtime.distribution_service import DistributionConflict
from easel_workbench.runtime.distribution_catalog import PROVIDER_NAMES as PLATFORMS, IMPORTABLE_PROVIDERS, identity_metadata, plain_text as _plain_text
from easel_workbench.runtime.toolbox_store import ident, pack, text


TTL_SECONDS = 180
EVENTS = frozenset({'page_ready', 'extension_started', 'result', 'extension_timeout', 'failed'})
ERROR_CODES = frozenset({'extension_unavailable', 'extension_timeout', 'extension_failed',
    'invalid_response', 'network_error', 'page_failed', 'launch_failed', 'unknown'})
TERMINAL = frozenset({'completed', 'failed', 'expired'})
MESSAGES = {
    'launch_requested': '已请求在电脑打开本次只读检测页。',
    'page_ready': '电脑检测页已就绪。',
    'extension_started': '电脑正在读取同步助手中的登录账号。',
    'result_received': '本次电脑检测结果已保存。',
    'extension_timeout': '同步助手未在本次检测时间内返回结果。',
    'failed': '本次电脑检测未完成，请查看检测阶段后重新发起。',
    'launch_failed': '未能在电脑启动本次检测页。',
    'expired': '本次只读检测已过期，请重新发起。',
}


class CheckConflict(DistributionConflict):
    pass


class CheckUnauthorized(PermissionError):
    """Map to 403; deliberately gives no job or ticket information."""


class CheckExpired(PermissionError):
    """Map to 403/410; no new report is accepted after the fixed deadline."""


class CheckUnavailable(RuntimeError):
    """Map to 503; never substitute a plaintext or process-local ticket store."""


def _canonical(value):
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf8')
    except (TypeError, ValueError, UnicodeError):
        raise ValueError('检测报告格式无效') from None
    if len(raw) > 100000:
        raise ValueError('检测报告过大')
    return raw


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _time(value):
    parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('检测时间需要明确时区')
    return parsed.astimezone(dt.timezone.utc)


def _safe_accounts(rows, ticket):
    """Display safe hints; import eligibility comes solely from the catalog."""
    if not isinstance(rows, list) or len(rows) > 100:
        raise ValueError('检测账号列表格式无效')
    result = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        platform = row.get('type')
        if not isinstance(platform, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', platform):
            continue
        # The official extension includes this local export adapter in the
        # same response. It is not a platform session or logged-in account.
        if platform.lower() == 'zip-download':
            continue
        account = row.get('uid', '')
        if _plain_text(account) is None:
            continue
        if ticket in account or quote(ticket, safe='') in account:
            continue
        key = (platform, account)
        if key in seen:
            continue
        seen.add(key)
        display_name = _plain_text(row.get('displayName'))
        name = PLATFORMS.get(platform) or (display_name.strip() if display_name else '') or platform
        result.append({'platform': platform, 'account': account, 'name': name,
            'reported_authenticated': True, 'verified': False, 'can_import': platform in IMPORTABLE_PROVIDERS and bool(account.strip()), **identity_metadata(row)})
    return result


class CheckService:
    def __init__(self, box, *, vault=None, clock=None):
        self.box = box
        self.store = box.store
        self.root = pathlib.Path(box.root).resolve()
        self.vault = vault if vault is not None else DPAPIVault(self.root)
        self.clock = clock or (lambda: dt.datetime.now(dt.timezone.utc))
        with self.store.connect() as c:
            c.executescript('''
CREATE TABLE IF NOT EXISTS distribution_checks(id TEXT PRIMARY KEY,operation_id TEXT NOT NULL UNIQUE,actor TEXT NOT NULL,ticket_sha256 TEXT NOT NULL,ticket_ref TEXT NOT NULL,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distribution_check_operations(operation_id TEXT PRIMARY KEY,signature TEXT NOT NULL,actor TEXT NOT NULL,check_id TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distribution_check_events(check_id TEXT NOT NULL,event TEXT NOT NULL,signature TEXT NOT NULL,ack TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(check_id,event));
CREATE TABLE IF NOT EXISTS distribution_observations(id TEXT PRIMARY KEY,signature TEXT NOT NULL,document TEXT NOT NULL,created_at TEXT NOT NULL);
''')

    def _now(self):
        result = self.clock()
        if not isinstance(result, dt.datetime) or result.tzinfo is None:
            raise ValueError('检测时钟需要带时区的时间')
        return result.astimezone(dt.timezone.utc)

    def _row(self, c, check_id, required=True):
        row = c.execute('SELECT * FROM distribution_checks WHERE id=?', (ident(check_id),)).fetchone()
        if row is None and required:
            raise ValueError('找不到本次检测')
        return row

    def _save(self, c, document):
        c.execute('UPDATE distribution_checks SET document=? WHERE id=?', (pack(document), document['check_id']))

    def _expire(self, c, document, now):
        if document['status'] not in TERMINAL and _time(document['expires_at']) <= now:
            document.update(status='expired', phase='expired', updated_at=now.isoformat(), completed_at=now.isoformat(),
                            error_code='extension_timeout', message=MESSAGES['expired'])
            self._save(c, document)
        return document

    def _public(self, c, document):
        # The document is constructed exclusively here; credential columns and
        # operation fingerprints are never merged into its client projection.
        result = copy.deepcopy(document)
        result['observation'] = None
        if document.get('observation_id'):
            row = c.execute('SELECT document FROM distribution_observations WHERE id=?', (document['observation_id'],)).fetchone()
            if row:
                result['observation'] = json.loads(row['document'])
        return result

    def _ticket(self, row):
        try:
            secret = self.vault.get(row['ticket_ref'], 'check-' + row['id'])
            ticket = secret.get('ticket') if isinstance(secret, dict) else None
            if not isinstance(ticket, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', ticket) or not hmac.compare_digest(_sha(ticket.encode('ascii')), row['ticket_sha256']):
                raise CheckUnavailable('本次检测凭据无法恢复，请重新发起只读检测')
            return ticket
        except CheckUnavailable:
            raise
        except Exception:
            raise CheckUnavailable('本次检测凭据无法恢复，请重新发起只读检测') from None

    def begin(self, operation_id, actor='owner'):
        """Server-only result: strip readonly_ticket/fresh before public return."""
        operation_id = ident(operation_id)
        actor = text(actor, 200, True)
        if actor.lower() in ('ai', 'assistant', 'system', 'runner', 'automatic'):
            raise ValueError('只读检测需要已登录用户发起')
        signature = _sha(_canonical({'operation_id': operation_id, 'actor': actor, 'action': 'begin-account-check'}))
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM distribution_check_operations WHERE operation_id=?', (operation_id,)).fetchone()
            now = self._now()
            if old:
                if not hmac.compare_digest(old['signature'], signature) or old['actor'] != actor:
                    raise CheckConflict('同一检测操作不能用于不同用户或请求')
                row = self._row(c, old['check_id'])
                document = self._expire(c, json.loads(row['document']), now)
                result = self._public(c, document)
                result['fresh'] = False
                if document['status'] not in TERMINAL:
                    result['readonly_ticket'] = self._ticket(row)
            else:
                check_id = 'check-' + uuid.uuid4().hex
                ticket = secrets.token_urlsafe(32)
                try:
                    reference = self.vault.put('check-' + check_id, {'ticket': ticket})
                except Exception:
                    raise CheckUnavailable('本机加密凭据库暂不可用，未启动电脑检测') from None
                if not isinstance(reference, str) or not re.fullmatch(r'vault:[A-Za-z0-9_-]{1,128}', reference):
                    raise CheckUnavailable('本机加密凭据库返回无效引用，未启动电脑检测')
                document = {'check_id': check_id, 'status': 'pending', 'phase': 'launch_requested',
                    'created_at': now.isoformat(), 'updated_at': now.isoformat(), 'expires_at': (now + dt.timedelta(seconds=TTL_SECONDS)).isoformat(),
                    'completed_at': None, 'page_ready_at': None, 'extension_started_at': None, 'result_received_at': None,
                    'failed_at': None, 'last_event_at': None, 'observation_id': None, 'error_code': None,
                    'verified': False, 'message': MESSAGES['launch_requested']}
                c.execute('INSERT INTO distribution_checks VALUES(?,?,?,?,?,?)',
                    (check_id, operation_id, actor, _sha(ticket.encode('ascii')), reference, pack(document)))
                c.execute('INSERT INTO distribution_check_operations VALUES(?,?,?,?,?)',
                    (operation_id, signature, actor, check_id, now.isoformat()))
                result = self._public(c, document)
                result.update(fresh=True, readonly_ticket=ticket)
        # A browser may be opened only after the job and operation are committed.
        return result

    def status(self, check_id):
        """Authenticated API only. A ticket is deliberately not an argument."""
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = self._row(c, check_id)
            document = self._expire(c, json.loads(row['document']), self._now())
            return self._public(c, document)

    def fail_launch(self, check_id, code='launch_failed'):
        if not isinstance(code, str) or code not in ERROR_CODES:
            raise ValueError('检测失败代码无效')
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = self._row(c, check_id)
            now = self._now()
            document = self._expire(c, json.loads(row['document']), now)
            # Observed page progress wins over a late launcher diagnostic.
            if document['status'] == 'pending' and document['phase'] == 'launch_requested':
                document.update(status='failed', phase='launch_failed', error_code=code, failed_at=now.isoformat(),
                    completed_at=now.isoformat(), updated_at=now.isoformat(), message=MESSAGES['launch_failed'])
                self._save(c, document)
            return self._public(c, document)

    def _authenticate(self, row, ticket):
        shape = isinstance(ticket, str) and re.fullmatch(r'[A-Za-z0-9_-]{43}', ticket)
        candidate = _sha(ticket.encode('ascii')) if shape else '0' * 64
        expected = row['ticket_sha256'] if row is not None else 'f' * 64
        matched = hmac.compare_digest(candidate, expected)
        if row is None or not shape or not matched:
            raise CheckUnauthorized('本次只读检测授权无效')

    @staticmethod
    def _ack(document):
        return {'check_id': document['check_id'], 'accepted': True, 'status': document['status'], 'phase': document['phase']}

    def _write_observation(self, c, document, accounts, now):
        observation_id = 'check-observation-' + document['check_id']
        observation = {'status': 'observed', 'source': 'browser_extension', 'check_id': document['check_id'],
            'accounts': accounts, 'checked_at': now.isoformat(), 'verified': False,
            'message': '本次电脑检测读回的登录观察；注册账号和执行权限仍须用户逐项确认。'}
        signature = _sha(_canonical(accounts))
        c.execute('INSERT INTO distribution_observations VALUES(?,?,?,?)',
            (observation_id, signature, pack(observation), now.isoformat()))
        return observation_id

    def accept(self, check_id, ticket, event, accounts=None, code=None):
        """Public same-origin submission only; never return account metadata."""
        ident(check_id)
        if not isinstance(event, str) or event not in EVENTS:
            raise ValueError('检测事件无效')
        if code is not None and (not isinstance(code, str) or code not in ERROR_CODES):
            raise ValueError('检测失败代码无效')
        if event == 'result':
            if code is not None:
                raise ValueError('完成报告不接收失败代码')
            if not isinstance(accounts, list) or len(accounts) > 100:
                raise ValueError('检测账号列表格式无效')
        elif accounts is not None:
            raise ValueError('此检测事件不接收账号列表')
        elif event in ('page_ready', 'extension_started') and code is not None:
            raise ValueError('进度报告不接收失败代码')
        payload = _canonical({'event': event, 'accounts': accounts, 'code': code})
        signature = _sha(payload)
        expired = False
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            row = self._row(c, check_id, required=False)
            self._authenticate(row, ticket)
            if ticket.encode('ascii') in payload:
                raise ValueError('检测报告不得包含检测凭据')
            document = json.loads(row['document'])
            previous = c.execute('SELECT signature,ack FROM distribution_check_events WHERE check_id=? AND event=?', (check_id, event)).fetchone()
            # A completed identical report is only an acknowledgement replay,
            # including after expiry; it cannot create or change any observation.
            if previous:
                if not hmac.compare_digest(previous['signature'], signature):
                    raise CheckConflict('同一检测事件不能覆盖不同报告')
                return json.loads(previous['ack'])
            now = self._now()
            document = self._expire(c, document, now)
            if document['status'] == 'expired':
                expired = True
            elif document['status'] in TERMINAL:
                raise CheckConflict('本次检测已结束，不能写入另一份报告')
            else:
                at = now.isoformat()
                document.update(last_event_at=at, updated_at=at)
                if event == 'page_ready':
                    document['page_ready_at'] = at
                    if document['phase'] == 'launch_requested':
                        document.update(status='running', phase='page_ready', message=MESSAGES['page_ready'])
                elif event == 'extension_started':
                    document['extension_started_at'] = at
                    document.update(status='running', phase='extension_started', message=MESSAGES['extension_started'])
                elif event == 'result':
                    safe = _safe_accounts(accounts, ticket)
                    document['observation_id'] = self._write_observation(c, document, safe, now)
                    document.update(status='completed', phase='result_received', result_received_at=at,
                        completed_at=at, message=MESSAGES['result_received'])
                else:
                    document.update(status='failed', phase=event, error_code=code or ('extension_timeout' if event == 'extension_timeout' else 'unknown'),
                        failed_at=at, completed_at=at, message=MESSAGES[event])
                self._save(c, document)
                ack = self._ack(document)
                c.execute('INSERT INTO distribution_check_events VALUES(?,?,?,?,?)', (check_id, event, signature, pack(ack), at))
        # Commit the terminal expiry before signaling the rejected late report.
        if expired:
            raise CheckExpired('本次只读检测已过期，请重新发起')
        return ack
