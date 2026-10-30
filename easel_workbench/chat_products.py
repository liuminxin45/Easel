"""Read-only view of exact chat products, including files left by an interruption."""
from functools import lru_cache
import hashlib
import json
import mimetypes
from pathlib import Path

from .paths import owned_output_path


def fingerprint(path):
    with path.open('rb') as source:return hashlib.file_digest(source,'sha256').hexdigest()


@lru_cache(maxsize=256)
def observed_sha(path,size,modified):return fingerprint(Path(path))


class ChatProducts:
    def __init__(self,business):self.business=business;self.root=business.root

    def _partial(self,turn):
        folder=owned_output_path(self.root,Path('outputs')/turn['session_id']/turn['id']/'products')
        if not folder.is_dir():return []
        result=[]
        for path in sorted(folder.rglob('*')):
            relative=path.relative_to(folder)
            if any(part.startswith('.') for part in relative.parts) or path.name.lower() in ('credentials.json','cookies.json'):continue
            if not path.is_file():continue
            try:checked=owned_output_path(self.root,path.relative_to(self.root))
            except ValueError:continue
            mime=mimetypes.guess_type(path.name)[0] or 'application/octet-stream'
            if not (mime.startswith(('image/','audio/','video/','text/')) or mime in ('application/json','application/pdf','application/zip')):continue
            stat=checked.stat();sha=observed_sha(str(checked),stat.st_size,stat.st_mtime_ns)
            token=hashlib.sha256((relative.as_posix()+'\0'+sha).encode()).hexdigest()
            result.append({'id':token,'name':path.name,'mime':mime,'sha256':sha,'size':stat.st_size,
                           'url':'/api/chat/products/'+turn['id']+'/files/'+token,'partial':True,'_path':checked})
            if len(result)>=64:break
        return result

    def describe(self,turn_id):
        turn=self.business.chat.get_turn(turn_id,private=True)
        with self.business.store.connect() as c:
            files=[{'id':r['id'],'name':r['name'],'mime':r['mime'],'url':'/api/files/'+r['id']} for r in c.execute('SELECT id,name,mime FROM artifacts WHERE task_id=? ORDER BY rowid',(turn_id,))]
        incomplete=turn['status']!='completed';work=turn.get('work') or {};version=None;decision=None
        if work:
            value=self.business.box.work(work['work_id'])
            version=next((v for v in value['versions'] if v['id']==work['version_id']),None)
            incomplete=incomplete or not version or version['status']!='completed'
            if version:decision=(version.get('decisions') or [None])[-1]
        if incomplete or not files:
            names={file['name'] for file in files}
            files.extend({k:v for k,v in file.items() if k!='_path'} for file in self._partial(turn) if file['name'] not in names)
        blocks=[]
        if version:
            article=version.get('article') or {};copy=version.get('copy') or {}
            title=article.get('title') or copy.get('title');body=article.get('body') or copy.get('caption')
            if title:blocks.append({'label':'标题','text':title})
            if body:blocks.append({'label':'正文','text':body})
        if not blocks:
            for file in files:
                if file['name']!='标题与配文.txt':continue
                path=self.file(turn_id,file['id'])[1] if file.get('partial') else self.business.box.file(file['id'])[1]
                if path.stat().st_size>256*1024:continue
                raw=path.read_bytes().decode('utf-8-sig');title,separator,body=raw.partition('\n')
                blocks=[{'label':'标题','text':title.rstrip('\r')},{'label':'正文','text':body.lstrip('\r\n')}] if separator else [{'label':file['name'],'text':raw}]
                break
        return {'turn_id':turn_id,'session_id':turn['session_id'],'files':files,'text_blocks':blocks,'incomplete':incomplete,
                'can_adopt':bool(version and not incomplete),'decision':decision,
                'work_id':work.get('work_id'),'version_id':work.get('version_id')}

    def file(self,turn_id,token):
        turn=self.business.chat.get_turn(turn_id,private=True)
        file=next((file for file in self._partial(turn) if file['id']==token),None)
        if not file:raise ValueError('本回合文件不存在或内容已变化，请重新读取')
        path=file.pop('_path')
        if fingerprint(path)!=file['sha256']:raise ValueError('本回合文件内容已变化，请重新读取')
        return file,path
