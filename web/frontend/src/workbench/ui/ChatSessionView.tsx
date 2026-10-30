import React,{useEffect,useRef,useState} from 'react';
import ChatPage,{type ChatCommand} from '../../components/ChatPage';
import {streamChat,type SkillItem,type UploadedFile,type ChatQuestion,type StreamChatOptions} from '../../lib/api';
import type {ChatSession,StreamState} from '../../lib/store';
import {useWorkbench,useResource,useDraft,useAsyncAction,draftFingerprint,array,record,string,workPath,type DraftAttachment,type JsonRecord,type Artifact} from '@workbench/core';
import {Notice,ArtifactView} from './common';
import {IconSkills} from './components/icons';
import {ProductionParameters} from './ProductionParameters';

export interface NativeSkill extends SkillItem {id?:string;skill_id?:string;version:number;available?:boolean;reason?:string;execution_kind?:string;launch_actions?:{id:string;label:string;task?:string;format?:string;requires_plan?:boolean;requires_context?:boolean;path?:string}[]}
export interface NativeSelection {skill_id:string;version:number;action_id:string;requires_plan:boolean;label:string;trial?:boolean;path?:string;task?:string}
export interface NativeSession extends ChatSession {profile_id?:string;revision?:number;message_count?:number;linked_works?:JsonRecord[]}
export interface NativeSessions {sessions:NativeSession[]}
interface FrozenTurn {turnId:string;message:string;attachments:UploadedFile[];context:JsonRecord;inputs:{text:string;files:DraftAttachment[];command?:NativeSelection|null;article_id?:string;article_mode?:'auto'|'product'};state:'connecting'|'accepted'|'rejected'|'unknown';accepted?:boolean}
interface SessionDraft {text:string;files:DraftAttachment[];article_id?:string;article_mode?:'auto'|'product';command?:NativeSelection|null;pending?:FrozenTurn}
const emptyStream=():StreamState=>({content:'',thinking:'',activity:'',questions:[]});
export function nativeSkillChoices(skills:NativeSkill[],versionContext=false):(ChatCommand&{selection:NativeSelection})[]{
 return skills.flatMap(skill=>(skill.launch_actions||[]).filter(action=>Number.isSafeInteger(skill.version)&&skill.version>0&&(!action.requires_context||versionContext||!!action.path)).map(action=>{
  const id=skill.skill_id||skill.id||skill.name,workflow=skill.execution_kind==='workflow'||id==='content-production';
  const label=workflow&&action.task==='poster'?'生成贴图':workflow&&action.task==='article'?'撰写文章':skill.name+' · '+action.label;
  return {id:id+':'+action.id,label,description:skill.reason||skill.description,disabled:skill.available===false,selection:{skill_id:id,version:skill.version,action_id:action.id,label,...(action.path?{path:action.path}:{}),task:action.task,requires_plan:action.requires_plan??['poster','article','image','change'].includes(action.task||action.format||'')}};
 }));
}
export function nativeSkillDestination(selection:NativeSelection,profileId:string,versionContext=false):string|null{
 if(['poster','article','discuss'].includes(selection.task||selection.action_id)||(versionContext&&['change','review'].includes(selection.task||selection.action_id)))return null;
 if(!selection.path)return '/toolbox?section=skills&item='+encodeURIComponent(selection.skill_id);
 const url=new URL(selection.path,'https://workbench.invalid');
 if(url.origin!=='https://workbench.invalid')return '/toolbox?section=skills';
 url.searchParams.set('profile',profileId);url.searchParams.set('skill',selection.skill_id);url.searchParams.set('skill_version',String(selection.version));url.searchParams.set('action',selection.action_id);if(selection.trial)url.searchParams.set('trial','1');
 return url.pathname+url.search;
}
export function nativeSkillInputTarget(selection:NativeSelection):{key:string;field:string}|null{
 const task=selection.task||selection.action_id;
 return task==='reference'?{key:'easel:reference',field:'text'}:task==='learning'?{key:'creator:experience',field:'goal'}:task==='analysis'?{key:'easel:metrics',field:'question'}:null;
}
export function NativeTurnOutputs({message}:{message:unknown}){
 const vm=useWorkbench(),value=record(message),files=array<Artifact>(value.output_files).filter(file=>!!file.id&&!!file.mime&&!!file.name),receipt=record(value.business_receipt),work=record(receipt.work||value.work),wid=string(work.work_id||receipt.work_id),vid=string(work.version_id||receipt.version_id||work.job_id);
 const issue=string(value.business_error);if(!files.length&&!wid&&!issue)return null;
 return <div className="chat-turn-outputs">{issue&&<details className="chat-task-status"><summary>本轮回复已保留，作品交付仍需核对</summary><p className="ew-preserve">{issue}</p></details>}{files.length>0&&<div className="ew-grid">{files.map(file=><ArtifactView key={file.id} file={file}/>)}</div>}{files.length>0&&wid&&vid&&<ProductionParameters key={vid} versionId={vid}/>} {wid&&<button className="btn btn-sm" onClick={()=>vm.navigate(workPath({id:wid,format:string(work.format)},vid||undefined))}>打开本轮作品版本</button>}</div>;
}
export function ChatSessionView({id,search}:{id:string;search:URLSearchParams}){
 const vm=useWorkbench(),resource=useResource<{session:NativeSession;linked_works?:JsonRecord[]}>('/api/chat/sessions/'+encodeURIComponent(id),{interval:3000}),catalog=useResource<NativeSkill[]>('/api/skills');
 const key='chat:'+id,[draft,patch]=useDraft<SessionDraft>(key,{text:'',files:[]}),action=useAsyncAction(),[stream,setStream]=useState<StreamState>(),[running,setRunning]=useState(false),[accepted,setAccepted]=useState(false),[error,setError]=useState('');
 const owner=useRef<object|null>(null),controller=useRef<AbortController|null>(null),blocked=useRef(new Set<string>()),completed=useRef(new Set<string>()),applied=useRef('');
 const session=resource.data?.session,profileId=session?.profile_id||session?.persona||search.get('profile')||'oil-pig',workId=search.get('work')||'',parentVersion=search.get('version')||'',versionContext=!!workId&&!!parentVersion,choices=nativeSkillChoices(catalog.data||[],versionContext);
 useEffect(()=>{if(!catalog.data||applied.current===search.toString()||(!versionContext&&draft.command!==undefined))return;const skill=search.get('skill'),version=Number(search.get('skill_version')),actionId=search.get('action');
  const selected=choices.find(choice=>choice.selection.skill_id===skill&&(!actionId||choice.selection.action_id===actionId));
  if(selected){applied.current=search.toString();patch({command:{...selected.selection,...(Number.isSafeInteger(version)&&version>0?{version}:{}),...(search.get('trial')==='1'?{trial:true}:{})}});}
 },[catalog.data,id,search.toString()]);
 const acknowledge=(turn:FrozenTurn)=>{
  const current=vm.client.drafts.get<SessionDraft>(key),same=current&&draftFingerprint({text:current.text,files:current.files,command:current.command,article_id:current.article_id,article_mode:current.article_mode})===draftFingerprint(turn.inputs);
  const acknowledged=current?.pending?.turnId===turn.turnId&&current.pending.accepted;
  patch({...(same&&!acknowledged?{text:'',files:[],command:null,article_id:undefined,article_mode:undefined}:{}),pending:{...turn,state:'accepted',accepted:true}});setAccepted(true);
 };
 const connect=(turn:FrozenTurn,resumeOnly=false)=>{
  controller.current?.abort();const token={};owner.current=token;setRunning(true);setAccepted(resumeOnly||turn.state==='accepted');setError('');setStream(emptyStream());
  patch({pending:{...turn,state:resumeOnly?turn.state:'connecting'}});
  const active=()=>owner.current===token;
  let finalizing=false;
  const verify=()=>void(async()=>{if(finalizing||!active())return;finalizing=true;try{
   const receipt=await vm.api.get<JsonRecord>('/api/chat/last/'+encodeURIComponent(id)+'?turn_id='+encodeURIComponent(turn.turnId));if(!active())return;
   const terminal=string(receipt.execution_status)||string(receipt.stop_reason),known=string(receipt.turn_id)===turn.turnId&&['completed','stopped','failed'].includes(terminal)&&receipt.delivery_state!=='unknown';
   if(known){acknowledge(turn);completed.current.add(turn.turnId);patch({pending:undefined});if(receipt.error)setError(string(receipt.error));if(['failed','unknown'].includes(string(receipt.hook_status)))setError(string(receipt.hook_error)||'模型回复已保留，作品记录仍待核对；不会重新制作。')}
   else{blocked.current.add(turn.turnId);setError(string(receipt.error)||'原回合结果尚未核对，已保留原请求，不会重复发送。');patch({pending:{...turn,state:'unknown',accepted:vm.client.drafts.get<SessionDraft>(key)?.pending?.accepted}})}
   await resource.reload();if(!active())return;owner.current=null;setRunning(false);setStream(undefined);const linked=string(record(receipt.work).work_id);void vm.client.invalidate(['chat','works','studio',...(linked?['work:'+linked]:[])]);
  }catch(caught){if(!active())return;blocked.current.add(turn.turnId);setError(caught instanceof Error?caught.message:'暂未取得原回执，输入仍保留');setRunning(false);patch({pending:{...turn,state:'unknown',accepted:vm.client.drafts.get<SessionDraft>(key)?.pending?.accepted}})}})();
  const fail=(caught:Error)=>{if(!active())return;setError(caught.message);const detail=caught as Error&{status?:number;terminal?:boolean};if(detail.terminal){verify();return}setRunning(false);const status=detail.status,saved=vm.client.drafts.get<SessionDraft>(key)?.pending,rejected=!resumeOnly&&!saved?.accepted&&!!status&&status>=400&&status<500;blocked.current.add(turn.turnId);patch({pending:{...turn,state:rejected?'rejected':'unknown',accepted:saved?.accepted}});if(rejected)owner.current=null;if(status===401)void vm.api.get('/api/config').catch(()=>{});void resource.reload()};
  const options:StreamChatOptions={basePath:'',context:turn.context,headers:{'X-CSRF-Token':vm.config?.csrf||''},onAccepted:()=>{if(active()){acknowledge(turn);void resource.reload()}}};
  controller.current=streamChat(turn.message,profileId,id,chunk=>{if(active()){setError('');setStream(old=>({...old||emptyStream(),content:(old?.content||'')+chunk}))}},
   verify,fail,
   chunk=>{if(active())setStream(old=>({...old||emptyStream(),thinking:(old?.thinking||'')+chunk}))},
   activity=>{if(active())setStream(old=>({...old||emptyStream(),activity:old?.activity?old.activity+'\n'+activity:activity}))},
   ()=>{if(active())setError('连接中断，正在核对原任务；不会重新发送。')},turn.turnId,resumeOnly,
   ()=>{if(active()){blocked.current.add(turn.turnId);setRunning(false);setError('原任务暂时无法核对，输入与请求标识仍保留。请核对原请求，不要重复发送。');patch({pending:{...turn,state:'unknown',accepted:vm.client.drafts.get<SessionDraft>(key)?.pending?.accepted}})}},turn.attachments,
   question=>{if(active())setStream(old=>({...old||emptyStream(),questions:[...(old?.questions||[]).filter(q=>q.id!==question.id),question]}))},
   note=>{if(active())setStream(old=>({...old||emptyStream(),stillWorking:note}))},
   closed=>{if(active())setStream(old=>({...old||emptyStream(),questions:(old?.questions||[]).filter(q=>q.id!==closed.id)}))},options);
 };
 useEffect(()=>{const pendingId=session?.pendingTurnId||draft.pending?.turnId;if(!session||!pendingId||owner.current||blocked.current.has(pendingId)||completed.current.has(pendingId)||draft.pending?.state==='rejected')return;
  const saved=draft.pending?.turnId===pendingId?draft.pending:{turnId:pendingId,message:'',attachments:[],context:{profile_id:profileId},inputs:{text:'',files:[]},state:'accepted' as const};
  connect(saved,true);
 },[resource.data,id]);
 useEffect(()=>()=>{owner.current=null;controller.current?.abort()},[id]);
 const submit=()=>void action.run(async()=>{
  if(!session)throw Error('会话尚未读回，输入已保留');if(owner.current||running||session.pendingTurnId)throw Error('原任务仍在进行，请先查看原回执');
  const pending=vm.client.drafts.get<SessionDraft>(key)?.pending;if(pending&&pending.state!=='rejected')throw Error('原请求结果尚未核对，不能重复发送');
  const uploads=await vm.service.uploadFiles(draft.files),bindVersion=versionContext&&(!draft.command||['change','review','discuss'].includes(draft.command.action_id)),context:JsonRecord={profile_id:profileId,...(bindVersion&&!draft.command?{action_id:'discuss'}:{}),...(draft.article_mode&&!bindVersion?{article_mode:draft.article_mode}:{}),...(draft.article_id?{article_id:draft.article_id}:{}),...(draft.command?{skill_id:draft.command.skill_id,version:draft.command.version,action_id:draft.command.action_id,...(draft.command.trial?{trial:true}:{})}:{}),...(bindVersion?{work_id:workId,parent_version_id:parentVersion}:{})};
  const turn:FrozenTurn={turnId:crypto.randomUUID(),message:draft.text,attachments:uploads.map(file=>({id:file.id,name:file.name,path:file.id})),context,inputs:{text:draft.text,files:draft.files,command:draft.command,...(draft.article_id?{article_id:draft.article_id}:{}),...(draft.article_mode?{article_mode:draft.article_mode}:{})},state:'connecting'};
  if(draft.command?.requires_plan){const result=await vm.api.post<JsonRecord>('/api/chat/plan',{message:turn.message,sessionId:id,turnId:turn.turnId,attachments:turn.attachments,context},vm.config?.csrf||'');if(!result.plan_token)throw Error('制作方案未返回冻结凭据，输入仍保留');connect({...turn,context:{...context,plan_token:result.plan_token}});}
  else connect(turn);
 });
 const stop=()=>void action.run(async()=>{const turn=vm.client.drafts.get<SessionDraft>(key)?.pending;if(!turn)return;const result=await vm.api.post<JsonRecord>('/api/chat/stop',{sessionId:id,turnId:turn.turnId},vm.config?.csrf||'');if(result.stopped!==true)throw Error('尚未确认原任务已经停止，请继续核对回执');controller.current?.abort();owner.current=null;setRunning(false);completed.current.add(turn.turnId);patch({pending:undefined});await resource.reload()});
 const activeTurn=draft.pending?.turnId||session?.pendingTurnId,shown:ChatSession=session?{...session,messages:(session.messages||[]).filter(message=>!(running&&message.role==='assistant'&&(record(message).turnId===activeTurn||record(message).id===activeTurn)))}:{id,title:'对话',messages:[],created:0};
 const selected=draft.command?{id:draft.command.skill_id+':'+draft.command.action_id,label:draft.command.label+' · v'+draft.command.version}:undefined;
 const unknown=!!draft.pending&&['connecting','accepted','unknown'].includes(draft.pending.state),busy=running||!!session?.pendingTurnId;
 return <div className="ew-chat-layout"><ChatPage apiDirect={false} session={shown} stream={running&&accepted?stream:undefined} onSend={submit} onStop={stop} onResend={()=>{}} canResend={()=>false} linkifyArtifactPaths={false} renderMessageExtra={message=><NativeTurnOutputs message={message}/>}
  questionServices={{answer:payload=>vm.api.post('/api/chat/question/answer',payload,vm.config?.csrf||''),status:async questionIds=>vm.api.post<JsonRecord>('/api/chat/question/status',{questionIds},vm.config?.csrf||'').then(value=>record(value.questions) as Record<string,{status:string}>).catch(()=>({}))}}
  onQuestionAnswered={questionId=>{setStream(old=>old?{...old,questions:old.questions.filter(question=>question.id!==questionId)}:old);void resource.reload()}}
  onQuestionClosed={questionId=>setStream(old=>old?{...old,questions:old.questions.filter(question=>question.id!==questionId)}:old)}
  composer={{text:draft.text,attachments:draft.files.map(file=>({id:file.id,name:file.name,path:file.id})),onTextChange:text=>patch({text}),onUpload:async files=>patch({files:await vm.service.attach(files,draft.files)}),onRemoveAttachment:fileId=>patch({files:draft.files.filter(file=>file.id!==fileId)}),commands:choices,selectedCommand:selected,
   onCommandSelect:(commandId,text)=>{const command=choices.find(choice=>choice.id===commandId)?.selection||null,target=command&&nativeSkillDestination(command,profileId,versionContext);patch({command:target?null:command,...(text!==undefined?{text}:{})});if(target)vm.navigate(target)},disabled:busy||unknown||!session,busy:action.busy,canSend:!!(draft.text.trim()||draft.files.length),label:'对话输入',placeholder:'说说你的想法，输入 / 或点 + 选择技能…',sendLabel:'发送',status:busy?'原生会话正在执行':unknown?'原请求结果待核对':'Enter 发送 · / 选择技能',registerLayer:vm.navigation.registerLayer}}
  emptyState={{brand:'创作工作台',icon:<IconSkills size={32}/>,subtitle:'先聊创作目标，或用 / 和 + 选择技能。制作、采纳和发布各自核对授权。',suggestions:[]}}
  notice={<>{draft.article_id&&<div className="chat-task-status"><span>本轮带入所选新闻的原始来源</span><button className="btn btn-sm" onClick={()=>vm.navigate('/news/a/'+encodeURIComponent(draft.article_id!))}>查看来源</button><button className="btn btn-ghost btn-sm" onClick={()=>patch({article_id:undefined})}>移除本轮来源绑定</button></div>}{versionContext&&<div className="chat-task-status"><p>{draft.command&&['poster','article'].includes(draft.command.action_id)?'本轮将新建作品，原作品与版本保留。':'本轮围绕选定作品版本讨论或修改。'}</p><button className="btn btn-sm" onClick={()=>vm.navigate(workPath({id:workId},parentVersion))}>打开所选版本</button></div>}<Notice message={resource.error||catalog.error||action.error||error}/>{unknown&&!running&&<button className="btn" onClick={()=>{if(draft.pending){blocked.current.delete(draft.pending.turnId);connect(draft.pending,true)}}}>核对原请求</button>}</>}
  footer={array<JsonRecord>(resource.data?.linked_works||session?.linked_works).length?<div className="chat-linked-works">{array<JsonRecord>(resource.data?.linked_works||session?.linked_works).map(link=><button className="btn btn-sm" key={string(link.work_id)+string(link.version_id||link.job_id)} onClick={()=>vm.navigate(workPath({id:string(link.work_id),format:string(link.format)},string(link.version_id||link.job_id)))}>{string(link.title)||'打开关联作品'}{link.version_label?' · '+string(link.version_label):''}</button>)}</div>:undefined}/>
  </div>;
}
