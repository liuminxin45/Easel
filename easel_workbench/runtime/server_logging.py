"""Content-free asynchronous JSONL diagnostics, hourly rotation and seven-day retention."""
import atexit
import datetime as dt
import hashlib
import json
import logging
import os
import pathlib
import queue
import re
import sqlite3
import threading
import time
import traceback

_sink=None
FIELDS={'trace_id','route','method','status','duration_ms','error_type','operation_ref','resource_ref','phase','count','pid','exit_code','dropped','phases_ms','reads','commands','failures','frames','origin_state','android','webview','login_cookie_present','sqlite_errorcode','sqlite_errorname'}
NAME=re.compile(r'^(server|worker|feedback|learning|local|supervisor|auth)-\d{10}-[a-f0-9]+-\d+\.jsonl$')

def reference(value):return hashlib.sha256(str(value).encode()).hexdigest()[:24]

def route(path):
    path=str(path).split('?',1)[0]
    if path in {'/login','/logout','/logout-all'}:return path
    if path in {'/distribution/check','/distribution/auto-check','/api/distribution/auto-relay','/api/distribution/auto-check','/native/','/native/login','/api/distribution/browser','/api/distribution/observations','/api/distribution/check-report','/api/distribution/discovery'}:return path
    if re.fullmatch(r'/api/distribution/checks/[A-Za-z0-9_-]{1,160}',path):return '/api/distribution/checks/:id'
    if path.startswith('/api/operations/'):return '/api/operations/:id'
    if path.startswith('/media/images/'):return '/media/images/:id/:name'
    if path in {'/api/wiki/overview','/api/wiki/notes','/api/wiki/notes/edit','/api/wiki/notes/delete','/api/wiki/categories','/api/wiki/document','/api/wiki/file','/api/wiki/jobs','/api/wiki/idea'}:return path
    if re.fullmatch(r'/api/wiki/jobs/[^/]+(?:/(?:apply|retry))?',path):return '/api/wiki/jobs/:id'+('/'+path.rsplit('/',1)[-1] if path.endswith(('/apply','/retry')) else '')
    if path in {'/api/release','/api/news','/api/news/read','/api/news/feedback','/api/news/feedback/retry','/api/works','/api/history','/api/uploads','/api/mobile/poll','/api/mobile/devices','/health'}:return path
    if re.fullmatch(r'/api/works/[^/]+/versions/[^/]+/download',path):return '/api/works/:id/versions/:id/download'
    if re.fullmatch(r'/api/works/[^/]+/actions',path):return '/api/works/:id/actions'
    if re.fullmatch(r'/api/works/[^/]+/(?:local-operations|project-binding|local-operations/retry)',path):return '/api/works/:id/'+path.split('/',4)[4]
    if re.fullmatch(r'/api/tasks/[^/]+/retry',path):return '/api/tasks/:id/retry'
    for resource in ('news','works','tasks','files'):
        if re.fullmatch(r'/api/'+resource+r'/[^/]+',path):return '/api/'+resource+'/:id'
    if path.startswith('/api/v2/uploads/'):return '/api/v2/uploads/:id'
    known={'bootstrap','snapshot','events','changes','operations','uploads','diagnostics','config','cache-session','status','articles','article','notifications','action','production'}
    if path in {prefix+name for prefix in ('/api/','/api/v2/') for name in known}:return path
    if path.startswith('/api/workbench/') and path.rsplit('/',1)[-1] in {'history','threads','messages','queue','settings','goal','control','hosts','providers','projects','questions','agents','seen','read','read-state','changes','answer'}:return path
    return '/api/other' if path.startswith('/api/') else '/page-or-asset'

