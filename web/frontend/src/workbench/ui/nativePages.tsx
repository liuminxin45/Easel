import {VersionOperations} from './VersionOperations';
import {useCallback,useMemo,useSyncExternalStore} from 'react';
import DashboardPage,{type DashboardViewState} from '../../components/DashboardPage';
import OutputsPage from '../../components/OutputsPage';
import IdeasPage,{type IdeasPageDraft} from '../../components/IdeasPage';
import TrendsPage,{type TrendsViewState} from '../../components/TrendsPage';
import CalendarPage,{type CalendarDraft,type CalendarViewState} from '../../components/CalendarPage';
import BreakdownPage from '../../components/BreakdownPage';
import type {Page} from '../../components/Sidebar';
import {nativePageRoutes} from '../platform/native-routes';
import {peekApiData,type OutputNode,type TrendSource} from '../../lib/api';
import {creatorLaunchSelection,record,string,array,type CreatorBootstrap,type JsonRecord} from '@workbench/core';
import {useWorkbench,useResource,useDraft,useViewState} from './hooks';
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

export function NativeDashboard({profileId,onUseTopic}:{profileId:string;onUseTopic:(title:string,sourceId?:string,note?:string)=>void}){
 const vm=useWorkbench(),status=useResource<JsonRecord>('/api/status');
 const compact=useSyncExternalStore(subscribeDashboardLayout,compactDashboard,()=>false);
 const viewState=useViewState<DashboardViewState>('dashboard:'+profileId,{platform:'',window:'week'});
 const onContentReady=useCallback(()=>vm.navigation.contentReady?.({entryId:vm.navigation.entryKey}),[vm.navigation.entryKey,vm.navigation.contentReady]);
 return <DashboardPage persona={profileId} gatewayStatus={status.data?.gateway===true?'connected':'disconnected'}
  apiDirect={status.data?.runtime==='api'} agentRuntime={string(status.data?.runtime)||'codex'}
  persistAnalytics={false} verifyAccountsOnMount={false} trendsEmptyState={null} listMaxHeight={compact?undefined:360}
  onContentReady={onContentReady} viewState={viewState}
  onNavigate={page=>vm.navigate(nativePageRoutes[page]||'/toolbox')} onUseTopic={onUseTopic}/>;
}

function ProjectVersion({project}:{project:OutputNode}){
 const meta=record(project.meta),workId=string(meta.work_id),versionId=string(meta.version_id);
 if(!workId)return null;
 return <VersionOperations workId={workId} versionId={versionId}/>;
}

export function NativeLibrary({jumpPath}:{jumpPath?:string}){
 const vm=useWorkbench();
 const viewState=useViewState('outputs',{stack:[] as string[],filter:'all'});
 const onContentReady=useCallback(()=>vm.navigation.contentReady?.({entryId:vm.navigation.entryKey}),[vm.navigation.entryKey,vm.navigation.contentReady]);
 const context=useResource<JsonRecord>(jumpPath?'/api/output-context?'+new URLSearchParams({path:jumpPath}):null);
 const resolved=string(context.data?.canonical_path)||jumpPath;
 const renderProject=useCallback((project:OutputNode)=><ProjectVersion project={project}/>,[]);
 return <OutputsPage jumpPath={resolved} canDelete={()=>false} renderProjectDetails={renderProject} registerLayer={vm.navigation?.registerLayer} viewState={viewState} onContentReady={onContentReady}/>;
}

export function NativeTopics({onUseTopic}:{onUseTopic:(title:string,sourceId?:string,note?:string)=>void}){
 const vm=useWorkbench(),draftStore=useMemo(()=>({
  read:()=>vm.client.drafts.get<IdeasPageDraft>('easel:topic-form'),
  write:(draft:IdeasPageDraft)=>{vm.client.drafts.set('easel:topic-form',draft)},
  remove:()=>vm.client.drafts.remove('easel:topic-form'),
 }),[vm.client]);
 const onContentReady=useCallback(()=>vm.navigation.contentReady?.({entryId:vm.navigation.entryKey}),[vm.navigation.entryKey,vm.navigation.contentReady]);
 return <IdeasPage onUseTopic={onUseTopic} draftStore={draftStore} onContentReady={onContentReady}/>;
}

