"""Version-bound adoption, verified byte snapshots and publication orchestration.

Reading never backfills a historical decision or performs a remote side effect.
Project archival and Git synchronization are separate from the local completion
snapshot. The fixed production conversation still performs canonical archival;
its receipt is accepted only after the declared project bytes are checked.
"""
from __future__ import annotations

import contextlib
import copy
import hashlib
import json
import os
import pathlib
import re
import uuid

from easel_workbench.runtime.desk import stamp
from easel_workbench.runtime.toolbox_store import ident, pack, text


class CompletionConflict(ValueError):
    pass


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else pack(value).encode('utf-8')).hexdigest()


def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS toolbox_completions(
        decision_id TEXT PRIMARY KEY,work_id TEXT NOT NULL,version_id TEXT NOT NULL,
        document TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL)''')
    c.execute('CREATE INDEX IF NOT EXISTS toolbox_completion_work ON toolbox_completions(work_id,created_at)')
    c.execute('CREATE TABLE IF NOT EXISTS toolbox_completion_ops(id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL)')


def _safe_name(value):
    result = re.sub(r'[\\/:*?"<>|\x00-\x1f]', '＿', value).strip('. ')
    return result[:180] or 'file'


def _write_once(path, data):
    """Never replace a prior snapshot, even after a partial crash."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or path.read_bytes() != data:
            raise CompletionConflict('已有完成快照与本次字节不一致，保留原文件供核对')
        return
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('xb') as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        # The directory is private to this immutable decision. Check again
        # rather than overwriting an existing byte sequence on recovery.
        if path.exists():
            if path.read_bytes() != data:
                raise CompletionConflict('完成快照已变化，未覆盖原文件')
        else:
            os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class CompletionService:
    def __init__(self, box, distribution=None, studio=None):
        self.box = box
        self.store = box.store
        self.root = pathlib.Path(box.root).resolve()
        from easel_workbench.runtime.studio_service import StudioService
        self.studio = studio or getattr(box, 'studio', None) or StudioService(box)
        from easel_workbench.runtime.distribution_service import DistributionService
        self.distribution = distribution or DistributionService(box)
        self.project = self.studio.project
        with self.store.connect() as c:
            initialize(c)

    def _get(self, c, decision_id):
        row = c.execute('SELECT document FROM toolbox_completions WHERE decision_id=?', (decision_id,)).fetchone()
        return json.loads(row['document']) if row else None

    def _put(self, c, item):
        item = copy.deepcopy(item)
        item['updated_at'] = stamp()
        c.execute('INSERT OR REPLACE INTO toolbox_completions VALUES(?,?,?,?,?,?)',
                  (item['decision_id'], item['work_id'], item['version_id'], pack(item), item['created_at'], item['updated_at']))
        return item

    def _public(self, item, c=None):
        result = {key: copy.deepcopy(value) for key, value in item.items() if not key.startswith('_')}
        if c is not None:
            latest = c.execute("SELECT id,kind,candidate_id FROM toolbox_jobs WHERE work_id=? AND kind IN ('accept','reject') ORDER BY rowid DESC LIMIT 1", (item['work_id'],)).fetchone()
            result['current'] = bool(latest and latest['id'] == item['decision_id'] and latest['kind'] == 'accept')
            if result['project_archive']['status'] != 'verified':
                jobs = c.execute("SELECT * FROM toolbox_jobs WHERE id=? OR (work_id=? AND kind='archive') ORDER BY rowid DESC", (item['decision_id'], item['work_id']))
                job = next((dict(row) for row in jobs if row['id'] == item['decision_id'] or self.archive_decision_id(row) == item['decision_id']), None)
                if job:
                    proof = result['project_archive']
                    proof.update(job_id=job['id'], job_status=job['status'], can_retry=False)
                    from easel_workbench.runtime.local_operations import execution_mode
                    if execution_mode(c, job['id']) == 'local':
                        task = c.execute("SELECT id,status,document FROM toolbox_local_tasks WHERE job_id=? AND kind='project_archive'", (job['id'],)).fetchone()
                        if task:
                            document=json.loads(task['document']);proof.update(local_task_id=task['id'], phase=task['status'], can_retry=task['status'] in ('failed','needs_attention','waiting_binding','waiting_production'))
                            if task['status'] in ('failed','needs_attention'):proof.update(status='failed',error=document.get('error') or '本地归档需要核对')
                            elif task['status'] != 'completed':proof.update(status='pending',next_action='核对本地归档任务')
                    elif job['status'] in ('uncertain', 'needs_desktop', 'parked') or job['status'] == 'error' and job['dispatch_started'] and not job.get('finished_at'):
                        proof.update(status='unknown', error='原归档任务已发送，结果尚未核对；不会重复提交', next_action='在 Codex 核对原归档任务')
                    elif job['status'] in ('error', 'blocked'):
                        proof.update(status='failed', error=job.get('error') or '项目归档任务未完成', next_action='重新提交归档，不重新制作或分发', can_retry=True)
                    elif job['status'] in ('queued', 'dispatching', 'running'):
                        proof.update(status='pending', phase='running' if job['status'] == 'running' else 'queued')
                    elif job['status'] == 'completed' and proof['status'] == 'pending':
                        proof.update(status='unknown', error='归档任务已结束，尚未取得本次项目文件的有效核验回执', next_action='补齐归档回执后重新核验')
                    elif job['status'] == 'completed' and proof['status'] == 'failed':
                        proof['can_retry'] = True
            # Remote receipts remain factual after later review changes.
            publications = []
            for entry in result['publications']:
                publication = self.studio._get(c, 'publications', entry['publication_id'], False)
                publications.append({**entry, **({key: copy.deepcopy(publication.get(key)) for key in ('status', 'title', 'url', 'published_at', 'registration_kind', 'publication_verification')} if publication else {})})
            result['publications'] = publications
        return result

    def list(self, work_id=None, connection=None):
        with self.store.connect() if connection is None else contextlib.nullcontext(connection) as c:
            if work_id is not None:
                ident(work_id)
            rows = c.execute('SELECT t.document FROM toolbox_completions t JOIN toolbox_jobs j ON j.id=t.decision_id WHERE ? IS NULL OR t.work_id=? ORDER BY j.rowid', (work_id, work_id))
            return [self._public(json.loads(row['document']), c) for row in rows]

    def get(self, work_id, connection=None):
        items = self.list(ident(work_id), connection)
        return {'items': items, 'latest': items[-1] if items else None}

    def _source(self, c, wid, vid):
        from easel_workbench.runtime.content_studio import source
        from easel_workbench.runtime.production_outcome import assess
        source_value, artifacts = source(self.box, c, ident(wid), ident(vid))
        job = dict(c.execute('SELECT * FROM toolbox_jobs WHERE id=?', (vid,)).fetchone())
        format_value = self.box.options(wid, c)['format']
        if format_value not in ('poster','article'):
            media=c.execute('SELECT document FROM media_jobs WHERE id=?',(vid,)).fetchone()
            document=json.loads(media['document']) if media else {}
            outcome={'status':document.get('status'),'available_scopes':['media'] if document.get('status')=='completed' and document.get('artifacts') else []}
        else:outcome = assess(self.box, c, job)
        available = outcome.get('available_scopes', [])
        required = ['media'] if format_value not in ('poster','article') else ['images', 'copy'] if format_value == 'poster' else ['article'] + (['images'] if 'images' in available else [])
        entries = []
        base = (self.root / 'data/artifacts').resolve()
        for artifact in artifacts:
            path = pathlib.Path(artifact['path']).resolve()
            if not path.is_relative_to(base) or not path.is_file() or path.stat().st_size > (512 if format_value not in ('poster','article') else 64) * 1024 * 1024:
                raise ValueError('本版文件不可用或超出大小范围，请核对原交付')
            entries.append({key: artifact[key] for key in ('id', 'name', 'mime')} | {'sha256': digest(path.read_bytes()), 'size': path.stat().st_size})
        frozen = {**source_value, 'artifacts': entries, 'format': format_value}
        return frozen, artifacts, available, required, outcome['status'] == 'completed'

    def options(self, wid, vid):
        with self.store.connect() as c:
            c.execute('BEGIN')
            frozen, _, available, required, ready = self._source(c, wid, vid)
            creator=self._creator_scope(c,wid,vid)
            from easel_workbench.runtime.distribution_service import PLATFORMS
            targets = []
            for connection in self.distribution._records(c, 'connections'):
                if creator is not None and connection['id'] not in creator['account_ids']:continue
                platform = next((item for item in PLATFORMS if item['id'] == connection['platform']), {})
                actions = []
                for action in ('draft', 'publish'):
                    capability = self.distribution._capability(connection, action)
                    trial = action == 'draft' and capability.get('status') == 'trial' and capability.get('account_verified') is True and capability.get('code_verified') is True
                    actions.append({'action': action, 'available': bool(connection.get('enabled') and (trial or capability.get('status') == 'available' and capability.get('verified'))), 'reason': ('试存草稿；缺少独立读回时仍需核对。' if trial else '') + capability.get('reason', '尚未取得本账号的实际能力证据'), 'trial': trial})
                targets.append({'connection_id': connection['id'], 'platform': connection['platform'], 'channel_id': platform.get('channel_id', connection['platform']), 'account': connection['account'], 'label': connection.get('label', connection['account']), 'actions': actions})
            configuration = self.studio._configuration()['document']
            channels = [{'id': key, 'name': value.get('name', key)} for key, value in configuration['channels'].items()]
            return {'work_id': wid, 'version_id': vid, 'format': frozen['format'], 'required_scopes': required, 'available_scopes': available, 'whole_ready': ready and all(scope in available for scope in required), 'channels': channels,
                    'default': {'mode': 'archive', 'targets': [], 'manual_publications': []}, 'targets': targets, 'manual_channels': channels, 'history': self.get(wid, c)['items'],
                    'creator':creator,'account_notice':'请在创作画像中绑定要使用的平台账号。' if creator is not None and not targets else ''}

    def _creator_scope(self,c,wid,vid):
        from easel_workbench.runtime.task_runtime import read_run
        run=read_run(c,vid)
        if run:profile=run['snapshot']['profile']
        else:
            from easel_workbench.runtime.creator_runtime import read_owner
            owner=read_owner(c,wid)
            if not owner:return None
            profile=owner['profile']
        current=c.execute('SELECT document FROM creator_profiles WHERE id=?',(profile['id'],)).fetchone()
        if current:profile=json.loads(current[0])
        return {'id':profile['id'],'name':profile.get('name',''),'account_ids':profile.get('account_ids',[])}

    def _normalize(self, value):
        value = copy.deepcopy(value or {})
        if not isinstance(value, dict) or set(value) - {'mode', 'targets', 'manual_publications', 'plan_hash'}:
            raise ValueError('完成方案包含未知参数')
        mode = value.get('mode', 'archive')
        targets, manual = value.get('targets', []), value.get('manual_publications', [])
        if mode not in ('archive', 'distribute', 'manual_published') or not isinstance(targets, list) or not isinstance(manual, list) or len(targets) + len(manual) > 40:
            raise ValueError('请选择有效的采纳后方案')
        normalized_targets, normalized_manual = [], []
        for selected in targets:
            if not isinstance(selected, dict) or set(selected) - {'connection_id', 'action'} or selected.get('action') not in ('draft', 'publish'):
                raise ValueError('自动分发需选择明确账号和动作')
            normalized_targets.append({'connection_id': ident(selected.get('connection_id')), 'action': selected['action']})
        for selected in manual:
            if not isinstance(selected, dict) or set(selected) - {'channel_id', 'account', 'status', 'url', 'published_at'}:
                raise ValueError('手动发布记录包含未知参数')
            status = selected.get('status', 'published' if mode == 'manual_published' else 'draft')
            if status not in ('draft', 'published'):
                raise ValueError('手动发布状态无效')
            url, published_at = selected.get('url') or '', selected.get('published_at') or None
            if url:
                from easel_workbench.runtime.distribution_service import safe_url
                if not safe_url(url):
                    raise ValueError('发布链接需为有效的 HTTPS 地址')
            if published_at:
                from easel_workbench.runtime.studio_service import when
                when(published_at, '发布时间')
            normalized_manual.append({'channel_id': text(selected.get('channel_id', ''), 128, True), 'account': text(selected.get('account', ''), 200, True), 'status': status, 'url': url, 'published_at': published_at})
        if len({(row['connection_id'], row['action']) for row in normalized_targets}) != len(normalized_targets) or len({(row['channel_id'], row['account']) for row in normalized_manual}) != len(normalized_manual):
            raise ValueError('同一账号目标不能重复添加')
        if mode == 'archive' and (targets or manual) or mode == 'manual_published' and (targets or not manual or any(row['status'] != 'published' for row in normalized_manual)):
            raise ValueError('采纳后方案与所选发布目标不一致')
        if mode == 'distribute' and not (targets or manual):
            raise ValueError('请选择至少一个发布目标，或仅归档')
        return {'mode': mode, 'targets': normalized_targets, 'manual_publications': normalized_manual}

    def _plan(self, c, wid, vid, scope, value):
        selection = self._normalize(value)
        frozen, artifacts, available, required, ready = self._source(c, wid, vid)
        if not isinstance(scope, list) or not scope or len(set(scope)) != len(scope) or any(item not in available for item in scope):
            raise ValueError('请只采纳本版本实际交付的范围')
        whole = ready and set(required).issubset(scope)
        if not whole and selection['mode'] != 'archive':
            raise ValueError('局部采纳只保存所选部分，整稿采纳后才能进入发布')
        channels = self.studio._configuration()['document']['channels']
        for row in selection['manual_publications']:
            if row['channel_id'] not in channels:
                raise ValueError('请选择已有发布渠道')
        distribution = None
        if selection['targets']:
            creator=self._creator_scope(c,wid,vid)
            if creator is not None and any(row['connection_id'] not in creator['account_ids'] for row in selection['targets']):
                raise ValueError('所选账号未绑定到这份作品的创作画像，请先核对画像与平台账号。')
            distribution = self.distribution.freeze_completion(c, wid, vid, selection['targets'])
        history_revision = c.execute("SELECT coalesce(max(rowid),0) FROM toolbox_jobs WHERE work_id=? AND kind IN ('accept','reject')", (wid,)).fetchone()[0]
        frozen_plan = {'work_id': wid, 'version_id': vid, 'scope': sorted(scope), 'whole_work': whole, 'selection': selection, 'source': frozen, 'distribution': distribution, 'decision_revision': history_revision}
        return frozen_plan, artifacts

    def _preview_public(self, plan):
        publications = [{'channel_id': row.get('channel_id', ''), 'account': row.get('account', ''), 'action': row['action'], 'status': 'planned' if row.get('supported') else 'manual_required', 'notice': row.get('notice', '')} for row in (plan['distribution'] or {}).get('targets', [])]
        publications += [{'channel_id': row['channel_id'], 'account': row['account'], 'action': 'manual', 'status': row['status']} for row in plan['selection']['manual_publications']]
        warnings = []
        warnings.extend(dict.fromkeys(row['notice'] for row in publications if row.get('notice')))
        if not plan['whole_work']:
            warnings.append('本次为局部采纳，仅保存所选范围，不发布整稿。')
        if any(row['status'] == 'published' and (not row['url'] or not row['published_at']) for row in plan['selection']['manual_publications']):
            warnings.append('手动已发布记录缺少的链接或时间会标为待补；未知发布时间不能计算发布后24小时或7天表现。')
        return {'plan_hash': digest(plan), 'summary': '采纳整稿并保存完成快照' if plan['whole_work'] else '采纳所选部分并保存快照', 'whole_work': plan['whole_work'], 'archive': {'status': 'planned', 'scope': 'local_snapshot'}, 'publications': publications, 'warnings': warnings}

    def preview(self, wid, vid, value):
        if not isinstance(value, dict) or set(value) - {'scope', 'completion'}:
            raise ValueError('完成预览参数无效')
        with self.store.connect() as c:
            c.execute('BEGIN')
            plan, _ = self._plan(c, ident(wid), ident(vid), value.get('scope'), value.get('completion'))
            return self._preview_public(plan)

    def freeze(self, c, job, value):
        """Called inside the original accept transaction, before its insert."""
        plan, artifacts = self._plan(c, job['work_id'], job['candidate_id'], json.loads(job['scope']), value)
        expected = (value or {}).get('plan_hash')
        if value is not None and (not isinstance(expected, str) or expected != digest(plan)):
            raise CompletionConflict('作品、最后决定或发布方案已变化，请核对新的完成预览')
        now = stamp()
        work = dict(c.execute('SELECT * FROM toolbox_works WHERE id=?', (job['work_id'],)).fetchone())
        history = [dict(row) for row in c.execute('SELECT * FROM toolbox_jobs WHERE work_id=? ORDER BY rowid', (job['work_id'],))]
        history.append(copy.deepcopy(job))
        input_rows = [dict(row) for row in c.execute('SELECT i.* FROM toolbox_article_inputs i JOIN toolbox_jobs j ON j.id=i.job_id WHERE j.work_id=?', (job['work_id'],))]
        review_rows = [dict(row) for row in c.execute('SELECT i.* FROM toolbox_review_inputs i JOIN toolbox_jobs j ON j.id=i.job_id WHERE j.work_id=?', (job['work_id'],))]
        annotations = [dict(row) for row in c.execute('SELECT * FROM toolbox_review_events WHERE work_id=? ORDER BY seq', (job['work_id'],))]
        transcript = {'coverage': '仅包含工作台已保存的原始输入、讨论、修改、决定、批注和实际交付；不补造缺失的聊天、提示词或检查。', 'work': work, 'history': history, 'article_inputs': input_rows, 'review_inputs': review_rows, 'annotation_events': annotations}
        selected = []
        scopes = plan['scope']
        for row in artifacts:
            # Only the adopted output scope becomes a product. Evidence and
            # user process remain in the immutable transcript separately.
            if plan['source']['format'] not in ('poster','article'):
                include='media' in scopes
            elif row['mime'].startswith('image/'):
                include = 'images' in scopes
            elif plan['source']['format'] == 'poster':
                include = 'copy' in scopes and not row['mime'].startswith(('audio/', 'video/'))
            else:
                include = 'article' in scopes
            if include:
                frozen = next(item for item in plan['source']['artifacts'] if item['id'] == row['id'])
                selected.append({**frozen, 'source_path': row['path'], 'relative_path': '成品/' + str(len(selected) + 1).zfill(2) + '-' + _safe_name(row['name'])})
        attachment_ids = list(dict.fromkeys(fid for item in history for fid in json.loads(item.get('files') or '[]')))
        attachments = []
        for fid in attachment_ids:
            original = c.execute('SELECT * FROM toolbox_files WHERE id=?', (fid,)).fetchone()
            if not original:
                raise ValueError('原始附件记录缺失，采纳前请核对')
            path = pathlib.Path(original['path']).resolve()
            if not path.is_file() or not path.is_relative_to(self.root / 'data') or digest(path.read_bytes()) != original['sha256']:
                raise ValueError('原始附件字节已变化，采纳前请核对')
            attachments.append({'id': fid, 'name': original['name'], 'mime': original['mime'], 'sha256': original['sha256'], 'size': original['size'], 'source_path': str(path), 'relative_path': '原始附件/' + str(len(attachments) + 1).zfill(2) + '-' + _safe_name(original['name'])})
        item = {'id': job['id'], 'decision_id': job['id'], 'work_id': job['work_id'], 'version_id': job['candidate_id'], 'title': plan['source']['title'] or work['title'], 'format': plan['source']['format'], 'scope': plan['scope'], 'whole_work': plan['whole_work'], 'mode': plan['selection']['mode'], 'plan_hash': digest(plan), 'status': 'pending',
                'archive': {'status': 'pending', 'scope': 'local_snapshot'}, 'project_archive': {'status': 'pending'}, 'sync': {'status': 'not_verified'}, 'publications': [], 'created_at': now,
                '_plan': plan, '_files': selected + attachments, '_transcript': transcript}
        return self._put(c, item)

    def _verify_or_copy_snapshot(self, item):
        directory = (self.root / 'data/completions' / ident(item['decision_id'])).resolve()
        if not directory.is_relative_to(self.root / 'data/completions'):
            raise ValueError('完成快照目录无效')
        documents = {'内容原文.json': pack({key: item['_plan']['source'][key] for key in ('title', 'body', 'author', 'locked_fields', 'format')}).encode('utf-8'),
                     '完整过程.json': pack(item['_transcript']).encode('utf-8'),
                     '采纳方案.json': pack({'decision_id': item['decision_id'], 'plan_hash': item['plan_hash'], **self._preview_public(item['_plan'])}).encode('utf-8')}
        entries = []
        for relative, raw in documents.items():
            _write_once(directory / relative, raw)
            entries.append({'path': relative, 'sha256': digest(raw), 'size': len(raw)})
        for entry in item['_files']:
            destination = directory / entry['relative_path']
            raw = destination.read_bytes() if destination.is_file() else pathlib.Path(entry['source_path']).read_bytes()
            if digest(raw) != entry['sha256']:
                raise CompletionConflict('采纳时冻结的原文件字节已变化，未复制变化后的文件')
            _write_once(destination, raw)
            entries.append({'path': entry['relative_path'], 'sha256': entry['sha256'], 'size': len(raw)})
        manifest = {'schema_version': 1, 'decision_id': item['decision_id'], 'work_id': item['work_id'], 'version_id': item['version_id'], 'plan_hash': item['plan_hash'], 'files': entries}
        raw = pack(manifest).encode('utf-8')
        _write_once(directory / '完成清单.json', raw)
        for entry in entries:
            if digest((directory / entry['path']).read_bytes()) != entry['sha256']:
                raise CompletionConflict('完成快照副本校验失败，未登记为已保存')
        return {'status': 'verified', 'scope': 'local_snapshot', 'path': str(directory), 'manifest_sha256': digest(raw), 'file_count': len(entries), 'verified_at': stamp()}

    def process(self, decision_id):
        """Only local bytes + durable queue writes; never calls a platform."""
        ident(decision_id)
        with self.store.connect() as c:
            item = self._get(c, decision_id)
        if not item:
            return None
        try:
            archive = self._verify_or_copy_snapshot(item)
            with self.store.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                item = self._get(c, decision_id)
                item['archive'] = archive
                self._put(c, item)
            # Archive verification is its own completed fact. A blocked target
            # must not turn a successfully verified byte copy into a failure.
            with self.store.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                item = self._get(c, decision_id)
                current = c.execute("SELECT id,kind FROM toolbox_jobs WHERE work_id=? AND kind IN ('accept','reject') ORDER BY rowid DESC LIMIT 1", (item['work_id'],)).fetchone()
                if not current or current['id'] != decision_id or current['kind'] != 'accept':
                    # A later review can stop future work. It cannot erase a
                    # user's already-received statement that a specific copy
                    # was actually published. Preserve only that frozen fact;
                    # draft targets and all automatic deliveries remain off.
                    if item['whole_work'] and not item.get('_historical_manual_recorded'):
                        for manual in item['_plan']['selection']['manual_publications']:
                            if manual['status'] != 'published':
                                continue
                            publication = self.studio.create_completion_publication(c, decision_id=decision_id, work_id=item['work_id'], version_id=item['version_id'], source_snapshot=item['_plan']['source'], manual=manual, allow_historical=True)
                            if 'publication' in publication:
                                publication = publication['publication']
                            item['publications'].append({'publication_id': publication['id'], 'channel_id': publication['channel_id'], 'account': publication['account'], 'status': publication['status'], 'action': 'manual'})
                        item['publications'] = list({row['publication_id']: row for row in reversed(item['publications'])}.values())[::-1]
                        item['_historical_manual_recorded'] = True
                    item['status'] = 'superseded'
                    return self._public(self._put(c, item), c)
                if item.get('_orchestrated'):
                    return self._public(self._put(c, item), c)
                selection = item['_plan']['selection']
                if item['whole_work']:
                    # User-confirmed historical publication is a fact. Create
                    # it first so the delivery guard can avoid publishing the
                    # same version/account again in a mixed-target plan.
                    for manual in selection['manual_publications']:
                        publication = self.studio.create_completion_publication(c, decision_id=decision_id, work_id=item['work_id'], version_id=item['version_id'], source_snapshot=item['_plan']['source'], manual=manual)
                        if 'publication' in publication:
                            publication = publication['publication']
                        item['publications'].append({'publication_id': publication['id'], 'channel_id': publication['channel_id'], 'account': publication['account'], 'status': publication['status'], 'action': 'manual'})
                    if selection['targets']:
                        frozen = item['_plan']['distribution']
                        result = self.distribution.complete_adoption(c, decision_id=decision_id, work_id=item['work_id'], version_id=item['version_id'], accepted_scopes=item['scope'], source_fingerprint=frozen['source_fingerprint'], targets=frozen['targets'], actor='owner')
                        item['publications'].extend(self._publication_rows(result))
                        item['dispatch_result'] = {key: copy.deepcopy(result.get(key, [])) for key in ('skipped', 'blocked')}
                item['publications'] = list({row['publication_id']: row for row in reversed(item['publications'])}.values())[::-1]
                item['_orchestrated'] = True
                item['status'] = 'needs_attention' if item.get('dispatch_result', {}).get('blocked') else 'ready'
                item.pop('error', None)
                return self._public(self._put(c, item), c)
        except Exception as exc:
            with self.store.connect() as c:
                c.execute('BEGIN IMMEDIATE')
                item = self._get(c, decision_id)
                item['status'] = 'needs_attention'
                if item['archive']['status'] != 'verified':
                    item['archive'] = {'status': 'failed', 'scope': 'local_snapshot', 'error': str(exc)[:800]}
                item['error'] = str(exc)[:800]
                return self._public(self._put(c, item), c)

    @staticmethod
    def _publication_rows(result):
        deliveries = result.get('deliveries', [])
        return [{'publication_id': row['id'], 'channel_id': row['channel_id'], 'account': row['account'], 'status': row['status'], 'action': next((delivery.get('action') for delivery in deliveries if delivery.get('publication_id') == row['id']), 'draft'), **({'delivery_id': next(delivery['id'] for delivery in deliveries if delivery.get('publication_id') == row['id'])} if any(delivery.get('publication_id') == row['id'] for delivery in deliveries) else {})} for row in result.get('publications', [])]

    def resume_pending(self, limit=3):
        with self.store.connect() as c:
            ids = [row['decision_id'] for row in c.execute("SELECT decision_id FROM toolbox_completions WHERE json_extract(document,'$.status')='pending' ORDER BY created_at,rowid LIMIT ?", (limit,))]
        for decision_id in ids:
            self.process(decision_id)

    @staticmethod
    def archive_decision_id(job):
        if job['kind'] != 'archive':
            return job['id']
        try:
            return ident(json.loads(job['signature'])['completion_decision_id'])
        except (ValueError, KeyError, TypeError):
            raise CompletionConflict('归档任务缺少原采纳操作标识')

    def retry_archive(self, wid, decision_id, value):
        """Explicit archive-only recovery; no new review or platform approval."""
        wid, decision_id = ident(wid), ident(decision_id)
        if not isinstance(value, dict) or set(value) - {'id', 'operation_id', 'plan_hash'}:
            raise ValueError('归档恢复参数无效')
        operation_id = ident(value.get('id') or value.get('operation_id'))
        signature = pack({'work_id': wid, 'decision_id': decision_id, 'request': value})
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM toolbox_completion_ops WHERE id=?', (operation_id,)).fetchone()
            if old:
                if old['signature'] != signature:
                    raise CompletionConflict('同一归档恢复操作不能用于不同材料')
                return json.loads(old['result'])
            item = self._get(c, decision_id)
            if not item or item['work_id'] != wid or value.get('plan_hash') != item['plan_hash']:
                raise CompletionConflict('采纳快照不符，请核对原归档记录')
            active_rows = list(c.execute("SELECT * FROM toolbox_jobs WHERE work_id=? AND kind IN ('accept','archive') AND (status IN ('queued','dispatching','running','uncertain','needs_desktop','parked') OR (status='error' AND dispatch_started=1 AND finished_at IS NULL)) ORDER BY rowid DESC", (wid,)))
            # A work may have several independent adoption decisions. Only an
            # archive attempt linked to this exact decision is its original;
            # another active decision merely makes this work temporarily busy.
            related = lambda row: row['id'] == decision_id or row['kind'] == 'archive' and self.archive_decision_id(row) == decision_id
            active = next((row for row in active_rows if related(row)), None)
            if active:
                result = {'id': active['id'], 'work_id': wid, 'status': active['status'], 'decision_id': decision_id, 'message': '原归档任务仍在处理或核对回执，未重复提交'}
            elif active_rows:
                original = next((row for row in c.execute("SELECT * FROM toolbox_jobs WHERE id=? OR (work_id=? AND kind='archive') ORDER BY rowid DESC", (decision_id, wid)) if related(row)), None)
                result = {'id': original['id'] if original else decision_id, 'work_id': wid, 'status': 'blocked', 'decision_id': decision_id,
                          'original_job_status': original['status'] if original else None, 'blocking_job_id': active_rows[0]['id'],
                          'message': '本作品另一个归档任务仍在处理或核对，请待其结束后重试；该任务不属于本次原采纳，未重复提交'}
            elif item['project_archive']['status'] == 'verified':
                result = {'id': operation_id, 'work_id': wid, 'status': 'completed', 'decision_id': decision_id, 'message': '项目归档已经核验，无需重复执行'}
            else:
                if c.execute('SELECT 1 FROM toolbox_jobs WHERE id=?', (operation_id,)).fetchone():
                    raise CompletionConflict('归档恢复标识已被其他操作使用')
                now = stamp()
                job_signature = pack({'completion_decision_id': decision_id, 'plan_hash': item['plan_hash'], 'request': value})
                from easel_workbench.runtime.local_operations import queue_action
                c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,candidate_id,scope,files,signature,status,created_at,finished_at,reply) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                          (operation_id, wid, 'archive', '仅恢复采纳操作 ' + decision_id + ' 的归档；保留其后最新决定，不重复分发。', item['version_id'], pack(item['scope']), '[]', job_signature, 'completed', now, now, '系统已受理本地归档恢复。'))
                queue_action(c,dict(c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(operation_id,)).fetchone()))
                item['project_archive'] = {'status': 'pending', 'job_id': operation_id}
                self._put(c, item)
                result = {'id': operation_id, 'work_id': wid, 'status': 'completed', 'decision_id': decision_id, 'message': '系统已受理本地归档恢复'}
            c.execute('INSERT INTO toolbox_completion_ops VALUES(?,?,?)', (operation_id, signature, pack(result)))
        # A failed local file copy can be recovered independently. Enqueued
        # remote intents already have durable IDs and are never sent here.
        self.process(decision_id)
        return result

    def archive_instructions(self, decision_id):
        with self.store.connect() as c:
            item = self._get(c, decision_id)
            original = c.execute('SELECT rowid AS accepted_sequence,* FROM toolbox_jobs WHERE id=?', (decision_id,)).fetchone()
            latest = c.execute("SELECT rowid AS accepted_sequence,* FROM toolbox_jobs WHERE work_id=? AND kind IN ('accept','reject') ORDER BY rowid DESC LIMIT 1", (item['work_id'],)).fetchone() if item else None
        if not item:
            return ''
        path = self.root / 'data/completions' / ident(decision_id)
        original_context = {key: original[key] for key in ('id', 'kind', 'candidate_id', 'scope', 'created_at', 'accepted_sequence')} if original else {'id': decision_id}
        latest_context = {key: latest[key] for key in ('id', 'kind', 'candidate_id', 'scope', 'created_at', 'accepted_sequence')} if latest else None
        superseded = not latest or latest['id'] != decision_id or latest['kind'] != 'accept'
        decision_context = ('\n原采纳决定（created_at为实际受理时间；先后以accepted_sequence为准）：' + pack(original_context) +
                            '\n派发时当前最新决定：' + pack(latest_context) +
                            '\n当前最新决定的完整用户原话：\n' + (latest['text'] if latest else '未取得；不得推定为采纳') + '\n')
        boundary = ('本次原采纳已被较后决定替代：仅保存历史采纳成品及过程，不调用 decide 把它设为当前，不新建采用事件，不改写当前决定状态。当前结果以较后实际受理的明确决定为准，保留其完整原话、版本和范围。' if superseded else
                    '本次仅处理上述原采纳决定与原始范围；完成前仍须核对项目中是否已有较后决定。已有较后决定时只能保存历史，不能把本次旧采纳重新设为当前。')
        return ('\n工作台完成快照已按真实用户决定冻结；不要重新制作、不要从最新版本取代本次版本。快照目录：' + str(path) +
                '\n按 neo-content 现行存档规范，将本次实际采纳范围的成品、完整过程和原始附件纳入其既有唯一标题目录；保留已归档、已发布及其他版本。不得创建并行标题目录。'
                '\n在正确内容目录下新增不覆盖历史的“产物/工作台-' + decision_id + '”快照，逐字节复制上述快照全部文件，保留“完成清单.json”；补齐实际内容档案、进度和反馈入口，缺失材料明确注明，不补造图片提示词、目视检查或来源。'
                '\n在内容档案中明确关联工作台作品ID ' + item['work_id'] + '、版本ID ' + item['version_id'] + ' 及本次完成清单入口；已有不同作品的档案不能借用。'
                '\n完成后在最终回复附独立JSON：{"completion_archive":{"schema_version":1,"decision_id":"' + decision_id + '","directory":"实际项目内快照绝对路径","manifest_sha256":"完成清单.json实际SHA-256"}}。'
                '\n服务端会核查路径、全部原字节、项目档案/反馈/进度是否真实存在；AI回合结束不代表归档或Git同步成功。这里只处理项目归档，不要调用平台发布，分发由工作台独立队列按已确认方案执行。' +
                decision_context + '\n归档决定强约束：' + boundary)

    def verify_project_archive(self, decision_id, reply):
        with self.store.connect() as c:
            item = self._get(c, decision_id)
        if not item:
            return None
        receipt = None
        for block in [reply, *re.findall(r'```(?:json)?\s*\n(.*?)\n```', reply or '', re.S)]:
            try:
                parsed = json.loads(block)
            except (ValueError, TypeError):
                continue
            if isinstance(parsed, dict) and isinstance(parsed.get('completion_archive'), dict):
                receipt = parsed['completion_archive']
                break
        try:
            if not receipt or receipt.get('schema_version') != 1 or receipt.get('decision_id') != decision_id:
                raise CompletionConflict('归档答复缺少本次决定的可核验清单，请补充归档回执；不重发平台')
            directory = pathlib.Path(receipt.get('directory', '')).resolve()
            content_root = (self.project / '内容').resolve()
            if directory == content_root or not directory.is_relative_to(content_root) or len(directory.relative_to(content_root).parts) < 3:
                raise CompletionConflict('归档目录必须位于本项目既有内容的版本目录内')
            manifest_path = directory / '完成清单.json'
            raw = manifest_path.read_bytes()
            local = self.root / 'data/completions' / decision_id / '完成清单.json'
            if raw != local.read_bytes() or digest(raw) != receipt.get('manifest_sha256') or digest(raw) != item['archive'].get('manifest_sha256'):
                raise CompletionConflict('项目归档清单与本次冻结清单不一致')
            manifest = json.loads(raw)
            for entry in manifest['files']:
                path = (directory / entry['path']).resolve()
                if not path.is_relative_to(directory) or digest(path.read_bytes()) != entry['sha256']:
                    raise CompletionConflict('项目归档的原文件字节未通过核对')
            item_directory = content_root / directory.relative_to(content_root).parts[0]
            for name in ('内容档案.md', '进度.md', '反馈.md'):
                path = item_directory / name
                if not path.is_file() or not path.read_text(encoding='utf-8-sig').strip():
                    raise CompletionConflict('项目归档缺少实际档案、进度或完整反馈入口')
            catalog = (item_directory / '内容档案.md').read_text(encoding='utf-8-sig')
            if item['work_id'] not in catalog or item['version_id'] not in catalog or '完成清单.json' not in catalog:
                raise CompletionConflict('内容档案尚未关联本作品、本版本和完成清单，不能借用其他作品档案')
            with self.store.connect() as c:
                latest = c.execute("SELECT id,kind,candidate_id FROM toolbox_jobs WHERE work_id=? AND kind IN ('accept','reject') ORDER BY rowid DESC LIMIT 1", (item['work_id'],)).fetchone()
            metadata = {'status': 'not_recorded', 'expected_decision_id': latest['id'] if latest else None}
            state_file = (item_directory / '决定状态.json').resolve()
            per_work_state = (item_directory / '工作台状态' / ('作品-' + item['work_id'] + '.json')).resolve()
            if per_work_state.is_relative_to(item_directory) and per_work_state.is_file():
                state_file = per_work_state
            if state_file.is_relative_to(item_directory) and state_file.is_file():
                try:
                    actual = json.loads(state_file.read_text(encoding='utf-8-sig'))
                    expected_kind = 'accepted' if latest and latest['kind'] == 'accept' else 'rejected'
                    metadata.update(status='verified' if latest and actual.get('id') == latest['id'] and actual.get('decision') == expected_kind else 'needs_review', actual_decision_id=actual.get('id'))
                except (ValueError, OSError):
                    metadata.update(status='needs_review')
            status = {'status': 'verified', 'path': str(directory), 'manifest_sha256': digest(raw), 'file_count': len(manifest['files']), 'verified_at': stamp(), 'coverage': '已核对工作台可取得的完整过程、原始附件与本次采纳文件；缺失材料不补造', 'decision_metadata': metadata}
        except Exception as exc:
            status = {'status': 'failed', 'error': str(exc)[:800], 'next_action': '补齐项目归档与本次清单回执后重新核验；不重复制作或分发'}
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            item = self._get(c, decision_id)
            # Keep past verification as evidence without presenting it as a
            # current successful check when the bytes subsequently changed.
            previous = item['project_archive']
            if previous.get('status') == 'verified' and status['status'] != 'verified':
                status['previous_verification'] = previous
            item['project_archive'] = status
            return self._public(self._put(c, item), c)


def service(box):
    result = getattr(box, 'completion', None)
    if not isinstance(result, CompletionService):
        result = CompletionService(box)
        box.completion = result
    return result
