import {array,record,string,type JsonRecord} from '@workbench/core';
import {useResource} from './hooks';
import {Panel,Notice,JsonDetails} from './common';

/** Read-only compatibility for existing reference-analysis task records. */
export function SkillTask({id}:{id:string}){
 const r=useResource<JsonRecord>('/api/creator/experience/'+encodeURIComponent(id),{interval:3000,stopOnTerminal:true}),result=record(r.data?.result),analysis=record(result.analysis);
 return <Panel title={string(r.data?.status)==='completed'?'拆解完成':'拆解进度'}><Notice sources={[r]} message={string(r.data?.error)}/><p>{string(analysis.summary)||string(result.reason)}</p>{array<JsonRecord>(analysis.suggestions).map((s,i)=><div key={i}><h3>{string(s.name)}</h3><p className="ew-preserve">{array<string>(s.instructions).join('\n')}</p><p>{string(s.reason)}</p></div>)}<JsonDetails title="执行记录" value={r.data}/></Panel>;
}
export {NativeProfiles as Profiles} from './nativeProfiles';
export {Accounts} from './PlatformAccounts';
