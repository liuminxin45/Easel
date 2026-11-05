import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const source=ts.transpileModule(readFileSync(new URL('../../web/frontend/src/workbench/platform/page-performance.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
function fixture(){
 const exports={},listeners={},stored=new Map(),sent=[];let now=0;
 const storage={getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)};
 const window={__wbBoot:{start:0,visible:100,entry:200,module:300,hidden:false,trace:'a'.repeat(16),release:'native-test'},addEventListener:(k,f)=>listeners[k]=f,setInterval:()=>1};
 const document={hidden:false,documentElement:{dataset:{nativePlatform:'android'}},querySelector:()=>({content:'native-test'}),addEventListener(){}};
 const performance={now:()=>now,getEntriesByType:()=>[{responseEnd:200,responseStart:150,requestStart:120,domainLookupStart:1,domainLookupEnd:2,connectStart:2,connectEnd:5,secureConnectionStart:3}]};
 const fetch=async(path,options)=>{sent.push({path,body:JSON.parse(options.body),headers:options.headers});return {ok:true,json:async()=>({accepted:true})}};
 const context={exports,require:id=>id==='../core/usage'?{usageScreen:()=> 'home'}:assert.fail(id),window,document,sessionStorage:storage,performance,fetch,location:{pathname:'/native/',search:'?path=secret'},setTimeout:()=>1,clearInterval(){},requestAnimationFrame:f=>f(),Date,Math,JSON,Number,Array,Object,Map,RegExp};
 runInNewContext(source,context);return {tracker:exports.pagePerformance,listeners,stored,sent,setTime:n=>now=n,window};
}
test('slow boot is aggregated and traced without storing the URL',async()=>{
 const f=fixture();f.setTime(4000);f.tracker.boot();await f.tracker.enable('csrf');await new Promise(r=>setImmediate(r));
 assert.equal(f.sent.length,1);const events=f.sent[0].body.events;assert.deepEqual(events.map(e=>e.kind),['summary','slow']);
 assert.equal(events[1].phases_ms.boot_visible,3900);assert.equal(events[1].trace,'a'.repeat(16));assert.equal(JSON.stringify(events).includes('secret'),false);
});
test('navigation records shell and actual slow content without leaking a path',async()=>{
 const f=fixture();f.listeners['workbench:performance-navigation']({detail:{key:'entry',path:'/chat/private-id?x=secret'}});f.setTime(500);f.tracker.shell('entry');f.setTime(4000);f.listeners['workbench:performance-content']({detail:{key:'entry'}});await f.tracker.enable('csrf');await new Promise(r=>setImmediate(r));
 const events=f.sent[0].body.events;assert.equal(events[0].kind,'summary');assert.equal(events[1].phases_ms.content,4000);assert.equal(JSON.stringify(events).includes('private-id'),false);
});
test('slow request records only a route class and bounded trace',async()=>{
 const f=fixture();f.listeners['workbench:performance-request']({detail:{path:'/api/chat/sessions/secret-id?token=hidden',duration:2100,status:503,trace:'b'.repeat(16)}});await f.tracker.enable('csrf');await new Promise(r=>setImmediate(r));
 const event=f.sent[0].body.events[0];assert.equal(event.request_group,'chat');assert.equal(event.status,503);assert.equal(event.trace,'b'.repeat(16));assert.equal(JSON.stringify(event).includes('secret'),false);assert.equal(JSON.stringify(event).includes('token='),false);
});
test('disabled reporting does not send and missing visibility is not invented',async()=>{
 const f=fixture();f.window.__wbBoot.visible=null;f.setTime(4000);f.tracker.boot();assert.equal(f.sent.length,0);f.tracker.disable();await f.tracker.flush();assert.equal(f.sent.length,0);
 f.tracker.enable('csrf');await new Promise(r=>setImmediate(r));const event=f.sent[0].body.events.find(e=>e.kind==='slow');assert.equal('boot_visible' in event.phases_ms,false);
});
