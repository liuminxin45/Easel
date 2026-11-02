import assert from 'node:assert/strict';
import fs from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';
const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const source=fs.readFileSync(new URL('../../web/frontend/src/components/SettingsPanel.tsx',import.meta.url),'utf8');
const tree=ts.createSourceFile('SettingsPanel.tsx',source,ts.ScriptTarget.Latest,true,ts.ScriptKind.TSX);
const component=tree.statements.find(node=>ts.isFunctionDeclaration(node)&&node.name?.text==='SettingsPanel');
function statements(names){return names.map(name=>component.body.statements.find(node=>ts.isVariableStatement(node)&&node.declarationList.declarations.some(decl=>decl.name.getText(tree)===name)).getText(tree)).join('\n')}
const compile=text=>ts.transpileModule(text,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText;

test('settings close can veto discarded secrets and navigation does not double-confirm an approved close',()=>{
 let accepted=false,confirmations=0,closed=0;
 const api=runInNewContext(compile(statements(['dirty','checkLeave','onClose'])+'\n({dirty,checkLeave,onClose});'),{
  useRef:initial=>({current:initial}),useCallback:callback=>callback,
  window:{confirm:()=>{confirmations++;return accepted}},onRequestClose:()=>closed++,
 });
 api.dirty.current=()=>true;
 api.onClose();assert.equal(confirmations,1);assert.equal(closed,0);assert.equal(api.checkLeave(),false);
 accepted=true;api.onClose();assert.equal(closed,1);const before=confirmations;
 assert.equal(api.checkLeave(),true);assert.equal(confirmations,before,'the navigation guard shares the same approved discard');
});

test('installation polling is one read per job and ignores a result arriving after unmount',async()=>{
 const callbacks=new Map(),timers=new Map();let index=0,complete,reads=0,updates=0;
 const document={hidden:false,addEventListener:(name,fn)=>callbacks.set(fn,name),removeEventListener:(_,fn)=>callbacks.delete(fn)};
 const load=moduleLoader({globals:{document,setTimeout:(fn,ms)=>{timers.set(++index,{fn,ms});return index},clearTimeout:id=>timers.delete(id)}});
 const alive={current:true},lifeEpoch={current:1},polls={current:new Map()};
 const pollJob=runInNewContext(compile(statements(['pollJob'])+'\npollJob;'),{
  useCallback:callback=>callback,Promise,alive,lifeEpoch,polls,
  visiblePoll:load('lib/visiblePoll.ts').visiblePoll,
  fetchEnvJob:()=>{reads++;return new Promise(resolve=>{complete=resolve})},setJobs:()=>updates++,
 });
 const first=pollJob('tool','original-job');assert.equal(pollJob('tool','original-job'),first);assert.equal(timers.size,1);
 const timer=[...timers.values()][0];timers.clear();timer.fn();await Promise.resolve();assert.equal(reads,1);
 for(const fn of callbacks.keys())fn();assert.equal(reads,1);
 alive.current=false;lifeEpoch.current++;for(const poll of polls.current.values())poll.stop();await first;
 complete({state:'ok',lines:['done']});for(let i=0;i<12;i++)await Promise.resolve();
 assert.equal(updates,0);assert.equal(reads,1);assert.equal(timers.size,0);assert.equal(callbacks.size,0);
});

test('a delayed channel save never overwrites input edited after that exact submission',async()=>{
 const row={slot:'custom',name:'provider',model:'old-model',baseUrl:'https://example.invalid',role:'主',protocol:'openai',keyNew:'ORIGINAL_SECRET'};
 let current=[row],complete;
 const baseline={current:{}},discardApproved={current:false};
 const save=runInNewContext(compile(statements(['saveCurrent'])+'\nsaveCurrent;'),{
  useCallback:callback=>callback,JSON,PLACEHOLDERS:new Set(),chan:'chat',chatRows:[row],transRows:[],mediaRows:{},
  setSaving(){},setSavedNote(){},saveModelConfig:()=>new Promise(resolve=>{complete=resolve}),
  setChatRows:next=>{current=typeof next==='function'?next(current):next},setTransRows(){},setMediaRows(){},
  baseline,discardApproved,refreshEnv:async()=>{},setTimeout(){},hostManaged:true,reportSavedNote(error){throw error},
 });
 const pending=save();current=[{...row,model:'newly-edited-model',keyNew:'LATER_SECRET'}];
 complete({channels:{chat:{rows:[{...row,keyNew:'',keyMasked:'masked',model:'old-model'}]}}});await pending;
 assert.equal(current[0].model,'newly-edited-model');assert.equal(current[0].keyNew,'LATER_SECRET');
 assert.equal(JSON.parse(baseline.current.chat)[0].keyNew,'');
});
