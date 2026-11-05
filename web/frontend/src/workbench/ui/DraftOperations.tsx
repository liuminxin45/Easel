import React from 'react';
import {sessionOpenFlows,record,string,array,type Work,type JsonRecord,type DraftAttachment} from '@workbench/core';
import {useWorkbench,useDraft,useAsyncAction} from './hooks';
import {Field,Notice,ActionButton,Pending} from './common';
import {creationSkillId} from './newsCreation';

/** Saved historical material opens an ordinary Easel skill conversation. */
export function DraftOperations({work}:{work:Work}){
 const vm=useWorkbench(),[draft,patch]=useDraft<JsonRecord>('work-draft:'+work.id,record(work.draft)),action=useAsyncAction();
 const profile=work.creator?.id||'oil-pig';
 const produce=()=>void action.run(async()=>{
  const skill=creationSkillId(work.format),submitted={...draft},original=record(work.draft);
  if(JSON.stringify(submitted)!==JSON.stringify(original))await vm.service.saveDraft(work.id,{...submitted,revision:original.revision,files:array<DraftAttachment>(submitted.files)});
  const text=[string(submitted.title,work.title),string(submitted.material),string(submitted.guidance),string(record(record(submitted.creative).recipe).prompt_text)].filter(Boolean).join('\n\n');
  await sessionOpenFlows(vm.client).open({profileId:profile,sourceKey:'work-draft:'+work.id,draft:{text,files:array(submitted.files),command:{skill_id:skill,action_id:'native',task:'native',label:work.format==='poster'?'油猪·做贴图':'油猪·做文章',requires_plan:false}}});
 });
 const discuss=()=>void action.run(async()=>{
  const text=[string(draft.title,work.title),string(draft.material),string(draft.guidance)].filter(Boolean).join('\n\n');
  await sessionOpenFlows(vm.client).open({profileId:profile,sourceKey:'work-draft:'+work.id,draft:{text,files:array(draft.files)}});
 });
 return <div className="ew-version-operations"><Notice sources={[action]}/><Pending scope={'finalize:'+work.id}/>
  <Field label="主题"><input className="field" value={string(draft.title,work.title)} onChange={event=>patch({title:event.target.value})}/></Field>
  <Field label="素材"><textarea className="field" rows={7} value={string(draft.material)} onChange={event=>patch({material:event.target.value})}/></Field>
  <Field label="制作要求"><textarea className="field" rows={3} value={string(draft.guidance)} onChange={event=>patch({guidance:event.target.value})}/></Field>

  <div className="ew-row"><ActionButton action={action} className="btn" onClick={()=>void action.run(()=>vm.service.saveDraft(work.id,{...draft,revision:work.draft.revision,files:array<DraftAttachment>(draft.files)}))}>保存草稿</ActionButton><ActionButton action={action} className="btn" onClick={discuss}>讨论草稿</ActionButton><ActionButton action={action} className="btn btn-primary" disabled={!!work.pending.length||action.busy} onClick={produce}>按当前草稿制作</ActionButton></div>
 </div>;
}
