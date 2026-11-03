import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function clocks(){const timers=[];return {timers,globals:{setTimeout:(callback,ms)=>{const timer={callback,ms,cleared:false,unref(){}};timers.push(timer);return timer},clearTimeout:timer=>{if(timer)timer.cleared=true}}};}
function aborting(_path,options){return new Promise((resolve,reject)=>{options.signal.addEventListener('abort',()=>{const error=new Error('aborted');error.name='AbortError';reject(error)},{once:true})})}

test('null request deadline leaves external cancellation active and does not schedule a browser timeout',async()=>{
 const clock=clocks(),load=moduleLoader({globals:clock.globals}),{ApiTransport}=load('workbench/core/transport.ts');let calls=0;
 const transport=new ApiTransport({fetcher:(...args)=>{calls++;return aborting(...args)}}),controller=new AbortController();
 const pending=transport.request('/api/skill',{body:{skill:'ordinary'},csrf:'owner',requestTimeout:null,signal:controller.signal});
 assert.equal(clock.timers.length,0);assert.equal(calls,1);controller.abort();await assert.rejects(pending,error=>error.cancelled===true&&error.timedOut===false&&error.uncertain===true);assert.equal(calls,1);
});

test('ordinary writes retain their thirty-second deadline and never retry after an expired write',async()=>{
 const clock=clocks(),load=moduleLoader({globals:clock.globals}),{ApiTransport}=load('workbench/core/transport.ts');let calls=0;
 const transport=new ApiTransport({fetcher:(...args)=>{calls++;return aborting(...args)}}),pending=transport.request('/api/ideas',{body:{title:'Keep standard deadline'},csrf:'owner'});
 assert.equal(clock.timers.length,1);assert.equal(clock.timers[0].ms,30000);clock.timers[0].callback();await assert.rejects(pending,error=>error.timedOut===true&&error.uncertain===true);assert.equal(calls,1);assert.equal(clock.timers[0].cleared,true);
});

test('the native binding disables only skill/chat POST deadlines without persisting transient options',async()=>{
 for(const path of ['/api/skill','/api/chat','/api/ideas']){
  const clock=clocks(),storage=new Map(),calls=[];let finish;
  const load=moduleLoader({globals:{...clock.globals,FormData,Event,window:{location:{pathname:'/native/'},dispatchEvent(){}}}}),{WorkbenchClient}=load('workbench/core/client.ts');
  const client=new WorkbenchClient({storage:{get length(){return storage.size},key:n=>[...storage.keys()][n],getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},fetcher:(target,options)=>{calls.push({target,options});return new Promise(resolve=>{finish=resolve})}});
  client.session.setState({config:{csrf:'owner-csrf'},loading:false});const release=load('workbench/ui/nativeApi.ts').bindWorkbenchNativeApi(client),api=load('lib/api.ts');
  try{
   const pending=path==='/api/skill'?api.executeSkill('content-production','Exact input','author'):path==='/api/chat'?api.runAgent('Exact message','author'):api.createIdea({title:'Ordinary write'});
   while(!finish)await tick();assert.equal(calls.length,1);assert.equal(calls[0].target,path);assert.equal(calls[0].options.headers['X-CSRF-Token'],'owner-csrf');assert.ok(calls[0].options.headers['X-Operation-Id']);
   assert.equal(clock.timers.filter(timer=>timer.ms===30000&&!timer.cleared).length,path==='/api/ideas'?1:0);
   assert.ok([...storage.values()].every(value=>!value.includes('requestTimeout')));assert.ok(!calls[0].options.body.includes('requestTimeout'));
   finish(new Response(JSON.stringify({response:'Actual acknowledged result',id:'idea'})));await pending;
  }finally{release();client.pauseVisible()}
 }
});

test('a lost long native response preserves one metadata identity and only reads its receipt',async()=>{
 const clock=clocks(),storage=new Map(),calls=[];
 const load=moduleLoader({globals:{...clock.globals,FormData,Event,window:{location:{pathname:'/native/'},dispatchEvent(){}}}}),{WorkbenchClient}=load('workbench/core/client.ts');
 const client=new WorkbenchClient({storage:{get length(){return storage.size},key:n=>[...storage.keys()][n],getItem:k=>storage.get(k)||null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},fetcher:async(path,options)=>{calls.push({path,method:options.method||'GET'});if(options.method==='POST')throw new TypeError('lost response');return new Response(JSON.stringify({state:'unavailable'}))}});
 client.session.setState({config:{csrf:'owner'},loading:false});client.pauseVisible();const release=load('workbench/ui/nativeApi.ts').bindWorkbenchNativeApi(client),api=load('lib/api.ts');
 try{
  await assert.rejects(api.executeSkill('content-production','Private input','author'),error=>error.uncertain===true);
  const scope='easel-native:POST:/api/skill',original=client.operation(scope).getState().pending;assert.ok(original?.id);assert.equal(original.metadataOnly,true);assert.deepEqual(Object.keys(original.body),[]);
  assert.ok([...storage.values()].every(value=>!value.includes('Private input')&&!value.includes('requestTimeout')));
  await client.reconcile(scope);assert.equal(client.operation(scope).getState().pending.id,original.id);assert.equal(calls.filter(call=>call.method==='POST').length,1);assert.ok(calls.some(call=>call.method==='GET'&&call.path.startsWith('/api/native/operations/')));
 }finally{release();client.pauseVisible()}
});
