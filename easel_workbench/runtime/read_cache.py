"""Authenticated, bounded read-view caching. Business JSON never persists here."""
from __future__ import annotations
import asyncio,copy,datetime as dt,hashlib,json,pathlib,re,sqlite3,threading,time
from contextlib import closing
from collections import OrderedDict
from dataclasses import dataclass
from fastapi.responses import JSONResponse,Response

GROUPS={
 'creator':('creator_profiles','creator_profile_history','creator_skills','creator_skill_versions','creator_skill_pointers','creator_task_runs','creator_model_calls','creator_work_owners'),
 'learning':('learning_evidence','learning_proposals','learning_analysis_queue','learning_operations'),
 'creative_quality':('learning_runs','learning_correction_links','learning_quality_acknowledgements'),
 'news':('articles','runs','provenance','periodical_batches','periodical_issues','periodical_items','periodical_themes','news_feedback','collection_source_versions'),
 'works':('toolbox_works','toolbox_jobs','toolbox_files','toolbox_work_options','toolbox_article_drafts','toolbox_article_inputs','toolbox_text_versions','toolbox_production_outcomes','toolbox_dispatch_retries','toolbox_review_notes','toolbox_review_events','toolbox_review_inputs','toolbox_completions','toolbox_style_presets','artifacts','toolbox_direct_turns','toolbox_archive'),
 'studio':('studio_records',),
 'distribution':('distribution_connections','distribution_revisions','distribution_approvals','distribution_deliveries','distribution_attempts','distribution_observations','distribution_check_monitor_state'),
}

