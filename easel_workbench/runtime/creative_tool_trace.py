"""Read actual structured image calls in one identified Codex turn, no JS eval."""
import json
def verified_calls(box,c,jid):
 job=c.execute('SELECT id,turn_id,rollout_offset FROM toolbox_jobs WHERE id=?',(jid,)).fetchone()
 if not job or not job['turn_id']:return []
 from easel_workbench.runtime.bridge import target,events
 from easel_workbench.runtime.task_runtime import read_run,thread_id_for,target_for_thread
 direct=c.execute('SELECT source_path FROM toolbox_direct_turns WHERE id=?',(jid,)).fetchone() if c.execute("SELECT 1 FROM sqlite_master WHERE name='toolbox_direct_turns'").fetchone() else None
 if direct:
  import pathlib
  path=pathlib.Path(direct['source_path'])
 elif read_run(c,jid):
  thread=thread_id_for(c,jid)
  if not thread:return []
  path=target_for_thread(thread)
 else:
  current=target();path=current.get('path') if isinstance(current,dict) else current
 if not path:return []
 active=False;result=[]
 for event in events(path,job['rollout_offset']):
  payload=event.get('payload',{})
  if event.get('type')=='event_msg' and payload.get('type')=='task_started':active=payload.get('turn_id')==job['turn_id']
  if event.get('type')=='turn_context':active=payload.get('turn_id')==job['turn_id']
  if not active or event.get('type')!='response_item' or payload.get('type')!='function_call':continue
  if payload.get('name') not in ('image_gen.imagegen','mcp__image_gen__imagegen','image_gen__imagegen'):continue
  try:args=json.loads(payload.get('arguments','{}'))
  except ValueError:continue
  if not isinstance(args.get('prompt'),str) or not payload.get('call_id'):continue
  result.append({'prompt':args['prompt'],'call_id':payload['call_id'],'tool':payload['name'],'references':args.get('referenced_image_paths',[])})
 return result
