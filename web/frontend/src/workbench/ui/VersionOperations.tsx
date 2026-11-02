import {DraftOperations} from './DraftOperations';
import React,{useState} from 'react';
import CopyableText from '../../components/CopyableText';
import {array,record,string,statusLabel,nativeContinuationPath,workProductionRecovery,type Work,type ReviewDocument,type JsonRecord,type DraftAttachment} from '@workbench/core';
import {useWorkbench,useResource,useAsyncAction,useDraft} from './hooks';
import {ExtensionDetails} from './ExtensionDetails';
import {Notice,ActionButton,Field,Modal,Pending,TextRecord,Markdown} from './common';
import {TaskStatus} from './TaskStatus';
import {ProductionParameters} from './ProductionParameters';
import {Completion} from './WorkCompletion';
import {nativeWorkChatPath} from './lib/workChatPath';

/** Lifecycle controls extend the native library; they do not own file browsing. */
export function VersionOperations({workId,versionId}:{workId:string;versionId:string}){
 const [opened,setOpened]=useState(false);
 return <ExtensionDetails title="版本与操作" onToggle={event=>setOpened(event.currentTarget.open)}>
  {opened&&<VersionPanel key={workId+':'+versionId} workId={workId} versionId={versionId}/>}
 </ExtensionDetails>;
}

