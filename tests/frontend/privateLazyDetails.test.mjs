import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';

const element=(type,props)=>({type,props:props??{}}),jsx={jsx:element,jsxs:element,Fragment:'fragment'};
const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
function runtime(){
 let active;
 const same=(a,b)=>a&&b&&a.length===b.length&&a.every((value,i)=>Object.is(value,b[i]));
 const react={
  createContext(value){const context={current:value};context.Provider={context};return context},useContext:context=>context.current,
  useState(initial){const owner=active,index=owner.index++;if(!(index in owner.slots))owner.slots[index]=typeof initial==='function'?initial():initial;return [owner.slots[index],value=>{const next=typeof value==='function'?value(owner.slots[index]):value;if(!Object.is(next,owner.slots[index])){owner.slots[index]=next;owner.dirty=true}}]},
  useRef(initial){const index=active.index++;return active.slots[index]??=( {current:initial} )},
  useMemo(fn,deps){const index=active.index++;if(!active.slots[index]||!same(active.slots[index].deps,deps))active.slots[index]={deps,value:fn()};return active.slots[index].value},
  useCallback(fn,deps){return react.useMemo(()=>fn,deps)},
  useEffect(fn,deps){const owner=active,index=owner.index++,old=owner.slots[index];if(!old||!same(old.deps,deps)){owner.slots[index]={deps,cleanup:old?.cleanup};owner.effects.push(()=>{old?.cleanup?.();owner.slots[index].cleanup=fn()})}},
 };
 function mount(component,initial={}){
  const owner={slots:[],index:0,dirty:true,effects:[],tree:null,props:initial};
  const render=(props=owner.props)=>{owner.props=props;owner.index=0;owner.dirty=false;active=owner;owner.tree=component(props);owner.effects.splice(0).forEach(fn=>fn());return owner.tree};
  return {render,async settle(){for(let i=0;i<20;i++){if(owner.dirty)render();await Promise.resolve()}assert.equal(owner.dirty,false);return owner.tree},unmount(){owner.slots.forEach(slot=>slot?.cleanup?.())}};
 }
 return {react,mount};
}

test('closed private details mount nothing until first open, then retain their child owner after close',async()=>{
 const rt=runtime(),load=moduleLoader({imports:{react:rt.react,'react/jsx-runtime':jsx}}),{ExtensionDetails}=load('workbench/ui/ExtensionDetails.tsx');
 const child=element('input',{defaultValue:'Exact unsaved draft'}),view=rt.mount(ExtensionDetails,{title:'交付记录',children:child});
 let tree=await view.settle();assert.equal(nodes(tree).filter(node=>node.props.className==='ew-disclosure-body').length,0);
 tree.props.onToggle({currentTarget:{open:true}});tree=await view.settle();let boundary=nodes(tree).find(node=>node.props.visible===true);assert.ok(boundary);assert.equal(nodes(boundary).find(node=>node.type==='input'),child);
 tree.props.onToggle({currentTarget:{open:false}});tree=await view.settle();boundary=nodes(tree).find(node=>node.props.visible===false);assert.ok(boundary);assert.equal(nodes(boundary).find(node=>node.type==='input'),child);assert.equal(tree.props.open,false);
});

test('nested visibility is an AND boundary, including an initially open child under a closed parent',()=>{
 const rt=runtime(),load=moduleLoader({imports:{react:rt.react,'react/jsx-runtime':jsx}}),{ResourceVisibility}=load('workbench/ui/hooks/visibility.tsx');
 const boundary=ResourceVisibility({visible:false,children:null}),context=boundary.type.context;assert.equal(boundary.props.value,false);context.current=false;
 assert.equal(ResourceVisibility({visible:true,children:null}).props.value,false);context.current=true;assert.equal(ResourceVisibility({visible:true,children:null}).props.value,true);
});

