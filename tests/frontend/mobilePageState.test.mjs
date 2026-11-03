import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
import {viewStateModule} from './helpers/viewState.mjs';
import {moduleLoader} from './helpers/modules.mjs';
const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const plain=value=>JSON.parse(JSON.stringify(value));
const all=value=>Array.isArray(value)?value.flatMap(all):value&&typeof value==='object'?[value,...all(value.props?.children)]:[];
const text=value=>Array.isArray(value)?value.map(text).join(''):value&&typeof value==='object'?text(value.props?.children):value==null?'':String(value);
const button=(tree,label)=>all(tree).find(node=>node.type==='button'&&text(node)===label);
const stateStore=initial=>{let value=initial;return {writes:[],read:()=>value,write(next){value=plain(next);this.writes.push(value)},remove(){value=null}}};

/** Real components and storage hook; no copied render or action implementation. */
function component(file,api={},options={}){
 const slots=[],effects=[];let index=0,dirty=true,tree,props={};
 const same=(a,b)=>a&&b&&a.length===b.length&&a.every((v,i)=>Object.is(v,b[i]));
 const react={Component:class{},
  useState(initial){const i=index++;if(!(i in slots))slots[i]=typeof initial==='function'?initial():initial;return [slots[i],next=>{const value=typeof next==='function'?next(slots[i]):next;if(!Object.is(value,slots[i])){slots[i]=value;dirty=true}}]},
  useRef(initial){const i=index++;return slots[i]??=( {current:initial} )},
  useMemo(fn,deps){const i=index++;if(!slots[i]||!same(slots[i].deps,deps))slots[i]={deps,value:fn()};return slots[i].value},
  useCallback(fn,deps){return react.useMemo(()=>fn,deps)},
  useEffect(fn,deps){const i=index++;if(!slots[i]||!same(slots[i].deps,deps)){const prior=slots[i];slots[i]={deps};effects.push(()=>{prior?.cleanup?.();slots[i].cleanup=fn()})}},
 };
 react.useLayoutEffect=react.useEffect;
 const apiPort={peekApiData:()=>undefined,subscribeApiData:()=>()=>{},...api};
 const element=(type,props,key)=>({type,props:props??{},key});
 const exports={},source=readFileSync(new URL('../../web/frontend/src/components/'+file+'.tsx',import.meta.url),'utf8')+(file==='TrendsPage'?'\nexport {TrendsPanel};':'');
 const imports={react,'react/jsx-runtime':{jsx:element,jsxs:element,Fragment:'fragment'},'../lib/viewState':viewStateModule(react),'../lib/api':apiPort,'../lib/outputBrowser':moduleLoader()('lib/outputBrowser.ts'),
  '../lib/sanitize':{renderMarkdown:value=>value},'../lib/skillDisplayNames':{displayName:value=>value},'./Drawer':'Drawer','./SettingsSelect':'SettingsSelect',
  './SkillDrawer':'SkillDrawer','./TrendSourcesDialog':'TrendSourcesDialog','./DownloadLink':'DownloadLink','./MessageBubble':'MessageBubble','./QuestionCards':'QuestionCards',
  './BrushEntry':{default:'BrushEntry',BrushItem:'BrushItem'},'./useBrushPopover':{useBrushPopover(){}}};
 Object.assign(imports,{'./skillIconsPlanning':{planningSkillIcons:{}},'./skillIconsProduce':{produceSkillIcons:{}},'./skillIconsPublish':{publishSkillIcons:{}},'./skillIconsBrand':{brandSkillIcons:{}}});
 runInNewContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,{
  exports,Date,Math,JSON,Error,window:{setTimeout:()=>1,clearTimeout(){},confirm:()=>true},document:{addEventListener(){},removeEventListener(){}},navigator:{clipboard:{}},requestAnimationFrame:fn=>{fn();return 1},
  fetch:async()=>({json:async()=>({max_mb:50})}),setTimeout:()=>1,clearTimeout(){},require:name=>name==='./icons'?new Proxy({},{get:()=>function Icon(){}}):imports[name]??assert.fail('Unexpected import '+name),
 });
 const page=file==='TrendsPage'?exports.TrendsPanel:exports.default;
 const render=(next=props)=>{props=next;index=0;dirty=false;tree=page(props);for(const node of all(tree)){if(node.props.ref&&node.props.className==='chat-messages')node.props.ref.current=options.scroll;if(node.type==='textarea'&&node.props.ref)node.props.ref.current={style:{},scrollHeight:30,focus(){}}}return tree};
 const settle=async()=>{for(let i=0;i<25;i++){if(dirty)render();effects.splice(0).forEach(run=>run());await Promise.resolve()}assert.equal(dirty,false);return tree};
 return {render,settle,get tree(){return tree},unmount(){for(const item of slots)item?.cleanup?.()}};
}

