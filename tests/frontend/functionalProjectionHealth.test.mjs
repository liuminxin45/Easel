import assert from 'node:assert/strict';
import {test} from 'node:test';
import {moduleLoader} from './helpers/modules.mjs';
const json=(value,status=200)=>new Response(JSON.stringify(value),{status,headers:{'Content-Type':'application/json'}});
const all=value=>Array.isArray(value)?value.flatMap(all):value&&typeof value==='object'?[value,...all(value.props?.children)]:[];
const text=value=>Array.isArray(value)?value.map(text).join(''):value&&typeof value==='object'?text(value.props?.children):value==null?'':String(value);
const trend=version=>({version:1,day:'1970-01-01',timezone:'Asia/Shanghai',trends:[{platform:'temp',label:'TEMP',ok:true,status:'fresh',fetched_at:version===1?'2026-11-01T12:00:00+08:00':'2026-11-03T12:00:00+08:00',items:[{id:'t'+version,title:'TEMP '+version}]}],updated:1,warnings:[]});

test('native radar subscriptions share the existing poll, update completed results, pause and retain failures',async()=>{
 const timers=[],calls=[],load=moduleLoader({globals:{FormData,window:{location:{pathname:'/native/'},dispatchEvent(){}},setTimeout:(callback,ms)=>{const timer={callback,ms,cleared:false,unref(){}};timers.push(timer);return timer},clearTimeout:timer=>{timer.cleared=true}}});
 let value=trend(1),failure=false,clock=100;
 const client=new(load('workbench/core/client.ts').WorkbenchClient)({clock:()=>clock,fetcher:async path=>{calls.push(path);return failure?json({error:'TEMP collector unavailable'},500):json(value)}});
 client.session.setState({config:{csrf:'TEMP'},loading:false});const api=load('lib/api.ts'),release=load('workbench/ui/nativeApi.ts').bindWorkbenchNativeApi(client),path='/api/trends?limit=12&platforms=temp';
 let a,b,error;const live=()=>timers.filter(timer=>!timer.cleared),poll=()=>live().find(timer=>timer.ms<3600000);
 try{
  await api.fetchTrends('temp');const stopA=api.subscribeApiData(path,data=>{a=data},caught=>{error=caught}),stopB=api.subscribeApiData(path,data=>{b=data});
  assert.equal(live().length,2);assert.equal(poll().ms,30000);assert.ok(live().some(timer=>timer.ms>3600000));
  value=trend(2);clock+=30000;let timer=poll();timer.cleared=true;timer.callback();await new Promise(done=>setImmediate(done));
  assert.equal(calls.length,2);assert.equal(a.trends[0].items[0].title,'TEMP 2');assert.equal(b.trends[0].items[0].title,'TEMP 2');
  failure=true;clock+=30000;timer=poll();timer.cleared=true;timer.callback();await new Promise(done=>setImmediate(done));
  assert.match(error.message,/TEMP collector unavailable/);assert.equal(api.peekApiData(path).trends[0].items[0].title,'TEMP 2');assert.ok(poll().ms>=60000);
  client.pauseVisible();assert.equal(live().length,0);stopA();stopB();
 }finally{release();client.pauseVisible()}
});

