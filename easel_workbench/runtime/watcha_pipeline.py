"""Project Watcha pipeline: bounded fetch, model annotations and exact persistence."""
import contextlib
import datetime as dt
import hashlib
import ipaddress
import json
import os
import pathlib
import socket
import urllib.parse
import urllib.request

from easel_workbench.runtime import watcha_collect as wc
from easel_workbench.runtime.feedback_ledger import Ledger,atomic,locked

from easel_workbench.runtime.project_paths import ROOT


def recent_context(root=ROOT,hours=48):
    cutoff=dt.datetime.now(wc.UTC)-dt.timedelta(hours=hours);rows=[]
    for folder in (root/'data/canonical').glob('*'):
        for path in sorted(folder.glob('*.json'),key=lambda p:p.stat().st_mtime,reverse=True)[:16]:
            try:
                d=json.loads(path.read_text(encoding='utf-8'));when=wc.parsed(d.get('run_at'))
                if not when or when<cutoff:continue
                rows.extend({'source_job':d['source_job'],'title':a['title'],'body':a['body'][:550],
                             'url':a['url'],'event_id':a.get('source_event_id')} for a in d['articles'])
            except (ValueError,OSError,KeyError):continue
    # Exact stored event IDs/URLs provide context; semantic dedup remains editorial.
    unique={}
    for row in rows:unique[(row['source_job'],row['url'],row['title'])]=row
    return list(unique.values())[-120:]


def editorial_prompt(candidates,snapshot,recent,root=ROOT):
    from easel_workbench.runtime.task_runtime import registry,runtime_box
    from easel_workbench.runtime.capability_contracts import resource_text
    frozen=registry(runtime_box(root)).resolve(task='news_enhancement')
    contract=resource_text(frozen,'watcha-editorial.md')
    return contract.replace('{profile_json}',json.dumps(snapshot,ensure_ascii=False)).replace('{recent_json}',json.dumps(recent,ensure_ascii=False)).replace('{candidates_json}',json.dumps(candidates,ensure_ascii=False))


def annotate(candidates,snapshot,recent,cfg,folder):
    from easel_workbench.runtime.collection_model import invoke
    root=pathlib.Path(cfg['project_root'])
    return invoke(editorial_prompt(candidates,{k:v for k,v in snapshot.items() if k!='read_at'},recent,root),{},folder,root=root)


def ranked(candidates,result,skill,snapshot,selection_limit=10):
    annotations=result.get('annotations')
    if not isinstance(annotations,list) or len(annotations)!=len(candidates):raise ValueError('Incomplete candidate annotations')
    available={c['event_id']:c for c in candidates};seen=set();rows=[]
    rules=snapshot['documents']['profile-current.md']
    for a in annotations:
        eid=a.get('event_id')
        if eid not in available or eid in seen:raise ValueError('Unknown or repeated annotation identity')
        seen.add(eid)
        for k in ('supported','fresh','substantive'):
            if type(a.get(k)) is not bool:raise ValueError('Quality gates require booleans')
        ids=a.get('rule_ids')
        if not isinstance(ids,list) or any(not isinstance(r,str) or r not in rules for r in ids):raise ValueError('Unknown interest rule')
        for k,limit in [('title',80),('summary',200),('reason',180),('match_reason',500),('interesting_reason',500),('major_reason',500)]:
            if not isinstance(a.get(k),str) or len(a[k])>limit:raise ValueError('Invalid editorial field '+k)
        if not a['title'].strip() or not a['summary'].strip() or not a['reason'].strip():raise ValueError('Empty editorial explanation')
        if a.get('duplicate_of') is not None:
            if not isinstance(a['duplicate_of'],str) or not a['duplicate_of'].startswith(('http://','https://')):raise ValueError('Invalid duplicate evidence')
            a=a|{'fresh':False}
        rows.append(a|{'entity':available[eid]['product_id']})
    from easel_workbench.runtime.collection_adapters.rank_candidates import rank
    return rank(rows,selection_limit)


