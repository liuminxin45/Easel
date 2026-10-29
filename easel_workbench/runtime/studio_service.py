"""Durable studio commands over existing works and canonical project documents.

Only historical snapshots/proposals live in SQLite. Active rules remain the
allowlisted project files. No platform publication or synthetic AI execution.
"""
import contextlib,copy,datetime as dt,difflib,hashlib,json,os,pathlib,re,shutil,uuid
from easel_workbench.runtime.desk import ROOT,PROJECT,THREAD,stamp
from easel_workbench.runtime.toolbox_store import ident,pack,text
from easel_workbench.runtime.content_studio import AXES,DEFAULT,BUILTINS,catalog as preset_catalog,source as version_source,options as creative_options
from easel_workbench.runtime.feedback_ledger import locked
from easel_workbench.runtime.semantic_style import intent as semantic_intent,resolve as resolve_intent,applicability as style_applicability

SECTIONS={
 'position':('我们是谁','规范/定位与编辑原则.md'),
 'audience':('读者是谁','规范/定位与编辑原则.md'),
 'standards':('内容标准','规范/内容总规格.md'),
 'style':('写法与风格','规范/写作要求.md'),
 'workflow':('生产流程','自动化/工作流/README.md'),
 'capabilities':('工具与技能入口','.agents/skills/neo-content/SKILL.md')}
CONFIG_PATH='自动化/工作流/工作台设置.json'
CONTEXT_FILES={'project_rules':'AGENTS.md','image_rules':'规范/图片制作要求.md','poster_rules':'规范/公众号贴图写作要求.md','layout_rules':'规范/公众号排版要求.md','review_rules':'规范/文章批注与改稿要求.md','archive_rules':'规范/存档规范.md','publication_rules':'规范/发布与归档要求.md','creative_strategy':'规范/创作策略.json'}
METRICS=('views','likes','comments','saves','shares','impressions','clicks','follows')
CATEGORIES=('question','praise','misunderstanding','correction','style','other')

class StudioConflict(ValueError):pass
class StudioUnavailable(ValueError):pass
def sha(data):return hashlib.sha256(data).hexdigest()
def fingerprint(value):return sha(pack(value).encode('utf-8'))
def clone(value):return copy.deepcopy(value)
def when(value,label='时间',nullable=False):
 if value is None and nullable:return None
 if not isinstance(value,str):raise ValueError(label+'需要带时区的时间')
 try:parsed=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
 except ValueError:raise ValueError(label+'无效')
 if parsed.tzinfo is None:raise ValueError(label+'需要明确时区')
 return value
def valid_url(value):return isinstance(value,str) and bool(re.match(r'^https?://[^\s/]+(?:/[^\s]*)?$',value))
def atomic_bytes(path,data):
 path.parent.mkdir(parents=True,exist_ok=True);tmp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
 try:
  with tmp.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
  os.replace(tmp,path)
 finally:
  if tmp.exists():tmp.unlink()
def default_configuration():
 def step(key,name,actor='AI',required=False):return {'id':key,'name':name,'enabled':True,'required':required,'actor':actor,'capability_id':key,'input':'当前素材与已确认要求','output':'有来源的执行记录','checkpoint':'保留实际限制'}
 return {'schema_version':1,'default_preset_id':'clear','values':clone(BUILTINS[0]['values']),
  'channels':{'wechat':{'id':'wechat','name':'公众号','values':{}},'xiaohongshu':{'id':'xiaohongshu','name':'小红书','values':{}}},
  'default_workflow_id':'default','workflows':{'default':{'id':'default','name':'通用内容流程','steps':[
   step('sources','收集与核对直接来源'),step('fact-check','核查事实与证据',required=True),step('production','固定会话制作'),step('human-review','人类明确评审','人类',True),step('archive','按决定记录与归档')]}}}

