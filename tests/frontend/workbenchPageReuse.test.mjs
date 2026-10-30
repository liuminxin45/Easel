import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';

const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url));
const ts=require('typescript');
const native={};
for(const name of ['DashboardPage','OutputsPage','IdeasPage','TrendsPage','CalendarPage','BreakdownPage','ProfilePage'])native[name]=function NativePage(){};
const element=(type,props)=>({type,props});
const record=value=>value&&typeof value==='object'?value:{};
const routeSource=readFileSync(new URL('../../web/frontend/src/workbench/platform/native-routes.ts',import.meta.url),'utf8');
const routeModule={};
runInNewContext(ts.transpileModule(routeSource,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,{exports:routeModule});

function load(name,{data={},vm={},choices=[],viewport={compact:false}}={}){
 const source=readFileSync(new URL('../../web/frontend/src/workbench/ui/'+name,import.meta.url),'utf8');
 const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
 const exports={};
 const client={drafts:{get:()=>({}),set:()=>true},...vm.client};
 const host={service:{collectAll:async()=>({accepted:true})},navigate:()=>{},replace:()=>{},...vm,client};
 const core={record,string:(value,fallback='')=>typeof value==='string'?value:fallback,array:value=>Array.isArray(value)?value:[],number:value=>Number(value)||0,
  useWorkbench:()=>host,useResource:path=>({data:data[path]??null,reload:async()=>data[path]??null}),
  useDraft:(_,initial)=>[initial,()=>{}],useAsyncAction:()=>({busy:false,run:async fn=>fn()}),
  creatorAssetInputs:value=>value||[],workPath:(work,version)=>'/works/'+work.id+(version?'?version='+version:'')};
 runInNewContext(compiled,{exports,matchMedia:()=>({matches:viewport.compact,addEventListener(){},removeEventListener(){}}),require:specifier=>{
  if(specifier==='react')return {useCallback:fn=>fn,useMemo:fn=>fn(),useState:initial=>[initial,()=>{}],useSyncExternalStore:(_,snapshot)=>snapshot()};
  if(specifier==='react/jsx-runtime')return {jsx:element,jsxs:element,Fragment:'fragment'};
  if(specifier==='@workbench/core')return core;
  if(specifier==='../platform/native-routes')return routeModule;
  if(specifier==='./ChatSessionView')return {nativeSkillChoices:()=>choices};
  if(specifier==='./common')return new Proxy({},{get:(_,name)=>name==='resultDocument'?record:function Component(){}});
  if(specifier==='./management')return {SkillTask:function SkillTask(){}};
  const component=specifier.split('/').at(-1);
  if(native[component])return native[component];
  throw Error('Unexpected dependency: '+specifier);
 }});
 return exports;
}

test('workbench common routes render the complete native page components',()=>{
 const pages=load('nativePages.tsx',{data:{'/api/status':{runtime:'codex',gateway:true}}});
 const useTopic=()=>{};
 assert.equal(pages.NativeDashboard({profileId:'creator-a',onUseTopic:useTopic}).type,native.DashboardPage);
 assert.equal(pages.NativeTopics({onUseTopic:useTopic}).type,native.IdeasPage);
 assert.equal(pages.NativeTrends({onUseTopic:useTopic}).type,native.TrendsPage);
 assert.equal(pages.NativeCalendar().type,native.CalendarPage);
 assert.equal(pages.NativeLibrary({}).type,native.OutputsPage);
});

test('native gallery retains registered project version actions and forbids destructive history deletion',()=>{
 const calls=[];
 const pages=load('nativePages.tsx',{vm:{navigate:path=>calls.push(path)}});
 const gallery=pages.NativeLibrary({jumpPath:'__workbench__/file'});
 assert.equal(gallery.props.jumpPath,'__workbench__/file');
 assert.equal(gallery.props.canDelete({path:'original.png'}),false);
 const project={meta:{work_id:'work-a',version_id:'version-3'}};
 const extension=gallery.props.renderProjectDetails(project);
 const rendered=extension.type(extension.props);
 rendered.props.children.props.onClick();
 assert.deepEqual(calls,['/works/work-a?version=version-3']);
});

test('trends only collect on explicit refresh and preserve the complete source list',async()=>{
 let collections=0;
 const pages=load('nativePages.tsx',{vm:{service:{collectAll:async()=>{collections++}}}});
 const trends=pages.NativeTrends({onUseTopic:()=>{}});
 assert.equal(collections,0);
 assert.equal(trends.props.listLimit,1000);
 await trends.props.refreshAll();
 assert.equal(collections,1);
});

test('dashboard uses server data and leaves retired account auto-detection disabled',()=>{
 const pages=load('nativePages.tsx');
 const dashboard=pages.NativeDashboard({profileId:'exact-id',onUseTopic:()=>{}});
 assert.equal(dashboard.props.persistAnalytics,false);
 assert.equal(dashboard.props.verifyAccountsOnMount,false);
 assert.equal(dashboard.props.listMaxHeight,360);
});

test('compact dashboard delegates flat scrolling to the native page and restores bounded desktop lists',()=>{
 const viewport={compact:true},pages=load('nativePages.tsx',{viewport});
 const mobile=pages.NativeDashboard({profileId:'exact-id',onUseTopic:()=>{}});
 assert.equal(mobile.type,native.DashboardPage);
 assert.equal(mobile.props.listMaxHeight,undefined);
 assert.equal(mobile.props.verifyAccountsOnMount,false);
 viewport.compact=false;
 assert.equal(pages.NativeDashboard({profileId:'exact-id',onUseTopic:()=>{}}).props.listMaxHeight,360);
});

test('native profile editor keeps stable identity and makes account imports and deletion unavailable',()=>{
 const bootstrap={profiles:[{id:'creator-a',name:'Display A'}]};
 const pages=load('nativeProfiles.tsx',{data:{'/api/creator/bootstrap':bootstrap}});
 const tree=pages.NativeProfiles({search:new URLSearchParams('item=creator-a')});
 const page=tree.props.children.find(node=>node?.type===native.ProfilePage);
 assert.equal(page.props.persona,'creator-a');
 assert.equal(page.props.personaLabel('creator-a'),'Display A');
 assert.equal(page.props.allowAccountImport,false);
 assert.equal(page.props.allowDelete,false);
});

test('publishing AI action opens the same server session composer with the selected exact skill',async()=>{
 const writes=[],drafts=[],navigation=[];
 const selection={skill_id:'skill-content-repurposing',version:7,action_id:'native',source_revision:'sha-exact'};
 const actions=load('nativePublishing.ts',{choices:[{selection}],vm:{
  client:{mutate:async(...args)=>{writes.push(args);return {session:{id:'session-a',runtime:'codex'}}},drafts:{set:(...args)=>{drafts.push(args);return true}}},
  navigate:(...args)=>navigation.push(args),
 }}).useNativePublishingActions('creator-exact');
 await actions.adapt('原字稿件');
 assert.equal(writes.length,1);
 assert.equal(writes[0][1],'/api/chat/sessions');
 assert.equal(writes[0][2].profile_id,'creator-exact');
 assert.equal(drafts[0][0],'chat:session-a');
 assert.equal(drafts[0][1].command,selection);
 assert.equal(drafts[0][1].text,'原字稿件');
 assert.equal(navigation[0][0],'/chat/session-a');
});

test('unavailable publishing skill cannot start an anonymous model or create a session',async()=>{
 let writes=0;
 const actions=load('nativePublishing.ts',{vm:{client:{mutate:async()=>{writes++}}}}).useNativePublishingActions('creator-a');
 await assert.rejects(actions.check('原稿'),/准确版本/);
 assert.equal(writes,0);
});

test('native gallery resolves declared virtual file paths independently of display labels',async()=>{
 const file={type:'file',name:'正文.md',path:'__workbench__/registered-id/正文.md',kind:'text'};
 const roots=[{type:'dir',name:'显示标题',path:'workbench-id',meta:{work_id:'work-id',version_id:'newest-version'},children:[{type:'dir',name:'v03',path:'workbench-id/exact-version',meta:{work_id:'work-id',version_id:'exact-version'},children:[file]}]}];
 const source=readFileSync(new URL('../../web/frontend/src/components/OutputsPage.tsx',import.meta.url),'utf8');
 const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
 const exports={},states=[],effects=[],reads=[];let cursor=0,handled=0;
 runInNewContext(compiled,{exports,require:specifier=>{
  if(specifier==='react')return {useState:initial=>{const index=cursor++;if(!(index in states))states[index]=index===0?roots:initial;return [states[index],value=>{states[index]=value}]},useMemo:fn=>fn(),useCallback:fn=>fn,useRef:value=>({current:value}),useEffect:fn=>effects.push(fn)};
  if(specifier==='react/jsx-runtime')return {jsx:element,jsxs:element,Fragment:'fragment'};
  if(specifier==='../lib/api')return {fetchOutputs:async()=>roots,fetchOutputContent:async path=>{reads.push(path);return {content:'原字内容',isBinary:false}},mediaUrl:path=>path,deleteOutput:async()=>{throw Error('Deletion must not run')}};
  if(specifier==='../lib/sanitize')return {renderMarkdown:text=>text};
  if(specifier==='./icons')return new Proxy({},{get:()=>function Icon(){}});
  throw Error(specifier);
 }});
 exports.default({jumpPath:file.path,onJumpHandled:()=>{handled++}});
 effects[1]();
 await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(Array.from(states[3]),['显示标题','v03']);
 assert.equal(states[5],file);
 assert.deepEqual(reads,[file.path]);
 assert.equal(handled,1);
 cursor=0;let selectedProject;
 exports.default({renderProjectDetails:project=>{selectedProject=project;return null}});
 assert.equal(selectedProject.meta.version_id,'exact-version','historical project directory must not inherit the root latest version');
});
