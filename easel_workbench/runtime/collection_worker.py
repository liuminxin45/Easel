"""One lightweight supervised process; collection is independent of AI production."""
from __future__ import annotations

if __name__ == "__main__" and not __package__:
    import sys as _bootstrap_sys
    from pathlib import Path as _BootstrapPath
    _bootstrap_sys.path.insert(0,str(_BootstrapPath(__file__).resolve().parents[2]))


import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
import uuid

from easel_workbench.runtime.project_paths import ROOT
from easel_workbench.runtime.collection_service import CollectionService,LeaseLost,timestamp,TERMINAL,COUNTERS
from easel_workbench.runtime.feedback_ledger import atomic,locked


def process_creation(pid):
    if os.name=='nt':
        from easel_workbench.runtime.scripts.windows_process_identity import ProcessIdentity
        with ProcessIdentity(pid) as handle:return str(handle.creation_ticks)
    path=Path('/proc')/str(pid)/'stat'
    if path.exists():return path.read_text().rsplit(')',1)[1].split()[19]
    return None


def owner_is_gone(task):
    """PID reuse is safe; unknown/access-denied identity is never treated as gone."""
    pid=task.get('owner_pid');expected=task.get('owner_creation')
    if type(pid) is not int or pid<=0:return False
    if os.name=='nt':
        from easel_workbench.runtime.scripts.windows_process_identity import ProcessIdentity
        try:
            with ProcessIdentity(pid) as handle:
                if handle.exited():return True
                return expected is not None and str(handle.creation_ticks)!=str(expected)
        except OSError as error:return getattr(error,'winerror',None)==87
    try:
        os.kill(pid,0)
    except ProcessLookupError:return True
    except PermissionError:return False
    actual=process_creation(pid)
    return expected is not None and actual is not None and actual!=str(expected)


