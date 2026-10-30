import React,{useState} from 'react';
import {useWorkbench,useResource,useAsyncAction,platformAccountStatus,array,record,string,type JsonRecord} from '@workbench/core';
import {PageHead,Panel,Field,Modal,Notice,Pending,resultDocument} from './common';

export function Accounts(){
 const vm=useWorkbench(),resource=useResource<JsonRecord>('/api/platform-accounts',{interval:2000}),action=useAsyncAction();
 const [active,setActive]=useState(''),[credential,setCredential]=useState<JsonRecord|null>(null),[appId,setAppId]=useState(''),[secret,setSecret]=useState(''),[sms,setSms]=useState('');
 const platforms=array<JsonRecord>(resource.data?.platforms).slice().sort((a,b)=>priority(string(a.id))-priority(string(b.id))),sessions=array<JsonRecord>(resource.data?.sessions),connections=array<JsonRecord>(resource.data?.connections);
 const selected=sessions.find(s=>s.id===active),phase=string(selected?.login_state)||string(selected?.state);
 const mutate=(fields:JsonRecord)=>vm.client.mutate<JsonRecord>('media:account','/api/platform-accounts',fields);
 const connect=(platform:JsonRecord,session?:JsonRecord,legacy?:JsonRecord)=>void action.run(async()=>{
  let current=session;
  if(!current){const result=await mutate({action:'create',platform:platform.id,label:legacy?.label||platform.name,...(legacy?{connection_id:legacy.id}:{})});current=record(resultDocument(result).session);if(!current.id)throw Error('连接记录尚未核对，请保留原操作重查。');}
  setActive(string(current.id));setSms('');
  try{await mutate({action:'login',session_id:current.id,base_revision:current.revision})}finally{await resource.reload()}
 });
 const command=(session:JsonRecord,kind:string)=>void action.run(async()=>{await mutate({action:kind,session_id:session.id,base_revision:session.revision});await resource.reload()});
 const card=(platform:JsonRecord,session?:JsonRecord,legacy?:JsonRecord)=>{
  const busy=session&&['login','checking'].includes(string(session.state)),connection=connections.find(c=>c.id===session?.connection_id),label=string(session?.label||legacy?.label||platform.name);
  return <div className="card account-card" key={string(session?.id||platform.id)}>
   <div className="account-card-head"><div className="account-avatar account-avatar-fallback">{session?.avatar?<img className="account-avatar" src={string(session.avatar)} alt="" referrerPolicy="no-referrer"/>:string(platform.name).slice(0,1)}</div><div><h2>{string(platform.name)}</h2><p>{string(session?.name)||label}</p></div><span className="badge">{session?platformAccountStatus(session.state):'尚未连接'}</span></div>
   {!!session?.account&&<p className="ew-muted">{string(session.account)}</p>}
   {session?.identity_status==='mismatch'&&<Notice message="扫码账号与原账号身份不一致，未替换旧账号；请使用原账号重新扫码。"/>}
   <div className="ew-row"><button className="btn btn-primary" disabled={action.busy} onClick={()=>busy?setActive(string(session?.id)):connect(platform,session,legacy)}>{busy?'查看登录进度':session?.state==='connected'?'重新扫码登录':legacy?'重新扫码连接':'扫码登录'}</button>
    {session&&<><button className="btn" disabled={action.busy||!!busy} onClick={()=>command(session,'probe')}>核对身份</button><button className="btn btn-ghost" disabled={action.busy} onClick={()=>command(session,'logout')}>断开连接</button></>}
    {session&&platform.id==='wechat-oa'&&<button className="btn btn-ghost" disabled={action.busy||!!busy} onClick={()=>{setCredential(session);setAppId('');setSecret('')}}>配置 AppID 凭据</button>}
    {!!session?.connection_id&&<button className="btn btn-ghost" onClick={()=>vm.navigate('/toolbox?section=profiles')}>关联画像</button>}
   </div>
   {connection&&<details><summary>交付能力与实际验证</summary>{Object.entries(record(connection.capabilities)).map(([key,value])=><p key={key}>{{draft:'存平台草稿',publish:'发布',verify:'读回回执'}[key]||key}：{platformAccountStatus(record(value).status)} · {string(record(value).reason)}</p>)}</details>}
  </div>;
 };
 return <div className="page-scroll"><PageHead title="平台账号"/><p className="page-subtitle">选择平台，用微信或对应平台 App 扫码登录。</p><Notice message={resource.error||action.error}/><Pending scope="media:account" reload={()=>void resource.reload()}/>
  <div className="accounts-grid">{platforms.flatMap(platform=>{const rows=sessions.filter(s=>s.platform===platform.id);return rows.length?rows.map(s=>card(platform,s)):[card(platform,undefined,connections.find(c=>c.platform===platform.channel&&!sessions.some(s=>s.connection_id===c.id)))];})}</div>
  <ConnectionEnvironment/>
  {connections.some(c=>!sessions.some(s=>s.connection_id===c.id))&&<details className="ew-panel"><summary>历史账号记录</summary><p>历史作品、账号和回执保留。重新扫码核对身份后，沿用原账号记录。</p>{connections.filter(c=>!sessions.some(s=>s.connection_id===c.id)).map(c=>{const platform=platforms.find(p=>p.channel===c.platform);return <div className="ew-row" key={string(c.id)}><span>{string(c.label)||string(c.account)} · {string(platform?.name||c.platform)}</span>{platform?<button className="btn" disabled={action.busy} onClick={()=>connect(platform,undefined,c)}>重新扫码连接此账号</button>:<span className="ew-muted">Easel 暂未提供此平台连接</span>}</div>})}</details>}
  <Modal open={!!active} title={string(platforms.find(p=>p.id===selected?.platform)?.name,'平台')+' · 扫码登录'} onClose={()=>setActive('')}>
   <p role="status">{loginLabel(phase)}</p><Notice message={action.error||string(selected?.error)}/>
   {!!selected?.qr_url&&<img className="ew-qr" src={string(selected.qr_url)} alt="平台登录二维码"/>}
   {phase==='sms_required'&&<><Field label="平台短信验证码"><input className="field" inputMode="numeric" autoComplete="one-time-code" value={sms} onChange={e=>setSms(e.target.value.replace(/\D/g,''))}/></Field><button className="btn btn-primary" disabled={action.busy||!/^\d{4,8}$/.test(sms)} onClick={()=>void action.run(async()=>{if(!selected)return;await mutate({action:'sms',session_id:selected.id,base_revision:selected.revision,code:sms});setSms('');await resource.reload()})}>提交验证码</button></>}
   {selected?.state==='connected'&&<p>已连接：{string(selected.name)||string(selected.label)}。身份已核对。</p>}
   {selected&&!['login','checking'].includes(string(selected.state))&&selected.state!=='connected'&&<button className="btn" disabled={action.busy} onClick={()=>connect(platforms.find(p=>p.id===selected.platform)!,selected)}>重新获取二维码</button>}
  </Modal>
  <Modal open={!!credential} title="公众号 AppID 凭据" onClose={()=>{setCredential(null);setSecret('');setAppId('')}}><p>扫码登录无需填写此项；接口凭据单独保存和验证。</p><Field label="AppID"><input className="field" autoComplete="off" value={appId} onChange={e=>setAppId(e.target.value)}/></Field><Field label="AppSecret"><input className="field" type="password" autoComplete="off" value={secret} onChange={e=>setSecret(e.target.value)}/></Field><button className="btn btn-primary" disabled={action.busy||!appId||!secret} onClick={()=>void action.run(async()=>{await vm.api.post('/api/platform-accounts',{id:crypto.randomUUID(),action:'credentials',session_id:credential?.id,base_revision:credential?.revision,app_id:appId,app_secret:secret},vm.config?.csrf||'');setSecret('');setAppId('');setCredential(null);await resource.reload()})}>加密保存并核对</button><Notice message={action.error}/></Modal>
 </div>;
}