export function VersionPanel({workId,versionId}:{workId:string;versionId:string}){
 const vm=useWorkbench(),resource=useResource<Work>('/api/works/'+encodeURIComponent(workId),{interval:10000}),work=resource.data,
  version=work?.versions.find(item=>item.id===versionId),action=useAsyncAction(),[dialog,setDialog]=useState<'accept'|'reject'|'manual'|null>(null),
  [note,patchNote]=useDraft('decision:'+workId+':'+versionId,{text:''}),
  [feedback,patchFeedback]=useDraft<{text:string;files:DraftAttachment[]}>('feedback:'+workId+':'+versionId,{text:'',files:[]}),
  [edit,patchEdit]=useDraft<JsonRecord>('text-edit:'+workId+':'+versionId,{}),
  review=useResource<ReviewDocument>(version?.status==='completed'?'/api/works/'+workId+'/versions/'+versionId+'/review':null),
  [annotation,setAnnotation]=useState<{field:string;quote:string;start:number;end:number}|null>(null),[annotationText,setAnnotationText]=useState('');
 if(work&&!work.versions.length)return <DraftOperations work={work}/>;
 if(!work||!version)return <><Notice sources={[resource]}/><p>{work?'此准确版本不存在；请选择内容库中的原版本。':'正在读取本版操作…'}</p></>;
 const title=version.editable_text?.title||version.copy?.title||version.article?.title||work.title,
  body=version.editable_text?.body||version.copy?.caption||version.article?.body||'',
  recovery=workProductionRecovery(work,version),continuation=nativeContinuationPath(recovery,work.id,version.id),
  decision=array<JsonRecord>(record(version).decisions).at(-1)||((work.decision?.candidate_id===version.id)?work.decision:undefined);
 const refresh=()=>{void resource.reload();void vm.client.invalidate(['works','chat','studio'])};
 const openChat=(change=false)=>void action.run(async()=>{
  const ticket=vm.navigation.ticket?.(),current=await vm.client.read<Work>('/api/works/'+work.id,true),selected=current?.versions.find(item=>item.id===version.id);
  if(!current||!selected||change&&selected.status!=='completed')throw Error('此版本的制作记录尚未核对，请重新读取原版本。');
  let target=nativeWorkChatPath(current,selected,change);
  if(!target){
   const root=selected.creative?.creator?.skills?.find(skill=>skill.id==='content-production');
   if(change&&!root?.version)throw Error('原版制作技能没有准确绑定，请先核对版本记录。');
   const result=await vm.client.mutate<JsonRecord>('chat:create','/api/chat/sessions',{action:'create',profile_id:work.creator?.id||'oil-pig'}),session=record(result.session||record(result.result).session||result),sid=string(session.id);
   if(!sid)throw Error('原生会话尚未创建，未启动制作。');
   target='/chat/'+encodeURIComponent(sid)+'?'+new URLSearchParams({work:work.id,version:version.id,...(change?{action:'change',skill:'content-production',skill_version:String(root!.version)}:{})});
  }
  if(ticket&&vm.navigation.finishFlow)vm.navigation.finishFlow(target,ticket);else vm.navigate(target,{intent:'flow'});
 });
 const selectText=(field:string,event:React.MouseEvent<HTMLDivElement>)=>{
  const root=event.currentTarget.querySelector('code'),selection=window.getSelection();if(!root||!selection?.rangeCount||selection.isCollapsed)return;
  const range=selection.getRangeAt(0);if(!root.contains(range.startContainer)||!root.contains(range.endContainer))return;
  const quote=range.toString();if(!quote.trim()||Array.from(quote).length>4000)return;
  const prefix=range.cloneRange();prefix.selectNodeContents(root);prefix.setEnd(range.startContainer,range.startOffset);const start=Array.from(prefix.toString()).length;
  setAnnotation({field,quote,start,end:start+Array.from(quote).length});
 };
 const manual=()=>{if(!Object.keys(edit).length)patchEdit({title,body,source_token:version.editable_text?.token||'',base_version:work.latest_version});setDialog('manual')};
 return <div className="ew-version-operations">
  <Notice sources={[resource,action]}/>
  {['accept','reject','feedback','change'].map(kind=><Pending key={kind} scope={'work:'+work.id+':'+kind} reload={refresh}/>)}
  <div className="ew-row"><label>作品版本 <select className="field" aria-label="作品版本" value={version.id} onChange={event=>vm.navigate('/works?'+new URLSearchParams({path:'workbench-'+work.id+'/'+event.target.value}))}>{work.versions.map(item=><option key={item.id} value={item.id}>{item.label}</option>)}</select></label><span role="status">{decision?.kind==='accept'?'此版本已采纳':decision?.kind==='reject'?'此版本未采纳':version.status==='completed'?(record(record(record(version).learning).quality).checked===true?'已生成 · 待采纳':'已生成 · 待独立检查'):recovery?.phase==='production_failed'?'成品接收失败':statusLabel(version.status)}</span></div>
  {recovery&&<TaskStatus title={recovery.phase==='production_failed'?'成品接收失败':statusLabel(recovery.phase)} description={recovery.message}>{continuation&&<button className="btn" onClick={()=>vm.navigate(continuation,{intent:'flow'})}>继续制作</button>}<TextRecord title="本版接收记录" value={recovery}/>{recovery.can_retry&&<ActionButton action={action} className="btn" onClick={()=>void action.run(()=>vm.service.retryTask(recovery.job_id,recovery.revision))}>按原冻结输入恢复发送</ActionButton>}</TaskStatus>}
  <div onMouseUp={event=>selectText(work.format==='article'?'article_title':'poster_title',event)}><CopyableText label="标题" text={title}/></div>
  {body&&<div onMouseUp={event=>selectText(work.format==='article'?'article_body':'caption',event)}><CopyableText label={work.format==='article'?'正文':'配文'} text={body}/></div>}
  {annotation&&<div><blockquote>{annotation.quote}</blockquote><Field label="批注意见"><textarea className="field" value={annotationText} onChange={event=>setAnnotationText(event.target.value)}/></Field><ActionButton action={action} className="btn" disabled={!annotationText.trim()||action.busy} onClick={()=>void action.run(async()=>{const source=review.data?.sources[annotation.field];if(!source)throw Error('原文指纹尚未取得');await vm.service.saveAnnotation(work.id,version.id,{kind:'create',...annotation,source_sha256:source.sha256,note:annotationText,dimension:annotation.field.includes('title')?'title':'text',scope:'work'});setAnnotation(null);setAnnotationText('');void review.reload()})}>保存到此版本</ActionButton><button className="btn btn-ghost" onClick={()=>setAnnotation(null)}>取消批注</button></div>}
  <div className="ew-row">
   <ActionButton action={action} className="btn" onClick={()=>openChat(false)}>讨论这版</ActionButton>
   {version.status==='completed'&&<><button className="btn btn-primary" onClick={()=>setDialog('accept')}>采纳并完成</button><button className="btn" onClick={()=>setDialog('reject')}>不采纳</button><ActionButton action={action} className="btn" onClick={()=>openChat(true)}>修改这版</ActionButton></>}
   <button className="btn btn-ghost" onClick={manual}>使用自写文案</button>
  </div>
  <ExtensionDetails title="只记录本版反馈"><label className="btn ew-file-pick">添加反馈素材<input type="file" multiple disabled={action.busy} aria-label="反馈素材" onChange={event=>{const files=Array.from(event.target.files||[]);event.currentTarget.value='';void action.run(async()=>{const attached=await vm.service.attach(files,feedback.files);patchFeedback({files:attached})})}}/></label>{feedback.files.map(file=><span key={file.id}>{file.name}<ActionButton action={action} className="btn btn-ghost" onClick={()=>patchFeedback({files:feedback.files.filter(item=>item.id!==file.id)})}>移除</ActionButton></span>)}<Field label="反馈原话"><textarea className="field" value={feedback.text} onChange={event=>patchFeedback({text:event.target.value})}/></Field><ActionButton action={action} className="btn" disabled={!feedback.text.trim()||action.busy} onClick={()=>void action.run(async()=>{const original=feedback.text;await vm.service.workAction(work.id,{kind:'feedback',candidate_id:version.id,text:original,files:feedback.files});const current=vm.client.drafts.get<{text:string;files:DraftAttachment[]}>('feedback:'+workId+':'+versionId);if(current?.text===original&&JSON.stringify(current.files)===JSON.stringify(feedback.files))patchFeedback({text:'',files:[]});refresh()})}>保存反馈，不制作</ActionButton></ExtensionDetails>
  {version.status==='completed'&&<ProductionParameters versionId={version.id}/>}
  <ExtensionDetails title="版本与记录">{work.history.map(item=><ExtensionDetails key={item.id} title={(item.id===version.id?version.label+' · ':'')+statusLabel(item.status)}><p className="ew-preserve">{item.text}</p><Markdown text={item.reply}/><TextRecord title="制作设置记录" value={item.creative}/></ExtensionDetails>)}<TextRecord title="本版制作设置" value={version.creative}/><TextRecord title="批注记录" value={review.data?.annotations||[]}/><TextRecord title="完成、归档与交付记录" value={record(work).completion}/><button className="btn" onClick={()=>vm.navigate('/toolbox?section=publications&work='+work.id+'&version='+version.id)}>发布与分发</button></ExtensionDetails>
  {dialog==='accept'&&<Completion work={work} version={version} open close={()=>setDialog(null)} done={()=>{setDialog(null);refresh()}}/>}
  <Modal open={dialog==='reject'} title={'不采纳 '+version.label} onClose={()=>setDialog(null)}><Field label="决定说明 · 可不填"><textarea className="field" value={note.text} onChange={event=>patchNote({text:event.target.value})}/></Field><Notice sources={[action]}/><ActionButton action={action} className="btn btn-primary" onClick={()=>void action.run(async()=>{await vm.service.workAction(work.id,{kind:'reject',candidate_id:version.id,text:note.text,files:[]});setDialog(null);refresh()})}>确认不采纳</ActionButton></Modal>
  <Modal open={dialog==='manual'} title="保存自写文案为新版本" onClose={()=>setDialog(null)}><Field label="标题"><input className="field" value={string(edit.title)} onChange={event=>patchEdit({title:event.target.value})}/></Field><Field label="正文／配文"><textarea className="field" rows={12} value={string(edit.body)} onChange={event=>patchEdit({body:event.target.value})}/></Field><Notice sources={[action]}/><ActionButton action={action} className="btn btn-primary" onClick={()=>void action.run(async()=>{const result=await vm.service.saveText(work.id,{...edit,candidate_id:version.id}),next=string(result.version_id)||string(result.id);setDialog(null);refresh();if(next)vm.navigate('/works?'+new URLSearchParams({path:'workbench-'+work.id+'/'+next}))})}>另存为新版本</ActionButton></Modal>
 </div>;
}
