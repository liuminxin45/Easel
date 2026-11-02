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

from easel_workbench.features.evidence.records import POLICY_PATH, CONDITIONS, RELATIONSHIPS, TERMINAL, TEXT_SUFFIXES, MEDIA_SUFFIXES, SECRET_NAME, SECRET_TEXT, FORBIDDEN_PARTS, packed, sha, stamp, identity, bounded, atomic_bytes, original_mime, LearningConflict


















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
        from easel_workbench.features.evidence.storage import EvidenceRecords
        from easel_workbench.features.evidence.index import EvidenceIndex
        from easel_workbench.features.evidence.rules import EvidenceRules
        self.records=EvidenceRecords()
        self.index=EvidenceIndex(store=self.store,project=self.project,records=self.records,wake_event=self.wake_event,enqueue=lambda *a,**k:self._enqueue(*a,**k))
        self.rules=EvidenceRules(store=self.store,index=self.index,records=self.records)
        with self.store.connect() as c:
            from easel_workbench.infrastructure.storage.schema import initialize_evidence
            initialize_evidence(c)
            from easel_workbench.runtime.batch_learning import BatchLearning
            self.batch = BatchLearning(self)
            self.index.batch=self.batch
            self.batch.migrate(c)
            from easel_workbench.runtime.creative_recipes import CreativeRecipes
            CreativeRecipes(self).initialize(c)

    def _safe_path(self, relative):
        return self.index._safe_path(relative)

    def policy(self):
        return self.rules.policy()

    def _conditions(self, value):
        return self.rules._conditions(value)

    def _validate_entry(self, entry):
        return self.rules._validate_entry(entry)

    def _validate_policy(self, document):
        return self.rules._validate_policy(document)

    def _all(self, c, table):
        return self.records._all(c, table)

    def _get(self, c, table, key, required=True):
        return self.records._get(c, table, key, required)

    def _put(self, c, table, document):
        return self.records._put(c, table, document)

    def _search_text(self, c, evidence, body):
        return self.index._search_text(c, evidence, body)

    def _table_exists(self, c, name):
        return self.index._table_exists(c, name)

    def _metadata_file(self, path):
        return self.index._metadata_file(path)

    def _upsert_evidence(self, c, kind, title, raw_sha, source, size=0, available=True, missing_reason=None):
        return self.index._upsert_evidence(c, kind, title, raw_sha, source, size, available, missing_reason)

    def _file_candidates(self):
        return self.index._file_candidates()

    def _source_rows(self, c):
        return self.index._source_rows(c)

    def _index(self, c):
        return self.index._index(c)

    def _coverage(self, c):
        return self.index._coverage(c)

    def _processing_state(self, c):
        return self.index._processing_state(c)

    def _save_processing(self, c, state):
        return self.index._save_processing(c, state)

    def processing_status(self, connection=None):
        return self.index.processing_status(connection)

    def _finish_history_budget(self, c, task):
        return self.index._finish_history_budget(c, task)

    def index_database(self, connection=None):
        return self.index.index_database(connection)

    def watch_fingerprint(self):
        return self.index.watch_fingerprint()

    def queue_index_refresh(self, fingerprint=None):
        return self.index.queue_index_refresh(fingerprint)

    def list_evidence(self, query='', kind='', page=1, page_size=30):
        return self.index.list_evidence(query, kind, page, page_size)

    def _evidence_summary(self, row):
        return self.index._evidence_summary(row)

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
        return self.index._read_locator(c, source)

    def evidence_content(self, c, key):
        return self.index.evidence_content(c, key)

    def original_file(self, key):
        return self.index.original_file(key)

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
        return self.rules._disjoint(left, right)

    def relationship(self, a, b):
        return self.rules.relationship(a, b)

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
        return self.rules._match(conditions, context)

    def _required_ref(self, c, ref):
        return self.rules._required_ref(c, ref)

    def resolve(self, connection, wid, vid=None, creation=None, context=None):
        return self.rules.resolve(connection, wid, vid, creation, context)

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
