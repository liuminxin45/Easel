import {ActionButton} from './common';
import React,{useState} from 'react';
import {useWorkbench,useResource,useAsyncAction,useOperation,requestFingerprint,RequestError,platformAccountStatus,array,record,string,number,type JsonRecord} from '@workbench/core';
import {PageHead,Field,Modal,Notice,Pending,resultDocument} from './common';

const accountPath='/api/platform-accounts';
const accountScope=(session:JsonRecord)=>'platform:account:'+string(session.id);
const loggingIn=(session?:JsonRecord)=>!!session&&['login','checking'].includes(string(session.state));

export function Accounts(){
 const vm=useWorkbench(),resource=useResource<JsonRecord>(accountPath,{interval:1500}),modalAction=useAsyncAction();
 const [active,setActive]=useState(''),[credential,setCredential]=useState<JsonRecord|null>(null),[appId,setAppId]=useState(''),[secret,setSecret]=useState(''),[sms,setSms]=useState('');
 const platforms=array<JsonRecord>(resource.data?.platforms).slice().sort((a,b)=>priority(string(a.id))-priority(string(b.id))),sessions=array<JsonRecord>(resource.data?.sessions),connections=array<JsonRecord>(resource.data?.connections);
 const selected=sessions.find(s=>s.id===active),operation=useOperation(selected?accountScope(selected):'platform:account:idle'),starting=operation.busy&&operation.pending?.body.action==='login',phase=starting?'login':string(selected?.login_state)||string(selected?.state);
 const apply=(result:unknown)=>record(resultDocument(result).session);
 const connect=async(platform:JsonRecord,session?:JsonRecord,legacy?:JsonRecord)=>{
  let current=session;
  if(!current){current=apply(await vm.client.mutate<JsonRecord>('platform:create:'+string(platform.id)+':'+string(legacy?.id),accountPath,{action:'create',platform:platform.id,label:legacy?.label||platform.name,...(legacy?{connection_id:legacy.id}:{})}));if(!current.id)throw Error('连接记录暂不可用，请稍后再试。');}
  setActive(string(current.id));setSms('');modalAction.setError('');
  try{apply(await vm.client.mutate(accountScope(current),accountPath,{action:'login',session_id:current.id,base_revision:current.revision}))}catch(error){modalAction.setError(error instanceof RequestError&&error.uncertain?'':error instanceof Error?error.message:'连接未完成');throw error}
 };
 const command=async(session:JsonRecord,action:string)=>{apply(await vm.client.mutate(accountScope(session),accountPath,{action,session_id:session.id,base_revision:session.revision}))};
 const card=(platform:JsonRecord,session?:JsonRecord,legacy?:JsonRecord)=><AccountCard key={string(session?.id||legacy?.id||platform.id)} platform={platform} session={session} legacy={legacy} connection={connections.find(c=>c.id===session?.connection_id)} onConnect={()=>connect(platform,session,legacy)} onProgress={()=>{setActive(string(session?.id));modalAction.setError('')}} onCommand={kind=>command(session!,kind)} onCredentials={()=>{setCredential(session!);setAppId('');setSecret('')}}/>;
 return <div className="page-scroll"><PageHead title="平台账号"/><p className="page-subtitle">选择平台，用微信或对应平台 App 扫码登录。</p><Notice sources={[resource]}/><Pending scope="media:account"/>
  <div className="accounts-grid">{platforms.flatMap(platform=>{const rows=sessions.filter(s=>s.platform===platform.id);return rows.length?rows.map(s=>card(platform,s)):[card(platform,undefined,connections.find(c=>c.platform===platform.channel&&!sessions.some(s=>s.connection_id===c.id)))];})}</div>
  <ConnectionEnvironment/>
  {connections.some(c=>!sessions.some(s=>s.connection_id===c.id))&&<details className="ew-panel"><summary>历史账号记录</summary><p>重新扫码登录后，沿用原账号记录。</p>{connections.filter(c=>!sessions.some(s=>s.connection_id===c.id)).map(c=>{const platform=platforms.find(p=>p.id===c.platform||p.channel===c.platform);return <div key={string(c.id)}>{platform?card(platform,undefined,c):<p>{string(c.label)||string(c.account)} · Easel 暂未提供此平台连接</p>}</div>})}</details>}
  <Modal open={!!active} title={string(platforms.find(p=>p.id===selected?.platform)?.name,'平台')+' · 扫码登录'} onClose={()=>setActive('')}>
   <p role="status" aria-live="polite">{loginLabel(phase)}</p><Notice sources={[modalAction]} message={string(selected?.error)}/>
   {!!selected?.qr_url&&<img className="ew-qr" src={string(selected.qr_url)} alt="平台登录二维码"/>}
   {phase==='sms_required'&&<><Field label="平台短信验证码"><input className="field" inputMode="numeric" autoComplete="one-time-code" value={sms} onChange={e=>setSms(e.target.value.replace(/\D/g,''))}/></Field><ActionButton action={modalAction} className="btn btn-primary" disabled={modalAction.busy||!/^\d{4,8}$/.test(sms)} onClick={()=>void modalAction.run(async()=>{if(!selected)return;apply(await vm.client.mutate(accountScope(selected),accountPath,{action:'sms',session_id:selected.id,base_revision:selected.revision,code:sms}));setSms('')})}>提交验证码</ActionButton></>}
   {selected?.state==='connected'&&<p>已连接：{string(selected.name)||string(selected.label)}</p>}
   {selected&&!starting&&!loggingIn(selected)&&selected.state!=='connected'&&<ActionButton action={modalAction} className="btn" disabled={modalAction.busy} onClick={()=>void modalAction.run(()=>connect(platforms.find(p=>p.id===selected.platform)!,selected))}>重新获取二维码</ActionButton>}
   {selected&&<Pending scope={accountScope(selected)}/>}
  </Modal>
  <Modal open={!!credential} title="公众号 AppID 凭据" onClose={()=>{setCredential(null);setSecret('');setAppId('')}}><p>扫码登录无需填写此项；接口凭据单独保存和验证。</p><Field label="AppID"><input className="field" autoComplete="off" value={appId} onChange={e=>setAppId(e.target.value)}/></Field><Field label="AppSecret"><input className="field" type="password" autoComplete="off" value={secret} onChange={e=>setSecret(e.target.value)}/></Field><ActionButton action={modalAction} className="btn btn-primary" disabled={modalAction.busy||!appId||!secret} onClick={()=>void modalAction.run(async()=>{const fields={action:'credentials',session_id:credential?.id,base_revision:credential?.revision,app_id:appId,app_secret:secret};apply(await vm.client.mutate(accountScope(credential!),accountPath,fields,{metadataOnly:true,requestSignature:await requestFingerprint(fields),receiptPath:id=>'/api/operations/'+encodeURIComponent(id)+'?'+new URLSearchParams({path:accountPath})}));setSecret('');setAppId('');setCredential(null);void resource.reload()})}>保存凭据</ActionButton><Notice sources={[modalAction]}/></Modal>
 </div>;
}

