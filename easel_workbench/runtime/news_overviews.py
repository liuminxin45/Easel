"""Chinese one-sentence reading titles; source articles/canonical remain untouched.

Reuse the existing logged-in, ephemeral read-only Codex runner, never production
threads or a paid API key. The web request only reads persisted projections.
"""

if __name__ == "__main__" and not __package__:
    import sys as _bootstrap_sys
    from pathlib import Path as _BootstrapPath
    _bootstrap_sys.path.insert(0,str(_BootstrapPath(__file__).resolve().parents[2]))

import argparse,hashlib,json,os,pathlib,re,sqlite3,subprocess,tempfile,threading,time
from easel_workbench.runtime.desk import ROOT,SOURCES,Store,Connection,stamp
from easel_workbench.runtime.feedback_ledger import locked,atomic
from easel_workbench.runtime.readonly_codex import CODEX,command

VERSION='zh-one-sentence-v1'
MODEL='gpt-6-luna'
REASONING_EFFORT='low'
SCHEMA={'type':'object','additionalProperties':False,'required':['items'],'properties':{'items':{'type':'array','items':{'type':'object','additionalProperties':False,'required':['id','summary'],'properties':{'id':{'type':'string'},'summary':{'type':'string'}}}}}}

def overview_command(directory):
    # Keep the shared read-only runner unchanged; pin only news title generation.
    args=command(directory)
    return [*args[:-1],'--model',MODEL,'-c',f'model_reasoning_effort="{REASONING_EFFORT}"',args[-1]]

def fingerprint(row):
    return hashlib.sha256(json.dumps([VERSION,row['title'],row['body'],row['url']],ensure_ascii=False).encode()).hexdigest()

def cutover_paused(root):
    """Pause automatic AI enrichment while the compatible server is readied."""
    try:
        value=json.loads((pathlib.Path(root)/'data/automation-enabled.json').read_text(encoding='utf-8-sig'))
        return not isinstance(value,dict) or value.get('cutover_paused') is True
    except FileNotFoundError:return False
    except (OSError,ValueError):return True

def validate(value):
    if not isinstance(value,str) or not 12<=len(value)<=120 or len(re.findall(r'[\u3400-\u9fff]',value))<4:raise ValueError('概述必须为12至120字的一句中文')
    if any(c in value for c in '\r\n<>') or re.search(r'[。！？!?].',value) or not value.endswith('。'):raise ValueError('概述须为一个完整中文句子')
    return value

def reading_summary(value):
    """Optional upstream projection. Bad/missing legacy fields need only enrichment."""
    try:return validate(value)
    except (ValueError,TypeError):return None

def record_upstream(store,root,document):
    """Persist only an exact read-back projection, without changing the article."""
    from easel_workbench.runtime.desk import article_identity
    service=Overviews(store,root);accepted=0
    with store.connect() as c:
        rows={r['id']:dict(r) for r in c.execute('SELECT * FROM articles WHERE source_job=?',(document['source_job'],))}
    with service.connect() as c:
        for item in document.get('articles',[]):
            value=reading_summary(item.get('reading_summary'));row=rows.get(article_identity(document['source_job'],item))
            if not value or not row or any(row[k]!=item.get(k) for k in ('title','body','url')):continue
            current=c.execute('SELECT * FROM overviews WHERE article_id=?',(row['id'],)).fetchone()
            # A valid successful observation of these exact inputs is sufficient.
            if current and current['input_hash']==fingerprint(row) and current['status']=='ready' and reading_summary(current['summary']):continue
            c.execute("INSERT OR REPLACE INTO overviews VALUES(?,?,'ready',?,NULL,0,0,?)",(row['id'],fingerprint(row),value,stamp()))
            c.execute('INSERT OR REPLACE INTO overview_sources VALUES(?,?,?,?)',(row['id'],fingerprint(row),'editorial_same_call',document.get('run_id','')));accepted+=1
    return accepted

