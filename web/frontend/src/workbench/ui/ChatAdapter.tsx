import React from 'react';
import ChatPage,{type ChatCommand} from '../../components/ChatPage';
import type {ChatSession,ChatMessage} from '../../lib/store';
import {IconSkills} from './components/icons';
import {useWorkbench,array,string,record,statusLabel,type CreatorBootstrap,type DraftAttachment,type HistoryEvent,type Work,type JsonRecord} from '@workbench/core';

export interface SkillCommand {skill_id:string;version:number;action_id:string;task:'poster'|'article'|'discuss';trial?:boolean}
export interface SkillChoice extends ChatCommand {selection:SkillCommand}
export function skillChoices(data:CreatorBootstrap,profileId:string,format?:string):SkillChoice[]{
 const profile=data.profiles.find(p=>p.id===profileId);
 return data.skills.flatMap(skill=>(skill.launch_actions||[]).filter(action=>!action.requires_context&&['poster','article','discuss'].includes(action.task)&&(!format||action.task==='discuss'||action.task===format)&&skill.published_version).map(action=>{
  const version=profile?.task_skill_versions?.[action.task]?.[skill.id]||profile?.skill_versions?.[skill.id]||skill.published_version;
  const label=skill.execution_kind==='workflow'?(action.task==='poster'?'生成贴图':action.task==='article'?'撰写文章':action.label):skill.name+' · '+action.label;
  return {id:skill.id+':'+action.id,label,description:skill.description,selection:{skill_id:skill.id,version,action_id:action.id,task:action.task as SkillCommand['task']}};
 }));
}
export function commandFromSearch(data:CreatorBootstrap,search:URLSearchParams,format:string):SkillCommand|undefined{
 const id=search.get('skill'),version=Number(search.get('skill_version')),skill=data.skills.find(s=>s.id===id);
 if(!skill||!Number.isSafeInteger(version)||version<1)return;
 const task=search.get('mode')==='research'?'discuss':format,action=skill.launch_actions?.find(a=>a.task===task&&!a.requires_context);
 return action?{skill_id:skill.id,version,action_id:action.id,task:task as SkillCommand['task'],trial:search.get('trial')==='1'}:undefined;
}
export function projectWorkChat(work:Work):{session:ChatSession;events:Map<number,HistoryEvent>}{
 const messages:ChatMessage[]=[],events=new Map<number,HistoryEvent>();
 for(const event of work.history.filter(e=>['create','change','discuss','feedback','accept','reject'].includes(e.kind))){
  if(['accept','reject'].includes(event.kind)&&!event.text&&!event.reply)continue;
  const text=event.kind==='create'?(event.input?.material||event.text||work.title):(event.text||statusLabel(event.kind));
  messages.push({role:'user',content:text});let index=messages.length-1;
  if(event.reply){messages.push({role:'assistant',content:event.reply});index=messages.length-1}
  events.set(index,event);
 }
 return {session:{id:work.id,title:work.title,persona:work.creator?.id,messages,created:0},events};
}
export function ChatAdapter({id,title='新对话',work,text,files,onText,onFiles,onSend,choices=[],command,onCommand,busy=false,disabled=false,canSend=true,label='对话输入',sendLabel='发送',status,notice,footer,onOpenVersion}:{
 id:string;title?:string;work?:Work;text:string;files:DraftAttachment[];onText:(text:string)=>void;onFiles:(files:DraftAttachment[])=>void;onSend:()=>void;
 choices?:SkillChoice[];command?:SkillCommand;onCommand?:(command:SkillCommand|null,remainingText?:string)=>void;busy?:boolean;disabled?:boolean;canSend?:boolean;
 label?:string;sendLabel?:string;status?:string;notice?:React.ReactNode;footer?:React.ReactNode;onOpenVersion?:(id:string)=>void;
}){
 const vm=useWorkbench(),projection=work?projectWorkChat(work):{session:{id,title,messages:[],created:0} as ChatSession,events:new Map<number,HistoryEvent>()};
 const selected=command&&choices.find(c=>c.selection.skill_id===command.skill_id&&c.selection.action_id===command.action_id);
 const selectedView=command?{id:command.skill_id+':'+command.action_id,label:(selected?.label||command.skill_id)+' · v'+command.version+(command.trial?' · 本次试用':'')}:undefined;
 return <ChatPage apiDirect={false} session={projection.session} onSend={()=>onSend()} onStop={()=>{}} onResend={()=>{}} canResend={()=>false} linkifyArtifactPaths={false}
  composer={{text,attachments:files.map(file=>({id:file.id,name:file.name,path:file.id})),onTextChange:onText,onUpload:async incoming=>onFiles(await vm.service.attach(incoming,files)),
   onRemoveAttachment:id=>onFiles(files.filter(file=>file.id!==id)),commands:choices,selectedCommand:selectedView,
   onCommandSelect:(id,rest)=>onCommand?.(choices.find(c=>c.id===id)?.selection||null,rest),busy,disabled,canSend,label,sendLabel,status,
   placeholder:'说说你想做什么，输入 / 或点画笔选择技能，可粘贴或拖入素材…',registerLayer:vm.navigation.registerLayer}}
  emptyState={{brand:'创作工作台',icon:<IconSkills size={32}/>,title:work?'继续这份作品':'想创作点什么？',subtitle:work?'材料保留在作品草稿中。继续讨论，或选择当前格式的制作技能；其它格式请新建对话。':'先聊目标，或用 / 或画笔选择生成贴图、撰写文章。发送后开始制作。',suggestions:[]}}
  notice={notice} footer={footer}
  renderMessageExtra={(_,index)=>{const event=projection.events.get(index);if(!event)return null;
   const issue=record(work?.production_issue),error=(issue.job_id===event.id?string(issue.message):'')||string(event.error),pending=['queued','running','dispatching'].includes(event.status),technical=/Traceback|Exception|RuntimeError|FileNotFound|ModuleNotFound|rollout|thread\/|RPC/i.test(error);
   const version=work?.versions.find(v=>v.id===event.id),hasFiles=!!version?.artifacts.length;
   return <div className="chat-task-status" role={error?'alert':'status'}><small>{statusLabel(event.kind)} · {statusLabel(event.status)}{event.candidate_id?' · '+(work?.versions.find(v=>v.id===event.candidate_id)?.label||'原版本'):''}</small>
    {pending&&<p>正在执行，回复会随实际回执更新。</p>}{error&&(technical?<><p>这轮没有完成，任务记录与原输入已保留。请核对原因后恢复原任务。</p><details><summary>查看失败原因</summary><p>{error}</p></details></>:<p>这轮未完成：{error}</p>)}
    {event.status==='needs_desktop'&&<p>这轮需要在原制作会话中处理，当前任务不会自动重发。</p>}
    {hasFiles&&<button className="btn btn-sm" onClick={()=>onOpenVersion?.(event.id)}>查看本版成品</button>}
   </div>;
  }}/>
}
