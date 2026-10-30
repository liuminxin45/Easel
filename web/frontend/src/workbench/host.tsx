import React,{Suspense,lazy,useEffect,useLayoutEffect,useMemo,useState,useSyncExternalStore,type ReactNode} from 'react';
import {CoreProvider,useWorkbench,useUsage} from '@workbench/core';
import {ActivityCoordinator,NavigationService,bindViewport,bindNavigationLinks,browserProfile,prepareNativeWorker,type PlatformProfile} from '@workbench/platform';
import {bindNativeModalFocus} from './platform/modal-focus';
import './host.css';
const EaselRoot=lazy(()=>import('@workbench/ui-easel').then(m=>({default:m.EaselWorkbench}))),EaselAuth=lazy(()=>import('@workbench/ui-easel').then(m=>({default:m.EaselAuth})));
const nonce=()=>document.querySelector<HTMLMetaElement>('meta[name="style-nonce"]')?.content||'';
type Theme='light'|'dark'|'system';
type Layout='auto'|'compact'|'expanded';
function initialTheme():Theme{try{const t=localStorage.getItem('native:theme')||localStorage.getItem('desk-theme');return t==='dark'||t==='light'?t:'system'}catch{return 'system'}}
class Boundary extends React.Component<{children:ReactNode},{error:string}>{state={error:''};static getDerivedStateFromError(error:Error){return {error:error.message}}render(){return this.state.error?<main className="native-boot-failure" role="alert"><h1>界面未能打开</h1><p>输入保留在这台设备上。</p><button onClick={()=>location.reload()}>重新打开</button><details><summary>错误详情</summary>{this.state.error}</details></main>:this.props.children}}
function InputNotice(){const vm=useWorkbench();return vm.persistenceError?<aside className="native-host-notice" role="alert">本机保存未完成：{vm.persistenceError}。请保留当前页面。</aside>:vm.expired?<aside className="native-host-notice" role="alert">登录已过期，草稿保留。<a href={'/native/login?'+new URLSearchParams({next:location.pathname+location.search})}>重新登录</a></aside>:null}
function RuntimeServices({activities,path,direction}:{activities:ActivityCoordinator;path:string;direction:string}){
 const {ready,persistenceError}=useWorkbench(),usage=useUsage();
 useEffect(()=>{if(ready)usage.view(path,direction)},[ready,path,direction,usage]);
 useEffect(()=>{if(!ready)return;let stopped=false;const release=document.querySelector<HTMLMetaElement>('meta[name="native-release"]')?.content;
  const cacheShell=()=>navigator.serviceWorker?.controller?.postMessage({type:'CACHE_SHELL'});
  let registration:Promise<ServiceWorkerRegistration>|undefined,checking=false;
  if('serviceWorker' in navigator){navigator.serviceWorker.addEventListener('controllerchange',cacheShell);registration=navigator.serviceWorker.register('/native/sw.js',{scope:'/native/',updateViaCache:'none'});void registration.then(async current=>{if(release)await prepareNativeWorker(current,release);if(!stopped){cacheShell();current.active?.postMessage({type:'CACHE_SHELL'})}}).catch(()=>{/* The online app remains usable if service workers are unavailable. */})}
  const check=async()=>{if(stopped||checking||document.hidden||!activities.canUpgrade||persistenceError)return;checking=true;try{const response=await fetch('/native/version',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(8000)});if(!response.ok)return;const value:unknown=await response.json();if(value&&typeof value==='object'&&'release' in value&&typeof value.release==='string'&&value.release!==release){if(registration&&!await prepareNativeWorker(await registration,value.release))return;if(!stopped&&activities.canUpgrade&&!persistenceError)location.reload()}}catch{/* A failed check does not replay a command. */}finally{checking=false}};
  const timer=setInterval(()=>void check(),30000),resume=()=>void check();window.addEventListener('online',resume);window.addEventListener('focus',resume);return()=>{stopped=true;clearInterval(timer);navigator.serviceWorker?.removeEventListener('controllerchange',cacheShell);window.removeEventListener('online',resume);window.removeEventListener('focus',resume)};
 },[ready,activities,persistenceError]);return null;
}
export default function NativeHost({auth=false}:{auth?:boolean}){
 const [layout,setLayout]=useState<Layout>(()=>{try{const v=localStorage.getItem('native:layout');return v==='compact'||v==='expanded'?v:'auto'}catch{return 'auto'}}),[profile,setProfile]=useState<PlatformProfile>(()=>browserProfile()),[preference,setPreference]=useState<Theme>(initialTheme),[systemDark,setSystemDark]=useState(()=>matchMedia('(prefers-color-scheme:dark)').matches);
 const activities=useMemo(()=>new ActivityCoordinator(),[]),navigation=useMemo(()=>new NavigationService(),[]),route=useSyncExternalStore(navigation.subscribe,navigation.snapshot,navigation.snapshot),theme=preference==='system'?(systemDark?'dark':'light'):preference;
 const delegate=useMemo(()=>({path:route.path,navigate:navigation.navigate,replace:navigation.replace,back:navigation.back,ticket:navigation.ticket,finishFlow:navigation.finishFlow,contentReady:navigation.contentReady,updateReturnAnchor:navigation.updateReturnAnchor,registerLayer:navigation.registerLayer}),[navigation,route.path]);
 const next=useMemo(()=>{const target=new URLSearchParams(location.search).get('next')||'/native/';try{const url=new URL(target,location.origin);return url.origin===location.origin&&url.pathname!=='/native/login'?url.pathname+url.search:'/native/'}catch{return '/native/'}},[]);
 useLayoutEffect(()=>auth?undefined:navigation.start(),[navigation,auth]);useLayoutEffect(()=>auth?undefined:navigation.committed(),[navigation,route,auth]);
 useEffect(()=>auth?undefined:bindNavigationLinks(navigation),[navigation,auth]);
 useEffect(()=>bindViewport(activities),[activities]);
 useEffect(()=>auth?undefined:bindNativeModalFocus(),[auth]);
 useEffect(()=>{const change=()=>{const next=browserProfile(layout);setProfile(current=>current.family===next.family&&current.os===next.os&&current.layout===next.layout&&current.input===next.input&&current.display===next.display&&current.supportedNative===next.supportedNative?current:next)},media=matchMedia('(prefers-color-scheme:dark)'),dark=()=>setSystemDark(media.matches);change();window.addEventListener('resize',change);media.addEventListener('change',dark);return()=>{window.removeEventListener('resize',change);media.removeEventListener('change',dark)}},[layout]);
 useEffect(()=>{document.documentElement.dataset.nativePlatform=profile.family;document.documentElement.dataset.nativeLayout=profile.layout;document.documentElement.dataset.nativeInput=profile.input;document.documentElement.dataset.nativeTheme=theme;document.documentElement.dataset.theme=theme;document.documentElement.classList.toggle('dark',theme==='dark')},[profile.family,profile.layout,profile.input,theme]);
 const onThemeChange=(value:Theme)=>{setPreference(value);try{localStorage.setItem('native:theme',value)}catch{/* Keep the selected theme for this session. */}};
 const onPreferencesChange=(value:Partial<{theme:Theme;layout:Layout}>)=>{if(value.theme)onThemeChange(value.theme);if(value.layout){setLayout(value.layout);try{localStorage.setItem('native:layout',value.layout)}catch{/* Keep in memory. */}}};
 return <Boundary><CoreProvider navigation={delegate} activities={activities} autoBoot={!auth}><div className={'native-host native-'+profile.family} data-layout={profile.layout} data-runtime={profile.display} data-direction={route.direction}>{!auth&&<><InputNotice/><RuntimeServices activities={activities} path={route.path} direction={route.direction}/></>}<Suspense fallback={<div className="native-loading" role="status">正在打开…</div>}>{auth?<EaselAuth next={next}/>:<EaselRoot theme={theme} onThemeChange={onThemeChange}/>}</Suspense></div></CoreProvider></Boundary>;
}
