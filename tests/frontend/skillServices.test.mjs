import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';
const record=value=>value&&typeof value==='object'?value:{};
const string=value=>typeof value==='string'?value:'';
function fixture({planned=false}={}){
 const selection={skill_id:'temp-skill',version:3,action_id:planned?'poster':'native',requires_plan:planned,label:'TEMP',source_revision:'exact-source'};
 const storage=new Map(),submissions=[],mutations=[],posts=[];
 let unknown=false,hook='completed',turn;
 const runtime={submit:async value=>{submissions.push(value);turn=value;},saved:()=>turn?{...turn,state:'accepted'}:undefined,state:{getState:()=>({error:''}),subscribe:()=>()=>{}}};
 const client={authenticationEpoch:1,session:{getState:()=>({config:{csrf:'csrf'}})},
  drafts:{get:key=>storage.get(key),set:(key,value)=>{storage.set(key,value);return true;}},
  invalidate:async()=>{},
  mutate:async(...args)=>{mutations.push(args);return args[1]==='/api/chat/sessions'?{id:'session-exact',runtime:'codex'}:{ok:true,skills:{'temp-skill':true}};},
  api:{get:async path=>{
   if(path==='/api/settings/harness')return {revision:8};
   assert.match(path,/\/api\/chat\/last\/session-exact\?turn_id=/);
   return {session_id:'session-exact',turn_id:turn?.turnId||new URL('https://temp'+path).searchParams.get('turn_id'),execution_status:unknown?'unknown':'completed',delivery_state:unknown?'unknown':'accepted',hook_status:hook,output:'actual completed result'};
  },post:async(path,value)=>{posts.push({path,value});return {plan:{production_input:{material:value.message},creator_snapshot:{skills:[{id:'temp-skill',version:3}]}},plan_token:'exact-preview-token',session_id:value.sessionId,turn_id:value.turnId};}},
 };
 const {createSkillServices}=moduleLoader({imports:{'@workbench/core':{record,string},'./chatRuntime':{sessionRuntime:()=>runtime},'./ChatSessionView':{nativeSkillChoices:()=>[{selection,disabled:false}]}}})('workbench/ui/skillServices.ts');
 return {service:createSkillServices(client,'profile-exact',[]),selection,storage,submissions,mutations,posts,setUnknown:value=>{unknown=value;},setHook:value=>{hook=value;}};
}
test('official execution returns actual original turn result inside the drawer',async()=>{
 const f=fixture(),value=await f.service.execute('temp-skill','original input','profile-exact');assert.equal(value.response,'actual completed result');assert.deepEqual(Object.keys(value),['response']);
 assert.equal(f.submissions.length,1);assert.equal(f.submissions[0].message,'original input');
 assert.equal(f.submissions[0].context.version,3);assert.equal(f.submissions[0].context.skill_revision,'exact-source');
 assert.equal(f.posts.length,0);
});
test('unknown result and failed receiving hook retain original identity and never resend',async()=>{
 for(const kind of ['unknown','hook']){
  const f=fixture();if(kind==='unknown')f.setUnknown(true);else f.setHook('failed');
  await assert.rejects(f.service.execute('temp-skill','original'),error=>error.uncertain===true);
  await assert.rejects(f.service.execute('temp-skill','different'),/原任务/);
  f.setUnknown(false);f.setHook('completed');
  assert.equal((await f.service.execute('temp-skill','original')).response,'actual completed result');
  assert.equal(f.submissions.length,1);assert.equal(f.mutations.length,1);
 }
});
test('production cannot start before exact server preview is confirmed, and editing invalidates it',async()=>{
 const f=fixture({planned:true});
 await assert.rejects(f.service.executeSelection(f.selection,'original'),/方案/);assert.equal(f.mutations.length,0);
 const prepared=await f.service.prepareSelection(f.selection,'original');assert.equal(f.submissions.length,0);
 assert.equal(f.posts[0].path,'/api/chat/plan');assert.equal(prepared.plan.production_input.material,'original');
 await assert.rejects(f.service.executeSelection(f.selection,'edited',{prepared}),/方案/);
 await assert.rejects(f.service.executeSelection({...f.selection,version:4},'original',{prepared}),/方案/);
 assert.equal(f.submissions.length,0);assert.equal(f.mutations.length,1);
 const value=await f.service.executeSelection(f.selection,'original',{prepared});assert.equal(value.response,'actual completed result');
 assert.equal(f.submissions[0].turnId,prepared.turnId);assert.equal(f.submissions[0].context.plan_token,prepared.token);
 assert.equal(f.posts.length,1);
});
test('official credential save uses the settings revision receipt without persisting credentials',async()=>{
 const f=fixture();await f.service.saveEnv({IMG_API_KEY:'private-original-key'});
 const [,path,fields,options]=f.mutations[0];assert.equal(path,'/api/env');assert.equal(fields.expected_revision,8);
 assert.equal(options.metadataOnly,true);assert.equal(options.receiptPath('same'),'/api/settings/operations/same');
 assert.ok(options.requestSignature);assert.doesNotMatch(JSON.stringify([...f.storage]),/private-original-key/);
});
