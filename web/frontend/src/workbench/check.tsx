import React,{useEffect,useRef,useState} from 'react';
import {createRoot} from 'react-dom/client';
import {discoverExtensionAccounts,parseReadOnlyCheckFragment,type ReadOnlyCheckEvent,type ExtensionAccountObservation} from '@workbench/core';
import './check.css';

// The one-use ticket is never a query parameter, DOM value or persisted draft.
let credentials=parseReadOnlyCheckFragment(location.hash);
try{history.replaceState(null,'',location.pathname)}catch{if(credentials)credentials.ticket='';credentials=null}
const clearCredentials=()=>{if(credentials){credentials.ticket='';credentials.check_id=''}credentials=null};
type Stage='connecting'|'checking'|'reporting'|'completed'|'failed';
type SafeError='network_error'|'ticket_expired'|'invalid_response'|'extension_timeout'|'extension_failed'|'page_failed';
class CheckError extends Error{constructor(readonly code:SafeError){super(code)}}
const failureText:Record<SafeError,string>={network_error:'检测结果未能回传。请从手机重新发起本次检测。',ticket_expired:'本次检测已过期。请从手机重新发起。',invalid_response:'本次检测回执无法确认。请从手机重新发起。',extension_timeout:'同步助手未在限定时间内返回账号结果。平台登录状态未被改变。',extension_failed:'未能读取同步助手的账号结果。平台登录状态未被改变。',page_failed:'此页没有有效的一次性检测请求。请从手机重新发起。'};

function CheckPage(){
 const [stage,setStage]=useState<Stage>('connecting'),[message,setMessage]=useState('正在连接本次电脑检测…'),started=useRef(false),alive=useRef(true);
 useEffect(()=>{
  if(started.current)return;started.current=true;alive.current=true;const controller=new AbortController();let accounts:ExtensionAccountObservation[]=[];
  const show=(next:Stage,text:string)=>{if(alive.current&&!controller.signal.aborted){setStage(next);setMessage(text)}};
  const pause=(ms:number)=>new Promise<void>((resolve,reject)=>{const cancel=()=>{clearTimeout(timer);reject(new CheckError('network_error'))},timer=setTimeout(()=>{controller.signal.removeEventListener('abort',cancel);resolve()},ms);controller.signal.addEventListener('abort',cancel,{once:true})});
  const report=async(event:ReadOnlyCheckEvent,fields:{accounts?:ExtensionAccountObservation[];code?:string}={})=>{
   if(!credentials?.ticket)throw new CheckError('ticket_expired');
   const body=JSON.stringify({check_id:credentials.check_id,event,...fields});
   for(let attempt=0;attempt<3;attempt++){
    if(controller.signal.aborted)throw new CheckError('network_error');
    const request=new AbortController(),cancel=()=>request.abort(),timeout=setTimeout(()=>request.abort(),7000);controller.signal.addEventListener('abort',cancel,{once:true});
    try{
     const response=await fetch('/api/distribution/check-report',{method:'POST',credentials:'omit',cache:'no-store',referrerPolicy:'no-referrer',headers:{Authorization:'Bearer '+credentials.ticket,'Content-Type':'application/json'},body,signal:request.signal});
     if([401,403,404,410].includes(response.status))throw new CheckError('ticket_expired');
     if(response.status>=400&&response.status<500)throw new CheckError('invalid_response');
     if(!response.ok)throw new CheckError('network_error');
     const value:unknown=await response.json();
     if(!value||typeof value!=='object'||!('accepted' in value)||value.accepted!==true||!('check_id' in value)||value.check_id!==credentials.check_id)throw new CheckError('invalid_response');
     if(event==='result'&&(!('status' in value)||value.status!=='completed'||!('phase' in value)||value.phase!=='result_received'))throw new CheckError('invalid_response');
     return;
    }catch(error){
     if(controller.signal.aborted)throw error;
     if(error instanceof CheckError&&error.code!=='network_error')throw error;
     if(attempt===2)throw new CheckError('network_error');
    }finally{clearTimeout(timeout);controller.signal.removeEventListener('abort',cancel)}
    if(event==='result')show('reporting','连接不稳，正在重试回传（'+(attempt+2)+'/3）…');
    await pause(400*(attempt+1));
   }
  };
  const run=async()=>{
   try{
    if(!credentials)throw new CheckError('page_failed');
    await report('page_ready');
    await report('extension_started');
    show('checking','正在只读检查同步助手中的账号，可能需要约两分钟。');
    try{const value=await discoverExtensionAccounts({signal:controller.signal,timeoutMs:120000});accounts=value.accounts}
    catch(error){
     if(controller.signal.aborted)return;
     const timed=error instanceof Error&&'code' in error&&error.code==='extension_timeout',code=timed?'extension_timeout':'extension_failed';
     await report(timed?'extension_timeout':'failed',{code});
     throw new CheckError(code);
    }
    show('reporting','检测已结束，正在回传本次结果…');
    await report('result',{accounts});
    accounts=[];clearCredentials();show('completed','本次结果已回传到手机，可以关闭此页。');
   }catch(error){
    if(controller.signal.aborted)return;
    const code=error instanceof CheckError?error.code:'page_failed';
    accounts=[];clearCredentials();show('failed',failureText[code]);
   }
  };
  void run();
  const leave=()=>{alive.current=false;controller.abort();accounts=[];clearCredentials()};window.addEventListener('pagehide',leave,{once:true});
  return()=>{window.removeEventListener('pagehide',leave);leave()};
 },[]);
 return <main className="account-check-page" data-stage={stage}><div className="account-check-mark" aria-hidden="true">{stage==='completed'?<svg viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"/></svg>:stage==='failed'?<svg viewBox="0 0 24 24"><path d="M12 7v6m0 4h.01"/><circle cx="12" cy="12" r="10"/></svg>:<span className="account-check-spinner"/>}</div><h1>{stage==='completed'?'电脑检测已完成':stage==='failed'?'本次检测未完成':'电脑账号检测'}</h1><p role="status" aria-live="polite">{message}</p><p className="account-check-note">仅检查并回传此请求的账号信息，不发布内容。</p></main>;
}
createRoot(document.getElementById('root')!).render(<CheckPage/>);
