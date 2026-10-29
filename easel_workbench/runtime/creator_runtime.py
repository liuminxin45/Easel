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

DEFAULT_PROFILE = 'oil-pig'
MANIFEST = '.agents/skills/capabilities.json'
MAX_PROMPT = 160000
MAX_RESOURCE = 40 * 1024 * 1024
TASK_DEFAULTS = {
    'poster': ['content-writing', 'image-production', 'delivery-review'],
    'article': ['content-writing', 'image-production', 'delivery-review'],
    'change': ['content-writing', 'image-production', 'delivery-review'],
    'discuss': ['topic-research'], 'research': ['topic-research'],
    'reference': ['reference-analysis'], 'review': ['delivery-review'],
    'analysis': ['publication-analysis'], 'learning': ['experience-distillation'],
    'news_enhancement': ['topic-research'], 'image': ['image-production', 'delivery-review'],
    'media': [], 'speech': [], 'video': [], 'music': [], 'transcribe': [], 'compose': [],
}


RETIRED_EASEL_SKILLS = frozenset(('easel-voiceover','easel-image','easel-video','easel-music','easel-transcribe','easel-compose'))

class CreatorConflict(ValueError):
    """Concurrent edits or an operation identity with different content."""


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(value if isinstance(value, bytes) else value.encode('utf-8')).hexdigest()


