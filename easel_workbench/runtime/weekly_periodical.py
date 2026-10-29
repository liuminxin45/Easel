"""Complete originals first; independent resumable summary/theme projections.

GitHub is the authority; AI only normalizes supplied text in the existing
ephemeral read-only subscription runner. Staging files are resumable, not news.
"""

if __name__ == "__main__" and not __package__:
    import sys as _bootstrap_sys
    from pathlib import Path as _BootstrapPath
    _bootstrap_sys.path.insert(0,str(_BootstrapPath(__file__).resolve().parents[2]))

import argparse,base64,datetime as dt,hashlib,json,os,pathlib,re,subprocess,tempfile,time
from easel_workbench.runtime.desk import ROOT,Store,stamp,TZ,url_ok
from easel_workbench.runtime.feedback_ledger import atomic,locked
from easel_workbench.runtime.news_overviews import validate as summary_valid
from easel_workbench.runtime.readonly_codex import CODEX,command

SOURCE='ruanyf-weekly'
VERSION='weekly-content-themes-v2'
REPO='repos/ruanyf/weekly'
def sha(data):return hashlib.sha256(data if isinstance(data,bytes) else data.encode('utf-8')).hexdigest()
def issue_id(path,hash_):return sha(SOURCE+'\0'+path+'\0'+hash_)
def migrate(c):
    c.executescript('''
CREATE TABLE IF NOT EXISTS periodical_issues(id TEXT PRIMARY KEY,source TEXT NOT NULL,number INTEGER NOT NULL,path TEXT NOT NULL,hash TEXT NOT NULL,title TEXT NOT NULL,published_at TEXT NOT NULL,url TEXT NOT NULL,original_markdown TEXT NOT NULL,metadata TEXT NOT NULL,item_count INTEGER NOT NULL,imported_at TEXT NOT NULL,UNIQUE(source,path,hash));
CREATE TABLE IF NOT EXISTS periodical_items(article_id TEXT PRIMARY KEY,issue_id TEXT NOT NULL,ordinal INTEGER NOT NULL,section TEXT NOT NULL,original_title TEXT NOT NULL,summary TEXT NOT NULL,detail TEXT NOT NULL,advertisement INTEGER NOT NULL,original_start INTEGER NOT NULL,original_end INTEGER NOT NULL,external_urls TEXT NOT NULL,UNIQUE(issue_id,ordinal));
CREATE INDEX IF NOT EXISTS periodical_source_number ON periodical_issues(source,number);
CREATE TABLE IF NOT EXISTS periodical_themes(article_id TEXT PRIMARY KEY,theme TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS periodical_batches(id TEXT PRIMARY KEY,manifest_hash TEXT NOT NULL,lower_issue INTEGER NOT NULL,upper_issue INTEGER NOT NULL,issue_count INTEGER NOT NULL,item_count INTEGER NOT NULL,inserted INTEGER NOT NULL,published_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS periodical_enhancement_tasks(id TEXT PRIMARY KEY,issue_id TEXT NOT NULL,offset INTEGER NOT NULL,input_hash TEXT NOT NULL,status TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,retry_at REAL NOT NULL DEFAULT 0,error_type TEXT,updated_at TEXT NOT NULL,UNIQUE(issue_id,offset));
CREATE TABLE IF NOT EXISTS periodical_enhancements(article_id TEXT PRIMARY KEY,input_hash TEXT NOT NULL,summary TEXT NOT NULL,detail TEXT NOT NULL,advertisement INTEGER NOT NULL,theme TEXT,updated_at TEXT NOT NULL);
''')

