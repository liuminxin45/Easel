import assert from 'node:assert/strict';
import {test} from 'node:test';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {inspectCommonDependencies,inspectPrivateFeedback,readOfficialBaseline} from '../../scripts/audit_easel_base.mjs';

test('common dependency guard rejects real direct, alias, re-export, type and dynamic private edges',()=>{
 for(const source of [
  "import X from '../workbench/ui/X'", "import type {X} from '@workbench/core'",
  "export * from '../workbench/ui/X'", "type X=import('../workbench/ui/X').X",
  "const load=()=>import('../workbench/'+'ui/X')", "const icon=require('../assets/workbench/pig.jpg?inline')",
 ])assert.ok(inspectCommonDependencies(source,'web/frontend/src/components/View.tsx').length,source);
 assert.deepEqual(inspectCommonDependencies("// import X from '@workbench/core'\nconst docs=\"import('@workbench/core')\"; import X from '../lib/api'"),[]);
});

test('plain private progress mutations fail while shared status and quiet-refresh condition remain allowed',()=>{
 for(const source of ['<p role="status">正在核对…</p>',"<div role={'status'}>正在刷新…</div>"])
  assert.ok(inspectPrivateFeedback(source).length,source);
 assert.deepEqual(inspectPrivateFeedback('<>{loading&&!data&&<StatusCard>正在核对…</StatusCard>}</>'),[]);
});

test('the integrated baseline is read from the selected record without a hardcoded release fallback',()=>{
 const root=fs.mkdtempSync(path.join(os.tmpdir(),'easel-baseline-'));
 try{
  const dir=path.join(root,'docs/workbench');fs.mkdirSync(dir,{recursive:true});const file=path.join(dir,'upstream-base.json');
  for(const commit of ['1'.repeat(40),'2'.repeat(40)]){fs.writeFileSync(file,JSON.stringify({upstream_commit:commit}));assert.equal(readOfficialBaseline(root).upstream_commit,commit);}
  fs.writeFileSync(file,JSON.stringify({upstream_commit:'0f43dc9'}));assert.throws(()=>readOfficialBaseline(root),/full official baseline/);
 }finally{fs.rmSync(root,{recursive:true,force:true});}
});
