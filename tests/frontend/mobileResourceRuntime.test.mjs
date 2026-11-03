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

test('original skill config uses the visible detail revision and preserves stale-save rejection',async()=>{
 const f=fixture();try{
  f.state.response=(path,options)=>options.method==='POST'?json({error:'配置已有新修订'},409):json({name:'ai-image-gen',body:'workflow',configuration_revision:4});
  await f.api.fetchSkillDetail('ai-image-gen');
  await assert.rejects(f.api.saveEnv({IMG_API_KEY:'TEMP'}),/配置已有新修订/);
  const sent=f.calls.find(call=>call.method==='POST'&&call.path==='/api/env');
  assert.equal(JSON.parse(sent.body).expected_revision,4);
  assert.equal(JSON.parse(sent.body).updates.IMG_API_KEY,'TEMP');
  assert.equal(typeof JSON.parse(sent.body).id,'string');
  assert.equal(JSON.parse(sent.body).id,sent.headers['X-Operation-Id']);
 }finally{f.close()}
});

test('original skill config refuses to invent a revision without a detail read',async()=>{
 const f=fixture();try{await assert.rejects(f.api.saveEnv({IMG_API_KEY:'TEMP'}),/重新打开技能详情/);assert.equal(f.calls.length,0)}finally{f.close()}
});

test('original skill detail waits past a cached snapshot so consecutive config saves use the new mask and revision',async()=>{
 const f=fixture();try{
  let revision=4,key='',finish;
  const detail=()=>({name:'ai-image-gen',configuration_revision:revision,apiSpec:{providers:[{keys:[{env:'IMG_API_KEY',configured:!!key,masked:key?'TEMP***':''}]}]}});
  f.state.response=(path,options)=>{
   if(options.method==='POST'){
    const body=JSON.parse(options.body);if(body.expected_revision!==revision)return json({error:'配置已有新修订'},409);
    key=body.updates.IMG_API_KEY;revision++;return json({ok:true,revision,skills:{}});
   }
   return json(detail());
  };
  assert.equal((await f.api.fetchSkillDetail('ai-image-gen')).configuration_revision,4);
  await f.api.saveEnv({IMG_API_KEY:'TEMP-first'});
  assert.equal(f.client.peek('/api/skill/ai-image-gen').configuration_revision,4);
  const response=f.state.response;f.state.response=(path,options)=>new Promise(resolve=>{finish=()=>resolve(response(path,options))});
  let settled=false;const refreshed=f.api.fetchSkillDetail('ai-image-gen').then(value=>{settled=true;return value});
  await new Promise(resolve=>setImmediate(resolve));assert.equal(settled,false,'a warm cached detail must not resolve before the current response');
  finish();const fresh=await refreshed;assert.equal(fresh.configuration_revision,5);assert.equal(fresh.apiSpec.providers[0].keys[0].configured,true);assert.equal(fresh.apiSpec.providers[0].keys[0].masked,'TEMP***');
  f.state.response=response;await f.api.saveEnv({IMG_API_KEY:'TEMP-second'});
  assert.deepEqual(f.calls.filter(call=>call.method==='POST').map(call=>JSON.parse(call.body).expected_revision),[4,5]);
  assert.equal((await f.api.fetchSkillDetail('ai-image-gen')).configuration_revision,6);
 }finally{f.close()}
});

test('a late closed detail read cannot replace the currently opened skill configuration revision',async()=>{
 const f=fixture();try{
  let first,second;
  f.state.response=(path,options)=>options.method==='POST'?json({ok:true,skills:{}}):new Promise(resolve=>{if(path.endsWith('/first'))first=resolve;else second=resolve});
  const old=f.api.fetchSkillDetail('first'),current=f.api.fetchSkillDetail('second');
  await new Promise(resolve=>setImmediate(resolve));second(json({name:'second',configuration_revision:6}));await current;
  first(json({name:'first',configuration_revision:4}));await old;
  await f.api.saveEnv({IMG_API_KEY:'TEMP'});
  assert.equal(JSON.parse(f.calls.find(call=>call.method==='POST').body).expected_revision,6);
 }finally{f.close()}
});

