import type {SkillDetail, SkillResponse, ChatQuestion} from '../../lib/api';
import {createStore,type StoreApi} from 'zustand/vanilla';
import {requestFingerprint} from '../../lib/interaction';
import {record,string,type JsonRecord,type WorkbenchClient} from '@workbench/core';
import {sessionRuntime,type FrozenTurn} from './chatRuntime';
import {nativeSkillChoices,type NativeSelection,type NativeSkill} from './ChatSessionView';

export interface PreparedSkillExecution {
  plan:JsonRecord; token:string; sessionId:string; turnId:string;
  selection:NativeSelection; input:string;
}
interface SkillRun {sessionId:string;turnId:string;input:string;selection:NativeSelection;state:'planned'|'submitted'|'finished'}
const preparedRequests=new WeakMap<PreparedSkillExecution,JsonRecord>();
interface ExecutionView {sessionId:string;turnId:string;questions:ChatQuestion[]}
interface ExecutionOwner {store:StoreApi<ExecutionView>;runtime?:ReturnType<typeof sessionRuntime>;release?:()=>void}
const executionOwners=new WeakMap<WorkbenchClient,Map<string,ExecutionOwner>>();
const pause=()=>new Promise<void>(resolve=>setTimeout(resolve,1000));
const sameSelection=(a:NativeSelection,b:NativeSelection)=>JSON.stringify(a)===JSON.stringify(b);

