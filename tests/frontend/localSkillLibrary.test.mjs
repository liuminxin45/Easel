import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';

const jsx={jsx:(type,props)=>({type,props:props||{}}),jsxs:(type,props)=>({type,props:props||{}}),Fragment:'fragment'};
const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
const text=value=>Array.isArray(value)?value.map(text).join(''):value&&typeof value==='object'?text(value.props?.children):value==null?'':String(value);
const plain=value=>JSON.parse(JSON.stringify(value));
const local=(id,category='writing',repo='example/writing',stars=1200,stages=['writing'])=>({name:id,display_name:'油猪·'+id,description:'说明',layer:'produce',needsApi:false,apiConfigured:true,local_skill:{id,category,category_label:category==='writing'?'写作与叙事':'润色与去 AI 味',repository:repo,url:'https://github.com/'+repo,commit:'a'.repeat(40),original_name:id+'-original',stages,tags:['中文'],stars,checked_at:1800000000}});

function fixture(){
 let cursor=0;const state=[],refs=[],calls={get:[],post:[],reads:[],changes:[]},views=new Map();
 const skills=[local('local-writer'),local('local-polish','polish','example/polish',2400,['polish']),local('local-layout','layout','example/layout',null,['layout'])];
 const data={revision:'exact-source-revision',skills,stages:{writing:'写作方法',research:'资料研究',polish:'润色',review:'审稿',layout:'排版',cover:'封面',illustration:'正文配图'}};
 const react={useState:initial=>{const i=cursor++;if(!(i in state))state[i]=typeof initial==='function'?initial():initial;return [state[i],value=>{state[i]=typeof value==='function'?value(state[i]):value}]},useRef:initial=>{const i=cursor++;if(!(i in refs))refs[i]={current:initial};return refs[i]}};
 const vm={config:{csrf:'fixture-csrf'},api:{get:async path=>{calls.get.push(path);return {running:false}},post:async(...args)=>{calls.post.push(args);return {running:true}}}};
 const hooks={useWorkbench:()=>vm,useResource:path=>{calls.reads.push(path);return {data:path.endsWith('view=sources')?{categories:{writing:'写作与叙事',polish:'润色与去 AI 味'},repositories:['example/writing','example/polish']}:data}},useViewState:(scope,initial)=>{if(!views.has(scope))views.set(scope,initial);return {read:()=>views.get(scope),write:value=>views.set(scope,value)}}};
 const load=moduleLoader({imports:{react,'react/jsx-runtime':jsx,'./hooks':hooks,'@workbench/core':{},'../../components/SettingsSelect':'SettingsSelect','./skillIcons':{localSkillIcon:(id,category)=>({id,category})},'./local-skills.css':{}},globals:{setTimeout:fn=>{fn();return 1}}});
 const lib=load('workbench/ui/LocalSkillLibrary.tsx');
 return {lib,data,skills,calls,render:()=>{cursor=0;return lib.useLocalSkillPresentation()},aux:props=>{cursor=0;return lib.AuxiliarySkills({value:{},disabled:false,format:'poster',onChange:(...args)=>calls.changes.push(plain(args)),...props})}};
}

test('source, category and Star order are private presentation over original native cards',()=>{
 const f=fixture();let p=f.render();
 assert.ok(p.filter(f.skills[0]));assert.ok(p.filter({name:'native-example'}));
 const select=label=>nodes(p.controls).find(node=>node.type==='SettingsSelect'&&node.props.label===label);
 select('技能来源').props.onChange('imported');p=f.render();assert.ok(p.filter(f.skills[0]));assert.equal(p.filter({name:'native-example'}),false);
 select('技能细分类').props.onChange('polish');p=f.render();assert.equal(p.filter(f.skills[0]),false);assert.ok(p.filter(f.skills[1]));
 select('技能细分类').props.onChange('all');p=f.render();select('技能排序').props.onChange('stars');p=f.render();
 assert.deepEqual([...f.skills].sort(p.compare).map(skill=>skill.name),['local-polish','local-writer','local-layout']);
 assert.match(p.searchText(f.skills[0]),/example\/writing/);assert.match(p.searchText(f.skills[0]),/original/);
 assert.equal(p.icon({name:'native-example'}),undefined);assert.equal(p.icon(f.skills[0]),p.icon(f.skills[0]));
 assert.ok(f.calls.reads.every(path=>path==='/api/local-skills?view=sources'));
 assert.equal(f.calls.get.length,0);assert.equal(f.calls.post.length,0);
});