test('original skill config lost replies recover through the existing settings receipt, without resending',async()=>{
 const f=fixture();try{
  f.state.response=(path,options)=>options.method==='POST'?Promise.reject(new TypeError('TEMP lost reply')):json({name:'ai-image-gen',configuration_revision:4});
  await f.api.fetchSkillDetail('ai-image-gen');
  await assert.rejects(f.api.saveEnv({IMG_API_KEY:'TEMP'}));
  const pending=f.client.operation('settings').getState().pending;
  assert.ok(pending&&pending.receiptPath.startsWith('/api/settings/operations/'));
  f.state.response=path=>{assert.equal(path,pending.receiptPath);return json({id:pending.id,state:'completed',result:{ok:true,revision:5,skills:{}}})};
  assert.equal((await f.client.reconcile('settings')).revision,5);
  assert.equal(f.calls.filter(call=>call.method==='POST').length,1);
 }finally{f.close()}
});

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

test('native profile reads and snapshot errors preserve exact HTTP status through the official API port',async()=>{
 const f=fixture(),path='/api/persona/profile-a/files';try{
  let caught;const stop=f.api.subscribeApiData(path,()=>{},error=>{caught=error});
  for(const status of [404,403]){
   f.state.response=()=>json({error:'TEMP profile unavailable'},status);
   await assert.rejects(f.api.fetchPersonaFiles('profile-a',true),error=>error instanceof f.api.ApiError&&error.status===status);
   assert.equal(f.client.resource(path).getState().errorStatus,status);assert.ok(caught instanceof f.api.ApiError);assert.equal(caught.status,status);
  }
  f.state.response=()=>{throw new TypeError('TEMP network offline')};
  await assert.rejects(f.api.fetchPersonaFiles('profile-a',true),error=>!(error instanceof f.api.ApiError)&&error.status===undefined);
  assert.equal(f.client.resource(path).getState().errorStatus,undefined);assert.equal(caught.status,undefined);
  f.state.response=()=>json({name:'profile-a',files:[]});await f.api.fetchPersonaFiles('profile-a',true);assert.equal(f.client.resource(path).getState().errorStatus,undefined);assert.equal(f.client.resource(path).getState().error,'');stop();
 }finally{f.close()}
});

test('stale profile failures cannot restore a status across an authentication epoch',async()=>{
 const f=fixture(),path='/api/persona/profile-a/files';try{
  let finish;f.state.response=()=>new Promise(resolve=>{finish=resolve});const request=f.api.fetchPersonaFiles('profile-a',true);
  f.client.beginAuthentication();f.client.session.setState({config:{csrf:'NEXT'},loading:false});finish(json({error:'TEMP old missing profile'},404));
  await assert.rejects(request,error=>error.cancelled===true);assert.equal(f.client.resource(path).getState().errorStatus,undefined);assert.equal(f.client.resource(path).getState().error,'');
  f.state.response=()=>json({name:'profile-a',files:[]});await f.api.fetchPersonaFiles('profile-a',true);assert.equal(f.client.resource(path).getState().errorStatus,undefined);
 }finally{f.close()}
});

test('native cached persona catalogs are validated for snapshots and subscriptions as ordinary reads are',async()=>{
 const f=fixture(),path='/api/personas';try{
  const list=[{name:'profile-a',description:'Actual profile'}];f.state.response=()=>json(list);await f.api.fetchPersonas();assert.equal(f.api.peekApiData(path)[0].name,'profile-a');
  let error;const stop=f.api.subscribeApiData(path,()=>{},value=>{error=value});f.client.resource(path).setState({data:[{name:'broken'}]});
  assert.equal(f.api.peekApiData(path),undefined);assert.match(error.message,/画像列表响应格式无效/);
  f.state.response=()=>json([{name:'broken'}]);await assert.rejects(f.api.fetchPersonas(true),/画像列表响应格式无效/);stop();
 }finally{f.close()}
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
  f.state.response=()=>json({version:1,day:'1970-01-01',timezone:'Asia/Shanghai',trends:[{platform:'temp',label:'TEMP',ok:true,items:[{id:'item',title:'TEMP title',url:'javascript:alert(1)'}]}],updated:1,warnings:[]});
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