test('hidden resource owners do not read, watch or reload and reopening retains the original cached data',async()=>{
 const rt=runtime(),calls=[],snapshot={data:{draft:'Exact cached input'},loading:false,error:'',revision:1,stale:false},store={getState:()=>snapshot};
 const client={session:{getState:()=>({config:{csrf:'TEMP'},expired:false})},drafts:{persistence:{getState:()=>({error:''})}},legacyPending:()=>[],resource:()=>store,watch:(path,interval)=>{calls.push(['watch',path,interval]);return()=>calls.push(['stop',path])},read:async(path,force)=>{calls.push(['read',path,force]);return snapshot.data},navigation:{path:'/toolbox'}};
 const load=moduleLoader({imports:{react:rt.react,'react/jsx-runtime':jsx,zustand:{useStore:(value,select)=>select?select(value.getState()):value.getState()}}});
 const visibility=load('workbench/ui/hooks/visibility.tsx'),boundary=visibility.ResourceVisibility({visible:true,children:null}),visibleContext=boundary.type.context;
 const hooks=load('workbench/ui/hooks/context.tsx'),provider=rt.mount(hooks.CoreProvider,{client,autoBoot:false,children:null});let tree=provider.render();tree.type.context.current=tree.props.value;
 visibleContext.current=false;const resource=rt.mount(()=>hooks.useResource('/api/large',{interval:5000}));let result=await resource.settle();assert.equal(calls.length,0);assert.equal(await result.reload(),snapshot.data);assert.equal(calls.length,0);
 visibleContext.current=true;resource.render();result=await resource.settle();assert.deepEqual(calls.map(row=>row[0]),['watch','read']);assert.equal(result.data,snapshot.data);
 visibleContext.current=false;resource.render();result=await resource.settle();assert.deepEqual(calls.map(row=>row[0]),['watch','read','stop']);await result.reload();assert.equal(calls.length,3);
 visibleContext.current=true;resource.render();result=await resource.settle();assert.equal(result.data,snapshot.data);assert.deepEqual(calls.map(row=>row[0]),['watch','read','stop','watch','read']);resource.unmount();provider.unmount();
});

