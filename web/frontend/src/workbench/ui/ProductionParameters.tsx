import React,{useState} from 'react';
import {useResource,array,record,string,type JsonRecord} from '@workbench/core';
import {Notice,TextRecord} from './common';

/** Read the selected version's stored input, never today's profile or skill defaults. */
export function ProductionParameters({versionId}:{versionId:string}){
 const [opened,setOpened]=useState(false),resource=useResource<JsonRecord>(opened?'/api/creative/prompts/'+encodeURIComponent(versionId):null);
 const execution=record(resource.data?.execution_prompt),snapshot=record(execution.creator_snapshot),profile=record(snapshot.profile),skills=array<JsonRecord>(snapshot.skills);
 return <details className="chat-production-details" onToggle={event=>{if(event.currentTarget.open)setOpened(true)}}>
  <summary>制作参数</summary>
  <Notice message={resource.error}/>
  {resource.error&&<button className="btn btn-sm" onClick={()=>void resource.reload()}>重新读取制作参数</button>}
  {!resource.data&&!resource.error&&<p role="status">正在读取本版制作记录…</p>}
  {resource.data&&<>
   <p><strong>作品版本：</strong>{versionId}</p>
   {Object.keys(profile).length>0&&<p><strong>画像：</strong>{string(profile.name)||string(profile.id)}{profile.revision!=null?' · v'+String(profile.revision):''}</p>}
   {skills.length>0&&<p><strong>技能：</strong>{skills.map(skill=>(string(skill.name)||string(skill.id))+' · v'+String(skill.version??'未记录')).join('、')}{snapshot.trial?' · 本次试用':''}</p>}
   {execution.body?<TextRecord title="完整实际制作指令" value={execution.body}/>:<p>此版本未保存完整制作指令。</p>}
   {execution.sha256&&<TextRecord title="制作指令 SHA-256" value={execution.sha256}/>}
   {array<JsonRecord>(resource.data.image_prompts).length>0&&<TextRecord title="逐图制作记录与核验状态" value={resource.data.image_prompts}/>}
  </>}
 </details>;
}