test('skill search restores per history entry and switching stores does not write another entry',async()=>{
 const a=stateStore({query:'image'}),b=stateStore({query:'audio'}),catalog={items:[],loading:false};
 const f=component('SkillPage');f.render({persona:'p',catalog,viewState:a});let tree=await f.settle();
 assert.equal(all(tree).find(node=>node.type==='input').props.value,'image');
 all(tree).find(node=>node.type==='input').props.onChange({target:{value:'poster'}});tree=await f.settle();assert.equal(a.read().query,'poster');
 f.render({persona:'p',catalog,viewState:b});tree=await f.settle();assert.equal(all(tree).find(node=>node.type==='input').props.value,'audio');
 assert.equal(a.read().query,'poster');assert.equal(b.writes.length,0);
 const again=component('SkillPage');again.render({persona:'p',catalog,viewState:a});tree=await again.settle();assert.equal(all(tree).find(node=>node.type==='input').props.value,'poster');
});

test('content gallery rehydrates exact directory and filter from metadata without serializing files',async()=>{
 const roots=[{type:'dir',name:'Project',path:'w',children:[{type:'file',name:'Image',path:'w/image.png',kind:'image'},{type:'file',name:'Text',path:'w/text.md',kind:'text'}]}];
 const api={peekApiData:path=>path==='/api/outputs'?roots:undefined,fetchOutputs:async()=>roots,mediaUrl:path=>'/media/'+path},store=stateStore({stack:['w'],filter:'image'});
 const f=component('OutputsPage',api);f.render({viewState:store,canDelete:()=>false});let tree=await f.settle();
 assert.ok(text(tree).includes('Project'));assert.equal(all(tree).filter(node=>node.props.className?.includes('gcard')&&node.key==='w/text.md').length,0);
 button(tree,'文档').props.onClick();tree=await f.settle();assert.equal(store.read().filter,'text');assert.deepEqual(Object.keys(store.read()).sort(),['filter','stack']);
 const again=component('OutputsPage',api);again.render({viewState:store,canDelete:()=>false});tree=await again.settle();assert.ok(text(tree).includes('Text'));assert.ok(!text(tree).includes('正在读取内容库'));
});

test('a consumed gallery deep link cannot reset browsing filters on background refresh or return',async()=>{
 const roots=[{type:'dir',name:'Project',path:'w',children:[{type:'file',name:'Text',path:'w/text.md',kind:'text'}]}];let updated;
 const api={peekApiData:path=>path==='/api/outputs'?roots:undefined,fetchOutputs:async()=>roots,mediaUrl:path=>'/media/'+path,subscribeApiData:(_path,onData)=>{updated=onData;return()=>{}}};
 const store=stateStore({stack:[],filter:'all'}),props={viewState:store,jumpPath:'w',canDelete:()=>false},f=component('OutputsPage',api);
 f.render(props);let tree=await f.settle();button(tree,'文档').props.onClick();await f.settle();assert.equal(store.read().jumpPath,'w');
 updated(plain(roots));tree=await f.settle();assert.equal(store.read().filter,'text');
 const again=component('OutputsPage',api);again.render(props);tree=await again.settle();assert.equal(store.read().filter,'text');assert.ok(button(tree,'文档').props.className.includes('active'));
});

