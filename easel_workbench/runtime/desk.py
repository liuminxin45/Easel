"""Project data store and canonical structured news persistence."""

if __name__ == "__main__" and not __package__:
    import sys as _bootstrap_sys
    from pathlib import Path as _BootstrapPath
    _bootstrap_sys.path.insert(0,str(_BootstrapPath(__file__).resolve().parents[2]))

import argparse, datetime as dt, hashlib, http.server, json, os, pathlib, re, secrets, sqlite3, threading, time, urllib.parse, uuid
from easel_workbench.runtime.project_paths import ROOT
TZ=dt.timezone(dt.timedelta(hours=8))
THREAD='01a11bd2-b03c-7441-aba5-2feb69d193ea'
PROJECT=pathlib.Path('D:/Projects/neo-content')
SOURCES=json.loads((ROOT/'sources.json').read_text(encoding='utf-8'))
if not SOURCES or any(not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',k) or not isinstance(v.get('name'),str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',v.get('feed','')) for k,v in SOURCES.items()): raise ValueError('invalid source registry')
def stamp(): return dt.datetime.now(TZ).isoformat()
def digest(v): return hashlib.sha256(v.encode('utf-8')).hexdigest()

def article_identity(job,article):
    event=article.get('source_event_id')
    if event is not None:
        if not isinstance(event,str) or not re.fullmatch(r'[A-Za-z0-9:_-]{1,200}',event):raise ValueError('invalid source event identity')
        return digest(job+'\0event\0'+event)
    return digest(job+'\0'+article['url']+'\0'+article['title'])
def url_ok(u):
    p=urllib.parse.urlsplit(u)
    return p.scheme in ('http','https') and bool(p.hostname) and not p.username and not p.password

class Connection(sqlite3.Connection):
    def __exit__(self,*args):
        try: return super().__exit__(*args)
        finally: self.close()