def official_check(url):
    """At most three public HTTPS reads; a readable page is not a verified product claim."""
    try:
        p=urllib.parse.urlsplit(url)
        if p.scheme!='https' or not p.hostname or p.username or p.password or p.port not in (None,443):raise ValueError('Unsupported official URL')
        addresses={x[4][0] for x in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)}
        if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):raise ValueError('Nonpublic official URL')
        opener=urllib.request.build_opener(wc.NoRedirect())
        req=urllib.request.Request(url,headers={'User-Agent':'AINewsDesk/1.0'})
        with opener.open(req,timeout=10) as response:
            response.read(200_001)
            return {'url':url,'readable':response.status==200,'claims_verified':False}
    except (ValueError,OSError):return {'url':url,'readable':False,'claims_verified':False}


def document(job,candidates,ranking,snapshot,coverage,checks,now=None):
    from easel_workbench.runtime.news_overviews import reading_summary
    now=now or dt.datetime.now(wc.UTC);by_id={c['event_id']:c for c in candidates};articles=[];lines=['观猹｜产品新发现与更新']
    for index,a in enumerate(ranking['selected'],1):
        source=by_id[a['event_id']]
        label='版本更新日志' if source['kind']=='update' else '产品新发现（非首发声明）'
        when=source['source_time_raw'] or '来源未提供'
        body=f"{a['summary']}\n类型：{label}\n来源：观猹产品介绍/用户提交，未独立核验原始产品能力。\n来源记录时间：{when}；发现时间：{wc.iso(now)}\n入选理由（编辑判断）：{a['reason']}\n事件ID：{source['event_id']}"
        if source['website_url']:body+='\n产品官网：'+source['website_url']
        if source['event_id'] in checks:
            body+='\n官网读取：'+('可访问，未逐项核验能力声明。' if checks[source['event_id']]['readable'] else '本轮未能读取，仍仅依据观猹。')
        articles.append({'title':a['title'],'body':body,'url':source['url'],'publisher':'观猹',
                         'published_at':None,'published_at_raw':None,'source_recorded_at':source['source_time_raw'],
                         'source_event_id':source['event_id'],'reading_summary':reading_summary(a.get('reading_summary'))})
        lines.append(f"{index}. {a['title']}\n{body}\n{source['url']}")
    lines.append('\n---\n兴趣画像版本：'+snapshot['version']+'\n来源覆盖：'+coverage['coverage']+'；有界采集，不代表全站穷尽。\n'+json.dumps({'errors':coverage['errors'],'page_caps':coverage['page_caps'],'backlog':coverage['backlog']},ensure_ascii=False))
    final='\n\n'.join(lines)
    return {'schema_version':1,'source_job':job,'feed_id':'watcha','run_id':'watcha-'+hashlib.sha256(final.encode()).hexdigest(),
            'run_at':wc.iso(now),'final_text':final,'articles':articles}


def publish_exact(doc,store,root=ROOT,health=None):
    from easel_workbench.runtime import desk as desk
    from easel_workbench.runtime.collection_health import site_health
    health=health or site_health
    if not health():raise RuntimeError('Reading desk unavailable; no delivery acknowledgment')
    receipt=desk.save_digest(doc,store,root=root)
    expected=hashlib.sha256(doc['final_text'].encode()).hexdigest()
    with store.connect() as c:
        row=c.execute('select hash,final_text from runs where id=?',(receipt['run'],)).fetchone()
        ids={r[0] for r in c.execute('select article_id from provenance where run=?',(receipt['run'],))}
    if not row or row['hash']!=expected or row['final_text']!=doc['final_text'] or ids!={desk.article_identity(doc['source_job'],a) for a in doc['articles']}:raise RuntimeError('Exact website readback failed')
    canonical=root/'data/canonical'/doc['source_job']/(receipt['run']+'.json')
    if json.loads(canonical.read_text(encoding='utf-8'))!=doc or not health():raise RuntimeError('Canonical/health readback failed')
    from easel_workbench.runtime.news_overviews import record_upstream
    record_upstream(store,root,doc)
    return receipt


