"""Durable, version-bound distribution; this module never invokes a publisher.

Only a separately supplied runtime may attest local/account capabilities or
verify a remote receipt. A committed delivery is an intent, never a receipt.
The existing studio publication is the sole publication/metrics identity.
"""
from __future__ import annotations

import copy
import datetime as dt
import hashlib
import ipaddress
import json
import pathlib
import re
import uuid
from typing import Any, Literal, TypedDict
from urllib.parse import parse_qsl, urlsplit

from easel_workbench.runtime.content_studio import source as version_source
from easel_workbench.runtime.distribution_catalog import PLATFORMS
from easel_workbench.runtime.desk import stamp
from easel_workbench.runtime.studio_service import StudioService, StudioConflict
from easel_workbench.runtime.toolbox_store import ident, pack, text


RemoteState = Literal['draft', 'pending_review', 'published', 'unknown', 'failed']


class Capability(TypedDict, total=False):
    status: Literal['unsupported', 'unknown', 'trial', 'available']
    verified: bool
    code_verified: bool
    account_verified: bool
    account: str
    reason: str
    checked_at: str
    last_checked_at: str


class AssetManifest(TypedDict):
    id: str
    source_id: str
    version_id: str
    name: str
    mime: str
    sha256: str
    size: int


class Revision(TypedDict):
    id: str
    hash: str
    work_id: str
    version_id: str
    publication_id: str
    connection_id: str
    connection_revision: int
    platform: str
    account: str
    content_kind: str
    title: str
    body: str
    source_token: str
    source_fingerprint: str
    source_snapshot: dict[str, Any]
    asset_manifest: list[AssetManifest]
    publication_hash: str
    created_at: str


class RemoteResult(TypedDict, total=False):
    remote_state: RemoteState
    verified: bool
    remote_id: str
    safe_url: str
    account: str
    revision_hash: str
    evidence: list[Any]
    published_at: str
    phase: Literal['pre_send', 'sent']
    error: str


class Connection(TypedDict, total=False):
    id: str
    platform: str
    account: str
    label: str
    secret_ref: str | None
    secret_configured: bool
    enabled: bool
    revision: int
    created_at: str
    updated_at: str
    capabilities: dict[str, Capability]


class Approval(TypedDict):
    id: str
    batch_id: str
    revision_id: str
    revision_hash: str
    connection_id: str
    connection_revision: int
    platform: str
    account: str
    action: Literal['draft', 'publish']
    schedule_at: str | None
    pilot: bool
    actor: str
    approved_at: str
    hash: str


class Delivery(TypedDict, total=False):
    id: str
    dedupe_key: str
    approval_id: str
    batch_id: str
    revision_id: str
    publication_id: str
    work_id: str
    connection_id: str
    account: str
    platform: str
    action: Literal['draft', 'publish']
    schedule_at: str | None
    pilot: bool
    status: Literal['queued', 'leased', 'succeeded', 'failed', 'unknown', 'blocked', 'cancelled']
    remote_state: RemoteState | None
    verified: bool
    attempt_ids: list[str]
    created_at: str
    updated_at: str
    error: str | None
    result: RemoteResult
    blocked_reason: str
    cancel_requested: bool
    dispatch_started_at: str
    publication_projected: bool
    projection_blocked: str
    reconciliations: list[dict[str, Any]]


class Attempt(TypedDict, total=False):
    id: str
    delivery_id: str
    runner_id: str
    lease_token: str
    lease_until: str
    status: Literal['leased', 'succeeded', 'failed', 'unknown', 'cancelled']
    created_at: str
    dispatched_at: str | None
    finished_at: str | None
    result: RemoteResult | None


class Batch(TypedDict, total=False):
    id: str
    actor: str
    created_at: str
    approval_ids: list[str]
    note: str
    status: Literal['approved', 'queued', 'succeeded', 'partial', 'needs_attention', 'cancelled']


class Runner(TypedDict, total=False):
    id: str
    last_seen_at: str
    state: Literal['polling', 'leased', 'idle']
    delivery_id: str
    last_delivery_id: str


TABLES = {'connections', 'revisions', 'approvals', 'deliveries', 'attempts', 'batches', 'runners'}
IMMUTABLE = {'revisions', 'approvals'}
REMOTE_STATES = {'draft', 'pending_review', 'published', 'unknown', 'failed'}
SUCCESS_STATES = {'draft', 'pending_review', 'published'}
SECRET_KEYS = {'password', 'passwd', 'secret', 'token', 'access_token', 'refresh_token', 'api_key', 'apikey', 'cookie', 'cookies', 'authorization', 'credentials'}


class DistributionConflict(StudioConflict):
    pass


def digest(value):
    return hashlib.sha256(pack(value).encode('utf-8')).hexdigest()


def raw_digest(value):
    return hashlib.sha256(value).hexdigest()


def object_id(kind, operation_id):
    """Derived object IDs also fit ident() for maximum-length operation IDs."""
    proposed = kind + '-' + operation_id
    return proposed if len(proposed) <= 128 else kind + '-' + raw_digest(operation_id.encode())


def _now():
    return dt.datetime.now(dt.timezone.utc)


def _iso(value):
    return value.isoformat()


def _time(value):
    if not isinstance(value, str):
        raise ValueError('时间需要带明确时区')
    try:
        result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('时间无效') from None
    if result.tzinfo is None:
        raise ValueError('时间需要带明确时区')
    return result


def safe_url(value):
    """Accept public HTTPS receipt URLs without credential-bearing components."""
    if not isinstance(value, str) or not value or len(value) > 4000 or any(ord(ch) < 33 for ch in value):
        return False
    try:
        parsed = urlsplit(value)
        host = parsed.hostname or ''
        if parsed.scheme != 'https' or not host or parsed.username or parsed.password or parsed.port not in (None, 443):
            return False
        if host in ('localhost',) or host.endswith(('.localhost', '.local', '.internal')) or '.' not in host:
            return False
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            pass
        if any(key.lower() in SECRET_KEYS | {'key', 'code', 'session', 'sessionid'} for key, _ in parse_qsl(parsed.query, keep_blank_values=True)):
            return False
        return '\\' not in value
    except ValueError:
        return False


