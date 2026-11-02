import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';

const json=(value,status=200,headers={})=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json',...headers}});
function storage(){const values=new Map();let reads=0,fail=false;return {values,get reads(){return reads},set fail(v){fail=v},get length(){return values.size},key:i=>[...values.keys()][i]??null,getItem:key=>{reads++;return values.get(key)??null},setItem:(key,value)=>{if(fail)throw Error('TEMP quota');values.set(key,value)},removeItem:key=>values.delete(key)}}
function fixture(){
 const saved=storage(),calls=[],clock={now:100},state={response:()=>json([{path:'original'}])};let transport;
 const load=moduleLoader({globals:{FormData,Event,window:{location:{pathname:'/native/'},dispatchEvent(){}}}});
 const client=new (load('workbench/core/client.ts').WorkbenchClient)({clock:()=>clock.now,storage:saved,retryDelay:0,fetcher:async(path,options)=>{calls.push({path,...options});return state.response(path,options)}});
 client.session.setState({config:{csrf:'TEMP'},loading:false});
 const api=load('lib/api.ts'),bind=api.bindEaselApiTransport;
 api.bindEaselApiTransport=value=>{transport=value;return bind(value)};
 const release=load('workbench/ui/nativeApi.ts').bindWorkbenchNativeApi(client);
 return {api,client,saved,calls,clock,state,get transport(){return transport},close(){release();client.pauseVisible()}};
}

test('native page reads share the real host cache and expose synchronous snapshots on return',async()=>{
 const f=fixture();try{
  await f.api.fetchOutputs();await f.api.fetchOutputs();
  assert.equal(f.calls.length,1);assert.equal(f.api.peekApiData('/api/outputs')[0].path,'original');
  assert.equal(f.api.peekApiData('/api/accounts'),undefined);
  f.clock.now+=31000;let resolve;f.state.response=()=>new Promise(yes=>{resolve=yes});
  let updated;const stop=f.api.subscribeApiData('/api/outputs',value=>{updated=value});
  assert.equal((await f.api.fetchOutputs())[0].path,'original');assert.equal(f.calls.length,2);
  resolve(json([{path:'updated'}]));await new Promise(yes=>setImmediate(yes));
  assert.equal(updated[0].path,'updated');stop();
 }finally{f.close()}
});

test('stale refresh failures retain data but surface an error, and explicit refresh rejects',async()=>{
 const f=fixture();try{
  await f.api.fetchOutputs();f.clock.now+=31000;f.state.response=()=>json({error:'TEMP server failure'},500);
  let error;const stop=f.api.subscribeApiData('/api/outputs',()=>{},value=>{error=value});
  assert.equal((await f.api.fetchOutputs())[0].path,'original');await new Promise(yes=>setImmediate(yes));
  assert.match(error.message,/TEMP server failure/);
  await assert.rejects(f.api.fetchOutputs(true),/TEMP server failure/);
  assert.equal(f.api.peekApiData('/api/outputs')[0].path,'original');stop();
 }finally{f.close()}
});

test('a failed cold read is rejected rather than returning null as page data',async()=>{
 const f=fixture();try{f.state.response=()=>json({error:'TEMP forbidden'},403);await assert.rejects(f.api.fetchOutputs(),/TEMP forbidden/);assert.equal(f.api.peekApiData('/api/outputs'),undefined)}finally{f.close()}
});

test('failed background refreshes back off, while an explicit refresh can retry immediately',async()=>{
 const f=fixture();try{
  await f.api.fetchOutputs();f.clock.now+=31000;f.state.response=()=>json({error:'TEMP offline'},500);
  await f.api.fetchOutputs();await new Promise(yes=>setImmediate(yes));assert.equal(f.calls.length,2);
  for(let i=0;i<5;i++)await f.api.fetchOutputs();assert.equal(f.calls.length,2);
  let retainedError;const stop=f.api.subscribeApiData('/api/outputs',()=>{},error=>{retainedError=error});assert.match(retainedError.message,/TEMP offline/);
  f.state.response=()=>json([{path:'manual-recovery'}]);assert.equal((await f.api.fetchOutputs(true))[0].path,'manual-recovery');assert.equal(f.calls.length,3);stop();
 }finally{f.close()}
});

test('an already canceled reader does not start a request',async()=>{
 const f=fixture();try{const abort=new AbortController();abort.abort();await assert.rejects(f.transport.request('/api/outputs',{signal:abort.signal}),error=>error.cancelled===true);assert.equal(f.calls.length,0)}finally{f.close()}
});

test('canceling one reader never aborts the shared transport or the other reader',async()=>{
 const f=fixture();try{
  let resolve;f.state.response=()=>new Promise(yes=>{resolve=yes});const abort=new AbortController();
  const first=f.transport.request('/api/outputs',{signal:abort.signal}),second=f.transport.request('/api/outputs');
  assert.equal(f.calls.length,1);abort.abort();await assert.rejects(first,error=>error.cancelled===true);
  assert.equal(f.calls[0].signal.aborted,false);resolve(json([{path:'shared'}]));assert.equal((await second)[0].path,'shared');
 }finally{f.close()}
});