def audit(skill,run,profile,coverage,ranking):
    record={'source':'watcha','run_id':run,'profile_version':profile['version'],
            'candidates':coverage['pending_total'],'coverage':{k:v for k,v in coverage.items() if k!='candidates'},
            'selected':ranking['selected'],'omitted':ranking['omitted'],'verification':'Watcha attributed; official readability is not claim verification'}
    with locked(skill/'.feedback-state/selection-audit.lock'):
        with (skill/'references/selection-audit.md').open('a',encoding='utf-8') as f:
            f.write('\n\n## Watcha '+run+'\n'+json.dumps(record,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())


def run(cfg,*,dry_run=False,interpreter=annotate,client=None,progress=None,task_dir=None,resume=False,force=False):
    from easel_workbench.runtime import desk as desk
    skill=pathlib.Path(cfg['profile_dir'])
    root=pathlib.Path(cfg['project_root']);state=pathlib.Path(cfg['state_dir'])
    state.mkdir(parents=True,exist_ok=True)
    with locked(state/'pipeline.lock',timeout=2):
        queue=wc.Queue(state/'queue.sqlite');store=desk.Store(root/'data/desk.sqlite');prepared=state/'prepared.json'
        pending_context=state/'pending-task-context.json';recovered=None;recovered_selected=0
        if prepared.exists() and not dry_run:
            if progress:progress('persisting',{})
            intent=json.loads(prepared.read_text(encoding='utf-8'))
            recovered=publish_exact(intent['document'],store,root=root)
            queue.ack(intent['selected_ids'],'site-run:'+recovered['run'])
            with queue.connect() as c:
                for eid,value in intent.get('review_hashes',{}).items():c.execute('update events set review_hash=? where id=?',(value,eid))
            recovered_selected=len(intent['selected_ids']);prepared.unlink()
            if progress:progress('persisting',{'fetched':recovered_selected,'selected':recovered_selected,'inserted':recovered.get('inserted',0)})
            continuation=resume and pending_context.exists() and json.loads(pending_context.read_text(encoding='utf-8'))['coverage'].get('errors')
            if pending_context.exists():pending_context.unlink()
            if not force and not continuation:return {'status':'recovered','receipt':recovered,'selected':recovered_selected}
        pending=queue.pending()
        task_root=pathlib.Path(task_dir) if task_dir is not None else None
        folder=task_root
        active=task_root/'watcha-active-stage.json' if task_root is not None else None
        if resume and active is not None and active.exists():
            folder=(task_root/json.loads(active.read_text(encoding='utf-8'))['relative']).resolve()
            if not folder.is_relative_to(task_root.resolve()):raise ValueError('Watcha recovery stage outside task')
        budget_path=task_root/'watcha-selection-budget.json' if task_root is not None else None
        selected_before=set(json.loads(budget_path.read_text(encoding='utf-8'))['selected_ids']) if budget_path is not None and budget_path.exists() else set()
        if folder is not None and (folder/'ranking.json').exists():selected_before.update(row['event_id'] for row in json.loads((folder/'ranking.json').read_text(encoding='utf-8'))['selected'])
        context_path=folder/'watcha-context.json' if folder is not None else None
        context=None
        if resume and context_path is not None and context_path.exists():context=json.loads(context_path.read_text(encoding='utf-8'))
        elif not force and pending_context.exists() and dt.datetime.now().timestamp()-pending_context.stat().st_mtime<72*3600:context=json.loads(pending_context.read_text(encoding='utf-8'))
        plan_path=folder/'watcha-repair-plan.json' if folder is not None else None
        plan=json.loads(plan_path.read_text(encoding='utf-8')) if plan_path is not None and plan_path.exists() else None
        retry_coverage=plan['coverage'] if plan is not None and context is None else None
        exclude_ids=set(plan['exclude_ids']) if plan is not None and context is None else set()
        if context is not None and resume and context['coverage'].get('errors') and (folder/'ranking.json').exists():
            prior_ranking=json.loads((folder/'ranking.json').read_text(encoding='utf-8'))
            with queue.connect() as c:pending_ids={row[0] for row in c.execute("SELECT id FROM events WHERE status='pending'")}
            if not any(row['event_id'] in pending_ids for row in prior_ranking['selected']):
                retry_coverage=context['coverage'];exclude_ids={row['event_id'] for row in context['candidates']}
                folder=folder/'coverage-retry';folder.mkdir(parents=True,exist_ok=True)
                atomic(folder/'watcha-repair-plan.json',{'coverage':retry_coverage,'exclude_ids':sorted(exclude_ids)})
                atomic(active,{'relative':folder.relative_to(task_root).as_posix()})
                context_path=folder/'watcha-context.json';context=None
        selection_limit=max(0,10-len(selected_before)) if retry_coverage is not None or active is not None and active.exists() else 10
        if context is not None:
            coverage=context['coverage'];profile=context['profile'];todo=context['todo'];candidates=context['candidates'];recent=context['recent']
        else:
            if progress:progress('fetching',{})
            coverage=wc.collect(queue,client or wc.Client(limit=27),retry_coverage=retry_coverage) if retry_coverage is not None else wc.collect(queue,client or wc.Client(limit=27))
            atomic(state/'last-collection.json',coverage)
            if progress:progress('fetching',{'fetched':len(coverage.get('candidates',[]))})
            if dry_run:return coverage
            profile=Ledger(skill).snapshot(cfg['job_id']);pending=queue.pending()
            def current_review_hash(row):return hashlib.sha256((row['hash']+profile['version']).encode()).hexdigest()
            todo=[dict(row) for row in pending if row['id'] not in exclude_ids and row['review_hash']!=current_review_hash(row)][:30]
            if not todo or selection_limit==0:
                if coverage['errors']:
                    if folder is not None:
                        folder.mkdir(parents=True,exist_ok=True)
                        atomic(folder/'watcha-context.json',{'coverage':coverage,'profile':profile,'todo':[],'candidates':[],'recent':recent_context(root)})
                        atomic(folder/'ranking.json',{'selected':[],'omitted':[]})
                    raise RuntimeError('Watcha partial collection; missing reads remain queued')
                return {'status':'no_new_candidates' if not todo else 'selection_cap_reached','pending':len(pending),'model_calls':0,'receipt':recovered,'selected':recovered_selected}
            candidates=[json.loads(row['payload']) for row in todo]
            recent=recent_context(root)
            context={'coverage':coverage,'profile':profile,'todo':todo,'candidates':candidates,'recent':recent}
        if folder is None:folder=state/'runs'/dt.datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        folder.mkdir(parents=True,exist_ok=True)
        atomic(folder/'watcha-context.json',context);atomic(pending_context,context)
        atomic(folder/'input.json',{'candidates':candidates,'profile_version':profile['version'],'coverage':coverage})
        if progress:progress('screening',{'fetched':len(candidates)})
        result=interpreter(candidates,profile,recent,cfg,folder)
        ranking=ranked(candidates,result,skill,profile,selection_limit)
        # Validate the frozen full model receipt before suppressing entries that
        # another completed attempt already delivered or that the queue expired.
        with queue.connect() as c:pending_ids={row['id'] for row in c.execute("SELECT id FROM events WHERE status='pending'")}
        ranking['selected']=[row for row in ranking['selected'] if row['event_id'] in pending_ids]
        atomic(folder/'ranking.json',ranking)
        if budget_path is not None:
            selected_before.update(row['event_id'] for row in ranking['selected']);atomic(budget_path,{'selected_ids':sorted(selected_before)})
        deferred={row['event_id'] for row in ranking['omitted'] if row['reason']=='capacity/diversity'}
        review_hashes={row['id']:hashlib.sha256((row['hash']+profile['version']).encode()).hexdigest() for row in todo if row['id'] not in deferred}
        checks={c['event_id']:official_check(c.get('website_url','')) for c in [next(c for c in candidates if c['event_id']==a['event_id']) for a in ranking['selected'][:3]] if c.get('website_url')}
        doc=document(cfg['job_id'],candidates,ranking,profile,coverage,checks)
        audit(skill,doc['run_id'],profile,coverage,ranking)
        receipt=None
        if doc['articles']:
            atomic(prepared,{'document':doc,'selected_ids':[a['source_event_id'] for a in doc['articles']],'review_hashes':review_hashes})
            if progress:progress('persisting',{'selected':len(doc['articles'])+recovered_selected})
            receipt=publish_exact(doc,store,root=root)
            queue.ack([a['source_event_id'] for a in doc['articles']],'site-run:'+receipt['run']);prepared.unlink()
        with queue.connect() as c:
            for eid,value in review_hashes.items():c.execute('update events set review_hash=? where id=?',(value,eid))
        if pending_context.exists():pending_context.unlink()
        summary={'status':'published' if receipt or recovered else 'no_qualified_events','selected':len(doc['articles'])+recovered_selected,
                 'model_calls':1,'profile_version':profile['version'],'receipt':receipt or recovered,'coverage':coverage['coverage'],'diagnostic':str(folder),
                 'inserted':(receipt or {}).get('inserted',0)+(recovered or {}).get('inserted',0)}
        atomic(state/'last-result.json',summary);return summary

