import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';

function setup(changes={}){
 const calls=[],draft={text:'稍后还要问的问题',files:[]},session={id:'same-session',profile_id:'oil-pig',source_article_id:'article-one',...changes};
 const runtime={state:{getState:()=>({running:false,accepted:true,error:''})},submit:async turn=>{calls.push(turn)}};
 const load=moduleLoader({imports:{'./chatRuntime':{sessionRuntime:()=>runtime}}});
 const client={api:{get:async()=>({session})},drafts:{get:()=>draft},invalidate:async()=>{}};
 const creation={intent:'produce',format:'poster',style:{writing:'editorial-writing',visual:'scene-visual',character:'simple-pig',layout:'page-roles'},catalog_revision:'exact-catalog',profile_revision:4,source_revision:'exact-source',note:'保留原话\n第二行'};
 const navigations=[];let opened=0;
 return {calls,draft,session,creation,navigations,async run(value=creation){return load('workbench/ui/newsCreationStart.ts').startNewsTurn(client,'article-one','oil-pig',value,{sessionId:'same-session',open:async()=>{opened++;return 'other-session'},navigate:path=>navigations.push(path)})},get opened(){return opened}};
}
test('explicit production is one native root-skill turn in the existing source session',async()=>{
 const f=setup();await f.run();assert.equal(f.calls.length,1);assert.equal(f.opened,0);
 assert.equal(f.calls[0].context.skill_id,'content-production');assert.equal(f.calls[0].context.action_id,'native');
 assert.deepEqual(f.calls[0].context.creation,f.creation);assert.equal(f.calls[0].context.article_id,'article-one');
 assert.equal(f.draft.text,'稍后还要问的问题');assert.deepEqual(f.navigations,['/chat/same-session']);
});
test('discussion carries the exact source but does not select a production skill',async()=>{
 const f=setup(),creation={...f.creation,intent:'discuss'};await f.run(creation);
 assert.equal(f.calls.length,1);assert.equal(f.calls[0].context.skill_id,undefined);assert.equal(f.calls[0].context.creation.intent,'discuss');
});
for(const field of ['pendingTurnId','pendingSubmissionId'])test(field+' navigates to the original receipt and cannot submit another turn',async()=>{
 const f=setup({[field]:'original-turn'});await assert.rejects(f.run(),/待核对/);assert.equal(f.calls.length,0);assert.equal(f.opened,0);assert.equal(f.navigations.length,1);
});
for(const fields of [{profile_id:'other-profile'},{source_article_id:'other-news'},{archived:true},{deleted_at:'saved'}])test('incompatible or read-only existing context is not silently replaced '+JSON.stringify(fields),async()=>{
 const f=setup(fields);await assert.rejects(f.run());assert.equal(f.calls.length,0);assert.equal(f.opened,0);
});
