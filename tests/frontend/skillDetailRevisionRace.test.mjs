import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';

const record=value=>value&&typeof value==='object'?value:{};
const string=value=>typeof value==='string'?value:'';
function fixture(){
 const reads=[],writes=[],acknowledgements=[];let revision=8,deferSaves=false,notifyWrite;
 const whenWritten=new Promise(resolve=>{notifyWrite=resolve});
 const client={
  authenticationEpoch:1,session:{getState:()=>({config:{csrf:'csrf-exact'}})},
  drafts:{get:()=>undefined,set:()=>true},invalidate:async()=>{},
  api:{get:path=>{
   assert.equal(path,'/api/skill/temp-method');
   return new Promise(resolve=>reads.push(resolve));
  }},
  mutate:async(...args)=>{
   writes.push(args);notifyWrite();const [,path,fields,options]=args;
   assert.equal(path,'/api/env');assert.equal(options.metadataOnly,true);
   if(fields.expected_revision!==revision)throw Object.assign(Error('配置已有新版本'),{status:409});
   const result={ok:true,revision:++revision,skills:{'temp-method':true}};
   return deferSaves?new Promise(resolve=>acknowledgements.push(()=>resolve(result))):result;
  },
 };
 const {createSkillServices}=moduleLoader({imports:{
  '@workbench/core':{record,string},'./chatRuntime':{sessionRuntime:()=>assert.fail('Detail reads must not execute a native turn')},
  './ChatSessionView':{nativeSkillChoices:()=>[]},
 }})('workbench/ui/skillServices.ts');
 const reopen=()=>createSkillServices(client,'profile-exact',[],'temp-method');
 return {
  service:reopen(),reopen,writes,whenWritten,
  resolveRead:(index,parent)=>reads[index]({name:'temp-method',body:'visible detail '+parent,needsApi:true,apiConfigured:true,configuration_revision:parent}),
  setRevision:value=>{revision=value},setDeferredSaves:value=>{deferSaves=value},acknowledge:index=>acknowledgements[index](),
 };
}

test('an old closed drawer response cannot replace the reopened visible detail revision',async()=>{
 const f=fixture(),old=f.service.loadDetail('temp-method'),reopened=f.reopen(),latest=reopened.loadDetail('temp-method');
 f.setRevision(9);f.resolveRead(1,9);const visible=await latest;assert.equal(visible.configuration_revision,9);
 f.resolveRead(0,8);await old;
 await assert.doesNotReject(reopened.saveEnv({IMG_API_KEY:'TEMP-new-value'}));
 assert.equal(f.writes[0][2].expected_revision,visible.configuration_revision);
});

test('a late older detail cannot supply a parent when the newest detail has no verified revision',async()=>{
 const f=fixture(),old=f.service.loadDetail('temp-method'),latest=f.reopen().loadDetail('temp-method');
 f.resolveRead(1,undefined);await latest;f.resolveRead(0,8);await old;
 await assert.rejects(f.service.saveEnv({IMG_API_KEY:'TEMP-not-sent'}),/核对配置版本/);
 assert.equal(f.writes.length,0);
});

test('an old save acknowledgement cannot replace a newer visible detail revision',async()=>{
 const f=fixture(),initial=f.service.loadDetail('temp-method');f.resolveRead(0,8);await initial;
 f.setDeferredSaves(true);const saving=f.service.saveEnv({IMG_API_KEY:'TEMP-first-value'});await f.whenWritten;
 assert.equal(f.writes[0][2].expected_revision,8);
 f.setRevision(10);const reopened=f.reopen(),latest=reopened.loadDetail('temp-method');f.resolveRead(1,10);await latest;
 f.acknowledge(0);assert.equal((await saving).revision,9);
 f.setDeferredSaves(false);await assert.doesNotReject(reopened.saveEnv({IMG_API_KEY:'TEMP-second-value'}));
 assert.equal(f.writes[1][2].expected_revision,10);
});
