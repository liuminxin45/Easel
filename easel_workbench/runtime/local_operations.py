"""Deterministic work decisions, project records and recoverable local I/O.

This module never starts a model, chooses a creative rule or publishes content.
Legacy job rows remain the chronological ledger; execution ownership is separate.
"""
from __future__ import annotations
import contextlib,copy,datetime as dt,hashlib,json,os,pathlib,re,shutil,subprocess,uuid
from easel_workbench.runtime.desk import stamp

LOCAL_KINDS={'accept','reject','feedback','archive'}
MODES={'local','agent','observed'}
class LocalConflict(ValueError):pass
WAITING={'queued','waiting_binding','waiting_production'}
TERMINAL={'completed','failed','needs_attention','superseded'}

def pack(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def sha(raw):return hashlib.sha256(raw).hexdigest()
def enabled(box,name):
 try:return json.loads((pathlib.Path(box.root)/'data/automation-enabled.json').read_text(encoding='utf-8-sig')).get(name) is True
 except (OSError,ValueError,AttributeError):return False
def ident(value):
 if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',value):raise ValueError('操作标识无效')
 return value

def initialize(c):
 c.executescript('''CREATE TABLE IF NOT EXISTS toolbox_execution(job_id TEXT PRIMARY KEY,mode TEXT NOT NULL,origin TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_local_tasks(id TEXT PRIMARY KEY,work_id TEXT NOT NULL,job_id TEXT NOT NULL,kind TEXT NOT NULL,status TEXT NOT NULL,document TEXT NOT NULL,revision INTEGER NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS toolbox_local_work ON toolbox_local_tasks(work_id,created_at);
CREATE TABLE IF NOT EXISTS toolbox_project_bindings(work_id TEXT PRIMARY KEY,relative_path TEXT NOT NULL,revision INTEGER NOT NULL,evidence TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_local_ops(operation_id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_product_origins(artifact_id TEXT PRIMARY KEY,job_id TEXT NOT NULL,source_path TEXT NOT NULL,sha256 TEXT NOT NULL,role TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_local_owned(path TEXT PRIMARY KEY,sha256 TEXT NOT NULL,work_id TEXT NOT NULL,job_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_local_delivery_inputs(job_id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_local_record_inputs(job_id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS toolbox_local_regions(path TEXT NOT NULL,work_id TEXT NOT NULL,sha256 TEXT NOT NULL,PRIMARY KEY(path,work_id));
''')

def execution_mode(c,job_id):
 row=c.execute('SELECT mode FROM toolbox_execution WHERE job_id=?',(job_id,)).fetchone()
 return row['mode'] if row else 'agent'

def mark_execution(c,job_id,mode,origin='web'):
 ident(job_id)
 if mode not in MODES:raise ValueError('执行归属无效')
 row=c.execute('SELECT mode,origin FROM toolbox_execution WHERE job_id=?',(job_id,)).fetchone()
 if row and (row['mode']!=mode or row['origin']!=origin):raise ValueError('执行归属已经冻结')
 c.execute('INSERT OR IGNORE INTO toolbox_execution VALUES(?,?,?,?)',(job_id,mode,origin,stamp()))

def is_agent(c,job_or_id):return execution_mode(c,job_or_id if isinstance(job_or_id,str) else job_or_id['id'])=='agent'

def product_origin(c,artifact_id,job_id,path,digest,role='product'):
 """Only call from a verified artifact receiver, never from a browser path."""
 ident(artifact_id);ident(job_id)
 record=(artifact_id,job_id,str(pathlib.Path(path).resolve()),digest,role)
 old=c.execute('SELECT * FROM toolbox_product_origins WHERE artifact_id=?',(artifact_id,)).fetchone()
 if old and tuple(old)!=record:raise ValueError('原始交付位置已变化')
 c.execute('INSERT OR IGNORE INTO toolbox_product_origins VALUES(?,?,?,?,?)',record)

def _task(c,job,kind):
 key='local-'+sha((kind+'\0'+job['id']).encode())[:40];now=stamp()
 document={'id':key,'work_id':job['work_id'],'job_id':job['id'],'kind':kind,'execution_mode':'local','status':'queued','result':None,'error':None,'attempts':0,'created_at':now,'updated_at':now,'revision':1}
 c.execute('INSERT OR IGNORE INTO toolbox_local_tasks VALUES(?,?,?,?,?,?,?,?,?)',(key,job['work_id'],job['id'],kind,'queued',pack(document),1,now,now))
 return key

def queue_action(c,job):
 job=dict(job);mark_execution(c,job['id'],'local', 'migration' if job.get('_migrated') else job.get('_origin','web'))
 history=[dict(r) for r in c.execute('SELECT * FROM toolbox_jobs WHERE work_id=? ORDER BY rowid',(job['work_id'],))]
 fileids=sorted(set(fid for row in history for fid in json.loads(row['files'])))
 original={'schema_version':1,'work':dict(c.execute('SELECT * FROM toolbox_works WHERE id=?',(job['work_id'],)).fetchone()),'history':history,'attachments':[dict(c.execute('SELECT * FROM toolbox_files WHERE id=?',(fid,)).fetchone()) for fid in fileids],'annotations':[dict(r) for r in c.execute('SELECT * FROM toolbox_review_events WHERE work_id=? ORDER BY seq',(job['work_id'],))],'coverage':'工作台可取得的完整原话及过程；不补造未取得提示词或目视检查'}
 c.execute('INSERT OR IGNORE INTO toolbox_local_record_inputs VALUES(?,?)',(job['id'],pack(original)))
 kinds=['project_archive'] if job['kind']=='archive' else ['record']+(['project_archive'] if job['kind']=='accept' else ['cleanup'] if job['kind']=='reject' else [])
 return [_task(c,job,kind) for kind in kinds]

def enqueue_delivery(c,job_or_id):
 job=dict(c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(job_or_id,)).fetchone()) if isinstance(job_or_id,str) else dict(job_or_id)
 option=c.execute('SELECT format FROM toolbox_work_options WHERE work_id=?',(job['work_id'],)).fetchone()
 if job['kind'] in ('create','change') and job['status']=='completed' and option and option['format']=='article':
  cutoff=c.execute('SELECT rowid FROM toolbox_jobs WHERE id=?',(job['id'],)).fetchone()[0]
  history=[dict(r) for r in c.execute('SELECT * FROM toolbox_jobs WHERE work_id=? AND rowid<=? ORDER BY rowid',(job['work_id'],cutoff))]
  ids=[row['id'] for row in history];inputs=[];reviews=[]
  for key in ids:
   row=c.execute('SELECT * FROM toolbox_article_inputs WHERE job_id=?',(key,)).fetchone()
   if row:inputs.append(dict(row))
   row=c.execute('SELECT * FROM toolbox_review_inputs WHERE job_id=?',(key,)).fetchone()
   if row:reviews.append(dict(row))
  files=sorted(set(fid for row in history for fid in json.loads(row['files'])))
  refs=[dict(c.execute('SELECT * FROM toolbox_files WHERE id=?',(fid,)).fetchone()) for fid in files]
  original={'schema_version':1,'work':dict(c.execute('SELECT * FROM toolbox_works WHERE id=?',(job['work_id'],)).fetchone()),'version_id':job['id'],'history':history,'article_inputs':inputs,'review_inputs':reviews,'annotations':[dict(r) for r in c.execute('SELECT * FROM toolbox_review_events WHERE work_id=? ORDER BY seq',(job['work_id'],))],'attachments':refs,'status':'待评审','coverage':'仅工作台可取得原始过程；不补造缺失来源、提示词或目视检查'}
  c.execute('INSERT OR IGNORE INTO toolbox_local_delivery_inputs VALUES(?,?)',(job['id'],pack(original)))
  return _task(c,job,'article_archive')
 return None

