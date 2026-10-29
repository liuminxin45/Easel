"""Bounded anonymous Watcha reads and a durable event queue. No model or delivery."""
import contextlib
import datetime as dt
import hashlib
import json
import pathlib
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request

UTC=dt.timezone.utc
BASE='https://watcha.cn/api/v2'


def iso(now=None):return (now or dt.datetime.now(UTC)).astimezone(UTC).isoformat()


def parsed(value):
    try:
        v=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
        return v.astimezone(UTC) if v.tzinfo else None
    except (ValueError,AttributeError,TypeError):return None


def plain(value):
    if isinstance(value,str):
        if value.lstrip().startswith(('{','[')):
            try:return plain(json.loads(value))
            except ValueError:pass
        return re.sub(r'<[^>]+>',' ',value).strip()
    if isinstance(value,list):return '\n'.join(filter(None,(plain(v) for v in value)))
    if isinstance(value,dict):return value.get('text','') or plain(value.get('content',[]))
    return ''


def identifier(value):
    if isinstance(value,bool) or not re.fullmatch(r'[1-9][0-9]{0,17}',str(value)):raise ValueError('Invalid Watcha ID')
    return str(value)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


class Client:
    def __init__(self,limit=30):
        self.remaining=limit;self.requests=0
        self.opener=urllib.request.build_opener(NoRedirect())

    def get(self,path,query=None):
        if not re.fullmatch(r'/(?:products(?:/[1-9][0-9]*)?(?:/launches)?|hot/products)',path):raise ValueError('Endpoint outside Watcha allowlist')
        url=BASE+path+('?' + urllib.parse.urlencode(query) if query else '')
        for attempt in range(2):
            if self.remaining<=0:raise RuntimeError('Watcha request budget exhausted')
            self.remaining-=1;self.requests+=1
            try:
                req=urllib.request.Request(url,headers={'User-Agent':'AINewsDesk/1.0 (+Watcha public product reader)','Accept':'application/json'})
                with self.opener.open(req,timeout=15) as response:
                    raw=response.read(2_000_001)
                    if len(raw)>2_000_000:raise ValueError('Watcha response exceeds limit')
                    data=json.loads(raw)
                if data.get('statusCode')!=200 or not isinstance(data.get('data'),dict):raise ValueError('Watcha response schema changed')
                return data['data']
            except (OSError,ValueError):
                if attempt:raise
                time.sleep(.5)


class Queue:
    def __init__(self,path):
        self.path=pathlib.Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.executescript('''
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,product_id TEXT NOT NULL,payload TEXT NOT NULL,hash TEXT NOT NULL,first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'pending',receipt TEXT,review_hash TEXT);
CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY,stats TEXT NOT NULL,last_seen TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS backlog(id TEXT PRIMARY KEY,kind TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,cursor INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
''')
            if 'cursor' not in {r[1] for r in c.execute('pragma table_info(backlog)')}:c.execute('alter table backlog add column cursor INTEGER NOT NULL DEFAULT 0')

    @contextlib.contextmanager
    def connect(self):
        c=sqlite3.connect(self.path,timeout=20);c.row_factory=sqlite3.Row
        try:
            c.execute('pragma journal_mode=WAL')
            with c:yield c
        finally:c.close()

    def event(self,payload,now):
        raw=json.dumps(payload,ensure_ascii=False,sort_keys=True)
        hashed=hashlib.sha256(raw.encode()).hexdigest()
        with self.connect() as c:
            c.execute('''insert into events(id,product_id,payload,hash,first_seen,last_seen) values(?,?,?,?,?,?)
ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,hash=excluded.hash,last_seen=excluded.last_seen''',
                      (payload['event_id'],payload['product_id'],raw,hashed,iso(now),iso(now)))

    def pending(self,now=None):
        cutoff=iso((now or dt.datetime.now(UTC))-dt.timedelta(hours=72))
        with self.connect() as c:
            c.execute("update events set status='expired' where status='pending' and first_seen<?",(cutoff,))
            rows=c.execute("select id,payload,hash,review_hash from events where status='pending' order by first_seen,id").fetchall()
        return [dict(r) for r in rows]

    def ack(self,ids,receipt):
        if not receipt or not receipt.startswith('site-run:'):raise ValueError('Verified site receipt required')
        with self.connect() as c:
            for eid in ids:
                if not c.execute('select 1 from events where id=?',(eid,)).fetchone():raise ValueError('Unknown event acknowledgment')
                c.execute("update events set status='delivered',receipt=? where id=?",(receipt,eid))


