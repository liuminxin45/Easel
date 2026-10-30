import {useCallback,useMemo,useSyncExternalStore} from 'react';
import DashboardPage from '../../components/DashboardPage';
import OutputsPage from '../../components/OutputsPage';
import IdeasPage,{type IdeasPageDraft} from '../../components/IdeasPage';
import TrendsPage from '../../components/TrendsPage';
import CalendarPage from '../../components/CalendarPage';
import BreakdownPage from '../../components/BreakdownPage';
import type {Page} from '../../components/Sidebar';
import {nativePageRoutes} from '../platform/native-routes';
import type {OutputNode} from '../../lib/api';
import {useWorkbench,useResource,useDraft,creatorLaunchSelection,workPath,record,string,array,type CreatorBootstrap,type JsonRecord} from '@workbench/core';
import {Notice} from './common';
import {SkillTask} from './management';

/** Only route/data adaptation lives here. Native pages own their complete UI. */
export {nativePageRoutes} from '../platform/native-routes';

const compactDashboardQuery='(max-width: 900px), (max-width: 1100px) and (max-height: 500px)';
const compactDashboard=()=>matchMedia(compactDashboardQuery).matches;
function subscribeDashboardLayout(change:()=>void){
 const media=matchMedia(compactDashboardQuery);media.addEventListener('change',change);
 return()=>media.removeEventListener('change',change);
}

export function NativeDashboard({profileId,onUseTopic}:{profileId:string;onUseTopic:(title:string)=>void}){
 const vm=useWorkbench(),status=useResource<JsonRecord>('/api/status');
 const compact=useSyncExternalStore(subscribeDashboardLayout,compactDashboard,()=>false);
 return <DashboardPage persona={profileId} gatewayStatus={status.data?.gateway===true?'connected':'disconnected'}
  apiDirect={status.data?.runtime==='api'} agentRuntime={string(status.data?.runtime)||'codex'}
  persistAnalytics={false} verifyAccountsOnMount={false} listMaxHeight={compact?undefined:360}
  onNavigate={page=>vm.navigate(nativePageRoutes[page]||'/toolbox')} onUseTopic={onUseTopic}/>;
}

function ProjectVersion({project}:{project:OutputNode}){
 const vm=useWorkbench(),meta=record(project.meta),workId=string(meta.work_id),versionId=string(meta.version_id);
 if(!workId)return null;
 return <div className="panel"><button className="btn" onClick={()=>vm.navigate(workPath({id:workId},versionId||undefined))}>查看准确版本、采纳与交付</button></div>;
}

export function NativeLibrary({jumpPath}:{jumpPath?:string}){
 const renderProject=useCallback((project:OutputNode)=><ProjectVersion project={project}/>,[]);
 return <OutputsPage jumpPath={jumpPath} canDelete={()=>false} renderProjectDetails={renderProject}/>;
}

export function NativeTopics({onUseTopic}:{onUseTopic:(title:string)=>void}){
 const vm=useWorkbench(),draftStore=useMemo(()=>({
  read:()=>vm.client.drafts.get<IdeasPageDraft>('easel:topic-form'),
  write:(draft:IdeasPageDraft)=>{vm.client.drafts.set('easel:topic-form',draft)},
  remove:()=>vm.client.drafts.remove('easel:topic-form'),
 }),[vm.client]);
 return <IdeasPage onUseTopic={onUseTopic} draftStore={draftStore}/>;
}

export function NativeTrends({onUseTopic}:{onUseTopic:(title:string)=>void}){
 const vm=useWorkbench();
 const refreshAll=useCallback(()=>vm.service.collectAll(),[vm.service]);
 return <TrendsPage onUseTopic={onUseTopic} refreshAll={refreshAll} listLimit={1000}/>;
}

export function NativeCalendar(){return <CalendarPage/>}

export function NativeBreakdown({profileId,search}:{profileId:string;search:URLSearchParams}){
 const vm=useWorkbench(),creators=useResource<CreatorBootstrap>('/api/creator/bootstrap');
 const [draft,patch]=useDraft('easel:reference',{text:'',goal:'',task_id:''});
 const task=useResource<JsonRecord>(draft.task_id?'/api/creator/experience/'+encodeURIComponent(draft.task_id):null,{interval:3000});
 const busy=!!draft.task_id&&!['completed','failed','stopped','cancelled'].includes(string(task.data?.status));
 const analyze=async(input:string)=>{
  if(!creators.data)throw Error('画像与准确技能版本正在读取，请稍后重试。');
  const creator=creatorLaunchSelection(creators.data,profileId,'reference',search);
  if(!creator)throw Error('准确拆解技能版本尚未核对，输入已保留。');
  const saved=await vm.service.creativeCommand('import-sample',{title:'参考拆解：'+input.trim().slice(0,40),body:input,url:'',goal:draft.goal,files:[]});
  const evidence=array<string>(record(saved.result).evidence_ids)[0];
  if(!evidence)throw Error('原件已保存，索引尚未核对。');
  const result=await vm.service.creatorCommand('reference-analyze',{profile_id:profileId,evidence_id:evidence,goal:draft.goal,creator});
  const id=string(record(result.result).task_id);patch({task_id:id});
  return ''; // The task slot reads the actual result; an acknowledgement is not content.
 };
 return <><Notice sources={[creators]}/><BreakdownPage persona={profileId} onAnalyze={analyze}
  inputState={{value:draft.text,onChange:text=>patch({text})}} analysisBusy={busy}
  resultContent={draft.task_id?<SkillTask id={draft.task_id}/>:undefined}/></>;
}

export interface WorkbenchNativePageProps {page:Page;profileId:string;onUseTopic:(title:string)=>void;search?:URLSearchParams}
export function WorkbenchNativePage({page,profileId,onUseTopic,search=new URLSearchParams()}:WorkbenchNativePageProps){
 switch(page){
  case 'dashboard':return <NativeDashboard profileId={profileId} onUseTopic={onUseTopic}/>;
  case 'outputs':return <NativeLibrary jumpPath={search.get('path')||undefined}/>;
  case 'ideas':return <NativeTopics onUseTopic={onUseTopic}/>;
  case 'trends':return <NativeTrends onUseTopic={onUseTopic}/>;
  case 'calendar':return <NativeCalendar/>;
  case 'breakdown':return <NativeBreakdown profileId={profileId} search={search}/>;
  default:return null;
 }
}