test('mobile trend feeds restore selected sources without adding a nested scroll cap or pagination controls',async()=>{
 const sources={sources:[{id:'a',label:'A',default:true},{id:'b',label:'B',default:false}],warnings:[]};
 const result=ids=>({trends:ids.map(platform=>({platform,label:platform.toUpperCase(),ok:true,items:Array.from({length:30},(_,i)=>({id:platform+i,title:platform+' item '+i,url:'https://example.invalid/'+i}))})),warnings:[],updated:1});
 const api={peekApiData:path=>path==='/api/trends/sources'?sources:path.startsWith('/api/trends?')?result(new URL('https://x'+path).searchParams.get('platforms').split(',')):undefined,
  fetchTrendSources:async()=>sources,fetchTrends:async platforms=>result(platforms.split(','))},store=stateStore({selected:['a'],initialized:true});
 const f=component('TrendsPage',api);f.render({onUseTopic(){},listLimit:1000,quietBackgroundRefresh:true,viewState:store});let tree=await f.settle();
 assert.equal(all(tree).filter(node=>node.props.className==='trend-item').length,30);
 assert.equal(all(tree).find(node=>node.props.className==='trend-list').props.style,undefined);
 button(tree,'B').props.onClick();tree=await f.settle();assert.deepEqual(store.read().selected,['a','b']);
 const again=component('TrendsPage',api);again.render({onUseTopic(){},listLimit:1000,quietBackgroundRefresh:true,viewState:store});tree=await again.settle();
 assert.equal(all(tree).filter(node=>node.props.className==='trend-item').length,60);assert.ok(!JSON.stringify(store.read()).includes('item'));
});

const calendarApi=()=>({peekApiData:path=>path==='/api/schedule'?[]:path.includes('/context')?{}:undefined,fetchSchedule:async()=>[],fetchScheduleContext:async()=>({})});
const calendarProps=()=>({viewState:stateStore({month:new Date(2026,0,1).getTime(),filter:'all',showSuggest:true}),draftStore:stateStore(null)});

test('calendar retains month and unsent input through close and remount, and reports read failures',async()=>{
 const props=calendarProps(),api=calendarApi();api.fetchSchedule=async()=>{throw Error('TEMP offline')};
 const f=component('CalendarPage',api);f.render(props);let tree=await f.settle();assert.ok(text(tree).includes('TEMP offline'));
 const cells=all(tree).filter(node=>node.props.className?.startsWith('cal-cell')&&!node.props.className.includes('dim'));cells[1].props.onClick();tree=await f.settle();
 const title=all(tree).find(node=>node.type==='input'&&node.props.placeholder==='要发什么内容');title.props.onChange({target:{value:'Unsent exact title'}});tree=await f.settle();
 all(tree).find(node=>node.type==='button'&&node.props.className==='icon-btn').props.onClick();await f.settle();assert.equal(props.draftStore.read().form.title,'Unsent exact title');
 const again=component('CalendarPage',calendarApi());again.render(props);tree=await again.settle();all(tree).filter(node=>node.props.className?.startsWith('cal-cell')&&!node.props.className.includes('dim'))[1].props.onClick();tree=await again.settle();
 assert.equal(all(tree).find(node=>node.type==='input'&&node.props.placeholder==='要发什么内容').props.value,'Unsent exact title');
});

test('a delayed calendar save acknowledgement does not erase newer unsent edits',async()=>{
 let done;const api=calendarApi();api.createSchedule=()=>new Promise(resolve=>{done=resolve});const props=calendarProps(),f=component('CalendarPage',api);
 f.render(props);let tree=await f.settle();all(tree).find(node=>node.props.className?.startsWith('cal-cell')&&!node.props.className.includes('dim')).props.onClick();tree=await f.settle();
 const input=()=>all(tree).find(node=>node.type==='input'&&node.props.placeholder==='要发什么内容');input().props.onChange({target:{value:'Submitted'}});tree=await f.settle();
 const save=button(tree,'保存').props.onClick();tree=await f.settle();input().props.onChange({target:{value:'New unsent input'}});tree=await f.settle();
 done({id:'created'});await save;tree=await f.settle();assert.equal(input().props.value,'New unsent input');assert.equal(props.draftStore.read().form.title,'New unsent input');
});

test('calendar drafts remain separate by day and opening another empty form does not persist server data',async()=>{
 const entries=new Map(),props=calendarProps();props.draftStore={read:(date,id)=>entries.get(id||date)??null,write:draft=>entries.set(draft.editingId||draft.key,plain(draft)),remove:draft=>entries.delete(draft.editingId||draft.key)};
 const f=component('CalendarPage',calendarApi());f.render(props);let tree=await f.settle();
 const day=i=>all(tree).filter(node=>node.props.className?.startsWith('cal-cell')&&!node.props.className.includes('dim'))[i];
 const input=()=>all(tree).find(node=>node.type==='input'&&node.props.placeholder==='要发什么内容');
 const close=()=>all(tree).find(node=>node.type==='button'&&node.props.className==='icon-btn').props.onClick();
 day(0).props.onClick();tree=await f.settle();assert.equal(entries.size,0);input().props.onChange({target:{value:'Day one input'}});tree=await f.settle();close();tree=await f.settle();
 day(1).props.onClick();tree=await f.settle();input().props.onChange({target:{value:'Day two input'}});tree=await f.settle();close();tree=await f.settle();
 day(0).props.onClick();tree=await f.settle();assert.equal(input().props.value,'Day one input');assert.equal(entries.size,2);
});

