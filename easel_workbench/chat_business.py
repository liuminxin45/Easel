"""Version and authorization adapter around Easel's native chat runner.

Creative methods come from project SKILL.md releases. This module only freezes
the accepted request, receives files, and records existing business identities.
It never opens a model transport or schedules the legacy production worker.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import uuid
import sqlite3
import tempfile
import contextlib

from .skill_catalog import ProjectSkillCatalog,parse_skill
from .paths import owned_output_path
from .runtime.creator_runtime import packed, key, digest
from .runtime.desk import stamp
from .runtime.toolbox_store import text


class PlanConflict(ValueError):
    pass


class ChatBusiness:
    def __init__(self,box,root=None):
        self.box,self.store=box,box.store
        self.root=Path(root or box.root).resolve()
        self.catalog=ProjectSkillCatalog(self.root)
        self.creator=box.creator
        self.chat=None
        with self.store.connect() as c:
            c.execute('CREATE TABLE IF NOT EXISTS easel_chat_plans(id TEXT PRIMARY KEY,session_id TEXT NOT NULL,signature TEXT NOT NULL,document TEXT NOT NULL)')

    def skills(self):
        from .skills import launch_metadata
        from .project_skill_sync import matches_source
        result=[];revision=self.catalog.revision()
        for item in self.catalog.entries():
            try:release=self.creator.detail('skill',item['id'])
            except ValueError:continue
            available=matches_source(self.creator,release)
            row={'id':item['id'],'skill_id':item['id'],'name':item['id'],'display_name':item['name'],
                 'description':item['description'],'layer':item['layer'],'needsApi':False,'apiConfigured':True,
                 'version':release['version'],'source_revision':revision,'sha256':release['sha256'],
                 'available':available,'reason':'' if available else '项目技能迁入版本尚未激活',**launch_metadata(release)}
            row['launch_actions']=[{**action,'requires_plan':action['task'] in ('poster','article','change','image'),
                                   **({'requires_context':True} if action['task'] not in ('poster','article','discuss','image') else {})} for action in row['launch_actions']]
            result.append(row)
        return result

    def skill(self,sid):
        item=next((r for r in self.skills() if r['id']==sid),None)
        if not item:raise ValueError('找不到项目内置技能')
        release=self.creator.detail('skill',sid)
        metadata,body=parse_skill(release['prompt'])
        return {**item,**release,'body':body,'content':body,'meta':metadata,'raw':release['prompt']}

    def history(self,sid):
        result=self.chat.history(sid)
        with self.store.connect() as c:
            for message in result['session']['messages']:
                if message['role']!='assistant':continue
                native=c.execute('SELECT document FROM easel_chat_turns WHERE id=?',(message['turnId'],)).fetchone()
                if native:
                    turn=json.loads(native[0])
                    message['work']=copy.deepcopy(turn.get('work'))
                    message['business_receipt']=copy.deepcopy(turn.get('business_receipt'))
                message['output_files']=[{'id':r['id'],'name':r['name'],'mime':r['mime'],'url':'/api/files/'+r['id']} for r in c.execute('SELECT id,name,mime FROM artifacts WHERE task_id=? ORDER BY rowid',(message['turnId'],))]
                job=c.execute('SELECT status,error FROM toolbox_jobs WHERE id=?',(message['turnId'],)).fetchone()
                if job:message.update(business_status=job['status'],business_error=job['error'])
            for work in result['linked_works']:
                row=c.execute('SELECT title FROM toolbox_works WHERE id=?',(work['work_id'],)).fetchone()
                if row:work['title']=row['title']
        return result

    def _session(self,value):
        sid=key(value.get('sessionId') or value.get('session_id'))
        return self.chat.history(sid)['session']

    def _selection(self,value):
        session=self._session(value);context=value.get('context') or {}
        if not isinstance(context,dict):raise ValueError('技能选择无效')
        profile_id=context.get('profile_id') or session['profile_id']
        if profile_id!=session['profile_id']:raise PlanConflict('已有会话保持原画像，请新建会话后切换')
        parent=self._parent(value)
        if parent:
            if context.get('action_id')=='discuss':
                profile=parent['snapshot']['profile'];sid=context.get('skill_id') or 'topic-research'
                profile_version=profile.get('task_skill_versions',{}).get('discuss',{}).get(sid,profile.get('skill_versions',{}).get(sid))
                version=context.get('version',profile_version)
                refs=[{'id':sid,**({'version':version} if version is not None else {})}]
                snapshot=self.creator.resolve(profile['id'],'discuss',refs,context.get('trial') is True,profile['revision'],allow_historical_profile=True)
                return session,{'id':'discuss','task':'discuss','requires_plan':False},snapshot
            snapshot=copy.deepcopy(parent['snapshot'])
            sid=context.get('skill_id') or 'content-production'
            selected=next((s for s in snapshot['skills'] if s['id']==sid),None)
            if not selected or context.get('version',selected['version'])!=selected['version']:
                raise PlanConflict('修改继承准确父版技能；请核对所选版本')
            if context.get('action_id','change')!='change':raise PlanConflict('所选作品版本只接受修改动作')
            for skill in snapshot['skills']:
                if 'change' not in skill['tasks']:raise ValueError('父版技能不支持修改，请明确另存制作方案')
            snapshot['task']='change';snapshot.pop('snapshot_sha256',None)
            snapshot['snapshot_sha256']=digest(packed(snapshot))
            return session,{'id':'change','task':'change','requires_plan':True,'format':parent['format']},snapshot
        sid=context.get('skill_id') or 'topic-research'
        source=next((s for s in self.skills() if s['id']==sid),None)
        if not source or not source['available']:raise ValueError('此项目技能尚不可调用')
        actions=source['launch_actions']
        action_id=context.get('action_id') or ('discuss' if sid=='topic-research' else actions[0]['id'] if actions else '')
        action=next((a for a in actions if a['id']==action_id),None)
        if not action or action.get('requires_context'):raise ValueError('请选择可直接执行的技能动作或准确作品版本')
        task=action['task'];profile=self.creator.detail('profile',profile_id)
        versions=profile.get('task_skill_versions',{}).get(task,{})
        version=context.get('version',versions.get(sid,profile.get('skill_versions',{}).get(sid,source['version'])))
        if type(version) is not int or version<1:raise ValueError('技能版本无效')
        release=self.creator.detail('skill',sid,version)
        trial=context.get('trial',False)
        if type(trial) is not bool:raise ValueError('候选试用标记无效')
        if release['status']!='published' and not trial:raise ValueError('候选技能需要先在明确试用入口确认范围')
        refs=[{'id':sid,'version':version}]
        for dep in (release.get('composition') or {}).get('requires',[]):
            meta=next((s for s in self.catalog.entries() if s['id']==dep),None)
            if meta and task in meta['tasks']:
                refs.append({'id':dep,'version':versions.get(dep,profile.get('skill_versions',{}).get(dep,self.creator.detail('skill',dep)['published_version']))})
        # Existing safety requirements remain service contracts, not methods.
        if task in ('poster','article','image'):
            for ref in profile.get('default_skills',{}).get(task,[]):
                if ref not in {r['id'] for r in refs}:
                    rel=self.creator.detail('skill',ref)
                    if task in rel['tasks']:refs.append({'id':ref,'version':versions.get(ref,profile.get('skill_versions',{}).get(ref,rel['published_version']))})
        snapshot=self.creator.resolve(profile_id,task,refs,trial,profile['revision'])
        return session,action,snapshot

    def _parent(self,value,c=None):
        context=value.get('context') or {};wid=context.get('work_id');vid=context.get('parent_version_id')
        if not wid and not vid:return None
        if not wid or not vid:raise ValueError('修改必须同时选择作品与准确父版本')
        wid=key(wid);vid=key(vid);sid=key(value.get('sessionId') or value.get('session_id'))
        if c is None:
            with self.store.connect() as conn:return self._parent(value,conn)
        linked=c.execute("SELECT 1 FROM easel_chat_turns WHERE session_id=? AND json_extract(document,'$.work.work_id')=?",(sid,wid)).fetchone()
        if not linked:raise PlanConflict('父版本不属于当前 Easel 会话')
        from .runtime.work_review import candidate,notes,source_data
        job=candidate(self.box,c,wid,vid)
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
        sources,_=source_data(self.box,c,wid,vid)
        from .runtime.article_drafts import job_work
        parent_mode=job_work(self.box.options(wid,c),vid,c)['article_mode']
        return {'work_id':wid,'version_id':vid,'format':self.box.options(wid,c)['format'],'article_mode':parent_mode,'snapshot':snapshot,
                'artifacts':artifacts,'text':sources,'annotations':notes(c,wid,vid),'raw_feedback':raw_feedback,
                'creation_options':document.get('creation_options'),
                'source_article':source_article,
                'notice':'原始意见尚未提炼；撤回、替代和矛盾分别保留，不据此改写长期画像或默认技能。'}

    def _news_source(self,value,c=None):
        aid=(value.get('context') or {}).get('article_id')
        if not aid:return None
        aid=key(aid)
        if c is None:
            with self.store.connect() as conn:return self._news_source(value,conn)
        row=c.execute('SELECT id,title,body,url,publisher,published_at,run_at,source_job,source_event_id FROM articles WHERE id=?',(aid,)).fetchone()
        if not row:raise ValueError('所选资讯不存在，原输入已保留')
        document=dict(row)
        document['provenance']=[dict(r) for r in c.execute('SELECT r.id,r.source_job,r.run_id,r.run_at,r.hash FROM provenance p JOIN runs r ON r.id=p.run WHERE p.article_id=? ORDER BY r.run_at,r.id',(aid,))]
        document['snapshot_sha256']=digest(packed(document))
        return document

    def _attachments(self,value):
        files=value.get('attachments') or []
        if not isinstance(files,list) or len(files)>20:raise ValueError('素材数量无效')
        result=[]
        for item in files:
            if not isinstance(item,dict):raise ValueError('素材引用无效')
            fid=key(item.get('id'));record,path=self.box.file(fid)
            if record.get('name')!=item.get('name'):raise ValueError('素材身份与当前文件不一致')
            raw=path.read_bytes();fingerprint=hashlib.sha256(raw).hexdigest()
            if record.get('sha256') and record['sha256']!=fingerprint:raise PlanConflict('素材字节已变化')
            target=owned_output_path(self.root,Path('outputs/_sessions/materials')/fingerprint/record['name'])
            result.append({'id':fid,'name':record['name'],'path':str(target),'sha256':fingerprint,'size':len(raw)})
        return result

    def _freeze_attachments(self,value):
        materials=self._attachments(value)
        for item in materials:
            _,source=self.box.file(item['id']);raw=source.read_bytes()
            if digest(raw)!=item['sha256']:raise PlanConflict('素材字节已有变化，未发送')
            target=owned_output_path(self.root,Path(item['path']).relative_to(self.root));target.parent.mkdir(parents=True,exist_ok=True)
            if target.exists():
                if digest(target.read_bytes())!=item['sha256']:raise PlanConflict('冻结素材副本字节不符')
            else:
                try:
                    with target.open('xb') as handle:handle.write(raw)
                except FileExistsError:
                    if digest(target.read_bytes())!=item['sha256']:raise PlanConflict('冻结素材副本字节不符')
        return materials

    def _instruction(self,snapshot,message,attachments,output_dir,work=None,source_article=None,review_input=None,reference_work=None):
        # All method text is the exact released SKILL content, not Python prose.
        sections=[snapshot['prompt_text']]
        payload={'session_task':snapshot['task'],'creator_profile':snapshot['profile'],
                 'user_message':message,'attachments':attachments,'output_directory':str(output_dir),
                 'selected_skills':[{'id':r['id'],'version':r['version'],'sha256':r['sha256'],'entry':r['entry']} for r in snapshot['skills']],
                 'frozen_skill_files':self._bundle(snapshot),
                 'source_article':source_article,
                 'reference_work':reference_work,
                 'delivery_contract':{k:review_input[k] for k in ('learning_snapshot','style_delivery_contract','frozen_reference_assets') if k in review_input} if review_input else None,
                 'work':work,'authorization':{'production':snapshot['task'] in ('poster','article','image','change'),
                                               'discussion_only':snapshot['task']=='discuss','publish':False,'adopt':False}}
        sections.append('## 本轮冻结输入\n'+packed(payload))
        return '\n\n'.join(sections)

    def _review_document(self,snapshot,work,message,parent=None):
        """Compile the existing review contract on a disposable DB, no task/files."""
        from .runtime.task_runtime import attach_profile_contract
        creative={'schema_version':2,'enabled':True,'creator':{
            'profile_id':snapshot['profile']['id'],'profile_revision':snapshot['profile']['revision'],
            'skills':[{'id':s['id'],'version':s['version']} for s in snapshot['skills']],'trial':bool(snapshot.get('trial'))}}
        for name in ('target','keep_text','text','text_policy','fixed_master'):
            if name in ((parent or {}).get('creation_options') or {}):creative[name]=copy.deepcopy(parent['creation_options'][name])
        from .runtime.revision_scope import conflicts
        if conflicts(creative,message):raise PlanConflict('本轮修改与原字锁定范围冲突，请先核对文字修改范围')
        document={'schema_version':2,'work_id':work['work_id'],'candidate_id':work.get('parent_version_id'),
                  'creation_options':creative,'creator_snapshot':snapshot,
                  'annotations':copy.deepcopy((parent or {}).get('annotations',[])),
                  'raw_feedback':{'items':copy.deepcopy((parent or {}).get('raw_feedback',[]))}}
        with tempfile.TemporaryDirectory(prefix='easel-chat-review-preview-') as folder:
            database=Path(folder)/'preview.sqlite'
            with self.store.connect() as source,contextlib.closing(sqlite3.connect(database)) as target:source.backup(target)
            store=copy.copy(self.store);store.path=database
            box=copy.copy(self.box);box.store=store;box.creative_preview=True
            box.creator=copy.copy(self.creator);box.creator.store=store;box.creator.box=box
            if getattr(box,'learning',None):
                box.learning=copy.copy(box.learning);box.learning.store=store;box.learning.box=box
            with store.connect() as c:attach_profile_contract(box,c,document,work['version_id'],request_text=message)
        if not document.get('learning_snapshot') or not document.get('style_delivery_contract'):
            raise ValueError('未能冻结独立交付核验合同，未开始制作')
        return document

    def _workspace(self):
        from easel.harnesses.base import RunRequest
        from easel.harnesses.workspace import harness_instructions
        value=harness_instructions(RunRequest('',self.root,{'EASEL_AGENT_RUNTIME':'codex'}))
        project=self.root/'AGENTS.md'
        if project.is_file():value+='\n\n## 本轮项目约定冻结\n'+project.read_text(encoding='utf-8-sig')
        return value

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
                if not row or digest(bytes(row[0]))!=resource['sha256']:raise PlanConflict('冻结技能资源缺失或字节不符')
                raw=bytes(row[0]);name=resource['path']
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
        return result

    @staticmethod
    def _plan_request(value):
        # Upstream persona is an optional display hint; the server session owns
        # identity. Only meaningful production inputs enter the plan signature.
        context=copy.deepcopy(value.get('context') or {});context.pop('plan_token',None)
        return {'message':value.get('message'),'sessionId':value.get('sessionId') or value.get('session_id'),
                'turnId':value.get('turnId') or value.get('turn_id') or value.get('id'),
                'attachments':value.get('attachments') or [],'context':context}

    def plan(self,value):
        value=self._plan_request(value)
        signature=digest(packed(value));turn_id=key(value['turnId']);plan_id='plan-'+turn_id
        with self.store.connect() as c:
            old=c.execute('SELECT signature,document FROM easel_chat_plans WHERE id=?',(plan_id,)).fetchone()
        if old:
            if old['signature']!=signature:raise PlanConflict('同一制作方案不能更换输入，请重新核对')
            return self._public_plan(json.loads(old['document']))
        message=text(value.get('message',''),100000)
        session,action,snapshot=self._selection(value)
        if not action.get('requires_plan'):raise ValueError('此技能直接在对话调用，无需制作方案')
        attachments=self._attachments(value)
        if not message.strip() and not attachments:raise ValueError('请先输入目标或添加素材')
        with self.store.connect() as c:
            old=c.execute('SELECT signature,document FROM easel_chat_plans WHERE id=?',(plan_id,)).fetchone()
            if old:
                if old['signature']!=signature:raise PlanConflict('同一制作方案不能更换输入，请重新核对')
                return self._public_plan(json.loads(old['document']))
            parent=self._parent(value)
            article_mode=parent['article_mode'] if parent else (value.get('context') or {}).get('article_mode','auto')
            if article_mode not in ('auto','product') or article_mode=='product' and action.get('format')!='article':raise ValueError('文章类型与本轮制作不一致')
            work_id=parent['work_id'] if parent else 'chat-work-'+uuid.uuid4().hex
            work={'work_id':work_id,'version_id':turn_id,'format':action.get('format','poster'),'kind':'change' if parent else 'create'}
            work['article_mode']=article_mode
            if parent:work['parent_version_id']=parent['version_id']
            output=owned_output_path(self.root,Path('outputs')/session['id']/turn_id/'products')
            source_article=parent.get('source_article') if parent else self._news_source(value)
            review_input=self._review_document(snapshot,work,message,parent)
            actual=self._instruction(snapshot,message,attachments,output,work,source_article,review_input)
            if parent:actual+='\n\n## 准确父版与原始意见\n'+packed(parent)
            document={'id':plan_id,'session_id':session['id'],'turn_id':turn_id,'request':copy.deepcopy(value),
                      'signature':signature,'snapshot':snapshot,'attachments':attachments,'work':work,
                      'output_directory':str(output),'actual_prompt':actual,'actual_prompt_sha256':digest(actual),
                      'library_revision':self.catalog.revision(),'parent':parent,'created_at':stamp()}
            document['source_article']=source_article
            document['review_input']=review_input
            document['frozen_instructions']=self._workspace()
            document['instructions_sha256']=digest(document['frozen_instructions'])
            document['token']=digest(packed(document))
            c.execute('BEGIN IMMEDIATE')
            concurrent=c.execute('SELECT signature,document FROM easel_chat_plans WHERE id=?',(plan_id,)).fetchone()
            if concurrent:
                if concurrent['signature']!=signature:raise PlanConflict('同一制作方案不能更换输入')
                return self._public_plan(json.loads(concurrent['document']))
            c.execute('INSERT INTO easel_chat_plans VALUES(?,?,?,?)',(plan_id,session['id'],signature,packed(document)))
        return self._public_plan(document)

    def _public_plan(self,document):
        snapshot=document['snapshot'];message=document['request']['message']
        preview={'production_input':{'material':message,'title':next((s.strip()[:120] for s in message.splitlines() if s.strip()),'所附素材'),
                                    'format':document['work']['format'],'article_mode':document['work'].get('article_mode','auto'),
                                    'files':[{k:f[k] for k in ('id','name','sha256')} for f in document['attachments']]},
                 'execution_prompt':{'body':document['actual_prompt'],'sha256':document['actual_prompt_sha256'],
                                     'runtime_instructions':document['frozen_instructions'],'instructions_sha256':document['instructions_sha256'],
                                     'editable_text':message,'creator_snapshot':snapshot},
                 'creator_snapshot':snapshot,'revision_token':document['token']}
        return {'plan':preview,'plan_token':document['token'],'session_id':document['session_id'],'turn_id':document['turn_id']}

    def prepare(self,value):
        previous=self.chat.receipt(value)
        if previous:return {'receipt':previous}
        context=value.get('context') or {}
        token=context.get('plan_token')
        if token:
            tid=key(value.get('turnId') or value.get('turn_id') or value.get('id'))
            with self.store.connect() as c:
                row=c.execute('SELECT document FROM easel_chat_plans WHERE id=?',('plan-'+tid,)).fetchone()
            if not row:raise ValueError('制作方案已失效，请重新核对')
            plan=json.loads(row[0]);original=self._plan_request(value)
            if plan['token']!=token or plan['signature']!=digest(packed(original)):
                raise PlanConflict('消息、素材或技能与已确认方案不同，未发送')
            if plan['library_revision']!=self.catalog.revision():raise PlanConflict('项目技能已有变化，请重新确认方案')
            if digest(self._workspace())!=plan['instructions_sha256']:raise PlanConflict('项目会话约定已有变化，请重新确认方案')
            current_files=self._attachments(value)
            if current_files!=plan['attachments']:raise PlanConflict('素材与确认方案不一致')
            if self._parent(value)!=plan.get('parent'):raise PlanConflict('父版反馈或素材已有变化，请重新确认修改方案')
            if not plan.get('parent') and self._news_source(value)!=plan.get('source_article'):raise PlanConflict('资讯来源已有变化，请重新确认方案')
            return {'snapshot':plan['snapshot'],'actual_prompt':plan['actual_prompt'],'work':plan['work'],'frozen_instructions':plan['frozen_instructions']}
        session,action,snapshot=self._selection(value)
        if action.get('requires_plan'):raise ValueError('请先确认本次制作方案')
        message=text(value.get('message',''),100000)
        attachments=self._attachments(value)
        if not message.strip() and not attachments:raise ValueError('请先输入目标或添加素材')
        return {'snapshot':snapshot,'actual_prompt':self._instruction(snapshot,message,attachments,self.root/'outputs'/session['id'],source_article=self._news_source(value),reference_work=self._parent(value)),
                'work':None,'frozen_instructions':self._workspace()}

    def accept(self,c,turn):
        """Join version registration to the native chat acceptance transaction."""
        self._bundle(turn['snapshot'],True,c)
        if (turn.get('work') or {}).get('internal_correction'):
            from .native_corrections import accept as accept_correction
            accept_correction(self,c,turn)
        elif turn.get('work'):
            row=c.execute('SELECT document FROM easel_chat_plans WHERE id=?',('plan-'+turn['id'],)).fetchone()
            if not row:raise PlanConflict('制作方案不存在，未创建作品')
            plan=json.loads(row[0])
            if plan['actual_prompt_sha256']!=turn['actual_prompt_sha256'] or plan['work']!=turn['work']:
                raise PlanConflict('会话与已确认制作方案不一致')
            if self._freeze_attachments(plan['request'])!=plan['attachments']:raise PlanConflict('素材与本轮确认方案不同')
            if self._parent(plan['request'],c)!=plan.get('parent'):raise PlanConflict('父版本依据已有变化，未发送')
            if not plan.get('parent') and self._news_source(plan['request'],c)!=plan.get('source_article'):raise PlanConflict('资讯来源已变化，未发送')
            from .native_corrections import supersede_queued_user
            supersede_queued_user(c,turn['session_id'])
            self._accept_work(c,plan)
        else:
            submitted=json.loads(turn['actual_prompt'].rsplit('## 本轮冻结输入\n',1)[1])
            if self._freeze_attachments({'attachments':turn['attachments']})!=submitted['attachments']:raise PlanConflict('素材与本轮冻结讨论输入不同')
            if self._news_source(turn,c)!=submitted['source_article']:raise PlanConflict('资讯来源与本轮冻结讨论输入不同')
            if self._parent(turn,c)!=submitted.get('reference_work'):raise PlanConflict('讨论所指版本依据已有变化，未发送')
            from .native_corrections import supersede_queued_user
            supersede_queued_user(c,turn['session_id'])
        task_id=turn['work']['version_id'] if turn.get('work') else turn['id']
        call={'schema_version':1,'id':'chat-call-'+turn['id'],'task_id':task_id,'task':turn['snapshot']['task'],
              'snapshot':turn['snapshot'],'prompt':turn['actual_prompt'],
              'input':{'message':turn['message'],'session_id':turn['session_id']},
              'input_sha256':turn['actual_prompt_sha256'],'status':'submitting','created_at':stamp(),
              'submission_started_at':stamp(),'delivery_state':'not_started',
              'active_skills':[{k:s[k] for k in ('id','name','version','sha256')} for s in turn['snapshot']['skills'] if s.get('execution_role')=='active'],
              'reserved_skills':[{k:s[k] for k in ('id','name','version','sha256')} for s in turn['snapshot']['skills'] if s.get('execution_role')=='reserved_independent'],
              'runner':'easel.harnesses.codex.CodexAdapter'}
        c.execute('INSERT INTO creator_model_calls VALUES(?,?,?,?)',(call['id'],task_id,packed(call),stamp()))
        if turn.get('work'):
            wid=turn['work']['work_id']
            turn['user_input_fence']={'review_seq':c.execute('SELECT coalesce(max(seq),0) FROM toolbox_review_events WHERE work_id=?',(wid,)).fetchone()[0],
                                      'draft_rowid':c.execute('SELECT coalesce(max(rowid),0) FROM toolbox_article_draft_ops WHERE work_id=?',(wid,)).fetchone()[0]}

    def _accept_work(self,c,plan):
        from .runtime.local_operations import mark_execution,reserve_work
        from .runtime.task_runtime import _put_run,workflow_template
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
            from .runtime.news_feedback import enqueue
            enqueue(c,aid,'',task_id=jid,created_at=now)
        mark_execution(c,jid,'observed','easel_native_chat')
        inputs={'title':title,'material':message,'guidance':'','files':[f['id'] for f in plan['attachments']], 'article_mode':work.get('article_mode','auto')}
        c.execute('INSERT INTO toolbox_article_inputs VALUES(?,?,?)',(jid,1,packed(inputs)))
        if work['kind']=='create':c.execute('INSERT INTO toolbox_article_drafts VALUES(?,?,?,?)',(wid,1,packed(inputs),1))
        document=copy.deepcopy(plan['review_input'])
        expected=copy.deepcopy(document['learning_snapshot'])
        from .runtime.task_runtime import attach_profile_contract
        # Reuse the exact legacy gate compiler and bind its frozen inspection run
        # to the same acceptance transaction, without reinterpreting methods.
        document.pop('learning_snapshot',None)
        attach_profile_contract(self.box,c,document,jid,request_text=message)
        if document['learning_snapshot']!=expected:raise PlanConflict('交付核验依据与确认方案不同，未发送')
        document.update(source_article=plan.get('source_article'),creation_instructions=plan['actual_prompt'],
                        execution_prompt={'body':plan['actual_prompt'],'sha256':plan['actual_prompt_sha256'],'creator_snapshot':snapshot})
        from .runtime.work_review import attach_document
        attach_document(self.box,c,wid,jid,document)
        flow=workflow_template(snapshot['task'])
        _put_run(c,{'schema_version':1,'id':jid,'work_id':wid,'snapshot':snapshot,'engine':'easel.harnesses.codex',
                    'session_id':plan['session_id'],'status':'queued','steps':[{**s,'status':'completed' if s['id']=='freeze' else 'waiting'} for s in flow['steps']], 'created_at':now})

    def started(self,turn):
        from .runtime.task_runtime import read_run,_put_run,step
        work=turn.get('work');call_id='chat-call-'+turn['id']
        with self.store.connect() as c:
            row=c.execute('SELECT document FROM creator_model_calls WHERE id=?',(call_id,)).fetchone()
            if not row:raise PlanConflict('会话调用登记不存在')
            call=json.loads(row[0])
            if call.get('native_turn_id') and call['native_turn_id']!=turn['native_turn_id']:raise PlanConflict('实际回合与调用登记不同')
            call.update(status='running',started_at=call.get('started_at') or stamp(),delivery_state='accepted',
                        native_id=turn['native_id'],native_turn_id=turn['native_turn_id'])
            c.execute('UPDATE creator_model_calls SET document=?,updated_at=? WHERE id=?',(packed(call),stamp(),call_id))
            if work:
                c.execute("UPDATE toolbox_jobs SET dispatch_started=1,status='running',started_at=?,turn_id=? WHERE id=?",(stamp(),turn['native_turn_id'],work['version_id']))
                run=read_run(c,work['version_id']);run['model_call_id']=call_id;run['native_id']=turn['native_id'];_put_run(c,run)
                step(c,work['version_id'],'production','running',native_turn_id=turn['native_turn_id'])
        return {'model_call_id':call_id}

    def finished(self,turn):
        from .runtime.task_runtime import finish_call
        with self.store.connect() as c:
            calls=c.execute('SELECT id FROM creator_model_calls WHERE task_id=?',(turn.get('work',{}).get('version_id') if turn.get('work') else turn['id'],)).fetchall()
        for call in calls:finish_call(self.box,call[0],'completed' if turn['status']=='completed' else 'unknown',turn.get('output'),turn.get('error'))
        work=turn.get('work')
        if not work:return {'session_id':turn['session_id'],'model_status':turn['status']}
        jid=work['version_id']
        if turn['status']!='completed':
            with self.store.connect() as c:c.execute("UPDATE toolbox_jobs SET status='uncertain',dispatch_started=1,error=?,reply=? WHERE id=?",(turn.get('error') or '原生会话未取得明确完成回执，请先核对。',turn.get('output',''),jid))
            return {**work,'status':'uncertain','replayed':False}
        from .runtime.production_delivery import record_delivery
        record_delivery(self.box,jid,turn['output'],turn['native_turn_id'],product_roots=[self.root/'outputs'/turn['session_id']/turn['id']/'products'])
        return {**work,'status':self.box.work(work['work_id'])['state']}