test('credentials, QR/login status and settings stay live and auth changes clear snapshot access',async()=>{
 const f=fixture();try{
  for(const path of ['/api/accounts','/api/login/wechat-oa/status','/api/accounts/wechat-oa/credentials','/api/settings/models']){
   await f.transport.request(path);await f.transport.request(path);assert.equal(f.calls.filter(call=>call.path===path).length,2);assert.equal(f.transport.peek(path),undefined);
  }
  await f.api.fetchOutputs();f.client.expireSession();assert.equal(f.api.peekApiData('/api/outputs'),undefined);
  await assert.rejects(f.api.fetchOutputs(),/登录已过期/);
 }finally{f.close()}
});

test('an auth epoch change also rejects a warm snapshot awaiting its consumer',async()=>{
 const f=fixture();try{await f.api.fetchOutputs();const pending=f.api.fetchOutputs();f.client.beginAuthentication();await assert.rejects(pending,error=>error.cancelled===true);assert.equal(f.api.peekApiData('/api/outputs'),undefined)}finally{f.close()}
});

test('one native source mutation invalidates exactly its own data domains once',async()=>{
 const f=fixture();try{
  f.state.response=()=>json({ok:true,id:'source-one'});const tags=[];f.client.invalidate=async value=>{tags.push(value)};
  await f.api.updateTrendSource({action:'toggle',id:'source-one',enabled:false});
  assert.equal(tags.length,1);assert.equal(tags[0].includes('trend-sources'),true);assert.equal(tags[0].includes('creator'),false);assert.equal(tags[0].includes('works'),false);
 }finally{f.close()}
});

test('cached trend snapshots and subscriptions keep the original URL and protocol validators',async()=>{
 const f=fixture();try{
  const path='/api/trends?limit=12&platforms=temp';
  f.state.response=()=>json({version:1,trends:[{platform:'temp',label:'TEMP',ok:true,items:[{id:'item',title:'TEMP title',url:'javascript:alert(1)'}]}],updated:1,warnings:[]});
  assert.equal((await f.api.fetchTrends('temp')).trends[0].items[0].url,'');
  assert.equal(f.api.peekApiData(path).trends[0].items[0].url,'');
  let update,error;const stop=f.api.subscribeApiData(path,value=>{update=value},value=>{error=value});
  await f.api.fetchTrends('temp',12,true);assert.equal(update.trends[0].items[0].url,'');
  f.client.resource(path).setState({data:{version:0,trends:[]}});assert.equal(f.api.peekApiData(path),undefined);assert.match(error.message,/格式异常/);stop();
 }finally{f.close()}
});

test('explicit poll intervals are honored, merged and paused in the background',()=>{
 const timers=[],load=moduleLoader({globals:{setTimeout:(callback,ms)=>{const timer={callback,ms,cleared:false,unref(){}};timers.push(timer);return timer},clearTimeout:timer=>{timer.cleared=true}}});
 const client=new (load('workbench/core/client.ts').WorkbenchClient)({storage:storage()});client.session.setState({config:{csrf:'TEMP'},loading:false});
 client.resource('/api/chat/sessions').setState({data:{sessions:[{pendingTurnId:'running'}]},loading:false});
 const slow=client.watch('/api/chat/sessions',10000);assert.equal(timers.at(-1).ms,10000);
 const fast=client.watch('/api/chat/sessions',5000);assert.equal(timers.at(-1).ms,5000);
 fast();assert.equal(timers.at(-1).ms,10000);client.pauseVisible();assert.ok(timers.every(timer=>timer.cleared));slow();
});

test('normal draft saves do not broadcast unchanged success and pending lookup does not rescan all drafts',()=>{
 const saved=storage();for(let i=0;i<200;i++)saved.values.set('toolbox:draft:input:'+i,JSON.stringify({text:'TEMP '+i}));
 saved.values.set('toolbox:draft:pending-one',JSON.stringify({pending:{id:'original'}}));
 const {DraftRepository}=moduleLoader()('workbench/core/persistence.ts'),drafts=new DraftRepository(saved);let notifications=0;drafts.persistence.subscribe(()=>notifications++);
 assert.equal(drafts.pending().length,1);const reads=saved.reads;
 for(let i=0;i<20;i++){drafts.set('input:0',{text:'edit '+i});assert.equal(drafts.pending().length,1)}
 assert.equal(saved.reads,reads);assert.equal(notifications,0);
 drafts.set('pending-one',{text:'complete'});assert.equal(drafts.pending().length,0);
 saved.fail=true;drafts.set('input:0',{text:'unsaved'});drafts.set('input:0',{text:'still unsaved'});assert.equal(notifications,1);
 saved.fail=false;drafts.set('input:0',{text:'saved'});assert.equal(notifications,2);
});
