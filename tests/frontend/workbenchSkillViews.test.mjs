import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';

const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const element=(type,props)=>({type,props}),jsx={jsx:element,jsxs:element,Fragment:'fragment'};
const record=value=>value&&typeof value==='object'?value:{},array=value=>Array.isArray(value)?value:[],plain=value=>JSON.parse(JSON.stringify(value));
const common=Object.fromEntries(['ActionButton','Drawer','Notice','Field','Panel','PageHead','Markdown','Pending','TextRecord','JsonDetails'].map(name=>[name,name]));
common.resultDocument=value=>record(record(value).result??value);
function nodes(value){if(Array.isArray(value))return value.flatMap(nodes);if(!value||typeof value!=='object')return [];return [value,...nodes(value.props?.children)];}
function text(value){if(Array.isArray(value))return value.map(text).join('');if(value&&typeof value==='object')return text(value.props?.children);return value==null?'':String(value);}
function load(name,imports,suffix=''){
 imports={...imports,'./hooks':imports['@workbench/core']};
 const source=readFileSync(new URL('../../web/frontend/src/workbench/ui/'+name,import.meta.url),'utf8')+suffix,exports={};
 const {outputText}=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}});
 runInNewContext(outputText,{exports,URLSearchParams,require:id=>id==='react/jsx-runtime'?jsx:id==='./common'?common:id==='./ExtensionDetails'?{ExtensionDetails:'ExtensionDetails'}:id==='./components/icons'?{}:id==='./nativeProfiles'?{NativeProfiles:()=>{}}:id==='./PlatformAccounts'?{Accounts:()=>{}}:id in imports?imports[id]:assert.fail('Unexpected import '+id)});
 return exports;
}
function hooks(){
 const slots=[],deps=[],effects=[];let cursor=0;
 const react={
  useState:initial=>{const at=cursor++;if(!(at in slots))slots[at]=initial;return [slots[at],next=>{slots[at]=typeof next==='function'?next(slots[at]):next}]},
  useRef:initial=>{const at=cursor++;if(!(at in slots))slots[at]={current:initial};return slots[at]},
  useEffect:(effect,next)=>{const at=cursor++,old=deps[at];if(!old||!next||old.length!==next.length||next.some((value,i)=>value!==old[i])){deps[at]=next;effects.push(effect)}}
 };
 return {react,render:fn=>{cursor=0;const tree=fn();effects.splice(0).forEach(effect=>effect());return tree}};
}
function fixture({onClose}={}){
 const state=hooks(),draft={prompt:'  原技能\n保留原字  ',reason:'改进表达',conditions:'移动端'},calls={writes:[],replace:[]};
 const detail={id:'creator-method',name:'贴图制作',version:2,published_version:1,status:'candidate',tasks:['poster','article'],resources:[],prompt:draft.prompt,diff:{before:'原方法',after:'新方法'},launch_actions:[]};
 const data={profiles:[{id:'profile-a',name:'作者甲',revision:7}],skills:[{id:detail.id,versions:[{version:1,status:'published'},{version:2,status:'candidate'}]}],task_policy:{poster:{},article:{}}};
 const vm={replace:path=>calls.replace.push(path),service:{creatorCommand:async(...args)=>{calls.writes.push(args);return {}}}};
 const core={record,array,string:value=>typeof value==='string'?value:'',number:value=>Number(value)||0,useWorkbench:()=>vm,useResource:()=>({data:detail}),useDraft:()=>[draft,patch=>Object.assign(draft,patch)],useAsyncAction:()=>({busy:false,run:fn=>fn()})};
 const {SkillDetail}=load('management.tsx',{react:state.react,'@workbench/core':core},'\nexport {SkillDetail};');
 const render=()=>state.render(()=>SkillDetail({id:detail.id,version:'2',data,profileId:'profile-a',onClose}));
 const button=(tree,label)=>nodes(tree).find(node=>['button','ActionButton'].includes(node.type)&&text(node.props.children)===label);
 return {render,button,calls,draft,detail};
}

