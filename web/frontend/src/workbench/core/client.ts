import {createStore,type StoreApi} from 'zustand/vanilla';
import {ApiTransport,RequestError,type TransportOptions} from './transport';
import {DraftRepository,attachFiles,draftFile,uploadFiles} from './persistence';
import {AuthService} from './auth';
import {retiredPersonalDraft} from './creation-scope';
import {record,string,array,type ActivityDelegate,type Artifact,type Config,type CreativeOptions,type DraftAttachment,type JsonRecord,type NavigationDelegate,type StudioAction,type CollectionRun} from './models';
import {completionPreviewPath,type CompletionPlan,type CompletionPreview} from './completion';
import {clearSessionMediaCache} from './session-media';
import type {LearningBootstrap,LearningDetail,LearningKind} from './learning';
import {UsageTracker} from './usage';
import {AUTH_CHECK_MS,RESOURCE_CACHE_BYTES,RESOURCE_CACHE_ENTRIES,mutationTags,resourceCacheable,resourceFreshMs,resourceTags,withServerTime} from './resource-cache';
import {commandScope,interactionFeedback,type InteractionFeedback} from '../../lib/interaction';

export interface ResourceState {data:unknown;loading:boolean;refreshing?:boolean;error:string;feedback?:InteractionFeedback;revision:number;stale:boolean;checkedAt?:number}
export interface PendingOperation {method?:'POST'|'PUT'|'PATCH'|'DELETE';scope:string;path:string;body:JsonRecord;id:string;uncertain:boolean;requestSignature?:string;receiptPath?:string;metadataOnly?:boolean;legacyKey?:string;legacyField?:'pending'|'request'|'pendingSave'|'pendingFinalize';legacyUploads?:boolean}
export interface MutationOptions {preserveBody?:boolean;raw?:FormData;method?:'POST'|'PUT'|'PATCH'|'DELETE';metadataOnly?:boolean;requestSignature?:string;receiptPath?:(id:string)=>string}
export interface OperationState {busy:boolean;pending:PendingOperation|null;error:string;notice:string;result?:unknown;feedback?:InteractionFeedback}
export interface SessionState {config:Config|null;loading:boolean;error:string;feedback?:InteractionFeedback;expired:boolean;reachable:boolean|null}
export interface ClientOptions extends TransportOptions {storage?:Storage;navigation?:NavigationDelegate;activities?:ActivityDelegate;clock?:()=>number;cacheBytes?:number;cacheEntries?:number}
const message=(error:unknown)=>error instanceof Error?error.message:'操作未完成';
const signature=(value:JsonRecord)=>JSON.stringify(Object.fromEntries(Object.entries(value).filter(([key])=>!['id','operation_id'].includes(key)).sort(([a],[b])=>a.localeCompare(b))));
export class WorkbenchClient {
  readonly session=createStore<SessionState>(()=>({config:null,loading:true,error:'',expired:false,reachable:null}));
  readonly api:ApiTransport;readonly drafts:DraftRepository;readonly service:DomainService;readonly auth:AuthService;readonly usage:UsageTracker;
  private resources=new Map<string,StoreApi<ResourceState>>();private activeResources=new Map<string,number>();private inflight=new Map<string,Promise<unknown>>();private invalidations=new Map<string,number>();private operations=new Map<string,StoreApi<OperationState>>();private receiptReads=new Map<string,Promise<unknown>>();private initializePromise?:Promise<void>;
  private cacheMeta=new Map<string,{etag?:string;checkedAt:number;lastAccess:number;lastAttempt:number;bytes:number}>();
  private pollWatchers=new Map<string,Map<symbol,number|undefined>>();private pollTimers=new Map<string,ReturnType<typeof setTimeout>>();
  private authEpoch=0;private lastAuthCheckedAt=0;private authCheckPromise?:Promise<boolean>;private resumePromise?:Promise<void>;private hidden=false;
  private receiptTimers=new Map<string,ReturnType<typeof setTimeout>>();
  private readonly now:()=>number;private readonly cacheBytes:number;private readonly cacheEntries:number;
  navigation?:NavigationDelegate;readonly activities?:ActivityDelegate;
  constructor(options:ClientOptions={}){
    this.usage=new UsageTracker({fetcher:options.fetcher,onExpired:()=>{this.expireSession();options.onExpired?.()}});
    this.now=options.clock??Date.now;this.cacheBytes=options.cacheBytes??RESOURCE_CACHE_BYTES;this.cacheEntries=options.cacheEntries??RESOURCE_CACHE_ENTRIES;
    this.navigation=options.navigation;this.activities=options.activities;this.drafts=new DraftRepository(options.storage,options.activities);
    this.api=new ApiTransport({...options,authEpoch:()=>this.authEpoch,onExpired:()=>{this.expireSession();options.onExpired?.()},onConnectivity:reachable=>{this.session.setState({reachable});options.onConnectivity?.(reachable)}});
    this.auth=new AuthService({fetcher:options.fetcher,activities:options.activities});this.service=new DomainService(this);
  }
  get authenticationEpoch():number{return this.authEpoch}
  private clearPrivateMemory():void{
    this.usage.clear();
    for(const timer of this.receiptTimers.values())clearTimeout(timer);this.receiptTimers.clear();this.receiptReads.clear();
    for(const state of this.operations.values())state.setState({result:undefined,error:'',feedback:undefined,notice:''});
    this.authEpoch++;this.cacheMeta.clear();this.inflight.clear();this.lastAuthCheckedAt=0;this.resumePromise=undefined;
    for(const timer of this.pollTimers.values())clearTimeout(timer);this.pollTimers.clear();
    for(const [path,state] of this.resources){this.invalidations.set(path,(this.invalidations.get(path)??0)+1);state.setState({data:null,loading:false,refreshing:false,error:'',feedback:undefined,stale:true,checkedAt:undefined})}
    clearSessionMediaCache();this.pruneResources();
  }
  beginAuthentication():void{this.clearPrivateMemory();this.initializePromise=undefined;this.authCheckPromise=undefined;this.session.setState({config:null,loading:true,expired:false,error:''})}
  initialize():Promise<void>{
    if(this.initializePromise)return this.initializePromise;
    const epoch=this.authEpoch;this.session.setState({loading:true,error:'',feedback:undefined});
    this.initializePromise=(async()=>{try{const config=await this.api.get<Config>('/api/config');if(epoch!==this.authEpoch)return;this.lastAuthCheckedAt=this.now();void this.usage.configure(record(config).usage,config.csrf);this.session.setState({config,loading:false,expired:false,error:'',feedback:undefined})}catch(error){if(epoch===this.authEpoch){this.session.setState({loading:false,error:message(error),feedback:interactionFeedback(error)});this.initializePromise=undefined}}})();return this.initializePromise;
  }
  expireSession():void{this.clearPrivateMemory();this.initializePromise=undefined;this.authCheckPromise=undefined;this.session.setState({expired:true,config:null,loading:false,error:'',feedback:undefined});for(const state of this.resources.values())state.setState({error:'登录已过期，输入已保留。'})}
  resource(path:string):StoreApi<ResourceState>{
    let state=this.resources.get(path);if(!state){state=createStore<ResourceState>(()=>({data:null,loading:true,error:'',revision:0,stale:true}));this.resources.set(path,state)}
    const meta=this.cacheMeta.get(path);if(meta)meta.lastAccess=this.now();return state;
  }
  private visible():boolean{return !this.hidden&&(typeof document==='undefined'||!document.hidden)}
  watch(path:string,interval?:number):()=>void{
    this.activeResources.set(path,(this.activeResources.get(path)??0)+1);let watchers=this.pollWatchers.get(path);if(!watchers){watchers=new Map();this.pollWatchers.set(path,watchers)}
    const id=Symbol(path);watchers.set(id,interval);this.schedulePoll(path);let released=false;
    return()=>{if(released)return;released=true;const n=(this.activeResources.get(path)??1)-1;if(n<=0)this.activeResources.delete(path);else this.activeResources.set(path,n);const rows=this.pollWatchers.get(path);rows?.delete(id);if(!rows?.size)this.pollWatchers.delete(path);this.schedulePoll(path);this.pruneResources()};
  }
  private schedulePoll(path:string):void{
    const previous=this.pollTimers.get(path);if(previous)clearTimeout(previous);this.pollTimers.delete(path);
    if(!this.visible()||this.session.getState().expired||![...(this.pollWatchers.get(path)?.values()??[])].some(value=>value!==undefined&&value>0))return;
    const ttl=Math.max(1000,resourceFreshMs(path,this.resources.get(path)?.getState().data??null)),last=this.cacheMeta.get(path)?.lastAttempt;
    const timer=setTimeout(()=>{this.pollTimers.delete(path);if(this.visible())void this.read(path).finally(()=>this.schedulePoll(path))},Math.max(20,last===undefined?ttl:ttl-(this.now()-last)));
    (timer as unknown as {unref?:()=>void}).unref?.();this.pollTimers.set(path,timer);
  }
  pauseVisible():void{this.hidden=true;for(const timer of this.pollTimers.values())clearTimeout(timer);this.pollTimers.clear();for(const timer of this.receiptTimers.values())clearTimeout(timer);this.receiptTimers.clear()}
  checkAuthentication():Promise<boolean>{
    if(this.session.getState().expired)return Promise.resolve(false);
    if(this.session.getState().config&&this.lastAuthCheckedAt>0&&this.now()-this.lastAuthCheckedAt<AUTH_CHECK_MS)return Promise.resolve(true);
    if(this.authCheckPromise)return this.authCheckPromise;
    if(!this.session.getState().config&&this.initializePromise)return this.initializePromise.then(()=>!!this.session.getState().config&&!this.session.getState().expired);
    const epoch=this.authEpoch;
    let job!:Promise<boolean>;job=(async()=>{try{const config=await this.api.get<Config>('/api/config');if(epoch!==this.authEpoch)return false;const old=this.session.getState().config;if(old&&old.csrf!==config.csrf)this.clearPrivateMemory();this.lastAuthCheckedAt=this.now();void this.usage.configure(record(config).usage,config.csrf);this.session.setState({config,loading:false,expired:false,error:'',feedback:undefined});return true}catch(error){if(epoch===this.authEpoch)this.session.setState({error:message(error),feedback:interactionFeedback(error)});return false}finally{if(this.authCheckPromise===job)this.authCheckPromise=undefined}})();
    this.authCheckPromise=job;return job;
  }
  resumeVisible():Promise<void>{
    this.hidden=false;if(this.resumePromise)return this.resumePromise;
    const job=(async()=>{if(!await this.checkAuthentication()||!this.visible())return;this.resumeReceiptRecovery();await Promise.all([...this.activeResources.keys()].map(path=>this.read(path)));for(const path of this.activeResources.keys())this.schedulePoll(path)})();
    this.resumePromise=job;void job.finally(()=>{if(this.resumePromise===job)this.resumePromise=undefined});return job;
  }
  read<T=JsonRecord>(path:string,force=false):Promise<T|null>{
    // A child hook may receive visibilitychange before CoreProvider does.
    // Its forced reload must still wait for foreground authentication.
    if(typeof document!=='undefined'&&!document.hidden&&(this.hidden||this.resumePromise&&this.authCheckPromise))return (this.hidden?this.resumeVisible():this.resumePromise!).then(()=>this.read<T>(path));
    const state=this.resource(path),running=this.inflight.get(path);if(this.session.getState().expired){state.setState({data:null,loading:false,refreshing:false,feedback:undefined,error:'登录已过期，输入已保留。'});return Promise.resolve(null)}if(running)return running as Promise<T|null>;
    const oldMeta=this.cacheMeta.get(path),oldState=state.getState(),now=this.now();
    if(!force&&oldState.data!==null&&!oldState.stale&&oldMeta&&now-oldMeta.checkedAt<resourceFreshMs(path,oldState.data)){oldMeta.lastAccess=now;return Promise.resolve(oldState.data as T)}
    state.setState({loading:oldState.data===null,refreshing:true,error:'',feedback:undefined});
    const epoch=this.invalidations.get(path)??0,authEpoch=this.authEpoch,meta=oldMeta??{checkedAt:0,lastAccess:now,lastAttempt:now,bytes:0};meta.lastAttempt=now;meta.lastAccess=now;this.cacheMeta.set(path,meta);
    let job!:Promise<T|null>;
    job=(async()=>{let data:T|null=null,revalidate=false;try{
      let reply=await this.api.conditionalGet<T>(path,resourceCacheable(path)&&oldState.data!==null?meta.etag:undefined);
      if(authEpoch!==this.authEpoch)return null;
      if(reply.status==='not-modified'&&state.getState().data===null){reply=await this.api.conditionalGet<T>(path);if(reply.status==='not-modified')throw new RequestError('服务器未返回可恢复的数据，请重新读取。')}
      if(authEpoch!==this.authEpoch||this.session.getState().expired)return null;
      revalidate=epoch!==(this.invalidations.get(path)??0);
      if(!revalidate){
        data=withServerTime(reply.status==='not-modified'?state.getState().data as T:reply.data as T,reply.serverTime);
        meta.etag=resourceCacheable(path)?reply.etag??(reply.status==='not-modified'?meta.etag:undefined):undefined;meta.checkedAt=this.now();meta.lastAccess=this.now();
        try{meta.bytes=new TextEncoder().encode(JSON.stringify(data)).byteLength}catch{meta.bytes=this.cacheBytes+1}
        state.setState(previous=>({data,loading:false,refreshing:false,error:'',feedback:undefined,revision:previous.revision+(reply.status==='modified'?1:0),stale:false,checkedAt:meta.checkedAt}));
      }
    }catch(error){const valid=authEpoch===this.authEpoch&&!this.session.getState().expired;revalidate=valid&&epoch!==(this.invalidations.get(path)??0);if(valid&&!revalidate)state.setState({loading:false,refreshing:false,error:message(error),feedback:interactionFeedback(error)})}
    finally{if(this.inflight.get(path)===job)this.inflight.delete(path);this.pruneResources();this.schedulePoll(path)}
    return revalidate?this.read<T>(path,true):data})();this.inflight.set(path,job);return job;
  }
  private pruneResources():void{
    const entries=[...this.resources.keys()].filter(path=>!this.activeResources.has(path)&&!this.inflight.has(path)).sort((a,b)=>(this.cacheMeta.get(a)?.lastAccess??0)-(this.cacheMeta.get(b)?.lastAccess??0));
    let bytes=[...this.cacheMeta.values()].reduce((total,meta)=>total+meta.bytes,0),inactive=entries.length;
    for(const path of entries){if(inactive<=this.cacheEntries&&bytes<=this.cacheBytes&&resourceCacheable(path))continue;const meta=this.cacheMeta.get(path);bytes-=meta?.bytes??0;inactive--;this.resources.get(path)?.setState({data:null,stale:true,loading:false});this.resources.delete(path);this.cacheMeta.delete(path);this.invalidations.delete(path)}
  }
  async invalidate(tags:string[]|null):Promise<void>{
    const affected:string[]=[];
    for(const [path,state] of this.resources){if(tags!==null&&!resourceTags(path).some(tag=>tags.includes(tag)))continue;this.invalidations.set(path,(this.invalidations.get(path)??0)+1);state.setState({stale:true});if(this.activeResources.has(path))affected.push(path)}
    await Promise.all(affected.map(path=>this.read(path,true)));
  }
  refresh():Promise<void>{return this.invalidate(null)}
  /** Apply an exact server acknowledgement without waiting for list refreshes. */
  updateResource<T>(path:string,update:(previous:T)=>T):void{const state=this.resource(path),data=state.getState().data;if(data!==null){this.invalidations.set(path,(this.invalidations.get(path)??0)+1);state.setState(previous=>({data:update(data as T),revision:previous.revision+1,stale:true}))}}
  legacyPending():{key:string;id:string;input:JsonRecord}[]{return this.drafts.list().filter(input=>!retiredPersonalDraft(input)&&!string(input.id).startsWith('native:pending:')).flatMap(input=>{const pending=record(input.pending),request=record(input.request),operation=record(input.operation);const id=string(input.pendingId)||string(pending.id)||string(request.id)||string(request.operation_id)||string(operation.id)||string(record(input.pendingSave).id)||string(record(input.pendingFinalize).id);return id?[{key:string(input.id),id,input}]:[]})}
  private legacyOperation(scope:string):PendingOperation|null{
    for(const item of this.legacyPending()){
      const key=item.key,request=record(item.input.request),pending=record(item.input.pending);
      let path='',body:JsonRecord={},field:NonNullable<PendingOperation['legacyField']>='pending',legacyUploads=false;
      if(scope.startsWith('text:')&&key.startsWith('text-edit:'+scope.slice(5)+':')&&request.id){path='/api/works/'+encodeURIComponent(scope.slice(5))+'/text';body=request;field='request'}
      else if(scope.startsWith('discuss:')&&key.startsWith('discussion:'+scope.slice(8)+':')&&pending.id&&typeof pending.text==='string'){path='/api/works/'+encodeURIComponent(scope.slice(8))+'/discussions';body=pending}
      else if(scope.startsWith('annotation:')){const parts=scope.split(':');if(key==='review:'+parts[1]+':'+parts[2]&&pending.id&&typeof pending.kind==='string'){path='/api/works/'+encodeURIComponent(parts[1]! )+'/versions/'+encodeURIComponent(parts[2]! )+'/review';body=pending}}
      else if(scope.startsWith('draft:')||scope.startsWith('finalize:')){const final=scope.startsWith('finalize:'),wid=scope.slice(final?9:6);if(key==='article:workspace:'+wid||key==='poster:workspace:'+wid){field=final?'pendingFinalize':'pendingSave';const original=record(item.input[field]);if(original.id&&typeof original.revision==='number'){path='/api/works/'+encodeURIComponent(wid)+(final?'/finalize':'/draft');body=original}}}
      else if(scope.startsWith('work:')){const [,wid,kind]=scope.split(':');if(key.startsWith('feedback:'+wid+':')&&pending.id&&typeof pending.signature==='string')try{const frozen=record(JSON.parse(pending.signature));if(frozen.kind===kind&&frozen.version&&typeof frozen.text==='string'&&Array.isArray(frozen.files)){body={id:pending.id,kind,candidate_id:frozen.version,text:frozen.text||(kind==='reject'?'此版暂不采用':''),files:frozen.files,scope:kind==='accept'?frozen.scope:[],...(kind==='change'?{creative:frozen.creative}:{}),...(['change','feedback'].includes(kind||'')?{review_revision:frozen.review_revision}:{})};path='/api/works/'+encodeURIComponent(wid!)+'/actions';legacyUploads=frozen.files.some(file=>typeof file!=='string')}}catch{/* An incomplete historical signature requires manual reconciliation. */}}
      if(path)return {scope,path,body,id:string(body.id),uncertain:true,legacyKey:key,legacyField:field,legacyUploads};
    }
    return null;
  }
  private clearPending(pending:PendingOperation):void{
    const timer=this.receiptTimers.get(pending.scope);if(timer)clearTimeout(timer);this.receiptTimers.delete(pending.scope);
    this.drafts.remove('native:pending:'+pending.scope);if(pending.scope==='studio')this.drafts.remove('studio:pending-command');
    if(pending.legacyKey&&!pending.legacyField)this.drafts.remove(pending.legacyKey);
    if(pending.legacyKey&&pending.legacyField){const old=this.drafts.get<JsonRecord>(pending.legacyKey);if(old){const store=this.drafts.store<JsonRecord>(pending.legacyKey,{}),current={...store.getState().value},next={...old};delete next[pending.legacyField];delete current[pending.legacyField];this.drafts.set(pending.legacyKey,next);store.setState({value:current})}}
  }
  operation(scope:string):StoreApi<OperationState>{
    let state=this.operations.get(scope);if(state)return state;
    const current=this.drafts.get<JsonRecord>('native:pending:'+scope);let pending=record(current?.operation) as unknown as PendingOperation|null;
    if(!pending?.id)pending=null;else pending={...pending,uncertain:true};
    if(scope==='studio'&&!pending){const old=record(this.drafts.get('studio:pending-command')?.request);if(string(old.operation_id))pending={scope,path:'/api/studio/commands',body:old,id:string(old.operation_id),uncertain:true}}
    if(scope==='settings'&&!pending){const old=record(this.drafts.get('settings:pending'));if(string(old.operation_id)&&string(old.path))pending={scope,path:string(old.path),body:{},id:string(old.operation_id),requestSignature:string(old.signature),metadataOnly:true,receiptPath:'/api/settings/operations/'+encodeURIComponent(string(old.operation_id)),legacyKey:'settings:pending',uncertain:true}}
    if(!pending&&['studio','learning','creative','creator'].includes(scope.split(':')[0]||'')){const domain=scope.split(':')[0]!;for(const saved of this.drafts.list()){const key=string(saved.id),old=record(saved.operation),body=record(old.body);if(key==='native:pending:'+scope||!key.startsWith('native:pending:'+domain)||!string(old.id)||commandScope(domain,string(body.action),body)!==scope)continue;pending={...old,scope,body,id:string(old.id),path:string(old.path),uncertain:true,legacyKey:key} as PendingOperation;break}if(!pending&&domain==='studio'){const old=record(this.drafts.get('studio:pending-command')?.request);if(string(old.operation_id)&&commandScope('studio',string(old.action),old)===scope)pending={scope,path:'/api/studio/commands',body:old,id:string(old.operation_id),uncertain:true,legacyKey:'studio:pending-command'}}}
    pending??=this.legacyOperation(scope);
    state=createStore<OperationState>(()=>({busy:false,pending,error:'',notice:'',feedback:pending?interactionFeedback({uncertain:true}):undefined}));this.operations.set(scope,state);if(pending)this.scheduleReceiptRecovery(scope,0);return state;
  }
  private resumeReceiptRecovery():void{for(const row of this.drafts.list()){const pending=record(row.operation);if(string(row.id).startsWith('native:pending:')&&string(pending.scope))this.operation(string(pending.scope))}if(this.drafts.get('settings:pending'))this.operation('settings');for(const scope of this.operations.keys())this.scheduleReceiptRecovery(scope,0)}
  private scheduleReceiptRecovery(scope:string,delay=1500):void{
    if(this.receiptTimers.has(scope)||!this.visible()||this.session.getState().expired||!this.session.getState().config||!this.operations.get(scope)?.getState().pending)return;
    const timer=setTimeout(()=>{this.receiptTimers.delete(scope);if(!this.visible()||this.operations.get(scope)?.getState().busy)return;void this.reconcile(scope).catch(()=>{/* Definite rejections are exposed by the operation store. */}).finally(()=>this.scheduleReceiptRecovery(scope,Math.min(Math.max(delay*2,1500),15000)))},delay);
    (timer as unknown as {unref?:()=>void}).unref?.();this.receiptTimers.set(scope,timer);
  }
  async mutate<T=JsonRecord>(scope:string,path:string,fields:JsonRecord,options:MutationOptions={}):Promise<T>{
    const state=this.operation(scope),current=state.getState();if(current.busy)throw new RequestError('这项操作正在处理。');
    if(options.metadataOnly&&(!options.requestSignature||!options.receiptPath))throw new RequestError('此操作缺少安全的恢复配置。');
    let pending=current.pending;
    if(pending){state.setState({busy:true});let result:T|null;try{result=await this.reconcile<T>(scope)}finally{state.setState({busy:false});this.scheduleReceiptRecovery(scope)}if(result!==null){if(pending.path===path&&(pending.method??'POST')===(options.method??'POST')&&(pending.requestSignature??signature(pending.body))===(options.requestSignature??signature(fields)))return result;if(options.metadataOnly&&typeof record(result).revision==='number')fields={...fields,expected_revision:record(result).revision};pending=null}else throw new RequestError('连接恢复中，原输入已保留，请稍后再试。',{status:409,uncertain:true,operationScope:scope,operationId:pending.id})}
    if(!this.session.getState().config?.csrf||this.session.getState().expired)throw new RequestError('请等待登录校验完成。');
    const id=(options.preserveBody?'':string(fields.operation_id)||string(fields.id))||crypto.randomUUID(),body=options.preserveBody?fields:{...fields,id,...(['/api/studio/commands','/api/learning/commands','/api/collection/sources'].includes(path)?{operation_id:id}:{})};
    pending={scope,path,...(options.method?{method:options.method}:{}),body:options.metadataOnly?{}:body,id,uncertain:false,...(options.metadataOnly?{metadataOnly:true,requestSignature:options.requestSignature,receiptPath:options.receiptPath!(id)}:{})};
    if(!this.drafts.set('native:pending:'+scope,{operation:pending}))throw new RequestError('原操作标识未能保存，请先核对本机存储；这次尚未提交。');state.setState({pending});
    return this.execute<T>(pending,body,options.raw);
  }
  /** Lost acknowledgements are recovered by GET. This never runs a command. */
  reconcile<T=JsonRecord>(scope:string):Promise<T|null>{
    const pending=this.operation(scope).getState().pending;if(!pending||this.session.getState().expired||!this.session.getState().config)return Promise.resolve(null);
    const key=scope+':'+pending.id,existing=this.receiptReads.get(key);if(existing)return existing as Promise<T|null>;
    const epoch=this.authEpoch;let job!:Promise<T|null>;
    job=(async()=>{try{
      const receipt=await this.api.get<{id?:string;state:string;result?:T}>(pending.receiptPath??'/api/operations/'+encodeURIComponent(pending.id)+'?'+new URLSearchParams({path:pending.path}),AbortSignal.timeout(3000));
      if(epoch!==this.authEpoch||(receipt.id!==undefined&&receipt.id!==pending.id)||(!pending.receiptPath&&receipt.id!==pending.id)||this.operation(scope).getState().pending?.id!==pending.id)return null;
      if(receipt.state==='unavailable')this.operation(scope).setState({feedback:{kind:'status',message:'暂未取得操作结果，输入已保留。'}});
      if(receipt.state==='rejected'){const error=new RequestError(string(record(receipt.result).error)||string(record(receipt.result).detail,'操作未被受理，请修正后重试。'),{status:400});this.clearPending(pending);this.operation(scope).setState({pending:null,error:error.message,feedback:interactionFeedback(error)});throw error}
      if(!['received','completed'].includes(receipt.state)||receipt.result===undefined)return null;
      this.clearPending(pending);this.operation(scope).setState({pending:null,error:'',feedback:undefined,notice:'已恢复连接',result:receipt.result});this.refreshAfterCommand(pending,receipt.result);return receipt.result;
    }catch(error){if(error instanceof RequestError&&error.status===400&&!error.uncertain)throw error;return null}finally{if(this.receiptReads.get(key)===job)this.receiptReads.delete(key)}})();this.receiptReads.set(key,job);return job;
  }
  private refreshAfterCommand(pending:PendingOperation,result:unknown):void{
    const payload=record(record(result).result??result),projections:[string,string,string][]=pending.path==='/api/creator/commands'?[['/api/creator/bootstrap','profiles','profile']]:pending.path==='/api/easel/commands'?[['/api/easel/plans','items','plan']]:pending.path==='/api/platform-accounts'?[['/api/platform-accounts','sessions','session']]:pending.path==='/api/collection/sources'?[['/api/collection/sources','sources','source']]:pending.path==='/api/studio/commands'?['publication','metric','comment','analysis','proposal'].map(key=>['/api/studio/bootstrap',key==='analysis'?'analyses':key+'s',key]):pending.path==='/api/distribution/commands'?['connection','revision','approval','delivery'].map(key=>['/api/distribution/bootstrap',key+'s',key]):[];
    for(const [path,field,key] of projections){const item=record(payload[key]);if(string(item.id))this.updateResource<JsonRecord>(path,previous=>{const rows=array<JsonRecord>(previous[field]),old=rows.find(row=>row.id===item.id);return {...previous,[field]:old?rows.map(row=>row.id===item.id&&Number(row.revision??0)<Number(item.revision??0)?{...row,...item}:row):[...rows,item]}})}
    if(pending.path==='/api/collection/sources'&&payload.deleted===true&&string(payload.id))this.updateResource<JsonRecord>('/api/collection/sources',previous=>({...previous,sources:array<JsonRecord>(previous.sources).filter(row=>row.id!==payload.id)}));
    if(pending.scope==='settings'&&typeof window!=='undefined')window.dispatchEvent(new Event('workbench:settings-changed'));
    void this.invalidate(mutationTags(pending.path,pending.body,result)).catch(()=>{/* A refresh failure cannot turn an acknowledged command into an unknown write. */});
  }
  async retry<T=JsonRecord>(scope:string):Promise<T>{const result=await this.reconcile<T>(scope);if(result===null)throw new RequestError('操作结果暂不可用，输入已保留。',{uncertain:true});return result}
  private async execute<T>(pending:PendingOperation,body=pending.body,raw?:FormData):Promise<T>{
    const state=this.operation(pending.scope);if(state.getState().busy)throw new RequestError('这项操作正在处理。');state.setState({busy:true,error:'',feedback:undefined,notice:''});
    const csrf=this.session.getState().config?.csrf;if(!csrf){state.setState({busy:false});throw new RequestError('请等待登录校验完成。')}
    const authEpoch=this.authEpoch;
    try{this.usage.command(pending.path,pending.body,'attempt',pending.id);const result=await this.api.request<T>(pending.path,{body,csrf,id:pending.id,method:pending.method,raw});if(authEpoch!==this.authEpoch)throw new RequestError('登录状态已变化，原输入已保留。',{uncertain:true});this.clearPending(pending);this.usage.command(pending.path,pending.body,'accepted',pending.id);state.setState({pending:null,notice:'已保存',result});this.refreshAfterCommand(pending,result);return result}
    catch(error){if(authEpoch!==this.authEpoch){state.setState({error:'登录状态已变化，请重新登录。原输入已保留。'});throw error}this.usage.command(pending.path,pending.body,error instanceof RequestError&&!!error.status&&error.status>=400&&error.status<500&&!error.uncertain?'failed':'uncertain',pending.id);const definite=error instanceof RequestError&&!!error.status&&error.status>=400&&error.status<500&&!error.uncertain;if(definite){this.clearPending(pending);state.setState({pending:null,error:message(error)});throw error}const next={...pending,uncertain:true};this.drafts.set('native:pending:'+pending.scope,{operation:next});state.setState({pending:next});const recovered=await this.reconcile<T>(pending.scope);if(recovered!==null)return recovered;state.setState({error:'',feedback:interactionFeedback(new RequestError('正在恢复状态',{uncertain:true}))});throw new RequestError('连接暂时中断，正在恢复状态。原输入已保留。',{uncertain:true,operationScope:pending.scope,operationId:pending.id})}
    finally{state.setState({busy:false});if(state.getState().pending)this.scheduleReceiptRecovery(pending.scope)}
  }
  studio(action:StudioAction,fields:JsonRecord={}):Promise<JsonRecord>{return this.mutate(commandScope('studio',action,fields),'/api/studio/commands',{...fields,action}).then(response=>record(response.result??response))}
}

