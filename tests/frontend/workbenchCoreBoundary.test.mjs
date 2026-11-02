import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {fileURLToPath} from 'node:url';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';
const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const core=fileURLToPath(new URL('../../web/frontend/src/workbench/core/',import.meta.url));
function forbidden(name,text){
 const tree=ts.createSourceFile(name,text,ts.ScriptTarget.Latest,true),errors=[];
 function visit(node){
  if((ts.isImportDeclaration(node)||ts.isExportDeclaration(node))&&node.moduleSpecifier){
   const spec=node.moduleSpecifier.text,target=spec.startsWith('.')?path.resolve(path.dirname(name),spec):spec;
   if(spec==='react'||spec.startsWith('react/')||spec.startsWith('@workbench/ui')||spec==='@workbench/platform'||target.startsWith(path.resolve(core,'../ui')+path.sep)||target.startsWith(path.resolve(core,'../platform')+path.sep))errors.push(spec);
  }
  ts.forEachChild(node,visit);
 }
 visit(tree);return errors;
}

test('core import/export graph cannot regain React, UI hooks or host dependencies',()=>{
 for(const name of fs.readdirSync(core).filter(n=>/\.tsx?$/.test(n))){
  const filename=path.join(core,name);
  assert.deepEqual(forbidden(filename,fs.readFileSync(filename,'utf8')),[],name);
 }
 const name=path.join(core,'negative.ts');
 assert.deepEqual(forbidden(name,"// import 'react';\nconst doc=\"export * from '../ui/hooks'\";"),[]);
 for(const code of ["export * from '../ui/hooks';","import {useState} from 'react';","import type {CoreProviderProps} from '../ui/hooks';","import {host} from '@workbench/platform';"])assert.equal(forbidden(name,code).length,1);
});

test('public client entry loads without React and exposes no interface hooks',()=>{
 const react=new Proxy({},{get(){assert.fail('Client barrel loaded React')}});
 const api=moduleLoader({imports:{react}})('workbench/core/index.ts');
 assert.equal(typeof api.createWorkbenchClient,'function');
 assert.equal(typeof api.ApiTransport,'function');
 for(const hook of ['CoreProvider','useWorkbench','useResource','useDraft','useAsyncAction','useCompletionPlan','useSessionMediaImage'])assert.equal(hook in api,false,hook);
});
