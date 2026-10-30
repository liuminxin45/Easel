"""Version-bound creative delivery verification and one bounded internal correction.

AI declarations, program checks and independent observations remain separate.
This module never publishes content and never replays an uncertain request.
"""
from __future__ import annotations
import copy,hashlib,json,math,os,pathlib,subprocess,tempfile,uuid
from easel_workbench.runtime.desk import stamp

def packed(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def sha(raw):return hashlib.sha256(raw).hexdigest()
REVIEW_VERSION='independent-observation-v2'
REVIEW_MODEL='gpt-6.1-sol'
REVIEW_EFFORT='low'

def initialize(c):
 c.executescript('''CREATE TABLE IF NOT EXISTS learning_correction_links(root_job_id TEXT PRIMARY KEY,child_job_id TEXT UNIQUE NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learning_quality_acknowledgements(operation_id TEXT PRIMARY KEY,job_id TEXT NOT NULL,quality_sha256 TEXT NOT NULL,created_at TEXT NOT NULL);''')
 c.executescript('''CREATE TABLE IF NOT EXISTS learning_observation_cache(input_hash TEXT PRIMARY KEY,job_id TEXT NOT NULL,observations TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS learning_manual_reviews(operation_id TEXT PRIMARY KEY,job_id TEXT NOT NULL,run_id TEXT NOT NULL,document TEXT NOT NULL,created_at TEXT NOT NULL);''')

def attach(box,studio=None):
 """Initialize services before entering a business write transaction."""
 from easel_workbench.runtime.studio_service import StudioService
 from easel_workbench.runtime.learning_service import LearningService
 studio=studio or getattr(box,'studio',None) or StudioService(box,root=box.root)
 box.studio=studio
 existing=getattr(box,'learning',None)
 if existing is None or pathlib.Path(existing.project)!=pathlib.Path(studio.project):
  existing=LearningService(box,studio,box.root,studio.project);box.learning=existing
 return existing

def enrich_context(box,c,wid,creation,context,parts=None):
 """Place profile defaults below explicit work/round/request overrides."""
 if creation.get('creator') or getattr(box,'creator',None) is not None:
  context['learning']={'status':'explicit_skills','notice':'本次使用冻结技能版本；旧风格归纳仅保留为历史材料，不追加隐藏要求。'}
  return context
 if creation.get('creator',{}).get('profile_id','oil-pig')!='oil-pig':
  context['learning']={'status':'not_applicable','notice':'其他画像的历史风格策略不进入本次制作。'}
  return context
 service=getattr(box,'learning',None)
 if not service:return context
 snap=service.resolve(c,wid,None,creation,context)
 profile=snap.get('profile') or {}
 if profile.get('intent') and parts:
  from easel_workbench.runtime.semantic_style import resolve,applicability
  merged=[]
  for scope,part in parts:
   merged.append((scope,part))
   if scope=='channel':merged.append(('profile',{'intent':profile['intent']}))
  resolved=resolve(merged)
  context['semantic_intent']=resolved['intent'];context['intent_provenance']=resolved['provenance'];context['layers']=resolved['layers'];context['legacy_conversions']=resolved['legacy_conversions']
  context['effective']['intent']=resolved['intent']
  context['creation_options'].update(resolved_intent=resolved['intent'],intent_provenance=resolved['provenance'],legacy_conversions=resolved['legacy_conversions'])
  context['creation_options']['applicability']=applicability(context['creation_options'])
 context['learning']=snap
 return context

def intent_evidence(creation):
 if 'recipe' in creation:
  return [{'id':'intent-readable-prompt','dimension':'text','kind':'readable_prompt','text':creation['recipe'].get('prompt_text','按本轮所选创作方案及可读提示词执行，不追加旧滑轨或隐含语义默认值。')}]
 from easel_workbench.runtime.semantic_style import CHOICES,applicability
 resolved=creation.get('resolved_intent',creation.get('intent',{}));applicable=applicability(creation)
 return [{'id':'intent-'+key,'dimension':key,'kind':'semantic_intent','text':CHOICES[key][value]['instructions'],
          'provenance':creation.get('intent_provenance',{}).get(key)} for key,value in resolved.items() if applicable.get(key,{}).get('applicable',True)]

def snapshot(c,jid):
 row=c.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?',(jid,)).fetchone()
 if not row:return None,None
 document=json.loads(row['document']);snap=document.get('learning_snapshot')
 if not snap:
  manual=c.execute('SELECT document FROM learning_manual_reviews WHERE job_id=? ORDER BY rowid DESC LIMIT 1',(jid,)).fetchone()
  if manual:document=json.loads(manual['document']);snap=document.get('learning_snapshot')
 return document,snap

def human_record(c,jid):
 row=c.execute('SELECT document FROM toolbox_text_versions WHERE job_id=?',(jid,)).fetchone()
 if not row:return None
 value=json.loads(row['document'])
 return value if value.get('origin')=='human' else None

def actual_locked_text(rows,root,kind):
 """Read exact deliverable bytes, never the UI's user-text overlay."""
 def file(name):
  matches=[r for r in rows if r['name']==name]
  if len(matches)!=1:raise ValueError('原字交付不唯一')
  path=pathlib.Path(matches[0]['path']).resolve()
  if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size>2_000_000:raise ValueError('原字交付不可用')
  return path
 if kind=='poster':
  value=file('标题与配文.txt').read_bytes().decode('utf-8');title,separator,body=value.partition('\n')
  if not separator:raise ValueError('原字交付缺少正文')
  return {'title':title,'body':body}
 manifest=json.loads(file('文章交付.json').read_bytes().decode('utf-8-sig'))
 return {'title':manifest['title'],'body':file(manifest['body_file']).read_bytes().decode('utf-8')}

def _human_quality(box,c,job,record,doc=None,snap=None):
 """User text is not an AI delivery, but real bytes/media still must pass."""
 root=(box.root/'data/artifacts').resolve();files=[];failures=[];rows=[dict(r) for r in c.execute('SELECT * FROM artifacts WHERE task_id=? ORDER BY rowid',(job['id'],))]
 seen=set()
 for row in rows:
  if row['name'] in seen:failures.append(_issue('ambiguous:'+row['name'],'同名交付文件不唯一：'+row['name']))
  seen.add(row['name']);path=pathlib.Path(row['path']).resolve()
  if not path.is_relative_to(root) or not path.is_file():failures.append(_issue('missing:'+row['id'],'交付文件不可用：'+row['name']));continue
  if row['mime'].startswith('image/'):
   try:
    from PIL import Image
    with Image.open(path) as image:image.verify()
   except Exception:failures.append(_issue('invalid_image:'+row['id'],'图片文件无法解码：'+row['name']));continue
  files.append({k:row[k] for k in ('id','name','mime')}|{'sha256':sha(path.read_bytes())})
 option=c.execute('SELECT format FROM toolbox_work_options WHERE work_id=?',(job['work_id'],)).fetchone();kind=option['format'] if option else 'poster'
 try:
  if kind=='poster':
   from easel_workbench.runtime.publish_content import from_artifacts
   actual=from_artifacts(rows,root) or {};actual={'title':actual.get('title'),'body':actual.get('caption')}
   if not any(r['mime'].startswith('image/') for r in files):failures.append(_issue('missing_image','本版尚未交付配图。'))
  else:
   from easel_workbench.runtime.article_delivery import from_artifacts
   actual=from_artifacts(rows,root) or {}
   if not actual.get('ready'):failures.extend(_issue('article_delivery:'+str(i),str(message)) for i,message in enumerate(actual.get('issues',[])))
  actual=actual_locked_text(rows,root,kind)
  for key,value in record['text'].items():
   if actual.get(key)!=value:failures.append(_issue('locked_text:'+key,'用户指定原文与实际交付字节不一致。'))
 except (ValueError,OSError,KeyError,TypeError):failures.append(_issue('locked_text','无法核对本版用户原字文案。'))
 inherited=[];parent=record.get('parent');service=getattr(box,'learning',None)
 previous=service.read_run(c,parent) if parent and service else None
 for finding in ((previous or {}).get('review') or {}).get('findings',[]):
  actual=next((r for r in files if r['name']==finding.get('artifact_name') and r['sha256']==finding.get('sha256') and r['mime'].startswith('image/')),None)
  if not actual:continue
  source_row=next(r for r in rows if r['id']==actual['id'])
  try:verify_anchor(finding,{**actual,'path':source_row['path']})
  except ValueError:continue
  inherited.append({**finding,'source_job_id':parent,'observed_at':previous.get('finished_at') or previous.get('created_at'),'inherited':True,'notice':'沿用未变图片的历史观察，非本次重新查看。'})
 return {'status':'needs_objective_fix' if failures else 'human_unassessed','objective_missing':failures,'subjective_disagreements':[],
         'checks':[{'id':'human_delivery_bytes','status':'failed' if failures else 'passed','checker':'program','evidence':'核对文件、图片及人类原文；未请求AI设计说明。'}],
         'report':None,'snapshot_id':(snap or {}).get('snapshot_id'),'text_origin':'human','self_correction':{'attempt':0,'status':'not_applicable'},'examined_artifacts':files,'inherited_observations':inherited}

def enqueue_manual_review(box,wid,vid,operation_id):
 """Explicit review only. Exact operation retries return the original task."""
 from easel_workbench.runtime.toolbox_store import ident
 for value in (wid,vid,operation_id):ident(value)
 service=attach(box)
 task_id='manual-review-'+sha(operation_id.encode())[:40]
 with box.store.connect() as c:
  c.execute('BEGIN IMMEDIATE');job=c.execute("SELECT * FROM toolbox_jobs WHERE id=? AND work_id=? AND status='completed' AND kind IN ('create','change')",(vid,wid)).fetchone()
  if not job:raise ValueError('只能核对当前作品已完成的准确版本')
  prior=c.execute('SELECT * FROM learning_manual_reviews WHERE operation_id=?',(operation_id,)).fetchone()
  if prior:
   if prior['job_id']!=vid:raise ValueError('同一操作ID不能改绑版本')
   return service._enqueue(c,task_id,'production_review',{'job_id':vid,'review_run_id':prior['run_id'],'manual':True},100)
  doc,snap=snapshot(c,vid)
  if not doc:doc={'schema_version':2,'work_id':wid,'creation_options':{},'annotations':[]}
  run_id='manual-'+sha((wid+'\0'+vid+'\0'+operation_id).encode())[:40]
  creation=doc.get('creation_options',{});context=copy.deepcopy(doc.get('studio_context') or {})
  context['_learning_annotations']=doc.get('annotations',[]);context['_learning_intent_evidence']=intent_evidence(creation)
  if not snap:snap=service.freeze(c,wid,run_id,vid,creation,context)
  else:
   original_id=vid
   if not service.read_run(c,vid):
    previous=c.execute('SELECT run_id FROM learning_manual_reviews WHERE job_id=? ORDER BY rowid DESC LIMIT 1',(vid,)).fetchone()
    if previous:original_id=previous['run_id']
   if service.read_run(c,original_id):service.clone_run(c,original_id,run_id)
  if not snap:raise ValueError('当前没有可用的创作核对依据')
  frozen={**copy.deepcopy(doc),'learning_snapshot':snap,'manual_review':True}
  c.execute('INSERT INTO learning_manual_reviews VALUES(?,?,?,?,?)',(operation_id,vid,run_id,packed(frozen),stamp()))
  task=service._enqueue(c,task_id,'production_review',{'job_id':vid,'review_run_id':run_id,'manual':True},100)
 service.wake_event.set();return task

def _issue(identity,message):return {'id':identity,'message':message}

def verify_anchor(ref,actual):
 """Verify an actual location. Human-readable labels are never coordinates."""
 anchor=ref.get('anchor') or {}
 if not isinstance(anchor,dict):raise ValueError('位置坐标格式无效')
 if actual['mime'].startswith('image/'):
  if anchor.get('type')!='region':raise ValueError('图片回应缺少实际画面区域')
  values=[anchor.get(key) for key in ('x','y','width','height')]
  if any(type(value) not in (int,float) or not math.isfinite(value) for value in values):raise ValueError('画面区域坐标无效')
  x,y,width,height=values
  if x<0 or y<0 or width<=0 or height<=0 or x+width>1 or y+height>1:raise ValueError('画面区域越界或为空')
  return {key:anchor[key] for key in ('type','x','y','width','height')}
 try:text=pathlib.Path(actual['path']).read_bytes().decode('utf-8-sig')
 except (UnicodeError,OSError):raise ValueError('文字位置无法读取') from None
 quote=anchor.get('quote') or ref.get('quote')
 if not isinstance(quote,str) or not quote:raise ValueError('文字回应缺少原字选段')
 if anchor.get('type')=='text':
  start,end=anchor.get('start'),anchor.get('end')
  if type(start) is not int or type(end) is not int or not 0<=start<end<=len(text) or text[start:end]!=quote:raise ValueError('文字选段坐标与原字不一致')
 else:
  if text.count(quote)!=1:raise ValueError('选段未出现或出现多次，需要准确坐标')
  start=text.index(quote);end=start+len(quote)
 return {'type':'text','start':start,'end':end,'quote':quote}

def verify_delivery(box,c,job):
 """No model call, no persistence. Only new frozen learning contracts are gated."""
 doc,snap=snapshot(c,job['id'])
 human=human_record(c,job['id'])
 if human:return _human_quality(box,c,job,human,doc,snap)
 if not snap or not snap.get('snapshot_id'):return None
 from easel_workbench.runtime.production_style import from_artifacts
 rows=[dict(row) for row in c.execute('SELECT * FROM artifacts WHERE task_id=? ORDER BY rowid',(job['id'],))]
 by_name={};failures=[];checks=[];subjective=[];root=(box.root/'data/artifacts').resolve()
 for row in rows:by_name.setdefault(row['name'],[]).append(row)
 files={}
 for name,items in by_name.items():
  if len(items)!=1:failures.append(_issue('ambiguous:'+name,'同名交付文件不唯一：'+name));continue
  item=items[0];path=pathlib.Path(item['path']).resolve()
  if not path.is_relative_to(root) or not path.is_file():failures.append(_issue('missing:'+item['id'],'交付文件不可用：'+name));continue
  if item['mime'].startswith('image/'):
   try:
    from PIL import Image
    with Image.open(path) as image:image.verify()
   except Exception:
    failures.append(_issue('invalid_image:'+item['id'],'图片文件无法解码：'+name));continue
  files[name]={'id':item['id'],'name':name,'mime':item['mime'],'sha256':sha(path.read_bytes()),'path':str(path)}
 option=c.execute('SELECT format,article_mode FROM toolbox_work_options WHERE work_id=?',(job['work_id'],)).fetchone();kind=option['format'] if option else 'poster'
 if kind=='poster':
  if not any(f['mime'].startswith('image/') for f in files.values()):failures.append(_issue('missing_image','本版尚未交付可用配图。'))
  try:
   actual=actual_locked_text(rows,root,'poster')
   if not actual['title'].strip() or not actual['body'].strip():raise ValueError('标题或配文为空')
  except (ValueError,OSError,KeyError,TypeError):failures.append(_issue('missing_copy','本版尚未交付可用标题与配文。'))
 else:
  from easel_workbench.runtime.article_delivery import from_artifacts as article_copy
  delivered=article_copy(rows,root,option['article_mode'] if option else 'auto')
  if not delivered['ready']:failures.extend(_issue('article_delivery:'+str(index),str(message)) for index,message in enumerate(delivered['issues']))
 report=from_artifacts(rows,root);document=report.get('document')
 if not report.get('ready') or not isinstance(document,dict) or document.get('schema_version')!=2:
  failures.append(_issue('design_report','本轮需补齐设计说明与逐条反馈回应。'))
  checks.append({'id':'design_report','status':'missing','checker':'program','evidence':report.get('issues',[])})
  document=None
 required={str(row.get('id') or row.get('basis_id')):row for row in snap.get('required_evidence',[]) if row.get('id') or row.get('basis_id')}
 annotations={str(row['id']) for row in doc.get('annotations',[])}
 expected_intent=doc.get('creation_options',{}).get('resolved_intent',doc.get('creation_options',{}).get('intent',{}))
 readable_prompt=bool(doc.get('creation_options',{}).get('recipe'))
 from easel_workbench.runtime.semantic_style import applicability
 expected_applicability=applicability(doc.get('creation_options',{}))
 responses={}
 if document:
  if readable_prompt and document.get('control_mode')!='readable_prompt':failures.append(_issue('control_mode','本版使用可读提示词，不应提交隐藏参数模式。'))
  for row in document.get('responses',[]):
   ident=row.get('basis_id');responses.setdefault(ident,[]).append(row)
   if ident not in required:failures.append(_issue('unknown_basis:'+str(ident),'回应引用了不属于本轮的依据：'+str(ident)))
   aid=row.get('annotation_id')
   if aid and aid not in annotations:failures.append(_issue('unknown_annotation:'+str(aid),'回应引用了不属于本轮的批注。'))
  for ident in required:
   if len(responses.get(ident,[]))!=1:failures.append(_issue('response:'+ident,'依据缺少唯一回应：'+ident))
  for dim in document.get('dimensions',[]):
   if dim.get('applicable')!=expected_applicability.get(dim['id'],{}).get('applicable',True):
    failures.append(_issue('applicability:'+dim['id'],'设计说明不能自行把本轮适用项标为不适用：'+dim['id']))
   if dim.get('applicable') and dim.get('intent')!=(None if readable_prompt else expected_intent.get(dim['id'])):
    failures.append(_issue('intent:'+dim['id'],'设计说明与本次冻结的创作模式不一致：'+dim['id']))
   if any(ref not in required for ref in dim.get('basis_ids',[])):failures.append(_issue('dimension_basis:'+dim['id'],'设计说明的依据不属于本轮。'))
  for row in [*document.get('dimensions',[]),*document.get('responses',[])]:
   for ref in row.get('deliverables',[]):
    actual=files.get(ref.get('artifact_name'))
    if not actual or actual['sha256']!=ref.get('sha256'):
     failures.append(_issue('artifact_binding:'+str(ref.get('artifact_name')),'回应中的交付文件不存在或字节不符。'));continue
    location=str(ref.get('location','')).strip()
    if len(location)<2:failures.append(_issue('location:'+actual['id'],'回应未指出具体段落或画面位置。'))
    try:verify_anchor(ref,actual)
    except ValueError as exc:failures.append(_issue('anchor:'+actual['id'],str(exc)+'：'+actual['name']))
    quote=ref.get('quote')
    if quote and actual['mime'].startswith('text/'):
     try:present=quote in pathlib.Path(actual['path']).read_bytes().decode('utf-8-sig')
     except (TypeError,UnicodeError):present=False
     if not present:failures.append(_issue('quote:'+actual['id'],'回应所指文字未出现在交付文件。'))
   if row.get('outcome') in ('partial','not_applied','deferred'):
    ident=row.get('basis_id') or row.get('id');subjective.append(_issue(str(ident),str(row.get('reason') or '该项尚未完整实现。')))
  checks.append({'id':'unique_responses_and_artifacts','status':'failed' if failures else 'passed','checker':'program','evidence':{'expected_basis_ids':list(required),'bound_artifacts':[{k:v for k,v in f.items() if k!='path'} for f in files.values()]}})
 # User-supplied text is an exact constraint, independent of an AI explanation.
 locked=doc.get('creation_options',{}).get('text',{})
 if locked:
  try:
   option=c.execute('SELECT format FROM toolbox_work_options WHERE work_id=?',(job['work_id'],)).fetchone()
   actual=actual_locked_text(rows,root,option['format'] if option else 'poster')
   for key,value in locked.items():
    if actual.get(key)!=value:failures.append(_issue('locked_text:'+key,'用户指定的'+('标题' if key=='title' else '正文')+'与交付原字不一致。'))
  except (ValueError,KeyError):failures.append(_issue('locked_text','无法核对本版用户原字文案。'))
 unique=lambda values:list({row['id']:row for row in values}.values())
 missing=unique(failures)
 return {'status':'needs_metadata' if missing and all(row['id']=='design_report' or row['id'].startswith(('anchor:','location:','response:','unknown_basis:','unknown_annotation:','dimension_basis:')) for row in missing) else 'needs_objective_fix' if missing else 'needs_review' if subjective else 'pending',
         'objective_missing':missing,'subjective_disagreements':unique(subjective),'checks':checks,'report':document,'snapshot_id':snap['snapshot_id'],
         'self_correction':{'attempt':0,'status':'not_required'},'examined_artifacts':[{k:v for k,v in item.items() if k!='path'} for item in files.values()]}

def public_learning(box,c,jid):
 doc,snap=snapshot(c,jid)
 human=human_record(c,jid)
 if not snap and not human:return None
 service=getattr(box,'learning',None)
 manual=c.execute('SELECT run_id FROM learning_manual_reviews WHERE job_id=? ORDER BY rowid DESC LIMIT 1',(jid,)).fetchone()
 run_id=manual['run_id'] if manual else jid
 run=service.read_run(c,run_id) if service else None
 # Recheck bytes on every adoption/read. A pending or old successful AI result
 # can never waive current objective requirements.
 work_id=(doc or {}).get('work_id') or c.execute('SELECT work_id FROM toolbox_jobs WHERE id=?',(jid,)).fetchone()['work_id']
 quality=verify_delivery(box,c,{'id':jid,'work_id':work_id})
 stored=(run or {}).get('quality') or {}
 identity=lambda q:sorted((row.get('id'),row.get('sha256')) for row in q.get('examined_artifacts',[]))
 if quality and not quality['objective_missing'] and stored.get('examined_artifacts') and identity(quality)==identity(stored):
  current=quality
  quality={**copy.deepcopy(stored),'objective_missing':current['objective_missing'],'report':current['report'],'examined_artifacts':current['examined_artifacts']}
  quality['checks']=[*current['checks'],*[row for row in stored.get('checks',[]) if row.get('checker')!='program']]
 if quality and quality['status']=='pending':quality['status']='unverified'
 return {'snapshot':snap,'report':(quality or {}).get('report'),'quality':quality,'quality_revision':sha(packed(quality).encode()),'run_id':run_id,'review':(run or {}).get('review'),'text_origin':'human' if human else 'ai'}

def require_adoption(box,c,jid,value=None,operation_id=None):
 result=public_learning(box,c,jid)
 if not result:return None
 quality=result.get('quality') or {}
 # Existing explicit copy-only adoption does not claim a picture was delivered.
 if result.get('text_origin')=='human' and (value or {}).get('scope')==['copy']:
  quality=copy.deepcopy(quality);quality['objective_missing']=[r for r in quality.get('objective_missing',[]) if r['id']!='missing_image']
  if not quality['objective_missing'] and quality.get('status')=='needs_objective_fix':quality['status']='human_unassessed'
  result={**result,'quality':quality}
 if quality.get('objective_missing'):raise ValueError('本版交付核对尚有缺失，请先补齐：'+'；'.join(row['message'] for row in quality['objective_missing'][:4]))
 needs_ack=quality.get('status') not in ('ready','human_unassessed') or bool(quality.get('subjective_disagreements'))
 acknowledged=bool((value or {}).get('subjective_acknowledged') or (value or {}).get('learning_acknowledged'))
 if needs_ack and not acknowledged:raise ValueError('本版仍有未核验或风格待核对项，请先查看并明确确认保留。')
 if needs_ack and (value or {}).get('learning_quality_token')!=result['quality_revision']:raise ValueError('核验结果已有变化，请重新查看本版未解决项后再确认。')
 if needs_ack and operation_id:
  c.execute('INSERT OR IGNORE INTO learning_quality_acknowledgements VALUES(?,?,?,?)',(operation_id,jid,sha(packed(quality).encode()),stamp()))
 return result

REVIEW_SCHEMA={'type':'object','properties':{'summary':{'type':'string'},'findings':{'type':'array','items':{'type':'object','properties':{
 'basis_id':{'type':'string'},'status':{'type':'string','enum':['pass','issue','unverified']},'message':{'type':'string'},'artifact_name':{'type':'string'},'sha256':{'type':'string'},'location':{'type':'string'},'quote':{'type':'string'},
 'anchor':{'type':'object','properties':{'type':{'type':'string','enum':['text','region','unverified']},'start':{'type':'integer'},'end':{'type':'integer'},'quote':{'type':'string'},'x':{'type':'number'},'y':{'type':'number'},'width':{'type':'number'},'height':{'type':'number'}},'required':['type','start','end','quote','x','y','width','height'],'additionalProperties':False}},
 'required':['basis_id','status','message','artifact_name','sha256','location','quote','anchor'],'additionalProperties':False}}},'required':['summary','findings'],'additionalProperties':False}

def image_selection(request):
 references=request.get('reference_images',[])[:8]
 outputs=[row for row in request['artifacts'] if row['mime'].startswith('image/')][:16-len(references)]
 return outputs,references

def independent_review(service,request):
 from easel_workbench.runtime.readonly_codex import command
 root=pathlib.Path(service.root).resolve();base=root/'data/learning-check-tmp';base.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(prefix='check-',dir=base) as name:
  directory=pathlib.Path(name).resolve()
  if not directory.is_relative_to(base):raise ValueError('核验临时目录越界')
  (directory/'schema.json').write_text(json.dumps(REVIEW_SCHEMA),encoding='utf-8')
  args=command(directory);args[-1:-1]=['--model',REVIEW_MODEL,'-c','model_reasoning_effort="'+REVIEW_EFFORT+'"']
  outputs,references=image_selection(request)
  images=[*outputs,*references]
  for index,image in enumerate(images):
   raw=pathlib.Path(image['path']).read_bytes()
   if sha(raw)!=image['sha256']:raise ValueError('核验图片在读取前已变化')
   target=directory/('image-'+str(index)+pathlib.Path(image['path']).suffix)
   target.write_bytes(raw);args[-1:-1]=['--image',str(target)]
  from easel_workbench.runtime.task_runtime import contract_prompt,observed_call
  submitted={k:v for k,v in request.items() if k not in ('image_paths','creator_snapshot')}
  submitted['attached_images']=[{'role':'output','artifact_name':r['artifact_name'],'sha256':r['sha256']} for r in outputs]+[{'role':'reference','evidence_id':r['evidence_id'],'sha256':r['sha256']} for r in references]
  prompt,binding=contract_prompt(service.box,'review','references/independent-check.md',submitted,snapshot=request.get('creator_snapshot'))
  with observed_call(service.box,'review',submitted,prompt,binding,request.get('job_id')) as record_result:
      from easel_workbench.readonly_runner import run,recorded_output,project_snapshot
      proc=run(binding if project_snapshot(request.get('creator_snapshot')) else None,args,input=prompt.encode('utf-8'),capture_output=True,timeout=180,cwd=directory,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),runtime_root=service.box,task_id=request.get('job_id'))
      output=directory/'answer.json'
      if proc.returncode or not output.is_file():raise ValueError('独立核验未取得有效结果')
      result=json.loads(output.read_text(encoding='utf-8-sig'))
      result['checker']='independent_ai';record_result(recorded_output(proc,result));return result

