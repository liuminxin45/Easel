import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url));
const ts=require('typescript'),exports={};
const source=readFileSync(new URL('../../web/frontend/src/workbench/ui/lib/localInputTitle.ts',import.meta.url),'utf8');
runInNewContext(ts.transpileModule(source,{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports});
test('local input headings use content before a type label, without changing the stored record',()=>{
 const row={id:'creator:experience',goal:'  原始目标\n第二行  ',files:[{id:'keep'}]};
 const original=JSON.stringify(row);
 assert.equal(exports.localInputTitle(row),'原始目标\n第二行');assert.equal(JSON.stringify(row),original);
});
test('known empty draft types are readable and unknown identifiers stay inside the record',()=>{
 for(const [id,title] of [['completion:work:version','采纳与交付选择'],['completion-note:work:version','采纳说明'],['easel:profile-files:oil-pig','画像资料'],['creator:experience','经验整理'],['unfamiliar:private-key','保留的输入']])assert.equal(exports.localInputTitle({id}),title);
});
