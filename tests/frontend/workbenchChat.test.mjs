import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript');
const root=new URL('../../web/frontend/src/',import.meta.url);
const jsx={jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props})};
const react={useState:value=>[value,()=>{}],useRef:value=>({current:value}),useLayoutEffect:()=>{},useEffect:fn=>{fn()},useMemo:fn=>fn()};
function load(file,imports={},globals={}){
 const source=readFileSync(new URL(file,root),'utf8'),exports={};
 const output=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}}).outputText;
 runInNewContext(output,{exports,URL,URLSearchParams,requestAnimationFrame:fn=>fn(),document:{addEventListener:()=>{},removeEventListener:()=>{}},...globals,
  require:id=>{if(id==='react')return react;if(id==='react/jsx-runtime')return jsx;if(id in imports)return imports[id];throw Error('Unexpected runtime dependency: '+id)}});
 return exports;
}
function nodes(value){return Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[]}
const plain=value=>JSON.parse(JSON.stringify(value));
function chat(composer,callbacks={}){
 const calls={send:[],draft:[],upload:[],api:[],commands:[]};
 const bindings={text:'  原始输入\n完整保留  ',attachments:[],onTextChange:value=>calls.draft.push(value),onUpload:async files=>calls.upload.push(files),onRemoveAttachment:()=>{},label:'创作输入',...composer};
 const {default:ChatPage}=load('components/ChatPage.tsx',{'./MessageBubble':()=>{},'./QuestionCards':()=>{},'./BrushEntry':()=>{},'./icons':{},
  '../lib/api':{uploadFiles:()=>{calls.api.push('upload');throw Error('Wrong upload service')},adoptOversize:()=>{throw Error('Wrong copy service')}}},
 {fetch:()=>{calls.api.push('limits');throw Error('Wrong upload limits service')}});
 const tree=ChatPage({apiDirect:false,session:{id:'work',messages:[],title:'测试'},onSend:(...args)=>calls.send.push(args),onStop:()=>{},onResend:()=>{},composer:bindings,
  emptyState:{brand:'创作工作台',suggestions:[]},...callbacks});
 return {tree,calls,bindings};
}
test('the real Easel composer leaves controlled input and attachments until a receipt',()=>{
 const {tree,calls}=chat();
 nodes(tree).find(n=>n.type==='button'&&n.props['aria-label']==='发送').props.onClick();
 assert.equal(calls.send.length,1);assert.equal(calls.draft.length,0);assert.equal(calls.api.length,0);
});
test('IME confirmation and keyCode 229 never send or select a slash command',()=>{
 const calls=[],{tree}=chat({text:'/生成贴图',commands:[{id:'flow:poster',label:'生成贴图'}],onCommandSelect:(...args)=>calls.push(args)});
 const input=nodes(tree).find(n=>n.type==='textarea');let prevented=0;
 input.props.onCompositionStart();input.props.onKeyDown({key:'Enter',nativeEvent:{},preventDefault:()=>prevented++});
 input.props.onCompositionEnd();input.props.onKeyDown({key:'Enter',nativeEvent:{keyCode:229},preventDefault:()=>prevented++});
 assert.equal(calls.length,0);assert.equal(prevented,0);
});
test('slash selection preserves the remaining original material and does not send',()=>{
 const selected=[],{tree,calls}=chat({text:'/生成贴图  原始材料\n第二行',commands:[{id:'flow:poster',label:'生成贴图'}],onCommandSelect:(...args)=>selected.push(args)});
 const input=nodes(tree).find(n=>n.type==='textarea');input.props.onKeyDown({key:'Enter',nativeEvent:{},preventDefault:()=>{}});
 assert.deepEqual(plain(selected),[['flow:poster',' 原始材料\n第二行']]);assert.equal(calls.send.length,0);assert.equal(calls.draft.length,0);
});
test('controlled attachment selection never calls the upstream upload API',async()=>{
 const {tree,calls}=chat();
 nodes(tree).find(n=>n.type==='input'&&n.props.type==='file').props.onChange({target:{files:[{name:'素材.png'}],value:'chosen'}});
 await new Promise(resolve=>setImmediate(resolve));
 assert.equal(calls.upload.length,1);assert.equal(calls.api.length,0);
});
test('a busy private task has no callable stop or anonymous resend',()=>{
 const {tree}=chat({busy:true,status:'等待原任务回执'}, {canResend:()=>false});
 const send=nodes(tree).find(n=>n.type==='button'&&n.props['aria-label']==='发送');assert.equal(send.props.disabled,true);
 assert.ok(!nodes(tree).some(n=>n.props?.title==='停止生成'));
});
test('the shared bubble can render private replies without parsing upstream output paths',()=>{
 let parsed=0;
 const {default:MessageBubble}=load('components/MessageBubble.tsx',{'../lib/sanitize':{renderMarkdown:text=>text},
  '../lib/linkifyOutputs':{linkifyOutputs:()=>{parsed++;return 'wrong'},externalizeMediaLinks:text=>text},
  '../lib/artifacts':{extractArtifacts:()=>{parsed++;return {html:'wrong',artifacts:[],archives:[]}}},'./ArtifactGallery':()=>{},'./icons':{}});
 const text='实际成品由绑定版本的 /api/files/id 提供，outputs/example 不是下载授权。';
 const tree=MessageBubble({message:{role:'assistant',content:text},linkifyArtifactPaths:false});
 assert.equal(parsed,0);assert.ok(nodes(tree).some(n=>n.props?.dangerouslySetInnerHTML?.__html===text));
});
test('work projection keeps real partial replies and exact task failure identities',()=>{
 const {projectWorkChat}=load('workbench/ui/ChatAdapter.tsx',{'../../components/ChatPage':()=>{},'./components/icons':{},
  '@workbench/core':{statusLabel:value=>value,string:value=>typeof value==='string'?value:'',record:value=>value||{},array:value=>Array.isArray(value)?value:[]}});
 const event={id:'exact-job',kind:'create',status:'running',text:'',input:{material:'原字材料'},reply:'真实已收到的部分回复'};
 const projected=projectWorkChat({id:'w',title:'主题',history:[event,{id:'adopt',kind:'accept',text:'',reply:'',status:'completed'}]});
 assert.deepEqual(plain(projected.session.messages),[{role:'user',content:'原字材料'},{role:'assistant',content:'真实已收到的部分回复'}]);
 assert.equal(projected.events.get(1).id,'exact-job');assert.equal(projected.events.get(1).status,'running');
});
