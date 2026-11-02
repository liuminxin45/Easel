import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
function fixture(hash=''){
 const listeners=new Map(),moves=[],replaced=[],location={hash,pathname:'/native/',search:'?path=%2Fchat%2Fold'};
 class Element{constructor(href){this.href=href;this.target=''}closest(){return this}getAttribute(){return this.href}hasAttribute(){return false}}
 const document={addEventListener:(key,fn)=>listeners.set('document:'+key,fn),removeEventListener:(key)=>listeners.delete('document:'+key)};
 const window={addEventListener:(key,fn)=>listeners.set(key,fn),removeEventListener:(key)=>listeners.delete(key)};
 const exports={};runInNewContext(ts.transpileModule(readFileSync(new URL('../../web/frontend/src/lib/outputNavigation.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports,window,document,Element,location,history:{state:{owner:'navigation'},replaceState:(...args)=>replaced.push(args)}});
 const close=exports.bindOutputNavigation(path=>moves.push(path));
 function click(href,extra={}){let prevented=false;listeners.get('document:click')({target:new Element(href),button:0,preventDefault:()=>{prevented=true},stopPropagation(){},...extra});return prevented}
 return {moves,replaced,listeners,close,click};
}
test('both hosts consume the same encoded output directory protocol and retain the navigation owner state',()=>{
 const f=fixture('#/outputs/workbench-work/version%2F%E5%9B%BE');assert.deepEqual(f.moves,['workbench-work/version/图']);
 assert.equal(f.replaced[0][0].owner,'navigation');assert.equal(f.replaced[0][2],'/native/?path=%2Fchat%2Fold');
 f.close();assert.equal(f.listeners.size,0);
});
test('ordinary output links navigate once without mutating the current hash',()=>{
 const f=fixture();assert.equal(f.click('#/outputs/workbench-work/exact-v1'),true);assert.deepEqual(f.moves,['workbench-work/exact-v1']);assert.equal(f.replaced.length,0);
});
test('modified, external and unrelated links keep native browser behavior',()=>{
 const f=fixture();for(const link of ['https://example.com','#other','/api/files/file'])assert.equal(f.click(link),false);
 assert.equal(f.click('#/outputs/exact',{ctrlKey:true}),false);assert.deepEqual(f.moves,[]);
});
