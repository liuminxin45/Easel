import {createStore} from 'zustand/vanilla';
import type {WorkbenchClient,PendingOperation} from './client';
import {record,string,type JsonRecord,type NavigationTicket} from './models';

export type SessionOpenPhase='creating'|'checking'|'not_accepted'|'ready'|'failed'|'opened';
export interface SessionOpenInput {profileId:string;draft?:JsonRecord;query?:string;navigate?:boolean;sourceKey?:string;flowId?:string;newsArticleId?:string;newsNewSession?:boolean}
export interface SessionOpenFlow extends JsonRecord {flow_id:string;operation_id:string;profile_id:string;phase:SessionOpenPhase;created_at:number;updated_at:number;request:JsonRecord;draft?:JsonRecord;query?:string;navigate:boolean;source_key?:string;session_id?:string;runtime?:string;draft_applied?:boolean;auto_retries:number;parent_operation_id?:string;error?:string;code?:string;trace_id?:string;ticket?:NavigationTicket;route_opened?:boolean;recovered?:boolean}
const key=(id:string)=>'session-open:'+id;
const scope=(id:string)=>'session-open:'+id;
const target=(flow:SessionOpenFlow)=>'/chat/'+encodeURIComponent(flow.session_id!)+(flow.query?'?'+flow.query:'');
const owners=new WeakMap<WorkbenchClient,SessionOpenFlows>();