const encode=encodeURIComponent;
export type CreationIntent='produce'|'research'|'text'|'draft'|'discuss';
/** Existing backend wire contracts, shared by both platform presentations. */
export class DomainService {
  constructor(private client:WorkbenchClient){}
  login(code:string,next='/toolbox'):Promise<string>{this.client.beginAuthentication();return this.client.auth.login(code,next)}
  async logout(allSessions=false):Promise<string>{const csrf=this.csrf;this.client.expireSession();const epoch=this.client.authenticationEpoch,url=await this.client.auth.logout(csrf,allSessions);if(epoch!==this.client.authenticationEpoch)throw new RequestError('登录状态已变化，原退出回执不覆盖当前登录。');return url}
  private get csrf():string{return this.client.session.getState().config?.csrf??''}
  private mutate<T=JsonRecord>(scope:string,path:string,input:JsonRecord):Promise<T>{return this.client.mutate<T>(scope,path,input)}
  async createWork(scope:string,input:JsonRecord,intent:CreationIntent='produce'):Promise<JsonRecord>{const files=array<DraftAttachment>(input.files),uploaded=await uploadFiles(files,this.client.api,this.csrf,this.client.activities);const path=intent==='text'?'/api/text-works':intent==='research'?'/api/topic-research':intent==='produce'?'/api/works':'/api/drafts';return this.mutate(scope,path,{revision:0,...input,...(input.pendingId&&!input.id?{id:input.pendingId}:{}),...(intent==='text'?{body:input.body??input.material}:{}),files:uploaded.map(file=>file.id)})}
  workAction(workId:string,input:JsonRecord):Promise<JsonRecord>{return this.withFiles(this.originalId(input,'feedback:'+workId+':'+string(input.candidate_id))).then(value=>this.mutate('work:'+workId+':'+string(input.kind),'/api/works/'+encode(workId)+'/actions',value))}
  saveText(workId:string,input:JsonRecord):Promise<JsonRecord>{return this.mutate('text:'+workId,'/api/works/'+encode(workId)+'/text',this.originalId(input,'text-edit:'+workId+':'+string(input.candidate_id)))}
  discuss(workId:string,input:JsonRecord):Promise<JsonRecord>{return this.withFiles(this.originalId(input,'discussion:'+workId+':'+(string(input.candidate_id)||'draft'))).then(value=>this.mutate('discuss:'+workId,'/api/works/'+encode(workId)+'/discussions',value))}
  saveAnnotation(workId:string,versionId:string,input:JsonRecord):Promise<JsonRecord>{return this.mutate('annotation:'+workId+':'+versionId,'/api/works/'+encode(workId)+'/versions/'+encode(versionId)+'/review',this.originalId(input,'review:'+workId+':'+versionId))}
  learningBootstrap():Promise<LearningBootstrap>{return this.client.api.get('/api/learning/bootstrap')}
  learningDetail(kind:LearningKind,id:string):Promise<LearningDetail>{return this.client.api.get('/api/learning/'+kind+'/'+encode(id))}
  learningCommand(action:string,input:JsonRecord={}):Promise<JsonRecord>{return this.mutate(commandScope('learning',action,input),'/api/learning/commands',{...input,action})}
  creativeCommand(action:string,input:JsonRecord={}):Promise<JsonRecord>{return this.mutate(commandScope('creative',action,input),'/api/creative/commands',{...input,action})}
  creatorCommand(action:string,input:JsonRecord={}):Promise<JsonRecord>{return this.mutate(commandScope('creator',action,input),'/api/creator/commands',{...input,action})}
  async prepareProduction(kind:'create'|'change'|'finalize',input:JsonRecord,workId=''):Promise<JsonRecord>{
    const files=await this.uploadFiles(array<DraftAttachment>(input.files)),body={...input,id:crypto.randomUUID(),...(kind==='create'?{revision:0}:{}),...(kind!=='finalize'?{files:files.map(f=>f.id)}:{})};
    const preview=await this.client.api.query<JsonRecord>('/api/creative/preview',{kind,work_id:workId,input:body},this.csrf);
    return {...record(preview.context),production_input:preview.input,execution_prompt:preview.execution_prompt};
  }
  stylePreset(input:JsonRecord):Promise<JsonRecord>{return this.mutate('style-preset','/api/style-presets',input)}
  context(workId='',creative?:CreativeOptions,candidateId='',requestText=''):Promise<JsonRecord>{return creative?this.client.api.query('/api/studio/context',{id:crypto.randomUUID(),work_id:workId,creative,...(candidateId?{candidate_id:candidateId}:{}),...(requestText?{request_text:requestText}:{})},this.csrf):this.client.api.get('/api/studio/context?'+new URLSearchParams({work_id:workId,...(candidateId?{candidate_id:candidateId}:{})}))}
  bindProject(workId:string,input:JsonRecord):Promise<JsonRecord>{return this.mutate('project-binding:'+workId,'/api/works/'+encode(workId)+'/project-binding',input)}
  workLocalRetry(workId:string,taskId:string):Promise<JsonRecord>{return this.mutate('local-retry:'+workId+':'+taskId,'/api/works/'+encode(workId)+'/local-operations/retry',{task_id:taskId})}
  manualReview(workId:string,versionId:string):Promise<JsonRecord>{return this.mutate('manual-review:'+workId+':'+versionId,'/api/works/'+encode(workId)+'/versions/'+encode(versionId)+'/manual-review',{})}
  saveDraft(workId:string,input:JsonRecord):Promise<JsonRecord>{return this.withFiles(input).then(value=>this.mutate('draft:'+workId,'/api/works/'+encode(workId)+'/draft',value))}
  finalize(workId:string,input:JsonRecord):Promise<JsonRecord>{return this.mutate('finalize:'+workId,'/api/works/'+encode(workId)+'/finalize',input)}
  retryTask(jobId:string,expected_retry_revision:number):Promise<JsonRecord>{return this.mutate('retry-task:'+jobId,'/api/tasks/'+encode(jobId)+'/retry',{operation_id:crypto.randomUUID(),expected_retry_revision})}
  completionPreview(workId:string,versionId:string,scope:string[],completion:CompletionPlan):Promise<CompletionPreview>{return this.client.api.query<CompletionPreview>(completionPreviewPath(workId,versionId),{scope,completion},this.csrf)}
  saveCompletionDefaults(completion:CompletionPlan,expected_revision:number):Promise<JsonRecord>{return this.mutate('completion-defaults','/api/completion/defaults',{operation_id:crypto.randomUUID(),expected_revision,completion})}
  retryCompletionArchive(workId:string,decisionId:string,plan_hash:string):Promise<JsonRecord>{return this.mutate('completion-archive:'+workId+':'+decisionId,'/api/works/'+encode(workId)+'/completion/'+encode(decisionId)+'/retry-archive',{operation_id:crypto.randomUUID(),plan_hash})}
  collectAll():Promise<CollectionRun>{return this.mutate('collection:start','/api/collection/runs',{scope:'all_enabled'})}
  retryCollection(runId:string):Promise<CollectionRun>{return this.mutate('collection:retry:'+runId,'/api/collection/runs/'+encode(runId)+'/retry',{})}
  markNewsRead(articleId:string):Promise<JsonRecord>{return this.mutate('news-read:'+articleId,'/api/news/read',{article_id:articleId})}
  newsFeedback(articleId:string,text:string,id?:string):Promise<JsonRecord>{return this.mutate('news-feedback:'+articleId,'/api/news/feedback',{article_id:articleId,text,...(id?{id}:{})})}
  notificationRead(eventId:string|number):Promise<JsonRecord>{return this.mutate('notifications:'+eventId,'/api/notifications/read',{event_id:eventId})}
  device(input:JsonRecord):Promise<JsonRecord>{return this.mutate('device:'+string(input.action)+':'+string(input.id),'/api/mobile/devices',input)}
  async attach(files:Iterable<File>,existing:DraftAttachment[]=[]):Promise<DraftAttachment[]>{return attachFiles(files,existing,this.client.activities)}
  async upload(file:File|DraftAttachment):Promise<Artifact>{if(file instanceof File){const attachments=await this.attach([file]);return(await this.uploadFiles(attachments))[0]!}return(await this.uploadFiles([file]))[0]!}
  uploadFiles(files:(DraftAttachment|string)[]):Promise<Artifact[]>{return uploadFiles(files,this.client.api,this.csrf,this.client.activities)}
  async draftFile(id:string):Promise<Blob|undefined>{return(await draftFile(id))?.blob}
  retry(scope:string):Promise<JsonRecord>{return this.client.retry(scope)}
  studio(action:StudioAction,fields:JsonRecord={}):Promise<JsonRecord>{return this.client.studio(action,fields)}
  private originalId(input:JsonRecord,key:string):JsonRecord{if(input.id)return input;const old=this.client.drafts.get(key),pending=record(old?.pending??old?.request);const id=string(input.pendingId)||string(pending.id);return id?{...input,id}:input}
  private async withFiles(input:JsonRecord):Promise<JsonRecord>{if(!Array.isArray(input.files))return input;if(input.files.every(value=>typeof value==='string'))return input;const files=await this.uploadFiles(array<DraftAttachment>(input.files));return {...input,files:files.map(file=>file.id)}}
}
export const createWorkbenchClient=(options:ClientOptions={})=>new WorkbenchClient(options);
