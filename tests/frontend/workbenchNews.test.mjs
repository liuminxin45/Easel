import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const root=new URL('../../web/frontend/src/',import.meta.url),jsx={jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})};
function load(file,imports={}){const exports={};if(imports['../lib/api'])imports['../lib/api']={peekApiData:()=>undefined,subscribeApiData:()=>()=>{},...imports['../lib/api']};runInNewContext(ts.transpileModule(readFileSync(new URL(file,root),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,{exports,URL,URLSearchParams,Date,Set,require:id=>id==='react/jsx-runtime'?jsx:imports[id]??(id==='./InteractionNotice'?{InteractionNotice:()=>null}:assert.fail(id))});return exports}
const context=load('workbench/platform/news-context.ts'),navigation=load('workbench/platform/navigation.ts',{'./news-context':context});
const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?typeof value.type==='function'&&value.type.name==='ContentPanel'?nodes(value.type(value.props)):[value,...nodes(value.props?.children)]:[];

test('quiet trend retries keep layout and prior errors until success; native defaults retain progress',async()=>{
 const source=readFileSync(new URL('components/TrendsPage.tsx',root),'utf8'),tree=ts.createSourceFile('TrendsPage.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);let declaration;
 const visit=node=>{if(ts.isVariableDeclaration(node)&&node.name.getText(tree)==='load')declaration=node;ts.forEachChild(node,visit)};visit(tree);
 const compiled=ts.transpileModule('exports.load='+declaration.initializer.arguments[0].getText(tree),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
 for(const quiet of [true,undefined]){
  const changes=[],exports={};let release;
  runInNewContext(compiled,{exports,requestId:{current:0},quietBackgroundRefresh:quiet,listLimit:15,
   fetchTrends:()=>new Promise(resolve=>release=resolve),setGroups:()=>{},setLoading:value=>changes.push(['loading',value]),setError:value=>changes.push(['error',value]),setUpdated(){},setWarnings(){}});
  exports.load(['source'],true);
  assert.equal(changes.some(([field,value])=>field==='loading'&&value===true),!quiet);
  assert.equal(changes.some(([field,value])=>field==='error'&&value===''),!quiet);
  release({trends:[],updated:1,warnings:[]});await Promise.resolve();await Promise.resolve();
  assert.ok(changes.some(([field,value])=>field==='error'&&value===''));
 }
});
test('multi-source return context survives old deep links and shell validation',()=>{
 const windows=Object.fromEntries(Array.from({length:73},(_,i)=>['custom-'+i,{day:'2026-10-29',section:'分类',theme:'主题'}]));
 const selected={source:'custom-3',day:'2026-10-29',sources:Object.keys(windows).join(','),windows:JSON.stringify(windows)};
 const path=context.newsDetailPath('article-id',selected);
 assert.equal(navigation.safePath(path),path);
 assert.equal(navigation.safePath('/native/?path='+encodeURIComponent(path)),path);
 const parent=navigation.parentPath(path),params=new URL(parent,'https://test.invalid').searchParams;
 assert.equal(params.get('windows'),selected.windows);assert.equal(params.get('sources'),selected.sources);
 const derived=context.newsItemContext({source_job:'custom-3',run_at:'2026-10-29T10:00:00+08:00'},selected);
 assert.equal(derived.windows,selected.windows);assert.equal(derived.day,'2026-10-29');
 assert.equal(context.newsListPath({source:'old',day:'2026-10-28'}),'/news?source=old&day=2026-10-28');
 assert.equal(context.newsListPath({sources:''}),'/news?sources=');
 assert.equal(Object.keys(context.newsWindows('[]')).length,0);
 assert.equal(Object.keys(context.newsWindows('{"bad/id":{"day":"x"}}')).length,0);
});
function radar(overrides={},api={}){
 const defaults=[[],[],false,[],false,'',false,0,new Set(),false,[],''];
 const state=defaults.map((value,i)=>Object.hasOwn(overrides,i)?overrides[i]:value);let slot=0;
 const icons=Object.fromEntries(['IconFire','IconRefresh','IconBookmark','IconCheck','IconChat'].map(key=>[key,()=>null]));
 const map=[0,2,3,4,5,6,7,8,9,10,11];
 const react={Component:class {},useState:()=>{const index=map[slot++];return [state[index],next=>{state[index]=typeof next==='function'?next(state[index]):next}]},useEffect(){},useCallback:fn=>fn,useRef:value=>({current:value})};
 const viewState={useStoredViewState:()=>[{selected:state[1],initialized:true},next=>{const value=typeof next==='function'?next({selected:state[1],initialized:true}):next;state[1]=value.selected}]};
 const {default:Page}=load('components/TrendsPage.tsx',{'react':react,'../lib/viewState':viewState,'../lib/api':{fetchTrends:async()=>({trends:[],updated:1,warnings:[]}),...api},'./icons':icons,'./TrendSourcesDialog':()=>null,'./ContentPanel':load('components/ContentPanel.tsx')});
 return {state,render(props){slot=0;const panel=Page(props).props.children;return nodes(panel.type(panel.props))}};
}

test('original radar exposes source toggles, internal reading and accurate row actions',async()=>{
 const calls=[],group={platform:'s',label:'TEMP',ok:true,items:[{id:'one',title:'第一条',hot:'真实热度',url:'https://source.invalid/item/one'}]};
 const view=radar({0:[{id:'s',label:'TEMP'}],1:['s'],2:true,3:[group]}, {createIdea:async input=>calls.push(['save',input.source,input.source_id])});
 const props={onRead:id=>calls.push(['read',id]),onUseTopic:(title,id)=>calls.push(['use',title,id])};
 let tree=view.render(props),chip=tree.find(n=>n.props?.className==='chip active'),link=tree.find(n=>n.props?.className==='trend-title');
 assert.equal(chip.props['aria-pressed'],true);chip.props.onClick();assert.equal(view.state[1].length,0);
 assert.equal(link.props.href,'https://source.invalid/item/one');assert.equal(link.props.target,undefined);
 assert.equal(link.props.title,group.items[0].title);
 assert.equal(tree.find(n=>n.props?.className==='trend-save').props['aria-label'],'收藏选题：'+group.items[0].title);
 assert.equal(tree.find(n=>n.props?.className==='trend-use').props['aria-label'],'做成内容：'+group.items[0].title);
 let prevented=0;link.props.onClick({button:0,preventDefault:()=>prevented++});assert.equal(prevented,1);
 link.props.onClick({button:0,ctrlKey:true,preventDefault:()=>assert.fail('modified click must remain a browser link')});
 await tree.find(n=>n.props?.className==='trend-save').props.onClick();tree.find(n=>n.props?.className==='trend-use').props.onClick();
 assert.deepEqual(calls,[['read','one'],['save','TEMP','one'],['use','第一条','one']]);
 assert.equal(view.render(props).find(n=>n.props?.className==='trend-save').props['aria-label'],'已收藏：'+group.items[0].title);
 const external=view.render({...props,onRead:undefined}).find(n=>n.props?.className==='trend-title');assert.equal(external.props.target,'_blank');
 assert.ok(view.render(props).some(n=>n.props?.children==='请选择上方的数据源查看热点。'));
});

test('reading stored results leaves the explicit collector enabled while native defaults retain read progress',async()=>{
 let requests=0;const api={fetchTrendSources:async()=>({sources:[],warnings:[]})};
 const view=radar({2:true,4:true},api),props={onUseTopic(){},refreshAll:async()=>requests++};
 let refresh=view.render(props).find(n=>n.type==='button'&&n.props.children?.some?.(part=>part==='刷新'));
 assert.equal(refresh.props.disabled,false);refresh.props.onClick();await Promise.resolve();assert.equal(requests,1);
 refresh=view.render(props).find(n=>n.type==='button'&&n.props.children?.some?.(part=>part==='刷新中…'));
 assert.equal(refresh.props.disabled,true);
 const native=radar({2:true,4:true},api).render({onUseTopic(){}}).find(n=>n.type==='button'&&n.props.children?.some?.(part=>part==='刷新中…'));
 assert.equal(native.props.disabled,true);
});