class StudioService:
 def __init__(self,box,project=None,wiki=None,root=None):
  self.box=box;self.store=box.store;self.root=pathlib.Path(root or box.root).resolve()
  self.project=pathlib.Path(project if project is not None else PROJECT if self.root==pathlib.Path(ROOT).resolve() else self.root/'content-project').resolve()
  with self.store.connect() as c:c.executescript('''
CREATE TABLE IF NOT EXISTS studio_records(category TEXT NOT NULL,id TEXT NOT NULL,revision INTEGER NOT NULL,document TEXT NOT NULL,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,PRIMARY KEY(category,id));
CREATE TABLE IF NOT EXISTS studio_operations(operation_id TEXT PRIMARY KEY,action TEXT NOT NULL,signature TEXT NOT NULL,status TEXT NOT NULL,result TEXT,created_at TEXT NOT NULL);
''')
 def _records(self,c,category):return [json.loads(row['document']) for row in c.execute('SELECT document FROM studio_records WHERE category=? ORDER BY created_at,rowid',(category,))]
 def _get(self,c,category,key,required=True):
  row=c.execute('SELECT document FROM studio_records WHERE category=? AND id=?',(category,key)).fetchone()
  if not row and required:raise ValueError('找不到对应记录：'+category)
  return json.loads(row['document']) if row else None
 def _put(self,c,category,document,new=False):
  document=clone(document);old=self._get(c,category,document['id'],False);now=stamp()
  if new and old:raise StudioConflict('记录已经存在，请核对原操作回执')
  document['revision']=(old['revision'] if old else 0)+1;document.setdefault('created_at',old['created_at'] if old else now);document['updated_at']=now
  c.execute('INSERT OR REPLACE INTO studio_records VALUES(?,?,?,?,?,?)',(category,document['id'],document['revision'],pack(document),document['created_at'],now));return document
 def _expected(self,document,value):
  if type(value.get('expected_revision')) is not int or value['expected_revision']!=document['revision']:raise StudioConflict('这份记录已变化，请核对最新版本；原输入仍保留')
 def _path(self,relative):
  if relative not in {path for _,path in SECTIONS.values()}|{CONFIG_PATH}|set(CONTEXT_FILES.values()):raise ValueError('不在允许读取的项目文件范围')
  result=self.project/relative
  for part in (result,*result.parents):
   if part==self.project:break
   if part.is_symlink() or getattr(part,'is_junction',lambda:False)():raise ValueError('不维护链接目录或文件')
  if not result.resolve().is_relative_to(self.project):raise ValueError('项目文件路径无效')
  return result
 def _file(self,relative):
  path=self._path(relative);raw=path.read_bytes() if path.is_file() else None
  if raw is not None and len(raw)>2_000_000:raise ValueError('规范文件过长，请在项目中维护')
  return {'path':relative,'content':raw.decode('utf-8-sig') if raw is not None else '', 'revision':sha(raw) if raw is not None else None,'exists':raw is not None,'utf8_bom':bool(raw and raw.startswith(b'\xef\xbb\xbf'))}
 def _configuration(self):
  entry=self._file(CONFIG_PATH);document=json.loads(entry['content']) if entry['exists'] else default_configuration();self._validate_config(document)
  return {**entry,'document':document}
 def _validate_config(self,document):
  from easel_workbench.runtime.content_studio import weights
  if not isinstance(document,dict) or type(document.get('schema_version')) is not int or document.get('schema_version') not in (1,2):raise ValueError('工作台设置需要schema_version 1或2')
  if document['schema_version']==1:weights(document.get('values'))
  else:
   semantic_intent(document.get('intent',{}))
   if 'values' in document:self._partial_weights(document['values'])
  channels=document.get('channels');flows=document.get('workflows')
  if not isinstance(channels,dict) or not channels or any(not isinstance(item,dict) or item.get('id')!=key for key,item in channels.items()):raise ValueError('渠道设置无效')
  for item in channels.values():self._partial_weights(item.get('values',{}));semantic_intent(item.get('intent',{}))
  if not isinstance(flows,dict) or document.get('default_workflow_id') not in flows:raise ValueError('默认流程不存在')
  for key,flow in flows.items():
   if not isinstance(flow,dict) or flow.get('id')!=key:raise ValueError('流程身份无效')
   self._validate_steps(flow.get('steps'))
  if len(pack(document))>200000:raise ValueError('工作台设置过长')
 def _validate_steps(self,steps):
  if not isinstance(steps,list) or not 2<=len(steps)<=40 or len({row.get('id') for row in steps})!=len(steps):raise ValueError('流程需要独立有序步骤')
  positions={row['id']:index for index,row in enumerate(steps)}
  if 'fact-check' not in positions or 'human-review' not in positions or positions['fact-check']>=positions['human-review']:raise ValueError('必须保留事实核查先于人类评审的关口')
  for row in steps:
   ident(row.get('id'));text(row.get('name',''),200,True)
   if type(row.get('enabled')) is not bool or type(row.get('required')) is not bool:raise ValueError('流程启用状态无效')
   if row['id'] in ('fact-check','human-review') and (not row['enabled'] or not row['required']):raise ValueError('事实核查与人类评审不能停用或删除')
   if row['id']=='human-review' and (row.get('actor')!='人类' or row.get('capability_id')!='human-review'):raise ValueError('人类评审不能改为AI审批')
   if row['id']=='production' and not positions['fact-check']<positions[row['id']]<positions['human-review']:raise ValueError('制作必须在核查之后、评审之前')
   if row['id']=='archive' and positions[row['id']]<positions['human-review']:raise ValueError('归档必须在人类评审之后')
   # Template text is data. No arbitrary executable command or plugin can enter.
   if set(row)-{'id','name','enabled','required','actor','capability_id','input','output','checkpoint'}:raise ValueError('流程只接收声明步骤，不接受任意命令')
 def _partial_weights(self,values):
  if not isinstance(values,dict) or any(key not in DEFAULT or type(n) is not int or not 0<=n<=100 for key,n in values.items()):raise ValueError('参数需要是六项中的0到100整数')
 def foundation(self):
  sections=[{'id':key,'title':label,**self._file(path),'editable':self.project.is_dir()} for key,(label,path) in SECTIONS.items()]
  with self.store.connect() as c:changes=self._records(c,'changes')
  for change in changes:
   current=self._file(change['path']);change['current_revision']=current['revision'];change['stale']=change['status']=='draft' and change['before_revision']!=current['revision'];change['can_confirm']=change['status']=='draft' and not change['stale']
  return {'sections':sections,'changes':changes,'configuration':self._configuration(),'available':self.project.is_dir()}
 def capabilities(self):
  skill=self.project/'.agents/skills/neo-content/SKILL.md';helper=self.project/'工具/贴图生产/cli.mjs'
  rows=[{'id':'neo-content','name':'neo-content唯一制作方法','status':'documented' if skill.is_file() else 'unavailable','evidence':[{'path':str(skill),'sha256':sha(skill.read_bytes()) if skill.is_file() else None}],'description':'现行方法文件；文件存在不代表本轮已执行','read_only':True},
   {'id':'production','name':'指定Codex会话制作','status':'configured','evidence':['toolbox_jobs','01a11bd2-b03c-7441-aba5-2feb69d193ea'],'note':'固定会话已配置；可用性以实际任务回执为准，不等于已登录或本次成功','read_only':True},
   {'id':'poster-tools','name':'贴图工具','status':'local-code' if helper.is_file() else 'unavailable','evidence':[{'path':str(helper),'sha256':sha(helper.read_bytes()) if helper.is_file() else None}],'description':'可核对本地程序字节；未因此声称依赖就绪或实测成功','read_only':True},
   {'id':'sources','name':'直接来源核对','status':'configured','evidence':['poster_executor.prompt_for','work_discussions.prompt'],'description':'由固定会话按来源执行，真实取材范围以交付回执为准','read_only':True},
   {'id':'fact-check','name':'事实与证据检查','status':'configured','evidence':[str(self.project/'工具/内容工作流/creative_review.py')],'description':'固定流程要求的检查关口，不把程序检查当成事实或人类认可','read_only':True},
   {'id':'human-review','name':'人类明确评审','status':'manual','evidence':['toolbox_jobs.accept/reject'],'description':'由用户明确版本与范围，保留最后决定及全部历史','read_only':True},
   {'id':'archive','name':'按明确决定归档','status':'configured','evidence':[str(self.project/'工具/内容工作流/poster_review.py')],'description':'沿用既有归档任务，是否完成以实际任务回执为准','read_only':True},
   {'id':'platform-data','name':'平台数据','status':'manual','evidence':['手工核对或用户导出文件'],'note':'公众号与小红书未接自动取数接口','read_only':True}]
  return rows
 def context(self,work_id,options=None,connection=None,candidate_id=None,exclude_job_id=None,request_text=None,task_kind=None,creator_snapshot=None):
  with self.store.connect() if connection is None else contextlib.nullcontext(connection) as c:
   sources=[{'id':key,**self._file(path)} for key,(_,path) in SECTIONS.items()];dependencies=[{'id':key,**self._file(path)} for key,path in CONTEXT_FILES.items()];settings=self._get(c,'contexts',work_id,False) if work_id else None;settings=settings or {'id':work_id,'revision':0,'channel_id':'wechat','workflow_id':None,'overrides':{},'round':{}}
   incoming=creative_options(options);workspace=incoming.get('workspace') or {}
   actual_format=(options or {}).get('format') or (self.box.options(work_id,c)['format'] if work_id else 'poster')
   execution_task=task_kind if task_kind in ('discuss','analysis','research','reference','learning','image') else actual_format
   explicit_runtime=bool(incoming.get('creator') or getattr(self.box,'creator',None) is not None)
   if explicit_runtime:
    from easel_workbench.runtime.task_runtime import workflow_template
    from easel_workbench.runtime.creator_runtime import read_owner
    owner=read_owner(c,work_id) if work_id else None
    if not incoming.get('creator') and owner:incoming['creator']={'profile_id':owner['profile_id'],'profile_revision':owner['profile_revision']}
    if task_kind is None:
     selected_ids={r['id'] for r in incoming.get('creator',{}).get('skills',[])}
     for sid,alias in [('topic-research','discuss'),('reference-analysis','reference'),('publication-analysis','analysis'),('experience-distillation','learning')]:
      if selected_ids=={sid}:execution_task=alias
    flow_template=workflow_template(execution_task)
    configuration={'revision':'explicit-runtime-v1','document':{'default_workflow_id':'explicit','default_preset_id':'inherit','values':{},
      'channels':{'wechat':{'id':'wechat','name':'公众号'},'xiaohongshu':{'id':'xiaohongshu','name':'小红书'}},'workflows':{'explicit':flow_template}}}
    dependencies=[row for row in dependencies if row['id']!='creative_strategy']
   else:configuration=self._configuration()
   config=configuration['document']
   creator=incoming.get('creator') or {};creator_id=creator.get('profile_id','oil-pig')
   prepared=None
   if creator_snapshot is not None:
    from easel_workbench.runtime.task_runtime import validated_snapshot
    prepared=validated_snapshot(creator_snapshot,execution_task,creator)
   if creator_id!='oil-pig':
    from easel_workbench.runtime.creator_runtime import service as creator_service
    profile_snapshot=prepared if prepared is not None else creator_service(self.box,c).resolve(creator_id,task=execution_task,skill_refs=creator.get('skills'),
      allow_trial=creator.get('trial') is True,profile_revision=creator.get('profile_revision'),c=c,allow_historical_profile=bool(work_id))
    profile=profile_snapshot['profile']
    sources=[r for r in sources if r['id'] not in ('position','audience','style','capabilities','workflow')]
    dependencies=[r for r in dependencies if r['id'] not in ('creative_strategy','image_rules','poster_rules','project_rules')]
    for key,label in [('position','identity'),('audience','audience'),('style','voice')]:
     content=profile.get(label,'')+'\n'+profile.get('boundaries','')
     sources.append({'id':key,'path':'creator_profile/'+creator_id+'/v'+str(profile['revision']),'content':content,'revision':fingerprint(content),'exists':True})
   if 'recipe' not in incoming:
    for layer in ('overrides','round'):
     if settings.get(layer,{}).get('recipe'):
      from easel_workbench.runtime.creative_recipes import parse_recipe
      incoming['recipe']=parse_recipe(settings[layer]['recipe'])
   if not isinstance(workspace,dict):raise ValueError('本次工作台设置无效')
   channel_id=workspace.get('channel') or settings.get('channel_id');flow_id='explicit' if explicit_runtime else workspace.get('flow_id') or settings.get('workflow_id') or config['default_workflow_id']
   if channel_id not in config['channels'] or flow_id not in config['workflows']:raise ValueError('所选渠道或流程不存在')
   channel=config['channels'][channel_id];flow=config['workflows'][flow_id];values={};request={}
   if incoming['schema_version']==1 and options and incoming['enabled']:request={'values':incoming['values']}
   elif incoming['schema_version']==2:request={'intent':incoming['intent']}
   parts=[('global',config),('channel',channel),('work',settings.get('overrides',{})),('round',settings.get('round',{})),('request',request)]
   resolved=resolve_intent(parts)
   for _,part in parts:values.update(part.get('values',{}))
   effective={}
   for _,part in parts:
    for key in ('goal','audience','position','standards','style_guidance','reader_goal','target','keep_text','text','fixed_master'):
     if key in part:effective[key]=clone(part[key])
   effective.update(values=values,intent=resolved['intent'],preset_id=incoming['preset_id'] if options and incoming['preset_id']!='inherit' else config.get('default_preset_id','clear'))
   positioning=next((item['content'] for item in sources if item['id']=='position'),'');goal=re.search(r'统一阅读理由[：:]([^。\n]+。?)',positioning)
   effective.update(channel=channel_id,flow_id=flow_id,reader_goal=workspace['reader_goal'] if 'reader_goal' in workspace else effective.get('reader_goal',effective.get('goal',goal.group(1) if goal else '')),style_guidance=workspace['style_guidance'] if 'style_guidance' in workspace else effective.get('style_guidance',''))
   if creator_id!='oil-pig':
    for key in ('goal','audience','position','standards','style_guidance','reader_goal'):effective.pop(key,None)
    effective.update(position=profile.get('identity',''),audience=profile.get('audience',''),reader_goal=workspace.get('reader_goal',profile.get('audience','')),style_guidance=workspace.get('style_guidance',profile.get('voice','')))
   creation={**incoming,'schema_version':2,'intent':incoming.get('intent',{}),'resolved_intent':resolved['intent'],'intent_provenance':resolved['provenance'],'legacy_conversions':resolved['legacy_conversions'],'enabled':True,'preset_id':effective['preset_id'],'workspace':{key:effective[key] for key in ('channel','reader_goal','flow_id','style_guidance')}}
   for key in ('target','keep_text','text','fixed_master'):
    if key not in (options or {}) and key in effective:creation[key]=clone(effective[key])
   creation['applicability']=style_applicability(creation)
   work_format=self.box.options(work_id,c)['format'] if work_id and c.execute('SELECT 1 FROM toolbox_works WHERE id=?',(work_id,)).fetchone() else 'poster'
   result={'schema_version':2,'work_id':work_id,'format':(options or {}).get('format',work_format),'sources':sources,'dependency_sources':dependencies,'source_versions':{row['id']:{'path':row['path'],'sha256':row['revision']} for row in [*sources,*dependencies]},'configuration':{'path':CONFIG_PATH,'revision':configuration['revision']},'settings_revision':settings['revision'],'channel':clone(channel),'workflow':clone(flow),'available_workflows':[{'id':item['id'],'name':item['name']} for item in config['workflows'].values()],'available_channels':[{'id':item['id'],'name':item['name']} for item in config['channels'].values()],'capabilities':self.capabilities(),'layers':resolved['layers'],'effective':effective,'semantic_intent':resolved['intent'],'intent_provenance':resolved['provenance'],'legacy_conversions':resolved['legacy_conversions'],'creation_options':creation,'conflicts':resolved['conflicts'],'available':all(row['exists'] for row in sources),'instructions':'仅采用此冻结快照作为本次设置；创作意图按字段逐层继承，旧数字只按原三段阈值兼容解释，不是语义选项的精确比例。规范原件仍是所列项目文件。当前任务不扩大为平台发布或自动调度。'}
   from easel_workbench.runtime.feedback_context import collect as collect_feedback
   result['raw_feedback']=collect_feedback(c,work_id,candidate_id,exclude_job_id)
   from easel_workbench.runtime.revision_scope import conflicts as text_conflicts,scope_summary
   result['text_scope']=scope_summary(creation)
   result['request_conflicts']=text_conflicts(creation,text(request_text or '',10000))
   result['_learning_raw_feedback']=result['raw_feedback']['items']
   from easel_workbench.runtime.learning_execution import enrich_context
   enrich_context(self.box,c,work_id,incoming,result,parts)
   result.pop('_learning_raw_feedback',None)
   learning_revision=(result.get('learning') or {}).get('policy_revision') or (result.get('learning') or {}).get('policy',{}).get('revision')
   revision_basis={'source_versions':result['source_versions'],'configuration':{'revision':configuration['revision']},'settings_revision':settings['revision'],'feedback_revision':result['raw_feedback']['revision']}
   if learning_revision:revision_basis['learning_policy']=learning_revision
   revision_token=fingerprint(revision_basis)
   if (options or {}).get('context_revision') and options['context_revision']!=revision_token:raise StudioConflict('创作基座或作品设置在确认后发生变化，请重新核对本次设置；未提交制作')
   capability_states={row['id']:row['status'] for row in result['capabilities']};result['blockers']=[] if explicit_runtime else [{'step_id':step['id'],'capability_id':step.get('capability_id'),'reason':'所选能力尚未接入或不可访问'} for step in flow['steps'] if step['enabled'] and capability_states.get(step.get('capability_id'),'unavailable')=='unavailable']
   result['revision_token']=revision_token;result['creation_options']['context_revision']=revision_token
   if incoming.get('creator') or getattr(self.box,'creator',None) is not None:
    from easel_workbench.runtime.creator_runtime import service as creator_service
    choice=incoming.get('creator') or {}
    result['creator_snapshot']=prepared if prepared is not None else creator_service(self.box,c).resolve(choice.get('profile_id','oil-pig'),task=execution_task,skill_refs=choice.get('skills'),
      allow_trial=choice.get('trial') is True,profile_revision=choice.get('profile_revision'),c=c,allow_historical_profile=bool(work_id),context={'format':result['format']})
    result['capabilities']=[{'id':row['id'],'name':row['name'],'version':row['version'],'status':'registered','release_status':row['status'],
      'execution_role':row.get('execution_role'),'description':'能力已登记；实际执行与结果见任务回执。'} for row in result['creator_snapshot']['skills']]
   if execution_task in ('poster','article','change','image') and incoming.get('recipe') is not None and getattr(self.box,'learning',None):
    from easel_workbench.runtime.creative_recipes import service as recipes
    result['prompt_preview']=recipes(self.box).context(result,incoming['recipe'],result['format'])
   result['token']=fingerprint(result);return result
 def consume_round(self,c,work_id,expected_revision):
  current=self._get(c,'contexts',work_id,False)
  if current and current.get('round') and current['revision']==expected_revision:
   current['round']={};self._put(c,'contexts',current)
 def _evidence(self,c,ids):
  if not isinstance(ids,list) or len(ids)>20 or len(set(ids))!=len(ids):raise ValueError('证据附件列表无效')
  rows=[]
  for fid in ids:
   ident(fid);row=c.execute('SELECT id,name,mime,size,sha256,path FROM toolbox_files WHERE id=?',(fid,)).fetchone()
   if not row:raise ValueError('证据附件尚未上传')
   file=pathlib.Path(row['path']).resolve()
   if not file.is_relative_to((self.root/'data').resolve()) or not file.is_file() or sha(file.read_bytes())!=row['sha256']:raise StudioConflict('证据附件已变化或不可用')
   rows.append({key:row[key] for key in ('id','name','mime','size','sha256')})
  return rows
 def _change_preview(self,c,value,configuration=False):
  if not self.project.is_dir():raise StudioUnavailable('内容项目不可访问，不能维护规范')
  section=value.get('section');relative=CONFIG_PATH if configuration else SECTIONS.get(section,('',None))[1]
  if not relative:raise ValueError('请选择已有基座部分')
  current=self._file(relative)
  if value.get('expected_revision')!=current['revision']:raise StudioConflict('权威原件已变化，请核对最新文件')
  if configuration:self._validate_config(value.get('document'));after=pack(value['document'])+'\n'
  else:after=text(value.get('content',''),2_000_000,True)
  change={'id':value['operation_id'],'kind':'configuration' if configuration else 'foundation','section':'configuration' if configuration else section,'path':relative,'before':current['content'],'before_bom':current['utf8_bom'],'after':after,'before_revision':current['revision'],'status':'draft','diff':'\n'.join(difflib.unified_diff(current['content'].splitlines(),after.splitlines(),fromfile='当前原件',tofile='确认后原件',lineterm=''))}
  return {'change':self._put(c,'changes',change,True)}
 def _apply_file(self,c,change,value,revert=False):
  expected=change.get('after_revision') if revert else change['before_revision'];desired=change['before'] if revert else change['after'];path=self._path(change['path']);before=path.read_bytes() if path.is_file() else None;missing=revert and change['before_revision'] is None or not revert and change.get('after_exists') is False;target=None if missing else (b'\xef\xbb\xbf' if (change.get('before_bom') if revert else change.get('after_bom')) else b'')+desired.encode('utf-8');target_sha=sha(target) if target is not None else None;journal=self.root/'data/studio-journal'/(value['operation_id']+'.json')
  if value.get('expected_revision')!=expected:raise StudioConflict('确认的原件修订与差异不一致')
  intent=json.loads(journal.read_text(encoding='utf-8')) if journal.exists() else None
  if intent and (intent['signature']!=value['_signature'] or intent['target_sha']!=target_sha or intent['path']!=change['path']):raise StudioConflict('文件恢复意图与原操作不一致')
  current_sha=sha(before) if before is not None else None
  if current_sha!=expected and not (intent and current_sha==target_sha):raise StudioConflict('原件或后续修改已变化，不能覆盖；请重新核对差异')
  if not intent:
   backup=self.root/'data/studio-backups'/value['operation_id'];backup.mkdir(parents=True,exist_ok=True)
   if before is not None:atomic_bytes(backup/'before.bin',before)
   intent={'operation_id':value['operation_id'],'signature':value['_signature'],'path':change['path'],'before_sha':expected,'target_sha':target_sha,'target':desired};atomic_bytes(journal,pack(intent).encode())
  if current_sha!=target_sha:
   fresh=path.read_bytes() if path.is_file() else None
   if (sha(fresh) if fresh is not None else None)!=expected:raise StudioConflict('文件刚刚被其它编辑器修改，未覆盖')
   if target is None:path.unlink()
   else:atomic_bytes(path,target)
  if (sha(path.read_bytes()) if path.is_file() else None)!=target_sha:raise OSError('规范写入回读失败，请核对原操作')
  changed={**change,'status':'reverted' if revert else 'confirmed',('reverted_at' if revert else 'confirmed_at'):stamp()}
  changed['reverted_revision' if revert else 'after_revision']=target_sha
  saved=self._put(c,'changes',changed);self._journals.append(journal);return {'change':saved,'saved':True,'revision':target_sha}
 def _version(self,c,work_id,version_id):
  ident(work_id);ident(version_id);source,artifacts=version_source(self.box,c,work_id,version_id);return source,artifacts
 def _images(self,c,work_id,ids,publication_id):
  if not isinstance(ids,list) or len(ids)>12 or len(set(ids))!=len(ids):raise ValueError('实际发布图片列表无效')
  result=[]
  for fid in ids:
   row=c.execute("SELECT a.*,j.work_id,j.status FROM artifacts a JOIN toolbox_jobs j ON j.id=a.task_id WHERE a.id=?",(ident(fid),)).fetchone()
   media=self.box.options(work_id,c)['format'] not in ('poster','article')
   if not row or row['work_id']!=work_id or row['status']!='completed' or not row['mime'].startswith(('image/','video/','audio/') if media else ('image/',)):raise ValueError('发布文件必须来自同作品明确完成的版本')
   path=pathlib.Path(row['path']).resolve()
   if not path.is_relative_to((self.root/'data/artifacts').resolve()) or not path.is_file() or path.stat().st_size>(512 if media else 32)*1024*1024:raise ValueError('原件不可用或过大')
   raw=path.read_bytes();digest=sha(raw);snapshot_id='studio-image-'+sha((publication_id+'\0'+fid+'\0'+digest).encode());target=self.root/'data/toolbox/files'/snapshot_id/path.name
   if target.exists() and target.read_bytes()!=raw:raise StudioConflict('发布图片快照指纹不一致')
   if not target.exists():atomic_bytes(target,raw)
   c.execute('INSERT OR IGNORE INTO toolbox_files VALUES(?,?,?,?,?,?)',(snapshot_id,path.name,str(target),row['mime'],len(raw),digest))
   result.append({'id':snapshot_id,'source_id':fid,'version_id':row['task_id'],'name':path.name,'mime':row['mime'],'sha256':digest})
  return result
 def registration_context(self,c,work_id):
  """Record current sources as facts; publishing records do not compile AI."""
  from easel_workbench.runtime.creator_runtime import read_owner
  owner=read_owner(c,work_id)
  sources=[{'id':key,**self._file(path)} for key,(_,path) in SECTIONS.items()]
  if owner and owner['profile_id']!='oil-pig':
   sources=[row for row in sources if row['id'] not in ('position','audience','style')]
   profile=owner['profile']
   for key,field in (('position','identity'),('audience','audience'),('style','voice')):
    content=profile.get(field,'')
    sources.append({'id':key,'path':'creator_profile/'+owner['profile_id']+'/v'+str(owner['profile_revision']),'content':content,'revision':fingerprint(content),'exists':True})
  result={'schema_version':1,'purpose':'publication_record','sources':sources,
          'source_versions':{row['id']:{'path':row.get('path'),'sha256':row.get('revision'),'exists':row.get('exists',True)} for row in sources},
          'settings':self._get(c,'contexts',work_id,False),'creator':clone(owner),'execution_mode':'local'}
  result['revision_token']=fingerprint(result)
  return result
 def _publication(self,c,value,update=False,source_snapshot=None,image_snapshot=None,frozen_source=False):
  if update:
   old=self._get(c,'publications',value.get('publication_id'));self._expected(old,value);pub=clone(old)
   for key in ('work_id','version_id','channel_id','account'):
    if key in value and value[key]!=old[key]:raise StudioConflict('账号、渠道与来源版本属于发布实例身份；请另建记录')
  else:
   work_id=ident(value.get('work_id'));version_id=ident(value.get('version_id'));channel_id=value.get('channel_id');config=self._configuration()['document']
   if frozen_source:
    if not source_snapshot or not c.execute('SELECT 1 FROM toolbox_jobs WHERE id=? AND work_id=?',(version_id,work_id)).fetchone():raise StudioConflict('冻结发布来源身份不符')
    source={**clone(source_snapshot),'token':source_snapshot.get('token',source_snapshot.get('source_token'))};artifacts=source_snapshot['artifacts']
   else:source,artifacts=self._version(c,work_id,version_id)
   from easel_workbench.runtime.distribution_catalog import PLATFORMS
   if channel_id not in config['channels'] and channel_id not in {p['channel_id'] for p in PLATFORMS}:raise ValueError('请选择已有发布渠道')
   original=c.execute('SELECT document FROM toolbox_review_inputs WHERE job_id=?',(version_id,)).fetchone();production_context=json.loads(original['document']).get('studio_context') if original else None
   pub={'id':value['operation_id'],'work_id':work_id,'version_id':version_id,'channel_id':channel_id,'account':text(value.get('account',''),200,True),'title':source['title'],'body':source['body'],'image_ids':[],'images':[],'status':'draft','url':'','published_at':None,'evidence':[],'history':[],'source_snapshot':{'title':source['title'],'body':source['body'],'source_token':source['token'],'artifacts':[{'id':row['id'],'name':row['name'],'mime':row['mime']} for row in artifacts],'studio_context':clone(production_context)},'context':clone(production_context),'context_status':'frozen_at_production' if production_context else 'not_recorded','registration_context':self.registration_context(c,work_id)}
   if source_snapshot is not None:pub['source_snapshot']={**clone(source_snapshot),'source_token':source_snapshot.get('source_token',source_snapshot.get('token',source['token'])),'studio_context':clone(production_context)}
  previous={key:clone(pub.get(key)) for key in ('title','body','image_ids','images','status','url','published_at','evidence')}
  for key,limit in (('title',500),('body',100000)):
   if key in value:pub[key]=text(value[key],limit,True)
  if image_snapshot is not None:pub['images']=clone(image_snapshot);pub['image_ids']=[row['source_id'] for row in image_snapshot]
  elif 'image_ids' in value:pub['images']=self._images(c,pub['work_id'],value['image_ids'],pub['id']);pub['image_ids']=clone(value['image_ids'])
  if 'evidence' in value:pub['evidence']=self._evidence(c,value['evidence'])
  for key in ('status','url','published_at'):
   if key in value:pub[key]=value[key]
  if pub['status'] not in ('draft','published','withdrawn'):raise ValueError('发布状态无效')
  if pub['url'] and not valid_url(pub['url']):raise ValueError('发布链接无效')
  when(pub['published_at'],'发布时间',True)
  pub.update(registration_kind='manual',publication_verification='manual')
  pub.update(self.publication_metadata(pub))
  pub['history'].append({'operation_id':value['operation_id'],'at':stamp(),'before':previous if update else None,'after':{key:clone(pub.get(key)) for key in previous},'note':text(value.get('note',''),10000)})
  return {'publication':self._put(c,'publications',pub,not update)}
 @staticmethod
 def publication_metadata(pub):
  missing=[key for key in ('url','published_at') if pub.get('status')=='published' and not pub.get(key)]
  receipt=pub.get('distribution_receipt') or {};legacy_verified=receipt.get('verified') is True and bool(pub.get('remote_id')) and bool(receipt.get('safe_url'))
  return {'registration_kind':pub.get('registration_kind','connector' if legacy_verified else 'manual'),'publication_verification':pub.get('publication_verification','verified' if legacy_verified else 'manual'),
          'metadata_pending':bool(missing),'missing_metadata':missing,'published_at_known':bool(pub.get('published_at')),
          'metric_windows':['24h','7d','custom'] if pub.get('published_at') else ['custom']}
 def create_completion_publication(self,c,decision_id,work_id,version_id,source_snapshot,manual,index=None,allow_historical=False):
  """Trusted completion caller, in its existing transaction; never a publisher."""
  ident(decision_id);ident(work_id);ident(version_id)
  decision=c.execute("SELECT id,kind,candidate_id FROM toolbox_jobs WHERE work_id=? AND kind IN ('accept','reject') ORDER BY rowid DESC LIMIT 1",(work_id,)).fetchone()
  completion=self._completion_plan(c,decision_id,work_id,version_id)
  if not isinstance(source_snapshot,dict) or not isinstance(manual,dict):raise ValueError('完成发布记录格式无效')
  if set(manual)-{'channel_id','account','status','url','published_at'}:raise ValueError('手工发布记录字段无效')
  status=manual.get('status','published')
  if status not in ('draft','published'):raise ValueError('请明确待发布或已手动发布')
  selection=completion['_plan']['selection']
  normalized={key:manual.get(key) for key in ('channel_id','account','status','url','published_at')};normalized.update(status=status,url=manual.get('url') or '')
  explicit=any({key:row.get(key) for key in normalized}==normalized for row in selection['manual_publications'])
  fallback=status=='draft' and not normalized['url'] and normalized['published_at'] is None and any(row['channel_id']==manual.get('channel_id') and row['account']==manual.get('account') for row in (completion['_plan'].get('distribution') or {}).get('targets',[]))
  if not explicit and not fallback:raise StudioConflict('发布记录不属于已确认的完成目标')
  original=c.execute("SELECT kind,candidate_id,scope FROM toolbox_jobs WHERE id=? AND work_id=?",(decision_id,work_id)).fetchone()
  if not original or original['kind']!='accept' or original['candidate_id']!=version_id or set(json.loads(original['scope']))!=set(completion['_plan']['scope']):raise StudioConflict('原人类采纳授权不符')
  current=bool(decision and decision['id']==decision_id and decision['kind']=='accept' and decision['candidate_id']==version_id)
  historical=allow_historical is True and explicit and status=='published'
  if not current and not historical:raise StudioConflict('采纳决定已变化，不能登记旧完成方案')
  if historical:source=clone(completion['_plan']['source']);artifacts=source['artifacts']
  else:source,artifacts=self._version(c,work_id,version_id)
  if any(source.get(key)!=source_snapshot.get(key) for key in ('title','body')) or source['token']!=source_snapshot.get('source_token',source_snapshot.get('token')):raise StudioConflict('已采纳稿件内容已变化，不能登记旧发布方案')
  frozen=completion['_plan']['source']
  if any(frozen.get(key)!=source.get(key) for key in ('title','body','token')):raise StudioConflict('冻结采纳稿件不符')
  source_snapshot=clone(frozen)
  channel=ident(manual.get('channel_id'));account=text(manual.get('account',''),200,True)
  key='completion-pub-'+sha(pack([decision_id,work_id,version_id,channel,account]).encode())[:40]
  signature=fingerprint({'source':source_snapshot,'manual':normalized})
  old=self._get(c,'completion_publications',key,False)
  if old:
   if old['signature']!=signature:raise StudioConflict('同一完成目标不能覆盖不同内容')
   return {'publication':self._get(c,'publications',old['publication_id']),'duplicate':True}
  publication_id='adopted-publication-'+sha(pack([work_id,version_id,channel,account]).encode())[:40]
  existing=self._get(c,'publications',publication_id,False)
  if existing and existing['status']=='published':pub=existing
  elif existing:
   if existing['title']!=source['title'] or existing['body']!=source['body']:raise StudioConflict('已有渠道稿已编辑，不能由重采纳覆盖')
   if status=='published':pub=self._publication(c,{'operation_id':key,'publication_id':existing['id'],'expected_revision':existing['revision'],'status':status,'url':manual.get('url') or '','published_at':manual.get('published_at'),'note':'用户明确登记已经手动发布'},True)['publication']
   else:pub=existing
  else:
   images=[row['id'] for row in artifacts if row['mime'].startswith('image/')]
   image_snapshot=self._completion_images(c,completion,publication_id) if historical else None
   pub=self._publication(c,{'operation_id':publication_id,'work_id':work_id,'version_id':version_id,'channel_id':channel,'account':account,'image_ids':images,'title':source['title'],'body':source['body'],
         'status':status,'url':manual.get('url') or '','published_at':manual.get('published_at'),'note':'采纳归档完成后的手动发布记录；未执行远端写入'},source_snapshot=source_snapshot,image_snapshot=image_snapshot,frozen_source=historical)['publication']
  self._put(c,'completion_publications',{'id':key,'signature':signature,'decision_id':decision_id,'publication_id':pub['id']},True)
  return {'publication':pub,'duplicate':bool(existing)}
 def _completion_images(self,c,item,publication_id):
  directory=(self.root/'data/completions'/ident(item['decision_id'])).resolve();result=[]
  for artifact in item['_plan']['source']['artifacts']:
   if not artifact['mime'].startswith('image/'):continue
   entry=next((row for row in item['_files'] if row.get('id')==artifact['id'] and row.get('sha256')==artifact['sha256']),None)
   if not entry:raise StudioConflict('已归档图片记录缺失，未虚构发布图片')
   path=(directory/entry['relative_path']).resolve()
   if not path.is_relative_to(directory) or not path.is_file():raise StudioConflict('已归档图片副本不可用')
   raw=path.read_bytes()
   if sha(raw)!=artifact['sha256']:raise StudioConflict('已归档图片字节不符')
   snapshot_id='studio-image-'+sha((publication_id+'\0'+artifact['id']+'\0'+artifact['sha256']).encode());name=pathlib.Path(artifact['name']).name;target=self.root/'data/toolbox/files'/snapshot_id/name
   if target.exists() and target.read_bytes()!=raw:raise StudioConflict('发布图片快照指纹不一致')
   if not target.exists():atomic_bytes(target,raw)
   c.execute('INSERT OR IGNORE INTO toolbox_files VALUES(?,?,?,?,?,?)',(snapshot_id,name,str(target),artifact['mime'],len(raw),artifact['sha256']))
   result.append({'id':snapshot_id,'source_id':artifact['id'],'version_id':item['version_id'],'name':name,'mime':artifact['mime'],'sha256':artifact['sha256']})
  return result
 def _completion_plan(self,c,decision_id,work_id,version_id):
  if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='toolbox_completions'").fetchone():raise StudioConflict('尚无已核验的采纳完成快照')
  row=c.execute('SELECT document FROM toolbox_completions WHERE decision_id=?',(decision_id,)).fetchone()
  item=json.loads(row['document']) if row else None
  if not item or item.get('work_id')!=work_id or item.get('version_id')!=version_id or not item.get('whole_work') or item.get('archive',{}).get('status')!='verified':raise StudioConflict('采纳归档尚未核验，未执行发布方案')
  return item
 def review_evidence(self,publication_id,connection=None):
  with self.store.connect() if connection is None else contextlib.nullcontext(connection) as c:
   pub=self._get(c,'publications',publication_id);metrics=[item for item in self._records(c,'metrics') if item['publication_id']==publication_id];comments=[item for item in self._records(c,'comments') if item['publication_id']==publication_id]
   original_comments=[{key:clone(row.get(key)) for key in ('id','publication_id','text','author','observed_at','evidence')} for row in comments]
   publication={key:clone(pub.get(key)) for key in ('id','work_id','version_id','channel_id','account','title','body','images','url','published_at')}
   evidence={'publication':publication,'metrics':metrics,'comments':original_comments};return {'signature':fingerprint(evidence),'evidence':evidence,'metrics_count':len(metrics),'comments_count':len(comments)}
 def queue_health(self,connection=None):
  with self.store.connect() if connection is None else contextlib.nullcontext(connection) as c:
   fields=('id','work_id','kind','status','error','dispatch_started','queue_id','turn_id','rollout_offset','created_at','started_at','finished_at')
   def project(row):
    result={key:row[key] for key in fields};result['job_id']=result.pop('id');result['thread_link']='codex://threads/'+THREAD;return result
   head=c.execute("SELECT * FROM toolbox_jobs WHERE status IN ('queued','dispatching','running','uncertain','needs_desktop') ORDER BY created_at,rowid LIMIT 1").fetchone();parked=[]
   deferrals={row['job_id']:row for row in self._records(c,'queue_deferrals')}
   for row in c.execute("SELECT * FROM toolbox_jobs WHERE status='parked' ORDER BY created_at,rowid"):
    item=project(row);audit=deferrals.get(row['id'],{});item.update(note=audit.get('note',''),deferral_id=audit.get('id'),deferred_at=audit.get('created_at'));parked.append(item)
   result={'state':'idle','job_id':None,'work_id':None,'kind':None,'status':None,'error':None,'queue_id':None,'turn_id':None,'dispatch_started':None,'thread_link':'codex://threads/'+THREAD,'can_defer':False,'parked':parked}
   if head:result.update(project(head));result['state']='blocked' if head['status'] in ('uncertain','needs_desktop') else 'processing';result['can_defer']=head['status'] in ('uncertain','needs_desktop') and head['dispatch_started']==1
   return result
 def _queue_defer(self,c,value):
  if value.get('acknowledged') is not True:raise ValueError('请明确确认你已在指定Codex会话核对原任务；不会自动代你确认')
  note=text(value.get('note',''),20000,True);expected=value.get('expected_status')
  if expected not in ('uncertain','needs_desktop'):raise ValueError('只能明确暂缓结果待核对或需要桌面确认的任务')
  health=self.queue_health(c);job_id=ident(value.get('job_id'))
  if job_id!=health['job_id']:raise StudioConflict('队首已经变化，请重新核对当前具体任务')
  row=c.execute('SELECT * FROM toolbox_jobs WHERE id=?',(job_id,)).fetchone()
  if row['status']!=expected or row['dispatch_started']!=1:raise StudioConflict('任务状态已经变化或尚未发送，不能用此入口暂缓')
  original={key:row[key] for key in ('status','dispatch_started','queue_id','turn_id','rollout_offset','created_at','started_at','finished_at','error')}
  updated=c.execute("UPDATE toolbox_jobs SET status='parked' WHERE id=? AND status=? AND dispatch_started=1",(job_id,expected))
  if updated.rowcount!=1:raise StudioConflict('任务刚刚发生变化，未暂缓')
  audit=self._put(c,'queue_deferrals',{'id':value['operation_id'],'job_id':job_id,'work_id':row['work_id'],'previous_status':expected,'status':'parked','acknowledged':True,'note':note,'original':original,'thread':THREAD,'thread_link':health['thread_link'],'statement':'只暂缓本地排队观察；不取消原生任务、不重发、不判定完成。原任务仍须在Codex核对，原作品不得重复制作。'},True)
  return {'deferral':audit,'job':{**{key:row[key] for key in ('id','work_id','kind','queue_id','turn_id','rollout_offset')},'status':'parked'},'queue_health':self.queue_health(c)}
 def _metric_import(self,c,value):
  pub=self._get(c,'publications',value.get('publication_id'));observed=when(value.get('observed_at'),'观察时间');window=value.get('window')
  if window not in ('24h','7d','custom'):raise ValueError('请明确数据时间窗')
  if window in ('24h','7d') and not pub.get('published_at'):raise ValueError('发布时间未知，仅可记录自定义时间窗数据')
  values=value.get('values',{})
  if not isinstance(values,dict) or set(values)-set(METRICS):raise ValueError('指标字段无效')
  values={key:values.get(key) for key in METRICS}
  if any(n is not None and (type(n) is not int or n<0) for n in values.values()):raise ValueError('指标只能是非负整数或未知null')
  if pub['published_at'] and dt.datetime.fromisoformat(observed.replace('Z','+00:00'))<dt.datetime.fromisoformat(pub['published_at'].replace('Z','+00:00')):raise ValueError('观察不能早于发布时间')
  source=clone(value.get('source',{}))
  if source.get('kind') not in ('manual','file'):raise ValueError('目前仅支持真实手工核对或导出文件，不冒充API连接')
  text(source.get('label',''),1000,True)
  if window=='custom':text(source.get('window_note',''),2000,True)
  source['evidence']=self._evidence(c,source.get('evidence',[]));document={'publication_id':pub['id'],'observed_at':observed,'window':window,'values':values,'source':source};signature=fingerprint(document)
  old=next((item for item in self._records(c,'metric_imports') if item['signature']==signature or fingerprint({key:({metric:item['values'].get(metric) for metric in METRICS} if key=='values' else item[key]) for key in ('publication_id','observed_at','window','values','source')})==signature),None)
  if old:return {'import':old,'duplicate':True}
  return {'import':self._put(c,'metric_imports',{'id':value['operation_id'],**document,'signature':signature,'status':'draft','metric_id':None},True)}
 def _metric_confirm(self,c,value):
  item=self._get(c,'metric_imports',value.get('import_id'))
  if item['status']=='confirmed':return {'import':item,'metric':self._get(c,'metrics',item['metric_id'])}
  if item['window'] in ('24h','7d') and not self._get(c,'publications',item['publication_id']).get('published_at'):raise ValueError('发布时间未知，不能确认24小时或7天数据')
  metric={key:clone(item[key]) for key in ('publication_id','observed_at','window','values','source')};metric.update(id='metric-'+item['id'],import_id=item['id'],confirmed_at=stamp());metric=self._put(c,'metrics',metric,True);item.update(status='confirmed',metric_id=metric['id']);return {'import':self._put(c,'metric_imports',item),'metric':metric}
 def _comment(self,c,value,update=False):
  if update:
   item=self._get(c,'comments',value.get('comment_id'));self._expected(item,value)
   if any(key in value and value[key]!=item.get(key) for key in ('text','publication_id','author','observed_at','evidence')):raise ValueError('原评论与来源不可改写，只能整理主题和分类')
   before={'topic':item['topic'],'category':item['category']}
  else:
   pub=self._get(c,'publications',value.get('publication_id'));item={'id':value['operation_id'],'publication_id':pub['id'],'work_id':pub['work_id'],'version_id':pub['version_id'],'text':text(value.get('text',''),20000,True),'author':text(value.get('author',''),200),'observed_at':when(value.get('observed_at'),'评论时间',True),'evidence':self._evidence(c,value.get('evidence',[])),'topic':'','category':'other','history':[]};before=None
  item['topic']=text(value.get('topic',item['topic']),500);item['category']=value.get('category',item['category'])
  if item['category'] not in CATEGORIES:raise ValueError('评论分类无效')
  item['history'].append({'operation_id':value['operation_id'],'at':stamp(),'before':before,'after':{'topic':item['topic'],'category':item['category']}});return {'comment':self._put(c,'comments',item,not update)}
 def _work_context(self,c,value):
  work_id=ident(value.get('work_id'))
  if not c.execute('SELECT 1 FROM toolbox_works WHERE id=?',(work_id,)).fetchone():raise ValueError('作品不存在')
  existing=self._get(c,'contexts',work_id,False);current=existing or {'id':work_id,'revision':0,'channel_id':'wechat','workflow_id':None,'overrides':{},'round':{}}
  self._expected(current,value);settings=clone(value.get('settings',{}))
  if set(settings)-{'channel_id','workflow_id','overrides','round'}:raise ValueError('作品设置字段无效')
  config=self._configuration()['document'];current.update(settings)
  if current['channel_id'] not in config['channels'] or current['workflow_id'] is not None and current['workflow_id'] not in config['workflows']:raise ValueError('渠道或流程不存在')
  for field in ('overrides','round'):
   patch=current[field]
   if not isinstance(patch,dict) or set(patch)-{'goal','audience','position','standards','style_guidance','values','intent','preset_id','target','keep_text','text','fixed_master','recipe'}:raise ValueError('创作覆盖字段无效')
   if 'recipe' in patch:
    from easel_workbench.runtime.creative_recipes import parse_recipe
    patch['recipe']=parse_recipe(patch['recipe'])
    for key in ('preview_id','source_revision','plan_id'):patch['recipe'].pop(key,None)
   self._partial_weights(patch.get('values',{}));semantic_intent(patch.get('intent',{}))
   creative_options({'schema_version':2,'intent':patch.get('intent',{}),**{key:patch[key] for key in ('target','keep_text','text','fixed_master') if key in patch}})
   for key in ('goal','audience','position','standards','style_guidance'):
    if key in patch:text(patch[key],10000)
  saved=self._put(c,'contexts',current);return {'settings':saved,'context':self.context(work_id,connection=c)}
 def _proposal_projection(self,c,scope,target_id,section):
  if scope=='work':
   if not c.execute('SELECT 1 FROM toolbox_works WHERE id=?',(ident(target_id),)).fetchone():raise ValueError('提案作品不存在')
   return self._get(c,'contexts',target_id,False) or {'id':target_id,'revision':0,'channel_id':'wechat','workflow_id':None,'overrides':{},'round':{}}
  if scope in ('global','workflow'):
   if scope=='global':return self._file(SECTIONS.get(section,('',None))[1]) if section in SECTIONS else None
   return self._configuration()
  if scope=='preset':
   row=c.execute('SELECT * FROM toolbox_style_presets WHERE id=?',(ident(target_id),)).fetchone()
   if not row:raise ValueError('请选择已保存的个人预设；内置起点请先另存')
   return {**json.loads(row['document']),'revision':row['revision'],'format':row['format']}
  raise ValueError('提案范围无效')
 def _proposal_create(self,c,value):
  scope=value.get('scope','work');target=value.get('target_id') or value.get('work_id');section=value.get('section','style');before=self._proposal_projection(c,scope,target,section)
  if before is None:raise ValueError('请选择具体规范文件')
  patch=clone(value.get('patch',{}));content=text(value.get('content',''),20000,True);after=clone(before)
  if scope=='work':
   if set(patch)-{'goal','audience','position','standards','style_guidance','values','intent','preset_id'}:raise ValueError('作品提案字段无效')
   self._partial_weights(patch.get('values',{}));semantic_intent(patch.get('intent',{}));after['overrides']={**after.get('overrides',{}),**patch}
  elif scope=='global':
   after['content']=text(patch.get('content',before['content']+('\n\n'+patch['append_content'] if patch.get('append_content') else '')),2_000_000,True)
  elif scope=='workflow':
   document=clone(before['document']);flow_id=target or document['default_workflow_id']
   if flow_id not in document['workflows']:raise ValueError('目标流程不存在')
   flow=clone(document['workflows'][flow_id]);flow.update(patch);document['workflows'][flow_id]=flow;self._validate_config(document);after['document']=document
  else:
   from easel_workbench.runtime.content_studio import weights
   if before.get('schema_version',1)==2:
    if set(patch)-{'name','intent'}:raise ValueError('新版风格提案只接收语义选项和名称')
    after['intent']=semantic_intent(patch.get('intent',before.get('intent',{})))
   else:
    if set(patch)-{'name','values'}:raise ValueError('旧数字预设请先另存为新版风格；不覆盖旧预设')
    after['values']=weights(patch.get('values',before['values']))
   after['name']=text(patch.get('name',before['name']),48,True)
  supplied=value.get('evidence',[])
  if not isinstance(supplied,list) or len(pack(supplied))>200000:raise ValueError('提案证据无效')
  refs=[]
  for ref in supplied:
   if not isinstance(ref,dict):raise ValueError('证据需要明确对象')
   if ref.get('comment_id'):
    original=self._get(c,'comments',ref['comment_id']);refs.append({'kind':'comment','comment_id':original['id'],'publication_id':original['publication_id'],'text':original['text']})
   elif ref.get('metric_id'):refs.append({'kind':'metric','metric':self._get(c,'metrics',ref['metric_id'])})
   elif ref.get('analysis_id'):
    analysis=self._get(c,'analyses',ref['analysis_id']);job=c.execute('SELECT status,reply FROM toolbox_jobs WHERE id=?',(analysis['job_id'],)).fetchone()
    if not job or job['status']!='completed':raise ValueError('分析尚未完成，不能当作已完成证据')
    refs.append({'kind':'analysis','analysis_id':analysis['id'],'job_id':analysis['job_id'],'reply':job['reply'],'signature':analysis['signature']})
   elif ref.get('kind')=='human':refs.append({'kind':'human','text':text(ref.get('text',''),20000,True)})
   else:raise ValueError('请引用已保存的原评论、指标、真实分析或明确的人类意见')
  proposal={'id':value['operation_id'],'title':text(value.get('title','改进建议'),300,True),'content':content,'scope':scope,'target_id':target,'section':section,'patch':patch,'before':before,'after':after,'status':'draft','evidence':refs}
  return {'proposal':self._put(c,'proposals',proposal,True)}
 def _proposal_apply(self,c,value,revert=False):
  proposal=self._get(c,'proposals',value.get('proposal_id'));required='confirmed' if revert else 'draft'
  if proposal['status']==('reverted' if revert else 'confirmed'):return {'proposal':proposal}
  if proposal['status']!=required:raise StudioConflict('提案状态已变化，请核对最新记录')
  if 'expected_revision' in value:self._expected(proposal,value)
  current=self._proposal_projection(c,proposal['scope'],proposal['target_id'],proposal['section']);expected=proposal.get('applied_projection') if revert else proposal['before']
  journal=self.root/'data/studio-journal'/(value['operation_id']+'.json')
  recovery=json.loads(journal.read_text(encoding='utf-8')) if journal.is_file() else None
  if fingerprint(current)!=fingerprint(expected):
   if recovery and proposal['scope'] in ('global','workflow') and recovery['signature']==value['_signature'] and current['revision']==recovery['target_sha']:current=clone(expected)
   else:raise StudioConflict('提案目标已被修改，不能覆盖后来的内容')
  desired=proposal['before'] if revert else proposal['after'];scope=proposal['scope']
  if scope=='work':saved=self._put(c,'contexts',desired)
  elif scope=='preset':
   c.execute('INSERT OR IGNORE INTO toolbox_style_preset_revisions SELECT id,revision,document,updated_at FROM toolbox_style_presets WHERE id=?',(current['id'],))
   revision=current['revision']+1;document={key:clone(desired[key]) for key in desired if key not in ('revision','format')};updated=stamp();c.execute('UPDATE toolbox_style_presets SET name=?,revision=?,document=?,updated_at=? WHERE id=?',(document['name'],revision,pack(document),updated,document['id']));c.execute('INSERT INTO toolbox_style_preset_revisions VALUES(?,?,?,?)',(document['id'],revision,pack(document),updated));saved={**document,'revision':revision,'format':current['format']}
  else:
   relative=CONFIG_PATH if scope=='workflow' else SECTIONS[proposal['section']][1];after=(desired['content'] if revert else pack(desired['document'])+'\n') if scope=='workflow' else desired['content'];change={'id':'proposal-'+proposal['id']+('-revert' if revert else '-apply'),'section':'configuration' if scope=='workflow' else proposal['section'],'path':relative,'kind':'configuration' if scope=='workflow' else 'foundation','before':current['content'],'before_bom':current.get('utf8_bom',False),'after':after,'after_bom':desired.get('utf8_bom',False),'after_exists':desired.get('exists',True) if revert else True,'before_revision':current['revision'],'status':'draft'};self._put(c,'changes',change,True);self._apply_file(c,change,{**value,'expected_revision':current['revision']});saved=self._proposal_projection(c,scope,proposal['target_id'],proposal['section'])
  proposal.update(status='reverted' if revert else 'confirmed');proposal['reverted_at' if revert else 'confirmed_at']=stamp()
  if not revert:proposal['applied_projection']=saved
  return {'proposal':self._put(c,'proposals',proposal)}
 def _execute(self,c,value):
  action=value['action']
  if action in ('foundation-preview','config-preview'):return self._change_preview(c,value,action=='config-preview')
  if action in ('foundation-confirm','config-confirm','foundation-revert','config-revert'):
   change=self._get(c,'changes',value.get('change_id'));revert=action.endswith('revert')
   if change['status']==('reverted' if revert else 'confirmed'):return {'change':change,'saved':True}
   if change['status']!=('confirmed' if revert else 'draft'):raise StudioConflict('差异状态已变化，请核对原操作')
   return self._apply_file(c,change,value,revert)
  if action in ('publication-create','publication-update'):return self._publication(c,value,action.endswith('update'))
  if action=='metric-import':return self._metric_import(c,value)
  if action=='metric-confirm':return self._metric_confirm(c,value)
  if action in ('comment-add','comment-update'):return self._comment(c,value,action.endswith('update'))
  if action=='work-context':return self._work_context(c,value)
  if action=='queue-defer':return self._queue_defer(c,value)
  if action=='proposal-create':return self._proposal_create(c,value)
  if action in ('proposal-confirm','proposal-revert'):return self._proposal_apply(c,value,action.endswith('revert'))
  if action=='review-complete':
   pub=self._get(c,'publications',value.get('publication_id'));report=self.review_evidence(pub['id'],c)
   if pub['status']!='published' or not report['metrics_count']+report['comments_count']:raise ValueError('仅对有真实数据或原评论的已发布实例复盘')
   if value.get('signature')!=report['signature']:raise StudioConflict('本次证据已变化，请核对新数据后再确认')
   note=text(value.get('note',''),20000);old=next((item for item in self._records(c,'review_completions') if item['publication_id']==pub['id'] and item['signature']==report['signature'] and item['note']==note),None)
   return {'review':old or self._put(c,'review_completions',{'id':value['operation_id'],'publication_id':pub['id'],'signature':report['signature'],'note':note,'evidence':report['evidence'],'completed_at':stamp()},True)}
  raise ValueError('不支持的工作台命令')
 def _normalize(self,value):
  if not isinstance(value,dict):raise ValueError('请求需要JSON对象')
  payload={**value,**(value.get('payload') if isinstance(value.get('payload'),dict) else {})};payload.pop('payload',None);operation=ident(value.get('operation_id') or value.get('id'));action=text(value.get('action',''),100,True);payload.update(operation_id=operation,action=action);payload.pop('id',None);payload['_signature']=fingerprint(payload);return payload
 def command(self,value):
  value=self._normalize(value)
  if value['action']=='analysis-start':return self._analysis(value)
  with locked(self.root/'data/studio-command.lock',timeout=20):
   self._journals=[]
   pending=list((self.root/'data/studio-journal').glob('*.json'))
   for file in pending:
    saved=json.loads(file.read_text(encoding='utf-8'))
    if saved['operation_id']!=value['operation_id']:
     with self.store.connect() as read:done=read.execute("SELECT status FROM studio_operations WHERE operation_id=?",(saved['operation_id'],)).fetchone()
     if not done or done['status']!='completed':raise StudioConflict('有一条文件维护回执待核对，请先重试原操作：'+saved['operation_id'])
   with self.store.connect() as c:
    c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM studio_operations WHERE operation_id=?',(value['operation_id'],)).fetchone()
    if old:
     if old['signature']!=value['_signature']:raise StudioConflict('同一操作ID不能覆盖不同内容')
     if old['status']=='completed':return json.loads(old['result'])
    result={'operation_id':value['operation_id'],'action':value['action'],'status':'completed','result':self._execute(c,value)};c.execute('INSERT OR REPLACE INTO studio_operations VALUES(?,?,?,?,?,?)',(value['operation_id'],value['action'],value['_signature'],'completed',pack(result),stamp()))
    if getattr(self.box,'learning',None) and value['action'] in ('comment-add','comment-update','metric-confirm'):
     self.box.learning.index_database(c)
   for journal in self._journals:
    if journal.exists():journal.unlink()
   return result
 def _analysis(self,value):
  from easel_workbench.runtime.work_discussions import enqueue
  from easel_workbench.runtime.article_drafts import read as read_draft
  oid=value['operation_id'];job_id='studio-analysis-'+sha(oid.encode())[:40]
  with locked(self.root/'data/studio-analysis.lock',timeout=20):
   with self.store.connect() as c:
    c.execute('BEGIN IMMEDIATE');old=c.execute('SELECT * FROM studio_operations WHERE operation_id=?',(oid,)).fetchone()
    if old and old['signature']!=value['_signature']:raise StudioConflict('同一分析操作ID不能改写原问题或证据')
    if old and old['status']=='completed':return json.loads(old['result'])
    intent=self._get(c,'analyses',oid,False)
    if not intent:
     pub=self._get(c,'publications',value.get('publication_id'));report=self.review_evidence(pub['id'],c);question=text(value.get('question',''),10000,True);draft=read_draft(self.box,pub['work_id'],c)
     intent=self._put(c,'analyses',{'id':oid,'job_id':job_id,'publication_id':pub['id'],'work_id':pub['work_id'],'version_id':pub['version_id'],'question':question,'signature':report['signature'],'snapshot':report['evidence'],'draft_revision':draft['revision'],'status':'pending'},True)
    if not intent.get('creator_snapshot'):
     from easel_workbench.runtime.content_studio import frozen_options
     from easel_workbench.runtime.task_runtime import request_snapshot
     prior=frozen_options(c,intent['version_id']) or {};owner=(prior.get('creator') or {}).get('profile_id','oil-pig')
     selection=value.get('creator') or {}
     if not isinstance(selection,dict) or (selection.get('profile_id') or value.get('profile_id') or owner)!=owner:
      raise StudioConflict('复盘须使用该作品的创作画像')
     intent['creator_snapshot']=request_snapshot(self.box,value,'analysis',c,fallback_profile=owner)
     intent=self._put(c,'analyses',intent)
    c.execute('INSERT OR IGNORE INTO studio_operations VALUES(?,?,?,?,?,?)',(oid,value['action'],value['_signature'],'pending',None,stamp()))
   attachment_id='studio-analysis-evidence-'+sha(oid.encode())[:40];self.box.upload(attachment_id,'发布复盘冻结证据.json',pack({'schema_version':1,'analysis_id':oid,'question':intent['question'],'evidence_signature':intent['signature'],'evidence':intent['snapshot']}).encode())
   selected=intent['creator_snapshot']
   creative={'creator':{'profile_id':selected['profile']['id'],'profile_revision':selected['profile']['revision'],
     'skills':[{'id':r['id'],'version':r['version']} for r in selected['skills']],'trial':bool(selected.get('trial'))}}
   prompt='发布复盘问题原话：\n'+intent['question']+'\n准确发布实例：'+intent['publication_id']+'\n实际证据附件：发布复盘冻结证据.json'
   try:job=enqueue(self.box,intent['work_id'],{'id':job_id,'candidate_id':intent['version_id'],'revision':intent['draft_revision'],'text':prompt,'files':[attachment_id],'creative':creative},execution_task='analysis',creator_snapshot=selected)
   except (ValueError,OSError) as error:
    with self.store.connect() as c:
     current=self._get(c,'analyses',oid);current.update(status='blocked',error=str(error));self._put(c,'analyses',current)
    raise
   with self.store.connect() as c:
    c.execute('BEGIN IMMEDIATE');current=self._get(c,'analyses',oid);current.update(status=job['status'],error=None);current=self._put(c,'analyses',current);result={'operation_id':oid,'action':value['action'],'status':'completed','result':{'analysis':current,'job':job}};c.execute("UPDATE studio_operations SET status='completed',result=? WHERE operation_id=?",(pack(result),oid))
   return result
 def bootstrap(self):
  foundation=self.foundation();works=self.box.works()['items']
  from easel_workbench.runtime.completion_service import CompletionService
  completion=getattr(self.box,'completion',None)
  if not isinstance(completion,CompletionService):
   completion=CompletionService(self.box,studio=self);self.box.completion=completion
  with self.store.connect() as c:
   result={'schema_version':1,'foundation':foundation,'capabilities':self.capabilities(),'presets':preset_catalog(self.box,'poster'),'works':works}
   result['completions']=completion.list(connection=c)
   for work in works:
    rows=c.execute("SELECT id,status FROM toolbox_jobs WHERE work_id=? AND kind IN ('create','change') ORDER BY julianday(created_at),rowid",(work['id'],)).fetchall();work['versions']=[{'id':row['id'],'status':row['status'],'label':'v'+str(index+1).zfill(2)} for index,row in enumerate(rows)]
   for category in ('publications','metric_imports','metrics','comments','proposals','review_completions','analyses'):result[category]=self._records(c,category)
   result['work_contexts']={item['id']:item for item in self._records(c,'contexts')};needs=[];processing=[];worth=[]
   for work in works:
    for job in work.get('pending',[]):
     if job['status']!='parked':
      recovery=job.get('recovery') or (work.get('recovery') if (work.get('recovery') or {}).get('job_id')==job['id'] else None)
      reason=(recovery or {}).get('message') if (recovery or {}).get('action') else ('核对同一次结果' if job['status']=='uncertain' else '任务处理中')
      processing.append({'id':job['id'],'kind':'operation','work_id':work['id'],'format':work['format'],'title':work['title'],'status':job['status'],'reason':reason,'recovery':recovery})
    needed=work.get('review_needed',work['state']=='review')
    if needed and not work.get('pending'):needs.append({'id':'review-'+work['id'],'kind':'work-review','work_id':work['id'],'format':work['format'],'version_id':work.get('latest_version'),'title':work['title'],'reason':'新版本等待评审'})
    issue=work.get('production_issue')
    if issue and not work.get('pending'):
     recovery=issue.get('recovery') or work.get('recovery');dispatch=(recovery or {}).get('failure_kind')=='dispatch'
     needs.append({'id':'issue-'+issue['job_id'],'kind':'production-issue','work_id':work['id'],'format':work['format'],'version_id':issue['job_id'],'title':work['title'],'status':issue['status'],'reason':('发送失败：' if dispatch else issue.get('title','制作受阻' if issue['status']=='blocked' else '制作未完成')+'：')+issue['message'],'recovery':recovery})
   for item in result['metric_imports']:
    if item['status']=='draft':needs.append({'id':item['id'],'kind':'metric-import','import_id':item['id'],'publication_id':item['publication_id'],'title':'核对平台数据','reason':'数据等待核对'})
   for item in foundation['changes']:
    if item['can_confirm']:needs.append({'id':item['id'],'kind':'foundation-change','change_id':item['id'],'section':item['section'],'title':SECTIONS.get(item['section'],('工作台配置',))[0],'reason':'基座差异待确认'})
   for item in result['proposals']:
    if item['status']=='draft':needs.append({'id':item['id'],'kind':'proposal','proposal_id':item['id'],'title':item['title'],'reason':'建议等待确认'})
   for publication in result['publications']:
    publication.update(self.publication_metadata(publication))
    publication['review_due_windows']=[]
    if publication['status']=='published' and publication.get('published_at'):
     published=dt.datetime.fromisoformat(publication['published_at'].replace('Z','+00:00'))
     elapsed=(dt.datetime.now(dt.timezone.utc)-published.astimezone(dt.timezone.utc)).total_seconds()
     recorded={item['window'] for item in result['metrics'] if item['publication_id']==publication['id']}
     for window,seconds,label in (('24h',86400,'24小时'),('7d',604800,'7天')):
      if elapsed>=seconds and window not in recorded:
       publication['review_due_windows'].append(window)
       needs.append({'id':publication['id']+'-data-'+window,'kind':'publication-data','publication_id':publication['id'],'window':window,'title':'录入发布后'+label+'数据','reason':'对应时间窗已到期，尚未登记真实数据；不会自动取数'})
    report=self.review_evidence(publication['id'],c);done=any(item['publication_id']==publication['id'] and item['signature']==report['signature'] for item in result['review_completions']);publication.update(review_signature=report['signature'],needs_review=publication['status']=='published' and report['metrics_count']+report['comments_count']>0 and not done)
    if publication['needs_review']:worth.append({'id':publication['id'],'kind':'publication-review','publication_id':publication['id'],'title':publication['title'],'signature':report['signature'],'reason':str(report['metrics_count'])+'份数据 · '+str(report['comments_count'])+'条原评论'})
   for analysis in result['analyses']:
    job=c.execute('SELECT status,reply,error,turn_id FROM toolbox_jobs WHERE id=?',(analysis['job_id'],)).fetchone()
    if job:analysis.update({key:job[key] for key in ('status','reply','error','turn_id')})
   result['queue_health']=self.queue_health(c)
   for parked in result['queue_health']['parked']:needs.append({'id':'parked-'+parked['job_id'],'kind':'queue-parked','job_id':parked['job_id'],'work_id':parked['work_id'],'title':'原任务仍待核对','reason':'已暂缓本地排队，原生结果未确认','thread_link':parked['thread_link']})
   result['tasks']={'needs_decision':needs,'processing':processing,'worth_review':worth};result['connections']=[{'channel_id':key,'status':'not-connected','mode':'manual','permissions':[]} for key in foundation['configuration']['document']['channels']]
   return result
