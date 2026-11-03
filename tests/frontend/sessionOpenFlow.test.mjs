import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';
const plain=value=>JSON.parse(JSON.stringify(value));
const json=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json','X-Workbench-Operation-Protocol':'2'}});
function fixture(saved=new Map(),globals={}){
 const calls=[],moves=[],state={mode:'completed',receipt:'waiting',sid:'created-exact',resolve:'sealed_not_accepted',entry:'source-entry',draftFail:false,flowFailAfterCommit:false,serverCommitted:false};
 const load=moduleLoader({globals:{FormData,Event,...globals}}),{WorkbenchClient}=load('workbench/core/client.ts');
 const storage={get length(){return saved.size},key:n=>[...saved.keys()][n],getItem:k=>saved.get(k)??null,setItem:(k,v)=>{if(state.draftFail&&k.includes('chat:created-exact')||state.flowFailAfterCommit&&state.serverCommitted&&k.includes('toolbox:draft:session-open:'))throw Error('storage full');saved.set(k,v)},removeItem:k=>saved.delete(k)};
 const navigation={path:'/toolbox',entryKey:'source-entry',ticket:()=>({entryId:state.entry}),finishFlow:(path,ticket)=>{if(ticket.entryId!==state.entry)return false;moves.push(path);navigation.path=path;state.entry='next-entry';return true},navigate:path=>{moves.push(path);navigation.path=path;state.entry='next-entry';}};
 const client=new WorkbenchClient({storage,navigation,retryDelay:0,fetcher:async(path,options={})=>{
  const body=options.body?JSON.parse(options.body):undefined;calls.push({path,method:options.method||'GET',body});
  if(path==='/api/diagnostics/client-operation')return json({ok:true});
  if(path.endsWith('/resolve'))return json({protocol_version:2,operation_id:body.request.id,operation_state:state.resolve,...(state.resolve==='completed'?{result:{session:{id:'old-existing',profile_id:body.request.profile_id,runtime:'codex'}}}:{})});
  if(path==='/api/chat/sessions'&&options.method==='POST'){
   if(state.mode==='lost')throw new TypeError('reply lost');
   if(state.mode==='not_accepted')return json({protocol_version:2,operation_id:body.id,operation_state:'not_accepted',code:'admission_paused',error:'服务切换'},503);
   if(state.mode==='accepted')return json({protocol_version:2,operation_id:body.id,operation_state:'accepted'},202);
   if(state.mode==='rejected')return json({protocol_version:2,operation_id:body.id,operation_state:'rejected',code:'profile_inactive',error:'画像已停用'},400);
   state.serverCommitted=true;
   return json({protocol_version:2,operation_id:body.id,operation_state:'completed',session:{id:state.sid,profile_id:body.profile_id,runtime:'codex'}});
  }
  if(path.startsWith('/api/operations/')){const id=decodeURIComponent(path.split('/')[3].split('?')[0]);return json(state.receipt==='completed'?{id,protocol_version:2,operation_id:id,operation_state:'completed',state:'received',result:{session:{id:id==='legacy-old'?'old-existing':state.sid,profile_id:'profile-a',runtime:'codex'}}}:{id,protocol_version:2,operation_id:id,operation_state:'running',state:'waiting'});}
  return json({csrf:'TEMP'});
 }});client.session.setState({config:{csrf:'TEMP'},loading:false});client.pauseVisible();
 const owner=load('workbench/core/session-open-flow.ts').sessionOpenFlows(client);
 return {client,owner,state,calls,moves,saved,close(){owner.dispose();client.pauseVisible()},creates(){return calls.filter(c=>c.path==='/api/chat/sessions'&&c.method==='POST')}};
}

