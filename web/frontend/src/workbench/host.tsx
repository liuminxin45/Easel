import React,{Suspense,lazy,useEffect,useLayoutEffect,useMemo,useState,useSyncExternalStore,type ReactNode} from 'react';
import {CoreProvider,useWorkbench,useUsage} from './ui/hooks';
import {ActivityCoordinator,NavigationService,bindViewport,bindNavigationLinks,browserProfile,prepareNativeWorker,type PlatformProfile} from '@workbench/platform';
import {bindNativeModalFocus} from './platform/modal-focus';
import {bindNativeUpgradeChecks} from './platform/native-resume';
import type {ImageLink} from './platform/links';
import './host.css';
import {StatusCard} from '../components/InteractionNotice';
import {pagePerformance} from './platform/page-performance';
const EaselRoot=lazy(()=>import('@workbench/ui-easel').then(m=>({default:m.EaselWorkbench}))),EaselAuth=lazy(()=>import('@workbench/ui-easel').then(m=>({default:m.EaselAuth}))),ImagePreview=lazy(()=>import('./ui/ImagePreview'));
const nonce=()=>document.querySelector<HTMLMetaElement>('meta[name="style-nonce"]')?.content||'';
type Theme='light'|'dark'|'system';
type Layout='auto'|'compact'|'expanded';
function initialTheme():Theme{try{const t=localStorage.getItem('native:theme')||localStorage.getItem('desk-theme');return t==='dark'||t==='light'?t:'system'}catch{return 'system'}}
class Boundary extends React.Component<{children:ReactNode},{error:string;detailsOpen:boolean}>{
 state={error:'',detailsOpen:false};
 static getDerivedStateFromError(error:Error){return {error:error.message}}
 render(){return this.state.error?<main className="native-boot-failure" role="alert"><h1>界面未能打开</h1><p>输入保留在这台设备上。</p><button className="btn btn-primary" onClick={()=>location.reload()}>重新打开</button><button className="btn btn-ghost" aria-expanded={this.state.detailsOpen} aria-controls="native-boot-diagnostic" onClick={()=>this.setState({detailsOpen:!this.state.detailsOpen})}>{this.state.detailsOpen?'收起错误详情':'查看错误详情'}</button>{this.state.detailsOpen&&<pre id="native-boot-diagnostic" className="native-boot-diagnostic">{this.state.error}</pre>}</main>:this.props.children}
}
function LoadingFallback(){useLayoutEffect(()=>pagePerformance?.loading(),[]);return <div className="native-loading"><StatusCard className="ew-status-card-compact">正在打开…</StatusCard></div>}
function InputNotice(){const vm=useWorkbench();return vm.persistenceError?<StatusCard className="native-host-notice ew-status-card-compact" tone="error">本机保存未完成：{vm.persistenceError}。请保留当前页面。</StatusCard>:vm.expired?<StatusCard className="native-host-notice ew-status-card-compact" tone="warning">登录已过期，草稿保留。<a href={'/native/login?'+new URLSearchParams({next:location.pathname+location.search})}>重新登录</a></StatusCard>:null}
function RuntimeServices({activities,path,direction}:{activities:ActivityCoordinator;path:string;direction:string}){
 const {ready,persistenceError,client,config}=useWorkbench(),usage=useUsage();
 useEffect(()=>{if(ready&&config?.csrf)pagePerformance?.enable(config.csrf);else pagePerformance?.disable();return()=>pagePerformance?.disable()},[ready,config?.csrf]);
 useEffect(()=>{if(ready)usage.view(path,direction)},[ready,path,direction,usage]);
 useEffect(()=>{if(!ready)return;let stopped=false;const release=document.querySelector<HTMLMetaElement>('meta[name="native-release"]')?.content;
  const cacheShell=()=>navigator.serviceWorker?.controller?.postMessage({type:'CACHE_SHELL'});
  let registration:Promise<ServiceWorkerRegistration>|undefined;
  if('serviceWorker' in navigator){navigator.serviceWorker.addEventListener('controllerchange',cacheShell);registration=navigator.serviceWorker.register('/native/sw.js',{scope:'/native/',updateViaCache:'none'});void registration.then(async current=>{if(release)await prepareNativeWorker(current,release);if(!stopped){cacheShell();current.active?.postMessage({type:'CACHE_SHELL'})}}).catch(()=>{/* The online app remains usable if service workers are unavailable. */})}
  const stopChecks=bindNativeUpgradeChecks({activities,release,registration,blocked:()=>!!client.drafts.persistence.getState().error||client.drafts.hasPending()||!!document.querySelector('.settings-panel,.drawer-overlay,dialog[open],[data-native-upgrade-blocked="true"]')});
  return()=>{stopped=true;stopChecks();navigator.serviceWorker?.removeEventListener('controllerchange',cacheShell)};
 },[ready,activities,persistenceError]);return null;
}
export default function NativeHost({auth=false}:{auth?:boolean}){
 const [imagePreview,setImagePreview]=useState<ImageLink|null>(null);
 const [layout,setLayout]=useState<Layout>(()=>{try{const v=localStorage.getItem('native:layout');return v==='compact'||v==='expanded'?v:'auto'}catch{return 'auto'}}),[profile,setProfile]=useState<PlatformProfile>(()=>browserProfile()),[preference,setPreference]=useState<Theme>(initialTheme),[systemDark,setSystemDark]=useState(()=>matchMedia('(prefers-color-scheme:dark)').matches);
 const activities=useMemo(()=>new ActivityCoordinator(),[]),navigation=useMemo(()=>new NavigationService(),[]),route=useSyncExternalStore(navigation.subscribe,navigation.snapshot,navigation.snapshot),theme=preference==='system'?(systemDark?'dark':'light'):preference;
 useLayoutEffect(()=>{if(!auth){pagePerformance?.boot();pagePerformance?.shell(route.key)}},[auth,route.key]);
 const delegate=useMemo(()=>({path:route.path,entryKey:route.key,direction:route.direction,navigate:navigation.navigate,replace:navigation.replace,back:navigation.back,ticket:navigation.ticket,finishFlow:navigation.finishFlow,contentReady:navigation.contentReady,updateReturnAnchor:navigation.updateReturnAnchor,registerLayer:navigation.registerLayer,registerLeaveGuard:navigation.registerLeaveGuard,readViewState:navigation.readViewState,writeViewState:navigation.writeViewState,clearViewState:navigation.clearViewState}),[navigation,route.path,route.key,route.direction]);
 const next=useMemo(()=>{const target=new URLSearchParams(location.search).get('next')||'/native/';try{const url=new URL(target,location.origin);return url.origin===location.origin&&url.pathname!=='/native/login'?url.pathname+url.search:'/native/'}catch{return '/native/'}},[]);
 useLayoutEffect(()=>auth?undefined:navigation.start(),[navigation,auth]);useLayoutEffect(()=>auth?undefined:navigation.committed(),[navigation,route,auth]);
 useEffect(()=>auth?undefined:bindNavigationLinks(navigation,setImagePreview),[navigation,auth]);
 useEffect(()=>bindViewport(activities),[activities]);
 useEffect(()=>auth?undefined:bindNativeModalFocus(),[auth]);
 useEffect(()=>{const change=()=>{const next=browserProfile(layout);setProfile(current=>current.family===next.family&&current.os===next.os&&current.layout===next.layout&&current.input===next.input&&current.display===next.display&&current.supportedNative===next.supportedNative?current:next)},media=matchMedia('(prefers-color-scheme:dark)'),dark=()=>setSystemDark(media.matches);change();window.addEventListener('resize',change);media.addEventListener('change',dark);return()=>{window.removeEventListener('resize',change);media.removeEventListener('change',dark)}},[layout]);
 useEffect(()=>{document.documentElement.dataset.nativePlatform=profile.family;document.documentElement.dataset.nativeLayout=profile.layout;document.documentElement.dataset.nativeInput=profile.input;document.documentElement.dataset.nativeTheme=theme;document.documentElement.dataset.theme=theme;document.documentElement.classList.toggle('dark',theme==='dark')},[profile.family,profile.layout,profile.input,theme]);
 const onThemeChange=(value:Theme)=>{setPreference(value);try{localStorage.setItem('native:theme',value)}catch{/* Keep the selected theme for this session. */}};
 const onPreferencesChange=(value:Partial<{theme:Theme;layout:Layout}>)=>{if(value.theme)onThemeChange(value.theme);if(value.layout){setLayout(value.layout);try{localStorage.setItem('native:layout',value.layout)}catch{/* Keep in memory. */}}};
 return <Boundary><CoreProvider navigation={delegate} activities={activities} autoBoot={!auth}><div className={'native-host native-'+profile.family} data-layout={profile.layout} data-runtime={profile.display} data-direction={route.direction}>{!auth&&<><InputNotice/><RuntimeServices activities={activities} path={route.path} direction={route.direction}/></>}<Suspense fallback={<LoadingFallback/>}>{auth?<EaselAuth next={next}/>:<EaselRoot theme={theme} onThemeChange={onThemeChange}/>}</Suspense>{imagePreview&&<Suspense fallback={null}><ImagePreview image={imagePreview} close={()=>setImagePreview(null)}/></Suspense>}</div></CoreProvider></Boundary>;
}
