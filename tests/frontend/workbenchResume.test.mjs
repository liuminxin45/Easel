import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const compile=name=>ts.transpileModule(readFileSync(new URL('../../web/frontend/src/workbench/platform/'+name,import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
const activitySource=compile('activities.ts'),resumeSource=compile('native-resume.ts');
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no});return {promise,resolve,reject}};
function fixture(){
 let now=0,seq=0;const timers=new Map(),requests=[],preparations=[],properties=new Map();let reloads=0;
 const later=(callback,ms,interval=0)=>{const id=++seq;timers.set(id,{callback,at:now+ms,interval});return id};
 const clear=id=>timers.delete(id);
 const events=()=>{const listeners=new Map();return {listeners,addEventListener:(name,fn)=>{if(!listeners.has(name))listeners.set(name,new Set());listeners.get(name).add(fn)},removeEventListener:(name,fn)=>listeners.get(name)?.delete(fn),emit:(name,event={})=>{for(const fn of [...listeners.get(name)||[]])fn(event)}}};
 class Node {constructor(){this.children=[]}contains(node){return this.children.includes(node)}}
 const owner=new Node(),other=new Node(),document={...events(),hidden:false,activeElement:owner,documentElement:{style:{getPropertyValue:key=>properties.get(key)||'',setProperty:(key,value)=>properties.set(key,value)}}};
 const viewport={...events(),height:600,offsetTop:0,scale:1},window={...events(),visualViewport:viewport};
 const response=()=>({ok:true,json:async()=>({release:'new'})});
 const state={fetch:async()=>response(),prepare:async()=>true};
 const globals={window,document,Node,innerHeight:800,Date:{now:()=>now},AbortSignal:{timeout:ms=>({timeout:ms})},location:{reload:()=>{reloads++}},setTimeout:(fn,ms=0)=>later(fn,ms),clearTimeout:clear,setInterval:(fn,ms)=>later(fn,ms,ms),clearInterval:clear};
 const activitiesExports={};runInNewContext(activitySource,{...globals,exports:activitiesExports});
 const exports={};runInNewContext(resumeSource,{...globals,exports,require:name=>{assert.equal(name,'./native-worker');return {prepareNativeWorker:async(...args)=>{preparations.push(args);return state.prepare(...args)}}},fetch:async(...args)=>{requests.push(args);return state.fetch(...args)}});
 const flush=async()=>{for(let i=0;i<15;i++)await Promise.resolve()};
 const advance=async(ms=0)=>{const until=now+ms;await flush();for(let guard=0;guard<200;guard++){const next=[...timers.entries()].filter(([,v])=>v.at<=until).sort((a,b)=>a[1].at-b[1].at)[0];if(!next)break;const [id,timer]=next;now=timer.at;if(timer.interval)timer.at+=timer.interval;else timers.delete(id);timer.callback();await flush()}now=until;await flush()};
 const activities=new activitiesExports.ActivityCoordinator();
 return {...activitiesExports,...exports,activities,state,window,document,owner,other,requests,preparations,advance,properties,timers,reloads:()=>reloads,response};
}

test('foreground visibility/pageshow events coalesce and reload an available release only once',async()=>{
 const f=fixture(),stop=f.bindNativeUpgradeChecks({activities:f.activities,release:'old'});
 f.document.hidden=true;f.document.emit('visibilitychange');f.window.emit('pageshow');await f.advance();assert.equal(f.requests.length,0);
 f.document.hidden=false;f.document.emit('visibilitychange');f.window.emit('pageshow');f.window.emit('focus');await f.advance();
 assert.equal(f.requests.length,1);assert.equal(f.reloads(),1);
 f.window.emit('online');await f.advance(60000);assert.equal(f.requests.length,1);stop();assert.equal(f.timers.size,0);
});

test('write/save/composition completion waits for every lock and the following input/save task',async()=>{
 const f=fixture(),stop=f.bindNativeUpgradeChecks({activities:f.activities,release:'old'}),write=f.activities.begin('write'),save=f.activities.begin('save'),composition=f.activities.begin('composition');
 f.window.emit('pageshow');await f.advance();write();save();await f.advance();assert.equal(f.requests.length,0);
 composition();const nextSave=f.activities.begin('save');await f.advance();assert.equal(f.requests.length,0);
 nextSave();await f.advance();assert.equal(f.requests.length,1);assert.equal(f.reloads(),1);stop();
});

test('a new protected write during version fetch prevents reload and its completion safely retries',async()=>{
 const f=fixture(),pending=deferred();f.state.fetch=()=>pending.promise;
 const stop=f.bindNativeUpgradeChecks({activities:f.activities,release:'old'});
 f.window.emit('focus');await f.advance();assert.equal(f.requests.length,1);
 const finish=f.activities.begin('write');pending.resolve(f.response());await f.advance();assert.equal(f.reloads(),0);
 f.state.fetch=async()=>f.response();finish();await f.advance();assert.equal(f.requests.length,2);assert.equal(f.reloads(),1);stop();
});

