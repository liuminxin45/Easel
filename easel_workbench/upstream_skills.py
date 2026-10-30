"""Read Easel's unmodified builtin library; freeze selected native methods.

SKILL.md remains authoritative. Existing creator tables only retain immutable
execution versions, never a parallel list of installed capabilities.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import mimetypes
from pathlib import Path
import shutil

from .skill_catalog import parse_skill
from .runtime.creator_runtime import packed, digest
from .runtime.desk import stamp
from .paths import owned_output_path


class UpstreamSkills:
    def __init__(self, root, creator, source_root=None):
        self.root, self.creator = Path(root).resolve(), creator
        self.source=Path(source_root or root).resolve()
        self.store = creator.store

    def _read(self, path):
        path = Path(path)
        if self.source!=self.root and path.is_relative_to(self.root/'skills'):path=self.source/path.relative_to(self.root)
        if not path.resolve().is_relative_to(self.source/'skills'):
            raise ValueError('技能资源离开本项目')
        for parent in (path, *path.parents):
            if parent == self.source:break
            if parent.is_symlink() or getattr(parent, 'is_junction', lambda:False)():
                raise ValueError('技能资源不能经过目录链接')
        return path.read_bytes()

    def entries(self):
        result=[]
        for path in sorted((self.source/'skills/builtin').glob('*/SKILL.md')):
            raw=self._read(path);meta,body=parse_skill(raw.decode('utf-8-sig'))
            if ((meta.get('metadata') or {}).get('openclaw') or {}).get('workbench') is not None:continue
            # Easel discovers by directory; some upstream skills deliberately
            # keep a different frontmatter alias (e.g. skill-xhs-analyzer/redbook).
            result.append({'id':path.parent.name,'entry':path.relative_to(self.source).as_posix(),
                           'description':meta.get('description',''),'layer':meta.get('layer','general'),
                           'prompt':raw.decode('utf-8'),'body':body,'meta':meta})
        return result

    def _common(self, entries):
        files={}
        directories=[(self.source/item['entry']).parent for item in entries]+[self.source/'skills/shared']
        for directory in directories:
            for path in sorted(directory.rglob('*')):
                if path.is_file() and not any(part in ('__pycache__','node_modules','.git','workbench') for part in path.relative_to(self.source/'skills').parts) and path.suffix not in ('.pyc','.pyo') and not path.name.startswith('.env'):
                    files[path.relative_to(self.source).as_posix()]=self._read(path)
        return files

    def _files(self, entry, common=None):
        # Preserve relative cross-skill links and script imports without sending
        # all method bodies into the model. Dependencies are frozen local files.
        files=common if common is not None else self._common(self.entries())
        if sum(map(len,files.values()))>40*1024*1024:raise ValueError('本技能资源包超过40MB，请拆分依赖')
        return files

    def release(self, sid, version=None, *, entries=None, common=None, rows=None, fingerprints=None, revision=None):
        item=next((item for item in (entries if entries is not None else self.entries()) if item['id']==sid),None)
        if not item:raise ValueError('找不到 Easel 原生技能')
        files=self._files(item,common)
        fingerprints=fingerprints if fingerprints is not None else {name:digest(raw) for name,raw in sorted(files.items())}
        revision=revision or digest(packed(fingerprints))
        if rows is None:
            with self.store.connect() as c:
                rows=[json.loads(row[0]) for row in c.execute('SELECT document FROM creator_skill_versions WHERE skill_id=? ORDER BY version DESC',(sid,))]
        for row in rows:
            if row.get('origin')!='easel':raise ValueError('技能身份已被其它能力占用')
            if version is not None and row['version']==version:return row
            if version is None and row.get('source_revision')==revision:return row
        next_version=max((row['version'] for row in rows),default=0)+1
        if version is not None and version!=next_version:raise ValueError('所选 Easel 技能版本已变化，请重新选择')
        resources=[{'path':name,'sha256':fingerprints[name],'size':len(raw),'available':True,'required':True,
                    'kind':'native_source','scope':'on-demand'} for name,raw in sorted(files.items()) if name!=item['entry']]
        release={**{k:item[k] for k in ('id','entry','description','layer','prompt')},'origin':'easel','name':sid,
                 'version':next_version,'source_revision':revision,'tasks':['native'],'executor':'agent',
                 'input_contract':{'required':['user_message']},'output_contract':{'required':['actual_result']},
                 'status':'published','resources':resources,'execution_role':'active','created_at':stamp()}
        release['sha256']=self.creator._release_hash(release)
        return release

    def items(self):
        # Listing is read-only. Import history is created only with an accepted
        # explicit invocation, in the same transaction as its native turn.
        result=[]
        environment=self.environment() if hasattr(self,'environment') else {}
        registry_path=self.source/'skills/shared/scripts/model_registry.py'
        registry=None
        if registry_path.is_file():
            spec=importlib.util.spec_from_file_location('easel_native_model_registry',registry_path)
            registry=importlib.util.module_from_spec(spec);spec.loader.exec_module(registry)
        channels={'ai-image-gen':'image','ecom-details-image':'image','ai-video-gen':'video','ai-music':'music','voice-clone':'voice','short-drama':'image'}
        entries=self.entries();common=self._common(entries)
        fingerprints={name:digest(raw) for name,raw in sorted(common.items())};revision=digest(packed(fingerprints))
        with self.store.connect() as c:
            history={}
            for row in c.execute('SELECT skill_id,document FROM creator_skill_versions ORDER BY version DESC'):
                history.setdefault(row[0],[]).append(json.loads(row[1]))
        for item in entries:
            release=self.release(item['id'],entries=entries,common=common,rows=history.get(item['id'],[]),fingerprints=fingerprints,revision=revision)
            channel=channels.get(item['id']);configured=bool(registry and registry.configured_providers(channel,environment)) if channel else True
            result.append({**{k:item[k] for k in ('id','description','layer','entry')},'skill_id':item['id'],'name':item['id'],
                'origin':'easel','version':release['version'],'sha256':release['sha256'],'source_revision':release['source_revision'],
                'available':True,'needsApi':bool(channel),'apiConfigured':configured,'validation_state':'not_tested',
                'reason':'Easel 原生技能；依赖与外部服务在执行前核对' if configured else '需要先在设置中配置对应媒体通道','execution_kind':'agent',
                'launch_actions':[{'id':'native','task':'native','label':'使用技能','requires_plan':False}]})
        return result

    def detail(self, sid):
        release=self.release(sid);meta,body=parse_skill(release['prompt'].lstrip('\ufeff'))
        return {**release,'name':sid,'body':body,'content':body,'meta':meta,'raw':release['prompt']}

    def snapshot(self, profile, sid, version=None):
        release=self.release(sid,version)
        lines=['按本轮冻结的 Easel 原生技能执行用户任务；使用 frozen_skill_files 中的同版文件和脚本。',
               '画像：'+profile['name'], '\n'.join(k+'：'+str(profile.get(k,'')) for k in ('identity','audience','voice','boundaries')),
               '## 显式技能：'+sid+' v'+str(release['version'])+'\n'+release['prompt']]
        result={'schema_version':1,'task':'native','profile':copy.deepcopy(profile),'skills':[release],
                'account_ids':list(profile.get('account_ids',[])),'prompt_text':'\n\n'.join(lines),'trial':False,'active_skill_ids':[sid]}
        result['snapshot_sha256']=digest(packed(result))
        return result

    def accept(self,c,snapshot):
        for release in snapshot['skills']:
            sid,version=release['id'],release['version']
            old=c.execute('SELECT document FROM creator_skill_versions WHERE skill_id=? AND version=?',(sid,version)).fetchone()
            if old:
                if json.loads(old[0])['sha256']!=release['sha256']:raise ValueError('同一技能版本不能改变已冻结内容')
                continue
            item=next(item for item in self.entries() if item['id']==sid);files=self._files(item)
            expected={r['path']:r['sha256'] for r in release['resources']};expected[release['entry']]=digest(release['prompt'].encode('utf-8'))
            if {name:digest(raw) for name,raw in files.items()}!=expected:raise ValueError('Easel 技能资源已有变化，未受理执行')
            for raw in files.values():c.execute('INSERT OR IGNORE INTO creator_skill_blobs VALUES(?,?)',(digest(raw),raw))
            metadata={k:copy.deepcopy(v) for k,v in release.items() if k not in ('prompt','resources','version','sha256')}
            c.execute('INSERT OR IGNORE INTO creator_skills VALUES(?,?)',(sid,packed(metadata)))
            c.execute('INSERT INTO creator_skill_versions VALUES(?,?,?)',(sid,version,packed(release)))
            c.execute('INSERT INTO creator_skill_pointers(skill_id,revision,version) VALUES(?,?,?) ON CONFLICT(skill_id) DO UPDATE SET version=max(version,excluded.version),revision=revision+1',(sid,1,version))

    def receive(self, turn):
        """Register only this native turn's owned products, not neighboring files."""
        if turn['status']!='completed':return
        folder=owned_output_path(self.root,Path('outputs')/turn['session_id']/turn['id']/'products')
        if not folder.exists():return
        for path in sorted(folder.rglob('*')):
            if not path.is_file() or path.name.startswith('.') or path.name.lower() in ('credentials.json','cookies.json'):continue
            checked=owned_output_path(self.root,path.relative_to(self.root))
            def fingerprint(file):
                with file.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
            content_hash=fingerprint(checked)
            aid=digest((turn['id']+'\0'+str(checked)+'\0'+content_hash).encode())
            target=self.root/'data/artifacts'/aid/path.name;target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists() and fingerprint(target)!=content_hash:raise ValueError('原生产物字节不符')
            if not target.exists():shutil.copy2(checked,target)
            if fingerprint(target)!=content_hash or fingerprint(checked)!=content_hash:raise ValueError('接收时原生产物字节变化')
            with self.store.connect() as c:c.execute('INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?,?)',(aid,turn['id'],path.name,str(target),mimetypes.guess_type(path.name)[0] or 'application/octet-stream'))

    def library(self):
        with self.store.connect() as c:
            turns=c.execute("SELECT id,document FROM easel_chat_turns WHERE json_extract(document,'$.snapshot.task')='native' ORDER BY rowid DESC LIMIT 100").fetchall()
            items=[]
            for tid,raw in turns:
                turn=json.loads(raw)
                if turn.get('snapshot',{}).get('task')!='native':continue
                files=[{'id':row['id'],'name':row['name'],'mime':row['mime']} for row in c.execute('SELECT id,name,mime FROM artifacts WHERE task_id=?',(tid,))]
                if files:items.append({'turn_id':tid,'session_id':turn['session_id'],'title':turn['message'][:100],'files':files})
        return {'items':items}
