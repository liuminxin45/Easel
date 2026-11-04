import {useCallback} from 'react';
import SkillPage from '../../components/SkillPage';
import {useWorkbench,useViewState} from './hooks';
import {workbenchSkillIcons} from './skillIcons';

/** The original Easel page owns catalog, drawer, configuration and execution. */
export function NativeSkills({profileId}:{profileId:string}){
 const vm=useWorkbench(),viewState=useViewState('skills:'+profileId,{query:''});
 const onContentReady=useCallback(()=>vm.navigation.contentReady?.({entryId:vm.navigation.entryKey}),[vm.navigation.entryKey,vm.navigation.contentReady]);
 return <SkillPage persona={profileId} viewState={viewState} onContentReady={onContentReady} icons={workbenchSkillIcons}/>;
}