function dashboard(api,file='DashboardPage',suppliedProps){
 const slots=[],effects=[];let index=0,dirty=true,tree,props=suppliedProps??{persona:'',gatewayStatus:'connected',apiDirect:false,agentRuntime:'codex',persistAnalytics:false,verifyAccountsOnMount:false,onNavigate(){},onUseTopic(){}};
 const same=(a,b)=>a&&b&&a.length===b.length&&a.every((value,i)=>Object.is(value,b[i]));
 const react={
  useState(initial){const i=index++;if(!(i in slots))slots[i]=typeof initial==='function'?initial():initial;return [slots[i],next=>{const value=typeof next==='function'?next(slots[i]):next;if(!Object.is(value,slots[i])){slots[i]=value;dirty=true}}]},
  useRef(initial){return slots[index++]??=({current:initial})},
  useMemo(fn,deps){const i=index++;if(!slots[i]||!same(slots[i].deps,deps))slots[i]={deps,value:fn()};return slots[i].value},
  useCallback(fn,deps){return react.useMemo(()=>fn,deps)},
  useEffect(fn,deps){const i=index++;if(!slots[i]||!same(slots[i].deps,deps)){const old=slots[i];slots[i]={deps};effects.push(()=>{old?.cleanup?.();slots[i].cleanup=fn()})}},
 };
 const element=(type,props)=>({type,props:props??{}}),load=moduleLoader({globals:{window:{confirm:()=>true},document:{addEventListener(){},removeEventListener(){}}},imports:{react,'react/jsx-runtime':{jsx:element,jsxs:element,Fragment:'fragment'},'../lib/api':api,'../lib/sanitize':{renderMarkdown:value=>value},'../lib/whoami':{getWhoamiCache:()=>({}),verifyStale(){}},'./DownloadLink':'DownloadLink','./icons':new Proxy({},{get:()=>function Icon(){}})}});let Page=load('components/'+file+'.tsx').default;
 return {enterChild(){for(const item of slots)item?.cleanup?.();slots.length=0;effects.length=0;Page=tree.type;props=tree.props;dirty=true},async settle(){for(let i=0;i<30;i++){if(dirty){index=0;dirty=false;tree=Page(props)}effects.splice(0).forEach(fn=>fn());await Promise.resolve()}assert.equal(dirty,false);return tree}};
}
function dashboardApi(){const subscriptions=new Map();return {subscriptions,peekApiData:()=>undefined,subscribeApiData:(path,onData,onError)=>{subscriptions.set(path,{onData,onError});return()=>{}},fetchTrends:async()=>trend(1),fetchSchedule:async()=>[],fetchIdeas:async()=>[],fetchAccounts:async()=>[],fetchOutputs:async()=>[],fetchAnalyticsPlatforms:async()=>[]}}

test('ordinary dashboard retains its original tree source and waits for the initial read',async()=>{
 const api=dashboardApi();let finish,reads=0,ready=0;api.fetchOutputs=()=>{reads++;return new Promise(resolve=>{finish=resolve})};
 const f=dashboard(api,'DashboardPage',{persona:'',gatewayStatus:'connected',apiDirect:false,agentRuntime:'codex',persistAnalytics:false,verifyAccountsOnMount:false,onNavigate(){},onUseTopic(){},onContentReady(){ready++}});
 let tree=await f.settle();assert.equal(reads,1);assert.equal(ready,0);assert.ok(text(tree).includes('正在读取最近产物'));assert.ok(api.subscriptions.has('/api/outputs'));
 finish([{type:'dir',name:'Original project',path:'old'}]);tree=await f.settle();assert.ok(ready>0);assert.ok(text(tree).includes('Original project'));
});

test('private dashboard becomes ready before bounded metadata, counts the real total and shows only five recent projects',async()=>{
 const api=dashboardApi();api.fetchOutputs=()=>assert.fail('Private home must not fetch the recursive legacy tree');let finish,ready=0;const calls=[];
 const source={list:input=>{calls.push(input);return new Promise(resolve=>{finish=resolve})},resolve:()=>assert.fail('Home must not descend into projects')};
 const f=dashboard(api,'DashboardPage',{persona:'',gatewayStatus:'connected',apiDirect:false,agentRuntime:'codex',persistAnalytics:false,verifyAccountsOnMount:false,onNavigate(){},onUseTopic(){},onContentReady(){ready++},outputsSource:source});
 let tree=await f.settle();assert.ok(ready>0);assert.equal(calls.length,1);assert.ok(!api.subscriptions.has('/api/outputs'));assert.ok(text(tree).includes('正在读取最近产物'));assert.ok(!text(tree).includes('还没有产物'));
 finish({items:Array.from({length:50},(_,i)=>({type:'dir',name:'Project '+i,path:'project-'+i})),total:912,next_cursor:'next',revision:'r1'});tree=await f.settle();
 const stat=all(tree).find(node=>node.props.className==='card card-hover dash-stat'&&text(node).includes('内容项目'));assert.ok(text(stat).includes('912'));
 const recent=all(tree).filter(node=>node.props.className==='dash-output');assert.equal(recent.length,5);assert.equal(text(recent.at(-1)),'Project 40 文件');assert.equal(calls.length,1);
});