def pages(client,path,count,errors,start=0):
    result=[];seen=set();limited=False
    for page in range(count):
        try:
            data=client.get(path,{'skip':start+page*20,'limit':20});rows=data.get('items')
            if not isinstance(rows,list) or len(rows)>20:raise ValueError('Invalid Watcha page items')
            ids=[identifier(r.get('id')) for r in rows]
            if rows and all(i in seen for i in ids):raise ValueError('Watcha pagination did not advance')
            seen.update(ids);result.extend(rows)
            if len(rows)<20:break
            limited=page==count-1
        except (ValueError,OSError,RuntimeError) as e:
            errors.append({'source':path,'page':page,'error':type(e).__name__+': '+str(e)[:160]});break
    return result,limited


def make_event(product,now,launch=None):
    pid=identifier(product.get('id'));slug=product.get('slug')
    if not isinstance(slug,str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,180}',slug):slug=pid
    name=product.get('name')
    if not isinstance(name,str) or not name.strip():raise ValueError('Product name missing')
    when=parsed((launch or product).get('create_at'))
    if when and when>now+dt.timedelta(minutes=5):raise ValueError('Source time is in the future')
    if when and when<now-dt.timedelta(hours=72):return None
    eid='watcha:launch:'+identifier(launch.get('id')) if launch else 'watcha:product:'+pid+':discovery'
    event={'event_id':eid,'product_id':pid,'name':name[:200],'slug':slug,
           'url':'https://watcha.cn/products/'+slug,'kind':'update' if launch else 'discovery',
           'title':(str(launch.get('title',''))[:150] if launch else name[:200]),
           'description':plain((launch or product).get('description',''))[:2200],
           'slogan':str(product.get('slogan',''))[:300],
           'source_time_raw':(launch or product).get('create_at'),
           'source_time':iso(when) if when else None,
           'time_basis':'watcha_log_created' if launch and when else 'first_seen',
           'source_role':'Watcha community product entry; not independently verified',
           'categories':[str(c.get('name',''))[:60] for c in product.get('categories',[]) if isinstance(c,dict)],
           'website_url':product.get('website_url',''),
           'tags':product.get('tag',{})}
    return event