def _safe(base,relative):
 base=pathlib.Path(base).resolve();value=pathlib.PurePosixPath(str(relative).replace('\\','/'))
 if value.is_absolute() or not value.parts or any(p in ('.','..') or ':' in p for p in value.parts):raise ValueError('项目相对路径无效')
 target=base.joinpath(*value.parts)
 for part in (target,*target.parents):
  if part==base:break
  if part.is_symlink() or getattr(part,'is_junction',lambda:False)():raise ValueError('不写入链接目录或文件')
 if not target.resolve().is_relative_to(base):raise ValueError('文件超出允许目录')
 return target

def _item_path(project,relative):
 value=pathlib.PurePosixPath(relative)
 if len(value.parts)!=2 or value.parts[0]!='内容':raise ValueError('请选择内容项目中的单个标题目录')
 return _safe(project,relative)

def reserve_work(c,wid,title):
 """Reserve metadata only for a newly created work, without creating folders."""
 ident(wid)
 existing=c.execute('SELECT * FROM toolbox_project_bindings WHERE work_id=?',(wid,)).fetchone()
 if existing:return dict(existing)
 name=re.sub(r'[\\/:*?"<>|\x00-\x1f]','＿',str(title)).strip('. ')[:120] or '未命名内容'
 if re.fullmatch(r'(?i)(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?',name):name='内容-'+name
 relative='内容/'+name;used={r[0] for r in c.execute('SELECT relative_path FROM toolbox_project_bindings')}
 if relative in used:relative+='-'+dt.datetime.now().strftime('%Y%m%d')+'-'+wid[:8]
 now=stamp();evidence={'kind':'new_work_reservation','title_at_creation':str(title),'work_id':wid}
 c.execute('INSERT INTO toolbox_project_bindings VALUES(?,?,?,?,?,?)',(wid,relative,1,pack(evidence),now,now))
 return {'work_id':wid,'relative_path':relative,'revision':1,'evidence':pack(evidence),'created_at':now,'updated_at':now}

def migrate_unsent(c):
 """Caller must hold the deployment writer fence; never run in constructors."""
 if not c.in_transaction:raise ValueError('迁移必须在安全切换写锁内进行')
 from easel_workbench.runtime.production_retry import recovery,read
 changed=[]
 for raw in list(c.execute("SELECT * FROM toolbox_jobs WHERE kind IN ('accept','reject','feedback','archive') AND status='queued' ORDER BY rowid")):
  job=dict(raw);state=read(c,job['id']) or {};r=recovery(job,c)
  if job['dispatch_started'] or job.get('queue_id') or job.get('turn_id') or not r or r['send_state']!='not_sent' or state.get('phase') in ('sending','submitted','unknown','uncertain','dispatching'):continue
  old=c.execute('SELECT mode FROM toolbox_execution WHERE job_id=?',(job['id'],)).fetchone()
  if old and old['mode']=='observed':continue
  if old:c.execute('DELETE FROM toolbox_execution WHERE job_id=?',(job['id'],))
  job['_migrated']=True;queue_action(c,job)
  c.execute("UPDATE toolbox_jobs SET status='completed',finished_at=?,reply='系统已记录；后续归档与同步由本地任务处理。',error=NULL WHERE id=?",(stamp(),job['id']))
  changed.append(job['id'])
 return {'converted':changed,'count':len(changed),'resubmitted_AI':0}

def _write_once(path,raw):
 path.parent.mkdir(parents=True,exist_ok=True)
 if path.exists():
  if not path.is_file() or path.read_bytes()!=raw:raise ValueError('目标已有不同字节，未覆盖：'+path.name)
  return
 temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
 try:
  temporary.write_bytes(raw)
  if path.exists():
   if path.read_bytes()!=raw:raise ValueError('目标在保存期间变化')
  else:os.replace(temporary,path)
 finally:temporary.unlink(missing_ok=True)

