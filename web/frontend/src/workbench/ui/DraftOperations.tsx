import React from 'react';
import {sessionOpenFlows,record,string,array,creatorSelection,creatorTaskSelection,type Work,type CreatorBootstrap,type JsonRecord,type DraftAttachment} from '@workbench/core';
import {useWorkbench,useResource,useDraft,useAsyncAction} from './hooks';
import {CreatorControls} from './production';
import {Field,Notice,ActionButton,Pending} from './common';

/** Existing saved drafts retain their exact first-production contract. */
export function DraftOperations({work}:{work:Work}){
 const vm=useWorkbench(),creators=useResource<CreatorBootstrap>('/api/creator/bootstrap'),[draft,patch]=useDraft<JsonRecord>('work-draft:'+work.id,record(work.draft)),action=useAsyncAction();
 const creative=record(draft.creative),data=creators.data,base=record(creative.creator),profile=work.creator?.id||data?.default_profile_id||'oil-pig';
 const production=data?{...creative,schema_version:2,creator:creatorTaskSelection(data,Object.keys(base).length?base as unknown as ReturnType<typeof creatorSelection>:creatorSelection(data,profile,work.format),work.format),recipe:creative.recipe||{pack_id:work.format==='article'?'editorial-article':'editorial-poster'}}:creative;
 const produce=()=>void action.run(async()=>{
  if(!data)throw Error('画像与技能尚未读取，草稿已保留');
  const submitted={...draft},original=record(work.draft);
  if(JSON.stringify(submitted)!==JSON.stringify(original))await vm.service.saveDraft(work.id,{...submitted,revision:original.revision,files:array<DraftAttachment>(submitted.files)});
  const current=await vm.client.read<Work>('/api/works/'+encodeURIComponent(work.id)+'/view',true);if(!current)throw Error('原草稿尚未读回');
  const fields={revision:current.draft.revision,discussion_token:current.draft.discussion_token,creative:production},plan=await vm.service.prepareProduction('finalize',fields,work.id);
  await vm.service.finalize(work.id,{...fields,...record(plan.production_input),creative:{...production,...record(record(plan.production_input).creative),context_revision:plan.revision_token}});
  void vm.client.invalidate(['works','chat']);
 });
 const discuss=()=>void action.run(async()=>{
  const text=[string(draft.title,work.title),string(draft.material),string(draft.guidance)].filter(Boolean).join('\n\n');
  await sessionOpenFlows(vm.client).open({profileId:profile,sourceKey:'work-draft:'+work.id,draft:{text,files:array(draft.files)}});
 });
 return <div className="ew-version-operations"><Notice sources={[creators,action]}/><Pending scope={'finalize:'+work.id}/>
  <Field label="主题"><input className="field" value={string(draft.title,work.title)} onChange={event=>patch({title:event.target.value})}/></Field>
  <Field label="素材"><textarea className="field" rows={7} value={string(draft.material)} onChange={event=>patch({material:event.target.value})}/></Field>
  <Field label="制作要求"><textarea className="field" rows={3} value={string(draft.guidance)} onChange={event=>patch({guidance:event.target.value})}/></Field>
  {data&&<CreatorControls data={data} value={production} format={work.format} onChange={value=>patch({creative:value})}/>}
  <div className="ew-row"><ActionButton action={action} className="btn" onClick={()=>void action.run(()=>vm.service.saveDraft(work.id,{...draft,revision:work.draft.revision,files:array<DraftAttachment>(draft.files)}))}>保存草稿</ActionButton><ActionButton action={action} className="btn" onClick={discuss}>讨论草稿</ActionButton><ActionButton action={action} className="btn btn-primary" disabled={!data||!!work.pending.length||action.busy} onClick={produce}>按当前草稿制作</ActionButton></div>
 </div>;
}
