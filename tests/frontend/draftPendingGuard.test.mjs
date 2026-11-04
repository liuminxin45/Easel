import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';

function fixture(initial=[]){
 const saved=new Map(initial.map(([key,value])=>['toolbox:draft:'+key,JSON.stringify(value)]));
 const storage={get length(){return saved.size},key:index=>[...saved.keys()][index]??null,getItem:key=>saved.get(key)??null,setItem:(key,value)=>saved.set(key,value),removeItem:key=>saved.delete(key)};
 const {DraftRepository}=moduleLoader()('workbench/core/persistence.ts');
 return {saved,storage,drafts:new DraftRepository(storage),reload:()=>new DraftRepository(storage)};
}
const flow=phase=>({phase,session_id:'acknowledged-session',request:{action:'create',id:'exact-original-operation'},draft:{text:'  exact draft\nsecond line  ',files:[{id:'original-attachment'}]}});

test('acknowledged ready/opened session requests remain byte-for-byte readable without blocking upgrade',()=>{
 const f=fixture([['session-open:ready',flow('ready')],['session-open:opened',flow('opened')]]),original=[...f.saved];
 assert.equal(f.drafts.hasPending(),false);assert.equal(f.drafts.list().length,2);
 assert.equal(f.drafts.get('session-open:opened').request.id,'exact-original-operation');
 assert.deepEqual([...f.saved],original,'classification must not delete or rewrite recovery/history evidence');
 assert.equal(f.reload().hasPending(),false,'the same persisted terminal evidence stays safe after reopening');
});

test('creating/checking/unknown requests and terminal-looking flows without a real session remain fenced',()=>{
 for(const phase of ['creating','checking','unknown']){
  const f=fixture([['session-open:uncertain',flow(phase)]]);assert.equal(f.drafts.hasPending(),true,phase);
 }
 for(const session_id of [undefined,null,'','   ',123])for(const phase of ['opened','ready']){
  const f=fixture([['session-open:unconfirmed',{...flow(phase),session_id}]]);assert.equal(f.drafts.hasPending(),true,phase+' without an acknowledged session');
 }
});

test('an acknowledged session never masks another active or unknown write marker',()=>{
 for(const field of ['pending','pendingId','operation','pendingSave','pendingFinalize']){
  const f=fixture([['session-open:confirmed',{...flow('opened'),[field]:{state:'unknown',id:'original-write'}}]]);
  assert.equal(f.drafts.hasPending(),true,field+' must remain protected');
 }
 const f=fixture([['session-open:confirmed',flow('opened')],['native:pending:session-open:op',{operation:{id:'accepted-original',uncertain:true}}]]);
 assert.equal(f.drafts.hasPending(),true);assert.equal(f.drafts.pending().length,1);
 assert.equal(f.drafts.pending()[0].operation.id,'accepted-original');
});

test('only the session-open namespace receives terminal request classification',()=>{
 for(const key of ['chat:session','profile-save:p','session-open-history:old']){
  assert.equal(fixture([[key,flow('opened')]]).drafts.hasPending(),true,key);
 }
});

test('completion updates the existing pending index while another in-flight request still blocks',()=>{
 const f=fixture([['session-open:a',flow('creating')],['session-open:b',flow('checking')]]);
 assert.equal(f.drafts.pending().length,2);
 f.drafts.set('session-open:a',flow('ready'));assert.equal(f.drafts.pending().length,1);assert.equal(f.drafts.hasPending(),true);
 f.drafts.set('session-open:b',flow('opened'));assert.equal(f.drafts.hasPending(),false);
 f.drafts.set('session-open:a',{...flow('ready'),pendingSave:{id:'not-yet-durable'}});assert.equal(f.drafts.hasPending(),true);
 assert.equal(f.reload().hasPending(),true);
});