def parse(raw,number):
    """Lossless character partition, numbered entries and unnumbered essays alike.

    Preamble and cover are explicit entries; retrospective links are individual
    entries. All headings/whitespace/footer remain in the full original document.
    Unsupported or incomplete structure fails closed rather than dropping text.
    """
    text=raw.decode('utf-8');title=re.match(r'^# (.+?)(?:\r?\n|$)',text)
    if not title or not re.search(r'第\s*'+str(number)+r'\s*期',title[1]):raise ValueError('issue title/number mismatch')
    if not re.search(r'（完）|## (?:感谢|鸣谢)',text):raise ValueError('issue completion marker missing')
    headings=list(re.finditer(r'^## (.+?)\r?$',text,re.M))
    if len(headings)<3:raise ValueError('incomplete issue sections')
    regions=[('刊首',title.end(),headings[0].start())]+[(h[1],h.end(),headings[n+1].start() if n+1<len(headings) else len(text)) for n,h in enumerate(headings)]
    items=[];sections=[]
    for section,start,end in regions:
        body=text[start:end];sections.append({'title':section,'start':start,'end':end,'original_markdown':body})
        numbered=list(re.finditer(r'^(?:\d+[、.．]\s*|[（(]\d+[）)]\s*)',body,re.M))
        if not numbered and section=='往年回顾':numbered=list(re.finditer(r'^\[[^\n]+?\]\(https?://',body,re.M))
        cuts=sorted(set([start]+[start+m.start() for m in numbered]+[end]))
        for a,b in zip(cuts,cuts[1:]):
            original=text[a:b]
            clean=re.sub(r'（完）','',original).strip()
            if not clean:continue
            first=clean.splitlines()[0];linked=re.search(r'(?<!!)\[([^\]]+)\]\(https?://',first)
            label=section if not numbered or a==start and numbered[0].start()>0 else (linked[1] if linked else re.sub(r'^(?:\d+[、.．]|[（(]\d+[）)])\s*','',first)[:160] or section)
            urls=list(dict.fromkeys(u.rstrip('。，；') for u in re.findall(r'(?<!!)\[[^\]]*\]\((https?://[^\s)]+)\)',original) if url_ok(u)))
            # Textual sponsorship labels are authoritative and cannot be removed by AI.
            ad=bool(re.search(r'广告|赞助|推广|赞助商|sponsor|advertis',section+'\n'+first,re.I))
            items.append({'id':str(len(items)+1),'section':section,'original_title':label,'original_text':original,'start':a,'end':b,'urls':urls,'advertisement':ad})
    if not items or len(items)>250:raise ValueError('issue entry count out of bounds')
    # Every nontrivial body character is covered by one entry. Only headings,
    # whitespace and the explicit end marker can remain outside the partition.
    residual=list(text)
    for heading in [title,*headings]:residual[heading.start():heading.end()]=[' ']*(heading.end()-heading.start())
    for item in items:
        residual[item['start']:item['end']]=[' ']*(item['end']-item['start'])
    rest=''.join(residual).replace('（完）','')
    if rest.strip():raise ValueError('uncovered substantive text')
    return {'title':title[1],'sections':sections,'items':items,'coverage':'all substantive body characters; full original retained'}

THEMES=('人工智能与自动化','软件开发与开源','数据与基础设施','安全与隐私','硬件与交通','科学与自然','设计与创作','职场与生活','社会与产业','出版与社区')
ITEM_SCHEMA={'type':'object','additionalProperties':False,'required':['id','summary','facts','caveats','advertisement','theme'],'properties':{'id':{'type':'string'},'summary':{'type':'string'},'facts':{'type':'array','items':{'type':'string'}},'caveats':{'type':'array','items':{'type':'string'}},'advertisement':{'type':'boolean'},'theme':{'type':'string','enum':list(THEMES)}}}
SCHEMA={'type':'object','additionalProperties':False,'required':['items'],'properties':{'items':{'type':'array','items':ITEM_SCHEMA}}}
def validate_result(entries,rows,require_theme=False):
    if not isinstance(rows,list) or len(rows)!=len(entries) or {r.get('id') for r in rows}!={e['id'] for e in entries}:raise ValueError('normalization completeness mismatch')
    for row in rows:
        summary_valid(row['summary'])
        if type(row.get('advertisement')) is not bool:raise ValueError('missing sponsorship classification')
        if (require_theme or 'theme' in row) and row.get('theme') not in THEMES:raise ValueError('missing actual-content theme')
        for key in ('facts','caveats'):
            values=row.get(key)
            if not isinstance(values,list) or len(values)>20 or (key=='facts' and not values):raise ValueError('missing structured detail')
            if any(not isinstance(v,str) or not 2<=len(v)<=2000 or len(re.findall('[\u3400-\u9fff]',v))<2 for v in values):raise ValueError('detail must be Chinese')
    return {r['id']:r for r in rows}

