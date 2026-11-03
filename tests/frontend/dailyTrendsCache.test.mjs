import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';

const PATH='/api/trends?limit=6';
const json=(value,headers={})=>new Response(JSON.stringify(value),{headers:{'Content-Type':'application/json',...headers}});
const today=ms=>new Date(ms+8*3600000).toISOString().slice(0,10);
const payload=(day,id=day)=>({version:1,day,timezone:'Asia/Shanghai',trends:[{platform:'source',label:'Source',ok:true,items:[{id,title:id,url:'https://example.test/'+id}]}],updated:1,warnings:[]});
function fixture(initial='2026-11-03T23:59:59+08:00'){
 const clock={now:Date.parse(initial)},timers=[],calls=[];
 const state={response:path=>path==='/api/config'?json({csrf:'TEMP'}):json(payload(today(clock.now)),{'ETag':'"'+today(clock.now)+'"'})};
 const load=moduleLoader({globals:{FormData,Event,window:{location:{pathname:'/native/'},dispatchEvent(){}},setTimeout:(callback,ms)=>{const timer={callback,ms,due:clock.now+ms,cleared:false,unref(){}};timers.push(timer);return timer},clearTimeout:timer=>{if(timer)timer.cleared=true}}});
 const client=new (load('workbench/core/client.ts').WorkbenchClient)({clock:()=>clock.now,retryDelay:0,fetcher:async(path,options)=>{calls.push({path,...options});return state.response(path,options)}});
 client.session.setState({config:{csrf:'TEMP'},loading:false});
 const api=load('lib/api.ts'),release=load('workbench/ui/nativeApi.ts').bindWorkbenchNativeApi(client);
 return {clock,timers,calls,state,client,api,advance(ms){clock.now+=ms;for(const timer of [...timers])if(!timer.cleared&&timer.due<=clock.now){timer.cleared=true;timer.callback()}},close(){release();client.pauseVisible()}};
}
const flush=()=>new Promise(resolve=>setImmediate(resolve));

test('same-day reads and returning pages reuse their current-day snapshot',async()=>{
 const f=fixture('2026-11-03T12:00:00+08:00');try{
  const first=await f.api.fetchTrends(undefined,6);assert.equal(first.trends[0].items[0].id,'2026-11-03');
  await f.api.fetchTrends(undefined,6);assert.equal(f.calls.filter(c=>c.path===PATH).length,1);
  assert.equal(f.api.peekApiData(PATH).day,'2026-11-03');
 }finally{f.close()}
});

test('midnight clears mounted news immediately, then silently reads the new date',async()=>{
 const f=fixture();try{
  await f.api.fetchTrends(undefined,6);let update;const stop=f.api.subscribeApiData(PATH,value=>{update=value});
  let resolve;f.state.response=()=>new Promise(yes=>{resolve=yes});f.advance(1000);
  assert.equal(update.day,'2026-11-04');assert.equal(update.trends.length,0);assert.equal(update.warnings.length,0);
  assert.equal(f.api.peekApiData(PATH).trends.length,0);
  assert.equal(f.calls.at(-1).headers?.['If-None-Match'],undefined);
  resolve(json(payload('2026-11-04','new')));await flush();assert.equal(update.trends[0].items[0].id,'new');stop();
 }finally{f.close()}
});

test('a page returning after midnight cannot synchronously peek yesterday',async()=>{
 const f=fixture();try{
  await f.api.fetchTrends(undefined,6);f.clock.now+=1000;
  assert.equal(f.api.peekApiData(PATH).day,'2026-11-04');assert.equal(f.api.peekApiData(PATH).trends.length,0);
  const immediate=await f.api.fetchTrends(undefined,6);assert.equal(immediate.trends.length,0);
  await flush();assert.equal(f.api.peekApiData(PATH).trends[0].items[0].id,'2026-11-04');
 }finally{f.close()}
});

test('foreground resume clears yesterday before waiting for authentication',async()=>{
 const f=fixture();try{
  await f.api.fetchTrends(undefined,6);let update;const stop=f.api.subscribeApiData(PATH,value=>{update=value});f.client.pauseVisible();f.clock.now+=1000;
  let auth;f.state.response=path=>path==='/api/config'?new Promise(yes=>{auth=yes}):json(payload('2026-11-04'));
  const resumed=f.client.resumeVisible();assert.equal(update.trends.length,0);assert.equal(update.day,'2026-11-04');
  auth(json({csrf:'TEMP'}));await resumed;assert.equal(update.trends[0].items[0].id,'2026-11-04');stop();
 }finally{f.close()}
});

test('a delayed modified response from yesterday never enters the new day',async()=>{
 const f=fixture();try{
  let resolve;f.state.response=()=>new Promise(yes=>{resolve=yes});const pending=f.api.fetchTrends(undefined,6);
  f.clock.now+=1000;f.state.response=()=>json(payload('2026-11-04','current'));
  resolve(json(payload('2026-11-03','yesterday'),{'X-Workbench-Server-Time':'2026-11-03T15:59:59Z'}));
  const result=await pending;assert.equal(result.trends[0].items[0].id,'current');assert.equal(f.calls.length,2);
  assert.equal(f.api.peekApiData(PATH).trends[0].items[0].id,'current');
 }finally{f.close()}
});

test('a prior-day 304 cannot revive its old snapshot and is followed by an unconditional read',async()=>{
 const f=fixture();try{
  await f.api.fetchTrends(undefined,6);let resolve;f.state.response=()=>new Promise(yes=>{resolve=yes});
  const pending=f.client.read(PATH,true);assert.equal(f.calls.at(-1).headers['If-None-Match'],'"2026-11-03"');
  f.clock.now+=1000;f.state.response=()=>json(payload('2026-11-04','current'));resolve(new Response(null,{status:304}));
  await pending;assert.equal(f.api.peekApiData(PATH).trends[0].items[0].id,'current');
  assert.equal(f.calls.at(-1).headers?.['If-None-Match'],undefined);
  assert.equal(f.calls.length,3);
 }finally{f.close()}
});

test('an unexpected same-day response claiming yesterday is rejected without returning old rows',async()=>{
 const f=fixture('2026-11-04T12:00:00+08:00');try{
  f.state.response=()=>json(payload('2026-11-03','old'));await assert.rejects(f.api.fetchTrends(undefined,6),/日期未能核对/);
  assert.equal(f.api.peekApiData(PATH),undefined);
 }finally{f.close()}
});

test('a warm snapshot captured before midnight is rechecked when delivered to its consumer',async()=>{
 const f=fixture();try{
  await f.api.fetchTrends(undefined,6);const pending=f.api.fetchTrends(undefined,6);f.clock.now+=1000;
  const result=await pending;assert.equal(result.day,'2026-11-04');assert.equal(result.trends.length,0);
 }finally{f.close()}
});

test('the server clock anchors the daily boundary when the device clock is skewed',async()=>{
 const f=fixture('2026-11-05T12:00:00+08:00');try{
  f.state.response=()=>json(payload('2026-11-03','server-today'),{'X-Workbench-Server-Time':'2026-11-03T04:00:00Z'});
  const result=await f.api.fetchTrends(undefined,6);assert.equal(result.day,'2026-11-03');assert.equal(result.trends[0].items[0].id,'server-today');
  const stop=f.client.watch(PATH);assert.equal(f.timers.filter(t=>!t.cleared).at(-1).ms,12*3600000);stop();
 }finally{f.close()}
});
