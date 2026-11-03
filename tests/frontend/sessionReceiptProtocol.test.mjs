import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';

const json=(body,status=200,headers={})=>new Response(JSON.stringify(body),{status,headers:{'Content-Type':'application/json',...headers}});
const envelope=(id,state,extra={})=>({protocol_version:2,operation_id:id,operation_state:state,...extra});
const completed=id=>({session:{id:'session-'+id,profile_id:'oil-pig',revision:1}});
function fixture(){
 const values=new Map(),calls=[],state={response:()=>json({})},load=moduleLoader({globals:{FormData}});
 const storage={fail:false,get length(){return values.size},key:n=>[...values.keys()][n],getItem:k=>values.get(k)??null,setItem(k,v){if(this.fail)throw Error('full');values.set(k,v)},removeItem:k=>values.delete(k)};
 const {WorkbenchClient}=load('workbench/core/client.ts'),{RequestError}=load('workbench/core/transport.ts');
 const client=new WorkbenchClient({storage,retryDelay:0,fetcher:async(path,options)=>{calls.push({path,...options});return state.response(path,options)}});
 client.session.setState({config:{csrf:'TEMP'},loading:false});client.pauseVisible();
 return {client,values,storage,calls,state,RequestError};
}
const input=id=>({id,action:'create',profile_id:'oil-pig'});
const create=(f,id='one')=>f.client.mutate('session-open:'+id,'/api/chat/sessions',input(id),{receiptProtocol:2});

test('only a matching versioned not-accepted proof releases a rejected creation, including a 503',async()=>{
 for(const valid of [true,false]){
  const f=fixture();f.state.response=(path,options)=>options.method?json({...envelope(valid?'one':'other','not_accepted'),error:'switching',code:'admission_paused'},503,{'X-Workbench-Operation-Protocol':'2','X-Desk-Trace':'safe-trace'}):json({id:'one',state:'waiting'});
  await assert.rejects(create(f),error=>valid?error.acceptance==='not_accepted'&&error.operationId==='one'&&error.code==='admission_paused':error.uncertain);
  assert.equal(!!f.client.operation('session-open:one').getState().pending,!valid);
  assert.equal(f.calls[0].headers['X-Workbench-Operation-Protocol'],'2');
 }
});

test('accepted 202 keeps the original pending identity until a completed receipt is durably applied',async()=>{
 const f=fixture();let final=false;f.state.response=(_path,options)=>options.method?json(envelope('one','accepted'),202):json({id:'one',state:final?'received':'waiting',...envelope('one',final?'completed':'running'),...(final?{result:completed('one')}:{})});
 const value=await create(f);assert.equal(value.operation_state,'accepted');
 assert.equal(f.client.operation('session-open:one').getState().pending.acceptance,'accepted');
 await f.client.reconcile('session-open:one');assert.ok(f.client.operation('session-open:one').getState().pending);
 let applied=false;f.client.beforeOperationComplete('session-open:one',result=>{assert.ok(f.client.operation('session-open:one').getState().pending);assert.equal(result.session.id,'session-one');applied=true});
 final=true;await f.client.reconcile('session-open:one');assert.ok(applied);
 assert.equal(f.client.operation('session-open:one').getState().pending,null);
 const receipt=f.client.drafts.get('native:session-receipt:one');assert.equal(receipt.session_id,'session-one');assert.ok(!Object.hasOwn(receipt,'session'));
 assert.equal(f.calls.filter(c=>c.method==='POST').length,1);
});

test('a committed response lost on the wire is recovered by GET and invokes the same pre-clear completion hook',async()=>{
 const f=fixture();f.state.response=(_path,options)=>{if(options.method)throw new TypeError('lost');return json({id:'one',state:'received',...envelope('one','completed'),result:completed('one')})};
 let saved=0;f.client.beforeOperationComplete('session-open:one',()=>{saved++;return true});
 const value=await create(f);assert.equal(value.session.id,'session-one');assert.equal(saved,1);
 assert.equal(f.calls.filter(c=>c.method==='POST').length,1);assert.equal(f.client.operation('session-open:one').getState().pending,null);
});

test('local completion persistence failure preserves the known identity rather than generating another creation',async()=>{
 const f=fixture();f.state.response=()=>json({...envelope('one','completed'),...completed('one'),result:completed('one')});
 const stop=f.client.beforeOperationComplete('session-open:one',()=>false);
 await assert.rejects(create(f),error=>error.code==='local_persistence_failed'&&error.acceptance==='accepted');
 assert.equal(f.client.operation('session-open:one').getState().pending.id,'one');
 assert.equal(f.client.operation('session-open:one').getState().result.session.id,'session-one');
 stop();f.state.response=()=>json({id:'one',state:'received',...envelope('one','completed'),result:completed('one')});
 await f.client.reconcile('session-open:one');assert.equal(f.client.operation('session-open:one').getState().pending,null);
 assert.equal(f.calls.filter(c=>c.method==='POST').length,1);
});

test('legacy create retirement requires server proof, archives its identity and cannot retire other commands',()=>{
 const f=fixture(),pending={id:'old',path:'/api/chat/sessions',scope:'chat:create',body:input('old'),uncertain:true};
 f.client.drafts.set('native:pending:chat:create',{operation:pending});f.client.operation('chat:create');
 assert.throws(()=>f.client.resolveSessionOperation('chat:create','old',envelope('other','sealed_not_accepted')),/不匹配/);
 assert.ok(f.client.operation('chat:create').getState().pending);
 assert.equal(f.client.resolveSessionOperation('chat:create','old',envelope('old','sealed_not_accepted')),true);
 assert.equal(f.client.operation('chat:create').getState().pending,null);assert.equal(f.client.drafts.get('native:resolved:old').operation.id,'old');
 assert.equal(f.client.resolveSessionOperation('chat:create','old',envelope('old','sealed_not_accepted')),false);
});

test('a wrong-operation direct completion is never applied and only the original identity is queried',async()=>{
 const f=fixture();f.state.response=(_path,options)=>options.method?json({...envelope('other','completed'),...completed('other')}):json({id:'one',state:'waiting'});
 let applied=0;f.client.beforeOperationComplete('session-open:one',()=>{applied++});
 await assert.rejects(create(f),error=>error.uncertain);assert.equal(applied,0);
 assert.equal(f.client.operation('session-open:one').getState().pending.id,'one');assert.equal(f.client.drafts.get('native:session-receipt:one'),null);
});
