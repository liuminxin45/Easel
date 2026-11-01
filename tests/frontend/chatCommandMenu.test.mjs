import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';

const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const jsx={jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props}),Fragment:'fragment'};
const plain=value=>JSON.parse(JSON.stringify(value));
function nodes(value){return Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];}
function load(file,react,imports,globals={}){
 const source=readFileSync(new URL('../../web/frontend/src/components/'+file,import.meta.url),'utf8'),exports={};
 const {outputText}=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}});
 runInNewContext(outputText,{exports,requestAnimationFrame:fn=>fn(),document:{addEventListener(){},removeEventListener(){}},...globals,require:id=>id==='react'?react:id==='react/jsx-runtime'?jsx:id==='./useBrushPopover'?{useBrushPopover:()=>{}}:id in imports?imports[id]:assert.fail('Unexpected import '+id)});
 return exports;
}
function hooks(){
 const slots=[],deps=[],effects=[];let cursor=0;
 const effect=(fn,next)=>{const index=cursor++,old=deps[index];if(!old||!next||old.length!==next.length||next.some((value,i)=>value!==old[i])){deps[index]=next;effects.push(fn)}};
 return {react:{useState:initial=>{const index=cursor++;if(!(index in slots))slots[index]=initial;return [slots[index],next=>{slots[index]=typeof next==='function'?next(slots[index]):next}]},useRef:initial=>{const index=cursor++;if(!(index in slots))slots[index]={current:initial};return slots[index]},useEffect:effect,useLayoutEffect:effect,useMemo:fn=>fn()},
  render(fn,mount=()=>{}){cursor=0;const tree=fn();mount(tree);effects.splice(0).forEach(fn=>fn());return tree}};
}
const menu={tabs:[{id:'make',label:'创作',groups:[{label:'图文',items:[{label:'写文章',skill:'writer',status:'ready',desc:'原版说明'}]}]}]};
function fixture({commands=[{id:'first',label:'生成贴图',description:'长说明'.repeat(100)}],input='/',controlled=true}={}){
 const state=hooks(),calls={picked:[],sent:[],scroll:[],upload:0,focus:0},brush=load('BrushEntry.tsx',state.react,{'../lib/capabilityMenu':{CAPABILITY_MENU:menu}});
 const {default:ChatPage}=load('ChatPage.tsx',state.react,{'./BrushEntry':brush,'./MessageBubble':()=>{},'./QuestionCards':()=>{},'./icons':{},'../lib/api':{}},{fetch:async()=>({json:async()=>({max_mb:50})})});
 const composer={text:input,attachments:[],commands,onTextChange:value=>{composer.text=value},onUpload:async()=>{},onRemoveAttachment:()=>{},onCommandSelect:(...args)=>calls.picked.push(args)};
 const render=()=>state.render(()=>ChatPage({apiDirect:false,session:{id:'session',title:'测试',messages:[]},composer:controlled?composer:undefined,onSend:(...args)=>calls.sent.push(args),onStop:()=>{},onResend:()=>{},emptyState:{suggestions:[]}}),tree=>{
  for(const node of nodes(tree)){
   if(!node.props?.ref)continue;
   if(node.type==='textarea')node.props.ref.current={style:{},scrollHeight:44,focus:()=>calls.focus++};
   else if(node.type==='input'&&node.props.type==='file')node.props.ref.current={click:()=>calls.upload++};
   else if(node.props.className==='brush-body')node.props.ref.current={querySelector:selector=>({scrollIntoView:options=>calls.scroll.push({selector,options})})};
  }
 });
 const key=(tree,key,extra={})=>nodes(tree).find(node=>node.type==='textarea').props.onKeyDown({key,nativeEvent:{},preventDefault(){},...extra});
 return {render,calls,key,composer,brush};
}