test('direct creation durably preserves exact draft and opens the same completed session once',async()=>{
 const f=fixture();try{const draft={text:' 原始输入\n第二行 ',files:[{id:'local-exact',name:'原附件'}],command:{skill_id:'exact',version:4}};
  const result=await f.owner.open({profileId:'profile-a',draft});assert.equal(result.id,'created-exact');
  assert.equal(f.creates().length,1);assert.equal(f.moves.length,1);assert.equal(f.moves[0],'/chat/created-exact');
  const flow=f.owner.state.getState().flow;assert.equal(flow.phase,'opened');
  assert.deepEqual(plain(f.client.drafts.get('chat:created-exact')).text,draft.text);assert.equal(f.client.drafts.get('chat:created-exact').files[0].id,'local-exact');
  assert.equal(f.client.operation('session-open:'+flow.flow_id).getState().pending,null);
 }finally{f.close()}
});

test('accepted response is not completion, and receipt recovery applies draft and navigation without another POST',async()=>{
 const f=fixture();try{f.state.mode='accepted';const result=await f.owner.open({profileId:'profile-a',draft:{text:'frozen input',files:[]}});
  assert.equal(result,null);const flow=f.owner.state.getState().flow;assert.equal(flow.phase,'creating');assert.equal(f.moves.length,0);
  f.state.receipt='completed';await f.owner.check();assert.equal(f.creates().length,1);assert.equal(f.moves[0],'/chat/created-exact');
  assert.equal(f.client.drafts.get('chat:created-exact').text,'frozen input');
 }finally{f.close()}
});

test('lost response never resends creation and a later successful receipt still completes the page flow',async()=>{
 const f=fixture();try{f.state.mode='lost';await f.owner.open({profileId:'profile-a',draft:{text:'kept',files:[]}});
  assert.equal(f.owner.state.getState().flow.phase,'checking');assert.equal(f.creates().length,1);
  f.state.receipt='completed';await f.owner.check();assert.equal(f.moves[0],'/chat/created-exact');assert.equal(f.creates().length,1);
  assert.equal(f.owner.state.getState().flow.recovered,true);
 }finally{f.close()}
});

test('a completed create does not steal navigation after the user leaves, and explicit open remains available',async()=>{
 const f=fixture();try{f.state.mode='accepted';await f.owner.open({profileId:'profile-a'});f.state.entry='user-left';f.state.receipt='completed';await f.owner.check();
  assert.equal(f.moves.length,0);assert.equal(f.owner.state.getState().flow.phase,'ready');await f.owner.retry();assert.equal(f.moves[0],'/chat/created-exact');
 }finally{f.close()}
});

test('storage failure retains the known successful session and retries draft application without creating again',async()=>{
 const f=fixture();try{f.state.draftFail=true;await f.owner.open({profileId:'profile-a',draft:{text:'original',files:[]}});
  assert.equal(f.owner.state.getState().flow.session_id,'created-exact');assert.equal(f.moves.length,0);
  f.state.draftFail=false;await f.owner.retry();assert.equal(f.moves[0],'/chat/created-exact');assert.equal(f.creates().length,1);
 }finally{f.close()}
});

test('a definite terminal rejection is archived and explicit recreate uses one new identity with the same context',async()=>{
 const f=fixture();try{f.state.mode='rejected';await f.owner.open({profileId:'profile-a',draft:{text:'exact original',files:[]},query:'work=frozen&version=exact'});
  const failed=f.owner.state.getState().flow;assert.equal(failed.phase,'failed');assert.equal(f.client.operation('session-open:'+failed.flow_id).getState().pending,null);
  f.state.mode='completed';await f.owner.retry();assert.equal(f.creates().length,2);assert.notEqual(f.creates()[1].body.id,failed.operation_id);
  assert.equal(f.creates()[1].body.profile_id,'profile-a');assert.equal(f.client.drafts.get('session-open-history:'+failed.operation_id).request.id,failed.operation_id);
  assert.equal(f.owner.state.getState().flow.parent_operation_id,failed.operation_id);assert.equal(f.client.drafts.get('chat:created-exact').text,'exact original');
  assert.equal(f.moves[0],'/chat/created-exact?work=frozen&version=exact');
 }finally{f.close()}
});

