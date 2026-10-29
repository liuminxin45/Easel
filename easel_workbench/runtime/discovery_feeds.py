"""Bounded public discovery feeds. No account, posting, LLM or remote execution."""
import datetime as dt,hashlib,json,pathlib,sqlite3,time,urllib.request,urllib.error
from easel_workbench.runtime.project_paths import ROOT
from easel_workbench.runtime.feedback_ledger import atomic,locked
UTC=dt.timezone.utc
DEADLINE=float('inf')
NAMES={'xinquji':'新趣集','github-trending':'GitHub Trending','product-hunt':'Product Hunt','hacker-news':'Hacker News'}

def publish(source,items,*,root=ROOT,store=None,health=None,metadata=None,limit=10):
 from easel_workbench.runtime import desk as desk
 from easel_workbench.runtime.collection_health import site_health
 store=store or desk.Store();health=health or site_health
 state=root/'data/discovery';state.mkdir(parents=True,exist_ok=True)
 intent=state/(source+'-intent.json')
 with locked(state/(source+'.lock'),timeout=2):
  if intent.exists():doc=json.loads(intent.read_text(encoding='utf-8'))
  else:
   with store.connect() as c:seen={r[0] for r in c.execute('select source_event_id from articles where source_job=?',(source,))}
   unique={}
   for a in items:
    if a['source_event_id'] not in seen:unique.setdefault(a['source_event_id'],a)
   rows=list(unique.values())[:limit]
   if not rows:return {'status':'no_new_items','inserted':0,'article_ids':[],'candidate_count':len(items)}
   when=dt.datetime.now(UTC).isoformat()
   text='\n\n'.join(f"{i}. {a['title']}\n{a['body']}\n{a['url']}" for i,a in enumerate(rows,1))
   doc={'schema_version':1,'source_job':source,'feed_id':desk.SOURCES[source]['feed'],'run_id':source+'-'+hashlib.sha256(text.encode()).hexdigest(),'run_at':when,'final_text':text,'articles':rows,'collection':metadata or {}}
   atomic(intent,doc)
  if not health():raise RuntimeError('Reading desk health unavailable; durable intent retained')
  receipt=desk.save_digest(doc,store,root=root)
  expected={desk.article_identity(source,a):a for a in doc['articles']}
  with store.connect() as c:
   run=c.execute('select * from runs where id=?',(receipt['run'],)).fetchone()
   actual={r['id']:dict(r) for r in c.execute('select a.* from articles a join provenance p on a.id=p.article_id where p.run=?',(receipt['run'],))}
  if not run or run['source_job']!=source or run['run_id']!=doc['run_id'] or run['hash']!=desk.digest(doc['final_text']) or run['final_text']!=doc['final_text'] or set(actual)!=set(expected):raise RuntimeError('Exact run/provenance verification failed')
  for aid,a in expected.items():
   if any(actual[aid][key]!=a.get(key) for key in ('title','body','url','published_at','source_event_id')):raise RuntimeError('Exact article verification failed: '+aid)
  canonical=root/'data/canonical'/source/(receipt['run']+'.json')
  if json.loads(canonical.read_text(encoding='utf-8'))!=doc or not health():raise RuntimeError('Canonical/health verification failed')
  result=receipt|{'status':'published','article_ids':list(expected),'events':[a['source_event_id'] for a in doc['articles']],'canonical':str(canonical),'candidate_count':len(items)}
  atomic(state/(source+'-last-success.json'),result);intent.unlink();return result

def plain(value):
 import html,re
 return ' '.join(html.unescape(re.sub('<[^>]+>',' ',value or '')).split())

def github_rows(text):
 import re
 rows=[]
 for block in re.findall(r'<article\b[^>]*class="[^"]*Box-row[^"]*"[^>]*>(.*?)</article>',text,re.S):
  h=re.search(r'<h2\b[^>]*>(.*?)</h2>',block,re.S)
  link=re.search(r'href="(/[^"?#]+/[^"?#]+)"',h.group(1) if h else '')
  if not link:raise ValueError('Trending repository shape changed')
  repo=link.group(1).strip('/');rank=len(rows)+1
  p=re.search(r'<p\b[^>]*>(.*?)</p>',block,re.S)
  desc=plain(p.group(1)) if p else '来源未提供描述'
  rows.append({'title':f'#{rank} {repo}','body':f'GitHub Trending 每日榜原始位置：{rank}。\n仓库描述（来源原文）：{desc}\n榜单发现，不代表仓库新建或新版本发布；未从编程语言推断类别。','url':'https://github.com/'+repo,'publisher':'GitHub Trending','source_event_id':'repo:'+hashlib.sha256(repo.lower().encode()).hexdigest(),'published_at':None,'source_rank':rank})
 if not rows:raise ValueError('Trending returned no repository rows; not treated as an empty success')
 return rows