class Store:
    def __init__(self,path=ROOT/'data/desk.sqlite'):
        self.path=pathlib.Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.executescript('''
CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,source_job TEXT NOT NULL,run_id TEXT NOT NULL,run_at TEXT NOT NULL,hash TEXT NOT NULL,final_text TEXT NOT NULL,UNIQUE(source_job,run_id,hash));
CREATE TABLE IF NOT EXISTS articles(id TEXT PRIMARY KEY,source_job TEXT NOT NULL,title TEXT NOT NULL,body TEXT NOT NULL,url TEXT NOT NULL,publisher TEXT,published_at TEXT,run_at TEXT NOT NULL,run TEXT NOT NULL,unread INTEGER NOT NULL DEFAULT 1,selected INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY,article_id TEXT NOT NULL,kind TEXT NOT NULL,text TEXT NOT NULL,status TEXT NOT NULL,created_at TEXT NOT NULL,started_at TEXT,finished_at TEXT,reply TEXT,error TEXT,thread TEXT NOT NULL,turn_id TEXT,rollout_offset INTEGER,output_path TEXT);
CREATE TABLE IF NOT EXISTS artifacts(id TEXT PRIMARY KEY,task_id TEXT NOT NULL,name TEXT NOT NULL,path TEXT NOT NULL,mime TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS provenance(article_id TEXT NOT NULL,run TEXT NOT NULL,PRIMARY KEY(article_id,run));
''')
            if 'published_at_raw' not in {r[1] for r in c.execute('pragma table_info(articles)')}: c.execute('alter table articles add column published_at_raw TEXT')
            if 'source_event_id' not in {r[1] for r in c.execute('pragma table_info(articles)')}: c.execute('alter table articles add column source_event_id TEXT')
            for field,kind in (('source_order','INTEGER'),('hot','TEXT'),('fetched_at','TEXT'),('source_protocol_id','TEXT')):
                if field not in {r[1] for r in c.execute('pragma table_info(articles)')}:c.execute('alter table articles add column '+field+' '+kind)
            from easel_workbench.runtime.source_registry import migrate as source_migrate
            source_migrate(c)
            c.execute('create unique index if not exists articles_source_event on articles(source_job,source_event_id) where source_event_id is not null')
            from easel_workbench.runtime import notifications as notifications
            notifications.migrate(c)
            from easel_workbench.runtime import news_feedback as news_feedback
            news_feedback.migrate(c)
            from easel_workbench.runtime import creative_review as creative_review
            creative_review.migrate(c)
            from easel_workbench.runtime.weekly_periodical import migrate as periodical_migrate
            periodical_migrate(c)
    def connect(self):
        c=sqlite3.connect(self.path,timeout=20,factory=Connection); c.row_factory=sqlite3.Row; c.execute('pragma journal_mode=WAL'); return c
    def ingest(self,d):
        required={'schema_version','source_job','feed_id','run_id','run_at','final_text','articles'}
        if not isinstance(d,dict) or not required<=d.keys() or d['schema_version']!=1: raise ValueError('invalid schema')
        job=d['source_job']
        registry=self.sources(include_deleted=True);meta=registry.get(job)
        if not meta or d['feed_id']!=meta['feed']: raise ValueError('source/feed mismatch')
        when=dt.datetime.fromisoformat(d['run_at'])
        if when.tzinfo is None: raise ValueError('run_at requires timezone')
        if not isinstance(d['run_id'],str) or not 1<=len(d['run_id'])<=250: raise ValueError('invalid run id')
        if not isinstance(d['final_text'],str) or not 1<=len(d['final_text'])<=200000: raise ValueError('invalid final text')
        if not isinstance(d['articles'],list) or not 1<=len(d['articles'])<=100: raise ValueError('articles must contain 1..100')
        for a in d['articles']:
            if not isinstance(a,dict) or not isinstance(a.get('title'),str) or not 1<=len(a['title'])<=(500 if meta['builtin'] else 1000) or not isinstance(a.get('body'),str) or len(a['body'])>100000 or not isinstance(a.get('url'),str) or not (url_ok(a['url']) or not meta['builtin'] and a['url']==''): raise ValueError('invalid article')
            if a.get('published_at'): dt.datetime.fromisoformat(a['published_at'])
            article_identity(job,a)
        hash_=digest(d['final_text']); rid=digest(job+'\0'+d['run_id']+'\0'+hash_); count=0
        with self.connect() as c:
            c.execute('insert or ignore into runs values(?,?,?,?,?,?)',(rid,job,d['run_id'],when.astimezone(TZ).isoformat(),hash_,d['final_text']))
            for a in d['articles']:
                aid=article_identity(job,a)
                count+=c.execute('insert or ignore into articles(id,source_job,title,body,url,publisher,published_at,run_at,run,source_event_id) values(?,?,?,?,?,?,?,?,?,?)',(aid,job,a['title'],a['body'],a['url'],a.get('publisher',''),a.get('published_at'),d['run_at'],rid,a.get('source_event_id'))).rowcount
                c.execute('update articles set publisher=?,published_at_raw=coalesce(published_at_raw,?) where id=?',(a.get('publisher',''),a.get('published_at_raw'),aid))
                c.execute('update articles set source_order=coalesce(source_order,?),hot=coalesce(hot,?),fetched_at=coalesce(fetched_at,?) where id=?',(a.get('source_order'),a.get('hot'),a.get('fetched_at'),aid))
                c.execute('update articles set source_protocol_id=coalesce(source_protocol_id,?) where id=?',(a.get('source_protocol_id'),aid))
                c.execute('insert or ignore into provenance values(?,?)',(aid,rid))
            from easel_workbench.runtime import notifications as notifications
            notifications.news(c,rid,job,count)
        return {'inserted':count,'run':rid,'source':meta['name'],'url':'https://leopc.tail2ce65.ts.net:8443/','status':'已推送'}
    def sources(self,include_deleted=False):
        from easel_workbench.runtime.source_registry import SourceRegistry
        return SourceRegistry(self,self.path.parent.parent).entries(include_deleted=include_deleted)
    def articles(self,q='',source='',state='',page=1):
        terms=[]; vals=[]
        if q: terms.append('(title like ? or body like ?)'); vals += ['%'+q+'%']*2
        if source: terms.append('source_job=?'); vals.append(source)
        if state in ('unread','selected'): terms.append(state+'=1')
        where=' where '+' and '.join(terms) if terms else ''
        with self.connect() as c: return [dict(x) for x in c.execute('select * from articles'+where+' order by run_at desc,id limit 20 offset ?',vals+[(max(1,page)-1)*20])]
    def selected_articles(self,q='',source=''):
        terms=['a.selected=1']; vals=[]
        if q: terms.append('(a.title like ? or a.body like ?)'); vals+=['%'+q+'%']*2
        if source: terms.append('a.source_job=?'); vals.append(source)
        # The first production request defines the order; later feedback must not
        # move an older selection above newly requested work. Keep legacy rows too.
        with self.connect() as c:
            return [dict(r) for r in c.execute('''
WITH production AS (SELECT article_id,MIN(rowid) AS task_rowid FROM tasks WHERE kind='select' GROUP BY article_id),
latest_production AS (SELECT article_id,MAX(rowid) AS task_rowid FROM tasks WHERE kind IN ('select','change','followup') GROUP BY article_id)
SELECT a.*,t.created_at AS selected_at,lt.id AS production_task_id,lt.status AS production_status FROM articles a
LEFT JOIN production p ON p.article_id=a.id LEFT JOIN tasks t ON t.rowid=p.task_rowid
LEFT JOIN latest_production lp ON lp.article_id=a.id LEFT JOIN tasks lt ON lt.rowid=lp.task_rowid
WHERE '''+' AND '.join(terms)+'''
ORDER BY julianday(COALESCE(t.created_at,a.run_at)) DESC,t.rowid DESC,a.id''',vals)]
    def article_day(self,q='',source='',state='',day=''):
        if day:
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',day): raise ValueError('invalid day; expected YYYY-MM-DD')
            dt.date.fromisoformat(day)
        terms=[]; vals=[]
        if q: terms.append('(title like ? or body like ?)'); vals+=['%'+q+'%']*2
        if source: terms.append('source_job=?'); vals.append(source)
        if state in ('unread','selected'): terms.append(state+'=1')
        # SQLite first interprets the stored timezone, then shifts UTC to Beijing.
        # Use the collection time, never a missing or ambiguous publication time.
        date_sql="date(run_at,'+8 hours')"
        where=' where '+' and '.join(terms) if terms else ''
        with self.connect() as c:
            days=[r[0] for r in c.execute('select distinct '+date_sql+' from articles'+where+' order by 1 desc',vals) if r[0]]
            chosen=(day or days[0]) if days else None
            day_where=' where '+' and '.join(terms+[date_sql+'=?'])
            items=[dict(r) for r in c.execute('select * from articles'+day_where+' order by julianday(run_at) desc,id',vals+[chosen])]
        if source and self.sources(include_deleted=True).get(source,{}).get('order')=='rank-prefix':
            # Rank is explicitly supplied by the source, never inferred from language.
            # Other sources retain the existing collection-time/hash ordering.
            def rank_key(row):
                match=re.match(r'^#(\d+)\s',row['title'])
                return (int(match[1]) if match else 10**9,row['id'])
            items.sort(key=rank_key)
        elif source and not self.sources(include_deleted=True).get(source,{}).get('builtin',True):
            items.sort(key=lambda row:(-(dt.datetime.fromisoformat(row['run_at']).timestamp()),row.get('source_order') or 0,row['id']))
        return {'items':items,'day':chosen,'days':days,'total':len(items),
                'previous_day':next((d for d in days if chosen and d<chosen),None),
                'next_day':next((d for d in reversed(days) if chosen and d>chosen),None)}
    def detail(self,aid):
        with self.connect() as c:
            a=c.execute('select * from articles where id=?',(aid,)).fetchone()
            if not a: raise ValueError('article not found')
            d=dict(a); d['tasks']=[dict(x) for x in c.execute('select id,kind,text,status,created_at,started_at,finished_at,reply,error,thread,turn_id,candidate_task_id from tasks where article_id=? order by rowid',(aid,))]
            from easel_workbench.runtime import creative_review as creative_review
            d['candidate_reviews']=creative_review.projections(d['tasks'])
            d['creative_review']=next(reversed(d['candidate_reviews'].values()),None)
            from easel_workbench.runtime import news_feedback as news_feedback
            d['news_feedback']=news_feedback.records(c,aid)
            from easel_workbench.runtime.weekly_periodical import detail as periodical_detail
            d['periodical']=periodical_detail(c,aid)
            from easel_workbench.runtime.publish_content import from_artifacts
            for t in d['tasks']:
                rows=[dict(x) for x in c.execute('select * from artifacts where task_id=? order by rowid',(t['id'],))]
                t['artifacts']=[{k:r[k] for k in ('id','name','mime')} for r in rows]
                t['publish']=from_artifacts(rows, ROOT/'data/artifacts')
            d['provenance']=[dict(x) for x in c.execute('select r.source_job,r.run_id,r.run_at,r.hash,r.final_text from runs r join provenance p on p.run=r.id where p.article_id=?',(aid,))]
            return d
    def action(self,aid,kind,text='',candidate_task_id=None):
        if kind=='read':
            with self.connect() as c:c.execute('UPDATE articles SET unread=0 WHERE id=?',(aid,))
            return {'ok':True}
        if kind=='topic_feedback':
            from easel_workbench.runtime import news_feedback as news_feedback
            with self.connect() as c:fid=news_feedback.enqueue(c,aid,text,request_id='topic:'+aid+':'+digest(text))
            return {'ok':True,'feedback_id':fid,'status':'pending'}
        raise ValueError('制作与评审请使用工具箱作品接口')