test('explicit retry on an unknown creation only checks its original receipt',async()=>{
 const f=fixture();try{f.state.mode='lost';await f.owner.open({profileId:'profile-a'});const original=f.creates()[0].body.id;
  f.state.mode='completed';await f.owner.retry();assert.equal(f.creates().length,1);assert.equal(f.owner.state.getState().flow.operation_id,original);
  assert.equal(f.owner.state.getState().flow.phase,'checking');
 }finally{f.close()}
});

test('storage full after server commit keeps a ready known session and retry-save cannot POST a new create',async()=>{
 const f=fixture();try{f.state.flowFailAfterCommit=true;await f.owner.open({profileId:'profile-a',draft:{text:'preserved after commit',files:[]}});
  const flow=f.owner.state.getState().flow;assert.equal(flow.phase,'ready');assert.equal(flow.session_id,'created-exact');assert.equal(flow.code,'local_persistence_failed');assert.equal(f.moves.length,0);
  assert.equal(f.client.operation('session-open:'+flow.flow_id).getState().pending.acceptance,'accepted');
  f.state.flowFailAfterCommit=false;f.state.receipt='completed';await f.owner.retry();assert.equal(f.creates().length,1);assert.equal(f.moves[0],'/chat/created-exact');
  assert.equal(f.client.drafts.get('chat:created-exact').text,'preserved after commit');assert.equal(f.client.operation('session-open:'+flow.flow_id).getState().pending,null);
 }finally{f.close()}
});

test('a successful receipt recovered in the initial POST catch cannot resume a caller model submission',async()=>{
 const f=fixture();try{f.state.mode='lost';f.state.receipt='completed';const result=await f.owner.open({profileId:'profile-a',draft:{text:'material',command:{skill_id:'content-production',version:3}}});
  assert.equal(result,null);assert.equal(f.creates().length,1);assert.equal(f.moves[0],'/chat/created-exact');assert.equal(f.owner.state.getState().flow.recovered,true);
 }finally{f.close()}
});

test('unchanged pending observations do not rewrite the preserved input or emit repeated diagnostics',async()=>{
 const f=fixture();try{f.state.mode='accepted';await f.owner.open({profileId:'profile-a',draft:{text:'kept original'}});const flow=f.owner.state.getState().flow;
  const before=f.calls.filter(c=>c.path==='/api/diagnostics/client-operation').length,raw=f.saved.get('toolbox:draft:session-open:'+flow.flow_id);
  const pending=f.client.operation('session-open:'+flow.flow_id);pending.setState({busy:true});pending.setState({busy:false});
  assert.equal(f.calls.filter(c=>c.path==='/api/diagnostics/client-operation').length,before);assert.equal(f.saved.get('toolbox:draft:session-open:'+flow.flow_id),raw);
 }finally{f.close()}
});

test('background completion of an older independent flow does not replace the active flow or its navigation',async()=>{
 const f=fixture();try{f.state.mode='accepted';await f.owner.open({profileId:'profile-a',sourceKey:'first'});const first=f.owner.state.getState().flow;
  await f.owner.open({profileId:'profile-b',sourceKey:'second'});const second=f.owner.state.getState().flow;
  f.state.receipt='completed';await f.owner.check(first.flow_id);
  assert.equal(f.owner.state.getState().flow.flow_id,second.flow_id);assert.equal(f.moves.length,0);assert.equal(f.creates().length,2);
 }finally{f.close()}
});

test('a reloaded accepted flow recovers the original identity, draft and destination',async()=>{
 const f=fixture();let id;try{f.state.mode='accepted';await f.owner.open({profileId:'profile-a',draft:{text:'reload-safe',files:[]},query:'work=exact-work&version=exact-version'});id=f.owner.state.getState().flow.flow_id;}finally{f.close()}
 const restored=fixture(f.saved);try{restored.state.receipt='completed';restored.state.entry='reloaded-flow-entry';restored.client.navigation.path='/chat?fresh=1&flow='+id;restored.owner.restore(id);await restored.owner.check(id);
  assert.equal(restored.creates().length,0);assert.equal(restored.moves[0],'/chat/created-exact?work=exact-work&version=exact-version');assert.equal(restored.client.drafts.get('chat:created-exact').text,'reload-safe');
 }finally{restored.close()}
});

