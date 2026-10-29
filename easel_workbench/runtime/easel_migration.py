"""Selective copy importer. Source files and Easel login directories stay intact."""
import copy
import hashlib
import json
import pathlib
import shutil

from easel_workbench.runtime.desk import stamp
from easel_workbench.runtime.toolbox_store import ident, pack
from easel_workbench.runtime.easel_integration import IntegrationConflict, digest, service as media_service


class EaselMigration:
    def __init__(self, box, source=None):
        self.box, self.store = box, box.store
        self.root = pathlib.Path(box.root).resolve()
        self.source = pathlib.Path(source or self.root.parent / 'Easel').resolve()
        self.media = media_service(box)

    def _files(self, directory):
        base = directory.resolve()
        if not base.is_relative_to(self.source) or directory.is_symlink():
            raise ValueError('迁入来源目录无效')
        result, total = [], 0
        for path in sorted(directory.rglob('*')):
            if path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(base) and not any(p.startswith('.') or p in ('node_modules', '__pycache__', 'venv') for p in path.relative_to(directory).parts):
                if path.stat().st_size > 512 * 1024 * 1024:
                    continue
                total += path.stat().st_size
                if total > 2 * 1024 * 1024 * 1024 or len(result) >= 2000:
                    raise ValueError('单项迁入超出2GB或2000个文件，请拆分目录')
                result.append({'relative': str(path.relative_to(self.source)).replace('\\', '/'), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': path.stat().st_size})
        return result

    def inventory(self):
        items = []
        if not self.source.is_dir():
            return {'items': [], 'fingerprint': digest([]), 'notice': '本机尚未找到独立 Easel 项目'}
        with self.store.connect() as c:
            imported = {r['source_id'] for r in c.execute('SELECT source_id FROM media_imports')}
        for category, parent in [('画像', 'profiles'), ('作品', 'outputs')]:
            folder = self.source / parent
            if not folder.is_dir() or folder.is_symlink():
                continue
            for directory in sorted(folder.iterdir()):
                if not directory.is_dir() or directory.name.startswith(('_', '.')) or directory.is_symlink():
                    continue
                files = self._files(directory)
                if not files:
                    continue
                fingerprint = digest(files)
                sid = digest([str(directory.relative_to(self.source)), fingerprint])
                items.append({'id': sid, 'category': category, 'name': directory.name, 'relative': str(directory.relative_to(self.source)).replace('\\', '/'),
                              'files': files, 'sha256': fingerprint, 'duplicate': sid in imported, 'size': sum(f['size'] for f in files)})
        # Provider metadata is inventoried without exposing or copying secrets.
        for candidate in (self.source / '.env', self.source / '.local/.env'):
            if candidate.is_file() and not candidate.is_symlink():
                sid = digest([str(candidate.relative_to(self.source)), hashlib.sha256(candidate.read_bytes()).hexdigest()])
                names = [l.split('=', 1)[0].strip() for l in candidate.read_text(encoding='utf-8-sig').splitlines() if '=' in l and not l.lstrip().startswith('#')]
                items.append({'id': sid, 'category': '配置', 'name': '媒体配置（凭据重新录入）', 'relative': str(candidate.relative_to(self.source)).replace('\\', '/'), 'sha256': hashlib.sha256(candidate.read_bytes()).hexdigest(), 'fields': names, 'duplicate': sid in imported})
        profiles=[{k:p[k] for k in ('id','name','revision')} for p in self.box.creator.bootstrap()['profiles'] if p.get('active',True)]
        return {'items': items, 'fingerprint': digest(items), 'profiles':profiles, 'source': str(self.source), 'credentials': '独立重新连接；不复制登录目录', 'checked_at': stamp()}

    def command(self, value):
        operation = ident(value.get('id'))
        with self.store.connect() as c:
            previous=c.execute('SELECT signature,result FROM media_operations WHERE id=?',(operation,)).fetchone()
        if previous:
            if previous['signature']!=digest(value):raise IntegrationConflict('同一迁入操作不能更换所选内容')
            return json.loads(previous['result'])
        inventory = self.inventory()
        if value.get('fingerprint') != inventory['fingerprint']:
            raise IntegrationConflict('Easel 原件或迁入清单已变化，请重新扫描')
        selected = value.get('selected')
        if not isinstance(selected, list) or not selected or len(set(selected)) != len(selected) or len(selected) > 100:
            raise ValueError('请选择1至100个不同迁入项目')
        items = {i['id']: i for i in inventory['items']}
        if any(s not in items for s in selected):
            raise ValueError('迁入项目不在本次清单中')
        signature = digest(value)
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old = c.execute('SELECT * FROM media_operations WHERE id=?', (operation,)).fetchone()
            if old:
                if old['signature'] != signature:
                    raise IntegrationConflict('同一迁入操作不能更换所选内容')
                return json.loads(old['result'])
            imported, skipped = [], []
            target_profile=value.get('target_profile_id') or 'oil-pig'
            profile=self.box.creator._profile(c,target_profile)
            if not profile.get('active',True):raise ValueError('目标画像已停用，请重新选择')
            if value.get('target_profile_revision',profile['revision'])!=profile['revision']:raise IntegrationConflict('目标画像已变化，请重新扫描归属')
            for sid in selected:
                if c.execute('SELECT 1 FROM media_imports WHERE source_id=?', (sid,)).fetchone():
                    skipped.append(sid)
                    continue
                item = items[sid]
                destination = self.root / 'data/easel-imports' / sid
                destination.mkdir(parents=True, exist_ok=True)
                for file in item.get('files', []):
                    original = (self.source / file['relative']).resolve()
                    if not original.is_relative_to(self.source) or original.is_symlink() or hashlib.sha256(original.read_bytes()).hexdigest() != file['sha256']:
                        raise IntegrationConflict('迁入时来源文件变化，未覆盖原件')
                    target = destination / pathlib.Path(file['relative']).relative_to(item['relative'])
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != file['sha256']:
                        raise IntegrationConflict('迁入副本字节冲突，未覆盖已有文件')
                    if not target.exists():
                        shutil.copyfile(original, target)
                document = {k: copy.deepcopy(v) for k, v in item.items() if k != 'duplicate'}
                document.update(imported_at=stamp(), operation_id=operation)
                if item['category'] == '画像':
                    def read(name):
                        p = destination / name
                        value=p.read_text(encoding='utf-8-sig') if p.is_file() else ''
                        if len(value)>12000:raise ValueError('画像字段超过12000字，请先拆分；原件未改写')
                        return value
                    pid = 'import-profile-' + sid[:20]
                    # Import as an independent profile, with raw experience kept
                    # in the copy/provenance rather than promoted to rules.
                    result = self.box.creator._save_profile(c, {'id': operation + '-' + sid[:8], 'profile_id': pid, 'base_revision': 0, 'document':
                        {'name': item['name'][:120], 'identity': read('identity.md'), 'audience': read('audience.md'), 'voice': read('style.md'), 'boundaries': read('preferences.md')}})
                    document['profile_id'] = result['profile']['id']
                elif item['category'] == '作品':
                    document['work_id'] = self._work(c, item, destination, profile)
                else:
                    # Nonsecret configuration copied through the same validated
                    # schema; keys/cookies are intentionally not transferred.
                    fields = {}
                    for line in (self.source / item['relative']).read_text(encoding='utf-8-sig').splitlines():
                        if '=' in line and not line.lstrip().startswith('#'):
                            key, val = line.split('=', 1)
                            fields[key.strip()] = val.strip().strip('\"\'')
                    configured = []
                    for channel, spec in self.media.catalog.items():
                        provider = next((p for p in spec['providers'] if any(k.get('required', True) and k.get('secret', True) and fields.get(k['env']) for k in p['keys'])), None)
                        if not provider:
                            continue
                        config_id = 'import-' + channel + '-' + sid[:12]
                        values = {k['env']: fields[k['env']] for k in provider['keys'] + spec.get('settings', []) if k.get('secret') is False and fields.get(k['env'])}
                        self.media._save_config(c, {'channel': channel, 'provider': provider['id'], 'config_id': config_id, 'base_revision': 0, 'values': values})
                        configured.append(config_id)
                    document['config_ids'] = configured
                c.execute('INSERT INTO media_imports VALUES(?,?)', (sid, pack(document)))
                imported.append({k: document[k] for k in ('id', 'category', 'name', 'work_id', 'profile_id', 'config_ids') if k in document})
            result = {'id': operation, 'status': 'completed', 'result': {'imported': imported, 'skipped': skipped, 'source_preserved': True}}
            c.execute('INSERT INTO media_operations VALUES(?,?,?)', (operation, signature, pack(result)))
            return result

    def _work(self, c, item, destination, profile):
        import mimetypes
        sid, now = item['id'], stamp()
        wid, jid = 'import-work-' + sid[:24], 'import-version-' + sid[:24]
        metadata = {}
        for name in ('meta.json', 'project.json', '作品.json'):
            p = destination / name
            if p.is_file() and p.stat().st_size < 1000000:
                try:
                    parsed = json.loads(p.read_text(encoding='utf-8-sig'))
                    if isinstance(parsed, dict):
                        metadata = parsed
                        break
                except ValueError:
                    pass
        files = []
        for source in sorted(destination.rglob('*')):
            if source.is_file() and not source.is_symlink():
                files.append((source, mimetypes.guess_type(source.name)[0] or 'application/octet-stream'))
        kind = 'video' if any(m.startswith('video/') for _, m in files) else 'audio' if any(m.startswith('audio/') for _, m in files) else 'image' if any(m.startswith('image/') for _, m in files) else 'transcript'
        title = str(metadata.get('title') or item['name'])[:500]
        c.execute('INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)', (wid, None, title, '从 Easel 复制的历史作品，原始元数据与文件完整保留。', now, now))
        c.execute('INSERT INTO toolbox_work_options VALUES(?,?,?)', (wid, kind, 'auto'))
        c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,scope,signature,status,created_at,finished_at) VALUES(?,?,?,?,?,?,?,?,?)', (jid, wid, 'create', '选择性复制历史作品', '[]', sid, 'completed', now, now))
        artifacts = []
        archive = self.root / 'data/artifacts' / jid
        archive.mkdir(parents=True, exist_ok=True)
        for index, (file, mime) in enumerate(files):
            raw = file.read_bytes()
            aid = 'import-file-' + digest([sid, str(file.relative_to(destination)), hashlib.sha256(raw).hexdigest()])[:24]
            target = archive / (str(index) + '-' + file.name)
            if target.exists() and target.read_bytes() != raw:
                raise IntegrationConflict('不可变迁入文件冲突')
            if not target.exists():
                shutil.copyfile(file, target)
            c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)', (aid, jid, file.name, str(target), mime))
            role='final' if mime.startswith(('image/','audio/','video/')) or file.suffix.lower() in ('.md','.txt','.html') and file.name not in ('identity.md','memory.md','style.md','preferences.md') else 'source'
            meta = {'id': aid, 'name': file.name, 'mime': mime, 'sha256': hashlib.sha256(raw).hexdigest(), 'size': len(raw), 'role': role, 'source_relative': str(file.relative_to(destination)).replace('\\', '/')}
            c.execute('INSERT INTO media_artifacts VALUES(?,?)', (aid, pack(meta)))
            artifacts.append(meta)
        self.box.creator.bind_work(c, wid,{'profile_id':profile['id'],'profile_revision':profile['revision']})
        job = {'id': jid, 'work_id': wid, 'format': kind, 'stage': 'import', 'status': 'completed', 'send_state': 'not_sent', 'title': title, 'prompt': '选择性复制历史作品',
               'creator': {'profile': profile, 'skills': [], 'provenance': '管理归属；原制作画像未核实'}, 'artifacts': artifacts, 'created_at': now, 'finished_at': now,
               'execution_mode': 'imported', 'source_metadata': {k:str(metadata[k])[:2000] for k in ('title','status','created_at','published_at','platform','url') if k in metadata and isinstance(metadata[k],(str,int,float,bool))}, 'source_id': sid, 'source_files': item['files'],
               'publication_verification': 'unverified_import', 'model_execution': False, 'instruction': '历史原件复制；不推定已采纳或已发布。'}
        self.media._put_job(c, job)
        return wid
