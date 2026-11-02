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
from contextvars import ContextVar

_compilation_work=ContextVar('workbench_compilation_work',default=None)

@contextlib.contextmanager
def compilation_work(work):
    """Trusted prepared-work scope for nested production context readers, not HTTP input."""
    token=_compilation_work.set(work)
    try:yield
    finally:_compilation_work.reset(token)

from easel_workbench.runtime.feedback_ledger import locked

from easel_workbench.features.evidence.records import POLICY_PATH, CONDITIONS, RELATIONSHIPS, TERMINAL, TEXT_SUFFIXES, MEDIA_SUFFIXES, SECRET_NAME, SECRET_TEXT, FORBIDDEN_PARTS, packed, sha, stamp, identity, bounded, atomic_bytes, original_mime, LearningConflict

class EvidenceRules:
    def __init__(self, *, store, index, records):
        self.store=store
        self._all=records._all
        self._safe_path=index._safe_path
        self._table_exists=index._table_exists
        self.evidence_content=index.evidence_content

    def policy(self):
        path = self._safe_path(POLICY_PATH)
        raw = path.read_bytes() if path.is_file() else None
        document = json.loads(raw.decode('utf-8-sig')) if raw is not None else {'schema_version': 2, 'revision': 0, 'methods': [], 'profiles': []}
        for collection in ('methods','profiles'):
            for entry in document.get(collection,[]):
                if entry.get('prompt_file'):
                    content=self._safe_path(entry['prompt_file']).read_bytes()
                    if sha(content)!=entry.get('prompt_sha256'):raise LearningConflict('风格提示词原件已变化，请核对修订后继续')
                    from easel_workbench.runtime.creative_policy_files import instructions_from_file
                    entry['instructions']=instructions_from_file(entry,content)
        self._validate_policy(document)
        return {'path': POLICY_PATH, 'revision': sha(raw) if raw is not None else None,
                'revision_number': document['revision'], 'available': raw is not None, 'document': document}

    def _conditions(self, value):
        if not isinstance(value, dict) or set(value) - CONDITIONS:
            raise ValueError('适用条件仅支持明确的格式、渠道、主题、作品、版本、用途或图像角色')
        for item in value.values():
            if not (isinstance(item, str) and item.strip() or isinstance(item, list) and item and all(isinstance(x, str) and x.strip() for x in item)):
                raise ValueError('每个适用条件需要文本或文本列表')
        return value

    def _validate_entry(self, entry):
        if not isinstance(entry, dict):
            raise ValueError('策略条目无效')
        identity(entry.get('id'))
        bounded(entry.get('name', ''), 500, True)
        self._conditions(entry.get('conditions', {}))
        instructions = entry.get('instructions')
        if instructions is None and entry.get('prompt_file'):
            data=self._safe_path(entry['prompt_file']).read_bytes()
            if sha(data)!=entry.get('prompt_sha256'):raise LearningConflict('提示词文件指纹不一致')
            from easel_workbench.runtime.creative_policy_files import instructions_from_file
            instructions=instructions_from_file(entry,data)
        if not isinstance(instructions, list) or not 1 <= len(instructions) <= 40:
            raise ValueError('策略需要逐项实际指令')
        for instruction in instructions:
            bounded(instruction, 10000, True)
        if entry.get('status', 'confirmed') not in ('confirmed', 'candidate', 'retired'):
            raise ValueError('策略状态无效')
        if not isinstance(entry.get('evidence_refs', []), list):
            raise ValueError('策略证据引用无效')
        for ref in entry.get('evidence_refs', []):
            if isinstance(ref, str):
                if not ref.startswith('ev-'):
                    self._safe_path(ref)
            elif isinstance(ref, dict) and isinstance(ref.get('path'), str):
                self._safe_path(ref['path'])
            else:
                raise ValueError('策略证据须引用索引ID或项目原件')
        for key in ('excludes', 'requires'):
            if not isinstance(entry.get(key, []), list) or any(not isinstance(item, str) for item in entry.get(key, [])):
                raise ValueError('策略关系无效')
        if 'intent' in entry:
            from easel_workbench.runtime.semantic_style import intent
            intent(entry['intent'])
        if type(entry.get('priority', 0)) is not int or not 0 <= entry.get('priority', 0) <= 100:
            raise ValueError('策略优先级无效')
        if type(entry.get('revision', 1)) is not int or entry.get('revision', 1) < 1:
            raise ValueError('策略条目修订号无效')

    def _validate_policy(self, document):
        if not isinstance(document, dict) or document.get('schema_version') != 2 or type(document.get('revision')) is not int or document['revision'] < 0:
            raise ValueError('创作策略需要schema_version 2和明确修订号')
        for key in ('methods', 'profiles'):
            rows = document.get(key)
            if not isinstance(rows, list) or len(rows) > 1000:
                raise ValueError('创作策略集合无效')
            for row in rows:
                self._validate_entry(row)
            if len({row['id'] for row in rows}) != len(rows):
                raise ValueError('策略ID不能重复')
        all_ids = [row['id'] for row in document['methods'] + document['profiles']]
        if len(set(all_ids)) != len(all_ids):
            raise ValueError('方法与主风格必须使用不同ID')
        if len(packed(document)) > 2_000_000 or SECRET_TEXT.search(packed(document)):
            raise ValueError('策略过长或包含秘密')

    def _disjoint(self, left, right):
        for key in left.keys() & right.keys():
            if key == 'topic':
                # Different topic words can describe the same title/material;
                # their mere spelling is insufficient proof of disjoint scope.
                continue
            a = set(left[key] if isinstance(left[key], list) else [left[key]])
            b = set(right[key] if isinstance(right[key], list) else [right[key]])
            if not a & b:
                return True
        return False

    def relationship(self, a, b):
        if self._disjoint(a.get('conditions', {}), b.get('conditions', {})):
            return 'different_conditions'
        if b['id'] in a.get('excludes', []) or a['id'] in b.get('excludes', []):
            return 'mutually_exclusive'
        group_a, group_b = a.get('compatibility_group'), b.get('compatibility_group')
        if group_a and group_a == group_b:
            return 'composable'
        if a.get('dimension') and a.get('dimension') == b.get('dimension') and a.get('conditions', {}) == b.get('conditions', {}):
            return 'mutually_exclusive'
        if a.get('dimension') != b.get('dimension'):
            return 'composable'
        return 'insufficient_evidence'

    def _match(self, conditions, context):
        for key, wanted in conditions.items():
            actual = context.get(key)
            allowed = wanted if isinstance(wanted, list) else [wanted]
            actual_values = actual if isinstance(actual, list) else [actual]
            if key == 'topic':
                # A work title/material is routing evidence, never a rigid tag.
                # This bounded lexical match is visible in snapshot conditions;
                # it does not infer popularity, causal effects or approval.
                def topic_match(value, expected):
                    if not isinstance(value, str):
                        return False
                    normalized = value.casefold()
                    if expected in ('工具合集', 'tool_collection') and re.search(r'(?:不做|不要|不是|不采用)\s*(?:工具合集|tool_collection)', normalized):
                        return False
                    if expected.casefold() in normalized:
                        return True
                    if expected in ('工具合集', 'tool_collection'):
                        subject = bool(re.search(r'工具|项目|开源|github', normalized))
                        collection = bool(re.search(r'合集|清单|精选|推荐|盘点|[0-9一二三四五六七八九十]+[个款项种]', normalized))
                        rejected = bool(re.search(r'(?:不做|不要|不是|不采用)\s*(?:工具合集|tool_collection)', normalized))
                        return subject and collection and not rejected
                    return False
                if any(topic_match(item, expected) for item in actual_values for expected in allowed):
                    continue
                return False
            if not any(item in allowed for item in actual_values):
                return False
        return True

    def _required_ref(self, c, ref):
        key = ref if isinstance(ref, str) and ref.startswith('ev-') else None
        if key:
            try:
                row = self.evidence_content(c, key)
                return {k: row.get(k) for k in ('id', 'sha256', 'source', 'available', 'missing_reason', 'content', 'content_is_original', 'verified_source', 'binary_original')}
            except ValueError:
                return {'id': key, 'available': False, 'missing_reason': '索引ID没有对应原件'}
        path = ref if isinstance(ref, str) else ref.get('path')
        try:
            target = self._safe_path(path)
            raw = target.read_bytes()
            if target.suffix.lower() in TEXT_SUFFIXES and SECRET_TEXT.search(raw.decode('utf-8-sig', errors='replace')):
                raise ValueError('秘密不进入冻结证据')
            return {'id': 'ev-' + sha(raw), 'kind': 'source_reference', 'source': {'kind': 'file', 'path': path}, 'sha256': sha(raw), 'available': True,
                    'content': raw.decode('utf-8-sig') if target.suffix.lower() in TEXT_SUFFIXES else None, 'content_is_original': True}
        except (ValueError, OSError):
            return {'id': 'missing-' + sha(str(path).encode())[:32], 'source': {'kind': 'file', 'path': path}, 'available': False, 'missing_reason': '所引权威原件不可访问'}

    def resolve(self, connection, wid, vid=None, creation=None, context=None, *, pending_work=None):
        creation = copy.deepcopy(creation or {})
        context = copy.deepcopy(context or {})
        with self.store.connect() if connection is None else contextlib.nullcontext(connection) as c:
            policy = self.policy()
            document = policy['document']
            # Only semantic selectors are accepted. Arbitrary numeric style weights
            # neither confirm a research method nor resolve a contradiction.
            selection = {}
            for layer in (context.get('learning'), creation.get('learning')):
                if isinstance(layer, dict):
                    if layer.get('snapshot_id') or 'required_evidence' in layer:
                        # Studio context carries the resolved snapshot for
                        # display; it is not another user-selection layer.
                        continue
                    selection.update(layer)
            # The semantic creative contract uses these names; older frozen
            # versions remain readable without becoming a parallel source.
            for modern, legacy in (('profile_id', 'selected_profile_id'), ('include_ids', 'selected_method_ids'), ('exclude_ids', 'excluded_ids'), ('conflict_choices', 'conflict_resolutions')):
                if modern in selection:
                    selection[legacy] = selection[modern]
            for key in ('selected_method_ids', 'trial_method_ids', 'excluded_ids'):
                if not isinstance(selection.get(key, []), list) or any(not isinstance(v, str) for v in selection.get(key, [])):
                    raise ValueError('本轮学习策略选择无效')
            proposals = self._all(c, 'learning_proposals')
            candidate_ids = {row['id'] for row in proposals if row['status'] in ('candidate', 'preview') and row['kind'] == 'method'}
            candidate_ids.update(row['id'] for row in document['methods'] + document['profiles'] if row.get('status') == 'candidate')
            selected_candidates = [key for key in selection.get('selected_method_ids', []) if key in candidate_ids]
            if selection.get('selected_profile_id') in candidate_ids:
                selected_candidates.append(selection['selected_profile_id'])
            trial = list(dict.fromkeys([*selection.get('trial_method_ids', []), *selected_candidates]))
            if len(trial) > 2:
                raise ValueError('本次最多试用两项候选方法')
            workspace = creation.get('workspace', {})
            effective = context.get('effective', {})
            conditions = {'work_id': wid, 'version_id': vid, 'format': context.get('format', creation.get('format', 'poster')),
                          'channel': workspace.get('channel', effective.get('channel', context.get('channel', {}).get('id') if isinstance(context.get('channel'), dict) else context.get('channel')))}
            supplied = selection.get('conditions', {})
            self._conditions(supplied)
            conditions.update({key: value for key, value in supplied.items() if key not in ('work_id', 'version_id')})
            if selection.get('topic'):
                conditions['topic'] = bounded(selection['topic'], 10000, True)
            if selection.get('goal'):
                conditions['purpose'] = bounded(selection['goal'], 5000, True)
            for key in CONDITIONS - {'work_id', 'version_id', 'format', 'channel'}:
                if key in context:
                    conditions[key] = context[key]
            requested_profile = next((row for row in document['profiles'] if row['id'] == selection.get('selected_profile_id')), None)
            if requested_profile and 'visual_role' not in conditions:
                image_intent = creation.get('intent', {}).get('image') or requested_profile.get('intent', {}).get('image')
                role = {'scene': 'illustrative_scene', 'scene_diagram': 'illustrative_scene', 'typographic': 'typographic_cover', 'diagram': 'information_diagram'}.get(image_intent)
                if role:
                    conditions['visual_role'] = role
            rows = [('method', row) for row in document['methods']] + [('profile', row) for row in document['profiles']]
            candidates = proposals
            for proposal in candidates:
                if proposal['status'] in ('candidate', 'preview') and proposal['kind'] == 'method':
                    entry = {**proposal['document'], 'id': proposal['id'], 'status': 'candidate', 'evidence_refs': proposal['evidence_refs']}
                    rows.append(('method', entry))
            known = {row['id'] for _, row in rows}
            requested = set(selection.get('selected_method_ids', [])) | set(trial)
            profile_id = selection.get('selected_profile_id')
            if profile_id:
                requested.add(profile_id)
            if requested - known:
                raise ValueError('所选方法或风格已不存在，请重新核对')
            if profile_id and selection.get('profile_revision') is not None:
                profile = next((row for kind, row in rows if kind == 'profile' and row['id'] == profile_id), None)
                if not profile or selection['profile_revision'] != profile.get('revision', 1):
                    raise LearningConflict('所选主风格修订已变化，请核对最新条件')
            selected, excluded, conflicts = [], [], []
            explicit_excluded = set(selection.get('excluded_ids', []))
            profiles = []
            for kind, row in rows:
                rid = row['id']
                reason = None
                if row.get('status') == 'retired':
                    reason = '已退役，保留历史不参与本轮'
                elif rid in explicit_excluded:
                    reason = '本次明确不采用'
                elif row.get('status') == 'candidate' and rid not in trial:
                    reason = '候选尚未获长期确认，本轮也未明确试用'
                elif not self._match(row.get('conditions', {}), conditions):
                    reason = '适用条件与本篇不符或缺少条件证据'
                elif kind == 'method' and row.get('selection', 'automatic') == 'explicit' and rid not in requested:
                    reason = '该方法需本轮明确选择'
                if reason:
                    excluded.append({'id': rid, 'kind': kind, 'name': row['name'], 'reason': reason})
                    if rid in requested and rid not in explicit_excluded and row.get('status') != 'retired':
                        conflicts.append({'id': 'applicability-' + rid, 'kind': 'insufficient_evidence', 'ids': [rid], 'resolved': False,
                                          'reason': '本轮明确纳入项尚不满足适用条件：' + row['name'] + '；需补充条件或取消纳入'})
                else:
                    entry = {**copy.deepcopy(row), 'kind': kind, 'trial': row.get('status') == 'candidate',
                             'reason': '本轮明确试用候选' if rid in trial else '本轮明确选择' if rid in requested else '与本篇条件匹配的已确认策略'}
                    if kind == 'profile':
                        profiles.append(entry)
                    else:
                        selected.append(entry)
            if profile_id:
                chosen_profiles = [row for row in profiles if row['id'] == profile_id]
                for row in profiles:
                    if row['id'] != profile_id:
                        excluded.append({'id': row['id'], 'kind': 'profile', 'name': row['name'], 'reason': '本轮明确选择其它主风格，保留此风格适用条件'})
                profiles = chosen_profiles
            elif len(profiles) > 1:
                # A specific condition can refine a general profile only when the
                # canonical entry explicitly declares that relationship.
                refinements = [row for row in profiles if set(row.get('refines', [])) >= {other['id'] for other in profiles if other['id'] != row['id']}]
                if len(refinements) == 1:
                    winner = refinements[0]
                    for row in profiles:
                        if row['id'] != winner['id']:
                            excluded.append({'id': row['id'], 'kind': 'profile', 'name': row['name'], 'reason': '已确认的条件风格明确细化此基线：' + winner['name']})
                    profiles = [winner]
                else:
                    conflicts.append({'id': 'main-profile', 'kind': 'main_style', 'ids': [row['id'] for row in profiles], 'resolved': False,
                                      'reason': '多个主风格同时适用，需明确选择；不能按时间、指标或优先级猜测'})
            selected.extend(profiles)
            resolutions = selection.get('conflict_resolutions', {})
            if not isinstance(resolutions, dict):
                raise ValueError('冲突选择需要明确的冲突ID和采用方法ID')
            for index, left in enumerate(list(selected)):
                for right in list(selected)[index + 1:]:
                    if left['kind'] == right['kind'] == 'profile':
                        continue
                    relation = self.relationship(left, right)
                    if relation not in ('mutually_exclusive', 'insufficient_evidence'):
                        continue
                    cid = 'conflict-' + sha('|'.join(sorted([left['id'], right['id']])).encode())[:20]
                    pick = resolutions.get(cid)
                    resolved = pick in (left['id'], right['id'])
                    conflicts.append({'id': cid, 'kind': relation, 'ids': [left['id'], right['id']], 'resolved': resolved,
                                      'selected_id': pick if resolved else None, 'reason': '本轮条件重叠且指令可能相反，需明确采用项或补充条件'})
                    if resolved:
                        loser = right if pick == left['id'] else left
                        if loser in selected:
                            selected.remove(loser)
                            excluded.append({'id': loser['id'], 'kind': loser['kind'], 'name': loser['name'], 'reason': '本轮明确冲突选择采用：' + pick})
            selected_ids = {row['id'] for row in selected}
            for row in selected:
                dependencies = set(row.get('requires', [])) - selected_ids
                if dependencies:
                    conflicts.append({'id': 'requires-' + row['id'], 'kind': 'insufficient_evidence', 'ids': [row['id'], *sorted(dependencies)], 'resolved': False,
                                      'reason': '所选方法的必要配合项未纳入或条件不匹配：' + '、'.join(sorted(dependencies))})
            required, source_evidence = [], []
            for row in selected:
                references = [self._required_ref(c, ref) for ref in row.get('evidence_refs', [])]
                dimensions = {'visual': 'image', 'copy': 'text', 'expression': 'text', 'main_style': 'tone', 'review': 'style'}
                canonical = any(entry['id'] == row['id'] for entry in document['methods'] + document['profiles'])
                strategy_source = {'kind': 'canonical_strategy', 'path': POLICY_PATH, 'sha256': policy['revision'], 'entry_id': row['id'],
                                   'collection': 'methods' if row['kind'] == 'method' else 'profiles'} if canonical else {
                                       'kind': 'database', 'table': 'learning_proposals', 'record_id': row['id'], 'field': 'document'}
                required.append({'id': row['id'], 'kind': 'strategy_execution', 'dimension': dimensions.get(row.get('dimension'), row.get('dimension', 'style')),
                                 'text': '\n'.join(row['instructions']), 'conditions': copy.deepcopy(row.get('conditions', {})),
                                 'status': row.get('status', 'confirmed'), 'trial': row['trial'], 'available': True,
                                 'source': strategy_source,
                                 'source_evidence_ids': list(dict.fromkeys(item['id'] for item in references)),
                                 'reason': row['reason']})
                for item in references:
                    if item not in source_evidence:
                        source_evidence.append(item)
            annotations = context.get('_learning_annotations', [])
            if not isinstance(annotations, list):
                raise ValueError('本轮批注证据无效')
            for annotation in annotations:
                if not isinstance(annotation, dict) or not annotation.get('id'):
                    raise ValueError('本轮批注必须有明确标识')
                required.append({'id': annotation['id'], 'kind': 'current_annotation', 'source': {'kind': 'database', 'table': 'toolbox_review_notes', 'record_id': annotation['id'], 'field': 'document', 'work_id': wid, 'version_id': vid},
                                 'sha256': sha(packed(annotation).encode()), 'available': True, 'annotation': copy.deepcopy(annotation)})
            preferences = context.get('_learning_preference_evidence', [])
            if not isinstance(preferences, list):
                raise ValueError('历史偏好证据无效')
            included_preferences = []
            for note in preferences:
                if not isinstance(note, dict) or not note.get('id') or note.get('deleted'):
                    continue
                scope = note.get('scope')
                source_work = note.get('work_id')
                source_format = note.get('format')
                if scope == 'format' and source_format is None and source_work and self._table_exists(c, 'toolbox_work_options'):
                    found = c.execute('SELECT format FROM toolbox_work_options WHERE work_id=?', (source_work,)).fetchone()
                    source_format = found['format'] if found else None
                relevant = scope == 'global' or scope == 'work' and source_work == wid or scope == 'format' and source_format == conditions.get('format')
                if not relevant or not self._match(note.get('conditions', {}), conditions):
                    continue
                if note['id'] in {annotation['id'] for annotation in annotations}:
                    continue
                included_preferences.append(note)
                required.append({'id': note['id'], 'kind': 'scoped_preference_evidence', 'scope': scope,
                                 'source': {'kind': 'database', 'table': 'toolbox_review_notes', 'record_id': note['id'], 'field': 'document', 'work_id': source_work, 'version_id': note.get('candidate_id')},
                                 'sha256': sha(packed(note).encode()), 'available': True, 'annotation': copy.deepcopy(note),
                                 'reason': '原始意见按其明确范围与本篇条件相关；不自动覆盖长期策略或当前指令'})
            intent_evidence = context.get('_learning_intent_evidence', [])
            if not isinstance(intent_evidence, list):
                raise ValueError('本轮实际意图证据无效')
            for intent in intent_evidence:
                if not isinstance(intent, dict) or not intent.get('id') or not intent.get('dimension'):
                    raise ValueError('本轮意图证据需要准确标识和维度')
                bounded(intent.get('text', ''), 100000, True)
                required.append({**copy.deepcopy(intent), 'kind': intent.get('kind', 'semantic_intent'), 'available': True,
                                 'sha256': sha(packed(intent).encode()), 'source': {'kind': 'current_creation_intent', 'id': intent['id']}})
            raw_feedback = context.get('_learning_raw_feedback', [])
            for asset in context.get('_learning_recipe_assets',[]):
                if not asset.get('available'):continue
                identity='recipe-asset-'+asset['sha256'][:32]
                if any(item['id']==identity for item in source_evidence):continue
                source_evidence.append({'id':identity,'kind':'recipe_reference','available':True,'content':None,'sha256':asset['sha256'],
                    'source':{'kind':'file','path':asset['path']},'role':asset.get('role'),'label':asset.get('label')})
                required.append({'id':identity,'kind':'recipe_reference','dimension':'image','available':True,'text':'按用途使用真实参考：'+asset.get('label',asset['path']),
                    'source_evidence_ids':[identity],'sha256':asset['sha256'],'source':{'kind':'file','path':asset['path']}})
            if not isinstance(raw_feedback, list):
                raise ValueError('本作品原始反馈列表无效')
            seen_feedback = set()
            for original in raw_feedback:
                if not isinstance(original, dict) or not isinstance(original.get('id'), str) or not original['id'].startswith('raw-') or original['id'] in seen_feedback:
                    raise ValueError('原始反馈需要准确且唯一的操作标识')
                seen_feedback.add(original['id'])
                bounded(original.get('text', ''), 2_000_000)
                evidence = {**copy.deepcopy(original), 'kind': 'raw_user_feedback', 'available': True,
                            'content': original.get('text', ''), 'content_is_original': True,
                            'sha256': sha(packed(original).encode()), 'refinement_status': 'unrefined',
                            'reason': '未提炼，仅本作品相关版本链；历史决定不是本轮强制偏好，逐条说明适用或未用原因'}
                evidence.setdefault('source', {'kind': 'local_feedback_record', 'operation_id': original['id'][4:], 'work_id': wid})
                required.append(copy.deepcopy(evidence))
                source_evidence.append(copy.deepcopy(evidence))
            missing = [row for row in source_evidence if not row.get('available')]
            if missing:
                conflicts.append({'id': 'missing-evidence', 'kind': 'insufficient_evidence', 'ids': [], 'resolved': False,
                                  'reason': '所选方法引用原件缺失；不得编造原话或声称已经核对'})
            override_layers = []
            for scope, source in (('work', context.get('settings', {}).get('overrides', {})), ('round', context.get('settings', {}).get('round', {})), ('current_round', effective), ('request', workspace)):
                if not isinstance(source, dict):
                    continue
                text = source.get('style_guidance') or source.get('instructions')
                if text:
                    override_layers.append({'scope': scope, 'instructions': bounded(text, 100000, True) if isinstance(text, str) else '\n'.join(text)})
            for annotation in annotations:
                note = annotation.get('note')
                if note:
                    override_layers.append({'scope': 'current_annotation', 'annotation_id': annotation['id'], 'instructions': bounded(note, 10000, True)})
            for intent in intent_evidence:
                override_layers.append({'scope': 'current_request' if intent.get('kind') == 'current_request' else 'resolved_semantic_intent', 'evidence_id': intent['id'], 'dimension': intent['dimension'],
                                        'provenance': copy.deepcopy(intent.get('provenance')), 'instructions': intent['text']})
            work_context = None
            if wid and self._table_exists(c, 'toolbox_works'):
                # A trusted keyword port, never read from the HTTP context dictionary.
                work = pending_work if pending_work is not None else _compilation_work.get()
                if work is not None and work.get('id')!=wid:work=None
                if work is None:work = c.execute('SELECT id,title,material FROM toolbox_works WHERE id=?', (wid,)).fetchone()
                if work:
                    work_context = {'id': work['id'], 'title': work['title'], 'material': work['material'], 'source': {'kind': 'database', 'table': 'toolbox_works', 'record_id': wid}}
            direct = context.get('_learning_direct_context')
            if direct is not None:
                if not isinstance(direct, dict):
                    raise ValueError('直接回合的明确关联原件无效')
                for field in ('request', 'material'):
                    content = direct.get(field, '')
                    if not content:
                        continue
                    bounded(content, 2_000_000, True)
                    source_evidence.append({'id': 'direct-' + field + '-' + sha(content.encode())[:32], 'kind': 'bound_direct_input',
                                            'content': content, 'content_is_original': True, 'available': True, 'sha256': sha(content.encode()),
                                            'source': {'kind': 'bound_direct_context', 'binding_id': direct.get('binding_id'), 'field': field, 'actor': 'user',
                                                       'authority': 'explicitly_bound_current_turn_original'}})
                if work_context is None:
                    work_context = {'id': wid, 'title': direct.get('title', ''), 'material': direct.get('material', ''),
                                    'source': {'kind': 'bound_direct_context', 'binding_id': direct.get('binding_id'), 'actor': 'user'}}
            instructions = ['当前作品、当前回合和用户明确指令优先于条件风格；冲突要逐项保留并请明确选择。',
                            '候选分析仅供本轮所选试用；不写回长期规范，不以新时间、高流量或点赞覆盖既有风格。']
            unresolved = any(not row['resolved'] for row in conflicts)
            blocked_ids = {rid for conflict in conflicts if not conflict['resolved'] for rid in conflict.get('ids', [])}
            for row in selected:
                if row['id'] not in blocked_ids:
                    instructions.append(row['name'] + '：' + '\n'.join(row['instructions']))
            for row in override_layers:
                if row['scope'] == 'resolved_semantic_intent':
                    instructions.append('本轮生效意图（依据' + row['evidence_id'] + '，保留所列provenance，不推定全部来自用户）：' + row['instructions'])
                else:
                    instructions.append('当前明确指令（' + row['scope'] + '，优先）：' + row['instructions'])
            if included_preferences:
                instructions.append('读取required_evidence中按范围纳入的历史用户原话，结合本篇条件逐项说明采用或不采用理由；历史意见不自动升为长期策略，不以时间排序覆盖当前指令。')
            if raw_feedback:
                instructions.append('读取raw_user_feedback的完整原话、版本范围和决定历史：这些尚未提炼，仅限本作品相关版本链。逐条说明本次适用或未用原因；撤回、替代和相反意见保留身份，不能全部叠成强制要求。采纳不代表所有维度都好，不采纳也不代表所有维度都差；未填原因即未给出具体原因，不补造原话，不提升长期规则。')
            if unresolved:
                instructions.append('存在未解冲突：先保留冲突并明确适用条件，不得自动忽略或宣称已经执行相反的全部方法。')
            semantic_selection = {key: value for key, value in selection.items() if key not in ('revision_token', 'selected_method_ids', 'selected_profile_id', 'excluded_ids', 'conflict_resolutions')}
            semantic_selection.update(profile_id=profile_id, include_ids=selection.get('selected_method_ids', []), exclude_ids=selection.get('excluded_ids', []), conflict_choices=selection.get('conflict_resolutions', {}))
            token = sha(packed({'policy': policy['revision'], 'conditions': {key: value for key, value in conditions.items() if key not in ('work_id', 'version_id')},
                               'selection': semantic_selection, 'selected_ids': [row['id'] for row in selected],
                               'overrides': override_layers, 'evidence': required,
                               'sources': [{key: value for key, value in row.items() if key != 'content'} for row in source_evidence]}).encode())
            expected = creation.get('learning_revision') or selection.get('revision_token')
            if expected and expected != token:
                raise LearningConflict('学习策略或证据在确认后变化，请重新核对；未提交制作')
            result = {'schema_version': 2, 'snapshot_id': 'snapshot-' + token, 'revision_token': token,
                      'policy': {key: policy[key] for key in ('path', 'revision', 'revision_number', 'available')},
                      'work_id': wid, 'version_id': vid, 'conditions': conditions, 'selected': selected, 'excluded': excluded,
                      'conflicts': conflicts, 'decision_required': unresolved, 'required_evidence': required,
                      'source_evidence': source_evidence, 'profile': copy.deepcopy(profiles[0]) if len(profiles) == 1 else None,
                      'max_trial_candidates': 2, 'main_profile_id': profiles[0]['id'] if len(profiles) == 1 else None,
                      'main_style_reason': profiles[0]['reason'] if len(profiles) == 1 else '本轮主风格尚待明确' if profiles else '没有已确认且条件匹配的主风格',
                      'override_layers': override_layers, 'work_context': work_context, 'instructions': '\n\n'.join(instructions)}
            return result
