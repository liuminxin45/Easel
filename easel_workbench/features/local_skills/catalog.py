"""Small local descriptors and exact selected packages; never a model executor."""
from __future__ import annotations
import copy,json,os,re,shutil,uuid
from functools import lru_cache
from pathlib import Path
from .install import digest,encoded,atomic
from .taxonomy import STAGES,CATEGORIES


@lru_cache(maxsize=8)
def _read(path,mtime):return json.loads(Path(path).read_text(encoding='utf-8'))


def checked_path(base, name):
 """Keep local packages and frozen input files inside their declared tree."""
 base=Path(base).absolute();relative=Path(name)
 if relative.is_absolute() or relative.drive or not relative.parts or any(part=='..' or ':' in part for part in relative.parts):
  raise ValueError('技能资源路径无效')
 current=base
 for part in relative.parts:
  current=current/part
  if current.is_symlink() or getattr(current,'is_junction',lambda:False)():raise ValueError('技能资源不能经链接跳转')
 if not current.resolve().is_relative_to(base.resolve()):raise ValueError('技能资源越界')
 return current


class Library:
 def __init__(self,root):self.root=Path(root).resolve();self.home=self.root/'.local/third-party-skills'
 def document(self):
  path=self.home/'catalog.json'
  if not path.is_file():return {'schema':1,'revision':'','skills':[],'sources':[]}
  return _read(str(path),path.stat().st_mtime_ns)
 def rows(self):return self.document()['skills']
 def find(self,sid):return next((item for item in self.rows() if item['id']==sid),None)
 def package(self,item):
  source=next(source for source in self.document()['sources'] if source['repository']==item['repository'] and source['commit']==item['commit'])
  directory=checked_path(self.root,Path('.local/third-party-skills')/source['directory'])
  return source,directory
 def available(self,item):
  _,directory=self.package(item)
  return checked_path(directory,item['entry']).is_file()
 def descriptors(self):
  from .stars import values
  stars=values(self.root);result=[]
  for item in self.rows():
   blocked=item.get('execution_blocked','') if self.available(item) else '本地技能原件缺失，请重新安装该来源'
   result.append({'name':item.get('reuse',item['id']),'description':item['description'],'display_name':item['display_name'],
    'layer':item['layer'],'needsApi':False,'apiConfigured':True,'executionBlocked':blocked,
    'local_skill':{'id':item['id'],'repository':item['repository'],'url':'https://github.com/'+item['repository'],
      'commit':item['commit'],'category':item['category'],'category_label':item['category_label'],
      'original_name':item['original_name'],'stages':item['stages'],'tags':item['tags'],
      'validation_state':item.get('validation_state','source_checked'),'reuse':item.get('reuse'),
      'stars':stars.get(item['repository'],{}).get('count'),
      'checked_at':stars.get(item['repository'],{}).get('checked_at')}})
  return result
 def summary(self):
  return {'revision':self.document()['revision'],'skills':self.descriptors(),'stages':STAGES,
          'categories':{key:value[0] for key,value in CATEGORIES.items()}}
 def verify(self):
  for source in self.document()['sources']:
   directory=checked_path(self.root,Path('.local/third-party-skills')/source['directory'])
   for name,expected in source['files'].items():
    path=checked_path(directory,name)
    if not path.is_file() or digest(path.read_bytes())!=expected:
     raise ValueError('本地技能原件已变化：'+source['repository']+'/'+name)
  return {'revision':self.document()['revision'],'repositories':len(self.document()['sources']),'skills':len(self.rows())}
 def selection(self,choices,revision,format):
  if not isinstance(choices,dict) or set(choices)-set(STAGES):raise ValueError('辅助技能阶段无效')
  if not choices:return []
  if revision!=self.document()['revision']:raise ValueError('辅助技能库已有变化，请重新选择')
  result=[]
  for stage,sid in choices.items():
   item=self.find(sid)
   if not item or stage not in item['stages']:raise ValueError('辅助技能与所选阶段不匹配')
   if format=='poster' and stage=='layout':raise ValueError('公众号文章排版不用于贴图组')
   if not self.available(item):raise ValueError('本地技能原件缺失')
   if item.get('execution_blocked'):raise ValueError(item['execution_blocked'])
   result.append({'stage':stage,**item})
  return result
 def freeze(self,items,turn_id):
  if not items:return ''
  if not re.fullmatch('[A-Za-z0-9_.-]{1,128}',turn_id) or turn_id in ('.','..'):raise ValueError('技能输入回合身份无效')
  selection=[{key:item[key] for key in ('id','commit','entry','repository','stage')} for item in items]
  from easel_workbench.paths import owned_output_path
  fingerprint=digest(encoded(selection));parent=owned_output_path(self.root,Path('outputs/_sessions/local-skill-inputs')/turn_id)
  target=owned_output_path(self.root,Path('outputs/_sessions/local-skill-inputs')/turn_id/fingerprint)
  if target.exists():
   saved=json.loads(checked_path(target,'manifest.json').read_text(encoding='utf-8'))
   if saved['selection']!=selection:raise ValueError('本轮技能输入身份不一致')
   for name,expected in saved['files'].items():
    if digest(checked_path(target,name).read_bytes())!=expected:raise ValueError('冻结辅助技能已变化')
  else:
   parent.mkdir(parents=True,exist_ok=True);staging=parent/('.'+uuid.uuid4().hex);staging.mkdir();files={};total=0
   try:
    for item in items:
     source,directory=self.package(item);base=Path(item['entry']).parent
     # Preserve a selected skill's relative resources. Same-repository sibling
     # links are copied as supporting files, not activated as additional methods.
     names={name for name in source['files'] if base==Path('.') or Path(name).is_relative_to(base)}
     text=checked_path(directory,item['entry']).read_text(encoding='utf-8-sig')
     for match in re.findall(r'(?:\.\./)+[\w./-]+',text):
      candidate=(directory/base/match).resolve()
      if candidate.is_relative_to(directory):
       prefix=candidate.relative_to(directory).as_posix().rstrip('/')
       names.update(name for name in source['files'] if name==prefix or name.startswith(prefix+'/'))
     for name in names:
      path=checked_path(directory,name)
      raw=path.read_bytes()
      if digest(raw)!=source['files'][name]:raise ValueError('技能资源已变化，请重新安装')
      relative=Path(item['id'])/name;key=relative.as_posix()
      if key in files:continue
      total+=len(raw)
      if total>40*1024*1024:raise ValueError('本轮所选辅助技能超过40MB，请减少辅助阶段')
      dest=staging/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw);files[key]=digest(raw)
    atomic(staging/'manifest.json',{'schema':1,'selection':selection,'files':files})
    try:staging.rename(target)
    except FileExistsError:
     if not staging.resolve().is_relative_to(parent.resolve()):raise ValueError('临时技能目录越界')
     shutil.rmtree(staging)
   except BaseException:
    if staging.exists():
     if not staging.resolve().is_relative_to(parent.resolve()):raise ValueError('临时技能目录越界')
     shutil.rmtree(staging)
    raise
  lines=['\n\n## 本轮明确选定的辅助技能（固定版本）',
   '仅在下列阶段应用对应方法，按研究、写作、润色、审稿、排版、配图的适用顺序处理；不运行其它整套主流程。',
   '用户本轮范围、画像、事实与油猪主生产技能的交付规范优先。原技能中的其它作者身份、默认个人经历、旧账号、自动学习或发布不能继承。',
   '已提供的主题、来源、画像与选择不要重复询问；制作不额外确认费用。不得自动切换模型、另起Agent或重发旧任务。',
   '以下文件为本轮只读输入；相对资源按其原目录读取，输出仍保存到本项目本版产物目录。原文里的 Skill/Read/Bash 等名称须映射到当前引擎真实工具，不冒称存在调用API。']
  for item in items:
   lines.append(STAGES.get(item['stage'],item['stage'])+'：'+item['display_name']+'；先完整读取 '+str(target/item['id']/item['entry']))
   lines.append('该方法的源仓库相对路径以 '+str(target/item['id'])+' 为根；原文中的仓库路径须映射到这里，不从项目根或全局技能目录找同名文件。缺少必要服务/工具时如实说明，不安装新服务或擅自改用另一执行器。')
  lines.append('完整字节清单：'+str(target/'manifest.json'))
  return '\n'.join(lines)