def _supplement(box,c,job,doc,snap,observations):
 """Evidence-based checker supplement; never attributed to the original producer."""
 from easel_workbench.runtime.production_style import validate_v2
 requirements=snap.get('required_evidence',[]);findings={r['basis_id']:r for r in observations['findings']}
 def item_for(basis):
  row=findings.get(basis['id'],{});status=row.get('status','unverified')
  refs=[{key:row[key] for key in ('artifact_name','sha256','location','anchor','quote') if key in row}] if status in ('pass','issue') and row.get('artifact_name') else []
  return {'basis_id':basis['id'],'dimension':basis.get('dimension','style') if basis.get('dimension') in ('image','text','title','tone','structure','style') else 'style',
          **({'annotation_id':basis['id']} if any(a['id']==basis['id'] for a in doc.get('annotations',[])) else {}),
          'outcome':'applied' if status=='pass' else 'not_applied' if status=='issue' else 'deferred','reason':row.get('message') or '材料不足，尚未核验。','deliverables':refs}
 responses=[item_for(basis) for basis in requirements];dimensions=[]
 intents=doc.get('creation_options',{}).get('resolved_intent',doc.get('creation_options',{}).get('intent',{}))
 from easel_workbench.runtime.semantic_style import applicability
 applicable=applicability(doc.get('creation_options',{}))
 for identity in ('image','text','title','tone','structure','style'):
  basis=[row for row in requirements if row.get('dimension')==identity]
  if (doc.get('creation_options',{}).get('recipe') or doc.get('creator_snapshot')) and not basis:
   basis=[row for row in requirements if row.get('kind') in ('readable_prompt','creator_skill_prompt')]
  refs=[r for row in responses if row['basis_id'] in {b['id'] for b in basis} for r in row['deliverables']]
  active=applicable.get(identity,{}).get('applicable',True) if isinstance(applicable,dict) else True
  complete=bool(basis) and all(findings.get(row['id'],{}).get('status')=='pass' for row in basis)
  dimensions.append({'id':identity,'applicable':active,'intent':intents.get(identity) if active and not doc.get('creation_options',{}).get('recipe') else None,'outcome':'applied' if complete and active else 'deferred' if active else 'not_applicable',
   'reason':'独立检查根据实际交付补充说明；不代表制作方阅读或用户认可。' if active else '本轮保留文字或固定母版，该维度不重设计。',
   'basis_ids':[row['id'] for row in basis] if active else [],'deliverables':refs if active else []})
 report={'schema_version':2,'basis':'execution','authored_by':'independent_checker_supplement','dimensions':dimensions,'responses':responses}
 if doc.get('creation_options',{}).get('recipe') or doc.get('creator_snapshot'):report['control_mode']='readable_prompt'
 validate_v2(report);raw=packed(report).encode();aid=sha((job['id']+'\0checker-supplement\0').encode()+raw);path=box.root/'data/artifacts'/aid/'设计说明.json';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
 # Keep any original producer bytes and their artifact identity visible.
 c.execute("UPDATE artifacts SET name='制作方原始-'||name WHERE task_id=? AND name='设计说明.json'",(job['id'],))
 c.execute('INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?,?)',(aid,job['id'],path.name,str(path),'application/json'))
 return report