test('Star badges distinguish unavailable metadata from zero and identify source and check time',()=>{
 const f=fixture();assert.equal(f.lib.SourceInfo({skill:{name:'official'}}),null);
 const known=f.lib.SourceInfo({skill:f.skills[0],detail:true});
 assert.match(text(known),/★ 1,200/);assert.match(text(known),/仓库关注数，非单技能使用人数/);assert.match(text(known),/核查：/);
 assert.equal(nodes(known).find(node=>node.type==='a').props.href,'https://github.com/example/writing');
 const unknown=f.lib.SourceInfo({skill:f.skills[2]});assert.match(text(unknown),/★ —/);assert.doesNotMatch(text(unknown),/★ 0/);
 const blocked=f.lib.SourceInfo({skill:{...f.skills[0],executionBlocked:'需配置：独立服务'}});assert.match(text(blocked),/需配置：独立服务/);
});

test('manual Star refresh updates presentation only through authenticated metadata routes',async()=>{
 const f=fixture();let p=f.render();await nodes(p.controls).find(node=>node.type==='button').props.onClick();
 // onClick intentionally starts a promise without returning it.
 await new Promise(resolve=>setImmediate(resolve));p=f.render();
 assert.deepEqual(plain(f.calls.post),[['/api/local-skills/sources/refresh',{},'fixture-csrf']]);assert.deepEqual(f.calls.get,['/api/local-skills/sources']);
 assert.equal(p.revision,1);assert.equal(f.data.revision,'exact-source-revision');assert.equal(f.calls.changes.length,0);
});

test('auxiliary selection remains optional, stage-specific and has no execution side effects',()=>{
 const f=fixture();let tree=f.aux();
 const selectors=nodes(tree).filter(node=>node.type==='SettingsSelect');assert.equal(selectors.some(node=>node.props.label==='排版技能'),false);
 const writer=selectors.find(node=>node.props.label==='写作方法技能');assert.equal(writer.props.value,'');assert.equal(writer.props.options[0].label,'沿用油猪写法');
 writer.props.onChange('local-writer');assert.deepEqual(f.calls.changes,[ [{writing:'local-writer'},'exact-source-revision'] ]);
 tree=f.aux({value:{writing:'local-writer',polish:'local-polish'},format:'article'});
 assert.ok(nodes(tree).find(node=>node.type==='SettingsSelect'&&node.props.label==='排版技能'));
 nodes(tree).find(node=>node.type==='SettingsSelect'&&node.props.label==='写作方法技能').props.onChange('');
 assert.deepEqual(f.calls.changes.at(-1),[{polish:'local-polish'},'exact-source-revision']);
 assert.ok(nodes(f.aux({disabled:true})).filter(node=>node.type==='SettingsSelect').every(node=>node.props.disabled));
 assert.equal(f.calls.get.length,0);assert.equal(f.calls.post.length,0);
 f.data.skills=[];assert.equal(f.aux(),null);
});

test('methods awaiting an external service remain visible in the library but are not production choices',()=>{
 const f=fixture();f.skills.push({...local('local-unconfigured'),executionBlocked:'需配置：独立工作目录与服务'});
 const presentation=f.render();assert.ok(presentation.filter(f.skills.at(-1)));
 const writer=nodes(f.aux()).find(node=>node.type==='SettingsSelect'&&node.props.label==='写作方法技能');
 assert.ok(writer.props.options.some(option=>option.value==='local-writer'));
 assert.equal(writer.props.options.some(option=>option.value==='local-unconfigured'),false);
 assert.equal(f.calls.post.length,0);
});

test('only production freezes explicit auxiliary choices; ordinary discussion keeps the original contract',()=>{
 const {creationRequest}=moduleLoader()('workbench/ui/newsCreation.ts');
 const style={writing:'writing-1',visual:'visual-1',character:'character-1',layout:'layout-1'};
 const context={catalog_revision:'catalog',source_revision:'news',profile_revision:4,formats:['poster','article'],components:Object.fromEntries(Object.entries(style).map(([slot,id])=>[slot,[{id,available:true}]])),defaults:{}};
 const draft={style,note:'原始要求',auxiliary_skills:{writing:'local-writer'},auxiliary_revision:'exact-source-revision'};
 const produce=creationRequest(context,'produce',draft,'poster');assert.deepEqual(plain(produce.auxiliary_skills),draft.auxiliary_skills);assert.equal(produce.auxiliary_revision,'exact-source-revision');
 const discuss=creationRequest(context,'discuss',draft);assert.equal(discuss.auxiliary_skills,undefined);assert.equal(discuss.auxiliary_revision,undefined);
 const original=creationRequest(context,'produce',{style,note:draft.note},'poster');assert.equal(original.auxiliary_skills,undefined);assert.equal(original.auxiliary_revision,undefined);
});
