import type {ActivityDelegate,JsonRecord} from './models';
import {record,string} from './models';

export class RequestError extends Error {
  status?:number; uncertain=false; unreachable=false; cancelled=false; timedOut=false;
  operationScope?:string;operationId?:string;
  constructor(message:string,properties:Partial<Pick<RequestError,'status'|'uncertain'|'unreachable'|'cancelled'|'timedOut'|'operationScope'|'operationId'>>={}){super(message);this.name='RequestError';Object.assign(this,properties)}
}
export interface RequestOptions {body?:JsonRecord;csrf?:string;id?:string;raw?:Blob|FormData;name?:string;signal?:AbortSignal;conditional?:boolean;etag?:string;readOnly?:boolean;method?:'POST'|'PUT'|'PATCH'|'DELETE'}
export interface ConditionalResponse<T> {status:'modified'|'not-modified';data?:T;etag?:string;serverTime?:string}
export interface TransportOptions {fetcher?:typeof fetch;activities?:ActivityDelegate;onExpired?:()=>void;onConnectivity?:(reachable:boolean)=>void;authEpoch?:()=>number;readTimeout?:number;writeTimeout?:number;uploadTimeout?:number;retryDelay?:number}
const abortError=()=>new RequestError('读取已取消',{cancelled:true});
const wait=(ms:number,signal?:AbortSignal)=>new Promise<void>((resolve,reject)=>{if(signal?.aborted){reject(abortError());return}const stop=()=>{clearTimeout(timer);reject(abortError())};const timer=setTimeout(()=>{signal?.removeEventListener('abort',stop);resolve()},ms);signal?.addEventListener('abort',stop,{once:true})});

/** Reads retry once. Mutations and lost receipts never replay in this layer. */
export class ApiTransport {
  private fetcher:typeof fetch;
  constructor(private options:TransportOptions={}){this.fetcher=options.fetcher??((...args)=>globalThis.fetch(...args))}
  async request<T=JsonRecord>(path:string,options:RequestOptions={}):Promise<T>{
    if(!path.startsWith('/api/')||path.startsWith('//'))throw new RequestError('请求地址无效');
    const write=(options.body!==undefined||options.raw!==undefined)&&!options.readOnly;
    const epoch=this.options.authEpoch?.();
    for(let attempt=0;;attempt++){
      if(options.signal?.aborted)throw abortError();
      if(attempt&&epoch!==this.options.authEpoch?.())throw abortError();
      try{return await this.attempt<T>(path,options)}catch(caught){
        const error=caught instanceof RequestError?caught:new RequestError(caught instanceof Error?caught.message:'请求未完成');
        if(!write&&!error.cancelled&&attempt===0&&(error.timedOut||error.unreachable||[502,503,504].includes(error.status??0))){await wait(this.options.retryDelay??400,options.signal);continue}
        if(error.unreachable)this.options.onConnectivity?.(false);throw error;
      }
    }
  }
  private async attempt<T>(path:string,options:RequestOptions):Promise<T>{
    const post=options.body!==undefined||options.raw!==undefined,write=post&&!options.readOnly,controller=new AbortController(),epoch=this.options.authEpoch?.();
    const release=this.options.activities?.begin(write?'write':'read');
    const timer=setTimeout(()=>controller.abort(),options.raw?this.options.uploadTimeout??45000:write?this.options.writeTimeout??30000:this.options.readTimeout??30000);
    const stop=()=>controller.abort();options.signal?.addEventListener('abort',stop,{once:true});
    try{
      const multipart=typeof FormData!=='undefined'&&options.raw instanceof FormData;
      const response=await this.fetcher(path,{credentials:'same-origin',cache:'no-store',signal:controller.signal,...(post?{method:options.method??'POST',headers:{...(!multipart?{'Content-Type':options.raw?'application/octet-stream':'application/json'}:{}),'X-CSRF-Token':options.csrf??'',...(options.id?{'X-Operation-Id':options.id}:{}),...(options.name?{'X-File-Name':encodeURIComponent(options.name)}:{})},body:options.raw??JSON.stringify(options.body)}:options.conditional&&options.etag?{headers:{'If-None-Match':options.etag}}:{})});
      if(epoch!==this.options.authEpoch?.())throw abortError();
      this.options.onConnectivity?.(true);
      if(response.status===401){if(epoch===this.options.authEpoch?.())this.options.onExpired?.();throw new RequestError('登录已过期，输入已保留，请重新登录。',{status:401})}
      const metadata={etag:response.headers.get('ETag')||undefined,serverTime:response.headers.get('X-Workbench-Server-Time')||undefined};
      if(response.status===304&&options.conditional&&!write)return {status:'not-modified',...metadata} as T;
      const text=await response.text();if(epoch!==this.options.authEpoch?.())throw abortError();let value:unknown;
      try{value=text?JSON.parse(text):{}}catch{throw new RequestError('服务器响应未能核对',{status:response.status,uncertain:write})}
      if(!response.ok)throw new RequestError(string(record(value).error)||string(record(value).detail,'请求未完成'),{status:response.status});
      return (options.conditional&&!write?{status:'modified',data:value,...metadata}:value) as T;
    }catch(caught){
      if(caught instanceof RequestError)throw caught;
      if(caught instanceof Error&&caught.name==='AbortError')throw new RequestError(write?'提交回执待核对，请保留原操作。':'读取超时，请重试。',{cancelled:!!options.signal?.aborted,timedOut:!options.signal?.aborted,uncertain:write});
      if(caught instanceof TypeError)throw new RequestError(write?'提交回执待核对，请保留原操作。':'暂时无法连接服务器。',{unreachable:true,uncertain:write});
      throw caught;
    }finally{clearTimeout(timer);options.signal?.removeEventListener('abort',stop);release?.()}
  }
  get<T=JsonRecord>(path:string,signal?:AbortSignal):Promise<T>{return this.request<T>(path,{signal})}
  conditionalGet<T=JsonRecord>(path:string,etag?:string,signal?:AbortSignal):Promise<ConditionalResponse<T>>{return this.request<ConditionalResponse<T>>(path,{conditional:true,etag,signal})}
  post<T=JsonRecord>(path:string,body:JsonRecord,csrf:string,id?:string):Promise<T>{return this.request<T>(path,{body,csrf,id})}
  query<T=JsonRecord>(path:string,body:JsonRecord,csrf:string):Promise<T>{return this.request<T>(path,{body,csrf,readOnly:true})}
}
