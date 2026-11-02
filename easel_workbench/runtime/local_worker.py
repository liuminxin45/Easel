"""Persistent deterministic project I/O; no AI and no platform publisher."""

if __name__ == "__main__" and not __package__:
    import sys as _bootstrap_sys
    from pathlib import Path as _BootstrapPath
    _bootstrap_sys.path.insert(0,str(_BootstrapPath(__file__).resolve().parents[2]))

import json,os,pathlib,time
from easel_workbench.runtime.local_operations import service,enabled

def progress(worker,state,*,error=None,**fields):
 """Report the actual cycle outcome; a live PID alone is not business health."""
 from easel_workbench.runtime.feedback_ledger import atomic
 from easel_workbench.runtime.desk import stamp
 path=worker.state/'heartbeat.json'
 try:previous=json.loads(path.read_text(encoding='utf-8'))
 except (OSError,ValueError):previous={}
 value={**previous,'schema_version':1,'pid':os.getpid(),'release':os.environ.get('AI_DESK_RELEASE'),
        'heartbeat':stamp(),'state':state,'error_type':type(error).__name__ if error else None,**fields}
 if error is not None:value['last_error_at']=value['heartbeat']
 elif state not in ('error','failed','blocked'):value['last_success_at']=value['heartbeat']
 atomic(path,value)


def tick(worker):
 """One recoverable iteration, with no content or credentials in diagnostics."""
 from easel_workbench.runtime import server_logging as journal
 started=time.monotonic();active=enabled(worker.box,'local_io');result=worker.process_one()
 with worker.store.connect() as c:counts={row[0]:row[1] for row in c.execute('SELECT status,count(*) FROM toolbox_local_tasks GROUP BY status')}
 state='paused' if not active else 'failed' if result and result.get('status')=='failed' else 'working' if result else 'waiting' if any(counts.get(key,0) for key in ('queued','waiting_binding','waiting_production','running')) else 'idle'
 progress(worker,state,enabled=active,counts=counts,last_operation=({'id':result['id'],'kind':result['kind'],'status':result['status']} if result else None))
 if result:journal.emit('local_operation',operation_ref=journal.reference(result['id']),phase=result['kind'],status=result['status'],duration_ms=(time.monotonic()-started)*1000)
 return result

def run(root=None,project=None,*,stop=None,sleep=time.sleep):
 from easel_workbench.runtime.project_paths import ROOT
 from easel_workbench.runtime.desk import Store
 from easel_workbench.runtime.toolbox_store import Toolbox
 root=pathlib.Path(root or ROOT);box=Toolbox(Store(root/'data/desk.sqlite'),root)
 if project:
  from easel_workbench.runtime.local_operations import LocalOperations
  worker=LocalOperations(box,project=project)
 else:worker=service(box)
 from easel_workbench.runtime.feedback_ledger import locked
 from easel_workbench.runtime import server_logging as journal
 try:
  with locked(worker.state/'process.lock',timeout=.2):
   while stop is None or not stop.is_set():
    try:result=tick(worker)
    except Exception as error:
     journal.exception('local_worker_error',error);progress(worker,'error',error=error);result=None
    if result is None:sleep(3)
 except TimeoutError:return

if __name__=='__main__':run()