test('skill publishing stays in one official drawer and shows its exact diff inline without writing',()=>{
 const f=fixture(),initial=f.render();
 f.button(initial,'确认适用范围并发布').props.onClick();const confirm=f.render();
 assert.equal(confirm.type,'Drawer');assert.equal(confirm.props.title,'发布技能版本');
 assert.equal(nodes(confirm).filter(node=>node.type==='Drawer').length,1);
 assert.equal(nodes(confirm).filter(node=>node.type==='TextRecord'||node.type==='JsonDetails').length,0);
 const diff=nodes(confirm).find(node=>node.type==='ExtensionDetails'&&node.props.title==='发布前差异');
 assert.equal(text(diff.props.children),JSON.stringify(f.detail.diff,null,2));
 assert.equal(f.calls.writes.length,0);
});

test('closing or backing from confirmation restores detail, preserves edits and keeps the detail history layer',()=>{
 const f=fixture();let tree=f.render();f.button(tree,'编辑方法，另存候选').props.onClick();tree=f.render();
 nodes(tree).find(node=>node.type==='textarea').props.onChange({target:{value:'  我修改的方法\n不丢失  '}});
 f.button(tree,'确认适用范围并发布').props.onClick();tree=f.render();tree.props.onClose();tree=f.render();
 assert.equal(tree.props.title,'贴图制作');assert.equal(nodes(tree).find(node=>node.type==='textarea').props.value,'  我修改的方法\n不丢失  ');
 assert.equal(f.calls.replace.length,0);assert.equal(f.calls.writes.length,0);
 f.button(tree,'确认适用范围并发布').props.onClick();tree=f.render();assert.equal(tree.props.onDismiss(),false);tree=f.render();
 assert.equal(tree.props.title,'贴图制作');assert.equal(tree.props.open,true);assert.equal(f.calls.replace.length,0);
 tree.props.onClose();assert.deepEqual(f.calls.replace,['/toolbox?section=skills']);
});

test('publication remains explicit and binds candidate, previous publication, profile revision and chosen tasks',async()=>{
 const f=fixture();f.button(f.render(),'确认适用范围并发布').props.onClick();let tree=f.render();
 nodes(tree).find(node=>node.type==='input').props.onChange({target:{checked:true}});tree=f.render();
 assert.equal(f.button(tree,'确认发布此版本').props.disabled,true);
 const poster=nodes(tree).find(node=>node.type==='label'&&text(node.props.children)==='贴图');nodes(poster).find(node=>node.type==='input').props.onChange({target:{checked:true}});tree=f.render();
 assert.equal(f.button(tree,'确认发布此版本').props.disabled,false);assert.equal(f.calls.writes.length,0);
 tree.props.onClose();f.button(f.render(),'确认适用范围并发布').props.onClick();tree=f.render();
 assert.equal(nodes(tree).find(node=>node.type==='input').props.checked,true);
 assert.equal(nodes(tree).filter(node=>node.type==='input')[1].props.checked,true);
 f.button(tree,'确认发布此版本').props.onClick();await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(plain(f.calls.writes),[['skill-publish',{skill_id:'creator-method',version:2,expected_published_version:1,confirm:true,profile_id:'profile-a',profile_revision:7,tasks:['poster']}]]);
 assert.equal(f.render().props.title,'贴图制作');
});

