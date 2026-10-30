import React,{useEffect} from 'react';
import SkillPage from '../../components/SkillPage';
import SkillDrawer from '../../components/SkillDrawer';
import type {SkillDetail} from '../../lib/api';
import {useWorkbench,useResource,type JsonRecord} from '@workbench/core';
import {nativeSkillChoices,nativeSkillDestination,nativeSkillInputTarget,type NativeSkill,type NativeSelection} from './ChatSessionView';
export function NativeSkills({profileId,onUse}:{profileId:string;onUse:(selection:NativeSelection,input:string)=>Promise<void>}){
 const vm=useWorkbench(),resource=useResource<NativeSkill[]>('/api/skills');
 return <SkillPage persona={profileId} catalog={{items:resource.data||[],error:resource.error,reload:()=>void resource.reload()}}
  headerActions={<button className="btn" onClick={()=>vm.navigate('/toolbox?section=skills&pane=experience&profile='+encodeURIComponent(profileId))}>整理经验</button>}
  subtitle="以 Easel 完整内置技能为核心，工作台技能作为扩展。选择后带入原生对话；外部服务与发布操作按实际配置和授权执行。"
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
  footer={skill?.origin==='easel'?<div className="panel"><p>Easel 原生技能，执行时冻结准确源码与依赖版本。</p><button className="btn" onClick={()=>vm.navigate('/settings')}>配置与运行环境</button></div>:<div className="panel"><button className="btn" onClick={()=>vm.navigate('/toolbox?section=skills&item='+encodeURIComponent(skill?.skill_id||skill?.id||name))}>版本与试用</button><p>发布技能及修改默认版本仍须单独确认。</p></div>}
  loadDetail={id=>vm.api.get<SkillDetail>('/api/skill/'+encodeURIComponent(id))}
  useActions={choices.map(choice=>({id:choice.id,label:choice.label}))} useDisabled={skill?.available===false||!choices.length}
  useNotice={skill?.reason||'带入对话不会立即制作。发送后核对本轮方案和准确技能版本。'}
  onUse={async(_,input,actionId)=>{const choice=choices.find(item=>item.id===actionId)||choices[0];if(!choice||choice.disabled)throw Error(skill?.reason||'技能尚无可执行入口');const target=nativeSkillDestination(choice.selection,profileId);if(target){const binding=nativeSkillInputTarget(choice.selection);if(input.trim()&&binding){const prior=vm.client.drafts.get<JsonRecord>(binding.key)||{};if(prior[binding.field]&&prior[binding.field]!==input)throw Error('目标页面已有未发送的输入。这里的原文仍保留，请先核对目标草稿。');if(!vm.client.drafts.set(binding.key,{...prior,[binding.field]:input}))throw Error('本机输入暂未保存，请恢复存储后再打开。')}else if(input.trim())throw Error('此动作需要先选择准确作品。当前输入仍保留，请先核对版本。');vm.navigate(target)}else await onUse(choice.selection,input);close()}}/>;
}
