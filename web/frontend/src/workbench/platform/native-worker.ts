/** A page may show a new build while its previous service worker still controls it. */
export async function nativeWorkerVersion(worker:ServiceWorker|null,timeout=600):Promise<{release:string;shell_ready:boolean}|null>{
 if(!worker||typeof MessageChannel==='undefined')return null;
 return new Promise(resolve=>{const channel=new MessageChannel();let closed=false;
  const finish=(value:{release:string;shell_ready:boolean}|null)=>{if(closed)return;closed=true;clearTimeout(timer);channel.port1.close();channel.port2.close();resolve(value)};
  const timer=setTimeout(()=>finish(null),timeout);
  channel.port1.onmessage=event=>{const value:unknown=event.data;finish(value&&typeof value==='object'&&'release' in value&&typeof value.release==='string'&&'shell_ready' in value?{release:value.release,shell_ready:value.shell_ready===true}:null)};
  try{worker.postMessage({type:'NATIVE_VERSION'},[channel.port2])}catch{finish(null)}
 });
}
export async function prepareNativeWorker(registration:ServiceWorkerRegistration,release:string,timeout=12000):Promise<boolean>{
 const deadline=Date.now()+timeout;
 if(timeout<=0)return false;
 // Some WebViews leave update() pending when a suspended request never resumes.
 // An offline rejection still permits checking the installed controller.
 const updated=await new Promise<boolean>(resolve=>{let settled=false;
  const finish=(value:boolean)=>{if(settled)return;settled=true;clearTimeout(timer);resolve(value)};
  const timer=setTimeout(()=>finish(false),Math.max(0,deadline-Date.now()));
  try{void registration.update().then(()=>finish(true),()=>finish(true))}catch{finish(true)}
 });
 if(!updated)return false;
 while(Date.now()<deadline){
  const state=await nativeWorkerVersion(navigator.serviceWorker.controller,Math.min(600,deadline-Date.now()));
  if(Date.now()<deadline&&state?.release===release&&state.shell_ready)return true;
  const remaining=deadline-Date.now();
  if(remaining>0)await new Promise<void>(resolve=>setTimeout(resolve,Math.min(100,remaining)));
 }
 return false;
}
