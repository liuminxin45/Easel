import {useEffect,useRef,useState} from 'react';
import IdeasView,{NEXT} from '../../components/IdeasView';
import type {Idea,IdeaInput} from '../../lib/api';
import {useWorkbench,useResource,useDraft,useAsyncAction,useOperation,string,record,type JsonRecord} from '@workbench/core';
import {Notice} from './common';

interface Topic extends Idea {revision:number;work_id?:string}
const empty:IdeaInput={title:'',note:'',source:'',status:'pending'};
export function NativeIdeas({onUseTopic}:{onUseTopic:(title:string)=>void}){
 const vm=useWorkbench(),resource=useResource<{items:Topic[]}>('/api/easel/topics'),action=useAsyncAction(),operation=useOperation('easel:topics');
 const [draft,patch]=useDraft('easel:topic-form',{form:null as IdeaInput|null,editId:null as string|null,revision:0}),[toast,setToast]=useState('');
 const timer=useRef<ReturnType<typeof setTimeout>|undefined>(undefined),recovery=useRef('');
 useEffect(()=>()=>{clearTimeout(timer.current)},[]);
 useEffect(()=>{if(resource.data)vm.navigation.contentReady?.()},[resource.data]);
 useEffect(()=>{if(!draft.form)return;return vm.navigation.registerLayer?.(()=>patch({form:null,editId:null}))},[!!draft.form]);
 useEffect(()=>{if(operation.pending?.uncertain)recovery.current=operation.pending.id;else if(recovery.current&&!operation.pending){recovery.current='';if(operation.result)patch({form:null,editId:null});void resource.reload()}},[operation.pending,operation.result]);
 const topics=resource.data?.items||[],byStatus:Record<string,Topic[]>={pending:[],doing:[],done:[]};
 for(const topic of topics)(byStatus[topic.status]||byStatus.pending).push(topic);
 const command=(fields:JsonRecord)=>vm.client.mutate('easel:topics','/api/easel/commands',fields);
 const update=(topic:Topic,fields:JsonRecord={})=>command({action:'topic-save',topic_id:topic.id,base_revision:topic.revision,title:topic.title,note:topic.note,source:topic.source,status:topic.status,...fields});
 const busy=action.busy||operation.busy||!!operation.pending;
 const save=()=>void action.run(async()=>{if(!draft.form||busy)return;await command({action:'topic-save',...(draft.editId?{topic_id:draft.editId}:{}),base_revision:draft.revision,...draft.form});patch({form:null,editId:null});void resource.reload()});
 const selected=(idea:Idea)=>topics.find(topic=>topic.id===idea.id)!;
 return <IdeasView byStatus={byStatus} form={draft.form} editId={draft.editId} toast={toast} busy={busy}
  notice={<Notice sources={[resource,action,operation]}/>}
  setForm={form=>{if(!busy)patch({form})}} openNew={()=>{if(!busy)patch({form:{...empty},editId:null,revision:0})}}
  openEdit={idea=>{if(!busy){const topic=selected(idea);patch({form:{title:topic.title,note:topic.note,source:topic.source,status:topic.status},editId:topic.id,revision:topic.revision})}}} save={save}
  advance={idea=>{if(!busy)void action.run(async()=>{await update(selected(idea),{status:NEXT[idea.status]});void resource.reload()})}}
  remove={idea=>{if(!busy)void action.run(async()=>{await update(selected(idea),{action:'topic-delete'});void resource.reload()})}}
  schedule={idea=>{if(!busy)void action.run(async()=>{
   const topic=selected(idea);let workId=topic.work_id;
   if(!workId){const result=await vm.service.createWork('topic-calendar:'+topic.id,{id:'topic-calendar-'+topic.id+'-'+topic.revision,title:topic.title,material:topic.note||topic.title,files:[],format:'poster'},'draft');workId=string(result.work_id||record(result.result).work_id);if(workId){await update(topic,{work_id:workId});void resource.reload()}}
   if(!workId)throw Error('选题尚未保存，排期未创建');
   const date=new Date();date.setHours(0,0,0,0);
   await vm.client.mutate('topic-plan:'+topic.id,'/api/easel/commands',{action:'plan-save',base_revision:0,work_id:workId,scheduled_at:date.toISOString(),status:'planned',note:topic.note});
   setToast('已加入日历（今天）');clearTimeout(timer.current);timer.current=setTimeout(()=>setToast(''),2200);
  })}} onUseTopic={onUseTopic}/>;
}