class LocalOperations:
 def __init__(self,box,project=None,git_runner=None):
  self.box=box;self.store=box.store;self.root=pathlib.Path(box.root).resolve()
  self.project=pathlib.Path(project or getattr(getattr(box,'studio',None),'project',self.root/'content-project')).resolve()
  self.state=self.root/'data/local-operations';self.git_runner=git_runner
  with self.store.connect() as c:initialize(c)

 def _binding(self,c,wid):
  row=c.execute('SELECT * FROM toolbox_project_bindings WHERE work_id=?',(wid,)).fetchone()
  if not row:return None
  return {**dict(row),'evidence':json.loads(row['evidence'])}

 def _save_binding(self,c,wid,relative,evidence):
  _item_path(self.project,relative);old=self._binding(c,wid);now=stamp();revision=(old['revision'] if old else 0)+1
  c.execute('INSERT OR REPLACE INTO toolbox_project_bindings VALUES(?,?,?,?,?,?)',(wid,relative,revision,pack(evidence),old['created_at'] if old else now,now))
  return self._binding(c,wid)

 def _infer(self,c,wid):
  current=self._binding(c,wid);candidates={}
  if current and current['evidence']['kind']!='new_work_reservation':return current
  for row in c.execute('SELECT document FROM toolbox_completions WHERE work_id=?',(wid,)):
   item=json.loads(row['document']);proof=item.get('project_archive',{})
   if proof.get('status')=='verified':
    try:
     p=pathlib.Path(proof['path']).resolve();parts=p.relative_to(self.project/'内容').parts
     if len(parts)>=3:candidates['内容/'+parts[0]]={'kind':'verified_project_archive','decision_id':item['decision_id']}
    except (ValueError,KeyError):pass
  for row in c.execute('SELECT o.* FROM toolbox_product_origins o JOIN toolbox_jobs j ON j.id=o.job_id WHERE j.work_id=?',(wid,)):
   try:
    p=pathlib.Path(row['source_path']);parts=p.resolve().relative_to(self.project/'内容').parts
    if len(parts)>=2 and p.is_file() and sha(p.read_bytes())==row['sha256']:candidates['内容/'+parts[0]]={'kind':'verified_delivery_origin','job_id':row['job_id'],'sha256':row['sha256']}
   except (ValueError,OSError):pass
  folder=self.project/'内容'
  if folder.is_dir():
   for item in folder.iterdir():
    if not item.is_dir() or item.is_symlink() or getattr(item,'is_junction',lambda:False)():continue
    catalog=item/'内容档案.md'
    if not catalog.is_file():continue
    body=catalog.read_text(encoding='utf-8-sig',errors='replace')
    if not re.search(r'(?<![A-Za-z0-9_-])'+re.escape(wid)+r'(?![A-Za-z0-9_-])',body):continue
    matched=[]
    for artifact in c.execute('SELECT a.*,j.id AS job_id FROM artifacts a JOIN toolbox_jobs j ON j.id=a.task_id WHERE j.work_id=?',(wid,)):
     if artifact['job_id'] not in body:continue
     original=pathlib.Path(artifact['path'])
     if not original.is_file():continue
     digest=sha(original.read_bytes())
     for target in item.rglob(artifact['name']):
      if target.is_file() and not target.is_symlink() and sha(target.read_bytes())==digest:matched.append(artifact['job_id']);break
    if matched:candidates['内容/'+item.name]={'kind':'exact_work_version_and_bytes','versions':sorted(set(matched))}
  if len(candidates)==1:
   relative,evidence=next(iter(candidates.items()))
   if not current or relative!=current['relative_path']:return self._save_binding(c,wid,relative,evidence)
   return current
  if len(candidates)>1:return None
  if current:
   target=_item_path(self.project,current['relative_path'])
   if target.exists():
    # A pre-existing independent article must not be appropriated by a title.
    if not target.is_dir():return None
    catalog=target/'内容档案.md';body=catalog.read_text(encoding='utf-8-sig',errors='replace') if catalog.is_file() else ''
    if wid not in body:return None
   else:return self._save_binding(c,wid,current['relative_path'],{'kind':'allocated_new_work','reservation':current['evidence']})
   return current
  return None

 def read(self,wid):
  ident(wid)
  with self.store.connect() as c:
   if not c.execute('SELECT 1 FROM toolbox_works WHERE id=?',(wid,)).fetchone():raise ValueError('作品不存在')
   binding=self._binding(c,wid);tasks=[json.loads(r['document']) for r in c.execute('SELECT document FROM toolbox_local_tasks WHERE work_id=? ORDER BY rowid',(wid,))]
  waiting=any(t['status']=='waiting_binding' for t in tasks)
  public_binding={**(binding or {}),'path':binding['relative_path'] if binding else None,'status':'needs_selection' if waiting or not binding else 'reserved' if binding['evidence']['kind']=='new_work_reservation' else 'verified','revision':binding['revision'] if binding else 0,'candidates':[]}
  if waiting:
   folder=self.project/'内容'
   public_binding['candidates']=[{'path':'内容/'+p.name,'label':p.name} for p in sorted(folder.iterdir()) if p.is_dir() and not p.is_symlink() and not getattr(p,'is_junction',lambda:False)()] if folder.is_dir() else []
  return {'work_id':wid,'execution_mode':'local','binding':public_binding,'tasks':tasks,'browser_cleanup':{'status':'manual','message':'本地决定不等待关闭浏览器；没有独立安全接口时请手动关闭。'}}

 def bind(self,value):
  wid=ident(value.get('work_id'));op=ident(value.get('operation_id') or value.get('id'));relative=value.get('path');signature=pack(value)
  if not isinstance(relative,str):raise ValueError('请选择准确的项目标题目录')
  target=_item_path(self.project,relative)
  if target.exists() and not target.is_dir():raise ValueError('请选择标题目录，不能关联普通文件')
  with self.store.connect() as c:
   c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM toolbox_local_ops WHERE operation_id=?',(op,)).fetchone()
   if old:
    if old['signature']!=signature:raise ValueError('同一操作不能绑定不同目录')
    return json.loads(old['result'])
   if not c.execute('SELECT 1 FROM toolbox_works WHERE id=?',(wid,)).fetchone():raise ValueError('作品不存在')
   current=self._binding(c,wid)
   if type(value.get('expected_revision')) is not int or value['expected_revision']!=(current['revision'] if current else 0):raise LocalConflict('项目关联已有变化，请重新核对')
   result={'binding':self._save_binding(c,wid,relative,{'kind':'explicit_owner_binding','operation_id':op,'existed':target.exists()})}
   c.execute('INSERT INTO toolbox_local_ops VALUES(?,?,?)',(op,signature,pack(result)))
   for row in c.execute("SELECT id,document FROM toolbox_local_tasks WHERE work_id=? AND status='waiting_binding'",(wid,)):
    task=json.loads(row['document']);self._put(c,task,status='queued',error=None)
  return result

 def retry(self,value):
  op=ident(value.get('operation_id') or value.get('id'));key=ident(value.get('task_id'));signature=pack(value)
  with self.store.connect() as c:
   c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM toolbox_local_ops WHERE operation_id=?',(op,)).fetchone()
   if old:
    if old['signature']!=signature:raise ValueError('同一恢复操作不能用于不同任务')
    return json.loads(old['result'])
   row=c.execute('SELECT document FROM toolbox_local_tasks WHERE id=?',(key,)).fetchone()
   if not row:raise ValueError('本地任务不存在')
   task=json.loads(row['document'])
   if value.get('work_id') and task['work_id']!=value['work_id']:raise ValueError('任务不属于此作品')
   if task['status'] in ('failed','needs_attention','waiting_binding','waiting_production'):task=self._put(c,task,status='queued',error=None)
   result={'task':task,'AI_requests_created':0};c.execute('INSERT INTO toolbox_local_ops VALUES(?,?,?)',(op,signature,pack(result)))
  return result

 def _put(self,c,task,**fields):
  if all(task.get(key)==value for key,value in fields.items()):return task
  task={**copy.deepcopy(task),**fields,'updated_at':stamp(),'revision':task.get('revision',0)+1}
  c.execute('UPDATE toolbox_local_tasks SET status=?,document=?,revision=?,updated_at=? WHERE id=?',(task['status'],pack(task),task['revision'],task['updated_at'],task['id']))
  return task

 def _busy(self,c,wid):
  for row in c.execute("SELECT * FROM toolbox_jobs WHERE work_id=? AND status IN ('dispatching','running','uncertain','needs_desktop','parked')",(wid,)):
   if is_agent(c,row['id']):return True
  return bool(c.execute("SELECT 1 FROM toolbox_direct_turns WHERE work_id=? AND state='watching'",(wid,)).fetchone())

 def process_one(self):
  if not enabled(self.box,'local_io'):return None
  from easel_workbench.runtime.feedback_ledger import locked
  try:
   with locked(self.state/'worker.lock',timeout=.2):return self._process_one()
  except TimeoutError:return None

 def _process_one(self):
  from easel_workbench.runtime.feedback_ledger import locked
  with self.store.connect() as c:
   c.execute('BEGIN IMMEDIATE')
   # A previous local process can stop mid-copy. All local byte writes are
   # write-once and Git has its own durable intent; resuming does not send AI.
   rows=list(c.execute("SELECT document FROM toolbox_local_tasks WHERE status IN ('queued','waiting_binding','waiting_production','running') ORDER BY CASE kind WHEN 'record' THEN 0 WHEN 'project_archive' THEN 1 WHEN 'article_archive' THEN 2 WHEN 'cleanup' THEN 3 ELSE 4 END,rowid"))
   task=None
   for row in rows:
    item=json.loads(row['document'])
    if self._busy(c,item['work_id']):self._put(c,item,status='waiting_production',error='等待同作品正在执行的制作回合结束');continue
    if item['kind']!='sync':
     binding=self._infer(c,item['work_id'])
     if not binding:self._put(c,item,status='waiting_binding',error='项目归档待关联；决定和反馈已经保存');continue
    task=self._put(c,item,status='running',error=None,attempts=item.get('attempts',0)+1);break
   if task is None:return None
  try:
   if task['kind']=='sync':result=self._sync(task)
   else:
    with self.store.connect() as c:binding=self._binding(c,task['work_id'])
    target=_item_path(self.project,binding['relative_path'])
    with locked(self.state/('work-'+task['work_id']+'.lock'),timeout=.5):
     result=self._record(task,target)
     if task['kind']=='project_archive':result=self._archive(task,target,result)
     elif task['kind']=='article_archive':result=self._article(task,target,result)
     elif task['kind']=='cleanup':
      cleanup=self._cleanup(task,target);result={**result,**cleanup,'files':{**result['files'],**cleanup.get('files',{})}}
   status=result.get('task_status','completed')
   with self.store.connect() as c:
    c.execute('BEGIN IMMEDIATE');task=self._put(c,task,status=status,result=result,error=result.get('error'))
    if task['kind']=='sync':self._sync_status(c,task,result.get('sync') or {'status':status})
    if task['kind']!='sync' and result.get('files'):
     for relative,digest in result['files'].items():c.execute('INSERT OR REPLACE INTO toolbox_local_owned VALUES(?,?,?,?)',(relative,digest,task['work_id'],task['job_id']))
    if task['kind'] not in ('sync','record') and result.get('files'):
     key=_task(c,{'id':task['id'],'work_id':task['work_id']},'sync');queued=json.loads(c.execute('SELECT document FROM toolbox_local_tasks WHERE id=?',(key,)).fetchone()['document']);self._put(c,queued,payload={'source_task':task['id'],'files':result['files'],'unsafe_before':result.get('unsafe_before',[])})
   return task
  except Exception as error:
   with self.store.connect() as c:
    task=self._put(c,task,status='failed',error=str(error)[:700])
    if task['kind']=='project_archive':self._completion_status(c,task,'failed',error=str(error)[:700])
    elif task['kind']=='sync':self._sync_status(c,task,{'status':'needs_attention','error':str(error)[:700]})
    if task['kind'] in ('cleanup','project_archive'):
     # A failed copy/cleanup must not prevent syncing the already preserved
     # decision and raw feedback. This is a distinct scope and durable task.
     prior=c.execute("SELECT document FROM toolbox_local_tasks WHERE job_id=? AND kind='record' AND status='completed'",(task['job_id'],)).fetchone()
     previous=json.loads(prior['document']) if prior else None
     if previous and (previous.get('result') or {}).get('files'):
      outcome=previous['result'];key=_task(c,{'id':previous['id'],'work_id':task['work_id']},'sync');queued=json.loads(c.execute('SELECT document FROM toolbox_local_tasks WHERE id=?',(key,)).fetchone()['document']);self._put(c,queued,payload={'source_task':previous['id'],'files':outcome['files'],'unsafe_before':outcome.get('unsafe_before',[])})
   return task

 def _git(self,*args,check=True,raw=False):
  if self.git_runner:return self.git_runner(list(args),check=check,raw=raw)
  environment={**os.environ,'GIT_TERMINAL_PROMPT':'0','GCM_INTERACTIVE':'Never'}
  result=subprocess.run(['git','-c','core.quotepath=false',*args],cwd=self.project,env=environment,capture_output=True,timeout=120)
  if check and result.returncode:raise ValueError('Git操作未完成：'+str(args[0]))
  return result if raw else result.stdout.decode('utf-8',errors='replace').strip()

 def _before(self,paths):
  result=[]
  if not (self.project/'.git').exists() and not self.git_runner:return result
  for path in paths:
   relative=path.relative_to(self.project).as_posix()
   if path.exists() and self._git('status','--porcelain','--',relative):
    with self.store.connect() as c:owned=c.execute('SELECT sha256 FROM toolbox_local_owned WHERE path=?',(relative,)).fetchone()
    if not owned or sha(path.read_bytes())!=owned['sha256']:result.append(relative)
  return result

 def _managed(self,path,wid,body,c):
  begin=('<!-- WORKBENCH:'+wid+':START -->').encode();end=('<!-- WORKBENCH:'+wid+':END -->').encode();raw=path.read_bytes() if path.exists() else ('# '+path.stem+'\n').encode()
  block=begin+b'\n'+body.encode()+b'\n'+end
  if raw.count(begin)>1 or raw.count(end)>1 or raw.count(begin)!=raw.count(end):raise ValueError('自动管理区边界不明确，保留原文')
  if begin in raw:
   start=raw.index(begin);finish=raw.index(end,start)+len(end);previous=raw[start:finish]
   tracked=c.execute('SELECT sha256 FROM toolbox_local_regions WHERE path=? AND work_id=?',(path.relative_to(self.project).as_posix(),wid)).fetchone()
   if previous!=block and (not tracked or sha(previous)!=tracked['sha256']):raise ValueError('自动管理区已有人工修改，保留原文，请核对后恢复')
   new=raw[:start]+block+raw[finish:]
  else:new=raw+(b'' if raw.endswith(b'\n') else b'\n')+b'\n'+block+b'\n'
  path.parent.mkdir(parents=True,exist_ok=True)
  temporary=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp');temporary.write_bytes(new);os.replace(temporary,path)
  c.execute('INSERT OR REPLACE INTO toolbox_local_regions VALUES(?,?,?)',(path.relative_to(self.project).as_posix(),wid,sha(block)))

 def _record(self,task,target):
  with self.store.connect() as c:
   job=dict(c.execute('SELECT rowid AS sequence,* FROM toolbox_jobs WHERE id=?',(task['job_id'],)).fetchone());latest=c.execute("SELECT rowid AS sequence,* FROM toolbox_jobs WHERE work_id=? AND kind IN ('accept','reject') ORDER BY rowid DESC LIMIT 1",(task['work_id'],)).fetchone();latest=dict(latest) if latest else None
   work=dict(c.execute('SELECT * FROM toolbox_works WHERE id=?',(task['work_id'],)).fetchone());frozen=c.execute('SELECT document FROM toolbox_local_record_inputs WHERE job_id=?',(job['id'],)).fetchone()
   original=json.loads(frozen['document']) if frozen else None
   refs=original['attachments'] if original else [dict(c.execute('SELECT * FROM toolbox_files WHERE id=?',(fid,)).fetchone()) for fid in json.loads(job['files'])]
  event=target/'反馈/工作台'/ (job['id']+'.json');text=target/'反馈/工作台'/(job['id']+'.md');managed=[target/name for name in ('内容档案.md','进度.md','反馈.md')];unsafe=self._before([event,text,*managed,target/'决定状态.json',target/'工作台状态'/('作品-'+work['id']+'.json')]);files=[]
  with self.store.connect() as c:
   for previous in c.execute("SELECT document FROM toolbox_local_tasks WHERE job_id=? AND kind='record' AND status='completed'",(job['id'],)):
    unsafe.extend((json.loads(previous['document']).get('result') or {}).get('unsafe_before',[]))
  unsafe=sorted(set(unsafe))
  document={'schema_version':1,'source':'workbench_original','actor':'system' if job['kind']=='archive' else 'user','work_id':work['id'],'version_id':job['candidate_id'] or job['id'],'operation_id':job['id'],'kind':job['kind'],'sequence':job['sequence'],'text':job['text'],'scope':json.loads(job['scope']),'created_at':job['created_at'],'attachments':[{key:r[key] for key in ('id','name','mime','sha256','size')} for r in refs]}
  self._protect_secret(event.name,pack(document).encode());_write_once(event,pack(document).encode());_write_once(text,('# 工作台原始记录\n\n操作：'+job['kind']+'\n\n版本：'+str(job['candidate_id'] or job['id'])+'\n\n## 用户原话\n\n'+job['text']+'\n').encode());files.extend([event,text])
  if original:
   process=target/'过程/工作台'/(job['id']+'-完整过程.json');raw=pack(original).encode();self._protect_secret(process.name,raw);_write_once(process,raw);files.append(process)
  for row in refs:
   path=pathlib.Path(row['path']).resolve();destination=target/'反馈/原始附件'/(row['id']+'-'+pathlib.Path(row['name']).name)
   if not path.is_relative_to(self.root/'data') or not path.is_file():raise ValueError('原始附件不可用')
   raw=path.read_bytes()
   if sha(raw)!=row['sha256']:raise ValueError('原始附件字节变化')
   self._protect_secret(row['name'],raw);_write_once(destination,raw);files.append(destination)
  # Always derive current state again; an older local queue receipt cannot
  # reinstate its own decision over a later user action.
  with self.store.connect() as c:
   c.execute('BEGIN IMMEDIATE');latest=c.execute("SELECT rowid AS sequence,* FROM toolbox_jobs WHERE work_id=? AND kind IN ('accept','reject') ORDER BY rowid DESC LIMIT 1",(task['work_id'],)).fetchone();latest=dict(latest) if latest else None
   status='采纳' if latest and latest['kind']=='accept' else '不采纳' if latest else '待评审';version=(latest or {}).get('candidate_id') or job['candidate_id'] or job['id']
   versions=[r['id'] for r in c.execute("SELECT id FROM toolbox_jobs WHERE work_id=? AND kind IN ('create','change') ORDER BY rowid",(work['id'],))]
   body='工作台作品ID：'+work['id']+'\n\n版本ID：'+str(version)+'\n\n全部版本ID：'+', '.join(versions)+'\n\n当前明确决定：'+status+'\n\n'+('决定操作：'+latest['id']+'\n\n' if latest else '')+'完整原话见 [反馈记录](反馈/工作台/)；真实完成清单为产物中对应版本的 `完成清单.json`。\n\n覆盖范围：工作台已取得的原始材料；缺失提示词、来源和目视记录不补造。'
   for path in managed:self._managed(path,work['id'],body,c);files.append(path)
   if latest:
    state=target/'工作台状态'/('作品-'+work['id']+'.json');state.parent.mkdir(parents=True,exist_ok=True);raw=pack({'id':latest['id'],'work_id':work['id'],'version_id':latest['candidate_id'],'sequence':latest['sequence'],'decision':'accepted' if latest['kind']=='accept' else 'rejected','text':latest['text'],'scope':json.loads(latest['scope']),'at':latest['created_at']}).encode();temp=state.with_suffix('.tmp');temp.write_bytes(raw);os.replace(temp,state);files.append(state)
    # Preserve older helper status bytes before maintaining its compatibility
    # pointer. Publication is factual metadata and never follows rejection.
    relative=target.relative_to(self.project).as_posix();owners=c.execute('SELECT count(*) FROM toolbox_project_bindings WHERE relative_path=?',(relative,)).fetchone()[0]
    if owners==1:
     pointer=target/'决定状态.json';previous=json.loads(pointer.read_text(encoding='utf-8-sig')) if pointer.exists() else {}
     if previous.get('work_id') in (None,work['id']):
      if pointer.exists():
       old=pointer.read_bytes();backup=target/'反馈/决定记录'/('工作台接续前-'+sha(old)+'.json');_write_once(backup,old);files.append(backup)
      decision=json.loads(raw);decision['version']=latest['candidate_id'];decision['publication']=previous.get('publication','not_inferred');decision['record']='反馈/工作台/'+latest['id']+'.md'
      record=target/decision['record'];decision['sha256']=sha(record.read_bytes()) if record.is_file() else None
      temporary=pointer.with_suffix('.tmp');temporary.write_bytes(pack(decision).encode());os.replace(temporary,pointer);files.append(pointer)
  return {'files':self._file_map(files),'unsafe_before':unsafe,'recorded':True,'browser_cleanup':'manual'}

 def _protect_secret(self,name,raw):
  from easel_workbench.runtime.learning_service import SECRET_NAME,SECRET_TEXT
  if SECRET_NAME.search(name) or pathlib.Path(name).suffix.lower() in ('.pem','.key','.p12'):raise ValueError('疑似凭据不进入项目归档')
  if pathlib.Path(name).suffix.lower() in ('.md','.json','.txt','.html','.csv') and SECRET_TEXT.search(raw.decode('utf-8',errors='replace')):raise ValueError('材料含疑似凭据，请核对后归档')

 def _file_map(self,files):return {p.relative_to(self.project).as_posix():sha(p.read_bytes()) for p in dict.fromkeys(files)}

 def _completion_status(self,c,task,status,**fields):
  from easel_workbench.runtime.completion_service import service
  completion=service(self.box);job=dict(c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(task['job_id'],)).fetchone());decision=completion.archive_decision_id(job);item=completion._get(c,decision)
  if item:item['project_archive']={'status':status,'local_task_id':task['id'],**fields};completion._put(c,item)

 def _copy_manifest(self,source,target):
  raw=(source/'完成清单.json').read_bytes();manifest=json.loads(raw);files=[]
  for entry in manifest['files']:
   original=_safe(source,entry['path']);destination=_safe(target,entry['path']);data=original.read_bytes()
   if sha(data)!=entry['sha256']:raise ValueError('冻结快照字节不符')
   self._protect_secret(original.name,data);_write_once(destination,data);files.append(destination)
  _write_once(target/'完成清单.json',raw);files.append(target/'完成清单.json')
  for entry in manifest['files']:
   if sha(_safe(target,entry['path']).read_bytes())!=entry['sha256']:raise ValueError('归档副本不完整')
  return files,sha(raw)

 def _archive(self,task,target,result):
  from easel_workbench.runtime.completion_service import service
  completion=service(self.box)
  with self.store.connect() as c:job=dict(c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(task['job_id'],)).fetchone())
  decision=completion.archive_decision_id(job);completion.process(decision)
  with self.store.connect() as c:item=completion._get(c,decision)
  if not item or item['archive']['status']!='verified':raise ValueError('工作台完成快照尚未核验')
  source=pathlib.Path(item['archive']['path']);destination=target/'产物'/('工作台-'+decision);files,digest=self._copy_manifest(source,destination)
  receipt=pack({'completion_archive':{'schema_version':1,'decision_id':decision,'directory':str(destination),'manifest_sha256':digest}})
  verified=completion.verify_project_archive(decision,receipt)
  if verified['project_archive']['status']!='verified':raise ValueError(verified['project_archive'].get('error','项目归档核验失败'))
  return {**result,'files':{**result['files'],**self._file_map(files)},'project_archive':verified['project_archive']}

 def _article(self,task,target,result):
  source=self.root/'data/local-deliveries'/task['job_id'];source.mkdir(parents=True,exist_ok=True);entries=[]
  with self.store.connect() as c:
   artifacts=[dict(r) for r in c.execute('SELECT * FROM artifacts WHERE task_id=? ORDER BY rowid',(task['job_id'],))]
   frozen=c.execute('SELECT document FROM toolbox_local_delivery_inputs WHERE job_id=?',(task['job_id'],)).fetchone()
   if not frozen:raise ValueError('未取得文章交付时冻结的原始过程，不猜测补造')
   original=json.loads(frozen['document'])
  if not artifacts:raise ValueError('文章尚无实际交付文件')
  for index,row in enumerate(artifacts):
   path=pathlib.Path(row['path']).resolve()
   if not path.is_relative_to(self.root/'data/artifacts') or not path.is_file():raise ValueError('文章交付文件不可用')
   raw=path.read_bytes();self._protect_secret(row['name'],raw);relative='成品/'+str(index+1).zfill(2)+'-'+path.name;_write_once(source/relative,raw);entries.append({'path':relative,'sha256':sha(raw),'size':len(raw)})
  for row in original['attachments']:
   path=pathlib.Path(row['path']).resolve()
   if not path.is_relative_to(self.root/'data') or not path.is_file():raise ValueError('文章原始附件不可用')
   raw=path.read_bytes()
   if sha(raw)!=row['sha256']:raise ValueError('文章原始附件字节变化')
   relative='原始附件/'+row['id']+'-'+pathlib.Path(row['name']).name;self._protect_secret(row['name'],raw);_write_once(source/relative,raw);entries.append({'path':relative,'sha256':sha(raw),'size':len(raw)})
  raw=pack(original).encode();_write_once(source/'完整过程.json',raw);entries.append({'path':'完整过程.json','sha256':sha(raw),'size':len(raw)})
  _write_once(source/'完成清单.json',pack({'schema_version':1,'kind':'article_delivery','work_id':task['work_id'],'version_id':task['job_id'],'files':entries}).encode())
  files,digest=self._copy_manifest(source,target/'产物'/('文章-工作台-'+task['job_id']))
  return {**result,'files':{**result['files'],**self._file_map(files)},'article_archive':{'status':'verified','manifest_sha256':digest,'publication':'not_inferred'}}

 def _cleanup(self,task,target):
  with self.store.connect() as c:
   job=dict(c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(task['job_id'],)).fetchone());vid=job['candidate_id']
   if self.box.options(task['work_id'],c)['format']!='poster':return {'cleanup':{'status':'preserved','reason':'文章沿用交付归档，不清理其历史成品'}}
   if c.execute("SELECT 1 FROM toolbox_jobs WHERE candidate_id=? AND kind='accept'",(vid,)).fetchone():return {'cleanup':{'status':'preserved','reason':'该版本曾被采纳，历史材料不删除'}}
   if c.execute("SELECT 1 FROM toolbox_jobs WHERE candidate_id=? AND kind IN ('change','discuss') AND status IN ('queued','running','dispatching','uncertain','needs_desktop','parked')",(vid,)).fetchone():return {'task_status':'waiting_production','cleanup':{'status':'waiting','reason':'仍有修改引用此版本'}}
   origins=[dict(r) for r in c.execute('SELECT * FROM toolbox_product_origins WHERE job_id=?',(vid,))]
  temporary=(self.project/'.runtime/贴图待采纳').resolve();bundles={}
  for row in origins:
   path=pathlib.Path(row['source_path']).resolve()
   if not path.is_relative_to(temporary):continue
   parts=path.relative_to(temporary).parts
   if len(parts)<3:continue
   bundle=_safe(temporary,'/'.join(parts[:2]));bundles.setdefault(bundle,[]).append(row)
  if len(bundles)!=1:return {'task_status':'needs_attention','error':'没有唯一且准确绑定的临时候选；未删除文件','cleanup':{'status':'not_verified','reason':'没有唯一且准确绑定的临时候选；未删除文件'}}
  bundle,known=next(iter(bundles.items()))
  if not bundle.exists():return {'cleanup':{'status':'already_removed'}}
  expected={pathlib.Path(row['source_path']).resolve():row['sha256'] for row in known};actual={}
  for path in bundle.rglob('*'):
   if path.is_symlink() or getattr(path,'is_junction',lambda:False)():raise ValueError('临时候选包含链接，不清理')
   if path.is_file():actual[path.resolve()]=sha(path.read_bytes())
  if set(actual)!=set(expected) or any(actual[p]!=digest for p,digest in expected.items()):return {'task_status':'needs_attention','error':'候选中有未分类或已变化文件；未删除','cleanup':{'status':'needs_review','reason':'候选中有未分类或已变化文件；未删除'}}
  preserved=[]
  for row in known:
   original=pathlib.Path(row['source_path']).resolve()
   if row['role'] in ('process','evidence','check') or original.suffix.lower() in ('.json','.md','.txt') and re.search('设计说明|检查|核查|创作方案|原始提示词|生成记录',original.name):
    raw=original.read_bytes();self._protect_secret(original.name,raw);destination=_safe(target/'过程/未采纳候选'/vid,original.relative_to(bundle).as_posix());_write_once(destination,raw);preserved.append(destination)
  # Only the exact verified version below the explicitly named temporary root.
  if bundle==temporary or not bundle.resolve().is_relative_to(temporary) or len(bundle.relative_to(temporary).parts)!=2:raise ValueError('临时清理目录越界')
  shutil.rmtree(bundle)
  return {'files':self._file_map(preserved),'cleanup':{'status':'removed','relative_path':bundle.relative_to(self.project).as_posix(),'files':len(actual),'preserved_process_files':len(preserved)}}

 def _sync(self,task):
  """Exact-path Git sync with a durable commit/push intent, never a model."""
  from easel_workbench.runtime.feedback_ledger import locked
  payload=task.get('payload') or {};files=payload.get('files') or {}
  with self.store.connect() as c:
   source=c.execute('SELECT job_id FROM toolbox_local_tasks WHERE id=?',(payload.get('source_task'),)).fetchone();job=c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(source['job_id'],)).fetchone() if source else None
  if not job or job['kind'] not in ('accept','reject','archive'):return {'sync':{'status':'not_authorized','message':'本次记录未包含自动Git同步授权'}}
  if not (self.project/'.git').exists() and not self.git_runner:return {'task_status':'needs_attention','sync':{'status':'not_configured','message':'项目没有Git元数据，未提交或推送'}}
  if payload.get('unsafe_before'):return {'task_status':'needs_attention','sync':{'status':'blocked','message':'相关文件含操作前未提交内容，已保留；同步待核对'}}
  with locked(self.state/'git.lock',timeout=.5):
   for relative,digest in files.items():
    path=_safe(self.project,relative)
    if not relative.startswith('内容/') or not path.is_file() or sha(path.read_bytes())!=digest:raise ValueError('同步文件已变化，未覆盖或提交')
   journal=self.state/'git'/ (task['id']+'.json');journal.parent.mkdir(parents=True,exist_ok=True);intent=json.loads(journal.read_text(encoding='utf-8')) if journal.exists() else None
   remote=self._git('remote','get-url','--push','origin');branch=self._git('branch','--show-current')
   if not re.fullmatch(r'(?:https://github\.com/|git@github\.com:)[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?',remote) or not branch:raise ValueError('远端或分支未经本流程核对')
   current=self._git('rev-parse','HEAD');answer=self._git('ls-remote','origin','refs/heads/'+branch);remote_head=answer.split()[0] if answer else None
   marker='[workbench:'+task['id']+']'
   if intent:
    if intent['branch']!=branch or intent['remote']!=remote or intent['files']!=files:raise ValueError('Git接续材料已变化')
    commit=intent.get('commit')
    if not commit:
     candidates=self._git('log','--all','--format=%H','--fixed-strings','--grep='+marker).splitlines()
     valid=[value for value in candidates if self._git('rev-parse',value+'^')==intent['base']]
     if len(valid)==1:commit=valid[0]
     elif current!=intent['base']:raise ValueError('提交回执未确认，保留原状态，不重复提交')
    if commit:
     changed=set(self._git('diff-tree','--no-commit-id','--name-only','-r',commit).splitlines())
     if not changed.issubset(files) or any(self._git('rev-parse',commit+':'+p)!=blob for p,blob in intent['blobs'].items()):raise ValueError('原提交不属于本次明确文件范围')
     intent['commit']=commit
     if remote_head==commit:return {'sync':{'status':'verified','commit':commit,'remote_verified':True,'recovered':True}}
     if remote_head!=intent['base']:raise ValueError('远端已有其他提交，未重复推送')
   else:
    if current!=remote_head:raise ValueError('本地与远端提交不一致，未夹带其他提交推送')
    if self._git('diff','--cached','--name-only'):raise ValueError('暂存区已有内容，保留原状')
    intent={'task_id':task['id'],'branch':branch,'remote':remote,'base':current,'files':files,'blobs':{p:self._git('hash-object','--path='+p,p) for p in files},'commit':None}
    _write_once(journal,pack(intent).encode())
   if not intent.get('commit'):
    pre_staged=set(self._git('diff','--cached','--name-only').splitlines())
    if pre_staged and (not pre_staged.issubset(files) or any(self._git('rev-parse',':'+p)!=intent['blobs'][p] for p in pre_staged)):raise ValueError('暂存区在接续前变化，未覆盖')
    names=list(files)
    for offset in range(0,len(names),25):self._git('add','--',*names[offset:offset+25])
    staged=set(self._git('diff','--cached','--name-only').splitlines())
    if not staged.issubset(files):raise ValueError('出现范围外暂存，已保留')
    if staged:self._git('commit','--only','-m','工作台本地决定 '+marker,'--',*names)
    commit=self._git('rev-parse','HEAD')
    if commit==intent['base']:return {'sync':{'status':'verified','commit':commit,'remote_verified':True,'new_commit':False}}
    changed=set(self._git('diff-tree','--no-commit-id','--name-only','-r',commit).splitlines())
    if self._git('rev-parse',commit+'^')!=intent['base'] or not changed.issubset(files) or any(self._git('rev-parse',commit+':'+p)!=blob for p,blob in intent['blobs'].items()):raise ValueError('新提交范围未通过核对，未推送')
    intent['commit']=commit;temporary=journal.with_suffix('.tmp');temporary.write_text(pack(intent),encoding='utf-8');os.replace(temporary,journal)
   commit=intent['commit'];self._git('push','origin',commit+':refs/heads/'+branch)
   actual=self._git('ls-remote','origin','refs/heads/'+branch).split()
   if not actual or actual[0]!=commit:raise ValueError('远端回执未确认；恢复时先核对原提交')
   return {'sync':{'status':'verified','commit':commit,'remote_verified':True}}

 def _sync_status(self,c,task,state):
  source=c.execute('SELECT job_id FROM toolbox_local_tasks WHERE id=?',((task.get('payload') or {}).get('source_task'),)).fetchone()
  if not source:return
  raw=c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(source['job_id'],)).fetchone()
  if not raw or raw['kind'] not in ('accept','archive'):return
  from easel_workbench.runtime.completion_service import CompletionService
  decision=CompletionService.archive_decision_id(raw);row=c.execute('SELECT document FROM toolbox_completions WHERE decision_id=?',(decision,)).fetchone()
  if row:
   item=json.loads(row['document']);item['sync']={**state,'local_task_id':task['id'],'updated_at':stamp()};c.execute('UPDATE toolbox_completions SET document=?,updated_at=? WHERE decision_id=?',(pack(item),stamp(),decision))

def service(box):
 value=getattr(box,'local_operations',None)
 if value is None:value=LocalOperations(box);box.local_operations=value
 return value