def producthunt_rows(text):
 import xml.etree.ElementTree as ET
 ns={'a':'http://www.w3.org/2005/Atom'};root=ET.fromstring(text);rows=[]
 for e in root.findall('a:entry',ns):
  links=e.findall('a:link',ns);url=next((x.get('href') for x in links if x.get('rel','alternate')=='alternate'),None)
  if not url or not url.startswith('https://www.producthunt.com/'):raise ValueError('Invalid Product Hunt link')
  title=e.findtext('a:title','',ns);when=e.findtext('a:published',None,ns)
  if when:dt.datetime.fromisoformat(when)
  summary=plain(e.findtext('a:content','',ns) or e.findtext('a:summary','',ns))
  eid=e.findtext('a:id',url,ns)
  rows.append({'title':title,'body':'Product Hunt 官方 Atom 订阅源；顺序为订阅源顺序，不冒充票数榜。\n来源摘要：'+summary[:2000]+'\n产品能力与优惠为来源声明，未独立验证。','url':url,'publisher':'Product Hunt','source_event_id':'post:'+hashlib.sha256(eid.encode()).hexdigest(),'published_at':when,'published_at_raw':when})
 if not rows:raise ValueError('Product Hunt feed has no entries')
 return rows

def xinquji_row(row,kind,today):
 import re
 text=(row.get('tagline') or row.get('summary') or row.get('description') or '')
 context=row.get('name',row.get('title',''))+' '+text
 recorded=row.get('launchDate') if kind=='product' else row.get('createdAt')
 if recorded:
  try:day=dt.date.fromisoformat(recorded[:10])
  except ValueError:return None
  if day>today or day<today-dt.timedelta(days=30):return None
 # Conservative evidence predicates: AI mechanism + developer artifact + concrete action.
 ai=any(str(t.get('id'))=='11' for t in row.get('topics',[])) or re.search(r'\bAI\b|\bagents?\b|人工智能|智能体|大模型|LLM',context,re.I)
 artifact=re.search(r'代码|开发|编程|测试|文档|工作流|code|developer|coding|test|workflow|SDLC',text,re.I)
 action=re.search(r'生成|自动|调试|部署|协作|集成|运行|管理|构建|开发|generate|automat|debug|deploy|collaborat|integrat|build|run',text,re.I)
 if not ai or not artifact or not action:return None
 url=row.get('productUrl') if kind=='product' else row.get('articleUrl')
 if not url or not url.startswith('https://xinquji.com/'):raise ValueError('Invalid Xinquji public link')
 eid='xinquji:'+kind+':'+str(row['id'])
 label='产品发现（非首发声明）' if kind=='product' else '文章发现'
 reason='H002 暂定低匹配：来源具体描述涉及开发产物及自动化/协作操作；仅为保守规则预选，未验证效率收益，不构成主体订阅。'
 body=f'{text[:1800]}\n类型：{label}。\n来源：新趣集公开介绍，能力/价格/隐私为来源声明，未经独立核验。\n来源记录时间：{recorded or "未提供"}；产品日期为平台上架日期、文章日期为创建时间，均不当作产品首次发布时间。\n入选理由（编辑规则判断）：{reason}'
 if row.get('url'):body+='\n产品原链接：'+row['url']
 return {'title':row.get('name',row.get('title',''))[:500],'body':body,'url':url,'publisher':'新趣集','source_event_id':eid,'published_at':None,'source_recorded_at':recorded,'rule_ids':['H002'],'match_reason':reason,'entity':row.get('url',eid)}

def fetch(url,*,payload=None,headers=None):
 h={'User-Agent':'AINewsDesk/1.0 (personal reading; public sources only)',**(headers or {})}
 for attempt in range(2):
  remaining=DEADLINE-time.monotonic()
  if remaining<=0:raise TimeoutError('Bounded collection deadline reached')
  try:
   req=urllib.request.Request(url,data=json.dumps(payload).encode() if payload is not None else None,headers=h)
   with urllib.request.urlopen(req,timeout=min(12,remaining)) as response:
    raw=response.read(2_000_001)
    if len(raw)>2_000_000:raise ValueError('Source exceeds bounded response limit')
    return raw.decode('utf-8'),dict(response.headers)
  except urllib.error.HTTPError as e:
   if e.code not in (429,500,502,503,504) or attempt:raise
  except (TimeoutError,OSError):
   if attempt:raise
  time.sleep(1)

