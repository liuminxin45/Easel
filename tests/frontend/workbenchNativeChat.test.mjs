import {moduleLoader} from './helpers/modules.mjs';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const sourceRoot=new URL('../../web/frontend/src/',import.meta.url),jsx={jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})};
const plain=value=>JSON.parse(JSON.stringify(value));
const record=value=>value&&typeof value==='object'?value:{},string=value=>typeof value==='string'?value:'',array=value=>Array.isArray(value)?value:[];
const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
function module(file,imports,globals={}){const exports={};runInNewContext(ts.transpileModule(readFileSync(new URL(file,sourceRoot),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,{exports,URL,URLSearchParams,crypto:{randomUUID:()=> 'exact-turn'},...globals,require:id=>id==='react/jsx-runtime'?jsx:imports[id]??(()=>{throw Error('Unexpected dependency '+id)})()});return exports}
const {RequestError}=module('workbench/core/transport.ts',{'./models':{record,string}},{Error});
const {interactionFeedback}=moduleLoader()('lib/interaction.ts');
const productionRecovery=moduleLoader()('workbench/core/production-recovery.ts');
const skill=(id,actions)=>({id,name:id,version:3,available:true,execution_kind:id==='content-production'?'workflow':'agent',launch_actions:actions});
const catalog=[skill('content-production',[{id:'poster',label:'贴图',task:'poster',requires_plan:true},{id:'article',label:'文章',task:'article',requires_plan:true},{id:'change',label:'修改',task:'change',requires_context:true,path:'/works',requires_plan:true}]),skill('topic-research',[{id:'discuss',label:'讨论',task:'discuss'}]),skill('experience-distillation',[{id:'learning',label:'整理经验',task:'learning',requires_context:true,path:'/toolbox?section=skills&pane=experience'}])];
function fixture({draft:initial={text:'  原字材料\n保留  ',files:[]},pendingTurnId,receipt={turn_id:'exact-turn',execution_status:'completed',delivery_state:'known'},search='',postOverride}={}){
 let cursor=0,draft=initial;const hooks=[],effects=[],calls={stream:[],post:[],get:[],navigate:[],invalidate:[]},resources={session:{id:'session-one',profile_id:'oil-pig',messages:[],created:1,title:'原生会话',pendingTurnId},linked_works:[]};
 const react={useMemo:(fn,deps)=>{const index=cursor++,old=hooks[index];if(!old||!deps||!old.deps||deps.length!==old.deps.length||deps.some((value,i)=>!Object.is(value,old.deps[i])))hooks[index]={deps,value:fn()};return hooks[index].value},useState:value=>{const index=cursor++;if(!(index in hooks))hooks[index]=value;return [hooks[index],next=>{hooks[index]=typeof next==='function'?next(hooks[index]):next}]},useRef:value=>{const index=cursor++;if(!(index in hooks))hooks[index]={current:value};return hooks[index]},useEffect:fn=>{cursor++;effects.push(fn)}};
 const vm={config:{csrf:'fixture-csrf'},navigation:{registerLayer:()=>()=>{}},navigate:path=>calls.navigate.push(path),client:{drafts:{get:()=>draft,set:(_key,next)=>{draft=next;return true}},read:async()=>resources,authenticationEpoch:0,session:require('zustand/vanilla').createStore(()=>({config:{csrf:'fixture-csrf'}})),invalidate:async tags=>calls.invalidate.push(tags)},service:{uploadFiles:async files=>files,attach:async files=>files},api:{get:async path=>{calls.get.push(path);return receipt},post:async(path,body,csrf)=>{calls.post.push({path,body,csrf});if(postOverride)return postOverride(path,body,csrf);return path==='/api/chat/plan'?{plan_token:'exact-plan-token',plan:{production_input:{title:'目标'},execution_prompt:{body:'真实冻结指令'}}}:{stopped:true}}}};
 vm.client.api=vm.api;
 const hookSource=readFileSync(new URL('workbench/core/react.tsx',sourceRoot),'utf8'),hookAst=ts.createSourceFile('react.tsx',hookSource,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX),hook=hookAst.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='useAsyncAction'),hookExports={};
 runInNewContext(ts.transpileModule(hook.getText(hookAst),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports:hookExports,useState:react.useState,useRef:react.useRef,useCallback:fn=>fn,useContext:()=>({client:vm.client}),Context:{},useEffect:react.useEffect,interactionFeedback,Error,RequestError});
 const core={...productionRecovery,useWorkbench:()=>vm,useResource:path=>({data:path==='/api/skills'?catalog:path?.startsWith('/api/chat/products/')?resources.product||null:path?.startsWith('/api/works/')?resources.work||null:path?resources:null,error:'',reload:async()=>resources}),useDraft:()=>[draft,patch=>{draft=typeof patch==='function'?patch(draft):{...draft,...patch}}],useAsyncAction:hookExports.useAsyncAction,draftFingerprint:JSON.stringify,fileDownload:file=>'/api/files/'+file.id+'?download=1',array,record,string,workPath:(work,version)=>'/works/'+work.id+(version?'?version='+version:'')};
 const components={ChatPage:()=>{},ProductionPlan:()=>{},ArtifactView:()=>{},ProductionParameters:()=>{},ArtifactGallery:()=>{},CopyableText:()=>{},Completion:()=>{}};
 const products=module('workbench/ui/ChatTurnProducts.tsx',{react,'../../components/ArtifactGallery':components.ArtifactGallery,'../../components/CopyableText':components.CopyableText,'@workbench/core':core,'./WorkCompletion':{Completion:components.Completion},'./common':{Notice:()=>{}}});
 const timers=new Map();
 const runtime=module('workbench/ui/chatRuntime.ts',{'zustand/vanilla':require('zustand/vanilla'),'@workbench/core':core,'../../lib/api':{streamChat:(...args)=>{calls.stream.push(args);return {abort:()=>{}}}}},{setTimeout:(fn,ms)=>{const key={unref(){}};timers.set(key,{fn,ms});return key},clearTimeout:key=>timers.delete(key),AbortSignal});
 const lib=module('workbench/ui/ChatSessionView.tsx',{react,'zustand':{useStore:store=>store.getState()},'./chatRuntime':runtime,'./ChatTurnProducts':products,'../../lib/capabilityMenu':module('lib/capabilityMenu.ts',{}),'../../lib/store':{generateSessionTitle:message=>'首条：'+message},'@workbench/core':core,'../../components/ChatPage':components.ChatPage,'../../lib/api':{streamChat:(...args)=>{calls.stream.push(args);return {abort:()=>{}}}},'./common':{Notice:()=>{},ArtifactView:components.ArtifactView},'./components/icons':{},'./production':{ProductionPlan:components.ProductionPlan},'./ProductionParameters':{ProductionParameters:components.ProductionParameters}});
 const render=()=>{cursor=0;effects.length=0;const tree=lib.ChatSessionView({id:'session-one',search:new URLSearchParams(search)});return {tree,chat:nodes(tree).find(n=>n.type===components.ChatPage).props,plan:nodes(tree).find(n=>n.type===components.ProductionPlan)?.props}};
 return {calls,resources,lib,runtime,vm,components,render,effects,get recoveryCount(){return timers.size},runRecovery:async()=>{const [key,value]=[...timers][0]||[];assert.ok(value,'scheduled recovery');timers.delete(key);value.fn();await tick();await tick()},get draft(){return draft},set draft(next){draft=next}};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
const continuationButtons=value=>nodes(value).filter(node=>node.type==='button'&&node.props.children==='继续制作');
function interruptedMessage(){return {role:'assistant',content:'已保留原文件',status:'stopped',turnId:'interrupted-version',work:{work_id:'exact-work',version_id:'interrupted-version'},business_recovery:{job_id:'interrupted-version',failure_kind:'production',send_state:'submitted',action:'edit_materials',error_code:'native_interrupted',can_continue:true,continuation:{session_id:'session-one',work_id:'exact-work',version_id:'interrupted-version',profile_id:'oil-pig',skill_id:'content-production',skill_version:2}}};}
const historicalInterruption='原生接口已核对本回合中断；未重新发送，原文件保留，制作与交付未完成。';
const retainedDraft=()=>({text:'  后写的新要求\n逐字保留  ',files:[{id:'later-file',name:'后来添加.png'}],command:{skill_id:'content-production',version:2,action_id:'poster',label:'生成贴图',requires_plan:true}});
const savedTurn=(turnId='interrupted-version',state='unknown')=>({turnId,state,message:'旧冻结输入',attachments:[],context:{profile_id:'oil-pig'},inputs:{text:'旧冻结输入',files:[]}});

test('confirmed explicit stop clears stale connection notices while preserving all later editable input',async()=>{
 const f=fixture();f.render().chat.onSend();await tick();const callbacks=f.calls.stream[0];callbacks[16].onAccepted();callbacks[8]();
 const later=retainedDraft();f.draft={...later,pending:f.draft.pending};const runtime=f.runtime.sessionRuntime(f.vm.client,'session-one');
 await runtime.stop();const state=runtime.state.getState();assert.equal(state.error,'');assert.equal(state.feedback,undefined);assert.equal(state.running,false);assert.equal(state.stream,undefined);
 assert.deepEqual(plain(f.draft),later);assert.equal(f.calls.stream.length,1);assert.equal(f.calls.post.length,1);assert.equal(f.calls.post[0].path,'/api/chat/stop');
 callbacks[3]('迟到分片不能复活已停止回合');callbacks[8]();assert.equal(runtime.state.getState().stream,undefined);assert.equal(runtime.state.getState().feedback,undefined);
});
test('an unconfirmed stop preserves the unresolved turn and later editable input',async()=>{
 const f=fixture({postOverride:()=>({stopped:false})});f.render().chat.onSend();await tick();f.calls.stream[0][16].onAccepted();f.calls.stream[0][8]();
 f.draft={...retainedDraft(),pending:f.draft.pending};const before=plain(f.draft),runtime=f.runtime.sessionRuntime(f.vm.client,'session-one'),state=runtime.state.getState();
 await assert.rejects(runtime.stop(),/尚未确认/);assert.deepEqual(plain(f.draft),before);assert.equal(runtime.state.getState(),state);assert.equal(f.calls.stream.length,1);
});
test('server-confirmed history restores either a fresh saved turn or an existing runtime before automatic resume',async()=>{
 for(const mode of ['fresh-saved','existing-runtime','existing-runtime-without-saved']){
  const later=retainedDraft(),f=fixture({draft:{...later,pending:savedTurn()}}),runtime=f.runtime.sessionRuntime(f.vm.client,'session-one');
  if(mode.startsWith('existing-runtime'))runtime.connect(savedTurn(),'oil-pig',true);
  f.draft={...later,...(mode==='existing-runtime-without-saved'?{}:{pending:f.draft.pending})};runtime.state.setState({error:historicalInterruption,feedback:{kind:'status',message:'连接暂时中断，正在恢复原任务状态。输入已保留。'}});
  f.resources.session.messages=[{...interruptedMessage(),business_error:historicalInterruption}];
  const originalStreams=f.calls.stream.length;f.render();for(const effect of [...f.effects])effect();await tick();
  const state=runtime.state.getState();assert.equal(state.error,'',mode);assert.equal(state.feedback,undefined,mode);assert.equal(state.running,false,mode);assert.equal(state.stream,undefined,mode);
  assert.deepEqual(plain(f.draft),later,mode);assert.equal(f.calls.stream.length,originalStreams,mode+' must not subscribe before restoring server history');assert.equal(f.calls.post.length,0);
  assert.equal(continuationButtons(f.render().chat.notice).length,1,mode+' exposes continuation after local stale state is reconciled');
  if(originalStreams){f.calls.stream[0][3]('迟到旧回调');assert.equal(runtime.state.getState().stream,undefined);}
 }
});
test('restoring the confirmed original turn cancels unknown receipt polling without reacknowledging later input',async()=>{
 const f=fixture({receipt:{turn_id:'exact-turn',execution_status:'unknown',delivery_state:'unknown'}});f.render().chat.onSend();await tick();const callbacks=f.calls.stream[0];callbacks[16].onAccepted();callbacks[4]();await tick();await tick();
 assert.equal(f.recoveryCount,1);const later=retainedDraft();f.draft={...later,pending:f.draft.pending};const runtime=f.runtime.sessionRuntime(f.vm.client,'session-one');
 runtime.state.setState({error:historicalInterruption});runtime.restoreStopped('exact-turn',historicalInterruption);
 assert.equal(f.recoveryCount,0);assert.deepEqual(plain(f.draft),later);assert.equal(runtime.state.getState().error,'');assert.equal(runtime.state.getState().feedback,undefined);
 const getCount=f.calls.get.length;callbacks[4]();callbacks[3]('迟到输出');await tick();assert.equal(f.calls.get.length,getCount);assert.equal(f.calls.stream.length,1);assert.equal(f.calls.post.length,0);
});
test('restoring an interrupted turn preserves a distinct hook failure instead of treating it as a historical notice',()=>{
 const later=retainedDraft(),f=fixture({draft:{...later,pending:savedTurn()}}),runtime=f.runtime.sessionRuntime(f.vm.client,'session-one'),hookError='模型原回执已保留，作品记录待核对；没有重跑模型。';
 runtime.state.setState({error:hookError,feedback:{kind:'status',message:'连接暂时中断'}});f.resources.session.messages=[{...interruptedMessage(),business_error:historicalInterruption}];
 f.render();for(const effect of [...f.effects])effect();assert.equal(runtime.state.getState().error,hookError);assert.equal(runtime.state.getState().feedback,undefined);assert.deepEqual(plain(f.draft),later);assert.equal(f.calls.stream.length,0);assert.equal(f.calls.post.length,0);
});
test('restoring one stopped history cannot clear a different saved or active turn or an unrelated runtime',()=>{
 for(const mode of ['saved-other','active-other','active-same-saved-other','unrelated']){
  const later=retainedDraft(),f=fixture({draft:later}),runtime=f.runtime.sessionRuntime(f.vm.client,'session-one');
  if(mode==='active-other')runtime.connect(savedTurn('another-turn'),'oil-pig',true);
  if(mode==='active-same-saved-other')runtime.connect(savedTurn(),'oil-pig',true);
  f.draft={...later,...(mode==='unrelated'?{}:{pending:savedTurn('another-turn')})};runtime.state.setState({error:historicalInterruption,feedback:{kind:'status',message:'仍需核对当前回合'}});
  const before=plain(f.draft),state=runtime.state.getState();runtime.restoreStopped('interrupted-version',historicalInterruption);
  assert.deepEqual(plain(f.draft),before,mode);assert.equal(runtime.state.getState(),state,mode);assert.equal(f.calls.post.length,0);
 }
});
test('unknown unauthorized or still-pending server history never authorizes restoring the local turn',()=>{
 for(const mode of ['unknown','not-authorized','server-pending','wrong-work']){
  const message={...interruptedMessage(),business_error:historicalInterruption},f=fixture({draft:{...retainedDraft(),pending:savedTurn()}}),runtime=f.runtime.sessionRuntime(f.vm.client,'session-one');
  if(mode==='unknown')message.status='unknown';if(mode==='not-authorized')message.business_recovery.can_continue=false;if(mode==='server-pending')f.resources.session.pendingTurnId='interrupted-version';if(mode==='wrong-work')message.work.work_id='other-work';
  f.resources.session.messages=[message];runtime.blocked.add('interrupted-version');runtime.state.setState({error:historicalInterruption,feedback:{kind:'status',message:'原任务执行结果待核对'}});
  const state=runtime.state.getState(),before=plain(f.draft);f.render();for(const effect of [...f.effects])effect();assert.deepEqual(plain(f.draft),before,mode);assert.equal(runtime.state.getState(),state,mode);assert.equal(f.calls.stream.length,0);assert.equal(f.calls.post.length,0);
 }
});

test('a confirmed stopped receipt clears transient and raw interruption notices while preserving later draft and attachments',async()=>{
 const error='原生接口已核对本回合中断；未重新发送，原文件保留，制作与交付未完成。';
 const f=fixture({receipt:{turn_id:'exact-turn',execution_status:'stopped',delivery_state:'interrupted',error}});
 f.render().chat.onSend();await tick();const callbacks=f.calls.stream[0];callbacks[16].onAccepted();callbacks[8]();
 const later={...f.draft,text:'  后写的新草稿\n不许清空  ',files:[{id:'later-attachment',name:'后加素材.png'}]};f.draft=later;
 callbacks[4]();await tick();await tick();const state=f.runtime.sessionRuntime(f.vm.client,'session-one').state.getState();
 assert.equal(state.error,'');assert.equal(state.feedback,undefined);assert.equal(state.running,false);assert.equal(f.draft.pending,undefined);
 assert.equal(f.draft.text,later.text);assert.deepEqual(plain(f.draft.files),later.files);assert.equal(f.calls.stream.length,1);assert.equal(f.calls.post.length,0);
});
test('the latest confirmed interrupted production shows one top continuation action for the original session and frozen version',()=>{
 const f=fixture(),message=interruptedMessage();f.resources.session.messages=[{role:'user',content:'原始贴图请求'},message];
 f.resources.product={work_id:'exact-work',version_id:'interrupted-version',files:[{id:'preserved-file',name:'原文件.png',mime:'image/png'}],incomplete:true};
 const ui=f.render(),buttons=continuationButtons(ui.chat.notice);assert.equal(buttons.length,1);
 assert.ok(nodes(ui.chat.notice).some(node=>node.props.children==='本轮已中断，原文件已保留。'));
 const extra=ui.chat.renderMessageExtra(ui.chat.session.messages.at(-1)),wrapper=extra.type(extra.props),products=wrapper.type(wrapper.props);
 assert.equal(continuationButtons(products).length,0,'the message must not repeat its top continuation action');
 buttons[0].props.onClick();const destination=new URL(f.calls.navigate[0],'https://example.test');
 assert.equal(destination.pathname,'/chat/session-one');assert.deepEqual(Object.fromEntries(destination.searchParams),{work:'exact-work',version:'interrupted-version',skill:'content-production',skill_version:'2',action:'change',continue:'1'});
 assert.equal(f.calls.post.length,0);assert.equal(f.calls.stream.length,0);assert.equal(f.draft.text,'  原字材料\n保留  ');
 const standalone=f.lib.NativeTurnOutputs({message}),standaloneProducts=standalone.type(standalone.props);
 assert.equal(continuationButtons(standaloneProducts).length,1,'standalone registered products retain the default continuation action');
});
test('continuation requires server authorization and exact stopped turn session profile work and version identities',()=>{
 const f=fixture(),message=interruptedMessage(),path=f.lib.confirmedContinuation(message,'session-one','oil-pig');
 assert.ok(path);assert.equal(path,productionRecovery.nativeContinuationPath(message.business_recovery,'exact-work','interrupted-version'));
 const invalid=[
  {...message,status:'unknown'},
  {...message,status:'completed'},
  {...message,turnId:'another-turn'},
  {...message,work:{...message.work,work_id:'another-work'}},
  {...message,work:{...message.work,version_id:'another-version'}},
  {...message,business_recovery:{...message.business_recovery,can_continue:false}},
  {...message,business_recovery:{...message.business_recovery,send_state:'unknown'}},
  {...message,business_recovery:{...message.business_recovery,job_id:'another-version'}},
  ...[{session_id:'another-session'},{profile_id:'another-profile'},{skill_version:0}].map(patch=>({...message,business_recovery:{...message.business_recovery,continuation:{...message.business_recovery.continuation,...patch}}}))
 ];
 for(const candidate of invalid){assert.equal(f.lib.confirmedContinuation(candidate,'session-one','oil-pig'),null);f.resources.session.messages=[candidate];assert.equal(continuationButtons(f.render().chat.notice).length,0);}
});
test('an unresolved or active turn prevents every continuation action and a newer response supersedes an older interruption',()=>{
 for(const state of ['connecting','accepted','unknown','server-pending','running']){
  const f=fixture(),message=interruptedMessage();f.resources.session.messages=[message];f.resources.product={work_id:'exact-work',version_id:'interrupted-version',files:[]};
  if(state==='server-pending')f.resources.session.pendingTurnId='another-turn';
  else if(state==='running')f.runtime.sessionRuntime(f.vm.client,'session-one').state.setState({running:true});
  else f.draft={...f.draft,pending:{turnId:'another-turn',state}};
  const ui=f.render();assert.equal(continuationButtons(ui.chat.notice).length,0,state);
  const extra=ui.chat.renderMessageExtra(message),wrapper=extra.type(extra.props);assert.equal(continuationButtons(wrapper.type(wrapper.props)).length,0,state+' must block the message action too');
  assert.equal(f.calls.post.length,0);assert.equal(f.calls.stream.length,0);
 }
 const f=fixture();f.resources.session.messages=[interruptedMessage(),{role:'assistant',turnId:'newer-turn',status:'completed',content:'后来已完成'}];
 assert.equal(continuationButtons(f.render().chat.notice).length,0);
});
test('opening the confirmed continuation prepares the pinned skill without replaying the old request or replacing later input',async()=>{
 const message=interruptedMessage(),path=productionRecovery.nativeContinuationPath(message.business_recovery,'exact-work','interrupted-version');
 for(const text of ['', '  我后来补写的要求\n保留  ']){
  const files=text?[{id:'later-file',name:'后来添加.png'}]:[],f=fixture({search:path.split('?')[1],draft:{text,files}});
  f.resources.session.messages=[message];f.resources.work={id:'exact-work',title:'原始贴图',versions:[{id:'interrupted-version',recovery:message.business_recovery}]};
  f.resources.product={work_id:'exact-work',version_id:'interrupted-version',files:[]};
  const ui=f.render();for(const effect of [...f.effects])effect();await tick();
  assert.equal(continuationButtons(ui.chat.notice).length,0,'the continuation page already represents this action');
  const extra=ui.chat.renderMessageExtra(message),wrapper=extra.type(extra.props);assert.equal(continuationButtons(wrapper.type(wrapper.props)).length,0,'the continuation page must not offer its message action again');
  assert.equal(f.draft.command.skill_id,'content-production');assert.equal(f.draft.command.version,2);assert.equal(f.draft.command.action_id,'change');
  if(text)assert.equal(f.draft.text,text);else assert.match(f.draft.text,/请继续完成《原始贴图》/);
  assert.deepEqual(plain(f.draft.files),files);assert.equal(f.calls.stream.length,0);assert.equal(f.calls.post.length,0);assert.equal(f.calls.navigate.length,0);
 }
});

test('editing a draft and identical history polls preserve the native scroll dependency',()=>{
 const f=fixture();f.resources.session.messages=[{role:'user',content:'原问题'},{role:'assistant',content:'保留阅读位置'}];
 const original=f.render().chat.session.messages;
 f.draft={...f.draft,text:'继续输入，未发送'};
 assert.equal(f.render().chat.session.messages,original);
 f.resources.session={...f.resources.session,messages:plain(f.resources.session.messages)};
 assert.equal(f.render().chat.session.messages,original);
 f.resources.session={...f.resources.session,messages:[...f.resources.session.messages,{role:'assistant',content:'新的真实消息'}]};
 const updated=f.render().chat.session.messages;
 assert.notEqual(updated,original);assert.equal(updated.at(-1).content,'新的真实消息');
 f.resources.session={...f.resources.session,id:'another-session'};
 assert.notEqual(f.render().chat.session.messages,updated);
 assert.equal(f.calls.post.length,0);assert.equal(f.calls.stream.length,0);
});
test('native commands come from exact server releases and contextual actions route to their business page',()=>{
 const f=fixture(),choices=f.lib.nativeSkillChoices(catalog,false),production=choices.find(c=>c.selection.action_id==='poster');
 assert.equal(production.label,'生成贴图');assert.equal(production.selection.version,3);
 const learning=choices.find(c=>c.selection.action_id==='learning');assert.ok(learning);
 const path=f.lib.nativeSkillDestination({...learning.selection,trial:true},'p-二');
 assert.deepEqual(Object.fromEntries(new URL(path,'https://example.test').searchParams),{section:'skills',pane:'experience',profile:'p-二',skill:'experience-distillation',skill_version:'3',action:'learning',trial:'1'});
 assert.equal(f.lib.nativeSkillDestination(production.selection,'p'),null);
 assert.equal(f.lib.nativeSkillDestination(choices.find(c=>c.selection.action_id==='change').selection,'p',true),null);
});
test('a native first send retains input until actual acceptance and later recovery never clears retyped input',async()=>{
 const f=fixture(),initial=plain(f.draft);f.render().chat.onSend();await tick();
 assert.equal(f.calls.stream.length,1);assert.equal(f.calls.stream[0][2],'session-one');assert.equal(f.calls.stream[0][9],'exact-turn');assert.equal(f.calls.stream[0][10],false);
 assert.equal(f.draft.text,initial.text);assert.equal(f.draft.pending.state,'connecting');
 const options=f.calls.stream[0][16];assert.deepEqual(plain(options.headers),{'X-CSRF-Token':'fixture-csrf'});assert.equal(options.basePath,'');
 options.onAccepted();assert.equal(f.draft.text,'');assert.equal(f.draft.pending.accepted,true);
 f.draft={...f.draft,text:initial.text};options.onAccepted();assert.equal(f.draft.text,initial.text,'duplicate acknowledgement must preserve later input');
 f.calls.stream[0][4]();await tick();await tick();assert.equal(f.draft.pending,undefined);assert.equal(f.draft.text,initial.text);
 assert.equal(f.calls.get[0],'/api/chat/last/session-one?turn_id=exact-turn');
});
test('a done event with unknown receipt retains the frozen turn and only GET recovery is allowed',async()=>{
 const f=fixture({receipt:{turn_id:'exact-turn',execution_status:'unknown',delivery_state:'unknown'}});f.render().chat.onSend();await tick();
 const callbacks=f.calls.stream[0];callbacks[16].onAccepted();callbacks[4]();await tick();await tick();
 assert.equal(f.draft.pending.state,'unknown');assert.equal(f.draft.pending.turnId,'exact-turn');
 const ui=f.render();assert.ok(!nodes(ui.chat.notice).some(n=>n.type==='button'&&n.props.children==='核对原请求'));
 await f.runRecovery();assert.equal(f.calls.stream.length,1);assert.equal(f.calls.post.length,0);assert.ok(f.calls.get.every(path=>path==='/api/chat/last/session-one?turn_id=exact-turn'));
 f.vm.api.get=async path=>{f.calls.get.push(path);return {turn_id:'exact-turn',execution_status:'completed',delivery_state:'accepted'}};
 await f.runRecovery();assert.equal(f.draft.pending,undefined);assert.equal(f.calls.stream.length,1);assert.equal(f.calls.post.length,0);
});

test('silent SSE restoration clears only the transport warning without acknowledging or resubmitting the turn',async()=>{
 const f=fixture();f.render().chat.onSend();await tick();const callbacks=f.calls.stream[0];
 callbacks[16].onAccepted();f.draft={...f.draft,text:'恢复期间继续输入'};
 callbacks[8]();const runtime=f.runtime.sessionRuntime(f.vm.client,'session-one');
 assert.match(runtime.state.getState().feedback.message,/连接暂时中断/);
 const pending=plain(f.draft.pending);callbacks[16].onConnectionRestored();
 assert.equal(runtime.state.getState().feedback,undefined);assert.equal(runtime.state.getState().error,'');
 assert.equal(runtime.state.getState().running,true);assert.equal(runtime.state.getState().accepted,true);
 assert.deepEqual(plain(f.draft.pending),pending);assert.equal(f.draft.text,'恢复期间继续输入');
 assert.equal(f.calls.stream.length,1);assert.equal(f.calls.post.length,0);
 callbacks[8]();runtime.state.setState({error:'授权状态暂未核对',feedback:{kind:'status',message:'授权状态暂未核对'}});
 callbacks[16].onConnectionRestored();assert.equal(runtime.state.getState().error,'授权状态暂未核对');
});

test('a known timeout receipt is reported as execution uncertainty until the same interrupted turn is confirmed',async()=>{
 const f=fixture({receipt:{turn_id:'exact-turn',execution_status:'unknown',delivery_state:'unknown',error:'Codex 本轮超时，等待核对原回合。'}});
 f.render().chat.onSend();await tick();const callbacks=f.calls.stream[0];callbacks[16].onAccepted();
 f.draft={...f.draft,text:'新草稿不能被恢复清空'};callbacks[8]();callbacks[4]();await tick();await tick();
 const runtime=f.runtime.sessionRuntime(f.vm.client,'session-one');
 assert.match(runtime.state.getState().feedback.message,/原任务执行结果待核对/);
 assert.match(runtime.state.getState().feedback.message,/Codex 本轮超时/);
 assert.doesNotMatch(runtime.state.getState().feedback.message,/连接暂时中断/);
 callbacks[16].onConnectionRestored();assert.ok(f.draft.pending,'late transport recovery must not resolve an unknown receipt');
 await f.runRecovery();assert.match(runtime.state.getState().feedback.message,/原任务执行结果待核对/);
 f.vm.api.get=async path=>{f.calls.get.push(path);return {turn_id:'exact-turn',execution_status:'stopped',delivery_state:'interrupted',error:'原生接口已核对本回合中断；未重新发送，原文件保留，制作与交付未完成。'}};
 await f.runRecovery();assert.equal(f.draft.pending,undefined);assert.equal(f.draft.text,'新草稿不能被恢复清空');
 assert.equal(runtime.state.getState().feedback,undefined);assert.equal(runtime.state.getState().error,'');assert.equal(runtime.state.getState().running,false);
 assert.equal(f.calls.stream.length,1);assert.equal(f.calls.post.length,0);
});
test('one production send freezes the exact plan and immediately streams without a confirmation dialog',async()=>{
 const command={skill_id:'content-production',version:2,action_id:'poster',task:'poster',label:'生成贴图',requires_plan:true,trial:true},f=fixture({draft:{text:'原字贴图',files:[{id:'attached',name:'素材.txt'}],command}});
 f.render().chat.onSend();await tick();assert.equal(f.calls.stream.length,1);assert.equal(f.draft.text,'原字贴图','input stays until real acceptance');
 const plan=f.calls.post[0];assert.equal(plan.path,'/api/chat/plan');assert.equal(plan.body.context.version,2);assert.equal(plan.body.context.trial,true);assert.deepEqual(plain(plan.body.attachments),[{id:'attached',name:'素材.txt',path:'attached'}]);
 assert.equal(f.calls.stream[0][9],plan.body.turnId);assert.equal(f.calls.stream[0][16].context.plan_token,'exact-plan-token');assert.equal(f.render().plan,undefined,'a read-only plan must not open another confirmation modal');
});
test('rapid production sends share one in-flight plan and one native turn',async()=>{
 let releasePlan;const held=new Promise(resolve=>{releasePlan=resolve}),command={skill_id:'content-production',version:2,action_id:'poster',label:'生成贴图',requires_plan:true},f=fixture({draft:{text:'只发一次原字',files:[],command},postOverride:()=>held});
 const view=f.render();view.chat.onSend();view.chat.onSend();await tick();assert.equal(f.calls.post.length,1);assert.equal(f.calls.stream.length,0);assert.equal(f.draft.text,'只发一次原字');
 releasePlan({plan_token:'same-plan',plan:{}});await tick();assert.equal(f.calls.stream.length,1);assert.equal(f.calls.stream[0][16].context.plan_token,'same-plan');
});
test('a plan failure leaves the production input and attachments intact without streaming',async()=>{
 const initial={text:'保留失败原字',files:[{id:'original',name:'素材.txt'}],command:{skill_id:'content-production',version:2,action_id:'poster',label:'生成贴图',requires_plan:true}},f=fixture({draft:initial,postOverride:async()=>{throw Error('TEMP plan rejected')}});
 f.render().chat.onSend();await tick();assert.equal(f.calls.stream.length,0);assert.equal(f.draft.text,initial.text);assert.deepEqual(plain(f.draft.files),initial.files);assert.equal(f.draft.pending,undefined);
});
test('a definite unaccepted 403 409 or 422 lets the user correct and send again while unknown stays blocked',async()=>{
 for(const status of [403,409,422]){const f=fixture();f.render().chat.onSend();await tick();const error=Object.assign(Error('TEMP definite rejection'),{status});f.calls.stream[0][5](error);assert.equal(f.draft.pending.state,'rejected');f.render().chat.composer.onTextChange('修正后的原字 '+status);f.render().chat.onSend();await tick();assert.equal(f.calls.stream.length,2,'definite '+status+' must release the owner');assert.equal(f.calls.stream[1][0],'修正后的原字 '+status);assert.equal(f.calls.stream[1][10],false)}
 const f=fixture({receipt:{turn_id:'exact-turn',execution_status:'unknown',delivery_state:'unknown'}});f.render().chat.onSend();await tick();f.calls.stream[0][16].onAccepted();f.calls.stream[0][4]();await tick();await tick();f.render().chat.onSend();await tick();assert.equal(f.calls.stream.length,1);assert.equal(f.draft.pending.state,'unknown');
});
test('news provenance survives an accepted discussion until explicit production',async()=>{
 const f=fixture({draft:{text:'新闻原字',files:[],article_id:'exact-news',article_mode:'product'}});f.render().chat.onSend();await tick();
 assert.equal(f.calls.stream[0][16].context.article_id,'exact-news');assert.equal(f.calls.stream[0][16].context.article_mode,'product');assert.equal(f.draft.article_id,'exact-news');
 f.calls.stream[0][16].onAccepted();assert.equal(f.draft.article_id,'exact-news');assert.equal(f.draft.article_mode,'product');assert.equal(f.draft.pending.context.article_mode,'product');assert.equal(f.draft.pending.context.article_id,'exact-news');
});
test('explicit poster acceptance clears only the consumed news binding and keeps the frozen provenance',async()=>{
 const command={skill_id:'content-production',version:3,action_id:'poster',task:'poster',label:'生成贴图',requires_plan:true};
 const f=fixture({draft:{text:'新闻原字',files:[],article_id:'exact-news',command}});f.render().chat.onSend();await tick();
 assert.equal(f.calls.post[0].body.context.article_id,'exact-news');f.calls.stream[0][16].onAccepted();
 assert.equal(f.draft.article_id,undefined);assert.equal(f.draft.pending.context.article_id,'exact-news');
});

test('native change binds the selected parent, while a new format in the same session creates another work',async()=>{
 for(const action of ['change','article']){const command={skill_id:'content-production',version:2,action_id:action,task:action,label:action,requires_plan:true},f=fixture({draft:{text:'请求',files:[],command},search:'work=exact-work&version=exact-parent'});f.render().chat.onSend();await tick();const context=f.calls.post[0].body.context;assert.equal(context.work_id,action==='change'?'exact-work':undefined);assert.equal(context.parent_version_id,action==='change'?'exact-parent':undefined)}
 const discussion=fixture({search:'work=exact-work&version=exact-parent'});discussion.render().chat.onSend();await tick();assert.equal(discussion.calls.stream[0][16].context.action_id,'discuss');assert.equal(discussion.calls.stream[0][16].context.parent_version_id,'exact-parent');
});
test('business-only skill selection preserves chat input and navigates without creating a model turn',()=>{
 const f=fixture(),ui=f.render();ui.chat.composer.onCommandSelect('experience-distillation:learning','  原字经验  ');
 assert.equal(f.draft.text,'  原字经验  ');assert.equal(f.draft.command,null);assert.equal(f.calls.stream.length,0);assert.match(f.calls.navigate[0],/skill_version=3/);
});
test('historical turn products use registered file IDs and open the exact business version',()=>{
 const f=fixture(),message={turnId:'turn',output_files:[{id:'registered',name:'成品.png',mime:'image/png',url:'/api/files/registered'}],business_receipt:{work_id:'exact-work',version_id:'exact-version'}};
 f.resources.product={work_id:'exact-work',version_id:'exact-version',files:message.output_files,text_blocks:[],can_adopt:false};
 const wrapper=f.lib.NativeTurnOutputs({message}),tree=wrapper.type(wrapper.props);
 assert.equal(f.lib.nativeArtifacts(message)[0].url,'/api/files/registered');assert.equal(nodes(tree).find(n=>n.type===f.components.ProductionParameters),undefined);nodes(tree).find(n=>n.type==='button').props.onClick();assert.equal(f.calls.navigate[0],'/works/exact-work?version=exact-version');
});
test('production parameters load only when opened and show the exact version profile skills and frozen bytes',()=>{
 let opened=false;const paths=[],parameters={execution_prompt:{body:'  本轮冻结原字\n保留全部内容  ',sha256:'a'.repeat(64),creator_snapshot:{profile:{id:'history-profile',name:'历史作者',revision:9},skills:[{id:'content-production',name:'内容生产',version:2}],trial:true}}};
 const TextRecord=()=>{},lib=module('workbench/ui/ProductionParameters.tsx',{react:{useState:()=>[opened,next=>{opened=next}]},'@workbench/core':{useResource:path=>{paths.push(path);return {data:path?parameters:null,error:'',reload:async()=>parameters}},array,record,string},'./common':{Notice:()=>{},TextRecord}});
 const initial=lib.ProductionParameters({versionId:'exact-version'});assert.equal(paths[0],null);assert.equal(nodes(initial).find(n=>n.type==='summary').props.children,'制作参数');initial.props.onToggle({currentTarget:{open:true}});
 const shown=lib.ProductionParameters({versionId:'exact-version'}),text=nodes(shown).flatMap(n=>array(n.props?.children).filter(v=>typeof v==='string')).join(' '),records=nodes(shown).filter(n=>n.type===TextRecord);
 assert.equal(paths.at(-1),'/api/creative/prompts/exact-version');assert.match(text,/历史作者/);assert.match(text,/v9/);assert.match(text,/内容生产 · v2/);assert.match(text,/本次试用/);assert.ok(records.some(n=>n.props.value===parameters.execution_prompt.body));assert.ok(records.some(n=>n.props.value===parameters.execution_prompt.sha256));
});

function transport(fetchImpl){const source=readFileSync(new URL('lib/api.ts',sourceRoot),'utf8'),ast=ts.createSourceFile('api.ts',source,ts.ScriptTarget.Latest,true),fn=ast.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='streamChat'),exports={};runInNewContext(ts.transpileModule(fn.getText(ast),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,{exports,BASE:'/native',window:{location:{pathname:'/native/chat/session'}},AbortController,TextDecoder,fetch:fetchImpl,setTimeout:(fn,ms)=>setTimeout(fn,Math.min(ms||0,2)),clearTimeout});return exports.streamChat}
test('the actual upstream stream transport sends root private APIs with CSRF and one accepted notification',async()=>{
 const calls=[],accepted=[],tokens=[],done=[];
 const send=transport(async(url,options)=>{calls.push({url,options});let read=false;return {ok:true,status:200,body:{getReader:()=>({read:async()=>read?{done:true}:(read=true,{done:false,value:new TextEncoder().encode('id: 1\nevent: accepted\ndata: {"turnId":"t"}\n\nid: 2\nevent: token\ndata: "真实分片"\n\nid: 3\nevent: done\ndata: {"sessionKey":"native"}\n\n')})})}}});
 send('原字','p','s',value=>tokens.push(value),value=>done.push(value),assert.fail,undefined,undefined,undefined,'t',false,undefined,[],undefined,undefined,undefined,{basePath:'',context:{skill_id:'content-production',version:2},headers:{'X-CSRF-Token':'csrf'},onAccepted:value=>accepted.push(value)});
 await tick();assert.equal(calls.length,1);assert.equal(calls[0].url,'/api/chat/stream');assert.equal(calls[0].options.headers['X-CSRF-Token'],'csrf');assert.equal(JSON.parse(calls[0].options.body).context.version,2);assert.equal(accepted.length,1);assert.deepEqual(tokens,['真实分片']);assert.deepEqual(done,['native']);
});
test('resumed HTTP 401 ends the existing stream without a second POST',async()=>{
 const calls=[],errors=[],send=transport(async(url,options)=>{calls.push({url,options});return {ok:false,status:401,json:async()=>({error:'登录已过期'})}});
 send('原字','p','s',()=>{},()=>{},err=>errors.push(err),undefined,undefined,undefined,'existing-turn',true,undefined,[],undefined,undefined,undefined,{basePath:'',headers:{'X-CSRF-Token':'csrf'}});
 await tick();await tick();assert.equal(calls.length,1);assert.match(calls[0].url,/\/api\/chat\/jobs\/existing-turn\/stream/);assert.notEqual(calls[0].options?.method,'POST');assert.equal(errors[0].status,401);
});

function legacyEntry({saved={},pending=null,search='draft=old-input',format='poster',news=null,profilePins={}}={}){
 const source=readFileSync(new URL('workbench/ui/index.tsx',sourceRoot),'utf8'),ast=ts.createSourceFile('index.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX),declaration=ast.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='NativeNewChat'),exports={},calls={create:[],errors:[]};
 const f=fixture(),core={useWorkbench:()=>({client:{drafts:{get:()=>saved},operation:()=>({getState:()=>({pending})}),legacyPending:()=>[]},navigate:()=>{}}),useResource:path=>({data:path==='/api/skills'?catalog:path==='/api/creator/bootstrap'?{profiles:[{id:'p',task_skill_versions:profilePins}]}:news,error:''}),useAsyncAction:()=>({busy:false,error:'',run:async fn=>{try{return await fn()}catch(error){calls.errors.push(error.message)}}}),useRef:value=>({current:value}),useEffect:()=>{}};
 runInNewContext(ts.transpileModule('export '+declaration.getText(ast),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,{exports,URLSearchParams,record,string,array,nativeSkillChoices:f.lib.nativeSkillChoices,...core,Notice:()=>{},ActionButton:'button',refreshViews:(...reads)=>reads.forEach(read=>void read()),require:id=>id==='react/jsx-runtime'?jsx:assert.fail(id)});
 const tree=exports.NativeNewChat({format,profileId:'p',search:new URLSearchParams(search),onCreate:async(...args)=>{calls.create.push(args);return 'created-session'}});
 return {calls,open:()=>nodes(tree).find(n=>n.type==='button').props.onClick()};
}
test('legacy new links copy exact input files, source ID and explicit trial version without deleting the old draft',async()=>{
 const saved={title:' 原始题目 ',material:' 第一行\n第二行 ',guidance:' 原始要求 ',files:[{id:'old-attachment',name:'素材.txt'}]},f=legacyEntry({saved,search:'draft=old-input&article=news-exact&skill=content-production&skill_version=2&trial=1',news:{title:'新闻标题',body:'来源正文'}});
 f.open();await tick();assert.equal(f.calls.errors.length,0);const [profile,command,text,files,article]=f.calls.create[0];assert.equal(profile,'p');assert.equal(command.version,2);assert.equal(command.trial,true);assert.equal(text,' 原始题目 \n\n 第一行\n第二行 \n\n 原始要求 ');assert.deepEqual(plain(files),saved.files);assert.equal(article,'news-exact');assert.equal(saved.material,' 第一行\n第二行 ');
});
test('a legacy unknown create receipt blocks new native forwarding',async()=>{
 const f=legacyEntry({saved:{material:'保留原字'},pending:{id:'original-unknown'}});f.open();await tick();assert.equal(f.calls.create.length,0);assert.match(f.calls.errors[0],/状态正在恢复/);
});

test('automatic legacy entry inherits the profile pin instead of the current global release',async()=>{const f=legacyEntry({saved:{material:'原字'},profilePins:{poster:{'content-production':2}}});f.open();await tick();assert.equal(f.calls.create[0][1].version,2);const explicit=legacyEntry({search:'skill=content-production&skill_version=3',profilePins:{poster:{'content-production':2}}});explicit.open();await tick();assert.equal(explicit.calls.create[0][1].version,3)});

test('legacy migration preserves explicit editable recipe and product article intent without inferred controls',async()=>{const f=legacyEntry({format:'article',saved:{material:'原字',article_mode:'product',creative:{recipe:{prompt_text:'  明确可编辑要求\n保留原字  '},intent:{tone:'inferred-control'},values:{text:50}}}});f.open();await tick();const text=f.calls.create[0][2];assert.equal(f.calls.create[0][5],'product');assert.match(text,/明确可编辑要求\n保留原字  /);assert.match(text,/文章类型为产品文章/);assert.ok(!text.includes('inferred-control'));assert.ok(!text.includes('50'))});


test('switching views retains the application stream, latest live step, and closed question set',async()=>{
 const f=fixture({postOverride:(_path,body)=>({questions:Object.fromEntries((body.questionIds||[]).map(id=>[id,{status:'pending'}]))})});
 f.render().chat.onSend();await tick();const callbacks=f.calls.stream[0],owner=f.runtime.sessionRuntime(f.vm.client,'session-one');
 callbacks[16].onAccepted();callbacks[7]('第一步');callbacks[7]('第二步');
 assert.equal(owner.state.getState().stream.activity,'第二步');
 const other=f.runtime.sessionRuntime(f.vm.client,'another-session');assert.notEqual(other,owner);
 assert.equal(f.runtime.sessionRuntime(f.vm.client,'session-one'),owner);assert.equal(f.calls.stream.length,1);
 const q={id:'permission-one',questions:[{questionId:'permission'}]};callbacks[13](q);await tick();
 assert.equal(owner.state.getState().stream.questions.length,1);owner.closeQuestion(q.id);
 callbacks[13](q);await tick();assert.equal(owner.state.getState().stream.questions.length,0);
 f.vm.client.authenticationEpoch++;f.vm.client.session.setState({config:null});
 assert.equal(owner.state.getState().stream,undefined);assert.ok(f.draft.pending,'auth change preserves input operation identity');
});

test('lost permission acknowledgement queries status and never posts another grant',async()=>{
 const f=fixture({postOverride:(path,body)=>{if(path.endsWith('/answer'))throw Error('lost HTTP acknowledgement');return {questions:{q:{status:'answered'}}}}});
 const owner=f.runtime.sessionRuntime(f.vm.client,'session-one');
 assert.equal((await owner.answer({questionId:'q',answers:{permission:['允许本次']}})).ok,true);
 assert.equal(f.calls.post.filter(x=>x.path.endsWith('/answer')).length,1);
 assert.equal(f.calls.post.at(-1).path,'/api/chat/question/status');
});

test('terminal question replay is checked before it becomes an actionable card',async()=>{
 const f=fixture({postOverride:()=>({questions:{old:{status:'answered'}}})});f.render().chat.onSend();await tick();
 const callbacks=f.calls.stream[0];callbacks[13]({id:'old',questions:[{questionId:'permission'}]});await tick();
 const owner=f.runtime.sessionRuntime(f.vm.client,'session-one');assert.equal(owner.state.getState().stream.questions.length,0);assert.ok(owner.closed.has('old'));
});

test('verified stream recovery clears transient connection notices',async()=>{
 const f=fixture();f.render().chat.onSend();await tick();const callbacks=f.calls.stream[0],owner=f.runtime.sessionRuntime(f.vm.client,'session-one');
 callbacks[8]();assert.match(owner.state.getState().error,/连接中断/);callbacks[3]('继续回复');assert.equal(owner.state.getState().error,'');
 callbacks[8]();callbacks[4]();await tick();await tick();assert.equal(owner.state.getState().error,'');
});


test('explicit ordinary retry pins the original skill version and preserves a later draft',async()=>{
 const f=fixture({receipt:{turn_id:'old-turn',execution_status:'completed',delivery_state:'accepted',context:{profile_id:'oil-pig'},skill_refs:[{id:'topic-research',version:2}]}});
 f.resources.session.messages=[{role:'user',content:'原问题',attachments:[{id:'source',name:'素材.txt',path:'source'}]},{role:'assistant',content:'原回答',turnId:'old-turn'}];
 f.render().chat.onResend(0);await tick();assert.equal(f.calls.stream.length,1);
 const args=f.calls.stream[0];assert.equal(args[0],'原问题');assert.equal(args[16].context.version,2);assert.equal(args[16].context.skill_id,'topic-research');
 args[16].onAccepted();assert.equal(f.draft.text,'  原字材料\n保留  ');
});


test('the upstream brush retains both official groups and places private skills in extensions',()=>{
 const f=fixture(),menu=module('lib/capabilityMenu.ts',{}).CAPABILITY_MENU;
 const originals=menu.tabs.flatMap(tab=>tab.groups.flatMap(group=>group.items.filter(item=>item.skill).map(item=>({id:item.skill,name:item.skill,layer:tab.id==='make'?'produce':'general',origin:'easel',version:1,source_revision:'a'.repeat(64),launch_actions:[{id:'native',label:'使用技能',task:'native',requires_plan:false}]}))));
 const choices=f.lib.nativeSkillChoices([...originals,...catalog]);
 assert.equal(choices.filter(item=>item.tab==='make').length,61);assert.equal(choices.filter(item=>item.tab==='operate').length,52);assert.ok(choices.some(item=>item.tab==='extensions'&&item.label==='生成贴图'));
 const card=choices.find(item=>item.selection.skill_id==='card-quote');assert.equal(card.label,'金句卡 / 数据卡');assert.equal(card.prompt,'帮我做「金句卡 / 数据卡」');assert.equal(card.selection.source_revision,'a'.repeat(64));assert.equal(f.lib.nativeSkillDestination(card.selection,'oil-pig'),null);
});