def _no_secrets(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in SECRET_KEYS:
                raise ValueError('分发记录不接收明文凭据；请使用凭据库引用')
            _no_secrets(item)
    elif isinstance(value, list):
        for item in value:
            _no_secrets(item)


def _public(value):
    result = copy.deepcopy(value)
    if isinstance(result, dict):
        if 'secret_ref' in result:
            result['secret_configured'] = bool(result.pop('secret_ref'))
        result.pop('lease_token', None)
        for key, item in list(result.items()):
            result[key] = _public(item)
    elif isinstance(result, list):
        result = [_public(item) for item in result]
    return result


class DistributionService:
    def __init__(self, box, runtime=None):
        self.box = box
        self.store = box.store
        self.root = pathlib.Path(box.root).resolve()
        self.runtime = runtime
        self.studio = getattr(box, 'studio', None) or StudioService(box)
        with self.store.connect() as c:
            c.executescript('''
CREATE TABLE IF NOT EXISTS distribution_connections(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distribution_revisions(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distribution_approvals(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distribution_deliveries(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distribution_attempts(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distribution_batches(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distribution_runners(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS distribution_operations(operation_id TEXT PRIMARY KEY,signature TEXT NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS distribution_delivery_dedupe ON distribution_deliveries(json_extract(document,'$.dedupe_key'));
CREATE INDEX IF NOT EXISTS distribution_delivery_status ON distribution_deliveries(json_extract(document,'$.status'));
CREATE INDEX IF NOT EXISTS distribution_revision_work ON distribution_revisions(json_extract(document,'$.work_id'));
CREATE TRIGGER IF NOT EXISTS distribution_revision_no_update BEFORE UPDATE ON distribution_revisions BEGIN SELECT RAISE(ABORT,'distribution revisions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS distribution_revision_no_delete BEFORE DELETE ON distribution_revisions BEGIN SELECT RAISE(ABORT,'distribution revisions are immutable'); END;
CREATE TRIGGER IF NOT EXISTS distribution_approval_no_update BEFORE UPDATE ON distribution_approvals BEGIN SELECT RAISE(ABORT,'distribution approvals are immutable'); END;
CREATE TRIGGER IF NOT EXISTS distribution_approval_no_delete BEFORE DELETE ON distribution_approvals BEGIN SELECT RAISE(ABORT,'distribution approvals are immutable'); END;
''')

    def _get(self, c, kind, key, required=True):
        assert kind in TABLES
        row = c.execute(f'SELECT document FROM distribution_{kind} WHERE id=?', (ident(key),)).fetchone()
        if row is None and required:
            raise ValueError('找不到分发记录：' + kind)
        return json.loads(row['document']) if row else None

    def _records(self, c, kind):
        assert kind in TABLES
        return [json.loads(row['document']) for row in c.execute(f'SELECT document FROM distribution_{kind} ORDER BY rowid')]

    def connection_internal(self, connection_id):
        """Server-only vault/runtime boundary; never return through an API route."""
        with self.store.connect() as c:
            return self._get(c, 'connections', connection_id)

    def _put(self, c, kind, document, new=False):
        assert kind in TABLES
        document = copy.deepcopy(document)
        ident(document['id'])
        _no_secrets(document)
        previous = self._get(c, kind, document['id'], False)
        if previous and (new or kind in IMMUTABLE):
            raise DistributionConflict('冻结记录不可覆盖，请创建新版本')
        if not previous:
            c.execute(f'INSERT INTO distribution_{kind} VALUES(?,?)', (document['id'], pack(document)))
        else:
            c.execute(f'UPDATE distribution_{kind} SET document=? WHERE id=?', (pack(document), document['id']))
        return document

    def _capability(self, connection, action):
        fallback = {'status': 'unknown', 'verified': False, 'account': connection['account'], 'reason': '未完成本账号实际验收'}
        if not connection.get('enabled', True):
            return {**fallback, 'status': 'unsupported', 'reason': '连接已停用'}
        if self.runtime is None:
            return fallback
        try:
            if callable(getattr(self.runtime, 'capability', None)):
                supplied = self.runtime.capability(copy.deepcopy(connection), action)
            elif callable(getattr(self.runtime, 'capabilities', None)):
                supplied = self.runtime.capabilities(copy.deepcopy(connection)).get(action)
            else:
                supplied = None
            if not isinstance(supplied, dict) or supplied.get('status') not in ('unsupported', 'unknown', 'trial', 'available'):
                return fallback
            result = {key: copy.deepcopy(supplied[key]) for key in ('status', 'verified', 'code_verified', 'account_verified', 'account', 'reason', 'evidence', 'checked_at', 'last_checked_at') if key in supplied}
            _no_secrets(result)
            if result.get('account') != connection['account']:
                return {**fallback, 'reason': '能力证据属于其他账号'}
            if result['status'] == 'available' and result.get('verified') is not True:
                result.update(status='unknown', verified=False)
            return result
        except Exception:
            return fallback

    def _runnable(self, connection, approval):
        capability = self._capability(connection, approval['action'])
        if approval.get('pilot'):
            ready = capability.get('status') == 'trial' and capability.get('account_verified') is True and capability.get('code_verified') is True
            ready = ready or capability.get('status') == 'available' and capability.get('verified') is True
        else:
            ready = capability.get('status') == 'available' and capability.get('verified') is True
        return bool(ready and connection['enabled'] and capability.get('account') == approval['account']), capability

    def _connection_save(self, c, value):
        allowed = {'operation_id', 'action', 'connection_id', 'platform', 'account', 'label', 'secret_ref', 'enabled', 'expected_revision'}
        if set(value) - allowed:
            raise ValueError('连接只保存账号元信息和凭据库引用，能力须由实际核验提供')
        key = ident(value.get('connection_id') or object_id('connection', value['operation_id']))
        old = self._get(c, 'connections', key, False)
        if old and value.get('expected_revision') != old['revision']:
            raise DistributionConflict('账号连接已变化，请核对最新记录')
        platform = value.get('platform', old['platform'] if old else None)
        if platform not in {row['id'] for row in PLATFORMS}:
            raise ValueError('请选择已有平台类型')
        if old and platform != old['platform']:
            raise DistributionConflict('平台属于连接身份，请另建连接')
        account = text(value.get('account', old['account'] if old else ''), 200, True)
        secret_ref = value.get('secret_ref', old.get('secret_ref') if old else None)
        if secret_ref is not None and (not isinstance(secret_ref, str) or not re.fullmatch(r'vault:[A-Za-z0-9_-]{1,128}', secret_ref)):
            raise ValueError('凭据引用必须是凭据库签发的vault标识')
        if secret_ref:
            validator = getattr(self.runtime, 'validate_secret_ref', None)
            if not callable(validator) or validator(secret_ref) is not True:
                raise ValueError('凭据库引用不存在或无权使用')
        enabled = value.get('enabled', old.get('enabled', True) if old else True)
        if type(enabled) is not bool:
            raise ValueError('连接启用状态无效')
        item = {'id': key, 'platform': platform, 'account': account, 'label': text(value.get('label', old.get('label', '') if old else ''), 200),
                'secret_ref': secret_ref, 'enabled': enabled, 'revision': old['revision'] + 1 if old else 1,
                'created_at': old['created_at'] if old else stamp(), 'updated_at': stamp()}
        self._put(c, 'connections', item)
        return {'connection': _public(item)}

    def _source(self, c, work_id, version_id):
        source, artifacts = version_source(self.box, c, work_id, version_id)
        entries = []
        base = (self.root / 'data/artifacts').resolve()
        for item in artifacts:
            path = pathlib.Path(item['path']).resolve()
            if not path.is_relative_to(base) or not path.is_file() or path.stat().st_size > 512 * 1024 * 1024:
                raise ValueError('来源文件不可用或超出大小范围')
            entries.append({'id': item['id'], 'name': item['name'], 'mime': item['mime'], 'sha256': raw_digest(path.read_bytes())})
        snapshot = {'title': source['title'], 'body': source['body'], 'source_token': source['token'], 'author': source['author'], 'locked_fields': source['locked_fields'], 'artifacts': entries}
        return source, snapshot, digest(snapshot)

    @staticmethod
    def _publication_hash(publication):
        return digest({key: publication.get(key) for key in ('id', 'work_id', 'version_id', 'account', 'channel_id', 'title', 'body', 'image_ids', 'images')})

    def _rejected(self, c, work_id, version_id):
        row = c.execute("SELECT kind,candidate_id FROM toolbox_jobs WHERE work_id=? AND kind IN ('accept','reject') ORDER BY rowid DESC LIMIT 1", (work_id,)).fetchone()
        return row is not None and (row['kind'] == 'reject' or row['candidate_id'] != version_id)

    def _validate_approval(self,c,approval,revision):
        latest=c.execute("SELECT rowid AS decision_revision,id,kind,candidate_id,created_at FROM toolbox_jobs WHERE work_id=? AND kind IN ('accept','reject') ORDER BY rowid DESC LIMIT 1",(revision['work_id'],)).fetchone()
        if 'decision_revision' in approval and (latest['decision_revision'] if latest else 0)!=approval['decision_revision']:
            raise DistributionConflict('作品决定已更新，原分发授权失效')
        if approval.get('decision_id') and (not latest or latest['id']!=approval['decision_id'] or latest['kind']!='accept' or latest['candidate_id']!=revision['version_id']):
            raise DistributionConflict('此采纳授权已被后续决定替代')
        if latest and 'decision_revision' not in approval and _time(latest['created_at'])>_time(approval['approved_at']):
            raise DistributionConflict('作品决定已更新，请使用新的明确授权')

    def freeze_completion(self,c,work_id,version_id,targets):
        """Read-only plan bindings; availability itself never becomes authority."""
        ident(work_id);ident(version_id)
        if not isinstance(targets,list) or not 1<=len(targets)<=40:raise ValueError('请选择准确的发布目标')
        _,snapshot,fingerprint=self._source(c,work_id,version_id)
        work_format=self.box.options(work_id,c)['format']
        frozen=[];seen=set()
        for item in targets:
            if not isinstance(item,dict) or set(item)-{'connection_id','action'} or item.get('action') not in ('draft','publish'):raise ValueError('发布目标需要准确账号和动作')
            connection=self._get(c,'connections',item.get('connection_id'))
            key=(connection['id'],item['action'])
            if key in seen:raise ValueError('同一发布目标不能重复选择')
            seen.add(key);platform=next(row for row in PLATFORMS if row['id']==connection['platform'])
            compatible=bool(set(platform['content_kinds'])&({'article'} if work_format=='article' else {'image_post','note'}))
            supported=compatible and (bool(platform.get('draft')) if item['action']=='draft' else True)
            binding={'connection_id':connection['id'],'connection_revision':connection['revision'],'platform':connection['platform'],'channel_id':platform['channel_id'],
                     'account':connection['account'],'action':item['action'],'pilot':item['action']=='draft' and supported,'schedule_at':None,'supported':supported,
                     'notice':'试存本次准确稿件到草稿箱；尚无独立远端内容读回。' if item['action']=='draft' and supported else '当前内容类型需要手动发布。' if not supported else '仅实际验收通过的正式发布能力可执行。'}
            binding['target_key']=digest(binding);frozen.append(binding)
        return {'source_snapshot':snapshot,'source_fingerprint':fingerprint,'targets':frozen}

    def complete_adoption(self,c,*,decision_id,work_id,version_id,accepted_scopes,source_fingerprint,targets,actor='owner'):
        """Archive-confirmed completion transaction; creates intents, never sends."""
        latest=c.execute("SELECT * FROM toolbox_jobs WHERE work_id=? AND kind IN ('accept','reject') ORDER BY rowid DESC LIMIT 1",(ident(work_id),)).fetchone()
        if not latest or latest['id']!=ident(decision_id) or latest['kind']!='accept' or latest['candidate_id']!=ident(version_id):raise DistributionConflict('采纳决定已变化，未执行旧发布方案')
        if not isinstance(accepted_scopes,list) or set(accepted_scopes)!=set(json.loads(latest['scope'])):raise DistributionConflict('采纳范围不符，不能扩大授权')
        if not isinstance(actor,str) or actor.lower() in ('ai','assistant','system','runner','automatic'):raise ValueError('发布方案需要真实用户授权')
        completion=self.studio._completion_plan(c,decision_id,work_id,version_id)
        approved_plan=completion['_plan'].get('distribution')
        if completion.get('mode')!='distribute' or not approved_plan or approved_plan.get('source_fingerprint')!=source_fingerprint or approved_plan.get('targets')!=targets:raise DistributionConflict('发布目标不属于已冻结的人类采纳方案')
        _,snapshot,current_fingerprint=self._source(c,work_id,version_id)
        if source_fingerprint!=current_fingerprint:raise DistributionConflict('采纳后原稿或原图已变化，未执行旧方案')
        required='article' if self.box.options(work_id,c)['format']=='article' else 'copy'
        image_ids=[row['id'] for row in snapshot['artifacts'] if row['mime'].startswith('image/')]
        if required not in accepted_scopes or image_ids and 'images' not in accepted_scopes:raise DistributionConflict('局部采纳不能自动分发整稿')
        if not isinstance(targets,list) or not 1<=len(targets)<=40:raise ValueError('发布目标格式无效')
        result={key:[] for key in ('publications','revisions','approvals','deliveries','skipped','blocked')}
        for target in targets:
            if not isinstance(target,dict):raise ValueError('发布目标格式无效')
            identity={key:copy.deepcopy(value) for key,value in target.items() if key!='target_key'}
            if target.get('target_key')!=digest(identity):raise DistributionConflict('冻结目标指纹不符')
            connection=self._get(c,'connections',target.get('connection_id'))
            if any(connection.get(key)!=target.get(wanted) for key,wanted in (('revision','connection_revision'),('platform','platform'),('account','account'))):raise DistributionConflict('账号绑定已变化，不能沿用旧采纳授权')
            platform=next(row for row in PLATFORMS if row['id']==connection['platform'])
            compatible=bool(set(platform['content_kinds'])&({'article'} if self.box.options(work_id,c)['format']=='article' else {'image_post','note'}))
            supported=compatible and (bool(platform.get('draft')) if target.get('action')=='draft' else True)
            if target.get('action') not in ('draft','publish') or target.get('channel_id')!=platform['channel_id'] or type(target.get('supported')) is not bool or target['supported']!=supported or target.get('pilot')!=(target['action']=='draft' and supported) or target.get('schedule_at') is not None:raise DistributionConflict('冻结目标与真实内容类型不符')
            key='adoption-target-'+digest([decision_id,work_id,version_id,target['target_key']])[:40]
            signature=digest({'source':source_fingerprint,'target':target,'scope':sorted(accepted_scopes),'actor':actor})
            link=self.studio._get(c,'completion_distribution',key,False)
            if link and link['signature']!=signature:raise DistributionConflict('同一采纳目标不能覆盖不同内容')
            if link and link['status']!='blocked':
                for name,entries in link['result'].items():result[name].extend(copy.deepcopy(entries))
                continue
            local={name:[] for name in result}
            publications=self.studio._records(c,'publications')
            published=next((p for p in publications if p['work_id']==work_id and p['version_id']==version_id and p['channel_id']==target['channel_id'] and p['account']==target['account'] and p['status']=='published'),None)
            previous=[row for row in self._records(c,'deliveries') if row['work_id']==work_id and row.get('platform')==target['platform'] and row['account']==target['account'] and row['action']==target['action'] and self._get(c,'revisions',row['revision_id'])['version_id']==version_id]
            sent=next((row for row in previous if row['status']=='succeeded' or row.get('dispatch_started_at') or row['status']=='unknown'),None)
            if published or sent:
                pub=published or self.studio._get(c,'publications',sent['publication_id']);local['publications'].append(pub)
                local['skipped'].append({'target_key':target['target_key'],'publication_id':pub['id'],'reason':'already_published' if published else 'existing_remote_intent','delivery_id':sent['id'] if sent else None})
                status='completed'
            elif not target['supported'] or connection['enabled'] and self._capability(connection,target['action'])['status']=='unsupported':
                pub=self.studio.create_completion_publication(c,decision_id,work_id,version_id,snapshot,{'channel_id':target['channel_id'],'account':target['account'],'status':'draft'})['publication']
                local['publications'].append(pub);local['skipped'].append({'target_key':target['target_key'],'publication_id':pub['id'],'reason':'manual_required'});status='manual'
            else:
                if link:
                    revision=self._get(c,'revisions',link['revision_id']);self._validate_revision(c,revision);pub=self.studio._get(c,'publications',revision['publication_id'])
                else:
                    matching=next((p for p in publications if p['work_id']==work_id and p['version_id']==version_id and p['channel_id']==target['channel_id'] and p['account']==target['account'] and p['status']=='draft' and p['title']==snapshot['title'] and p['body']==snapshot['body'] and p.get('image_ids',[])==image_ids),None)
                    publication_id=matching['id'] if matching else 'adopted-auto-'+digest([work_id,version_id,target['platform'],target['account']])[:40]
                    prepared=self._prepare(c,{'operation_id':key,'work_id':work_id,'version_id':version_id,'connection_id':connection['id'],'publication_id':publication_id,'image_ids':image_ids,'title':snapshot['title'],'body':snapshot['body']},allow_disabled=True)
                    revision,pub=prepared['revision'],prepared['publication']
                local['publications'].append(pub);local['revisions'].append(revision)
                runnable,capability=self._runnable(connection,{'action':target['action'],'pilot':target['pilot'],'account':target['account']})
                if not runnable:
                    local['blocked'].append({'target_key':target['target_key'],'publication_id':pub['id'],'connection_id':connection['id'],'action':target['action'],'reason':capability.get('reason') or '账号连接待检查'});status='blocked'
                else:
                    approved=self._approve(c,{'operation_id':key,'items':[{'revision_id':revision['id'],'revision_hash':revision['hash'],'action':target['action'],'pilot':target['pilot'],'schedule_at':target['schedule_at']}]},actor,decision_id=decision_id)
                    local['approvals'].extend(approved['approvals'])
                    local['deliveries'].append(self._enqueue(c,{'operation_id':key,'approval_id':approved['approvals'][0]['id']})['delivery']);status='queued'
            document={'id':key,'signature':signature,'decision_id':decision_id,'status':status,'result':local}
            if local['revisions']:document['revision_id']=local['revisions'][0]['id']
            self.studio._put(c,'completion_distribution',document,not link)
            for name,entries in local.items():result[name].extend(copy.deepcopy(entries))
        return _public(result)

    def _prepare(self, c, value,allow_disabled=False):
        work_id = ident(value.get('work_id'))
        version_id = ident(value.get('version_id'))
        connection = self._get(c, 'connections', value.get('connection_id'))
        if not connection['enabled'] and not allow_disabled:
            raise ValueError('账号连接已停用')
        if self._rejected(c, work_id, version_id):
            raise DistributionConflict('本作品最新决定已拒绝或转向其他版本，不能分发旧稿')
        source, snapshot, source_fingerprint = self._source(c, work_id, version_id)
        platform = next(row for row in PLATFORMS if row['id'] == connection['platform'])
        content_kind = value.get('content_kind', platform['content_kinds'][0])
        if content_kind not in platform['content_kinds']:
            raise ValueError('内容类型与账号渠道不符')
        title = text(value.get('title', source['title']), 500, True)
        body = text(value.get('body', source['body']), 100000, True)
        platform_options={}
        if connection['platform']=='bilibili_video':
            platform_options=value.get('platform_options') or {}
            if not isinstance(platform_options,dict) or set(platform_options)-{'tid','copyright','source'} or type(platform_options.get('tid')) is not int or not 1<=platform_options['tid']<=99999 or platform_options.get('copyright') not in ('1','2'):
                raise ValueError('请明确选择B站分区ID及原创／转载声明')
            if platform_options['copyright']=='2' and not safe_url(platform_options.get('source')):raise ValueError('转载需要可核对的原始来源链接')
        publication_id = ident(value.get('publication_id') or object_id('publication', value['operation_id']))
        old = self.studio._get(c, 'publications', publication_id, False)
        if old and any(old.get(key) != wanted for key, wanted in (('work_id', work_id), ('version_id', version_id), ('channel_id', platform['channel_id']), ('account', connection['account']))):
            raise DistributionConflict('发布实例的作品、来源、渠道和账号身份不可更换')
        if old and old['status'] != 'draft':
            raise DistributionConflict('已发布或已撤回记录请保留，分发新稿须另建发布实例')
        images = self.studio._images(c, work_id, value.get('image_ids', old.get('image_ids', []) if old else []), publication_id)
        manifests = []
        for image in images:
            file = c.execute('SELECT * FROM toolbox_files WHERE id=?', (image['id'],)).fetchone()
            manifests.append({**image, 'size': file['size']})
        original = c.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?', (version_id,)).fetchone()
        production_context = json.loads(original['document']).get('studio_context') if original else None
        pub = copy.deepcopy(old) if old else {'id': publication_id, 'work_id': work_id, 'version_id': version_id, 'channel_id': platform['channel_id'], 'account': connection['account'], 'status': 'draft', 'url': '', 'published_at': None, 'evidence': [], 'history': [], 'source_snapshot': {**copy.deepcopy(snapshot), 'studio_context': copy.deepcopy(production_context)}, 'context': copy.deepcopy(production_context), 'context_status': 'frozen_at_production' if production_context else 'not_recorded'}
        before = {key: copy.deepcopy(pub.get(key)) for key in ('title', 'body', 'images', 'image_ids', 'status', 'url', 'published_at', 'evidence')}
        pub.update(title=title, body=body, images=images, image_ids=[row['source_id'] for row in images])
        pub['history'].append({'operation_id': value['operation_id'], 'at': stamp(), 'before': before if old else None, 'after': {key: copy.deepcopy(pub.get(key)) for key in before}, 'note': '已准备本地渠道稿；尚无远端草稿回执'})
        pub = self.studio._put(c, 'publications', pub, not old)
        item = {'id': object_id('revision', value['operation_id']), 'work_id': work_id, 'version_id': version_id, 'publication_id': publication_id, 'connection_id': connection['id'],
                'connection_revision': connection['revision'], 'platform': connection['platform'], 'account': connection['account'], 'content_kind': content_kind,
                'title': title, 'body': body, 'source_token': source['token'], 'source_fingerprint': source_fingerprint, 'source_snapshot': snapshot,
                'asset_manifest': manifests, 'publication_hash': self._publication_hash(pub), 'created_at': stamp()}
        if platform_options:item['platform_options']=platform_options
        item['hash'] = digest({key: item[key] for key in item if key not in ('id', 'created_at')})
        self._put(c, 'revisions', item, True)
        return {'revision': item, 'publication': pub}

    def _validate_revision(self, c, revision):
        connection = self._get(c, 'connections', revision['connection_id'])
        if not connection['enabled'] or connection['revision'] != revision['connection_revision'] or connection['account'] != revision['account'] or connection['platform'] != revision['platform']:
            raise DistributionConflict('账号连接已变化，原批准失效，请重新准备和确认')
        if self._rejected(c, revision['work_id'], revision['version_id']):
            raise DistributionConflict('本作品最新决定已变化，原批准失效')
        _, _, current = self._source(c, revision['work_id'], revision['version_id'])
        if current != revision['source_fingerprint']:
            raise DistributionConflict('来源稿件或原图已变化，原批准失效')
        publication = self.studio._get(c, 'publications', revision['publication_id'])
        if publication['status'] == 'withdrawn' or self._publication_hash(publication) != revision['publication_hash']:
            raise DistributionConflict('渠道稿件已变化或撤回，原批准失效')
        for image in revision['asset_manifest']:
            row = c.execute('SELECT * FROM toolbox_files WHERE id=?', (image['id'],)).fetchone()
            if not row:
                raise DistributionConflict('冻结图片快照丢失')
            path = pathlib.Path(row['path']).resolve()
            if not path.is_relative_to((self.root / 'data/toolbox/files').resolve()) or not path.is_file() or raw_digest(path.read_bytes()) != image['sha256'] or row['sha256'] != image['sha256']:
                raise DistributionConflict('冻结图片快照字节不一致')
            source = c.execute('SELECT a.*,j.work_id,j.status FROM artifacts a JOIN toolbox_jobs j ON j.id=a.task_id WHERE a.id=?', (image['source_id'],)).fetchone()
            if not source or source['work_id'] != revision['work_id'] or source['status'] != 'completed':
                raise DistributionConflict('原图不再属于同作品完成版')
            original = pathlib.Path(source['path']).resolve()
            if not original.is_relative_to((self.root / 'data/artifacts').resolve()) or not original.is_file() or raw_digest(original.read_bytes()) != image['sha256']:
                raise DistributionConflict('原图字节已变化，原批准失效')
        return connection

    def _approve(self, c, value, actor, decision_id=None):
        items = value.get('items')
        if not isinstance(items, list) or not 1 <= len(items) <= 40:
            raise ValueError('请选择需要逐项批准的渠道稿')
        if actor.lower() in ('ai', 'assistant', 'system', 'runner', 'automatic'):
            raise ValueError('分发需要真实用户逐项确认')
        batch_id = object_id('batch', value['operation_id'])
        approvals = []
        seen = set()
        for index, selected in enumerate(items):
            if not isinstance(selected, dict) or set(selected) - {'revision_id', 'revision_hash', 'action', 'schedule_at', 'pilot'}:
                raise ValueError('批准项仅接收版本指纹、动作、时间和试运行选择')
            revision = self._get(c, 'revisions', selected.get('revision_id'))
            self._validate_revision(c, revision)
            if selected.get('revision_hash') != revision['hash']:
                raise DistributionConflict('批准版本指纹不符，请核对实际稿件')
            action = selected.get('action')
            if action not in ('draft', 'publish'):
                raise ValueError('请选择存草稿或发布的具体动作')
            schedule_at = selected.get('schedule_at')
            if schedule_at is not None:
                schedule_at = _iso(_time(schedule_at))
            pilot = selected.get('pilot', False)
            if type(pilot) is not bool:
                raise ValueError('试运行选择无效')
            binding = {'revision_id': revision['id'], 'revision_hash': revision['hash'], 'connection_id': revision['connection_id'], 'connection_revision': revision['connection_revision'], 'platform': revision['platform'], 'account': revision['account'], 'action': action, 'schedule_at': schedule_at, 'pilot': pilot}
            decision=c.execute("SELECT max(rowid) FROM toolbox_jobs WHERE work_id=? AND kind IN ('accept','reject')",(revision['work_id'],)).fetchone()[0]
            binding['decision_revision']=decision or 0
            if decision_id is not None:binding['decision_id']=ident(decision_id)
            key = digest(binding)
            if key in seen:
                raise ValueError('同一批次不可重复批准相同动作')
            seen.add(key)
            approval = {**binding, 'id': 'approval-' + raw_digest((value['operation_id'] + ':' + str(index)).encode())[:40], 'batch_id': batch_id, 'actor': actor, 'approved_at': stamp(), 'hash': key}
            self._put(c, 'approvals', approval, True)
            approvals.append(approval)
        batch = {'id': batch_id, 'actor': actor, 'created_at': stamp(), 'approval_ids': [item['id'] for item in approvals], 'note': text(value.get('note', ''), 4000)}
        self._put(c, 'batches', batch, True)
        return {'batch': batch, 'approvals': approvals}

    def _enqueue(self, c, value):
        approval = self._get(c, 'approvals', value.get('approval_id'))
        revision = self._get(c, 'revisions', approval['revision_id'])
        self._validate_revision(c, revision)
        self._validate_approval(c,approval,revision)
        if value.get('revision_id', revision['id']) != revision['id'] or value.get('revision_hash', revision['hash']) != revision['hash']:
            raise DistributionConflict('入队稿件与本次批准不符')
        dedupe = digest({key: approval[key] for key in ('revision_hash', 'platform', 'account', 'action', 'schedule_at')})
        if approval.get('decision_id'):dedupe=digest([dedupe,approval['decision_id']])
        row = c.execute("SELECT document FROM distribution_deliveries WHERE json_extract(document,'$.dedupe_key')=?", (dedupe,)).fetchone()
        if row:
            return {'delivery': json.loads(row['document']), 'duplicate': True}
        item = {'id': object_id('delivery', value['operation_id']), 'dedupe_key': dedupe, 'approval_id': approval['id'], 'batch_id': approval['batch_id'], 'revision_id': revision['id'], 'publication_id': revision['publication_id'], 'work_id': revision['work_id'], 'connection_id': revision['connection_id'], 'account': revision['account'], 'platform': revision['platform'], 'action': approval['action'], 'schedule_at': approval['schedule_at'], 'pilot': approval['pilot'], 'status': 'queued', 'remote_state': None, 'verified': False, 'attempt_ids': [], 'created_at': stamp(), 'updated_at': stamp(), 'error': None}
        self._put(c, 'deliveries', item, True)
        return {'delivery': item, 'duplicate': False}

    def _cancel(self, c, value):
        delivery = self._get(c, 'deliveries', value.get('delivery_id'))
        if delivery['status'] in ('succeeded', 'cancelled'):
            return {'delivery': delivery}
        attempt = self._get(c, 'attempts', delivery['attempt_ids'][-1]) if delivery['attempt_ids'] else None
        sent = bool(attempt and attempt.get('dispatched_at'))
        delivery.update(status='unknown' if sent else 'cancelled', cancel_requested=True, updated_at=stamp(), error='已请求停止；已发送结果须实际核验' if sent else None)
        if sent:
            delivery['remote_state'] = 'unknown'
        if attempt and attempt['status'] == 'leased':
            attempt.update(status='unknown' if sent else 'cancelled', finished_at=stamp())
            self._put(c, 'attempts', attempt)
        self._put(c, 'deliveries', delivery)
        return {'delivery': delivery}

    def _retry(self, c, value):
        delivery = self._get(c, 'deliveries', value.get('delivery_id'))
        attempt = self._get(c, 'attempts', delivery['attempt_ids'][-1]) if delivery['attempt_ids'] else None
        if delivery['status'] != 'failed' or not attempt or attempt.get('dispatched_at') or attempt.get('result', {}).get('phase') != 'pre_send':
            raise DistributionConflict('仅明确未发送的失败可显式重试；未知回执不能重新发送')
        self._validate_revision(c, self._get(c, 'revisions', delivery['revision_id']))
        self._validate_approval(c,self._get(c,'approvals',delivery['approval_id']),self._get(c,'revisions',delivery['revision_id']))
        delivery.update(status='queued', error=None, updated_at=stamp(), verified=False, remote_state=None)
        self._put(c, 'deliveries', delivery)
        return {'delivery': delivery}

    def _normalize(self, value):
        if not isinstance(value, dict):
            raise ValueError('请求需要JSON对象')
        value = copy.deepcopy(value)
        nested = value.pop('payload', None)
        if nested is not None:
            if not isinstance(nested, dict):
                raise ValueError('payload需要JSON对象')
            value.update(nested)
        value['operation_id'] = ident(value.get('operation_id') or value.get('id'))
        value.pop('id', None)
        value['action'] = text(value.get('action', ''), 100, True)
        _no_secrets(value)
        if len(pack(value)) > 300000:
            raise ValueError('分发请求过大')
        return value

    def command(self, value, actor='user'):
        value = self._normalize(value)
        actor = text(actor, 200, True)
        signature = digest({'value': value, 'actor': actor})
        # Reconciliation uses a read-only verifier outside the SQL transaction.
        if value['action'] == 'delivery-reconcile':
            return self._reconcile(value, actor, signature)
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM distribution_operations WHERE operation_id=?', (value['operation_id'],)).fetchone()
            if old:
                if old['signature'] != signature:
                    raise DistributionConflict('同一操作ID不能用于不同内容或用户')
                return json.loads(old['result'])
            actions = {'connection-save': lambda: self._connection_save(c, value), 'channel-prepare': lambda: self._prepare(c, value), 'batch-approve': lambda: self._approve(c, value, actor), 'delivery-enqueue': lambda: self._enqueue(c, value), 'delivery-cancel': lambda: self._cancel(c, value), 'delivery-retry': lambda: self._retry(c, value)}
            if value['action'] not in actions:
                raise ValueError('不支持的分发操作')
            result = {'operation_id': value['operation_id'], 'action': value['action'], 'status': 'accepted' if value['action'] in ('delivery-enqueue', 'delivery-retry') else 'completed', 'result': _public(actions[value['action']]())}
            c.execute('INSERT INTO distribution_operations VALUES(?,?,?,?,?,?)', (value['operation_id'], signature, actor, value['action'], pack(result), stamp()))
        return result

    def _expire(self, c):
        for attempt in self._records(c, 'attempts'):
            if attempt['status'] != 'leased' or _time(attempt['lease_until']) > _now():
                continue
            delivery = self._get(c, 'deliveries', attempt['delivery_id'])
            if delivery['status'] != 'leased':
                continue
            sent = bool(attempt.get('dispatched_at'))
            result = {'remote_state': 'unknown' if sent else 'failed', 'verified': False, 'phase': 'sent' if sent else 'pre_send', 'error': '发送后租约到期，须实际核验' if sent else '发送前租约到期，可核对后显式重试'}
            attempt.update(status='unknown' if sent else 'failed', result=result, finished_at=stamp())
            delivery.update(status=attempt['status'], remote_state=result['remote_state'], error=result['error'], updated_at=stamp())
            self._put(c, 'attempts', attempt)
            self._put(c, 'deliveries', delivery)

    def claim_next(self, runner_id, lease_seconds=60):
        ident(runner_id)
        if type(lease_seconds) is not int or not 5 <= lease_seconds <= 3600:
            raise ValueError('执行租约时长无效')
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            self._expire(c)
            self._put(c, 'runners', {'id': runner_id, 'last_seen_at': stamp(), 'state': 'polling'})
            for delivery in self._records(c, 'deliveries'):
                if delivery['status'] != 'queued' or delivery['schedule_at'] and _time(delivery['schedule_at']) > _now():
                    continue
                revision = self._get(c, 'revisions', delivery['revision_id'])
                approval = self._get(c, 'approvals', delivery['approval_id'])
                try:
                    connection = self._validate_revision(c, revision)
                    self._validate_approval(c,approval,revision)
                except (ValueError, OSError) as exc:
                    delivery.update(status='blocked', error=str(exc), updated_at=stamp())
                    self._put(c, 'deliveries', delivery)
                    continue
                runnable, capability = self._runnable(connection, approval)
                if not runnable:
                    delivery.update(blocked_reason=capability.get('reason') or '本账号未完成该动作实际验收', updated_at=stamp())
                    self._put(c, 'deliveries', delivery)
                    continue
                attempt = {'id': 'attempt-' + uuid.uuid4().hex, 'delivery_id': delivery['id'], 'runner_id': runner_id, 'lease_token': uuid.uuid4().hex,
                           'lease_until': _iso(_now() + dt.timedelta(seconds=lease_seconds)), 'status': 'leased', 'created_at': stamp(), 'dispatched_at': None, 'finished_at': None, 'result': None}
                delivery.update(status='leased', updated_at=stamp(), error=None)
                delivery.pop('blocked_reason', None)
                delivery['attempt_ids'].append(attempt['id'])
                self._put(c, 'attempts', attempt, True)
                self._put(c, 'deliveries', delivery)
                self._put(c, 'runners', {'id': runner_id, 'last_seen_at': stamp(), 'state': 'leased', 'delivery_id': delivery['id']})
                result = {'delivery': _public(delivery), 'attempt': _public(attempt), 'revision': revision, 'connection': connection, 'lease_token': attempt['lease_token']}
                break
            else:
                result = None
        # Returning only after commit is the send boundary.
        return result

    def _lease(self, c, delivery_id, attempt_id, lease_token, runner_id=None, live=True):
        delivery = self._get(c, 'deliveries', delivery_id)
        attempt = self._get(c, 'attempts', attempt_id)
        if attempt['delivery_id'] != delivery_id or attempt['lease_token'] != lease_token or runner_id is not None and attempt['runner_id'] != runner_id or not delivery['attempt_ids'] or delivery['attempt_ids'][-1] != attempt_id:
            raise DistributionConflict('执行租约不属于当前分发任务')
        if live and (attempt['status'] != 'leased' or delivery['status'] != 'leased' or _time(attempt['lease_until']) <= _now()):
            raise DistributionConflict('执行租约已失效，请核对原回执')
        return delivery, attempt

    def mark_dispatched(self, delivery_id, attempt_id, lease_token, runner_id=None):
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            delivery, attempt = self._lease(c, delivery_id, attempt_id, lease_token, runner_id)
            if attempt.get('dispatched_at'):
                raise DistributionConflict('此租约已跨过发送边界，不可重复发送')
            revision = self._get(c, 'revisions', delivery['revision_id'])
            connection = self._validate_revision(c, revision)
            self._validate_approval(c,self._get(c,'approvals',delivery['approval_id']),revision)
            runnable, _ = self._runnable(connection, self._get(c, 'approvals', delivery['approval_id']))
            if not runnable:
                raise DistributionConflict('账号实际能力已变化，不能发送')
            attempt['dispatched_at'] = stamp()
            self._put(c, 'attempts', attempt)
            delivery.update(updated_at=stamp(), dispatch_started_at=attempt['dispatched_at'])
            self._put(c, 'deliveries', delivery)
        return {'delivery': _public(delivery), 'attempt': _public(attempt), 'dispatched': True}

    def _result(self, value, revision, dispatched):
        if not isinstance(value, dict):
            raise ValueError('平台结果需要JSON对象')
        _no_secrets(value)
        if len(pack(value)) > 100000:
            raise ValueError('平台回执过大')
        state = value.get('remote_state')
        if state not in REMOTE_STATES or type(value.get('verified', False)) is not bool:
            raise ValueError('远端结果状态无效')
        result = {key: copy.deepcopy(value[key]) for key in ('remote_state', 'verified', 'remote_id', 'safe_url', 'account', 'revision_hash', 'evidence', 'published_at', 'error') if key in value}
        result.setdefault('verified', False)
        result['phase'] = 'sent' if dispatched else 'pre_send'
        if 'error' in result:
            text(result['error'], 10000)
        verified = bool(result['verified'] and state in SUCCESS_STATES and result.get('account') == revision['account'] and result.get('revision_hash') == revision['hash'] and isinstance(result.get('remote_id'), str) and result['remote_id'].strip() and len(result['remote_id']) <= 1000 and safe_url(result.get('safe_url')) and isinstance(result.get('evidence'), list) and result['evidence'])
        if verified and state == 'published':
            try:
                _time(result.get('published_at'))
            except ValueError:
                verified = False
        if not dispatched and state != 'failed':
            raise DistributionConflict('未经过持久发送边界不能记录远端成功')
        if state in SUCCESS_STATES and not verified or dispatched and state == 'failed':
            result.update(remote_state='unknown', verified=False)
            result.setdefault('error', '缺少本账号和稿件的真实回执证据，须核验')
        else:
            result['verified'] = verified
        if result.get('safe_url') and not safe_url(result['safe_url']):
            result.pop('safe_url', None)
        return result

    def _project(self, c, delivery, revision, result):
        if not result.get('verified') or result['remote_state'] not in SUCCESS_STATES:
            return False
        publication = self.studio._get(c, 'publications', revision['publication_id'])
        if publication.get('status') == 'withdrawn' or self._publication_hash(publication) != revision['publication_hash']:
            delivery['projection_blocked'] = '发布台账已编辑或撤回，保留远端回执供人工核对'
            return False
        before = {key: copy.deepcopy(publication.get(key)) for key in ('status', 'url', 'published_at', 'evidence', 'remote_id', 'distribution_receipt')}
        publication.update(remote_id=result['remote_id'], distribution_receipt={'delivery_id': delivery['id'], 'revision_id': revision['id'], 'revision_hash': revision['hash'], 'remote_state': result['remote_state'], 'verified': True, 'safe_url': result['safe_url'], 'evidence': copy.deepcopy(result['evidence'])})
        publication.update(registration_kind='connector',publication_verification='verified')
        if result['remote_state'] == 'published':
            publication.update(status='published', url=result['safe_url'], published_at=result['published_at'])
        publication.update(self.studio.publication_metadata(publication))
        publication['history'].append({'operation_id': delivery['id'], 'at': stamp(), 'before': before, 'after': {key: copy.deepcopy(publication.get(key)) for key in before}, 'note': '真实远端回执核验后回填同一发布实例'})
        self.studio._put(c, 'publications', publication)
        return True

    def finish_attempt(self, delivery_id, attempt_id, lease_token, result, runner_id=None):
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            delivery, attempt = self._lease(c, delivery_id, attempt_id, lease_token, runner_id, live=False)
            revision = self._get(c, 'revisions', delivery['revision_id'])
            normalized = self._result(result, revision, bool(attempt.get('dispatched_at')))
            if attempt['status'] != 'leased':
                if attempt.get('result') == normalized:
                    return {'delivery': _public(delivery), 'attempt': _public(attempt)}
                raise DistributionConflict('此执行回执已结束；迟到结果须走实际核验')
            if _time(attempt['lease_until']) <= _now():
                # Persist uncertainty even when a worker arrives after expiry.
                self._expire(c)
                delivery = self._get(c, 'deliveries', delivery_id)
                attempt = self._get(c, 'attempts', attempt_id)
                return {'delivery': _public(delivery), 'attempt': _public(attempt), 'late_result_requires_reconcile': True}
            status = 'succeeded' if normalized['verified'] else 'failed' if normalized['remote_state'] == 'failed' else 'unknown'
            attempt.update(status=status, finished_at=stamp(), result=normalized)
            delivery.update(status=status, remote_state=normalized['remote_state'], verified=normalized['verified'], result=normalized, error=normalized.get('error'), updated_at=stamp())
            if normalized['verified']:
                delivery['publication_projected'] = self._project(c, delivery, revision, normalized)
            self._put(c, 'attempts', attempt)
            self._put(c, 'deliveries', delivery)
            self._put(c, 'runners', {'id': attempt['runner_id'], 'last_seen_at': stamp(), 'state': 'idle', 'last_delivery_id': delivery_id})
        return {'delivery': _public(delivery), 'attempt': _public(attempt)}

    def _reconcile(self, value, actor, signature):
        if set(value) - {'operation_id', 'action', 'delivery_id', 'remote_id', 'safe_url', 'note'}:
            raise ValueError('核验只接收原任务和远端线索，不能由客户端自报成功')
        with self.store.connect() as c:
            old = c.execute('SELECT * FROM distribution_operations WHERE operation_id=?', (value['operation_id'],)).fetchone()
            if old:
                if old['signature'] != signature:
                    raise DistributionConflict('同一操作ID不能用于不同内容或用户')
                return json.loads(old['result'])
            delivery = self._get(c, 'deliveries', value.get('delivery_id'))
            revision = self._get(c, 'revisions', delivery['revision_id'])
            connection = self._get(c, 'connections', delivery['connection_id'])
            before = digest(delivery)
        if not delivery.get('dispatch_started_at'):
            raise DistributionConflict('此任务尚无发送记录，不能认领远端成功')
        if connection['account'] != revision['account'] or connection['platform'] != revision['platform']:
            raise DistributionConflict('当前连接账号已变化，不能核验原账号任务')
        if not callable(getattr(self.runtime, 'verify', None)):
            raise ValueError('平台实际核验尚未接入，保留未知结果')
        hints = {key: value[key] for key in ('remote_id', 'safe_url') if key in value}
        if 'safe_url' in hints and not safe_url(hints['safe_url']):
            raise ValueError('核验链接不安全或带有凭据')
        verified = self.runtime.verify(copy.deepcopy(delivery), copy.deepcopy(revision), copy.deepcopy(connection), hints)
        normalized = self._result(verified, revision, True)
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM distribution_operations WHERE operation_id=?', (value['operation_id'],)).fetchone()
            if old:
                if old['signature'] != signature:
                    raise DistributionConflict('同一操作ID不能用于不同内容或用户')
                return json.loads(old['result'])
            current = self._get(c, 'deliveries', delivery['id'])
            if digest(current) != before:
                raise DistributionConflict('核验期间任务变化，请重新核对最新状态')
            current.setdefault('reconciliations', []).append({'actor': actor, 'at': stamp(), 'operation_id': value['operation_id'], 'result': normalized, 'note': text(value.get('note', ''), 4000)})
            current.update(status='succeeded' if normalized['verified'] else 'unknown', result=normalized, verified=normalized['verified'], remote_state=normalized['remote_state'], error=normalized.get('error'), updated_at=stamp())
            if normalized['verified']:
                current['publication_projected'] = self._project(c, current, revision, normalized)
            self._put(c, 'deliveries', current)
            result = {'operation_id': value['operation_id'], 'action': value['action'], 'status': 'completed', 'result': {'delivery': _public(current)}}
            c.execute('INSERT INTO distribution_operations VALUES(?,?,?,?,?,?)', (value['operation_id'], signature, actor, value['action'], pack(result), stamp()))
        return result

    def bootstrap(self, work_id=None):
        if work_id is not None:
            ident(work_id)
        with self.store.connect() as c:
            # A read never expires leases or changes a production decision.
            revisions = [item for item in self._records(c, 'revisions') if work_id is None or item['work_id'] == work_id]
            revision_ids = {item['id'] for item in revisions}
            approvals = [item for item in self._records(c, 'approvals') if item['revision_id'] in revision_ids]
            approval_ids = {item['id'] for item in approvals}
            deliveries = [item for item in self._records(c, 'deliveries') if work_id is None or item['work_id'] == work_id]
            delivery_ids = {item['id'] for item in deliveries}
            attempts = [item for item in self._records(c, 'attempts') if item['delivery_id'] in delivery_ids]
            batches = [item for item in self._records(c, 'batches') if work_id is None or approval_ids.intersection(item['approval_ids'])]
            publications = [item for item in self.studio._records(c, 'publications') if work_id is None or item['work_id'] == work_id]
            for publication in publications:publication.update(self.studio.publication_metadata(publication))
            connections = self._records(c, 'connections')
            for item in connections:
                item['capabilities'] = {action: self._capability(item, action) for action in ('draft', 'publish', 'verify')}
            for revision in revisions:
                try:
                    self._validate_revision(c, revision)
                    revision.update(valid=True, invalid_reason=None)
                except (ValueError, OSError) as exc:
                    revision.update(valid=False, invalid_reason=str(exc))
            for batch in batches:
                related = [item for item in deliveries if item['batch_id'] == batch['id']]
                states = [item['status'] for item in related]
                batch['status'] = 'approved' if not states else 'succeeded' if len(states) == len(batch['approval_ids']) and all(state == 'succeeded' for state in states) else 'partial' if 'succeeded' in states else 'needs_attention' if any(state in ('unknown', 'failed', 'blocked') for state in states) else 'cancelled' if all(state == 'cancelled' for state in states) else 'queued'
            runners = self._records(c, 'runners')
        runtime_summary = {'status': 'not_configured', 'note': '安装与账号实际验收分别核对；未启用自动执行'}
        if callable(getattr(self.runtime, 'summary', None)):
            try:
                runtime_summary = self.runtime.summary()
                _no_secrets(runtime_summary)
            except Exception:
                runtime_summary = {'status': 'unknown', 'note': '执行器状态暂不可核对'}
        return _public({'schema_version': 1, 'work_id': work_id, 'platforms': list(copy.deepcopy(PLATFORMS)), 'connections': connections, 'revisions': revisions, 'approvals': approvals,
                        'deliveries': deliveries, 'attempts': attempts, 'batches': batches, 'runner': {'runtime': runtime_summary, 'instances': runners}, 'publications': publications,
                        'tasks': {'needs_decision': [{'id': item['id'], 'kind': 'distribution-reconcile', 'delivery_id': item['id'], 'title': '核对分发回执', 'reason': item.get('error') or item.get('blocked_reason') or item['status']} for item in deliveries if item['status'] in ('unknown', 'failed', 'blocked')], 'independent_of_production': True}})
