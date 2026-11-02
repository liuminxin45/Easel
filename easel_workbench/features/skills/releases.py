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

class SkillReleases:
    def __init__(self, *, store, root, project, catalog):
        self.store=store
        self.root=root
        self.project=project
        self.catalog=catalog

    def _safe(self, relative):
        if not isinstance(relative, str) or not relative or len(relative) > 2000 or '\x00' in relative or '\\' in relative or pathlib.PurePosixPath(relative).is_absolute():
            raise ValueError('资源路径无效')
        path = (self.project / relative).resolve()
        if self.catalog is not None and not path.exists() and pathlib.PurePosixPath(relative).parts[0] in ('规范','资料'):
            path=(self.project/'skills/shared/workbench'/relative).resolve()
        if not path.is_relative_to(self.project) or '..' in pathlib.PurePosixPath(relative).parts:
            raise ValueError('资源不能离开内容项目')
        if pathlib.PurePosixPath(relative).parts[0] not in ('规范', '资料', '工具', '内容', '.agents', 'skills'):
            raise ValueError('技能只引用创作规范、材料、工具和技能资源')
        return path

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

    def _event(self, c, sid, version, action, extra=None):
        event = {'id': uuid.uuid4().hex, 'skill_id': sid, 'version': version, 'action': action, 'created_at': stamp(), **(extra or {})}
        c.execute('INSERT INTO creator_skill_events VALUES(?,?,?,?,?,?)', (event['id'], sid, version, action, packed(event), event['created_at']))

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

    def export(self, skill_id, version=None):
        with self.store.connect() as c:
            release = self._skill(c, key(skill_id), version, False)
        output = io.BytesIO()
        with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('SKILL.md', release['prompt'])
            archive.writestr('release.json', packed(release))
            archive.writestr('调用说明.md', '# ' + release['name'] + ' v' + str(release['version']) + '\n\n'
                '本包来自工作台已保存的技能版本及资源快照。工作台中选择创作画像和任务后，指定本技能与版本；候选只供明确试用，发布并设置适用范围后才影响后续默认。\n\n'
                'SKILL.md 是实际可读指令；release.json 保存输入输出合同、资源原路径与SHA、适用任务和版本。resources/ 的文件按资源清单序号保存，与原件逐字节对应。项目内置技能路径相对于 Easel，旧版本路径属于其原始来源项目；导出不授权覆盖当前规范。\n\n'
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
