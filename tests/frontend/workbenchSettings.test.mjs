import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';
const json=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});
function setup(){
 const storage=new Map(),posts=[],gets=[],events=[];let receipt={state:'pending'},fail=false;
 const load=moduleLoader({globals:{window:{dispatchEvent:event=>events.push(event)},Event}}),{WorkbenchClient}=load('workbench/core/client.ts');
 const client=new WorkbenchClient({storage:{get length(){return storage.size},key:n=>[...storage.keys()][n],getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)},retryDelay:0,fetcher:async(path,options)=>{
  if(options?.method==='POST'){const body=JSON.parse(options.body);posts.push({path,body,csrf:options.headers['X-CSRF-Token']});if(fail)throw new TypeError('dropped response');return json({revision:body.expected_revision+1,runtime:'codex'})}
  gets.push(path);return json(path.startsWith('/api/settings/operations/')?receipt:{revision:4,runtime:'codex'});
 }});client.session.setState({config:{csrf:'owner-csrf'},loading:false});
 const api=load('workbench/ui/settingsApi.ts').workbenchSettingsApi(client);
 return {api,client,storage,posts,gets,events,set receipt(value){receipt=value},set fail(value){fail=value}};
}

test('settings share CSRF and revision handling while only persisting operation metadata',async()=>{
 const f=setup();await f.api.fetchHarnessSettings();f.fail=true;
 await assert.rejects(f.api.saveModelConfig('chat',[{slot:'direct-api',model:'m',baseUrl:'https://example.com/v1',key:'PRIVATE_DRAFT_KEY'}]));
 assert.equal(f.posts[0].csrf,'owner-csrf');assert.equal(f.posts[0].body.expected_revision,4);assert.ok(f.posts[0].body.id);
 assert.ok(!JSON.stringify([...f.storage]).includes('PRIVATE_DRAFT_KEY'));const pending=f.client.operation('settings').getState().pending;
 assert.equal(pending.id,f.posts[0].body.id);assert.equal(pending.metadataOnly,true);assert.deepEqual(JSON.parse(JSON.stringify(pending.body)),{});f.client.pauseVisible();
});

test('lost settings replies recover the exact receipt through the common GET path',async()=>{
 const f=setup();f.fail=true;await assert.rejects(f.api.saveHarnessSettings('codex','m','workspace-write',false));
 const id=f.posts[0].body.id;f.receipt={state:'completed',result:{revision:8,runtime:'codex'}};
 const result=await f.api.saveHarnessSettings('codex','m','workspace-write',false);
 assert.equal(result.revision,8);assert.equal(f.posts.length,1);assert.ok(f.gets.includes('/api/settings/operations/'+id));assert.equal(f.storage.size,0);f.client.pauseVisible();
});

test('a changed form saves its own input after the previous acknowledgement resolves',async()=>{
 const f=setup();f.fail=true;await assert.rejects(f.api.saveHarnessSettings('codex','first','workspace-write',false));
 f.receipt={state:'completed',result:{revision:8,runtime:'codex'}};f.fail=false;
 const result=await f.api.saveHarnessSettings('codex','edited-later','workspace-write',false);
 assert.equal(result.revision,9);assert.equal(f.posts.length,2);assert.equal(f.posts[1].body.model,'edited-later');assert.equal(f.posts[1].body.expected_revision,8);assert.notEqual(f.posts[0].body.id,f.posts[1].body.id);f.client.pauseVisible();
});

test('an unknown provider request keeps its exact identity without another POST',async()=>{
 const f=setup();f.fail=true;await assert.rejects(f.api.fetchAvailableModels('https://example.com','SECRET','openai'));
 await assert.rejects(f.api.fetchAvailableModels('https://example.com','SECRET','openai'),/连接恢复中/);assert.equal(f.posts.length,1);assert.ok(!JSON.stringify([...f.storage]).includes('SECRET'));f.client.pauseVisible();
});

test('old metadata-only settings drafts are recovered without replay or losing current form fields',async()=>{
 const f=setup();f.storage.set('toolbox:draft:settings:pending',JSON.stringify({operation_id:'legacy-settings',path:'/api/settings/harness',signature:'old-sha',pending:true}));
 f.receipt={state:'completed',result:{revision:7,runtime:'codex'}};
 const result=await f.api.saveHarnessSettings('codex','new-model','workspace-write',false);
 assert.equal(result.revision,8);assert.equal(f.posts.length,1);assert.notEqual(f.posts[0].body.id,'legacy-settings');assert.equal(f.posts[0].body.expected_revision,7);assert.equal(f.storage.size,0);f.client.pauseVisible();
});

test('a definite recovered settings rejection releases the identity and exposes the actual reason',async()=>{
 const f=setup();f.fail=true;await assert.rejects(f.api.saveHarnessSettings('codex','bad','workspace-write',false));
 f.receipt={state:'rejected',result:{error:'模型名称无效'}};
 await assert.rejects(f.client.reconcile('settings'),/模型名称无效/);assert.equal(f.client.operation('settings').getState().pending,null);assert.equal(f.storage.size,0);f.client.pauseVisible();
});
