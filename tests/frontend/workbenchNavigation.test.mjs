import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript'),exports={};
let counter=0;
runInNewContext(ts.transpileModule(readFileSync(new URL('../../web/frontend/src/workbench/platform/navigation.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,{exports,URL,URLSearchParams,crypto:{randomUUID:()=> 'navigation-'+(++counter)},require:id=>id==='./news-context'?{navigationIdentity:path=>path}:assert.fail(id)});
const {safePath,parentPath,NavigationService}=exports;
test('native chat accepts only its root or a stable session ID, including protected shell handoff',()=>{
 assert.equal(safePath('/chat'),'/chat');assert.equal(safePath('/chat/session_1-abc?work=w&version=v'),'/chat/session_1-abc?work=w&version=v');
 assert.equal(safePath('/native/?path=%2Fchat%2Fsession_1-abc'),'/chat/session_1-abc');
 for(const path of ['/chat/a/b','/chat/%2f','/chat/a%5cb','/chat/'+('x'.repeat(201)),'//foreign.invalid/chat/a','/chat/a#unsafe'])assert.equal(safePath(path),null,path);
 assert.equal(parentPath('/chat/exact-session?work=w&version=v'),'/chat');
});
function windowFor(path,{asyncHistory=false}={}){
 const storage=new Map(),listeners=new Map(),stack=[{state:null,url:'/native/?'+new URLSearchParams({path})}],pops=[];let index=0;
 const location={origin:'https://workbench.invalid',pathname:'/native/',search:'?'+new URLSearchParams({path})};
 const update=()=>{const url=new URL(stack[index].url,location.origin);location.pathname=url.pathname;location.search=url.search};
 const history={scrollRestoration:'auto',get state(){return stack[index].state},replaceState:(state,_,url)=>{stack[index]={state,url};update()},pushState:(state,_,url)=>{stack.splice(index+1);stack.push({state,url});index++;update()},go:delta=>{const apply=()=>{index=Math.max(0,Math.min(stack.length-1,index+delta));update();listeners.get('popstate')?.()};if(asyncHistory)pops.push(apply);else apply()},back:()=>history.go(-1)};
 return {location,history,flushHistory:()=>{let limit=20;while(pops.length){assert.ok(limit--,'history traversal must settle');pops.shift()()}},sessionStorage:{getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:()=>{}};
}
test('server-created native session replaces its start flow and returns to the actual news source',()=>{
 const win=windowFor('/news/a/source-item?source=s&day=2026-10-30'),nav=new NavigationService({window:win,viewport:()=>null});nav.start();
 nav.navigate('/chat?fresh=1',{intent:'flow'});const ticket=nav.ticket();assert.equal(nav.finishFlow('/chat/server-session',ticket),true);assert.equal(nav.snapshot().path,'/chat/server-session');
 nav.back();assert.equal(nav.snapshot().path,'/news/a/source-item?source=s&day=2026-10-30');
});
test('a late session response cannot take over after the user leaves the chat flow',()=>{
 const win=windowFor('/toolbox'),nav=new NavigationService({window:win,viewport:()=>null});nav.start();nav.navigate('/chat?fresh=1',{intent:'flow'});const ticket=nav.ticket();nav.navigate('/works',{intent:'module'});
 assert.equal(nav.finishFlow('/chat/late-session',ticket),false);assert.equal(nav.snapshot().path,'/works');
});

for(const close of ['button','back'])test('same-page acknowledgement retains its layer and filters after '+close,()=>{
 const win=windowFor('/toolbox'),nav=new NavigationService({window:win,viewport:()=>null});nav.start();nav.navigate('/news?sources=one');let dismissed=0;
 let release;release=nav.registerLayer(()=>{dismissed++;release()});
 nav.replace('/news?sources=one,two',{preserveScroll:true,preserveLayers:true});
 assert.equal(dismissed,0);assert.equal(nav.snapshot().path,'/news?sources=one,two');assert.ok(win.history.state.nativeLayer);
 if(close==='button')release();else nav.back();
 assert.equal(nav.snapshot().path,'/news?sources=one,two');assert.equal(new URLSearchParams(win.location.search).get('path'),'/news?sources=one,two');assert.equal(win.history.state.nativeLayer,undefined);
 nav.back();assert.equal(nav.snapshot().path,'/toolbox');
});

test('preserveLayers never bypasses dismissal when navigating to another page',()=>{
 const win=windowFor('/news'),nav=new NavigationService({window:win,viewport:()=>null});nav.start();let dismissed=0;
 let release;release=nav.registerLayer(()=>{dismissed++;release()});
 nav.replace('/settings',{preserveLayers:true});assert.equal(dismissed,1);assert.equal(nav.snapshot().path,'/settings');
});

test('navigation preserves independent card offsets without persisting card contents',()=>{
 const win=windowFor('/news?sources=one'),region={dataset:{nativeScrollRegion:'news:one'},scrollTop:840,scrollLeft:0};
 const viewport={scrollTop:180,scrollLeft:0,getBoundingClientRect:()=>({top:0,bottom:900}),querySelectorAll:selector=>selector==='[data-native-scroll-region]'?[region]:[]};
 const nav=new NavigationService({window:win,viewport:()=>viewport});nav.start();nav.navigate('/news/a/exact?source=one');
 const position=win.history.state.nativeNavigation.returnTo.position;
 assert.equal(position.regions['news:one'].top,840);assert.equal(position.top,180);
 region.scrollTop=0;nav.back();assert.equal(win.history.state.nativeNavigation.position.regions['news:one'].top,840);
 assert.ok(!JSON.stringify(position).includes('body'));
});

for(const path of ['/settings','/settings?panel=model','/settings?panel=env','/settings?panel=more'])test('fresh settings closes in one action: '+path,()=>{
 const win=windowFor(path),nav=new NavigationService({window:win,viewport:()=>null});nav.start();nav.back();
 assert.equal(nav.snapshot().path,'/toolbox');
});

test('settings tab replacements retain the real chat caller and its news return anchor',()=>{
 const source='/news/a/source-item?source=s&day=2026-10-30',win=windowFor(source);
 const viewport={scrollTop:415,scrollLeft:0,getBoundingClientRect:()=>({top:0,bottom:900}),querySelectorAll:()=>[]};
 const nav=new NavigationService({window:win,viewport:()=>viewport});nav.start();
 nav.navigate('/chat/exact-session',{intent:'object'});viewport.scrollTop=165;
 nav.navigate('/settings');nav.replace('/settings?panel=more',{preserveScroll:true});nav.back();
 assert.equal(nav.snapshot().path,'/chat/exact-session');
 assert.equal(win.history.state.nativeNavigation.position.top,165);
 assert.equal(win.history.state.nativeNavigation.returnTo.path,source);
 assert.equal(win.history.state.nativeNavigation.returnTo.position.top,415);
 nav.back();assert.equal(nav.snapshot().path,source);
});

for(const target of ['/toolbox?section=skills','/works'])test('accepted modal navigation detaches before a reentrant close, preserving '+target,()=>{
 const win=windowFor('/toolbox?section=skills&pane=experience'),nav=new NavigationService({window:win,viewport:()=>null});nav.start();let dismissed=0;
 const release=nav.registerLayer(()=>{dismissed++;nav.replace('/toolbox?section=skills')});
 nav.replace(target);
 assert.equal(dismissed,1);assert.equal(nav.snapshot().path,target);assert.equal(win.history.state.nativeLayer,undefined);
 const entry=nav.snapshot().key;release();release();
 assert.equal(nav.snapshot().key,entry,'late React cleanup is idempotent');assert.equal(nav.snapshot().path,target);
 nav.navigate('/account');assert.equal(dismissed,1,'accepted layer cannot trap later navigation');
});

test('browser Back accepts a modal cleanup route without recursively dismissing its layer',()=>{
 const win=windowFor('/toolbox'),nav=new NavigationService({window:win,viewport:()=>null});nav.start();
 nav.navigate('/toolbox?section=skills&pane=experience');let dismissed=0;
 const release=nav.registerLayer(()=>{dismissed++;nav.replace('/toolbox?section=skills')});
 nav.back();assert.equal(dismissed,1);assert.equal(nav.snapshot().path,'/toolbox?section=skills');assert.equal(win.history.state.nativeLayer,undefined);
 release();nav.back();assert.equal(nav.snapshot().path,'/toolbox');
});

test('browser Back cleanup navigation also dismisses an underlying layer before committing',()=>{
 const win=windowFor('/toolbox'),nav=new NavigationService({window:win,viewport:()=>null});nav.start();nav.navigate('/toolbox?section=skills&pane=experience');const calls=[];
 nav.registerLayer(()=>{calls.push('lower')});nav.registerLayer(()=>{calls.push('upper');nav.replace('/toolbox?section=skills')});
 nav.back();assert.deepEqual(calls,['upper','lower']);assert.equal(nav.snapshot().path,'/toolbox?section=skills');assert.equal(win.history.state.nativeLayer,undefined);
 nav.back();assert.equal(nav.snapshot().path,'/toolbox');
});

test('dirty modal veto rejects the outer route and nested cleanup navigation until accepted',()=>{
 const path='/toolbox?section=skills&pane=experience',win=windowFor(path),nav=new NavigationService({window:win,viewport:()=>null});nav.start();let accepted=false,dismissed=0;
 nav.registerLayer(()=>{dismissed++;nav.replace('/toolbox?section=skills');return accepted});
 nav.navigate('/works');assert.equal(nav.snapshot().path,path);assert.ok(win.history.state.nativeLayer);
 nav.back();assert.equal(nav.snapshot().path,path);assert.ok(win.history.state.nativeLayer);
 accepted=true;nav.navigate('/works');assert.equal(nav.snapshot().path,'/works');assert.equal(win.history.state.nativeLayer,undefined);assert.equal(dismissed,3);
});

test('stacked layers dismiss once, retire accepted upper layers and retain a lower veto',()=>{
 const path='/toolbox?section=skills&pane=experience',win=windowFor(path),nav=new NavigationService({window:win,viewport:()=>null});nav.start();let accepted=false;const calls=[];
 const lower=nav.registerLayer(()=>{calls.push('lower');nav.replace('/toolbox?section=skills');return accepted});
 const upper=nav.registerLayer(()=>{calls.push('upper');nav.replace('/account')});
 nav.navigate('/works');assert.equal(nav.snapshot().path,path);assert.deepEqual(calls,['upper','lower']);assert.ok(win.history.state.nativeLayer);
 upper();accepted=true;nav.navigate('/works');assert.equal(nav.snapshot().path,'/works');assert.deepEqual(calls,['upper','lower','lower']);assert.equal(win.history.state.nativeLayer,undefined);
 lower();upper();nav.navigate('/account');assert.equal(nav.snapshot().path,'/account');
});

test('a thrown dismissal releases the transaction guard and keeps the layer for a later retry',()=>{
 const path='/toolbox?section=skills&pane=experience',win=windowFor(path),nav=new NavigationService({window:win,viewport:()=>null});nav.start();let fail=true;
 nav.registerLayer(()=>{nav.replace('/toolbox?section=skills');if(fail)throw Error('TEMP dirty check failed')});
 assert.throws(()=>nav.navigate('/works'),/TEMP dirty check failed/);assert.equal(nav.snapshot().path,path);assert.ok(win.history.state.nativeLayer);
 fail=false;nav.navigate('/works');assert.equal(nav.snapshot().path,'/works');assert.equal(win.history.state.nativeLayer,undefined);
});

test('asynchronous history retires stacked modal entries before committing the original route',()=>{
 const path='/toolbox?section=skills&pane=experience',win=windowFor(path,{asyncHistory:true}),nav=new NavigationService({window:win,viewport:()=>null});nav.start();const calls=[];
 const lower=nav.registerLayer(()=>{calls.push('lower');nav.replace('/toolbox?section=skills')});
 const upper=nav.registerLayer(()=>{calls.push('upper');nav.replace('/account')});
 nav.navigate('/works');assert.equal(nav.snapshot().path,path,'route waits for browser history traversal');
 lower();upper();win.flushHistory();assert.deepEqual(calls,['upper','lower']);assert.equal(nav.snapshot().path,'/works');assert.equal(win.history.state.nativeLayer,undefined);
 nav.back();win.flushHistory();assert.equal(nav.snapshot().path,path);
});

test('asynchronous Back preserves a dirty veto then accepts a later modal cleanup route',()=>{
 const path='/toolbox?section=skills&pane=experience',win=windowFor(path,{asyncHistory:true}),nav=new NavigationService({window:win,viewport:()=>null});nav.start();let accepted=false;
 nav.registerLayer(()=>{nav.replace('/toolbox?section=skills');return accepted});
 nav.back();win.flushHistory();assert.equal(nav.snapshot().path,path);assert.ok(win.history.state.nativeLayer);
 accepted=true;nav.back();win.flushHistory();assert.equal(nav.snapshot().path,'/toolbox?section=skills');assert.equal(win.history.state.nativeLayer,undefined);
});
