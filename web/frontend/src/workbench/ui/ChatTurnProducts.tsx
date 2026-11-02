import React from 'react';
import type {Artifact as PreviewArtifact} from '../../lib/artifacts';
import {nativeContinuationPath,array,record,string,fileDownload,type JsonRecord} from '@workbench/core';
import {useWorkbench} from './hooks';
import {TaskStatus} from './TaskStatus';

export function productArtifacts(files:unknown):PreviewArtifact[]{
 return array<JsonRecord>(files).filter(file=>file.id&&file.name&&file.mime).map(file=>{
  const mime=string(file.mime),url=string(file.url),id=string(file.id),name=string(file.name);
  const target=/^\/api\/(?:files\/[A-Za-z0-9_-]+|chat\/products\/[A-Za-z0-9_-]+\/files\/[a-f0-9]{64})$/.test(url)?url:'/api/files/'+encodeURIComponent(id);
  const kind:PreviewArtifact['kind']=mime.startsWith('image/')?'image':mime.startsWith('video/')?'video':mime.startsWith('audio/')?'audio':mime==='text/html'?'html':mime==='application/pdf'?'pdf':mime.startsWith('text/')||mime==='application/json'?'text':'file';
  const downloadUrl=target.startsWith('/api/files/')?fileDownload({id,name,mime,image_url:string(file.image_url)}):target+'?download=1';
  return {url:target,downloadUrl,name,kind};
 }).sort((a,b)=>Number(b.kind==='image')-Number(a.kind==='image'));
}

export function ChatTurnProducts({message,showStatus=true,showContinuation=true,continuationPath:authorizedPath}:{message:unknown;showNavigation?:boolean;showContinuation?:boolean;showStatus?:boolean;continuationPath?:string|null}){
 const vm=useWorkbench(),value=record(message),work=record(value.work),wid=string(work.work_id),vid=string(work.version_id),issue=string(value.business_error),path=authorizedPath===undefined?nativeContinuationPath(value.business_recovery,wid,vid):authorizedPath;
 if(!showStatus||!issue&&!path)return null;
 return <TaskStatus title={path?'制作中断':value.business_status==='error'?'成品接收失败':'交付待核对'} description={issue||'已保存的文件仍可在本版内容库查看。'}>
  {showContinuation&&path&&<button className="btn btn-sm" onClick={()=>vm.navigate(path,{intent:'flow'})}>继续制作</button>}
 </TaskStatus>;
}
