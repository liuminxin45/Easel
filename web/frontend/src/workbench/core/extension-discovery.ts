import platformCatalog from './distribution-platforms.json';
import {distributionCapability,distributionCapabilityReason,type DistributionConnection} from './distribution';
/** Read-only discovery through the installed extension's public getAccounts API.
 * Browser observations are untrusted hints, never server capability evidence. */
export type ExtensionIdentityKind='provider_user_id'|'reported_username';
export type ExtensionIdentityStatus='resolved'|'not_provided'|'timeout'|'unavailable'|'unconfirmed';
export interface ExtensionAccountObservation {type:string;title:string;displayName:string;uid:string;account_name?:string;identity_kind?:ExtensionIdentityKind;identity_status?:ExtensionIdentityStatus}
export type ExtensionImportPlatform='wechat_article'|'juejin_article'|'xiaohongshu_note'|'zhihu_article'|'csdn_article'|'cnblogs_article';
export interface ExtensionDiscoveryResult {accounts:ExtensionAccountObservation[];transport:'syncer_api'|'public_message';observed_at:string;trust:'browser_observed'}
export interface ExtensionDiscoveryProps {onImported?:()=>void;onObserved?:(accounts:ExtensionAccountObservation[])=>void;connections?:DistributionConnection[];onManage?:(connectionId:string)=>void}
export interface ComputerExtensionObservation {accounts:ExtensionAccountObservation[];checked_at:string;source:'saved_observation'|'computer_bridge'|'computer_check'}
export interface ReadOnlyAccountCheck {check_id:string;id?:string;status:'pending'|'running'|'completed'|'failed'|'expired';phase:string;created_at:string;updated_at?:string;expires_at:string;completed_at?:string|null;observation?:unknown;code?:string;error?:string}
export interface AccountAutoCheckState {
 enabled:boolean;phase:string;current_check_id:string|null;current_check:ReadOnlyAccountCheck|null;
 last_check_id?:string|null;last_success_at:string|null;last_success_observation:unknown;
 next_check_at:string|null;next_retry_at:string|null;retry_count:number;server_now:string;
 retry_allowed:boolean;error_code?:string|null;last_error?:{code:string;message:string;at:string}|null;
 worker?:{online?:boolean;state?:string};runtime?:Record<string,unknown>;
}
export function accountAutoCheckMessage(state:AccountAutoCheckState|null):string{
 if(!state)return '正在读取自动检测状态…';
 if(!state.enabled)return '自动检测已暂停';
 return ({scheduled:'等待后台开始检测',launch_requested:'正在连接电脑检测页',page_ready:'电脑检测页已连接',extension_started:'正在读取同步助手账号',launch_uncertain:'等待电脑检测页响应',recovering:'正在恢复自动检测',waiting_next:'最近一次检测已完成',retry_wait:'本次检测未完成，将自动重试',disabled:'自动检测已暂停'} as Record<string,string>)[state.phase]||'正在核对自动检测状态';
}
export function accountAutoCheckCountdown(state:AccountAutoCheckState|null,serverNow:number):string{
 if(!state?.enabled)return '';
 const retry=!!state.next_retry_at,target=state.next_retry_at||state.next_check_at;
 if(!target||!['retry_wait','recovering','waiting_next'].includes(state.phase))return '';
 const remaining=Math.max(0,Math.ceil((Date.parse(target)-serverNow)/1000));if(!Number.isFinite(remaining))return '';
 if(!remaining)return retry?'等待后台自动重试':'等待后台开始下次检测';
 const time=remaining>=60?Math.floor(remaining/60)+'分'+String(remaining%60).padStart(2,'0')+'秒':remaining+'秒';
 return retry?time+'后自动重试':time+'后再次检测';
}
export function accountAutoCheckError(state:AccountAutoCheckState|null):string{
 if(!state?.last_error||!['retry_wait','recovering','launch_uncertain'].includes(state.phase))return '';
 const code=state.last_error.code;
 return ({extension_timeout:'同步助手尚未返回结果',extension_failed:'本次未能读取同步助手',extension_unavailable:'同步助手暂不可用',launch_failed:'电脑检测页暂未连接',launch_uncertain:'尚未确认电脑检测页响应',network_error:'本次检测连接中断',expired:'本次检测已过期',page_failed:'电脑检测页暂不可用'} as Record<string,string>)[code]||'本次检测尚未完成，保留最近成功结果';
}
export {useAccountAutoCheck,accountAutoCheckScopes} from './auto-check';
export type ReadOnlyCheckEvent='page_ready'|'extension_started'|'result'|'extension_timeout'|'failed';
export function accountCheckId(value:unknown):string{if(!value||typeof value!=='object'||Array.isArray(value))return '';const id=cleanText(own(value,'check_id')||own(value,'id'),160);return /^[A-Za-z0-9_-]{1,160}$/.test(id)?id:''}
export function accountCheckMessage(value:Pick<ReadOnlyAccountCheck,'phase'|'status'>):string{if(value.status==='completed')return '本次电脑检测已完成';return ({launch_requested:'已请求电脑检测，等待检测页响应',page_ready:'电脑检测页已连接',checking_extension:'电脑正在读取同步助手账号',extension_started:'电脑正在读取同步助手账号',result_received:'已收到本次电脑检测结果',extension_timeout:'同步助手未在限定时间内返回账号结果',launch_failed:'电脑检测页未能启动',failed:'本次电脑检测未完成',expired:'本次检测已过期，请重新发起'} as Record<string,string>)[value.phase]||'正在核对本次电脑检测状态'}
export function parseReadOnlyCheckFragment(fragment:string):{check_id:string;ticket:string}|null{if(!fragment.startsWith('#')||fragment.length>600)return null;const params=new URLSearchParams(fragment.slice(1));if([...params.keys()].some(key=>!['check','ticket'].includes(key))||params.getAll('check').length!==1||params.getAll('ticket').length!==1)return null;const check_id=params.get('check')||'',ticket=params.get('ticket')||'';return /^[A-Za-z0-9_-]{1,160}$/.test(check_id)&&/^[A-Za-z0-9_-]{43}$/.test(ticket)?{check_id,ticket}:null}
export interface ExtensionReadHost {
  origin:string;source:unknown;
  getAccounts?: (callback:(rows:unknown)=>void)=>void;
  addMessageListener:(listener:(event:ExtensionMessageEvent)=>void)=>void;
  removeMessageListener:(listener:(event:ExtensionMessageEvent)=>void)=>void;
  postMessage:(message:string,targetOrigin:string)=>void;
}
export interface ExtensionMessageEvent {source:unknown;origin:string;data:unknown}
const providers:Record<string,{name:string;default_platform:string|null;identity_note?:string}>=platformCatalog.providers;
const cleanText=(value:unknown,max=200):string=>typeof value==='string'?value.replace(/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069]/g,'').trim().slice(0,max):'';
function own(value:object,key:string):unknown{return Object.getOwnPropertyDescriptor(value,key)?.value}
export function sanitizeExtensionAccounts(value:unknown):ExtensionAccountObservation[]{
  if(!Array.isArray(value))throw Error('扩展未返回可识别的账号列表，请重新检查');
  const rows:ExtensionAccountObservation[]=[],seen=new Set<string>();
  for(const raw of value.slice(0,100)){
    if(!raw||typeof raw!=='object'||Array.isArray(raw))continue;
    try{
      const type=cleanText(own(raw,'type'),80).toLowerCase();if(!type||type==='zip-download')continue;
      const account:ExtensionAccountObservation={type,title:cleanText(own(raw,'title')),displayName:cleanText(own(raw,'displayName')),uid:cleanText(own(raw,'uid'))};
      const name=cleanText(own(raw,'account_name')),kind=own(raw,'identity_kind');
      if(name)account.account_name=name;
      if(kind==='provider_user_id'||kind==='reported_username')account.identity_kind=kind;
      const status=own(raw,'identity_status');
      if(status==='resolved'||status==='not_provided'||status==='timeout'||status==='unavailable'||status==='unconfirmed')account.identity_status=status;
      const identity=JSON.stringify([account.type,account.uid,account.uid?'':account.title,account.uid?'':account.displayName]);
      if(!seen.has(identity)){seen.add(identity);rows.push(account)}
    }catch{/* A page-supplied getter/proxy is not account metadata. */}
  }
  return rows;
}
export function extensionImportPlatform(account:ExtensionAccountObservation):ExtensionImportPlatform|null{return (Object.hasOwn(providers,account.type)?providers[account.type]?.default_platform:null) as ExtensionImportPlatform|null}
export function extensionPlatformName(account:ExtensionAccountObservation):string{return (Object.hasOwn(providers,account.type)?providers[account.type]?.name:'')||account.displayName||account.type}
export function extensionAccountIssue(account:ExtensionAccountObservation):string{
 if(!account.uid){
  if(account.type==='weixin'){
   const reason=({timeout:'公众号身份补查超时，下轮会自动重试',not_provided:'同步助手未返回公众号ID或账号名',unavailable:'公众号身份补查暂不可用，下轮继续检测',unconfirmed:'公众号身份尚未核实，下轮继续检测'} as Partial<Record<ExtensionIdentityStatus,string>>)[account.identity_status||'resolved'];
   if(reason)return reason;
  }
  return providers[account.type]?.identity_note||'账号标识尚未取得，暂不能登记';
 }
 return !extensionImportPlatform(account)?'已识别平台登录，工作台暂未接入此平台':'';
}
export interface ExtensionAccountView {
 account:ExtensionAccountObservation;platform_name:string;account_label:string;identity_reason:string;
 registration:'missing_identity'|'unsupported'|'unregistered'|'registered';registration_label:string;
 connections:DistributionConnection[];draft_label:string;draft_reason:string;
}
/** Join exact provider + UID only. Names and browser login claims grant no ability. */
export function extensionAccountView(account:ExtensionAccountObservation,connections:DistributionConnection[]=[]):ExtensionAccountView{
 const platform=extensionImportPlatform(account),matches=account.uid?connections.filter(connection=>connection.account===account.uid&&platformCatalog.platforms.some(row=>row.id===connection.platform&&row.provider===account.type)):[];
 const registration=!account.uid?'missing_identity':matches.length?'registered':!platform?'unsupported':'unregistered';
 const declaration=platformCatalog.platforms.find(row=>row.id===platform),supported=declaration?.draft===true;
 let draft_label=supported?'待核验':'尚未接入',draft_reason=supported?'登记账号后检查连接与实际草稿能力':account.type==='xiaohongshu'?'小红书普通图文草稿尚未接入':platform?'此内容类型的草稿能力尚未接入':'此平台的草稿能力尚未接入';
 if(matches.length){
  const capabilities=matches.map(connection=>({connection,cap:distributionCapability(connection,'draft')}));
  const usable=capabilities.find(({connection,cap})=>connection.enabled&&cap.account===account.uid&&cap.status==='available'&&cap.verified===true);
  const trial=capabilities.find(({connection,cap})=>connection.enabled&&cap.account===account.uid&&cap.status==='trial'&&cap.code_verified===true&&cap.account_verified===true);
  const unknown=capabilities.find(({connection,cap})=>connection.enabled&&(cap.account!==account.uid||cap.status!=='unsupported'));
  const chosen=usable||trial||unknown||capabilities[0];
  if(chosen){draft_label=usable?'已验证可用':trial?'可申请试运行':unknown?'待核验':'尚未接入';draft_reason=distributionCapabilityReason(chosen.cap.reason,usable?'本账号草稿能力已核验':trial?'仅支持逐次明确授权的草稿试运行':unknown?'检查本账号连接后查看实际结果':'本账号当前内容类型尚不支持平台草稿')}
 }
 return {account,platform_name:extensionPlatformName(account),account_label:account.account_name||account.uid||'账号标识待识别',identity_reason:account.uid?'同步助手已返回账号标识':extensionAccountIssue(account),registration,registration_label:{missing_identity:'标识待识别',unsupported:'暂未接入',unregistered:'待登记',registered:'已登记'}[registration],connections:matches,draft_label,draft_reason};
}
/** Server account is the previously observed uid, never the platform/name fallback. */
export function computerExtensionObservation(value:unknown,source:'saved_observation'|'computer_bridge'|'computer_check'='saved_observation'):ComputerExtensionObservation|null{
  if(!value||typeof value!=='object'||Array.isArray(value))return null;
  if(source==='saved_observation'&&own(value,'source')!=='browser_extension')return null;
  if(source==='computer_check'&&!['browser_extension','browser_observed'].includes(String(own(value,'source'))))return null;
  const input=own(value,'accounts');if(!Array.isArray(input))return null;
  const mapped=input.slice(0,100).filter(row=>row&&typeof row==='object'&&!Array.isArray(row)&&own(row,source==='computer_bridge'?'authenticated':'reported_authenticated')===true).map(row=>({type:cleanText(own(row,'platform'),80),title:cleanText(own(row,'name')),displayName:cleanText(own(row,'name')),uid:cleanText(own(row,'account')),account_name:own(row,'account_name'),identity_kind:own(row,'identity_kind'),identity_status:own(row,'identity_status')}));
  return {accounts:sanitizeExtensionAccounts(mapped),checked_at:cleanText(own(value,'checked_at'),80),source};
}
/** Poll exactly one authenticated job. Global latest observations never complete it. */
export async function waitForAccountCheck(read:(signal:AbortSignal)=>Promise<unknown>,options:{signal?:AbortSignal;intervalMs?:number;durationMs?:number;checkId?:string;onUpdate?:(value:ReadOnlyAccountCheck)=>void}={}):Promise<ReadOnlyAccountCheck|null>{
 const controller=new AbortController(),duration=Math.min(options.durationMs??180000,180000),deadline=performance.now()+duration,stop=()=>controller.abort(),timer=setTimeout(stop,duration);options.signal?.addEventListener('abort',stop,{once:true});if(options.signal?.aborted)controller.abort();
 const pause=()=>new Promise<void>((resolve,reject)=>{const cancel=()=>{clearTimeout(handle);reject(Error('检查已取消'))},handle=setTimeout(()=>{controller.signal.removeEventListener('abort',cancel);resolve()},Math.min(options.intervalMs??2000,Math.max(1,deadline-performance.now())));controller.signal.addEventListener('abort',cancel,{once:true});if(controller.signal.aborted)cancel()});
 try{while(!controller.signal.aborted&&performance.now()<deadline){const raw=await read(controller.signal);if(raw&&typeof raw==='object'&&!Array.isArray(raw)){const nested=own(raw,'check'),value=(nested&&typeof nested==='object'?nested:raw) as ReadOnlyAccountCheck,id=accountCheckId(value);if(id){if(options.checkId&&id!==options.checkId)throw Error('返回的检测标识与本次请求不一致');options.onUpdate?.(value);if(['completed','failed','expired'].includes(value.status)||['result_received','extension_timeout','launch_failed','failed','expired'].includes(value.phase))return value}}await pause()}return null}
 catch(error){if(controller.signal.aborted)return null;throw error}
 finally{clearTimeout(timer);options.signal?.removeEventListener('abort',stop);controller.abort()}
}
/** A user-triggered, bounded wait for a newer computer observation. No background poll. */
export async function waitForComputerObservation(read:(signal:AbortSignal)=>Promise<unknown>,previousCheckedAt:string,options:{signal?:AbortSignal;intervalMs?:number;durationMs?:number}={}):Promise<ComputerExtensionObservation|null>{
 const controller=new AbortController(),duration=Math.min(options.durationMs??30000,30000),interval=options.intervalMs??2000,deadline=Date.now()+duration;
 const stop=()=>controller.abort(),deadlineTimer=setTimeout(stop,duration);options.signal?.addEventListener('abort',stop,{once:true});if(options.signal?.aborted)controller.abort();
 const pause=(ms:number)=>new Promise<void>((resolve,reject)=>{const cancel=()=>{clearTimeout(timer);reject(Error('检查已取消'))},timer=setTimeout(()=>{controller.signal.removeEventListener('abort',cancel);resolve()},ms);controller.signal.addEventListener('abort',cancel,{once:true});if(controller.signal.aborted)cancel()});
 try{while(!controller.signal.aborted&&Date.now()<deadline){await pause(Math.min(interval,Math.max(1,deadline-Date.now())));if(controller.signal.aborted||Date.now()>=deadline)break;const snapshot=await read(controller.signal);if(!snapshot||typeof snapshot!=='object'||Array.isArray(snapshot))continue;const next=computerExtensionObservation(own(snapshot,'observation'));if(next?.checked_at&&next.checked_at!==previousCheckedAt)return next}return null}
 catch(error){if(controller.signal.aborted)return null;throw error}
 finally{clearTimeout(deadlineTimer);options.signal?.removeEventListener('abort',stop);controller.abort()}
}
export function extensionImportInput(account:ExtensionAccountObservation):{operation_id:string;platform:ExtensionImportPlatform;account:string;label:string;source:'browser_extension'}{
  const issue=extensionAccountIssue(account),platform=extensionImportPlatform(account);if(issue||!platform)throw Error(issue||'此平台暂不支持自动接入');
  return {operation_id:crypto.randomUUID(),platform,account:account.uid,label:account.account_name||account.uid,source:'browser_extension'};
}
/** Official replies omit method, but are bound to the sole getAccounts request's nonce. */
export function matchExtensionAccountsMessage(event:ExtensionMessageEvent,host:Pick<ExtensionReadHost,'source'|'origin'>,nonce:string):{matched:boolean;accounts?:ExtensionAccountObservation[]}{
  if(event.source!==host.source||event.origin!==host.origin||typeof event.data!=='string'||event.data.length>256000)return {matched:false};
  let value:unknown;try{value=JSON.parse(event.data)}catch{return {matched:false}}
  if(!value||typeof value!=='object'||Array.isArray(value))return {matched:false};
  const row=value as Record<string,unknown>;
  if(row.eventID!==nonce||row.callReturn!==true||row.method!==undefined&&row.method!=='getAccounts')return {matched:false};
  return {matched:true,accounts:sanitizeExtensionAccounts(row.result)};
}
export function readExtensionAccounts(host:ExtensionReadHost,options:{signal?:AbortSignal;timeoutMs?:number;nonce?:string}={}):Promise<ExtensionDiscoveryResult>{
  return new Promise((resolve,reject)=>{
    const nonce=options.nonce||crypto.randomUUID(),transport=host.getAccounts?'syncer_api':'public_message',timeoutMs=options.timeoutMs??120000;
    let settled=false,timer:ReturnType<typeof setTimeout>|undefined;
    const cleanup=()=>{if(timer!==undefined)clearTimeout(timer);host.removeMessageListener(message);options.signal?.removeEventListener('abort',abort)};
    const fail=(error:unknown)=>{if(settled)return;settled=true;cleanup();reject(error instanceof Error?error:Error('读取扩展账号未完成'))};
    const done=(rows:unknown)=>{if(settled)return;try{const accounts=sanitizeExtensionAccounts(rows);settled=true;cleanup();resolve({accounts,transport,observed_at:new Date().toISOString(),trust:'browser_observed'})}catch(error){fail(error)}};
    const message=(event:ExtensionMessageEvent)=>{if(transport!=='public_message'||settled)return;try{const result=matchExtensionAccountsMessage(event,host,nonce);if(result.matched)done(result.accounts)}catch(error){fail(error)}};
    const abort=()=>{const error=Error('账号检查已取消');error.name='AbortError';fail(error)};
    if(options.signal?.aborted){abort();return}
    options.signal?.addEventListener('abort',abort,{once:true});
    timer=setTimeout(()=>{const error=Error('未在限定时间内收到同步助手的账号结果') as Error&{code:string};error.code='extension_timeout';fail(error)},timeoutMs);
    if(host.getAccounts){try{host.getAccounts(rows=>done(rows))}catch(error){fail(error)}}
    else{host.addMessageListener(message);try{host.postMessage(JSON.stringify({method:'getAccounts',eventID:nonce}),host.origin)}catch(error){fail(error)}}
  });
}
export async function discoverExtensionAccounts(options:{signal?:AbortSignal;timeoutMs?:number}={}):Promise<ExtensionDiscoveryResult>{
  const win=window as Window&{$syncer?:{getAccounts?:(callback:(rows:unknown)=>void)=>void}},syncer=win.$syncer;
  const result=await readExtensionAccounts({origin:win.location.origin,source:win,
    getAccounts:typeof syncer?.getAccounts==='function'?callback=>syncer.getAccounts!.call(syncer,callback):undefined,
    addMessageListener:listener=>win.addEventListener('message',listener as (event:MessageEvent)=>void),
    removeMessageListener:listener=>win.removeEventListener('message',listener as (event:MessageEvent)=>void),
    postMessage:(message,origin)=>win.postMessage(message,origin)},options);
  const {supplementWechatIdentity}=await import('./extension-identity');
  return {...result,accounts:await supplementWechatIdentity(result.accounts,options)};
}
