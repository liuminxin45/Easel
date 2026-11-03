"""Owner-authenticated HTTP ports for Easel chat and project builtin skills.

The host authenticates and checks CSRF before entering these ports. SSE only
tails accepted receipts; reconnects never create another native turn.
"""
from __future__ import annotations

import json
import re
import asyncio
import contextlib

from fastapi.responses import JSONResponse, StreamingResponse
from easel.web_services.concurrency import run_sync

from easel_workbench.features.conversations.receipts import ChatConflict, identity
from easel_workbench.contracts.production import PlanConflict


def response(value, status=200, *, trace=None):
    headers={'Cache-Control':'no-store'}
    if isinstance(value,dict) and value.get('protocol_version')==2:
        headers['X-Workbench-Operation-Protocol']='2'
        if trace:value={**value,'trace_id':trace}
    return JSONResponse(value, status_code=status, headers=headers)


def stream(service, turn_id, after=0, accepted=False,authenticated=None):
    async def body():
        allowed=lambda:authenticated is None or bool(authenticated())
        if not allowed():return
        events=service.events(turn_id,after).__aiter__();pending=None
        try:
            if accepted:yield 'event: accepted\ndata: '+json.dumps({'turnId':turn_id})+'\n\n'
            emitted_done=False
            while allowed():
                if pending is None:pending=asyncio.create_task(anext(events))
                ready,_=await asyncio.wait((pending,),timeout=1)
                if not allowed():return
                if not ready:
                    yield ': keep-alive\n\n'
                    continue
                try:event=pending.result()
                except StopAsyncIteration:break
                finally:pending=None
                data=event['data']
                if event['event'] in ('question','question_closed') and isinstance(data,str):
                    try:data=json.loads(data)
                    except ValueError:pass
                yield 'id: '+str(event['id'])+'\nevent: '+event['event']+'\ndata: '+json.dumps(data,ensure_ascii=False)+'\n\n'
                emitted_done=event['event']=='done'
            if not emitted_done and allowed():
                turn=await run_sync(service.get_turn,turn_id)
                if turn['status'] in ('completed','stopped','failed','unknown'):
                    yield 'event: done\ndata: '+json.dumps({'sessionKey':turn['session_id']})+'\n\n'
        finally:
            if pending:
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError,StopAsyncIteration):await pending
            await events.aclose()
    return StreamingResponse(body(),media_type='text/event-stream',headers={
        'Cache-Control':'no-store, no-transform','X-Accel-Buffering':'no','Content-Encoding':'identity'})


