import {useCallback,useEffect,useRef,useState} from 'react';
import {useOperation,useResource,useWorkbench} from './react';
import {record,type JsonRecord} from './models';
import {accountAutoCheckCountdown,accountAutoCheckMessage,accountAutoCheckError,computerExtensionObservation,type AccountAutoCheckState} from './extension-discovery';

const path='/api/distribution/auto-check';
export const accountAutoCheckScopes={ensure:'extension:auto-check:ensure',control:'extension:auto-check:control'} as const;
/** The view observes one server monitor. It never ticks it or schedules jobs. */
export function useAccountAutoCheck(){
 const {client,ready}=useWorkbench(),remote=useResource<AccountAutoCheckState>(ready?path:null,{interval:5000});
 const ensure=useOperation(accountAutoCheckScopes.ensure),control=useOperation(accountAutoCheckScopes.control),ensured=useRef(false),alive=useRef(true);
 const [commandError,setCommandError]=useState(''),[clock,setClock]=useState(0),anchor=useRef({server:Date.now(),monotonic:performance.now()});
 useEffect(()=>{alive.current=true;return()=>{alive.current=false}},[]);
 const reload=remote.reload;
 const accept=useCallback(async(_value?:JsonRecord)=>{if(alive.current){setCommandError('');await reload()}},[reload]);
 useEffect(()=>{
  if(!ready||ensured.current)return;ensured.current=true;
  if(client.operation(accountAutoCheckScopes.ensure).getState().pending)return;
  void client.mutate(accountAutoCheckScopes.ensure,path,{id:crypto.randomUUID(),action:'ensure'}).then(()=>{if(alive.current)void reload()}).catch(error=>{if(alive.current)setCommandError(error instanceof Error?error.message:'自动检测状态尚未确认')});
 },[client,ready,reload]);
 useEffect(()=>{const server=Date.parse(remote.data?.server_now||'');if(Number.isFinite(server)){anchor.current={server,monotonic:performance.now()};setClock(server)}},[remote.data]);
 useEffect(()=>{
  const update=()=>{if(!document.hidden)setClock(anchor.current.server+performance.now()-anchor.current.monotonic)};
  const resume=()=>{if(!document.hidden){update();if(ready)void reload()}};
  const timer=setInterval(update,1000);document.addEventListener('visibilitychange',resume);
  return()=>{clearInterval(timer);document.removeEventListener('visibilitychange',resume)};
 },[ready,reload]);
 const command=useCallback(async(action:'set-enabled'|'retry-now',enabled?:boolean)=>{
  setCommandError('');try{await client.mutate(accountAutoCheckScopes.control,path,{id:crypto.randomUUID(),action,...(action==='set-enabled'?{enabled}: {})});if(alive.current)await reload()}
  catch(error){if(alive.current)setCommandError(error instanceof Error?error.message:'检测设置尚未保存')}
 },[client,reload]);
 const state=remote.data,observation=computerExtensionObservation(state?.last_success_observation,'computer_check');
 const running=!!state?.current_check_id||!!state&&['scheduled','launch_requested','page_ready','extension_started','launch_uncertain','recovering'].includes(state.phase);
 return {state,observation,ready,loading:remote.loading,busy:ensure.busy||control.busy,
  pending:!!ensure.pending||!!control.pending,ensure,control,accept,
  statusText:accountAutoCheckMessage(state),countdown:accountAutoCheckCountdown(state,clock),
  error:remote.error||(!ensure.pending&&!control.pending?commandError:''),failure:accountAutoCheckError(state),
  running,retrying:!!state&&['retry_wait','recovering'].includes(state.phase),
  setEnabled:(enabled:boolean)=>command('set-enabled',enabled),retry:()=>command('retry-now'),reload,
  runtime:record(state?.runtime)};
}
