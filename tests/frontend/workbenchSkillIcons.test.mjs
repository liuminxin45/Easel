import assert from 'node:assert/strict';
import {test} from 'node:test';
import {readFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {moduleLoader} from './helpers/modules.mjs';
const jsx={jsx:(type,props)=>({type,props:props||{}}),jsxs:(type,props)=>({type,props:props||{}})};
const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
const root=new URL('../../',import.meta.url),digest=file=>createHash('sha256').update(readFileSync(new URL(file,root))).digest('hex');
function icons(){let sequence=0;return moduleLoader({imports:{react:{useId:()=>':avatar-'+sequence++},'react/jsx-runtime':jsx,'../../assets/workbench/oil-pig-avatar.jpg?inline':'approved-pig.jpg'}})('workbench/ui/skillIcons.tsx').workbenchSkillIcons}

test('seven exact project skills share the original approved avatar with distinct independent purpose marks',()=>{
 const registry=icons(),ids=['content-production','content-writing','image-production','delivery-review','publication-analysis','reference-analysis','topic-research'],purposes=[];
 for(const id of ids){const svg=registry[id]({size:26}),all=nodes(svg);assert.equal(svg.props.viewBox,'0 0 24 24');assert.equal(svg.props.width,26);assert.equal(svg.props['data-workbench-skill-icon'],id);
  const image=all.find(node=>node.type==='image');assert.equal(image.props.href,'approved-pig.jpg');
  const badge=all.find(node=>node.props['data-workbench-skill-purpose']===id);assert.ok(badge);assert.equal(badge.props.clipPath,undefined,'the independent corner must not be inside the avatar clipping group');
  const path=nodes(badge).find(node=>node.type==='path');assert.equal(path.props.stroke,'currentColor');purposes.push(path.props.d);
 }
 assert.equal(new Set(purposes).size,7);
 assert.equal(digest('web/frontend/src/assets/workbench/oil-pig-avatar.jpg'),'fada68aa7ebdf42b9dd89f4650013b0c0ba54b867776f6ab02a9f1ee31a095b1');
});

test('unrelated native skill icons keep their exact original line SVG without project avatars',()=>{
 const registry=moduleLoader({imports:{'react/jsx-runtime':jsx}})('components/skillIconsProduce.tsx').produceSkillIcons;for(const id of ['ai-image-gen','ai-music','video-production']){const svg=registry[id]({size:26});assert.equal(svg.props.stroke,'currentColor');assert.equal(nodes(svg).some(node=>node.type==='image'),false);assert.equal(svg.props['data-workbench-skill-icon'],undefined)}
 for(const id of Object.keys(icons()))assert.equal(registry[id],undefined,'standalone Easel cannot include private skill identities');
 assert.equal(registry['unknown-private-skill'],undefined);
});

test('poster and article each retain the approved pig avatar with distinct purpose badges',()=>{
 const registry=icons(),badges=[];
 for(const id of ['oil-pig-poster','oil-pig-article']){
  const svg=registry[id]({size:26}),all=nodes(svg),image=all.find(node=>node.type==='image');
  assert.equal(image.props.href,'approved-pig.jpg');
  const badge=all.find(node=>node.props['data-workbench-skill-purpose']===id);assert.ok(badge);
  badges.push(nodes(badge).find(node=>node.type==='path').props.d);
 }
 assert.notEqual(badges[0],badges[1]);
});
