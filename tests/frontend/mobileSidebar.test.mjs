import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';

const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url));
const ts=require('typescript');
const source=readFileSync(new URL('../../web/frontend/src/components/ResponsiveSidebar.tsx',import.meta.url),'utf8');
const {outputText}=ts.transpileModule(source,{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,jsx:ts.JsxEmit.ReactJSX,esModuleInterop:true}});

/** Exercise real component state and callbacks; browser checks cover DOM focus/CSS. */
function setup(narrow=true,extra={}){
 const state=[],refs=[];let cursor=0,refCursor=0;
 const jsx=(type,props)=>({type,props});
 const Sidebar=function NativeSidebar(){};
 class Element{constructor(navigation=false){this.navigation=navigation}closest(){return this.navigation?this:null}}
 const exports={},queries=[],effects=[];
 runInNewContext(outputText,{exports,window:{matchMedia:query=>{queries.push(query);return {matches:narrow}}},Element,
  require:specifier=>{
   if(specifier==='./Sidebar')return {__esModule:true,default:Sidebar};
   if(specifier==='react/jsx-runtime')return {jsx,jsxs:jsx,Fragment:'fragment'};
   if(specifier==='react')return {
    useState(initial){const slot=cursor++;if(!(slot in state))state[slot]=typeof initial==='function'?initial():initial;return [state[slot],value=>{state[slot]=typeof value==='function'?value(state[slot]):value}]},
    useRef(initial){const slot=refCursor++;return refs[slot]??=( {current:initial} )},
    useId:()=>':mobile-nav:',useEffect:(callback,dependencies)=>effects.push({callback,dependencies}),useLayoutEffect:()=>{},
   };
   throw Error('Unexpected dependency: '+specifier);
  },
 });
 const calls=[];
 const props={currentPage:'dashboard',activeSessionId:'same-session',selectedPersona:'same-persona',sessions:[],personas:[],gatewayStatus:'connected',apiDirect:false,agentRuntime:'codex'};
 for(const name of ['onPageChange','onSessionSelect','onPersonaChange','onNewProfile','onNewChat','onOpenSettings','onSessionDelete','onSessionRename','onSessionArchive'])props[name]=(...args)=>calls.push([name,...args]);
 Object.assign(props,extra);
 function render(){cursor=0;refCursor=0;effects.length=0;return exports.default(props)}
 const children=tree=>tree.props.children;
 const panel=tree=>children(tree).find(node=>node.props?.className?.startsWith('sidebar-panel'));
 const trigger=tree=>children(tree).find(node=>node.props?.className==='sidebar-toggle');
 const native=tree=>panel(tree).props.children;
 const open=()=>{trigger(render()).props.onClick();return render()};
 return {render,panel,trigger,native,open,props,calls,Element,queries,effects};
}

test('narrow screens start with the native sidebar inert and can open it as a modal',()=>{
 const view=setup(),initial=view.render();
 assert.equal(view.panel(initial).props.inert,true);
 assert.equal(view.panel(initial).props['aria-hidden'],true);
 assert.equal(view.trigger(initial).props['aria-expanded'],false);
 const opened=view.open();
 assert.equal(view.panel(opened).props.inert,false);
 assert.equal(view.panel(opened).props['aria-modal'],true);
 assert.equal(view.trigger(opened).props['aria-expanded'],true);
 assert.equal(view.trigger(opened).props['aria-controls'],view.panel(opened).props.id);
});

test('same-page and same-session actions dismiss the drawer without relying on a parent change',()=>{
 for(const [name,args] of [['onPageChange',['dashboard']],['onSessionSelect',['same-session']],['onPersonaChange',['same-persona']],['onNewProfile',[]],['onNewChat',[]],['onOpenSettings',[]]]){
  const view=setup(),opened=view.open();
  view.native(opened).props[name](...args);
  assert.equal(view.panel(view.render()).props.inert,true,name);
  assert.deepEqual(view.calls,[[name,...args]],name);
 }
});

test('drawer directly renders the original sidebar without an added header or close button',()=>{
 const view=setup(),opened=view.open();
 assert.equal(view.panel(opened).props.children,view.native(opened));
 assert.equal(typeof view.native(opened).type,'function');
 assert.equal(view.trigger(opened).type,'button');
 assert.equal(view.trigger(opened).props['aria-label'],'打开导航');
 assert.equal(opened.props.children.some(node=>node.props?.className==='mobile-nav-bar'),false);
});

test('backdrop dismisses the same mounted original sidebar',()=>{
 const view=setup(),opened=view.open(),sidebarType=view.native(opened).type;
 opened.props.children.find(node=>node.props?.className?.startsWith('sidebar-backdrop')).props.onClick();
 assert.equal(view.trigger(view.render()).props['aria-expanded'],false);
 const closed=view.render();
 assert.equal(view.panel(closed).props.inert,true);
 assert.equal(view.native(closed).type,sidebarType);
});

test('native navigation click capture also dismisses a host-owned custom nav callback',()=>{
 const view=setup(),opened=view.open();
 view.panel(opened).props.onClickCapture({target:new view.Element(true)});
 assert.equal(view.trigger(view.render()).props['aria-expanded'],false);
 assert.deepEqual(view.calls,[],'the wrapper does not invent a second navigation callback');
 const again=view.open();
 view.panel(again).props.onClickCapture({target:new view.Element(false)});
 assert.equal(view.trigger(view.render()).props['aria-expanded'],true,'other controls retain the drawer');
});

test('desktop sidebar is neither hidden nor modal and unrelated actions are forwarded intact',()=>{
 const view=setup(false),tree=view.render(),native=view.native(tree);
 assert.equal(view.panel(tree).props.inert,false);
 assert.equal(view.panel(tree).props.role,undefined);
 assert.equal(view.panel(tree).props['aria-hidden'],undefined);
 assert.equal(view.panel(tree).props['aria-modal'],undefined);
 for(const name of ['onSessionDelete','onSessionRename','onSessionArchive'])assert.equal(native.props[name],view.props[name]);
 assert.equal(native.props.sessions,view.props.sessions);
 assert.equal(native.props.personas,view.props.personas);
});

test('a hosted sidebar registers its open drawer with the same history owner',()=>{
 let dismiss,released=0;const registerLayer=callback=>{dismiss=callback;return()=>released++};
 const view=setup(true,{registerLayer}),tree=view.open();
 const effect=view.effects.find(item=>item.dependencies.includes(registerLayer));assert.ok(effect);
 const cleanup=effect.callback();assert.equal(typeof dismiss,'function');dismiss();
 assert.equal(view.panel(view.render()).props.inert,true);cleanup();assert.equal(released,1);
 assert.equal(view.panel(tree).props.children.type,view.native(tree).type);
});

test('host compact query is explicit while the ordinary Easel breakpoint remains 760px',()=>{
 const query='(max-width: 900px), (max-width: 1100px) and (max-height: 500px)';
 const hosted=setup(true,{compactQuery:query}),tree=hosted.render();
 assert.equal(hosted.queries[0],query);assert.equal(hosted.panel(tree).props['data-compact'],true);
 const native=setup(true),ordinary=native.render();assert.equal(native.queries[0],'(max-width: 760px)');
 assert.equal(native.panel(ordinary).props['data-compact'],undefined);
});
