import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';

const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url));
const ts=require('typescript');
const json=value=>JSON.parse(JSON.stringify(value));

// Execute the real native components with a small React hook host. Persistence
// assertions observe user events and rejected/accepted API calls, not markup copies.
function component(name,api){
 const source=readFileSync(new URL('../../web/frontend/src/components/'+name+'.tsx',import.meta.url),'utf8');
 const compiled=ts.transpileModule(source+(name==='ProfilePage'?'\nexport {ProfileDetail};':''),{
  compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true},
 }).outputText;
 const hooks=[],effects=[];let cursor=0;
 const react={
  useState:initial=>{const index=cursor++;if(!(index in hooks))hooks[index]=typeof initial==='function'?initial():initial;return [hooks[index],next=>{hooks[index]=typeof next==='function'?next(hooks[index]):next}]},
  useRef:initial=>{const index=cursor++;return hooks[index]??=( {current:initial} )},
  useEffect:(effect,deps)=>{const index=cursor++,previous=hooks[index];if(!previous||deps.some((value,i)=>!Object.is(value,previous[i]))){hooks[index]=deps;effects.push(effect)}},
  useCallback:fn=>{cursor++;return fn},useMemo:fn=>{cursor++;return fn()},
 };
 const exports={};
 runInNewContext(compiled,{exports,Error,JSON,Object,setTimeout:()=>0,window:{confirm:()=>true},require:specifier=>{
  if(specifier==='react')return react;
  if(specifier==='react/jsx-runtime')return {jsx:(type,props)=>({type,props}),jsxs:(type,props)=>({type,props}),Fragment:'fragment'};
  if(specifier==='../lib/api')return api;
  if(specifier==='../lib/sanitize')return {renderMarkdown:value=>value};
  if(specifier==='./IdeasView')return {__esModule:true,default:'IdeasView',NEXT:{pending:'doing',doing:'done',done:'pending'}};
  if(specifier==='./icons')return new Proxy({},{get:()=>function Icon(){}});
  throw Error('Unexpected import '+specifier);
 }});
 const page=name==='ProfilePage'?exports.ProfileDetail:exports.default;
 return {
  render(props){cursor=0;return page(props)},
  async effects(){for(const effect of effects.splice(0))effect();await new Promise(resolve=>setImmediate(resolve))},
 };
}

function nodes(tree,predicate){
 if(!tree||typeof tree!=='object')return [];
 const children=tree.props?.children;
 return [...(predicate(tree)?[tree]:[]),...(Array.isArray(children)?children:[children]).flatMap(child=>Array.isArray(child)?child.flatMap(value=>nodes(value,predicate)):nodes(child,predicate))];
}
const text=tree=>typeof tree==='string'?tree:Array.isArray(tree)?tree.map(text).join(''):tree?.props?text(tree.props.children):'';
const button=(tree,label)=>nodes(tree,node=>node.type==='button'&&text(node).includes(label))[0];

test('only edited profile fields survive 401 and reload until explicit current-revision review',async()=>{
 let saved=null,remoteRevision=7;const writes=[],calls=[];
 const store={read:()=>saved,write:(_id,draft)=>{saved=json(draft);writes.push(saved)},remove:()=>{saved=null}};
 const api={fetchPersonaFiles:async()=>({files:[{filename:'identity.md',content:'server identity'},{filename:'style.md',content:'server style'}],revision:remoteRevision}),
  savePersonaFile:async(...args)=>{calls.push(args);if(calls.length===1)throw Error('401 登录已过期');if(args[3]!==remoteRevision)throw Object.assign(Error('409 画像已有新修订'),{status:409});return {ok:true,revision:remoteRevision+1}},
 };
 const props={persona:'stable-id',onBack:()=>{},onDeleted:()=>{},onUsePersona:()=>{},inUse:true,allowAccountImport:false,draftStore:store};
 const first=component('ProfilePage',api);first.render(props);await first.effects();
 let tree=first.render(props);
 assert.equal(writes.length,0,'server file reads must never populate local drafts');
 button(tree,'编辑资料').props.onClick();tree=first.render(props);
 nodes(tree,node=>node.type==='textarea')[0].props.onChange({target:{value:'user original input'}});tree=first.render(props);
 assert.deepEqual(saved,{fields:{'identity.md':'user original input'},revision:7});
 await button(tree,'保存').props.onClick();
 assert.deepEqual(saved,{fields:{'identity.md':'user original input'},revision:7});
 remoteRevision=8;
 const reloaded=component('ProfilePage',api);reloaded.render(props);await reloaded.effects();tree=reloaded.render(props);
 assert.equal(nodes(tree,node=>node.type==='textarea')[0].props.value,'user original input');
 await button(tree,'保存').props.onClick();
 assert.equal(calls[1][3],7,'reloading must not silently rebase unsaved text on the latest server version');
 assert.equal(saved.fields['identity.md'],'user original input');
 assert.ok(!JSON.stringify(saved).includes('server style'));
 tree=reloaded.render(props);
 button(tree,'查看当前修订').props.onClick();tree=reloaded.render(props);
 assert.equal(saved.revision,7,'viewing the latest server content is not acceptance');
 assert.equal(nodes(tree,node=>node.type==='textarea').length,0);
 button(tree,'已核对当前修订，保留输入继续编辑').props.onClick();tree=reloaded.render(props);
 assert.equal(saved.revision,8);
 assert.equal(nodes(tree,node=>node.type==='textarea')[0].props.value,'user original input');
 assert.equal(button(tree,'已核对当前修订，保留输入继续编辑'),undefined,'explicit review is a single revision transition');
 await button(tree,'保存').props.onClick();
 assert.equal(calls[2][3],8);
 assert.equal(saved,null);
});

test('idea input survives 401/reload and an accepted save clears only its exact submitted input',async()=>{
 let saved=null,reject=true,finish;const writes=[],calls=[];
 const store={read:()=>saved,write:draft=>{saved=json(draft);writes.push(saved)},remove:()=>{saved=null}};
 const api={fetchIdeas:async()=>[{id:'idea-a',title:'server title',note:'server note',source:'',status:'pending',revision:3}],
  updateIdea:async(id,form)=>{calls.push([id,json(form)]);if(reject)throw Error('401 登录已过期');return await new Promise(resolve=>{finish=resolve})},
 };
 const props={onUseTopic:()=>{},draftStore:store};
 const first=component('IdeasPage',api);first.render(props);await first.effects();let view=first.render(props).props;
 view.openEdit(view.byStatus.pending[0]);view=first.render(props).props;
 assert.equal(writes.length,0,'opening a server row does not cache it');
 view.setForm({...view.form,title:'unsent original'});view=first.render(props).props;
 await view.save();
 assert.equal(saved.form.title,'unsent original');assert.equal(saved.revision,3);
 const reloaded=component('IdeasPage',api);view=reloaded.render(props).props;
 assert.equal(view.form.title,'unsent original');assert.equal(view.editId,'idea-a');
 reject=false;const accepted=view.save();view=reloaded.render(props).props;
 view.setForm({...view.form,title:'typed during save'});
 finish({id:'idea-a'});await accepted;view=reloaded.render(props).props;
 assert.equal(view.form.title,'typed during save');assert.equal(saved.form.title,'typed during save');
 const exact=view.save();finish({id:'idea-a'});await exact;view=reloaded.render(props).props;
 assert.equal(view.form,null);assert.equal(saved,null);
 assert.deepEqual(calls.map(value=>value[1].title),['unsent original','unsent original','typed during save']);
});
