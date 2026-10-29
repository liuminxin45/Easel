"""Observe explicitly bound desktop turns; never infer a work or dispatch AI."""
import hashlib,json,mimetypes,pathlib,re,sqlite3,uuid
from easel_workbench.runtime.desk import THREAD,PROJECT,stamp

ACTIVE={'queued','dispatching','running','uncertain','needs_desktop'}
KINDS={'create','change','discuss','feedback'}

def packed(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(value):return hashlib.sha256(value).hexdigest()

def initialize(c):
    c.execute('''CREATE TABLE IF NOT EXISTS toolbox_direct_turns(
id TEXT PRIMARY KEY,thread TEXT NOT NULL,turn_id TEXT NOT NULL UNIQUE,work_id TEXT NOT NULL,
kind TEXT NOT NULL,candidate_id TEXT,signature TEXT NOT NULL,source_path TEXT NOT NULL,
scan_offset INTEGER NOT NULL,request TEXT NOT NULL,reply TEXT NOT NULL DEFAULT '',
state TEXT NOT NULL,error TEXT,created_at TEXT NOT NULL,finished_at TEXT,
baseline_version TEXT,options TEXT NOT NULL,fingerprint TEXT)''')

def records(path,offset):
    """Only complete JSONL records up to this EOF; retain partial-line cursor."""
    end=path.stat().st_size
    if offset>end:raise ValueError('制作会话记录发生截断，停止同步')
    with path.open('rb') as f:
        f.seek(offset)
        while f.tell()<end:
            start=f.tell();line=f.readline(end-start)
            if not line.endswith(b'\n'):break
            try:value=json.loads(line)
            except (ValueError,UnicodeError):raise ValueError('制作会话记录无法解析')
            yield start,f.tell(),value

def user_text(event):
    p=event.get('payload',{})
    if event.get('type')=='response_item' and p.get('type')=='message' and p.get('role')=='user':
        return '\n'.join(x['text'] for x in p.get('content',[]) if x.get('type') in ('input_text','text') and isinstance(x.get('text'),str))
    return None

def current_turn(path):
    # A bind is made at turn start, not a scan/import of historical conversations.
    start=max(0,path.stat().st_size-16*1024*1024)
    if start:
        with path.open('rb') as f:f.seek(start);f.readline();start=f.tell()
    current=None
    for pos,end,e in records(path,start):
        p=e.get('payload',{})
        if e.get('type')=='event_msg' and p.get('type')=='task_started':
            current={'turn_id':p.get('turn_id'),'offset':pos,'request':[],'active':True}
        if not current:continue
        text=user_text(e)
        if text is not None:current['request'].append(text)
        if e.get('type')=='event_msg' and p.get('type')=='user_message' and not current['request']:
            current['request'].append(p.get('message',''))
        if e.get('type')=='event_msg' and p.get('type') in ('task_complete','turn_aborted') and p.get('turn_id')==current['turn_id']:current['active']=False
    if not current or not current['active'] or not current['turn_id'] or not current['request']:
        raise ValueError('未定位当前制作回合与用户原话；请在新回合开始时关联作品')
    current['request']='\n\n'.join(current['request'])
    return current

def delivered_paths(reply):
    paths=[]
    for raw in re.findall(r'```(?:json)?\s*\n(.*?)\n```',reply,re.S):
        try:value=json.loads(raw)
        except ValueError:continue
        if isinstance(value,dict) and isinstance(value.get('artifacts'),list):
            for item in value['artifacts']:
                if isinstance(item,dict) and isinstance(item.get('path'),str):paths.append(item['path'])
    # Exact delivered file links, never directories or neighboring files.
    paths.extend(re.findall(r'\]\(<?([A-Za-z]:[/\\][^\n)]+?)>?\)',reply))
    return list(dict.fromkeys(str(pathlib.Path(p).resolve()) for p in paths))

class DirectTurns:
    def __init__(self,box,*,roots=None,validate_file=None):
        self.box=box;self.store=box.store;self.root=box.root
        self.roots=[pathlib.Path(p).resolve() for p in (roots or [PROJECT/'内容',PROJECT/'.runtime/贴图待采纳'])]
        self.validate_file=validate_file

    def bind(self,value,path,turn=None):
        from easel_workbench.runtime.toolbox_store import ident
        thread=value.get('thread') or THREAD
        if thread!=THREAD:
            from easel_workbench.runtime.task_runtime import target_for_thread
            verified=target_for_thread(thread)
            if verified is None or verified.resolve()!=pathlib.Path(path).resolve():raise ValueError('直接对话来源与明确会话身份不一致')
        turn=turn or current_turn(path)
        if '[AI_NEWS_DESK_REQUEST:' in turn['request']:
            raise ValueError('工作台发起的回合由原任务接收，不重复关联直接对话')
        kind=value.get('kind');wid=ident(value.get('work_id'));parent=value.get('candidate_id')
        if kind not in KINDS:raise ValueError('直接接续只支持制作、修改、讨论和反馈；采纳继续使用明确范围的决策流程')
        if parent:ident(parent)
        if kind in ('change','feedback') and not parent:raise ValueError('必须明确对应版本')
        options={k:value.get(k,'') for k in ('title','material','format','article_mode')}
        if value.get('creative') is not None:options['creative']=value['creative']
        if kind=='create':
            if not options['title'] or options['format'] not in ('poster','article'):raise ValueError('新作品须给标题与类型')
            if options['article_mode'] not in ('','auto','product'):raise ValueError('文章类型无效')
        jid=str(uuid.uuid5(uuid.NAMESPACE_URL,'toolbox-direct-turn:'+thread+':'+turn['turn_id']))
        signature=packed({'thread':thread,'turn':turn['turn_id'],'work':wid,'kind':kind,'parent':parent,'options':options})
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM toolbox_direct_turns WHERE id=?',(jid,)).fetchone()
            if old:
                if old['signature']!=signature:raise ValueError('本回合已经关联另一作品或版本')
                frozen=c.execute('SELECT file_id,document FROM toolbox_review_inputs WHERE job_id=?',(jid,)).fetchone()
                return {'id':jid,'work_id':wid,'state':old['state'],'already_bound':True,**({'creative_snapshot':json.loads(frozen['document']),'creative_snapshot_file':str(self.box.file(frozen['file_id'])[1])} if frozen else {})}
            work=c.execute('SELECT * FROM toolbox_works WHERE id=?',(wid,)).fetchone()
            if kind=='create' and work:raise ValueError('作品已存在，请明确关联现有版本')
            if kind!='create' and not work:raise ValueError('作品不存在')
            if parent and not c.execute("SELECT 1 FROM toolbox_jobs WHERE id=? AND work_id=? AND kind IN ('create','change') AND status='completed'",(parent,wid)).fetchone():raise ValueError('版本不属于所选作品或尚未完成')
            if c.execute("SELECT 1 FROM toolbox_jobs WHERE work_id=? AND status IN ('queued','dispatching','running','uncertain','needs_desktop')",(wid,)).fetchone():raise ValueError('该作品仍有未结束任务，先核对原操作')
            latest=c.execute("SELECT id FROM toolbox_jobs WHERE work_id=? AND kind IN ('create','change') AND status='completed' ORDER BY created_at DESC,rowid DESC LIMIT 1",(wid,)).fetchone()
            c.execute('INSERT INTO toolbox_direct_turns(id,thread,turn_id,work_id,kind,candidate_id,signature,source_path,scan_offset,request,state,created_at,baseline_version,options) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (jid,thread,turn['turn_id'],wid,kind,parent,signature,str(path.resolve()),turn['offset'],'','watching',stamp(),latest['id'] if latest else None,packed(options)))
            if kind=='create':
                from easel_workbench.runtime.local_operations import reserve_work
                reserve_work(c,wid,options['title'])
            learning=getattr(self.box,'learning',None)
            if learning and kind in ('create','change','discuss'):
                creative={**(options.get('creative') or {})}
                if not creative and parent:
                    from easel_workbench.runtime.content_studio import frozen_options
                    creative=frozen_options(c,parent) or {}
                creative['learning']={**creative.get('learning',{}),'topic':(options['title']+'\n'+(options['material'] or turn.get('request','')))[:2600]}
                from easel_workbench.runtime.work_review import freeze
                freeze(self.box,c,wid,jid,parent,creation=creative,kind_hint=kind,format_hint=options['format'] or None,pending_request=turn.get('request',''),pending_material=options['material'])
                from easel_workbench.runtime.task_runtime import read_run,context_id
                run=read_run(c,jid)
                if run:
                    profile=run['snapshot']['profile']['id']
                    if profile!='oil-pig' and thread==THREAD:raise ValueError('该画像需要独立对话；不能复用油猪大侠的历史会话')
                    for existing_context in c.execute('SELECT document FROM creator_thread_contexts'):
                        context=json.loads(existing_context['document'])
                        if context.get('thread_id')==thread and context.get('profile_id')!=profile:raise ValueError('此对话已属于另一画像，请使用独立对话')
                    context={'id':context_id(run),'profile_id':profile,'work_id':wid,'thread_id':thread,'status':'ready','rollout_path':str(path.resolve()),'created_at':stamp(),'origin':'explicit_direct_binding'}
                    c.execute('INSERT OR REPLACE INTO creator_thread_contexts VALUES(?,?,?)',(context['id'],packed(context),stamp()))
            frozen=c.execute('SELECT file_id,document FROM toolbox_review_inputs WHERE job_id=?',(jid,)).fetchone()
            prepared=json.loads(frozen['document']) if frozen else None
        return {'id':jid,'work_id':wid,'state':'watching','turn_id':turn['turn_id'],**({'creative_snapshot':prepared,'creative_snapshot_file':str(self.box.file(frozen['file_id'])[1])} if prepared else {})}

    def plan(self,row,reply):
        if row['kind'] in ('discuss','feedback'):return []
        paths=delivered_paths(reply)
        if not paths:raise ValueError('未交付明确成品路径，未登记新版本')
        result=[];names=set()
        for raw in paths:
            p=pathlib.Path(raw).resolve()
            if not p.is_file() or not any(p.is_relative_to(r) for r in self.roots):raise ValueError('成品缺失或超出内容目录')
            if self.validate_file:allowed=self.validate_file(p)
            else:
                from easel_workbench.runtime.bridge import allowed_artifact
                allowed=allowed_artifact(p)
            if not allowed:raise ValueError('交付包含非成品文件')
            if p.name in names:raise ValueError('同一交付有重名文件')
            names.add(p.name);data=p.read_bytes();mime=mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
            if p.suffix.lower()=='.gif' and data[:6] not in (b'GIF87a',b'GIF89a'):raise ValueError('GIF附件实际格式不符')
            sha=digest(data);aid=digest((row['id']+'\0'+str(p)+'\0'+sha).encode())
            dest=self.root/'data/artifacts'/aid/p.name
            result.append({'id':aid,'name':p.name,'source':p,'dest':dest,'bytes':data,'sha256':sha,'mime':mime})
        return result

    def complete(self,row,request,reply):
        if not request.strip() or not reply.strip():raise ValueError('缺用户原话或最终答复，未登记')
        if '[AI_NEWS_DESK_REQUEST:' in request:raise ValueError('工作台原任务不能重复接收')
        products=self.plan(row,reply)
        fingerprint=digest(packed({'request':request,'reply':reply,'signature':row['signature'],'products':[(p['name'],p['sha256']) for p in products]}).encode())
        # Copy before exposing the completed row. A crash can leave an unreferenced
        # content-addressed file, never a visible half-delivery or overwritten file.
        for p in products:
            p['dest'].parent.mkdir(parents=True,exist_ok=True)
            if not p['dest'].exists():
                try:
                    with p['dest'].open('xb') as f:f.write(p['bytes'])
                except FileExistsError:pass
            if digest(p['dest'].read_bytes())!=p['sha256']:raise ValueError('附件保存不完整')
        now=stamp();options=json.loads(row['options'])
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE');current=c.execute('SELECT * FROM toolbox_direct_turns WHERE id=?',(row['id'],)).fetchone()
            if current['state']=='completed':
                if current['fingerprint']!=fingerprint:raise ValueError('已登记内容变化，禁止覆盖历史回执')
                return
            if c.execute('SELECT 1 FROM toolbox_jobs WHERE id=?',(row['id'],)).fetchone():raise ValueError('操作标识冲突')
            if c.execute("SELECT 1 FROM toolbox_jobs WHERE work_id=? AND status IN ('queued','dispatching','running','uncertain','needs_desktop')",(row['work_id'],)).fetchone():raise ValueError('作品出现并发任务，停止自动接续')
            latest=c.execute("SELECT id FROM toolbox_jobs WHERE work_id=? AND kind IN ('create','change') AND status='completed' ORDER BY created_at DESC,rowid DESC LIMIT 1",(row['work_id'],)).fetchone()
            if row['kind'] in ('create','change') and (latest['id'] if latest else None)!=row['baseline_version']:raise ValueError('作品已增加其他版本，停止自动接续')
            if row['kind']=='create':
                if c.execute('SELECT 1 FROM toolbox_works WHERE id=?',(row['work_id'],)).fetchone():raise ValueError('新作品标识冲突')
                c.execute('INSERT INTO toolbox_works VALUES(?,?,?,?,?,?)',(row['work_id'],None,options['title'],options['material'] or request,row['created_at'],now))
                c.execute('INSERT INTO toolbox_work_options VALUES(?,?,?)',(row['work_id'],options['format'],options['article_mode'] or 'auto'))
            if row['candidate_id'] and not c.execute("SELECT 1 FROM toolbox_jobs WHERE id=? AND work_id=? AND status='completed'",(row['candidate_id'],row['work_id'])).fetchone():raise ValueError('父版本不匹配')
            c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,candidate_id,signature,status,created_at,finished_at,turn_id,reply) VALUES(?,?,?,?,?,?,?,?,?,?,?)',
                (row['id'],row['work_id'],row['kind'],request,row['candidate_id'],row['signature'],'completed',row['created_at'],now,row['turn_id'],reply))
            from easel_workbench.runtime.local_operations import mark_execution,product_origin,enqueue_delivery
            mark_execution(c,row['id'],'observed','direct_turn')
            prepared=c.execute('SELECT file_id FROM toolbox_review_inputs WHERE job_id=?',(row['id'],)).fetchone()
            if prepared:c.execute('UPDATE toolbox_jobs SET files=? WHERE id=?',(packed([prepared['file_id']]),row['id']))
            for p in products:
                c.execute('INSERT INTO artifacts VALUES(?,?,?,?,?)',(p['id'],row['id'],p['name'],str(p['dest']),p['mime']))
                product_origin(c,p['id'],row['id'],p['source'],p['sha256'])
            if row['kind'] in ('create','change'):
                from easel_workbench.runtime.production_outcome import assess,record
                outcome=assess(self.box,c,{'id':row['id'],'work_id':row['work_id'],'reply':reply})
                record(c,row['id'],outcome)
                if outcome['status']!='completed':c.execute('UPDATE toolbox_jobs SET status=?,error=? WHERE id=?',(outcome['status'],outcome['message'],row['id']))
                elif getattr(self.box,'learning',None):self.box.learning.enqueue_review(c,row['id'])
                enqueue_delivery(c,row['id'])
            c.execute('UPDATE toolbox_works SET updated_at=? WHERE id=?',(now,row['work_id']))
            c.execute("UPDATE toolbox_direct_turns SET state='completed',request=?,reply=?,fingerprint=?,error=NULL,finished_at=? WHERE id=?",(request,reply,fingerprint,now,row['id']))
            from easel_workbench.runtime.task_runtime import step
            step(c,row['id'],'production','completed',executor='observed',turn_id=row['turn_id'],thread_id=row['thread'],new_model_calls=0,
                 notice='接收已发生的直接对话；未再次发送Agent。冻结要求已提供，不以接收结果冒称逐字已读。')
            step(c,row['id'],'capture','completed',artifacts=[{'id':p['id'],'name':p['name'],'sha256':p['sha256']} for p in products])
            if getattr(self.box,'learning',None):self.box.learning.index_database(c)
        # Verify the same records consumed by the existing work page/downloads.
        work=self.box.work(row['work_id'])
        if row['kind'] in ('create','change'):
            version=next(v for v in work['versions'] if v['id']==row['id'])
            if [a['name'] for a in version['artifacts']]!=[p['name'] for p in products]:raise ValueError('工作台附件回读不一致')

    def poll(self):
        with self.store.connect() as c:rows=[dict(r) for r in c.execute("SELECT * FROM toolbox_direct_turns WHERE state='watching' ORDER BY created_at")]
        for row in rows:
            try:self._poll_one(row)
            except Exception as exc:
                # Preserve failed delivery for an explicit retry; never dispatch AI.
                message=str(exc) if isinstance(exc,ValueError) else type(exc).__name__
                with self.store.connect() as c:c.execute("UPDATE toolbox_direct_turns SET state='blocked',error=? WHERE id=? AND state!='completed'",(message,row['id']))
        with self.store.connect() as c:
            return {r['state']:r['n'] for r in c.execute('SELECT state,count(*) AS n FROM toolbox_direct_turns GROUP BY state')}

    def _poll_one(self,row):
        request=row['request'];offset=row['scan_offset']
        for _,end,e in records(pathlib.Path(row['source_path']),offset):
            p=e.get('payload',{});offset=end
            if e.get('type')=='event_msg' and p.get('type')=='task_started' and p.get('turn_id')!=row['turn_id']:raise ValueError('目标回合结束记录缺失，未套用下一回合')
            text=user_text(e)
            if text is not None:request+=('\n\n' if request else '')+text
            # Older runtimes use user_message rather than response_item messages.
            if e.get('type')=='event_msg' and p.get('type')=='user_message' and not request:request=p.get('message','')
            if e.get('type')=='event_msg' and p.get('type')=='turn_aborted' and p.get('turn_id')==row['turn_id']:raise ValueError('制作回合中止，未登记候选')
            if e.get('type')=='event_msg' and p.get('type')=='task_complete' and p.get('turn_id')==row['turn_id']:
                self.complete(row,request,p.get('last_agent_message',''));return
        with self.store.connect() as c:c.execute("UPDATE toolbox_direct_turns SET scan_offset=?,request=? WHERE id=? AND state='watching'",(offset,request,row['id']))

    def status(self,jid):
        with self.store.connect() as c:row=c.execute('SELECT id,work_id,kind,state,error,turn_id FROM toolbox_direct_turns WHERE id=?',(jid,)).fetchone()
        if not row:raise ValueError('接续记录不存在')
        return dict(row)