function nativeFixture({privateSkill=false,plan=false,pathOnly=false}={}){
 const state=hooks(),calls={executions:[],previews:[],navigation:[],answers:[],closed:[],resumes:0},selection={skill_id:'method',version:7,action_id:plan?'poster':'native',label:'制作贴图',requires_plan:plan};
 let execution={sessionId:'',turnId:'',questions:[]};
 if(pathOnly)selection.path='/toolbox?section=skills&pane=experience';
 const skill={id:'method',name:'method',origin:privateSkill?'workbench':'easel',version:7,available:true,reason:''};
 const services={
  execution:{getState:()=>execution},
  resume:()=>{calls.resumes++},
  questionServices:{answer:async payload=>{calls.answers.push(payload);return {ok:true}},status:async()=>({})},
  closeQuestion:id=>{calls.closed.push(id);execution={...execution,questions:execution.questions.filter(question=>question.id!==id)}},
  loadDetail:async()=>({...skill,body:'原技能正文',needsApi:false,apiConfigured:true}),
  saveEnv:async()=>({ok:true,skills:{}}),
  execute:async(...args)=>{calls.executions.push(args);return {response:'原生实际回复'}},
  prepareSelection:async(chosen,input)=>{const prepared={selection:chosen,input,token:'preview-'+calls.previews.length,sessionId:'session',turnId:'turn',plan:{production_input:{title:'冻结目标',material:input},creator_snapshot:{profile:{name:'作者甲'},skills:[{name:'贴图方法',version:7}]},execution_prompt:{body:'准确冻结指令'}}};calls.previews.push(prepared);return prepared},
  executeSelection:async(...args)=>{calls.executions.push(args);return {response:'准确制作结果'}}
 };
 const react={...state.react,useMemo:fn=>fn(),useEffect:()=>{}};
 const core={record,array,string:value=>typeof value==='string'?value:'',useWorkbench:()=>({client:{},navigation:{},navigate:path=>calls.navigation.push(path)}),useResource:path=>({data:path==='/api/creator/bootstrap'?{profiles:[],skills:[skill]}:[skill]})};
 const pages=load('NativeSkills.tsx',{react,zustand:{useStore:store=>store.getState()},'@workbench/core':core,'../../components/SkillPage':'SkillPage','../../components/SkillDrawer':'SkillDrawer','../../components/SettingsSelect':'SettingsSelect','../../components/QuestionCards':'QuestionCards','./management':{SkillDetail:'SkillDetail'},'./skillServices':{createSkillServices:()=>services},'./ChatSessionView':{nativeSkillChoices:()=>[{id:'choice',label:'制作贴图',selection}]}});
 const page=pages.NativeSkills({profileId:'profile-a'}),wrapped=page.props.renderDrawer(skill.name,()=>{});
 const render=()=>state.render(()=>wrapped.type(wrapped.props));
 return {page,render,calls,selection,services,setExecution:value=>{execution=value}};
}

test('official skills keep the native drawer API configuration and run services without replacement controls',async()=>{
 const f=nativeFixture(),tree=f.render(),drawer=nodes(tree).find(node=>node.type==='SkillDrawer');
 assert.equal(f.page.props.subtitle,undefined);
 assert.equal(drawer.props.canConfigure,undefined);assert.equal(drawer.props.onUse,undefined);assert.equal(drawer.props.useActions,undefined);assert.equal(drawer.props.extension,undefined);
 assert.equal(f.calls.executions.length,0);
 assert.deepEqual(plain(await drawer.props.services.execute('method','原文输入','profile-a')),{response:'原生实际回复'});
 assert.deepEqual(plain(f.calls.executions),[['method','原文输入']]);
 assert.equal(f.calls.navigation.length,0);
});

test('private production previews its precise plan and cancel never sends or redirects',async()=>{
 const f=nativeFixture({privateSkill:true,plan:true}),drawer=nodes(f.render()).find(node=>node.type==='SkillDrawer');
 const run=drawer.props.services.execute('method','  本轮原始输入\n保留字节  ','profile-a');
 await new Promise(resolve=>setImmediate(resolve));
 const confirmation=nodes(f.render()).find(node=>node.type==='Drawer'&&node.props.open);
 assert.equal(confirmation.props.title,'确认本次制作');assert.match(text(confirmation),/冻结目标/);assert.match(text(confirmation),/本轮原始输入/);assert.match(text(confirmation),/v7/);
 assert.equal(f.calls.executions.length,0);assert.equal(f.calls.previews.length,1);
 confirmation.props.onClose();await assert.rejects(run,/取消/);
 assert.equal(f.calls.executions.length,0);assert.equal(f.calls.navigation.length,0);
});