test('private dashboard exposes a local metadata retry and forces only that bounded request',async()=>{
 const api=dashboardApi(),calls=[];api.fetchOutputs=()=>assert.fail('Private retry must never fetch the legacy tree');
 const source={list:async input=>{calls.push(input);if(!input.force)throw Error('TEMP metadata failed');return {items:[],total:0,next_cursor:null,revision:'r2'}},resolve:()=>assert.fail('No project resolve')};
 const f=dashboard(api,'DashboardPage',{persona:'',gatewayStatus:'connected',apiDirect:false,agentRuntime:'codex',persistAnalytics:false,verifyAccountsOnMount:false,onNavigate(){},onUseTopic(){},outputsSource:source});
 let tree=await f.settle();assert.ok(text(tree).includes('TEMP metadata failed'));assert.ok(!text(tree).includes('还没有产物'));const notice=all(tree).find(node=>node.props.role==='alert'&&text(node).includes('最近产物读取失败'));
 all(notice).find(node=>node.type==='button').props.onClick();tree=await f.settle();assert.equal(calls.length,2);assert.equal(calls[1].force,true);assert.ok(!text(tree).includes('TEMP metadata failed'));assert.ok(text(tree).includes('还没有产物'));
});

test('dashboard read failures remain visible and never masquerade as empty sources, schedules or account totals',async()=>{
 const api=dashboardApi();for(const key of ['fetchTrends','fetchSchedule','fetchIdeas','fetchAccounts','fetchAnalyticsPlatforms'])api[key]=async()=>{throw Error('TEMP '+key+' failed')};
 const f=dashboard(api),tree=await f.settle(),display=text(tree);
 for(const key of ['fetchTrends','fetchSchedule','fetchIdeas','fetchAccounts','fetchAnalyticsPlatforms'])assert.ok(display.includes('TEMP '+key+' failed'));
 for(const falseEmpty of ['暂无热点，请到热点雷达','还没攒选题','暂无排期，去日历','0/0','加载中 / 需配置代理'])assert.ok(!display.includes(falseEmpty));
 assert.equal(all(tree).filter(node=>node.props.className==='dash-stat-val'&&text(node)==='—').length,3);
});

test('a dashboard snapshot keeps the actual collection date and cannot hide a retained refresh error',async()=>{
 const api=dashboardApi(),snapshot=trend(1);api.peekApiData=path=>path==='/api/trends?limit=6'?snapshot:undefined;
 api.subscribeApiData=(path,onData,onError)=>{api.subscriptions.set(path,{onData,onError});if(path==='/api/trends?limit=6')onError(Error('TEMP retained SWR failure'));return()=>{}};
 const f=dashboard(api);let tree=await f.settle(),display=text(tree);
 assert.ok(display.includes('TEMP 1'));assert.ok(display.includes('2026/11/1采集'));assert.ok(display.includes('TEMP retained SWR failure'));
 api.subscriptions.get('/api/trends?limit=6').onData(trend(2));tree=await f.settle();display=text(tree);
 assert.ok(display.includes('TEMP 2'));assert.ok(display.includes('2026/11/3采集'));assert.ok(!display.includes('TEMP retained SWR failure'));
 api.subscriptions.get('/api/trends?limit=6').onError(Error('TEMP new failure'));tree=await f.settle();display=text(tree);assert.ok(display.includes('TEMP 2'));assert.ok(display.includes('TEMP new failure'));
});

