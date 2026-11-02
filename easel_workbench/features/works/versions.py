"""Exact parent versions and work lifecycle, sharing caller-owned transactions.

No model transport or HTTP dependency lives here. The existing work store and
review/delivery helpers remain the authority while later domains migrate.
"""
import copy
import json
from pathlib import Path

from easel_workbench.contracts.production import PlanConflict
from easel_workbench.paths import owned_output_path
from easel_workbench.runtime.creator_runtime import packed, key, digest
from easel_workbench.runtime.desk import stamp


class WorkVersions:
    def __init__(self, *, store, root, creator, work_store):
        self.store = store
        self.root = Path(root).resolve()
        self.creator = creator
        self.box = work_store

    def parent(self,value,c=None):
        context=value.get('context') or {};wid=context.get('work_id');vid=context.get('parent_version_id')
        if not wid and not vid:return None
        if not wid or not vid:raise ValueError('修改必须同时选择作品与准确父版本')
        wid=key(wid);vid=key(vid);sid=key(value.get('sessionId') or value.get('session_id'))
        if c is None:
            with self.store.connect() as conn:return self.parent(value,conn)
        linked=c.execute("SELECT 1 FROM easel_chat_turns WHERE session_id=? AND json_extract(document,'$.work.work_id')=?",(sid,wid)).fetchone()
        if not linked:raise PlanConflict('父版本不属于当前 Easel 会话')
        from easel_workbench.runtime.work_review import candidate,notes,source_data
        from easel_workbench.runtime.native_continuation import continuation
        original=c.execute("SELECT * FROM toolbox_jobs WHERE id=? AND work_id=? AND kind IN ('create','change')",(vid,wid)).fetchone()
        followup=continuation(c,original)
        if followup and followup['session_id']!=sid:raise PlanConflict('中断版本须回到其原生会话继续')
        job=dict(original) if followup else candidate(self.box,c,wid,vid)
        row=c.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?',(vid,)).fetchone()
        document=json.loads(row[0]) if row else {}
        snapshot=document.get('creator_snapshot')
        source_article=document.get('source_article')
        cursor=job.get('candidate_id');seen={vid}
        while not snapshot and cursor and cursor not in seen:
            seen.add(cursor)
            previous=c.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?',(cursor,)).fetchone()
            inherited=json.loads(previous[0]) if previous else {}
            snapshot=inherited.get('creator_snapshot')
            source_article=source_article or inherited.get('source_article')
            ancestor=c.execute('SELECT candidate_id FROM toolbox_jobs WHERE id=? AND work_id=?',(cursor,wid)).fetchone()
            cursor=ancestor[0] if ancestor else None
        if not snapshot:raise ValueError('父版本缺少冻结技能依据')
        artifacts=[]
        for file in c.execute('SELECT id,name,path,mime FROM artifacts WHERE task_id=? ORDER BY rowid',(vid,)):
            path=Path(file['path']).resolve()
            if not path.is_relative_to((self.root/'data/artifacts').resolve()) or not path.is_file():raise PlanConflict('父版本成品不可用')
            artifacts.append({**dict(file),'sha256':digest(path.read_bytes())})
        chain=[];cursor=vid
        for _ in range(64):
            raw=c.execute('SELECT id,candidate_id FROM toolbox_jobs WHERE id=? AND work_id=?',(cursor,wid)).fetchone()
            if not raw or raw['id'] in chain:break
            chain.append(raw['id']);cursor=raw['candidate_id']
            if not cursor:break
        raw_feedback=[dict(r) for r in c.execute("SELECT id,candidate_id,kind,text,scope,status,created_at FROM toolbox_jobs WHERE work_id=? AND kind IN ('feedback','accept','reject') ORDER BY rowid",(wid,)) if r['candidate_id'] in chain]
        sources,_=source_data(self.box,c,wid,vid,allow_partial=bool(followup))
        retained=None
        if followup:
            raw=c.execute('SELECT document FROM easel_chat_plans WHERE id=?',('plan-'+vid,)).fetchone()
            if not raw:raise PlanConflict('中断版本缺少原始冻结制作方案')
            plan=json.loads(raw[0])
            if plan.get('snapshot')!=snapshot or plan.get('work',{}).get('work_id')!=wid:raise PlanConflict('原始制作方案与所选版本不一致')
            directory=Path(plan['output_directory'])
            try:directory=owned_output_path(self.root,directory.relative_to(self.root))
            except ValueError as exc:raise PlanConflict('中断版本的原文件目录不属于当前项目') from exc
            files=[]
            for path in sorted(directory.rglob('*')) if directory.is_dir() else []:
                safe=owned_output_path(self.root,path.relative_to(self.root))
                if safe.is_file():files.append({'path':str(safe),'sha256':digest(safe.read_bytes())})
            retained={'source_version_id':vid,'material':plan['request']['message'],'attachments':plan['attachments'],'files':files,
                      'notice':'原回合已确认中断。保留原文件，仅在本轮新输出目录中完成后续版本。'}
        from easel_workbench.runtime.article_drafts import job_work
        parent_mode=job_work(self.box.options(wid,c),vid,c)['article_mode']
        return {'continuation':retained,'work_id':wid,'version_id':vid,'format':self.box.options(wid,c)['format'],'article_mode':parent_mode,'snapshot':snapshot,
                'artifacts':artifacts,'text':sources,'annotations':notes(c,wid,vid),'raw_feedback':raw_feedback,
                'creation_options':document.get('creation_options'),
                'source_article':source_article,
                'notice':'原始意见尚未提炼；撤回、替代和矛盾分别保留，不据此改写长期画像或默认技能。'}

    def accept(self,c,plan):
        from easel_workbench.runtime.local_operations import mark_execution,reserve_work
        from easel_workbench.runtime.task_runtime import _put_run,workflow_template
        work=plan['work'];wid=work['work_id'];jid=work['version_id'];now=stamp();snapshot=plan['snapshot']
        old=c.execute('SELECT signature FROM toolbox_jobs WHERE id=?',(jid,)).fetchone()
        if old:
            if old['signature']!=plan['token']:raise PlanConflict('此回合已经用于其他作品版本')
            return
        message=plan['request']['message'];title=next((s.strip()[:120] for s in message.splitlines() if s.strip()),'素材创作')
        if work['kind']=='create':
            article=plan.get('source_article');aid=article['id'] if article else None
            c.execute('INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)',(wid,aid,title,message,now,now))
            c.execute('INSERT INTO toolbox_work_options VALUES(?,?,?)',(wid,work['format'],work.get('article_mode','auto')))
            reserve_work(c,wid,title)
            self.creator.bind_work(c,wid,{'profile_id':snapshot['profile']['id'],'profile_revision':snapshot['profile']['revision']})
        if c.execute("SELECT 1 FROM toolbox_jobs WHERE work_id=? AND status IN ('queued','dispatching','running','uncertain','needs_desktop','parked')",(wid,)).fetchone():
            raise PlanConflict('作品尚有在途或回执未知的操作，请先核对')
        c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,candidate_id,files,signature,status,created_at) VALUES(?,?,?,?,?,?,?,?,?)',
                  (jid,wid,work['kind'],message,work.get('parent_version_id'),packed([f['id'] for f in plan['attachments']]),plan['token'],'queued',now))
        if work['kind']=='create' and aid:
            c.execute('UPDATE articles SET selected=1 WHERE id=?',(aid,))
            from easel_workbench.runtime.news_feedback import enqueue
            enqueue(c,aid,'',task_id=jid,created_at=now)
        mark_execution(c,jid,'observed','easel_native_chat')
        inputs={'title':title,'material':message,'guidance':'','files':[f['id'] for f in plan['attachments']], 'article_mode':work.get('article_mode','auto')}
        c.execute('INSERT INTO toolbox_article_inputs VALUES(?,?,?)',(jid,1,packed(inputs)))
        if work['kind']=='create':c.execute('INSERT INTO toolbox_article_drafts VALUES(?,?,?,?)',(wid,1,packed(inputs),1))
        document=copy.deepcopy(plan['review_input'])
        expected=copy.deepcopy(document['learning_snapshot'])
        from easel_workbench.runtime.task_runtime import attach_profile_contract
        # Reuse the exact legacy gate compiler and bind its frozen inspection run
        # to the same acceptance transaction, without reinterpreting methods.
        document.pop('learning_snapshot',None)
        attach_profile_contract(self.box,c,document,jid,request_text=message)
        if document['learning_snapshot']!=expected:raise PlanConflict('交付核验依据与确认方案不同，未发送')
        document.update(source_article=plan.get('source_article'),creation_instructions=plan['actual_prompt'],
                        execution_prompt={'body':plan['actual_prompt'],'sha256':plan['actual_prompt_sha256'],'creator_snapshot':snapshot})
        from easel_workbench.runtime.work_review import attach_document
        attach_document(self.box,c,wid,jid,document)
        flow=workflow_template(snapshot['task'])
        _put_run(c,{'schema_version':1,'id':jid,'work_id':wid,'snapshot':snapshot,'engine':'easel.harnesses.codex',
                    'session_id':plan['session_id'],'status':'queued','steps':[{**s,'status':'completed' if s['id']=='freeze' else 'waiting'} for s in flow['steps']], 'created_at':now})

    def started(self,c,turn,call_id,execution_id):
        from easel_workbench.runtime.task_runtime import read_run,_put_run,step
        work=turn['work']
        c.execute("UPDATE toolbox_jobs SET dispatch_started=1,status='running',started_at=?,turn_id=? WHERE id=?",(stamp(),execution_id,work['version_id']))
        run=read_run(c,work['version_id']);run['model_call_id']=call_id;run['native_id']=turn['native_id'];_put_run(c,run)
        step(c,work['version_id'],'production','running',native_turn_id=turn.get('native_turn_id'),execution_identity=turn.get('execution_identity'))

    def finished(self,turn):
        work=turn['work']
        jid=work['version_id']
        if turn['status']!='completed':
            with self.store.connect() as c:c.execute("UPDATE toolbox_jobs SET status='uncertain',dispatch_started=1,error=?,reply=? WHERE id=?",(turn.get('error') or '原生会话未取得明确完成回执，请先核对。',turn.get('output',''),jid))
            return {**work,'status':'uncertain','replayed':False}
        from easel_workbench.runtime.production_delivery import record_delivery
        record_delivery(self.box,jid,turn['output'],turn.get('native_turn_id',''),product_roots=[self.root/'outputs'/turn['session_id']/turn['id']/'products'],execution_identity=turn.get('execution_identity'))
        return {**work,'status':self.box.work(work['work_id'])['state']}
