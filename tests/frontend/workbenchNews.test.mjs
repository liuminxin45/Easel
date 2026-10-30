import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const root=new URL('../../web/frontend/src/',import.meta.url),jsx={jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})};
function load(file,imports={}){const exports={};runInNewContext(ts.transpileModule(readFileSync(new URL(file,root),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,{exports,URL,URLSearchParams,Date,Set,require:id=>id==='react/jsx-runtime'?jsx:imports[id]??(id==='./InteractionNotice'?{InteractionNotice:()=>null}:assert.fail(id))});return exports}
const context=load('workbench/platform/news-context.ts'),navigation=load('workbench/platform/navigation.ts',{'./news-context':context});
const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
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
test('shared radar exposes independent source toggles, internal reading and row actions',()=>{
 const icons=Object.fromEntries(['IconFire','IconRefresh','IconBookmark','IconCheck'].map(key=>[key,()=>null]));
 const view=load('components/TrendsView.tsx',{'./icons':icons}),calls=[];
 const group={platform:'s',label:'TEMP',ok:true,items:[{id:'one',title:'第一条',hot:'真实热度'}]};
 const props={sources:[{id:'s',label:'TEMP'}],selected:['s'],groups:[group],ready:true,loading:false,saved:new Set(),onToggle:id=>calls.push(['toggle',id]),onManage:()=>{},onRefresh:()=>calls.push(['refresh']),onSave:(g,it)=>calls.push(['save',g.platform,it.id]),onUse:(g,it)=>calls.push(['use',g.platform,it.id]),onRead:(g,it)=>calls.push(['read',g.platform,it.id]),itemHref:()=>'/native/?path=exact'};
 const tree=nodes(view.default(props)),chip=tree.find(n=>n.props?.className==='chip active'),link=tree.find(n=>n.props?.className==='trend-title');
 assert.equal(chip.props['aria-pressed'],true);chip.props.onClick();
 assert.equal(link.props.href,'/native/?path=exact');assert.equal(link.props.target,undefined);
 let prevented=0;link.props.onClick({button:0,preventDefault:()=>prevented++});assert.equal(prevented,1);
 link.props.onClick({button:0,ctrlKey:true,preventDefault:()=>assert.fail('modified click must remain a browser link')});
 tree.find(n=>n.props?.className==='trend-save').props.onClick();tree.find(n=>n.props?.className==='trend-use').props.onClick();
 assert.deepEqual(calls,[['toggle','s'],['read','s','one'],['save','s','one'],['use','s','one']]);
 const external=nodes(view.default({...props,onRead:undefined,itemHref:undefined})).find(n=>n.props?.className==='trend-title');assert.equal(external.props.target,'_blank');
 assert.ok(nodes(view.default({...props,selected:[],groups:[]})).some(n=>n.props?.children==='请选择上方的数据源查看热点。'));
});

test('reading stored results leaves the manual collector enabled',()=>{
 const icons=Object.fromEntries(['IconFire','IconRefresh','IconBookmark','IconCheck'].map(key=>[key,()=>null]));
 const view=load('components/TrendsView.tsx',{'./icons':icons});let requests=0;
 const base={sources:[],selected:[],groups:[],ready:true,loading:true,refreshing:false,saved:new Set(),onToggle:()=>{},onManage:()=>{},onSave:()=>{},onUse:()=>{},onRefresh:()=>requests++};
 const refresh=nodes(view.default(base)).find(n=>n.type==='button'&&n.props.onClick===base.onRefresh);
 assert.equal(refresh.props.disabled,false);refresh.props.onClick();assert.equal(requests,1);
 assert.equal(nodes(view.default({...base,loading:false,refreshing:true})).find(n=>n.type==='button'&&n.props.onClick===base.onRefresh).props.disabled,true);
});