/** A create intent owns durable identity and navigation; no model call lives here. */
export class SessionOpenFlows {
 readonly state=createStore<{flow:SessionOpenFlow|null}>(()=>({flow:null}));
 private releases=new Map<string,()=>void>();private running=new Map<string,Promise<JsonRecord|null>>();private timers=new Map<string,ReturnType<typeof setTimeout>>();private legacyTimers=new Map<string,ReturnType<typeof setTimeout>>();private legacyAttempts=new Map<string,number>();private detachVisibility?:()=>void;
 constructor(private client:WorkbenchClient){
  if(typeof window!=='undefined'&&typeof window.addEventListener==='function'){
   const resume=()=>{if(!this.visible()){for(const timer of this.legacyTimers.values())clearTimeout(timer);this.legacyTimers.clear();return;}const flow=this.state.getState().flow;if(flow?.retry_waiting)void this.retryAutomatically(flow.flow_id);else if(flow&&!['opened','failed'].includes(flow.phase))void this.check(flow.flow_id);};
   for(const event of ['online','focus','pageshow'])window.addEventListener(event,resume);if(typeof document!=='undefined')document.addEventListener('visibilitychange',resume);
   this.detachVisibility=()=>{for(const event of ['online','focus','pageshow'])window.removeEventListener(event,resume);if(typeof document!=='undefined')document.removeEventListener('visibilitychange',resume);};
  }
 }
 private save(flow:SessionOpenFlow):boolean{
  const previous=this.load(flow.flow_id);
  const fields:(keyof SessionOpenFlow)[]=['operation_id','phase','session_id','runtime','draft_applied','auto_retries','parent_operation_id','error','code','trace_id','route_opened','recovered','legacy','legacy_waiting','retry_waiting','failure_kind'];
  if(previous&&fields.every(field=>previous[field]===flow[field])&&previous.ticket?.entryId===flow.ticket?.entryId&&previous.ticket?.flowId===flow.ticket?.flowId){const active=this.state.getState().flow;if(active?.flow_id===flow.flow_id&&fields.some(field=>active[field]!==flow[field]))this.state.setState({flow:previous});return true;}
  flow={...flow,updated_at:Date.now()};
  if(!this.client.drafts.set(key(flow.flow_id),flow)){this.state.setState({flow:{...flow,phase:flow.session_id?'ready':'failed',code:'local_persistence_failed',failure_kind:'local',error:flow.session_id?'对话已创建，本机恢复记录尚未保存，请重试保存。':'本机输入暂未保存，请重试保存后继续。'}});return false;}
  if(!previous||!this.state.getState().flow||this.state.getState().flow?.flow_id===flow.flow_id)this.state.setState({flow});if(previous?.phase!==flow.phase)this.client.reportOperationPhase({operation_id:flow.operation_id,flow_id:flow.flow_id,phase:flow.phase,elapsed_ms:Math.max(0,Date.now()-flow.created_at),...(flow.code?{code:flow.code}:{})});return true;
 }
 private load(id:string){return this.client.drafts.get<SessionOpenFlow>(key(id))}
 private visible(){return typeof document==='undefined'||!document.hidden}
 private attach(flow:SessionOpenFlow){
  if(this.releases.has(flow.flow_id))return;
  const state=this.client.operation(scope(flow.flow_id));
  const persist=(value:unknown)=>{const session=record(record(value).session||record(record(value).result).session||value),id=string(session.id);if(!id)return true;const current=this.load(flow.flow_id)||flow;return this.save({...current,session_id:id,runtime:string(session.runtime),phase:'ready',error:undefined});};
  const before=this.client.beforeOperationComplete(scope(flow.flow_id),persist);
  const update=()=>{const current=this.load(flow.flow_id)||flow,value=state.getState(),result=record(value.result),session=record(result.session||record(result.result).session);if(string(session.id)){if(persist(value.result)&&!value.pending)this.apply(flow.flow_id);}else if(value.pending){const unknown=value.pending.uncertain;this.save({...current,phase:unknown?'checking':'creating',recovered:current.recovered||unknown});}};
  const stop=state.subscribe(update);this.releases.set(flow.flow_id,()=>{before();stop()});
 }
 restore(id?:string):SessionOpenFlow|null{
  if(!id)return null;let flow=this.load(id);if(!flow)return null;
  const navigation=this.client.navigation,route=navigation?new URL(navigation.path,'https://workbench.invalid'):undefined;
  const ownsRoute=route?.pathname==='/chat'&&route.searchParams.get('flow')===id;
  // A reload creates a new navigation instance. Adopt its ticket only when
  // the currently visible route explicitly owns this exact persisted flow.
  if(ownsRoute){flow={...flow,ticket:navigation?.ticket?.(),route_opened:true,phase:flow.session_id?'ready':flow.phase};if(!this.save(flow))return this.state.getState().flow;}
  this.state.setState({flow});this.attach(flow);
  const pointer=record(this.client.drafts.get('native:session-receipt:'+flow.operation_id));
  if(!flow.session_id&&string(pointer.session_id)){this.save({...flow,session_id:string(pointer.session_id),phase:'ready',recovered:true});void this.check(id);}
  else if(flow.session_id){if(ownsRoute)this.apply(id);}else void this.check(id);
  return this.state.getState().flow;
 }
 async open(input:SessionOpenInput):Promise<JsonRecord|null>{
  const current=this.state.getState().flow;
  if(input.flowId&&this.load(input.flowId)){this.restore(input.flowId);return this.run(input.flowId);}
  if(current&&!['opened','failed'].includes(current.phase)&&current.profile_id===input.profileId&&current.source_key===(input.sourceKey||'')&&JSON.stringify(current.draft||{})===JSON.stringify(input.draft||{})){this.save({...current,ticket:this.client.navigation?.ticket?.()});this.show(current.flow_id);return this.run(current.flow_id);}
  const legacy=this.client.drafts.get<{operation?:PendingOperation}>('native:pending:chat:create')?.operation;
  const id=crypto.randomUUID(),operation=crypto.randomUUID(),request={action:'create',profile_id:input.profileId,id:operation,...(input.newsArticleId?{news_article_id:input.newsArticleId,...(input.newsNewSession?{news_new_session:true}:{})}:{})};
  const flow:SessionOpenFlow={flow_id:id,operation_id:operation,profile_id:input.profileId,request,phase:legacy?'checking':'creating',created_at:Date.now(),updated_at:Date.now(),auto_retries:0,draft:input.draft,query:input.query,navigate:input.navigate!==false,source_key:input.sourceKey||'',ticket:this.client.navigation?.ticket?.(),...(legacy?{legacy:true,legacy_operation_id:legacy.id,legacy_request:legacy.body}:{})};
  if(!this.save(flow))return null;this.attach(flow);
  const timer=setTimeout(()=>{this.timers.delete(id);const row=this.load(id);if(row&&!['opened'].includes(row.phase))this.show(id)},800);(timer as unknown as {unref?:()=>void}).unref?.();this.timers.set(id,timer);
  return this.run(id);
 }
 private run(id:string):Promise<JsonRecord|null>{
  const active=this.running.get(id);if(active)return active;
  const task=this.execute(id).finally(()=>this.running.delete(id));this.running.set(id,task);return task;
 }
 private async execute(id:string):Promise<JsonRecord|null>{
  let flow=this.load(id);if(!flow)return null;if(flow.session_id){this.apply(id);return {id:flow.session_id,runtime:flow.runtime};}
  if(flow.legacy)return this.resolveLegacy(flow);
  const pending=this.client.operation(scope(id)).getState().pending;
  if(pending){await this.client.reconcile(scope(id));flow=this.load(id)!;if(flow.session_id){this.apply(id);return {id:flow.session_id,runtime:flow.runtime};}this.save({...flow,phase:'checking'});return null;}
  try{
   const reply=await this.client.mutate<JsonRecord>(scope(id),'/api/chat/sessions',flow.request,{receiptProtocol:2});
   const session=record(reply.session||record(reply.result).session),sid=string(session.id);
   if(sid){const latest=this.load(id)!;if(latest.phase==='opened')return latest.recovered?null:session;if(this.save({...latest,session_id:sid,runtime:string(session.runtime),phase:'ready'})){this.apply(id);return latest.recovered?null:session;}return null;}
   this.save({...this.load(id)!,phase:'creating'});return null;
  }catch(error){
   const detail=error as {acceptance?:string;message?:string;code?:string;traceId?:string};flow=this.load(id)!;
   if(detail.acceptance==='not_accepted'){
    this.save({...flow,phase:'not_accepted',error:detail.message,code:detail.code,trace_id:detail.traceId});
    if(flow.auto_retries<1){this.save({...this.load(id)!,auto_retries:flow.auto_retries+1,retry_waiting:true});const timer=setTimeout(()=>{this.timers.delete(id);void this.retryAutomatically(id)},3000);(timer as unknown as {unref?:()=>void}).unref?.();this.timers.set(id,timer);}
   }else{const operation=this.client.operation(scope(id)).getState(),known=record(record(operation.result).session||record(record(operation.result).result).session),uncertain=!!operation.pending,local=detail.code==='local_persistence_failed'||!!this.client.drafts.persistence.getState().error;
    this.save({...flow,...(string(known.id)?{session_id:string(known.id),runtime:string(known.runtime)}:{}),phase:string(known.id)?'ready':local?'failed':uncertain?'checking':'failed',failure_kind:local?'local':uncertain?undefined:'rejected',recovered:uncertain,error:local?detail.message:uncertain?undefined:detail.message,code:local?'local_persistence_failed':detail.code,trace_id:detail.traceId});}
   return null;
  }
 }
 private async resolveLegacy(flow:SessionOpenFlow):Promise<JsonRecord|null>{
  try{
   const original=string(flow.legacy_operation_id),request=record(flow.legacy_request);
   const result=flow.legacy_waiting?await this.client.api.request<JsonRecord>('/api/operations/'+encodeURIComponent(original)+'?'+new URLSearchParams({path:'/api/chat/sessions'}),{operationProtocol:2}):await this.client.api.post<JsonRecord>('/api/chat/sessions/operations/'+encodeURIComponent(original)+'/resolve',{id:'resolve-'+flow.flow_id,request},this.client.session.getState().config?.csrf||'','resolve-'+flow.flow_id);
   const state=string(result.operation_state);
   if(state==='completed'||state==='sealed_not_accepted'){
    if(!this.client.drafts.set('session-open-history:'+original,{operation_id:original,state,...(state==='completed'?{session_id:string(record(result.session||record(result.result).session).id)}:{})}))return null;
    this.client.resolveSessionOperation('chat:create',original,result);
    const timer=this.legacyTimers.get(flow.flow_id);if(timer)clearTimeout(timer);this.legacyTimers.delete(flow.flow_id);this.legacyAttempts.delete(flow.flow_id);
    if(!this.save({...flow,legacy:false,legacy_waiting:false,parent_operation_id:original,phase:'creating'}))return null;
    return this.execute(flow.flow_id);
   }
   this.save({...flow,legacy_waiting:['accepted','running'].includes(state),phase:'checking'});this.scheduleLegacy(flow.flow_id);return null;
  }catch(error){this.save({...flow,phase:'checking',error:(error as Error).message});this.scheduleLegacy(flow.flow_id);return null;}
 }
 private scheduleLegacy(id:string){if(this.legacyTimers.has(id)||!this.visible())return;const attempt=this.legacyAttempts.get(id)||0,delay=[1000,2000,4000,8000,15000,30000][Math.min(attempt,5)];this.legacyAttempts.set(id,attempt+1);const timer=setTimeout(()=>{this.legacyTimers.delete(id);if(this.visible())void this.check(id)},delay);(timer as unknown as {unref?:()=>void}).unref?.();this.legacyTimers.set(id,timer);}
 private async retryAutomatically(id:string){if(!this.visible()||!await this.client.checkAuthentication())return;const flow=this.load(id);if(!flow?.retry_waiting)return;if(!this.save({...flow,retry_waiting:false,phase:'creating'}))return;await this.run(id);}
 async check(id=this.state.getState().flow?.flow_id):Promise<void>{
  if(!id||!await this.client.checkAuthentication())return;const flow=this.load(id);if(!flow)return;
  if(flow.retry_waiting){await this.retryAutomatically(id);return;}
  if(flow.legacy){await this.run(id);return;}
  if(flow.session_id){this.apply(id);return;}
  await this.client.reconcile(scope(id));const current=this.load(id);if(current?.session_id)this.apply(id);
 }
 async retry(id=this.state.getState().flow?.flow_id):Promise<JsonRecord|null>{
  if(!id)return null;const memory=this.state.getState().flow;let flow=memory?.flow_id===id&&memory.code==='local_persistence_failed'?memory:this.load(id);if(!flow)return null;
  if(flow.session_id){if(!this.save({...flow,phase:'ready',error:undefined,code:undefined,failure_kind:undefined}))return null;if(this.client.operation(scope(id)).getState().pending)await this.client.reconcile(scope(id));if(this.load(id)?.phase!=='opened')this.apply(id,true);return {id:flow.session_id,runtime:flow.runtime};}
  const pending=this.client.operation(scope(id)).getState().pending;
  if(flow.code==='local_persistence_failed'){
   if(!this.save({...flow,phase:'creating',error:undefined,code:undefined,failure_kind:undefined}))return null;this.attach(flow);if(pending){await this.check(id);return null;}return this.run(id);
  }
  if(flow.phase==='failed'&&!pending){
   if(!this.client.drafts.set('session-open-history:'+flow.operation_id,{flow_id:id,operation_id:flow.operation_id,request:flow.request,state:'rejected',code:flow.code,trace_id:flow.trace_id}))return null;
   const original=flow.operation_id,next=crypto.randomUUID();flow={...flow,operation_id:next,parent_operation_id:original,request:{...flow.request,id:next,...(flow.request.operation_id?{operation_id:next}:{})},auto_retries:1,retry_waiting:false,phase:'creating',error:undefined,code:undefined,failure_kind:undefined};
  }
  if(!this.save({...flow,phase:pending?'checking':'creating',error:undefined}))return null;return this.run(id);
 }
 show(id:string){const flow=this.load(id);if(!flow||!flow.navigate||this.state.getState().flow?.flow_id!==id)return;const navigation=this.client.navigation;if(!navigation)return;const path='/chat?'+new URLSearchParams({fresh:'1',flow:id});if(flow.ticket&&navigation.finishFlow&&!navigation.finishFlow(path,flow.ticket))return;if(!flow.ticket||!navigation.finishFlow)navigation.navigate(path,{intent:'flow'});this.save({...flow,route_opened:true,ticket:navigation.ticket?.()});}
 apply(id:string,explicit=false):boolean{
  const flow=this.load(id);if(!flow?.session_id)return false;
  if(flow.draft&&!flow.draft_applied){if(!this.client.drafts.set('chat:'+flow.session_id,flow.draft)){this.save({...flow,phase:'ready',code:'local_persistence_failed',failure_kind:'local',error:'对话已创建，本机输入尚未保存，请重试保存。'});return false;}if(!this.save({...flow,draft_applied:true,phase:'ready'}))return false;}
  const current=this.load(id)!;if(!current.navigate&&!explicit){const timer=this.timers.get(id);if(timer)clearTimeout(timer);this.timers.delete(id);this.releases.get(id)?.();this.releases.delete(id);return true;}const navigation=this.client.navigation;if(!navigation)return true;
  if(current.phase==='opened'&&!explicit)return true;
  if(!explicit&&this.state.getState().flow?.flow_id!==id)return false;
  const moved=explicit?(navigation.navigate(target(current),{intent:'flow'}),true):current.ticket&&navigation.finishFlow?navigation.finishFlow(target(current),current.ticket):(navigation.navigate(target(current),{intent:'flow'}),true);
  if(moved){const timer=this.timers.get(id);if(timer)clearTimeout(timer);this.timers.delete(id);this.save({...current,phase:'opened',error:undefined});this.releases.get(id)?.();this.releases.delete(id);void this.client.invalidate(['chat']);}return moved;
 }
 dispose(){this.detachVisibility?.();for(const release of this.releases.values())release();this.releases.clear();for(const timer of this.timers.values())clearTimeout(timer);this.timers.clear();for(const timer of this.legacyTimers.values())clearTimeout(timer);this.legacyTimers.clear();}
}
export const sessionOpenFlows=(client:WorkbenchClient)=>{let value=owners.get(client);if(!value){value=new SessionOpenFlows(client);owners.set(client,value);}return value;};