def queue_correction(service,c,job,quality):
 box=service.box
 link=c.execute('SELECT root_job_id FROM learning_correction_links WHERE child_job_id=?',(job['id'],)).fetchone()
 root_id=link['root_job_id'] if link else job['id']
 prior=c.execute('SELECT child_job_id FROM learning_correction_links WHERE root_job_id=?',(root_id,)).fetchone()
 if prior:return {'attempt':1,'status':'limit_reached','job_id':prior['child_job_id']}
 later=c.execute('SELECT 1 FROM toolbox_jobs WHERE work_id=? AND rowid>(SELECT rowid FROM toolbox_jobs WHERE id=?) LIMIT 1',(job['work_id'],job['id'])).fetchone()
 if later:return {'attempt':0,'status':'superseded_by_user'}
 issues=quality.get('subjective_disagreements',[])
 if not issues:return {'attempt':0,'status':'not_required'}
 from easel_workbench.native_corrections import enqueue as native_correction
 try:native=native_correction(service,c,job,quality)
 except (ValueError,OSError,KeyError,TypeError) as error:
  from easel_workbench.runtime import server_logging as journal
  journal.exception('native_correction_prepare_failed',error,operation_ref=journal.reference(job['id']))
  return {'attempt':0,'status':'blocked','code':'native_correction_evidence_unavailable','message':'内部修正冻结依据或原件待核对，未发送，也不转交旧制作器。'}
 if native is not None:return native
 child='learning-fix-'+sha(root_id.encode())[:32];now=stamp();doc,_=snapshot(c,job['id']);frozen=copy.deepcopy(doc)
 frozen['internal_correction']={'root_job_id':root_id,'parent_job_id':job['id'],'attempt':1,'issues':issues}
 message='交付前内部修正（本次唯一一次）。保留原版，只修以下有实际成品证据的问题；沿用冻结依据，不混入后来反馈。\n'+'\n'.join(row['message'] for row in issues)
 if frozen.get('execution_prompt'):
  original=frozen['execution_prompt'];body=original['body']+'\n\n## 已授权的一次内部修正\n'+message+'\n实际检查证据：\n'+packed(issues)
  products=[dict(row) for row in c.execute('SELECT id,name,path,mime FROM artifacts WHERE task_id=? ORDER BY rowid',(job['id'],))]
  body+='\n待修正版的实际交付文件：\n'+packed(products)
  frozen['execution_prompt']={**original,'body':body,'sha256':sha(body.encode()),'origin_prompt_sha256':original['sha256'],'internal_correction':frozen['internal_correction'],'approval_scope':'用户已授权同一冻结依据下的一次有据内部修正'}
  frozen['execution_prompt'].pop('approved_preview_id',None)
 files=[fid for fid in json.loads(job.get('files') or '[]') if not fid.startswith('review-')]
 c.execute('INSERT INTO toolbox_jobs(id,work_id,kind,text,candidate_id,scope,files,signature,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)',(child,job['work_id'],'change',message,job['id'],'[]',packed(files),packed({'internal_correction':root_id}),'queued',now))
 c.execute('INSERT INTO learning_correction_links VALUES(?,?,?)',(root_id,child,now))
 c.execute('INSERT OR IGNORE INTO toolbox_article_inputs SELECT ?,revision,document FROM toolbox_article_inputs WHERE job_id=?',(child,root_id))
 from easel_workbench.runtime.work_review import attach_document
 from easel_workbench.runtime.task_runtime import clone_correction
 clone_correction(c,job['id'],child)
 attach_document(box,c,job['work_id'],child,frozen)
 service.clone_run(c,job['id'],child)
 if frozen.get('execution_prompt'):
  run=service.read_run(c,child);run['execution_prompt']=frozen['execution_prompt'];service._put(c,'learning_runs',run)
 c.execute('UPDATE toolbox_works SET updated_at=? WHERE id=?',(now,job['work_id']))
 return {'attempt':1,'status':'queued','job_id':child}