async def handle(service,business,path,request,value=None,*,authenticated=None,serve_file=None,admissions=None):
    method=request.method
    get=method in ('GET','HEAD')
    if not (path.startswith('/api/chat/') or path=='/api/skills' or path.startswith('/api/skill/')):
        return None
    try:
        if path=='/api/chat/submit' and method=='POST':
            if admissions is None:return response({'error':'接收端口未连接'},503)
            return response(await admissions.receive(value),202)
        match=re.fullmatch(r'/api/chat/products/([A-Za-z0-9_-]+)(?:/files/([a-f0-9]{64}))?',path)
        if match and get:
            from easel_workbench.features.works.products import ChatProducts
            products=ChatProducts(root=business.root,store=business.store,chat=service,work_store=business.box)
            if match[2]:
                if serve_file is None:raise ValueError('文件响应端口未连接')
                metadata,file=await asyncio.to_thread(products.file,match[1],match[2])
                return serve_file(metadata,file,request.headers,request.query_params.get('download')=='1')
            return response(await asyncio.to_thread(products.describe,match[1]))
        if path=='/api/skills' and get:return response(await asyncio.to_thread(business.skills))
        if path=='/api/chat/artifacts' and get:return response(await run_sync(business.upstream.library))
        match=re.fullmatch(r'/api/skill/([a-z0-9-]+)',path)
        if match and get:return response(await asyncio.to_thread(business.skill,match[1]))
        if path=='/api/chat/sessions':
            if get:
                return response(await run_sync(service.list_sessions,summaries=True))
            action=value.get('action','create')
            if action=='create':
                def validate_profile(profile_id):
                    profile=business.creator.detail('profile',profile_id)
                    if not profile.get('active',True):raise ValueError('创作画像已停用')
                    return profile
                if request.headers.get('x-workbench-operation-protocol')=='2':
                    operation=identity(value.get('operation_id') or value.get('id'))
                    if request.headers.getlist('x-operation-id')!=[operation]:raise ValueError('新建对话操作身份与请求不一致')
                    receipt=await service.session_creations.receive(value,validate_profile)
                    state=receipt['operation_state']
                    return response(receipt,202 if state in ('accepted','running') else 409 if state in ('rejected','sealed_not_accepted') else 200,
                                    trace=getattr(request.state,'workbench_trace',None))
                def create():
                    operation=identity(value.get('operation_id') or value.get('id'))
                    existing=service.session_creations.inspect(operation)
                    if existing['operation_state']!='completed':validate_profile(value.get('profile_id') or 'oil-pig')
                    return service.create_session(value)
                return response(await run_sync(create))
            sid=identity(value.get('session_id') or value.get('sessionId'))
            if action=='rename':return response(await run_sync(service.rename_session,sid,value))
            if action=='auto-title':return response(await run_sync(service._command,action,value,sid))
            if action=='archive':return response(await run_sync(service.archive_session,sid,value))
            raise ValueError('不支持的对话操作')
        match=re.fullmatch(r'/api/chat/sessions/operations/([A-Za-z0-9_.-]+)/resolve',path)
        if match and method=='POST':
            control=identity(value.get('id'))
            if request.headers.getlist('x-operation-id')!=[control]:raise ValueError('核对操作缺少匹配身份')
            return response(await run_sync(service.session_creations.resolve,match[1],value),trace=getattr(request.state,'workbench_trace',None))
        match=re.fullmatch(r'/api/chat/sessions/([A-Za-z0-9_.-]+)',path)
        if match and get:
            if admissions is None:return response(await run_sync(business.history,match[1]))
            raw_limit=request.query_params.get('limit')
            # Existing integrations retain the complete wire response. The
            # mobile view explicitly opts into bounded windows and cursors.
            if raw_limit is None:return response(await run_sync(admissions.history,match[1]))
            try:limit=int(raw_limit)
            except ValueError:raise ValueError('历史分页数量无效') from None
            return response(await run_sync(admissions.history,match[1],limit=limit,before=request.query_params.get('before')))
        if path=='/api/chat/plan' and method=='POST':return response(await run_sync(business.plan,value))
        if path=='/api/chat/stream' and method=='POST':
            prepared=await asyncio.to_thread(business.prepare,value)
            if authenticated is not None and not authenticated():return response({'error':'authentication_required'},401)
            turn=prepared.get('receipt') or await service.submit(value,**prepared)
            return stream(service,turn['id'],accepted=True,authenticated=authenticated)
        match=re.fullmatch(r'/api/chat/jobs/([A-Za-z0-9_.-]+)/stream',path)
        if match and get:
            source=service
            try:turn=await run_sync(service.get_turn,match[1])
            except ValueError:
                if admissions is None:raise
                turn=await run_sync(admissions.get_turn,match[1]);source=admissions
            if request.query_params.get('sessionId',turn['session_id'])!=turn['session_id']:
                raise ValueError('回合与会话不一致')
            after=int(request.query_params.get('after',request.headers.get('last-event-id','0')))
            if not 0<=after<=100000000:raise ValueError('事件位置无效')
            return stream(source,match[1],after,True,authenticated)
        match=re.fullmatch(r'/api/chat/last/([A-Za-z0-9_.-]+)',path)
        if match and get:
            turn=request.query_params.get('turn_id')
            result=await run_sync(service.last,match[1])
            if turn:
                try:current=await run_sync(service.get_turn,turn)
                except ValueError:
                    if admissions is None:raise
                    current=await run_sync(admissions.get_turn,turn)
                if current['session_id']!=match[1]:raise ValueError('回合与会话不一致')
                result={**current,'status':'done' if current['status'] in ('completed','stopped','failed','unknown') else 'running',
                        'execution_status':current['status'],'text':current.get('output',''),'turn_id':current['id'],
                        'clean_end':current['status']=='completed','stop_reason':None if current['status']=='completed' else current['status']}
            return response(result)
        if path=='/api/chat/stop' and method=='POST':
            sid=identity(value.get('sessionId') or value.get('session_id'));tid=value.get('turnId') or value.get('turn_id')
            if admissions is not None and tid:
                with service.store.connect() as c:pending=admissions._row(c,tid)
                if pending:return response(await admissions.stop(sid,tid))
            return response(await service.stop(sid,tid))
        if path=='/api/chat/question/answer' and method=='POST':
            qid=identity(value.get('id') or value.get('questionId'))
            record=service._questions.get(qid)
            sid=value.get('sessionId') or value.get('session_id') or (record or {}).get('session_id')
            return response(service.answer(qid,value.get('answers'),sid,value.get('turnId')))
        if path=='/api/chat/question/status' and method=='POST':
            ids=value.get('questionIds',[])
            if not isinstance(ids,list) or len(ids)>100:raise ValueError('问题列表无效')
            return response({'questions':{identity(qid):service.question_status(qid,value.get('sessionId'),value.get('turnId')) for qid in ids}})
        return response({'error':'对话接口或方法不存在'},404)
    except (ChatConflict,PlanConflict) as exc:return response({'error':str(exc)},409)
    except (ValueError,TypeError,KeyError) as exc:return response({'error':str(exc)},400)
