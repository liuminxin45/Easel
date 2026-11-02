import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';

function fixture(path='/news'){
 let index=0;const listeners=new Map(),frames=[],rows=[{state:null,url:'/native/?'+new URLSearchParams({path})}],data=new Map();
 const location={origin:'https://workbench.invalid',pathname:'/native/',search:'?'+new URLSearchParams({path})};
 const update=()=>{const u=new URL(rows[index].url,location.origin);location.pathname=u.pathname;location.search=u.search};
 const win={location,sessionStorage:{getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v)},requestAnimationFrame:fn=>{frames.push(fn);return frames.length},cancelAnimationFrame(){},addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name),history:{scrollRestoration:'auto',get state(){return rows[index].state},replaceState(state,_,url){rows[index]={state,url};update()},pushState(state,_,url){rows.splice(index+1);rows.push({state,url});index++;update()},go(delta){index=Math.max(0,Math.min(rows.length-1,index+delta));update();listeners.get('popstate')?.()},back(){this.go(-1)}}};
 const viewport={scrollTop:0,scrollLeft:0,scrollHeight:2000,clientHeight:800,getBoundingClientRect:()=>({top:0,bottom:800}),querySelectorAll:()=>[],scrollTo({top}){this.scrollTop=top}};
 const {NavigationService}=moduleLoader()('workbench/platform/navigation.ts'),navigation=new NavigationService({window:win,viewport:()=>viewport});navigation.start();
 return {win,navigation,viewport,listeners,flush(){let budget=30;while(frames.length&&budget--)frames.shift()();assert.ok(budget>=0)}};
}

test('view state isolates history entries, restores module fallback and never retains caller objects',()=>{
 const {ViewStateRepository}=moduleLoader()('workbench/platform/view-state.ts');const state=new ViewStateRepository();
 state.write('first','/news','filters',{selected:['one']});state.write('second','/news','filters',{selected:['two']});
 const original=state.read('first','/news','filters');assert.deepEqual(Array.from(original.selected),['one']);original.selected.push('bad');
 assert.deepEqual(Array.from(state.read('first','/news','filters').selected),['one']);
 assert.deepEqual(Array.from(state.read('new-module','/news','filters').selected),['two']);
 assert.equal(state.read('first','/works','other-scope'),null);
 state.clear();assert.equal(state.read('first','/news','filters'),null);
});

test('view metadata is bounded and oversized server-like objects are rejected',()=>{
 const {ViewStateRepository}=moduleLoader()('workbench/platform/view-state.ts');const state=new ViewStateRepository(2,512);
 for(let i=0;i<3;i++)state.write('entry-'+i,'/'+i,'view',{i});
 assert.equal(state.read('entry-0','/0','view'),null);
 state.write('oversized','/huge','view',{body:'x'.repeat(70000)});assert.equal(state.read('oversized','/huge','view'),null);
});

test('approved navigation metadata survives reconstruction and is cleared on auth change',()=>{
 const f=fixture();const entry=f.navigation.snapshot().key;
 f.navigation.writeViewState(entry,'trends',{selected:['source-one']});
 const {NavigationService}=moduleLoader()('workbench/platform/navigation.ts');
 const restored=new NavigationService({window:f.win,viewport:()=>f.viewport});restored.start();
 assert.deepEqual(Array.from(restored.readViewState(entry,'trends').selected),['source-one']);
 restored.clearViewState();assert.equal(restored.readViewState(entry,'trends'),null);
 assert.ok(!JSON.stringify(f.win.history.state).includes('source-one'));
});

test('default scroll owner resolves the actual page child instead of the flex host',()=>{
 const child={name:'real-page'},root={querySelector:selector=>selector.includes('.trends-page')?child:null};
 const {pageViewport}=moduleLoader({globals:{document:{querySelector:()=>root}}})('workbench/platform/navigation.ts');
 assert.equal(pageViewport('/news'),child);assert.equal(pageViewport('/works'),root);
});

test('Back preserves a reachable saved offset without a manual readiness dependency',()=>{
 const f=fixture();f.viewport.scrollTop=520;f.navigation.navigate('/works');f.viewport.scrollTop=0;f.navigation.back();
 const stop=f.navigation.committed();f.flush();assert.equal(f.viewport.scrollTop,520);stop();
});

