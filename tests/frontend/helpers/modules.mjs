import fs from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {webcrypto} from 'node:crypto';
import {fileURLToPath} from 'node:url';
const require=createRequire(new URL('../../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const sourceRoot=new URL('../../../web/frontend/src/',import.meta.url);
export function moduleLoader({imports={},globals={}}={}){
 const cache=new Map();
 return function load(name){
  const file=name instanceof URL?name:path.isAbsolute(name)?name:new URL(name,sourceRoot),filename=file instanceof URL?fileURLToPath(file):file;
  if(cache.has(filename))return cache.get(filename);
  if(filename.endsWith('.json'))return JSON.parse(fs.readFileSync(file,'utf8'));
  const exports={};cache.set(filename,exports);
  const settings={module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true};
  runInNewContext(ts.transpileModule(fs.readFileSync(file,'utf8'),{fileName:filename,compilerOptions:settings}).outputText,{exports,URL,URLSearchParams,Error,TypeError,TextEncoder,TextDecoder,Blob,File,Response,Headers,AbortController,AbortSignal,crypto:webcrypto,performance,fetch,setTimeout,clearTimeout,...globals,require:id=>{
   if(Object.hasOwn(imports,id))return imports[id];if(!id.startsWith('.'))return require(id);
   let target=path.resolve(path.dirname(filename),id);if(!fs.existsSync(target))target+=fs.existsSync(target+'.ts')?'.ts':'.tsx';return load(target);
  }});return exports;
 };
}