test('foreground loss while preparing a worker never reloads the hidden page',async()=>{
 const f=fixture(),pending=deferred();f.state.prepare=()=>pending.promise;
 const stop=f.bindNativeUpgradeChecks({activities:f.activities,release:'old',registration:Promise.resolve({})});
 f.window.emit('pageshow');await f.advance();assert.equal(f.preparations.length,1);
 f.document.hidden=true;pending.resolve(true);await f.advance();assert.equal(f.reloads(),0);
 f.document.hidden=false;f.state.prepare=async()=>true;f.document.emit('visibilitychange');await f.advance();assert.equal(f.reloads(),1);stop();
});

test('a stuck register promise is bounded and later resume attempts remain usable',async()=>{
 const f=fixture(),pending=deferred(),stop=f.bindNativeUpgradeChecks({activities:f.activities,release:'old',registration:pending.promise});
 f.window.emit('pageshow');await f.advance(12001);assert.equal(f.requests.length,1);assert.equal(f.reloads(),0);
 pending.resolve({});f.window.emit('pageshow');await f.advance();assert.equal(f.requests.length,2);assert.equal(f.reloads(),1);stop();
});

test('read activities and blocked persistence never request an unsafe reload; network failures stay silent',async()=>{
 const f=fixture();let blocked=true;const stop=f.bindNativeUpgradeChecks({activities:f.activities,release:'old',blocked:()=>blocked});
 const read=f.activities.begin('read');read();await f.advance();assert.equal(f.requests.length,0);
 f.window.emit('online');await f.advance();assert.equal(f.requests.length,0);
 blocked=false;f.state.fetch=async()=>{throw Error('offline')};f.window.emit('pageshow');await f.advance();assert.equal(f.reloads(),0);
 f.state.fetch=async()=>({ok:false});f.window.emit('focus');await f.advance();assert.equal(f.reloads(),0);
 f.state.fetch=async()=>({ok:true,json:async()=>({release:'old'})});f.window.emit('focus');await f.advance();assert.equal(f.reloads(),0);
 stop();f.window.emit('pageshow');await f.advance(60000);assert.equal(f.requests.length,3);
});

test('unmount cancels pending foreground work and a late prepared worker cannot reload',async()=>{
 const f=fixture(),pending=deferred();f.state.prepare=()=>pending.promise;
 const stop=f.bindNativeUpgradeChecks({activities:f.activities,release:'old',registration:Promise.resolve({})});
 f.window.emit('focus');await f.advance();stop();pending.resolve(true);await f.advance();assert.equal(f.reloads(),0);assert.equal(f.timers.size,0);
 for(const surface of [f.window,f.document])assert.ok([...surface.listeners.values()].every(set=>set.size===0));
});

test('IME cancellation releases a missing compositionend only after focus really leaves its owner',async()=>{
 const f=fixture(),stop=f.bindViewport(f.activities);
 f.document.emit('compositionstart',{target:f.owner});assert.equal(f.activities.canUpgrade,false);
 f.document.hidden=true;f.window.emit('blur');f.document.emit('visibilitychange');f.document.emit('focusout',{target:f.owner});await f.advance();assert.equal(f.activities.canUpgrade,false);
 f.document.activeElement=f.other;f.document.emit('focusout',{target:f.owner});assert.equal(f.activities.canUpgrade,false);await f.advance();assert.equal(f.activities.canUpgrade,true);
 stop();assert.equal(f.timers.size,0);
});

test('compositionend and rapid refocus retain an active IME lock and clean up canceled checks',async()=>{
 const f=fixture(),stop=f.bindViewport(f.activities);
 f.document.emit('compositionstart',{target:f.owner});f.document.activeElement=f.other;f.document.emit('focusout',{target:f.owner});f.document.activeElement=f.owner;await f.advance();assert.equal(f.activities.canUpgrade,false);
 f.document.emit('compositionend',{target:f.owner});assert.equal(f.activities.canUpgrade,true);
 f.document.emit('compositionstart',{target:f.owner});f.document.activeElement=f.other;f.document.emit('focusout',{target:f.owner});stop();assert.equal(f.activities.canUpgrade,true);assert.equal(f.timers.size,0);
 for(const surface of [f.window,f.document,f.window.visualViewport])assert.ok([...surface.listeners.values()].every(set=>set.size===0));
});

test('viewport updates ignore pinch zoom, avoid duplicate style writes and retain layout-resize behavior',()=>{
 const f=fixture();assert.equal(JSON.stringify(f.viewportInsets(500,{height:500,offsetTop:0,scale:1})),JSON.stringify({height:500,bottom:0}));
 assert.equal(JSON.stringify(f.viewportInsets(800,{height:400,offsetTop:20,scale:2})),JSON.stringify({height:800,bottom:0}));
 const stop=f.bindViewport(f.activities);assert.equal(f.properties.get('--native-height'),'600px');assert.equal(f.properties.get('--native-keyboard-inset'),'200px');stop();
});
