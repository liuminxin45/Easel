"""Version receipts for explicitly selected Oil Pig native skill runs."""
import json
import re
from pathlib import Path
from easel_workbench.runtime.desk import stamp

FORMATS={'oil-pig-poster':'poster','oil-pig-article':'article'}
MARKER='\n\n## 工作台本轮审阅绑定\n'

def latest(business,sid):
    with business.store.connect() as c:
        row=c.execute("SELECT json_extract(document,'$.business_receipt.review_candidate'),json_extract(document,'$.status'),json_extract(document,'$.hook_status') FROM easel_chat_turns WHERE session_id=? AND json_extract(document,'$.local_review') IS NULL AND (json_extract(document,'$.context.skill_id') IN ('oil-pig-poster','oil-pig-article') OR instr(json_extract(document,'$.frozen_instructions'),?)>0) ORDER BY rowid DESC LIMIT 1",(sid,MARKER)).fetchone()
        if row and row[0] and row[1]=='completed' and row[2]=='completed':
            candidate=json.loads(row[0])
            if candidate.get('status')=='completed':return candidate
    return None

def modifying(message):
    if '?' in message or '？' in message:return False
    if re.match(r'^(?:图片|图)可以[，,]\s*配文(?:再改|改短|修改)',message.strip()):return True
    return bool(re.search(r'^(?:请)?(?:修改这版|改一下这版|继续修改|再改|配文再改|正文再改|标题再改)',message.strip()))

