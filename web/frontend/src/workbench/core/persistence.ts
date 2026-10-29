import {createStore,type StoreApi} from 'zustand/vanilla';
import type {ActivityDelegate,Artifact,DraftAttachment,JsonRecord} from './models';
import {record,string} from './models';
import type {ApiTransport} from './transport';
import {isoTime} from './metrics';

const prefix='toolbox:draft:';
const localStorageIfAvailable=():Storage|undefined=>{try{return typeof localStorage==='undefined'?undefined:localStorage}catch{return undefined}};
export class DraftRepository {
  private stores=new Map<string,StoreApi<{value:object}>>();
  private resetBaselines=new Set<string>();
  readonly persistence=createStore<{error:string}>(()=>({error:''}));
  constructor(private storage:Storage|undefined=localStorageIfAvailable(),private activities?:ActivityDelegate){}
  get<T extends object=JsonRecord>(key:string):T|null{try{const raw=this.storage?.getItem(prefix+key);return raw?JSON.parse(raw) as T:null}catch{return null}}
  set<T extends object>(key:string,value:T):boolean{const release=this.activities?.begin('save');this.resetBaselines.delete(key);this.stores.get(key)?.setState({value});try{if(!this.storage)throw Error('storage unavailable');this.storage.setItem(prefix+key,JSON.stringify({...value,id:key,updatedAt:Date.now()}));this.persistence.setState({error:''});return true}catch{this.persistence.setState({error:'本机存储未能保存，输入仍在当前页面；请保留或复制原文后重试。'});return false}finally{release?.()}}
  remove(key:string):void{try{this.storage?.removeItem(prefix+key)}catch{this.persistence.setState({error:'本机输入记录未能更新，请核对存储设置。'})}}
  clearInputs():void{if(!this.storage)return;const keys=Array.from({length:this.storage.length},(_,index)=>this.storage!.key(index));for(const key of keys)if(key&&(key.startsWith(prefix)||key.startsWith('desk-draft:')))this.storage.removeItem(key);this.resetBaselines.clear();for(const [key,store] of this.stores){store.setState({value:{}});this.stores.delete(key)}}
  reset<T extends object>(key:string,initial:T):void{this.remove(key);this.resetBaselines.add(key);this.stores.get(key)?.setState({value:initial})}
  rebaseReset<T extends object>(key:string,initial:T):void{if(!this.resetBaselines.has(key))return;const store=this.stores.get(key);if(store&&JSON.stringify(store.getState().value)!==JSON.stringify(initial))store.setState({value:initial})}
  list():JsonRecord[]{if(!this.storage)return[];const result:JsonRecord[]=[];for(let index=0;index<this.storage.length;index++){const k=this.storage.key(index);if(k?.startsWith(prefix)){const d=this.get(k.slice(prefix.length));if(d)result.push({...d,id:k.slice(prefix.length)})}}return result.sort((a,b)=>Number(b.updatedAt??0)-Number(a.updatedAt??0))}
  private compatibleInput(key:string):JsonRecord|null{
    const own=this.get<JsonRecord>(key);if(own)return this.adaptDateInput(own);
    const section=key.match(/^studio:(?:rule|foundation):(.+)$/)?.[1];if(section){const value=record(this.get('studio:foundation-inputs'))[section];return value&&typeof value==='object'?record(value):null}
    if(key==='studio:configuration-editor')return this.get('studio:configuration');
    if(key==='studio:publication:new'){const old=this.get<JsonRecord>('studio:publication');return old?this.adaptDateInput(old):null}
    const scoped=key.match(/^studio:(metric|comment):(.+)$/);if(scoped){const old=this.get<JsonRecord>('studio:'+scoped[1]);if(old?.publication_id===scoped[2])return this.adaptDateInput(old)}
    if(key==='studio:analysis-question')return this.get('studio:analysis');
    if(key.startsWith('work-draft:'))return this.get('article:workspace:'+key.slice(11))??this.get('poster:workspace:'+key.slice(11));
    return null;
  }
  private adaptDateInput(value:JsonRecord):JsonRecord{
    const moment=record(value.moment),day=string(moment.day),time=string(moment.time);if(!day||!time)return value;
    const stamp=isoTime({day,time}),local=day+'T'+time;return {...value,day:value.day??day,time:value.time??time,...(stamp?{published_at:value.published_at??local,observed_at:value.observed_at??local}:{})};
  }
  store<T extends object>(key:string,initial:T):StoreApi<{value:T}>{let current=this.stores.get(key);if(!current){const saved=this.compatibleInput(key),input=Object.fromEntries(Object.entries(saved??{}).filter(([field])=>!['id','updatedAt'].includes(field)));const value=saved?{...initial,...record(saved.draft),...input}:initial;current=createStore<{value:object}>(()=>({value}));this.stores.set(key,current)}else this.rebaseReset(key,initial);return current as StoreApi<{value:T}>}
  /** Inputs remain in their existing keys. Never copy saved server results. */
  hasPending():boolean{return this.list().some(d=>!!(d.pending||d.pendingId||d.request||d.operation||d.pendingSave||d.pendingFinalize))}
}
export interface StoredDraftFile {blob:Blob;name:string;uploadId?:string;uploaded?:Artifact;[key:string]:unknown}
export async function draftFile(id:string,value?:StoredDraftFile,activities?:ActivityDelegate):Promise<StoredDraftFile|undefined>{
  const release=activities?.begin('save');let db:IDBDatabase|undefined;
  try{
    db=await new Promise<IDBDatabase>((resolve,reject)=>{const request=indexedDB.open('toolbox-draft-files',1);request.onupgradeneeded=()=>{if(!request.result.objectStoreNames.contains('files'))request.result.createObjectStore('files')};request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error)});
    return await new Promise<StoredDraftFile|undefined>((resolve,reject)=>{const tx=db!.transaction('files',value===undefined?'readonly':'readwrite'),store=tx.objectStore('files'),request=value===undefined?store.get(id):store.put(value,id);let result:StoredDraftFile|undefined;request.onsuccess=()=>{result=request.result as StoredDraftFile|undefined};tx.oncomplete=()=>resolve(value===undefined?result:value);tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error??Error('附件保存中断'))});
  }finally{db?.close();release?.()}
}
export async function attachFiles(files:Iterable<File>,existing:DraftAttachment[]=[],activities?:ActivityDelegate,maxBytes=20*1024*1024):Promise<DraftAttachment[]>{
  const next=[...existing];for(const file of files){if(file.size>maxBytes)throw Error('单个附件不能超过'+Math.round(maxBytes/1024/1024)+'MB');if(next.length>=12)throw Error('最多添加12个附件');const id='local-'+crypto.randomUUID(),uploadId=crypto.randomUUID();await draftFile(id,{blob:file,name:file.name,uploadId},activities);next.push({id,name:file.name,mime:file.type,size:file.size,local:true,uploadId})}return next;
}
export async function uploadFiles(files:(DraftAttachment|string)[],api:ApiTransport,csrf:string,activities?:ActivityDelegate):Promise<Artifact[]>{
  const result:Artifact[]=[];for(const file of files){if(typeof file==='string'){result.push({id:file,name:'已保存附件',mime:'application/octet-stream'});continue}if(!file.id.startsWith('local-')&&!file.local){result.push({id:file.id,name:file.name,mime:string(file.mime,'application/octet-stream')});continue}const saved=await draftFile(file.id,undefined,activities);if(!saved?.blob)throw Error('本机原始附件不可用，请重新选择');if(saved.uploaded){result.push(saved.uploaded);continue}saved.uploadId??=string(file.uploadId)||crypto.randomUUID();await draftFile(file.id,saved,activities);const uploaded=await api.request<Artifact>('/api/uploads',{raw:saved.blob,name:saved.name,csrf,id:saved.uploadId});await draftFile(file.id,{...saved,uploaded},activities);result.push(uploaded)}return result;
}
/** Typed read adapter for historical input records, preserving every original key. */
export function recoverInput<T extends object>(repository:DraftRepository,key:string,initial:T):T{return {...initial,...record(repository.get(key))} as T}
