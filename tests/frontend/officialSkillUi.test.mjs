import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
import {viewStateModule} from './helpers/viewState.mjs';

const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const jsx={jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props}),Fragment:'fragment'};
const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
const text=value=>Array.isArray(value)?value.map(text).join(''):value&&typeof value==='object'?text(value.props?.children):value==null?'':String(value);
const plain=value=>JSON.parse(JSON.stringify(value)),tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(file,api){
 const slots=[],deps=[],effects=[],timers=[];let cursor=0;
 const react={
  useState:initial=>{const i=cursor++;if(!(i in slots))slots[i]=typeof initial==='function'?initial():initial;return [slots[i],next=>{slots[i]=typeof next==='function'?next(slots[i]):next}]},
  useRef:initial=>{const i=cursor++;if(!(i in slots))slots[i]={current:initial};return slots[i]},
  useMemo:fn=>{cursor++;return fn()},useCallback:fn=>{cursor++;return fn},
  useEffect:(fn,next)=>{const i=cursor++,old=deps[i];if(!old||!next||old.length!==next.length||next.some((value,j)=>value!==old[j])){deps[i]=next;effects.push(fn)}},
 };
 const imports={react,'react/jsx-runtime':jsx,'./Drawer':'Drawer','./SettingsSelect':'SettingsSelect','../lib/api':api,'../lib/viewState':viewStateModule(react),'../lib/sanitize':{renderMarkdown:value=>'<p>'+value+'</p>'},'../lib/skillDisplayNames':{displayName:value=>value}};
 const source=readFileSync(new URL('../../web/frontend/src/components/'+file,import.meta.url),'utf8'),exports={};
 runInNewContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,{exports,require:name=>imports[name]??assert.fail('Unexpected import '+name),setTimeout:fn=>{timers.push(fn);return timers.length},clearTimeout:()=>{}});
 return {render(props){cursor=0;const tree=exports.default(props);effects.splice(0).forEach(fn=>fn());return tree},timers};
}

test('native skill controls keep configuration, explicit execution and inline real results through the official API functions',async()=>{
 let configured=false,finish;const calls={reads:0,saves:[],executions:[]};
 const read=async()=>{calls.reads++;return {name:'image',body:'原技能正文',layer:'produce',needsApi:true,apiConfigured:configured,apiSpec:{label:'原生供应商',settings:[],providers:[{id:'provider',name:'供应商',keys:[{env:'IMG_API_KEY',label:'API Key',required:true,secret:true,configured,masked:'',choices:[]}]}]}}};
 const api={fetchSkillDetail:read,saveEnv:async updates=>{calls.saves.push(updates);configured=true;return {ok:true,skills:{image:true}}},executeSkill:(...args)=>{calls.executions.push(args);return new Promise(resolve=>{finish=resolve})}};
 const f=fixture('SkillDrawer.tsx',api),props={skillName:'image',persona:'exact-profile',onClose:()=>{},onConfigured:()=>{}};
 let tree=f.render(props);await tick();tree=f.render(props);
 assert.equal(tree.type,'Drawer');assert.equal(calls.executions.length,0);
 assert.deepEqual(nodes(tree).filter(node=>node.props?.className==='panel-title').map(text),['🔑 原生供应商 · API 配置（任选一个服务商填齐即可用）','▶ 运行','📖 说明']);
 const runButton=()=>nodes(tree).find(node=>node.type==='button'&&text(node)==='执行');assert.equal(runButton().props.disabled,true);
 nodes(tree).find(node=>node.type==='input').props.onChange({target:{value:'the-new-key'}});tree=f.render(props);
 await nodes(tree).find(node=>node.type==='button'&&text(node)==='保存到 .env').props.onClick();tree=f.render(props);
 assert.deepEqual(plain(calls.saves),[{IMG_API_KEY:'the-new-key'}]);assert.equal(calls.reads,2);assert.equal(calls.executions.length,0);
 nodes(tree).find(node=>node.type==='textarea').props.onChange({target:{value:'  本轮输入\n原文  '}});tree=f.render(props);assert.equal(runButton().props.disabled,false);
 const pending=runButton().props.onClick();tree=f.render(props);assert.match(text(tree),/执行中/);assert.deepEqual(plain(calls.executions),[['image','本轮输入\n原文','exact-profile']]);
 finish({response:'真实完成结果'});await pending;tree=f.render(props);
 assert.equal(nodes(tree).find(node=>node.props?.className==='skill-result').props.dangerouslySetInnerHTML.__html,'<p>真实完成结果</p>');
 assert.equal(nodes(tree).some(node=>node.type==='select'),false);assert.doesNotMatch(text(tree),/带入对话|在对话中使用/);
});

test('the original onboarding form preserves all submitted fields and uses the returned stable profile identity',async()=>{
 const form={name:'作者显示名',platforms:['公众号'],accountStage:'已有账号',links:{公众号:'https://example.test/u'},direction:'保留方向原文',reason:'独特经历',goal:'运营目标',formats:'图文',likes:'原始喜好',tone:'专业严谨',avoid:'原始边界'};
 const calls={builds:[],created:[],removed:0,writes:[],status:0};
 const api={buildProfile:async(...args)=>{calls.builds.push(args);return {created:true,name:'profile-stable-id',async:false}},profileBuildStatus:async()=>{calls.status++;return {state:'done',log:''}}};
 const f=fixture('OnboardingWizard.tsx',api),props={onClose:()=>{},onCreated:id=>calls.created.push(id),draftStore:{read:()=>({form,step:2}),write:draft=>calls.writes.push(plain(draft)),remove:()=>calls.removed++}};
 let tree=f.render(props);assert.match(text(tree),/基础信息社媒链接运营意图偏好与红线/);
 assert.equal(nodes(tree).find(node=>node.type==='input'&&node.props.placeholder==='如：平价护肤测评').props.value,form.direction);
 nodes(tree).find(node=>node.type==='button'&&text(node)==='下一步').props.onClick();tree=f.render(props);
 await nodes(tree).find(node=>node.type==='button'&&text(node)==='生成画像').props.onClick();
 assert.deepEqual(plain(calls.builds),[[form.name,form]]);assert.deepEqual(calls.created,['profile-stable-id']);assert.equal(calls.removed,1);assert.equal(calls.status,0);
 assert.equal(calls.writes.at(-1).step,3);assert.deepEqual(calls.writes.at(-1).form,form);
});

test('closing the onboarding wizard preserves its draft without creating a profile',()=>{
 const calls={created:0,closed:0,writes:[]},f=fixture('OnboardingWizard.tsx',{buildProfile:()=>{calls.created++;throw Error('unexpected')},profileBuildStatus:()=>{throw Error('unexpected')}});
 let saved=null;const props={onClose:()=>calls.closed++,onCreated:()=>{},draftStore:{read:()=>saved,write:value=>{saved=plain(value);calls.writes.push(saved)},remove:()=>{saved=null}}};
 let tree=f.render(props);nodes(tree).find(node=>node.type==='input').props.onChange({target:{value:'未发送原输入'}});tree=f.render(props);
 nodes(tree).find(node=>node.type==='button'&&text(node)==='取消').props.onClick();assert.equal(calls.closed,1);assert.equal(calls.created,0);assert.equal(saved.form.name,'未发送原输入');
});
