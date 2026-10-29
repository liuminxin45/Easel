"""Authenticated version-bound annotations and immutable AI handoff snapshots."""

if __name__ == "__main__" and not __package__:
    import sys as _bootstrap_sys
    from pathlib import Path as _BootstrapPath
    _bootstrap_sys.path.insert(0,str(_BootstrapPath(__file__).resolve().parents[2]))

import argparse,contextlib,hashlib,json,pathlib,re,sys,uuid
from easel_workbench.runtime.production_style import DIMENSIONS,SCOPES,CONTRACT,from_artifacts as style_from_artifacts
from easel_workbench.runtime.desk import stamp

def packed(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(value):return hashlib.sha256(value.encode('utf-8')).hexdigest()

def initialize(c):
    c.executescript('''
CREATE TABLE IF NOT EXISTS toolbox_review_notes(id TEXT PRIMARY KEY,work_id TEXT NOT NULL,candidate_id TEXT NOT NULL,revision INTEGER NOT NULL,document TEXT NOT NULL,deleted INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_review_events(seq INTEGER PRIMARY KEY AUTOINCREMENT,id TEXT UNIQUE NOT NULL,work_id TEXT NOT NULL,candidate_id TEXT NOT NULL,annotation_id TEXT NOT NULL,kind TEXT NOT NULL,document TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_review_ops(id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_review_inputs(job_id TEXT PRIMARY KEY,file_id TEXT NOT NULL,document TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS toolbox_review_candidate ON toolbox_review_notes(work_id,candidate_id);
''')

def candidate(box,c,wid,vid):
    from easel_workbench.runtime.toolbox_store import ident
    row=c.execute("SELECT * FROM toolbox_jobs WHERE id=? AND work_id=? AND kind IN ('create','change') AND status='completed'",(ident(vid),ident(wid))).fetchone()
    if not row:raise ValueError('批注须绑定本作品已完成的明确版本')
    return dict(row)

def source_data(box,c,wid,vid,allow_partial=False):
    if not allow_partial:candidate(box,c,wid,vid)
    else:
        from easel_workbench.runtime.revision_scope import can_continue_partial
        row=c.execute("SELECT * FROM toolbox_jobs WHERE id=? AND work_id=? AND kind IN ('create','change')",(vid,wid)).fetchone()
        if not row or row['status']!='completed' and not can_continue_partial(c,row):raise ValueError('所选修改版本不可接续')
    rows=[dict(row) for row in c.execute('SELECT * FROM artifacts WHERE task_id=? ORDER BY rowid',(vid,))]
    sources={}
    from easel_workbench.runtime.publish_content import from_artifacts
    copy=from_artifacts(rows,box.root/'data/artifacts')
    if copy:sources.update(poster_title=copy['title'],poster_caption=copy['caption'])
    if box.options(wid,c)['format']=='article':
        from easel_workbench.runtime.article_delivery import from_artifacts as article
        result=article(rows,box.root/'data/artifacts',box.options(wid,c)['article_mode'])
        if result['title']:sources['article_title']=result['title']
        if result['body']:sources['article_body']=result['body']
    style=style_from_artifacts(rows,box.root/'data/artifacts')
    authored=c.execute('SELECT document FROM toolbox_text_versions WHERE job_id=?',(vid,)).fetchone()
    if authored:
        raw=json.loads(authored['document'])['text']
        if box.options(wid,c)['format']=='article':sources.update(article_title=raw['title'],article_body=raw['body'])
        else:sources.update(poster_title=raw['title'],poster_caption=raw['body'])
    if style['text']:sources['style_weights']=style['text']
    return {key:{'text':value,'sha256':digest(value)} for key,value in sources.items()},style

def notes(c,wid,vid=None):
    return [json.loads(row['document']) for row in c.execute('SELECT document FROM toolbox_review_notes WHERE work_id=? AND (? IS NULL OR candidate_id=?) AND deleted=0 ORDER BY created_at,rowid',(wid,vid,vid))]

def revision(c,wid,vid):return c.execute('SELECT coalesce(max(seq),0) FROM toolbox_review_events WHERE work_id=? AND candidate_id=?',(wid,vid)).fetchone()[0]

def read(box,wid,vid):
    with box.store.connect() as c:
        c.execute('BEGIN');sources,style=source_data(box,c,wid,vid)
        linked=c.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?',(vid,)).fetchone()
        inputs=json.loads(linked['document']) if linked else None
        expected={note['id'] for note in inputs.get('annotations',[])} if inputs else set()
        responses=style['document'].get('responses' if style['document'].get('schema_version')==2 else 'feedback_responses',[]) if style['ready'] else []
        answered={row.get('annotation_id',row.get('basis_id')) for row in responses if row.get('annotation_id',row.get('basis_id')) in expected}
        events=[dict(row) for row in c.execute('SELECT seq,annotation_id,kind,document,created_at FROM toolbox_review_events WHERE work_id=? AND candidate_id=? ORDER BY seq',(wid,vid))]
        for event in events:event['document']=json.loads(event['document'])
        return {'work_id':wid,'candidate_id':vid,'revision':revision(c,wid,vid),'sources':sources,'style':style,
                'annotations':notes(c,wid,vid),'events':events,'input_annotations':inputs.get('annotations',[]) if inputs else [],
                'input_context':inputs.get('studio_context') if inputs else None,
                'unanswered':sorted(expected-answered),'dimensions':DIMENSIONS,'scopes':SCOPES}

class ReviewConflict(ValueError):pass

def mutate(box,wid,vid,value):
    from easel_workbench.runtime.toolbox_store import ident,text
    operation=ident(value.get('id'));kind=value.get('kind');aid=ident(value.get('annotation_id',operation));signature=packed({'work':wid,'version':vid,'request':value})
    if kind not in ('create','update','delete'):raise ValueError('批注操作无效')
    with box.store.connect() as c:
        c.execute('BEGIN IMMEDIATE');candidate(box,c,wid,vid)
        old=c.execute('SELECT * FROM toolbox_review_ops WHERE id=?',(operation,)).fetchone()
        if old:
            if old['signature']!=signature:raise ValueError('同一批注操作ID不能用于不同内容')
            return json.loads(old['result'])
        existing=c.execute('SELECT * FROM toolbox_review_notes WHERE id=?',(aid,)).fetchone();expected=value.get('revision',0)
        if type(expected) is not int:raise ValueError('批注版本无效')
        if kind=='create':
            if existing or expected!=0:raise ReviewConflict('批注已存在，请核对原操作回执')
            if len(notes(c,wid,vid))>=100:raise ValueError('本版活动批注已达100条，请先整理意见')
            previous=None
        else:
            if not existing or existing['work_id']!=wid or existing['candidate_id']!=vid:raise ValueError('批注不属于此作品版本')
            if existing['revision']!=expected or existing['deleted']:raise ReviewConflict('其它页面已修改或删除此批注，请核对最新内容；输入仍保留')
            previous=json.loads(existing['document'])
        now=stamp()
        if kind=='delete':document={**previous,'revision':expected+1,'deleted':True,'updated_at':now}
        else:
            sources,_=source_data(box,c,wid,vid);field=value.get('field')
            if not isinstance(field,str) or field not in sources or value.get('source_sha256')!=sources[field]['sha256']:raise ReviewConflict('原文版本已变化，请重新打开对应版本后标注')
            quote=text(value.get('quote',''),4000,True);note=text(value.get('note',''),10000,True)
            dimension=value.get('dimension');scope=value.get('scope','work')
            if not isinstance(dimension,str) or dimension not in DIMENSIONS or not isinstance(scope,str) or scope not in SCOPES:raise ValueError('批注维度或适用范围无效')
            # Offsets locate rendered text, not Markdown source bytes. The raw
            # source hash and exact human quote stay available for AI review.
            start=value.get('start');end=value.get('end')
            if type(start) is not int or type(end) is not int or start<0 or end-start!=len(quote) or end>2_000_000:raise ValueError('选中文字的位置无效')
            document={'id':aid,'work_id':wid,'candidate_id':vid,'revision':expected+1,'field':field,'source_sha256':sources[field]['sha256'],
                'quote':quote,'start':start,'end':end,'note':note,'dimension':dimension,'scope':scope,'deleted':False,
                'created_at':previous['created_at'] if previous else now,'updated_at':now}
        c.execute('INSERT OR REPLACE INTO toolbox_review_notes VALUES(?,?,?,?,?,?,?,?)',(aid,wid,vid,document['revision'],packed(document),int(kind=='delete'),document['created_at'],now))
        c.execute('INSERT INTO toolbox_review_events(id,work_id,candidate_id,annotation_id,kind,document,created_at) VALUES(?,?,?,?,?,?,?)',(operation,wid,vid,aid,kind,packed(document),now))
        result={'annotation':document,'revision':revision(c,wid,vid),'saved':True}
        c.execute('INSERT INTO toolbox_review_ops VALUES(?,?,?)',(operation,signature,packed(result)))
        c.execute('UPDATE toolbox_works SET updated_at=? WHERE id=?',(now,wid))
        if getattr(box,'learning',None):box.learning.index_database(c)
    return result

def freeze(box,c,wid,jid,vid=None,expected=None,creation=None,kind_hint=None,format_hint=None,pending_request=None,pending_material=None,origin=None):
    """Attach a frozen data file readable even by the already-running worker."""
    if c.execute('SELECT 1 FROM toolbox_review_inputs WHERE job_id=?',(jid,)).fetchone():return
    current=revision(c,wid,vid) if vid else 0
    if expected is not None and type(expected) is not int:raise ValueError('批注修订无效')
    if expected is not None and expected!=current:raise ReviewConflict('批注已有更新，请核对后重新提交；不会混入未看过的意见')
    current_job=c.execute('SELECT kind FROM toolbox_jobs WHERE id=?',(jid,)).fetchone()
    requested_kind=current_job['kind'] if current_job else kind_hint
    # A revision keeps the creator and pinned capability versions of its
    # actual parent. Switching the drawer's active persona cannot re-own it.
    if vid:
        from easel_workbench.runtime.content_studio import frozen_options
        parent_options=frozen_options(c,vid) or {}
        parent_creator=parent_options.get('creator')
        if parent_creator:
            selected=(creation or {}).get('creator')
            if selected and selected.get('profile_id')!=parent_creator.get('profile_id'):
                raise ReviewConflict('这份作品属于另一创作画像；请在原画像继续修改，或另建作品后明确引用素材。')
            if not selected:
                import copy
                creation={**(creation or {}),'creator':copy.deepcopy(parent_creator)}
                if requested_kind=='discuss' or not creation['creator'].get('skills'):
                    creation['creator'].pop('skills',None)
                    creation['creator'].pop('trial',None)
    annotations=notes(c,wid,vid) if vid else []
    if vid:sources,style=source_data(box,c,wid,vid,allow_partial=True)
    else:sources,style={},None
    if any(note['field'] not in sources or note['source_sha256']!=sources[note['field']]['sha256'] for note in annotations):
        raise ReviewConflict('批注对应的原文已有变化，请重新核对选中段落后再提交')
    format=format_hint or box.options(wid,c)['format']
    evidence=[]
    profile_id=(creation or {}).get('creator',{}).get('profile_id','oil-pig')
    owners={}
    if c.execute("SELECT 1 FROM sqlite_master WHERE name='creator_task_runs'").fetchone():
        for run in c.execute('SELECT work_id,document FROM creator_task_runs ORDER BY rowid'):
            owner=json.loads(run['document']).get('snapshot',{}).get('profile',{}).get('id')
            if owner:owners.setdefault(run['work_id'],owner)
    for row in c.execute('SELECT n.document,n.work_id,coalesce(o.format,\'poster\') AS format FROM toolbox_review_notes n LEFT JOIN toolbox_work_options o ON o.work_id=n.work_id WHERE n.deleted=0 ORDER BY n.updated_at,n.rowid'):
        note=json.loads(row['document'])
        same_profile=owners.get(row['work_id'],'oil-pig')==profile_id
        if same_profile and (note['scope']=='global' or note['scope']=='format' and row['format']==format) or note['scope']=='work' and row['work_id']==wid:
            if note['id'] not in {item['id'] for item in annotations}:evidence.append(note)
    document={'schema_version':1,'work_id':wid,'candidate_id':vid,'revision':current,'annotations':annotations,'sources':sources,
              'previous_style':style,'preference_evidence':evidence,'style_delivery_contract':CONTRACT,
              'instructions':'先读 neo-content 规范/写作要求.md 与文章批注与改稿要求。按本次动作读取完整批注和适用范围；修改另存版本，逐条回应并更新本版六维权重及原因，明确哪些是助手建议。反馈动作只记录，不制作。仅明确通用/同类偏好按范围进入既有规范及类型笔记，保留原话与前后证据，不把单篇意见或沉默当成已确认的通用比例。交付时独立列出风格权重.json 的绝对路径；不把权重放进读者正文或图片。'}
    from easel_workbench.runtime.content_studio import freeze_options
    # Recording a decision/feedback has no dependency on capability discovery
    # or production configuration. Unavailable skills cannot block a decision.
    studio=getattr(box,'studio',None) if origin!='human_edit' and requested_kind in ('create','change','discuss') else None
    if studio:
        context=studio.context(wid,{**(creation or {}),**({'format':format_hint} if format_hint else {})},connection=c,candidate_id=vid,exclude_job_id=jid,task_kind=requested_kind)
        kind_row=c.execute('SELECT kind FROM toolbox_jobs WHERE id=?',(jid,)).fetchone()
        kind=kind_row['kind'] if kind_row else kind_hint
        if kind in ('create','change') and context.get('blockers'):
            raise ValueError('流程有未接入能力，请先调整步骤：'+'；'.join(row['step_id']+'：'+row['reason'] for row in context['blockers']))
        document['studio_context']=context
        creation=context.get('creation_options',creation)
    document['creation_options'],document['creation_instructions']=freeze_options(box,c,wid,vid,creation)
    if kind_hint=='change' or (current_kind:=c.execute('SELECT kind,text FROM toolbox_jobs WHERE id=?',(jid,)).fetchone()) and current_kind['kind']=='change':
        from easel_workbench.runtime.revision_scope import conflicts
        request=c.execute('SELECT text FROM toolbox_jobs WHERE id=?',(jid,)).fetchone()
        problems=conflicts(document['creation_options'],request['text'] if request else pending_request or '') if origin!='human_edit' else []
        if problems:raise ReviewConflict('修改范围待确认：'+'；'.join(item['message'] for item in problems))
    from easel_workbench.runtime.feedback_context import collect as collect_feedback
    document['raw_feedback']=collect_feedback(c,wid,vid,jid)
    if origin:document['origin']=origin
    if origin=='human_edit':
        document['style_delivery_contract']=None
        document['instructions']='人类直接提供文字，本地保存及客观检查；不要求AI设计说明，不自动改回用户文字。'
        document['creation_instructions']='系统保存用户原字文案，不调用AI，不执行生成技能。'
    if document['raw_feedback']['items']:
        document['creation_instructions']+='\n本作品相关原始反馈（尚未提炼，不因批量学习未运行而忽略）：\n'+packed(document['raw_feedback'])
    if studio:
        document['creation_instructions']+='\n同时读取 studio_context 中冻结的定位、读者、标准、流程、来源及适用范围。它是本次提交快照；未配置或未接入能力不能当作已完成。'
    kind_row=c.execute('SELECT kind FROM toolbox_jobs WHERE id=?',(jid,)).fetchone()
    kind=kind_row['kind'] if kind_row else kind_hint
    learning=getattr(box,'learning',None)
    explicit_creator=bool(document['creation_options'].get('creator')) or bool(studio and (pathlib.Path(studio.project)/'.agents/skills/capabilities.json').is_file())
    if learning and studio and kind in ('create','change') and origin!='human_edit' and profile_id=='oil-pig' and not explicit_creator:
        from easel_workbench.runtime.learning_execution import intent_evidence
        learning_context={**context,'_learning_annotations':annotations,'_learning_preference_evidence':evidence,
                          '_learning_intent_evidence':intent_evidence(document['creation_options']),
                          '_learning_raw_feedback':document['raw_feedback']['items']}
        if document['creation_options'].get('recipe'):
            from easel_workbench.runtime.creative_recipes import service as recipes
            chosen=recipes(box).select(document['creation_options']['recipe'],format)
            learning_context['_learning_recipe_assets']=chosen['assets']
        current_job=c.execute('SELECT text FROM toolbox_jobs WHERE id=?',(jid,)).fetchone()
        if current_job and current_job['text'].strip():
            learning_context['_learning_intent_evidence'].append({'id':'request-current','dimension':'style','kind':'current_request','text':current_job['text'],'provenance':{'scope':'request','source_id':jid}})
        elif pending_request:
            learning_context['_learning_intent_evidence'].append({'id':'request-current','dimension':'style','kind':'current_request','text':pending_request,'provenance':{'scope':'direct_request','source_id':jid}})
        if pending_request is not None or pending_material is not None:
            document['direct_context']={'request':pending_request or '','material':pending_material or ''}
            learning_context['_learning_direct_context']={**document['direct_context'],'title':(creation or {}).get('learning',{}).get('topic','').split('\n',1)[0]}
        learned=learning.freeze(c,wid,jid,vid,document['creation_options'],learning_context)
        if learned:
            if learned.get('decision_required'):raise ReviewConflict('本次创作依据存在待确认分歧，请先选择适用方向。')
            from easel_workbench.runtime.production_style import V2_CONTRACT
            document['schema_version']=2;document['learning_snapshot']=learned;document['style_delivery_contract']={**V2_CONTRACT,'expected_basis_ids':[row['id'] for row in learned.get('required_evidence',[])]}
            if document['creation_options'].get('recipe'):
                import copy
                document['style_delivery_contract']=copy.deepcopy(document['style_delivery_contract']);contract=document['style_delivery_contract'];contract['control_mode']='readable_prompt'
                for dimension in contract['dimensions']:dimension['intent']=None
                contract['instructions']='六个设计方面分别说明实际处理与原因，intent为null，不索取隐藏语义模式或百分比。control_mode必须为readable_prompt。每个真实依据ID唯一回应；采用必须指出真实交付位置和SHA。'
            document['instructions']='本轮逐条回应冻结依据，交付设计说明.json及准确成品位置、SHA。声明采用不代表已经核验或用户认可；不要编造百分比。'
            document['creation_instructions']+='\n本次创作依据：\n'+('\n'.join(learned['instructions']) if isinstance(learned.get('instructions'),list) else learned.get('instructions',''))+'\n本轮需唯一回应的依据ID：'+', '.join(row['id'] for row in learned.get('required_evidence',[]))+'。按style_delivery_contract交付设计说明.json。'
    if vid:
        document['candidate_artifacts']=[{'id':row['id'],'name':row['name'],'mime':row['mime'],'path':row['path']} for row in c.execute('SELECT * FROM artifacts WHERE task_id=? ORDER BY rowid',(vid,))
            if pathlib.Path(row['path']).resolve().is_relative_to((box.root/'data/artifacts').resolve())]
    if kind not in ('create','change'):document['creation_instructions']='本次是'+kind+'，只处理当前动作的讨论、反馈或指定范围归档；不生成、改写或重做作品。原文、参数与成品路径仅供核对。'
    if kind in ('create','change','discuss') and origin!='human_edit':
        from easel_workbench.runtime.task_runtime import freeze as freeze_task
        snapshot=freeze_task(c,box,wid,jid,document['creation_options'],task='discuss' if kind=='discuss' else format)
        if snapshot:
            document['creator_snapshot']=snapshot
            if kind in ('create','change'):
                from easel_workbench.runtime.task_runtime import attach_profile_contract
                attach_profile_contract(box,c,document,jid,request_text=pending_request)
            elif kind=='discuss':
                from easel_workbench.runtime.task_runtime import clean_explicit_contract
                clean_explicit_contract(document)
    if kind in ('create','change') and origin!='human_edit' and document['creation_options'].get('recipe') is not None:
        from easel_workbench.runtime.creative_recipes import service as recipes
        recipes(box).freeze(c,wid,jid,document,pending_request,pending_material)
    attach_document(box,c,wid,jid,document)
    if studio and kind in ('create','change'):
        # The accepted snapshot owns this revision's temporary settings. A
        # retry reads the frozen file and must not consume a newer edit.
        studio.consume_round(c,wid,context.get('settings_revision'))

def attach_document(box,c,wid,jid,document):
    """Persist one immutable attachment, including direct-turn preparation."""
    content=packed(document).encode('utf-8');fid='review-'+uuid.uuid4().hex;path=box.root/'data/toolbox/files'/fid/'审阅与风格反馈.json'
    if not getattr(box,'creative_preview',False):
        path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_suffix('.tmp');temporary.write_bytes(content);temporary.replace(path)
    c.execute('INSERT INTO toolbox_files VALUES(?,?,?,?,?,?)',(fid,path.name,str(path),'application/json',len(content),hashlib.sha256(content).hexdigest()))
    job=c.execute('SELECT files FROM toolbox_jobs WHERE id=?',(jid,)).fetchone()
    if job:
        files=json.loads(job['files']);files.append(fid)
        c.execute('UPDATE toolbox_jobs SET files=? WHERE id=?',(packed(files),jid))
    c.execute('INSERT INTO toolbox_review_inputs VALUES(?,?,?)',(jid,fid,packed(document)))

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--work-id',required=True);parser.add_argument('--candidate-id',required=True);args=parser.parse_args()
    from easel_workbench.runtime.toolbox_store import Toolbox
    from easel_workbench.runtime.desk import Store
    print(json.dumps(read(Toolbox(Store()),args.work_id,args.candidate_id),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