def initialize(c,groups=GROUPS):
 c.execute('CREATE TABLE IF NOT EXISTS read_cache_revisions(domain TEXT PRIMARY KEY, revision INTEGER NOT NULL DEFAULT 0)')
 tables={row[0] for row in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
 for domain,members in groups.items():
  c.execute('INSERT OR IGNORE INTO read_cache_revisions(domain,revision) VALUES(?,0)',(domain,))
  for member in members:
   if member not in tables:continue
   for action in ('INSERT','UPDATE','DELETE'):
    name='read_revision_'+domain+'_'+member+'_'+action.lower()
    c.execute(f'CREATE TRIGGER IF NOT EXISTS "{name}" AFTER {action} ON "{member}" BEGIN UPDATE read_cache_revisions SET revision=revision+1 WHERE domain=\'{domain}\'; END')

@dataclass(frozen=True)
class Policy:
 domains:tuple[str,...]
 ttl:float=30
 assets:bool=False
 foundation:bool=False
 overviews:bool=False

def policy(path):
 if path=='/api/news' or re.fullmatch(r'/api/news/[A-Za-z0-9_-]+',path):return Policy(('news','works'),overviews=True)
 if path=='/api/works':return Policy(('works',),assets=True)
 if re.fullmatch(r'/api/works/[A-Za-z0-9_-]+',path):return Policy(('works','studio','creative_quality','creator'),3,assets=True)
 if re.fullmatch(r'/api/works/[A-Za-z0-9_-]+/(completion|versions/[A-Za-z0-9_-]+/review)',path):return Policy(('works','studio','creative_quality'),3,assets=True)
 if path=='/api/history':return Policy(('works',),assets=True)
 if path=='/api/studio/bootstrap':return Policy(('works','news','studio'),3,True,True)
 if path=='/api/studio/foundation':return Policy(('studio',),foundation=True)
 if path=='/api/style-presets':return Policy(('works','studio'),foundation=True)
 # These endpoints evaluate leases/runtime and therefore always execute their
 # original read logic. They still benefit from semantic conditional responses.
 if path=='/api/distribution/bootstrap':return Policy(('works','studio','distribution'),0,True,True)
 if path=='/api/collection/status':return Policy(('news',),0)
 if path=='/api/creator/bootstrap':return Policy(('creator','learning','distribution','works'),3)
 if re.fullmatch(r'/api/creator/(profiles|skills|runs)/[A-Za-z0-9_-]+',path):return Policy(('creator',),3)
 return None

def _recovery(value):return isinstance(value,dict) and 'job_id' in value and 'failure_kind' in value and 'max_auto_retries' in value

def semantic(value):
 if isinstance(value,list):return [semantic(row) for row in value]
 if isinstance(value,dict):return {key:semantic(row) for key,row in value.items() if not(key=='server_now' and _recovery(value))}
 return value

def clocked(value,now):
 if isinstance(value,list):return [clocked(row,now) for row in value]
 if isinstance(value,dict):return {key:(now if key=='server_now' and _recovery(value) else clocked(row,now)) for key,row in value.items()}
 return value

def matches(header,etag):
 normalize=lambda value:value.strip().removeprefix('W/')
 return bool(header and any(row.strip()=='*' or normalize(row)==normalize(etag) for row in header.split(',')))

class ViewCache:
 def __init__(self,store,root,project,*,max_bytes=16*1024*1024,max_entries=128,clock=time.monotonic):
  self.store=store;self.root=pathlib.Path(root).resolve();self.project=pathlib.Path(project).resolve();self.max_bytes=max_bytes;self.max_entries=max_entries;self.clock=clock
  self.entries=OrderedDict();self.locks={};self.mutex=threading.RLock();self.bytes=0
  self.stats={'hits':0,'misses':0,'not_modified':0,'computations':0,'unstable':0}
  with self.store.connect() as c:initialize(c)
  self.aux=self.root/'data/news-overviews.sqlite'
  if self.aux.exists():
   with closing(sqlite3.connect(self.aux)) as c:
    with c:initialize(c,{'overviews':('overviews',)})

 def _revisions(self,domains):
  with self.store.connect() as c:
   values={row['domain']:row['revision'] for row in c.execute('SELECT domain,revision FROM read_cache_revisions')}
  return tuple((domain,values.get(domain,0)) for domain in domains)

 @staticmethod
 def _stat(path):
  try:
   stat=path.stat();return (stat.st_size,stat.st_mtime_ns,stat.st_ctime_ns)
  except OSError:return None

 def _assets(self):
  with self.store.connect() as c:paths=[row[0] for row in c.execute('SELECT path FROM artifacts UNION SELECT path FROM toolbox_files')]
  result=[]
  for raw in paths:
   path=pathlib.Path(raw).resolve()
   if any(path.is_relative_to((self.root/part).resolve()) for part in ('data/artifacts','data/toolbox/files','data/workbench')):result.append((str(path),self._stat(path)))
  return tuple(sorted(result))

 def _foundation(self):
  from easel_workbench.runtime.studio_service import SECTIONS,CONTEXT_FILES,CONFIG_PATH
  names={*[value[1] for value in SECTIONS.values()],*CONTEXT_FILES.values(),CONFIG_PATH}
  # Dependency rules are the allowlisted project specifications, not arbitrary
  # caller paths. Including their names catches additions/deletions as well.
  directory=self.project/'规范'
  if directory.is_dir():names.update(str(path.relative_to(self.project)) for path in directory.rglob('*.md') if path.is_file())
  return tuple((name,self._stat(self.project/name)) for name in sorted(names))

 def signature(self,p):
  result=[self._revisions(p.domains)]
  if p.assets:result.append(self._assets())
  if p.foundation:result.append(self._foundation())
  if p.overviews and self.aux.exists():
   with closing(sqlite3.connect(self.aux)) as c:
    row=c.execute("SELECT revision FROM read_cache_revisions WHERE domain='overviews'").fetchone();result.append(row[0] if row else None)
  # Legacy native-download capabilities change once per hour; a cached response
  # must never retain an obsolete signing window indefinitely.
  result.append(int(time.time())//3600)
  return hashlib.sha256(repr(result).encode()).hexdigest()

 def _get(self,key,signature,p):
  with self.mutex:
   entry=self.entries.get(key)
   if entry and p.ttl>0 and entry['signature']==signature and self.clock()<entry['until']:
    self.entries.move_to_end(key);return copy.deepcopy(entry)
  return None

 def _put(self,key,entry):
  size=entry['size']
  if size>self.max_bytes:return
  with self.mutex:
   old=self.entries.pop(key,None)
   if old:self.bytes-=old['size']
   self.entries[key]=entry;self.bytes+=size
   while self.entries and (self.bytes>self.max_bytes or len(self.entries)>self.max_entries):
    _,old=self.entries.popitem(last=False);self.bytes-=old['size']

 async def respond(self,request,scope,loader,p):
  key=(scope,request.url.path,request.url.query)
  # Locks exist only while a request is running. Avoid a second unbounded map.
  with self.mutex:
   slot=self.locks.setdefault(key,{'lock':asyncio.Lock(),'users':0});slot['users']+=1
  try:
   async with slot['lock']:
    try:signature=await asyncio.to_thread(self.signature,p)
    except (OSError,sqlite3.Error):return await loader()
    entry=self._get(key,signature,p);hit=entry is not None
    if hit:self.stats['hits']+=1
    else:
     self.stats['misses']+=1
     for attempt in range(2):
      self.stats['computations']+=1;response=await loader()
      if response.status_code!=200 or not response.headers.get('content-type','').startswith('application/json'):return response
      value=json.loads(response.body)
      try:after=await asyncio.to_thread(self.signature,p)
      except (OSError,sqlite3.Error):return response
      if after==signature:break
      self.stats['unstable']+=1;signature=after
     else:
      # A continuously changing view must not validate a pre-write body as
      # current. Return its latest read normally without admitting it to cache.
      return JSONResponse(clocked(value,dt.datetime.now(dt.timezone.utc).isoformat()),headers={'Cache-Control':'no-store','X-Workbench-Cache':'unstable','X-Workbench-Server-Time':dt.datetime.now(dt.timezone.utc).isoformat()})
     canonical=json.dumps(semantic(value),ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
     entry={'data':value,'etag':'W/"'+hashlib.sha256(canonical).hexdigest()+'"','size':len(response.body),'until':self.clock()+p.ttl,'signature':signature}
     if p.ttl>0:self._put(key,entry)
    now=dt.datetime.now(dt.timezone.utc).isoformat()
    headers={'Cache-Control':'no-store','ETag':entry['etag'],'X-Workbench-Server-Time':now,'X-Workbench-Cache':'hit' if hit else 'miss','Vary':'Accept-Encoding, Cookie'}
    if matches(request.headers.get('if-none-match'),entry['etag']):
     self.stats['not_modified']+=1;return Response(status_code=304,headers=headers)
    return JSONResponse(clocked(entry['data'],now),headers=headers)
  finally:
   with self.mutex:
    slot['users']-=1
    if not slot['users']:self.locks.pop(key,None)