test('restoring a different flow does not adopt the ticket of the page the user is currently visiting',async()=>{
 const original=fixture();let id;try{original.state.mode='accepted';await original.owner.open({profileId:'profile-a',draft:{text:'original draft'}});id=original.owner.state.getState().flow.flow_id;}finally{original.close()}
 const restored=fixture(original.saved);try{restored.state.entry='another-page-entry';restored.client.navigation.path='/toolbox?section=skills';restored.state.receipt='completed';restored.owner.restore(id);await restored.owner.check(id);
  assert.equal(restored.creates().length,0);assert.equal(restored.moves.length,0);assert.equal(restored.owner.state.getState().flow.phase,'ready');
  await restored.owner.retry(id);assert.equal(restored.moves[0],'/chat/created-exact');
 }finally{restored.close()}
});

test('returning to the owning flow after its session was already created opens it using the new route ticket',async()=>{
 const original=fixture();let id;try{original.state.mode='accepted';await original.owner.open({profileId:'profile-a'});id=original.owner.state.getState().flow.flow_id;original.state.entry='left-before-completion';original.state.receipt='completed';await original.owner.check(id);assert.equal(original.moves.length,0);}finally{original.close()}
 const restored=fixture(original.saved);try{restored.state.entry='new-owning-route';restored.client.navigation.path='/chat?fresh=1&flow='+id;restored.owner.restore(id);
  assert.equal(restored.moves[0],'/chat/created-exact');assert.equal(restored.creates().length,0);
 }finally{restored.close()}
});

for(const oldState of ['completed','sealed_not_accepted'])for(const oldProfile of ['profile-a','different-profile'])test('legacy '+oldState+' from '+oldProfile+' cannot capture new input or its requested profile',async()=>{
 const f=fixture();try{const old={scope:'chat:create',path:'/api/chat/sessions',id:'legacy-old',body:{action:'create',profile_id:oldProfile,id:'legacy-old'},uncertain:true};f.client.drafts.set('native:pending:chat:create',{operation:old});f.state.resolve=oldState;
  const result=await f.owner.open({profileId:'profile-a',draft:{text:'new exact input',files:[]}});assert.equal(result.id,'created-exact');
  assert.equal(f.creates().length,1);assert.equal(f.creates()[0].body.profile_id,'profile-a');assert.notEqual(f.creates()[0].body.id,'legacy-old');
  assert.equal(f.client.drafts.get('chat:created-exact').text,'new exact input');assert.equal(f.client.drafts.get('chat:old-existing'),null);
  assert.equal(f.moves[0],'/chat/created-exact');assert.equal(f.client.operation('chat:create').getState().pending,null);
 }finally{f.close()}
});

