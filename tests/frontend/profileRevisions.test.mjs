import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {createContext,runInContext} from 'node:vm';
import {test} from 'node:test';

const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url));
const ts=require('typescript');
const source=readFileSync(new URL('../../web/frontend/src/components/ProfilePage.tsx',import.meta.url),'utf8');
const ast=ts.createSourceFile('ProfilePage.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let handler;
function walk(node){
 if(ts.isVariableDeclaration(node)&&node.name.getText(ast)==='handleSave')handler=node;
 ts.forEachChild(node,walk);
}
walk(ast);
assert.ok(handler);
const compiled=ts.transpileModule('const '+handler.getText(ast)+'; exports.save=handleSave;',{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;

function fixture(save){
 let files=[{filename:'identity.md',content:'server original'}],revision=7,toast='',saving='',refreshes=0;
 const exports={},context=createContext({exports,Error,persona:'creator-exact',drafts:{'identity.md':'submitted original bytes'},fileRevision:revision,savingFile:saving,
  DIM_META:{'identity.md':{label:'身份定位'}},savePersonaFile:save,setFiles:update=>{files=update(files)},
  changedFields:{current:{'identity.md':'submitted original bytes'}},draftStore:undefined,
  setFileRevision:next=>{revision=next},setSavingFile:next=>{saving=next},showToast:text=>{toast=text},onFileSaved:()=>{refreshes++},
  setServerRevision:()=>{},
 });
 runInContext(compiled,context);
 return {context,save:exports.save,get files(){return files},get revision(){return revision},get toast(){return toast},get saving(){return saving},get refreshes(){return refreshes}};
}

test('a delayed profile save uses its captured parent revision and preserves later typing',async()=>{
 let finish;const calls=[];
 const f=fixture((...args)=>{calls.push(args);return new Promise(resolve=>{finish=resolve})});
 const pending=f.save('identity.md');
 assert.deepEqual(calls[0],['creator-exact','identity.md','submitted original bytes',7]);
 f.context.drafts={'identity.md':'typed while the request was running'};
 finish({ok:true,revision:8});await pending;
 assert.equal(f.files[0].content,'submitted original bytes');
 assert.equal(f.context.drafts['identity.md'],'typed while the request was running');
 assert.equal(f.revision,8);
 assert.equal(f.refreshes,1);
 assert.equal(f.saving,'');
});

test('a stale profile parent revision cannot be silently advanced after conflict',async()=>{
 const f=fixture(async(_persona,_filename,_body,expected)=>{
  assert.equal(expected,7);throw Object.assign(Error('画像已有新修订，请重新核对'),{status:409});
 });
 await f.save('identity.md');
 assert.equal(f.files[0].content,'server original');
 assert.equal(f.revision,7);
 assert.equal(f.context.drafts['identity.md'],'submitted original bytes');
 assert.match(f.toast,/新修订/);
 assert.equal(f.refreshes,0);
});

test('the same native handler retains the upstream unversioned API default',async()=>{
 const calls=[],f=fixture(async(...args)=>{calls.push(args);return {ok:true}});
 f.context.fileRevision=undefined;
 await f.save('identity.md');
 assert.equal(calls[0][3],undefined);
 assert.equal(f.files[0].content,'submitted original bytes');
 assert.equal(f.context.drafts['identity.md'],'submitted original bytes');
});
