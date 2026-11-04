import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';

const jsx={jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})};
const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];

test('copy success stays on the button and failed copy exposes a status card',async()=>{
 let state='idle',fail=false;
 const load=moduleLoader({imports:{react:{useState:()=>[state,value=>{state=value}]},'react/jsx-runtime':jsx},globals:{navigator:{clipboard:{writeText:async()=>{if(fail)throw Error('denied')}}}}});
 const CopyableText=load('components/CopyableText.tsx').default;
 const render=()=>CopyableText({label:'正文',text:'原文'});
 let tree=render(),button=nodes(tree).find(node=>node.type==='button');button.props.onClick();await new Promise(resolve=>setImmediate(resolve));tree=render();
 assert.equal(nodes(tree).find(node=>node.type==='button').props.children,'已复制');
 assert.equal(nodes(tree).filter(node=>node.type==='span'&&node.props.role==='status').length,0);
 fail=true;button=nodes(tree).find(node=>node.type==='button');button.props.onClick();await new Promise(resolve=>setImmediate(resolve));tree=render();
 const card=nodes(tree).find(node=>typeof node.type==='function'&&node.type.name==='StatusCard');
 assert.equal(card.props.tone,'error');assert.match(card.props.children,/复制未成功/);
});
