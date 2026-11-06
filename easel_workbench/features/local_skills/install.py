"""Install complete pinned repositories locally, using skill-installer's archive helper.

No imported script, package manager, hook or model is executed by installation.
"""
from __future__ import annotations
import hashlib,importlib.util,json,os,re,shutil,subprocess,tempfile,time
from pathlib import Path
import httpx,yaml
from concurrent.futures import ThreadPoolExecutor
from .taxonomy import classify


def digest(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def atomic(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 temporary=path.with_name(path.name+'.'+str(os.getpid())+'.tmp')
 temporary.write_bytes(encoded(value));os.replace(temporary,path)


def helper():
 path=Path.home()/'.codex/skills/.system/skill-installer/scripts/install-skill-from-github.py'
 if not path.is_file():raise ValueError('缺少本机 skill-installer 安装助手')
 import sys
 sys.path.insert(0,str(path.parent))
 spec=importlib.util.spec_from_file_location('local_skill_installer',path)
 module=importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
 return module


def install(root,*,progress=print,repositories=None,workers=3):
 from easel_workbench.runtime.feedback_ledger import locked
 root=Path(root).resolve()
 with locked(root/'.local/third-party-skills/install.lock',timeout=1):
  return _install(root,progress=progress,repositories=repositories,workers=workers)


def _install(root,*,progress=print,repositories=None,workers=3):
 root=Path(root).resolve();home=root/'.local/third-party-skills';home.mkdir(parents=True,exist_ok=True)
 config=json.loads((root/'config/local-skill-sources.json').read_text(encoding='utf-8')) if repositories is None else {}
 repositories=config.get('repositories',[]) if repositories is None else repositories
 pins=config.get('commits',{})
 installer=helper();sources=[];skills=[];errors=[]
 with httpx.Client(trust_env=False,timeout=15,follow_redirects=True) as client:
  # Reuse the helper's safe extraction, with the project's explicit network environment.
  def download(url):
   started=time.monotonic();parts=[];size=0;last=started
   with client.stream('GET',url) as result:
    result.raise_for_status()
    for part in result.iter_raw():
     size+=len(part)
     if size>512*1024*1024 or time.monotonic()-started>600:raise ValueError('来源下载超过大小或总时限')
     parts.append(part)
     if time.monotonic()-last>15:
      progress(json.dumps({'phase':'receiving','bytes':size,'seconds':int(time.monotonic()-started)},ensure_ascii=False),flush=True);last=time.monotonic()
   return b''.join(parts)
  installer._request=download
  if hasattr(installer,'_run_git'):
   def run_git(command):
    result=subprocess.run([command[0],'-c','core.hooksPath=NUL','-c','core.autocrlf=false','-c','core.symlinks=false',*command[1:]],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=180,
                          env={**os.environ,'GIT_TERMINAL_PROMPT':'0','GCM_INTERACTIVE':'never'})
    if result.returncode:raise installer.InstallError(result.stderr[:1000])
    return result.stdout
   installer._run_git=run_git
  def fetch(repo):
   try:
    progress(json.dumps({'repository':repo,'phase':'downloading'},ensure_ascii=False),flush=True)
    if not re.fullmatch(r'[\w.-]+/[\w.-]+',repo):raise ValueError('无效来源仓库')
    sha=pins.get(repo) or subprocess.check_output(['git','ls-remote','https://github.com/'+repo+'.git','HEAD'],text=True,timeout=50).split()[0]
    if not re.fullmatch('[a-f0-9]{40}',sha):raise ValueError('未取得准确Git提交')
    destination=home/'packages'/repo/sha
    receipt=home/'receipts'/repo/(sha+'.json')
    links=[]
    if not destination.exists() or not receipt.is_file():
     with tempfile.TemporaryDirectory(prefix='easel-skill-') as temporary:
      if hasattr(installer,'_git_sparse_checkout'):
       source=Path(installer._git_sparse_checkout('https://github.com/'+repo+'.git',sha,['.'],temporary))
       # The helper starts sparse; this import promises every nested skill and
       # supporting file, so materialize the entire exact commit before copying.
       installer._run_git(['git','-C',str(source),'sparse-checkout','disable'])
       tree=installer._run_git(['git','-C',str(source),'ls-files','--stage','-z'])
       links=[entry.split('\t',1)[1] for entry in tree.split('\0') if entry.startswith('120000 ')]
      else:source=Path(installer._download_repo_zip(*repo.split('/'),sha,temporary))
      for path in source.rglob('*'):
       if '.git' in path.relative_to(source).parts:continue
       if path.is_symlink() or getattr(path,'is_junction',lambda:False)():raise ValueError('来源包含链接，请人工核对：'+path.relative_to(source).as_posix())
      destination.parent.mkdir(parents=True,exist_ok=True)
      staging=destination.with_name('.'+sha+'.'+str(os.getpid()))
      shutil.copytree(source,staging,ignore=shutil.ignore_patterns('.git','node_modules','__pycache__','*.pyc','.env','.env.local'))
      if destination.exists():
       archive=home/'archives'/repo/(sha+'-'+str(time.time_ns()))
       if not destination.resolve().is_relative_to(home.resolve()) or not archive.resolve().is_relative_to(home.resolve()):raise ValueError('来源归档路径越界')
       archive.parent.mkdir(parents=True,exist_ok=True);destination.rename(archive)
      staging.rename(destination)
      atomic(receipt,{'repository':repo,'commit':sha,'complete_checkout':True,'link_paths':links})
    else:links=json.loads(receipt.read_text(encoding='utf-8')).get('link_paths',[])
    return repo,sha,destination,links,None
   except Exception as error:return repo,None,None,[],error
  with ThreadPoolExecutor(max_workers=max(1,min(3,workers))) as pool:
   downloaded=list(pool.map(fetch,repositories))
  for repo,sha,destination,links,error in downloaded:
   try:
    if error:raise error
    files={p.relative_to(destination).as_posix():digest(p.read_bytes()) for p in sorted(destination.rglob('*')) if p.is_file()}
    package={'repository':repo,'commit':sha,'directory':destination.relative_to(home).as_posix(),'files':files,'link_paths':links,
             'license_paths':[name for name in files if Path(name).name.upper().startswith(('LICENSE','COPYING'))]}
    sources.append(package)
    for name in files:
     if Path(name).name!='SKILL.md' or name in links:continue
     path=destination/name;raw=path.read_text(encoding='utf-8-sig')
     match=re.match(r'\A---\s*\n(.*?)\n---(?:\n|$)',raw,re.S)
     try:meta=yaml.safe_load(match[1]) if match else {}
     except yaml.YAMLError:meta={}
     if not isinstance(meta,dict):meta={}
     sid='local-'+digest((repo+':'+name).encode())[:16]
     entry={'id':sid,'repository':repo,'commit':sha,'entry':name,'original_name':str(meta.get('name') or path.parent.name),
            **classify(repo,name,meta),'installed':True,'validation_state':'source_checked'}
     # A method that requires another service is not automatically verified by copying files.
     required=[]
     if repo=='imraywang/wewrite':required=['WeWrite CLI（独立本轮工作目录）']
     elif repo=='geekjourneyx/md2wechat-skill':required=['md2wechat CLI 与所选排版/配图服务']
     elif repo=='white0dew/XiaohongshuSkills':required=['小红书浏览器驱动与登录态']
     elif 'WoopSocial' in raw and re.search(r'\b(MCP|mcp)\b',raw):required=['WoopSocial MCP 服务']
     elif entry['category']=='publish':required=['发布通道与本次明确交付授权']
     elif re.search(r'\b(Bash|Read|Write|Edit|WebSearch)\b',raw):
      # These are runtime tools, supplied by the existing native Agent, not packages.
      required=[]
     entry['requirements']=required;entry['execution_blocked']='需配置：'+'、'.join(required) if required else ''
     if repo=='isjiamu/gzh-design-skill' and (root/'skills/builtin/gzh-design/SKILL.md').is_file():
      # Only alias when every installed source file actually agrees with the native copy.
      native=root/'skills/builtin/gzh-design'
      if all((native/file).is_file() and digest((native/file).read_bytes())==value for file,value in files.items()):entry['reuse']='gzh-design'
     skills.append(entry)
    progress(json.dumps({'repository':repo,'commit':sha,'skills':sum(s['repository']==repo for s in skills),'installed':True},ensure_ascii=False),flush=True)
   except Exception as error:
    errors.append({'repository':repo,'error_type':type(error).__name__,'error':str(error)[:250]})
    progress(json.dumps(errors[-1],ensure_ascii=False),flush=True)
 if errors:
  atomic(home/'install-errors.json',errors)
  raise ValueError('部分来源安装失败；已保存原件，未激活不完整技能库：'+str(len(errors)))
 revision=digest(encoded([{'repository':s['repository'],'commit':s['commit'],'files':s['files']} for s in sources]))
 document={'schema':1,'revision':revision,'sources':sources,'skills':skills,'installed_at':time.time()}
 # Tiny project-local native entries. Their entire path is Git-ignored.
 for item in skills:
  if item.get('reuse'):continue
  path=root/'skills/builtin'/item['id']/'SKILL.md';path.parent.mkdir(parents=True,exist_ok=True)
  metadata={'name':item['id'],'description':item['display_name']+'。来源：'+item['repository']+'。'+item['description'],'layer':item['layer']}
  path.write_text('---\n'+yaml.safe_dump(metadata,allow_unicode=True,sort_keys=False)+'---\n\n# '+item['display_name']+'\n\n本地第三方技能。仅使用本轮宿主提供的冻结技能清单，不自行寻找当前原件、不修改技能或账号。原作者：'+item['repository']+'。\n',encoding='utf-8')
 atomic(home/'catalog.json',document)
 inventory=['# 本地第三方技能清单','',f'仓库 {len(sources)}；技能 {len(skills)}；内容版本 {revision}','','| 中文名 | 分类 | 来源 | 原始技能 | 状态 |','| --- | --- | --- | --- | --- |']
 inventory += ['| '+' | '.join(str(item.get(key,'')).replace('|','/') for key in ('display_name','category_label','repository','original_name'))+' | '+(item['execution_blocked'] or '已安装；工具在执行前核对')+' |' for item in skills]
 (home/'安装清单.md').write_text('\n'.join(inventory)+'\n',encoding='utf-8')
 return {'repositories':len(sources),'skills':len(skills),'revision':revision}