test('terminal task transitions release the fast watcher while hidden owners retain their exact draft and attachments',async()=>{
 const rt=runtime(),calls=[],snapshot={data:{status:'running'},loading:false,error:'',revision:1,stale:false},store={getState:()=>snapshot},saved=new Map();
 const load=moduleLoader({imports:{react:rt.react,'react/jsx-runtime':jsx,zustand:{useStore:(value,select)=>select?select(value.getState()):value.getState()}}});
 const {DraftRepository}=load('workbench/core/persistence.ts'),drafts=new DraftRepository({get length(){return saved.size},key:i=>[...saved.keys()][i]??null,getItem:key=>saved.get(key)??null,setItem:(key,value)=>saved.set(key,value),removeItem:key=>saved.delete(key)});
 const client={session:{getState:()=>({config:{csrf:'TEMP'},expired:false})},drafts,legacyPending:()=>[],resource:()=>store,watch:(path,interval)=>{calls.push(['watch',path,interval]);return()=>calls.push(['stop',path,interval])},read:async(path,force)=>{calls.push(['read',path,force]);return snapshot.data},navigation:{path:'/toolbox'}};
 const visibility=load('workbench/ui/hooks/visibility.tsx'),boundary=visibility.ResourceVisibility({visible:true,children:null}),visible=boundary.type.context,hooks=load('workbench/ui/hooks/context.tsx');
 const provider=rt.mount(hooks.CoreProvider,{client,autoBoot:false,children:null}),tree=provider.render();tree.type.context.current=tree.props.value;
 const task=rt.mount(({stop=true})=>({resource:hooks.useResource('/api/task',{interval:3000,stopOnTerminal:stop}),draft:hooks.useDraft('task-input',{text:'',files:[]})}));let view=await task.settle();
 assert.equal(calls.filter(row=>row[0]==='watch').at(-1)[2],3000);view.draft[1]({text:'  Exact unsent note\nKeep bytes  ',files:[{id:'original-file',name:'附件.png'}]});view=await task.settle();
 for(const status of ['completed','failed','stopped','cancelled']){
  snapshot.data={status:'running'};task.render();await task.settle();assert.equal(calls.filter(row=>row[0]==='watch').at(-1)[2],3000);
  const releases=calls.filter(row=>row[0]==='stop').length;snapshot.data={status};task.render();view=await task.settle();assert.equal(calls.filter(row=>row[0]==='stop').length,releases+1,status+' must release its old 3s owner');assert.equal(calls.filter(row=>row[0]==='watch').at(-1)[2],undefined,status+' keeps invalidation ownership without a timed poll');
 }
 snapshot.data={status:'unknown'};task.render();await task.settle();assert.equal(calls.filter(row=>row[0]==='watch').at(-1)[2],3000,'unknown receipts must keep their read-only checking interval');
 visible.current=false;task.render();view=await task.settle();const count=calls.length;await view.resource.reload();snapshot.data={status:'completed'};task.render();view=await task.settle();assert.equal(calls.length,count,'closing pauses both terminal and active watchers/reloads');
 assert.equal(view.draft[0].text,'  Exact unsent note\nKeep bytes  ');assert.deepEqual(JSON.parse(JSON.stringify(view.draft[0].files)),[{id:'original-file',name:'附件.png'}]);
 visible.current=true;task.render();view=await task.settle();assert.equal(calls.filter(row=>row[0]==='watch').at(-1)[2],undefined);assert.equal(view.draft[0].text,'  Exact unsent note\nKeep bytes  ');
 task.render({stop:false});await task.settle();assert.equal(calls.filter(row=>row[0]==='watch').at(-1)[2],3000,'the opt-in does not change ordinary interval resources');task.unmount();provider.unmount();
});

for(const name of ['JsonDetails','TextRecord'])test(name+' formats large records only when its original drawer opens',async()=>{
 const rt=runtime();let formats=0;const value={toJSON(){formats++;return {text:'large original record'}}};
 const load=moduleLoader({imports:{react:rt.react,'react/jsx-runtime':jsx,'./hooks':{},'@workbench/core':{},'../../components/DownloadLink':'DownloadLink','../../components/Drawer':'OriginalDrawer','../../components/InteractionNotice':{InteractionNotice:'InteractionNotice'},'./ExtensionDetails':{DetailChevron:'DetailChevron'},'./lib/sanitize':{}}});
 const common=load('workbench/ui/common.tsx'),node=common[name]({title:'原始记录',value});assert.equal(formats,0);const view=rt.mount(node.type,node.props);let tree=await view.settle();assert.equal(formats,0);
 nodes(tree).find(node=>node.type==='button').props.onClick();tree=await view.settle();assert.equal(formats,1);const drawer=nodes(tree).find(node=>node.type===common.Drawer);assert.ok(drawer.props.open);drawer.props.onClose();tree=await view.settle();assert.equal(formats,1);assert.equal(nodes(tree).find(node=>node.type===common.Drawer).props.open,false);
});

test('an already mounted record does not stringify replacement data while its disclosure is hidden',async()=>{
 const rt=runtime();let visible=true,formats=0;const value=()=>({toJSON(){formats++;return {text:'Exact large diff'}}});
 const load=moduleLoader({imports:{react:rt.react,'react/jsx-runtime':jsx,'./hooks':{},'./hooks/visibility':{useResourceVisibility:()=>visible},'@workbench/core':{},'../../components/DownloadLink':'DownloadLink','../../components/Drawer':'OriginalDrawer','../../components/InteractionNotice':{InteractionNotice:'InteractionNotice'},'./ExtensionDetails':{DetailChevron:'DetailChevron'},'./lib/sanitize':{}}});
 const view=rt.mount(load('workbench/ui/common.tsx').RecordBody,{value:value()});await view.settle();assert.equal(formats,1);visible=false;view.render({value:value()});await view.settle();assert.equal(formats,1);visible=true;view.render({value:value()});await view.settle();assert.equal(formats,2);
});