class MCP:
 allowed={'search_products','search_articles','list_topics','get_product','get_article','get_feed'}
 def __init__(self):self.headers={'Content-Type':'application/json','Accept':'application/json, text/event-stream'};self.ready=False;self.sequence=0
 def rpc(self,method,params):
  self.sequence+=1
  text,headers=fetch('https://xinquji.com/api/mcp',payload={'jsonrpc':'2.0','id':self.sequence,'method':method,'params':params},headers=self.headers)
  session=next((v for k,v in headers.items() if k.lower()=='mcp-session-id'),None)
  if session:self.headers['Mcp-Session-Id']=session
  if text.lstrip().startswith('data:') or text.lstrip().startswith('event:'):
   lines=[line[5:].strip() for line in text.splitlines() if line.startswith('data:')];data=json.loads(lines[-1])
  else:data=json.loads(text)
  if 'error' in data:raise ValueError('MCP protocol error: '+json.dumps(data['error'])[:300])
  return data['result']
 def tool(self,name,args):
  if name not in self.allowed:raise ValueError('Only approved anonymous read tools are allowed')
  if not self.ready:
   self.rpc('initialize',{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'ai-news-desk','version':'1.0'}});self.ready=True
  result=self.rpc('tools/call',{'name':name,'arguments':args})
  if result.get('isError'):raise ValueError('MCP read tool failed')
  return result.get('structuredContent') or json.loads(next(c['text'] for c in result['content'] if c['type']=='text'))

def hn_row(row,rank):
 if not row or row.get('deleted') or row.get('dead') or row.get('type')!='story' or not row.get('title'):return None
 discussion='https://news.ycombinator.com/item?id='+str(row['id'])
 when=dt.datetime.fromtimestamp(row['time'],UTC).isoformat()
 return {'title':f"#{rank} {row['title']}",'body':f'Hacker News topstories 原始位置：{rank}。\n讨论：{discussion}\n来源分数：{row.get("score","未提供")}；评论数：{row.get("descendants","未提供")}。仅为采集时快照。\n'+plain(row.get('text',''))[:2000],'url':row.get('url') or discussion,'publisher':'Hacker News','published_at':when,'published_at_raw':when,'source_event_id':'hn:'+str(row['id']),'source_rank':rank}

