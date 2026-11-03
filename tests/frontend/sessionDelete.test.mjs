import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import assert from 'node:assert/strict';
import {test} from 'node:test';

const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const source=readFileSync(new URL('../../web/frontend/src/workbench/ui/index.tsx',import.meta.url),'utf8');
const parsed=ts.createSourceFile('index.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
let handler;
function visit(node){if(ts.isVariableDeclaration(node)&&node.name.getText(parsed)==='deleteSession')handler=node.initializer.getText(parsed);ts.forEachChild(node,visit)}visit(parsed);
assert.ok(handler,'The private host owns the original Sidebar delete callback');
const code=ts.transpileModule('exports.handler='+handler,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS}}).outputText;
function fixture({confirm=true,mutate}={}){
 const state={rows:[{id:'one',revision:7},{id:'two',revision:3}],calls:[],navigated:[],path:'/chat/one',tasks:[],errors:[],prompts:[]};
 const exports={},vm={client:{mutate:async(...args)=>{state.calls.push(args);return mutate?mutate(...args):{deleted:true,session:{id:'one'}}},updateResource:(path,update)=>{state.rows=update({sessions:state.rows}).sessions}},navigation:{get path(){return state.path}},replace:path=>state.navigated.push(path)};
 const sessions={get data(){return {sessions:state.rows}}},chatAction={run:action=>{const job=action().catch(error=>state.errors.push(error));state.tasks.push(job);return job}};
 runInNewContext(code,{exports,vm,sessions,chatAction,window:{confirm:message=>{state.prompts.push(message);return confirm}},location:{origin:'https://fixture.test'},URL,record:value=>value||{},string:value=>typeof value==='string'?value:''});
 return {state,run:exports.handler,settle:()=>Promise.all(state.tasks)};
}
test('cancel uses original confirmation and sends no command',async()=>{const f=fixture({confirm:false});f.run('one');await f.settle();assert.equal(f.state.prompts[0],'确定删除这条对话？');assert.deepEqual(f.state.calls,[])});
test('successful delete keeps original revision and returns to dashboard without creating a session',async()=>{const f=fixture();f.run('one');await f.settle();assert.equal(f.state.calls.length,1);assert.equal(f.state.calls[0][1],'/api/chat/sessions');assert.equal(f.state.calls[0][2].action,'delete');assert.equal(f.state.calls[0][2].expected_revision,7);assert.deepEqual(f.state.rows.map(row=>row.id),['two']);assert.deepEqual(f.state.navigated,['/toolbox'])});
test('late delete response never steals navigation from another page',async()=>{let finish;const f=fixture({mutate:()=>new Promise(resolve=>finish=resolve)});f.run('one');f.state.path='/works';finish({deleted:true,session:{id:'one'}});await f.settle();assert.deepEqual(f.state.navigated,[]);assert.deepEqual(f.state.rows.map(row=>row.id),['two'])});
test('failed or mismatched delete receipt leaves list and navigation intact',async()=>{for(const mutate of [()=>Promise.reject(Error('original task unknown')),()=>({deleted:true,session:{id:'other'}})]){const f=fixture({mutate});f.run('one');await f.settle();assert.deepEqual(f.state.rows.map(row=>row.id),['one','two']);assert.deepEqual(f.state.navigated,[]);assert.equal(f.state.errors.length,1)}});
test('the original Sidebar delete control is enabled by the private callback',()=>{assert.match(source,/onSessionDelete:deleteSession/);assert.doesNotMatch(source,/canDeleteSession:false/)});
test('delete failures use the existing global native Notice on every page',()=>{assert.match(source,/notice:<Notice sources=\{\[\{error:chatAction\.error,feedback:chatAction\.feedback\}\]\}/)});
