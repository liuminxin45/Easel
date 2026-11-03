import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';
import {viewStateModule} from './helpers/viewState.mjs';

const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url));
const ts=require('typescript');
const native={};
for(const name of ['DashboardPage','OutputsPage','IdeasPage','TrendsPage','CalendarPage','BreakdownPage','ProfilePage','OnboardingWizard'])native[name]=function NativePage(){};
const element=(type,props)=>({type,props});
const record=value=>value&&typeof value==='object'?value:{};
const routeSource=readFileSync(new URL('../../web/frontend/src/workbench/platform/native-routes.ts',import.meta.url),'utf8');
const routeModule={};
runInNewContext(ts.transpileModule(routeSource,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,{exports:routeModule});

function load(name,{data={},vm={},choices=[],viewport={compact:false},react:reactOverride={},resourceReads=[],draftCache}={}){
 const source=readFileSync(new URL('../../web/frontend/src/workbench/ui/'+name,import.meta.url),'utf8');
 const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
 const exports={};
 const client={drafts:{get:()=>({}),set:()=>true},...vm.client};
 const host={service:{collectAll:async()=>({accepted:true})},navigation:{entryKey:'fixture',contentReady(){}},navigate:()=>{},replace:()=>{},...vm,client};
 const core={record,string:(value,fallback='')=>typeof value==='string'?value:fallback,array:value=>Array.isArray(value)?value:[],number:value=>Number(value)||0,sessionOpenFlows:()=>({open:input=>host.openSession?.(input)}),libraryDataSource:()=>({list(){},resolve(){}}),
  useWorkbench:()=>host,useResource:path=>{resourceReads.push(path);return {data:data[path]??null,reload:async()=>data[path]??null}},
  useDraft:(key,initial)=>{if(!draftCache)return [initial,()=>{}];if(!draftCache.has(key))draftCache.set(key,initial);return [draftCache.get(key),patch=>draftCache.set(key,{...draftCache.get(key),...patch})]},useAsyncAction:()=>({busy:false,run:async fn=>fn()}),
  useViewState:(_,initial)=>({read:()=>initial,write(){}}),
  creatorAssetInputs:value=>value||[],workPath:(work,version)=>'/works/'+work.id+(version?'?version='+version:'')};
 runInNewContext(compiled,{exports,URLSearchParams,matchMedia:()=>({matches:viewport.compact,addEventListener(){},removeEventListener(){}}),require:specifier=>{
  if(specifier==='react')return {useCallback:fn=>fn,useMemo:fn=>fn(),useState:initial=>[initial,()=>{}],useSyncExternalStore:(_,snapshot)=>snapshot(),...reactOverride};
  if(specifier==='react/jsx-runtime')return {jsx:element,jsxs:element,Fragment:'fragment'};
  if(specifier==='@workbench/core'||specifier==='./hooks')return core;
  if(specifier==='../../lib/api')return {peekApiData:()=>undefined};
  if(specifier==='../platform/native-routes')return routeModule;
  if(specifier==='./ChatSessionView')return {nativeSkillChoices:()=>choices};
  if(specifier==='./common')return new Proxy({},{get:(_,name)=>name==='resultDocument'?record:function Component(){}});
  if(specifier==='./ExtensionDetails')return {ExtensionDetails:function ExtensionDetails(){}};
  if(specifier==='./VersionOperations')return {VersionOperations:function VersionOperations(){}};
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
 assert.equal(rendered.type.name,'VersionOperations');assert.equal(rendered.props.workId,'work-a');assert.equal(rendered.props.versionId,'version-3');
 assert.deepEqual(calls,[]);
});

test('trends only collect on explicit refresh and preserve the complete source list',async()=>{
 let collections=0;
 const pages=load('nativePages.tsx',{vm:{service:{collectAll:async()=>{collections++}}}});
 const trends=pages.NativeTrends({onUseTopic:()=>{}});
 assert.equal(collections,0);
 assert.equal(trends.props.listLimit,1000);
 assert.equal(trends.props.quietBackgroundRefresh,true);
 await trends.props.refreshAll();
 assert.equal(collections,1);
});

test('dashboard uses server data and leaves retired account auto-detection disabled',()=>{
 const pages=load('nativePages.tsx');
 const dashboard=pages.NativeDashboard({profileId:'exact-id',onUseTopic:()=>{}});
 assert.equal(dashboard.props.persistAnalytics,false);
 assert.equal(dashboard.props.verifyAccountsOnMount,false);
 assert.equal(dashboard.props.listMaxHeight,360);
 assert.equal(typeof dashboard.props.outputsSource.list,'function');
});

test('compact dashboard delegates flat scrolling to the native page and restores bounded desktop lists',()=>{
 const viewport={compact:true},pages=load('nativePages.tsx',{viewport});
 const mobile=pages.NativeDashboard({profileId:'exact-id',onUseTopic:()=>{}});
 assert.equal(mobile.type,native.DashboardPage);
 assert.equal(mobile.props.listMaxHeight,null);
 assert.equal(mobile.props.verifyAccountsOnMount,false);
 viewport.compact=false;
 assert.equal(pages.NativeDashboard({profileId:'exact-id',onUseTopic:()=>{}}).props.listMaxHeight,360);
});

test('native profile editor keeps stable identity and makes account imports and deletion unavailable',()=>{
 const bootstrap={profiles:[{id:'creator-a',name:'Display A'}]};
 const pages=load('nativeProfiles.tsx',{data:{'/api/creator/bootstrap?view=summary':bootstrap}});
 const tree=pages.NativeProfiles({search:new URLSearchParams('item=creator-a')});
 const page=tree.props.children.find(node=>node?.type===native.ProfilePage);
 assert.equal(page.props.persona,'creator-a');
 assert.equal(page.props.personaLabel('creator-a'),'Display A');
 assert.equal(page.props.allowAccountImport,false);
 assert.equal(page.props.allowDelete,false);
});

test('profile binding disclosure requests only full selected current data and never saves summary blanks',async()=>{
 const id='creator-a',reads=[],commands=[],draftCache=new Map(),states=[];let cursor=0;
 const react={useState:initial=>{const index=cursor++;if(!(index in states))states[index]=initial;return [states[index],value=>{states[index]=value}]}};
 const summary={profiles:[{id,name:'Summary A',revision:4}],skills:[],accounts:[],task_defaults:{poster:[]}},path='/api/creator/profiles/'+id+'?view=current';
 const data={'/api/creator/bootstrap?view=summary':summary},profile={id,name:'Full A',revision:4,identity:'Exact identity',audience:'Exact audience',voice:'Exact voice',boundaries:'Exact boundaries',account_ids:[],asset_refs:[{path:'assets/original.png',label:'Original',role:'reference',required:true}],default_skills:{poster:['exact-skill']}};
 const pages=load('nativeProfiles.tsx',{data,react,resourceReads:reads,draftCache,vm:{service:{uploadFiles:async()=>[],creatorCommand:async(action,input)=>{commands.push({action,input});return {profile:{...profile,revision:5,asset_refs:input.document.asset_refs}}}}}});
 const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
 const tree=pages.NativeProfiles({search:new URLSearchParams('item='+id)}),page=tree.props.children.find(node=>node?.type===native.ProfilePage),extension=page.props.renderDetailExtension(id);
 const renderDisclosure=()=>{cursor=0;return extension.type(extension.props)};
 let disclosure=renderDisclosure();assert.deepEqual(reads,['/api/creator/bootstrap?view=summary']);assert.equal(disclosure.props.children,false);
 disclosure.props.onToggle({currentTarget:{open:true}});disclosure=renderDisclosure();
 const source=disclosure.props.children;let selected=source.type(source.props);
 assert.equal(reads.at(-1),path);assert.equal(draftCache.size,0,'no editable form initialized from missing/summary data');
 data[path]=profile;selected=source.type(source.props);
 let form=nodes(selected).find(node=>node.props?.profile===profile),bindings=form.type(form.props);
 assert.equal(draftCache.get('creator:profile-bindings:'+id).asset_refs[0].path,'assets/original.png');
 nodes(bindings).find(node=>node.props?.children==='移除绑定').props.onClick();
 disclosure.props.onToggle({currentTarget:{open:false}});disclosure=renderDisclosure();assert.ok(disclosure.props.children,'first-open resource/form remain mounted across collapse');
 selected=source.type(source.props);form=nodes(selected).find(node=>node.props?.profile===profile);bindings=form.type(form.props);
 assert.deepEqual(JSON.parse(JSON.stringify(draftCache.get('creator:profile-bindings:'+id).asset_refs)),[]);
 nodes(bindings).find(node=>node.props?.children==='保存素材绑定').props.onClick();await new Promise(resolve=>setImmediate(resolve));
 assert.equal(commands.length,1);assert.equal(commands[0].action,'profile-save');assert.equal(commands[0].input.base_revision,4);
 for(const key of ['name','identity','audience','voice','boundaries'])assert.equal(commands[0].input.document[key],profile[key]);
 assert.equal(commands[0].input.document.default_skills,undefined);
 assert.deepEqual(JSON.parse(JSON.stringify(commands[0].input.document.asset_refs)),[]);
 assert.equal(reads.some(path=>path==='/api/creator/bootstrap'),false);
});

test('creating a profile composes the original onboarding wizard and preserves the server stable ID',()=>{
 const navigation=[],drafts=[],invalidated=[];
 const pages=load('nativeProfiles.tsx',{vm:{replace:path=>navigation.push(path),client:{invalidate:async tags=>invalidated.push(tags),drafts:{get:()=>null,set:(...args)=>{drafts.push(args);return true},remove:()=>{}}}}});
 const route=pages.NativeProfiles({search:new URLSearchParams('item=new')}),wizard=route.type(route.props);
 assert.equal(wizard.type,native.OnboardingWizard);
 const input={form:{name:'显示名',direction:'原始方向'},step:2};wizard.props.draftStore.write(input);
 assert.deepEqual(drafts,[['creator:profile:wizard',input]]);
 wizard.props.onCreated('stable-profile-id');assert.deepEqual(navigation,['/toolbox?section=profiles&item=stable-profile-id']);assert.deepEqual(JSON.parse(JSON.stringify(invalidated)),[['creator']]);
});

test('publishing AI action opens the same server session composer with the selected exact skill',async()=>{
 const opens=[];
 const selection={skill_id:'skill-content-repurposing',version:7,action_id:'native',source_revision:'sha-exact'};
 const actions=load('nativePublishing.ts',{choices:[{selection}],vm:{
  openSession:async input=>{opens.push(input);return {id:'session-a',runtime:'codex'}},
 }}).useNativePublishingActions('creator-exact');
 await actions.adapt('原字稿件');
 assert.equal(opens.length,1);
 assert.equal(opens[0].profileId,'creator-exact');
 assert.equal(opens[0].draft.command,selection);
 assert.equal(opens[0].draft.text,'原字稿件');
});

test('unavailable publishing skill cannot start an anonymous model or create a session',async()=>{
 let writes=0;
 const actions=load('nativePublishing.ts',{vm:{client:{mutate:async()=>{writes++}}}}).useNativePublishingActions('creator-a');
 await assert.rejects(actions.check('原稿'),/所需技能尚不可用/);
 assert.equal(writes,0);
});

test('native gallery resolves declared virtual file paths independently of display labels',async()=>{
 const file={type:'file',name:'正文.md',path:'__workbench__/registered-id/正文.md',kind:'text'};
 const roots=[{type:'dir',name:'显示标题',path:'workbench-id',meta:{work_id:'work-id',version_id:'newest-version'},children:[{type:'dir',name:'v03',path:'workbench-id/exact-version',meta:{work_id:'work-id',version_id:'exact-version'},children:[file]}]}];
 const source=readFileSync(new URL('../../web/frontend/src/components/OutputsPage.tsx',import.meta.url),'utf8');
 const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
 const exports={},states=[],effects=[],reads=[];let cursor=0,handled=0;
 const react={useState:initial=>{const index=cursor++;if(!(index in states))states[index]=typeof initial==='function'?initial():initial;return [states[index],value=>{states[index]=typeof value==='function'?value(states[index]):value}]},useMemo:fn=>fn(),useCallback:fn=>fn,useRef:value=>({current:value}),useEffect:fn=>effects.push(fn)};
 runInNewContext(compiled,{exports,require:specifier=>{
  if(specifier==='react')return react;
  if(specifier==='../lib/viewState')return viewStateModule(react);
  if(specifier==='../lib/outputBrowser')return moduleLoader()('lib/outputBrowser.ts');
  if(specifier==='react/jsx-runtime')return {jsx:element,jsxs:element,Fragment:'fragment'};
  if(specifier==='../lib/api')return {peekApiData:()=>roots,subscribeApiData:()=>()=>{},fetchOutputs:async()=>roots,fetchOutputContent:async path=>{reads.push(path);return {content:'原字内容',isBinary:false}},mediaUrl:path=>path,deleteOutput:async()=>{throw Error('Deletion must not run')}};
  if(specifier==='../lib/sanitize')return {renderMarkdown:text=>text};
  if(specifier==='./DownloadLink')return {default:'DownloadLink'};
  if(specifier==='./icons')return new Proxy({},{get:()=>function Icon(){}});
  throw Error(specifier);
 }});
 exports.default({jumpPath:file.path,onJumpHandled:()=>{handled++}});
 for(const effect of effects)effect();
 await new Promise(resolve=>setImmediate(resolve));
 assert.deepEqual(Array.from(states.find(value=>value?.stack)?.stack||[]),['workbench-id','workbench-id/exact-version']);
 assert.ok(states.includes(file));
 assert.deepEqual(reads,[file.path]);
 assert.equal(handled,1);
 cursor=0;let selectedProject;
 exports.default({renderProjectDetails:project=>{selectedProject=project;return null}});
 assert.equal(selectedProject.meta.version_id,'exact-version','historical project directory must not inherit the root latest version');
});


test('breakdown keeps its original execution port and preserved input without private skill selection or experience polling',()=>{
 const reads=[],draftCache=new Map([['easel:reference',{text:'  Exact source\nsecond line  ',goal:'Historical goal',task_id:'old-task'}]]),pages=load('nativePages.tsx',{resourceReads:reads,draftCache}),page=pages.NativeBreakdown({profileId:'creator-a',search:new URLSearchParams('skill=reference-analysis&trial=1')});
 assert.equal(page.type,native.BreakdownPage);assert.equal(page.props.persona,'creator-a');assert.equal(page.props.onAnalyze,undefined);assert.equal(page.props.resultContent,undefined);assert.equal(page.props.analysisBusy,undefined);assert.equal(page.props.inputState.value,'  Exact source\nsecond line  ');assert.equal(reads.length,0);
 page.props.inputState.onChange('  Later editable source  ');assert.equal(draftCache.get('easel:reference').text,'  Later editable source  ');assert.equal(draftCache.get('easel:reference').task_id,'old-task');
});