def collect(source,folder,seen,profile_dir=None):
 from easel_workbench.collectors import enabled, acquire
 if enabled():
     return acquire('discovery',{'source':source,'folder':str(folder),'seen':seen,'profile_dir':str(profile_dir) if profile_dir is not None else None},source=source)
 today=dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date();meta={'source':source,'at':dt.datetime.now(UTC).isoformat(),'model_calls':0,'errors':[]};rows=[]
 if source=='github-trending':
  text,_=fetch('https://github.com/trending');(folder/'source.html').write_text(text,encoding='utf-8');rows=github_rows(text)[:50]
  meta.update(endpoint='https://github.com/trending',bound='one unfiltered daily Trending page, at most 50 repositories; no language category inference')
 elif source=='product-hunt':
  text,_=fetch('https://www.producthunt.com/feed');(folder/'source.atom').write_text(text,encoding='utf-8');rows=producthunt_rows(text)[:50]
  meta.update(endpoint='https://www.producthunt.com/feed',bound='one official Atom feed, at most 50 entries; not a votes ranking')
 elif source=='hacker-news':
  import concurrent.futures
  text,_=fetch('https://hacker-news.firebaseio.com/v0/topstories.json');ids=json.loads(text)[:60];atomic(folder/'topstories.json',json.loads(text));raw=[]
  def one(pair):
   rank,id_=pair
   try:
    data=json.loads(fetch(f'https://hacker-news.firebaseio.com/v0/item/{id_}.json')[0]);return rank,data,None
   except Exception as e:return rank,None,type(e).__name__+': '+str(e)[:200]
  for start in range(0,len(ids),10):
   with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:batch=list(pool.map(one,enumerate(ids[start:start+10],start+1)))
   for rank,data,error in batch:
    raw.append({'rank':rank,'item':data,'error':error})
    if error:meta['errors'].append({'rank':rank,'error':error});continue
    a=hn_row(data,rank)
    if a:rows.append(a)
   if len([r for r in rows if r['source_event_id'] not in seen])>=10:break
  atomic(folder/'items.json',raw);meta.update(endpoint='https://hacker-news.firebaseio.com/v0/topstories.json',bound='topstories order, at most first 60 IDs, batches of 10')
 elif source=='xinquji':
  from easel_workbench.runtime.feedback_ledger import Ledger
  skill=pathlib.Path(profile_dir) if profile_dir is not None else ROOT/'data/collection/profile'
  snapshot=Ledger(skill).snapshot(source);atomic(folder/'profile-snapshot.json',snapshot)
  if 'H002' not in snapshot['documents']['profile-current.md']:raise ValueError('H002 missing; review deterministic scope before collection')
  client=MCP();topics=client.tool('list_topics',{'query':'人工智能','limit':10});atomic(folder/'topics.json',topics)
  topic=next(t['id'] for t in topics['items'] if t['name']=='人工智能')
  raw=[]
  for kind,name in [('product','search_products'),('article','search_articles')]:
   for page in range(1,3):
    args={'limit':50,'page':page}
    if kind=='product':args.update(topicId=topic,sort='newest',source='all',**{'from':str(today-dt.timedelta(days=30)),'to':str(today)})
    result=client.tool(name,args);atomic(folder/f'{kind}-{page}.json',result)
    for row in result['items']:
     raw.append({'kind':kind,'row':row});a=xinquji_row(row,kind,today)
     if a and a['source_event_id'] not in seen:rows.append(a)
    if page>=result.get('lastPage',1):break
  # Reuse the existing original ranker without a new model call or profile edits.
  from easel_workbench.runtime.collection_adapters.rank_candidates import rank
  annotated=[{'event_id':a['source_event_id'],'entity':a['entity'],'supported':True,'fresh':True,'substantive':True,'match':1,'interesting':0,'major':0,'rule_ids':a['rule_ids'],'match_reason':a['match_reason']} for a in rows]
  ranking=rank(annotated,10);selected={a['event_id'] for a in ranking['selected']};rows=[r for r in rows if r['source_event_id'] in selected]
  meta.update(endpoint='https://xinquji.com/api/mcp',bound='AI category products + public articles, 2 pages x 50 each; last 30 days; conservative H002 evidence predicates only',profile_version=snapshot['version'],raw_candidates=len(raw),ranking=ranking,selection_boundary='Deterministic low-tier H002 development utility only, not full semantic exploration; no user feedback fabricated')
 else:raise ValueError('Unknown source')
 meta['candidate_count']=len(rows);atomic(folder/'candidates.json',rows);atomic(folder/'coverage.json',meta)
 return rows,meta

def discovery_input(source,rows,meta,folder,selected_ids,today):
 value={'schema_version':1,'source':source,'rows':rows,'coverage':meta,'evidence':str(folder),'selected_ids':selected_ids,'date':today}
 value['sha256']=hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 return value

