"""Authenticated, receipt-first adapter for private production evidence."""
from __future__ import annotations
import asyncio
import hashlib
import json
import re
from fastapi.responses import JSONResponse
from easel_workbench.contracts.values import ident
from easel_workbench.runtime.desk import stamp

PREFIX='/api/production-insights'
VERSION=re.compile(PREFIX+r'/works/([A-Za-z0-9_-]{1,160})/versions/([A-Za-z0-9_-]{1,160})/(review|decisions|templates|publication|sync)')
MASTER=re.compile(PREFIX+r'/skills/(oil-pig-poster|oil-pig-article)/master')
SOURCE=re.compile(PREFIX+r'/works/([A-Za-z0-9_-]{1,160})/versions/([A-Za-z0-9_-]{1,160})/sources/([A-Za-z0-9_.:-]{1,240})')
OP=re.compile(PREFIX+r'/operations/([A-Za-z0-9_.-]{1,128})')
TEMPLATE=re.compile(PREFIX+r'/templates/([A-Za-z0-9_-]{1,160})')


def initialize(box):
    with box.store.connect() as c:
        c.execute('CREATE TABLE IF NOT EXISTS production_insight_http_operations(id TEXT PRIMARY KEY,signature TEXT NOT NULL,status TEXT NOT NULL,document TEXT NOT NULL)')
        # Created once by the exclusively owned server role. An old action is
        # reconciled from its service receipt, never dispatched on startup.
        for row in c.execute("SELECT id,document FROM production_insight_http_operations WHERE status='running'").fetchall():
            doc=json.loads(row[1]);doc.update(status='unknown',updated_at=stamp())
            c.execute('UPDATE production_insight_http_operations SET status=?,document=? WHERE id=?',('unknown',json.dumps(doc),row[0]))


def response(value,status=200):return JSONResponse(value,status_code=status,headers={'Cache-Control':'no-store'})


def receipt(box,hub,operation):
    with box.store.connect() as c:row=c.execute('SELECT document FROM production_insight_http_operations WHERE id=?',(operation,)).fetchone()
    if not row:return {'id':operation,'state':'unavailable'}
    doc=json.loads(row[0])
    if doc['status'] not in ('completed','rejected'):
        for owner in (hub.reviews,hub.templates,hub.metrics):
            recover=getattr(owner,'operation_result',None)
            result=recover(operation) if recover else None
            if isinstance(result,dict) and result.get('status') in ('reserved','running','queued'):continue
            if result is not None:
                if owner is hub.templates:hub.reviews.mark_template_applied(result)
                doc.update(status='completed',result=result)
                with box.store.connect() as c:c.execute('UPDATE production_insight_http_operations SET status=?,document=? WHERE id=?',('completed',json.dumps(doc,ensure_ascii=False),operation))
                break
    return {'id':operation,'state':doc['status'] if doc['status'] in ('completed','rejected') else 'unavailable',**({'result':doc['result']} if 'result' in doc else {})}


def execute(box,hub,operation,path,value,wid,vid,action):
    signature=hashlib.sha256(json.dumps([path,value],ensure_ascii=False,sort_keys=True).encode()).hexdigest()
    with box.store.connect() as c:
        c.execute('BEGIN IMMEDIATE')
        old=c.execute('SELECT signature,document FROM production_insight_http_operations WHERE id=?',(operation,)).fetchone()
        if old:
            if old[0]!=signature:raise ValueError('同一操作不能更换版本或输入')
            doc=json.loads(old[1])
            return doc.get('result'),doc['status']
        doc={'id':operation,'path':path,'status':'running','created_at':stamp()}
        c.execute('INSERT INTO production_insight_http_operations VALUES(?,?,?,?)',(operation,signature,'running',json.dumps(doc)))
    try:
        if action=='decisions':result=hub.reviews.decide(wid,vid,value)
        elif action=='templates':
            result=hub.templates.create(wid,vid,value)
            hub.reviews.mark_template_applied(result)
        elif action=='publication':result=hub.metrics.bind(wid,vid,value)
        elif action=='sync':
            # Verify this precise version before requesting read-only statistics.
            hub.metrics.view(wid,vid)
            result=hub.metrics.sync(value)
        else:raise ValueError('未知复盘操作')
        state='completed'
    except ValueError as exc:result={'error':str(exc)};state='rejected'
    except Exception:
        with box.store.connect() as c:
            doc.update(status='unknown',updated_at=stamp())
            c.execute('UPDATE production_insight_http_operations SET status=?,document=? WHERE id=?',('unknown',json.dumps(doc),operation))
        raise
    doc.update(status=state,result=result,updated_at=stamp())
    with box.store.connect() as c:c.execute('UPDATE production_insight_http_operations SET status=?,document=? WHERE id=?',(state,json.dumps(doc,ensure_ascii=False),operation))
    return result,state


async def handle(box,path,request,value=None):
    from easel_workbench.features.production_insights.service import service
    hub=service(box)
    match=VERSION.fullmatch(path)
    if request.method in ('GET','HEAD'):
        if template:=TEMPLATE.fullmatch(path):
            q=request.query_params
            if set(q)-{'profile_id','format','revision'} or any(len(q.getlist(key))!=1 for key in q):raise ValueError('模板详情参数无效')
            return response(await asyncio.to_thread(hub.templates.get,template[1],q.get('profile_id'),q.get('format'),q.get('revision')))
        if source:=SOURCE.fullmatch(path):return response(await asyncio.to_thread(hub.reviews.source,*source.groups()))
        if match:
            wid,vid,action=match.groups()
            if action!='review':return response({'error':'method rejected'},405)
            return response(await asyncio.to_thread(hub.view,wid,vid))
        if master:=MASTER.fullmatch(path):return response(await asyncio.to_thread(hub.reviews.master,master[1]))
        if op:=OP.fullmatch(path):return response(await asyncio.to_thread(receipt,box,hub,op[1]))
        return response({'error':'not found'},404)
    if request.method!='POST' or not match or match[3]=='review':return response({'error':'method rejected'},405)
    operation=ident(request.headers.get('x-operation-id'))
    if value.get('operation_id') not in (None,operation) or value.get('id') not in (None,operation):return response({'error':'操作身份不一致'},409)
    value={key:item for key,item in value.items() if key!='id'}
    value['operation_id']=operation;wid,vid,action=match.groups()
    result,state=await asyncio.shield(asyncio.to_thread(execute,box,hub,operation,path,value,wid,vid,action))
    if state in ('running','unknown'):
        return response({'protocol_version':2,'operation_id':operation,'operation_state':'accepted'},202)
    return response(result,400 if state=='rejected' else 200)
