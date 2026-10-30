import assert from 'node:assert/strict';
import {readFileSync,existsSync} from 'node:fs';
import path from 'node:path';
import {createRequire} from 'node:module';
import {runInNewContext} from 'node:vm';
import {test} from 'node:test';
import {webcrypto} from 'node:crypto';
const require=createRequire(new URL('../../web/frontend/package.json',import.meta.url)),ts=require('typescript'),cache=new Map();
const root=path.resolve('web/frontend/src/workbench/core');
function load(file){
 file=path.resolve(file);if(cache.has(file))return cache.get(file);
 const exports={};cache.set(file,exports);
 runInNewContext(ts.transpileModule(readFileSync(file,'utf8'),{compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,esModuleInterop:true}}).outputText,{exports,URL,URLSearchParams,crypto:webcrypto,TextEncoder,TextDecoder,Blob,File,Response,Headers,AbortController,AbortSignal,setTimeout,clearTimeout,performance,fetch,require:id=>{if(!id.startsWith('.'))return require(id);const target=path.resolve(path.dirname(file),id);if(id.endsWith('.json'))return JSON.parse(readFileSync(target,'utf8'));return load(existsSync(target+'.ts')?target+'.ts':target+'.tsx')}});
 return exports;
}
const {WorkbenchClient}=load(path.join(root,'client.ts'));
const {resourceFreshMs,resourceCacheable}=load(path.join(root,'resource-cache.ts'));
const json=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve}};
function fixture(fetcher,storage=new Map()){
 const client=new WorkbenchClient({fetcher,retryDelay:0,storage:{get length(){return storage.size},key:n=>[...storage.keys()][n],getItem:key=>storage.get(key)||null,setItem:(key,value)=>storage.set(key,value),removeItem:key=>storage.delete(key)}});
 client.session.setState({config:{csrf:'fixture'},loading:false});return {client,storage};
}

test('a normal pending request is busy but not uncertain, and prevents double clicks',async()=>{
 const response=deferred();let posts=0;const {client}=fixture(async()=>{posts++;return response.promise});
 const first=client.mutate('account','/api/platform-accounts',{action:'login',session_id:'one'});
 assert.equal(client.operation('account').getState().busy,true);assert.equal(client.operation('account').getState().pending.uncertain,false);
 await assert.rejects(client.mutate('account','/api/platform-accounts',{action:'login',session_id:'one'}),/正在处理/);
 response.resolve(json({id:'accepted'}));await first;assert.equal(posts,1);assert.equal(client.operation('account').getState().pending,null);
});

test('acknowledged commands return before slow resource refresh, without regaining unknown state',async()=>{
 const refresh=deferred();let reads=0;const {client}=fixture(async(_path,options)=>options?.method==='POST'?json({ok:true}):(reads++,refresh.promise));
 const release=client.watch('/api/platform-accounts');client.resource('/api/platform-accounts').setState({data:{sessions:[]},loading:false});
 const result=await client.mutate('account','/api/platform-accounts',{action:'login'});assert.equal(result.ok,true);assert.equal(reads,1);assert.equal(client.operation('account').getState().busy,false);assert.equal(client.operation('account').getState().pending,null);
 refresh.resolve(json({sessions:[]}));release();
});

test('a dropped POST response recovers its stored receipt with GET, without a second POST',async()=>{
 const calls=[];let identity;const receipt={status:'accepted',result:{session:{id:'original-session',revision:2}}};
 const {client,storage}=fixture(async(url,options)=>{calls.push([url,options?.method||'GET']);if(options?.method==='POST'){identity=JSON.parse(options.body).id;throw new TypeError('connection dropped')}return json({id:identity,state:'received',result:receipt})});
 const result=await client.mutate('account','/api/platform-accounts',{action:'login',session_id:'original-session'});
 assert.equal(result.result.session.id,'original-session');assert.deepEqual(calls.map(c=>c[1]),['POST','GET']);assert.ok(calls[1][0].includes(encodeURIComponent(identity)));assert.equal(storage.size,0);
});

