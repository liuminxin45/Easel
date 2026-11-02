import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';
const jsx={jsx:(type,props)=>({type,props:props||{}}),jsxs:(type,props)=>({type,props:props||{}})};
const pure=moduleLoader(),core={...pure('workbench/core/models.ts'),...pure('workbench/core/learning.ts')};
const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
function render(missing){
 const flow={options:{data:{available_scopes:[],targets:[],manual_channels:[]}},input:{scope:[],plan:{mode:'archive'}},whole:true,canSubmit:true};
 const load=moduleLoader({imports:{'react/jsx-runtime':jsx,'@workbench/core':core,
  './hooks':{useCompletionPlan:()=>flow,useWorkbench:()=>({}),useAsyncAction:()=>({busy:false}),useDraft:()=>[{}]},
  './common':Object.fromEntries(['Drawer','Notice','Field','Panel','ActionButton'].map(name=>[name,name]))}});
 return load('workbench/ui/WorkCompletion.tsx').Completion({work:{id:'w'},version:{id:'v',label:'V1',learning:{quality:{objective_missing:missing}}},open:true,close(){},done(){}});
}
test('adoption shows actual missing-delivery messages and keeps its objective gate',()=>{
 const tree=render([{id:'independent_review',message:'本版尚未完成独立复核'},{id:'missing_image',message:'缺少本版图片'}]);
 const notice=nodes(tree).find(node=>node.type==='Notice'&&node.props.message);
 assert.equal(notice.props.message,'客观交付缺失：本版尚未完成独立复核、缺少本版图片');
 assert.equal(nodes(tree).find(node=>node.type==='ActionButton').props.disabled,true);
 assert.equal(tree.type,'Drawer');
});
test('legacy text and unknown delivery entries remain readable without stringifying objects',()=>{
 const tree=render(['保留原核对文案',{id:'missing_source'},{}]);
 const message=nodes(tree).find(node=>node.type==='Notice'&&node.props.message).props.message;
 assert.equal(message,'客观交付缺失：保留原核对文案、missing_source、待补充的交付核对项');
 assert.equal(message.includes('[object Object]'),false);
});