class CollectionWorker:
    def __init__(self,service,runner=None,concurrency=3,is_gone=owner_is_gone):
        self.service=service;self.root=service.root;self.owner=uuid.uuid4().hex
        self.pid=os.getpid();self.creation=process_creation(self.pid);self.stop=threading.Event()
        self.runner=runner;self.is_gone=is_gone;self.concurrency=max(1,min(3,concurrency))
        self.pool=concurrent.futures.ThreadPoolExecutor(max_workers=self.concurrency,thread_name_prefix='news-collection')
        self.active={}

    def prepare_resume(self,task,directory):
        """Copy successful stages once; never rewind a restarted attempt's files."""
        source_id=task.get('resume_from')
        if not source_id:return
        if not re.fullmatch(r'[a-f0-9]{32}',source_id):raise ValueError('resume identity is invalid')
        marker=directory/'resume.json'
        if marker.exists() and json.loads(marker.read_text(encoding='utf-8')).get('task_id')==source_id:return
        previous=self.service.state/'tasks'/source_id
        if not previous.is_dir():
            atomic(marker,{'task_id':source_id,'files':[],'stage_available':False});return
        total=0;files=[]
        for path in previous.rglob('*'):
            if path.is_symlink():raise ValueError('resume stage contains a link')
            if not path.is_file() or path.name in ('resume.json','worker-result.json'):continue
            relative=path.relative_to(previous);total+=path.stat().st_size
            if len(files)>=1024 or total>512*1024*1024:raise ValueError('resume stages exceed the bounded copy size')
            target=directory/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
            with path.open('rb') as file:old_hash=hashlib.file_digest(file,'sha256').hexdigest()
            with target.open('rb') as file:new_hash=hashlib.file_digest(file,'sha256').hexdigest()
            if old_hash!=new_hash:raise OSError('resume stage did not copy completely')
            files.append({'path':relative.as_posix(),'sha256':new_hash})
        atomic(marker,{'task_id':source_id,'files':files,'stage_available':True})

    def execute(self,task):
        jid=task['id'];token=task['lease_token'];source=task['source_id']
        directory=self.service.state/'tasks'/jid;directory.mkdir(parents=True,exist_ok=True)
        lock_name=hashlib.sha256(source.encode()).hexdigest()+'.lock'
        receipt=directory/'worker-result.json'
        def report(phase,counters=None):self.service.progress(jid,token,phase,counters)
        def validated(result):
            if not isinstance(result,dict):raise ValueError('collector returned no result')
            if result.get('status') not in TERMINAL or not isinstance(result.get('warnings',[]),list):raise ValueError('collector returned invalid terminal state')
            if any(type(result[key]) is not int or not 0<=result[key]<=1000000 for key in COUNTERS if key in result):raise ValueError('collector returned invalid counters')
            return result
        try:
            # OS-held lock complements the DB source index. A stalled process
            # retains its lock, and expiry alone cannot start a second writer.
            with locked(self.service.state/'locks'/lock_name,timeout=2):
                if receipt.exists():
                    prior=json.loads(receipt.read_text(encoding='utf-8'))
                    if prior.get('task_id')!=jid or prior.get('source_id')!=source:raise ValueError('collector receipt identity mismatch')
                    return validated(prior['result'])
                report('fetching')
                self.prepare_resume(task,directory)
                runner=self.runner
                if runner is None:
                    from easel_workbench.runtime.collection_sources import run_source
                    runner=run_source
                result=validated(runner(source,directory,report=report,force=bool(task['force']),root=self.root))
                atomic(receipt,{'task_id':jid,'source_id':source,'result':result})
                return result
        except LeaseLost:
            # A superseded execution must never overwrite the new owner's state.
            return None
        except Exception as error:
            # Collector exceptions may contain URLs/credentials. Keep private
            # response bodies out of the public status and filesystem journal.
            result={'status':'failed','error':'采集未完成（'+type(error).__name__+'）。',
                    'message':'已保留本次阶段；可在采集记录中重试此来源。'}
            atomic(receipt,{'task_id':jid,'source_id':source,'result':result})
            return result

    def tick(self):
        for future,task in list(self.active.items()):
            if future.done():
                # execute catches provider exceptions, but a programming error
                # is still made terminal rather than hidden as a live spinner.
                try:result=future.result()
                except Exception:
                    result={'status':'failed','error':'采集进程发生异常。','message':'阶段已保留，请检查后重试。'}
                try:
                    if result is not None:self.service.finish(task['id'],task['lease_token'],result)
                except sqlite3.OperationalError as error:
                    if 'locked' in str(error).lower() or 'busy' in str(error).lower():continue
                    raise
                except LeaseLost:pass
                del self.active[future]
            else:
                try:self.service.progress(task['id'],task['lease_token'])
                except LeaseLost:pass
        self.service.recover(self.is_gone)
        if self.service.configuration().get('enabled',False):
            self.service.schedule_due()
            for _ in range(self.concurrency-len(self.active)):
                task=self.service.claim(self.owner,self.pid,self.creation)
                if not task:break
                self.active[self.pool.submit(self.execute,task)]=task
        atomic(self.service.state/'heartbeat.json',{'heartbeat':timestamp(self.service.clock()),
               'state':'running' if self.active else 'watching' if self.service.configuration().get('enabled',False) else 'disabled',
               'active_tasks':[task['id'] for task in self.active.values()]})

    def close(self):
        self.stop.set();self.pool.shutdown(wait=True,cancel_futures=False)


def run(root=ROOT):
    from easel_workbench.runtime.desk import Store
    root=Path(root);state=root/'data/collection';state.mkdir(parents=True,exist_ok=True)
    try:
        with locked(state/'worker.lock',timeout=.2):
            worker=CollectionWorker(CollectionService(Store(root/'data/desk.sqlite'),root))
            try:
                while not worker.stop.is_set():
                    try:worker.tick()
                    except Exception as error:
                        atomic(state/'heartbeat.json',{'heartbeat':timestamp(),'state':'blocked','error':'采集服务异常（'+type(error).__name__+'）。'})
                    worker.stop.wait(10)
            finally:worker.close()
    except TimeoutError:return


if __name__=='__main__':run()
