"""Bounded, content-free client performance telemetry for the private host."""
from __future__ import annotations

from collections import deque
from pathlib import Path
import json
import math
import queue
import re
import threading
import time

SCREENS=frozenset(('home','chat.list','chat.detail','news.list','news.detail','skills','profiles','works.list','work.detail','work.create','settings','research','calendar','publications','distribution','unknown'))
METRICS=frozenset(('boot','navigation','loading','request'))
PLATFORMS=frozenset(('android','windows','unknown'))
PHASES=frozenset(('document','dns','connect','tls','first_byte','download','entry','module','boot_visible','shell','config','content','total'))
BUCKETS=(250,500,1000,2000,3000,5000,10000,30000)
_sink=None


def validate(value):
    if not isinstance(value,dict) or set(value)!={'events','dropped'}:raise ValueError('invalid performance batch')
    events=value['events'];dropped=value['dropped']
    if not isinstance(events,list) or not 1<=len(events)<=20 or type(dropped) is not int or not 0<=dropped<=100000:raise ValueError('invalid performance batch')
    clean=[]
    for item in events:
        if not isinstance(item,dict) or set(item)-{'kind','metric','screen','platform','release','buckets','duration_ms','phases_ms','outcome','hidden','trace','request_group','status','at'}:raise ValueError('invalid performance event')
        if item.get('kind') not in ('summary','slow') or item.get('metric') not in METRICS or item.get('screen') not in SCREENS or item.get('platform') not in PLATFORMS:raise ValueError('invalid performance label')
        release=item.get('release')
        if not isinstance(release,str) or not re.fullmatch(r'native-[A-Za-z0-9_-]{1,80}',release):raise ValueError('invalid release')
        row={key:item[key] for key in ('kind','metric','screen','platform','release')}
        if item['kind']=='summary':
            bins=item.get('buckets')
            if not isinstance(bins,list) or len(bins)!=len(BUCKETS)+1 or any(type(n) is not int or not 0<=n<=10000 for n in bins):raise ValueError('invalid histogram')
            row['buckets']=bins
        else:
            duration=item.get('duration_ms');phases=item.get('phases_ms',{});trace=item.get('trace','')
            if type(duration) not in (int,float) or not math.isfinite(duration) or not 0<=duration<=3600000:raise ValueError('invalid duration')
            if not isinstance(phases,dict) or set(phases)-PHASES or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=3600000 for v in phases.values()):raise ValueError('invalid phases')
            if item.get('outcome') not in ('ready','failed','timeout','cancelled','unknown') or type(item.get('hidden')) is not bool:raise ValueError('invalid outcome')
            if not isinstance(trace,str) or (trace and not re.fullmatch(r'[a-f0-9]{16,64}',trace)):raise ValueError('invalid trace')
            row.update(duration_ms=round(duration,1),phases_ms={k:round(v,1) for k,v in phases.items()},outcome=item['outcome'],hidden=item['hidden'])
            if trace:row['trace']=trace
            at=item.get('at')
            if at is not None:
                if type(at) not in (int,float) or not math.isfinite(at) or not 0<=at<=4102444800:raise ValueError('invalid timestamp')
                row['at']=round(at,3)
            group=item.get('request_group');status=item.get('status')
            if group is not None:
                if group not in ('config','chat','news','works','skills','other'):raise ValueError('invalid request group')
                row['request_group']=group
            if status is not None:
                if type(status) is not int or not 0<=status<=599:raise ValueError('invalid status')
                row['status']=status
        clean.append(row)
    return clean,dropped


class Sink:
    def __init__(self,directory,*,max_bytes=64*1024*1024,queue_size=256,clock=time.time):
        self.directory=Path(directory);self.directory.mkdir(parents=True,exist_ok=True)
        self.max_bytes=max_bytes;self.clock=clock;self.queue=queue.Queue(queue_size);self.dropped=0;self.failures=0;self.stop=threading.Event();self.rate=deque();self.rate_lock=threading.Lock()
        self.thread=threading.Thread(target=self._run,name='page-performance',daemon=True);self.thread.start()

    def submit(self,events,dropped):
        now=self.clock()
        with self.rate_lock:
            while self.rate and self.rate[0]<=now-60:self.rate.popleft()
            if len(self.rate)>=60:self.dropped+=len(events);return False
            self.rate.append(now)
        try:self.queue.put_nowait({'at':self.clock(),'events':events,'dropped':dropped})
        except queue.Full:self.dropped+=len(events);return False
        return True

    def _prune(self):
        files=[];cutoff=self.clock()-7*86400
        for path in self.directory.glob('performance-*.jsonl'):
            if path.is_symlink() or not re.fullmatch(r'performance-\d{10}-\d+\.jsonl',path.name):continue
            stat=path.stat();files.append((stat.st_mtime,path,stat.st_size))
        files.sort();total=sum(item[2] for item in files)
        for stamp,path,size in files:
            if stamp<cutoff or total>self.max_bytes:
                try:path.unlink();total-=size
                except OSError:self.failures+=1

    def _write(self,value):
        import datetime
        hour=datetime.datetime.fromtimestamp(self.clock(),datetime.timezone.utc).strftime('%Y%m%d%H')
        for number in range(32):
            path=self.directory/f'performance-{hour}-{number}.jsonl'
            if not path.exists() or path.stat().st_size<4*1024*1024:break
        else:self.dropped+=len(value['events']);return
        if path.is_symlink():raise OSError('linked diagnostics file')
        value={**value,'server_dropped':self.dropped,'write_failures':self.failures}
        with path.open('a',encoding='utf8',newline='\n') as output:output.write(json.dumps(value,ensure_ascii=True,separators=(',',':'),allow_nan=False)+'\n')
        self._prune()

    def _run(self):
        cleaned=0.0
        while not self.stop.is_set() or not self.queue.empty():
            try:value=self.queue.get(timeout=.5)
            except queue.Empty:
                if self.clock()-cleaned>=60:
                    try:self._prune();cleaned=self.clock()
                    except OSError:self.failures+=1
                continue
            try:self._write(value)
            except (OSError,ValueError,TypeError):self.failures+=1
            finally:self.queue.task_done()

    def close(self):self.stop.set();self.thread.join(5)


def configure(directory):
    global _sink
    if _sink:_sink.close()
    _sink=Sink(directory)
    import atexit
    atexit.register(_sink.close)
    return _sink


def ingest(value):
    events,dropped=validate(value)
    if _sink is None:return {'accepted':False,'reason':'unavailable'}
    return {'accepted':_sink.submit(events,dropped)}