def observation_key(job,document,request):
 """Only identical work, ordered bytes, full evidence and checker configuration."""
 from easel_workbench.runtime.production_style import V2_CONTRACT
 snap=copy.deepcopy(request['snapshot'])
 for key in ('snapshot_id','created_at','resolved_at','job_id','run_id'):snap.pop(key,None)
 def clean(value):
  if isinstance(value,dict):return {k:clean(v) for k,v in value.items() if k not in ('path','artifact_id','source_artifact_id')}
  if isinstance(value,list):return [clean(v) for v in value]
  return value
 artifacts=[{'role':'output','name':r['artifact_name'],'mime':r['mime'],'sha256':r['sha256']} for r in request['artifacts'] if '设计说明' not in r['artifact_name'] and r['artifact_name']!='风格权重.json']
 references=[{'role':'reference','evidence_id':r['evidence_id'],'mime':r['mime'],'sha256':r['sha256']} for r in request.get('reference_images',[])]
 value={'checker_version':REVIEW_VERSION,'requested_model':REVIEW_MODEL,'reasoning_effort':REVIEW_EFFORT,'schema':REVIEW_SCHEMA,'reader':'utf8-sig-codepoints-preserve-crlf-v1',
        'work_id':job['work_id'],'artifacts':artifacts,'reference_images':references,'snapshot':clean(snap),'requirements':request.get('required_evidence',[]),
        'creation_options':document.get('creation_options',{}),'annotations':document.get('annotations',[]),'contract':V2_CONTRACT,'producer_report':clean(request.get('producer_report'))}
 return sha(packed(value).encode())

