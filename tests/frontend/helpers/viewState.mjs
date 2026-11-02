import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
const require=createRequire(new URL('../../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
export function viewStateModule(react){
 const exports={},source=readFileSync(new URL('../../../web/frontend/src/lib/viewState.ts',import.meta.url),'utf8');
 runInNewContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText,{exports,require:name=>{if(name==='react')return react;throw Error(name)}});
 return exports;
}
