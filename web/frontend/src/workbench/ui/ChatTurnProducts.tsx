import React,{useState} from 'react';
import ArtifactGallery from '../../components/ArtifactGallery';
import CopyableText from '../../components/CopyableText';
import type {Artifact as PreviewArtifact} from '../../lib/artifacts';
import {nativeContinuationPath,useResource,useWorkbench,array,record,string,workPath,type JsonRecord,type Work} from '@workbench/core';
import {Completion} from './WorkCompletion';
import {Notice} from './common';

export function productArtifacts(files:unknown):PreviewArtifact[]{
 return array<JsonRecord>(files).filter(file=>file.id&&file.name&&file.mime).map(file=>{
  const mime=string(file.mime),url=string(file.url),id=string(file.id),name=string(file.name);
  const target=/^\/api\/(?:files\/[A-Za-z0-9_-]+|chat\/products\/[A-Za-z0-9_-]+\/files\/[a-f0-9]{64})$/.test(url)?url:'/api/files/'+encodeURIComponent(id);
  const kind:PreviewArtifact['kind']=mime.startsWith('image/')?'image':mime.startsWith('video/')?'video':mime.startsWith('audio/')?'audio':mime==='text/html'?'html':mime==='application/pdf'?'pdf':mime.startsWith('text/')||mime==='application/json'?'text':'file';
  return {url:target,downloadUrl:target+'?download=1',name,kind};
 }).sort((a,b)=>Number(b.kind==='image')-Number(a.kind==='image'));
}

export function ChatTurnProducts({message,showNavigation=true}:{message:unknown;showNavigation?:boolean}){
 const vm=useWorkbench(),value=record(message),tid=string(value.turnId||value.id),product=useResource<JsonRecord>(tid?'/api/chat/products/'+encodeURIComponent(tid):null,{interval:10000}),[opened,setOpened]=useState(false);
 const data=product.data,wid=string(data?.work_id),vid=string(data?.version_id),decision=string(record(data?.decision).kind),blocks=array<JsonRecord>(data?.text_blocks),fallback=array<JsonRecord>(data?.files).filter(file=>file.partial),issue=string(value.business_error),continuationPath=nativeContinuationPath(value.business_recovery,wid,vid);
 if(!data&&!issue)return null;
 const hasProducts=array(data?.files).length>0||blocks.length>0;
 return <div className="chat-turn-outputs">
  {continuationPath&&<button className="btn btn-sm btn-primary" onClick={()=>vm.navigate(continuationPath,{intent:'flow'})}>继续制作</button>}
  {issue&&<details><summary>作品交付仍需核对</summary><p className="ew-preserve">{issue}</p></details>}
  {data?.incomplete===true&&hasProducts&&<p className="chat-task-status">本轮未完成；以下为已保存文件，可查看和保存，尚不能采纳。</p>}
  {fallback.length>0&&<ArtifactGallery artifacts={productArtifacts(fallback)}/>}
  {blocks.map(block=><CopyableText key={string(block.label)} label={string(block.label)} text={string(block.text)}/>)}
  {(hasProducts||wid)&&<div className="ew-row chat-product-actions"><span role="status">{decision==='accept'?'此版本已采纳':decision==='reject'?'此版本未采纳':data?.can_adopt?'此版本待采纳':''}</span>
   {data?.can_adopt===true&&decision!=='accept'&&<button className="btn btn-sm" onClick={()=>setOpened(true)}>采纳此版</button>}
   {showNavigation&&<button className="btn btn-sm" onClick={()=>vm.navigate(wid?workPath({id:wid},vid):'/works?session='+encodeURIComponent(string(data?.session_id)))}>查看产物</button>}
  </div>}
  {opened&&wid&&<ChatAdoption workId={wid} versionId={vid} close={()=>setOpened(false)} done={()=>{setOpened(false);void product.reload();vm.client.invalidate(['works','chat'])}}/>}
 </div>;
}

function ChatAdoption({workId,versionId,close,done}:{workId:string;versionId:string;close:()=>void;done:()=>void}){
 const work=useResource<Work>('/api/works/'+encodeURIComponent(workId)),version=work.data?.versions.find(version=>version.id===versionId);
 return <><Notice sources={[work]}/>{work.data&&version?<Completion work={work.data} version={version} open close={close} done={done}/>:<button className="btn" onClick={close}>取消读取采纳信息</button>}</>;
}
