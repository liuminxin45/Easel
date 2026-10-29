"""Toolbox works, version-bound decisions and durable fixed-thread jobs."""
import contextlib,hashlib,json,mimetypes,pathlib,re,uuid
from easel_workbench.runtime.desk import ROOT,THREAD,stamp

KINDS={'create','change','feedback','accept','reject'}
ACTIVE={'queued','dispatching','running','uncertain','needs_desktop','parked'}
def pack(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def ident(value):
    if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',value):raise ValueError('记录标识无效')
    return value
def text(value,limit,required=False):
    if not isinstance(value,str) or len(value)>limit or required and not value.strip():raise ValueError('内容为空或超过长度限制')
    return value

class Toolbox:
    def __init__(self,store,root=ROOT):
        self.store=store;self.root=pathlib.Path(root)
        with store.connect() as c:
            c.executescript('''
CREATE TABLE IF NOT EXISTS toolbox_works(id TEXT PRIMARY KEY,article_id TEXT,title TEXT NOT NULL,material TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_jobs(id TEXT PRIMARY KEY,work_id TEXT,kind TEXT NOT NULL,text TEXT NOT NULL,candidate_id TEXT,scope TEXT NOT NULL DEFAULT '[]',files TEXT NOT NULL DEFAULT '[]',signature TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,started_at TEXT,finished_at TEXT,turn_id TEXT,reply TEXT,error TEXT,dispatch_started INTEGER NOT NULL DEFAULT 0,queue_id TEXT,rollout_offset INTEGER);
CREATE INDEX IF NOT EXISTS toolbox_jobs_work ON toolbox_jobs(work_id,created_at);
CREATE TABLE IF NOT EXISTS toolbox_files(id TEXT PRIMARY KEY,name TEXT NOT NULL,path TEXT NOT NULL,mime TEXT NOT NULL,size INTEGER NOT NULL,sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_archive(file_id TEXT PRIMARY KEY,turn_id TEXT,created_at TEXT);
CREATE TABLE IF NOT EXISTS toolbox_work_options(work_id TEXT PRIMARY KEY,format TEXT NOT NULL,article_mode TEXT NOT NULL);
''')
            from easel_workbench.runtime.article_drafts import initialize
            initialize(c)
            from easel_workbench.runtime.direct_turns import initialize as initialize_direct_turns
            initialize_direct_turns(c)
            from easel_workbench.runtime.browser_cleanup import initialize as initialize_cleanup
            initialize_cleanup(c)
            from easel_workbench.runtime.work_review import initialize as initialize_review
            initialize_review(c)
            from easel_workbench.runtime.content_studio import initialize as initialize_studio
            initialize_studio(c)
            from easel_workbench.runtime.production_outcome import initialize as initialize_outcomes
            initialize_outcomes(c)
            from easel_workbench.runtime.production_retry import initialize as initialize_retries
            initialize_retries(c)
            from easel_workbench.runtime.learning_execution import initialize as initialize_learning_execution
            initialize_learning_execution(c)
            from easel_workbench.runtime.completion_service import initialize as initialize_completions
            initialize_completions(c)
            from easel_workbench.runtime.local_operations import initialize as initialize_local
            initialize_local(c)
            from easel_workbench.runtime.creator_runtime import initialize as initialize_creator
            initialize_creator(c)
            from easel_workbench.runtime.task_runtime import initialize as initialize_task_runtime
            initialize_task_runtime(c)
            if not c.execute("SELECT 1 FROM toolbox_meta WHERE key='legacy-import-v1'").fetchone():
                self._import_history(c)
                c.execute("INSERT INTO toolbox_meta VALUES('legacy-import-v1','done')")
            if not c.execute("SELECT 1 FROM toolbox_meta WHERE key='legacy-files-v1'").fetchone():
                try:
                    c.execute("INSERT OR IGNORE INTO toolbox_archive SELECT f.id,f.turn_id,f.created_at FROM wb_files f JOIN toolbox_files t ON t.id=f.id WHERE f.thread_id=? AND f.direction='output'",(THREAD,))
                except __import__('sqlite3').OperationalError:pass
                c.execute("INSERT INTO toolbox_meta VALUES('legacy-files-v1','done')")
        if self.root.resolve()==pathlib.Path(ROOT).resolve():
            from easel_workbench.runtime.learning_execution import attach
            attach(self)
    def archive(self,page=1,kind=''):
        page=max(1,min(10000,int(page)));where=" WHERE f.mime LIKE 'image/%'" if kind=='images' else ''
        with self.store.connect() as c:
            total=c.execute('SELECT count(*) FROM toolbox_archive a JOIN toolbox_files f ON a.file_id=f.id'+where).fetchone()[0]
            rows=[dict(r) for r in c.execute('SELECT f.id,f.name,f.mime,a.turn_id,a.created_at FROM toolbox_archive a JOIN toolbox_files f ON a.file_id=f.id'+where+' ORDER BY a.created_at DESC,f.id LIMIT 24 OFFSET ?',((page-1)*24,))]
        return {'items':rows,'page':page,'total':total,'has_more':page*24<total}
    def _import_history(self,c):
        # Historical rows and original files remain untouched for rollback.
        rows=[dict(r) for r in c.execute('SELECT * FROM tasks WHERE thread=? ORDER BY rowid',(THREAD,))]
        mapping={'select':'create','change':'change','creative_feedback':'feedback','followup':'feedback','accept':'accept','reject':'reject'}
        for row in rows:
            article=c.execute('SELECT * FROM articles WHERE id=?',(row['article_id'],)).fetchone()
            if not article:continue
            wid='legacy-'+article['id'];kind=mapping.get(row['kind'])
            if kind is None:continue
            c.execute('INSERT OR IGNORE INTO toolbox_works VALUES(?,?,?,?,?,?)',(wid,article['id'],article['title'],article['body']+'\n\n来源：'+article['url'],row['created_at'],row['created_at']))
            status=row['status'];dispatch=int(bool(row['turn_id'] or row['output_path']))
            # No accepted legacy operation is automatically dispatched again.
            if status in ('queued','running'):status='uncertain';dispatch=1
            c.execute('INSERT OR IGNORE INTO toolbox_jobs(id,work_id,kind,text,candidate_id,scope,files,signature,status,created_at,started_at,finished_at,turn_id,reply,error,dispatch_started,rollout_offset) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                      (row['id'],wid,kind,row['text'],row.get('candidate_task_id'),'[]','[]','legacy:'+row['id'],status,row['created_at'],row['started_at'],row['finished_at'],row['turn_id'],row['reply'],row['error'],dispatch,row['rollout_offset']))
            c.execute('UPDATE toolbox_works SET updated_at=? WHERE id=?',(row['created_at'],wid))
        # Preserve uploads from every old client as file records, never sessions.
        paths=[self.store.path,*sorted((self.root/'data/workbench/providers').glob('*/state.sqlite'))]
        import sqlite3,contextlib
        for database in paths:
            try:
                with contextlib.closing(sqlite3.connect(database)) as source:
                    source.row_factory=sqlite3.Row
                    for row in source.execute('SELECT id,name,path,mime,size,hash FROM wb_files'):
                        p=pathlib.Path(row['path']).resolve()
                        if p.is_relative_to((self.root/'data/workbench').resolve()) and p.is_file():
                            c.execute('INSERT OR IGNORE INTO toolbox_files VALUES(?,?,?,?,?,?)',tuple(row))
            except sqlite3.OperationalError:pass
    def _files(self,c,ids):
        if not isinstance(ids,list) or len(ids)>12 or len(set(ids))!=len(ids):raise ValueError('附件列表无效')
        for fid in ids:
            ident(fid)
            if not c.execute('SELECT 1 FROM toolbox_files WHERE id=?',(fid,)).fetchone():raise ValueError('附件不存在，请重新选择')
        return pack(ids)
    def create(self,value):
        jid=ident(value.get('id'));title=text(value.get('title',''),500);material=text(value.get('material',''),100000);guidance=text(value.get('guidance',''),10000)
        format=value.get('format','poster');mode=value.get('article_mode','auto')
        if format not in ('poster','article') or mode not in ('auto','product'):raise ValueError('制作类型无效')
        aid=value.get('article_id') or None;signature=pack(value);now=stamp();wid=jid
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(jid,)).fetchone()
            if old:
                if old['signature']!=signature:
                    try:
                        previous=json.loads(old['signature']);previous.setdefault('format','poster');previous.setdefault('article_mode','auto')
                        current={**value};current.setdefault('format','poster');current.setdefault('article_mode','auto')
                    except (ValueError,AttributeError):raise ValueError('同一操作 ID 不能用于不同内容')
                    if pack(previous)!=pack(current):raise ValueError('同一操作 ID 不能用于不同内容')
                return {'id':jid,'work_id':old['work_id'],'status':old['status']}
            if c.execute('SELECT 1 FROM toolbox_article_draft_ops WHERE id=?',(jid,)).fetchone():raise ValueError('操作 ID 已用于保存草稿')
            if aid:
                row=c.execute('SELECT * FROM articles WHERE id=?',(ident(aid),)).fetchone()
                if not row:raise ValueError('资讯不存在')
                title=title or row['title'];material=row['body']+'\n\n来源：'+row['url']
            files=self._files(c,value.get('files',[]))
            if not any(v.strip() for v in (title,material,guidance)) and not json.loads(files):raise ValueError('提供一句话、一个链接或一个素材文件即可开始')
            title=title.strip() or next((line.strip()[:120] for line in (material or guidance).splitlines() if line.strip()),'图片选题' if format=='poster' else '素材文章')
            c.execute('INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)',(wid,aid,title,material,now,now))
            c.execute('INSERT INTO toolbox_work_options VALUES(?,?,?)',(wid,format,mode))
            c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,files,signature,status,created_at) VALUES(?,?,?,?,?,?,?,?)',(jid,wid,'create',guidance,files,signature,'queued',now))
            from easel_workbench.runtime.local_operations import mark_execution,reserve_work
            mark_execution(c,jid,'agent');reserve_work(c,wid,title)
            c.execute('INSERT INTO toolbox_article_inputs VALUES(?,?,?)',(jid,0,pack({'title':title,'material':material,'guidance':guidance,'files':json.loads(files),'article_mode':mode})))
            from easel_workbench.runtime.work_review import freeze as freeze_review
            freeze_review(self,c,wid,jid,creation=value.get('creative'))
            if aid:
                c.execute('UPDATE articles SET selected=1 WHERE id=?',(aid,))
                from easel_workbench.runtime import news_feedback as news_feedback
                news_feedback.enqueue(c,aid,guidance,task_id=jid,created_at=now)
        return {'id':jid,'work_id':wid,'status':'queued'}
    def action(self,wid,value,*,origin='web'):
        ident(wid);jid=ident(value.get('id'));kind=value.get('kind');candidate=ident(value.get('candidate_id'));note=text(value.get('text',''),10000)
        if kind not in KINDS-{'create'}:raise ValueError('不支持的制作操作')
        scope=value.get('scope',[])
        if not isinstance(scope,list) or len(scope)!=len(set(scope)) or kind=='accept' and not scope:raise ValueError('请选择本次采纳的范围')
        if kind!='accept' and 'completion' in value:raise ValueError('只有明确采纳可以设置完成方案')
        completion=None
        if kind=='accept':
            from easel_workbench.runtime.completion_service import service as completion_service
            completion=completion_service(self)
        # A record is always a local transaction. Pausing archive/sync workers
        # must never turn a rejection or feedback note into an AI request.
        local=kind in ('accept','reject','feedback')
        signature=pack(value);now=stamp()
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(jid,)).fetchone()
            if old:
                if old['work_id']!=wid or old['signature']!=signature:raise ValueError('同一操作 ID 不能用于不同内容')
                from easel_workbench.runtime.local_operations import execution_mode
                return {'id':jid,'work_id':wid,'status':old['status'],'execution_mode':execution_mode(c,jid)}
            row=c.execute("SELECT * FROM toolbox_jobs WHERE id=? AND work_id=? AND kind IN ('create','change')",(candidate,wid)).fetchone()
            from easel_workbench.runtime.revision_scope import can_continue_partial
            if row and row['status']!='completed' and not (kind=='change' and can_continue_partial(c,row)):row=None
            if c.execute('SELECT 1 FROM toolbox_article_draft_ops WHERE id=?',(jid,)).fetchone():raise ValueError('操作 ID 已用于保存草稿')
            if not row:raise ValueError('所选作品版本尚未完成或不属于此作品')
            if kind=='accept':
                from easel_workbench.runtime.production_outcome import assess
                outcome=assess(self,c,dict(row))
                if outcome['status']!='completed':raise ValueError('本版没有可评审成品，请先补充素材并完成制作')
                if any(s not in outcome['available_scopes'] for s in scope):raise ValueError('所选范围尚未交付，请只采纳实际成品')
                from easel_workbench.runtime.learning_execution import require_adoption
                require_adoption(self,c,candidate,value,jid)
            if kind=='change' and c.execute("SELECT 1 FROM toolbox_jobs WHERE work_id=? AND status='parked'",(wid,)).fetchone():raise ValueError('本作品有已暂缓的原任务，请先在 Codex 核对原结果，不能重复制作')
            from easel_workbench.runtime.work_review import notes as review_notes,freeze as freeze_review
            from easel_workbench.runtime.content_studio import options as creation_options
            creative=creation_options(value.get('creative'))
            if kind in ('change','feedback') and not note.strip() and not review_notes(c,wid,candidate) and not (kind=='change' and (creative['enabled'] or creative['target']=='images')):raise ValueError('请填写修改意见、添加批注或调整本次生成设置')
            if kind=='change' and c.execute("SELECT 1 FROM toolbox_jobs WHERE work_id=? AND kind='discuss' AND status IN ('queued','dispatching','running','uncertain','needs_desktop')",(wid,)).fetchone():raise ValueError('请先完成或核对本作品讨论，再制作修改版')
            options=self.options(wid,c)
            allowed=('article','images') if options['format']=='article' else ('images','copy')
            if any(s not in allowed for s in scope):raise ValueError('采纳范围与作品类型不符')
            human=c.execute('SELECT 1 FROM toolbox_text_versions WHERE job_id=?',(candidate,)).fetchone()
            if kind=='accept' and human and 'images' in scope and not c.execute("SELECT 1 FROM artifacts WHERE task_id=? AND mime LIKE 'image/%'",(candidate,)).fetchone():raise ValueError('本版尚无配图，请先生成配图或只采纳文案')
            if kind=='accept' and options['format']=='article':
                from easel_workbench.runtime.article_drafts import job_work
                options=job_work(options,candidate,c)
                from easel_workbench.runtime.article_delivery import from_artifacts
                artifacts=[dict(r) for r in c.execute('SELECT * FROM artifacts WHERE task_id=?',(candidate,))]
                if not from_artifacts(artifacts,self.root/'data/artifacts',options['article_mode'])['ready']:raise ValueError('文章正文或实测材料未齐，请先补齐后采纳')
            files=self._files(c,value.get('files',[]))
            if completion:
                completion.freeze(c,{'id':jid,'work_id':wid,'kind':kind,'candidate_id':candidate,'scope':pack(scope),'text':note,'files':files,'signature':signature,'status':'queued','created_at':now},value.get('completion'))
            status='completed' if local else 'queued'
            c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,candidate_id,scope,files,signature,status,created_at,finished_at,reply) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(jid,wid,kind,note,candidate,pack(scope),files,signature,status,now,now if local else None,'系统已记录。' if local else None))
            from easel_workbench.runtime.local_operations import queue_action,mark_execution
            job=dict(c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(jid,)).fetchone())
            if local:queue_action(c,{**job,'_origin':origin})
            else:mark_execution(c,jid,'agent',origin)
            if kind=='change':
                from easel_workbench.runtime.article_drafts import job_work
                from easel_workbench.runtime.work_discussions import freeze
                source={**dict(c.execute('SELECT * FROM toolbox_works WHERE id=?',(wid,)).fetchone()),**self.options(wid,c)}
                source=job_work(source,candidate,c)
                document={k:source.get(k,'') for k in ('title','material','guidance','article_mode')}
                document.update(freeze(c,wid,candidate));document['files']=json.loads(files)
                c.execute('INSERT INTO toolbox_article_inputs VALUES(?,?,?)',(jid,source.get('draft_revision',0),pack(document)))
            if kind in ('change','feedback'):freeze_review(self,c,wid,jid,candidate,value.get('review_revision'),creation=value.get('creative'))
            elif kind in ('accept','reject') and human:freeze_review(self,c,wid,jid,candidate)
            if kind in ('accept','reject') and not local:
                from easel_workbench.runtime.browser_cleanup import require as require_cleanup
                require_cleanup(c,jid)
            c.execute('UPDATE toolbox_works SET updated_at=? WHERE id=?',(now,wid))
            if getattr(self,'learning',None):self.learning.index_database(c)
        if completion:completion.process(jid)
        return {'id':jid,'work_id':wid,'status':status,'execution_mode':'local' if local else 'agent'}
    def job(self,jid):
        with self.store.connect() as c:
            row=c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(ident(jid),)).fetchone()
            if not row:raise ValueError('任务不存在')
            from easel_workbench.runtime.production_retry import recovery
            from easel_workbench.runtime.production_outcome import read as read_outcome
            from easel_workbench.runtime.local_operations import execution_mode
            mode=execution_mode(c,jid)
            from easel_workbench.runtime.task_runtime import read_run,thread_id_for
            creator_context=bool(read_run(c,jid))
            try:thread_id=thread_id_for(c,jid)
            except ValueError:thread_id=None
            return {**{k:row[k] for k in ('id','work_id','kind','status','turn_id','created_at','error')},'execution_mode':mode,'recovery':recovery(row,c,outcome=read_outcome(c,jid)) if mode=='agent' else None,
                    'creator_context':creator_context,'thread_link':'codex://threads/'+thread_id if thread_id else None}
    def retry(self,jid,operation_id=None,expected_retry_revision=None):
        from easel_workbench.runtime.production_retry import manual_retry
        return manual_retry(self,jid,operation_id,expected_retry_revision)
    def options(self,wid,c):
        row=c.execute('SELECT format,article_mode FROM toolbox_work_options WHERE work_id=?',(wid,)).fetchone()
        return dict(row) if row else {'format':'poster','article_mode':'auto'}
    def news_production(self,ids):
        # Only submitted poster jobs count; opening a draft and article work do not.
        wanted=set(ids);result={}
        with self.store.connect() as c:
            rows=c.execute("SELECT w.article_id,w.id,j.id AS job_id,j.status,j.kind,j.created_at FROM toolbox_works w JOIN toolbox_jobs j ON j.work_id=w.id LEFT JOIN toolbox_work_options o ON o.work_id=w.id WHERE w.article_id IS NOT NULL AND coalesce(o.format,'poster')='poster' AND j.kind IN ('create','change') ORDER BY j.created_at,j.rowid")
            for row in rows:
                if row['article_id'] in wanted:result[row['article_id']]={'state':'failed' if row['status'] in ('error','blocked') else 'submitted','status':row['status'],'work_id':row['id'],'job_id':row['job_id']}
        return result
    def works(self,format=''):
        if format not in ('','poster','article','audio','video','music','image','transcript'):raise ValueError('制作类型无效')
        with self.store.connect() as c:
            c.execute('BEGIN')
            rows=list(c.execute("SELECT w.id FROM toolbox_works w LEFT JOIN toolbox_work_options o ON o.work_id=w.id WHERE ?='' OR coalesce(o.format,'poster')=? ORDER BY w.updated_at DESC,w.id DESC",(format,format)))
            result=[self.work(row['id'],_summary=True,_connection=c) for row in rows]
        return {'items':result}
    def work(self,wid,*,_summary=False,_connection=None):
        with self.store.connect() if _connection is None else contextlib.nullcontext(_connection) as media_connection:
            # Only the media registry owns these new stages; historical jobs keep
            # their original outcome/recovery contracts.
            if media_connection.execute("SELECT 1 FROM sqlite_master WHERE name='media_jobs'").fetchone() and media_connection.execute("SELECT 1 FROM media_jobs WHERE work_id=? LIMIT 1", (wid,)).fetchone():
                from easel_workbench.runtime.easel_integration import service as easel_service
                media_work=easel_service(self).work(wid,media_connection,_summary)
                if media_work is not None:return media_work
        from easel_workbench.runtime.publish_content import from_artifacts
        from easel_workbench.runtime.browser_cleanup import public_reply
        with self.store.connect() if _connection is None else contextlib.nullcontext(_connection) as c:
            row=c.execute('SELECT * FROM toolbox_works WHERE id=?',(ident(wid),)).fetchone()
            if not row:raise ValueError('作品不存在')
            work={**dict(row),**self.options(wid,c)};jobs=[dict(r) for r in c.execute('SELECT * FROM toolbox_jobs WHERE work_id=? ORDER BY rowid',(wid,))]
            from easel_workbench.runtime.creator_runtime import read_owner
            binding=read_owner(c,wid)
            owner=c.execute("SELECT json_extract(document,'$.snapshot.profile.id') AS id,json_extract(document,'$.snapshot.profile.name') AS name,json_extract(document,'$.snapshot.profile.revision') AS revision FROM creator_task_runs WHERE work_id=? ORDER BY rowid DESC LIMIT 1",(wid,)).fetchone()
            work['creator']=dict(owner) if owner else ({'id':binding['profile_id'],'name':binding['profile']['name'],'revision':binding['profile_revision']} if binding else {'id':'oil-pig','name':'油猪大侠','revision':None})
            versions=[]
            for job in jobs:
                if job['kind'] not in ('create','change'):continue
                if _summary:
                    versions.append({'id':job['id'],'status':job['status'],'decisions':[{'kind':j['kind']} for j in jobs if j['candidate_id']==job['id'] and j['kind'] in ('accept','reject')]})
                    continue
                artifacts=[dict(r) for r in c.execute('SELECT * FROM artifacts WHERE task_id=? ORDER BY rowid',(job['id'],))]
                versions.append({'id':job['id'],'label':'v'+str(len(versions)+1).zfill(2),'status':job['status'],'created_at':job['created_at'],'reply':job['reply'] or '',
                    'artifacts':[{k:a[k] for k in ('id','name','mime')} for a in artifacts],'copy':from_artifacts(artifacts,self.root/'data/artifacts'),
                    'decisions':[{'kind':j['kind'],'scope':json.loads(j['scope']),'status':j['status'],'text':j['text']} for j in jobs if j['candidate_id']==job['id'] and j['kind'] in ('accept','reject')]})
            from easel_workbench.runtime.article_drafts import read as read_draft, job_work
            from easel_workbench.runtime.work_discussions import freeze,production_token
            if _summary:
                draft=c.execute('SELECT revision,submitted_revision FROM toolbox_article_drafts WHERE work_id=?',(wid,)).fetchone()
                work['draft']=dict(draft) if draft else {'revision':0,'submitted_revision':0}
            else:
                work['draft']=read_draft(self,wid,c)
                work['draft']['files']=[dict(f) for fid in work['draft']['files'] for f in c.execute('SELECT id,name,mime,size FROM toolbox_files WHERE id=?',(fid,))]
            completed=[v for v in versions if v['status']=='completed']
            # List cards need no transcript token when no saved draft can be submitted.
            token=freeze(c,wid,completed[-1]['id'] if completed else None,bounded=False)['discussion_token'] if not _summary or work['draft']['revision']>0 else None
            work['draft'].update(discussion_token=token,can_finalize=work['draft']['revision']>0 and (work['draft']['revision']!=work['draft']['submitted_revision'] or token!=production_token(c,wid)))
            if work['format']=='article':
                from easel_workbench.runtime.article_delivery import from_artifacts as article_from_artifacts
                # Keep live evidence validation for the latest completed article;
                # old versions and full bodies belong to the detail view.
                for version in completed[-1:] if _summary else versions:
                    artifacts=[dict(r) for r in c.execute('SELECT * FROM artifacts WHERE task_id=?',(version['id'],))]
                    version['article']=article_from_artifacts(artifacts,self.root/'data/artifacts',job_work(work,version['id'],c)['article_mode']) if version['status']=='completed' else None
            from easel_workbench.runtime.production_outcome import read as read_outcome,assess as assess_outcome,issue as production_issue
            from easel_workbench.runtime.production_retry import recovery as job_recovery
            by_id={j['id']:j for j in jobs}
            for version in reversed(completed) if _summary else versions:
                job=by_id[version['id']];outcome=read_outcome(c,job['id'])
                if version['status']=='completed':
                    if work['format']=='article' and version.get('article') is None:
                        artifacts=[dict(r) for r in c.execute('SELECT * FROM artifacts WHERE task_id=?',(version['id'],))]
                        version['article']=article_from_artifacts(artifacts,self.root/'data/artifacts',job_work(work,version['id'],c)['article_mode'])
                    outcome=assess_outcome(self,c,job,article=version.get('article'),summary=_summary)
                    # Preserve a recorded terminal blockage even with partial files.
                    recorded=read_outcome(c,job['id'])
                    if recorded and recorded['status'] in ('blocked','error'):outcome=recorded
                    version['status']=outcome['status']
                version['recovery']=job_recovery(job,c,outcome=outcome)
                from easel_workbench.runtime.learning_execution import public_learning
                version['learning']=public_learning(self,c,version['id'])
                version['production_issue']=production_issue(job,outcome,recovery=version['recovery'])
                version['available_scopes']=outcome.get('available_scopes',[]) if outcome else []
                if _summary and version['status']=='completed':break
            pending=[{'id':j['id'],'kind':j['kind'],'status':j['status'],'error':j['error'],'recovery':job_recovery(j,c)} for j in jobs if j['status'] in ACTIVE]
            complete=[v for v in versions if v['status']=='completed'];latest=complete[-1] if complete else None
            if latest:
                from easel_workbench.runtime.production_title import from_artifacts as title_from_artifacts
                artifacts=[dict(r) for r in c.execute('SELECT name,path,mime FROM artifacts WHERE task_id=?',(latest['id'],))]
                work['title']=title_from_artifacts(artifacts,self.root/'data/artifacts',work['format']) or work['title']
                authored=c.execute('SELECT document FROM toolbox_text_versions WHERE job_id=?',(latest['id'],)).fetchone()
                if authored:work['title']=json.loads(authored['document'])['text']['title']
            production_history=[j for j in jobs if j['kind']!='discuss']
            state='discussing' if any(j['kind']=='discuss' for j in pending) else 'working' if pending else 'error' if production_history and production_history[-1]['status']=='error' else ('accepted' if latest['decisions'][-1]['kind']=='accept' else 'rejected') if latest and latest['decisions'] else 'review' if latest else 'queued'
            if not pending and latest and work['format']=='article' and not latest.get('article',{}).get('ready'):state='needs_evidence'
            if not pending and work['draft']['can_finalize']:state='draft'
            # A persisted user decision takes effect when received. Archival
            # completion, failures and later production do not replace it.
            # Wall-clock adjustments cannot make an earlier received decision
            # current again. The SQLite acceptance sequence is authoritative.
            decision_row=c.execute("SELECT * FROM toolbox_jobs WHERE work_id=? AND kind IN ('accept','reject') ORDER BY rowid DESC LIMIT 1",(wid,)).fetchone()
            decision=dict(decision_row) if decision_row else None
            work['decision']={**{k:decision[k] for k in ('id','kind','candidate_id','created_at','status')},'scope':json.loads(decision['scope'])} if decision else None
            if decision:state='accepted' if decision['kind']=='accept' else 'rejected'
            # Adoption is a durable user decision, independent of a later draft.
            # A new completed deliverable can still need review without silently
            # reversing that decision or rewriting the publication record.
            review_needed=bool(latest and not pending and (not decision or next(i for i,j in enumerate(jobs) if j['id']==latest['id'])>next(i for i,j in enumerate(jobs) if j['id']==decision['id'])))
            if latest and decision and not pending and not review_needed:
                review_needed=bool(c.execute('SELECT 1 FROM toolbox_jobs WHERE id=? AND julianday(finished_at)>julianday(?)',(latest['id'],decision['created_at'])).fetchone())
            production=[j for j in jobs if j['kind'] in ('create','change')]
            last_job=production[-1] if production else None
            last_version=next((v for v in versions if last_job and v['id']==last_job['id']),None)
            work['recovery']=job_recovery(last_job,c,outcome=read_outcome(c,last_job['id'])) if last_job else None
            work['production_issue']=(last_version or {}).get('production_issue') or (production_issue(last_job,read_outcome(c,last_job['id']),recovery=work['recovery']) if last_job else None)
            if work['production_issue'] and not pending:
                review_needed=False
                if not decision and state!='draft':state=work['production_issue']['status']
            if latest and work['format']=='article' and not latest.get('article',{}).get('ready'):review_needed=False
            work['review_needed']=review_needed
            # A list card carries its actual display descriptor. Rendering a
            # thumbnail must not fetch this work's full history in a second
            # per-row request or download the original image into a tiny box.
            work['thumbnail']=None
            work['latest_version_label']='v'+str(next(index for index,item in enumerate(versions) if item['id']==latest['id'])+1).zfill(2) if latest else None
            if latest:
                from easel_workbench.runtime.media_cache import service as display_media
                for image in c.execute("SELECT id,name,mime,path FROM artifacts WHERE task_id=? AND mime LIKE 'image/%' ORDER BY rowid",(latest['id'],)):
                    try:
                        work['thumbnail']=display_media(self).describe(dict(image),image['path'])
                        break
                    except (ValueError,OSError):
                        continue
            # Creation happens before any read transaction via the initialized
            # table; a plain read cannot backfill or dispatch historical rows.
            completion=getattr(self,'completion',None)
            if completion is not None:work['completion']=completion.get(wid,c)
            else:
                rows=[json.loads(r['document']) for r in c.execute('SELECT t.document FROM toolbox_completions t JOIN toolbox_jobs j ON j.id=t.decision_id WHERE t.work_id=? ORDER BY j.rowid',(wid,))]
                public=[{**{k:v for k,v in item.items() if not k.startswith('_')},'current':bool(decision and decision['id']==item['decision_id'] and decision['kind']=='accept')} for item in rows]
                work['completion']={'items':public,'latest':public[-1] if public else None}
            if _summary:
                work.update(latest_version=latest['id'] if latest else None,state=state,pending=pending)
                return {k:work[k] for k in ('id','title','article_id','format','updated_at','state','latest_version','latest_version_label','thumbnail','pending','decision','review_needed','production_issue','recovery','completion','creator')}
            from easel_workbench.runtime.local_operations import execution_mode
            work.update(versions=versions,latest_version=latest['id'] if latest else None,state=state,pending=pending,retryable=[{'id':j['id'],'error':j['error'],'recovery':r} for j in jobs if execution_mode(c,j['id'])=='agent' and (r:=job_recovery(j,c)) and r['can_retry']],
                history=[{**{k:j[k] for k in ('id','kind','text','candidate_id','status','created_at','finished_at','error','reply')},'scope':json.loads(j['scope']),'execution_mode':execution_mode(c,j['id']),'recovery':job_recovery(j,c,outcome=read_outcome(c,j['id'])) if execution_mode(c,j['id'])=='agent' else None,
                    'reply':public_reply(j['reply']) if j['kind'] in ('accept','reject') else j['reply'],
                    'files':[dict(f) for fid in json.loads(j['files']) for f in c.execute('SELECT id,name FROM toolbox_files WHERE id=?',(fid,))],
                    'artifacts':[dict(a) for a in c.execute('SELECT id,name FROM artifacts WHERE task_id=? ORDER BY rowid',(j['id'],))]} for j in jobs])
            work['discussions']=[j for j in work['history'] if j['kind']=='discuss']
            from easel_workbench.runtime.task_runtime import projection as task_projection
            for entry in work['history']:
                execution=task_projection(c,entry['id'])
                if execution:entry['execution']=execution
            for version in versions:
                execution=task_projection(c,version['id'])
                if execution:version['execution']=execution
            for entry in work['history']:
                if entry['kind']=='discuss':
                    from easel_workbench.runtime.content_studio import frozen_options
                    entry['creative']=frozen_options(c,entry['id'])
                if entry['kind'] in ('create','change'):
                    snapshot=c.execute('SELECT revision,document FROM toolbox_article_inputs WHERE job_id=?',(entry['id'],)).fetchone()
                    document=json.loads(snapshot['document']) if snapshot else None
                    entry['input']={key:document.get(key,'') for key in ('title','material','guidance')} if document else None
                context=c.execute('SELECT file_id FROM toolbox_review_inputs WHERE job_id=?',(entry['id'],)).fetchone()
                if context:entry['files']=[file for file in entry['files'] if file['id']!=context['file_id']];entry['review_file']={'id':context['file_id'],'name':'审阅与风格反馈.json'}
            from easel_workbench.runtime.work_review import revision as review_revision
            for version in versions:
                version['review_revision']=review_revision(c,wid,version['id'])
                version['review_count']=c.execute('SELECT count(*) FROM toolbox_review_notes WHERE work_id=? AND candidate_id=? AND deleted=0',(wid,version['id'])).fetchone()[0]
                from easel_workbench.runtime.revision_scope import can_continue_partial
                if version['status']=='completed' or can_continue_partial(c,by_id[version['id']]):
                    from easel_workbench.runtime.content_studio import source as studio_source,frozen_options
                    version['editable_text']=studio_source(self,c,wid,version['id'])[0]
                    version['creative']=frozen_options(c,version['id'])
                    version['human_text']=bool(c.execute('SELECT 1 FROM toolbox_text_versions WHERE job_id=?',(version['id'],)).fetchone())
                    if version['human_text']:
                        raw=version['editable_text']
                        if version['copy']:version['copy'].update(title=raw['title'],caption=raw['body'])
                        if version.get('article'):version['article'].update(title=raw['title'],body=raw['body'])
            work['input_history']=[{'id':row['id'],'created_at':row['created_at'],'revision':json.loads(row['result'])['revision'],
                'input':{key:json.loads(row['document']).get(key,'') for key in ('title','material','guidance')}}
                for row in c.execute('SELECT id,created_at,result,document FROM toolbox_article_draft_ops WHERE work_id=? ORDER BY julianday(created_at),rowid',(wid,))]
            return work
    def upload(self,jid,name,body):
        import os
        ident(jid)
        if not isinstance(name,str) or not 1<=len(name)<=240 or pathlib.PureWindowsPath(name).name!=name or any(ord(x)<32 for x in name):raise ValueError('附件名称无效')
        if not 0<len(body)<=20*1024*1024:raise ValueError('附件需在 20 MB 以内')
        sha=hashlib.sha256(body).hexdigest();directory=self.root/'data/toolbox/files'/jid;directory.mkdir(parents=True,exist_ok=True);path=directory/name
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM toolbox_files WHERE id=?',(jid,)).fetchone()
            if old:
                if old['sha256']!=sha or old['name']!=name:raise ValueError('同一附件 ID 不能用于不同文件')
                return {k:old[k] for k in ('id','name','mime','size')}
            temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
            with temp.open('xb') as stream:stream.write(body);stream.flush();os.fsync(stream.fileno())
            os.replace(temp,path);mime=mimetypes.guess_type(name)[0] or 'application/octet-stream'
            c.execute('INSERT INTO toolbox_files VALUES(?,?,?,?,?,?)',(jid,name,str(path),mime,len(body),sha))
        return {'id':jid,'name':name,'mime':mime,'size':len(body)}
    def file(self,fid):
        ident(fid)
        with self.store.connect() as c:
            row=c.execute('SELECT * FROM toolbox_files WHERE id=?',(fid,)).fetchone()
            if row is None:row=c.execute('SELECT * FROM artifacts WHERE id=?',(fid,)).fetchone()
        if not row:raise ValueError('附件不存在')
        value=dict(row)
        from easel_workbench.paths import artifact_path
        path=artifact_path(value['path'],self.root).resolve()
        # New task inputs must use the migrated file as well as file downloads.
        # The original database row and historical frozen inputs stay unchanged.
        value['path']=str(path)
        roots=[self.root/'data/artifacts',self.root/'data/toolbox/files',self.root/'data/workbench']
        if not any(path.is_relative_to(p.resolve()) for p in roots) or not path.is_file():raise ValueError('附件文件不可用')
        if value.get('sha256') and hashlib.sha256(path.read_bytes()).hexdigest()!=value['sha256']:raise ValueError('附件校验失败')
        return value,path
