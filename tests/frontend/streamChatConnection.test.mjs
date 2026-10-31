import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';

const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url));
const ts=require('typescript');
const source=readFileSync(new URL('../../web/frontend/src/lib/api.ts',import.meta.url),'utf8');
const parsed=ts.createSourceFile('api.ts',source,ts.ScriptTarget.Latest,true);
const declaration=parsed.statements.find(node=>ts.isFunctionDeclaration(node)&&node.name?.text==='streamChat');
const compiled=ts.transpileModule(declaration.getText(parsed),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const accepted='event: accepted\ndata: {"turnId":"fixed-turn"}\n\n';
const done='event: done\ndata: {"sessionKey":"session"}\n\n';
const tick=()=>new Promise(resolve=>setImmediate(resolve));

function response(chunks=[],{hold=false,status=200}={}){
 let index=0;
 return {ok:status<400,status,json:async()=>({error:'fixture status '+status}),body:{getReader:()=>({read:async()=>{
  if(index<chunks.length){const value=chunks[index++];if(value instanceof Error)throw value;return {done:false,value:new TextEncoder().encode(value)}}
  return hold?new Promise(()=>{}):{done:true};
 }})}};
}

function start(replies){
 const calls={requests:[],accepted:0,restored:0,interrupted:0,done:0,errors:[]};
 const timers=[];
 const exports={};
 runInNewContext(compiled,{exports,BASE:'',window:{location:{pathname:'/native/'}},AbortController,TextDecoder,clearTimeout,
  setTimeout:fn=>{timers.push(fn);return timers.length},
  fetch:async(url,options)=>{calls.requests.push({url,method:options?.method||'GET'});assert.ok(replies.length,'no unexpected retries');return replies.shift()}});
 const controller=exports.streamChat('original',undefined,'session',()=>{},()=>calls.done++,error=>calls.errors.push(error),undefined,undefined,()=>calls.interrupted++,'fixed-turn',false,undefined,[],undefined,undefined,undefined,
  {onAccepted:()=>calls.accepted++,onConnectionRestored:()=>calls.restored++});
 return {calls,controller,retry:async()=>{await tick();assert.ok(timers.length,'retry scheduled');timers.shift()();await tick()}};
}

test('a quiet accepted reconnect clears transport interruption without acknowledging the turn twice',async()=>{
 const f=start([response([accepted]),response([accepted,': keep-alive\n\n'],{hold:true})]);
 await f.retry();
 assert.equal(f.calls.interrupted,1);assert.equal(f.calls.restored,1);assert.equal(f.calls.accepted,1);
 assert.deepEqual(f.calls.requests,[{url:'/api/chat/stream',method:'POST'},{url:'/api/chat/jobs/fixed-turn/stream?after=0',method:'GET'}]);
 assert.equal(f.calls.done,0);assert.equal(f.calls.errors.length,0);f.controller.abort();
});

test('SSE keep-alive alone confirms resumed transport without requiring a model token',async()=>{
 const f=start([response([accepted]),response([': keep-alive\n\n',': keep-alive\n\n'],{hold:true})]);
 await f.retry();assert.equal(f.calls.restored,1);assert.equal(f.calls.accepted,1);assert.equal(f.calls.done,0);
 assert.equal(f.calls.requests.filter(value=>value.method==='POST').length,1);f.controller.abort();
});

test('a successful HTTP status with no SSE proof does not announce restoration',async()=>{
 const f=start([response([accepted]),response([],{hold:true})]);
 await f.retry();assert.equal(f.calls.requests.length,2);assert.equal(f.calls.restored,0);assert.equal(f.calls.accepted,1);
 assert.equal(f.calls.done,0);f.controller.abort();
});

test('each real reconnection notifies once while all retries retain the original turn',async()=>{
 const f=start([response([accepted]),response([accepted,': keep-alive\n\n']),response([': keep-alive\n\n',accepted,done])]);
 await f.retry();await f.retry();
 assert.equal(f.calls.interrupted,2);assert.equal(f.calls.restored,2);assert.equal(f.calls.accepted,1);assert.equal(f.calls.done,1);
 assert.equal(f.calls.requests.filter(value=>value.method==='POST').length,1);
 assert.ok(f.calls.requests.slice(1).every(value=>value.method==='GET'&&value.url==='/api/chat/jobs/fixed-turn/stream?after=0'));
 f.controller.abort();
});

test('a rejected resumed stream never announces connection restoration or repeats the POST',async()=>{
 const f=start([response([accepted]),response([],{status:401})]);
 await f.retry();assert.equal(f.calls.restored,0);assert.equal(f.calls.errors.length,1);assert.equal(f.calls.errors[0].status,401);
 assert.equal(f.calls.requests.length,2);assert.equal(f.calls.requests.filter(value=>value.method==='POST').length,1);f.controller.abort();
});
