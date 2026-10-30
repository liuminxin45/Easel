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
