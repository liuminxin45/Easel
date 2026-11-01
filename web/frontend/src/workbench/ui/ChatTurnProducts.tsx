import React,{useState} from 'react';
import ArtifactGallery from '../../components/ArtifactGallery';
import CopyableText from '../../components/CopyableText';
import type {Artifact as PreviewArtifact} from '../../lib/artifacts';
import {nativeContinuationPath,useResource,useWorkbench,useAsyncAction,useDraft,array,record,string,workPath,fileDownload,type JsonRecord,type Work} from '@workbench/core';
import {Completion} from './WorkCompletion';
import {Notice,Modal,Field,ActionButton} from './common';
import {ExtensionDetails} from './ExtensionDetails';
import {TaskStatus} from './TaskStatus';
import {nativeWorkChatPath} from './lib/workChatPath';

export function productArtifacts(files:unknown):PreviewArtifact[]{
 return array<JsonRecord>(files).filter(file=>file.id&&file.name&&file.mime).map(file=>{
  const mime=string(file.mime),url=string(file.url),id=string(file.id),name=string(file.name);
  const target=/^\/api\/(?:files\/[A-Za-z0-9_-]+|chat\/products\/[A-Za-z0-9_-]+\/files\/[a-f0-9]{64})$/.test(url)?url:'/api/files/'+encodeURIComponent(id);
  const kind:PreviewArtifact['kind']=mime.startsWith('image/')?'image':mime.startsWith('video/')?'video':mime.startsWith('audio/')?'audio':mime==='text/html'?'html':mime==='application/pdf'?'pdf':mime.startsWith('text/')||mime==='application/json'?'text':'file';
  const downloadUrl=target.startsWith('/api/files/')?fileDownload({id,name,mime,image_url:string(file.image_url)}):target+'?download=1';
  return {url:target,downloadUrl,name,kind};
 }).sort((a,b)=>Number(b.kind==='image')-Number(a.kind==='image'));
}

export function ChatTurnProducts({message,showNavigation=true,showContinuation=true,showStatus=true,continuationPath:authorizedPath}:{message:unknown;showNavigation?:boolean;showContinuation?:boolean;showStatus?:boolean;continuationPath?:string|null}){
 const vm=useWorkbench(),value=record(message),tid=string(value.turnId||value.id),product=useResource<JsonRecord>(tid?'/api/chat/products/'+encodeURIComponent(tid):null,{interval:10000}),[opened,setOpened]=useState<'accept'|'reject'|null>(null),action=useAsyncAction();
 const data=product.data,wid=string(data?.work_id),vid=string(data?.version_id),decision=string(record(data?.decision).kind),blocks=array<JsonRecord>(data?.text_blocks),fallback=array<JsonRecord>(data?.files).filter(file=>file.partial),issue=string(value.business_error),continuationPath=authorizedPath===undefined?nativeContinuationPath(value.business_recovery,wid,vid):authorizedPath;
 if(!data&&!issue&&!continuationPath)return null;
 const hasProducts=array(data?.files).length>0||blocks.length>0;
 const incomplete=data?.incomplete===true||!!continuationPath,interrupted=string(value.status)==='stopped'||!!continuationPath;
 const change=()=>void action.run(async()=>{const ticket=vm.navigation.ticket?.(),work=await vm.client.read<Work>('/api/works/'+encodeURIComponent(wid),true),version=work?.versions.find(item=>item.id===vid),path=work&&version?.status==='completed'?nativeWorkChatPath(work,version,true):null;if(!path)throw Error('此版本的制作记录尚未核对，请在产物页查看。');if(ticket&&vm.navigation.finishFlow)vm.navigation.finishFlow(path,ticket);else vm.navigate(path,{intent:'flow'})});
 return <div className="chat-turn-outputs">
  {showStatus&&(incomplete||issue)&&<TaskStatus title={incomplete?'制作未完成':'交付待核对'} label={interrupted?'制作中断':'制作状态'} description={incomplete?(hasProducts?'已保存的内容可以查看，制作完成后才能采纳。':'原有素材与任务记录已保留。'):'请查看制作记录中的核对结果。'}>
   {showContinuation&&continuationPath&&<button className="btn btn-sm btn-primary" onClick={()=>vm.navigate(continuationPath,{intent:'flow'})}>继续制作</button>}
   {issue&&<ExtensionDetails title="查看制作记录"><p className="ew-preserve">{issue}</p></ExtensionDetails>}
  </TaskStatus>}
  {fallback.length>0&&<ArtifactGallery artifacts={productArtifacts(fallback)}/>}
  {blocks.map(block=><CopyableText key={string(block.label)} label={string(block.label)} text={string(block.text)}/>)}
  {(hasProducts||wid)&&(decision||data?.can_adopt||showNavigation)&&<div className="ew-row chat-product-actions"><span role="status">{decision==='accept'?'此版本已采纳':decision==='reject'?'此版本未采纳':data?.can_adopt?'此版本待采纳':''}</span>
   {data?.can_adopt===true&&wid&&vid&&<>
    {decision!=='accept'&&<button className="btn btn-sm btn-primary" onClick={()=>setOpened('accept')}>采纳此版</button>}
    <ActionButton action={action} className="btn btn-sm" onClick={change}>修改这版</ActionButton>
    {decision!=='reject'&&<button className="btn btn-ghost btn-sm" onClick={()=>setOpened('reject')}>不采纳</button>}
   </>}
   {showNavigation&&<button className="btn btn-sm" onClick={()=>vm.navigate(wid?workPath({id:wid},vid):'/works?session='+encodeURIComponent(string(data?.session_id)))}>查看产物</button>}
  </div>}
  <Notice sources={[action]}/>
  {opened&&wid&&<ChatAdoption workId={wid} versionId={vid} mode={opened} close={()=>setOpened(null)} done={()=>{setOpened(null);void product.reload();vm.client.invalidate(['works','chat'])}}/>}
 </div>;
}

function ChatAdoption({workId,versionId,mode,close,done}:{workId:string;versionId:string;mode:'accept'|'reject';close:()=>void;done:()=>void}){
 const work=useResource<Work>('/api/works/'+encodeURIComponent(workId)),version=work.data?.versions.find(version=>version.id===versionId);
 return <><Notice sources={[work]}/>{work.data&&version?(mode==='accept'?<Completion work={work.data} version={version} open close={close} done={done}/>:<ChatRejection work={work.data} versionId={versionId} close={close} done={done}/>):<button className="btn" onClick={close}>取消读取版本信息</button>}</>;
}

function ChatRejection({work,versionId,close,done}:{work:Work;versionId:string;close:()=>void;done:()=>void}){
 const vm=useWorkbench(),action=useAsyncAction(),[note,patch]=useDraft('decision:'+work.id+':'+versionId,{text:''});
 return <Modal open title="不采纳此版" onClose={close}><p>保留这版内容和决定，不会重新制作。</p><Field label="决定说明 · 可不填"><textarea className="field" rows={4} value={note.text} onChange={event=>patch({text:event.target.value})}/></Field><Notice sources={[action]}/><ActionButton action={action} className="btn btn-primary" onClick={()=>void action.run(async()=>{await vm.service.workAction(work.id,{kind:'reject',candidate_id:versionId,text:note.text,files:[]});done()})}>确认不采纳</ActionButton></Modal>;
}