test('a page-owned message viewport is not forced to route zero or an obsolete bottom offset',()=>{
 const f=fixture('/chat/exact');f.viewport.dataset={nativeScrollOwner:'page'};f.viewport.scrollTop=500;
 const close=f.navigation.committed();f.flush();assert.equal(f.viewport.scrollTop,500);close();
});

test('late layout waits for matching content readiness and never restores after user interaction',()=>{
 const f=fixture();f.viewport.scrollTop=520;f.navigation.navigate('/works');f.viewport.scrollTop=0;f.viewport.scrollHeight=800;f.navigation.back();
 const stop=f.navigation.committed();f.flush();assert.equal(f.viewport.scrollTop,0);
 f.navigation.contentReady({entryId:'stale-entry'});f.flush();assert.equal(f.viewport.scrollTop,0);
 f.viewport.scrollHeight=2000;f.navigation.contentReady({entryId:f.navigation.snapshot().key});f.flush();assert.equal(f.viewport.scrollTop,520);stop();
 f.viewport.scrollTop=400;f.navigation.navigate('/works');f.viewport.scrollTop=0;f.viewport.scrollHeight=800;f.navigation.back();
 const close=f.navigation.committed();f.flush();f.listeners.get('touchstart')();f.viewport.scrollHeight=2000;f.navigation.contentReady();f.flush();assert.equal(f.viewport.scrollTop,0);close();
});

test('unsaved settings veto browser Back and route switches once, but not section replacement',()=>{
 const f=fixture('/toolbox');f.navigation.navigate('/settings');let attempts=0,accepted=false;
 const release=f.navigation.registerLeaveGuard(()=>{attempts++;return accepted});
 f.navigation.replace('/settings?panel=env');assert.equal(attempts,0);
 f.navigation.back();assert.equal(f.navigation.snapshot().path,'/settings?panel=env');assert.equal(attempts,1);
 f.navigation.navigate('/works');assert.equal(f.navigation.snapshot().path,'/settings?panel=env');assert.equal(attempts,2);
 accepted=true;f.navigation.back();assert.equal(f.navigation.snapshot().path,'/toolbox');assert.equal(attempts,3);release();
});

test('shared toolbox pathname never bypasses guards for another module or selected object',()=>{
 const f=fixture('/toolbox?section=profiles&item=first');let checks=0;
 f.navigation.registerLeaveGuard(()=>{checks++;return false});
 f.navigation.navigate('/toolbox?section=calendar');assert.equal(f.navigation.snapshot().path,'/toolbox?section=profiles&item=first');
 f.navigation.navigate('/toolbox?section=profiles&item=second');assert.equal(f.navigation.snapshot().path,'/toolbox?section=profiles&item=first');
 assert.equal(checks,2);
});

test('long navigation is bounded in memory and old browser entries retain their own metadata',()=>{
 const f=fixture('/news');const first=f.navigation.snapshot().key;f.navigation.writeViewState(first,'trends',{selected:['original']});f.viewport.scrollTop=310;
 for(let i=0;i<180;i++){f.navigation.navigate('/works?path='+i);f.navigation.writeViewState(f.navigation.snapshot().key,'view',{filter:'image'})}
 assert.ok(f.navigation.entries.size<=96);assert.ok(f.navigation.positions.size<=128);
 f.win.history.go(-180);assert.equal(f.navigation.snapshot().key,first);
 assert.deepEqual(Array.from(f.navigation.readViewState(first,'trends').selected),['original']);
 f.viewport.scrollTop=0;const stop=f.navigation.committed();f.flush();assert.equal(f.viewport.scrollTop,310);stop();
});

test('separate entries at the same URL restore their own offset instead of the last path offset',()=>{
 const f=fixture('/news');f.viewport.scrollTop=310;f.navigation.navigate('/works');f.navigation.navigate('/news');f.viewport.scrollTop=720;f.navigation.navigate('/works?again=1');
 f.win.history.go(-3);f.viewport.scrollTop=0;const stop=f.navigation.committed();f.flush();assert.equal(f.viewport.scrollTop,310);stop();
});
