import {useEffect,useMemo,useRef,useState} from 'react';
import {useStore} from 'zustand';
import SkillPage from '../../components/SkillPage';
import SkillDrawer from '../../components/SkillDrawer';
import SettingsSelect from '../../components/SettingsSelect';
import QuestionCards from '../../components/QuestionCards';
import {array,record,string,type JsonRecord,type CreatorBootstrap} from '@workbench/core';
import {useWorkbench,useResource} from './hooks';
import {Drawer,TextRecord,Notice} from './common';
import {SkillDetail} from './management';
import {createSkillServices,type PreparedSkillExecution} from './skillServices';
import {nativeSkillChoices,nativeSkillDestination,type NativeSkill} from './ChatSessionView';

interface Confirmation {
 prepared:PreparedSkillExecution;
 resolve:(value:{response:string})=>void;
 reject:(error:Error)=>void;
}

/** Native catalog and native skill detail; only their service ports are adapted. */
export function NativeSkills({profileId}:{profileId:string}){
 const vm=useWorkbench(),resource=useResource<NativeSkill[]>('/api/skills');
 return <SkillPage persona={profileId} catalog={{items:resource.data||[],error:resource.error,loading:!resource.data&&!resource.error,reload:()=>void resource.reload()}}
  headerActions={<button className="btn" onClick={()=>vm.navigate('/toolbox?section=skills&pane=experience&profile='+encodeURIComponent(profileId))}>整理经验</button>}
  renderDrawer={(name,close)=><NativeDetail name={name} skills={resource.data||[]} profileId={profileId} close={close} reload={()=>void resource.reload()}/>}/>;
}