def normalize(entries,root=ROOT,timeout=600,cancel=None):
    """One explicit research-skill invocation; no extra model request for tracing."""
    from easel_workbench.runtime.task_runtime import finish_call
    receipt={}
    try:
        rows=_normalize(entries,root,timeout,cancel,receipt)
    except BaseException as error:
        if receipt.get('call_id'):
            status='unknown' if isinstance(error,(TimeoutError,subprocess.TimeoutExpired,InterruptedError)) else 'failed'
            finish_call(root,receipt['call_id'],status,error=type(error).__name__)
        raise
    if receipt.get('call_id'):finish_call(root,receipt['call_id'],'completed',result={'items':rows})
    return rows

def _normalize(entries,root=ROOT,timeout=600,cancel=None,_receipt=None):
    env={k:v for k,v in os.environ.items() if k not in ('OPENAI_API_KEY','CODEX_API_KEY')}
    options=dict(capture_output=True,text=True,encoding='utf-8',errors='replace',env=env,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    login=subprocess.run([str(CODEX),'login','status'],timeout=30,**options)
    if login.returncode or 'Logged in using ChatGPT' not in login.stdout+login.stderr:raise RuntimeError('existing ChatGPT login required; no paid API fallback')
    runtime=pathlib.Path(root)/'data/weekly-runtime';runtime.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='normalize-',dir=runtime) as tmp:
        directory=pathlib.Path(tmp);(directory/'schema.json').write_text(json.dumps(SCHEMA),encoding='utf-8')
        from easel_workbench.runtime.task_runtime import named_prompt,begin_call
        from easel_workbench.runtime.capability_contracts import resource_text
        prefix,snapshot=named_prompt(root,'news_enhancement',{'operation':'weekly-normalize','items':entries})
        prompt=prefix+'\n\n## 输出合同\n'+resource_text(snapshot,'weekly-normalize.md')
        if _receipt is not None:
            _receipt['call_id']=begin_call(root,'news_enhancement',{'operation':'weekly-normalize','items':entries},prompt,snapshot=snapshot)
        if cancel is None:
            result=subprocess.run(command(directory),input=prompt,timeout=timeout,**options)
        else:
            # Only this newly created readonly child is cancellable; no shared
            # shared creative process or session is ever signalled.
            popts={k:v for k,v in options.items() if k!='capture_output'}
            with subprocess.Popen(command(directory),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,**popts) as child:
                deadline=time.monotonic()+timeout;first=True
                try:
                    while True:
                        if cancel():raise InterruptedError('weekly normalization cancelled')
                        remaining=deadline-time.monotonic()
                        if remaining<=0:raise TimeoutError('bounded normalization deadline')
                        try:
                            stdout,stderr=child.communicate(input=prompt if first else None,timeout=min(3,remaining));break
                        except subprocess.TimeoutExpired:first=False
                    result=subprocess.CompletedProcess(child.args,child.returncode,stdout,stderr)
                except BaseException:
                    child.kill();child.communicate();raise
        answer=directory/'answer.json'
        if result.returncode or not answer.is_file():
            # Persist only allowlisted failure categories, never raw child text,
            # URLs, prompts or credentials. TemporaryDirectory otherwise erases
            # the only upstream evidence before the resumable checkpoint sees it.
            text=(result.stdout+'\n'+result.stderr).lower()
            category=next((label for label,markers in (
                ('workspace-routing-timeout',('workspace routing discovery timed out',)),
                ('network-disconnected',('stream disconnected','error sending request','connection reset','network is unreachable','failed to connect')),
                ('quota',('usage limit','quota exceeded','rate limit')),
                ('authentication',('unauthorized','authentication failed','token expired')),
                ('invalid-schema',('invalid schema','invalid_json_schema')),
            ) if any(marker in text for marker in markers)),'child-failed')
            failure={'at':stamp(),'category':category,'returncode':result.returncode,'answer_exists':answer.is_file(),'entry_ids':[e['id'] for e in entries]}
            atomic(runtime/'failures'/(directory.name+'.json'),failure)
            raise RuntimeError('temporary readonly Codex normalization failed: '+category)
        if answer.stat().st_size>300000:raise ValueError('normalization response too large')
        try:
            rows=json.loads(answer.read_text(encoding='utf-8'))['items']
            validate_result(entries,rows,require_theme=True)
        except (ValueError,KeyError,TypeError,AttributeError) as exc:
            # Retain only validator-owned reasons and exact input identities.
            # Never retain child output, prompts, URLs or generated prose.
            allowed={'normalization completeness mismatch','missing sponsorship classification','missing actual-content theme','missing structured detail','detail must be Chinese','概述必须为12至120字的一句中文','概述须为一个完整中文句子'}
            invalid=[]
            if isinstance(locals().get('rows'),list):
                for entry in entries:
                    matching=[r for r in rows if isinstance(r,dict) and r.get('id')==entry['id']]
                    try:validate_result([entry],matching,require_theme=True)
                    except (ValueError,KeyError,TypeError,AttributeError) as error:
                        invalid.append({'id':entry['id'],'reason':str(error) if str(error) in allowed else 'response-shape'})
            atomic(runtime/'failures'/(directory.name+'.json'),{'at':stamp(),'category':'response-validation','entry_ids':[e['id'] for e in entries],'reason':str(exc) if str(exc) in allowed else 'response-shape','invalid_entries':invalid})
            raise
        return rows