test('slash menu uses the original brush panel, scrolling body and one shared capability row',()=>{
 const f=fixture(),tree=f.render(),popup=nodes(tree).find(node=>node.props?.className==='chat-command-menu brush-panel');
 assert.ok(popup);assert.equal(popup.props.role,'menu');assert.ok(nodes(popup).some(node=>node.props?.className==='brush-body'));
 const rows=nodes(popup).filter(node=>node.type===f.brush.BrushItem);assert.equal(rows.length,2);
 assert.equal(rows[0].props['aria-label'],'上传素材');
 const row=rows[1].type(rows[1].props);assert.equal(row.type,'button');assert.equal(row.props.className,'brush-item');
 assert.equal(nodes(row).find(node=>node.props?.className==='brush-idesc').props.children,'长说明'.repeat(100));
 assert.equal(nodes(row).find(node=>node.props?.className==='brush-il').props.children[0],'/');
 assert.equal(row.props.style.background,'var(--surface-2)');assert.equal(f.calls.sent.length,0);
});

test('keyboard selection skips disabled entries, keeps the active row visible and never sends',()=>{
 const commands=Array.from({length:25},(_,i)=>({id:'command-'+i,label:'能力'+i,disabled:i===1})),f=fixture({commands,input:'/ 原始素材\n逐字保留'});
 let tree=f.render();for(let i=0;i<22;i++){f.key(tree,'ArrowDown');tree=f.render();}
 const active=nodes(tree).find(node=>node.type===f.brush.BrushItem&&node.props.active);assert.equal(active.props['data-command-index'],23);
 assert.equal(f.calls.scroll.at(-1).selector,'[data-command-index="23"]');assert.deepEqual(plain(f.calls.scroll.at(-1).options),{block:'nearest'});
 f.key(tree,'ArrowUp');tree=f.render();f.key(tree,'Enter');
 assert.deepEqual(plain(f.calls.picked),[['command-22','原始素材\n逐字保留']]);assert.equal(f.calls.sent.length,0);
 assert.ok(!nodes(f.render()).some(node=>node.props?.className==='chat-command-menu brush-panel'));
});

test('empty and disabled-only matches consume Enter, Escape dismisses, and upload opens only the picker',()=>{
 for(const commands of [[],[{id:'blocked',label:'不可用',disabled:true}]]){
  const f=fixture({commands}),tree=f.render();f.key(tree,'Enter');assert.equal(f.calls.sent.length,0);assert.equal(f.calls.picked.length,0);
  f.key(tree,'Escape');assert.ok(!nodes(f.render()).some(node=>node.props?.className==='chat-command-menu brush-panel'));
 }
 const f=fixture(),tree=f.render(),upload=nodes(tree).find(node=>node.type===f.brush.BrushItem&&node.props['aria-label']==='上传素材');upload.props.onClick();
 assert.equal(f.calls.upload,1);assert.equal(f.calls.sent.length,0);assert.equal(f.calls.picked.length,0);
 assert.ok(!nodes(f.render()).some(node=>node.props?.className==='chat-command-menu brush-panel'));
});

test('standalone brush rows retain the original labels, descriptions, classes and prefill-only action',()=>{
 const state=hooks(),picked=[],brush=load('BrushEntry.tsx',state.react,{'../lib/capabilityMenu':{CAPABILITY_MENU:menu}});
 const render=()=>state.render(()=>brush.default({onPick:value=>picked.push(value)}));
 nodes(render()).find(node=>node.type==='button').props.onClick();const row=nodes(render()).find(node=>node.type===brush.BrushItem),button=row.type(row.props);
 assert.equal(button.props.className,'brush-item');assert.equal(button.props.style,undefined);
 assert.equal(nodes(button).find(node=>node.props?.className==='brush-il').props.children[1],'写文章');
 assert.equal(nodes(button).find(node=>node.props?.className==='brush-idesc').props.children,'原版说明');button.props.onClick();
 assert.deepEqual(picked,['帮我做「写文章」']);
 const standalone=fixture({controlled:false});assert.ok(!nodes(standalone.render()).some(node=>node.props?.className==='chat-command-menu brush-panel'));
});
