import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript'),exports={};
const registry=JSON.parse(readFileSync(new URL('../../web/frontend/src/workbench/usage_registry.json',import.meta.url),'utf8'));
runInNewContext(ts.transpileModule(readFileSync(new URL('../../web/frontend/src/workbench/core/usage.ts',import.meta.url),'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,{exports,URL,require:()=>({default:registry})});

test('current native destinations record their actual screen without storing URL parameters',()=>{
 const cases={'/toolbox?section=profiles&item=PRIVATE':'profiles','/toolbox?section=skills':'skills','/toolbox?section=research':'research','/chat':'chat.list','/chat/private-session':'chat.detail','/works':'works.list','/works/work/version':'work.detail','/works/new':'work.create','/settings?panel=more':'settings','/settings?panel=usage':'settings','/toolbox?section=insights':'home'};
 for(const [path,screen] of Object.entries(cases)){
  assert.equal(exports.usageScreen(path),screen,path);
  assert.equal(exports.usageScreen('/native/?'+new URLSearchParams({path})),screen,path);
 }
});

test('retired screen enums remain accepted for existing queued history',()=>{
 for(const id of registry.retired.screens)assert.ok(registry.screens[id]);
 for(const id of registry.retired.actions)assert.ok(registry.actions[id]);
});