def repair_metadata(box,c,job):
 """Fill computable omissions only; retain original bytes, reasons and claims."""
 if human_record(c,job['id']):return False
 from easel_workbench.runtime.production_style import validate_v2
 rows=[dict(r) for r in c.execute('SELECT * FROM artifacts WHERE task_id=?',(job['id'],))]
 reports=[r for r in rows if r['name']=='设计说明.json']
 if len(reports)!=1:return False
 root=(box.root/'data/artifacts').resolve();source=pathlib.Path(reports[0]['path']).resolve()
 if not source.is_relative_to(root) or not source.is_file() or source.stat().st_size>256000:return False
 try:report=json.loads(source.read_text(encoding='utf-8-sig'))
 except (ValueError,OSError,UnicodeError):return False
 if not isinstance(report,dict) or report.get('schema_version')!=2:return False
 original=copy.deepcopy(report);doc,snap=snapshot(c,job['id']);required={r['id'] for r in (snap or {}).get('required_evidence',[]) if r.get('id')}
 for row in [*report.get('dimensions',[]),*report.get('responses',[])]:
  if not isinstance(row,dict):continue
  if not row.get('basis_id') and row.get('annotation_id') in required:row['basis_id']=row['annotation_id']
  for ref in row.get('deliverables',[]):
   matches=[r for r in rows if r['name']==ref.get('artifact_name')]
   if len(matches)!=1:continue
   actual=matches[0];path=pathlib.Path(actual['path']).resolve()
   if not path.is_relative_to(root) or not path.is_file():continue
   digest=sha(path.read_bytes())
   if not ref.get('sha256'):ref['sha256']=digest
   # A provided, wrong digest/coordinate is a real defect, not an omission.
   if ref.get('sha256')!=digest:continue
   if not ref.get('anchor') and not actual['mime'].startswith('image/'):
    try:
     anchor=verify_anchor(ref,actual);ref['anchor']=anchor
     if not ref.get('location'):ref['location']='字符 '+str(anchor['start'])+'–'+str(anchor['end'])
    except ValueError:pass
 if report==original:return False
 try:validate_v2(report)
 except (ValueError,KeyError,TypeError):return False
 report['metadata_completion']={'checker':'program','source_artifact_id':reports[0]['id'],'source_sha256':sha(source.read_bytes()),'notice':'仅补可计算的指纹或唯一引文坐标；原设计原因与采用声明未改写。'}
 raw=packed(report).encode();aid=sha((job['id']+'\0metadata\0').encode()+raw);path=root/aid/'设计说明.json';path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(raw)
 c.execute("UPDATE artifacts SET name='制作方原始-'||name WHERE id=?",(reports[0]['id'],))
 c.execute('INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?,?)',(aid,job['id'],path.name,str(path),'application/json'))
 return True

