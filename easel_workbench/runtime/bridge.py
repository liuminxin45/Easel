"""Fixed-thread FIFO bridge. Never edits Codex stores; unknown state blocks."""
import json, pathlib, re, shutil, subprocess, threading, time, mimetypes, os, msvcrt
from easel_workbench.runtime.desk import ROOT,PROJECT,THREAD,Store,stamp
CODEX=pathlib.Path('C:/Users/38482/AppData/Local/Programs/OpenAI/Codex/bin/codex.exe')
STATE=pathlib.Path('C:/Users/38482/.codex/state_5.sqlite')
PRODUCT_ROOTS=[PROJECT/'内容',PROJECT/'.runtime/贴图待采纳']
EXTENSIONS={'.png','.jpg','.jpeg','.webp','.gif','.pdf','.txt','.docx','.md','.html','.mp4','.webm'}
def events(path,offset=None):
    """Stream complete JSONL records to a captured EOF, without a task-size cap.

    Image/compaction records can themselves exceed 16 MB. A prefix of that size
    is not a complete task history and must never hide a later completion.
    Tail-only reads are reserved for the conservative global lifecycle probe.
    """
    size=path.stat().st_size
    start=max(0,size-8000000) if offset is None else offset
    return event_lines(path,start,size,discard_first=offset is None and start>0)

def event_lines(path,start,end,discard_first=False):
    with path.open('rb') as f:
        f.seek(start)
        if discard_first: f.readline(max(0,end-f.tell()))
        while f.tell()<end:
            line=f.readline(end-f.tell())
            if not line or not line.endswith(b'\n'): break
            try: event=json.loads(line)
            except (ValueError,UnicodeError): continue
            if isinstance(event,dict): yield event

def lifecycle(es):
    active=set(); completed=False
    for e in es:
        if e.get('type')!='event_msg': continue
        p=e.get('payload',{}); kind=p.get('type'); turn=p.get('turn_id') or p.get('root_turn_id') or 'unknown'
        if kind=='task_started': active.add(turn)
        elif kind in ('task_complete','turn_aborted'):
            active.discard(turn); completed=True
    return 'running' if active else ('idle' if completed else 'unknown')

def target():
    import sqlite3
    c=sqlite3.connect('file:'+str(STATE)+'?mode=ro',uri=True)
    try: row=c.execute('select id,cwd,rollout_path from threads where id=?',(THREAD,)).fetchone()
    finally: c.close()
    if not row or pathlib.Path(row[1].removeprefix('\\\\?\\')).resolve()!=PROJECT.resolve(): raise RuntimeError('fixed thread/project verification failed')
    return pathlib.Path(row[2].removeprefix('\\\\?\\'))

def allowed_artifact(p):
    try:
        p=pathlib.Path(p).resolve()
        name=p.name.lower(); label=re.sub(r'^\d+[-_. ]*','',p.stem.lower())
        process_file=label.startswith(('检查','check','验收','验证')) or any(x in name for x in ('检查记录','检查报告','检查结果'))
        return p.is_file() and (p.suffix.lower() in EXTENSIONS or p.name in ('文章交付.json','风格权重.json','设计说明.json')) and any(p.is_relative_to(root.resolve()) for root in PRODUCT_ROOTS) and not process_file and not any(x in name for x in ('reference','prompt','source','参考','原图','证据','原始'))
    except OSError: return False

def capture_artifacts(store,tid,reply):
    # Only explicit delivered file links or delivered directories, not global newest files.
    paths=re.findall(r'\]\(((?:D:|d:)/[^)\n]+)\)',reply)
    json_candidates=[reply]+re.findall(r'```(?:json)?\s*\n(.*?)\n```',reply,re.S)
    def collect(value):
        if isinstance(value,str) and re.match(r'^[dD]:[/\\\\]',value): paths.append(value.replace('\\\\','/'))
        elif isinstance(value,list):
            for x in value: collect(x)
        elif isinstance(value,dict):
            for key in ('artifacts','deliverables','files','path','file','final_path','output_path'): 
                if key in value: collect(value[key])
    for candidate in json_candidates:
        try: collect(json.loads(candidate))
        except ValueError: pass
    discovered=[]
    for value in paths:
        p=pathlib.Path(value)
        if p.is_file(): discovered.append(p)
        # A directory link is not an authorization to expose every neighboring file.
        # Executor must enumerate exact final products in its delivery Markdown/JSON.
    for p in dict.fromkeys(discovered):
        if not allowed_artifact(p): continue
        import hashlib
        content_hash=hashlib.sha256(p.read_bytes()).hexdigest()
        aid=hashlib.sha256((tid+'\0'+str(p.resolve())+'\0'+content_hash).encode('utf-8')).hexdigest(); dest=ROOT/'data/artifacts'/aid/p.name; dest.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(p,dest)
        mime=mimetypes.guess_type(p.name)[0] or 'application/octet-stream'
        with store.connect() as c:
            c.execute('insert or ignore into artifacts values(?,?,?,?,?)',(aid,tid,p.name,str(dest),mime))
            if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='toolbox_product_origins'").fetchone():
                from easel_workbench.runtime.local_operations import product_origin
                product_origin(c,aid,tid,str(p.resolve()),content_hash)

    from easel_workbench.runtime.content_studio import apply_locked_text
    apply_locked_text(store,tid,ROOT)

def correlate(es,token):
    seen=False; pending=False; turn=None; result=None; final=''
    marker=re.compile(r'^\s*\[AI_NEWS_DESK_REQUEST:([A-Za-z0-9_-]+)\]')
    declared=re.compile(r'^\['+re.escape(token)+r'\]\s*$',re.M)
    for e in es:
        p=e.get('payload',{})
        if e.get('type')=='event_msg' and p.get('type')=='task_started':
            turn=p.get('turn_id'); seen=False; final=''
        user=None
        if e.get('type')=='response_item' and p.get('type')=='message':
            text='\n'.join(c.get('text','') for c in p.get('content',[]) if c.get('type') in ('text','input_text','output_text'))
            if p.get('role')=='user': user=text
            elif p.get('role')=='assistant' and p.get('channel')=='final': final=text
        if e.get('type')=='event_msg' and p.get('type')=='user_message': user=p.get('message')
        if isinstance(user,str):
            request=marker.match(user)
            if request:
                pending=seen=('AI_NEWS_DESK_REQUEST:'+request.group(1)==token)
        if e.get('type')=='event_msg' and p.get('type')=='task_complete' and p.get('turn_id')==turn:
            reply=p.get('last_agent_message') or final
            # Interrupted turns may end with a null completion. Only a real
            # final reply can complete a job. A resumed turn must explicitly
            # declare the original request; another work's request cancels it.
            if isinstance(reply,str) and reply.strip() and (seen or pending and declared.search(reply)):
                result={'reply':reply,'turn_id':turn}; pending=False
    return result

