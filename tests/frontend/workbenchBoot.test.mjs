import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const compiled=ts.transpileModule(readFileSync(new URL('../../web/frontend/src/workbench/entry.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function launch(fail=false){let timer,cleared=false;const node={textContent:'正在打开工作台…'};
 runInNewContext(compiled,{exports:{},document:{getElementById:()=>node},setTimeout:fn=>(timer=fn,1),clearTimeout:()=>{cleared=true},require:()=>{if(fail)throw Error('chunk unavailable');return {}}});
 return {node,timeout:()=>timer(),cleared:()=>cleared};}
test('failed startup chunk produces a recovery message instead of an endless spinner',async()=>{const view=launch(true);await settle();assert.match(view.node.textContent,/加载失败/);assert.match(view.node.textContent,/草稿仍保留/);assert.equal(view.cleared(),true)});
test('slow startup reports the connection problem while allowing loading to complete',async()=>{const view=launch();view.timeout();assert.match(view.node.textContent,/加载较慢/);await settle();assert.equal(view.cleared(),true)});
test('successful startup clears the watchdog without replacing application content',async()=>{const view=launch();await settle();assert.equal(view.cleared(),true);assert.equal(view.node.textContent,'正在打开工作台…')});
test('migration unregisters only the retired root worker, retaining the native worker and cached inputs',async()=>{
 const removed=[];const registrations=[['https://example.test/','/sw.js'],['https://example.test/native/','/native/sw.js'],['https://example.test/','/different-worker.js']].map(([scope,path])=>({scope,active:{scriptURL:'https://example.test'+path},unregister:async()=>{removed.push(path);return true}}));
 runInNewContext(compiled,{exports:{},URL,location:{origin:'https://example.test'},navigator:{serviceWorker:{getRegistrations:async()=>registrations}},document:{getElementById:()=>null},setTimeout:()=>1,clearTimeout:()=>{},require:()=>({})});
 await settle();assert.deepEqual(removed,['/sw.js']);
});