def read_discovery_input(path,source,root):
 value=json.loads(path.read_text(encoding='utf-8'));original={key:item for key,item in value.items() if key!='sha256'}
 expected=hashlib.sha256(json.dumps(original,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
 if value.get('schema_version')!=1 or value.get('source')!=source or value.get('sha256')!=expected:raise ValueError('Frozen discovery input identity mismatch')
 if not isinstance(value.get('rows'),list) or not isinstance(value.get('coverage'),dict) or not isinstance(value.get('selected_ids'),list):raise ValueError('Frozen discovery input shape invalid')
 rows={row['source_event_id']:row for row in value['rows']}
 if len(rows)!=len(value['rows']) or len(set(value['selected_ids']))!=len(value['selected_ids']) or not set(value['selected_ids'])<=set(rows):raise ValueError('Frozen discovery selection mismatch')
 from easel_workbench.paths import discovery_evidence
 folder=discovery_evidence(value['evidence'],root)
 if not folder.is_relative_to((root/'evidence/discovery'/source).resolve()):raise ValueError('Frozen discovery evidence is outside its source')
 return value

def retry_partial_capture(source,snapshot,folder,seen,profile_dir=None,root=None):
 """Only missing HN items are retried; successful raw items remain unchanged."""
 from easel_workbench.paths import discovery_evidence
 original=discovery_evidence(snapshot['evidence'],root or ROOT)
 if source!='hacker-news' or not (original/'topstories.json').is_file() or not (original/'items.json').is_file():
  return collect(source,folder,seen,profile_dir=profile_dir) if profile_dir is not None else collect(source,folder,seen)
 ids=json.loads((original/'topstories.json').read_text(encoding='utf-8'))[:60]
 raw=json.loads((original/'items.json').read_text(encoding='utf-8'));by_rank={row['rank']:row for row in raw}
 failed=sorted({error['rank'] for error in snapshot['coverage']['errors'] if isinstance(error.get('rank'),int)})
 if not failed:return collect(source,folder,seen,profile_dir=profile_dir) if profile_dir is not None else collect(source,folder,seen)
 import concurrent.futures
 def one(rank):
  if not 1<=rank<=len(ids) or type(ids[rank-1]) is not int or ids[rank-1]<=0:raise ValueError('Frozen Hacker News identity mismatch')
  try:
   data=json.loads(fetch('https://hacker-news.firebaseio.com/v0/item/'+str(ids[rank-1])+'.json')[0])
   if data and data.get('id')!=ids[rank-1]:raise ValueError('Hacker News response identity mismatch')
   return {'rank':rank,'item':data,'error':None}
  except (OSError,ValueError,TimeoutError) as error:return {'rank':rank,'item':None,'error':type(error).__name__}
 for offset in range(0,len(failed),10):
  with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
   for row in pool.map(one,failed[offset:offset+10]):by_rank[row['rank']]=row
 raw=[by_rank[rank] for rank in sorted(by_rank)];rows=[];errors=[]
 for item in raw:
  if item['error']:errors.append({'rank':item['rank'],'error':item['error']});continue
  article=hn_row(item['item'],item['rank'])
  if article:rows.append(article)
 meta=snapshot['coverage']|{'at':dt.datetime.now(UTC).isoformat(),'errors':errors,'candidate_count':len(rows),'retried_ranks':failed,'repaired_from':str(original)}
 atomic(folder/'topstories.json',ids);atomic(folder/'items.json',raw);atomic(folder/'candidates.json',rows);atomic(folder/'coverage.json',meta)
 return rows,meta

def run_source(source,*,force=False,root=None,profile_dir=None,report=None,raise_partial=True,task_dir=None,resume=False):
 from easel_workbench.runtime import desk as desk
 root=pathlib.Path(root or ROOT).resolve();store=desk.Store(root/'data/desk.sqlite');state=root/'data/discovery';state.mkdir(parents=True,exist_ok=True)
 task=pathlib.Path(task_dir) if task_dir is not None else None
 if task is not None:task.mkdir(parents=True,exist_ok=True)
 frozen=task/'discovery-input.json' if task is not None else None
 today=dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
 with locked(state/(source+'-pipeline.lock'),timeout=2):
  snapshot=read_discovery_input(frozen,source,root) if frozen is not None and frozen.exists() else None
  restored=snapshot is not None;warnings=[]
  recovered=publish(source,[],root=root,store=store) if (state/(source+'-intent.json')).exists() else None
  if recovered and report:report('persisting',{'fetched':len(recovered.get('article_ids',[])),'selected':len(recovered.get('article_ids',[])),'inserted':recovered.get('inserted',0)})
  if recovered and not force and snapshot is None:return recovered
  # Old daily markers describe another capture. An explicit source retry must
  # first settle its own frozen selection, without fetching it for a second time.
  if resume and snapshot is None:warnings.append('上次未保存冻结输入，本次已重新读取来源；继续使用原有去重和每日额度。')
  daily=state/(source+'-daily.json')
  if snapshot is None and not force and not resume and source!='xinquji' and daily.exists() and json.loads(daily.read_text(encoding='utf-8')).get('date')==today:return {'status':'already_collected_today','inserted':0,'article_ids':[]}
  with store.connect() as c:
   history=list(c.execute('select source_event_id,run_at from articles where source_job=?',(source,)))
  seen={r['source_event_id'] for r in history}
  used=sum(dt.datetime.fromisoformat(r['run_at']).astimezone(dt.timezone(dt.timedelta(hours=8))).date().isoformat()==today for r in history) if source!='xinquji' else 0
  remaining=max(0,10-used)
  if snapshot is not None and resume and snapshot['coverage'].get('errors'):
   folder=root/'evidence/discovery'/source/dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f');folder.mkdir(parents=True)
   if report:report('fetching',{'fetched':snapshot['coverage'].get('raw_candidates',len(snapshot['rows']))})
   rows,meta=retry_partial_capture(source,snapshot,folder,seen,profile_dir,root=root)
   previous_pending=[eid for eid in snapshot['selected_ids'] if eid not in seen]
   unique={row['source_event_id']:row for row in rows if row['source_event_id'] not in seen}
   selected_ids=previous_pending+[eid for eid in unique if eid not in previous_pending][:max(0,remaining-len(previous_pending))]
   if not set(previous_pending)<=set(unique):raise ValueError('Partial retry lost an undelivered frozen selection')
   if frozen is not None:
    retained=task/('discovery-input-before-retry-'+snapshot['sha256']+'.json')
    if not retained.exists():retained.write_bytes(frozen.read_bytes())
   snapshot=discovery_input(source,rows,meta,folder,selected_ids,today)
   if frozen is not None:atomic(frozen,snapshot)
   warnings.append('已补查上次未取得的来源资料，原始快照与已交付条目继续保留。')
  if snapshot is None and used>=10 and not force and not resume:return {'status':'daily_quota_reached','inserted':0,'article_ids':[]}
  if snapshot is None:
   folder=root/'evidence/discovery'/source/dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f');folder.mkdir(parents=True)
   if report:report('fetching',{})
   rows,meta=collect(source,folder,seen,profile_dir=profile_dir) if profile_dir is not None else collect(source,folder,seen)
   unique={}
   for row in rows:
    if row['source_event_id'] not in seen:unique.setdefault(row['source_event_id'],row)
   selected_ids=list(unique)[:remaining]
   snapshot=discovery_input(source,rows,meta,folder,selected_ids,today)
   # This is deliberately before importing/calling the publisher. Even a local
   # missing dependency must leave a retryable, correctly identified capture.
   if frozen is not None:atomic(frozen,snapshot)
  else:
   from easel_workbench.paths import discovery_evidence
   rows=snapshot['rows'];meta=snapshot['coverage'];folder=discovery_evidence(snapshot['evidence'],root)
   selected_ids=snapshot['selected_ids']
  available={row['source_event_id']:row for row in rows}
  pending_ids=[eid for eid in selected_ids if eid not in seen]
  deliver=[available[eid] for eid in pending_ids[:remaining]]
  fetched=meta.get('raw_candidates',len(rows));duplicates=sum(row['source_event_id'] in seen for row in rows)
  if report:report('persisting',{'fetched':fetched,'selected':len(selected_ids),'duplicates':duplicates})
  result=publish(source,deliver,root=root,store=store,metadata=meta,limit=remaining)
  with store.connect() as c:delivered={row[0] for row in c.execute('select source_event_id from articles where source_job=?',(source,))}
  pending_ids=[eid for eid in selected_ids if eid not in delivered]
  result.update(fetched_count=fetched,duplicate_count=duplicates,selected_count=len(selected_ids),
                selected_event_ids=selected_ids,delivered_event_ids=[eid for eid in selected_ids if eid in delivered],pending_event_ids=pending_ids,pending_delivery_count=len(pending_ids),
                input_sha256=snapshot['sha256'],resumed_input=restored,warnings=warnings)
  if recovered:result['inserted']=result.get('inserted',0)+recovered.get('inserted',0)
  result.update(source=source,evidence=str(folder),coverage=meta,shortfall=max(0,10-len(result.get('article_ids',[]))))
  if pending_ids:result.update(status='blocked' if not result.get('inserted') else 'partial',error='本批仍有未交付条目，当前每日额度不足。',message='冻结批次已保留；日额度恢复后可继续。')
  elif meta['errors']:result['status']='partial'
  elif used>=10:result.update(status='daily_quota_reached',message='已重新检查来源；今日10条额度已用完，未继续新增')
  # Keep the original source capture intact; a retry gets its own result file.
  result_path=task/'discovery-result.json' if task is not None else folder/'result.json'
  atomic(result_path,result);atomic(state/(source+'-status.json'),result)
  if meta['errors'] and raise_partial:raise RuntimeError('Partial collection; frozen input preserved; a fresh round may fetch the missing coverage')
  if not pending_ids and not meta['errors'] and source!='xinquji':atomic(daily,{'date':today,'result':result})
  return result

