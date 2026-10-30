import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const source=readFileSync(new URL('../../web/frontend/src/workbench/platform/native-worker.ts',import.meta.url),'utf8');
function setup(controller){
 const exports={},serviceWorker={controller};
 class Channel {constructor(){this.port1={close(){},onmessage:null};this.port2={close(){},postMessage:value=>setImmediate(()=>this.port1.onmessage?.({data:value}))}}}
 runInNewContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,{exports,MessageChannel:Channel,navigator:{serviceWorker},Date,setTimeout:(fn,ms)=>setTimeout(fn,Math.min(ms,10)),clearTimeout});
 return {...exports,serviceWorker};
}
const worker=value=>({postMessage:(message,ports)=>{assert.equal(message.type,'NATIVE_VERSION');ports[0].postMessage(value)}});
test('worker readiness uses the controlling release and an actually cached shell',async()=>{
 const f=setup(worker({release:'old',shell_ready:true}));let updates=0;const ready=f.prepareNativeWorker({update:async()=>{updates++;setTimeout(()=>{f.serviceWorker.controller=worker({release:'new',shell_ready:true})},5)}},'new',200);
 assert.equal(await ready,true);assert.equal(updates,1);
 const wrong=setup(worker({release:'new',shell_ready:false}));assert.equal(await wrong.prepareNativeWorker({update:async()=>{}},'new',40),false);
});
test('an unavailable legacy handshake does not claim that offline upgrade is ready',async()=>{
 const f=setup({postMessage:()=>{}});assert.equal(await f.nativeWorkerVersion(f.serviceWorker.controller,10),null);
 const valid=setup(worker({release:'new',shell_ready:true}));assert.equal(await valid.prepareNativeWorker({update:async()=>{throw Error('offline')}},'new',100),true);
});

const template=readFileSync(new URL('../../easel_workbench/assets/native-sw-template.js',import.meta.url),'utf8');
const origin='https://workbench.test',release='current-release';
const shell=version=>'<html><meta name="native-release" content="'+version+'"><body>'+version+'</body></html>';

// Execute the shipped worker, with CacheStorage returning cloned Responses as a browser does.
function installedWorker(entries={},network=async()=>{throw Error('offline')}){
 const stores=new Map(Object.entries(entries).map(([name,values])=>[name,new Map(Object.entries(values).map(([path,body])=>[new URL(path,origin).href,new Response(body)]))]));
 const listeners={},deleted=[],requests=[],opened=[];
 const key=request=>new URL(typeof request==='string'?request:request.url,origin).href;
 const caches={
  keys:async()=>[...stores.keys()],
  delete:async name=>{deleted.push(name);return stores.delete(name)},
  open:async name=>{
   opened.push(name);if(!stores.has(name))stores.set(name,new Map());const values=stores.get(name);
   return {
    match:async request=>values.get(key(request))?.clone(),
    put:async(request,response)=>{values.set(key(request),response.clone())},
    addAll:async paths=>{for(const path of paths){const response=await fetch(path);if(!response.ok)throw Error('asset unavailable');values.set(key(path),response.clone())}},
   };
  },
 };
 const fetch=async(request,options)=>{requests.push({request,options});return network(request,options)};
 let claimed=0;
 const self={location:{origin},clients:{claim:async()=>{claimed++}},skipWaiting:async()=>{},addEventListener:(type,listener)=>{listeners[type]=listener}};
 const variables={VERSION:release,CACHE:'native-static-'+release,SHELL:'native-shell-'+release,ASSETS:['/native-assets/'+release+'/app.js']};
 runInNewContext('const {VERSION,CACHE,SHELL,ASSETS}=workerConfig;\n'+template,{workerConfig:variables,self,caches,fetch,URL,Response,AbortSignal});
 async function dispatch(type,extra={}){
  const pending=[];let response;
  listeners[type]({...extra,waitUntil:promise=>pending.push(Promise.resolve(promise)),respondWith:promise=>{assert.equal(response,undefined);response=Promise.resolve(promise)}});
  const handled=response!==undefined,result=await response;await Promise.all(pending);
  return {handled,response:result};
 }
 return {stores,deleted,requests,opened,claimed:()=>claimed,dispatch,navigate:()=>dispatch('fetch',{request:{url:origin+'/native/',method:'GET',mode:'navigate'}})};
}

test('offline navigation serves only the current release shell even when older caches precede it',async()=>{
 const f=installedWorker({
  'native-shell-old':{'/native/':shell('old')},
  ['native-shell-'+release]:{'/native/':shell(release)},
  'native-shell-newer':{'/native/':shell('newer')},
 });
 const result=await f.navigate();
 assert.equal(result.handled,true);assert.equal(result.response.status,200);
 assert.equal(await result.response.text(),shell(release));
 assert.deepEqual(f.opened,['native-shell-'+release]);assert.equal(f.requests.length,1);
});