test('dashboard explicit retry bypasses old snapshots and only clears the matching real success',async()=>{
 const api=dashboardApi(),forces=[];api.peekApiData=path=>path==='/api/trends?limit=6'?trend(1):path==='/api/outputs'?[]:undefined;
 api.fetchTrends=async(_sources,_limit,force)=>{forces.push(['trends',force]);return trend(2)};api.fetchOutputs=async force=>{forces.push(['outputs',force]);return []};
 api.subscribeApiData=(path,onData,onError)=>{api.subscriptions.set(path,{onData,onError});if(['/api/trends?limit=6','/api/outputs'].includes(path))onError(Error('TEMP stale '+path));return()=>{}};
 const f=dashboard(api);let tree=await f.settle();assert.ok(text(tree).includes('TEMP stale /api/outputs'));
 for(const part of ['热点读取失败','最近产物读取失败']){const notice=all(tree).find(node=>node.props.role==='alert'&&text(node).includes(part));await all(notice).find(node=>node.type==='button').props.onClick();tree=await f.settle()}
 assert.ok(forces.some(([key,force])=>key==='trends'&&force===true));assert.ok(forces.some(([key,force])=>key==='outputs'&&force===true));assert.ok(!text(tree).includes('TEMP stale'));
});

test('breakdown failures remain errors rather than saveable analysis, even with an earlier task',async()=>{
 const api=dashboardApi(),f=dashboard(api,'BreakdownPage',{persona:'p',inputState:{value:'Exact reference',onChange(){}},resultContent:{type:'old-task',props:{children:'Earlier task result'}},onAnalyze:async()=>{throw Error('TEMP analysis refused')}});
 let tree=await f.settle();await all(tree).find(node=>node.type==='button'&&text(node).includes('开始拆解')).props.onClick();tree=await f.settle();
 assert.ok(all(tree).some(node=>node.props.role==='alert'&&text(node).includes('TEMP analysis refused')));
 assert.ok(!all(tree).some(node=>node.type==='button'&&text(node).includes('存入选题库')));
});

test('profile SWR refresh updates server files while preserving unsaved input and its captured revision',async()=>{
 const api=dashboardApi(),path='/api/persona/p/files',first={name:'p',revision:1,files:[{filename:'identity.md',content:'Server original'}]},draft={fields:{'identity.md':'Exact unsaved input'},revision:1};
 api.peekApiData=p=>p===path?first:undefined;api.fetchPersonas=async()=>[{name:'p'}];api.fetchPersonaFiles=async()=>first;
 const f=dashboard(api,'ProfilePage',{persona:'p',onUsePersona(){},onNewProfile(){},onDeleted(){},allowDelete:false,allowAccountImport:false,draftStore:{read:()=>draft,write(){},remove(){}}});
 await f.settle();f.enterChild();let tree=await f.settle();assert.equal(all(tree).find(node=>node.type==='textarea').props.value,'Exact unsaved input');
 assert.ok(api.subscriptions.has(path));api.subscriptions.get(path).onData({...first,revision:2,files:[{filename:'identity.md',content:'New server revision'}]});tree=await f.settle();
 assert.equal(all(tree).find(node=>node.type==='textarea').props.value,'Exact unsaved input');assert.ok(text(tree).includes('服务器画像已有新修订'));assert.equal(draft.revision,1);
});

test('profile list SWR changes become visible without navigating away',async()=>{
 const api=dashboardApi();api.fetchPersonas=async()=>[];
 const f=dashboard(api,'ProfilePage',{persona:'',onUsePersona(){},onNewProfile(){},onDeleted(){}});await f.settle();assert.ok(api.subscriptions.has('/api/personas'));
 api.subscriptions.get('/api/personas').onData([{name:'New actual profile',description:'New actual description'}]);const tree=await f.settle();assert.ok(text(tree).includes('New actual profile'));
});

test('calendar read successes do not clear failures from another independent endpoint',async()=>{
 const api=dashboardApi();api.fetchSchedule=async()=>[];api.fetchScheduleContext=async()=>{throw Error('TEMP context failed')};
 const f=dashboard(api,'CalendarPage',{});let tree=await f.settle();assert.ok(text(tree).includes('TEMP context failed'));
 api.subscriptions.get('/api/schedule').onData([]);tree=await f.settle();assert.ok(text(tree).includes('TEMP context failed'));
 api.subscriptions.get('/api/schedule/context?days=14').onData({suggestions:[]});tree=await f.settle();assert.ok(!text(tree).includes('TEMP context failed'));
 api.subscriptions.get('/api/schedule').onError(Error('TEMP schedule failed'));api.subscriptions.get('/api/schedule/context?days=14').onData({suggestions:[]});tree=await f.settle();assert.ok(text(tree).includes('TEMP schedule failed'));
});

