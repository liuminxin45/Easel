"""Human-confirmed, immutable production examples; never another skill registry."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

from easel_workbench.features.skills.records import CreatorConflict
from easel_workbench.runtime.desk import stamp

FORMATS = {'oil-pig-poster': 'poster', 'oil-pig-article': 'article'}
MAX_REFERENCES = 4
MAX_BYTES = 40 * 1024 * 1024


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,160}', value):
        raise ValueError('模板身份无效')
    return value


def _text(value, limit, label):
    if not isinstance(value, str) or not value.strip() or len(value) > limit or '\x00' in value:
        raise ValueError(label + '为空或过长')
    return value


class Service:
    def __init__(self, box):
        self.box, self.store, self.root = box, box.store, Path(box.root).resolve()

    def ensure(self, connection):
        connection.execute('''CREATE TABLE IF NOT EXISTS production_templates(
            id TEXT PRIMARY KEY, operation_id TEXT UNIQUE NOT NULL,
            signature TEXT NOT NULL, profile_id TEXT NOT NULL,
            format TEXT NOT NULL, document TEXT NOT NULL)''')

    def _exists(self, connection):
        return bool(connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='production_templates'").fetchone())

    def _skill_sha(self, skill_id):
        path = self.root / 'skills/builtin' / identifier(skill_id) / 'SKILL.md'
        if path.is_symlink() or not path.is_file():
            raise ValueError('模板对应技能不可用')
        from easel_workbench.skill_catalog import parse_skill
        metadata, _ = parse_skill(path.read_text(encoding='utf-8-sig'))
        resources = metadata.get('metadata', {}).get('openclaw', {}).get('workbench', {}).get('resources', [])
        files = {path.relative_to(self.root).as_posix(): digest(path.read_bytes())}
        for item in resources:
            if not item.get('required'):
                continue
            target = self.root / item['path']
            if target.is_symlink() or not target.is_file() or not target.resolve().is_relative_to(path.parent.resolve()):
                raise ValueError('模板对应技能的必要资源不可用')
            files[item['path']] = digest(target.read_bytes())
        return digest(packed(files).encode('utf-8'))

    def _compatible(self, document, *, verify_references=True, skill_cache=None):
        try:
            skill_id = document['skill_id']
            if skill_cache is not None:
                if skill_id not in skill_cache:
                    skill_cache[skill_id] = self._skill_sha(skill_id)
                skill_sha = skill_cache[skill_id]
            else:
                skill_sha = self._skill_sha(skill_id)
            if skill_sha != document['skill_sha256']:
                return False, '对应技能已更新，请重新核对并确认模板'
            for reference in document['references']:
                path = self._path(reference['path'])
                if (not path.is_file() or path.stat().st_size != reference['size']
                        or verify_references and digest(path.read_bytes()) != reference['sha256']):
                    return False, '模板参考文件缺失或发生变化'
            return True, ''
        except (ValueError, OSError):
            return False, '对应技能或模板参考当前不可用'

    def _path(self, relative):
        path = self.root / relative
        permitted = self.root / 'data/production-insights/templates'
        if not path.resolve().is_relative_to(permitted.resolve()):
            raise ValueError('模板参考路径无效')
        current = self.root
        for part in Path(relative).parts:
            current /= part
            if current.is_symlink() or getattr(current, 'is_junction', lambda: False)():
                raise ValueError('模板不允许符号链接')
        return path

    def _artifact(self, value):
        path = Path(value)
        relative = path.relative_to(self.root)
        if not (relative.parts[:2] == ('data', 'artifacts') or relative.parts[:1] == ('outputs',)):
            raise ValueError('模板参考不是当前项目已登记的产物')
        current = self.root
        for part in relative.parts:
            if part in ('.', '..'):
                raise ValueError('模板参考路径无效')
            current /= part
            if current.is_symlink() or getattr(current, 'is_junction', lambda: False)():
                raise ValueError('模板参考不能经链接跳转')
        if not current.resolve().is_relative_to(self.root) or not current.is_file():
            raise ValueError('模板参考文件不存在')
        return current

    def _public(self, document, *, summary=False, skill_cache=None):
        available, reason = self._compatible(document, verify_references=not summary, skill_cache=skill_cache)
        keys = ('id', 'revision', 'name', 'profile_id', 'format', 'skill_id', 'style',
                'source_work_id', 'source_version_id', 'created_at', 'review_item_ids')
        result = {key: document[key] for key in keys}
        result.update(available=available, reason=reason)
        if not summary:
            result.update(method=document['method'], references=[{
                key: item[key] for key in ('id', 'name', 'mime', 'sha256', 'size')
            } for item in document['references']])
        return result

    def list(self, profile_id, format):
        identifier(profile_id)
        if format not in FORMATS.values():
            raise ValueError('模板格式无效')
        with self.store.connect() as connection:
            if not self._exists(connection):
                return []
            rows = connection.execute('SELECT document FROM production_templates WHERE profile_id=? AND format=? ORDER BY rowid DESC LIMIT 100', (profile_id, format)).fetchall()
        skill_cache = {}
        return [self._public(json.loads(row[0]), summary=True, skill_cache=skill_cache) for row in rows]

    def get(self, template_id, profile_id, format, revision=None):
        document = self._document(template_id, profile_id, format, revision)
        result = self._public(document)
        if not result['available']:
            raise CreatorConflict(result['reason'])
        return result

    def operation_result(self, operation_id):
        with self.store.connect() as connection:
            if not self._exists(connection):
                return None
            row = connection.execute('SELECT document FROM production_templates WHERE operation_id=?', (identifier(operation_id),)).fetchone()
        return self._public(json.loads(row[0])) if row else None

    def _document(self, template_id, profile_id, format, revision=None):
        with self.store.connect() as connection:
            if not self._exists(connection):
                raise ValueError('模板不存在，或不属于当前画像及格式')
            row = connection.execute('SELECT document FROM production_templates WHERE id=? AND profile_id=? AND format=?',
                                     (identifier(template_id), identifier(profile_id), format)).fetchone()
        if not row:
            raise ValueError('模板不存在，或不属于当前画像及格式')
        document = json.loads(row[0])
        if revision is not None and revision != document['revision']:
            raise CreatorConflict('所选模板版本不一致，请重新核对')
        return document

    def materials(self, template_id, profile_id, format, revision):
        document = self._document(template_id, profile_id, format, revision)
        available, reason = self._compatible(document, verify_references=False)
        if not available:
            raise CreatorConflict(reason)
        summary = {key: document[key] for key in ('id', 'revision', 'name', 'skill_id', 'style', 'source_work_id', 'source_version_id', 'review_item_ids')}
        snapshot = dict(summary, method=document['method'], references=[{
            key: item[key] for key in ('name', 'mime', 'sha256', 'size')
        } for item in document['references']])
        result = [(Path('template.json'), packed(snapshot).encode('utf-8'), 'template', document['name'], None)]
        for item in document['references']:
            raw = self._path(item['path']).read_bytes()
            if digest(raw) != item['sha256']:
                raise CreatorConflict('模板参考发生变化，未冻结新回合')
            result.append((Path(item['name']), raw, 'template-reference', item['name'], None))
        return summary, result

    def create(self, work_id, version_id, value):
        identifier(work_id); identifier(version_id)
        if not isinstance(value, dict) or set(value) - {'operation_id', 'name', 'method', 'style', 'reference_ids', 'review_item_ids', 'confirmed'}:
            raise ValueError('模板确认字段无效')
        if value.get('confirmed') is not True:
            raise ValueError('优秀模板须由用户明确确认')
        operation_id = identifier(value.get('operation_id'))
        name = _text(value.get('name'), 100, '模板名称')
        method = _text(value.get('method'), 20000, '制作方法与规范')
        references = value.get('reference_ids', [])
        if not isinstance(references, list) or len(references) > MAX_REFERENCES or any(not isinstance(item, str) for item in references) or len(set(references)) != len(references):
            raise ValueError('每个模板最多选择四份不重复参考产物')
        for reference in references:
            identifier(reference)
        review_items = value.get('review_item_ids', [])
        if not isinstance(review_items, list) or len(review_items) > 30 or any(not isinstance(item, str) for item in review_items) or len(set(review_items)) != len(review_items):
            raise ValueError('模板复盘建议身份无效')
        for item in review_items:
            identifier(item)
        signature = digest(packed({'work_id': work_id, 'version_id': version_id, **value}).encode('utf-8'))
        with self.store.connect() as connection:
            self.ensure(connection)
            old = connection.execute('SELECT signature,document FROM production_templates WHERE operation_id=?', (operation_id,)).fetchone()
            if old:
                if old[0] != signature:
                    raise CreatorConflict('同一次模板确认已有不同输入')
                return self._public(json.loads(old[1]))
            row = connection.execute('SELECT value FROM toolbox_meta WHERE key=?', ('native-review:' + version_id,)).fetchone()
            source = json.loads(row[0]) if row else {}
            receipt = source.get('receipt') or {}
            if (receipt.get('work_id') != work_id or receipt.get('version_id') != version_id
                    or receipt.get('status') != 'completed' or not receipt.get('whole_ready')
                    or receipt.get('skill_id') not in FORMATS):
                raise ValueError('只能将本项目完整交付的油猪贴图或文章确认为模板')
            turn_row = connection.execute('SELECT document FROM easel_chat_turns WHERE id=?', (version_id,)).fetchone()
            turn = json.loads(turn_row[0]) if turn_row else {}
            if turn.get('status') != 'completed' or not (turn.get('native_turn_id') or (turn.get('execution_identity') or {}).get('kind') in ('jsonrpc_request', 'cli_result_sha256')):
                raise ValueError('模板来源缺少准确完成回执')
            from easel_workbench.features.news_creation import _catalog, _style
            creation = (turn.get('context') or {}).get('creation') or {}
            style = _style(value.get('style', creation.get('style', {})), _catalog(self.root)[1])
            artifacts = {row['id']: dict(row) for row in connection.execute('SELECT id,name,path,mime FROM artifacts WHERE task_id=?', (version_id,))}
        if review_items:
            from easel_workbench.features.production_insights.reviews import Service as Reviews
            review = Reviews(self.box).view(work_id, version_id)
            approved = {item['id'] for item in review.get('items', []) if item.get('status') == 'approved'}
            if review.get('version_id') != version_id or review.get('work_id') != work_id or not set(review_items).issubset(approved):
                raise ValueError('仅能将本版已同意的复盘建议关联到模板')
        selected, total = [], 0
        original = {item['path']: item['sha256'] for item in source.get('files', [])}
        for reference_id in references:
            item = artifacts.get(reference_id)
            if not item or not item['mime'].startswith(('image/', 'text/')):
                raise ValueError('请选择该准确版本的图片或文本参考')
            path = self._artifact(item['path'])
            raw = path.read_bytes()
            if digest(raw) != original.get(str(path)):
                raise CreatorConflict('模板来源原件已变化，未确认模板')
            total += len(raw)
            if total > MAX_BYTES:
                raise ValueError('模板参考总量最多40MB')
            selected.append((item, raw))
        template_id = 'template-' + digest(operation_id.encode())[:24]
        directory = self._path('data/production-insights/templates/' + template_id)
        directory.mkdir(parents=True, exist_ok=True)
        frozen = []
        for index, (item, raw) in enumerate(selected):
            name_part = str(index).zfill(2) + '-' + Path(item['name']).name
            path = self._path((directory / name_part).relative_to(self.root))
            if path.exists():
                if path.read_bytes() != raw:
                    raise CreatorConflict('已冻结模板参考不一致')
            else:
                with path.open('xb') as output:
                    output.write(raw)
            frozen.append({'id': item['id'], 'name': name_part, 'mime': item['mime'], 'path': path.relative_to(self.root).as_posix(), 'sha256': digest(raw), 'size': len(raw)})
        document = {'id': template_id, 'name': value['name'], 'method': method, 'style': style,
                    'profile_id': receipt['profile_id'], 'format': receipt['format'], 'skill_id': receipt['skill_id'],
                    'skill_sha256': self._skill_sha(receipt['skill_id']), 'source_work_id': work_id,
                    'source_version_id': version_id, 'references': frozen, 'created_at': stamp(),
                    'confirmed_by': 'owner', 'review_item_ids': review_items}
        document['revision'] = digest(packed(document).encode('utf-8'))
        with self.store.connect() as connection:
            self.ensure(connection)
            connection.execute('BEGIN IMMEDIATE')
            old = connection.execute('SELECT signature,document FROM production_templates WHERE operation_id=?', (operation_id,)).fetchone()
            if old:
                if old[0] != signature:
                    raise CreatorConflict('同一次模板确认已有不同输入')
                return self._public(json.loads(old[1]))
            connection.execute('INSERT INTO production_templates VALUES(?,?,?,?,?,?)',
                               (template_id, operation_id, signature, document['profile_id'], document['format'], packed(document)))
        return self._public(document)