test('an absent receipt keeps the exact input and identity, without replay or blocking another account',async()=>{
 let posts=0,identity;const {client,storage}=fixture(async(url,options)=>{if(options?.method==='POST'){posts++;const body=JSON.parse(options.body);if(body.session_id==='two')return json({ok:true});identity=body.id;throw new TypeError('offline')}return json({id:identity,state:'waiting'})});
 await assert.rejects(client.mutate('account:one','/api/platform-accounts',{action:'login',session_id:'one',raw:'  原输入\n'}),/正在恢复/);
 const pending=client.operation('account:one').getState().pending;assert.equal(pending.id,identity);assert.equal(pending.body.raw,'  原输入\n');assert.equal(pending.uncertain,true);
 await client.reconcile('account:one');await assert.rejects(client.retry('account:one'),/输入已保留/);assert.equal(posts,1);assert.equal(storage.size,1);
 await client.mutate('account:two','/api/platform-accounts',{action:'login',session_id:'two'});assert.equal(posts,2);assert.equal(client.operation('account:one').getState().pending.id,identity);
});

test('refreshing a page restores and resolves the original operation using only GET',async()=>{
 const storage=new Map();let identity;const original=fixture(async(url,options)=>{if(options?.method==='POST'){identity=JSON.parse(options.body).id;throw new TypeError('offline')}return json({id:identity,state:'waiting'})},storage);
 await assert.rejects(original.client.mutate('account','/api/platform-accounts',{action:'create',platform:'wechat-oa'}));
 const methods=[];const resumed=fixture(async(_url,options)=>{methods.push(options?.method||'GET');return json({id:identity,state:'received',result:{result:{session:{id:'kept-session'}}}})},storage);
 assert.equal(resumed.client.operation('account').getState().pending.id,identity);const result=await resumed.client.reconcile('account');assert.equal(result.result.session.id,'kept-session');assert.deepEqual(methods,['GET']);assert.equal(storage.size,0);
});

test('background receipt recovery also runs without a mounted operation component',async()=>{
 let identity,posts=0,reads=0;const {client}=fixture(async(_url,options)=>{if(options?.method==='POST'){posts++;identity=JSON.parse(options.body).id;throw new TypeError('dropped')}return json(++reads===1?{id:identity,state:'waiting'}:{id:identity,state:'received',result:{ok:true}})});
 await assert.rejects(client.mutate('unmounted','/api/creator/commands',{action:'skill-publish'}));
 const deadline=Date.now()+4000;while(client.operation('unmounted').getState().pending&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,30));
 assert.equal(client.operation('unmounted').getState().pending,null);assert.equal(posts,1);assert.equal(reads,2);client.pauseVisible();
});

test('definite validation errors release the operation and allow corrected input',async()=>{
 let posts=0;const {client,storage}=fixture(async()=>++posts===1?json({error:'请填写名称'},400):json({ok:true}));
 await assert.rejects(client.mutate('profile','/api/creator/commands',{name:''}),/请填写名称/);assert.equal(storage.size,0);assert.equal(client.operation('profile').getState().pending,null);
 await client.mutate('profile','/api/creator/commands',{name:'修正名称'});assert.equal(posts,2);
});

test('a late recovered receipt cannot clear the draft after the login identity changes',async()=>{
 let identity;const response=deferred();const {client,storage}=fixture(async(url,options)=>{if(options?.method==='POST'){identity=JSON.parse(options.body).id;throw new TypeError('offline')}return json({id:identity,state:'waiting'})});
 await assert.rejects(client.mutate('account','/api/platform-accounts',{action:'login'}));client.api.get=()=>response.promise;
 const recovering=client.reconcile('account');client.expireSession();response.resolve({id:identity,state:'received',result:{ok:true}});assert.equal(await recovering,null);assert.equal(storage.size,1);assert.equal(client.operation('account').getState().pending.id,identity);
});

test('missing login validation never records a submission that did not happen',async()=>{
 const {client,storage}=fixture(async()=>assert.fail('must not send'));client.session.setState({config:null});
 await assert.rejects(client.mutate('account','/api/platform-accounts',{action:'login'}),/登录校验/);assert.equal(storage.size,0);assert.equal(client.operation('account').getState().pending,null);
});

