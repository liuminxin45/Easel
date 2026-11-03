"""Durable HTTP acceptance; preparation delegates to the original chat use case.

Receiving a request is distinct from the native engine accepting its final turn.
Only ChatService submits to a harness; browser subscriptions never own this work.
"""
from __future__ import annotations

import asyncio
import copy
import json

from easel.web_services.concurrency import run_sync
from easel_workbench.features.conversations.receipts import ChatConflict,identity,text,packed,sha,now
from easel_workbench.infrastructure.storage.schema import initialize_chat_submissions


class ChatAdmission:
    def __init__(self, *, chat, business):
        self.chat,self.business,self.store=chat,business,chat.store
        self.tasks={}
        self.receivers=set()
        self.closing=False
        with self.store.connect() as c:initialize_chat_submissions(c)

    def _row(self,c,tid):
        row=c.execute('SELECT document FROM easel_chat_submissions WHERE id=?',(identity(tid),)).fetchone()
        return json.loads(row[0]) if row else None

    def _put(self,c,row):
        c.execute('UPDATE easel_chat_submissions SET document=? WHERE id=?',(packed(row),row['id']))

    def _anchor(self,c,value,session):
        profile=c.execute('SELECT revision,document FROM creator_profiles WHERE id=?',(session['profile_id'],)).fetchone()
        if not profile:raise ValueError('创作画像不存在')
        anchor={'profile':sha(list(profile)),
                'skills':[],
                'settings':self.chat.execution_settings(session),'workspace':sha(self.business._workspace(session))}
        context=value.get('context') or {}
        if context.get('article_id'):
            row=c.execute('SELECT * FROM articles WHERE id=?',(identity(context['article_id']),)).fetchone()
            if not row:raise ValueError('原资讯不存在')
            anchor['article']=sha(dict(row))
        if context.get('work_id'):
            wid=identity(context['work_id'])
            anchor['parent_feedback']=[c.execute('SELECT coalesce(max(seq),0) FROM toolbox_review_events WHERE work_id=?',(wid,)).fetchone()[0],
                                       c.execute('SELECT coalesce(max(rowid),0) FROM toolbox_article_draft_ops WHERE work_id=?',(wid,)).fetchone()[0]]
        return anchor

    def _receive(self,value):
        if not isinstance(value,dict) or set(value)-{'message','persona','sessionId','session_id','turnId','turn_id','id','operation_id','attachments','context','initial_title'}:
            raise ValueError('对话请求格式无效')
        tid=identity(value.get('turnId') or value.get('turn_id') or value.get('id'))
        sid=identity(value.get('sessionId') or value.get('session_id'))
        message=text(value.get('message',''),160000)
        attachments=value.get('attachments') or []
        if not isinstance(attachments,list) or len(attachments)>32:raise ValueError('附件列表无效')
        if not message.strip() and not attachments:raise ValueError('请输入消息或添加素材')
        context=value.get('context') or {}
        if not isinstance(context,dict) or set(context)-{'skill_id','version','action_id','profile_id','plan_token','work_id','parent_version_id','trial','article_id','article_mode','skill_revision'}:
            raise ValueError('对话启动上下文无效')
        signature=sha(value)
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE')
            old=self._row(c,tid)
            if old:
                if old['signature']!=signature:raise ChatConflict('同一请求不能更换消息、素材或技能')
                return old
            if c.execute('SELECT 1 FROM easel_chat_turns WHERE id=? OR operation_id=?',(tid,tid)).fetchone():
                raise ChatConflict('回合标识已有执行记录，请读取原回执')
            if any(field in context for field in ('plan_token','work_id','parent_version_id','trial','version','skill_revision')) or context.get('action_id','native')!='native':
                from easel_workbench.features.skills.retirement import SkillFeatureRetired
                raise SkillFeatureRetired('legacy-skill-orchestration')
            if self.closing or self.chat._closing:raise ChatConflict('服务正在关闭，请保留草稿')
            session=self.chat._session(c,sid)
            if session.get('archived') or session.get('pendingTurnId') or session.get('pendingSubmissionId'):
                raise ChatConflict('原任务仍在进行或待核对；没有重复发送')
            if context.get('profile_id',session['profile_id'])!=session['profile_id']:raise ChatConflict('已有会话保持原画像')
            if session.get('runtime')=='api' and any(context.get(k) for k in ('skill_id','action_id','work_id','parent_version_id')):
                raise ChatConflict('API 仅聊天模式没有本机技能和制作工具')
            row={'id':tid,'session_id':sid,'signature':signature,'request':copy.deepcopy(value),
                 'anchor':self._anchor(c,value,session),'status':'queued','created_at':now(),'updated_at':now()}
            c.execute('INSERT INTO easel_chat_submissions VALUES(?,?,?,?)',(tid,sid,signature,packed(row)))
            session.update(pendingSubmissionId=tid,revision=session['revision']+1,updated=now())
            self.chat._put_session(c,session)
        return row

    def get_turn(self,tid):
        with self.store.connect() as c:
            row=self._row(c,tid)
            if not row:raise ValueError('任务记录不存在')
            actual=c.execute('SELECT 1 FROM easel_chat_turns WHERE id=?',(tid,)).fetchone()
        if actual:return self.chat.get_turn(tid)
        failed=row['status']=='failed';stopped=row['status']=='stopped'
        return {'id':tid,'turn_id':tid,'session_id':row['session_id'],'status':'failed' if failed else 'stopped' if stopped else 'accepted',
                'execution_status':'failed' if failed else 'stopped' if stopped else 'accepted',
                'delivery_state':'not_started','accepted_by_server':True,'admission_phase':row['status'],
                'admission_failed':failed,'error':row.get('error',''),'created_at':row['created_at'],
                'message':row['request'].get('message',''),'attachments':row['request'].get('attachments',[])}

    def _kick(self,tid):
        if self.closing or tid in self.tasks:return
        task=asyncio.create_task(self._process(tid));self.tasks[tid]=task
        task.add_done_callback(lambda done:self.tasks.pop(tid,None) if self.tasks.get(tid) is done else None)

    async def receive(self,value):
        async def owned():
            row=await run_sync(self._receive,value)
            if row['status'] in ('queued','preparing','admitting'):self._kick(row['id'])
            return await run_sync(self.get_turn,row['id'])
        task=asyncio.create_task(owned());self.receivers.add(task)
        def finished(done):
            self.receivers.discard(done)
            if not done.cancelled():done.exception()
        task.add_done_callback(finished)
        return await asyncio.shield(task)

    def _stage(self,tid,status,*,anchor=False,error=None,expected=None):
        with self.store.connect() as c:
            c.execute('BEGIN IMMEDIATE');row=self._row(c,tid)
            if not row or row['status'] in ('failed','stopped','dispatched'):return None
            if expected is not None and row['status'] not in expected:return None
            session=self.chat._session(c,row['session_id'])
            if anchor and row['anchor']!=self._anchor(c,row['request'],session):
                raise ChatConflict('准备期间画像、技能默认版本或原始依据已变化，请重新核对；未调用模型')
            row.update(status=status,updated_at=now())
            if error:row['error']=error
            self._put(c,row)
            if status in ('failed','stopped','dispatched') and session.get('pendingSubmissionId')==tid:
                session.update(pendingSubmissionId=None,revision=session['revision']+1,updated=now());self.chat._put_session(c,session)
            return row

    def _prepare(self,row):
        request=copy.deepcopy(row['request'])
        return request,self.business.prepare(request)

    async def _process(self,tid):
        try:
            with self.store.connect() as c:
                actual=c.execute('SELECT 1 FROM easel_chat_turns WHERE id=?',(tid,)).fetchone()
            if actual:
                await run_sync(self._stage,tid,'dispatched');return
            row=await run_sync(self._stage,tid,'preparing',anchor=True)
            if not row:return
            request,prepared=await run_sync(self._prepare,row)
            row=await run_sync(self._stage,tid,'admitting',anchor=True)
            if not row:return
            await self.chat.submit(request,**prepared,admission_id=tid)
            await run_sync(self._stage,tid,'dispatched')
        except asyncio.CancelledError:
            # No native call was started during preparation; restart reads the
            # same request and anchors. Admitting tasks are drained by close().
            await run_sync(self._stage,tid,'queued')
            raise
        except Exception as error:
            message=str(error)[:500] if isinstance(error,ValueError) else '本轮准备未完成（'+type(error).__name__+'），输入已保留，请核对后重试。'
            with self.store.connect() as c:
                actual=c.execute('SELECT 1 FROM easel_chat_turns WHERE id=?',(tid,)).fetchone()
            await run_sync(self._stage,tid,'dispatched' if actual else 'failed',error=message)

    async def start(self):
        with self.store.connect() as c:
            ids=[r[0] for r in c.execute("SELECT id FROM easel_chat_submissions WHERE json_extract(document,'$.status') IN ('queued','preparing','admitting')")]
        for tid in ids:self._kick(tid)

    async def close(self):
        self.closing=True
        if self.receivers:await asyncio.gather(*self.receivers,return_exceptions=True)
        for tid,task in list(self.tasks.items()):
            with self.store.connect() as c:row=self._row(c,tid)
            if row and row['status']!='admitting':task.cancel()
        if self.tasks:await asyncio.gather(*list(self.tasks.values()),return_exceptions=True)

    async def stop(self,sid,tid):
        with self.store.connect() as c:
            row=self._row(c,tid)
            if not row or row['session_id']!=sid:raise ValueError('回合与会话不一致')
        if row['status'] in ('queued','preparing'):
            stopped=await run_sync(self._stage,tid,'stopped',expected=('queued','preparing'))
            if stopped:return {'stopped':True,'turn_id':tid,'native_started':False}
        task=self.tasks.get(tid)
        if task:await asyncio.shield(task)
        with self.store.connect() as c:actual=c.execute('SELECT 1 FROM easel_chat_turns WHERE id=?',(tid,)).fetchone()
        if actual:return await self.chat.stop(sid,tid)
        return {'stopped':row['status']=='stopped','turn_id':tid}

    async def events(self,tid,after=0):
        # Waiting/subscribing never creates a model call or replays a POST.
        yield {'id':0,'event':'activity','data':'AI已接收，正在处理；正在准备本轮技能与素材。'}
        while True:
            receipt=await run_sync(self.get_turn,tid)
            if 'admission_phase' not in receipt:
                async for event in self.chat.events(tid,after):yield event
                return
            if receipt['status'] in ('failed','stopped'):
                if receipt.get('error'):yield {'id':0,'event':'error','data':receipt['error']}
                yield {'id':0,'event':'done','data':{'sessionKey':receipt['session_id']}}
                return
            await asyncio.sleep(.25)

    def history(self,sid,*,limit=None,before=None):
        window=self.chat.history_window(sid,limit=limit,before=before) if limit is not None else None
        result=self.business.history(sid,**({'turn_ids':window['ids']} if window else {}));messages=result['session']['messages']
        existing={m['id'] for m in messages}
        with self.store.connect() as c:
            if window and not window['ids']:rows=[]
            elif window:
                rows=[json.loads(r[0]) for r in c.execute('SELECT document FROM easel_chat_submissions WHERE session_id=? AND id IN ('+','.join('?' for _ in window['ids'])+') ORDER BY rowid',(sid,*window['ids']))]
            else:rows=[json.loads(r[0]) for r in c.execute('SELECT document FROM easel_chat_submissions WHERE session_id=? ORDER BY rowid',(sid,))]
        for row in rows:
            if window and row['id'] not in window['ids']:continue
            if row['id'] in existing:continue
            value=row['request'];failed=row['status']=='failed';stopped=row['status']=='stopped'
            messages.extend([{'id':row['id']+'-user','role':'user','content':value.get('message',''),'timestamp':row['created_at'],'attachments':value.get('attachments',[])},
                             {'id':row['id'],'turnId':row['id'],'role':'assistant','content':row.get('error','') if failed else '',
                              'timestamp':row['updated_at'],'status':'failed' if failed else 'stopped' if stopped else 'running',
                              'activity':'已停止准备，未调用模型' if stopped else 'AI已接收，正在处理','admission_failed':failed}])
        if window:
            order={tid:index for index,tid in enumerate(window['ids'])}
            messages.sort(key=lambda message:(order.get(message.get('turnId') or (message['id'][:-5] if message['role']=='user' else message['id']),len(order)),message['role']!='user'))
        else:messages.sort(key=lambda message:message['timestamp'])
        if window:result['history_page']={key:value for key,value in window.items() if key!='ids'}
        return result
