import type {SettingsApi} from '../../components/SettingsApi';
import type {WorkbenchClient} from '../core/client';
import {record, type JsonRecord} from '../core/models';
import {requestFingerprint} from '../../lib/interaction';

/** Provider keys stay in the live form and the HTTPS request only. */
export function workbenchSettingsApi(client:WorkbenchClient):SettingsApi {
 let revision=0;
 const read=async<T>(path:string):Promise<T>=>{const value=await client.api.get<T>(path);const data=record(value);if(typeof data.revision==='number')revision=Math.max(revision,data.revision);return value};
 const command=async<T>(path:string,fields:JsonRecord):Promise<T>=>{
  const requestSignature=await requestFingerprint(fields);
  const known=record(client.operation('settings').getState().result);if(typeof known.revision==='number')revision=Math.max(revision,known.revision);
  const result=await client.mutate<T>('settings',path,{...fields,expected_revision:revision},{metadataOnly:true,requestSignature,receiptPath:id=>'/api/settings/operations/'+encodeURIComponent(id)});
  const data=record(result);if(typeof data.revision==='number')revision=Math.max(revision,data.revision);return result;
 };
 return {
  fetchHarnessSettings:()=>read('/api/settings/harness'),
  saveHarnessSettings:(runtime,model,sandbox,codex_auto_approve)=>command('/api/settings/harness',{runtime,model,sandbox,...(codex_auto_approve===undefined?{}:{codex_auto_approve})}),
  fetchHarnessModels:runtime=>command('/api/settings/harness/models/'+encodeURIComponent(runtime),{}),
  fetchModelChannels:runtime=>read('/api/settings/models'+(runtime?'?runtime='+encodeURIComponent(runtime):'')),
  saveModelConfig:(channel,rows)=>command('/api/settings/models/save',{channel,rows}),
  runChannelSelftest:channel=>command('/api/settings/models/selftest',{channel}),
  fetchLocalAgents:()=>read('/api/settings/local-agents'),
  enableLocalAgent:(agent_id,model='')=>command('/api/settings/local-agents/enable',{agent_id,model}),
  fetchAvailableModels:(baseUrl,key,protocol,slot='',name='')=>command('/api/settings/models/available',{baseUrl,key,protocol,slot,name}),
  fetchEnvTools:refresh=>read('/api/env/tools'+(refresh?'?refresh=1':'')),
  startEnvInstall:tool_id=>command('/api/env/install',{tool_id}),
  fetchEnvJob:id=>read('/api/env/job/'+encodeURIComponent(id)),
 };
}
