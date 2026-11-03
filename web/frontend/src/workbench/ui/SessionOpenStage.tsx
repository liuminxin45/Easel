import React,{useEffect,useMemo,useRef,useState} from 'react';
import {useStore} from 'zustand';
import type {WorkbenchClient} from '../core/client';
import {sessionOpenFlows,type SessionOpenFlow} from '../core/session-open-flow';
import {IconChat,IconCheck,IconRefresh} from '../../components/icons';
import {Drawer} from './common';
import './styles/session-open.css';

export function useSessionOpenFlow(client:WorkbenchClient){const owner=useMemo(()=>sessionOpenFlows(client),[client]);return {owner,...useStore(owner.state)};}
export function SessionOpenStage({client,flow,error,onRetry}:{client:WorkbenchClient;flow:SessionOpenFlow|null;error?:string;onRetry?:()=>void}){
 const owner=sessionOpenFlows(client),[details,setDetails]=useState(false),[now,setNow]=useState(Date.now()),mounted=useRef(Date.now()),started=flow?.created_at??mounted.current;
 useEffect(()=>{const elapsed=Date.now()-started,next=elapsed<800?800:elapsed<30000?30000:0;if(!next)return;const timer=setTimeout(()=>setNow(Date.now()),Math.max(1,next-elapsed));return()=>clearTimeout(timer)},[flow?.flow_id,flow?.phase,now,started]);
 const long=!!flow&&now-flow.created_at>=30000,ready=!!flow?.session_id;
 const local=flow?.code==='local_persistence_failed',profileFailure=!!flow&&(/profile/i.test(flow.code||'')||/画像/.test(flow.error||''));
 const title=ready?'对话已创建':local?'输入尚未保存':flow?.phase==='not_accepted'?'对话尚未创建':flow?.phase==='failed'?'无法创建对话':error?'暂时无法读取对话':!flow?'正在读取对话':long?'暂时无法确认创建结果':flow?.phase==='checking'?'正在核对对话状态':'正在创建对话';
 const description=ready?(flow?.error||'准备好后即可进入对话。'):flow?.phase==='not_accepted'?'服务尚未受理本次创建，可以安全重试。':flow?.phase==='failed'||error?flow?.error||error:long?'可以稍后检查状态，或先返回工作台。':flow?.phase==='checking'?'确认结果后会自动继续，不会重复创建。':'完成后会自动打开。';
 const waiting=!ready&&!error&&!['failed','not_accepted'].includes(flow?.phase||'')&&!long;
 if((!flow||flow.phase==='creating')&&!error&&!ready&&now-started<800)return null;
 return <main className="ew-session-open-stage"><section className={'card ew-session-open-card'+(flow?.phase==='failed'||error?' is-error':long||flow?.phase==='not_accepted'?' is-warning':ready?' is-ready':'')} role={flow?.phase==='failed'||error?'alert':'status'} aria-label="新建对话状态" aria-live="polite">
  <div className={'ew-session-open-icon'+(waiting?' is-working':'')} aria-hidden="true">{ready?<IconCheck size={28}/>:waiting?<IconRefresh size={28}/>:<IconChat size={28}/>}</div>
  <h1 className="ew-session-open-title">{title}</h1><p className="ew-session-open-description">{description}</p>
  {flow?.draft&&(!!flow.draft.text||Array.isArray(flow.draft.files)&&flow.draft.files.length>0)&&<p className="ew-session-open-preserved">输入和附件已保留</p>}
  <div className="ew-session-open-actions">
   {local?<button className="btn btn-primary" onClick={()=>void owner.retry(flow!.flow_id)}>重试保存</button>:ready?<button className="btn btn-primary" onClick={()=>void owner.retry(flow!.flow_id)}>打开对话</button>:flow?.phase==='failed'?<><button className="btn btn-primary" onClick={()=>client.navigation?.navigate(profileFailure?'/toolbox?'+new URLSearchParams({section:'profiles',item:flow.profile_id}):'/settings',{intent:'object'})}>{profileFailure?'核对画像':'核对设置'}</button><button className="btn" onClick={()=>void owner.retry(flow.flow_id)}>重新创建</button></>:flow?.phase==='not_accepted'?<button className="btn btn-primary" onClick={()=>void owner.retry(flow.flow_id)}>重试创建</button>:flow?<button className="btn btn-primary" onClick={()=>void owner.check(flow.flow_id)}>检查状态</button>:onRetry?<button className="btn btn-primary" onClick={onRetry}>重试读取</button>:null}
   <button className="btn" onClick={()=>client.navigation?.navigate('/toolbox',{intent:'module'})}>返回工作台</button>
  </div>
  {flow&&<button className="btn btn-ghost ew-session-open-details" onClick={()=>setDetails(true)}>查看详情</button>}
 </section><Drawer open={details} title="对话创建记录" onClose={()=>setDetails(false)}><dl className="ew-session-open-record"><dt>操作标识</dt><dd>{flow?.operation_id}</dd><dt>处理阶段</dt><dd>{title}</dd><dt>创建时间</dt><dd>{flow&&new Date(flow.created_at).toLocaleString('zh-CN')}</dd>{flow?.session_id&&<><dt>对话标识</dt><dd>{flow.session_id}</dd></>}{flow?.code&&<><dt>诊断代码</dt><dd>{flow.code}</dd></>}{flow?.trace_id&&<><dt>跟踪标识</dt><dd>{flow.trace_id}</dd></>}{flow?.error&&<><dt>详细原因</dt><dd>{flow.error}</dd></>}</dl></Drawer></main>;
}