function priority(id:string){return id==='wechat-oa'?0:id==='weixin-channels'?1:2}
function loginLabel(state:string){return ({login:'正在准备二维码…',qr_ready:'请用对应平台 App 扫码，并在手机上确认登录。',scanned:'已扫码，请在手机上确认。',window_login:'请完成平台登录。',sms_required:'平台要求短信验证。',verifying:'正在验证…',checking:'正在核对身份…',success:'扫码已完成，正在核对账号身份…',connected:'登录成功',expired:'二维码已过期，请重新获取。',not_connected:'登录尚未完成，请重新扫码。',account_mismatch:'扫码账号与原账号不一致。',identity_unconfirmed:'尚未取得可靠的账号身份，请核对。'} as Record<string,string>)[state]||'正在读取登录进度…'}

export function ConnectionEnvironment(){const vm=useWorkbench(),action=useAsyncAction(),[data,setData]=useState<JsonRecord|null>(null);const check=async()=>setData(await vm.api.get('/api/platform-accounts/environment'));return <details className="ew-panel"><summary>平台连接所需依赖</summary><button className="btn" disabled={action.busy} onClick={()=>void action.run(check)}>检测／刷新连接环境</button><Notice message={action.error}/>{data&&<><p>执行主机：{string(data.host)}</p>{array<JsonRecord>(data.tools).map(t=><p key={string(t.id)}>{string(t.name)} · {t.state==='ok'?'已安装':'缺少依赖'} {string(t.version)} {!!t.installable&&t.state!=='ok'&&<button className="btn" disabled={action.busy} onClick={()=>void action.run(async()=>{await vm.client.mutate('platform:install','/api/platform-accounts/environment/install',{recipe:t.id});await check()})}>安装连接依赖</button>}</p>)}{array<JsonRecord>(data.jobs).map(j=><p key={string(j.id)}>{string(j.recipe)} · {({queued:'等待安装',running:'正在安装',ok:'装后复测通过',fail:'安装或复测失败'} as Record<string,string>)[string(j.state)]||string(j.state)}</p>)}</>}</details>}
