import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';

const helpers=moduleLoader()('workbench/ui/newsCreation.ts');
test('new drafts select the explicit oil-pig format without changing explicit native skills',()=>{
 for(const [format,id] of [['poster','oil-pig-poster'],['article','oil-pig-article']]){
  assert.equal(helpers.creationDraftSkillId(format),id);
  assert.equal(helpers.creationDraftSkillId(format,'content-production'),id);
  assert.equal(helpers.creationDraftSkillId(format,'topic-research'),'topic-research');
 }
 assert.throws(()=>helpers.creationDraftSkillId(undefined),/请选择|明确选择/);
});

function fixture(format){
 const work={id:'saved-work',format,creator:{id:'profile'},draft:{title:'原题',material:' 原始材料\n保留 ',guidance:'本轮要求',files:[{id:'file',name:'参考.png'}],command:{skill_id:'content-production'}},pending:[]};
 const before=JSON.stringify(work),calls=[],jobs=[];
 const core={record:v=>v&&typeof v==='object'?v:{},string:(v,f='')=>typeof v==='string'?v:f,array:v=>Array.isArray(v)?v:[],sessionOpenFlows:()=>({open:async input=>calls.push(input)})};
 const action={busy:false,run:fn=>{const job=Promise.resolve().then(fn);jobs.push(job);return job}};
 const vm={client:{},service:{saveDraft:()=>assert.fail('opening unchanged material cannot rewrite historical input')}};
 const jsx={jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})};
 const load=moduleLoader({imports:{react:{},'react/jsx-runtime':jsx,'@workbench/core':core,'./hooks':{useWorkbench:()=>vm,useDraft:()=>[structuredClone(work.draft),()=>{}],useAsyncAction:()=>action},'./common':{Field:'Field',Notice:'Notice',ActionButton:'ActionButton',Pending:'Pending'}}});
 const tree=load('workbench/ui/DraftOperations.tsx').DraftOperations({work});
 const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
 return {work,before,calls,jobs,click:label=>nodes(tree).find(n=>n.props?.children===label).props.onClick()};
}
for(const [format,id] of [['poster','oil-pig-poster'],['article','oil-pig-article']])test(`saved ${format} draft opens a native skill draft without sending or rewriting its original`,async()=>{
 const f=fixture(format);f.click('按当前草稿制作');await Promise.all(f.jobs);
 assert.equal(f.calls.length,1);assert.equal(f.calls[0].draft.command.skill_id,id);
 assert.equal(f.calls[0].draft.files[0].id,'file');assert.match(f.calls[0].draft.text,/ 原始材料\n保留 /);
 assert.equal(JSON.stringify(f.work),f.before);
});
test('unknown saved format does not guess a workflow or start a conversation',async()=>{
 const f=fixture('unknown');f.click('按当前草稿制作');await assert.rejects(f.jobs[0],/明确选择/);assert.equal(f.calls.length,0);assert.equal(JSON.stringify(f.work),f.before);
});
