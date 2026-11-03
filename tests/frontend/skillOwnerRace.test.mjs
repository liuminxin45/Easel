import assert from 'node:assert/strict';
import {createRequire} from 'node:module';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';

const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url));
const {createStore}=require('zustand/vanilla');
const record=value=>value&&typeof value==='object'?value:{};
const string=value=>typeof value==='string'?value:'';
const flush=()=>new Promise(resolve=>setImmediate(resolve));

async function fixture(){
 const selection={skill_id:'temp-method',version:3,action_id:'native',requires_plan:false,label:'TEMP',source_revision:'exact-source'};
 const storage=new Map([['skill:execution:profile-exact:temp-method:native',{
  sessionId:'old-session',turnId:'old-turn',input:'old input',selection,state:'submitted',
 }]]);
 const question={id:'new-permission',status:'pending',questions:[{
  questionId:'allow-exact',header:'准确原生授权',question:'允许本轮请求吗？',options:[{label:'允许'},{label:'拒绝'}],multiSelect:false,
 }]};
 const calls={submissions:[],connections:[],answers:[],statuses:[]};
 let oldReads=0,resolveOld,resolveNew,newTurn;
 function runtime(sessionId){
  const state=createStore(()=>({running:false,error:'',stream:undefined}));
  return {
   state,completed:new Set(),saved:()=>newTurn?{...newTurn,state:'accepted'}:undefined,
   submit:async turn=>{
    newTurn=turn;calls.submissions.push({sessionId,turn});
    state.setState({running:true,stream:{content:'',thinking:'',activity:'等待本轮授权',questions:[question]}});
   },
   connect:(...args)=>calls.connections.push({sessionId,args}),
   answer:async payload=>{calls.answers.push({sessionId,turnId:newTurn?.turnId,payload});return {ok:true}},
   status:async ids=>{calls.statuses.push({sessionId,ids});return Object.fromEntries(ids.map(id=>[id,{status:'pending'}]))},
   closeQuestion:id=>state.setState({stream:{...state.getState().stream,questions:(state.getState().stream?.questions||[]).filter(item=>item.id!==id)}}),
  };
 }
 const runtimes=new Map([['old-session',runtime('old-session')],['new-session',runtime('new-session')]]);
 const client={
  authenticationEpoch:1,session:{getState:()=>({config:{csrf:'csrf-exact'}})},
  drafts:{get:key=>storage.get(key),set:(key,value)=>{storage.set(key,value);return true}},invalidate:async()=>{},
  mutate:async(_scope,path)=>{assert.equal(path,'/api/chat/sessions');return {id:'new-session',runtime:'codex'}},
  api:{get:async path=>{
   if(path.includes('/old-session?')){
    if(++oldReads===1)return new Promise(resolve=>{resolveOld=resolve});
    return {session_id:'old-session',turn_id:'old-turn',execution_status:'completed',delivery_state:'accepted',hook_status:'completed'};
   }
   assert.equal(path,'/api/chat/last/new-session?turn_id='+newTurn.turnId);
   return new Promise(resolve=>{resolveNew=resolve});
  }},
 };
 const {createSkillServices}=moduleLoader({imports:{
  '@workbench/core':{record,string,sessionOpenFlows:()=>({open:async()=>({id:'new-session',runtime:'codex'})})},'./chatRuntime':{sessionRuntime:(_client,id)=>runtimes.get(id)},
  './ChatSessionView':{nativeSkillChoices:()=>[{selection,disabled:false}]},
 }})('workbench/ui/skillServices.ts');
 const service=createSkillServices(client,'profile-exact',[],'temp-method');
 service.resume();await flush();assert.equal(typeof resolveOld,'function');
 const execution=service.execute('temp-method','new original input');
 for(let attempt=0;attempt<5&&!resolveNew;attempt++)await flush();
 assert.equal(typeof resolveNew,'function');
 assert.equal(service.execution.getState().sessionId,'new-session');assert.equal(service.execution.getState().turnId,newTurn.turnId);
 assert.equal(service.execution.getState().questions[0],question);
 return {
  service,question,calls,newTurn,
  finishOld:async state=>{resolveOld({session_id:'old-session',turn_id:'old-turn',execution_status:state,delivery_state:'accepted',hook_status:'completed'});await flush()},
  complete:async()=>{resolveNew({session_id:'new-session',turn_id:newTurn.turnId,execution_status:'completed',delivery_state:'accepted',hook_status:'completed',output:'exact real turn result'});return execution},
 };
}

for(const delayedState of ['completed','running']){
 test('late old '+delayedState+' receipt cannot clear or replace the new native permission owner',async()=>{
  const f=await fixture();
  try{
   await f.finishOld(delayedState);
   const current=f.service.execution.getState();
   assert.equal(current.sessionId,'new-session');assert.equal(current.turnId,f.newTurn.turnId);
   assert.equal(current.questions.length,1);assert.equal(current.questions[0],f.question);
   assert.deepEqual(f.calls.connections,[],'A delayed old receipt must not reconnect an obsolete runtime');
   const statuses=await f.service.questionServices.status([f.question.id]);assert.equal(statuses[f.question.id].status,'pending');
   const payload={questionId:f.question.id,answers:{'allow-exact':['允许']}};
   assert.equal((await f.service.questionServices.answer(payload)).ok,true);
   assert.deepEqual(f.calls.answers,[{sessionId:'new-session',turnId:f.newTurn.turnId,payload}]);
   assert.deepEqual(f.calls.statuses,[{sessionId:'new-session',ids:[f.question.id]}]);
   f.service.closeQuestion(f.question.id);assert.deepEqual(f.service.execution.getState().questions,[]);
   assert.equal(f.calls.submissions.length,1);assert.equal(f.calls.submissions[0].sessionId,'new-session');
   assert.equal(f.calls.submissions[0].turn.message,'new original input');
  }finally{
   assert.equal((await f.complete()).response,'exact real turn result');
  }
 });
}
