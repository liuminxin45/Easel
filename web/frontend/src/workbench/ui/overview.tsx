import {useWorkbench} from '@workbench/core';
import EaselSubNav from '../../components/SubNav';
import type {Page} from '../../components/Sidebar';
import {NativeDashboard,NativeLibrary,NativeTopics,NativeBreakdown,nativePageRoutes} from './nativePages';

export const workspaceTabs=Object.entries(nativePageRoutes).filter(([page])=>['trends','ideas','calendar','publish','breakdown'].includes(page));
export function SubNav({path}:{path?:string}){
 const vm=useWorkbench(),current=Object.entries(nativePageRoutes).find(([,route])=>route===(path||vm.navigation.path))?.[0] as Page||'dashboard';
 return <EaselSubNav current={current} onNavigate={page=>vm.navigate(nativePageRoutes[page]||'/toolbox')}/>;
}
export function Dashboard({profileId,onUseTopic}:{profileId:string;onUseTopic:(title:string,sourceId?:string,note?:string)=>void}){return <NativeDashboard profileId={profileId} onUseTopic={onUseTopic}/>}
export function Library({format: _format='',history: _history=false}:{format?:string;history?:boolean}){const vm=useWorkbench(),search=new URL(vm.navigation.path,location.origin).searchParams;return <NativeLibrary jumpPath={search.get('path')||(search.get('session')?'native-session-'+search.get('session'):undefined)}/>}
export function Research({profileId,search,onUseTopic}:{profileId:string;search:URLSearchParams;onUseTopic:(title:string,sourceId?:string,note?:string)=>void}){
 return search.get('pane')==='breakdown'?<NativeBreakdown profileId={profileId} search={search}/>:<NativeTopics onUseTopic={onUseTopic}/>;
}