def binding(business,value):
    context=value.get('context') or {};skill=context.get('skill_id')
    sid=value.get('sessionId') or value.get('session_id');parent=latest(business,sid) if modifying(value.get('message','')) else None
    if parent and skill not in FORMATS:skill=parent['skill_id']
    if skill not in FORMATS:return None
    tid=value.get('turnId') or value.get('turn_id') or value.get('id')
    sid=value.get('sessionId') or value.get('session_id')
    if not tid or not sid:return None
    from easel_workbench.features.conversations.receipts import identity
    tid,sid=identity(tid),identity(sid)
    session=business._session(value)
    with business.store.connect() as c:profile=business.box.creator._profile(c,session['profile_id'])
    if parent and parent['format']!=FORMATS[skill]:raise ValueError('修改须使用原作品格式对应的技能')
    references=[]
    if parent:
        import hashlib
        with business.store.connect() as c:
            for row in c.execute('SELECT name,path FROM artifacts WHERE task_id=?',(parent['version_id'],)):
                path=Path(row['path']);references.append({'name':row['name'],'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    return {'schema':1,'skill_id':skill,'format':FORMATS[skill],'session_id':sid,'version_id':tid,
            'work_id':parent['work_id'] if parent else 'native-'+tid,'parent_version_id':parent['version_id'] if parent else None,
            'profile_id':profile['id'],'profile_revision':profile['revision'],
            'parent_files':references,
            'product_directory':str(business.root/'outputs'/sid/tid/'products')}

def instructions(frame):
    if not frame:return ''
    return MARKER+json.dumps(frame,ensure_ascii=False,sort_keys=True)+'\n成品只保存到以上 product_directory，最终回复明确列出真实成品文件链接。parent_files 是准确父版，只读参考，按本轮原话修改，其他范围保留；新版本须交付完整成品，不能覆盖父版。保留来源和过程文件，不能把过程文件当成成品。'

def read_binding(turn):
    raw=turn.get('frozen_instructions','')
    if MARKER not in raw:return None
    try:frame=json.JSONDecoder().raw_decode(raw.rsplit(MARKER,1)[1])[0]
    except ValueError:return None
    if frame.get('version_id')!=turn['id'] or frame.get('session_id')!=turn['session_id'] or FORMATS.get(frame.get('skill_id'))!=frame.get('format'):raise ValueError('原生作品回执与本轮绑定不同')
    return frame

def receive(business,turn):
    frame=read_binding(turn)
    if not frame or turn.get('status')!='completed':return None
    execution=turn.get('execution_identity') or {}
    if not turn.get('native_turn_id') and execution.get('kind') not in ('jsonrpc_request','cli_result_sha256'):
        raise ValueError('制作完成尚未绑定准确原生回执')
    import hashlib
    for item in frame.get('parent_files',[]):
        if hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()!=item['sha256']:raise ValueError('准确父版原件发生变化，未登记修改版')
    from easel_workbench.paths import owned_output_path
    directory=owned_output_path(business.root,Path('outputs')/turn['session_id']/turn['id']/'products')
    if str(directory)!=frame['product_directory']:raise ValueError('本轮产物目录已变化')
    from easel_workbench.runtime.bridge import capture_artifacts,delivery_paths,allowed_artifact
    identity=hashlib.sha256((turn['actual_prompt_sha256']+'\0'+turn.get('output','')).encode()).hexdigest()
    key='native-review:'+turn['id']
    with business.store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT value FROM toolbox_meta WHERE key=?',(key,)).fetchone()
        if old:
            saved=json.loads(old[0])
            if saved['identity']!=identity:raise ValueError('已登记版本的原始回执不能变化')
            for item in saved.get('files',saved.get('sources',[])):
                if hashlib.sha256(Path(item['path']).read_bytes()).hexdigest()!=item['sha256']:raise ValueError('已登记版本原件已变化')
            if saved.get('receipt'):return saved['receipt']
        else:
            sources=[{'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()} for path in delivery_paths(turn.get('output','')) if allowed_artifact(path,[directory])]
            if not sources:return None
            saved={'identity':identity,'sources':sources}
            c.execute('INSERT INTO toolbox_meta(key,value) VALUES(?,?)',(key,json.dumps(saved,ensure_ascii=False)))
    capture_artifacts(business.store,turn['id'],turn.get('output',''),root=business.root,product_roots=[directory])
    now=stamp();wid=frame['work_id'];tid=turn['id']
    with business.store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM artifacts WHERE task_id=?',(tid,)).fetchone():return None
        title=next((s.strip()[:120] for s in turn['message'].splitlines() if s.strip()),'素材创作')
        c.execute('INSERT OR IGNORE INTO toolbox_works VALUES(?,?,?,?,?,?)',(wid,None,title,turn['message'],now,now))
        c.execute('INSERT OR IGNORE INTO toolbox_work_options VALUES(?,?,?)',(wid,frame['format'],'auto'))
        if frame.get('profile_id'):
            business.box.creator.bind_work(c,wid,{'profile_id':frame['profile_id'],'profile_revision':frame['profile_revision']},allow_historical=True)
        from easel_workbench.runtime.local_operations import reserve_work
        reserve_work(c,wid,title)
        old=c.execute('SELECT work_id,signature FROM toolbox_jobs WHERE id=?',(tid,)).fetchone()
        signature='native-review:'+turn['actual_prompt_sha256']
        if old and (old['work_id']!=wid or old['signature']!=signature):raise ValueError('本轮版本已有不同登记')
        c.execute('INSERT OR IGNORE INTO toolbox_jobs(id,work_id,kind,text,candidate_id,files,scope,signature,status,created_at,finished_at,turn_id,reply) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                  (tid,wid,'change' if frame.get('parent_version_id') else 'create',turn['message'],frame.get('parent_version_id'),'[]','[]',signature,'completed',turn['created_at'],now,turn.get('native_turn_id'),turn['output']))
        from easel_workbench.runtime.production_outcome import assess,record
        outcome=assess(business.box,c,dict(c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(tid,)).fetchone()))
        record(c,tid,outcome)
        c.execute('UPDATE toolbox_jobs SET status=? WHERE id=?',(outcome['status'],tid))
        scopes=outcome.get('available_scopes',[])
        whole=all(scope in scopes for scope in ('images','copy')) if frame['format']=='poster' else 'article' in scopes and bool(c.execute("SELECT 1 FROM artifacts WHERE task_id=? AND mime='text/html'",(tid,)).fetchone())
        receipt={**frame,'status':outcome['status'],'available_scopes':scopes,'whole_ready':whole}
        files=[{'path':row['path'],'sha256':hashlib.sha256(Path(row['path']).read_bytes()).hexdigest()} for row in c.execute('SELECT path FROM artifacts WHERE task_id=?',(tid,))]
        c.execute('UPDATE toolbox_meta SET value=? WHERE key=?',(json.dumps({'identity':identity,'files':files,'receipt':receipt},ensure_ascii=False),key))
    return receipt

def decision(business,value):
    if value.get('attachments'):return None
    context=value.get('context') or {}
    if context.get('creation') or context.get('skill_id') and context['skill_id'] not in FORMATS:return None
    message=value.get('message','').strip().rstrip('。！!')
    positive={'采纳':None,'采纳这版':None,'全部采纳':None,'这版全部采纳':None,'只采纳图片':['images'],'仅采纳图片':['images'],
              '只采纳配文':['copy'],'仅采纳配文':['copy'],'只采纳正文':['article'],'仅采纳正文':['article']}
    reject=re.fullmatch(r'(?:不采纳(?:这版)?|这版不采纳)(?:[，,:：](.+))?',message,re.S)
    ambiguous=message in ('可以','不错','好的','看起来不错','采纳上一版','上一版采纳','修改上一版','请修改上一版')
    if message not in positive and not reject and not ambiguous:return None
    sid=value.get('sessionId') or value.get('session_id');target=latest(business,sid)
    if not target:return None
    if context.get('skill_id') and context['skill_id']!=target['skill_id']:return None
    if ambiguous:return {'reply':'请明确要操作哪一版，以及是采纳整版、仅图片、配文或正文，还是继续讨论修改；我还没有记录采纳。'}
    return {'target':target,'kind':'reject' if reject else 'accept','scope':[] if reject else positive[message],'text':value['message']}

def apply_decision(business,command,tid):
    if 'reply' in command:return command['reply'],None
    target=command['target'];wid,vid=target['work_id'],target['version_id'];operation='review-'+tid
    with business.store.connect() as c:
        old=c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(operation,)).fetchone()
        if old:
            if old['work_id']!=wid or old['candidate_id']!=vid or old['kind']!=command['kind'] or old['text']!=command['text']:raise ValueError('决定回执与原始输入不一致')
            return ('已记录此版本的采纳；归档进度以内容库实际回执为准。' if command['kind']=='accept' else '已记录此版本不采纳，原文件保留。'),{'operation_id':operation,'work_id':wid,'version_id':vid,'kind':command['kind']}
    payload={'id':operation,'kind':command['kind'],'candidate_id':vid,'text':command['text'],'files':[],'scope':command['scope'] or []}
    if command['kind']=='accept':
        from easel_workbench.runtime.completion_service import service
        completion=service(business.box);options=completion.options(wid,vid)
        scope=command['scope'] if command['scope'] is not None else options['required_scopes']
        if command['scope'] is None and not target.get('whole_ready',False) or not scope or any(s not in options['available_scopes'] for s in scope):
            return '这版尚未完整交付所选范围。你可以补齐后再采纳，或明确只采纳已有的图片、配文或正文；尚未记录采纳。',None
        plan={'mode':'archive','targets':[],'manual_publications':[]}
        preview=completion.preview(wid,vid,{'scope':scope,'completion':plan})
        payload.update(scope=scope,completion={**plan,'plan_hash':preview['plan_hash']})
    try:result=business.box.action(wid,payload,origin='native_review')
    except ValueError as error:return '尚未记录本次决定：'+str(error)+'。可以继续讨论或修改；原文件保留。',None
    return ('已记录此版本的采纳；归档进度以内容库实际回执为准。' if command['kind']=='accept' else '已记录此版本不采纳，原文件保留。'),{'operation_id':operation,'work_id':wid,'version_id':vid,'kind':command['kind'],'receipt':result}
