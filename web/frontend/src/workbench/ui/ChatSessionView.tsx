import {ChatTurnProducts,productArtifacts} from './ChatTurnProducts';
import React,{useEffect,useRef,useMemo} from 'react';
import {useStore} from 'zustand';
import {sessionRuntime,type FrozenTurn,type SessionDraft} from './chatRuntime';
import ChatPage,{type ChatCommand} from '../../components/ChatPage';
import {type SkillItem} from '../../lib/api';
import {generateSessionTitle,type ChatSession} from '../../lib/store';
import type {Artifact as ChatArtifact} from '../../lib/artifacts';
import {CAPABILITY_MENU} from '../../lib/capabilityMenu';
import {nativeContinuationPath,workProductionRecovery,type Work,useWorkbench,useResource,useDraft,useAsyncAction,array,record,string,workPath,type DraftAttachment,type JsonRecord,fileDownload,type Artifact} from '@workbench/core';
import {Notice} from './common';
import {IconSkills} from './components/icons';

export interface NativeSkill extends SkillItem {id?:string;skill_id?:string;display_name?:string;origin?:string;source_revision?:string;version:number;available?:boolean;reason?:string;execution_kind?:string;launch_actions?:{id:string;label:string;task?:string;format?:string;requires_plan?:boolean;requires_context?:boolean;path?:string}[]}
export interface NativeSelection {skill_id:string;version:number;action_id:string;requires_plan:boolean;label:string;trial?:boolean;path?:string;task?:string;source_revision?:string}
export interface NativeSession extends ChatSession {runtime?:string;execution_settings?:JsonRecord;profile_id?:string;revision?:number;message_count?:number;linked_works?:JsonRecord[]}
export interface NativeSessions {sessions:NativeSession[]}
export function nativeSkillChoices(skills:NativeSkill[],versionContext=false):(ChatCommand&{selection:NativeSelection})[]{
 const choices=skills.flatMap(skill=>(skill.launch_actions||[]).filter(action=>Number.isSafeInteger(skill.version)&&skill.version>0&&(!action.requires_context||versionContext||!!action.path)).map(action=>{
  const id=skill.skill_id||skill.id||skill.name,workflow=skill.execution_kind==='workflow'||id==='content-production';
  const position=CAPABILITY_MENU.tabs.flatMap(tab=>tab.groups.flatMap(group=>group.items.filter(item=>item.skill===id).map(item=>({tab,group,item}))))[0];
  const native=skill.origin==='easel',label=native?(position?.item.label||skill.display_name||skill.name):workflow&&action.task==='poster'?'生成贴图':workflow&&action.task==='article'?'撰写文章':(skill.display_name||skill.name)+' · '+action.label;
  const fallback=CAPABILITY_MENU.tabs.find(tab=>tab.id===(['discover','publish','attribute'].includes(skill.layer||'')?'operate':'make'))!;
  return {id:id+':'+action.id,label,...(native?{prompt:`帮我做「${label}」`}:{}),tab:native?(position?.tab.id||fallback.id):'extensions',tabLabel:native?(position?.tab.label||fallback.label):'工作台扩展',group:native?(position?.group.label||'其他内置技能'):(skill.display_name||skill.name),status:skill.needsApi&&!skill.apiConfigured?'need':'ready',description:skill.description||skill.reason,disabled:skill.available===false,selection:{skill_id:id,version:skill.version,action_id:action.id,label,...(native?{source_revision:skill.source_revision}:{}),...(action.path?{path:action.path}:{}),task:action.task,requires_plan:action.requires_plan??['poster','article','image','change'].includes(action.task||action.format||'')}};
 }));
 const order=CAPABILITY_MENU.tabs.flatMap(tab=>tab.groups.flatMap(group=>group.items.map(item=>item.skill))).filter(Boolean);
 return choices.sort((a,b)=>{const ai=order.indexOf(a.selection.skill_id),bi=order.indexOf(b.selection.skill_id);return (a.tab==='extensions'?10000:ai<0?9999:ai)-(b.tab==='extensions'?10000:bi<0?9999:bi)});
}
export function nativeSkillDestination(selection:NativeSelection,profileId:string,versionContext=false):string|null{
 if(['poster','article','discuss','native'].includes(selection.task||selection.action_id)||(versionContext&&['change','review'].includes(selection.task||selection.action_id)))return null;
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
export function nativeArtifacts(message:unknown):ChatArtifact[]{return productArtifacts(record(message).output_files)}
export function NativeTurnOutputs({message,showContinuation}:{message:unknown;showContinuation?:boolean}){return <ChatTurnProducts message={message} showContinuation={showContinuation}/>}
/** Bind server-authorized continuation to this view's exact stopped version. */
export function confirmedContinuation(message:unknown,sessionId:string,profileId:string):string|null{
 const value=record(message),work=record(value.work),versionId=string(value.turnId||value.id),workId=string(work.work_id),link=record(record(value.business_recovery).continuation);
 if(string(value.status)!=='stopped'||!versionId||!workId||string(work.version_id)!==versionId||string(link.session_id)!==sessionId||string(link.profile_id)!==profileId)return null;
 return nativeContinuationPath(value.business_recovery,workId,versionId);
}
export function ChatSessionView({id,search}:{id:string;search:URLSearchParams}){
 const vm=useWorkbench(),resource=useResource<{session:NativeSession;linked_works?:JsonRecord[]}>('/api/chat/sessions/'+encodeURIComponent(id),{interval:3000}),catalog=useResource<NativeSkill[]>('/api/skills');
 const key='chat:'+id,[draft,patch]=useDraft<SessionDraft>(key,{text:'',files:[]}),action=useAsyncAction();
 const runtime=useMemo(()=>sessionRuntime(vm.client,id),[vm.client,id,vm.client.authenticationEpoch]),{stream,running,accepted,error,feedback}=useStore(runtime.state);
 const applied=useRef(''),repair=useRef('');
 const session=resource.data?.session,profileId=session?.profile_id||session?.persona||search.get('profile')||'oil-pig',workId=search.get('work')||'',parentVersion=search.get('version')||'',versionContext=!!workId&&!!parentVersion,choices=session?.runtime==='api'?[]:nativeSkillChoices(catalog.data||[],versionContext);
 const continuationIdle=!running&&!session?.pendingTurnId&&!(draft.pending&&['connecting','accepted','unknown'].includes(draft.pending.state));
 const lastAssistant=session?.messages.filter(message=>message.role==='assistant').at(-1),lastTurn=string(record(lastAssistant).turnId||record(lastAssistant).id);
 const interruptedPath=continuationIdle?confirmedContinuation(lastAssistant,id,profileId):null,showInterruptedAction=!!interruptedPath&&search.get('continue')!=='1';
 useEffect(()=>{if(session)vm.navigation.contentReady?.()},[session,vm.navigation.contentReady]);
 const continuationWork=useResource<Work>(search.get('continue')==='1'&&workId?'/api/works/'+encodeURIComponent(workId):null),continuationApplied=useRef('');
 const continuationVersion=continuationWork.data?.versions.find(v=>v.id===parentVersion),continuationPath=continuationWork.data?nativeContinuationPath(workProductionRecovery(continuationWork.data,continuationVersion),workId,parentVersion):null;
 useEffect(()=>{if(search.get('continue')!=='1'||!continuationPath||!session||session.pendingTurnId||draft.pending||continuationApplied.current===search.toString())return;continuationApplied.current=search.toString();runtime.state.setState({error:'',feedback:undefined});if(!draft.text.trim()&&!draft.files.length)patch({text:'请继续完成《'+continuationWork.data!.title+'》，沿用所选版本的原始素材、制作要求和保留文件，完成后另存新版本。'})},[continuationPath,session?.pendingTurnId,draft.pending,search.toString()]);
 useEffect(()=>{if(!catalog.data||applied.current===search.toString()||(!versionContext&&draft.command!==undefined))return;const skill=search.get('skill'),version=Number(search.get('skill_version')),actionId=search.get('action');
  const selected=choices.find(choice=>choice.selection.skill_id===skill&&(!actionId||choice.selection.action_id===actionId));
  if(selected){applied.current=search.toString();patch({command:{...selected.selection,...(Number.isSafeInteger(version)&&version>0?{version}:{}),...(search.get('trial')==='1'?{trial:true}:{})}});}
 },[catalog.data,id,search.toString()]);
 const confirmedStoppedPath=confirmedContinuation(lastAssistant,id,profileId),historicalError=string(record(lastAssistant).business_error);
 useEffect(()=>{if(confirmedStoppedPath&&!session?.pendingTurnId)runtime.restoreStopped(lastTurn,historicalError)},[runtime,confirmedStoppedPath,session?.pendingTurnId,lastTurn,historicalError]);
 useEffect(()=>{const pendingId=session?.pendingTurnId||draft.pending?.turnId;if(!session||!pendingId||runtime.state.getState().running||runtime.blocked.has(pendingId)||runtime.completed.has(pendingId)||draft.pending?.state==='rejected')return;
  const saved=draft.pending?.turnId===pendingId?draft.pending:{turnId:pendingId,message:'',attachments:[],context:{profile_id:profileId},inputs:{text:'',files:[]},state:'accepted' as const};
  runtime.connect(saved,profileId,true);
 },[resource.data,id,runtime]);
 useEffect(()=>{const first=session?.messages.find(message=>message.role==='user');if(!session||!first||!['新对话','New Chat'].includes(session.title)||session.pendingTurnId||repair.current===session.id)return;
  repair.current=session.id;void vm.api.post('/api/chat/sessions',{action:'auto-title',session_id:id,operation_id:crypto.randomUUID(),expected_revision:session.revision,title:generateSessionTitle(first.content)},vm.config?.csrf||'').then(()=>vm.client.invalidate(['chat'])).catch(()=>{});
 },[session?.id,session?.revision]);
 const submit=()=>void action.run(async()=>{
  if(!session)throw Error('会话尚未读回，输入已保留');if(search.get('continue')==='1'&&!continuationPath)throw Error('中断版本的恢复状态尚未核对，请返回成品页重新读取');if(runtime.state.getState().running||session.pendingTurnId)throw Error('原任务仍在进行，请先查看原回执');
  const pending=vm.client.drafts.get<SessionDraft>(key)?.pending;if(pending&&pending.state!=='rejected')throw Error('原请求结果尚未核对，不能重复发送');
  const uploads=await vm.service.uploadFiles(draft.files),bindVersion=versionContext&&(!draft.command||['change','review','discuss'].includes(draft.command.action_id)),context:JsonRecord={profile_id:profileId,...(bindVersion&&!draft.command?{action_id:'discuss'}:{}),...(draft.article_mode&&!bindVersion?{article_mode:draft.article_mode}:{}),...(draft.article_id?{article_id:draft.article_id}:{}),...(draft.command?{skill_id:draft.command.skill_id,version:draft.command.version,action_id:draft.command.action_id,...(draft.command.source_revision?{skill_revision:draft.command.source_revision}:{}),...(draft.command.trial?{trial:true}:{})}:{}),...(bindVersion?{work_id:workId,parent_version_id:parentVersion}:{})};
  const turn:FrozenTurn={turnId:crypto.randomUUID(),message:draft.text,attachments:uploads.map(file=>({id:file.id,name:file.name,path:file.id})),context,inputs:{text:draft.text,files:draft.files,command:draft.command,...(draft.article_id?{article_id:draft.article_id}:{}),...(draft.article_mode?{article_mode:draft.article_mode}:{})},state:'connecting',initial_title:generateSessionTitle(draft.text)};
  if(draft.command?.requires_plan){const result=await vm.api.post<JsonRecord>('/api/chat/plan',{message:turn.message,sessionId:id,turnId:turn.turnId,attachments:turn.attachments,context},vm.config?.csrf||'');if(!result.plan_token)throw Error('制作方案未返回冻结凭据，输入仍保留');runtime.connect({...turn,context:{...context,plan_token:result.plan_token}},profileId);}
  else runtime.connect(turn,profileId);
 });
 const stop=()=>void action.run(()=>runtime.stop());
 const retry=(index:number)=>void action.run(async()=>{
  if(!session||busy||unknown)throw Error('请先核对原回合');
  const message=session.messages[index],reply=record(session.messages[index+1]);
  if(!message||message.role!=='user'||record(reply.work).work_id||record(reply.business_receipt).work_id)throw Error('作品重新制作请在成品页发起');
  const original=await vm.api.get<JsonRecord>('/api/chat/last/'+encodeURIComponent(id)+'?turn_id='+encodeURIComponent(string(reply.turnId||reply.id)));
  if(!['completed','failed','stopped'].includes(string(original.execution_status))||original.delivery_state==='unknown'||record(original.work).work_id)throw Error('原回合仍需核对，不能重发');
  const refs=array<JsonRecord>(original.skill_refs);if(!refs.length)throw Error('原技能版本尚未核对，不能重发');
  const context:JsonRecord={...record(original.context),skill_id:string(refs[0]!.id),version:refs[0]!.version};delete context.plan_token;
  const turn:FrozenTurn={turnId:crypto.randomUUID(),message:message.content,attachments:message.attachments||[],context,inputs:{text:draft.text,files:draft.files,command:draft.command},state:'connecting'};
  // Retry is an explicit new conversational turn, not an implicit production action.
  if(!['discuss','','native'].includes(string(turn.context.action_id)))throw Error('请在成品页恢复原任务或显式选择制作技能');
  turn.inputs={text:'',files:[]};runtime.connect(turn,profileId);
 });
 const activeTurn=draft.pending?.turnId||session?.pendingTurnId;
 // Draft edits and identical polling replies must not retrigger the native
 // ChatPage's new-message scroll effect. API history is plain JSON.
 const historyJson=useMemo(()=>JSON.stringify(session?.messages||[]),[session?.messages]);
 const visibleMessages=useMemo(()=>
  (JSON.parse(historyJson) as ChatSession['messages']).filter(message=>!((running||!!session?.pendingTurnId)&&message.role==='assistant'&&(record(message).turnId===activeTurn||record(message).id===activeTurn))),
  [historyJson,session?.id,running,session?.pendingTurnId,activeTurn]);
 const shown:ChatSession=session?{...session,messages:visibleMessages}:{id,title:'对话',messages:visibleMessages,created:0};
 const selected=draft.command?{id:draft.command.skill_id+':'+draft.command.action_id,label:draft.command.label+' · v'+draft.command.version}:undefined;
 const unknown=!!draft.pending&&['connecting','accepted','unknown'].includes(draft.pending.state),busy=running||!!session?.pendingTurnId;
 return <div className="ew-chat-layout" ref={element=>{element?.querySelector('.chat-messages')?.setAttribute('data-native-scroll-region','chat-messages')}}><ChatPage apiDirect={session?.runtime==='api'} session={shown} stream={running&&accepted?stream:undefined} onSend={submit} onStop={stop} onResend={index=>retry(index)} canResend={(message,index)=>!busy&&!unknown&&!record(session?.messages[index+1]).work&&!record(record(session?.messages[index+1]).business_receipt).work_id} linkifyArtifactPaths={false} messageArtifacts={nativeArtifacts} renderMessageExtra={message=><NativeTurnOutputs message={message} showContinuation={!!(continuationIdle&&confirmedContinuation(message,id,profileId)&&!(interruptedPath&&string(record(message).turnId||record(message).id)===lastTurn))}/>}
  questionServices={{answer:payload=>runtime.answer(payload),status:ids=>runtime.status(ids)}}
  onQuestionAnswered={questionId=>{runtime.closeQuestion(questionId);void resource.reload()}}
  onQuestionClosed={questionId=>runtime.closeQuestion(questionId)}
  composer={{text:draft.text,attachments:draft.files.map(file=>({id:file.id,name:file.name,path:file.id})),onTextChange:text=>patch({text}),onUpload:async files=>patch({files:await vm.service.attach(files,draft.files)}),onRemoveAttachment:fileId=>patch({files:draft.files.filter(file=>file.id!==fileId)}),commands:choices,selectedCommand:selected,
   onCommandSelect:(commandId,text)=>{const command=choices.find(choice=>choice.id===commandId)?.selection||null,target=command&&nativeSkillDestination(command,profileId,versionContext);patch({command:target?null:command,...(text!==undefined?{text}:{})});if(target)vm.navigate(target)},disabled:busy||unknown||!session||(search.get('continue')==='1'&&!continuationPath),busy:action.busy,canSend:!!(draft.text.trim()||draft.files.length),label:'对话输入',placeholder:'说说你的想法，输入 / 或点画笔选择技能…',sendLabel:'发送',status:busy?'原生会话正在执行':unknown?'正在恢复原任务状态，输入已保留':'',registerLayer:vm.navigation.registerLayer}}
  emptyState={{brand:'创作工作台',icon:<IconSkills size={32}/>,subtitle:'先聊创作目标，或用 / 或画笔选择技能。制作、采纳和发布各自核对授权。',suggestions:[]}}
  notice={<>{showInterruptedAction&&<div className="chat-task-status" role="status" aria-label="制作中断"><span>本轮已中断，原文件已保留。</span><button className="btn btn-sm" onClick={()=>vm.navigate(interruptedPath!,{intent:'flow'})}>继续制作</button></div>}{draft.article_id&&<div className="chat-task-status"><span>本轮带入所选新闻的原始来源</span><button className="btn btn-sm" onClick={()=>vm.navigate('/news/a/'+encodeURIComponent(draft.article_id!))}>查看来源</button><button className="btn btn-ghost btn-sm" onClick={()=>patch({article_id:undefined})}>移除本轮来源绑定</button></div>}{search.get('continue')==='1'&&<div className="chat-task-status">本轮接续所选中断版本；确认发送后才开始制作，原文件保留，新结果另存版本。</div>}{versionContext&&<div className="chat-task-status"><p>{draft.command&&['poster','article'].includes(draft.command.action_id)?'本轮将新建作品，原作品与版本保留。':'本轮围绕选定作品版本讨论或修改。'}</p><button className="btn btn-sm" onClick={()=>vm.navigate(workPath({id:workId},parentVersion))}>打开所选版本</button></div>}<Notice sources={[resource,catalog,action,{error,feedback}]}/></>}
  footer={array<JsonRecord>(resource.data?.linked_works||session?.linked_works).length?<div className="chat-linked-works">{array<JsonRecord>(resource.data?.linked_works||session?.linked_works).map(link=><button className="btn btn-sm" key={string(link.work_id)+string(link.version_id||link.job_id)} onClick={()=>vm.navigate(workPath({id:string(link.work_id),format:string(link.format)},string(link.version_id||link.job_id)))}>{string(link.title)||'打开关联作品'}{link.version_label?' · '+string(link.version_label):''}</button>)}</div>:undefined}/>
  </div>;
}
