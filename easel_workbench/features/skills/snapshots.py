"""Creator identities and explicit, immutable capability releases.

This module performs local transactions only. A skill is a versioned instruction
and resource package; it is not a claim that a model or a publisher has run.
"""
from __future__ import annotations

import copy
import difflib
import hashlib
import io
import json
import mimetypes
import os
import pathlib
import re
import uuid
import warnings
import zipfile

from easel_workbench.runtime.desk import PROJECT, stamp
from easel_workbench.skills import (
    RETIRED_EASEL_SKILLS, RETIRED_TASKS, TASK_DEFAULTS, launch_metadata,
    require_selection, require_task, task_policy,
)

from easel_workbench.features.skills.records import DEFAULT_PROFILE, MANIFEST, MAX_PROMPT, MAX_RESOURCE, CreatorConflict, packed, digest, key, text, validate_package

class SnapshotResolver:
    def __init__(self, *, store, profile, skill):
        self.store=store
        self._profile=profile
        self._skill=skill

    def resolve(self, profile_id=DEFAULT_PROFILE, task='poster', skill_refs=None, allow_trial=False, profile_revision=None, c=None, allow_historical_profile=False, context=None):
        if c is None:
            with self.store.connect() as connection:
                return self.resolve(profile_id, task, skill_refs, allow_trial, profile_revision, connection, allow_historical_profile, context)
        if profile_revision is not None and (type(profile_revision) is not int or profile_revision < 1):
            raise ValueError('画像修订号无效')
        profile = self._profile(c, profile_id, profile_revision if allow_historical_profile else None)
        if profile_revision is not None and profile_revision != profile['revision']:
            raise CreatorConflict('画像已有新修订，请核对后再制作')
        if not profile.get('active', True):
            raise ValueError('创作画像已停用')
        if task not in TASK_DEFAULTS:
            raise ValueError('没有对应的显式任务能力')
        refs = skill_refs if skill_refs is not None else profile.get('default_skills', {}).get(task, TASK_DEFAULTS[task])
        if not isinstance(refs, list) or not refs or len(refs) > 8:
            raise ValueError('请选择1至8项制作技能')
        skills, seen = [], set()
        for ref in refs:
            ref = {'id': ref} if isinstance(ref, str) else ref
            if not isinstance(ref, dict) or set(ref) - {'id', 'version'}:
                raise ValueError('技能引用无效')
            sid = key(ref.get('id'))
            if sid in RETIRED_EASEL_SKILLS:raise ValueError('此技能已撤下；历史版本保留，新任务请选择已注册技能')
            if sid in seen:
                raise ValueError('同一技能不能重复加入')
            seen.add(sid)
            selected_version = ref.get('version')
            if selected_version is None:
                selected_version = profile.get('task_skill_versions', {}).get(task, {}).get(sid, profile.get('skill_versions', {}).get(sid))
            release = self._skill(c, sid, selected_version)
            require_task(release, task)
            if release['status'] != 'published' and not allow_trial:
                raise ValueError('候选技能需要明确选择本次试用')
            for resource in release.get('resources', []):
                if resource.get('required') and not resource.get('available'):
                    raise ValueError('技能必要资源缺失')
            skills.append({k: copy.deepcopy(v) for k, v in release.items() if k not in ('history', 'diff', 'base_prompt', 'published_version', 'is_current')})
        require_selection(task, seen)
        lines = ['以下是本次已选技能版本的完整冻结正文；磁盘入口用于发现，不得用当前磁盘或最新默认版本替换已冻结指令。已提供冻结规范与资产时使用该版本，原路径只是来源索引。本轮明确要求优先于技能默认；保留事实、原字和授权边界。', '## 本次创作画像：' + profile['name'],
                 '\n'.join(label + '：' + profile.get(field, '') for field, label in [('identity', '身份'), ('audience', '读者'), ('voice', '表达'), ('boundaries', '边界')])]
        if profile['id'] == DEFAULT_PROFILE and profile.get('source', {}).get('content'):
            lines.append('## 油猪大侠画像的定位依据\n' + profile['source']['content'])
        if task in ('poster', 'article', 'change', 'image') and profile.get('asset_refs'):
            refs = []
            for resource in profile['asset_refs']:
                if resource.get('required') and not resource.get('available'):
                    raise ValueError('画像必要参考资产未取得，尚未启动制作')
                if resource.get('required'):
                    blob = c.execute('SELECT bytes FROM creator_skill_blobs WHERE sha256=?', (resource.get('sha256'),)).fetchone()
                    if not blob or digest(bytes(blob['bytes'])) != resource['sha256']:
                        raise CreatorConflict('画像冻结参考资产缺失或字节不符，尚未启动制作')
                refs.append({k: copy.deepcopy(resource[k]) for k in ('path', 'sha256', 'available', 'required', 'role', 'label', 'kind') if k in resource})
            lines.append('## 当前画像明确绑定的参考资产\n' + packed(refs) + '\n仅在本轮用途适用时使用；原件字节不符时使用本任务的冻结副本，不借用其他画像的角色或署名。')
        for skill in skills:
            if skill.get('executor') == 'workflow':
                skill['execution_role'] = 'workflow_entry'
                lines.append('## 程序编排入口\n' + skill['name'] + ' v' + str(skill['version']) + ' 已冻结登记；由工作流服务编排所选子技能，本入口不新增模型调用。')
                continue
            skill['execution_role'] = 'active'
            available_context = {**(context or {}), 'format': (context or {}).get('format', task if task in ('poster', 'article') else 'poster' if task == 'image' else None)}
            active_rules, rule_states = [], []
            for rule in skill.get('baseline_rules', []):
                matches = profile['id'] == rule.get('creator_profile_id')
                reason = '当前画像匹配' if matches else '属于另一创作画像'
                for field, expected in rule.get('conditions', {}).items():
                    actual = available_context.get(field)
                    allowed = expected if isinstance(expected, list) else [expected]
                    if actual is None or actual not in allowed:
                        matches = False
                        reason = '条件未明确或不匹配：' + field
                        break
                rule_states.append({'id': rule['id'], 'active': matches, 'conditions': rule.get('conditions', {}), 'reason': reason, 'provenance': rule['provenance']})
                if matches:
                    active_rules.append(rule)
            skill['baseline_state'] = rule_states
            skill['applied_baseline_ids'] = [rule['id'] for rule in active_rules]
            if active_rules:
                lines.append('## 本技能已确认基线（随当前技能版本冻结；条件不匹配的不采用）\n' + '\n\n'.join('### ' + rule['id'] + '\n' + '\n'.join(rule['instructions']) for rule in active_rules))
            lines.append('## 显式技能：' + skill['name'] + ' v' + str(skill['version']) + '\n' + skill['prompt'])
            for resource in skill['resources']:
                if resource.get('content') and resource.get('scope') != 'on-demand':
                    lines.append('### 冻结资源：' + resource['path'] + '\n' + resource['content'])
        result = {'schema_version': 1, 'task': task, 'profile': copy.deepcopy(profile), 'skills': skills,
                  'account_ids': list(profile.get('account_ids', [])), 'prompt_text': '\n\n'.join(lines),
                  'trial': bool(allow_trial and any(s['status'] != 'published' for s in skills)),
                  'active_skill_ids': [s['id'] for s in skills if s['execution_role'] == 'active']}
        result['snapshot_sha256'] = digest(packed(result))
        return result