test('the ideas explicit reread forces a real request rather than accepting a stale snapshot',async()=>{
 const api=dashboardApi(),calls=[];api.fetchIdeas=async force=>{calls.push(force);if(!force)throw Error('TEMP ideas failed');return []};
 const f=dashboard(api,'IdeasPage',{onUseTopic(){}});let tree=await f.settle();await all(tree).find(node=>node.type==='button'&&text(node)==='重新读取选题').props.onClick();tree=await f.settle();assert.equal(calls.at(-1),true);assert.ok(!text(tree).includes('TEMP ideas failed'));
});

test('text previews show 403 and 500 errors with retry instead of an unhandled empty preview',async()=>{
 for(const status of [403,500]){
  const api=dashboardApi(),file={type:'file',name:'original.md',path:'original.md',kind:'text'};let fail=true;
  api.fetchOutputs=async()=>[file];api.mediaUrl=path=>'/media/'+path;api.fetchOutputContent=async()=>{if(fail)throw Error('TEMP preview '+status);return {content:'Actual original text'}};
  const f=dashboard(api,'OutputsPage',{canDelete:()=>false});let tree=await f.settle();await assert.doesNotReject(()=>all(tree).find(node=>node.props.className?.includes('gcard')&&node.props.onClick).props.onClick());tree=await f.settle();
  assert.ok(all(tree).some(node=>node.props.role==='alert'&&text(node).includes('TEMP preview '+status)));
  fail=false;await all(tree).find(node=>node.type==='button'&&text(node)==='重试预览').props.onClick();tree=await f.settle();assert.ok(all(tree).some(node=>node.props.dangerouslySetInnerHTML?.__html==='Actual original text'));assert.ok(!text(tree).includes('TEMP preview '+status));
 }
});

test('a late failed preview cannot put an error into the next file preview',async()=>{
 const api=dashboardApi(),files=['a','b'].map(name=>({type:'file',name:name+'.md',path:name+'.md',kind:'text'}));let reject;
 api.fetchOutputs=async()=>files;api.mediaUrl=path=>'/media/'+path;api.fetchOutputContent=async path=>path==='a.md'?await new Promise((_resolve,no)=>{reject=no}):{content:'File B current'};
 const f=dashboard(api,'OutputsPage',{canDelete:()=>false});let tree=await f.settle(),cards=all(tree).filter(node=>node.props.className?.includes('gcard')&&node.props.onClick);const a=cards[0].props.onClick();await cards[1].props.onClick();tree=await f.settle();reject(Error('TEMP late file A'));await assert.doesNotReject(()=>a);tree=await f.settle();assert.ok(!text(tree).includes('TEMP late file A'));assert.ok(all(tree).some(node=>node.props.dangerouslySetInnerHTML?.__html==='File B current'));
});

test('explicit profile and text preview rereads use reload while default Easel requests keep their original behavior',async()=>{
 const load=moduleLoader({globals:{window:{location:{pathname:'/'}}}}),api=load('lib/api.ts'),calls=[];
 const release=api.bindEaselApiTransport({request:async(path,options)=>{calls.push({path,options});return []}});
 try{
  await api.fetchPersonas();await api.fetchPersonas(true);await api.fetchPersonaFiles('p');await api.fetchPersonaFiles('p',true);await api.fetchOutputContent('folder/original.md');await api.fetchOutputContent('folder/original.md',true);
  for(let i=0;i<calls.length;i++)assert.equal(calls[i].options?.cache,i%2?'reload':undefined);
  assert.equal(calls[5].path,'/api/output/folder/original.md');
 }finally{release()}
});