test('skill execution input survives close/remount without persisting API credentials',async()=>{
 const store=stateStore(null),detail={name:'image',body:'Native body',needsApi:true,apiConfigured:false,apiSpec:{label:'Image',settings:[],providers:[{id:'p',name:'P',keys:[{env:'SECRET',label:'Key',required:true,secret:true,configured:false,choices:[]}]}]}};
 const props={skillName:'image',persona:'p',onClose(){},onConfigured(){},draftStore:store,services:{loadDetail:async()=>detail}};
 const f=component('SkillDrawer');f.render(props);let tree=await f.settle();
 all(tree).find(node=>node.type==='textarea').props.onChange({target:{value:'Original unsent input'}});tree=await f.settle();
 all(tree).find(node=>node.type==='input'&&node.props.type==='password').props.onChange({target:{value:'do-not-persist'}});await f.settle();assert.equal(store.read(),'Original unsent input');
 const again=component('SkillDrawer');again.render(props);tree=await again.settle();assert.equal(all(tree).find(node=>node.type==='textarea').props.value,'Original unsent input');assert.equal(all(tree).find(node=>node.type==='input'&&node.props.type==='password').props.value,'');
});

test('chat restores reading position, ignores streaming while scrolled up and resumes following near bottom',async()=>{
 const calls=[],scroll={scrollTop:0,scrollHeight:1200,clientHeight:300,scrollTo(value){calls.push(value);this.scrollTop=value.top}},store=stateStore({top:140,following:false});
 let props={apiDirect:false,session:{id:'s',title:'s',messages:[{id:'m1',role:'assistant',content:'Original message'}]},onSend(){},onStop(){},onResend(){},viewState:store};
 const f=component('ChatPage',{}, {scroll});f.render(props);let tree=await f.settle();assert.equal(scroll.scrollTop,140);assert.equal(calls.length,0);
 props={...props,stream:{content:'New token',thinking:'',activity:'',questions:[]}};f.render(props);tree=await f.settle();assert.equal(calls.length,0);
 assert.equal(all(tree).find(node=>node.props['data-native-anchor']).props['data-native-anchor'],'chat:m1');
 scroll.scrollTop=900;all(tree).find(node=>node.props.className==='chat-messages').props.onScroll({currentTarget:scroll});assert.equal(store.read().following,true);
 props={...props,stream:{...props.stream,content:'More token'}};f.render(props);await f.settle();assert.equal(calls.at(-1).top,1200);
});

test('the same chat component restores each history entry and resets its following state',async()=>{
 const calls=[],scroll={scrollTop:0,scrollHeight:1200,clientHeight:300,scrollTo(value){calls.push(value);this.scrollTop=value.top}},a=stateStore({top:140,following:false}),b=stateStore({top:900,following:true});
 const props={apiDirect:false,session:{id:'same-session',title:'s',messages:[{id:'m1',role:'assistant',content:'Original message'}]},onSend(){},onStop(){},onResend(){}};
 const f=component('ChatPage',{}, {scroll});f.render({...props,viewState:a});await f.settle();assert.equal(scroll.scrollTop,140);assert.equal(calls.length,0);
 f.render({...props,viewState:b});let tree=await f.settle();assert.equal(calls.at(-1).top,1200);
 scroll.scrollTop=620;all(tree).find(node=>node.props.className==='chat-messages').props.onScroll({currentTarget:scroll});assert.deepEqual(b.read(),{top:620,following:false});
 f.render({...props,viewState:a});await f.settle();assert.equal(scroll.scrollTop,140);assert.equal(calls.length,1);
 f.render({...props,viewState:b});await f.settle();assert.equal(scroll.scrollTop,620);assert.equal(calls.length,1);
 assert.equal(a.writes.length,0);assert.equal(b.writes.length,1);
});