test('full delivery and publication records are requested only by their explicit original drawer',async()=>{
 const rt=runtime(),reads=[];
 const load=moduleLoader({imports:{react:rt.react,'react/jsx-runtime':jsx,'./hooks':{useResource:path=>{reads.push(path);return {data:{publication:{id:'exact',text:'Original full receipt'}},loading:false,error:''}}},'@workbench/core':{record:value=>value??{}},'../../components/DownloadLink':'DownloadLink','../../components/Drawer':'OriginalDrawer','../../components/InteractionNotice':{InteractionNotice:'InteractionNotice'},'./ExtensionDetails':{DetailChevron:'DetailChevron'},'./lib/sanitize':{}}});
 const common=load('workbench/ui/common.tsx'),node=common.RemoteRecord({title:'准确记录',path:'/api/studio/publications/exact',field:'publication'}),view=rt.mount(node.type,node.props);let tree=await view.settle();assert.equal(reads.length,0);
 nodes(tree).find(node=>node.type==='button').props.onClick();tree=await view.settle();const drawer=nodes(tree).find(node=>node.type===common.Drawer),reader=drawer.props.children;assert.equal(reads.length,0);const content=rt.mount(reader.type,reader.props);tree=await content.settle();assert.deepEqual(reads,['/api/studio/publications/exact']);assert.ok(nodes(tree).some(node=>node.type==='pre'&&node.props.children.includes('Original full receipt')));drawer.props.onClose();await view.settle();assert.equal(reads.length,1);
});

test('work pickers request bounded summary pages, preserve earlier rows and never reset selection IDs',async()=>{
 const rt=runtime(),calls=[];const pages=new Map(),first='/api/works?view=summary&limit=50&profile_id=profile-a',second=first+'&cursor=next';
 pages.set(first,{items:[{id:'a',title:'A',format:'poster'}],next_cursor:'next',total:3});pages.set(second,{items:[{id:'b',title:'B',format:'poster'}],next_cursor:null,total:3});
 const load=moduleLoader({imports:{react:rt.react,'./context':{useResource:path=>{calls.push(path);return {data:pages.get(path)??null,loading:false,error:'',reload:async()=>pages.get(path)}}}}}),{useWorkSummaries}=load('workbench/ui/hooks/work-summaries.ts');
 const selected=['not-in-loaded-page'],view=rt.mount(()=>useWorkSummaries('profile-a'));let value=await view.settle();assert.deepEqual(Array.from(value.items,item=>item.id),['a']);value.more();value=await view.settle();assert.deepEqual(Array.from(value.items,item=>item.id),['a','b']);assert.deepEqual(selected,['not-in-loaded-page']);assert.ok(calls.every(path=>path.startsWith('/api/works?view=summary&limit=50&')));assert.ok(calls.includes(second));
});

