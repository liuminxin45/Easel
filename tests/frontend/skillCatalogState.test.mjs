import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';

const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const element=(type,props)=>({type,props}),jsx={jsx:element,jsxs:element,Fragment:'fragment'};
const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
const text=value=>Array.isArray(value)?value.map(text).join(''):value&&typeof value==='object'?text(value.props?.children):value==null?'':String(value);
const skill={name:'test-skill',layer:'produce',description:'测试技能的真实说明',needsApi:false};
const tick=()=>new Promise(resolve=>setImmediate(resolve));
function fixture(){
 let cursor=0,fetches=0;const slots=[],deps=[],effects=[],requests=[];
 const react={
  useState:initial=>{const at=cursor++;if(!(at in slots))slots[at]=initial;return [slots[at],value=>{slots[at]=typeof value==='function'?value(slots[at]):value}]},
  useMemo:fn=>{cursor++;return fn()},
  useEffect:(effect,next)=>{const at=cursor++,old=deps[at];if(!old||old.length!==next.length||next.some((value,index)=>value!==old[index])){deps[at]=next;effects.push(effect)}},
 };
 const exports={},source=readFileSync(new URL('../../web/frontend/src/components/SkillPage.tsx',import.meta.url),'utf8');
 const imports={react,'react/jsx-runtime':jsx,'../lib/api':{fetchSkills:()=>{fetches++;return new Promise((resolve,reject)=>requests.push({resolve,reject}))}},'./SkillDrawer':'SkillDrawer','../lib/skillDisplayNames':{displayName:value=>value},'./icons':new Proxy({},{get:()=>()=>null})};
 runInNewContext(ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText,{exports,require:id=>imports[id]??assert.fail('Unexpected import '+id)});
 const render=catalog=>{cursor=0;const tree=exports.default({persona:'author',...(catalog?{catalog}:{})});effects.splice(0).forEach(effect=>effect());return tree};
 return {render,requests,get fetches(){return fetches}};
}
const cards=tree=>nodes(tree).filter(node=>node.props?.className?.split(' ').includes('skill-card'));
const search=tree=>nodes(tree).find(node=>node.type==='input');

test('hosted skill catalog distinguishes initial loading from an actual empty result',()=>{
 const f=fixture();let tree=f.render({items:[],loading:true});
 assert.equal(tree.props['data-catalog-state'],'loading');assert.equal(tree.props['aria-busy'],true);
 assert.match(text(tree),/正在读取技能/);assert.doesNotMatch(text(tree),/没有匹配|暂无可用技能|共 0 个技能/);assert.equal(f.fetches,0);
 tree=f.render({items:[],loading:false});assert.equal(tree.props['data-catalog-state'],'empty');assert.match(text(tree),/暂无可用技能/);
 search(tree).props.onChange({target:{value:' missing '}});tree=f.render({items:[],loading:false});assert.match(text(tree),/没有匹配「missing」的技能/);
 search(tree).props.onChange({target:{value:'  '}});assert.match(text(f.render({items:[],loading:false})),/暂无可用技能/);
});

test('background catalog refresh leaves loaded cards in place without a routine loading notice',()=>{
 const f=fixture();let tree=f.render({items:[skill],loading:false});assert.equal(cards(tree).length,1);
 tree=f.render({items:[skill],loading:true});assert.equal(cards(tree).length,1);assert.equal(tree.props['data-catalog-state'],'ready');assert.equal(tree.props['aria-busy'],undefined);assert.doesNotMatch(text(tree),/正在读取|暂无可用|没有匹配/);
 tree=f.render({items:[skill],loading:false,error:'服务连接失败，原有技能保留'});assert.equal(cards(tree).length,1);assert.equal(tree.props['data-catalog-state'],'error');assert.match(text(nodes(tree).find(node=>node.props.role==='alert')),/服务连接失败/);
});

test('standalone Easel skill loading and refresh use the same no-false-empty contract',async()=>{
 const f=fixture();let tree=f.render();assert.equal(f.fetches,1);assert.equal(tree.props['data-catalog-state'],'loading');assert.doesNotMatch(text(tree),/没有匹配|暂无可用/);
 f.requests[0].resolve([skill]);await tick();tree=f.render();assert.equal(cards(tree).length,1);assert.equal(tree.props['data-catalog-state'],'ready');
 cards(tree)[0].props.onClick();tree=f.render();nodes(tree).find(node=>node.type==='SkillDrawer').props.onConfigured();tree=f.render();
 assert.equal(f.fetches,2);assert.equal(cards(tree).length,1);assert.equal(tree.props['data-catalog-state'],'ready');assert.doesNotMatch(text(tree),/正在读取/);
 f.requests[1].reject(Error('offline'));await tick();tree=f.render();assert.equal(cards(tree).length,1);assert.equal(tree.props['data-catalog-state'],'error');assert.match(text(tree),/加载 SKILL 列表失败/);
 nodes(tree).find(node=>node.type==='SkillDrawer').props.onConfigured();f.requests[2].resolve([]);await tick();tree=f.render();assert.equal(tree.props['data-catalog-state'],'empty');assert.match(text(tree),/暂无可用技能/);assert.doesNotMatch(text(tree),/加载 SKILL 列表失败/);
});

test('a host-provided failure stays visible and a new host catalog does not inherit standalone failures',async()=>{
 const f=fixture();f.render();f.requests[0].reject(Error('offline'));await tick();let tree=f.render();assert.equal(tree.props['data-catalog-state'],'error');
 tree=f.render({items:[skill],loading:false,error:''});assert.equal(tree.props['data-catalog-state'],'ready');assert.doesNotMatch(text(tree),/加载 SKILL 列表失败/);
 tree=f.render({items:[],loading:true,error:'读取被拒绝'});assert.equal(tree.props['data-catalog-state'],'error');assert.match(text(tree),/读取被拒绝/);assert.doesNotMatch(text(tree),/正在读取|暂无可用|没有匹配/);
});
