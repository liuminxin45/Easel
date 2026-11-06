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

def read_owner(c, work_id):
    if not c.execute("SELECT 1 FROM sqlite_master WHERE name='creator_work_owners'").fetchone():
        return None
    row = c.execute('SELECT document FROM creator_work_owners WHERE work_id=?', (key(work_id),)).fetchone()
    return json.loads(row['document']) if row else None


def read_profile(c, profile_id, revision=None):
    """Read the existing profile without initializing skill releases or defaults."""
    if revision is None:
        row = c.execute('SELECT document FROM creator_profiles WHERE id=?', (key(profile_id),)).fetchone()
    else:
        row = c.execute('SELECT document FROM creator_profile_history WHERE id=? AND revision=?', (key(profile_id), revision)).fetchone()
    if not row:
        raise ValueError('找不到创作画像或指定修订')
    return json.loads(row['document'])


class ProfileService:
    def __init__(self, *, store, root, skills):
        self.store=store
        self.root=root
        self._skill=skills._skill
        self._published=skills._published
        self._safe=skills._safe
        self._resource=skills._resource

    def _profile(self, c, profile_id, revision=None):
        return read_profile(c, profile_id, revision)

    def _put_profile(self, c, profile):
        for index, resource in enumerate(profile.get('asset_refs', [])):
            resource['url'] = '/api/creator/profiles/' + profile['id'] + '/assets/' + str(profile['revision']) + '/' + str(index)
        raw = packed(profile)
        c.execute('INSERT INTO creator_profile_history VALUES(?,?,?)', (profile['id'], profile['revision'], raw))
        c.execute('INSERT INTO creator_profiles VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,document=excluded.document', (profile['id'], profile['revision'], raw))

    def bind_work(self, c, work_id, selection=None, allow_historical=False, *, persist=True):
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
        if previous is None and persist:
            c.execute('INSERT INTO creator_work_owners VALUES(?,?,?,?,?)', (work_id, profile_id, profile['revision'], packed(owner), owner['created_at']))
        return owner

    def _validate_defaults(self, c, value):
        if not isinstance(value, dict) or set(value) - set(TASK_DEFAULTS):
            raise ValueError('默认技能任务类型无效')
        result = {}
        for task, skills in value.items():
            if not isinstance(skills, list) or not skills and task not in RETIRED_TASKS or len(skills) > 8 or any(not isinstance(sid, str) for sid in skills) or len(skills) != len(set(skills)):
                raise ValueError('每项任务选择1至8个不同技能')
            for sid in skills:
                if not self._published(c, sid):raise ValueError('候选技能不能成为画像默认')
                require_task(self._skill(c, sid, self._published(c, sid), False), task)
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
        fields = {'name', 'identity', 'audience', 'voice', 'boundaries', 'default_skills', 'skill_versions', 'task_skill_versions', 'asset_refs', 'active','media_defaults','creation_defaults'}
        if not isinstance(document, dict) or set(document) - fields:
            raise ValueError('画像只保存身份、读者、表达、技能和资产引用')
        from easel_workbench.features.skills.retirement import native_mode
        result = copy.deepcopy(old) if old else {'id': pid, 'account_ids': [], 'default_skills': {} if native_mode(self.root) else copy.deepcopy(TASK_DEFAULTS), 'asset_refs': [], 'active': True, 'created_at': stamp()}
        for field in ('name', 'identity', 'audience', 'voice', 'boundaries'):
            result[field] = text(document.get(field, result.get(field, '')), 120 if field == 'name' else 12000, field == 'name')
        if 'creation_defaults' in document:
            from easel_workbench.features.news_creation import validate_defaults
            result['creation_defaults'] = validate_defaults(self.root, document['creation_defaults'])
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
        # Ordinary profile edits must not recreate retired skill version pins.
        if any(field in document for field in ('default_skills','skill_versions','task_skill_versions')):
            task_pins = result.setdefault('task_skill_versions', {})
            for task, skills in result['default_skills'].items():
                task_pins.setdefault(task, {})
                for sid in skills:
                    task_pins[task].setdefault(sid, result.get('skill_versions', {}).get(sid, self._published(c, sid)))
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
                            require_task(release, task)
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
                    require_task(release, task)
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