test('publishing requests only visible summaries and exact selected versions; approval requires the matching full revision',async()=>{
 const rt=runtime(),paths=[],writes=[],work={id:'work-a',title:'Work A',format:'poster',latest_version:'v2',versions:[],version_summaries:[{id:'v1',label:'v01',status:'completed'},{id:'v2',label:'v02',status:'completed'}]},selected={id:'v1',label:'v01',status:'completed',artifacts:[]};
 const revision={id:'revision-a',hash:'hash-a',account:'Exact account',title:'Exact title',platform:'TEMP'},draft={title:'Exact draft',body:'Exact unsent body',image_ids:[],content_kind:'article'};let revisionReply;
 const summary={connections:[{id:'account-a',enabled:true,account:'Exact account',platform:'TEMP'}],platforms:[{id:'TEMP',content_kinds:['article']}],approvals:[],deliveries:[]};
 const core={record:value=>value??{},string:value=>typeof value==='string'?value:'',distributionSource:()=>assert.fail('Existing draft must not be overwritten'),distributionPermission:()=>({allowed:true,reason:'TEMP permitted'}),distributionStatus:value=>value,workPath:()=>'/works/work-a'};
 const vm={client:{drafts:{get:()=>({})},mutate:async(_scope,_path,input)=>{writes.push(input);return {revision}}},navigate(){}};
 const hooks={useWorkbench:()=>vm,useResource:path=>{if(path)paths.push(path);return {data:path==='/api/distribution/bootstrap?view=summary'?summary:path==='/api/works/work-a/view'?work:path==='/api/works/work-a/versions/v1/view'?{...work,versions:[selected]}:path==='/api/distribution/revisions/revision-a'?revisionReply:null,loading:false,error:'',reload(){}}},useDraft:()=>[draft,value=>Object.assign(draft,value)],useAsyncAction:()=>({busy:false,run:fn=>fn()})};
 const common=Object.fromEntries(['ActionButton','Panel','Drawer','Notice','Pending','RemoteRecord','Field'].map(name=>[name,name]));common.resultDocument=value=>value.result??value;
 const load=moduleLoader({imports:{react:rt.react,'react/jsx-runtime':jsx,'@workbench/core':core,'./hooks':hooks,'./hooks/work-summaries':{useWorkSummaries:()=>({items:[],loading:false,error:'',next_cursor:null})},'./common':common,'./ExtensionDetails':{ExtensionDetails:'ExtensionDetails'},'../../components/PublishingPage':'PublishingPage','./nativePages':{NativeCalendar:'Calendar'},'./nativePublishing':{useNativePublishingActions:()=>({})}}});
 const shell=rt.mount(load('workbench/ui/publishing.tsx').Publishing,{section:'publish',search:new URLSearchParams({work:'work-a',version:'v1'}),profileId:'profile-a'});let tree=await shell.settle();assert.equal(paths.length,0,'the closed delivery section must not mount its read owner');const delivery=nodes(tree).find(node=>typeof node.type==='function'&&node.type.name==='PublishCenter'),page=rt.mount(delivery.type,delivery.props);tree=await page.settle();assert.ok(paths.includes('/api/works/work-a/versions/v1/view'));assert.ok(!paths.includes('/api/studio/bootstrap'));assert.ok(!paths.includes('/api/works/work-a'));
 nodes(tree).find(node=>node.type==='select'&&node.props['aria-label']==='交付账号').props.onChange({target:{value:'account-a'}});tree=await page.settle();const button=(value,label)=>nodes(value).find(node=>node.type==='ActionButton'&&node.props.children===label);
 await button(tree,'冻结并核对渠道稿').props.onClick();tree=await page.settle();button(tree,'核对并批准这份渠道稿').props.onClick();tree=await page.settle();assert.equal(button(tree,'确认批准此稿与动作').props.disabled,true);assert.equal(writes.length,1);
 revisionReply={revision:{...revision,hash:'other-hash'}};page.render();tree=await page.settle();assert.equal(button(tree,'确认批准此稿与动作').props.disabled,true);
 revisionReply={revision:{...revision,valid:false}};page.render();tree=await page.settle();assert.equal(button(tree,'确认批准此稿与动作').props.disabled,true);
 revisionReply={revision};page.render();tree=await page.settle();assert.equal(button(tree,'确认批准此稿与动作').props.disabled,false);await button(tree,'确认批准此稿与动作').props.onClick();assert.equal(writes[1].items[0].revision_id,'revision-a');assert.equal(writes[1].items[0].revision_hash,'hash-a');assert.equal(writes[0].version_id,'v1');assert.equal(draft.body,'Exact unsent body');
});