export function NativeTrends({onUseTopic,search}:{onUseTopic:(title:string,sourceId?:string,note?:string)=>void;search?:URLSearchParams}){
 const vm=useWorkbench();
 const sourceSnapshot=peekApiData<{sources:TrendSource[]}>('/api/trends/sources');
 const declared=search?.get('sources')??search?.get('source');
 const viewState=useViewState<TrendsViewState>('trends',{selected:declared!==undefined&&declared!==null?declared.split(',').filter(Boolean):sourceSnapshot?.sources.filter(source=>source.default).map(source=>source.id)??[],initialized:declared!==undefined&&declared!==null||!!sourceSnapshot});
 const compact=useSyncExternalStore(subscribeDashboardLayout,compactDashboard,()=>false);
 const onContentReady=useCallback(()=>vm.navigation.contentReady?.({entryId:vm.navigation.entryKey}),[vm.navigation.entryKey,vm.navigation.contentReady]);
 const refreshAll=useCallback(()=>vm.service.collectAll(),[vm.service]);
 return <TrendsPage onUseTopic={onUseTopic} onRead={id=>vm.navigate('/news/a/'+encodeURIComponent(id))} refreshAll={refreshAll} listLimit={1000} listMaxHeight={compact?undefined:540} quietBackgroundRefresh viewState={viewState} onContentReady={onContentReady}/>;
}

export function NativeCalendar(){
 const vm=useWorkbench(),viewState=useViewState<CalendarViewState>('calendar',{month:new Date(new Date().getFullYear(),new Date().getMonth(),1).getTime(),filter:'all',showSuggest:true});
 const draftStore=useMemo(()=>{
  const key=(date:string,id?:string|null)=>'easel:calendar:input:'+(id?'edit:'+id:'new:'+date);
  return {read:(date?:string,id?:string|null)=>{const old=vm.client.drafts.get<CalendarDraft>('easel:calendar:input');return date?vm.client.drafts.get<CalendarDraft>(key(date,id))||(old?.form.date===date&&old.editingId===(id||null)?old:null):old},
   write:(value:CalendarDraft)=>{vm.client.drafts.set(key(value.key||value.form.date,value.editingId),value)},
   remove:(value?:CalendarDraft)=>{if(value)vm.client.drafts.remove(key(value.key||value.form.date,value.editingId));const old=vm.client.drafts.get<CalendarDraft>('easel:calendar:input');if(value&&old?.editingId===value.editingId&&JSON.stringify(old.form)===JSON.stringify(value.form))vm.client.drafts.remove('easel:calendar:input')},};
 },[vm.client]);
 const onContentReady=useCallback(()=>vm.navigation.contentReady?.({entryId:vm.navigation.entryKey}),[vm.navigation.entryKey,vm.navigation.contentReady]);
 return <CalendarPage viewState={viewState} draftStore={draftStore} onContentReady={onContentReady} registerLayer={vm.navigation.registerLayer}/>;
}

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

export interface WorkbenchNativePageProps {page:Page;profileId:string;onUseTopic:(title:string,sourceId?:string,note?:string)=>void;search?:URLSearchParams}
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

export function WorkLibrary({id,versionId}:{id:string;versionId?:string}){
 const resource=useResource<import('@workbench/core').Work>('/api/works/'+encodeURIComponent(id));
 const vid=versionId||resource.data?.latest_version||resource.data?.versions.at(-1)?.id;
 return resource.data?<NativeLibrary jumpPath={'workbench-'+id+(vid?'/'+vid:'')}/>:<div className="page-scroll"><Notice sources={[resource]}/>{resource.error&&<button className="btn" onClick={()=>void resource.reload()}>重试</button>}</div>;
}
