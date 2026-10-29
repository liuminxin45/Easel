/** Fixed, read-only identity lookup for the pinned WeChat adapter.
 * No generic extension RPC, caller-selected provider or write action is exposed.
 * The extension's public compatibility API omits userId from getAccounts.
 */
import type {ExtensionAccountObservation} from './extension-discovery';

export interface WechatIdentityHost {
 origin:string;source:unknown;
 checkWechat?:(callback:(value:unknown)=>void)=>void;
 addMessageListener:(callback:(event:IdentityMessage)=>void)=>void;
 removeMessageListener:(callback:(event:IdentityMessage)=>void)=>void;
 postMessage:(message:string,targetOrigin:string)=>void;
}
interface IdentityMessage {source:unknown;origin:string;data:unknown}
export interface WechatIdentity {userId:string;username:string}
export type WechatIdentityStatus='resolved'|'not_provided'|'timeout'|'unavailable'|'unconfirmed';
const own=(value:object,key:string):unknown=>Object.getOwnPropertyDescriptor(value,key)?.value;
function safeText(value:unknown):string{
 if(typeof value!=='string'||value.length>200||/[\u0000-\u001f\u007f-\u009f\u202a-\u202e\u2066-\u2069<>]/.test(value)||/[A-Za-z][A-Za-z0-9+.-]*:\/\//.test(value))return '';
 return value.trim();
}
export function parseWechatIdentity(value:unknown):WechatIdentity|null{
 try{
  if(!value||typeof value!=='object'||Array.isArray(value))return null;
  const auth=own(value,'result');if(!auth||typeof auth!=='object'||Array.isArray(auth)||own(auth,'isAuthenticated')!==true)return null;
  const userId=safeText(own(auth,'userId')),username=safeText(own(auth,'username'));
  return userId||username?{userId,username}:null;
 }catch{return null}
}
function identityResponseStatus(value:unknown,identity:WechatIdentity|null):WechatIdentityStatus{
 if(identity)return 'resolved';
 try{if(value&&typeof value==='object'){const result=own(value,'result');if(result&&typeof result==='object'){if(own(result,'isAuthenticated')===true)return 'not_provided';if(own(result,'isAuthenticated')===false)return 'unconfirmed'}}}catch{/* Discard malformed metadata. */}
 return 'unavailable';
}
export function readWechatIdentity(host:WechatIdentityHost,options:{signal?:AbortSignal;timeoutMs?:number;nonce?:string;onStatus?:(status:WechatIdentityStatus)=>void}={}):Promise<WechatIdentity|null>{
 return new Promise(resolve=>{
  const nonce=options.nonce||crypto.randomUUID(),timeoutMs=Math.min(options.timeoutMs??20000,20000);
  let settled=false,timer:ReturnType<typeof setTimeout>|undefined;
  const finish=(value:WechatIdentity|null,status:WechatIdentityStatus)=>{if(settled)return;settled=true;if(timer)clearTimeout(timer);host.removeMessageListener(message);options.signal?.removeEventListener('abort',abort);try{options.onStatus?.(status)}catch{/* An observer cannot change the read contract. */}resolve(value)};
  const received=(value:unknown)=>{const identity=parseWechatIdentity(value);finish(identity,identityResponseStatus(value,identity))};
  const abort=()=>finish(null,'unavailable');
  const message=(event:IdentityMessage)=>{
   if(event.source!==host.source||event.origin!==host.origin||typeof event.data!=='string'||event.data.length>64000)return;
   try{
    const envelope:unknown=JSON.parse(event.data);
    if(!envelope||typeof envelope!=='object'||Array.isArray(envelope)||own(envelope,'eventID')!==nonce||own(envelope,'callReturn')!==true)return;
    const method=own(envelope,'method');if(method!==undefined&&method!=='magicCall')return;
    received(own(envelope,'result'));
   }catch{/* Ignore unrelated or malformed page messages. */}
  };
  if(options.signal?.aborted){finish(null,'unavailable');return}
  options.signal?.addEventListener('abort',abort,{once:true});timer=setTimeout(()=>finish(null,'timeout'),Math.max(1,timeoutMs));
  try{
   if(host.checkWechat)host.checkWechat(received);
   else{
    host.addMessageListener(message);
    // Literal method/provider only. A result nonce confers no business authority.
    host.postMessage(JSON.stringify({method:'magicCall',methodName:'checkAuth',data:{methodName:'checkAuth',account:{type:'weixin'}},eventID:nonce}),host.origin);
   }
  }catch{finish(null,'unavailable')}
 });
}
export function applyWechatIdentity(accounts:ExtensionAccountObservation[],identity:WechatIdentity|null,status?:WechatIdentityStatus):ExtensionAccountObservation[]{
 if(!identity&&!status)return accounts;
 return accounts.map(account=>{
  if(account.type!=='weixin')return account;
  const observed=status?{...account,identity_status:status}:account;
  if(!identity)return observed;
  if(identity.userId)return {...observed,uid:identity.userId,identity_kind:'provider_user_id',...(identity.username?{account_name:identity.username}:{})};
  // Do not erase a previously obtained identifier with an empty supplement.
  return account.uid?observed:{...observed,uid:identity.username,identity_kind:'reported_username'};
 });
}
export async function supplementWechatIdentity(accounts:ExtensionAccountObservation[],options:{signal?:AbortSignal}={}):Promise<ExtensionAccountObservation[]>{
 if(options.signal?.aborted||!accounts.some(account=>account.type==='weixin'))return accounts;
 const win=window as Window&{$syncer?:{magicCall?:(input:{methodName:'checkAuth';account:{type:'weixin'}},callback:(value:unknown)=>void)=>void}},sdk=win.$syncer;
 let status:WechatIdentityStatus|undefined;
 const identity=await readWechatIdentity({origin:win.location.origin,source:win,
  checkWechat:typeof sdk?.magicCall==='function'?callback=>sdk.magicCall!.call(sdk,{methodName:'checkAuth',account:{type:'weixin'}},callback):undefined,
  addMessageListener:callback=>win.addEventListener('message',callback as (event:MessageEvent)=>void),
  removeMessageListener:callback=>win.removeEventListener('message',callback as (event:MessageEvent)=>void),
  postMessage:(message,origin)=>win.postMessage(message,origin)},{...options,onStatus:value=>{status=value}});
 return options.signal?.aborted?accounts:applyWechatIdentity(accounts,identity,status);
}