function NativeDetail({name,skills,profileId,close,reload}:{name:string;skills:NativeSkill[];profileId:string;close:()=>void;reload:()=>void}){
 const vm=useWorkbench(),skill=skills.find(item=>item.name===name),choices=nativeSkillChoices(skill?[skill]:[]);
 const runnable=choices.filter(choice=>!choice.selection.path),pathOnly=!!skill&&skill.origin!=='easel'&&!runnable.length;
 const services=useMemo(()=>createSkillServices(vm.client,profileId,skills,name),[vm.client,profileId,skills,name,vm.client.authenticationEpoch]);
 const execution=useStore(services.execution);
 useEffect(()=>services.resume(),[services]);
 const [actionId,setActionId]=useState(''),[confirmation,setConfirmation]=useState<Confirmation|null>(null);
 const pending=useRef<Confirmation|null>(null),generation=useRef(0);
 const selected=runnable.find(choice=>choice.id===actionId)||(runnable.length===1?runnable[0]:undefined);
 const cancelPreview=()=>{generation.current++;const previous=pending.current;pending.current=null;setConfirmation(null);previous?.reject(Error('已取消本次制作，尚未发送。'))};
 useEffect(()=>{
  if(pathOnly)return;
  const release=vm.navigation.registerLayer?.(close),previous=document.activeElement as HTMLElement|null;
  const key=(event:KeyboardEvent)=>{
   if(event.key!=='Escape'||event.defaultPrevented||event.isComposing||document.querySelector('dialog[open]'))return;
   const overlays=[...document.querySelectorAll<HTMLElement>('.drawer-overlay')].filter(element=>element.getClientRects().length&&getComputedStyle(element).visibility!=='hidden');
   if(overlays.at(-1)?.querySelector('.skill-detail-rawname')?.textContent!==name)return;
   event.preventDefault();close();
  };
  document.addEventListener('keydown',key);
  const timer=setTimeout(()=>document.querySelector<HTMLElement>('.drawer-overlay button[title="关闭"]')?.focus(),0);
  return()=>{generation.current++;pending.current?.reject(Error('制作确认已关闭，尚未发送。'));pending.current=null;clearTimeout(timer);release?.();document.removeEventListener('keydown',key);if(previous?.isConnected)previous.focus({preventScroll:true})};
 },[name,profileId,skill?.version,pathOnly]);
 const execute=async(id:string,input:string)=>{
  if(skill?.origin==='easel')return services.execute(id,input);
  if(!selected||selected.disabled||skill?.available===false)throw Error(skill?.reason||'请先选择本次使用的准确技能动作');
  if(!selected.selection.requires_plan)return services.executeSelection(selected.selection,input);
  const request=generation.current,prepared=await services.prepareSelection(selected.selection,input);
  if(request!==generation.current)throw Error('输入或技能已变化，请重新核对制作方案。');
  return new Promise<{response:string}>((resolve,reject)=>{
   const next={prepared,resolve,reject};pending.current=next;setConfirmation(next);
  });
 };
 const confirm=()=>{
  const current=pending.current;if(!current)return;
  pending.current=null;setConfirmation(null);
  void services.executeSelection(current.prepared.selection,current.prepared.input,{prepared:current.prepared}).then(current.resolve,error=>current.reject(error instanceof Error?error:Error('本次制作未完成，请核对原回执')));
 };
 const snapshot=record(confirmation?.prepared.plan.creator_snapshot),profile=record(snapshot.profile),input=record(confirmation?.prepared.plan.production_input);
 if(pathOnly)return <PrivateSkillDetail skill={skill} profileId={profileId} close={close}/>;
 return <>
  <SkillDrawer skillName={name} persona={profileId} onClose={close} onConfigured={reload}
   services={{...services,execute}} onInputChange={cancelPreview}
   extension={execution.questions.length||skill?.origin!=='easel'?<>
    {execution.questions.length>0&&<QuestionCards questions={execution.questions} services={services.questionServices}
     onDone={id=>services.closeQuestion(id)} onClosed={id=>services.closeQuestion(id)}/>}
    {skill?.origin!=='easel'&&<div className="panel">
    <div className="panel-title">项目技能</div>
    {runnable.length>1&&<SettingsSelect label="本次技能动作" value={actionId} options={[{value:'',label:'选择本次动作'},...runnable.map(choice=>({value:choice.id,label:choice.label}))]}
     onChange={value=>{cancelPreview();setActionId(value)}}/>}
    <p>{skill?.display_name||name} · v{skill?.version}</p>
    {skill?.reason&&<p>{skill.reason}</p>}
    {choices.filter(choice=>choice.selection.path).map(choice=><button key={choice.id} className="btn" onClick={()=>vm.navigate(nativeSkillDestination(choice.selection,profileId)!)}>{choice.label}</button>)}
    {!choices.length&&<p>此技能需要在准确作品版本中选择动作。</p>}
    <button className="btn" onClick={()=>vm.navigate('/toolbox?section=skills&item='+encodeURIComponent(skill?.skill_id||skill?.id||name))}>版本与试用</button>
   </div>}
   </>:undefined}/>
  <Drawer open={!!confirmation} title="确认本次制作" onClose={cancelPreview}>
   {confirmation&&<>
    <p><strong>画像：</strong>{string(profile.name)||profileId}</p>
    <p><strong>技能：</strong>{array<JsonRecord>(snapshot.skills).map(item=>(string(item.name)||string(item.id))+' · v'+String(item.version)).join('、')}</p>
    <p><strong>本次动作：</strong>{confirmation.prepared.selection.label}</p>
    <p><strong>制作目标：</strong>{string(input.title)}</p>
    <pre className="ew-preserve">{string(input.material)||confirmation.prepared.input}</pre>
    <p>本次仅制作，不采纳、归档或发布。</p>
    <TextRecord title="完整冻结制作指令" value={record(confirmation.prepared.plan.execution_prompt).body}/>
    <div className="ew-row"><button className="btn" onClick={cancelPreview}>取消</button><button className="btn btn-primary" onClick={confirm}>确认本次制作</button></div>
   </>}
  </Drawer>
 </>;
}

function PrivateSkillDetail({skill,profileId,close}:{skill:NativeSkill;profileId:string;close:()=>void}){
 const resource=useResource<CreatorBootstrap>('/api/creator/bootstrap');
 return resource.data?<SkillDetail id={skill.skill_id||skill.id||skill.name} version={String(skill.version)} data={resource.data} profileId={profileId} onClose={close}/>
  :<Drawer open title="读取技能" onClose={close}><Notice sources={[resource]}/>{!resource.error&&<p role="status">正在读取技能版本…</p>}</Drawer>;
}
