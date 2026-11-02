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












from easel_workbench.infrastructure.storage.schema import initialize_creator as initialize


class CreatorRuntime:
    def __init__(self, box, project=None, c=None):
        self.box = box
        self.store = box.store
        self.root = pathlib.Path(box.root)
        self.project = pathlib.Path(project or getattr(getattr(box, 'studio', None), 'project', PROJECT)).resolve()
        from easel_workbench.skill_catalog import ProjectSkillCatalog
        local=ProjectSkillCatalog(self.root)
        self.catalog=local if local.available() else None
        if self.catalog is not None:self.project=self.root.resolve()
        from easel_workbench.features.skills.releases import SkillReleases
        from easel_workbench.features.profiles.service import ProfileService
        from easel_workbench.features.skills.snapshots import SnapshotResolver
        self.releases=SkillReleases(store=self.store,root=self.root,project=self.project,catalog=self.catalog)
        self.profiles=ProfileService(store=self.store,root=self.root,skills=self.releases)
        self.snapshots=SnapshotResolver(store=self.store,profile=lambda *a,**k:self._profile(*a,**k),skill=lambda *a,**k:self._skill(*a,**k))
        if c is not None:
            initialize(c)
            self._seed(c)
        else:
            with self.store.connect() as connection:
                initialize(connection)
                self._seed(connection)

    def _safe(self, relative):
        return self.releases._safe(relative)

    def _profile(self, c, profile_id, revision=None):
        return self.profiles._profile(c, profile_id, revision)

    def _put_profile(self, c, profile):
        return self.profiles._put_profile(c, profile)

    def bind_work(self, c, work_id, selection=None, allow_historical=False):
        return self.profiles.bind_work(c, work_id, selection, allow_historical)

    def _seed(self, c):
        if not c.execute('SELECT 1 FROM creator_profiles WHERE id=?', (DEFAULT_PROFILE,)).fetchone():
            source = self._safe('规范/定位与编辑原则.md')
            raw = source.read_bytes() if source.is_file() else b''
            profile = {'id': DEFAULT_PROFILE, 'name': '油猪大侠', 'revision': 1,
                       'identity': '油猪大侠，亲自使用工具和制作东西的程序员。',
                       'audience': '持续关注 AI，希望看懂变化、看见可能、形成判断的读者。',
                       'voice': '清楚、克制、有依据；不移植他人经历和口头禅。',
                       'boundaries': '事实与判断分开，保留来源和适用范围。',
                       'default_skills': copy.deepcopy(TASK_DEFAULTS), 'account_ids': [], 'asset_refs': [],
                       'active': True, 'source': {'path': '规范/定位与编辑原则.md', 'sha256': digest(raw),
                       'content': raw.decode('utf-8-sig') if raw else '', 'available': bool(raw)},
                       'created_at': stamp(), 'updated_at': stamp()}
            self._put_profile(c, profile)
        if self.catalog is not None:
            document=self.catalog.document()
        else:
            manifest = self._safe(MANIFEST)
            if not manifest.is_file():return
            document = json.loads(manifest.read_text(encoding='utf-8-sig'))
        if document.get('schema_version') != 1 or not isinstance(document.get('skills'), list):
            raise ValueError('技能目录无效')
        for skill in document['skills'] + [s for s in document.get('candidates', []) if self._safe(s['entry']).is_file()]:
            sid = key(skill['id'])
            if c.execute('SELECT 1 FROM creator_skills WHERE id=?', (sid,)).fetchone():
                continue
            body = self._safe(skill['entry']).read_text(encoding='utf-8-sig')
            source_resources = copy.deepcopy(skill.get('resources', []))
            variants = []
            policy_path = self._safe('规范/创作策略.json')
            policy_raw = policy_path.read_bytes() if policy_path.is_file() else None
            policy = json.loads(policy_raw.decode('utf-8-sig')) if policy_raw else {}
            confirmed = []
            for collection in ('methods', 'profiles'):
                for item in policy.get(collection, []):
                    if item.get('status', 'confirmed') != 'confirmed':
                        continue
                    item = copy.deepcopy(item)
                    if item.get('prompt_file'):
                        raw = self._safe(item['prompt_file']).read_bytes()
                        if item.get('prompt_sha256') and digest(raw) != item['prompt_sha256']:
                            raise CreatorConflict('已确认基线的提示词原件字节变化，请核对后迁移')
                        from easel_workbench.runtime.creative_policy_files import instructions_from_file
                        item['instructions'] = instructions_from_file(item, raw)
                    if not isinstance(item.get('instructions'), list):
                        raise ValueError('已确认基线缺少实际指令')
                    item['original_collection'] = collection
                    item['creator_profile_id'] = DEFAULT_PROFILE
                    item['provenance'] = {'path': '规范/创作策略.json', 'sha256': digest(policy_raw), 'id': item['id'], 'status': 'confirmed'}
                    confirmed.append(item)
            recipe_catalog = self._safe('规范/创作方案/目录.json')
            if sid in ('content-writing', 'image-production') and recipe_catalog.is_file():
                recipes = json.loads(recipe_catalog.read_text(encoding='utf-8-sig'))
                variants = [{name: copy.deepcopy(pack[name]) for name in ('id', 'name', 'status', 'formats', 'components', 'fixed_master', 'description') if name in pack} for pack in recipes.get('packs', [])]
                for component in recipes.get('components', []):
                    writing = component.get('slot') == 'writing'
                    if writing != (sid == 'content-writing'):
                        continue
                    if component.get('prompt_file'):
                        source_resources.append({'path': component['prompt_file'], 'kind': 'prompt', 'scope': 'on-demand', 'variant': component['id'], 'approval': component.get('status'), 'label': component.get('name')})
                    for asset in component.get('assets', []):
                        source_resources.append({**asset, 'kind': 'asset', 'scope': 'on-demand', 'variant': component['id'], 'approval': component.get('status')})
            resources = [self._resource(c, item) for item in source_resources]
            # Freeze the effective, already-confirmed variant text exactly once.
            # A later edit to the legacy policy cannot mutate a released skill.
            for resource in resources:
                overrides = [row for row in confirmed if row.get('recipe_component_id') == resource.get('variant')]
                if overrides and resource.get('kind') == 'prompt':
                    method = overrides[-1]
                    raw = '\n'.join(method['instructions']).encode('utf-8')
                    resource.update(sha256=digest(raw), size=len(raw), available=True, derived=True,
                                    creator_profile_id=DEFAULT_PROFILE, provenance=method['provenance'])
                    c.execute('INSERT OR IGNORE INTO creator_skill_blobs VALUES(?,?)', (resource['sha256'], raw))
            baselines = []
            if sid in ('content-writing', 'image-production', 'delivery-review'):
                for row in confirmed:
                    dimension = row.get('dimension', '')
                    if row.get('recipe_component_id'):
                        continue
                    if sid == 'content-writing' and dimension not in ('visual', 'image', 'review') or sid == 'image-production' and dimension in ('visual', 'image', 'main_style') or sid == 'delivery-review' and dimension == 'review':
                        baselines.append(row)
                if policy_raw:
                    resources.append(self._resource(c, {'path': '规范/创作策略.json', 'kind': 'contract', 'scope': 'on-demand', 'label': '迁移时的策略原件（含候选身份，不自动采用）'}))
                if baselines:
                    raw = packed({'creator_profile_id': DEFAULT_PROFILE, 'rules': baselines, 'source_sha256': digest(policy_raw)}).encode('utf-8')
                    c.execute('INSERT OR IGNORE INTO creator_skill_blobs VALUES(?,?)', (digest(raw), raw))
                    resources.append({'path': str(pathlib.PurePosixPath(skill['entry']).parent / 'references/confirmed-baseline.json'),
                                      'kind': 'contract', 'scope': 'on-demand', 'label': '已确认基线的冻结提炼',
                                      'available': True, 'required': False, 'sha256': digest(raw), 'size': len(raw),
                                      'derived': True, 'creator_profile_id': DEFAULT_PROFILE,
                                      'provenance': {'path': '规范/创作策略.json', 'sha256': digest(policy_raw), 'ids': [r['id'] for r in baselines]}})
            metadata = {name: copy.deepcopy(skill.get(name)) for name in ('id', 'name', 'description', 'entry', 'tasks', 'executor', 'input_contract', 'output_contract', 'acceptance_cases','composition','layer')}
            metadata['created_at'] = stamp()
            metadata['variants'] = variants
            release = {**metadata, 'version': 1, 'prompt': body, 'resources': resources,
                       'base_version': None, 'reason': '从现行制作能力整理的初始技能包；不新增风格认可。',
                       'conditions': {}, 'evidence_refs': [], 'status': 'candidate' if skill.get('status') == 'candidate' else 'published', 'created_at': stamp()}
            if release['status'] == 'candidate':
                release['base_version'] = 0
                release['reason'] = '外部方法迁入候选；仅明确试用，不自动成为默认。'
            release['baseline_rules'] = baselines
            validate_package(release)
            release['sha256'] = self._release_hash(release)
            c.execute('INSERT INTO creator_skills VALUES(?,?)', (sid, packed(metadata)))
            c.execute('INSERT INTO creator_skill_versions VALUES(?,?,?)', (sid, 1, packed(release)))
            c.execute('INSERT INTO creator_skill_pointers VALUES(?,?,?)', (sid, 1, 0 if release['status'] == 'candidate' else 1))
        # Pin persona defaults independently. Publishing for one persona must not
        # silently replace another persona's chosen version.
        for row in c.execute('SELECT document FROM creator_profiles').fetchall():
            profile = json.loads(row['document'])
            changed = False
            if 'skill_versions' not in profile:
                profile['skill_versions'] = {r['skill_id']: r['version'] for r in c.execute('SELECT skill_id,version FROM creator_skill_pointers WHERE version>0')}
                changed = True
            if 'task_skill_versions' not in profile:
                profile['task_skill_versions'] = {task: {sid: profile['skill_versions'].get(sid, self._published(c, sid)) for sid in skills} for task, skills in profile.get('default_skills', TASK_DEFAULTS).items()}
                changed = True
            if changed:
                c.execute('UPDATE creator_profiles SET document=? WHERE id=?', (packed(profile), profile['id']))
                c.execute('UPDATE creator_profile_history SET document=? WHERE id=? AND revision=?', (packed(profile), profile['id'], profile['revision']))

    def _resource(self, c, item):
        return self.releases._resource(c, item)

    def _release_hash(self, release):
        from easel_workbench.features.skills.releases import SkillReleases
        return SkillReleases._release_hash(None, release)

    def _published(self, c, sid):
        return self.releases._published(c, sid)

    def _skill(self, c, sid, version=None, with_content=True):
        return self.releases._skill(c, sid, version, with_content)

    def accounts(self, c=None):
        if c is None:
            with self.store.connect() as connection:
                return self.accounts(connection)
        if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='distribution_connections'").fetchone():
            return []
        accounts = []
        for row in c.execute('SELECT id,document FROM distribution_connections ORDER BY rowid'):
            document = json.loads(row['document'])
            account = {name: copy.deepcopy(document.get(name)) for name in ('id', 'platform', 'account', 'label', 'enabled', 'revision')}
            account['id'] = row['id']
            account['status'] = 'enabled' if document.get('enabled', True) else 'disabled'
            # Do not return arbitrary connector evidence, secret_ref or nested auth fields.
            caps = document.get('capabilities') or {}
            account['capabilities'] = {name: {k: v for k, v in cap.items() if k in ('status', 'verified', 'code_verified', 'account_verified', 'reason', 'checked_at')} for name, cap in caps.items() if isinstance(cap, dict)} if isinstance(caps, dict) else {}
            accounts.append(account)
        return accounts

    def bootstrap(self):
        with self.store.connect() as c:
            profiles = [json.loads(row['document']) for row in c.execute('SELECT document FROM creator_profiles ORDER BY rowid')]
            skills = []
            for row in c.execute('SELECT id FROM creator_skills ORDER BY rowid'):
                if row['id'] in RETIRED_EASEL_SKILLS:continue
                item = self._skill(c, row['id'], with_content=False)
                item['versions'] = [{'version': r['version'], 'status': self._skill(c, row['id'], r['version'], False)['status'], 'created_at': json.loads(r['document'])['created_at']} for r in c.execute('SELECT version,document FROM creator_skill_versions WHERE skill_id=? ORDER BY version DESC', (row['id'],))]
                item.pop('prompt', None)
                item.pop('base_prompt', None)
                item.pop('history', None)
                item.update(launch_metadata(item))
                skills.append(item)
            return {'schema_version': 1, 'default_profile_id': DEFAULT_PROFILE, 'profiles': profiles,
                    'skills': skills, 'accounts': self.accounts(c), 'task_defaults': copy.deepcopy(TASK_DEFAULTS),
                    'task_policy': task_policy(skills),
                    'learning': {'mode': 'manual', 'automatic_model_learning': False}}

    def detail(self, kind, item_id, version=None):
        kind = {'profiles': 'profile', 'skills': 'skill', 'runs': 'run'}.get(kind, kind)
        if isinstance(version, str):
            try:
                version = int(version)
            except ValueError:
                raise ValueError('版本无效') from None
        with self.store.connect() as c:
            if kind == 'profile':
                result = self._profile(c, item_id, version)
                result['history'] = [json.loads(r['document']) for r in c.execute('SELECT document FROM creator_profile_history WHERE id=? ORDER BY revision DESC', (item_id,))]
                return result
            if kind == 'skill':
                result = self._skill(c, item_id, version)
                result.update(launch_metadata(result))
                result['uses'] = self._uses(c, item_id, result['version'])
                result['usage_coverage'] = {'source': 'creator_task_runs', 'historical_inference': False,
                                          'limit': 100, 'notice': '仅统计已有显式技能快照的作品；旧稿未记录不等于未使用。'}
                return result
            if kind == 'run':
                from easel_workbench.runtime.task_runtime import projection
                result = projection(c, item_id)
                if result is None:
                    raise ValueError('找不到显式任务记录；历史任务不补造技能执行')
                return result
            if kind == 'experience':
                from easel_workbench.runtime.task_runtime import experience_detail
                return experience_detail(c, item_id)
            raise ValueError('不支持的详情类型')

    def _uses(self, c, skill_id, version):
        tables = {r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {'creator_task_runs', 'toolbox_jobs', 'toolbox_works'} <= tables:
            return []
        rows = c.execute('''SELECT r.id,r.work_id,r.updated_at,
            json_extract(r.document,'$.snapshot.profile.id') AS profile_id,
            w.title,COALESCE(o.format,'poster') AS format,j.kind,j.status,j.created_at
            FROM creator_task_runs r JOIN toolbox_jobs j ON j.id=r.id
            JOIN toolbox_works w ON w.id=r.work_id
            LEFT JOIN toolbox_work_options o ON o.work_id=r.work_id
            WHERE EXISTS(SELECT 1 FROM json_each(json_extract(r.document,'$.snapshot.skills')) s
                WHERE json_extract(s.value,'$.id')=? AND json_extract(s.value,'$.version')=?)
            ORDER BY r.rowid DESC LIMIT 100''', (skill_id, version)).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item['job_id'] = item.pop('id')
            decision = c.execute("SELECT id,kind,text,scope,created_at FROM toolbox_jobs WHERE work_id=? AND candidate_id=? AND kind IN ('accept','reject') AND status='completed' ORDER BY created_at DESC,rowid DESC LIMIT 1", (item['work_id'], item['job_id'])).fetchone()
            item['decision'] = ({'id': decision['id'], 'kind': decision['kind'], 'reason': decision['text'],
                                 'scope': json.loads(decision['scope']), 'created_at': decision['created_at']} if decision else None)
            item['feedback'] = [{'id': feedback['id'], 'text': feedback['text'], 'created_at': feedback['created_at']} for feedback in c.execute("SELECT id,text,created_at FROM toolbox_jobs WHERE work_id=? AND candidate_id=? AND kind='feedback' AND status='completed' ORDER BY created_at,rowid", (item['work_id'], item['job_id']))]
            result.append(item)
        return result

    def _validate_defaults(self, c, value):
        return self.profiles._validate_defaults(c, value)

    def _uploaded_asset(self, c, profile_id, reference):
        return self.profiles._uploaded_asset(c, profile_id, reference)

    def _profile_assets(self, c, profile_id, references, old):
        return self.profiles._profile_assets(c, profile_id, references, old)

    def _save_profile(self, c, value):
        return self.profiles._save_profile(c, value)

    def _bind(self, c, value, remove=False):
        profile = self._profile(c, value.get('profile_id') or DEFAULT_PROFILE)
        if type(value.get('base_revision')) is not int or profile['revision'] != value.get('base_revision'):
            raise CreatorConflict('画像已有新修订，请重新核对')
        connection_id = key(value.get('connection_id'))
        if not remove and not any(a['id'] == connection_id for a in self.accounts(c)):
            raise ValueError('请先连接准确的平台账号')
        if remove:
            profile['account_ids'] = [cid for cid in profile['account_ids'] if cid != connection_id]
        elif connection_id not in profile['account_ids']:
            profile['account_ids'].append(connection_id)
        profile.update(revision=profile['revision'] + 1, updated_at=stamp())
        self._put_profile(c, profile)
        return {'profile': profile}

    def propose(self, c, skill_id, base_version, prompt, reason='', evidence_refs=None, conditions=None, operation_id=None, resources=None, validation_cases=None):
        if type(base_version) is not int or base_version < 1:
            raise ValueError('技能修订需要准确的基础版本')
        base = self._skill(c, key(skill_id), base_version, with_content=False)
        text(prompt, MAX_PROMPT, True)
        changed_resources = base['resources']
        if resources is not None:
            if not isinstance(resources, list) or len(resources) > 40:
                raise ValueError('技能资源数量无效')
            changed_resources = [self._resource(c, item) for item in resources]
        if prompt == base['prompt'] and changed_resources == base['resources']:
            raise ValueError('提示词和资源没有变化，无需建立候选版本')
        if evidence_refs is not None and (not isinstance(evidence_refs, list) or len(evidence_refs) > 100 or any(not isinstance(e, (str, dict)) for e in evidence_refs)):
            raise ValueError('经验来源格式无效')
        if conditions is not None and not isinstance(conditions, (str, dict)):
            raise ValueError('适用条件格式无效')
        if validation_cases is not None and (not isinstance(validation_cases, list) or len(validation_cases) > 40 or any(not isinstance(case, str) or not case.strip() or len(case) > 2000 for case in validation_cases)):
            raise ValueError('验证建议需要有界、明确的案例文字')
        release = {k: copy.deepcopy(v) for k, v in base.items() if k not in ('history', 'diff', 'base_prompt', 'published_version', 'is_current', 'resource_changes')}
        version = c.execute('SELECT COALESCE(MAX(version),0)+1 FROM creator_skill_versions WHERE skill_id=?', (skill_id,)).fetchone()[0]
        release.update(version=version, prompt=prompt, status='candidate', base_version=base_version,
                       reason=text(reason, 12000), conditions=conditions or {}, evidence_refs=evidence_refs or [], created_at=stamp())
        release['validation_cases'] = {'status': 'not_run', 'cases': validation_cases or [], 'notice': '这是验证建议，尚未执行。'}
        release['resources'] = changed_resources
        before = {r['path']: r.get('sha256') for r in base['resources']}
        after = {r['path']: r.get('sha256') for r in changed_resources}
        release['resource_changes'] = [{'path': path, 'before_sha256': before.get(path), 'after_sha256': after.get(path)} for path in sorted(before.keys() | after.keys()) if before.get(path) != after.get(path)]
        # Unchanged resource snapshots are retained from the exact base release.
        release['sha256'] = self._release_hash(release)
        c.execute('INSERT INTO creator_skill_versions VALUES(?,?,?)', (skill_id, version, packed(release)))
        self._event(c, skill_id, version, 'draft', {'reason': reason, 'operation_id': operation_id})
        return self._skill(c, skill_id, version)

    def _event(self, c, sid, version, action, extra=None):
        return self.releases._event(c, sid, version, action, extra)

    def _publish(self, c, value, revert=False):
        sid = key(value.get('skill_id'))
        old = self._published(c, sid)
        if type(value.get('expected_published_version')) is not int or value.get('expected_published_version') != old:
            raise CreatorConflict('技能默认版本已变化，请重新核对差异')
        if value.get('confirm') is not True:
            raise ValueError('请明确确认发布或恢复版本')
        version = value.get('version')
        if type(version) is not int or version < 1:
            raise ValueError('请选择准确的技能版本')
        release = self._skill(c, sid, version)
        if revert and release['status'] != 'published':
            raise ValueError('只能恢复曾经发布的版本')
        if not revert and release['status'] == 'candidate' and release.get('base_version') != old:
            raise CreatorConflict('候选基于旧版本，请先核对当前提示词后另存修订')
        validation = validate_package(release)
        for resource in release.get('resources', []):
            if resource.get('required') and not resource.get('available'):
                raise ValueError('必要资源缺失，不能发布')
            if resource.get('available'):
                blob = c.execute('SELECT bytes FROM creator_skill_blobs WHERE sha256=?', (resource['sha256'],)).fetchone()
                if not blob or digest(bytes(blob['bytes'])) != resource['sha256']:
                    raise CreatorConflict('冻结资源字节缺失或不符，不能发布')
        validation['checks'].append('resource_bytes')
        from easel_workbench.project_skill_sync import stage
        source_sync=stage(self,c,release,value['id'],self._skill(c,sid,old,False) if old else None)
        if release['version'] != old:
            c.execute('UPDATE creator_skill_pointers SET revision=revision+1,version=? WHERE skill_id=?', (version, sid))
            self._event(c, sid, version, 'revert' if revert else 'publish', {'previous_version': old, 'validation': validation})
        profile = None
        if value.get('profile_id'):
            profile = self._profile(c, value['profile_id'])
            if type(value.get('profile_revision')) is not int or profile['revision'] != value.get('profile_revision'):
                raise CreatorConflict('画像已有新修订，请重新选择适用范围')
            tasks = value.get('tasks', [])
            if not isinstance(tasks, list) or not tasks or any(not isinstance(t, str) or t not in TASK_DEFAULTS for t in tasks):
                raise ValueError('技能适用任务无效')
            for task in tasks:
                require_task(release, task)
                defaults = profile['default_skills'].setdefault(task, [])
                if sid not in defaults:
                    defaults.append(sid)
                profile.setdefault('task_skill_versions', {}).setdefault(task, {})[sid] = version
            self._validate_defaults(c, profile['default_skills'])
            profile.update(revision=profile['revision'] + 1, updated_at=stamp())
            self._put_profile(c, profile)
        result = {'skill': self._skill(c, sid, version)}
        if source_sync is not None:result['source_sync']=source_sync
        if profile is not None:
            result['profile'] = profile
        return result

    def command(self, value):
        if not isinstance(value, dict):
            raise ValueError('操作格式无效')
        value = copy.deepcopy(value)
        operation = key(value.get('id') or value.get('operation_id'))
        value['id'] = operation
        signature = digest(packed(value))
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            previous = c.execute('SELECT signature,result FROM creator_operations WHERE id=?', (operation,)).fetchone()
            if previous:
                if previous['signature'] != signature:
                    raise CreatorConflict('相同操作标识不能提交不同内容')
                from easel_workbench.project_skill_sync import finish_response
                return finish_response(self,c,json.loads(previous['result']))
            action = value.get('action')
            if action == 'profile-save':
                result = self._save_profile(c, value)
            elif action in ('profile-proposal-confirm','profile-proposal-revert'):
                from easel_workbench.runtime.profile_learning import confirm
                result=confirm(self,c,value,action=='profile-proposal-revert')
            elif action in ('bind-account', 'unbind-account'):
                result = self._bind(c, value, action == 'unbind-account')
            elif action == 'skill-draft':
                result = {'skill': self.propose(c, value.get('skill_id'), value.get('base_version'), value.get('prompt'), value.get('reason', ''), value.get('evidence_refs'), value.get('conditions'), operation, value.get('resources'), value.get('validation_cases'))}
            elif action in ('skill-publish', 'skill-revert'):
                result = self._publish(c, value, action == 'skill-revert')
            elif action == 'skill-source-reconcile':
                from easel_workbench.project_skill_sync import pending
                result={'source_sync':pending(self,c,key(value.get('skill_id')),value.get('version'))}
            elif action == 'trial':
                snapshot = self.resolve(value.get('profile_id') or DEFAULT_PROFILE, value.get('task', 'poster'), value.get('skills'), True, value.get('profile_revision'), c)
                result = {'snapshot': snapshot, 'trial': True, 'started': False}
            elif action == 'experience-organize':
                from easel_workbench.runtime.task_runtime import enqueue_experience
                result = enqueue_experience(self.box, value, c)
            elif action == 'reference-analyze':
                from easel_workbench.runtime.task_runtime import enqueue_reference
                result = enqueue_reference(self.box, value, c)
            else:
                raise ValueError('不支持的画像或技能操作')
            response = {'id': operation, 'status': 'completed', 'execution': 'script', 'result': result}
            c.execute('INSERT INTO creator_operations VALUES(?,?,?,?)', (operation, signature, packed(response), stamp()))
            from easel_workbench.project_skill_sync import finish_response
            return finish_response(self,c,response)

    def resolve(self, profile_id=DEFAULT_PROFILE, task='poster', skill_refs=None, allow_trial=False, profile_revision=None, c=None, allow_historical_profile=False, context=None):
        return self.snapshots.resolve(profile_id, task, skill_refs, allow_trial, profile_revision, c, allow_historical_profile, context)

    def resource(self, skill_id, version, index):
        return self.releases.resource(skill_id, version, index)

    def profile_resource(self, profile_id, revision, index):
        return self.profiles.profile_resource(profile_id, revision, index)

    def export(self, skill_id, version=None):
        return self.releases.export(skill_id, version)

    def materialize(self, snapshot, folder, selected_paths=None, c=None, write=True):
        return self.releases.materialize(snapshot, folder, selected_paths, c, write)


from easel_workbench.features.profiles.service import read_owner


def service(box, c=None):
    runtime = getattr(box, 'creator', None)
    if runtime is None:
        runtime = CreatorRuntime(box, c=c)
        box.creator = runtime
    return runtime
