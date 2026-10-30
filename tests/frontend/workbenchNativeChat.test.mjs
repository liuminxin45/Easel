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
const skill=(id,actions)=>({id,name:id,version:3,available:true,execution_kind:id==='content-production'?'workflow':'agent',launch_actions:actions});
const catalog=[skill('content-production',[{id:'poster',label:'贴图',task:'poster',requires_plan:true},{id:'article',label:'文章',task:'article',requires_plan:true},{id:'change',label:'修改',task:'change',requires_context:true,path:'/works',requires_plan:true}]),skill('topic-research',[{id:'discuss',label:'讨论',task:'discuss'}]),skill('experience-distillation',[{id:'learning',label:'整理经验',task:'learning',requires_context:true,path:'/toolbox?section=skills&pane=experience'}])];
function fixture({draft:initial={text:'  原字材料\n保留  ',files:[]},pendingTurnId,receipt={turn_id:'exact-turn',execution_status:'completed',delivery_state:'known'},search='',postOverride}={}){
 let cursor=0,draft=initial;const hooks=[],effects=[],calls={stream:[],post:[],get:[],navigate:[],invalidate:[]},resources={session:{id:'session-one',profile_id:'oil-pig',messages:[],created:1,title:'原生会话',pendingTurnId},linked_works:[]};
 const react={useState:value=>{const index=cursor++;if(!(index in hooks))hooks[index]=value;return [hooks[index],next=>{hooks[index]=typeof next==='function'?next(hooks[index]):next}]},useRef:value=>{const index=cursor++;if(!(index in hooks))hooks[index]={current:value};return hooks[index]},useEffect:fn=>{cursor++;effects.push(fn)}};
 const vm={config:{csrf:'fixture-csrf'},navigation:{registerLayer:()=>()=>{}},navigate:path=>calls.navigate.push(path),client:{drafts:{get:()=>draft},invalidate:async tags=>calls.invalidate.push(tags)},service:{uploadFiles:async files=>files,attach:async files=>files},api:{get:async path=>{calls.get.push(path);return receipt},post:async(path,body,csrf)=>{calls.post.push({path,body,csrf});if(postOverride)return postOverride(path,body,csrf);return path==='/api/chat/plan'?{plan_token:'exact-plan-token',plan:{production_input:{title:'目标'},execution_prompt:{body:'真实冻结指令'}}}:{stopped:true}}}};
 const hookSource=readFileSync(new URL('workbench/core/react.tsx',sourceRoot),'utf8'),hookAst=ts.createSourceFile('react.tsx',hookSource,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX),hook=hookAst.statements.find(n=>ts.isFunctionDeclaration(n)&&n.name?.text==='useAsyncAction'),hookExports={};
 runInNewContext(ts.transpileModule(hook.getText(hookAst),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports:hookExports,useState:react.useState,useRef:react.useRef,useCallback:fn=>fn,Error});
 const core={useWorkbench:()=>vm,useResource:path=>({data:path==='/api/skills'?catalog:resources,error:'',reload:async()=>resources}),useDraft:()=>[draft,patch=>{draft=typeof patch==='function'?patch(draft):{...draft,...patch}}],useAsyncAction:hookExports.useAsyncAction,draftFingerprint:JSON.stringify,array,record,string,workPath:(work,version)=>'/works/'+work.id+(version?'?version='+version:'')};
 const components={ChatPage:()=>{},ProductionPlan:()=>{},ArtifactView:()=>{},ProductionParameters:()=>{}};
 const lib=module('workbench/ui/ChatSessionView.tsx',{react,'@workbench/core':core,'../../components/ChatPage':components.ChatPage,'../../lib/api':{streamChat:(...args)=>{calls.stream.push(args);return {abort:()=>{}}}},'./common':{Notice:()=>{},ArtifactView:components.ArtifactView},'./components/icons':{},'./production':{ProductionPlan:components.ProductionPlan},'./ProductionParameters':{ProductionParameters:components.ProductionParameters}});
 const render=()=>{cursor=0;effects.length=0;const tree=lib.ChatSessionView({id:'session-one',search:new URLSearchParams(search)});return {tree,chat:nodes(tree).find(n=>n.type===components.ChatPage).props,plan:nodes(tree).find(n=>n.type===components.ProductionPlan)?.props}};
 return {calls,resources,lib,vm,components,render,effects,get draft(){return draft},set draft(next){draft=next}};
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));
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
 const ui=f.render(),retry=nodes(ui.chat.notice).find(n=>n.type==='button'&&n.props.children==='核对原请求');assert.ok(retry);retry.props.onClick();
 assert.equal(f.calls.stream.length,2);assert.equal(f.calls.stream[1][10],true);assert.equal(f.calls.stream[1][9],'exact-turn');
 assert.equal(f.calls.post.length,0);
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
test('news provenance belongs to the frozen turn and clears with the accepted input',async()=>{
 const f=fixture({draft:{text:'新闻原字',files:[],article_id:'exact-news',article_mode:'product'}});f.render().chat.onSend();await tick();
 assert.equal(f.calls.stream[0][16].context.article_id,'exact-news');assert.equal(f.calls.stream[0][16].context.article_mode,'product');assert.equal(f.draft.article_id,'exact-news');
 f.calls.stream[0][16].onAccepted();assert.equal(f.draft.article_id,undefined);assert.equal(f.draft.article_mode,undefined);assert.equal(f.draft.pending.context.article_mode,'product');assert.equal(f.draft.pending.context.article_id,'exact-news');
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
 const f=fixture(),tree=f.lib.NativeTurnOutputs({message:{turnId:'turn',output_files:[{id:'registered',name:'成品.png',mime:'image/png',url:'/api/files/registered'}],business_receipt:{work_id:'exact-work',version_id:'exact-version'}}}),output=nodes(tree).find(n=>n.props?.file);
 assert.equal(output.props.file.id,'registered');assert.equal(nodes(tree).find(n=>n.type===f.components.ProductionParameters)?.props.versionId,'exact-version');nodes(tree).find(n=>n.type==='button').props.onClick();assert.equal(f.calls.navigate[0],'/works/exact-work?version=exact-version');
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
 runInNewContext(ts.transpileModule('export '+declaration.getText(ast),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX}}).outputText,{exports,URLSearchParams,record,string,array,nativeSkillChoices:f.lib.nativeSkillChoices,...core,Notice:()=>{},require:id=>id==='react/jsx-runtime'?jsx:assert.fail(id)});
 const tree=exports.NativeNewChat({format,profileId:'p',search:new URLSearchParams(search),onCreate:async(...args)=>{calls.create.push(args);return 'created-session'}});
 return {calls,open:()=>nodes(tree).find(n=>n.type==='button').props.onClick()};
}
test('legacy new links copy exact input files, source ID and explicit trial version without deleting the old draft',async()=>{
 const saved={title:' 原始题目 ',material:' 第一行\n第二行 ',guidance:' 原始要求 ',files:[{id:'old-attachment',name:'素材.txt'}]},f=legacyEntry({saved,search:'draft=old-input&article=news-exact&skill=content-production&skill_version=2&trial=1',news:{title:'新闻标题',body:'来源正文'}});
 f.open();await tick();assert.equal(f.calls.errors.length,0);const [profile,command,text,files,article]=f.calls.create[0];assert.equal(profile,'p');assert.equal(command.version,2);assert.equal(command.trial,true);assert.equal(text,' 原始题目 \n\n 第一行\n第二行 \n\n 原始要求 ');assert.deepEqual(plain(files),saved.files);assert.equal(article,'news-exact');assert.equal(saved.material,' 第一行\n第二行 ');
});
test('a legacy unknown create receipt blocks new native forwarding',async()=>{
 const f=legacyEntry({saved:{material:'保留原字'},pending:{id:'original-unknown'}});f.open();await tick();assert.equal(f.calls.create.length,0);assert.match(f.calls.errors[0],/待核对/);
});

test('automatic legacy entry inherits the profile pin instead of the current global release',async()=>{const f=legacyEntry({saved:{material:'原字'},profilePins:{poster:{'content-production':2}}});f.open();await tick();assert.equal(f.calls.create[0][1].version,2);const explicit=legacyEntry({search:'skill=content-production&skill_version=3',profilePins:{poster:{'content-production':2}}});explicit.open();await tick();assert.equal(explicit.calls.create[0][1].version,3)});

test('legacy migration preserves explicit editable recipe and product article intent without inferred controls',async()=>{const f=legacyEntry({format:'article',saved:{material:'原字',article_mode:'product',creative:{recipe:{prompt_text:'  明确可编辑要求\n保留原字  '},intent:{tone:'inferred-control'},values:{text:50}}}});f.open();await tick();const text=f.calls.create[0][2];assert.equal(f.calls.create[0][5],'product');assert.match(text,/明确可编辑要求\n保留原字  /);assert.match(text,/文章类型为产品文章/);assert.ok(!text.includes('inferred-control'));assert.ok(!text.includes('50'))});
