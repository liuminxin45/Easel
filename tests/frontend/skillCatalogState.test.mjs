import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
import {viewStateModule} from './helpers/viewState.mjs';

const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const element=(type,props)=>({type,props}),jsx={jsx:element,jsxs:element,Fragment:'fragment'};
const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
const text=value=>Array.isArray(value)?value.map(text).join(''):value&&typeof value==='object'?text(value.props?.children):value==null?'':String(value);
const skill={name:'test-skill',layer:'produce',description:'测试技能的真实说明',needsApi:false};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(){
 let cursor=0,fetches=0;const slots=[],deps=[],effects=[],requests=[];
 const react={
  useState:initial=>{const at=cursor++;if(!(at in slots))slots[at]=typeof initial==='function'?initial():initial;return [slots[at],value=>{slots[at]=typeof value==='function'?value(slots[at]):value}]},
  useRef:initial=>{const at=cursor++;return slots[at]??=( {current:initial} )},
  useCallback:fn=>{cursor++;return fn},
  useMemo:fn=>{cursor++;return fn()},
  useEffect:(effect,next)=>{const at=cursor++,old=deps[at];if(!old||old.length!==next.length||next.some((value,index)=>value!==old[index])){deps[at]=next;effects.push(effect)}},
 };
 const exports={},source=readFileSync(new URL('../../web/frontend/src/components/SkillPage.tsx',import.meta.url),'utf8');
 const imports={react,'react/jsx-runtime':jsx,'../lib/viewState':viewStateModule(react),'../lib/api':{fetchSkills:()=>{fetches++;return new Promise((resolve,reject)=>requests.push({resolve,reject}))}},'./SkillDrawer':'SkillDrawer','../lib/skillDisplayNames':{displayName:value=>value},'./icons':new Proxy({},{get:()=>()=>null})};
 Object.assign(imports,{'./skillIconsPlanning':{planningSkillIcons:{}},'./skillIconsProduce':{produceSkillIcons:{}},'./skillIconsPublish':{publishSkillIcons:{}},'./skillIconsBrand':{brandSkillIcons:{}}});
 runInNewContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,{exports,require:id=>imports[id]??assert.fail('Unexpected import '+id)});
 const render=()=>{cursor=0;const tree=exports.default({persona:'author'});effects.splice(0).forEach(effect=>effect());return tree};
 return {render,requests,get fetches(){return fetches}};
}
const cards=tree=>nodes(tree).filter(node=>node.props?.className?.split(' ').includes('skill-card'));
const search=tree=>nodes(tree).find(node=>node.type==='input');

test('standalone Easel skill loading and refresh use the same no-false-empty contract',async()=>{
 const f=fixture();let tree=f.render();assert.equal(f.fetches,1);assert.equal(tree.props['data-catalog-state'],'loading');assert.doesNotMatch(text(tree),/没有匹配|暂无可用/);
 f.requests[0].resolve([skill]);await tick();tree=f.render();assert.equal(cards(tree).length,1);assert.equal(tree.props['data-catalog-state'],'ready');
 cards(tree)[0].props.onClick();tree=f.render();nodes(tree).find(node=>node.type==='SkillDrawer').props.onConfigured();tree=f.render();
 assert.equal(f.fetches,2);assert.equal(cards(tree).length,1);assert.equal(tree.props['data-catalog-state'],'ready');assert.doesNotMatch(text(tree),/正在读取/);
 f.requests[1].reject(Error('offline'));await tick();tree=f.render();assert.equal(cards(tree).length,1);assert.equal(tree.props['data-catalog-state'],'error');assert.match(text(tree),/加载 SKILL 列表失败/);
 nodes(tree).find(node=>node.type==='SkillDrawer').props.onConfigured();f.requests[2].resolve([]);await tick();tree=f.render();assert.equal(tree.props['data-catalog-state'],'empty');assert.match(text(tree),/暂无可用技能/);assert.doesNotMatch(text(tree),/加载 SKILL 列表失败/);
});


test('native skill catalog distinguishes an in-flight read, an empty directory and an unmatched search',async()=>{
 const f=fixture();let tree=f.render();assert.equal(f.fetches,1);assert.equal(tree.props['data-catalog-state'],'loading');assert.match(text(tree),/正在读取技能/);assert.doesNotMatch(text(tree),/没有匹配|暂无可用技能|共 0 个技能/);
 f.requests[0].resolve([]);await tick();tree=f.render();assert.equal(tree.props['data-catalog-state'],'empty');assert.match(text(tree),/暂无可用技能/);
 search(tree).props.onChange({target:{value:' missing '}});tree=f.render();assert.match(text(tree),/没有匹配「missing」的技能/);search(tree).props.onChange({target:{value:'  '}});assert.match(text(f.render()),/暂无可用技能/);
});

test('native initial failure stays visible instead of falsely rendering an empty catalog',async()=>{
 const f=fixture();f.render();f.requests[0].reject(Error('offline'));await tick();const tree=f.render();assert.equal(tree.props['data-catalog-state'],'error');assert.match(text(tree),/加载 SKILL 列表失败/);assert.doesNotMatch(text(tree),/正在读取技能|暂无可用技能|没有匹配/);
 const fresh=fixture();fresh.render();fresh.requests[0].resolve([skill]);await tick();assert.equal(cards(fresh.render()).length,1);
});
