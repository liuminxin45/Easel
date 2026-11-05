import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';
const jsx={jsx:(type,props)=>({type,props:props||{}}),jsxs:(type,props)=>({type,props:props||{}})},nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];

test('saved business draft opens an ordinary native skill with exact material and no private planning request',async()=>{
 const draft={revision:4,title:' Exact title ',material:'Original\nmaterial',guidance:'Raw instruction',files:[{id:'kept-file',name:'reference.png'}],creative:{recipe:{prompt_text:'Explicit original recipe'}}},work={id:'saved-work',format:'poster',title:'Saved',draft,creator:{id:'author'},pending:[]},opens=[],writes=[];
 const vm={service:{saveDraft:async(...args)=>writes.push(args)},client:{invalidate(){}}},hooks={useWorkbench:()=>vm,useDraft:()=>[draft,()=>assert.fail('Opening must not replace the draft')],useAsyncAction:()=>({busy:false,run:fn=>fn()})};
 const core={record:v=>v||{},string:(v,fallback='')=>typeof v==='string'?v:fallback,array:v=>Array.isArray(v)?v:[],sessionOpenFlows:()=>({open:async input=>{opens.push(input);return {id:'ordinary-chat'}}})};
 const load=moduleLoader({imports:{react:{},'react/jsx-runtime':jsx,'@workbench/core':core,'./hooks':hooks,'./common':Object.fromEntries(['Field','Notice','ActionButton','Pending'].map(name=>[name,name]))}}),tree=load('workbench/ui/DraftOperations.tsx').DraftOperations({work});
 await nodes(tree).find(node=>node.props.children==='按当前草稿制作').props.onClick();
 assert.equal(writes.length,0);assert.equal(opens.length,1);assert.equal(opens[0].profileId,'author');assert.equal(opens[0].query,undefined);
 assert.equal(opens[0].draft.text,' Exact title \n\nOriginal\nmaterial\n\nRaw instruction\n\nExplicit original recipe');assert.deepEqual(opens[0].draft.files,draft.files);
 const command=opens[0].draft.command;assert.equal(command.skill_id,'oil-pig-poster');assert.equal(command.action_id,'native');assert.equal(command.requires_plan,false);assert.equal(command.version,undefined);assert.equal(command.trial,undefined);
 assert.deepEqual(work.draft,draft);assert.ok(!nodes(tree).some(node=>node.type?.name==='CreatorControls'));
});
