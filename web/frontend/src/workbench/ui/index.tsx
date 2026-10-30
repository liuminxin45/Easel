import {ActionButton} from './common';
import React,{useEffect,useLayoutEffect,useRef,useState} from 'react';
import App,{topicPrompt} from '../../App';
import type {Page} from '../../components/Sidebar';
import {bindWorkbenchNativeApi} from './nativeApi';
import {ChatSessionView,nativeSkillChoices,type NativeSkill,type NativeSessions,type NativeSelection} from './ChatSessionView';
import {NativeSkills} from './NativeSkills';
import {useWorkbench,useResource,useDraft,useAsyncAction,creationDestination,workPath,statusLabel,string,array,record,type WorkList,type CreatorBootstrap,type JsonRecord,type DraftAttachment} from '@workbench/core';
import {IconDashboard,IconChat,IconSkills,IconOutputs,IconAccounts,IconProfile,IconPlus,IconFire,IconCalendar,IconPublish,IconChart} from './components/icons';
import {IconGear} from './components/settingsIcons';
import SettingsSelect from './components/SettingsSelect';
import {Notice,Modal} from './common';
import {Dashboard,Library,Research} from './overview';
import {nativePageRoutes} from '../platform/native-routes';
import NativeNews from './NativeNews';
import {sessionRuntime,type FrozenTurn} from './chatRuntime';
import {generateSessionTitle} from '../../lib/store';
import {Production,WorkPage} from './production';
import {Skills,Profiles,Accounts} from './management';
import {Publishing} from './publishing';
import {Settings,LocalInputs} from './system';
import '../../index.css';
import './styles/workbench.css';
import './styles/mobile.css';