def run_review(service,task,runner=None):
 """Queue consumer; read-only model inspection plus bounded local writes."""
 jid=(task.get('payload') or {}).get('job_id') or task.get('job_id')
 run_id=(task.get('payload') or {}).get('review_run_id') or jid
 manual=(task.get('payload') or {}).get('manual') is True
 box=service.box
 with box.store.connect() as c:
  row=c.execute("SELECT * FROM toolbox_jobs WHERE id=? AND kind IN ('create','change') AND status='completed'",(jid,)).fetchone()
  if not row:return {'status':'not_ready','job_id':jid}
  job=dict(row);doc,snap=snapshot(c,jid)
  if manual:
   frozen=c.execute('SELECT document FROM learning_manual_reviews WHERE run_id=? AND job_id=?',(run_id,jid)).fetchone()
   if not frozen:raise ValueError('手动核验缺少准确冻结记录')
   doc=json.loads(frozen['document']);snap=doc.get('learning_snapshot')
  if human_record(c,jid) and not manual:return {'status':'human_unassessed','job_id':jid,'model_calls':0}
  if not snap:return {'status':'legacy','job_id':jid}
  old=service.read_run(c,run_id) or {}
  if old.get('status')=='reviewed':return old.get('quality',{})
  repair_metadata(box,c,job)
  quality=verify_delivery(box,c,job);service.update_run(c,run_id,{'status':'checking','quality':quality})
  from easel_workbench.runtime.task_runtime import step
  step(c,jid,'delivery','failed' if quality.get('status')=='needs_objective_fix' else 'completed',checks=quality.get('checks',[]))
  if quality.get('status')=='needs_objective_fix':
   quality['checks'].append({'id':'independent_review','status':'not_requested','checker':'program','evidence':'客观交付不合格，未发送模型核验。'})
   service.update_run(c,run_id,{'status':'reviewed','quality':quality,'review':{'status':'not_requested','model_calls':0},'finished_at':stamp()})
   step(c,jid,'review','not_requested',reason='客观交付缺失，先由程序指出；未请求模型')
   return quality
  artifacts=[]
  for row in c.execute('SELECT * FROM artifacts WHERE task_id=?',(jid,)):
   p=pathlib.Path(row['path']).resolve()
   if not p.is_relative_to((box.root/'data/artifacts').resolve()) or not p.is_file():continue
   raw=p.read_bytes();record={key:row[key] for key in ('name','mime','path')};record['artifact_name']=record.pop('name');record['sha256']=sha(raw)
   if row['mime'].startswith('text/') or p.suffix.lower() in ('.md','.txt','.html'):
    try:record['content']=raw.decode('utf-8-sig')[:160000]
    except UnicodeError:record['unreadable']=True
   artifacts.append(record)
 references=[];binary_sources=set()
 for source in snap.get('source_evidence',[]):
  if source.get('content') is not None:continue
  binary_sources.add(source['id'])
  try:
   if source.get('source',{}).get('kind')=='frozen_creator_asset':
    path=pathlib.Path(source['source']['path']).resolve()
    if not path.is_relative_to((box.root/'data/creator-inputs').resolve()):raise ValueError('核验冻结参考路径越界')
    from easel_workbench.runtime.learning_service import original_mime
    mime=original_mime(path)
   else:
    try:original=service.original_file(source['id']);path=pathlib.Path(original['path']);mime=original['mime']
    except ValueError:
     path=service._safe_path(source['source']['path'])
     from easel_workbench.runtime.learning_service import original_mime
     mime=original_mime(path)
   if not mime.startswith('image/') or sha(path.read_bytes())!=source['sha256']:continue
   from PIL import Image
   with Image.open(path) as im:
    if getattr(im,'n_frames',1)!=1:continue
    im.verify()
   references.append({'evidence_id':source['id'],'path':str(path),'mime':mime,'sha256':source['sha256']})
  except (ValueError,OSError,KeyError):continue
 request={'job_id':jid,'snapshot':snap,'required_evidence':snap.get('required_evidence',[]),'artifacts':artifacts,'producer_report':quality.get('report'),'reference_images':references,'creator_snapshot':doc.get('creator_snapshot')}
 cache_key=observation_key(job,doc,request)
 with box.store.connect() as c:cached=c.execute('SELECT * FROM learning_observation_cache WHERE input_hash=?',(cache_key,)).fetchone()
 reused=dict(cached) if cached else None
 try:observations=json.loads(reused['observations']) if reused else (runner or independent_review)(service,request)
 except Exception as error:
  with box.store.connect() as c:
   quality['status']='needs_objective_fix' if quality['objective_missing'] else 'unverified';quality['checks'].append({'id':'independent_review','status':'unverified','checker':'independent_ai','evidence':'未取得有效核验结果；不推定为已通过。'})
   service.update_run(c,run_id,{'status':'reviewed','quality':quality,'review':{'status':'unverified'},'finished_at':stamp()})
   step(c,jid,'review','unknown',reason='未取得有效独立核验结果')
  from easel_workbench.readonly_runner import ReadonlyExecutionUnknown
  if isinstance(error,ReadonlyExecutionUnknown):raise
  return quality
 expected={row['id'] for row in snap.get('required_evidence',[])};findings=observations.get('findings',[]);names={row['artifact_name']:row for row in artifacts};seen=set();valid=[]
 outputs,reference_inputs=image_selection(request)
 attached_images={row['artifact_name'] for row in outputs};attached_references={row['evidence_id'] for row in reference_inputs}
 requirements={row['id']:row for row in snap.get('required_evidence',[])}
 for finding in findings:
  ident=finding.get('basis_id');actual=names.get(finding.get('artifact_name'))
  if ident not in expected or ident in seen:continue
  seen.add(ident);item=copy.deepcopy(finding)
  required_sources=set(requirements[ident].get('source_evidence_ids',[])) & binary_sources
  if required_sources-attached_references:item.update(status='unverified',message='相关参考原件未实际附入核验，不能声称已对照。')
  if actual and actual['mime'].startswith('image/') and actual['artifact_name'] not in attached_images:item.update(status='unverified',message='该图片未附入本次独立核验，不能声称已查看。')
  if item.get('status') not in ('pass','issue','unverified') or item.get('status')!='unverified' and (not actual or item.get('sha256')!=actual['sha256'] or not item.get('location')):item.update(status='unverified',message='独立检查未提供准确的成品位置与指纹。')
  if item.get('status')!='unverified':
   try:
    item['anchor']=verify_anchor(item,actual)
    if actual.get('unreadable') or item['anchor']['type']=='text' and item['anchor']['end']>len(actual.get('content','')):raise ValueError('该选段未完整附入核验输入')
   except ValueError:item.update(status='unverified',message='独立检查所指位置未通过原字或画面区域核对。')
  valid.append(item)
 for ident in expected-seen:valid.append({'basis_id':ident,'status':'unverified','message':'独立检查未覆盖这一项。','artifact_name':'','sha256':'','location':''})
 observations={**observations,'findings':valid}
 with box.store.connect() as c:
  c.execute('BEGIN IMMEDIATE')
  if quality['status']=='needs_metadata' and not human_record(c,jid):
   try:_supplement(box,c,job,doc,snap,observations);quality=verify_delivery(box,c,job)
   except (ValueError,KeyError,TypeError):pass
  semantic=[_issue(str(item['basis_id']),str(item.get('message') or '独立检查发现待核对项。')) for item in valid if item['status']!='pass']
  quality['subjective_disagreements']=list({row['id']:row for row in [*quality['subjective_disagreements'],*semantic]}.values())
  provenance={'reused':bool(reused),'source_job_id':reused['job_id'] if reused else jid,'observed_at':reused['created_at'] if reused else stamp(),'input_sha256':cache_key,'requested_model':REVIEW_MODEL,'actual_model':None,'reasoning_effort':REVIEW_EFFORT,'checker_version':REVIEW_VERSION,'notice':'复用相同输入的历史观察，非本次重新查看。' if reused else '本次独立检查。'}
  quality['checks'].append({'id':'independent_review','status':'passed' if not semantic else 'needs_review','checker':'independent_ai','evidence':observations,'provenance':provenance})
  quality['status']='needs_objective_fix' if quality['objective_missing'] else 'unverified' if any(item['status']=='unverified' for item in valid) else 'needs_review' if semantic or quality['subjective_disagreements'] else 'ready'
  # Only anchored issues trigger repair; unknown or subjective uncertainty does not.
  if not quality['objective_missing'] and not human_record(c,jid) and not manual and any(item['status']=='issue' for item in valid):
   anchored=copy.deepcopy(quality);anchored['subjective_disagreements']=[_issue(item['basis_id'],item['message']) for item in valid if item['status']=='issue']
   quality['self_correction']=queue_correction(service,c,job,anchored)
  # Only valid, complete semantic observations can be reused. User judgments and
  # automated correction state never enter this cache.
  if not reused and valid and all(item['status'] in ('pass','issue') for item in valid):
   c.execute('INSERT OR IGNORE INTO learning_observation_cache VALUES(?,?,?,?)',(cache_key,jid,packed(observations),stamp()))
  service.update_run(c,run_id,{'status':'reviewed','quality':quality,'review':observations,'finished_at':stamp()})
  step(c,jid,'review','reused' if reused else 'completed',quality_status=quality['status'],provenance=provenance,findings=valid)
 return quality
