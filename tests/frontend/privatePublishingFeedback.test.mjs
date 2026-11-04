import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';
const jsx={jsx:(type,props)=>({type,props:props??{}}),jsxs:(type,props)=>({type,props:props??{}}),Fragment:'fragment'};
const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
function renderRevision(resource){
 let state=0,read=0;
 const revision={id:'exact-revision',hash:'original-hash',account:'account',title:'Original draft'},states=['','','',revision,'draft',false,true];
 const imports={react:{useState:()=>[states[state++],()=>{}],useEffect:()=>{}},'react/jsx-runtime':jsx,
  './ExtensionDetails':{ExtensionDetails:'ExtensionDetails'},'./common':Object.fromEntries(['ActionButton','Notice','Panel','Field','Drawer','Pending','RemoteRecord'].map(name=>[name,name])),
  './hooks/work-summaries':{useWorkSummaries:()=>({items:[]})},
  './hooks':{useWorkbench:()=>({client:{drafts:{get:()=>null}}}),useResource:()=>[{data:{connections:[],platforms:[],approvals:[],deliveries:[]}}, {}, {},resource][read++],useDraft:()=>[{},()=>{}],useAsyncAction:()=>({busy:false})},
  '@workbench/core':{string:value=>typeof value==='string'?value:'',record:value=>value??{},distributionPermission:()=>({allowed:true,reason:''})},
  '../../components/PublishingPage':{default:'PublishingPage'},'./nativePages':{NativeCalendar:'NativeCalendar'},
  './nativePublishing':{useNativePublishingActions:()=>({})},'../../components/InteractionNotice':{StatusCard:'StatusCard'},
 };
 const {Publishing}=moduleLoader({imports})('workbench/ui/publishing.tsx');
 const search=new URLSearchParams(),outer=Publishing({section:'publications',search,profileId:'p'});
 const center=nodes(outer).find(node=>typeof node.type==='function'&&node.type.name==='PublishCenter');assert.ok(center);
 return nodes(center.type(center.props));
}
test('explicit channel confirmation initial read uses the shared status card without weakening approval fencing',()=>{
 const tree=renderRevision({loading:true}),status=tree.find(node=>node.type==='StatusCard');assert.ok(status);assert.equal(status.props.children,'正在核对准确渠道稿…');
 const approve=tree.find(node=>node.type==='ActionButton'&&node.props.children==='确认批准此稿与动作');assert.equal(approve.props.disabled,true);
});
test('background channel verification keeps the accepted revision and remains visually quiet',()=>{
 const tree=renderRevision({loading:true,refreshing:true,data:{revision:{id:'exact-revision',hash:'original-hash',valid:true}}});
 assert.equal(tree.some(node=>node.type==='StatusCard'),false);
 const approve=tree.find(node=>node.type==='ActionButton'&&node.props.children==='确认批准此稿与动作');assert.equal(approve.props.disabled,false);
});
