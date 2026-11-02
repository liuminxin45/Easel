import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
import {viewStateModule} from './helpers/viewState.mjs';

const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url));
const ts=require('typescript');
const file=(path,name='成品.png')=>({type:'file',name,path,kind:'image'});
const dir=(path,name,children,meta)=>({type:'dir',path,name,children,meta});
const fixture=()=>[
 dir('works/a','同名项目',[dir('works/a/left','重复目录',[file('works/a/left/a.png')])],{title:'同名项目',work_id:'a',version_id:'a-v1'}),
 dir('works/b','同名项目',[
  dir('works/b/left','重复目录',[file('works/b/left/left.png')]),
  dir('works/b/right','重复目录',[file('works/b/right/right.png')]),
 ],{title:'同名项目',work_id:'b',version_id:'b-v2'}),
];

function gallery(initial,{jumpPath}={}){
 let data=initial,slots=[],index=0,dirty=true,tree,effects=[],props={jumpPath},handled=0;
 const details=[];
 const element=(type,props,key)=>({type,props:props||{},key});
 const exports={};
 const depsEqual=(a,b)=>a&&b&&a.length===b.length&&a.every((v,i)=>Object.is(v,b[i]));
 const hooks={
  useState(initial){const id=index++;if(!(id in slots))slots[id]=typeof initial==='function'?initial():initial;
   return [slots[id],value=>{const next=typeof value==='function'?value(slots[id]):value;if(!Object.is(next,slots[id])){slots[id]=next;dirty=true;}}];},
  useRef(value){const id=index++;return slots[id]??(slots[id]={current:value});},
  useMemo(fn,deps){const id=index++;if(!slots[id]||!depsEqual(slots[id].deps,deps))slots[id]={deps,value:fn()};return slots[id].value;},
  useCallback(fn,deps){return hooks.useMemo(()=>fn,deps);},
  useEffect(fn,deps){const id=index++;if(!slots[id]||!depsEqual(slots[id].deps,deps)){const previous=slots[id];slots[id]={deps,cleanup:previous?.cleanup};effects.push(()=>{previous?.cleanup?.();slots[id].cleanup=fn();});}},
 };
 const source=readFileSync(new URL('../../web/frontend/src/components/OutputsPage.tsx',import.meta.url),'utf8');
 const compiled=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
 runInNewContext(compiled,{exports,document:{addEventListener(){},removeEventListener(){}},require:specifier=>{
  if(specifier==='react')return hooks;
  if(specifier==='react/jsx-runtime')return {jsx:element,jsxs:element,Fragment:'fragment'};
  if(specifier==='../lib/api')return {peekApiData:()=>undefined,subscribeApiData:()=>()=>{},fetchOutputs:async()=>data,fetchOutputContent:async()=>({content:'original'}),mediaUrl:path=>'/media/'+path};
  if(specifier==='../lib/viewState')return viewStateModule(hooks);
  if(specifier==='../lib/sanitize')return {renderMarkdown:text=>text};
  if(specifier==='./DownloadLink')return {default:'DownloadLink'};
  if(specifier==='./icons')return new Proxy({},{get:(_,name)=>name});
  assert.fail('Unexpected import '+specifier);
 }});
 const render=()=>{index=0;dirty=false;details.length=0;tree=exports.default({...props,onJumpHandled:()=>{handled++;props={...props,jumpPath:undefined};dirty=true;},
  renderProjectDetails:project=>{details.push(project);return element('project-actions',{project});},canDelete:()=>false});
  const pending=effects;effects=[];pending.forEach(run=>run());};
 const settle=async()=>{for(let i=0;i<15;i++){if(dirty)render();await Promise.resolve();}assert.equal(dirty,false,'gallery reaches a stable render');};
 const all=node=>!node||typeof node!=='object'?[]:[node,...(Array.isArray(node.props?.children)?node.props.children:[node.props?.children]).flatMap(child=>Array.isArray(child)?child.flatMap(item=>all(item)):all(child))];
 const text=node=>node==null?'':Array.isArray(node)?node.map(text).join(''):typeof node==='object'?(Array.isArray(node.props?.children)?node.props.children:[node.props?.children]).map(text).join(''):String(node);
 const card=path=>all(tree).find(node=>node.key===path&&node.props.className?.split(' ').includes('gcard'));
 const click=async path=>{const node=card(path);assert.ok(node,'card exists: '+path);node.props.onClick();await settle();};
 return {settle,click,paths:()=>all(tree).filter(node=>node.props.className?.split(' ').includes('gcard')).map(node=>node.key),
  project:()=>details.at(-1),breadcrumbs:()=>text(all(tree).find(node=>node.props.className==='page-title gallery-breadcrumbs')),
  preview:()=>text(all(tree).find(node=>node.props.className==='drawer-header')),
  async jump(path){props={...props,jumpPath:path};dirty=true;await settle();},
  async refresh(next){data=next;const button=all(tree).find(node=>node.type==='button'&&text(node).includes('刷新'));assert.ok(button);button.props.onClick();await settle();},
  async crumb(label){const node=all(tree).find(node=>node.props.className==='crumb'&&text(node)===label);assert.ok(node);node.props.onClick();await settle();},
  handled:()=>handled};
}

