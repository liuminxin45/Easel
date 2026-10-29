"""Human-readable creative recipes, exact application prompts and honest traces.

No model calls on reads, edits, evidence import, export or feedback. Long-term
changes go through the existing proposal confirmation transaction.
"""
from __future__ import annotations
import copy,hashlib,io,json,pathlib,re,zipfile,uuid,tempfile,sqlite3,contextlib
from easel_workbench.runtime.desk import stamp

CATALOG='规范/创作方案/目录.json'
SLOTS=('writing','visual','character','layout')
MAX_PROMPT=160000
def packed(v):return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
def digest(v):return hashlib.sha256(v if isinstance(v,bytes) else v.encode('utf-8')).hexdigest()
def bounded(value,limit=MAX_PROMPT):
 if not isinstance(value,str) or len(value)>limit or '\x00' in value:raise ValueError('提示词为空或超过可保存范围')
 return value

def parse_recipe(value):
 if not isinstance(value,dict) or set(value)-{'pack_id','overrides','prompt_text','source_revision','plan_id','preview_id'}:raise ValueError('创作方案格式无效')
 result={}
 for key in ('pack_id','source_revision','plan_id','preview_id'):
  if key in value:
   item=bounded(value[key],160)
   if key!='source_revision' and not re.fullmatch(r'[A-Za-z0-9_-]{1,160}',item):raise ValueError('方案标识无效')
   result[key]=item
 raw=value.get('overrides',{})
 if not isinstance(raw,dict) or set(raw)-set(SLOTS):raise ValueError('只能替换写法、画面、角色与页面结构')
 result['overrides']={key:bounded(item,160) for key,item in raw.items()}
 if 'prompt_text' in value:result['prompt_text']=bounded(value['prompt_text'])
 return result