def analyze(rows,root=ROOT,*,native_allowed=True):
    env={k:v for k,v in os.environ.items() if k not in ('OPENAI_API_KEY','CODEX_API_KEY')}
    options={'capture_output':True,'text':True,'encoding':'utf-8','errors':'replace','creationflags':subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0,'env':env}
    runtime=pathlib.Path(root)/'data/news-overview-runtime';runtime.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='overview-',dir=runtime) as tmp:
        directory=pathlib.Path(tmp);(directory/'schema.json').write_text(json.dumps(SCHEMA),encoding='utf-8')
        material=[{k:r[k] for k in ('id','title','body','url','source_job')} for r in rows]
        for r in material:r['body']=r['body'][:6000]
        from easel_workbench.runtime.task_runtime import contract_prompt,observed_call
        from easel_workbench.readonly_runner import run,recorded_output,project_snapshot,ReadonlyOutputInvalid
        prompt,binding=contract_prompt(root,'news_enhancement','references/news-summary.md',material)
        native_binding=binding if native_allowed and project_snapshot(binding) else None
        if native_binding is None:
            login=subprocess.run([str(CODEX),'login','status'],timeout=30,**options)
            if login.returncode or 'Logged in using ChatGPT' not in login.stdout+login.stderr:raise RuntimeError('需要现有 ChatGPT 订阅登录；未启用付费API')
        with observed_call(root,'news_enhancement',material,prompt,binding) as record_result:
            result=run(native_binding,overview_command(directory),input=prompt,timeout=360,cwd=directory,runtime_root=root,**options)
            try:
                answer=directory/'answer.json'
                if result.returncode or not answer.is_file():raise RuntimeError('本机Codex未返回概述；原文已保留')
                if answer.stat().st_size>100000:raise ValueError('概述响应过大')
                items=json.loads(answer.read_text(encoding='utf-8'))['items']
                if len(items)!=len(rows) or {i['id'] for i in items}!={r['id'] for r in rows}:raise ValueError('概述ID不匹配')
                summaries={i['id']:validate(i['summary']) for i in items}
            except Exception:
                receipt=getattr(result,'execution_receipt',None)
                if receipt:raise ReadonlyOutputInvalid(receipt) from None
                raise
            record_result(recorded_output(result,summaries))
            return {i['id']:validate(i['summary']) for i in items}

class Overviews:
    def __init__(self,store,root=ROOT):
        self.store=store;self.root=pathlib.Path(root);self.path=self.root/'data/news-overviews.sqlite';self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as c:
            c.execute('''CREATE TABLE IF NOT EXISTS overviews(article_id TEXT PRIMARY KEY,input_hash TEXT NOT NULL,status TEXT NOT NULL,summary TEXT,error TEXT,attempts INTEGER NOT NULL DEFAULT 0,retry_at REAL NOT NULL DEFAULT 0,updated_at TEXT NOT NULL)''')
            c.execute('CREATE TABLE IF NOT EXISTS overview_sources(article_id TEXT PRIMARY KEY,input_hash TEXT NOT NULL,origin TEXT NOT NULL,source_run TEXT NOT NULL)')
    def connect(self):
        c=sqlite3.connect(self.path,timeout=20,factory=Connection);c.row_factory=sqlite3.Row;c.execute('PRAGMA journal_mode=WAL');return c
    def project(self,rows):
        with self.connect() as c:
            records={r['article_id']:dict(r) for r in c.execute('SELECT * FROM overviews')}
            sources={r['article_id']:dict(r) for r in c.execute('SELECT * FROM overview_sources')}
        result=[]
        for row in rows:
            record=records.get(row['id']);current=record if record and record['input_hash']==fingerprint(row) else None
            status=current['status'] if current else 'pending';summary=reading_summary(current['summary']) if current and status=='ready' else None
            if status=='ready' and not summary:status='pending'
            label={'pending':'中文概述待生成','running':'中文概述生成中','error':'中文概述生成失败，原文已保留'}
            provenance=sources.get(row['id']) or {}
            result.append({**row,'original_title':row['title'],'title':summary or '【'+label.get(status,'中文概述待生成')+'】'+row['title'],'overview':summary,'overview_status':status,'overview_error':current['error'] if current else None,'overview_source':provenance.get('origin') if provenance.get('input_hash')==fingerprint(row) else ('overview_model' if summary else None)})
        return result
    def tick(self,runner=None,limit=16,sources=None):
        with locked(self.root/'data/news-overviews.lock',timeout=.1):
            with self.store.connect() as c:rows=[dict(r) for r in c.execute('SELECT * FROM articles ORDER BY CASE WHEN source_job IN (\'xinquji\',\'github-trending\',\'product-hunt\',\'hacker-news\') THEN 0 ELSE 1 END,run_at DESC,id')]
            now=time.time();pending=[]
            with self.connect() as c:
                for row in rows:
                    if row['source_job'] not in SOURCES or SOURCES[row['source_job']].get('kind')=='periodical' or (sources and row['source_job'] not in sources):continue
                    record=c.execute('SELECT * FROM overviews WHERE article_id=?',(row['id'],)).fetchone();hash_=fingerprint(row)
                    if not record or record['input_hash']!=hash_ or record['status']=='ready' and not reading_summary(record['summary']):
                        c.execute('INSERT OR REPLACE INTO overviews VALUES(?,?,\'pending\',NULL,NULL,0,0,?)',(row['id'],hash_,stamp()));record=None
                    if record and record['status']=='running' and record['retry_at']<=now:
                        c.execute("UPDATE overviews SET status='error',error='后台曾中断，原文已保留',updated_at=? WHERE article_id=?",(stamp(),row['id']))
                    if record and (record['status']=='ready' or record['attempts']>=3 or record['retry_at']>now):continue
                    # A running row surviving a process interruption waits at most six minutes.
                    pending.append({**row,'_native_first_send':not record or record['attempts']==0})
                    if len(pending)>=limit:break
                for row in pending:c.execute("UPDATE overviews SET status='running',attempts=attempts+1,retry_at=?,updated_at=? WHERE article_id=?",(now+420,stamp(),row['id']))
            if not pending:return 0
            try:
                result=(runner or (lambda batch:analyze(batch,self.root,native_allowed=all(row['_native_first_send'] for row in batch))))(pending)
                if set(result)!={r['id'] for r in pending}:raise ValueError('概述ID不匹配')
                result={aid:validate(value) for aid,value in result.items()}
                with self.store.connect() as c:current={r['id']:fingerprint(dict(r)) for r in c.execute('SELECT * FROM articles')}
                with self.connect() as c:
                    for row in pending:
                        if current.get(row['id'])!=fingerprint(row):continue
                        c.execute("UPDATE overviews SET status='ready',summary=?,error=NULL,retry_at=0,updated_at=? WHERE article_id=? AND input_hash=?",(result[row['id']],stamp(),row['id'],fingerprint(row)))
                        c.execute('INSERT OR REPLACE INTO overview_sources VALUES(?,?,?,?)',(row['id'],fingerprint(row),'overview_model',''))
            except Exception as exc:
                from easel_workbench.readonly_runner import ReadonlyExecutionUnknown,ReadonlyOutputInvalid
                held=isinstance(exc,(ReadonlyExecutionUnknown,ReadonlyOutputInvalid))
                # Never persist model output, credentials, prompt or arbitrary exception text as an error.
                with self.connect() as c:
                    for row in pending:c.execute("UPDATE overviews SET status='error',summary=NULL,error=?,retry_at=?,updated_at=? WHERE article_id=?",('中文概述回执待核对，未自动重跑，原始资料已保留' if held else '中文概述未完成（'+type(exc).__name__+'），原始资料已保留',253402300799.0 if held else time.time()+300,stamp(),row['id']))
                raise
            return len(pending)
    def status(self):
        with self.connect() as c:return {r[0]:r[1] for r in c.execute('SELECT status,count(*) FROM overviews GROUP BY status')}

