"""Rebuildable metadata index. Request reads never enumerate original assets."""
from __future__ import annotations
import base64,contextlib,hashlib,json,sqlite3,threading,time,uuid
from pathlib import Path
from fastapi import HTTPException
from easel_workbench.runtime.feedback_ledger import locked


def _connect(path):
    c=sqlite3.connect(path,timeout=2);c.row_factory=sqlite3.Row
    c.execute('PRAGMA journal_mode=WAL');return c


def _read(path):
    c=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=1);c.row_factory=sqlite3.Row;return c


def _refresh_counts(c):
    values=dict(c.execute("SELECT key,value FROM metadata WHERE key IN ('refresh_requested','refresh_completed')"))
    return int(values.get('refresh_requested',0)),int(values.get('refresh_completed',0))


def request_refresh(root):
    """A durable metadata signal; original file enumeration stays in the worker."""
    path=Path(root)/'data/content-library.sqlite'
    if not path.is_file():return False # A newly created index starts with a full build.
    if path.is_symlink():raise ValueError('linked library index is not writable')
    with contextlib.closing(_connect(path)) as c,c:
        c.execute('BEGIN IMMEDIATE');requested,_=_refresh_counts(c)
        c.execute("INSERT OR REPLACE INTO metadata VALUES('refresh_requested',?)",(str(requested+1),))
    return True


def health(root):
    path=Path(root)/'data/content-library.sqlite'
    if not path.exists() or path.is_symlink():return {'status':'unavailable','building':False,'counts':{}}
    try:
        with contextlib.closing(sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=.1)) as c:
            row=c.execute("SELECT value FROM metadata WHERE key='state'").fetchone()
            value=json.loads(row[0]) if row else {}
        if value.get('building') and time.time()-value.get('build_started_at',0)>600:value['status']='stale'
        elif value.get('refreshed_at') and time.time()-value['refreshed_at']>600 and not value.get('building'):value['status']='stale'
        return value or {'status':'unavailable','building':False,'counts':{}}
    except (OSError,ValueError,sqlite3.Error):return {'status':'unavailable','building':False,'counts':{}}