def github(path,raw=False):
    from easel_workbench.collectors import enabled, acquire
    if enabled():
        return acquire('weekly',{'path':path,'raw':raw})
    args=['gh','api',path]
    if raw:args+=['-H','Accept: application/vnd.github.raw+json']
    # Fixed official read-only API path, bounded response and timeout; no credential reads.
    for attempt in range(2):
        p=subprocess.run(args,capture_output=True,timeout=40,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if p.returncode==0:
            if len(p.stdout)>4000000:raise ValueError('GitHub response too large')
            return p.stdout if raw else json.loads(p.stdout)
        if attempt:raise RuntimeError('official GitHub fetch failed')
        time.sleep(1)

def discover(fetch=github):
    repo=fetch(REPO);branch=repo['default_branch'];commit=fetch(REPO+'/commits/'+branch)['sha']
    rows=fetch(REPO+'/contents/docs?ref='+commit)
    docs=[{**r,'number':int(re.fullmatch(r'issue-(\d+)\.md',r['name'])[1]),'commit':commit} for r in rows if re.fullmatch(r'issue-(\d+)\.md',r['name'])]
    if not docs:raise ValueError('official docs directory empty')
    return sorted(docs,key=lambda r:r['number'])

def fetch_issue(doc,fetch=github):
    raw=fetch(REPO+'/contents/'+doc['path']+'?ref='+doc['commit'],raw=True)
    blob=hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
    if blob!=doc['sha']:raise ValueError('GitHub original blob mismatch')
    commits=[]
    for page in range(1,4):
        batch=fetch(REPO+'/commits?path='+doc['path']+'&sha='+doc['commit']+'&per_page=100&page='+str(page));commits+=batch
        if len(batch)<100:break
    else:raise ValueError('publication history exceeds bound')
    if not commits:raise ValueError('official publication date unavailable')
    published=commits[-1]['commit']['author']['date'];dt.datetime.fromisoformat(published.replace('Z','+00:00'))
    parsed=parse(raw,doc['number'])
    return {**parsed,'source':SOURCE,'number':doc['number'],'path':doc['path'],'hash':sha(raw),'git_blob_sha':blob,'commit':doc['commit'],'published_at':published,'published_date':dt.datetime.fromisoformat(published.replace('Z','+00:00')).astimezone(TZ).date().isoformat(),'date_basis':'earliest official GitHub path commit author date','publication_commit':commits[-1]['sha'],'url':'https://github.com/ruanyf/weekly/blob/'+doc['commit']+'/'+doc['path'],'original_markdown':raw.decode('utf-8'),'original_base64':base64.b64encode(raw).decode(),'normalizer_version':VERSION}

class Periodical:
    def __init__(self,store,root=ROOT):self.store=store;self.root=pathlib.Path(root)
    def publish(self,document,normalized,fault=None):
        self.validate_document(document,normalized)
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            return self.publish_on(c,document,normalized,fault=fault)
    @staticmethod
    def validate_document(document,normalized,require_theme=False):
        raw=base64.b64decode(document['original_base64'],validate=True)
        if sha(raw)!=document['hash'] or raw.decode('utf-8')!=document['original_markdown']:raise ValueError('original hash mismatch')
        parsed=parse(raw,document['number'])
        if parsed['items']!=document['items'] or parsed['sections']!=document['sections'] or parsed['title']!=document['title']:raise ValueError('original segmentation changed')
        if document['source']!=SOURCE or document['path']!='docs/issue-'+str(document['number'])+'.md':raise ValueError('source identity mismatch')
        if normalized is not None:validate_result(document['items'],normalized,require_theme=require_theme)
    def publish_on(self,c,document,normalized,fault=None,notify=True):
        """Caller validates first and owns the sole surrounding transaction."""
        raw_only=normalized is None
        normalized=({e['id']:{'summary':'','facts':[],'caveats':[],'advertisement':False} for e in document['items']} if raw_only else validate_result(document['items'],normalized));iid=issue_id(document['path'],document['hash'])
        metadata={k:v for k,v in document.items() if k not in ('original_markdown','original_base64','items')}
        # Enrich existing identities without rewriting original, summary,
        # article IDs, unread state or any version-bound user references.
        for entry in document['items']:
            row=normalized[entry['id']]
            if row.get('theme'):c.execute('INSERT OR REPLACE INTO periodical_themes VALUES(?,?)',(sha(iid+'\0'+entry['id']),row['theme']))
        if c.execute('SELECT 1 FROM periodical_issues WHERE id=?',(iid,)).fetchone():return {'issue_id':iid,'inserted':0,'items':len(document['items']),'deduplicated':True}
        c.execute('INSERT INTO periodical_issues VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(iid,SOURCE,document['number'],document['path'],document['hash'],document['title'],document['published_at'],document['url'],document['original_markdown'],json.dumps(metadata,ensure_ascii=False),len(document['items']),stamp()))
        for entry in document['items']:
            row=normalized[entry['id']];aid=sha(iid+'\0'+entry['id']);url=entry['urls'][0] if entry['urls'] else document['url']
            c.execute('INSERT INTO articles(id,source_job,title,body,url,publisher,published_at,run_at,run,source_event_id) VALUES(?,?,?,?,?,?,?,?,?,?)',(aid,SOURCE,entry['original_title'],entry['original_text'],url,'阮一峰科技爱好者周刊',document['published_at'],stamp(),iid,'issue:'+str(document['number'])+':'+document['hash']+':'+entry['id']))
            c.execute('INSERT INTO periodical_items VALUES(?,?,?,?,?,?,?,?,?,?,?)',(aid,iid,int(entry['id']),entry['section'],entry['original_title'],row['summary'],json.dumps({k:row[k] for k in ('facts','caveats')},ensure_ascii=False),int(entry['advertisement'] or row['advertisement']),entry['start'],entry['end'],json.dumps(entry['urls'],ensure_ascii=False)))
            if fault:fault(entry)
        if c.execute('SELECT count(*) FROM periodical_items WHERE issue_id=?',(iid,)).fetchone()[0]!=len(document['items']):raise ValueError('publication count mismatch')
        from easel_workbench.runtime import notifications as notifications
        if notify:notifications.news(c,iid,SOURCE,len(document['items']))
        return {'issue_id':iid,'inserted':len(document['items']),'items':len(document['items']),'deduplicated':False}
    def listing(self,requested='',section='',theme=''):
        with self.store.connect() as c:
            allrows=[dict(r) for r in c.execute('SELECT id,number,path,hash,title,published_at,url,item_count,metadata FROM periodical_issues WHERE source=? ORDER BY number DESC,rowid DESC',(SOURCE,))]
            current={}
            for row in allrows:current.setdefault(row['number'],row)
            issues=list(current.values());chosen=next((r for r in allrows if r['id']==requested),None) if requested else (issues[0] if issues else None)
            if requested and chosen is None:raise ValueError('published issue does not exist')
            items=[dict(r) for r in c.execute('SELECT p.*,a.unread,a.selected,t.theme FROM periodical_items p JOIN articles a ON a.id=p.article_id LEFT JOIN periodical_themes t ON t.article_id=p.article_id WHERE issue_id=? ORDER BY ordinal',(chosen['id'],))] if chosen else []
            projections={r['article_id']:dict(r) for r in c.execute('SELECT * FROM periodical_enhancements')}
            tasks={r['offset']:dict(r) for r in c.execute('SELECT * FROM periodical_enhancement_tasks WHERE issue_id=?',(chosen['id'],))} if chosen else {}
        for row in items:
            projection=projections.get(row['article_id'])
            task=tasks.get(((row['ordinal']-1)//10)*10) or {}
            if projection:
                row.update({k:projection[k] for k in ('summary','detail','theme')});row['advertisement']=int(row['advertisement'] or projection['advertisement'])
            summary=row['summary'];status='ready' if summary else task.get('status','pending')
            row.update(id=row['article_id'],title=summary or row['original_title'],overview=summary or None,overview_status=status,enhancement_status=status,enhancement_error=task.get('error_type'),detail=json.loads(row['detail']),external_urls=json.loads(row['external_urls']),overview_source='weekly_enhancement' if projection else 'legacy_normalization' if summary else None)
        def brief(row):return {k:row[k] for k in ('id','number','title','published_at','url','hash','path','item_count')}
        themed=bool(items) and all(r.get('theme') for r in items);sections=list(dict.fromkeys(r['section'] for r in items));themes=list(dict.fromkeys(r['theme'] for r in items if r.get('theme')))
        # Old clients sent original columns through the theme parameter.
        if theme and theme not in THEMES and theme in sections and not section:section,theme=theme,''
        visible=[r for r in items if (not section or r['section']==section) and (not theme or r.get('theme')==theme)]
        return {'kind':'periodical','source':SOURCE,'issue':brief(chosen) if chosen else None,'issues':[brief(r) for r in issues],'revisions':[brief(r) for r in allrows if chosen and r['number']==chosen['number']],'items':visible,'themes':themes,'sections':sections,'section':section,'theme':theme,'grouping':'original-section' if section else 'content-theme' if themed else 'original-section','previous_issue':next((r['id'] for r in issues if chosen and r['number']<chosen['number']),None),'next_issue':next((r['id'] for r in reversed(issues) if chosen and r['number']>chosen['number']),None)}
    def original(self,iid):
        with self.store.connect() as c:row=c.execute('SELECT * FROM periodical_issues WHERE id=?',(iid,)).fetchone()
        if row is None:raise ValueError('published issue does not exist')
        return {**dict(row),'metadata':json.loads(row['metadata'])}
    def import_issue(self,document,runner=None):
        directory=self.root/'data/weekly-staging';directory.mkdir(parents=True,exist_ok=True)
        path=directory/(issue_id(document['path'],document['hash'])+'.json')
        stage=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'document':document,'normalized':{},'status':'staging','attempts':0}
        if stage['document']!=document:raise ValueError('staged original changed')
        # Validate original bytes and lossless partition before making anything visible.
        self.validate_document(document,None)
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE');result=self.publish_on(c,document,None)
            for offset in range(0,len(document['items']),10):
                entries=document['items'][offset:offset+10];key=sha(json.dumps([VERSION,entries],ensure_ascii=False,sort_keys=True))
                c.execute("INSERT OR IGNORE INTO periodical_enhancement_tasks VALUES(?,?,?,?,'pending',0,0,NULL,?)",(sha(result['issue_id']+'\0'+str(offset)),result['issue_id'],offset,key,stamp()))
            statuses=[r[0] for r in c.execute('SELECT status FROM periodical_enhancement_tasks WHERE issue_id=?',(result['issue_id'],))]
        enhancement='ready' if statuses and all(s=='ready' for s in statuses) else 'unknown' if 'unknown' in statuses else 'error' if 'error' in statuses else 'pending'
        stage.update(status='published',result=result,enhancement_status=enhancement);stage['attempts']+=1;atomic(path,stage)
        if runner is None:return {**result,'enhancement_status':enhancement}
        # Explicit runner is useful for isolated tests/manual focused processing;
        # collection never waits for it. A failure cannot undo the published original.
        try:
            for offset in range(0,len(document['items']),10):
                entries=document['items'][offset:offset+10]
                if all(e['id'] in stage['normalized'] for e in entries):
                    saved=[stage['normalized'][e['id']] for e in entries];validate_result(entries,saved);self._store_enhancement(document,offset,saved);continue
                rows=(runner or (lambda entries:normalize(entries,self.root)))(entries)
                stage['normalized'].update(validate_result(entries,rows));atomic(path,stage)
                self._store_enhancement(document,offset,rows)
            stage.update(enhancement_status='ready',error_type=None);atomic(path,stage);return result
        except Exception as exc:
            stage.update(enhancement_status='error',error_type=type(exc).__name__);atomic(path,stage);raise

    def _store_enhancement(self,document,offset,rows):
        entries=document['items'][offset:offset+10];result=validate_result(entries,rows);iid=issue_id(document['path'],document['hash'])
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            for entry in entries:
                row=result[entry['id']];aid=sha(iid+'\0'+entry['id']);key=sha(json.dumps([VERSION,entry],ensure_ascii=False,sort_keys=True))
                c.execute('INSERT OR REPLACE INTO periodical_enhancements VALUES(?,?,?,?,?,?,?)',(aid,key,row['summary'],json.dumps({k:row[k] for k in ('facts','caveats')},ensure_ascii=False),int(row['advertisement']),row.get('theme'),stamp()))
                if row.get('theme'):c.execute('INSERT OR REPLACE INTO periodical_themes VALUES(?,?)',(aid,row['theme']))
            c.execute("UPDATE periodical_enhancement_tasks SET status='ready',error_type=NULL,retry_at=0,updated_at=? WHERE issue_id=? AND offset=?",(stamp(),iid,offset))

    def enhance_one(self,runner=None):
        """One bounded near-real-time packet; never changes article identity/unread."""
        with locked(self.root/'data/weekly-enhancement.lock',timeout=.1):
            with self.store.connect() as c:
                # Interrupted read-only invocation has an unknown result. Surface it;
                # do not silently resend an operation whose receipt is unknown.
                c.execute("UPDATE periodical_enhancement_tasks SET status='unknown',error_type='Interrupted',updated_at=? WHERE status='running' AND retry_at<=?",(stamp(),time.time()))
                task=c.execute("SELECT * FROM periodical_enhancement_tasks WHERE status IN ('pending','error') AND attempts<3 AND retry_at<=? ORDER BY rowid LIMIT 1",(time.time(),)).fetchone()
                if not task:return 0
                task=dict(task);original=c.execute('SELECT * FROM periodical_issues WHERE id=?',(task['issue_id'],)).fetchone()
                metadata=json.loads(original['metadata']);raw=original['original_markdown'].encode('utf-8');parsed=parse(raw,original['number'])
                document={**metadata,**parsed,'original_markdown':original['original_markdown'],'original_base64':base64.b64encode(raw).decode()}
                self.validate_document(document,None);entries=document['items'][task['offset']:task['offset']+10]
                if sha(json.dumps([VERSION,entries],ensure_ascii=False,sort_keys=True))!=task['input_hash']:raise ValueError('enhancement frozen input changed')
                # Legacy completed summaries need no additional model call.
                existing=c.execute('SELECT summary FROM periodical_items WHERE issue_id=? ORDER BY ordinal LIMIT ? OFFSET ?',(task['issue_id'],len(entries),task['offset'])).fetchall()
                if existing and all(r['summary'] for r in existing):
                    c.execute("UPDATE periodical_enhancement_tasks SET status='ready',updated_at=? WHERE id=?",(stamp(),task['id']));return 0
                c.execute("UPDATE periodical_enhancement_tasks SET status='running',attempts=attempts+1,retry_at=?,updated_at=? WHERE id=?",(time.time()+600,stamp(),task['id']))
            try:
                if runner:rows=runner(entries)
                else:
                    with locked(self.root/'data/collection/model.lock',timeout=.1):rows=normalize(entries,self.root)
                self._store_enhancement(document,task['offset'],rows)
                return len(entries)
            except TimeoutError:
                with self.store.connect() as c:c.execute("UPDATE periodical_enhancement_tasks SET status='pending',attempts=max(attempts-1,0),retry_at=?,updated_at=? WHERE id=?",(time.time()+20,stamp(),task['id']))
                raise
            except Exception as exc:
                with self.store.connect() as c:c.execute("UPDATE periodical_enhancement_tasks SET status='error',error_type=?,retry_at=?,updated_at=? WHERE id=?",(type(exc).__name__,time.time()+300,stamp(),task['id']))
                raise
    def collect(self,fetch=github,runner=None,limit=3):
        if not 1<=limit<=3:raise ValueError('catchup limit must be 1..3')
        directory=self.root/'data/weekly-staging';directory.mkdir(parents=True,exist_ok=True)
        with locked(self.root/'data/weekly-import.lock',timeout=.1):
            # Finish pending immutable originals first; a failed normalization is
            # retried with its successful batches, never published as a fragment.
            results=[]
            for path in sorted(directory.glob('*.json')):
                stage=json.loads(path.read_text(encoding='utf-8'))
                if stage['status']!='published':
                    results.append(self.import_issue(stage['document'],runner))
                    if len(results)>=limit:return results
            docs=discover(fetch)
            with self.store.connect() as c:known=[dict(r) for r in c.execute('SELECT number,path,hash,metadata FROM periodical_issues WHERE source=? ORDER BY rowid DESC',(SOURCE,))]
            if not known:targets=[docs[-1]] # first import: exactly the actual latest issue
            else:
                maximum=max(r['number'] for r in known);new=[d for d in docs if d['number']>maximum]
                latest={}
                for row in known:latest.setdefault(row['path'],row)
                revisions=[d for d in docs if d['path'] in latest and d['sha']!=json.loads(latest[d['path']]['metadata'])['git_blob_sha']]
                targets=(revisions+new)[:limit-len(results)]
            for doc in targets:results.append(self.import_issue(fetch_issue(doc,fetch),runner))
            return results

def detail(c,aid):
    row=c.execute('SELECT p.*,t.theme,i.number,i.path,i.hash,i.title AS issue_title,i.published_at,i.url AS issue_url FROM periodical_items p JOIN periodical_issues i ON i.id=p.issue_id LEFT JOIN periodical_themes t ON t.article_id=p.article_id WHERE p.article_id=?',(aid,)).fetchone()
    if not row:return None
    value=dict(row);projection=c.execute('SELECT * FROM periodical_enhancements WHERE article_id=?',(aid,)).fetchone()
    if projection:value.update({k:projection[k] for k in ('summary','detail','theme')})
    task=c.execute('SELECT status,error_type FROM periodical_enhancement_tasks WHERE issue_id=? AND offset=?',(row['issue_id'],((row['ordinal']-1)//10)*10)).fetchone()
    value.update(overview_status='ready' if value['summary'] else (task['status'] if task else 'pending'),enhancement_error=task['error_type'] if task else None)
    return {**value,'detail':json.loads(value['detail']),'external_urls':json.loads(value['external_urls'])}

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int,default=3);args=parser.parse_args()
    result=Periodical(Store()).collect(limit=args.limit);print(json.dumps({'source':SOURCE,'results':result},ensure_ascii=False))
if __name__=='__main__':main()
