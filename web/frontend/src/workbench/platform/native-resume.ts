import type {ActivityCoordinator} from './activities';
import {prepareNativeWorker} from './native-worker';

/** Recheck on WebView resume and after a protected input/save finishes. */
export function bindNativeUpgradeChecks({activities,release,registration,blocked=()=>false}:{
 activities:ActivityCoordinator;release:string|undefined;registration?:Promise<ServiceWorkerRegistration>;blocked?:()=>boolean;
}):()=>void {
 let stopped=false,checking=false,reloading=false,again=false,scheduled:ReturnType<typeof setTimeout>|undefined;
 let wasSafe=activities.canUpgrade;
 // register() is also a browser-owned promise and may be suspended indefinitely.
 const registered=async(deadline:number)=>new Promise<ServiceWorkerRegistration|null>(resolve=>{
  const timer=setTimeout(()=>resolve(null),Math.max(0,deadline-Date.now()));
  void registration!.then(value=>{clearTimeout(timer);resolve(value)},()=>{clearTimeout(timer);resolve(null)});
 });
 const safe=()=>!stopped&&!reloading&&!document.hidden&&activities.canUpgrade&&!blocked();
 const check=async()=>{
  if(!safe())return;
  if(checking){again=true;return}
  checking=true;
  try{
   const response=await fetch('/native/version',{credentials:'same-origin',cache:'no-store',signal:AbortSignal.timeout(8000)});
   if(!response.ok)return;
   const value:unknown=await response.json();
   if(!value||typeof value!=='object'||!('release' in value)||typeof value.release!=='string'||value.release===release)return;
   if(registration){
    const deadline=Date.now()+12000,current=await registered(deadline);
    if(!current||!safe()||!await prepareNativeWorker(current,value.release,Math.max(0,deadline-Date.now())))return;
   }
   if(safe()){reloading=true;location.reload()}
  }catch{/* Resume failures stay silent and never replay an operation. */}
  finally{checking=false;if(again){again=false;request()}}
 };
 // Let compositionend/input and save handlers complete before starting a check.
 const request=()=>{if(stopped||reloading||scheduled!==undefined)return;scheduled=setTimeout(()=>{scheduled=undefined;void check()},0)};
 const visible=()=>{if(!document.hidden)request()};
 const releaseActivities=activities.subscribe(()=>{const next=activities.canUpgrade;if(!wasSafe&&next)request();wasSafe=next});
 const timer=setInterval(request,30000);
 document.addEventListener('visibilitychange',visible);
 window.addEventListener('pageshow',visible);
 window.addEventListener('online',request);
 window.addEventListener('focus',request);
 return()=>{stopped=true;clearInterval(timer);if(scheduled!==undefined)clearTimeout(scheduled);releaseActivities();document.removeEventListener('visibilitychange',visible);window.removeEventListener('pageshow',visible);window.removeEventListener('online',request);window.removeEventListener('focus',request)};
}
