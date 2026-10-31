/** Application-owned chat subscriptions. Views do not own native executions. */
import {createStore} from 'zustand/vanilla';
import {streamChat,type UploadedFile,type ChatQuestion} from '../../lib/api';
import {type StreamState} from '../../lib/store';
import {draftFingerprint,record,string,type WorkbenchClient,type DraftAttachment,type JsonRecord,type InteractionFeedback} from '@workbench/core';
import type {NativeSelection} from './ChatSessionView';

export interface FrozenTurn {turnId:string;message:string;attachments:UploadedFile[];context:JsonRecord;initial_title?:string;inputs:{text:string;files:DraftAttachment[];command?:NativeSelection|null;article_id?:string;article_mode?:'auto'|'product'};state:'connecting'|'accepted'|'rejected'|'unknown';accepted?:boolean}
export interface SessionDraft {text:string;files:DraftAttachment[];article_id?:string;article_mode?:'auto'|'product';command?:NativeSelection|null;pending?:FrozenTurn}
const emptyStream=():StreamState=>({content:'',thinking:'',activity:'',questions:[]});
const recovering=():InteractionFeedback=>({kind:'status',message:'连接暂时中断，正在恢复原任务状态。输入已保留。'});
const awaitingReceipt=(receipt:JsonRecord):InteractionFeedback=>({kind:'status',message:'原任务执行结果待核对。'+(string(receipt.error)?string(receipt.error)+' ':'')+'输入已保留，不会重复发送。'});
export class SessionRuntime {
 readonly state=createStore<{stream?:StreamState;running:boolean;accepted:boolean;error:string;feedback?:InteractionFeedback}>(()=>({running:false,accepted:false,error:''}));
 readonly blocked=new Set<string>();readonly completed=new Set<string>();readonly closed=new Set<string>();
 private controller?:AbortController;private owner?:object;private activeTurn?:string;
 private recoveryTimer?:ReturnType<typeof setTimeout>;
 constructor(readonly client:WorkbenchClient,readonly id:string){}
 private patch(value:Partial<SessionDraft>){const key='chat:'+this.id;this.client.drafts.set(key,{...this.client.drafts.get<SessionDraft>(key)||{text:'',files:[]},...value})}
 private reload(){return this.client.read('/api/chat/sessions/'+encodeURIComponent(this.id),true)}
 private acknowledge(turn:FrozenTurn){
  const current=this.client.drafts.get<SessionDraft>('chat:'+this.id),same=current&&draftFingerprint({text:current.text,files:current.files,command:current.command,article_id:current.article_id,article_mode:current.article_mode})===draftFingerprint(turn.inputs);
  this.patch({...(same&&!current?.pending?.accepted?{text:'',files:[],command:null,article_id:undefined,article_mode:undefined}:{}),pending:{...turn,state:'accepted',accepted:true}});this.state.setState({accepted:true});
 }
 private clearRecovery(){if(this.recoveryTimer)clearTimeout(this.recoveryTimer);this.recoveryTimer=undefined}
 private scheduleRecovery(turn:FrozenTurn,profileId:string,delay=1500){
  if(this.recoveryTimer||this.completed.has(turn.turnId))return;
  const epoch=this.client.authenticationEpoch;
  const timer=setTimeout(()=>{this.recoveryTimer=undefined;void(async()=>{
   if(epoch!==this.client.authenticationEpoch||this.client.session.getState().expired||this.saved()?.turnId!==turn.turnId)return;
   if(this.owner||typeof document!=='undefined'&&document.hidden){this.scheduleRecovery(turn,profileId,delay);return}
   try{
    const receipt=await this.client.api.get<JsonRecord>('/api/chat/last/'+encodeURIComponent(this.id)+'?turn_id='+encodeURIComponent(turn.turnId),AbortSignal.timeout(3000));
    if(epoch!==this.client.authenticationEpoch||this.saved()?.turnId!==turn.turnId)return;
    const status=string(receipt.execution_status)||string(receipt.stop_reason);
    if(string(receipt.turn_id)===turn.turnId){
     if(receipt.delivery_state!=='unknown'){
     if(['completed','stopped','failed'].includes(status)){
      this.acknowledge(turn);this.completed.add(turn.turnId);this.blocked.delete(turn.turnId);this.patch({pending:undefined});this.state.setState({running:false,stream:undefined,feedback:undefined,error:status==='failed'?string(receipt.error):''});void this.reload();void this.client.invalidate(['chat','works','studio']);return;
     }
      if(['running','accepted','submitting'].includes(status)){this.blocked.delete(turn.turnId);this.connect(turn,profileId,true);return}
     }
     this.state.setState({feedback:awaitingReceipt(receipt),error:string(receipt.error)});
     this.scheduleRecovery(turn,profileId,Math.min(delay*2,15000));return;
    }
   }catch{/* Only read the original receipt; an unavailable read never starts another turn. */}
   this.state.setState({feedback:recovering()});this.scheduleRecovery(turn,profileId,Math.min(delay*2,15000));
  })()},delay);
  (timer as unknown as {unref?:()=>void}).unref?.();this.recoveryTimer=timer;
 }
 clear(){this.clearRecovery();this.owner=undefined;this.controller?.abort();this.controller=undefined;this.activeTurn=undefined;this.closed.clear();this.blocked.clear();this.completed.clear();this.state.setState({stream:undefined,running:false,accepted:false,error:'',feedback:undefined})}
 /** Called only after history authorizes this exact interrupted version. */
 restoreStopped(turnId:string,historicalError:string){
  const saved=this.saved();
  if(saved&&saved.turnId!==turnId||this.activeTurn&&this.activeTurn!==turnId||!saved&&this.activeTurn!==turnId)return;
  const state=this.state.getState();
  if(!saved&&!this.owner&&!state.running&&!state.feedback&&(!historicalError||state.error!==historicalError))return;
  this.clearRecovery();this.owner=undefined;this.controller?.abort();this.controller=undefined;
  this.completed.add(turnId);this.blocked.delete(turnId);
  if(saved)this.patch({pending:undefined});
  this.state.setState({running:false,stream:undefined,feedback:undefined,...(historicalError&&state.error===historicalError?{error:''}:{})});
 }
 closeQuestion(id:string){this.closed.add(id);const stream=this.state.getState().stream;if(stream)this.state.setState({stream:{...stream,questions:stream.questions.filter(q=>q.id!==id)}})}
 async status(ids:string[]){const value=await this.client.api.post<JsonRecord>('/api/chat/question/status',{questionIds:ids,sessionId:this.id,...(this.activeTurn?{turnId:this.activeTurn}:{})},this.client.session.getState().config?.csrf||'');return record(value.questions) as Record<string,{status:string}>}
 async answer(payload:{questionId:string;answers:Record<string,string[]>}){
  try{return await this.client.api.post<{ok:boolean;status?:string;expired?:boolean;error?:string}>('/api/chat/question/answer',{...payload,sessionId:this.id,turnId:this.activeTurn},this.client.session.getState().config?.csrf||'')}
  catch(error){
   // A lost HTTP acknowledgement must not become another permission decision.
   const statuses=await this.status([payload.questionId]);const status=statuses[payload.questionId]?.status;
   if(status==='answered')return {ok:true,status};
   if(status&&status!=='pending')return {ok:false,status,expired:true};
   throw error;
  }
 }
 connect(turn:FrozenTurn,profileId:string,resumeOnly=false){
  if(this.owner||this.completed.has(turn.turnId))return;
  this.clearRecovery();this.controller?.abort();const token={};this.owner=token;this.activeTurn=turn.turnId;
  this.state.setState({running:true,accepted:resumeOnly||turn.state==='accepted',error:'',feedback:undefined,stream:emptyStream()});
  this.patch({pending:{...turn,state:resumeOnly?turn.state:'connecting'}});
  const active=()=>this.owner===token;
  const change=(update:(stream:StreamState)=>StreamState)=>{if(active())this.state.setState({error:'',feedback:undefined,stream:update(this.state.getState().stream||emptyStream())})};
  let finalizing=false,transportInterrupted=false;
  const interruptionMessage='连接中断，正在核对原任务；不会重新发送。';
  const verify=()=>void(async()=>{if(finalizing||!active())return;finalizing=true;try{
   const receipt=await this.client.api.get<JsonRecord>('/api/chat/last/'+encodeURIComponent(this.id)+'?turn_id='+encodeURIComponent(turn.turnId));if(!active())return;
   const terminal=string(receipt.execution_status)||string(receipt.stop_reason),known=string(receipt.turn_id)===turn.turnId&&['completed','stopped','failed'].includes(terminal)&&receipt.delivery_state!=='unknown';
   if(known){this.clearRecovery();this.state.setState({error:'',feedback:undefined});this.acknowledge(turn);this.completed.add(turn.turnId);this.patch({pending:undefined});if(receipt.error&&terminal!=='stopped')this.state.setState({error:string(receipt.error)});if(['failed','unknown'].includes(string(receipt.hook_status)))this.state.setState({error:string(receipt.hook_error)||'模型回复已保留，作品记录仍待核对；不会重新制作。'})}
   else{this.blocked.add(turn.turnId);this.state.setState({feedback:string(receipt.turn_id)===turn.turnId?awaitingReceipt(receipt):recovering(),error:string(receipt.error)||'原回合结果尚未核对，已保留原请求，不会重复发送。'});this.patch({pending:{...turn,state:'unknown',accepted:this.saved()?.accepted}})}
   if(!active())return;this.owner=undefined;this.state.setState({running:false,stream:undefined});void this.reload();if(!known)this.scheduleRecovery(turn,profileId);const linked=string(record(receipt.work).work_id);void this.client.invalidate(['chat','works','studio',...(linked?['work:'+linked]:[])]);
  }catch(error){if(!active())return;this.owner=undefined;this.blocked.add(turn.turnId);this.state.setState({running:false,feedback:recovering(),error:error instanceof Error?error.message:'暂未取得原回执，输入仍保留'});this.patch({pending:{...turn,state:'unknown',accepted:this.saved()?.accepted}});this.scheduleRecovery(turn,profileId)}})();
  const fail=(error:Error)=>{if(!active())return;this.state.setState({error:error.message});const detail=error as Error&{status?:number;terminal?:boolean};if(detail.terminal){verify();return}const rejected=!resumeOnly&&!this.saved()?.accepted&&!!detail.status&&detail.status>=400&&detail.status<500;this.blocked.add(turn.turnId);this.patch({pending:{...turn,state:rejected?'rejected':'unknown',accepted:this.saved()?.accepted}});this.owner=undefined;this.state.setState({running:false,feedback:rejected?undefined:recovering()});if(!rejected)this.scheduleRecovery(turn,profileId);if(detail.status===401)void this.client.api.get('/api/config').catch(()=>{});void this.reload()};
  const receiveQuestion=async(question:ChatQuestion)=>{
   if(!active()||this.closed.has(question.id))return;
   try{const statuses=await this.status([question.id]);if(!active()||this.closed.has(question.id))return;
    if(statuses[question.id]?.status!=='pending'){this.closeQuestion(question.id);return}
    change(old=>({...old,questions:[...old.questions.filter(q=>q.id!==question.id),question]}));
   }catch{if(active()){this.state.setState({feedback:recovering(),error:'授权状态暂未核对，正在等待原回合；不会重复提交。'});setTimeout(()=>{if(active())void receiveQuestion(question)},5000)}}
  };
  this.controller=streamChat(turn.message,profileId,this.id,chunk=>change(old=>({...old,content:old.content+chunk})),verify,fail,
   chunk=>change(old=>({...old,thinking:old.thinking+chunk})),activity=>change(old=>({...old,activity,stillWorking:undefined})),
   ()=>{if(active()){transportInterrupted=true;this.state.setState({feedback:recovering(),error:interruptionMessage})}},turn.turnId,resumeOnly,
   ()=>{if(active()){this.owner=undefined;this.blocked.add(turn.turnId);this.state.setState({running:false,feedback:recovering(),error:'原任务暂时无法核对，输入与请求标识仍保留。'});this.patch({pending:{...turn,state:'unknown',accepted:this.saved()?.accepted}});this.scheduleRecovery(turn,profileId)}},turn.attachments,
   question=>void receiveQuestion(question),note=>change(old=>({...old,stillWorking:note})),closed=>{if(active())this.closeQuestion(closed.id)},
   {basePath:'',context:turn.context,initialTitle:turn.initial_title,headers:{'X-CSRF-Token':this.client.session.getState().config?.csrf||''},onAccepted:()=>{if(active()){this.acknowledge(turn);void this.client.invalidate(['chat'])}},onConnectionRestored:()=>{
    if(!active()||!transportInterrupted)return;transportInterrupted=false;
    if(this.state.getState().error===interruptionMessage)this.state.setState({error:'',feedback:undefined});
   }});
 }
 saved(){return this.client.drafts.get<SessionDraft>('chat:'+this.id)?.pending}
 async stop(){const turn=this.saved();if(!turn)return;const epoch=this.client.authenticationEpoch;
  const result=await this.client.api.post<JsonRecord>('/api/chat/stop',{sessionId:this.id,turnId:turn.turnId},this.client.session.getState().config?.csrf||'');
  if(epoch!==this.client.authenticationEpoch)return;
  if(result.stopped!==true)throw Error('尚未确认原任务已经停止，请继续核对回执');
  this.owner=undefined;this.controller?.abort();this.state.setState({running:false,stream:undefined,error:'',feedback:undefined});this.clearRecovery();this.completed.add(turn.turnId);this.patch({pending:undefined});void this.reload();
 }
}
const coordinators=new WeakMap<WorkbenchClient,Map<string,SessionRuntime>>();
export function sessionRuntime(client:WorkbenchClient,id:string){
 let sessions=coordinators.get(client);if(!sessions){sessions=new Map();coordinators.set(client,sessions);let epoch=client.authenticationEpoch;const owned=sessions;
  client.session.subscribe(()=>{if(epoch!==client.authenticationEpoch){epoch=client.authenticationEpoch;for(const runtime of owned.values())runtime.clear();owned.clear()}});
 }
 let runtime=sessions.get(id);if(!runtime){runtime=new SessionRuntime(client,id);sessions.set(id,runtime)}return runtime;
}
