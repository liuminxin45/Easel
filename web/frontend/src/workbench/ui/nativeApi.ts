import {bindDownloadResolver} from '../../lib/download';
import {bindEaselApiTransport, type EaselApiTransport} from '../../lib/api';
import {bindWhoamiStorage} from '../../lib/whoami';
import type {WorkbenchClient} from '../core/client';
import {requestFingerprint} from '../../lib/interaction';
import {record, type JsonRecord} from '../core/models';
import {nativeResourceCacheable,RESOURCE_FRESH_MS} from '../core/resource-cache';
import {RequestError} from '../core/transport';

/** Cancellation belongs to this reader, never the shared in-flight request. */
function reader<T>(promise:Promise<T>,signal?:AbortSignal|null):Promise<T>{
 if(!signal)return promise;
 if(signal.aborted){void promise.catch(()=>{});return Promise.reject(new RequestError('读取已取消',{cancelled:true}));}
 return new Promise<T>((resolve,reject)=>{
  const abort=()=>reject(new RequestError('读取已取消',{cancelled:true}));signal.addEventListener('abort',abort,{once:true});
  void promise.then(value=>{signal.removeEventListener('abort',abort);if(!signal.aborted)resolve(value)},error=>{signal.removeEventListener('abort',abort);reject(error)});
 });
}

/** Keep native protocols while retaining the host's durable operation identity. */
export function bindWorkbenchNativeApi(client:WorkbenchClient):()=>void {
 let detailSequence=0,configurationEpoch=-1,configurationRevision:number|undefined;
 const transport:EaselApiTransport={
  peek<T>(path:string){return nativeResourceCacheable(path)?client.peek<T>(path):undefined},
  subscribe<T>(path:string,onData:(value:T)=>void,onError?:(error:Error)=>void){
   if(!nativeResourceCacheable(path))return()=>{};
   const state=client.resource(path),unwatch=client.watch(path,new URL(path,'https://workbench.invalid').pathname==='/api/trends'?RESOURCE_FRESH_MS:undefined);let previous=state.getState().data,error='',status:number|undefined;
   if(state.getState().error){error=state.getState().error;status=state.getState().errorStatus;onError?.(new RequestError(error,{status}))}
   const unsubscribe=state.subscribe(value=>{
    if(value.data!==null&&(value.data!==previous||error&&!value.error)){previous=value.data;onData(value.data as T)}
    if(value.error&&(value.error!==error||value.errorStatus!==status))onError?.(new RequestError(value.error,{status:value.errorStatus}));error=value.error;status=value.errorStatus;
   });
   return()=>{unsubscribe();unwatch()};
  },
  async request<T>(path:string,options:RequestInit={}):Promise<T>{
   const method=(options.method||'GET').toUpperCase();
   if(method==='GET'||method==='HEAD'){
    const detail=new URL(path,'https://workbench.invalid').pathname.startsWith('/api/skill/'),sequence=detail?++detailSequence:0,authentication=client.authenticationEpoch;
    const remember=(value:T):T=>{const revision=record(value).configuration_revision;if(detail&&sequence===detailSequence&&authentication===client.authenticationEpoch){configurationRevision=typeof revision==='number'?revision:undefined;configurationEpoch=authentication;}return value};
    if(options.signal?.aborted)throw new RequestError('读取已取消',{cancelled:true});
    if(!nativeResourceCacheable(path))return remember(await client.api.get<T>(path,options.signal??undefined));
    const force=options.cache==='reload'||options.cache==='no-cache',epoch=client.authenticationEpoch;
    const read=async():Promise<T>=>{
     const value=await client.read<T>(path,force);
     if(epoch!==client.authenticationEpoch)throw new RequestError('登录状态已变化，读取已取消',{cancelled:true});
     if(value===null){const failure=client.resource(path).getState();throw new RequestError(failure.error||'页面数据暂未读取成功',{status:failure.errorStatus})}
     return value;
    };
    const snapshot=force?undefined:client.peek<T>(path);
    if(snapshot!==undefined){void read().catch(()=>{/* The subscriber exposes refresh failures without discarding the snapshot. */});return reader(Promise.resolve().then<T>(()=>{if(epoch!==client.authenticationEpoch)throw new RequestError('登录状态已变化，读取已取消',{cancelled:true});const current=client.peek<T>(path);return current===undefined?read():current}),options.signal).then(remember)}
    return reader(read(),options.signal).then(remember);
   }
   if(!['POST','PUT','PATCH','DELETE'].includes(method))throw Error('请求方法不受支持');
   const body:JsonRecord=typeof options.body==='string'?record(JSON.parse(options.body)):{};
   if(path==='/api/env'&&body.expected_revision===undefined){
    if(configurationRevision===undefined||configurationEpoch!==client.authenticationEpoch)throw new RequestError('请重新打开技能详情核对配置后再保存。',{status:409});
    body.expected_revision=configurationRevision;
   }
   const raw=options.body instanceof FormData?options.body:undefined;
   const fields:unknown[]=[];
   if(raw)for(const [key,value] of raw.entries()){
    if(typeof value==='string')fields.push([key,value]);
    else {const digest=await crypto.subtle.digest('SHA-256',await value.arrayBuffer());fields.push([key,value.name,value.size,value.type,Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('')]);}
   }
   const requestSignature=await requestFingerprint({method,path,body,...(raw?{fields}:{})});
   const settings=path==='/api/env';
   const result=await client.mutate<T>(settings?'settings':'easel-native:'+method+':'+path,path,body,{
    method:method as 'POST'|'PUT'|'PATCH'|'DELETE',raw,preserveBody:!settings,metadataOnly:true,requestSignature,
    receiptPath:id=>(settings?'/api/settings/operations/':'/api/native/operations/')+encodeURIComponent(id),
    ...(method==='POST'&&(path==='/api/skill'||path==='/api/chat')?{requestTimeout:null}:{}),
   });
   return result;
  },
  mediaUrl:path=>'/api/media/'+path.split('/').map(encodeURIComponent).join('/'),
 };
 const releaseDownloads=bindDownloadResolver(async(href,name)=>{
  const target=new URL(href,location.origin);
  const result=await client.api.query<{url:string}>('/api/downloads',{target:target.pathname+target.search,name},String(client.session.getState().config?.csrf||''));
  if(!result?.url)throw Error('下载凭证未取得，请重试');return result.url;
 });
 const values=new Map<string,string>();
 const releaseCache=bindWhoamiStorage({getItem:key=>values.get(key)??null,setItem:(key,value)=>{values.set(key,value)},removeItem:key=>{values.delete(key)}},{automaticVerification:false});
 const releaseApi=bindEaselApiTransport(transport);
 return ()=>{releaseDownloads();releaseApi();releaseCache();values.clear()};
}