def background(service,stop):
    while not stop.is_set():
        if cutover_paused(service.root):stop.wait(20);continue
        busy=False
        try:
            if getattr(service,'store',None):
                with service.store.connect() as c:
                    tables={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    busy='toolbox_jobs' in tables and c.execute("SELECT 1 FROM toolbox_jobs WHERE kind IN ('create','change') AND status IN ('queued','dispatching','running') LIMIT 1").fetchone()
                    busy=busy or ('learning_analysis_queue' in tables and c.execute("SELECT 1 FROM learning_analysis_queue WHERE kind='production_review' AND status IN ('queued','running') LIMIT 1").fetchone())
        except Exception:stop.wait(20);continue
        if busy:stop.wait(20);continue
        # Independent projection queue: raw weekly entries are already readable.
        if cutover_paused(service.root):stop.wait(20);continue
        try:
            from easel_workbench.runtime.weekly_periodical import Periodical
            Periodical(service.store,service.root).enhance_one()
        except Exception:pass
        if cutover_paused(service.root):stop.wait(20);continue
        try:
            count=service.tick();atomic(service.root/'data/news-overviews-status.json',{'at':stamp(),'states':service.status(),'last_batch':count,'provider':'existing ChatGPT login; ephemeral read-only Codex','model':MODEL,'reasoning_effort':REASONING_EFFORT})
        except TimeoutError:pass
        except Exception as error:atomic(service.root/'data/news-overviews-status.json',{'at':stamp(),'states':service.status(),'error_type':type(error).__name__,'originals_preserved':True,'model':MODEL,'reasoning_effort':REASONING_EFFORT})
        stop.wait(20)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--batches',type=int,default=1);parser.add_argument('--source',action='append');args=parser.parse_args()
    if not 1<=args.batches<=100:parser.error('--batches must be 1..100')
    service=Overviews(Store());completed=0
    for _ in range(args.batches):
        count=service.tick(sources=args.source);completed+=count
        if not count:break
    print(json.dumps({'processed':completed,'states':service.status()},ensure_ascii=False))
if __name__=='__main__':main()
