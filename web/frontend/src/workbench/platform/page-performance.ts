import {usageScreen} from '../core/usage';

type Boot={start:number;visible:number|null;entry?:number;module?:number;failed?:boolean;hidden:boolean;trace:string;release:string};
type Metric='boot'|'navigation'|'loading'|'request';
type Event={kind:'summary'|'slow';metric:Metric;screen:string;platform:string;release:string;buckets?:number[];duration_ms?:number;phases_ms?:Record<string,number>;outcome?:string;hidden?:boolean;trace?:string;request_group?:string;status?:number;at?:number};
declare global {interface Window {__wbBoot?:Boot}}
const KEY='workbench:page-performance:v1',LIMIT=64*1024,BUCKETS=[250,500,1000,2000,3000,5000,10000,30000];
const valid=(v:number)=>Number.isFinite(v)&&v>=0&&v<=3600000;
const timestamp=()=>{const at=Date.now()/1000;return Number.isFinite(at)&&at>=0&&at<=4102444800?{at}:{}};

class PagePerformance {
 private rows:Event[]=[];private dropped=0;private csrf='';private timer?:number;private sending=false;private start=new Map<string,{at:number;screen:string;hidden:boolean;shell?:number}>();
 private release=typeof document==='undefined'?'':document.querySelector<HTMLMetaElement>('meta[name="native-release"]')?.content||'';
 private platform=()=>typeof document==='undefined'?'unknown':['android','windows'].includes(document.documentElement.dataset.nativePlatform||'')?document.documentElement.dataset.nativePlatform!:'unknown';
 constructor(){try{const v=JSON.parse(sessionStorage.getItem(KEY)||'null');if(v&&Array.isArray(v.rows)&&Date.now()-v.at<86400000){this.rows=v.rows.slice(-100);this.dropped=Number.isSafeInteger(v.dropped)?Math.min(100000,v.dropped):0}
  const old=JSON.parse(sessionStorage.getItem('workbench:performance:unfinished')||'null');if(old&&typeof old.at==='number'&&Date.now()-old.at>=0&&Date.now()-old.at<86400000&&/^native-[A-Za-z0-9_-]{1,80}$/.test(old.release)){this.rows.push({kind:'slow',metric:'boot',screen:'unknown',platform:'unknown',release:old.release,at:old.at/1000,duration_ms:old.outcome==='failed'&&valid(old.duration_ms)?old.duration_ms:15000,phases_ms:{},outcome:old.outcome==='failed'?'failed':'timeout',hidden:old.hidden===true,...(/^[a-f0-9]{16,64}$/.test(old.trace||'')?{trace:old.trace}:{})});sessionStorage.removeItem('workbench:performance:unfinished');this.save()}
 }catch{/* Diagnostics never block startup. */}
  window.addEventListener('workbench:performance-navigation',event=>{const value=(event as CustomEvent).detail;if(value&&typeof value.key==='string'&&typeof value.path==='string')this.navigation(value.key,value.path)});
  window.addEventListener('workbench:performance-content',event=>{const value=(event as CustomEvent).detail;if(value&&typeof value.key==='string')this.content(value.key)});
  window.addEventListener('workbench:performance-request',event=>{const v=(event as CustomEvent).detail;if(!v||typeof v.path!=='string'||!valid(v.duration)||!Number.isInteger(v.status)||v.status<0||v.status>599||!/^native-[A-Za-z0-9_-]{1,80}$/.test(this.release))return;const path=v.path.split('?')[0] as string,group=path==='/api/config'?'config':path.startsWith('/api/chat')?'chat':path.startsWith('/api/news')||path.startsWith('/api/trends')?'news':path.startsWith('/api/works')||path.startsWith('/api/outputs')?'works':path.startsWith('/api/skill')?'skills':'other';this.rows.push({kind:'slow',metric:'request',screen:usageScreen(location.pathname+location.search),platform:this.platform(),release:this.release,...timestamp(),duration_ms:Math.round(v.duration),phases_ms:{},outcome:v.status>=200&&v.status<400?'ready':'failed',hidden:document.hidden,request_group:group,status:v.status,...(/^[a-f0-9]{16,64}$/.test(v.trace||'')?{trace:v.trace}:{})});while(this.rows.length>100){this.rows.shift();this.dropped++}this.save()});
  window.addEventListener('pagehide',()=>void this.flush());document.addEventListener('visibilitychange',()=>{if(document.hidden)for(const item of this.start.values())item.hidden=true});
 }
 private save(){try{let value=JSON.stringify({at:Date.now(),rows:this.rows,dropped:this.dropped});while(value.length>LIMIT&&this.rows.length){this.rows.shift();this.dropped++;value=JSON.stringify({at:Date.now(),rows:this.rows,dropped:this.dropped})}sessionStorage.setItem(KEY,value)}catch{this.dropped++}}
 private add(metric:Metric,screen:string,duration:number,phases:Record<string,number>,outcome='ready',hidden=false,trace=''){
  if(!valid(duration)||!/^native-[A-Za-z0-9_-]{1,80}$/.test(this.release))return;
  const platform=this.platform();let histogram=this.rows.find(x=>x.kind==='summary'&&x.metric===metric&&x.screen===screen&&x.platform===platform&&x.release===this.release);
  if(!histogram){histogram={kind:'summary',metric,screen,platform,release:this.release,buckets:Array(9).fill(0)};this.rows.push(histogram)}
  const index=BUCKETS.findIndex(n=>duration<=n);const bin=index<0?8:index;histogram.buckets![bin]=Math.min(10000,histogram.buckets![bin]!+1);
  if(outcome==='failed'||outcome==='timeout'||duration>=(metric==='navigation'?2000:3000))this.rows.push({kind:'slow',metric,screen,platform,release:this.release,...timestamp(),duration_ms:Math.round(duration),phases_ms:Object.fromEntries(Object.entries(phases).filter(([,n])=>valid(n)).map(([k,n])=>[k,Math.round(n)])),outcome,hidden,...(/^[a-f0-9]{16,64}$/.test(trace)?{trace}:{})});
  while(this.rows.length>100){this.rows.shift();this.dropped++}this.save();
 }
 boot(){try{const b=window.__wbBoot;if(!b)return;const now=performance.now(),nav=performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming|undefined;
  const phases:Record<string,number>={shell:now};if(b.entry!==undefined)phases.entry=b.entry;if(b.module!==undefined)phases.module=b.module;if(b.visible!==null)phases.boot_visible=Math.max(0,now-b.visible);
  if(nav){for(const [key,value] of Object.entries({document:nav.responseEnd,dns:nav.domainLookupEnd-nav.domainLookupStart,connect:nav.connectEnd-nav.connectStart,tls:nav.secureConnectionStart?nav.connectEnd-nav.secureConnectionStart:0,first_byte:nav.responseStart-nav.requestStart,download:nav.responseEnd-nav.responseStart}))if(value>0&&valid(value))phases[key]=value}
  this.add('boot',usageScreen(location.pathname+location.search),now,phases,'ready',b.hidden,b.trace);try{sessionStorage.removeItem('workbench:performance:unfinished')}catch{};delete window.__wbBoot
 }catch{/* Optional observation only. */}}
 navigation(key:string,path:string){try{this.start.set(key,{at:performance.now(),screen:usageScreen(path),hidden:document.hidden});if(this.start.size>16)this.start.delete(this.start.keys().next().value!);setTimeout(()=>this.start.delete(key),30000)}catch{}}
 content(key:string){const item=this.start.get(key);if(!item)return;this.start.delete(key);try{const duration=performance.now()-item.at;if(item.shell===undefined)this.add('navigation',item.screen,duration,{content:duration},'ready',item.hidden||document.hidden);else if(duration>=2000){this.rows.push({kind:'slow',metric:'navigation',screen:item.screen,platform:this.platform(),release:this.release,...timestamp(),duration_ms:Math.round(duration),phases_ms:{shell:Math.round(item.shell),content:Math.round(duration)},outcome:'ready',hidden:item.hidden||document.hidden});this.save()}}catch{}}
 shell(key:string){const item=this.start.get(key);if(!item)return;requestAnimationFrame(()=>{try{const current=this.start.get(key);if(!current||current.shell!==undefined)return;current.shell=performance.now()-current.at;this.add('navigation',current.screen,current.shell,{shell:current.shell},'unknown',current.hidden||document.hidden)}catch{/* Diagnostics cannot affect navigation. */}})}
 loading(){const start=performance.now(),screen=usageScreen(location.pathname+location.search),hidden=document.hidden;return()=>{try{this.add('loading',screen,performance.now()-start,{},'ready',hidden||document.hidden)}catch{}}}
 enable(csrf:string){if(!csrf)return;this.csrf=csrf;if(this.timer===undefined)this.timer=window.setInterval(()=>void this.flush(),30000);void this.flush()}
 disable(){this.csrf='';if(this.timer!==undefined){clearInterval(this.timer);this.timer=undefined}}
 async flush(){if(this.sending||!this.csrf||!this.rows.length)return;this.sending=true;const events=this.rows.splice(0,20),dropped=Math.min(100000,this.dropped);this.dropped=0;this.save();try{const response=await fetch('/api/diagnostics/page-performance',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':this.csrf},body:JSON.stringify({events,dropped}),keepalive:true});const value=await response.json();if(!response.ok||!value.accepted)this.dropped+=events.length}catch{this.dropped+=events.length}finally{this.sending=false;this.save()}}
}
export const pagePerformance=typeof window==='undefined'?null:new PagePerformance();