export interface EaselProps{theme:'light'|'dark';onThemeChange:(theme:'light'|'dark')=>void}
const icons:Record<string,React.ReactNode>={workbench:<IconDashboard size={18}/>,chat:<IconChat size={18}/>,skills:<IconSkills size={18}/>,content:<IconOutputs size={18}/>,accounts:<IconAccounts size={18}/>,profiles:<IconProfile size={18}/>};
function active(id:string,path:string){const u=new URL(path,location.origin),s=u.searchParams.get('section');return id==='workbench'?u.pathname==='/toolbox'&&!['skills','profiles','distribution'].includes(s||''):id==='chat'?u.pathname==='/chat'||u.pathname.startsWith('/chat/'):id==='content'?/^\/(posters|articles|works)(\/|$)/.test(u.pathname):id==='accounts'?s==='distribution'&&u.searchParams.get('pane')==='connections':id==='skills'?s==='skills':id==='profiles'?s==='profiles':false}
export function EaselWorkbench({theme,onThemeChange}:EaselProps){const vm=useWorkbench(),{config,navigation,navigate}=vm,path=creationDestination(navigation.path);
 const priorPage=useRef('/toolbox'),settingsOpen=['/settings','/account'].includes(new URL(path,location.origin).pathname),shownPath=settingsOpen?priorPage.current:path;
 if(!settingsOpen)priorPage.current=path;
 const u=new URL(shownPath,location.origin),p=u.pathname,q=u.searchParams,sidebar=useRef<HTMLDivElement>(null),creators=useResource<CreatorBootstrap>(vm.ready?'/api/creator/bootstrap':null),sessions=useResource<NativeSessions>(vm.ready?'/api/chat/sessions':null,{interval:10000}),chatAction=useAsyncAction(),[selected,patch]=useDraft('creator:current',{profile_id:'oil-pig'});
 const booted=useRef(false);if(vm.ready)booted.current=true;
 const [binding,setBinding]=useState<{client:object;epoch:number}|null>(null),epoch=vm.client.authenticationEpoch;
 const apiReady=binding?.client===vm.client&&binding.epoch===epoch;
 useLayoutEffect(()=>{const release=bindWorkbenchNativeApi(vm.client);setBinding({client:vm.client,epoch});return release},[vm.client,epoch]);
 useEffect(()=>{document.documentElement.dataset.theme=theme},[theme]);useEffect(()=>{if(path!==navigation.path)navigation.replace(path,{preserveScroll:true})},[path,navigation.path]);
 const runtimeStatus=useResource<JsonRecord>(vm.ready?'/api/status':null,{interval:30000});
 useEffect(()=>{const reload=()=>void runtimeStatus.reload();window.addEventListener('workbench:settings-changed',reload);return()=>window.removeEventListener('workbench:settings-changed',reload)},[runtimeStatus.reload]);
 const nativeId=p.startsWith('/chat/')?decodeURIComponent(p.slice(6)):q.get('session')||'',activeSession=sessions.data?.sessions.find(session=>session.id===nativeId),profile=q.get('profile')||activeSession?.profile_id||activeSession?.persona||selected.profile_id;
 const open=(target:string)=>{navigate(target,{intent:'module'})};
 const createChat=async(wantedProfile=profile,command?:NativeSelection,text='',files:DraftAttachment[]=[],articleId?:string,articleMode?:'auto'|'product',topicTitle?:string)=>{let created:string|undefined;const ticket=navigation.ticket?.();await chatAction.run(async()=>{
  const response=await vm.client.mutate<JsonRecord>('chat:create','/api/chat/sessions',{action:'create',profile_id:wantedProfile}),session=record(response.session||record(response.result).session||response),id=string(session.id);if(!id)throw Error('服务器尚未返回会话标识');
  if((text||command||files.length)&&!vm.client.drafts.set('chat:'+id,{text,files,...(command?{command}:{}),...(articleId?{article_id:articleId}:{}),...(articleMode?{article_mode:articleMode}:{})}))throw Error('本机输入暂未保存，原窗口仍保留，请恢复存储后再带入对话。');created=id;void sessions.reload();
  const target='/chat/'+encodeURIComponent(id)+(p==='/chat'&&q.has('skill')?'?'+q.toString():'');if(ticket&&navigation.finishFlow)navigation.finishFlow(target,ticket);else navigate(target,{intent:'flow'});
  if(topicTitle){const turn:FrozenTurn={turnId:crypto.randomUUID(),message:text,attachments:[],context:{profile_id:wantedProfile},inputs:{text,files:[]},state:'connecting',initial_title:generateSessionTitle(topicTitle)};sessionRuntime(vm.client,id).connect(turn,wantedProfile);}

 });return created};
 const useTopic=(title:string)=>{if(!title.trim())return;
  const prompt=topicPrompt(title);
  void createChat(profile,undefined,prompt,[],undefined,undefined,title);
 };
 const changeProfile=(id:string)=>{if(id==='__new__'){open('/toolbox?section=profiles&item=new');return}patch({profile_id:id});void createChat(id)};
 const sessionCommand=(action:string,id:string,extra:JsonRecord={})=>void chatAction.run(async()=>{const current=sessions.data?.sessions.find(value=>value.id===id);await vm.client.mutate('chat:'+action+':'+id,'/api/chat/sessions',{action,session_id:id,expected_revision:current?.revision,...extra});});

 let page:React.ReactNode;
 if(p==='/chat'||p.startsWith('/chat/'))page=nativeId?<ChatSessionView key={nativeId} id={nativeId} search={q}/>:<ChatLanding sessions={sessions.data} loading={sessions.loading} error={sessions.error||chatAction.error} fresh={q.has('skill')||q.get('fresh')==='1'} onOpen={id=>vm.replace('/chat/'+encodeURIComponent(id))} onCreate={()=>void createChat()}/>;
 else if(p==='/news'||p.startsWith('/news/a/'))page=<NativeNews onUseTopic={useTopic} id={p.startsWith('/news/a/')?decodeURIComponent(p.slice(8)):undefined} search={q}/>;
 else if(['/posters/new','/articles/new','/works/new'].includes(p))page=<NativeNewChat key={shownPath} format={p==='/articles/new'?'article':'poster'} profileId={profile} search={q} onCreate={createChat}/>;
 else if(/^\/(posters|articles|works)\/[^/]+$/.test(p)&&!p.endsWith('/history'))page=<WorkPage id={decodeURIComponent(p.split('/')[2]!)} search={q}/>;
 else if(['/posters','/articles','/works'].includes(p)||p.endsWith('/history'))page=q.get('drafts')==='1'?<LocalInputs/>:<Library format={p==='/articles'?'article':q.get('format')||''} history={p.endsWith('/history')}/>;
 else if(p==='/settings'||p==='/account')page=<Settings/>;
 else if(q.get('section')==='skills')page=<><NativeSkills profileId={profile} onUse={async(command,text)=>{if(!await createChat(profile,command,text))throw Error('会话暂未创建，输入仍保留在这里。')}}/>{(q.get('pane')==='experience'||q.get('pane')==='legacy'||q.has('item'))&&<Skills profileId={profile} search={q}/>}</>;
 else if(q.get('section')==='profiles')page=<Profiles profileId={profile} search={q}/>;
 else if(q.get('section')==='distribution'&&q.get('pane')==='connections')page=<Accounts/>;
 else if(['distribution','publications','insights','calendar'].includes(q.get('section')||''))page=<Publishing profileId={profile} section={q.get('section')||''} search={q}/>;
 else if(q.get('section')==='research')page=<Research profileId={profile} search={q} onUseTopic={useTopic}/>;
 else page=<Dashboard profileId={profile} onUseTopic={useTopic}/>;
 const currentPage:Page=p.startsWith('/chat')?'chat':p.startsWith('/news')?'trends':/^\/(posters|articles|works)(\/|$)/.test(p)?'outputs':q.get('section')==='skills'?'skills':q.get('section')==='profiles'?'profile':q.get('section')==='research'?(q.get('pane')==='breakdown'?'breakdown':'ideas'):q.get('section')==='calendar'?'calendar':['publications','distribution','insights'].includes(q.get('section')||'')?(q.get('pane')==='connections'?'accounts':'publish'):'dashboard';
 const onPageChange=(value:Page)=>open(nativePageRoutes[value]||'/toolbox');
 return <App host={{currentPage,onPageChange,sidebar:{currentPage,onPageChange,
  personas:[],selectedPersona:profile,onPersonaChange:changeProfile,onNewProfile:()=>open('/toolbox?section=profiles&item=new'),
  sessions:sessions.data?.sessions||[],activeSessionId:nativeId||null,hasMessages:session=>!!(session as import('./ChatSessionView').NativeSession).message_count||session.messages?.length>0,
  onSessionSelect:id=>open('/chat/'+encodeURIComponent(id)),onSessionDelete:()=>{},canDeleteSession:false,
  onSessionRename:(id,title)=>sessionCommand('rename',id,{title}),onSessionArchive:(id,archived)=>sessionCommand('archive',id,{archived}),onNewChat:()=>void createChat(),
  gatewayStatus:runtimeStatus.data?.gateway===true?'connected':runtimeStatus.loading?'connecting':'disconnected',apiDirect:runtimeStatus.data?.runtime==='api',agentRuntime:string(runtimeStatus.data?.runtime)||'codex',
  statusText:vm.reachable===false?'暂时离线':runtimeStatus.error?'运行环境检测失败':runtimeStatus.data?.error?string(runtimeStatus.data.error):undefined,
  onOpenSettings:()=>open('/settings'),theme,onThemeChange,
  assetUrl:name=>'/native-assets/'+document.querySelector<HTMLMetaElement>('meta[name="native-release"]')?.content+'/'+name,
  rootRef:sidebar,rootLabel:'工作导航',navigationLabel:'工作台导航',
  personaOptions:[...(creators.data?.profiles.map(value=>({value:value.id,label:value.name}))||[{value:'oil-pig',label:'油猪大侠'}]),{value:'__new__',label:'+ 新建画像…'}],
  navigation:config?.tools.map(tool=>({id:tool.id,label:tool.name,icon:icons[tool.id]||<IconDashboard size={18}/>,active:active(tool.id,shownPath),onSelect:()=>open(tool.path)}))||[],
 },pageHostProps:{id:'easel-main',tabIndex:-1,'data-native-scroll':'main'} as React.HTMLAttributes<HTMLDivElement>,
 notice:<Notice sources={[chatAction]}/>,
 overlays:settingsOpen&&apiReady&&vm.ready?<Settings/>:undefined,
 content:<>{(!vm.ready||!apiReady)&&<div className="ew-loading"><Notice sources={[vm]}/><p>{vm.expired?'登录已过期，输入已保留。':'正在连接工作台…'}</p><button className="btn" onClick={()=>void vm.refresh()}>重新读取</button>{(vm.reachable===false||!navigator.onLine||vm.expired)&&<LocalInputs/>}</div>}{apiReady&&(vm.ready||booted.current)&&page}</>,
 }}/>;
}
export function EaselAuth({next='/native/'}:{next?:string}){const {service}=useWorkbench(),[code,setCode]=useState(''),action=useAsyncAction();return <main className="ew-auth"><div className="card ew-auth-card"><IconDashboard size={36}/><h1>登录创作工作台</h1><p>使用 Ente Auth 的验证码继续。</p><form onSubmit={e=>{e.preventDefault();void action.run(async()=>location.assign(await service.login(code,next)))}}><label className="ew-field"><span>6位验证码</span><input className="field" autoFocus aria-label="6位验证码" inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code} onChange={e=>setCode(e.target.value.replace(/\D/g,'').slice(0,6))}/></label><Notice sources={[action]}/><ActionButton action={action} className="btn btn-primary" type="submit" disabled={action.busy||code.length!==6}>{action.busy?'正在登录…':'登录'}</ActionButton></form></div></main>}