def collect(queue,client,now=None,retry_coverage=None):
    from easel_workbench.collectors import enabled, acquire
    if enabled() and type(client) is Client:
        return acquire('watcha',{'queue':str(queue.path),'limit':client.remaining,'now':now,'retry_coverage':retry_coverage})
    now=now or dt.datetime.now(UTC);errors=[];limits={};lists={}
    previous_errors=(retry_coverage or {}).get('errors',[])
    retry_sources={row.get('source') for row in previous_errors}
    for label,path,n in [('new','/products',3),('updates','/products/launches',2),('hot','/hot/products',1)]:
        if retry_coverage is not None and path not in retry_sources and label not in retry_sources:
            lists[label]=[];limits[label]=False;continue
        first=min((row.get('page',0) for row in previous_errors if row.get('source')==path),default=0)
        lists[label],limits[label]=pages(client,path,max(1,n-first),errors,start=first*20)
    if retry_coverage is None and not any(lists.values()) and errors:raise RuntimeError('Watcha all sources failed: '+json.dumps(errors,ensure_ascii=False))
    products={};new_ids=set();update_ids=set()
    for label,rows in lists.items():
        for row in rows:
            try:pid=identifier(row.get('id'))
            except ValueError as e:errors.append({'source':label,'error':str(e)});continue
            products[pid]=products.get(pid,{})|row
            cutoff=now-dt.timedelta(hours=72)
            created=parsed(row.get('create_at'))
            if label=='new' and (not created or created>=cutoff):new_ids.add(pid)
            # A recent product appearing only in hot is a discovery backstop;
            # old hot products contribute statistics without becoming fake launches.
            if label=='hot' and created and created>=cutoff:new_ids.add(pid)
            launched=parsed(row.get('last_launch',{}).get('create_at'))
            if label=='updates' and (not launched or launched>=cutoff):update_ids.add(pid)
            with queue.connect() as c:
                c.execute('insert or replace into products values(?,?,?)',(pid,json.dumps(row.get('stats',{})),iso(now)))
    with queue.connect() as c:
        for pid,row in products.items():
            created=parsed(row.get('create_at'));launched=parsed(row.get('last_launch',{}).get('create_at'))
            if created and created<now-dt.timedelta(hours=72):
                c.execute("delete from backlog where id=? and kind='discovery'",(pid,))
            if launched and launched<now-dt.timedelta(hours=72):
                c.execute("delete from backlog where id=? and kind='update'",(pid,))
        for pid in new_ids|update_ids:
            c.execute("insert into backlog(id,kind) values(?,?) on conflict(id) do update set kind=case when excluded.kind='update' then 'update' else backlog.kind end",(pid,'update' if pid in update_ids else 'discovery'))
        c.execute("delete from backlog where rowid not in (select rowid from backlog order by rowid desc limit 500)")
        jobs=[dict(r) for r in c.execute("select * from backlog order by attempts,case kind when 'update' then 0 else 1 end,rowid")]
        if retry_coverage is not None:
            failed_ids={value.split(':',1)[1] for value in retry_sources if isinstance(value,str) and value.startswith('detail:')}
            failed_ids.update(value.split('/')[2] for value in retry_sources if isinstance(value,str) and re.fullmatch(r'/products/[1-9][0-9]*/launches',value))
            jobs=[row for row in jobs if row['id'] in failed_ids|new_ids|update_ids]
        jobs=jobs[:20]
    enriched=0
    for job in jobs:
        pid=job['id']
        if getattr(client,'remaining',30)<2:break
        try:
            product=client.get('/products/'+pid)
            if identifier(product.get('id'))!=pid:raise ValueError('Product detail identity mismatch')
            if pid in new_ids or job['kind']=='discovery':
                event=make_event(product,now)
                if event:queue.event(event,now)
            if pid in update_ids or job['kind']=='update':
                logs,bounded=pages(client,'/products/'+pid+'/launches',2,errors,job['cursor'])
                # pages returns launch rows, which have stable ids too.
                for log in logs:
                    if str(log.get('product_id'))!=pid:raise ValueError('Launch product identity mismatch')
                    event=make_event(product,now,log)
                    if event:queue.event(event,now)
                if bounded:
                    limits['log:'+pid]=True
                    with queue.connect() as c:c.execute('update backlog set cursor=cursor+20,attempts=attempts+1 where id=?',(pid,))
                if any(e['source']=='/products/'+pid+'/launches' for e in errors):raise RuntimeError('Launch history incomplete; retained for retry')
            if not (pid in update_ids or job['kind']=='update') or not bounded:
                with queue.connect() as c:c.execute('delete from backlog where id=?',(pid,))
            enriched+=1
        except (ValueError,OSError,RuntimeError) as e:
            errors.append({'source':'detail:'+pid,'error':type(e).__name__+': '+str(e)[:160]})
            with queue.connect() as c:c.execute('update backlog set attempts=attempts+1 where id=?',(pid,))
    with queue.connect() as c:
        backlog=c.execute('select count(*) from backlog').fetchone()[0]
        c.execute('insert or replace into meta values(?,?)',('last_collection',iso(now)))
    pending=queue.pending(now)
    return {'collected_at':iso(now),'coverage':'partial' if errors else 'ok','errors':errors,'request_count':getattr(client,'requests',0),
            'retried_sources':sorted(str(value) for value in retry_sources) if retry_coverage is not None else [],
            'input_positions':{k:len(v) for k,v in lists.items()},'page_caps':limits,'details_completed':enriched,
            'backlog':backlog,'pending_total':len(pending),'remaining':max(0,len(pending)-30),
            'candidates':[json.loads(r['payload'])|{'content_hash':r['hash'],'review_hash':r['review_hash']} for r in pending[:30]]}
