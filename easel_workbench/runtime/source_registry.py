"""Private, versioned source configuration. No upstream registry is rewritten."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import uuid

from easel.trends.protocol import MAX_SCRIPT_BYTES
from easel.trends.sources import _source, display_label

PUBLIC_SOURCE_FIELDS = ('id', 'label', 'type', 'enabled', 'default', 'builtin', 'revision', 'refresh_seconds')


def packed(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def migrate(connection):
    connection.executescript('''
CREATE TABLE IF NOT EXISTS collection_source_versions(source_id TEXT NOT NULL,revision INTEGER NOT NULL,payload TEXT NOT NULL,PRIMARY KEY(source_id,revision));
CREATE TABLE IF NOT EXISTS collection_source_operations(operation_id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL);
''')


class SourceRegistry:
    def __init__(self, store, root):
        self.store, self.root = store, Path(root).resolve()

    def baseline(self):
        path = self.root/'sources.json'
        if not path.is_file():
            path = Path(__file__).with_name('sources.json')
        return json.loads(path.read_text(encoding='utf-8'))

    def entries(self, connection=None, *, include_deleted=False):
        if connection is None:
            with self.store.connect() as connection:
                return self.entries(connection, include_deleted=include_deleted)
        entries = {key: {**meta, 'id': key, 'label': meta['name'], 'builtin': True,
                         'enabled': True, 'default': True, 'type': 'python', 'revision': 0}
                   for key, meta in self.baseline().items()}
        rows = connection.execute('''SELECT v.* FROM collection_source_versions v JOIN
            (SELECT source_id,MAX(revision) AS revision FROM collection_source_versions GROUP BY source_id) latest
            USING(source_id,revision) ORDER BY v.rowid''')
        for row in rows:
            entries[row['source_id']] = {**json.loads(row['payload']), 'revision': row['revision']}
        return {key: row for key, row in entries.items() if include_deleted or not row.get('deleted')}

    def public(self):
        # Deliberately never return request headers, URLs with query credentials or script paths.
        keys = PUBLIC_SOURCE_FIELDS
        return {'version': 1, 'sources': [{key: row[key] for key in keys if key in row}
                for row in self.entries().values()], 'scripts': [], 'warnings': [],
                'python_template': Path(__file__).parents[2].joinpath('easel/trends/template.py').read_text(encoding='utf-8'),
                'script_max_bytes': MAX_SCRIPT_BYTES}

    def update(self, value):
        operation = value.get('operation_id')
        if not isinstance(operation, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', operation):
            raise ValueError('来源操作标识无效')
        signature = hashlib.sha256(packed(value).encode()).hexdigest()
        with self.store.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            old = connection.execute('SELECT * FROM collection_source_operations WHERE operation_id=?', (operation,)).fetchone()
            if old:
                if old['signature'] != signature:
                    raise ValueError('同一来源操作标识不能用于不同内容')
                return json.loads(old['result'])
            entries = self.entries(connection, include_deleted=True)
            action = value.get('action')
            if action == 'add':
                if sum(not row['builtin'] and not row.get('deleted') for row in entries.values()) >= 64:
                    raise ValueError('最多配置 64 个自定义来源')
                identifier = 'custom-' + uuid.uuid4().hex[:12]
                row = self.prepare(identifier, value)
                revision = 1
            elif action in ('toggle', 'delete'):
                identifier = value.get('source_id')
                row = entries.get(identifier)
                if not row or row.get('deleted'):
                    raise ValueError('来源不存在或已删除，请刷新列表')
                if value.get('expected_revision') != row['revision']:
                    raise ValueError('来源版本已变化，请刷新列表后重试')
                row = dict(row)
                revision = row.pop('revision') + 1
                if action == 'delete':
                    if row['builtin']:
                        raise ValueError('内置来源只能停用')
                    row.update(deleted=True, enabled=False)
                else:
                    if type(value.get('enabled')) is not bool:
                        raise ValueError('来源启用状态无效')
                    row['enabled'] = value['enabled']
            else:
                raise ValueError('来源操作无效')
            connection.execute('INSERT INTO collection_source_versions VALUES(?,?,?)', (identifier, revision, packed(row)))
            result = {'ok': True, 'id': identifier, 'revision': revision,
                      'deleted': bool(row.get('deleted')),
                      'source': None if row.get('deleted') else {key: item for key, item in {**row, 'revision': revision}.items() if key in PUBLIC_SOURCE_FIELDS}}
            connection.execute('INSERT INTO collection_source_operations VALUES(?,?,?)', (operation, signature, packed(result)))
            return result

    def receipt(self, operation):
        with self.store.connect() as connection:
            row=connection.execute('SELECT result FROM collection_source_operations WHERE operation_id=?',(operation,)).fetchone()
        return {'id':operation,'state':'received','result':json.loads(row['result'])} if row else {'id':operation,'state':'unknown'}

    def prepare(self, identifier, value):
        row = {'id': identifier, 'label': value.get('label'), 'type': value.get('type'),
               'refresh_seconds': value.get('refresh_seconds', 300), 'default': True}
        if row['type'] == 'python':
            from easel.trends.management import _prepare_script
            directory = self.root/'data/collection/source-assets'
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='validate-', dir=directory) as temporary:
                checked = _prepare_script(row, value, Path(temporary), dict(os.environ))
                raw = checked.read_bytes()
                digest = hashlib.sha256(raw).hexdigest()
                target = directory/(digest+'.py')
                try:
                    with target.open('xb') as output:
                        output.write(raw)
                except FileExistsError:
                    if target.read_bytes() != raw:
                        raise ValueError('来源脚本资产 SHA 不匹配')
                row['script'] = target.relative_to(self.root).as_posix()
                row['script_sha256'] = digest
                row.pop('uploaded_script', None)
        else:
            row.update(url=value.get('url'), headers=value.get('headers', {}))
            if row['type'] == 'http':
                row['method']=value.get('method','GET')
                if row['method']=='POST':row['body']=value.get('body',{})
        source = _source(row, self.root)
        return {**row, 'label': display_label(source.label), 'name': display_label(source.label),
                'feed': identifier, 'enabled': True, 'builtin': False}

    def source(self, snapshot):
        row = dict(snapshot)
        if row.get('builtin'):
            raise ValueError('内置来源保留专用采集流程')
        if row['type'] == 'python':
            path = (self.root/row['script']).resolve()
            if not path.is_relative_to(self.root/'data/collection/source-assets') or path.is_symlink():
                raise ValueError('来源脚本路径无效')
            if hashlib.sha256(path.read_bytes()).hexdigest() != row['script_sha256']:
                raise ValueError('来源脚本 SHA 不匹配')
        return _source(row, self.root)
