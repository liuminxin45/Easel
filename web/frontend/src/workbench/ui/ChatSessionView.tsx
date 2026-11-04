import {ChatTurnProducts,productArtifacts} from './ChatTurnProducts';
import {useCallback,useEffect,useRef,useMemo} from 'react';
import {useStore} from 'zustand';
import {sessionRuntime,type FrozenTurn,type SessionDraft} from './chatRuntime';
import ChatPage,{type ChatCommand,type ChatViewState} from '../../components/ChatPage';
import {type SkillItem} from '../../lib/api';
import {generateSessionTitle,type ChatSession} from '../../lib/store';
import type {Artifact as ChatArtifact} from '../../lib/artifacts';
import {CAPABILITY_MENU} from '../../lib/capabilityMenu';
import {displayName} from '../../lib/skillDisplayNames';
import {nativeContinuationPath,workProductionRecovery,type Work,array,record,string,type JsonRecord} from '@workbench/core';
import {useWorkbench,useResource,useDraft,useAsyncAction,useViewState} from './hooks';
import {Notice} from './common';
import {ExtensionDetails} from './ExtensionDetails';
import {nativeAsset} from './lib/nativeAsset';

export type NativeSkill=SkillItem;
export interface NativeSelection {skill_id:string;version?:number;action_id:string;requires_plan:boolean;label:string;trial?:boolean;path?:string;task?:string;source_revision?:string}
export interface NativeSession extends ChatSession {runtime?:string;execution_settings?:JsonRecord;profile_id?:string;source_article_id?:string;revision?:number;message_count?:number;linked_works?:JsonRecord[];pendingSubmissionId?:string|null}
export interface NativeSessions {sessions:NativeSession[]}
interface HistoryPage {has_more:boolean;next_before:string|null;before?:string|null;limit:number}
export function nativeSkillChoices(skills:NativeSkill[],_versionContext=false):(ChatCommand&{selection:NativeSelection})[]{
 return skills.map(skill=>{
  const id=skill.name,position=CAPABILITY_MENU.tabs.flatMap(tab=>tab.groups.flatMap(group=>group.items.filter(item=>item.skill===id).map(item=>({tab,group,item}))))[0],fallback=CAPABILITY_MENU.tabs.find(tab=>tab.id===(['discover','publish','attribute'].includes(skill.layer||'')?'operate':'make'))!,label=position?.item.label||displayName(skill.name);
  return {id:id+':native',label,prompt:`帮我做「${label}」`,tab:position?.tab.id||fallback.id,tabLabel:position?.tab.label||fallback.label,group:position?.group.label||'其他内置技能',status:skill.needsApi&&!skill.apiConfigured?'need':'ready',description:skill.description,selection:{skill_id:id,action_id:'native',task:'native',label,requires_plan:false}};
 });
}
export function nativeArtifacts(message:unknown):ChatArtifact[]|undefined{const files=productArtifacts(record(message).output_files);return files.length?files:undefined}
export function nativeArtifactPath(message:unknown,path:string,kind:'media'|'library'='media'):string|undefined{const rel=path.replace(/^outputs\//,'');const file=array<JsonRecord>(record(message).output_files).find(file=>string(file.source_path)===rel);return file?(kind==='library'?'#/outputs/__workbench__/'+encodeURIComponent(string(file.id))+'/'+encodeURIComponent(string(file.name)):string(file.url)):undefined}
export function NewsMessageLink({articleId,navigate}:{articleId:string;navigate:(path:string)=>void}){
 const path='/news/a/'+encodeURIComponent(articleId);
 return <div className="ew-news-message-source"><a href={'?path='+encodeURIComponent(path)} onClick={event=>{if(event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;event.preventDefault();navigate(path)}}>这条新闻</a></div>;
}
export function NativeTurnOutputs({message,showContinuation,continuationPath}:{message:unknown;showContinuation?:boolean;continuationPath?:string|null}){return <><ChatTurnProducts message={message} showContinuation={showContinuation} continuationPath={continuationPath}/></>}
/** Bind server-authorized continuation to this view's exact stopped version. */
export function confirmedContinuation(message:unknown,sessionId:string,profileId:string):string|null{
 const value=record(message),work=record(value.work),versionId=string(value.turnId||value.id),workId=string(work.work_id),link=record(record(value.business_recovery).continuation);
 if(string(value.status)!=='stopped'||!versionId||!workId||string(work.version_id)!==versionId||string(link.session_id)!==sessionId||string(link.profile_id)!==profileId)return null;
 return nativeContinuationPath(value.business_recovery,workId,versionId);
}
export function ChatSessionView({id,search}:{id:string;search:URLSearchParams}){
 const vm=useWorkbench(),historyBefore=search.get('history_before')||'',historyQuery=new URLSearchParams({limit:'50',...(historyBefore?{before:historyBefore}:{})});
 const resource=useResource<{session:NativeSession;linked_works?:JsonRecord[];history_page?:HistoryPage}>('/api/chat/sessions/'+encodeURIComponent(id)+'?'+historyQuery,{interval:historyBefore?undefined:3000}),catalog=useResource<NativeSkill[]>('/api/skills');
 const viewState=useViewState<ChatViewState>('chat-view:'+id,{top:0,following:true});
 const onContentReady=useCallback(()=>{if(resource.data?.session)vm.navigation.contentReady?.({entryId:vm.navigation.entryKey})},[resource.data?.session,vm.navigation.entryKey,vm.navigation.contentReady]);
 const key='chat:'+id,[draft,patch]=useDraft<SessionDraft>(key,{text:'',files:[]}),action=useAsyncAction();
 const runtime=useMemo(()=>sessionRuntime(vm.client,id),[vm.client,id,vm.client.authenticationEpoch]),{stream,running,accepted,error,feedback}=useStore(runtime.state);
 const applied=useRef(''),repair=useRef('');
 const session=resource.data?.session,profileId=session?.profile_id||session?.persona||search.get('profile')||'oil-pig',workId=search.get('work')||'',parentVersion=search.get('version')||'',versionContext=!!workId&&!!parentVersion,choices=session?.runtime==='api'?[]:nativeSkillChoices(catalog.data||[],versionContext);
 const continuationIdle=!running&&!session?.pendingTurnId&&!session?.pendingSubmissionId&&!(draft.pending&&['connecting','accepted','unknown'].includes(draft.pending.state));
 const lastAssistant=session?.messages.filter(message=>message.role==='assistant').at(-1),lastTurn=string(record(lastAssistant).turnId||record(lastAssistant).id);
 const continuationWork=useResource<Work>(search.get('continue')==='1'&&workId&&parentVersion?'/api/works/'+encodeURIComponent(workId)+'/versions/'+encodeURIComponent(parentVersion)+'/view':null),continuationApplied=useRef('');
 const continuationVersion=continuationWork.data?.versions.find(v=>v.id===parentVersion),continuationPath=continuationWork.data?nativeContinuationPath(workProductionRecovery(continuationWork.data,continuationVersion),workId,parentVersion):null;
 useEffect(()=>{if(search.get('continue')!=='1'||!continuationPath||!session||session.pendingTurnId||draft.pending||continuationApplied.current===search.toString())return;continuationApplied.current=search.toString();runtime.state.setState({error:'',feedback:undefined});if(!draft.text.trim()&&!draft.files.length)patch({text:'请继续完成《'+continuationWork.data!.title+'》，沿用所选版本的原始素材、制作要求和保留文件，完成后另存新版本。'})},[continuationPath,session?.pendingTurnId,draft.pending,search.toString()]);
 useEffect(()=>{if(!catalog.data||applied.current===search.toString()||(!versionContext&&draft.command!==undefined))return;const skill=search.get('skill');
  const selected=choices.find(choice=>choice.selection.skill_id===skill);
  if(selected){applied.current=search.toString();patch({command:{...selected.selection}});}
 },[catalog.data,id,search.toString()]);
 const confirmedStoppedPath=confirmedContinuation(lastAssistant,id,profileId),historicalError=string(record(lastAssistant).business_error);
 useEffect(()=>{if(!historyBefore&&confirmedStoppedPath&&!session?.pendingTurnId)runtime.restoreStopped(lastTurn,historicalError)},[runtime,historyBefore,confirmedStoppedPath,session?.pendingTurnId,lastTurn,historicalError]);
 useEffect(()=>{const pendingId=session?.pendingTurnId||session?.pendingSubmissionId||draft.pending?.turnId;if(!session||!pendingId||runtime.state.getState().running||runtime.blocked.has(pendingId)||runtime.completed.has(pendingId)||draft.pending?.state==='rejected')return;
  const saved=draft.pending?.turnId===pendingId?draft.pending:{turnId:pendingId,message:'',attachments:[],context:{profile_id:profileId},inputs:{text:'',files:[]},state:'accepted' as const};
  runtime.connect(saved,profileId,true);
 },[resource.data,id,runtime]);
 useEffect(()=>{const first=session?.messages.find(message=>message.role==='user');if(historyBefore||resource.data?.history_page?.has_more||!session||!first||!['新对话','New Chat'].includes(session.title)||session.pendingTurnId||repair.current===session.id)return;
  repair.current=session.id;void vm.api.post('/api/chat/sessions',{action:'auto-title',session_id:id,operation_id:crypto.randomUUID(),expected_revision:session.revision,title:generateSessionTitle(first.content)},vm.config?.csrf||'').then(()=>vm.client.invalidate(['chat'])).catch(()=>{});
 },[session?.id,session?.revision]);
 const readOnly=!!session?.archived||!!record(session).deleted_at;
 const submit=()=>void action.run(async()=>{
  if(readOnly)throw Error('此对话已归档或删除，仅可查看；输入已保留。');
  if(historyBefore)throw Error('请返回最新消息后继续输入；当前草稿已保留。');
  if(!session)throw Error('会话尚未读回，输入已保留');if(search.get('continue')==='1'&&!continuationPath)throw Error('中断版本的恢复状态尚未核对，请返回成品页重新读取');if(runtime.state.getState().running||session.pendingTurnId||session.pendingSubmissionId)throw Error('原任务仍在进行，请先查看原回执');
  const pending=vm.client.drafts.get<SessionDraft>(key)?.pending;if(pending&&pending.state!=='rejected')throw Error('原请求结果尚未核对，不能重复发送');
  const articleId=draft.article_id||session.source_article_id,uploads=await vm.service.uploadFiles(draft.files),context:JsonRecord={profile_id:profileId,...(draft.article_mode?{article_mode:draft.article_mode}:{}),...(articleId?{article_id:articleId}:{}),...(draft.creation?{creation:draft.creation,...(draft.creation.intent==='produce'?{skill_id:'content-production',action_id:'native'}:{})}:draft.command?{skill_id:draft.command.skill_id,action_id:'native'}:{})};
  const turn:FrozenTurn={turnId:crypto.randomUUID(),message:draft.text,attachments:uploads.map(file=>({id:file.id,name:file.name,path:file.id})),context,inputs:{text:draft.text,files:draft.files,command:draft.command,...(draft.article_id?{article_id:draft.article_id}:{}),...(draft.article_mode?{article_mode:draft.article_mode}:{}),...(draft.creation?{creation:draft.creation}:{})},state:'connecting',initial_title:generateSessionTitle(draft.text)};
  await runtime.submit(turn,profileId);
 });
 const stop=()=>void action.run(()=>runtime.stop());
 const retry=(index:number)=>void action.run(async()=>{
  if(readOnly)throw Error('此对话已归档或删除，仅可查看；输入已保留。');
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
  turn.inputs={text:'',files:[]};await runtime.submit(turn,profileId);
 });
 const activeTurn=draft.pending?.turnId||session?.pendingTurnId||session?.pendingSubmissionId;
 // Draft edits and identical polling replies must not retrigger the native
 // ChatPage's new-message scroll effect. API history is plain JSON.
 const historyJson=useMemo(()=>JSON.stringify(session?.messages||[]),[session?.messages]);
 const visibleMessages=useMemo(()=>
  {const messages=(JSON.parse(historyJson) as ChatSession['messages']).map(message=>{const path=string(record(message).library_path);return message.role==='assistant'&&path?{...message,content:message.content+'\n\n[内容库 › 本版产物](#/outputs/'+path.split('/').map(encodeURIComponent).join('/')+')'}:message}).filter(message=>!((running||!!session?.pendingTurnId||!!session?.pendingSubmissionId)&&message.role==='assistant'&&(record(message).turnId===activeTurn||record(message).id===activeTurn)));
  const pending=draft.pending;if(!historyBefore&&pending?.accepted&&!messages.some(message=>record(message).id===pending.turnId+'-user'))messages.push({id:pending.turnId+'-user',role:'user',content:pending.message,timestamp:'',attachments:pending.attachments,article_id:pending.context.article_id} as ChatSession['messages'][number]);return messages;},
  [historyJson,session?.id,running,session?.pendingTurnId,session?.pendingSubmissionId,activeTurn,draft.pending?.accepted,historyBefore]);
 const shown:ChatSession=session?{...session,messages:visibleMessages}:{id,title:'对话',messages:visibleMessages,created:0};
 const selected=draft.command?{id:draft.command.skill_id+':'+draft.command.action_id,label:draft.command.label}:undefined;
 const unknown=!!draft.pending&&['connecting','accepted','unknown'].includes(draft.pending.state),busy=running||!!session?.pendingTurnId||!!session?.pendingSubmissionId;
 const historyPath=(before?:string)=>{const query=new URLSearchParams(search);if(before)query.set('history_before',before);else query.delete('history_before');return '/chat/'+encodeURIComponent(id)+(query.size?'?'+query:'')};
 return <div className="ew-chat-layout"><ChatPage viewState={viewState} onContentReady={onContentReady} apiDirect={session?.runtime==='api'} session={shown} stream={!historyBefore&&running&&accepted?stream:undefined} onSend={submit} onStop={stop} onResend={index=>retry(index)} canResend={(message,index)=>!readOnly&&!historyBefore&&!busy&&!unknown&&!record(session?.messages[index+1]).work&&!record(record(session?.messages[index+1]).business_receipt).work_id} resolveArtifactPath={nativeArtifactPath} messageArtifacts={nativeArtifacts} renderMessageExtra={message=>message.role==='assistant'?<NativeTurnOutputs message={message} continuationPath={continuationIdle?confirmedContinuation(message,id,profileId):null} showContinuation={!readOnly&&!historyBefore&&!(search.get('continue')==='1'&&string(record(message).turnId||record(message).id)===parentVersion)}/>:string(record(message).article_id)?<NewsMessageLink articleId={string(record(message).article_id)} navigate={vm.navigate}/>:null}
  questionServices={{answer:payload=>runtime.answer(payload),status:ids=>runtime.status(ids)}}
  onQuestionAnswered={questionId=>{runtime.closeQuestion(questionId);void resource.reload()}}
  onQuestionClosed={questionId=>runtime.closeQuestion(questionId)}
  composer={{text:draft.text,attachments:draft.files.map(file=>({id:file.id,name:file.name,path:file.id})),onTextChange:text=>patch({text,...(draft.creation?{creation:{...draft.creation,note:text}}:{})}),onUpload:async files=>patch({files:await vm.service.attach(files,draft.files)}),onRemoveAttachment:fileId=>patch({files:draft.files.filter(file=>file.id!==fileId)}),commands:choices,selectedCommand:selected,
   onCommandSelect:(commandId,text)=>{const command=choices.find(choice=>choice.id===commandId)?.selection||null;patch({command,creation:undefined,...(text!==undefined?{text}:{})})},disabled:readOnly||!!historyBefore||busy||unknown||!session||(search.get('continue')==='1'&&!continuationPath),busy:action.busy,canSend:!readOnly&&!historyBefore&&!!(draft.text.trim()||draft.files.length),label:'对话输入',placeholder:readOnly?'此对话仅可查看；输入仍保留在本机':historyBefore?'查看历史消息；返回最新消息后可继续输入':'说说你的想法，输入 / 或点画笔选择技能…',sendLabel:'发送',registerLayer:vm.navigation.registerLayer}}
  emptyState={{icon:<img src={nativeAsset('static/easel-icon-transparent.png')} alt=""/>}}
  notice={<><Notice sources={[resource,catalog,action,{error,feedback:feedback||(!busy&&unknown?{kind:'status',message:'正在恢复原任务状态，输入已保留。'}:undefined)}]}/>{(resource.data?.history_page?.has_more||historyBefore)&&<div className="ew-row">{resource.data?.history_page?.next_before&&<button className="btn btn-sm" onClick={()=>vm.navigate(historyPath(resource.data!.history_page!.next_before!),{intent:'object'})}>查看更早消息</button>}{historyBefore&&<button className="btn btn-sm" onClick={()=>vm.navigate(historyPath(),{intent:'object'})}>返回最新消息</button>}</div>}</>}
  footer={<>
   {(draft.article_id||versionContext)&&<ExtensionDetails className="ew-composer-context" title={search.get('continue')==='1'?'继续制作 · 已选原版本':versionContext?'已选作品版本':'已选新闻素材'}>
    {draft.article_id&&<div className="ew-row"><button className="btn btn-sm" onClick={()=>vm.navigate('/news/a/'+encodeURIComponent(draft.article_id!))}>查看来源</button><button className="btn btn-ghost btn-sm" onClick={()=>patch({article_id:undefined,creation:undefined})}>移除本轮来源绑定</button></div>}
    {versionContext&&<><p>{search.get('continue')==='1'?'发送后基于所选版本继续制作，结果另存新版本。':draft.command&&['poster','article'].includes(draft.command.action_id)?'本轮将新建作品，原作品与版本保留。':'本轮围绕选定作品版本讨论或修改。'}</p><a href={"#/outputs/"+encodeURIComponent("workbench-"+workId)+"/"+encodeURIComponent(parentVersion)}>内容库 › 所选版本</a></>}
   </ExtensionDetails>}

  </>}/>
  </div>;
}