def save_digest(document,store=None,root=None):
    """Persist a project-owned structured digest and its exact canonical JSON."""
    root=pathlib.Path(root) if root is not None else ROOT
    store=store or Store(root/'data/desk.sqlite')
    result=store.ingest(document)
    dest=root/'data/canonical'/document['source_job']/(result['run']+'.json')
    dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_suffix('.tmp-'+uuid.uuid4().hex)
    with tmp.open('w',encoding='utf-8',newline='\n') as f:
        json.dump(document,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(tmp,dest)
    return result

def main():
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest='cmd',required=True)
    sub.add_parser('serve')
    sub.add_parser('worker')
    sub.add_parser('status')
    a=p.parse_args(); s=Store()
    if a.cmd=='serve': serve(s)
    elif a.cmd=='worker':
        from easel_workbench.runtime.poster_executor import run
        run()
    elif a.cmd=='status':
        with s.connect() as c: print(json.dumps({'articles':c.execute('select count(*) from articles').fetchone()[0],'runs':c.execute('select count(*) from runs').fetchone()[0],'sources':[dict(x) for x in c.execute('select source_job,count(*) as count from articles group by source_job')],'tasks':[dict(x) for x in c.execute('select status,count(*) as count from tasks group by status')]},ensure_ascii=False))

# HTTP implementation below, deliberately no general filesystem or command endpoints.
def serve(store):
    from easel_workbench.runtime.server import run
    run(store)
if __name__=='__main__': main()
