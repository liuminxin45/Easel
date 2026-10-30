"""Easel project scripts behind the existing explicitly approved delivery ledger."""
import json
import datetime as dt
import os
import pathlib
import re
import subprocess
import sys
from easel_workbench.runtime.desk import stamp
from easel_workbench.runtime.feedback_ledger import locked


def supported_action(platform,action):
    # B站上传还需要准确分区与版权元数据，当前渠道稿尚未冻结这些字段。
    return action=='draft' if platform=='wechat-oa' else action=='publish' and platform in {'xiaohongshu','douyin','kuaishou','weixin-channels','zhihu'}


class EaselDistributionRuntime:
    extension_retired=True

    def __init__(self,box,fallback=None,*,runner=None):
        self.box,self.root,self.runner=box,pathlib.Path(box.root).resolve(),runner

    def _accounts(self):
        from easel_workbench.runtime.easel_accounts import service
        return service(self.box)

    def summary(self):
        return {'status':'ready_for_account_probe','connector':'easel','extension_required':False,
                'automatic_publish':False,'note':'平台直接扫码连接；仅执行准确账号与稿件的明确交付授权。'}

    def capability(self,connection,action):
        return self._accounts().capability(connection,action) or {'status':'unsupported','verified':False,'account':connection['account'],
                'account_verified':False,'code_verified':False,'reason':'此历史账号需重新扫码连接；旧浏览器扩展已退役。'}

    def probe(self,connection):
        session=self._accounts().session_for(connection)
        return {'account':connection['account'],'logged_in':bool(session and session.get('state')=='connected'),
                'identity_status':session.get('identity_status') if session else 'unconfirmed','checked_at':session.get('checked_at') if session else None}

    def _invoke(self,payload):
        if self.runner:return self.runner(payload)
        from easel_workbench.runtime.connection_environment import service
        python=service(self.box).python
        if not python.is_file():python=pathlib.Path(sys.executable)
        completed=subprocess.run([str(python),str(pathlib.Path(__file__).with_name('easel_publish_worker.py'))],input=json.dumps(payload,ensure_ascii=False),capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=600,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        return json.loads(completed.stdout) if completed.returncode==0 else {}

    def _remote(self,result,revision,connection):
        if not isinstance(result,dict):result={}
        observed=result.get('readback') or {};matched=observed.get('matched') or {};identifier=str(matched.get('platform_content_id') or result.get('media_id') or result.get('remote_id') or '')[:200]
        answer={'remote_state':'unknown','verified':False,'remote_id':identifier,'account':connection['account'],'revision_hash':revision['hash'],
                'evidence':[{'kind':'easel_execution_receipt','at':stamp(),'account':connection['account'],'readback_verified':False}],
                'error':'执行记录已保留，远端内容尚未完整核实；请在平台核对，不会自动重发。'}
        prefix={'douyin_video':'https://www.douyin.com/video/','kuaishou_video':'https://www.kuaishou.com/short-video/','bilibili_video':'https://www.bilibili.com/video/'}.get(connection['platform'])
        if (result.get('account')!=connection['account'] or observed.get('outcome')!='verified' or matched.get('title')!=revision['title'] or not prefix or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}',identifier)):return answer
        state=matched.get('status');remote='pending_review' if state in ('pending_review','reviewing','审核中','待审核') else 'published' if state in ('published','已发布','开放浏览') else 'unknown'
        if remote=='unknown':return answer
        if remote=='published':
            milliseconds=matched.get('published_at_ms')
            if type(milliseconds) not in (int,float) or milliseconds<=0:return answer
            try:answer['published_at']=dt.datetime.fromtimestamp(milliseconds/1000,dt.timezone.utc).isoformat()
            except (OverflowError,OSError,ValueError):return answer
        answer.update(remote_state=remote,verified=True,safe_url=prefix+identifier,error='',evidence=[{'kind':'easel_platform_readback','account':connection['account'],'remote_id':identifier,'readback_verified':True}])
        return answer

    def send(self,claim,assets):
        from easel_workbench.runtime.distribution_worker import preflight_assets
        delivery,revision,connection=claim['delivery'],claim['revision'],claim['connection']
        session=self._accounts().session_for(connection)
        if not session or session.get('state')!='connected' or session.get('identity_status')!='resolved' or session.get('account')!=connection['account']:
            raise ValueError('请先扫码连接并核对准确账号')
        if not supported_action(session['platform'],delivery['action']) or delivery.get('pilot') is not True:
            raise ValueError('当前 Easel 动作仅允许明确批准的首次试运行')
        for key in ('connection_id','account','platform'):
            if delivery.get(key)!=revision.get(key) or revision.get(key)!=(connection['id'] if key=='connection_id' else connection.get(key)):raise ValueError('交付身份与批准版本不一致')
        with self.box.store.connect() as c:
            row=c.execute('SELECT document FROM distribution_attempts WHERE id=?',(claim['attempt']['id'],)).fetchone()
            attempt=json.loads(row[0]) if row else {}
        if attempt.get('delivery_id')!=delivery['id'] or not attempt.get('dispatched_at') or attempt.get('status')!='leased' or attempt.get('lease_token')!=claim.get('lease_token'):
            raise ValueError('缺少准确的持久化发送边界')
        if assets!=preflight_assets(self.box,revision):raise ValueError('成品字节与批准快照不一致')
        directory=self.root/'data/easel-accounts'/session['id']
        payload={'session':session,'directory':str(directory),'action':delivery['action'],'revision':revision,'assets':assets,'delivery_id':delivery['id']}
        with locked(directory/'browser.lock',timeout=1):
            result=self._invoke(payload)
        return self._remote(result,revision,connection)

    def verify(self,delivery,revision,connection,hints):
        session=self._accounts().session_for(connection)
        unknown={'remote_state':'unknown','verified':False,'account':connection['account'],'reason':'保留原交付，尚未核实远端内容；不会重新发送。'}
        if not session or not delivery.get('dispatch_started_at') or session.get('account')!=connection['account'] or any(delivery.get(k)!=revision.get(k) for k in ('account','platform','connection_id')):return unknown
        directory=self.root/'data/easel-accounts'/session['id']
        try:
            with locked(directory/'browser.lock',timeout=1):
                result=self._invoke({'session':session,'directory':str(directory),'mode':'verify','revision':revision,'hints':hints,'dispatch_started_at':delivery['dispatch_started_at']})
            return self._remote(result,revision,connection)
        except Exception:return unknown
