import React,{useEffect} from 'react';
import SkillPage from '../../components/SkillPage';
import SkillDrawer from '../../components/SkillDrawer';
import type {SkillDetail} from '../../lib/api';
import {useWorkbench,useResource,type JsonRecord} from '@workbench/core';
import {nativeSkillChoices,nativeSkillDestination,nativeSkillInputTarget,type NativeSkill,type NativeSelection} from './ChatSessionView';
export function NativeSkills({profileId,onUse}:{profileId:string;onUse:(selection:NativeSelection,input:string)=>Promise<void>}){
 const vm=useWorkbench(),resource=useResource<NativeSkill[]>('/api/skills');
 return <SkillPage persona={profileId} catalog={{items:resource.data||[],error:resource.error,loading:!resource.data&&!resource.error,reload:()=>void resource.reload()}}
  headerActions={<button className="btn" onClick={()=>vm.navigate('/toolbox?section=skills&pane=experience&profile='+encodeURIComponent(profileId))}>整理经验</button>}
  subtitle="选择技能，带入对话后开始创作。"
  renderDrawer={(name,close)=><NativeDetail name={name} skills={resource.data||[]} profileId={profileId} close={close} reload={()=>void resource.reload()} onUse={onUse}/>}/>;
}
function NativeDetail({name,skills,profileId,close,reload,onUse}:{name:string;skills:NativeSkill[];profileId:string;close:()=>void;reload:()=>void;onUse:(selection:NativeSelection,input:string)=>Promise<void>}){
 const vm=useWorkbench(),skill=skills.find(item=>item.name===name),choices=nativeSkillChoices(skill?[skill]:[]);
 useEffect(()=>{const release=vm.navigation.registerLayer?.(close),previous=document.activeElement as HTMLElement|null;
  const key=(event:KeyboardEvent)=>{if(event.key==='Escape'){event.preventDefault();close()}};document.addEventListener('keydown',key);
  const timer=setTimeout(()=>document.querySelector<HTMLElement>('.drawer-overlay button[title="关闭"]')?.focus(),0);
  return()=>{clearTimeout(timer);release?.();document.removeEventListener('keydown',key);previous?.focus({preventScroll:true})};
 },[name]);
 return <SkillDrawer skillName={name} persona={profileId} onClose={close} onConfigured={reload} canConfigure={false}
  footer={skill?.origin==='easel'?undefined:<div className="panel"><button className="btn" onClick={()=>vm.navigate('/toolbox?section=skills&item='+encodeURIComponent(skill?.skill_id||skill?.id||name))}>版本与试用</button></div>}
  loadDetail={id=>vm.api.get<SkillDetail>('/api/skill/'+encodeURIComponent(id))}
  useActions={choices.map(choice=>({id:choice.id,label:choice.label}))} useDisabled={skill?.available===false||!choices.length}
  useNotice={skill?.reason||'带入对话后，确认发送才会开始。'}
  onUse={async(_,input,actionId)=>{const choice=choices.find(item=>item.id===actionId)||choices[0];if(!choice||choice.disabled)throw Error(skill?.reason||'技能尚无可执行入口');const target=nativeSkillDestination(choice.selection,profileId);if(target){const binding=nativeSkillInputTarget(choice.selection);if(input.trim()&&binding){const prior=vm.client.drafts.get<JsonRecord>(binding.key)||{};if(prior[binding.field]&&prior[binding.field]!==input)throw Error('目标页面已有未发送的输入。这里的原文仍保留，请先核对目标草稿。');if(!vm.client.drafts.set(binding.key,{...prior,[binding.field]:input}))throw Error('本机输入暂未保存，请恢复存储后再打开。')}else if(input.trim())throw Error('此动作需要先选择准确作品。当前输入仍保留，请先核对版本。');vm.navigate(target)}else await onUse(choice.selection,input);close()}}/>;
}