function AccountCard({platform,session,legacy,connection,onConnect,onProgress,onCommand,onCredentials}:{platform:JsonRecord;session?:JsonRecord;legacy?:JsonRecord;connection?:JsonRecord;onConnect:()=>Promise<unknown>;onProgress:()=>void;onCommand:(kind:string)=>Promise<unknown>;onCredentials:()=>void}){
 const vm=useWorkbench(),action=useAsyncAction(),busy=loggingIn(session),label=string(session?.label||legacy?.label||platform.name),scope=session?accountScope(session):'platform:create:'+string(platform.id)+':'+string(legacy?.id),operation=useOperation(scope),submitting=action.busy||operation.busy;
 return <div className="card account-card" aria-busy={submitting}>
  <div className="account-card-head"><div className="account-avatar account-avatar-fallback">{session?.avatar?<img className="account-avatar" src={string(session.avatar)} alt="" referrerPolicy="no-referrer"/>:string(platform.name).slice(0,1)}</div><div><h2>{string(platform.name)}</h2><p>{string(session?.name)||label}</p></div><span className="badge">{session?platformAccountStatus(session.state):'尚未连接'}</span></div>
  {!!session?.account&&<p className="ew-muted">{string(session.account)}</p>}
  {session?.identity_status==='mismatch'&&<Notice message="扫码账号与原账号不一致，请使用原账号重新扫码。"/>}
  <div className="ew-row"><ActionButton action={{busy:submitting}} className="btn btn-primary" disabled={submitting} onClick={()=>busy?onProgress():void action.run(onConnect)}>{submitting?'处理中…':busy?'查看登录进度':session?.state==='connected'?'重新扫码登录':legacy?'重新扫码连接':'扫码登录'}</ActionButton>
   {session&&<><ActionButton action={{busy:submitting}} className="btn" disabled={submitting||busy} onClick={()=>void action.run(()=>onCommand('probe'))}>刷新状态</ActionButton><ActionButton action={{busy:submitting}} className="btn btn-ghost" disabled={submitting} onClick={()=>void action.run(()=>onCommand('logout'))}>断开连接</ActionButton></>}
   {session&&platform.id==='wechat-oa'&&<button className="btn btn-ghost" disabled={submitting||busy} onClick={onCredentials}>配置 AppID 凭据</button>}
   {!!session?.connection_id&&<button className="btn btn-ghost" onClick={()=>vm.navigate('/toolbox?section=profiles')}>关联画像</button>}
  </div>
  <Notice sources={[action]}/><Pending scope={scope}/>
  {connection&&<details><summary>交付能力与实际验证</summary>{Object.entries(record(connection.capabilities)).map(([key,value])=><p key={key}>{{draft:'存平台草稿',publish:'发布',verify:'读回回执'}[key]||key}：{platformAccountStatus(record(value).status)} · {string(record(value).reason)}</p>)}</details>}
 </div>;
}