/** The official drawer remains the view. Execution uses the existing server turn. */
export function createSkillServices(client:WorkbenchClient,profileId:string,skills:NativeSkill[],skillName=''){
  let owners=executionOwners.get(client);if(!owners){owners=new Map();executionOwners.set(client,owners);}
  const ownerKey=client.authenticationEpoch+':'+profileId+':'+skillName;
  let owner=owners.get(ownerKey);if(!owner){owner={store:createStore<ExecutionView>(()=>({sessionId:'',turnId:'',questions:[]}))};owners.set(ownerKey,owner);}
  const execution=owner.store,executionOwner=owner;
  const observe=(run:SkillRun)=>{
    executionOwner.release?.();const runtime=sessionRuntime(client,run.sessionId);executionOwner.runtime=runtime;
    const update=()=>execution.setState({sessionId:run.sessionId,turnId:run.turnId,questions:runtime.state.getState().stream?.questions||[]});
    executionOwner.release=runtime.state.subscribe(update);update();
  };
  const keyFor=(selection:NativeSelection)=>'skill:execution:'+profileId+':'+selection.skill_id+':'+selection.action_id;
  const csrf=()=>client.session.getState().config?.csrf||'';
  const save=(key:string,value:SkillRun)=>{if(!client.drafts.set(key,value))throw Error('本机原请求标识未保存，尚未开始新的制作。');};
  const checkSelection=(selection:NativeSelection)=>{
    if(selection.path)throw Error('请从下方入口选择准确作品或账号后执行此动作。');
    const choice=nativeSkillChoices(skills).find(item=>sameSelection(item.selection,selection));
    if(!choice||choice.disabled)throw Error(choice?.description||'所选技能版本尚不可执行，请重新读取技能。');
  };
  const requestFor=async(selection:NativeSelection,input:string):Promise<{run:SkillRun;request:JsonRecord}>=>{
    checkSelection(selection);if(!input.trim())throw Error('请先输入本次目标或素材。');
    const key=keyFor(selection),saved=client.drafts.get<SkillRun>(key);
    if(saved?.state==='submitted'){
      if(saved.input!==input||!sameSelection(saved.selection,selection))throw Error('原任务尚未核对，请先恢复原输入；不会重新发送。');
      return {run:saved,request:requestBody(saved)};
    }
    if(saved?.state==='planned'&&saved.input===input&&sameSelection(saved.selection,selection))return {run:saved,request:requestBody(saved)};
    const created=await client.mutate<JsonRecord>('skill:session:'+profileId+':'+selection.skill_id,'/api/chat/sessions',{action:'create',profile_id:profileId});
    const session=record(created.session||record(created.result).session||created),sessionId=string(session.id);
    if(!sessionId)throw Error('原生会话尚未确认创建，请核对原回执。');
    if(session.runtime==='api')throw Error('仅聊天模式不能运行本机技能，请在设置中选择原生 Agent 后新建会话。');
    const run:SkillRun={sessionId,turnId:crypto.randomUUID(),input,selection:{...selection},state:'planned'};
    save(key,run);return {run,request:requestBody(run)};
  };
  function requestBody(run:SkillRun):JsonRecord{
    const choice=run.selection;
    return {sessionId:run.sessionId,turnId:run.turnId,message:run.input,attachments:[],context:{profile_id:profileId,
      skill_id:choice.skill_id,version:choice.version,action_id:choice.action_id,
      ...(choice.source_revision?{skill_revision:choice.source_revision}:{}),...(choice.trial?{trial:true}:{})}};
  }
  const result=async(run:SkillRun):Promise<SkillResponse>=>{
    const epoch=client.authenticationEpoch,deadline=Date.now()+30*60*1000;
    while(Date.now()<deadline){
      if(epoch!==client.authenticationEpoch||client.session.getState().expired)throw Error('登录已变化，原任务及输入已保留，请重新登录核对。');
      let receipt:JsonRecord;
      try{receipt=await client.api.get<JsonRecord>('/api/chat/last/'+encodeURIComponent(run.sessionId)+'?turn_id='+encodeURIComponent(run.turnId));}
      catch(error){if((error as {status?:number}).status===401)throw error;await pause();continue;}
      if(string(receipt.turn_id)!==run.turnId||string(receipt.session_id)!==run.sessionId)throw Error('原任务回执身份未能核对；不会重复发送。');
      const state=string(receipt.execution_status)||string(receipt.stop_reason);
      if(state==='unknown'||receipt.delivery_state==='unknown')throw Object.assign(Error('原任务结果待核对，原输入和文件已保留；不会重新发送。'),{uncertain:true});
      if(['completed','failed','stopped'].includes(state)){
        if(state==='completed'&&string(receipt.hook_status)==='pending'){await pause();continue;}
        if(['failed','unknown'].includes(string(receipt.hook_status)))throw Object.assign(Error('模型回复已保留，制作登记仍待核对；不会重新制作。'),{uncertain:true});
        save(keyFor(run.selection),{...run,state:'finished'});void client.invalidate(['chat','works','creator']);
        if(state!=='completed')throw Error(string(receipt.error)||'本轮'+(state==='stopped'?'已停止':'未完成')+'，原输入与原文件已保留。');
        return {response:string(receipt.output)||string(receipt.text)};
      }
      await pause();
    }
    throw Object.assign(Error('原任务尚未结束，原会话和输入已保留；请核对原任务，不要重复制作。'),{uncertain:true});
  };
  const prepareSelection=async(selection:NativeSelection,input:string):Promise<PreparedSkillExecution>=>{
    const {run,request}=await requestFor(selection,input);
    if(run.state==='submitted')throw Error('原任务已受理，请核对原任务，不能重新确认方案。');
    const value=await client.api.post<JsonRecord>('/api/chat/plan',request,csrf());
    if(string(value.session_id)!==run.sessionId||string(value.turn_id)!==run.turnId||!string(value.plan_token))throw Error('方案身份未核对，没有开始制作。');
    const prepared:PreparedSkillExecution={plan:record(value.plan),token:string(value.plan_token),sessionId:run.sessionId,turnId:run.turnId,selection:{...selection},input};
    preparedRequests.set(prepared,request);return prepared;
  };
  const executeSelection=async(selection:NativeSelection,input:string,options:{prepared?:PreparedSkillExecution}={}):Promise<SkillResponse>=>{
    const existing=client.drafts.get<SkillRun>(keyFor(selection));
    if(selection.requires_plan&&existing?.state!=='submitted'){
      const prepared=options.prepared;
      if(!prepared||!preparedRequests.has(prepared)||prepared.input!==input||!sameSelection(prepared.selection,selection))throw Error('请先核对本次准确制作方案，再确认执行。');
    }
    const {run,request}=await requestFor(selection,input);
    if(run.state==='submitted'){observe(run);return result(run);}
    if(selection.requires_plan){
      const prepared=options.prepared,original=prepared&&preparedRequests.get(prepared);
      if(!prepared||!original||prepared.input!==input||!sameSelection(prepared.selection,selection)||prepared.sessionId!==run.sessionId||prepared.turnId!==run.turnId||JSON.stringify(original)!==JSON.stringify(request))throw Error('请先核对本次准确制作方案，再确认执行。');
      request.context={...record(request.context),plan_token:prepared.token};
    }
    const runtime=sessionRuntime(client,run.sessionId);
    observe(run);
    const turn:FrozenTurn={turnId:run.turnId,message:input,attachments:[],context:record(request.context),state:'connecting',inputs:{text:input,files:[],command:selection}};
    // Save the original identity before the only POST; later clicks only read it.
    save(keyFor(selection),{...run,state:'submitted'});
    await runtime.submit(turn,profileId);
    const saved=runtime.saved();
    if(saved?.state==='rejected'){save(keyFor(selection),{...run,state:'finished'});throw Error(runtime.state.getState().error||'本次请求未受理。');}
    return result(run);
  };
  const resume=()=>{if(skillName){
    for(const choice of nativeSkillChoices(skills).filter(item=>item.selection.skill_id===skillName)){
      const saved=client.drafts.get<SkillRun>(keyFor(choice.selection));
      if(saved?.state!=='submitted')continue;
      observe(saved);const runtime=executionOwner.runtime!;
      if(!runtime.state.getState().running&&!runtime.completed.has(saved.turnId)){
        const pending=runtime.saved();
        runtime.connect(pending||{turnId:saved.turnId,message:saved.input,attachments:[],context:record(requestBody(saved).context),inputs:{text:saved.input,files:[],command:saved.selection},state:'accepted',accepted:true},profileId,true);
      }
      break;
    }
  }};
  return {
    loadDetail:(name:string)=>client.api.get<SkillDetail>('/api/skill/'+encodeURIComponent(name)),
    saveEnv:async(updates:Record<string,string>)=>{
      const current=await client.api.get<JsonRecord>('/api/settings/harness'),fields={updates,expected_revision:current.revision};
      const requestSignature=await requestFingerprint(fields);
      const value=await client.mutate<{ok:boolean;skills:Record<string,boolean>}>('settings','/api/env',fields,{metadataOnly:true,requestSignature,receiptPath:id=>'/api/settings/operations/'+encodeURIComponent(id)});
      void client.invalidate(['creator','easel','settings']);return value;
    },
    execute:async(name:string,input:string,persona?:string)=>{
      if(persona&&persona!==profileId)throw Error('执行画像与原抽屉不同，请重新打开技能后核对。');
      const choice=nativeSkillChoices(skills).find(item=>item.selection.skill_id===name&&!item.selection.path);
      if(!choice)throw Error('请在下方选择准确任务和版本。');
      return executeSelection(choice.selection,input);
    },
    prepareSelection,executeSelection,execution,resume,
    questionServices:{
      answer:(payload:{questionId:string;answers:Record<string,string[]>})=>{
        if(!executionOwner.runtime)throw Error('原生执行尚未开始');return executionOwner.runtime.answer(payload);
      },
      status:(ids:string[])=>{
        if(!executionOwner.runtime)return Promise.resolve({});return executionOwner.runtime.status(ids);
      },
    },
    closeQuestion:(id:string)=>executionOwner.runtime?.closeQuestion(id),
  };
}