class LibraryIndex:
    def __init__(self,root,builder,signature=lambda:None):
        self.root=Path(root);self.path=self.root/'data/content-library.sqlite'
        if self.path.is_symlink():raise ValueError('linked library index is not writable')
        self.builder=builder;self.signature=signature;self.stop=threading.Event();self.wake=threading.Event();self.thread=None
        self.metrics_lock=threading.Lock();self.last_metrics={}
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with contextlib.closing(_connect(self.path)) as c,c:
            c.execute('CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
            c.execute('CREATE TABLE IF NOT EXISTS nodes(path TEXT PRIMARY KEY,parent TEXT NOT NULL,sort_type INTEGER NOT NULL,mtime REAL NOT NULL,name TEXT NOT NULL,kind TEXT NOT NULL,document TEXT NOT NULL)')
            c.execute('CREATE INDEX IF NOT EXISTS library_parent_order ON nodes(parent,sort_type,mtime DESC,path DESC)')
            c.execute('CREATE TABLE IF NOT EXISTS thumbnails(id TEXT PRIMARY KEY,source TEXT NOT NULL)')

    def _state(self,c,**changes):
        row=c.execute("SELECT value FROM metadata WHERE key='state'").fetchone()
        value=json.loads(row[0]) if row else {'status':'building','counts':{},'building':True}
        value.update(changes)
        c.execute("INSERT OR REPLACE INTO metadata VALUES('state',?)",(json.dumps(value),))

    def rebuild(self, *, lock_timeout=.1):
        with locked(self.root/'data/content-library.lock',timeout=lock_timeout):
            with contextlib.closing(_connect(self.path)) as c,c:
                requested,_=_refresh_counts(c)
                self._state(c,building=True,status='building',build_started_at=time.time())
            try:
                source_version=self.signature()
                roots=self.builder()
                if self.stop.is_set():return
                rows=[];thumbs={};seen=set()
                def visit(node,parent):
                    path=node['path']
                    if path in seen:raise ValueError('duplicate library identity')
                    seen.add(path)
                    first_image=path if node.get('type')=='file' and node.get('kind')=='image' else None
                    for child in node.get('children',[]):
                        candidate=visit(child,path)
                        if not first_image:first_image=candidate
                    value={k:node[k] for k in ('path','type','name','kind','mtime','size','fileCount','meta') if k in node}
                    # Store metadata only, never a nested tree or file bodies.
                    value['hasChildren']=bool(node.get('children'))
                    if first_image and not value.get('meta',{}).get('cover'):
                        value['meta']={**value.get('meta',{}),'cover':first_image}
                    if value.get('meta',{}).get('cover'):
                        value['meta']=dict(value['meta']);source=value['meta']['cover']
                        thumb=hashlib.sha256(source.encode()).hexdigest();thumbs[thumb]=source
                        value['meta']['cover']='__thumb__/'+thumb+'.jpg'
                    search_name=node.get('name','')+'\n'+str(node.get('meta',{}).get('title',''))
                    rows.append((path,parent,0 if node['type']=='dir' else 1,float(node.get('mtime') or 0),search_name,node.get('kind') or node.get('meta',{}).get('kind') or '',json.dumps(value,ensure_ascii=False)))
                    return first_image
                for node in roots:visit(node,'')
                digest=hashlib.sha256(json.dumps(sorted(rows),ensure_ascii=False).encode()).hexdigest()
                with contextlib.closing(_connect(self.path)) as c,c:
                    previous=c.execute("SELECT value FROM metadata WHERE key='content_hash'").fetchone()
                    if not previous or previous[0]!=digest:
                        c.execute('DELETE FROM nodes');c.executemany('INSERT INTO nodes VALUES(?,?,?,?,?,?,?)',rows)
                        c.execute('DELETE FROM thumbnails');c.executemany('INSERT INTO thumbnails VALUES(?,?)',thumbs.items())
                        c.execute("INSERT OR REPLACE INTO metadata VALUES('revision',?)",(uuid.uuid4().hex,))
                        c.execute("INSERT OR REPLACE INTO metadata VALUES('content_hash',?)",(digest,))
                    c.execute("INSERT OR REPLACE INTO metadata VALUES('refresh_completed',?)",(str(requested),))
                    self._state(c,status='ready',building=False,counts={'nodes':len(rows),'projects':len(roots)},refreshed_at=time.time(),source_revision=source_version,**self.last_metrics)
            except BaseException as error:
                with contextlib.closing(_connect(self.path)) as c,c:self._state(c,status='error',building=False,error_type=type(error).__name__)
                raise

    def invalidate(self):
        request_refresh(self.root);self.wake.set()

    def start(self):
        if self.thread and self.thread.is_alive():return
        def run():
            state=health(self.root)
            previous=state.get('source_revision',object());last=time.monotonic() if state.get('status')=='ready' else 0
            while not self.stop.is_set():
                self.wake.clear()
                try:
                    current=self.signature()
                    with contextlib.closing(_read(self.path)) as c:requested,completed=_refresh_counts(c)
                    if requested>completed or current!=previous or time.monotonic()-last>300:
                        self.rebuild();previous=current;last=time.monotonic()
                    with self.metrics_lock:metrics=dict(self.last_metrics)
                    if metrics:
                        with contextlib.closing(_connect(self.path)) as c,c:self._state(c,**metrics)
                except Exception:pass
                self.wake.wait(5)
        self.thread=threading.Thread(target=run,name='content-library-index',daemon=True);self.thread.start()

    def close(self):
        self.stop.set();self.wake.set()
        if self.thread:self.thread.join(timeout=2)

    @staticmethod
    def summary(node):
        value={k:v for k,v in node.items() if k!='meta'}
        value['name']=str(value.get('name',''))[:240]
        if node.get('meta'):
            value['meta']={k:v for k,v in node['meta'].items() if k in ('title','kind','status','work_id','version_id','session_id','turn_id','cover')}
            if 'title' in value['meta']:value['meta']['title']=str(value['meta']['title'])[:240]
        return value

    def list(self,*,parent='',cursor=None,limit=50,query='',kind=''):
        start=time.monotonic()
        if not 1<=limit<=100 or len(parent)>4096 or len(query)>200 or kind not in ('','all','image','video','audio','text','binary','poster','article','music','transcript'):raise HTTPException(400,'内容查询无效')
        identity=hashlib.sha256(json.dumps([parent,query,kind],ensure_ascii=False).encode()).hexdigest()
        with contextlib.closing(_read(self.path)) as c:
            c.execute('BEGIN')
            row=c.execute("SELECT value FROM metadata WHERE key='revision'").fetchone();revision=row[0] if row else ''
            state=c.execute("SELECT value FROM metadata WHERE key='state'").fetchone();requested,completed=_refresh_counts(c);indexing=not bool(revision) or requested>completed
            args=[parent];where='parent=?'
            if query:where+=' AND name LIKE ? ESCAPE \'!\'';args.append('%'+query.replace('!','!!').replace('%','!%').replace('_','!_')+'%')
            if kind and kind!='all':where+=' AND (sort_type=0 OR kind=?)';args.append(kind)
            total=json.loads(state[0]).get('counts',{}).get('projects',0) if not parent and not query and kind in ('','all') and state else c.execute('SELECT count(*) FROM nodes WHERE '+where,args).fetchone()[0]
            if cursor:
                try:
                    if len(cursor)>8192:raise ValueError()
                    token=json.loads(base64.urlsafe_b64decode(cursor+'='*(-len(cursor)%4)))
                    if token['revision']!=revision or token['identity']!=identity:raise HTTPException(409,'library_cursor_stale')
                    order,mtime,path=token['after']
                    if order not in (0,1) or not isinstance(mtime,(float,int)) or not isinstance(path,str):raise ValueError()
                    where+=' AND (sort_type>? OR (sort_type=? AND (mtime<? OR (mtime=? AND path<?))))';args.extend((order,order,mtime,mtime,path))
                except HTTPException:raise
                except Exception:raise HTTPException(400,'分页标识无效') from None
            rows=c.execute('SELECT * FROM nodes WHERE '+where+' ORDER BY sort_type,mtime DESC,path DESC LIMIT ?',(*args,limit+1)).fetchall()
            items=[];last=None;size=0
            for row in rows[:limit]:
                node=self.summary(json.loads(row['document']));length=len(json.dumps(node,ensure_ascii=False).encode())
                if items and size+length>85000:break
                items.append(node);last=row;size+=length
            next_cursor=None
            if last and len(rows)>len(items):
                next_cursor=base64.urlsafe_b64encode(json.dumps({'revision':revision,'identity':identity,'after':[last['sort_type'],last['mtime'],last['path']]}).encode()).decode().rstrip('=')
            value={'items':items,'next_cursor':next_cursor,'revision':revision,'indexing':indexing,'total':total}
            if parent:
                row=c.execute('SELECT document FROM nodes WHERE path=?',(parent,)).fetchone()
                if row:value['parent']=json.loads(row[0])
                elif revision:raise HTTPException(404,'内容不存在或已归档')
        with self.metrics_lock:self.last_metrics={'last_list_ms':round((time.monotonic()-start)*1000,3),'last_list_bytes':len(json.dumps(value,ensure_ascii=False).encode())}
        return value

    def resolve(self,path):
        # Await only an already-requested background publication, never scan
        # files in a request. Stay below the host's ordinary 30-second read cap.
        deadline=time.monotonic()+20
        while True:
            try:return self._resolve_indexed(path)
            except HTTPException as error:
                if error.status_code!=404:raise
                with contextlib.closing(_read(self.path)) as c:requested,completed=_refresh_counts(c)
                if requested<=completed or time.monotonic()>=deadline:
                    return self._resolve_indexed(path) # Recheck a publication racing this read.
                time.sleep(.05)

    def _resolve_indexed(self,path):
        if not isinstance(path,str) or len(path)>4096:raise HTTPException(400,'内容路径无效')
        nodes=[];seen=set()
        with contextlib.closing(_read(self.path)) as c:
            c.execute('BEGIN')
            while path:
                if path in seen:raise HTTPException(409,'内容路径关系无效')
                seen.add(path);row=c.execute('SELECT parent,document FROM nodes WHERE path=?',(path,)).fetchone()
                if not row:raise HTTPException(404,'内容尚未登记或已归档')
                nodes.append(json.loads(row['document']));path=row['parent']
        return {'nodes':list(reversed(nodes))}

    def subtree(self,path, *, with_revision=False):
        """Exact indexed descendants for a user-selected storage operation."""
        self._resolve_indexed(path)
        with contextlib.closing(_read(self.path)) as c:
            c.execute('BEGIN')
            revision=c.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0]
            nodes=[json.loads(row[0]) for row in c.execute('''
                WITH RECURSIVE selected(path,document) AS (
                    SELECT path,document FROM nodes WHERE path=?
                    UNION ALL SELECT n.path,n.document FROM nodes n JOIN selected s ON n.parent=s.path
                ) SELECT document FROM selected''',(path,))]
        return {'nodes':nodes,'revision':revision} if with_revision else nodes

    def generation(self):
        with contextlib.closing(_read(self.path)) as c:
            row=c.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()
        return row[0] if row else None

    def thumbnail_source(self,key):
        with contextlib.closing(_read(self.path)) as c:
            row=c.execute('SELECT source FROM thumbnails WHERE id=?',(key,)).fetchone()
        if not row:raise HTTPException(404,'封面尚未登记')
        return row[0]
