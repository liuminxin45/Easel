"""Repository-scoped display metadata, independent of execution fingerprints."""
from __future__ import annotations
import json,time,threading
from pathlib import Path
import httpx
from .install import atomic

_running=set();_guard=threading.Lock()

def values(root):
 path=Path(root)/'.local/third-party-skills/stars.json'
 try:return json.loads(path.read_text(encoding='utf-8')).get('sources',{})
 except (OSError,ValueError):return {}

def refresh(root,*,client=None):
 from .catalog import Library
 from easel_workbench.runtime.feedback_ledger import locked
 root=Path(root);path=root/'.local/third-party-skills/stars.json'
 path.parent.mkdir(parents=True,exist_ok=True)
 with locked(path.with_suffix('.lock'),timeout=1):
  sources=values(root);own=client is None;client=client or httpx.Client(trust_env=False,timeout=12,follow_redirects=True)
  failures=0
  try:
   for package in Library(root).document()['sources']:
    repo=package['repository'];previous=sources.get(repo,{})
    headers={'Accept':'application/vnd.github+json'}
    if previous.get('etag'):headers['If-None-Match']=previous['etag']
    try:
     response=client.get('https://api.github.com/repos/'+repo,headers=headers)
     if response.status_code==304 and type(previous.get('count')) is int:
      sources[repo]={**previous,'checked_at':time.time()}
     elif response.status_code==200:
      count=response.json().get('stargazers_count')
      if type(count) is not int or count<0:raise ValueError('Invalid repository star count')
      sources[repo]={'count':count,'checked_at':time.time(),'etag':response.headers.get('etag')}
     elif response.status_code in (403,429):
      retry=float(response.headers.get('retry-after','60'))
      reset=float(response.headers.get('x-ratelimit-reset','0'))
      atomic(path,{'sources':sources,'checked_at':time.time(),'retry_at':max(time.time()+retry,reset)})
      return {'complete':False,'rate_limited':True}
     else:failures+=1
    except (httpx.HTTPError,ValueError):failures+=1
    atomic(path,{'sources':sources,'checked_at':time.time(),'failures':failures})
  finally:
   if own:client.close()
 return {'complete':not failures,'sources':len(sources),'failures':failures}

def schedule(root,*,force=False):
 root=Path(root).resolve();path=root/'.local/third-party-skills/stars.json'
 if not (root/'.local/third-party-skills/catalog.json').is_file():return False
 try:cache=json.loads(path.read_text(encoding='utf-8'))
 except (OSError,ValueError):cache={}
 if cache.get('retry_at',0)>time.time():return False
 if not force and time.time()-cache.get('checked_at',0)<86400:return False
 key=str(root)
 with _guard:
  if key in _running:return True
  _running.add(key)
 def work():
  try:refresh(root)
  except Exception:pass  # Read-only metadata must never take down chat or discovery.
  finally:
   with _guard:_running.discard(key)
 threading.Thread(target=work,name='easel-local-skill-stars',daemon=True).start()
 return True

def status(root):
 with _guard:running=str(Path(root).resolve()) in _running
 try:cache=json.loads((Path(root)/'.local/third-party-skills/stars.json').read_text(encoding='utf-8'))
 except (OSError,ValueError):cache={}
 return {'running':running,'sources':cache.get('sources',{}),'retry_at':cache.get('retry_at',0),'failures':cache.get('failures',0)}