test('offline navigation never falls back to an old shell when the current shell is absent or empty',async()=>{
 for(const current of [false,true]){
  const entries={'native-shell-old':{'/native/':shell('old')},'native-shell-newer':{'/native/':shell('newer')}};
  if(current)entries['native-shell-'+release]={};
  const f=installedWorker(entries),result=await f.navigate(),body=await result.response.text();
  assert.equal(result.response.status,503);assert.match(body,/暂时无法连接/);
  assert.ok(body.includes('/native-assets/'+release+'/reconnect.js'));
  assert.ok(!body.includes(shell('old')));assert.ok(!body.includes(shell('newer')));
  assert.equal(result.response.headers.get('cache-control'),'no-store');
  assert.match(result.response.headers.get('content-security-policy'),/script-src 'self'/);
  assert.ok(f.opened.every(name=>name==='native-shell-'+release));
 }
});

test('activation retires only other compiled native versions and preserves draft and attachment caches byte for byte',async()=>{
 const retained={
  ['native-static-'+release]:{['/native-assets/'+release+'/app.js']:'current JavaScript'},
  ['native-shell-'+release]:{'/native/':shell(release)},
  'native-drafts-old':{'/draft':'  原字草稿\n第二行  '},
  'native-attachments-old':{'/attachment':'attachment bytes \u0000\u0001'},
  'workbench-drafts':{'/draft':'draft from a different store'},
  'other-native-static-old':{'/input':'unrelated cache'},
 };
 const f=installedWorker({...retained,'native-static-old':{'/app.js':'old code'},'native-shell-old':{'/native/':shell('old')},'native-static-future':{'/app.js':'other code'},'native-shell-future':{'/native/':shell('future')}});
 await f.dispatch('activate');
 assert.deepEqual(f.deleted.sort(),['native-shell-future','native-shell-old','native-static-future','native-static-old']);
 assert.deepEqual([...f.stores.keys()].sort(),Object.keys(retained).sort());
 for(const [name,values] of Object.entries(retained))for(const [path,body] of Object.entries(values))assert.equal(await f.stores.get(name).get(new URL(path,origin).href).clone().text(),body);
 assert.equal(f.claimed(),1);
});

test('an online shell from another release cannot replace the current offline shell or claim readiness',async()=>{
 const f=installedWorker({'native-shell-old':{'/native/':shell('old')}},async()=>new Response(shell('old')));
 const replies=[];await f.dispatch('message',{data:{type:'NATIVE_VERSION'},ports:[{postMessage:value=>replies.push(value)}]});
 assert.equal(replies.length,1);assert.equal(replies[0].release,release);assert.equal(replies[0].shell_ready,false);
 assert.equal(f.stores.get('native-shell-'+release).size,0);
 const current=installedWorker({['native-shell-'+release]:{'/native/':shell(release)}},async()=>new Response(shell('old')));
 await current.dispatch('message',{data:{type:'CACHE_SHELL'}});
 assert.equal(await current.stores.get('native-shell-'+release).get(origin+'/native/').clone().text(),shell(release));
});

test('static assets come from the current compiled cache rather than another release',async()=>{
 const path='/native-assets/'+release+'/app.js';
 const f=installedWorker({'native-static-old':{[path]:'old JavaScript'},['native-static-'+release]:{[path]:'current JavaScript'}});
 const result=await f.dispatch('fetch',{request:{url:origin+path,method:'GET',mode:'same-origin'}});
 assert.equal(result.handled,true);assert.equal(await result.response.text(),'current JavaScript');assert.equal(f.requests.length,0);
 assert.deepEqual(f.opened,['native-static-'+release]);
});

test('API, login, cross-origin and every non-GET request bypass the worker without touching network or caches',async()=>{
 const f=installedWorker();
 const requests=[
  {url:origin+'/api/chat/sessions',method:'GET',mode:'navigate'},
  {url:origin+'/native/login?next=%2Fnative%2F',method:'GET',mode:'navigate'},
  {url:'https://elsewhere.test/native/',method:'GET',mode:'navigate'},
  ...['POST','PUT','PATCH','DELETE','HEAD'].flatMap(method=>[
   {url:origin+'/native/',method,mode:'navigate'},
   {url:origin+'/native-assets/'+release+'/app.js',method,mode:'same-origin'},
   {url:origin+'/api/chat/sessions',method,mode:'same-origin'},
  ]),
 ];
 for(const request of requests)assert.equal((await f.dispatch('fetch',{request})).handled,false,request.method+' '+request.url);
 assert.equal(f.requests.length,0);assert.equal(f.opened.length,0);assert.equal(f.stores.size,0);assert.deepEqual(f.deleted,[]);
});
