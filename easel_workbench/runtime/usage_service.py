"""First-party allowlisted interaction metadata, isolated from creative storage."""
from __future__ import annotations
import contextlib,datetime as dt,hashlib,hmac,json,pathlib,re,secrets,sqlite3,time,uuid

REGISTRY=json.loads(pathlib.Path(__file__).with_name('usage_registry.json').read_text(encoding='utf-8'))
KINDS={'attempt','view','exposure','activate','commit','dismiss','accepted','failed','uncertain','local_success'}
FIELDS={'event_id','journey_id','visit_id','seq','at','kind','screen','surface','action','platform','input','release','operation_id','from_screen','direction','lost'}
UUID=re.compile(r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$')
PLATFORMS={'android','windows','legacy','unknown'}
TZ=dt.timezone(dt.timedelta(hours=8))

class UsageError(ValueError):status=400
class UsageUnavailable(UsageError):status=503

class SafeUsageService:
 """A failed analytics database never prevents creative server startup/config."""
 def __init__(self,store,root,*,clock=time.time):self.store=store;self.root=root;self.clock=clock;self.service=None;self.last_attempt=float('-inf')
 def _get(self):
  if self.service is not None:return self.service
  if self.clock()-self.last_attempt<30:raise UsageUnavailable('使用统计暂时不可用，创作不受影响')
  self.last_attempt=self.clock()
  try:self.service=UsageService(self.store,self.root,clock=self.clock)
  except (sqlite3.Error,OSError):raise UsageUnavailable('使用统计暂时不可用，创作不受影响') from None
  return self.service
 def _call(self,name,*args):
  try:return getattr(self._get(),name)(*args)
  except (sqlite3.Error,OSError):
   self.service=None;self.last_attempt=self.clock();raise UsageUnavailable('使用统计暂时不可用，创作不受影响') from None
 def config(self,session_key):
  try:return {**self._call('config',session_key),'available':True}
  except UsageUnavailable:return {'available':False,'enabled':False,'schema_version':1,'raw_days':30,'aggregate_days':180,'queue_days':7,'queue_limit':5000,'queue_bytes':2*1024*1024}
 def ingest(self,session_key,value):return self._call('ingest',session_key,value)
 def summary(self,session_key,query=None):return self._call('summary',session_key,query)
 def settings(self,session_key,value):return self._call('settings',session_key,value)
 def clear(self,session_key,value):return self._call('clear',session_key,value)

class UsageService:
 def __init__(self,store,root,*,clock=time.time):
  self.store=store;self.root=pathlib.Path(root);self.path=self.root/'data/usage.sqlite';self.path.parent.mkdir(parents=True,exist_ok=True);self.clock=clock
  with self.connect() as c:
   c.executescript('''CREATE TABLE IF NOT EXISTS usage_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS usage_events(id TEXT PRIMARY KEY,scope TEXT NOT NULL,at REAL NOT NULL,day TEXT NOT NULL,journey TEXT NOT NULL,visit TEXT NOT NULL,seq INTEGER NOT NULL,kind TEXT NOT NULL,screen TEXT NOT NULL,surface TEXT NOT NULL,action TEXT NOT NULL,platform TEXT NOT NULL,release TEXT NOT NULL,document TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS usage_time ON usage_events(at);
CREATE TABLE IF NOT EXISTS usage_receipts(id TEXT PRIMARY KEY,signature TEXT NOT NULL,day TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS usage_daily(day TEXT NOT NULL,kind TEXT NOT NULL,screen TEXT NOT NULL,surface TEXT NOT NULL,action TEXT NOT NULL,platform TEXT NOT NULL,count INTEGER NOT NULL,PRIMARY KEY(day,kind,screen,surface,action,platform));
CREATE TABLE IF NOT EXISTS usage_edges(day TEXT NOT NULL,source TEXT NOT NULL,target TEXT NOT NULL,platform TEXT NOT NULL,count INTEGER NOT NULL,PRIMARY KEY(day,source,target,platform));''')
   for k,v in {'enabled':'true','secret':secrets.token_hex(32),'generation':secrets.token_hex(16),'since':str(self.clock())}.items():c.execute('INSERT OR IGNORE INTO usage_meta VALUES(?,?)',(k,v))
 def connect(self):
  c=sqlite3.connect(self.path,timeout=2);c.row_factory=sqlite3.Row;c.execute('PRAGMA journal_mode=WAL');return _Connection(c)
 def _meta(self,c):return {r['key']:r['value'] for r in c.execute('SELECT key,value FROM usage_meta')}
 def config(self,session_key):
  with self.connect() as c:m=self._meta(c)
  scope=hmac.new(m['secret'].encode(),(str(session_key)+':'+m['generation']).encode(),hashlib.sha256).hexdigest()
  return {'enabled':m['enabled']=='true','scope':scope,'schema_version':1,'raw_days':30,'aggregate_days':180,'queue_days':7,'queue_limit':5000,'queue_bytes':2*1024*1024,'since':float(m['since'])}
 def _event(self,value,now):
  if not isinstance(value,dict) or set(value)-FIELDS:raise UsageError('操作统计包含未允许字段')
  for key in ('event_id','journey_id','visit_id'):
   if not isinstance(value.get(key),str) or not UUID.fullmatch(value[key]):raise UsageError('统计标识无效')
  if type(value.get('seq')) is not int or not 0<=value['seq']<=10000000:raise UsageError('统计顺序无效')
  if type(value.get('at')) not in (int,float) or not now-7*86400<=value['at']<=now+300:raise UsageError('统计时间超出允许范围')
  if any(not isinstance(value.get(key),str) for key in ('kind','screen','surface','action','platform','input','release')):raise UsageError('统计枚举无效')
  if value.get('kind') not in KINDS or value.get('screen') not in REGISTRY['screens'] or value.get('surface') not in REGISTRY['surfaces']:raise UsageError('统计页面或类型未登记')
  if value.get('action','') not in REGISTRY['actions'] and not(value.get('kind')=='view' and value.get('action','')==''):raise UsageError('统计操作未登记')
  if value.get('platform') not in PLATFORMS or value.get('input') not in {'touch','mouse','keyboard','system','unknown'}:raise UsageError('统计平台无效')
  if not isinstance(value.get('release'),str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,110}',value['release']):raise UsageError('统计版本无效')
  if 'operation_id' in value and (not isinstance(value['operation_id'],str) or not UUID.fullmatch(value['operation_id'])):raise UsageError('仅关联不含内容的操作标识')
  if 'from_screen' in value and (not isinstance(value['from_screen'],str) or value['from_screen'] not in REGISTRY['screens']):raise UsageError('来源页面未登记')
  if 'direction' in value and (not isinstance(value['direction'],str) or value['direction'] not in {'initial','forward','back','replace'}):raise UsageError('导航类型无效')
  if value.get('lost') is not None and (type(value['lost']) is not int or not 0<=value['lost']<=10000000):raise UsageError('缺失计数无效')
  return value
 def ingest(self,session_key,value):
  if not isinstance(value,dict) or set(value)-{'scope','events'}:raise UsageError('统计批次无效')
  if len(json.dumps(value,ensure_ascii=False,separators=(',',':')).encode())>16384:raise UsageError('统计批次过大')
  config=self.config(session_key)
  if value.get('scope')!=config['scope']:return {'accepted':[],'discarded':True,'config':config}
  events=value.get('events')
  if not isinstance(events,list) or not 1<=len(events)<=20:raise UsageError('每批最多20条统计')
  now=self.clock();events=[self._event(e,now) for e in events]
  if not config['enabled']:return {'accepted':[e['event_id'] for e in events],'discarded':True,'config':config}
  with self.connect() as c:
   c.execute('BEGIN IMMEDIATE')
   m=self._meta(c);expected=hmac.new(m['secret'].encode(),(str(session_key)+':'+m['generation']).encode(),hashlib.sha256).hexdigest()
   if value.get('scope')!=expected or m['enabled']!='true':return {'accepted':[],'discarded':True,'config':self.config(session_key)}
   for e in events:
    raw=json.dumps(e,sort_keys=True,separators=(',',':'));signature=hashlib.sha256(raw.encode()).hexdigest();old=c.execute('SELECT signature FROM usage_receipts WHERE id=?',(e['event_id'],)).fetchone()
    if old:
     if old['signature']!=signature:raise UsageError('同一统计标识不能覆盖其它操作')
     continue
    day=dt.datetime.fromtimestamp(e['at'],TZ).date().isoformat()
    c.execute('INSERT INTO usage_receipts VALUES(?,?,?)',(e['event_id'],signature,day))
    c.execute('INSERT INTO usage_events VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(e['event_id'],config['scope'],e['at'],day,e['journey_id'],e['visit_id'],e['seq'],e['kind'],e['screen'],e['surface'],e.get('action',''),e['platform'],e['release'],raw))
    c.execute('INSERT INTO usage_daily VALUES(?,?,?,?,?,?,1) ON CONFLICT(day,kind,screen,surface,action,platform) DO UPDATE SET count=count+1',(day,e['kind'],e['screen'],e['surface'],e.get('action',''),e['platform']))
    if e.get('lost'):c.execute('INSERT INTO usage_daily VALUES(?,?,?,?,?,?,?) ON CONFLICT(day,kind,screen,surface,action,platform) DO UPDATE SET count=count+excluded.count',(day,'loss',e['screen'],e['surface'],'',e['platform'],e['lost']))
    if e['kind']=='view' and e.get('from_screen'):
     c.execute('INSERT INTO usage_edges VALUES(?,?,?,?,1) ON CONFLICT(day,source,target,platform) DO UPDATE SET count=count+1',(day,e['from_screen'],e['screen'],e['platform']))
   self._prune(c,now)
  return {'accepted':[e['event_id'] for e in events],'config':config}
 def _prune(self,c,now):
  c.execute('DELETE FROM usage_events WHERE at<?',(now-30*86400,));day=dt.datetime.fromtimestamp(now-180*86400,TZ).date().isoformat()
  c.execute('DELETE FROM usage_daily WHERE day<?',(day,));c.execute('DELETE FROM usage_edges WHERE day<?',(day,));c.execute('DELETE FROM usage_receipts WHERE day<?',(day,))
 def settings(self,session_key,value):
  if not isinstance(value,dict) or set(value)!={'enabled'} or type(value['enabled']) is not bool:raise UsageError('统计设置无效')
  with self.connect() as c:
   c.execute("UPDATE usage_meta SET value=? WHERE key='enabled'",('true' if value['enabled'] else 'false',))
   c.execute("UPDATE usage_meta SET value=? WHERE key='generation'",(secrets.token_hex(16),))
  return {'config':self.config(session_key)}
 def clear(self,session_key,value):
  if value!={'confirm':True}:raise UsageError('请明确确认清空操作统计')
  with self.connect() as c:
   for table in ('usage_events','usage_daily','usage_edges','usage_receipts'):c.execute('DELETE FROM '+table)
   c.execute("UPDATE usage_meta SET value=? WHERE key='generation'",(secrets.token_hex(16),));c.execute("UPDATE usage_meta SET value=? WHERE key='since'",(str(self.clock()),))
  return {'config':self.config(session_key),'cleared':True}
 def _ledger(self,events):
  counts={'completed':0,'failed':0,'pending':0,'published':0,'stored':0,'unmatched':0};seen=set()
  with self.store.connect() as c:
   tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
   for event in events:
    oid=event.get('operation_id')
    if not oid or oid in seen:continue
    seen.add(oid);row=c.execute('SELECT status,kind FROM toolbox_jobs WHERE id=?',(oid,)).fetchone() if 'toolbox_jobs' in tables else None
    if row:
     counts['completed' if row['status']=='completed' else 'failed' if row['status'] in ('error','blocked') else 'pending']+=1;continue
    delivery=c.execute("SELECT CASE WHEN json_valid(document) THEN json_extract(document,'$.status') END AS status,CASE WHEN json_valid(document) THEN json_extract(document,'$.remote_state') END AS remote_state,CASE WHEN json_valid(document) THEN json_type(document,'$.verified') END AS verified FROM distribution_deliveries WHERE id=?",('delivery-'+oid,)).fetchone() if 'distribution_deliveries' in tables else None
    if delivery:
     counts['published' if delivery['verified']=='true' and delivery['remote_state']=='published' else 'stored' if delivery['verified']=='true' and delivery['remote_state']=='draft' else 'failed' if delivery['status']=='failed' else 'pending' if delivery['status'] or delivery['remote_state'] else 'unmatched']+=1;continue
    row=c.execute('SELECT status FROM studio_operations WHERE operation_id=?',(oid,)).fetchone() if 'studio_operations' in tables else None
    if row:counts['stored' if row['status']=='completed' else 'pending']+=1
    else:counts['unmatched']+=1
  return counts
 def summary(self,session_key,query=None):
  q=query or {}
  try:days=int(q.get('days',7))
  except (ValueError,TypeError):raise UsageError('统计时间范围无效') from None
  platform=q.get('platform','all')
  if days not in (7,30,180) or platform not in PLATFORMS|{'all'}:raise UsageError('统计筛选无效')
  now=self.clock();cut=dt.datetime.fromtimestamp(now-(days-1)*86400,TZ).date().isoformat();where='day>=?'+(' AND platform=?' if platform!='all' else '');args=(cut,) if platform=='all' else (cut,platform)
  with self.connect() as c:
   self._prune(c,now)
   grouped=[dict(r) for r in c.execute('SELECT action,kind,SUM(count) AS count FROM usage_daily WHERE '+where+' GROUP BY action,kind',args)]
   edges=[dict(r) for r in c.execute('SELECT source,target,SUM(count) AS count FROM usage_edges WHERE '+where+' GROUP BY source,target ORDER BY count DESC LIMIT 15',args)]
   events=[json.loads(r[0]) for r in c.execute('SELECT document FROM usage_events WHERE '+where+' ORDER BY at,journey,seq',args)]
  actions=[]
  for action,label in REGISTRY['actions'].items():
   counts={r['kind']:r['count'] for r in grouped if r['action']==action};actions.append({'id':action,'label':label,**{k:counts.get(k,0) for k in KINDS}})
  actions.sort(key=lambda r:r['activate']+r['commit'],reverse=True)
  back_count=sum(e.get('direction')=='back' for e in events if e['kind']=='view');backtracks=0;journeys={}
  for e in events:
   if e['kind']=='view':journeys.setdefault(e['journey_id'],[]).append(e)
  for views in journeys.values():
   views.sort(key=lambda e:e['seq']);unique=[]
   for e in views:
    if not unique or e['screen']!=unique[-1]['screen']:unique.append(e)
   for a,b,d in zip(unique,unique[1:],unique[2:]):
    if a['screen']==d['screen'] and a['screen']!=b['screen'] and 0<=d['at']-a['at']<=120:backtracks+=1
  return {'config':self.config(session_key),'days':days,'platform':platform,'actions':actions,'paths':[{'from':REGISTRY['screens'][r['source']],'to':REGISTRY['screens'][r['target']],'count':r['count']} for r in edges],
   'totals':{kind:sum(r['count'] for r in grouped if r['kind']==kind) for kind in KINDS},'backtracks':backtracks,'back_count':back_count,'backtrack_note':'同一次工作会话两分钟内A→B→A，正常返回也会产生此线索，不自动判定为障碍。','lost':sum(r['count'] for r in grouped if r['kind']=='loss'),'ledger':self._ledger(events),
   'coverage':{'registered_actions':len(actions),'observed_actions':sum(bool(r['exposure'] or r['activate'] or r['commit']) for r in actions),'raw_days':30,'aggregate_days':180,'path_detail_available_days':min(days,30),'note':'未观察到的操作不等于从未使用；180天仅保留频率和页面转换，业务结果与折返详情仅覆盖最近30天。'},'schema_version':1}

class _Connection:
 def __init__(self,c):self.c=c
 def __enter__(self):return self.c
 def __exit__(self,*exc):
  try:self.c.__exit__(*exc)
  finally:self.c.close()
