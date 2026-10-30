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

from .chat import ChatConflict, identity
from .chat_business import PlanConflict


def response(value, status=200):
    return JSONResponse(value, status_code=status, headers={'Cache-Control':'no-store'})


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
                turn=service.get_turn(turn_id)
                if turn['status'] in ('completed','stopped','failed','unknown'):
                    yield 'event: done\ndata: '+json.dumps({'sessionKey':turn['session_id']})+'\n\n'
        finally:
            if pending:
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError,StopAsyncIteration):await pending
            await events.aclose()
    return StreamingResponse(body(),media_type='text/event-stream',headers={
        'Cache-Control':'no-store, no-transform','X-Accel-Buffering':'no','Content-Encoding':'identity'})


async def handle(service,business,path,request,value=None,*,authenticated=None):
    method=request.method
    get=method in ('GET','HEAD')
    if not (path.startswith('/api/chat/') or path=='/api/skills' or path.startswith('/api/skill/')):
        return None
    try:
        if path=='/api/skills' and get:return response(business.skills())
        match=re.fullmatch(r'/api/skill/([a-z0-9-]+)',path)
        if match and get:return response(business.skill(match[1]))
        if path=='/api/chat/sessions':
            if get:
                result=service.list_sessions()
                for session in result['sessions']:
                    history=service.history(session['id'])
                    session.update(message_count=len(history['session']['messages']),linked_works=history['linked_works'])
                return response(result)
            action=value.get('action','create')
            if action=='create':
                profile=business.creator.detail('profile',value.get('profile_id') or 'oil-pig')
                if not profile.get('active',True):raise ValueError('创作画像已停用')
                return response(service.create_session(value))
            sid=identity(value.get('session_id') or value.get('sessionId'))
            if action=='rename':return response(service.rename_session(sid,value))
            if action=='auto-title':return response(service._command(action,value,sid))
            if action=='archive':return response(service.archive_session(sid,value))
            raise ValueError('不支持的对话操作')
        match=re.fullmatch(r'/api/chat/sessions/([A-Za-z0-9_.-]+)',path)
        if match and get:return response(business.history(match[1]))
        if path=='/api/chat/plan' and method=='POST':return response(business.plan(value))
        if path=='/api/chat/stream' and method=='POST':
            prepared=business.prepare(value)
            if authenticated is not None and not authenticated():return response({'error':'authentication_required'},401)
            turn=prepared.get('receipt') or await service.submit(value,**prepared)
            return stream(service,turn['id'],accepted=True,authenticated=authenticated)
        match=re.fullmatch(r'/api/chat/jobs/([A-Za-z0-9_.-]+)/stream',path)
        if match and get:
            turn=service.get_turn(match[1])
            if request.query_params.get('sessionId',turn['session_id'])!=turn['session_id']:
                raise ValueError('回合与会话不一致')
            after=int(request.query_params.get('after',request.headers.get('last-event-id','0')))
            if not 0<=after<=100000000:raise ValueError('事件位置无效')
            return stream(service,match[1],after,True,authenticated)
        match=re.fullmatch(r'/api/chat/last/([A-Za-z0-9_.-]+)',path)
        if match and get:
            turn=request.query_params.get('turn_id')
            result=service.last(match[1])
            if turn:
                current=service.get_turn(turn)
                if current['session_id']!=match[1]:raise ValueError('回合与会话不一致')
                result={**current,'status':'done' if current['status'] in ('completed','stopped','failed','unknown') else 'running',
                        'execution_status':current['status'],'text':current.get('output',''),'turn_id':current['id'],
                        'clean_end':current['status']=='completed','stop_reason':None if current['status']=='completed' else current['status']}
            return response(result)
        if path=='/api/chat/stop' and method=='POST':
            return response(await service.stop(identity(value.get('sessionId') or value.get('session_id')),value.get('turnId') or value.get('turn_id')))
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