test('same-name projects and child directories use declared paths for clicks and version actions',async()=>{
 const ui=gallery(fixture());await ui.settle();await ui.click('works/b');
 assert.equal(ui.project().path,'works/b');assert.equal(ui.project().meta.version_id,'b-v2');
 assert.deepEqual(ui.paths(),['works/b/left','works/b/right']);
 await ui.click('works/b/right');assert.deepEqual(ui.paths(),['works/b/right/right.png']);
 assert.equal(ui.project().meta.work_id,'b');assert.equal(ui.breadcrumbs(),'内容库/同名项目/重复目录');
 assert.ok(!ui.breadcrumbs().includes('works/'));
 await ui.crumb('同名项目');assert.deepEqual(ui.paths(),['works/b/left','works/b/right']);
 await ui.crumb('内容库');assert.deepEqual(ui.paths(),['works/a','works/b']);
});

test('directory and file jumps retain the exact same-name project and child directory',async()=>{
 const ui=gallery(fixture(),{jumpPath:'works/b/right'});await ui.settle();
 assert.equal(ui.handled(),1);assert.deepEqual(ui.paths(),['works/b/right/right.png']);
 assert.equal(ui.project().meta.version_id,'b-v2');
 await ui.jump('works/b/right/right.png');assert.equal(ui.handled(),2);
 assert.ok(ui.preview().includes('works/b/right/right.png'));assert.deepEqual(ui.paths(),['works/b/right/right.png']);
 assert.equal(ui.project().path,'works/b');
});

test('refresh reorder and renamed labels preserve exact project identity and use current metadata',async()=>{
 const ui=gallery(fixture());await ui.settle();await ui.click('works/b');await ui.click('works/b/right');
 const next=fixture().reverse();next[0].meta={...next[0].meta,title:'新的展示标题',version_id:'b-v3'};
 next[0].name='新的项目名';next[0].children.reverse();next[0].children[0].name='新的子目录名';
 await ui.refresh(next);
 assert.deepEqual(ui.paths(),['works/b/right/right.png']);assert.equal(ui.project().meta.version_id,'b-v3');
 assert.equal(ui.breadcrumbs(),'内容库/新的项目名/新的子目录名');
 await ui.crumb('新的项目名');assert.equal(ui.breadcrumbs(),'内容库/新的展示标题');
 assert.equal(ui.project().meta.work_id,'b');
});

test('refresh removing a selected directory stops at its actual surviving parent without name fallback',async()=>{
 const ui=gallery(fixture(),{jumpPath:'works/b/right'});await ui.settle();
 const next=fixture();next[1].children=next[1].children.filter(node=>node.path!=='works/b/right');
 await ui.refresh(next);assert.deepEqual(ui.paths(),['works/b/left']);
 assert.equal(ui.project().path,'works/b');assert.equal(ui.breadcrumbs(),'内容库/同名项目');
 await ui.click('works/b/left');assert.deepEqual(ui.paths(),['works/b/left/left.png']);
});
