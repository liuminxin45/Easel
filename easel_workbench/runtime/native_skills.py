"""Thin authenticated host ports for the single official skill service.

Discovery, prompt construction and response shape belong to Easel. This host
only supplies its existing profile/settings stores, native chat transport and
durable operation receipt; it never resolves private skill versions or plans.
"""
from __future__ import annotations
import asyncio
import hashlib
from pathlib import Path
import re
from types import SimpleNamespace

from fastapi import HTTPException
from easel.web_services.skills import create_skills_context
from easel.persona import chat_turn_message
from easel_workbench.contracts.values import ident,pack


class NativeSkills:
    def __init__(self,box,chat):
        self.box,self.chat=box,chat
        self._executions=set()
        self.root=Path(box.root).resolve()
        # Easel's workspace SKILL.md is the single live source used both by
        # discovery and by the existing native engine rooted at this project.
        self.skills=self.root/'skills'

    def _persona(self,name):
        if not name:return ''
        # The original profile remains a host storage port. No filesystem
        # mirror or second profile version is created to render a skill.
        with self.box.store.connect() as c:profile=self.box.creator._profile(c,name)
        return '我当前使用的画像是「'+profile['name']+'」。\n'+ '\n'.join(str(profile.get(k,'')) for k in ('identity','audience','voice','boundaries'))+'\n\n'

    def context(self,execute=None,ports=None):
        async def unavailable(message,timeout):raise HTTPException(409,'技能执行端口未连接')
        return create_skills_context(self.root,skills=self.skills,
            environment=self.chat.settings.environment,execute=execute or unavailable,
            persona=self._persona,direct_api=lambda:self.chat.settings.current()['runtime']=='api',ports=ports)

    def prepare_message(self,skill,value,persona=None):
        if not isinstance(skill,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',skill):raise HTTPException(404,'技能不存在')
        native=self.context()
        return native._publishing_message(native.prepare_skill_message(skill,value,persona))

    def prepare_chat_message(self,value,persona=None):
        native=self.context()
        return native._publishing_message(self._persona(persona)+chat_turn_message(value,None))

    def items(self):return self.context().get_skills()
    async def detail(self,name):
        configuration=self.chat.settings.skill_configuration()
        native=self.context(ports={'_read_env':lambda:configuration['environment']})
        return {**await native.api_skill_detail(name),'configuration_revision':configuration['revision']}

    async def execute(self,request,value,*,plain_chat=False):
        from easel_workbench.runtime.native_api import adapter
        api=await adapter(self.box)
        operation=ident(request.headers.get('x-operation-id'))
        fields=dict(value)
        signature=hashlib.sha256(pack({'method':request.method,'path':request.url.path,'body':fields}).encode()).hexdigest()
        pending={'id':operation,'native_protocol':True,'state':'unavailable','result':None}
        exists,previous=await asyncio.to_thread(api._reserve_operation,operation,signature,pending)
        if exists:return previous
        task=asyncio.create_task(self._execute_owned(api,pending,fields,plain_chat=plain_chat))
        self._executions.add(task)
        def finished(done):
            self._executions.discard(done)
            if not done.cancelled():done.exception()
        task.add_done_callback(finished)
        return await asyncio.shield(task)

    async def _execute_owned(self,api,pending,fields,*,plain_chat=False):
        operation=pending['id']
        try:
            skill=fields.get('skill');value=fields.get('message' if plain_chat else 'input');persona=fields.get('persona')
            if (not plain_chat and (not isinstance(skill,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',skill))) or not isinstance(value,str) or len(value)>160000:
                raise HTTPException(400,'技能执行输入无效')
            if persona is not None and not isinstance(persona,str):raise HTTPException(400,'画像无效')
            if plain_chat and fields.get('sessionId') is not None and (not isinstance(fields['sessionId'],str) or not fields['sessionId'].strip() or len(fields['sessionId'])>256):raise HTTPException(400,'对话标识无效')
            if plain_chat and fields.get('attachments'):raise HTTPException(400,'请在流式对话中发送附件')
            async def execute(message,timeout,session_id=None):
                # Session and turn IDs are deterministic per accepted HTTP
                # operation. Unknown receipts are never converted into replay.
                sid=session_id or 'skill-'+operation;tid='skill-turn-'+operation
                with self.box.store.connect() as c:exists=c.execute('SELECT 1 FROM easel_chat_sessions WHERE id=?',(sid,)).fetchone()
                if not exists:await asyncio.to_thread(self.chat.create_internal_session,{'id':'skill-create-'+operation,'session_id':sid,'profile_id':persona or 'oil-pig'})
                context={'profile_id':persona or 'oil-pig'}
                if not plain_chat:context.update(skill_id=skill,action_id='native')
                message=self.context()._publishing_message(message)
                turn=await self.chat.submit({'sessionId':sid,'turnId':tid,'message':value,'attachments':[],
                    'context':context},snapshot=None,actual_prompt=message,interactive=False)
                async for _ in self.chat.events(turn['id']):pass
                final=await asyncio.to_thread(self.chat.get_turn,turn['id'])
                if final['status']=='unknown':
                    error=HTTPException(503,'技能执行结果尚未核对；原请求保留，不会自动重发')
                    error.native_unknown=True
                    raise error
                if final['status']!='completed':raise HTTPException(502,final.get('error') or '技能执行未取得完成回执；原请求保留，不会自动重发')
                return final.get('output','')
            if plain_chat:
                async def harness(req,sk,message,runtime,config,emit,*args,**kwargs):return await execute(message,0,sk)
                async def direct(req,sk,content,system,emit):return await execute(self._persona(persona)+value,0,sk)
                context=self.context(execute,ports={'_chat_backend':lambda sid:self.chat.settings.current()['runtime'],
                    '_harness_settings':self.chat.settings.current,'_run_harness_chat':harness,'_run_direct_chat':direct,
                    '_attachment_context':lambda req:'','chat_turn_message':lambda message,name:self._persona(name)+chat_turn_message(message,None),
                    '_direct_chat_content':lambda req:(req.message,''),'SESSIONS_DIR':self.root/'outputs/_sessions'})
                result=await context.api_chat(SimpleNamespace(message=value,persona=persona,sessionId=fields.get('sessionId'),turnId=None,attachments=[]))
            else:result=await self.context(execute).api_skill(SimpleNamespace(skill=skill,input=value,persona=persona))
        except HTTPException as exc:
            if getattr(exc,'native_unknown',False):raise
            await asyncio.to_thread(api._save_operation,operation,{**pending,'state':'rejected','result':{'detail':str(exc.detail)}})
            raise
        except ValueError as exc:
            # Validation or a configuration conflict before the native turn
            # is a definite rejection. Unexpected failures retain unavailable
            # and can never trigger an automatic second native execution.
            await asyncio.to_thread(api._save_operation,operation,{**pending,'state':'rejected','result':{'detail':str(exc)}})
            raise HTTPException(409,str(exc)) from exc
        await asyncio.to_thread(api._save_operation,operation,{**pending,'state':'completed','result':result})
        return result


def service(box,chat=None):
    if not getattr(box,'_native_skills',None):
        if chat is None:raise RuntimeError('技能执行需连接现有原生会话服务')
        box._native_skills=NativeSkills(box,chat)
    return box._native_skills
