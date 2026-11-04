"""Storage policy for native library deletion; historical bytes remain owned.

The official deletion use case owns the public action. This repository only
records which exact entries left the active library and retains their history.
"""
from __future__ import annotations
import hashlib
import json
import shutil
from fastapi import HTTPException


def packed(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))


class LibraryDeletion:
    def __init__(self,api):
        self.api=api
        with api.store.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS native_library_deletions(path TEXT PRIMARY KEY,document TEXT NOT NULL)')

    def fingerprint(self,node):
        value={key:node.get(key) for key in ('path','type','name','mtime','size')}
        path=node['path']
        if node['type']=='file' and not path.startswith(('__workbench__/','__partial__/')):
            try:
                stat=self.api.outputs._safe_output_path(path).stat()
                value['file_identity']=[stat.st_ino,stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns]
            except (OSError,HTTPException):value['file_identity']=None
        return hashlib.sha256(packed(value).encode()).hexdigest()

    def resolve(self,path):
        # Only an entry already exposed by the protected library may be deleted;
        # raw paths, system directories and missing aliases cannot become writes.
        parts=path.replace('\\','/').split('/')
        if not parts or any(part in ('','.','..') for part in parts) or parts[0].startswith(('_','.')) and parts[0] not in ('__workbench__','__partial__'):
            raise HTTPException(403,'系统数据受保护，不可从内容库删除')
        chain=self.api.library.resolve(path)['nodes']
        snapshot=self.api.library.subtree(chain[-1]['path'],with_revision=True)
        nodes=snapshot['nodes']
        virtual=path.startswith(('__workbench__/','__partial__/')) or any(
            node.get('meta',{}).get('work_id') or node.get('meta',{}).get('session_id') for node in chain)
        protected=False if virtual else self.api.outputs._is_protected(self.api.outputs._safe_output_target(path))
        return {'kind':chain[-1]['type'],'protected':protected,'value':nodes,'chain':chain,
                'selected_path':chain[-1]['path'],'index_revision':snapshot['revision'],
                'operation_id':self.api._operation}

    def remove(self,target):
        from easel_workbench.runtime.desk import stamp
        nodes=target['value'];path=target['selected_path'];operation=target['operation_id']
        versions={node.get('meta',{}).get(key) for node in target['chain']+nodes for key in ('version_id','turn_id')}-{None,''}
        files={node['path'].split('/')[1] for node in nodes if node['path'].startswith('__workbench__/')}
        # Snapshot physical originals before recording removal. Registered
        # immutable artifact IDs already have their historical storage owner.
        # File I/O never holds the business database's writer lock.
        snapshots=[]
        archive=(self.api.root/'data/library-deletions'/operation).resolve()
        if not archive.is_relative_to(self.api.root/'data/library-deletions'):
            raise HTTPException(403,'历史归档目录不属于本项目')
        for node in nodes:
            item={'node':node,'fingerprint':self.fingerprint(node),'archive':None}
            if node['type']=='file' and not node['path'].startswith(('__workbench__/','__partial__/')):
                source=self.api.outputs._safe_output_path(node['path'])
                saved=archive/hashlib.sha256(node['path'].encode()).hexdigest()/source.name
                if not saved.resolve().is_relative_to(archive):raise HTTPException(403,'历史归档路径不属于本次操作')
                saved.parent.mkdir(parents=True,exist_ok=True)
                if not saved.exists():shutil.copy2(source,saved)
                with source.open('rb') as stream:before=hashlib.file_digest(stream,'sha256').hexdigest()
                with saved.open('rb') as stream:actual=hashlib.file_digest(stream,'sha256').hexdigest()
                if before!=actual or self.fingerprint(node)!=item['fingerprint']:
                    raise HTTPException(409,'内容在删除前已有变化，原文件仍保留，请重新核对')
                item.update(archive=saved.relative_to(self.api.root).as_posix(),sha256=actual)
            snapshots.append(item)
        if archive.exists():
            (archive/'manifest.json').write_text(packed({'operation_id':operation,'selected_path':path,
                'files':[{k:v for k,v in item.items() if k!='node'}|{'path':item['node']['path']} for item in snapshots]}),encoding='utf-8')
        with self.api.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            for fid in files:
                row=c.execute('SELECT task_id FROM artifacts WHERE id=?',(fid,)).fetchone()
                if row and row[0]:versions.add(row[0])
            for version in versions:
                if 'easel_chat_turns' in tables:
                    row=c.execute('SELECT document FROM easel_chat_turns WHERE id=?',(version,)).fetchone()
                    if row and json.loads(row[0])['status'] not in ('completed','stopped','failed'):
                        raise HTTPException(409,'这份内容的原任务仍在执行或结果待核对，请核对后删除')
                row=c.execute('SELECT status FROM toolbox_jobs WHERE id=?',(version,)).fetchone()
                if row and row[0] in ('queued','dispatching','running','uncertain','parked','needs_desktop'):
                    raise HTTPException(409,'这份内容的原任务仍在执行或结果待核对，请核对后删除')
            at=stamp()
            for item in snapshots:
                node=item['node']
                if self.fingerprint(node)!=item['fingerprint']:raise HTTPException(409,'内容已有变化，请重新核对后删除')
                document={'path':node['path'],'type':node['type'],'fingerprint':item['fingerprint'],'archive':item['archive'],
                          'operation_id':operation,'selected_path':path,'at':at,'retained_history':True,
                          'index_revision':target['index_revision']}
                c.execute('INSERT INTO native_library_deletions VALUES(?,?) ON CONFLICT(path) DO UPDATE SET document=excluded.document',
                          (node['path'],packed(document)))
            self.api.commit_local_result(c,{'ok':True,'deleted':path,'kind':target['kind']},operation=operation)
        # A write may reconcile metadata; ordinary read requests still never
        # enumerate originals. Rebuild uses the same background-owned builder.
        try:
            self.api.library.invalidate()
            self.api.library.rebuild(lock_timeout=10)
        except Exception as error:
            # Removal and its exact receipt are already committed. A damaged
            # rebuildable projection must not turn them into an unknown write.
            from easel_workbench.runtime import server_logging
            server_logging.exception('library_deletion_projection_failed',error,
                operation_ref=server_logging.reference(operation))

    def pending_paths(self,nodes,revision):
        by_path={node['path']:node for node in nodes}
        if not by_path:return set()
        with self.api.store.connect() as c:
            rows=c.execute('SELECT path,document FROM native_library_deletions WHERE path IN ('+','.join('?' for _ in by_path)+')',tuple(by_path)).fetchall()
        return {row[0] for row in rows if (marker:=json.loads(row[1])).get('index_revision')==revision
                and marker['fingerprint']==self.fingerprint(by_path[row[0]])}

    def apply(self,roots):
        with self.api.store.connect() as c:
            removed={r[0]:json.loads(r[1]) for r in c.execute('SELECT path,document FROM native_library_deletions')}
        if not removed:return roots
        def visit(node):
            marker=removed.get(node['path'])
            matches=marker and marker['fingerprint']==self.fingerprint(node)
            if node['type']=='file':return None if matches else node
            previous=node.get('children',[])
            children=[kept for child in previous if (kept:=visit(child)) is not None]
            if not children and matches:return None
            if len(children)==len(previous) and all(a is b for a,b in zip(children,previous)):return node
            result={**node,'children':children,'fileCount':sum(child.get('fileCount',1) for child in children)}
            if 'meta' in result:
                result['meta']={key:value for key,value in result['meta'].items() if key not in ('cover','deliverablePaths')}
            return result
        return [kept for root in roots if (kept:=visit(root)) is not None]