test('active login observations refresh at 1.5s and operation receipts never enter the resource cache',()=>{
 assert.equal(resourceFreshMs('/api/platform-accounts',{sessions:[{state:'login'}]}),1500);assert.equal(resourceFreshMs('/api/platform-accounts',{sessions:[{state:'connected'}]}),30000);assert.equal(resourceCacheable('/api/operations/original?path=x'),false);
});


test('exact profile acknowledgements become visible before background bootstrap refresh',async()=>{
 let resolveRead;const waiting=new Promise(resolve=>resolveRead=resolve);const {client}=fixture(async(_path,options)=>options?.method==='POST'?json({result:{profile:{id:'new-profile',revision:1,name:'准确新画像'}}}):waiting);
 client.resource('/api/creator/bootstrap').setState({data:{profiles:[]},loading:false});const release=client.watch('/api/creator/bootstrap');
 await client.service.creatorCommand('profile-save',{document:{name:'准确新画像'}});
 const profile=client.resource('/api/creator/bootstrap').getState().data.profiles[0];assert.equal(profile.id,'new-profile');assert.equal(profile.revision,1);assert.equal(client.operation('creator:profile-save:').getState().busy,false);
 resolveRead(json({profiles:[profile]}));release();client.pauseVisible();
});

test('independent studio actions do not share an unresolved form lock',async()=>{
 let identity,posts=0;const {client}=fixture(async(_path,options)=>{if(options?.method==='POST'){posts++;const body=JSON.parse(options.body);if(body.action==='comment-add')return json({result:{comment:{id:'comment',revision:1}}});identity=body.id;throw new TypeError('offline')}return json({id:identity,state:'waiting'})});
 await assert.rejects(client.service.studio('metric-import',{publication_id:'publication-one'}));
 const response=await client.service.studio('comment-add',{publication_id:'publication-two',text:'原字反馈'});
 assert.equal(response.comment.id,'comment');assert.equal(posts,2);assert.ok(client.operation('studio:metric-import:publication-one').getState().pending);client.pauseVisible();
});

test('a legacy global studio operation retains its ID when action scopes are split',async()=>{
 const body={id:'old-metric',operation_id:'old-metric',action:'metric-import',publication_id:'publication-one'},storage=new Map([['toolbox:draft:native:pending:studio',JSON.stringify({operation:{scope:'studio',path:'/api/studio/commands',body,id:'old-metric',uncertain:true}})]]);
 let posts=0;const {client}=fixture(async(_path,options)=>{if(options?.method==='POST'){posts++;return json({})}return json({id:'old-metric',state:'received',result:{result:{import:{id:'original-import'}}}})},storage);
 const response=await client.service.studio('metric-import',{publication_id:'publication-one'});assert.equal(response.import.id,'original-import');assert.equal(posts,0);assert.equal(storage.size,0);client.pauseVisible();
});

test('an older account acknowledgement cannot replace a more recent verified observation',async()=>{
 const {client}=fixture(async()=>json({result:{session:{id:'account',revision:2,state:'login'}}}));client.resource('/api/platform-accounts').setState({data:{sessions:[{id:'account',revision:4,state:'connected'}]},loading:false});
 await client.mutate('account','/api/platform-accounts',{action:'login',session_id:'account'});
 assert.equal(client.resource('/api/platform-accounts').getState().data.sessions[0].state,'connected');client.pauseVisible();
});

test('an older in-flight read cannot overwrite an acknowledged setting before verification completes',async()=>{
 const earlier=deferred(),verified=deferred();let reads=0;const {client}=fixture(async()=>++reads===1?earlier.promise:verified.promise);
 client.resource('/api/usage/summary').setState({data:{config:{enabled:true}},loading:false});const reading=client.read('/api/usage/summary',true);
 client.updateResource('/api/usage/summary',previous=>({...previous,config:{enabled:false}}));earlier.resolve(json({config:{enabled:true}}));
 const deadline=Date.now()+1000;while(reads<2&&Date.now()<deadline)await new Promise(resolve=>setTimeout(resolve,10));
 assert.equal(reads,2);assert.equal(client.resource('/api/usage/summary').getState().data.config.enabled,false);
 verified.resolve(json({config:{enabled:false}}));await reading;assert.equal(client.resource('/api/usage/summary').getState().data.config.enabled,false);client.pauseVisible();
});