function priority(id:string){return id==='wechat-oa'?0:id==='weixin-channels'?1:2}
function loginLabel(state:string){return ({login:'正在启动浏览器并准备二维码…',qr_ready:'请用对应平台 App 扫码，并在手机上确认登录。',scanned:'已扫码，请在手机上确认。',window_login:'请完成平台登录。',sms_required:'平台要求短信验证。',verifying:'正在登录…',checking:'正在刷新账号状态…',success:'扫码已完成，正在读取账号信息…',connected:'登录成功',expired:'二维码已过期，请重新获取。',not_connected:'登录尚未完成，请重新扫码。',account_mismatch:'扫码账号与原账号不一致。',identity_unconfirmed:'暂未取得账号信息，请刷新状态。'} as Record<string,string>)[state]||'正在准备登录…'}

export function ConnectionEnvironment(){const vm=useWorkbench(),action=useAsyncAction(),[data,setData]=useState<JsonRecord|null>(null);const check=async()=>setData(await vm.api.get('/api/platform-accounts/environment'));return <details className="ew-panel"><summary>平台连接所需依赖</summary><ActionButton action={action} className="btn" disabled={action.busy} onClick={()=>void action.run(check)}>检测／刷新连接环境</ActionButton><Notice sources={[action]}/><Pending scope="platform:install" reload={()=>void action.run(check)}/>{data&&<><p>执行主机：{string(data.host)}</p>{array<JsonRecord>(data.tools).map(t=><p key={string(t.id)}>{string(t.name)} · {t.state==='ok'?'已安装':'缺少依赖'} {string(t.version)} {!!t.installable&&t.state!=='ok'&&<ActionButton action={action} className="btn" disabled={action.busy} onClick={()=>void action.run(async()=>{await vm.client.mutate('platform:install','/api/platform-accounts/environment/install',{recipe:t.id});await check()})}>安装连接依赖</ActionButton>}</p>)}{array<JsonRecord>(data.jobs).map(j=><p key={string(j.id)}>{string(j.recipe)} · {({queued:'等待安装',running:'正在安装',ok:'装后复测通过',fail:'安装或复测失败'} as Record<string,string>)[string(j.state)]||string(j.state)}</p>)}</>}</details>}