def key(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', value):
        raise ValueError('记录标识无效')
    return value


def text(value, limit=MAX_PROMPT, required=False):
    if not isinstance(value, str) or len(value) > limit or '\x00' in value or required and not value.strip():
        raise ValueError('文字为空或超过长度限制')
    return value


def validate_package(release):
    """Deterministic publish gate; these checks do not judge content quality."""
    import yaml
    match = re.match(r'\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)', release.get('prompt', ''), re.S)
    if not match:
        raise ValueError('技能缺少完整的 YAML 名称与用途头部，请先保存为可调用技能格式')
    try:
        metadata = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        raise ValueError('技能头部格式无效，尚未发布') from None
    if not isinstance(metadata, dict) or set(metadata) - {'name', 'description', 'license', 'allowed-tools', 'metadata'}:
        raise ValueError('技能头部只能包含支持的能力元信息')
    name = metadata.get('name')
    description = metadata.get('description')
    if not isinstance(name, str) or not re.fullmatch(r'[a-z0-9]+(?:-[a-z0-9]+)*', name) or len(name) > 64:
        raise ValueError('技能名称需要64字以内的小写英文标识')
    if name != pathlib.PurePosixPath(release['entry']).parent.name:
        raise ValueError('修订须保留此技能的稳定名称；新能力不能覆盖另一个技能身份')
    if not isinstance(description, str) or not description.strip() or len(description) > 1024 or '<' in description or '>' in description:
        raise ValueError('技能需要明确、完整的用途说明')
    if not release['prompt'][match.end():].strip() or re.search(r'^\s*\[TODO:[^\n]*\]\s*$', release['prompt'][match.end():], re.M):
        raise ValueError('技能正文为空或仍有待填写占位')
    for field in ('input_contract', 'output_contract'):
        contract = release.get(field)
        if not isinstance(contract, dict) or not isinstance(contract.get('required'), list) or not contract['required'] or any(not isinstance(item, str) or not item for item in contract['required']):
            raise ValueError('技能缺少明确的输入输出合同')
    return {'status': 'passed', 'checks': ['skill_metadata', 'nonempty_instructions', 'input_contract', 'output_contract'],
            'semantic_cases': 'not_run', 'notice': '程序格式检查不代表审美、事实或效果验收。'}


def initialize(c):
    statements = '''
CREATE TABLE IF NOT EXISTS creator_profiles(id TEXT PRIMARY KEY,revision INTEGER NOT NULL,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS creator_profile_history(id TEXT NOT NULL,revision INTEGER NOT NULL,document TEXT NOT NULL,PRIMARY KEY(id,revision));
CREATE TABLE IF NOT EXISTS creator_skills(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS creator_skill_versions(skill_id TEXT NOT NULL,version INTEGER NOT NULL,document TEXT NOT NULL,PRIMARY KEY(skill_id,version));
CREATE TABLE IF NOT EXISTS creator_skill_pointers(skill_id TEXT PRIMARY KEY,revision INTEGER NOT NULL,version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS creator_skill_blobs(sha256 TEXT PRIMARY KEY,bytes BLOB NOT NULL);
CREATE TABLE IF NOT EXISTS creator_skill_events(id TEXT PRIMARY KEY,skill_id TEXT NOT NULL,version INTEGER NOT NULL,action TEXT NOT NULL,document TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS creator_operations(id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS creator_work_owners(work_id TEXT PRIMARY KEY,profile_id TEXT NOT NULL,profile_revision INTEGER NOT NULL,document TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS creator_profile_proposals(id TEXT PRIMARY KEY,document TEXT NOT NULL);
'''
    for statement in statements.split(';'):
        if statement.strip():
            c.execute(statement)


class CreatorRuntime:
    def __init__(self, box, project=None, c=None):
        self.box = box
        self.store = box.store
        self.root = pathlib.Path(box.root)
        self.project = pathlib.Path(project or getattr(getattr(box, 'studio', None), 'project', PROJECT)).resolve()
        if c is not None:
            initialize(c)
            self._seed(c)
        else:
            with self.store.connect() as connection:
                initialize(connection)
                self._seed(connection)

    def _safe(self, relative):
        if not isinstance(relative, str) or not relative or len(relative) > 2000 or '\x00' in relative or '\\' in relative or pathlib.PurePosixPath(relative).is_absolute():
            raise ValueError('资源路径无效')
        path = (self.project / relative).resolve()
        if not path.is_relative_to(self.project) or '..' in pathlib.PurePosixPath(relative).parts:
            raise ValueError('资源不能离开内容项目')
        if pathlib.PurePosixPath(relative).parts[0] not in ('规范', '资料', '工具', '内容', '.agents'):
            raise ValueError('技能只引用创作规范、材料、工具和技能资源')
        return path

    def _profile(self, c, profile_id, revision=None):
        if revision is None:
            row = c.execute('SELECT document FROM creator_profiles WHERE id=?', (key(profile_id),)).fetchone()
        else:
            row = c.execute('SELECT document FROM creator_profile_history WHERE id=? AND revision=?', (key(profile_id), revision)).fetchone()
        if not row:
            raise ValueError('找不到创作画像或指定修订')
        return json.loads(row['document'])

    def _put_profile(self, c, profile):
        for index, resource in enumerate(profile.get('asset_refs', [])):
            resource['url'] = '/api/creator/profiles/' + profile['id'] + '/assets/' + str(profile['revision']) + '/' + str(index)
        raw = packed(profile)
        c.execute('INSERT INTO creator_profile_history VALUES(?,?,?)', (profile['id'], profile['revision'], raw))
        c.execute('INSERT INTO creator_profiles VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,document=excluded.document', (profile['id'], profile['revision'], raw))

    def bind_work(self, c, work_id, selection=None, allow_historical=False):
        """Bind ownership for human and AI work alike, without creating AI work."""
        key(work_id)
        previous = read_owner(c, work_id)
        if selection is not None and not isinstance(selection, dict):
            raise ValueError('作品画像选择无效')
        selection = selection or {}
        profile_id = key(selection.get('profile_id') or (previous['profile_id'] if previous else DEFAULT_PROFILE))
        revision = selection.get('profile_revision')
        if revision is not None and (type(revision) is not int or revision < 1):
            raise ValueError('画像修订号无效')
        if previous and previous['profile_id'] != profile_id:
            raise CreatorConflict('作品已绑定其他画像，请另建作品后明确引用材料')
        profile = self._profile(c, profile_id, revision if allow_historical and revision is not None else None)
        if revision is not None and revision != profile['revision']:
            raise CreatorConflict('画像已有新修订，请重新核对')
        if not profile.get('active', True) and not previous:
            raise ValueError('创作画像已停用')
        if previous is None and c.execute("SELECT 1 FROM sqlite_master WHERE name='creator_task_runs'").fetchone():
            row = c.execute('SELECT document FROM creator_task_runs WHERE work_id=? ORDER BY rowid LIMIT 1', (work_id,)).fetchone()
            if row:
                old_profile = json.loads(row['document'])['snapshot']['profile']
                if old_profile['id'] != profile_id:
                    raise CreatorConflict('作品已有其他画像的冻结任务，不能改变归属')
        owner = {'work_id': work_id, 'profile_id': profile_id, 'profile_revision': profile['revision'],
                 'profile': copy.deepcopy(profile), 'created_at': previous['created_at'] if previous else stamp()}
        if previous is None:
            c.execute('INSERT INTO creator_work_owners VALUES(?,?,?,?,?)', (work_id, profile_id, profile['revision'], packed(owner), owner['created_at']))
        return owner

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
        manifest = self._safe(MANIFEST)
        if not manifest.is_file():
            return
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
            metadata = {name: copy.deepcopy(skill.get(name)) for name in ('id', 'name', 'description', 'entry', 'tasks', 'executor', 'input_contract', 'output_contract', 'acceptance_cases')}
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
        item = {'path': item} if isinstance(item, str) else copy.deepcopy(item)
        if not isinstance(item, dict) or 'path' not in item:
            raise ValueError('技能资源需要明确的项目路径')
        path = self._safe(item['path'])
        result = {name: copy.deepcopy(item[name]) for name in ('path', 'kind', 'label', 'required', 'scope', 'variant', 'approval', 'role') if name in item}
        result.setdefault('kind', 'reference')
        result.setdefault('required', False)
        if not path.is_file():
            if result['required']:
                raise ValueError('技能必要资源缺失：' + item['path'])
            result.update(available=False, sha256=None, reason='原件未取得')
            return result
        if path.stat().st_size > MAX_RESOURCE:
            raise ValueError('单份技能资源超过40MB，请使用明确分件')
        raw = path.read_bytes()
        if item.get('sha256') and digest(raw) != item['sha256']:
            raise CreatorConflict('技能资源字节已变化，请核对原件后发布新版本')
        result.update(available=True, sha256=digest(raw), size=len(raw))
        c.execute('INSERT OR IGNORE INTO creator_skill_blobs VALUES(?,?)', (result['sha256'], raw))
        return result

    def _release_hash(self, release):
        return digest(packed({k: v for k, v in release.items() if k not in ('sha256', 'status', 'created_at', 'history', 'published_version', 'diff')}))

    def _published(self, c, sid):
        row = c.execute('SELECT version FROM creator_skill_pointers WHERE skill_id=?', (key(sid),)).fetchone()
        if not row:
            raise ValueError('找不到技能')
        return int(row['version'])

    def _skill(self, c, sid, version=None, with_content=True):
        published = self._published(c, sid)
        if version is None:
            version = published or c.execute('SELECT max(version) FROM creator_skill_versions WHERE skill_id=?', (sid,)).fetchone()[0]
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ValueError('技能版本无效')
        row = c.execute('SELECT document FROM creator_skill_versions WHERE skill_id=? AND version=?', (sid, version)).fetchone()
        if not row:
            raise ValueError('找不到技能版本')
        result = json.loads(row['document'])
        # A published old release stays published; the pointer determines recommendation.
        published_before = result.get('status') == 'published' or c.execute("SELECT 1 FROM creator_skill_events WHERE skill_id=? AND version=? AND action='publish'", (sid, version)).fetchone()
        result['status'] = 'published' if published_before else 'candidate'
        result['published_version'] = published
        result['is_current'] = published == version
        result['resources'] = copy.deepcopy(result.get('resources', []))
        if with_content:
            for index, resource in enumerate(result['resources']):
                resource['url'] = '/api/creator/skills/' + sid + '/resources/' + str(version) + '/' + str(index)
                if resource.get('available') and resource.get('kind') in ('reference', 'prompt', 'contract'):
                    blob = c.execute('SELECT bytes FROM creator_skill_blobs WHERE sha256=?', (resource['sha256'],)).fetchone()
                    try:
                        content = bytes(blob['bytes']).decode('utf-8-sig') if blob else None
                    except UnicodeDecodeError:
                        content = None
                    if content is not None:
                        resource['content'] = content
        result['history'] = [json.loads(row['document']) for row in c.execute('SELECT document FROM creator_skill_events WHERE skill_id=? ORDER BY created_at,rowid', (sid,))]
        base = result.get('base_version')
        if base:
            row = c.execute('SELECT document FROM creator_skill_versions WHERE skill_id=? AND version=?', (sid, base)).fetchone()
            before = json.loads(row['document'])['prompt'] if row else ''
            result['base_prompt'] = before
            result['diff'] = ''.join(difflib.unified_diff(before.splitlines(True), result['prompt'].splitlines(True), fromfile='v' + str(base), tofile='v' + str(version)))
        return result

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
                skills.append(item)
            return {'schema_version': 1, 'default_profile_id': DEFAULT_PROFILE, 'profiles': profiles,
                    'skills': skills, 'accounts': self.accounts(c), 'task_defaults': copy.deepcopy(TASK_DEFAULTS),
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
        if not isinstance(value, dict) or set(value) - set(TASK_DEFAULTS):
            raise ValueError('默认技能任务类型无效')
        result = {}
        for task, skills in value.items():
            if not isinstance(skills, list) or not skills and task not in ('media','speech','video','music','transcribe','compose') or len(skills) > 8 or any(not isinstance(sid, str) for sid in skills) or len(skills) != len(set(skills)):
                raise ValueError('每项任务选择1至8个不同技能')
            for sid in skills:
                if not self._published(c, sid):raise ValueError('候选技能不能成为画像默认')
            result[task] = skills
        return copy.deepcopy(result)

    def _uploaded_asset(self, c, profile_id, reference):
        """Promote an authenticated upload to an immutable creator reference."""
        from PIL import Image, UnidentifiedImageError
        file_id = key(reference.get('file_id'))
        row = c.execute('SELECT * FROM toolbox_files WHERE id=?', (file_id,)).fetchone()
        if not row:
            raise ValueError('画像图片尚未上传，请先等待上传完成')
        path = pathlib.Path(row['path']).resolve()
        if not path.is_relative_to((self.root / 'data').resolve()) or not path.is_file():
            raise ValueError('画像图片不属于工作台的准确上传原件')
        if path.stat().st_size > MAX_RESOURCE:
            raise ValueError('画像图片总量最多40MB')
        with path.open('rb') as handle:
            raw = handle.read(MAX_RESOURCE + 1)
        if len(raw) > MAX_RESOURCE or digest(raw) != row['sha256'] or len(raw) != row['size']:
            raise CreatorConflict('画像上传原件字节已变化，请重新上传；没有保存画像')
        try:
            with warnings.catch_warnings():
                warnings.simplefilter('error', Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as image:
                    format = image.format
                    width, height = image.size
                    if format not in ('PNG', 'JPEG', 'WEBP') or getattr(image, 'is_animated', False) or getattr(image, 'n_frames', 1) != 1:
                        raise ValueError('请使用PNG、JPEG或WebP静态图片，动图不能作为画像参考')
                    if width * height > 40_000_000:
                        raise ValueError('画像参考图片像素过大，请缩小后上传')
                    image.verify()
                # Verify the actual compressed image data as well as its header.
                with Image.open(io.BytesIO(raw)) as image:
                    image.load()
        except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombWarning, Image.DecompressionBombError):
            raise ValueError('无法完整读取画像图片，请使用有效的PNG、JPEG或WebP静态图片') from None
        suffix, mime = {'PNG': ('.png', 'image/png'), 'JPEG': ('.jpg', 'image/jpeg'), 'WEBP': ('.webp', 'image/webp')}[format]
        fingerprint = digest(raw)
        relative = '资料/画像资产/' + key(profile_id) + '/' + fingerprint + suffix
        destination = self._safe(relative)
        if destination.exists():
            if digest(destination.read_bytes()) != fingerprint:
                raise CreatorConflict('画像资产位置已有不同字节，未覆盖原件')
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            temporary = destination.with_name(destination.name + '.' + uuid.uuid4().hex + '.tmp')
            try:
                with temporary.open('xb') as handle:
                    handle.write(raw)
                    handle.flush()
                    os.fsync(handle.fileno())
                try:
                    # Atomic create without replacing a concurrent immutable copy.
                    os.link(temporary, destination)
                except FileExistsError:
                    if digest(destination.read_bytes()) != fingerprint:
                        raise CreatorConflict('画像资产出现不同字节，未覆盖原件')
            finally:
                temporary.unlink(missing_ok=True)
        c.execute('INSERT OR IGNORE INTO creator_skill_blobs VALUES(?,?)', (fingerprint, raw))
        return {'path': relative, 'sha256': fingerprint, 'available': True, 'size': len(raw),
                'kind': 'asset', 'mime': mime, 'width': width, 'height': height,
                'label': text(reference.get('label', row['name']), 200),
                'role': text(reference.get('role', 'reference'), 80), 'required': reference.get('required', True),
                'original_name': row['name'], 'provenance': {'file_id': file_id, 'original_name': row['name'],
                'sha256': fingerprint, 'type': 'user_uploaded_reference', 'approval': 'profile_binding_only'}}

    def _profile_assets(self, c, profile_id, references, old):
        if not isinstance(references, list) or len(references) > 8:
            raise ValueError('每个画像最多8张参考资产，总量不超过40MB')
        result, total = [], 0
        for reference in references:
            if not isinstance(reference, dict):
                raise ValueError('画像资产需要已上传文件或准确原路径')
            if 'required' in reference and type(reference['required']) is not bool:
                raise ValueError('画像资产的必要状态无效')
            if 'file_id' in reference:
                item = self._uploaded_asset(c, profile_id, reference)
            else:
                previous = next((item for item in (old or {}).get('asset_refs', []) if item.get('path') == reference.get('path') and item.get('sha256') == reference.get('sha256')), None)
                if previous:
                    # Editing a label must not reload a changed external source.
                    item = copy.deepcopy(previous)
                    for name in ('label', 'role'):
                        if name in reference:
                            item[name] = text(reference[name], 200 if name == 'label' else 80)
                    if 'required' in reference:
                        item['required'] = reference['required']
                else:
                    item = self._resource(c, reference)
            total += item.get('size', 0)
            if total > MAX_RESOURCE:
                raise ValueError('每个画像的参考资产总量最多40MB')
            result.append(item)
        return result

    def _save_profile(self, c, value):
        pid = key(value.get('profile_id') or ('profile-' + digest(value['id'])[:24]))
        row = c.execute('SELECT document FROM creator_profiles WHERE id=?', (pid,)).fetchone()
        old = json.loads(row['document']) if row else None
        if type(value.get('base_revision')) is not int or value.get('base_revision') != (old['revision'] if old else 0):
            raise CreatorConflict('画像已有新修订，请重新核对')
        document = value.get('document')
        fields = {'name', 'identity', 'audience', 'voice', 'boundaries', 'default_skills', 'skill_versions', 'task_skill_versions', 'asset_refs', 'active','media_defaults'}
        if not isinstance(document, dict) or set(document) - fields:
            raise ValueError('画像只保存身份、读者、表达、技能和资产引用')
        result = copy.deepcopy(old) if old else {'id': pid, 'account_ids': [], 'default_skills': copy.deepcopy(TASK_DEFAULTS), 'skill_versions': {r['skill_id']: r['version'] for r in c.execute('SELECT skill_id,version FROM creator_skill_pointers WHERE version>0')}, 'asset_refs': [], 'active': True, 'created_at': stamp()}
        for field in ('name', 'identity', 'audience', 'voice', 'boundaries'):
            result[field] = text(document.get(field, result.get(field, '')), 120 if field == 'name' else 12000, field == 'name')
        if 'media_defaults' in document:
            defaults=document['media_defaults']
            if not isinstance(defaults,dict) or set(defaults)-{'speech','image','video','music','transcribe'}:raise ValueError('画像媒体默认值无效')
            for channel,settings in defaults.items():
                if not isinstance(settings,dict) or set(settings)-{'config_id','voice_id'}:raise ValueError('画像只绑定媒体配置和音色引用')
                for field,val in settings.items():text(val,200)
            result['media_defaults']=copy.deepcopy(defaults)
        if 'default_skills' in document:
            result['default_skills'] = self._validate_defaults(c, document['default_skills'])
            for skills in result['default_skills'].values():
                for sid in skills:
                    result.setdefault('skill_versions', {}).setdefault(sid, self._published(c, sid))
        task_pins = result.setdefault('task_skill_versions', {})
        for task, skills in result['default_skills'].items():
            task_pins.setdefault(task, {})
            for sid in skills:
                task_pins[task].setdefault(sid, result['skill_versions'].get(sid, self._published(c, sid)))
        if 'skill_versions' in document:
            if not isinstance(document['skill_versions'], dict) or len(document['skill_versions']) > 40:
                raise ValueError('画像技能版本格式无效')
            for sid, version in document['skill_versions'].items():
                release = self._skill(c, sid, version, False)
                if release['status'] != 'published':
                    raise ValueError('候选技能不能成为画像默认')
                changed_version = result.setdefault('skill_versions', {}).get(sid) != release['version']
                result.setdefault('skill_versions', {})[sid] = release['version']
                if changed_version:
                    for task, skills in result['default_skills'].items():
                        if sid in skills:
                            task_pins[task][sid] = release['version']
        if 'task_skill_versions' in document:
            pins = document['task_skill_versions']
            if not isinstance(pins, dict) or set(pins) - set(TASK_DEFAULTS):
                raise ValueError('任务技能版本范围无效')
            for task, bindings in pins.items():
                if not isinstance(bindings, dict) or set(bindings) - set(result['default_skills'].get(task, [])):
                    raise ValueError('只能设置本任务已选技能的版本')
                for sid, version in bindings.items():
                    release = self._skill(c, sid, version, False)
                    if release['status'] != 'published':
                        raise ValueError('候选技能不能成为画像默认')
                    task_pins.setdefault(task, {})[sid] = release['version']
        if 'active' in document:
            if not isinstance(document['active'], bool):
                raise ValueError('画像状态无效')
            if pid == DEFAULT_PROFILE and not document['active']:
                raise ValueError('默认画像保持可用；可以另选制作身份')
            result['active'] = document['active']
        if 'asset_refs' in document:
            result['asset_refs'] = self._profile_assets(c, pid, document['asset_refs'], old)
        result.update(revision=(old['revision'] if old else 0) + 1, updated_at=stamp())
        self._put_profile(c, result)
        return {'profile': result}

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
        event = {'id': uuid.uuid4().hex, 'skill_id': sid, 'version': version, 'action': action, 'created_at': stamp(), **(extra or {})}
        c.execute('INSERT INTO creator_skill_events VALUES(?,?,?,?,?,?)', (event['id'], sid, version, action, packed(event), event['created_at']))

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
                defaults = profile['default_skills'].setdefault(task, [])
                if sid not in defaults:
                    defaults.append(sid)
                profile.setdefault('task_skill_versions', {}).setdefault(task, {})[sid] = version
            self._validate_defaults(c, profile['default_skills'])
            profile.update(revision=profile['revision'] + 1, updated_at=stamp())
            self._put_profile(c, profile)
        result = {'skill': self._skill(c, sid, version)}
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
                return json.loads(previous['result'])
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
            return response

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
            if release['status'] != 'published' and not allow_trial:
                raise ValueError('候选技能需要明确选择本次试用')
            for resource in release.get('resources', []):
                if resource.get('required') and not resource.get('available'):
                    raise ValueError('技能必要资源缺失')
            skills.append({k: copy.deepcopy(v) for k, v in release.items() if k not in ('history', 'diff', 'base_prompt', 'published_version', 'is_current')})
        if task in ('poster', 'article', 'change', 'image'):
            if 'delivery-review' not in seen:
                raise ValueError('制作任务须保留交付核验技能；尚未启动制作')
            producers = {'content-writing'} if task == 'article' else {'image-production'} if task == 'image' else {'content-writing', 'image-production'}
            if not producers.intersection(seen):
                raise ValueError('请选择能完成本次任务的写作或配图技能；尚未启动制作')
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
            reserved = task in ('poster', 'article', 'change', 'image') and skill['id'] == 'delivery-review'
            skill['execution_role'] = 'reserved_independent' if reserved else 'active'
            if reserved:
                lines.append('## 后续独立检查\n' + skill['name'] + ' v' + str(skill['version']) + ' 已冻结供交付后的独立只读检查使用。本阶段执行制作；检查者的只读约束只作用于后续检查过程。')
                continue
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

    def resource(self, skill_id, version, index):
        with self.store.connect() as c:
            release = self._skill(c, skill_id, version, False)
            if not isinstance(index, int) or index < 0 or index >= len(release['resources']):
                raise ValueError('找不到技能资源')
            resource = release['resources'][index]
            row = c.execute('SELECT bytes FROM creator_skill_blobs WHERE sha256=?', (resource.get('sha256'),)).fetchone()
            if not row:
                raise ValueError('原件未取得')
            raw = bytes(row['bytes'])
            if digest(raw) != resource['sha256']:
                raise CreatorConflict('冻结资源字节不符')
            return {'name': pathlib.PurePosixPath(resource['path']).name, 'path': resource['path'], 'bytes': raw, 'sha256': resource['sha256']}

    def profile_resource(self, profile_id, revision, index):
        if type(revision) is not int or revision < 1 or type(index) is not int or index < 0:
            raise ValueError('画像资产修订无效')
        with self.store.connect() as c:
            profile = self._profile(c, key(profile_id), revision)
            refs = profile.get('asset_refs', [])
            if index >= len(refs):
                raise ValueError('找不到此版本的画像资产')
            reference = refs[index]
            row = c.execute('SELECT bytes FROM creator_skill_blobs WHERE sha256=?', (reference.get('sha256'),)).fetchone()
            if not row or not reference.get('available'):
                raise ValueError('画像资产原件未取得')
            raw = bytes(row['bytes'])
            if digest(raw) != reference['sha256']:
                raise CreatorConflict('画像冻结资产字节不符')
            mime = reference.get('mime') or mimetypes.guess_type(reference['path'])[0] or 'application/octet-stream'
            if mime not in ('image/png', 'image/jpeg', 'image/webp'):
                mime = 'application/octet-stream'
            return {'name': reference.get('original_name') or pathlib.PurePosixPath(reference['path']).name,
                    'mime': mime, 'bytes': raw, 'sha256': reference['sha256']}

    def export(self, skill_id, version=None):
        with self.store.connect() as c:
            release = self._skill(c, key(skill_id), version, False)
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('SKILL.md', release['prompt'])
            archive.writestr('release.json', packed(release))
            archive.writestr('调用说明.md', '# ' + release['name'] + ' v' + str(release['version']) + '\n\n'
                '本包来自工作台已保存的技能版本及资源快照。工作台中选择创作画像和任务后，指定本技能与版本；候选只供明确试用，发布并设置适用范围后才影响后续默认。\n\n'
                'SKILL.md 是实际可读指令；release.json 保存输入输出合同、资源原路径与SHA、适用任务和版本。resources/ 的文件按资源清单序号保存，与原件逐字节对应。原路径相对于 neo-content 项目根目录，不代表允许覆盖当前规范。\n\n'
                '脚本与工具依赖须在实际环境可用；不同模型和生图工具不保证相同效果。参考资料、图片和原话是材料，不扩大发布、账号或写入授权。格式检查、制作方声明、实际工具证据和用户认可分别判断。\n')
            for index, resource in enumerate(release['resources']):
                if resource.get('available'):
                    item = self.resource(skill_id, release['version'], index)
                    archive.writestr('resources/' + str(index + 1) + '-' + item['name'], item['bytes'])
        return output.getvalue()

    def materialize(self, snapshot, folder, selected_paths=None, c=None, write=True):
        """Make only selected/required frozen resources available to local tools.

        Optional style variants are catalogue entries, never all attached to a
        production task. Callers supply the selected recipe reference paths.
        """
        destination = pathlib.Path(folder).resolve()
        if not destination.is_relative_to(self.root.resolve()):
            raise ValueError('冻结输入目录必须位于工作台项目内')
        selected = set(selected_paths or [])
        result, seen = [], set()
        if c is None:
            with self.store.connect() as connection:
                return self.materialize(snapshot, folder, selected_paths, connection, write)
        if c is not None:
            groups = [{'resources': snapshot.get('profile', {}).get('asset_refs', [])}, *snapshot.get('skills', [])]
            for skill in groups:
                for resource in skill.get('resources', []):
                    if not resource.get('available') or resource.get('path') not in selected and not resource.get('required'):
                        continue
                    fingerprint = resource['sha256']
                    if fingerprint in seen:
                        continue
                    seen.add(fingerprint)
                    row = c.execute('SELECT bytes FROM creator_skill_blobs WHERE sha256=?', (fingerprint,)).fetchone()
                    if not row or digest(bytes(row['bytes'])) != fingerprint:
                        raise CreatorConflict('冻结输入资源缺失或字节不符')
                    path = destination / (fingerprint + '-' + pathlib.PurePosixPath(resource['path']).name)
                    if not write:
                        pass
                    elif path.exists():
                        if digest(path.read_bytes()) != fingerprint:
                            raise CreatorConflict('本机冻结输入字节发生变化')
                    else:
                        destination.mkdir(parents=True, exist_ok=True)
                        try:
                            with path.open('xb') as handle:
                                handle.write(bytes(row['bytes']))
                        except FileExistsError:
                            if digest(path.read_bytes()) != fingerprint:
                                raise CreatorConflict('本机冻结输入字节发生变化')
                    result.append({'original_path': resource['path'], 'path': str(path), 'sha256': fingerprint})
        return result


def read_owner(c, work_id):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='creator_work_owners'").fetchone():
        return None
    row = c.execute('SELECT document FROM creator_work_owners WHERE work_id=?', (key(work_id),)).fetchone()
    return json.loads(row['document']) if row else None


def service(box, c=None):
    runtime = getattr(box, 'creator', None)
    if runtime is None:
        runtime = CreatorRuntime(box, c=c)
        box.creator = runtime
    return runtime
