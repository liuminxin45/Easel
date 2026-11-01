import {bindDownloadResolver} from '../../lib/download';
import {bindEaselApiTransport, type EaselApiTransport} from '../../lib/api';
import {bindWhoamiStorage} from '../../lib/whoami';
import type {WorkbenchClient} from '../core/client';
import {requestFingerprint} from '../../lib/interaction';
import {record, type JsonRecord} from '../core/models';

/** Keep native protocols while retaining the host's durable operation identity. */
export function bindWorkbenchNativeApi(client:WorkbenchClient):()=>void {
 const transport:EaselApiTransport={
  async request<T>(path:string,options:RequestInit={}):Promise<T>{
   const method=(options.method||'GET').toUpperCase();
   if(method==='GET'||method==='HEAD')return client.api.get<T>(path,options.signal??undefined);
   if(!['POST','PUT','PATCH','DELETE'].includes(method))throw Error('请求方法不受支持');
   const body:JsonRecord=typeof options.body==='string'?record(JSON.parse(options.body)):{};
   const raw=options.body instanceof FormData?options.body:undefined;
   const fields:unknown[]=[];
   if(raw)for(const [key,value] of raw.entries()){
    if(typeof value==='string')fields.push([key,value]);
    else {const digest=await crypto.subtle.digest('SHA-256',await value.arrayBuffer());fields.push([key,value.name,value.size,value.type,Array.from(new Uint8Array(digest),b=>b.toString(16).padStart(2,'0')).join('')]);}
   }
   const requestSignature=await requestFingerprint({method,path,body,...(raw?{fields}:{})});
   const result=await client.mutate<T>('easel-native:'+method+':'+path,path,body,{
    method:method as 'POST'|'PUT'|'PATCH'|'DELETE',raw,preserveBody:true,metadataOnly:true,requestSignature,
    receiptPath:id=>'/api/native/operations/'+encodeURIComponent(id),
   });
   client.invalidate(['creator','works','easel','distribution']);
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
