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

from easel_workbench.skill_catalog import ProjectSkillCatalog
from easel_workbench.paths import owned_output_path
from easel_workbench.features.skills.records import packed, key, digest
from easel_workbench.runtime.desk import stamp
from easel_workbench.contracts.values import text


from easel_workbench.contracts.production import PlanConflict
from easel_workbench.features.works.versions import WorkVersions


class ChatBusiness:
    def __init__(self,box,root=None,*,store=None,creator=None,catalog=None,works=None):
        self.box=box
        self.store=store if store is not None else box.store
        self.root=Path(root or box.root).resolve()
        self.catalog=catalog if catalog is not None else ProjectSkillCatalog(self.root)
        self.creator=creator if creator is not None else box.creator
        self.works=works if works is not None else WorkVersions(store=self.store,root=self.root,creator=self.creator,work_store=box)
        from easel_workbench.upstream_skills import UpstreamSkills
        source_root=Path(__file__).resolve().parents[2]
        selector=self.root/'data/active-workbench.json'
        approved=(source_root/'workbench-release.json').is_file() and selector.is_file() and json.loads(selector.read_text(encoding='utf-8'))['release']==source_root.name
        self.upstream=UpstreamSkills(self.root,self.creator,source_root if approved else None)
        self.upstream.environment=lambda:self.chat.settings.environment() if self.chat and hasattr(self.chat,'settings') else self.chat._environment() if self.chat else {}
        self.upstream.configuration=lambda:self.chat.settings.skill_configuration() if self.chat and hasattr(self.chat,'settings') else {'revision':None,'environment':self.upstream.environment()}
        from easel_workbench.features.skills.bundles import SkillBundles
        self.bundles=SkillBundles(root=self.root,store=self.store,upstream=self.upstream)
        self.chat=None
        with self.store.connect() as c:
            from easel_workbench.infrastructure.storage.schema import initialize_chat_plans
            initialize_chat_plans(c)



    def history(self,sid,*,turn_ids=None):
        result=self.chat.history(sid,**({'turn_ids':turn_ids} if turn_ids is not None else {}))
        with self.store.connect() as c:
            for message in result['session']['messages']:
                if message['role']!='assistant':continue
                native=c.execute('SELECT document FROM easel_chat_turns WHERE id=?',(message['turnId'],)).fetchone()
                if native:
                    turn=json.loads(native[0])
                    message['work']=copy.deepcopy(turn.get('work'))
                    message['business_receipt']=copy.deepcopy(turn.get('business_receipt'))
                    if turn.get('work'):message['library_path']='workbench-'+turn['work']['work_id']+'/'+turn['work']['version_id']
                message['output_files']=[{'id':r['id'],'name':r['name'],'mime':r['mime'],'url':'/api/files/'+r['id']} for r in c.execute('SELECT id,name,mime FROM artifacts WHERE task_id=? ORDER BY rowid',(message['turnId'],))]
                from easel_workbench.features.conversations.generated_images import display
                mappings={}
                if c.execute("SELECT 1 FROM sqlite_master WHERE name='easel_generated_image_sources'").fetchone():
                    rows=c.execute('SELECT s.source,s.artifact_id,a.path FROM easel_generated_image_sources s LEFT JOIN artifacts a ON a.id=s.artifact_id AND a.task_id=s.turn_id WHERE s.turn_id=?',(message['turnId'],)).fetchall()
                    mappings={r[0]:r[1] for r in rows if r[2] and Path(r[2]).is_file()}
                    unavailable={r[1] for r in rows if r[0] not in mappings}
                    message['output_files']=[file for file in message['output_files'] if file['id'] not in unavailable]
                message['content']=display(message.get('content',''),mappings)
                if c.execute("SELECT 1 FROM sqlite_master WHERE name='toolbox_product_origins'").fetchone():
                    for file in message['output_files']:
                        origin=c.execute('SELECT source_path FROM toolbox_product_origins WHERE artifact_id=?',(file['id'],)).fetchone()
                        if origin:
                            try:file['source_path']=Path(origin[0]).relative_to(self.root/'outputs').as_posix()
                            except ValueError:pass
                job=c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(message['turnId'],)).fetchone()
                if job:
                    from easel_workbench.runtime.production_retry import recovery
                    from easel_workbench.runtime.production_outcome import read as read_outcome
                    message.update(business_status=job['status'],business_error=job['error'],business_recovery=recovery(job,c,outcome=read_outcome(c,job['id'])))
            for work in result['linked_works']:
                row=c.execute('SELECT title FROM toolbox_works WHERE id=?',(work['work_id'],)).fetchone()
                if row:work['title']=row['title']
        return result

    def _session(self,value):
        sid=key(value.get('sessionId') or value.get('session_id'))
        return self.chat.history(sid)['session']


    def _parent(self,value,c=None):
        return self.works.parent(value,c)

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

    def _attachments(self,value,*,native=False):
        files=value.get('attachments') or []
        if not isinstance(files,list) or len(files)>20:raise ValueError('素材数量无效')
        result=[]
        for item in files:
            if not isinstance(item,dict):raise ValueError('素材引用无效')
            fid=key(item.get('id'));record,path=self.box.file(fid)
            if record.get('name')!=item.get('name'):raise ValueError('素材身份与当前文件不一致')
            raw=path.read_bytes();fingerprint=hashlib.sha256(raw).hexdigest()
            if record.get('sha256') and record['sha256']!=fingerprint:raise PlanConflict('素材字节已变化')
            target=path if native else owned_output_path(self.root,Path('outputs/_sessions/materials')/fingerprint/record['name'])
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
                 'work':work,'authorization':{'production':snapshot['task'] in ('poster','article','image','change','native'),
                                               'discussion_only':snapshot['task']=='discuss','publish':False,'adopt':False}}
        if snapshot['task']=='native':
            bundle=payload['frozen_skill_files'];folder=self.root/'outputs/_sessions/skill-inputs'/snapshot['snapshot_sha256']
            payload['frozen_skill_library']={'root':str(folder),'manifest':str(folder/'native-library.json'),'sha256':digest(packed(bundle))}
            payload['frozen_skill_files']=[file for file in bundle if file['original_path'] in {skill['entry'] for skill in snapshot['skills']}]
            sections.append('按上方 Easel 原生 SKILL 完成本轮任务，不套用工作台贴图或文章交付格式。使用 frozen_skill_files 的版本副本，跨技能依赖和脚本从 frozen_skill_library.root 按原相对路径读取，完整路径与 SHA 见其 manifest。运行脚本时仍以项目根为工作目录读取实际配置。成品写入 output_directory/products 并返回文件链接。未配置的服务先明确缺项；本轮没有发布、修改账号或写入长期偏好的授权，相关动作须另行明确确认。已有画像与账号以工作台记录为准；长期更新先展示候选，通过画像或技能服务确认发布，不直接改写数据库或默认版本。')
        sections.append('## 本轮冻结输入\n'+packed(payload))
        return '\n\n'.join(sections)

    def _review_document(self,snapshot,work,message,parent=None):
        """Compile the existing review contract read-only, without task/file writes."""
        from easel_workbench.runtime.task_runtime import attach_profile_contract
        creative={'schema_version':2,'enabled':True,'creator':{
            'profile_id':snapshot['profile']['id'],'profile_revision':snapshot['profile']['revision'],
            'skills':[{'id':s['id'],'version':s['version']} for s in snapshot['skills']],'trial':bool(snapshot.get('trial'))}}
        for name in ('target','keep_text','text','text_policy','fixed_master'):
            if name in ((parent or {}).get('creation_options') or {}):creative[name]=copy.deepcopy(parent['creation_options'][name])
        from easel_workbench.runtime.revision_scope import conflicts
        if conflicts(creative,message):raise PlanConflict('本轮修改与原字锁定范围冲突，请先核对文字修改范围')
        document={'schema_version':2,'work_id':work['work_id'],'candidate_id':work.get('parent_version_id'),
                  'creation_options':creative,'creator_snapshot':snapshot,
                  'annotations':copy.deepcopy((parent or {}).get('annotations',[])),
                  'raw_feedback':{'items':copy.deepcopy((parent or {}).get('raw_feedback',[]))}}
        # The same contract builder supports a read-only preview: learning is
        # only its persistence sink, while creative_preview prevents asset writes.
        # Copying the complete business DB per plan scales with unrelated history.
        box=copy.copy(self.box);box.creative_preview=True;box.learning=None
        with self.store.connect() as c:
            c.execute('PRAGMA query_only=ON')
            attach_profile_contract(box,c,document,work['version_id'],request_text=message)
        if not document.get('learning_snapshot') or not document.get('style_delivery_contract'):
            raise ValueError('未能冻结独立交付核验合同，未开始制作')
        return document

    def _workspace(self,session=None):
        from easel.harnesses.base import RunRequest
        from easel.harnesses.workspace import harness_instructions
        config=self.chat.execution_settings(session) if session else {'runtime':'codex','models':{},'sandbox':'workspace-write'}
        value=harness_instructions(RunRequest('',self.root,{'EASEL_AGENT_RUNTIME':config['runtime']},model=config['models'].get(config['runtime'],''),sandbox=config['sandbox'],codex_auto_approve=config.get('codex_auto_approve',False)))
        project=self.root/'AGENTS.md'
        if project.is_file():value+='\n\n## 本轮项目约定冻结\n'+project.read_text(encoding='utf-8-sig')
        return value

    def _bundle(self, snapshot, write=False, c=None):
        return self.bundles._bundle(snapshot, write, c)

    @staticmethod
    def _plan_request(value):
        # Upstream persona is an optional display hint; the server session owns
        # identity. Only meaningful production inputs enter the plan signature.
        context=copy.deepcopy(value.get('context') or {});context.pop('plan_token',None)
        return {'message':value.get('message'),'sessionId':value.get('sessionId') or value.get('session_id'),
                'turnId':value.get('turnId') or value.get('turn_id') or value.get('id'),
                'attachments':value.get('attachments') or [],'context':context}



    def prepare(self,value,*,selection=None):
        previous=self.chat.receipt(value)
        if previous:return {'receipt':previous}
        context=copy.deepcopy(value.get('context') or {})
        if selection is None:
            from easel_workbench.features.skills.retirement import SkillFeatureRetired
            if any(field in context for field in ('plan_token','work_id','parent_version_id','trial','version','skill_revision')) or context.get('action_id','native')!='native':
                raise SkillFeatureRetired('legacy-skill-orchestration')
            session=self._session(value)
            if not context.get('article_id') and session.get('source_article_id'):
                context['article_id']=session['source_article_id']
            if context.get('profile_id',session['profile_id'])!=session['profile_id']:
                raise PlanConflict('已有会话保持原画像，请新建会话后切换')
            message=text(value.get('message',''),100000)
            attachments=self._attachments(value,native=True)
            source_materials=None
            if not message.strip() and not attachments:raise ValueError('请先输入目标或添加素材')
            if context.get('skill_id')=='content-production':
                config=self.chat.execution_settings(session)
                if config['runtime']=='api':raise PlanConflict('API 仅聊天模式不能制作，请新建 Agent 对话')
                if config['runtime']=='codex' and config.get('sandbox')=='read-only':raise PlanConflict('此对话使用只读沙箱，请新建允许制作文件的 Agent 对话')
            if context.get('creation') is not None:
                from easel_workbench.features.news_creation import NewsCreation
                if isinstance(context['creation'],dict) and context['creation'].get('intent')=='produce':
                    config=self.chat.execution_settings(session)
                    if config['runtime']=='api':raise PlanConflict('API 仅聊天模式不能制作，请新建 Agent 对话')
                    if config['runtime']=='codex' and config.get('sandbox')=='read-only':raise PlanConflict('此对话使用只读沙箱，请新建允许制作文件的 Agent 对话')
                tid=value.get('turnId') or value.get('turn_id') or value.get('id')
                prepared=NewsCreation(self.box).prepare(context['creation'],session['profile_id'],context.get('article_id'),tid)
                source_materials=prepared
                if prepared['creation']['intent']=='produce':
                    if session.get('runtime')=='api':raise PlanConflict('API 仅聊天模式不能执行本机技能')
                    if context.get('skill_id')!='content-production':raise ValueError('新闻制作须调用内容生产技能')
                elif context.get('skill_id'):raise ValueError('讨论不启动制作技能')
                message=prepared['input_text']
                # Material identities and selected bytes are server-owned, never
                # supplied as arbitrary paths by an HTTP caller.
                for item in prepared['material_manifest']['files']:
                    attachments.append({**item,'path':str(self.root/item['path'])})
            elif context.get('article_id') or context.get('skill_id')=='content-production':
                from easel_workbench.features.news_creation import NewsCreation
                tid=value.get('turnId') or value.get('turn_id') or value.get('id')
                prepared=NewsCreation(self.box).prepare_native(message,session['profile_id'],context.get('article_id'),tid,
                    content_production=context.get('skill_id')=='content-production')
                source_materials=prepared
                message=prepared['input_text']
                for item in prepared['material_manifest']['files']:
                    attachments.append({**item,'path':str(self.root/item['path'])})
            if source_materials and self.chat.execution_settings(session)['runtime']=='api':
                from easel_workbench.features.news_creation import NewsCreation
                message+=NewsCreation(self.box).api_source_text(source_materials)
            if context.get('skill_id'):
                if session.get('runtime')=='api':raise PlanConflict('API 仅聊天模式不能执行本机技能')
                from easel_workbench.runtime.native_skills import service
                message=service(self.box,self.chat).prepare_message(context['skill_id'],message,session['profile_id'])
            else:
                from easel_workbench.runtime.native_skills import service
                message=service(self.box,self.chat).prepare_chat_message(message,session['profile_id'])
            if attachments:message+='\n\n## 本轮附件\n'+packed(attachments)
            summary = None
            if source_materials and context.get('creation'):
                from easel_workbench.features.news_creation import NewsCreation
                summary = NewsCreation(self.box).display_summary(source_materials, context.get('skill_id'))
            return {'snapshot':None,'actual_prompt':message,'work':None,'frozen_instructions':self._workspace(session),
                    **({'display_summary':summary} if summary is not None else {})}
        from easel_workbench.features.skills.retirement import SkillFeatureRetired
        raise SkillFeatureRetired('legacy-skill-orchestration')

    def accept(self,c,turn):
        """Join version registration to the native chat acceptance transaction."""
        if not turn.get('snapshot'):return
        if turn['snapshot']['task']=='native':self.upstream.accept(c,turn['snapshot'])
        self._bundle(turn['snapshot'],True,c)
        if (turn.get('work') or {}).get('internal_correction'):
            from easel_workbench.native_corrections import accept as accept_correction
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
            from easel_workbench.native_corrections import supersede_queued_user
            supersede_queued_user(c,turn['session_id'])
            self._accept_work(c,plan)
        else:
            submitted=json.loads(turn['actual_prompt'].rsplit('## 本轮冻结输入\n',1)[1])
            if self._freeze_attachments({'attachments':turn['attachments']})!=submitted['attachments']:raise PlanConflict('素材与本轮冻结讨论输入不同')
            if self._news_source(turn,c)!=submitted['source_article']:raise PlanConflict('资讯来源与本轮冻结讨论输入不同')
            if self._parent(turn,c)!=submitted.get('reference_work'):raise PlanConflict('讨论所指版本依据已有变化，未发送')
            from easel_workbench.native_corrections import supersede_queued_user
            supersede_queued_user(c,turn['session_id'])
        task_id=turn['work']['version_id'] if turn.get('work') else turn['id']
        call={'schema_version':1,'id':'chat-call-'+turn['id'],'task_id':task_id,'task':turn['snapshot']['task'],
              'snapshot':turn['snapshot'],'prompt':turn['actual_prompt'],
              'input':{'message':turn['message'],'session_id':turn['session_id']},
              'input_sha256':turn['actual_prompt_sha256'],'status':'submitting','created_at':stamp(),
              'submission_started_at':stamp(),'delivery_state':'not_started',
              'active_skills':[{k:s[k] for k in ('id','name','version','sha256')} for s in turn['snapshot']['skills'] if s.get('execution_role')=='active'],
              'reserved_skills':[{k:s[k] for k in ('id','name','version','sha256')} for s in turn['snapshot']['skills'] if s.get('execution_role')=='reserved_independent'],
              'runner':turn['runner'],'execution_settings':turn.get('execution_settings')}
        c.execute('INSERT INTO creator_model_calls VALUES(?,?,?,?)',(call['id'],task_id,packed(call),stamp()))
        if turn.get('work'):
            wid=turn['work']['work_id']
            turn['user_input_fence']={'review_seq':c.execute('SELECT coalesce(max(seq),0) FROM toolbox_review_events WHERE work_id=?',(wid,)).fetchone()[0],
                                      'draft_rowid':c.execute('SELECT coalesce(max(rowid),0) FROM toolbox_article_draft_ops WHERE work_id=?',(wid,)).fetchone()[0]}

    def _accept_work(self,c,plan):
        return self.works.accept(c,plan)

    def started(self,turn):
        if not turn.get('snapshot'):return {'session_id':turn['session_id']}
        work=turn.get('work');call_id='chat-call-'+turn['id']
        with self.store.connect() as c:
            row=c.execute('SELECT document FROM creator_model_calls WHERE id=?',(call_id,)).fetchone()
            if not row:raise PlanConflict('会话调用登记不存在')
            call=json.loads(row[0])
            if call.get('native_turn_id') and call['native_turn_id']!=turn.get('native_turn_id'):raise PlanConflict('实际回合与调用登记不同')
            execution_id=(turn.get('execution_identity') or {}).get('id') or turn.get('native_turn_id')
            call.update(status='running',started_at=call.get('started_at') or stamp(),delivery_state='accepted',
                        native_id=turn['native_id'],native_turn_id=turn.get('native_turn_id'),execution_identity=turn.get('execution_identity'))
            c.execute('UPDATE creator_model_calls SET document=?,updated_at=? WHERE id=?',(packed(call),stamp(),call_id))
            if work:
                self.works.started(c,turn,call_id,execution_id)
        return {'model_call_id':call_id}

    def finished(self,turn):
        from easel_workbench.features.conversations.generated_images import receive
        receive(self.root,self.store,turn)
        if not turn.get('snapshot'):
            # Ordinary native runs can write files without creating private work
            # rows. Wake the existing metadata index, including partial outputs.
            if turn.get('status') in ('completed','stopped','failed','unknown'):
                try:
                    native=getattr(self.box,'_native_api',None)
                    if native is not None:native.library.invalidate()
                    else:
                        from easel_workbench.features.works.library_index import request_refresh
                        request_refresh(self.root)
                except Exception as error:
                    from easel_workbench.runtime.server_logging import exception
                    exception('library_refresh_signal_failed',error,phase='native_finish')
            return {'session_id':turn['session_id'],'model_status':turn['status']}
        from easel_workbench.runtime.task_runtime import finish_call
        with self.store.connect() as c:
            calls=c.execute('SELECT id FROM creator_model_calls WHERE task_id=?',(turn.get('work',{}).get('version_id') if turn.get('work') else turn['id'],)).fetchall()
        for call in calls:finish_call(self.box,call[0],'completed' if turn['status']=='completed' else 'unknown',turn.get('output'),turn.get('error'))
        work=turn.get('work')
        if not work:
            if turn['snapshot']['task']=='native':self.upstream.receive(turn)
            return {'session_id':turn['session_id'],'model_status':turn['status']}
        return self.works.finished(turn)
