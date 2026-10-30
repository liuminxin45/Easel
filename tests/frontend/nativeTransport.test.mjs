import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';

function fixture(){
 const storage=new Map(),calls=[];let dropped=false,receipt={state:'unavailable'};
 const load=moduleLoader({globals:{FormData,window:{location:{pathname:'/native/'},dispatchEvent(){}},Event}});
 const {WorkbenchClient}=load('workbench/core/client.ts');
 const client=new WorkbenchClient({retryDelay:0,storage:{get length(){return storage.size},key:n=>[...storage.keys()][n],getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},fetcher:async(path,options)=>{
  calls.push({path,...options});if(options?.method&&dropped)throw new TypeError('acknowledgement lost');
  return new Response(JSON.stringify(path.startsWith('/api/native/operations/')?receipt:{ok:true,id:'source-id',files:[],platform:'wechat-oa'}),{headers:{'Content-Type':'application/json'}});
 }});
 client.session.setState({config:{csrf:'owner-csrf'},loading:false});
 const release=load('workbench/ui/nativeApi.ts').bindWorkbenchNativeApi(client);
 return {client,calls,storage,api:load('lib/api.ts'),close(){release();client.pauseVisible()},set dropped(value){dropped=value},set receipt(value){receipt=value}};
}

test('a native read completed after authentication changes is discarded',async()=>{
 const load=moduleLoader(),{ApiTransport}=load('workbench/core/transport.ts');let epoch=1,complete;
 const transport=new ApiTransport({authEpoch:()=>epoch,fetcher:()=>new Promise(resolve=>{complete=resolve})});
 const pending=transport.get('/api/accounts');epoch=2;
 complete(new Response(JSON.stringify([{loggedIn:true}]),{headers:{'Content-Type':'application/json'}}));
 await assert.rejects(pending,error=>error.cancelled===true);
});

test('native requests preserve HTTP verbs and original entity IDs with a separate operation header',async()=>{
 const f=fixture();try{
  await f.api.updateTrendSource({action:'toggle',id:'source-id',enabled:false});
  const first=f.calls.find(call=>call.method==='POST');
  assert.equal(JSON.parse(first.body).id,'source-id');assert.notEqual(first.headers['X-Operation-Id'],'source-id');
  assert.equal(first.headers['X-CSRF-Token'],'owner-csrf');assert.equal(first.path,'/api/trends/manage');
  await f.api.savePersonaFile('profile','identity.md','original text');
  assert.ok(f.calls.some(call=>call.method==='PUT'&&JSON.parse(call.body).content==='original text'));
  await f.api.deleteIdea('idea-id');assert.ok(f.calls.some(call=>call.method==='DELETE'&&call.path==='/api/ideas/idea-id'));
 }finally{f.close()}
});

test('lost native acknowledgements persist only metadata and recover by GET without another write',async()=>{
 const f=fixture();try{
  f.dropped=true;await assert.rejects(f.api.savePersonaFile('profile','identity.md','PRIVATE INPUT'));
  const first=f.calls.find(call=>call.method==='PUT'),id=first.headers['X-Operation-Id'];
  assert.ok(!JSON.stringify([...f.storage]).includes('PRIVATE INPUT'));
  f.receipt={id,state:'completed',result:{ok:true}};
  assert.equal((await f.api.savePersonaFile('profile','identity.md','PRIVATE INPUT')).ok,true);
  assert.equal(f.calls.filter(call=>call.method==='PUT').length,1);
  assert.ok(f.calls.some(call=>call.path==='/api/native/operations/'+id&&!call.method));
 }finally{f.close()}
});

test('native multipart uploads preserve browser boundaries and opaque upload identity',async()=>{
 const f=fixture();try{
  await f.api.uploadFiles([new File(['bytes'],'reference.png',{type:'image/png'})],'exact-session');
  const call=f.calls.find(call=>call.method==='POST');assert.equal(call.path,'/api/upload');
  assert.ok(call.body instanceof FormData);assert.equal(call.body.get('sessionId'),'exact-session');
  assert.equal(call.headers['Content-Type'],undefined);assert.ok(call.headers['X-Operation-Id']);
 }finally{f.close()}
});
