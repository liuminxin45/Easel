"""Materialize accepted skill/resource bytes in the exact task-local directory."""
from pathlib import Path
from easel_workbench.paths import owned_output_path
from easel_workbench.contracts.production import PlanConflict
from .records import packed, digest

class SkillBundles:
    def __init__(self, *, root, store, upstream):
        self.root=root
        self.store=store
        self.upstream=upstream

    def _bundle(self,snapshot,write=False,c=None):
        """Expose exact version bytes to tools inside this project, never globally."""
        if c is None:
            with self.store.connect() as conn:return self._bundle(snapshot,write,conn)
        folder=owned_output_path(self.root,Path('outputs/_sessions/skill-inputs')/snapshot['snapshot_sha256'])
        files={}
        for skill in snapshot['skills']:
            files[skill['entry']]=skill['prompt'].encode('utf-8')
        groups=[{'resources':snapshot.get('profile',{}).get('asset_refs',[])},*snapshot['skills']]
        for group in groups:
            for resource in group.get('resources',[]):
                if not resource.get('available'):continue
                row=c.execute('SELECT bytes FROM creator_skill_blobs WHERE sha256=?',(resource['sha256'],)).fetchone()
                if not row and snapshot['task']=='native':
                    raw=self.upstream._read(self.root/resource['path'])
                elif row:raw=bytes(row[0])
                else:raise PlanConflict('冻结技能资源缺失或字节不符')
                if digest(raw)!=resource['sha256']:raise PlanConflict('冻结技能资源缺失或字节不符')
                name=resource['path']
                if name in files and files[name]!=raw:raise PlanConflict('技能资源同路径存在不同版本，请先明确适用组合')
                files[name]=raw
        result=[]
        for name,raw in sorted(files.items()):
            if Path(name).is_absolute() or '..' in Path(name).parts or '\\' in name:raise ValueError('冻结技能路径无效')
            target=owned_output_path(self.root,folder.relative_to(self.root)/name)
            if not target.is_relative_to(folder.resolve()):raise ValueError('冻结技能路径无效')
            fingerprint=digest(raw)
            if write:
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists():
                    if digest(target.read_bytes())!=fingerprint:raise PlanConflict('本地冻结技能副本发生变化')
                else:
                    try:
                        with target.open('xb') as handle:handle.write(raw)
                    except FileExistsError:
                        if digest(target.read_bytes())!=fingerprint:raise PlanConflict('本地冻结技能副本发生变化')
            result.append({'original_path':name,'path':str(target),'sha256':fingerprint})
        if write and snapshot['task']=='native':
            manifest=owned_output_path(self.root,folder.relative_to(self.root)/'native-library.json');raw=packed(result).encode('utf-8')
            try:
                with manifest.open('xb') as handle:handle.write(raw)
            except FileExistsError:
                if manifest.read_bytes()!=raw:raise PlanConflict('本地冻结技能清单发生变化')
        return result