test('the body card uses one clear operation title, native button classes and the same Drawer for details',()=>{
 const load=moduleLoader({imports:{react:{useMemo:fn=>fn(),useEffect(){},useRef:value=>({current:value}),useState:value=>[value,()=>{}]},'./common':{Drawer:function OfficialDrawer(){}},'./styles/session-open.css':{}}});
 const {SessionOpenStage}=load('workbench/ui/SessionOpenStage.tsx');
 const client={drafts:{get:()=>null}};
 const flow={flow_id:'flow',operation_id:'op',profile_id:'profile',phase:'checking',created_at:Date.now()-31000,draft:{text:'kept'},auto_retries:0};
 const result=SessionOpenStage({client,flow}),section=result.props.children[0];
 assert.equal(result.props.className,'ew-session-open-stage');assert.match(section.props.className,/card ew-session-open-card/);assert.equal(section.props['aria-label'],'新建对话状态');
 const nodes=value=>Array.isArray(value)?value.flatMap(nodes):value&&typeof value==='object'?[value,...nodes(value.props?.children)]:[];
 const tree=nodes(section);assert.equal(tree.find(node=>node.type==='h1').props.children,'暂时无法确认创建结果');
 assert.equal(tree.filter(node=>node.type==='button').some(node=>node.props.className==='btn btn-primary'&&node.props.children==='检查状态'),true);
 assert.equal(result.props.children[1].props.title,'对话创建记录');assert.equal(tree.some(node=>String(node.props?.className||'').includes('is-working')),false);
 assert.equal(SessionOpenStage({client,flow:null}),null);
 const local=nodes(SessionOpenStage({client,flow:{...flow,phase:'ready',session_id:'created',code:'local_persistence_failed',error:'本机恢复记录尚未保存'}}));
 assert.equal(local.find(node=>node.type==='h1').props.children,'对话已创建');assert.ok(local.some(node=>node.type==='button'&&node.props.children==='重试保存'));
 assert.ok(!local.some(node=>node.type==='button'&&node.props.children==='重新创建'));
 const rejected=nodes(SessionOpenStage({client,flow:{...flow,phase:'failed',code:'profile_inactive',error:'画像已停用'}}));
 assert.ok(rejected.some(node=>node.type==='button'&&node.props.children==='核对画像'));
 assert.ok(rejected.some(node=>node.type==='button'&&node.props.children==='重新创建'));
});

test('a running legacy operation is polled by GET and automatically unblocks the distinct new intent after completion',async()=>{
 const timers=[],globals={setTimeout:(callback,ms)=>{const timer={callback,ms,cleared:false,unref(){}};timers.push(timer);return timer},clearTimeout:timer=>{if(timer)timer.cleared=true}};
 const f=fixture(new Map(),globals);try{
  const old={scope:'chat:create',path:'/api/chat/sessions',id:'legacy-old',body:{action:'create',profile_id:'old-profile',id:'legacy-old'},uncertain:true};f.client.drafts.set('native:pending:chat:create',{operation:old});f.state.resolve='running';
  await f.owner.open({profileId:'profile-a',draft:{text:'new material'}});assert.equal(f.creates().length,0);
  const poll=timers.find(timer=>!timer.cleared&&timer.ms===1000);assert.ok(poll);
  f.state.receipt='completed';poll.callback();await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.calls.filter(call=>call.path.endsWith('/resolve')).length,1);
  assert.ok(f.calls.some(call=>call.method==='GET'&&call.path.includes('/api/operations/legacy-old')));
  assert.equal(f.creates().length,1);assert.equal(f.client.drafts.get('chat:old-existing'),null);assert.equal(f.client.drafts.get('chat:created-exact').text,'new material');
 }finally{f.close()}
});

test('explicit not-accepted proof permits one automatic same-identity retry when the service becomes ready',async()=>{
 const timers=[],globals={setTimeout:(callback,ms)=>{const timer={callback,ms,cleared:false,unref(){}};timers.push(timer);return timer},clearTimeout:timer=>{if(timer)timer.cleared=true}};
 const f=fixture(new Map(),globals);try{f.state.mode='not_accepted';await f.owner.open({profileId:'profile-a'});
  const first=f.creates()[0].body.id;assert.equal(f.owner.state.getState().flow.phase,'not_accepted');assert.equal(f.owner.state.getState().flow.auto_retries,1);
  f.state.mode='completed';const retry=timers.find(timer=>!timer.cleared&&timer.ms===3000);assert.ok(retry);retry.callback();await new Promise(resolve=>setImmediate(resolve));await new Promise(resolve=>setImmediate(resolve));
  assert.equal(f.creates().length,2);assert.equal(f.creates()[1].body.id,first);assert.equal(f.moves[0],'/chat/created-exact');
 }finally{f.close()}
});