class CreativeRecipes:
 def __init__(self,learning):
  self.learning=learning;self.box=learning.box;self.root=learning.root;self.project=learning.project;self.store=learning.store
 def initialize(self,c):
  c.executescript('''CREATE TABLE IF NOT EXISTS creative_image_plans(id TEXT PRIMARY KEY,work_id TEXT NOT NULL,candidate_id TEXT,revision INTEGER NOT NULL,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS creative_receipts(operation_id TEXT PRIMARY KEY,signature TEXT NOT NULL,result TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS creative_exports(id TEXT PRIMARY KEY,document TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS creative_prompt_previews(id TEXT PRIMARY KEY,job_id TEXT NOT NULL,guard TEXT NOT NULL,document TEXT NOT NULL,created_at TEXT NOT NULL);''')
 def path(self,relative):return self.learning._safe_path(relative)
 def document(self):
  path=self.path(CATALOG)
  if not path.is_file():return {'schema_version':1,'revision':1,'packs':[],'components':[]}
  doc=json.loads(path.read_text(encoding='utf-8-sig'))
  if doc.get('schema_version')!=1 or not isinstance(doc.get('packs'),list) or not isinstance(doc.get('components'),list):raise ValueError('创作方案目录无效')
  return doc
 def original(self,relative,expected=None):
  p=self.path(relative)
  raw=p.read_bytes()
  if expected and digest(raw)!=expected:raise ValueError('方案原件已变化，请重新核对')
  return raw
 def component(self,item):
  item=copy.deepcopy(item);raw=self.original(item['prompt_file'],item.get('prompt_sha256'));item['prompt']=raw.decode('utf-8-sig');item['prompt_sha256']=digest(raw)
  policy=self.learning.policy()['document']
  override=next((entry for entry in reversed(policy['methods']) if entry.get('recipe_component_id')==item['id'] and entry.get('status')=='confirmed'),None)
  if override:
   item['prompt']='\n'.join(override['instructions']);item['prompt_sha256']=digest(item['prompt']);item['active_policy_id']=override['id'];item['active_policy_revision']=override.get('revision')
  assets=[]
  for index,ref in enumerate(item.get('assets',[])):
   ref=copy.deepcopy(ref)
   try:raw=self.original(ref['path'],ref.get('sha256'));ref.update(available=True,sha256=digest(raw),url='/api/creative/assets/'+item['id']+'/'+str(index))
   except (ValueError,OSError):ref.update(available=False,url=None,reason='原件缺失或字节已变化')
   assets.append(ref)
  item['assets']=assets;return item
 def frozen_component(self,item,snapshot):
  item=copy.deepcopy(item);resources=[r for skill in snapshot['skills'] for r in skill.get('resources',[])]
  prompt=next((r for r in resources if r.get('kind')=='prompt' and (r.get('variant')==item['id'] or r.get('path')==item.get('prompt_file'))),None)
  if not prompt or not isinstance(prompt.get('content'),str):raise ValueError('所选技能版本未包含此写法或画面组件：'+item['id'])
  item.update(prompt=prompt['content'],prompt_sha256=prompt['sha256'],available=True)
  for key in ('provenance','active_policy_id','active_policy_revision'):
   if key in prompt:item[key]=copy.deepcopy(prompt[key])
  assets=[]
  for original in item.get('assets',[]):
   resource=next((r for r in resources if r.get('path')==original['path'] and r.get('kind')=='asset'),None)
   available=bool(resource and resource.get('available'))
   assets.append({**original,'available':available,'sha256':resource['sha256'] if available else original.get('sha256'),
                  'url':resource.get('url') if available else None,**({} if available else {'reason':'此技能版本未取得该参考原件'})})
  item['assets']=assets;return item
 def frozen_document(self,snapshot):
  resource=next((r for skill in snapshot['skills'] for r in skill.get('resources',[]) if r.get('path')==CATALOG and isinstance(r.get('content'),str)),None)
  if not resource:raise ValueError('所选技能版本未包含创作方案目录，请核对技能资源')
  doc=json.loads(resource['content'])
  if doc.get('schema_version')!=1 or not isinstance(doc.get('packs'),list) or not isinstance(doc.get('components'),list):raise ValueError('技能冻结的方案目录无效')
  return doc
 def catalog(self):
  creator=getattr(self.box,'creator',None)
  snapshot=creator.resolve(task='poster') if creator else None
  doc=self.frozen_document(snapshot) if snapshot else self.document();components=[]
  for row in doc['components']:
   try:components.append(self.frozen_component(row,snapshot) if snapshot else self.component(row))
   except (ValueError,OSError) as error:components.append({**row,'available':False,'error':str(error),'prompt':'','assets':[]})
  for row in components:row.setdefault('available',True)
  packs=[]
  for row in doc['packs']:
   row=copy.deepcopy(row);row['examples']=[asset for cid in row.get('components',{}).values() for component in components if component['id']==cid for asset in component['assets'] if asset.get('role')=='example']
   previews=row['examples'] or [asset for cid in row.get('components',{}).values() for component in components if component['id']==cid for asset in component['assets'] if asset.get('available')]
   row['preview_asset']=previews[0] if previews else None
   row['reference_count']=sum(len(component['assets']) for component in components if component['id'] in row.get('components',{}).values());packs.append(row)
  return {'schema_version':1,'revision':digest(packed({'catalog':doc,'prompts':{row['id']:row.get('prompt_sha256') for row in components}})),'packs':packs,'components':components,'workflow_skill':'.agents/skills/neo-content/SKILL.md'}
 def select(self,recipe,format='poster',snapshot=None):
  recipe=parse_recipe(recipe)
  if snapshot:
   document=self.frozen_document(snapshot);components=[]
   for row in document['components']:
    try:components.append(self.frozen_component(row,snapshot))
    except ValueError:components.append({**row,'available':False,'prompt':'','assets':[]})
   catalog={**document,'components':components,'revision':digest(packed({'catalog':document,'prompts':{row['id']:row.get('prompt_sha256') for row in components}}))}
  else:catalog=self.catalog()
  pid=recipe.get('pack_id') or ('editorial-article' if format=='article' else 'editorial-poster')
  pack=next((row for row in catalog['packs'] if row['id']==pid),None)
  if not pack:raise ValueError('没有找到这套创作方案')
  if format not in pack.get('formats',['poster','article']):raise ValueError('这套方案不适合当前内容格式')
  if not snapshot and recipe.get('source_revision') and recipe['source_revision']!=catalog['revision']:raise ValueError('创作方案有新修订，请核对提示词后提交')
  choices={**pack.get('components',{}),**recipe.get('overrides',{})};selected=[]
  if pack.get('fixed_master') and recipe.get('overrides'):raise ValueError('固定栏目母版不能通过局部替换改变，请另选方案')
  for slot,cid in choices.items():
   row=next((item for item in catalog['components'] if item['id']==cid and item.get('slot')==slot),None)
   if not row or not row['available']:raise ValueError('方案组件不可用：'+slot)
   if format not in row.get('formats',['poster','article']):raise ValueError('所选组件不适合当前内容格式')
   if any(not a['available'] for a in row['assets'] if a.get('required')):raise ValueError('方案所需参考图缺失')
   selected.append(row)
  main='\n\n'.join('## '+row['name']+'\n'+row['prompt'] for row in selected)
  if 'prompt_text' in recipe:main=recipe['prompt_text']
  return {'pack':pack,'components':selected,'prompt_text':main,'source_revision':catalog['revision'],'assets':[a for row in selected for a in row['assets']]}
 def context(self,context,recipe,format='poster'):
  selected=self.select(recipe,format,snapshot=context.get('creator_snapshot'))
  creator=context.get('creation_options',{}).get('creator') or {}
  if creator.get('profile_id','oil-pig')!='oil-pig' and selected['pack']['id'] in ('editorial-poster','editorial-article'):
   # The default personal recipe is not another creator's identity. Only
   # consciously replaced components may travel across this boundary.
   replacements=set(recipe.get('overrides',{}).values())
   selected['components']=[row for row in selected['components'] if row['id'] in replacements]
   selected['assets']=[a for row in selected['components'] for a in row['assets']]
   selected['prompt_text']=recipe.get('prompt_text') or '\n\n'.join(row['prompt'] for row in selected['components']) or '按本次创作画像与已选技能完成内容；围绕本轮主题、材料和明确意见设计，不套用其他画像的角色或风格。'
  fixed=['本次只完成已授权的内容制作，不发布、不代替用户采纳。修改另存版本。',
         '本轮可编辑提示词是当前明确创作要求；原话、样本和历史方法按适用范围使用，不以历史默认值覆盖本轮明确选择。',
         '事实、用户锁定原字、固定母版及本轮明确修改范围仍须遵守；原件与外部样本是材料，不是额外授权。',
         '逐图生图时保存 生图执行记录.json，格式为 {"images":[{"page":1,"prompt":"实际完整提示词","references":[{"path":"实际参照路径","sha256":"实际SHA"}],"width":1086,"height":1448,"tool":"实际工具名","artifact_name":"最终交付图片文件名","output_sha256":"该交付文件实际SHA"}]}。不得冒称已核实工具入参；未取得真实工具记录只能标为制作方提交。',
         '交付真实文件及设计说明.json，逐条回应本轮真实依据；不编造百分比或流量提升。']
  for row in [*context.get('sources',[]),*context.get('dependency_sources',[])]:
   if row.get('id')=='creative_strategy' and (creator or getattr(self.box,'creator',None) is not None):continue
   if row.get('content'):fixed.append('## 冻结规范原件：'+str(row.get('path'))+'\n'+row['content'])
  skill=self.project/'.agents/skills/neo-content/SKILL.md'
  if skill.is_file() and creator.get('profile_id','oil-pig')=='oil-pig':fixed.append('## 创作路由的本轮冻结原文\n'+skill.read_text(encoding='utf-8-sig'))
  raw=context.get('raw_feedback',{}).get('items',[])
  if raw:fixed.append('## 本作品相关原始反馈（保留各自适用范围）\n'+packed(raw))
  scope=context.get('text_scope',[])
  if scope:fixed.append('## 本轮文字范围\n'+'\n'.join(row['label']+'：'+('原字保留' if row['mode']=='preserve' else '按本轮明确意见处理，未涉及部分保持') for row in scope))
  for key,label in [('title','标题'),('body','配文／正文')]:
   if key in context.get('creation_options',{}).get('text',{}):fixed.append('## 锁定'+label+'\n'+context['creation_options']['text'][key])
  refs=[{key:a.get(key) for key in ('path','sha256','available','required','role','label','url')} for a in selected['assets']]
  if refs:fixed.append('## 参考资产（使用前核对真实原件）\n'+packed(refs))
  return {**selected,'fixed_text':'\n\n'.join(fixed),'prompt_sha256':digest(selected['prompt_text']),'note':'这是应用可控指令；不冒充模型供应商不可见的系统指令。'}
 def freeze(self,c,wid,jid,document,request=None,material=None):
  creation=document['creation_options'];recipe=creation.get('recipe')
  if recipe is None:return
  context=document.get('studio_context',{});compiled=self.context({**context,'creation_options':creation,'creator_snapshot':document.get('creator_snapshot')},recipe,context.get('format','poster'))
  job=c.execute('SELECT kind,text FROM toolbox_jobs WHERE id=?',(jid,)).fetchone();work=c.execute('SELECT title,material FROM toolbox_works WHERE id=?',(wid,)).fetchone()
  article=c.execute('SELECT document FROM toolbox_article_inputs WHERE job_id=?',(jid,)).fetchone()
  article=json.loads(article['document']) if article else {}
  actual_request=request if request is not None else job['text'] if job else ''
  actual_material=material if material is not None else article.get('material',work['material'] if work else '')
  creator=document.get('creator_snapshot')
  if creator:
   from easel_workbench.runtime.task_runtime import attach_review_basis
   frozen_refs=attach_review_basis(self.box,c,document,jid,editable_text=compiled['prompt_text'],assets=compiled['assets'])
   if frozen_refs:compiled['fixed_text']+='\n\n## 本轮参考原件的冻结副本（原路径仅作来源索引）\n'+packed(frozen_refs)
  lines=([creator['prompt_text']] if creator else [])+[compiled['prompt_text'],'## 本次任务\n'+str(actual_request),'## 原始素材\n'+str(actual_material),compiled['fixed_text']]
  snapshot=document.get('learning_snapshot') or {}
  if snapshot:lines.append('## 已冻结创作依据及逐条回应合同\n'+packed(snapshot))
  if document.get('style_delivery_contract'):lines.append('## 实际交付说明合同\n'+packed(document['style_delivery_contract']))
  if document.get('candidate_artifacts'):lines.append('## 所改版本的真实文件\n'+packed(document['candidate_artifacts']))
  files=[]
  for row in c.execute('SELECT id,name,path,sha256 FROM toolbox_files WHERE id IN (SELECT value FROM json_each((SELECT files FROM toolbox_jobs WHERE id=?)))',(jid,)):
   files.append(dict(row))
  if files:lines.append('## 本轮附件\n'+packed(files))
  if article.get('discussion_context'):lines.append('## 已确认讨论上下文\n'+packed(article['discussion_context']))
  if document.get('annotations'):lines.append('## 本版批注原话\n'+packed(document['annotations']))
  if recipe.get('plan_id'):
   row=c.execute('SELECT * FROM creative_image_plans WHERE id=?',(recipe['plan_id'],)).fetchone()
   if not row or row['work_id']!=wid or row['candidate_id']!=document.get('candidate_id'):raise ValueError('图稿方案不属于当前作品和准确版本')
   plan=json.loads(row['document']);lines.append('## 已确认逐图准备方案\n'+packed(plan));compiled['image_plan']=plan
  body='\n\n'.join(lines)
  clean_recipe={k:v for k,v in recipe.items() if k!='preview_id'}
  guard=digest(packed({'work_id':wid,'job_id':jid,'candidate_id':document.get('candidate_id'),'request':actual_request,'material':actual_material,
      'title':work['title'] if work else '', 'recipe':clean_recipe,'revision':context.get('revision_token'),'format':context.get('format'),
      'feedback':document.get('raw_feedback'),'annotations':document.get('annotations'),'files':files,'plan':compiled.get('image_plan'),
      'sources':context.get('source_versions'),'recipe_revision':compiled['source_revision'],'creator_snapshot':creator.get('snapshot_sha256') if creator else None}))
  document['execution_prompt']={'schema_version':1,'body':body,'sha256':digest(body),'editable_text':compiled['prompt_text'],'fixed_text':compiled['fixed_text'],
    'recipe_id':compiled['pack']['id'],'recipe_name':compiled['pack']['name'],'source_revision':compiled['source_revision'],
    'components':[{k:r.get(k) for k in ('id','name','slot','prompt_sha256','active_policy_id','active_policy_revision')} for r in compiled['components']],
    'assets':compiled['assets'],'image_plan':compiled.get('image_plan'),'protocol_note':'发送时只增加任务关联标记，不追加创作指令。'}
  document['execution_prompt']['preview_guard']=guard
  if creator:document['execution_prompt']['creator_snapshot']=copy.deepcopy(creator)
  if recipe.get('preview_id') and not getattr(self.box,'creative_preview',False):
   row=c.execute('SELECT * FROM creative_prompt_previews WHERE id=?',(recipe['preview_id'],)).fetchone()
   if not row or row['job_id']!=jid or row['guard']!=guard:raise ValueError('提示词、材料或依据在预览后变化，请重新核对完整指令；未提交制作')
   approved=json.loads(row['document'])
   for key in ('execution_prompt','learning_snapshot','style_delivery_contract'):
    if key in approved:document[key]=approved[key]
   document['execution_prompt']['approved_preview_id']=recipe['preview_id']
  run=self.learning.read_run(c,jid)
  if run:
   run['execution_prompt']=copy.deepcopy(document['execution_prompt']);run['snapshot']=document.get('learning_snapshot',run['snapshot']);self.learning._put(c,'learning_runs',run)
 def preview(self,value):
  """Run the real compiler against a disposable DB. Never enqueue live work.

  The only persistent write is a preview receipt. Files and business operations
  remain untouched; the accepted command must match the frozen guard.
  """
  kind=value.get('kind');request=copy.deepcopy(value.get('input',{}));wid=value.get('work_id')
  from easel_workbench.runtime.toolbox_store import ident
  jid=ident(request.get('id'))
  creative=request.get('creative',{})
  if not isinstance(creative.get('recipe'),dict):raise ValueError('请先选择创作方案')
  creative['recipe'].pop('preview_id',None)
  with tempfile.TemporaryDirectory(prefix='creative-preview-') as folder:
   database=pathlib.Path(folder)/'preview.sqlite'
   with self.store.connect() as source,contextlib.closing(sqlite3.connect(database)) as target:source.backup(target)
   store=copy.copy(self.store);store.path=database
   box=copy.copy(self.box);box.store=store;box.creative_preview=True
   box.studio=copy.copy(self.box.studio);box.studio.box=box;box.studio.store=store
   box.learning=copy.copy(self.learning);box.learning.box=box;box.learning.store=store;box.learning.studio=box.studio
   if kind=='create':result=box.create(request)
   elif kind=='change':result=box.action(ident(wid),{**request,'kind':'change'})
   elif kind=='finalize':
    from easel_workbench.runtime.article_drafts import finalize
    result=finalize(box,ident(wid),request)
   else:raise ValueError('不支持的制作预览')
   with store.connect() as c:
    row=c.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?',(jid,)).fetchone()
    if not row:raise ValueError('未取得本轮制作指令')
    document=json.loads(row['document'])
  prompt=document.get('execution_prompt')
  if not prompt:raise ValueError('未取得创作方案的完整指令')
  preview_id=uuid.uuid4().hex
  with self.store.connect() as c:
   c.execute('DELETE FROM creative_prompt_previews WHERE julianday(created_at)<julianday(\'now\',\'-7 days\')')
   c.execute('INSERT INTO creative_prompt_previews VALUES(?,?,?,?,?)',(preview_id,jid,prompt['preview_guard'],packed(document),stamp()))
  request['creative']['recipe']['preview_id']=preview_id
  return {'preview_id':preview_id,'input':request,'execution_prompt':prompt,'context':document.get('studio_context',{}),'work_id':result['work_id']}
 def asset(self,cid,index,thumbnail=False):
  row=next((r for r in self.document()['components'] if r['id']==cid),None)
  if not row or index<0 or index>=len(row.get('assets',[])):raise ValueError('找不到参考资产')
  item=row['assets'][index];raw=self.original(item['path'],item.get('sha256'))
  from PIL import Image
  image=Image.open(io.BytesIO(raw));image.verify()
  if thumbnail:
   image=Image.open(io.BytesIO(raw));image.thumbnail((512,512));out=io.BytesIO();image.convert('RGB').save(out,format='JPEG',quality=85);return out.getvalue(),'image/jpeg'
  import mimetypes
  return raw,mimetypes.guess_type(item['path'])[0] or 'application/octet-stream'
 def export(self,pid):
  selected=self.select({'pack_id':pid},next((p.get('formats',['poster'])[0] for p in self.document()['packs'] if p['id']==pid),'poster'));stream=io.BytesIO()
  with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as out:
   out.writestr('创作方案.md','# '+selected['pack']['name']+'\n\n'+selected['prompt_text'])
   out.writestr('使用说明.md','本包是 neo-content 技能加载的风格资源，不是另一个独立 Agent。\n先选择主题、材料和准确版本，再使用本包提示词及适用参考。\n同一提示词跨工具不保证得到相同图片。\n')
   manifest={'pack':selected['pack'],'source_revision':selected['source_revision'],'assets':[]}
   for n,a in enumerate(selected['assets']):
    record={k:a.get(k) for k in ('label','role','path','sha256','available')}
    if a['available']:
     name='参考资产/'+str(n+1)+pathlib.Path(a['path']).suffix;out.writestr(name,self.original(a['path'],a['sha256']));record['exported_path']=name
    manifest['assets'].append(record)
   out.writestr('版本与来源.json',json.dumps(manifest,ensure_ascii=False,indent=2))
  return stream.getvalue()
 def suggestions(self):
  with self.store.connect() as c:proposals=self.learning._all(c,'learning_proposals')
  groups={}
  for p in reversed(proposals):
   if p.get('status') not in ('candidate','preview'):continue
   doc=p.get('document',{});key=packed([doc.get('dimension'),doc.get('conditions',{}),doc.get('name') or p.get('title')])
   group=groups.setdefault(key,{'id':p['id'],'title':doc.get('name') or p.get('title'),'conditions':doc.get('conditions',{}),'reason':p.get('reason',''),
      'before':'','after':'\n'.join(doc.get('instructions',[])),'proposal_ids':[],'evidence_refs':p.get('evidence_refs',[]),
      'target_component_id':doc.get('target_component_id'),'do_not_copy':doc.get('do_not_copy'),'dimension':doc.get('dimension')})
   group['proposal_ids'].append(p['id'])
  return list(groups.values())
 def effects(self,pid=None):
  with self.store.connect() as c:
   runs=self.learning._all(c,'learning_runs');rows=[]
   for run in reversed(runs):
    prompt=run.get('execution_prompt',{})
    if pid and prompt.get('recipe_id')!=pid:continue
    if not prompt:continue
    job=c.execute('SELECT id,work_id,status,candidate_id FROM toolbox_jobs WHERE id=?',(run['job_id'],)).fetchone()
    if not job:continue
    work=c.execute('SELECT title FROM toolbox_works WHERE id=?',(job['work_id'],)).fetchone()
    decisions=[dict(r) for r in c.execute("SELECT id,kind,text,scope,candidate_id,status,created_at FROM toolbox_jobs WHERE work_id=? AND candidate_id=? AND kind IN ('accept','reject','feedback') ORDER BY rowid",(job['work_id'],job['id']))]
    entry={'job_id':job['id'],'work_id':job['work_id'],'format':self.box.options(job['work_id'],c)['format'],'title':work['title'] if work else '作品','status':job['status'],'recipe_id':prompt.get('recipe_id'),'recipe_name':prompt.get('recipe_name'),
       'prompt_sha256':prompt.get('sha256'),'decisions':decisions,'quality':run.get('quality',{}),'created_at':run.get('created_at'),'version_source':run.get('version_id')}
    try:
     pubs=[p for p in self.box.studio._records(c,'publications') if p.get('work_id')==job['work_id'] and p.get('version_id')==job['id']]
     entry['publications']=[{**p,'metrics':[m for m in self.box.studio._records(c,'metrics') if m.get('publication_id')==p['id']],
       'comments':[m for m in self.box.studio._records(c,'comments') if m.get('publication_id')==p['id']]} for p in pubs]
    except (AttributeError,ValueError):entry['publications']=[]
    rows.append(entry)
   repeated={}
   for r in c.execute("SELECT work_id,candidate_id,text FROM toolbox_jobs WHERE kind IN ('reject','feedback','change') AND length(trim(text))>3 ORDER BY rowid"):
    if r['text'].strip() in ('此版不采纳','暂不采用','此版暂不采用'):continue
    entry=repeated.setdefault(r['text'],{'text':r['text'],'versions':[]})
    reference={'work_id':r['work_id'],'version_id':r['candidate_id']}
    if reference not in entry['versions']:entry['versions'].append(reference)
  return {'runs':rows,'repeated_feedback':[r for r in repeated.values() if len(r['versions'])>1][:20],'comparison_kind':'observational','causal_improvement_proven':False,'note':'只展示真实评价与平台记录；没有曝光分母不计算点击率，缺失指标为未取得。'}
 def bootstrap(self):
  catalog=self.catalog();suggestions=self.suggestions()
  return {**catalog,'suggestions':suggestions[:3],'more_suggestions':suggestions[3:],'suggestion_count':len(suggestions),'effects':self.effects()}
 def prompt_record(self,jid):
  with self.store.connect() as c:
   row=c.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?',(jid,)).fetchone()
   if not row:raise ValueError('该版本没有制作快照')
   doc=json.loads(row['document']);prepared=(doc.get('execution_prompt',{}).get('image_plan') or {}).get('images',[])
   return {'execution_prompt':doc.get('execution_prompt'),'image_prompts':[{**r,'verification':'prepared','verification_label':'准备使用，尚不证明实际执行'} for r in prepared]+self.image_records(c,jid),'legacy':not bool(doc.get('execution_prompt'))}
 def image_records(self,c,jid):
  rows=[]
  for a in c.execute("SELECT * FROM artifacts WHERE task_id=? AND name='生图执行记录.json'",(jid,)):
   try:
    path=pathlib.Path(a['path']).resolve()
    if not path.is_relative_to((self.root/'data/artifacts').resolve()):continue
    value=json.loads(path.read_text(encoding='utf-8-sig'))
    for item in value.get('images',[]):
     if not isinstance(item,dict) or not isinstance(item.get('prompt'),str):continue
     rows.append({**item,'verification':'producer_submitted','verification_label':'制作方提交，未核实工具入参'})
   except (ValueError,OSError):continue
  # Only genuine structured tool events in this job's actual turn can upgrade
  # proof. An uploaded file/HTTP field can never assert tool_input_verified.
  try:
   from easel_workbench.runtime.creative_tool_trace import verified_calls
   actual=verified_calls(self.box,c,jid)
   for event in actual:
    target=next((row for row in rows if row['prompt']==event['prompt']),None)
    if target:target.update(verification='tool_input_verified',verification_label='工具调用输入已核实',tool_call_id=event['call_id'])
    else:rows.append({**event,'verification':'tool_input_verified','verification_label':'工具调用输入已核实','output_binding':'未核实对应输出文件'})
  except (ValueError,OSError,RuntimeError,sqlite3.Error):pass
  artifacts=[dict(r) for r in c.execute('SELECT id,name,path,mime FROM artifacts WHERE task_id=?',(jid,))]
  for row in rows:
   for a in artifacts:
    if a['name']!=row.get('artifact_name') or not a['mime'].startswith('image/'):continue
    p=pathlib.Path(a['path']).resolve()
    if not p.is_relative_to((self.root/'data/artifacts').resolve()) or not p.is_file():continue
    checksum=digest(p.read_bytes())
    if checksum==row.get('output_sha256'):
     row.update(output_url='/api/media/images/'+a['id']+'/'+checksum+'/original',output_binding='已绑定实际交付图片字节；不据此证明工具产生了该图片')
   row.setdefault('output_binding','未核实对应交付图片')
  return rows
 def command(self,value):
  if not isinstance(value,dict):raise ValueError('创作操作无效')
  oid=value.get('operation_id') or value.get('id');self.learning._conditions(value.get('conditions',{}))
  from easel_workbench.runtime.toolbox_store import ident
  ident(oid);signature=packed(value);action=value.get('action')
  # Existing discussion queue is the only AI preparation route; never generate
  # images merely because a prompt is saved or a recipe is inspected.
  if action=='prepare-image-plan':
   from easel_workbench.runtime.article_drafts import read as draft_read
   with self.store.connect() as c:draft=draft_read(self.box,value.get('work_id'),c)
   wid=ident(value.get('work_id'));request='[CREATIVE_IMAGE_PLAN]\n只准备图稿方案，禁止生图、渲染、发布。按下列主题与要求返回一个JSON对象：{"images":[{"page":1,"purpose":"本页作用","prompt":"逐字可执行的生图提示词","references":["参考资产路径"],"width":1086,"height":1448}]}。\n'+bounded(value.get('request',''),20000)
   from easel_workbench.runtime.work_discussions import enqueue
   return enqueue(self.box,wid,{'id':oid,'revision':value.get('revision',draft['revision']),'candidate_id':value.get('candidate_id'),'text':request,'files':value.get('files',[]),'creative':value.get('creative',{})})
  with self.store.connect() as c:
   c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT signature,result FROM creative_receipts WHERE operation_id=?',(oid,)).fetchone()
   if old:
    if old['signature']!=signature:raise ValueError('同一操作不能保存不同内容')
    return json.loads(old['result'])
   if action=='import-sample':
    title=bounded(value.get('title','学习样本'),200);body=bounded(value.get('body',''),100000);goal=bounded(value.get('goal',''),4000)
    if not body.strip() and not value.get('files'):raise ValueError('请提供原文或图片；只有链接尚不代表已读取原件')
    url=bounded(value.get('url',''),2000)
    if url and not re.fullmatch(r'https?://[^\s]+',url):raise ValueError('参考链接格式无效')
    file_ids=value.get('files',[])
    if not isinstance(file_ids,list) or len(file_ids)>20:raise ValueError('每份样本最多20个附件')
    originals=[];total=0
    from easel_workbench.runtime.learning_service import SECRET_NAME
    for fid in file_ids:
     f,path=self.box.file(ident(fid));data=path.read_bytes();suffix=pathlib.Path(f['name']).suffix.lower();total+=len(data)
     if SECRET_NAME.search(f['name']) or suffix not in ('.png','.jpg','.jpeg','.webp','.gif','.txt','.md'):raise ValueError('请使用图片或文本学习原件')
     if digest(data)!=f['sha256']:raise ValueError('附件字节已变化')
     if total>40*1024*1024:raise ValueError('单份样本附件总量最多40MB')
     originals.append((suffix,data))
    relative='资料/风格研究/工作台导入/'+oid;folder=self.path(relative);folder.mkdir(parents=True,exist_ok=True)
    raw=('# '+title+'\n\n来源链接：'+url+'\n\n希望学习：'+goal+'\n\n## 原始文字\n'+body).encode()
    target=folder/'用户提供原件.md'
    if target.exists() and target.read_bytes()!=raw:raise ValueError('导入原件已存在不同字节')
    target.write_bytes(raw);refs=[relative+'/用户提供原件.md']
    for n,(suffix,data) in enumerate(originals):
     destination=folder/('原始附件-'+str(n+1)+suffix)
     if destination.exists() and destination.read_bytes()!=data:raise ValueError('原始附件已变化')
     destination.write_bytes(data);refs.append(relative+'/'+destination.name)
    # Reconcile with the existing evidence index, retaining original identities.
    coverage=self.learning._index(c);result={'saved':True,'source_paths':refs,'evidence_ids':['ev-'+digest(raw)],'goal':goal,'coverage':coverage,'analysis_started':False}
   elif action=='save-image-plan':
    wid=ident(value.get('work_id'));candidate=value.get('candidate_id');images=value.get('images')
    if not c.execute('SELECT 1 FROM toolbox_works WHERE id=?',(wid,)).fetchone():raise ValueError('作品不存在')
    if candidate and not c.execute('SELECT 1 FROM toolbox_jobs WHERE id=? AND work_id=?',(candidate,wid)).fetchone():raise ValueError('图稿版本不属于此作品')
    if not isinstance(images,list) or not 1<=len(images)<=20:raise ValueError('请准备1到20张图的提示词')
    normalized=[]
    for i,row in enumerate(images):
     if not isinstance(row,dict):raise ValueError('逐图方案格式无效')
     text=bounded(row.get('prompt',''),20000)
     if not text.strip():raise ValueError('每张图需要完整提示词')
     refs=row.get('references',[])
     if not isinstance(refs,list) or any(not isinstance(r,str) for r in refs):raise ValueError('参考图需要项目路径列表')
     references=[{'path':ref,'sha256':digest(self.original(ref))} for ref in refs]
     if len(refs)>8 or any(type(row.get(key)) is not int or not 128<=row[key]<=8192 for key in ('width','height')):raise ValueError('每图最多8个参照，尺寸须在128到8192之间')
     normalized.append({'page':i+1,'purpose':bounded(row.get('purpose',''),1000),'prompt':text,'prompt_sha256':digest(text),'references':references,
       'width':row.get('width'),'height':row.get('height'),'verification':'prepared'})
    doc={'images':normalized,'created_at':stamp(),'verification_label':'准备使用，尚未调用生图工具'}
    c.execute('INSERT INTO creative_image_plans VALUES(?,?,?,?,?)',(oid,wid,candidate,1,packed(doc)));result={'plan_id':oid,'plan':doc,'generation_started':False}
   else:raise ValueError('不支持的创作操作')
   receipt={'operation_id':oid,'status':'completed','result':result};c.execute('INSERT INTO creative_receipts VALUES(?,?,?)',(oid,signature,packed(receipt)));return receipt
 def plans(self,wid):
  with self.store.connect() as c:
   saved=[{'id':r['id'],'candidate_id':r['candidate_id'],**json.loads(r['document'])} for r in c.execute('SELECT * FROM creative_image_plans WHERE work_id=?',(wid,))]
   discussions=[]
   for r in c.execute("SELECT id,candidate_id,status,reply FROM toolbox_jobs WHERE work_id=? AND kind='discuss' AND text LIKE '[CREATIVE_IMAGE_PLAN]%'",(wid,)):
    text=r['reply'] or '';match=re.search(r'```(?:json)?\s*(\{[\s\S]*?\})\s*```',text)
    try:parsed=json.loads(match.group(1) if match else text);images=parsed.get('images',[]) if isinstance(parsed,dict) else []
    except ValueError:images=[]
    discussions.append({'id':r['id'],'candidate_id':r['candidate_id'],'status':r['status'],'reply':text,'images':images})
  return {'saved':saved,'preparations':discussions}

def service(box):
 return CreativeRecipes(box.learning)