test('editing input invalidates a pending production plan and confirmation binds the replacement exact input',async()=>{
 const f=nativeFixture({privateSkill:true,plan:true});let drawer=nodes(f.render()).find(node=>node.type==='SkillDrawer');
 const old=drawer.props.services.execute('method','旧输入','profile-a');await new Promise(resolve=>setImmediate(resolve));
 drawer=nodes(f.render()).find(node=>node.type==='SkillDrawer');drawer.props.onInputChange('新输入');await assert.rejects(old,/取消/);
 const run=drawer.props.services.execute('method','新输入','profile-a');await new Promise(resolve=>setImmediate(resolve));
 const confirmation=nodes(f.render()).find(node=>node.type==='Drawer'&&node.props.open);
 const confirm=nodes(confirmation).find(node=>node.type==='button'&&text(node)==='确认本次制作');confirm.props.onClick();
 assert.deepEqual(plain(await run),{response:'准确制作结果'});
 const [selection,input,options]=f.calls.executions[0];assert.deepEqual(plain(selection),f.selection);assert.equal(input,'新输入');assert.equal(options.prepared.token,'preview-1');
 assert.equal(f.calls.navigation.length,0);
});

test('path-only project skills reuse the existing exact version detail instead of showing an unusable run form',()=>{
 const f=nativeFixture({privateSkill:true,pathOnly:true}),wrapper=f.render(),detail=wrapper.type(wrapper.props);
 assert.equal(detail.type,'SkillDetail');assert.equal(detail.props.id,'method');assert.equal(detail.props.version,'7');assert.equal(detail.props.profileId,'profile-a');
 assert.equal(typeof detail.props.onClose,'function');assert.equal(f.calls.executions.length,0);assert.equal(f.calls.previews.length,0);
});

test('catalog-owned version details close their original selection for both close and Back',()=>{
 let closed=0;const f=fixture({onClose:()=>closed++});f.render().props.onClose();assert.equal(closed,1);assert.equal(f.calls.replace.length,0);
 const back=fixture({onClose:()=>closed++});back.render().props.onDismiss();assert.equal(closed,2);assert.equal(back.calls.replace.length,0);
});

test('a real skill question uses the original QuestionCards and exact runtime services without a permanent bar',async()=>{
 const f=nativeFixture(),extension=()=>nodes(f.render()).find(node=>node.type==='SkillDrawer').props.extension;assert.equal(extension(),undefined);
 const question={id:'permission-exact',status:'pending',items:[]};f.setExecution({sessionId:'session-exact',turnId:'turn-exact',questions:[question]});
 const drawer=nodes(f.render()).find(node=>node.type==='SkillDrawer'),cards=nodes(drawer.props.extension).find(node=>node.type==='QuestionCards');
 assert.equal(cards.props.questions[0],question);assert.equal(cards.props.services,f.services.questionServices);
 await cards.props.services.answer({questionId:'permission-exact',answers:{action:['allow']}});cards.props.onDone('permission-exact');
 assert.deepEqual(f.calls.answers,[{questionId:'permission-exact',answers:{action:['allow']}}]);assert.deepEqual(f.calls.closed,['permission-exact']);
 assert.equal(extension(),undefined);assert.equal(f.calls.executions.length,0);assert.equal(f.calls.navigation.length,0);
 f.setExecution({sessionId:'session-exact',turnId:'turn-exact',questions:[{...question,id:'expired-question'}]});
 const closed=nodes(nodes(f.render()).find(node=>node.type==='SkillDrawer').props.extension).find(node=>node.type==='QuestionCards');closed.props.onClosed('expired-question','expired');
 assert.deepEqual(f.calls.closed,['permission-exact','expired-question']);assert.equal(extension(),undefined);
});
