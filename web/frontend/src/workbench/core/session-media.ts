import type {Artifact} from './models';

const MAX_BYTES=32*1024*1024,MAX_ENTRIES=64,SINGLE_LIMIT=8*1024*1024;
export class MediaSessionExpired extends Error {}
export class MediaSessionChanged extends Error {}
export interface MediaLease {url:string;release:()=>void;cached:boolean}
interface Entry {key:string;url:string;size:number;refs:number;used:number}
interface CacheOptions {fetcher?:typeof fetch;maxBytes?:number;maxEntries?:number;singleLimit?:number;makeUrl?:(blob:Blob)=>string;revokeUrl?:(url:string)=>void}
export function mediaDescriptorPath(file:Artifact,compact=false):string {const path=compact?file.thumbnail_url:file.display_url;if(!path||!/^\/api\/media\/images\/[A-Za-z0-9_-]+\/[a-f0-9]{64}\/(?:original|thumb-256)$/.test(path))return '';return path}
/** Private image bytes live only in this page session, never Storage/IDB/SW. */
export class SessionMediaCache {
 private entries=new Map<string,Entry>();private pending=new Map<string,{promise:Promise<Entry|null>;controller:AbortController}>();private bytes=0;private clock=0;private epoch=0;
 constructor(private options:CacheOptions={}){}
 get generation(){return this.epoch}
 get stats(){return {entries:this.entries.size,bytes:this.bytes,pending:this.pending.size,generation:this.epoch}}
 private remove(entry:Entry){if(this.entries.get(entry.key)!==entry)return;this.entries.delete(entry.key);this.bytes-=entry.size;(this.options.revokeUrl??URL.revokeObjectURL.bind(URL))(entry.url)}
 private room(size:number){const maxBytes=this.options.maxBytes??MAX_BYTES,maxEntries=this.options.maxEntries??MAX_ENTRIES;while(this.bytes+size>maxBytes||this.entries.size>=maxEntries){const candidate=[...this.entries.values()].filter(entry=>entry.refs===0).sort((a,b)=>a.used-b.used)[0];if(!candidate)return false;this.remove(candidate)}return size<=maxBytes&&maxEntries>0}
 clear(){this.epoch++;for(const item of this.pending.values())item.controller.abort();this.pending.clear();for(const entry of [...this.entries.values()])this.remove(entry)}
 dropUnused(key:string){const entry=this.entries.get(key);if(entry?.refs===0)this.remove(entry)}
 async acquire(path:string,knownSize?:number):Promise<MediaLease>{
  if(!/^\/api\/media\/images\/[A-Za-z0-9_-]+\/[a-f0-9]{64}\/(?:original|thumb-256)$/.test(path))throw Error('图片地址无效');
  const direct=():MediaLease=>({url:path,release:()=>{},cached:false}),generation=this.epoch,limit=this.options.singleLimit??SINGLE_LIMIT;
  if(knownSize!==undefined&&knownSize>limit)return direct();
  let entry=this.entries.get(path);
  if(!entry){let request=this.pending.get(path);if(!request){const controller=new AbortController();const promise=(async()=>{const response=await (this.options.fetcher??fetch)(path,{credentials:'same-origin',cache:'no-cache',signal:controller.signal});if(generation!==this.epoch)throw new MediaSessionChanged();if(response.status===401){this.clear();throw new MediaSessionExpired('登录已过期')}if(!response.ok)throw Error('图片暂未读取');if(generation!==this.epoch)throw new MediaSessionChanged();if(Number(response.headers.get('content-length'))>limit){await response.body?.cancel();return null}const blob=await response.blob();if(generation!==this.epoch)throw new MediaSessionChanged();if(blob.size>limit||!blob.type.startsWith('image/')||!this.room(blob.size))return null;const item:Entry={key:path,url:(this.options.makeUrl??URL.createObjectURL.bind(URL))(blob),size:blob.size,refs:0,used:++this.clock};this.entries.set(path,item);this.bytes+=blob.size;return item})().finally(()=>{if(this.pending.get(path)?.controller===controller)this.pending.delete(path)});request={promise,controller};this.pending.set(path,request)}const loaded=await request.promise;if(generation!==this.epoch)throw new MediaSessionChanged();entry=loaded&&this.entries.get(path)===loaded?loaded:undefined}
  if(!entry)return direct();entry.refs++;entry.used=++this.clock;const acquired=entry;let released=false;return {url:entry.url,cached:true,release:()=>{if(released)return;released=true;acquired.refs=Math.max(0,acquired.refs-1);acquired.used=++this.clock}};
 }
}
export const sessionMediaCache=new SessionMediaCache();
export const clearSessionMediaCache=()=>sessionMediaCache.clear();
