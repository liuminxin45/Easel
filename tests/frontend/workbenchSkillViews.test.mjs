import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';

const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const element=(type,props)=>({type,props}),jsx={jsx:element,jsxs:element,Fragment:'fragment'};
const record=value=>value&&typeof value==='object'?value:{},array=value=>Array.isArray(value)?value:[],plain=value=>JSON.parse(JSON.stringify(value));
const common=Object.fromEntries(['ActionButton','Modal','Notice','Field','Panel','PageHead','Markdown','Pending','TextRecord','JsonDetails'].map(name=>[name,name]));
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
function fixture(){
 const state=hooks(),draft={prompt:'  原技能\n保留原字  ',reason:'改进表达',conditions:'移动端'},calls={writes:[],replace:[]};
 const detail={id:'creator-method',name:'贴图制作',version:2,published_version:1,status:'candidate',tasks:['poster','article'],resources:[],prompt:draft.prompt,diff:{before:'原方法',after:'新方法'},launch_actions:[]};
 const data={profiles:[{id:'profile-a',name:'作者甲',revision:7}],skills:[{id:detail.id,versions:[{version:1,status:'published'},{version:2,status:'candidate'}]}],task_policy:{poster:{},article:{}}};
 const vm={replace:path=>calls.replace.push(path),service:{creatorCommand:async(...args)=>{calls.writes.push(args);return {}}}};
 const core={record,array,string:value=>typeof value==='string'?value:'',number:value=>Number(value)||0,useWorkbench:()=>vm,useResource:()=>({data:detail}),useDraft:()=>[draft,patch=>Object.assign(draft,patch)],useAsyncAction:()=>({busy:false,run:fn=>fn()})};
 const {SkillDetail}=load('management.tsx',{react:state.react,'@workbench/core':core},'\nexport {SkillDetail};');
 const render=()=>state.render(()=>SkillDetail({id:detail.id,version:'2',data,profileId:'profile-a'}));
 const button=(tree,label)=>nodes(tree).find(node=>['button','ActionButton'].includes(node.type)&&text(node.props.children)===label);
 return {render,button,calls,draft,detail};
}

test('skill publishing stays in one modal and shows its exact diff inline without writing',()=>{
 const f=fixture(),initial=f.render();
 f.button(initial,'确认适用范围并发布').props.onClick();const confirm=f.render();
 assert.equal(confirm.type,'Modal');assert.equal(confirm.props.title,'发布技能版本');
 assert.equal(nodes(confirm).filter(node=>node.type==='Modal').length,1);
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

test('native skill catalog uses concise copy and preserves real unavailable reasons',()=>{
 const reason='所需服务尚未配置',skill={id:'upstream-skill',name:'upstream-skill',origin:'easel',available:false,reason};
 const core={useWorkbench:()=>({navigation:{},navigate:()=>{}}),useResource:()=>({data:[skill]})};
 const pages=load('NativeSkills.tsx',{react:{useEffect:()=>{}},'@workbench/core':core,'../../components/SkillPage':'SkillPage','../../components/SkillDrawer':'SkillDrawer','./ChatSessionView':{nativeSkillChoices:()=>[{id:'skill:entry',label:'使用技能',disabled:true}],nativeSkillDestination:()=>null}});
 const page=pages.NativeSkills({profileId:'profile-a',onUse:async()=>{}}),wrapped=page.props.renderDrawer(skill.name,()=>{}),drawer=wrapped.type(wrapped.props);
 assert.equal(page.props.subtitle,'选择技能，带入对话后开始创作。');
 assert.equal(drawer.type,'SkillDrawer');assert.equal(drawer.props.footer,undefined);
 assert.equal(drawer.props.useNotice,reason);assert.equal(drawer.props.useDisabled,true);assert.equal(drawer.props.canConfigure,false);
});
