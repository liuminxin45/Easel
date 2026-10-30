import {useMemo} from 'react';
import type {PublishingAgentActions} from '../../components/PublishingPage';
import {useWorkbench,useResource,record,string} from '@workbench/core';
import {nativeSkillChoices,type NativeSkill} from './ChatSessionView';

/** Page actions enter the same explicit-skill composer as the skill library. */
export function useNativePublishingActions(profileId:string):PublishingAgentActions{
 const vm=useWorkbench(),catalog=useResource<NativeSkill[]>('/api/skills');
 return useMemo(()=>{
  const open=async(action:'adapt'|'check',input:string)=>{
   const skillId=action==='adapt'?'skill-content-repurposing':'skill-publish-checklist';
   const choice=nativeSkillChoices(catalog.data||[]).find(item=>item.selection.skill_id===skillId);
   if(!choice||choice.disabled)throw Error('所需技能的准确版本尚未可用，原稿仍保留。');
   const result=await vm.client.mutate('chat:create','/api/chat/sessions',{action:'create',profile_id:profileId});
   const session=record(result.session||record(result.result).session||result),id=string(session.id);
   if(!id)throw Error('会话尚未确认创建，原稿仍保留。');
   if(session.runtime==='api')throw Error('仅聊天模式不受理本机技能，原稿仍保留。');
   const text=action==='check'?'请按本轮所选技能审核下面的原稿，只提供检查建议，不发布、不修改长期规则。\n\n'+input:input;
   if(!vm.client.drafts.set('chat:'+id,{text,files:[],command:choice.selection}))throw Error('本机输入未能保存，原稿仍保留。');
   vm.navigate('/chat/'+encodeURIComponent(id),{intent:'flow'});
  };
  return {adapt:input=>open('adapt',input),check:input=>open('check',input)};
 },[vm.client,vm.navigate,catalog.data,profileId]);
}