function NativeNewChat({format,profileId,search,onCreate}:{format:'poster'|'article';profileId:string;search:URLSearchParams;onCreate:(profile:string,command?:NativeSelection,text?:string,files?:DraftAttachment[],articleId?:string,articleMode?:'auto'|'product')=>Promise<string|undefined>}){
 const vm=useWorkbench(),sourceId=search.get('article')||'',source=useResource<JsonRecord>(sourceId?'/api/news/'+encodeURIComponent(sourceId):null),catalog=useResource<NativeSkill[]>('/api/skills'),creators=useResource<CreatorBootstrap>('/api/creator/bootstrap'),action=useAsyncAction(),started=useRef(false);
 const key=(format==='article'?'article:':'')+(search.get('draft')||(sourceId?(format==='article'?sourceId:'new:news:'+sourceId):'new'));
 const open=()=>void action.run(async()=>{
  if(!catalog.data||!creators.data||(sourceId&&!source.data))return;
  const saved=vm.client.drafts.get<JsonRecord>(key)||{},pending=vm.client.operation('create:'+key).getState().pending;
  if(pending||vm.client.legacyPending().some(item=>item.key===key))throw Object.assign(Error('原草稿状态正在恢复，输入和原操作标识已保留。'),{uncertain:true,...(pending?{operationScope:pending.scope,operationId:pending.id}:{})});
  const profile=search.get('profile')||string(record(record(saved.creative).creator).profile_id)||profileId,profileData=creators.data.profiles.find(value=>value.id===profile);
  const choices=nativeSkillChoices(catalog.data),legacy=record(saved.command),skill=search.get('skill')||string(legacy.skill_id)||'content-production',actionId=search.get('action')||string(legacy.action_id)||(search.get('mode')==='research'?'discuss':format),wanted=choices.find(choice=>choice.selection.skill_id===skill&&choice.selection.action_id===actionId),version=Number(search.get('skill_version')||legacy.version||profileData?.task_skill_versions?.[wanted?.selection.task||actionId]?.[skill]||profileData?.skill_versions?.[skill]),command=search.get('mode')==='research'&&!search.has('skill')?undefined:wanted?{...wanted.selection,...(Number.isSafeInteger(version)&&version>0?{version}:{}),...(search.get('trial')==='1'?{trial:true}:{})}:undefined;
  if(!command&&search.get('mode')!=='research')throw Error('准确制作技能尚不可用，旧草稿已保留。请从技能库核对后再打开。');
  const material=string(saved.material)||string(source.data?.body),title=string(saved.title)||string(source.data?.title),text=[title,material,string(saved.guidance),string(record(record(saved.creative).recipe).prompt_text)?'原草稿明确制作要求：\n'+string(record(record(saved.creative).recipe).prompt_text):'',saved.article_mode==='product'?'原草稿明确选择：文章类型为产品文章。':''].filter(Boolean).join('\n\n'),files=array<DraftAttachment>(saved.files);
  if(!await onCreate(profile,command,text,files,sourceId||string(saved.article_id)||undefined,saved.article_mode==='product'?'product':saved.article_mode==='auto'?'auto':undefined))throw Error('原生会话尚未确认创建，旧草稿仍保留。');
 });
 useEffect(()=>{if(started.current||!catalog.data||!creators.data||(sourceId&&!source.data))return;started.current=true;open()},[catalog.data,creators.data,source.data]);
 return <div className="ew-loading"><Notice sources={[catalog,creators,source,action]}/><p>正在将材料带入原生对话。原草稿与来源保留，确认方案后才开始制作。</p><ActionButton action={action} className="btn" disabled={action.busy} onClick={open}>重新打开对话</ActionButton><button className="btn btn-ghost" onClick={()=>vm.navigate('/posters?drafts=1')}>查看本机草稿</button></div>;
}
function ChatLanding({sessions,loading,error,fresh,onOpen,onCreate}:{sessions:NativeSessions|null;loading:boolean;error:string;fresh:boolean;onOpen:(id:string)=>void;onCreate:()=>void}){const started=useRef(false);useEffect(()=>{if(!sessions||started.current)return;started.current=true;const recent=!fresh&&sessions.sessions.find(session=>!session.archived);if(recent)onOpen(recent.id);else onCreate()},[sessions]);return <div className="ew-loading"><Notice message={error}/><p>{loading?'正在读取原生会话…':'正在打开原生对话…'}</p><button className="btn" onClick={onCreate}>新建对话</button></div>}