class Journal:
    def __init__(self,directory,role,clock=time.time,max_bytes=16*1024*1024):
        if role not in {'server','worker','feedback','learning','local','supervisor','auth'}:raise ValueError('Unknown log role')
        self.directory=pathlib.Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.role=role;self.clock=clock;self.max_bytes=max_bytes;self.queue=queue.Queue(10000)
        self.dropped=0;self.failures=0;self.sequence=0;self.handle=None;self.hour=None;self.last_cleanup=0
        self.instance=f'{os.getpid():x}{time.time_ns():x}';self.stopping=threading.Event()
        release=os.environ.get('AI_DESK_RELEASE','')
        self.release=release if re.fullmatch(r'(?:toolbox|workbench)-[A-Za-z0-9_.-]{1,100}',release) else None
        self.thread=threading.Thread(target=self._run,name='diagnostic-journal',daemon=True);self.thread.start()

    def emit(self,event,**fields):
        if self.stopping.is_set():return
        # Callers provide fixed event names and typed metadata; arbitrary payload keys are discarded.
        if not re.fullmatch(r'[a-z_]{1,64}',event):return
        data={'at':self.clock(),'event':event,'role':self.role,'pid':os.getpid()}
        if self.release:data['release']=self.release
        for key,value in fields.items():
            if key not in FIELDS:continue
            if key=='frames':
                data[key]=[{k:v for k,v in frame.items() if k in {'file','line','function'}} for frame in value[:12]]
            elif key=='phases_ms':
                data[key]={k:round(v,3) for k,v in value.items() if re.fullmatch(r'[a-z_]{1,50}',k) and isinstance(v,(int,float))} if isinstance(value,dict) else {}
            elif key=='sqlite_errorcode':
                if type(value) is int and 0<=value<=0x7fffffff:data[key]=value
            elif key=='sqlite_errorname':
                if isinstance(value,str) and re.fullmatch(r'SQLITE_[A-Z0-9_]{1,64}',value):data[key]=value
            elif isinstance(value,(int,float,bool)) or value is None:data[key]=value
            elif key in {'operation_ref','resource_ref','trace_id'} and re.fullmatch(r'[a-f0-9]{16,64}',str(value)):data[key]=value
            elif key=='route':data[key]=route(value)
            elif key in {'phase','method','error_type','origin_state'} and re.fullmatch(r'[A-Za-z0-9_]{1,64}',str(value)):data[key]=value
        try:self.queue.put_nowait(data)
        except queue.Full:self.dropped+=1

    def cleanup(self,now=None):
        now=self.clock() if now is None else now
        cutoff=now-7*86400
        if self.handle and dt.datetime.strptime(self.hour,'%Y%m%d%H').replace(tzinfo=dt.timezone.utc).timestamp()+3600<=cutoff:
            self.handle.close();self.handle=None
        for path in self.directory.iterdir():
            if not NAME.fullmatch(path.name) or path.is_symlink():continue
            hour=path.name.split('-')[1]
            stamp=dt.datetime.strptime(hour,'%Y%m%d%H').replace(tzinfo=dt.timezone.utc).timestamp()
            if stamp+3600<=cutoff and (self.handle is None or pathlib.Path(self.handle.name)!=path):
                try:path.unlink()
                # Another process may have pruned the same expired file.
                except FileNotFoundError:pass
                except OSError:self.failures+=1

    def _write(self,data):
        now=self.clock();hour=dt.datetime.fromtimestamp(now,dt.timezone.utc).strftime('%Y%m%d%H')
        if self.handle is None or self.hour!=hour or self.handle.tell()>=self.max_bytes:
            if self.handle:self.handle.close()
            self.sequence+=1;self.hour=hour
            self.handle=(self.directory/f'{self.role}-{hour}-{self.instance}-{self.sequence}.jsonl').open('a',encoding='utf-8')
        self.handle.write(json.dumps(data,ensure_ascii=True,separators=(',',':'),allow_nan=False)+'\n');self.handle.flush()
        if now-self.last_cleanup>=60:self.cleanup(now);self.last_cleanup=now

    def _run(self):
        last_status=None
        while not self.stopping.is_set() or not self.queue.empty():
            # Use the existing writer to persist real counters during idle time.
            now=self.clock()
            if not self.stopping.is_set() and (last_status is None or now-last_status>=60):
                self.emit('journal_status',count=self.queue.qsize(),dropped=self.dropped,failures=self.failures)
                last_status=now
            try:data=self.queue.get(timeout=.5)
            except queue.Empty:
                try:
                    if self.clock()-self.last_cleanup>=60:self.cleanup();self.last_cleanup=self.clock()
                except OSError:self.failures+=1
                continue
            try:self._write(data)
            except (OSError,ValueError,TypeError):self.failures+=1
            finally:self.queue.task_done()
        if self.handle:self.handle.close()

    def status(self):return {'queued':self.queue.qsize(),'dropped':self.dropped,'failures':self.failures,'retention_days':7}
    def close(self):self.stopping.set();self.thread.join(5)

def configure(directory,role):
    global _sink
    if _sink:_sink.close()
    _sink=Journal(directory,role);atexit.register(_sink.close);return _sink

class SafeExceptionHandler(logging.Handler):
    def emit(self,record):
        # Never interpolate third-party messages: they can contain URLs or headers.
        if record.exc_info and record.exc_info[1]:exception('runtime_exception',record.exc_info[1])
        elif record.levelno>=logging.WARNING:emit('runtime_warning',phase=record.levelname)

def install_exception_hooks():
    import sys
    handler=SafeExceptionHandler()
    for name in ('uvicorn','uvicorn.error','asyncio'):
        logger=logging.getLogger(name);logger.handlers=[handler];logger.propagate=False
    def uncaught(kind,value,tb):
        exception('process_exception',value)
        if _sink:_sink.close()
    sys.excepthook=uncaught

def exception(event,error,**fields):
    frames=[{'file':pathlib.Path(f.filename).name,'line':f.lineno,'function':f.name} for f in traceback.extract_tb(error.__traceback__)[-12:]]
    if isinstance(error,sqlite3.Error):
        code=getattr(error,'sqlite_errorcode',None);name=getattr(error,'sqlite_errorname',None)
        if type(code) is int and 0<=code<=0x7fffffff:fields['sqlite_errorcode']=code
        if isinstance(name,str) and re.fullmatch(r'SQLITE_[A-Z0-9_]{1,64}',name):fields['sqlite_errorname']=name
    emit(event,error_type=type(error).__name__,frames=frames,**fields)

def emit(event,**fields):
    if _sink:_sink.emit(event,**fields)

def status():return _sink.status() if _sink else {'enabled':False}
