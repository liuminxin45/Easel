import {array,record,string,type JsonRecord} from './models';

export const RESOURCE_FRESH_MS=30_000;
export const DYNAMIC_FRESH_MS=3_000;
export const AUTH_CHECK_MS=30_000;
export const RESOURCE_CACHE_BYTES=16*1024*1024;
export const RESOURCE_CACHE_ENTRIES=128;
const active=new Set(['queued','dispatching','running','working','processing','sending','leased','retry_wait','uncertain','needs_desktop','checking','login']);
const url=(path:string)=>new URL(path,'https://workbench.invalid');

/** Only ordinary native page data may use the host's read snapshots. */
export function nativeResourceCacheable(path:string):boolean {
 const p=url(path).pathname;
 return p==='/api/outputs'||p.startsWith('/api/output/')||p==='/api/ideas'||p==='/api/trends'||p==='/api/trends/sources'
  ||p==='/api/personas'||/^\/api\/persona\/[^/]+(?:\/files)?$/.test(p)||p==='/api/schedule'||p==='/api/schedule/context';
}

export function resourceCacheable(path:string):boolean{return !/^\/api\/(?:config(?:\?|$)|operations\/|mobile\/|auth(?:\/|$)|distribution\/credentials(?:\/|\?|$))/.test(path)}
export function dynamicResource(path:string,data:unknown):boolean{
 const root=record(data),state=string(root.status)||string(root.state)||string(root.phase);
 if(record(root.session).pendingTurnId)return true;
 if(active.has(state)||array(root.pending).length||array(root.active_runs).length)return true;
 if(active.has(string(record(root.recovery).phase)))return true;
 if(array<JsonRecord>(record(root.tasks).processing).length)return true;
 if(active.has(string(record(record(root.batch_learning).latest_cycle).status)))return true;
 for(const key of ['works','items','deliveries','jobs','analyses','tasks','cycles','sessions'])for(const item of array<JsonRecord>(root[key])){
  if(item.current===false)continue;
  if(item.pendingTurnId||active.has(string(item.status))||active.has(string(item.state))||array(item.pending).length||active.has(string(record(item.recovery).phase)))return true;
  const archive=record(item.project_archive);
  if(active.has(string(archive.phase)))return true;
 }
 return /^\/api\/tasks\//.test(path)&&data===null;
}
export const resourceFreshMs=(path:string,data:unknown):number=>resourceCacheable(path)?dynamicResource(path,data)?url(path).pathname==='/api/platform-accounts'?1500:DYNAMIC_FRESH_MS:url(path).pathname==='/api/learning/bootstrap'?15_000:RESOURCE_FRESH_MS:0;
export function resourceTags(path:string):string[]{
 const target=url(path),p=target.pathname,work=p.match(/^\/api\/works\/([^/]+)/)?.[1];
 if(p==='/api/outputs'||p.startsWith('/api/output/'))return ['outputs','works'];
 if(p==='/api/ideas')return ['ideas'];
 if(p==='/api/trends/sources'||p==='/api/trends/manage')return ['trend-sources','collection'];
 if(p==='/api/trends')return ['trends','news','collection'];
 if(p==='/api/personas'||p.startsWith('/api/persona/'))return ['creator','foundation'];
 if(p==='/api/schedule'||p.startsWith('/api/schedule/'))return ['schedule'];
 if(p.startsWith('/api/chat/'))return ['chat'];
 if(p==='/api/skills'||p.startsWith('/api/skill/'))return ['native-skills'];
 if(p.startsWith('/api/easel/'))return ['easel-plans'];
 if(p.startsWith('/api/platform-accounts'))return ['platform-accounts'];
 if(p.startsWith('/api/creator/'))return ['creator'];
 if(p.startsWith('/api/media/'))return ['media'];
 if(p.startsWith('/api/learning/'))return ['learning','foundation'];
 if(p.startsWith('/api/creative/'))return ['creative','learning','foundation','works','publications','metrics','comments'];
 if(work)return ['work:'+work,...(p.endsWith('/completion-options')?['completion-defaults','foundation','distribution']:[])];
 if(p==='/api/works'||p==='/api/history')return ['works'];
 if(p==='/api/studio/bootstrap')return ['studio','works','publications','metrics','comments','foundation','distribution','collection'];
 if(p==='/api/studio/context')return ['foundation',...(target.searchParams.get('work_id')?['work:'+target.searchParams.get('work_id')]:[])];
 if(p==='/api/studio/foundation'||p==='/api/style-presets')return ['foundation'];
 if(p==='/api/news'||p.startsWith('/api/periodicals/'))return ['news'];
 if(p.startsWith('/api/news/'))return ['news:'+p.slice('/api/news/'.length)];
 if(p.startsWith('/api/distribution/'))return ['distribution'];
 if(p.startsWith('/api/collection/'))return ['collection'];
 if(p.startsWith('/api/notifications'))return ['notifications'];
 return [p];
}

/** null means unknown mutation and requires conservative global invalidation. */
export function mutationTags(path:string,input:JsonRecord,result:unknown):string[]|null{
 const nativePath=url(path).pathname;
 if(nativePath==='/api/trends/manage')return ['trend-sources','trends','collection','news'];
 if(nativePath==='/api/ideas'||nativePath.startsWith('/api/ideas/'))return ['ideas'];
 if(nativePath==='/api/schedule'||nativePath.startsWith('/api/schedule/'))return ['schedule','studio'];
 if(nativePath.startsWith('/api/output/'))return ['outputs','works'];
 if(nativePath.startsWith('/api/persona/')||nativePath==='/api/profile/build')return ['creator','foundation'];
 if(nativePath.startsWith('/api/easel/'))return ['easel-plans'];
 if(nativePath==='/api/env'||nativePath.startsWith('/api/settings/')||nativePath.startsWith('/api/env/'))return ['settings','native-skills'];
 if(nativePath.startsWith('/api/login/')||nativePath.startsWith('/api/logout/')||nativePath.startsWith('/api/accounts/'))return ['accounts','platform-accounts','distribution','creator'];
 if(nativePath==='/api/chat'||nativePath==='/api/skill')return ['chat','outputs','works'];
 if(nativePath==='/api/upload'||nativePath==='/api/upload/local'||/^\/api\/manual-publish\/[^/]+\/export$/.test(nativePath))return ['outputs'];
 if(nativePath.startsWith('/api/publish/'))return ['publications','distribution','works','studio','outputs'];
 if(new URL(path,'https://workbench.invalid').pathname.startsWith('/api/chat/'))return ['chat'];
 if(new URL(path,'https://workbench.invalid').pathname.startsWith('/api/platform-accounts'))return ['platform-accounts','distribution','creator'];
 if(new URL(path,'https://workbench.invalid').pathname.startsWith('/api/creator/'))return ['creator','creative','foundation','learning'];
 if(new URL(path,'https://workbench.invalid').pathname.startsWith('/api/creative/'))return ['creative','learning','foundation',...(input.work_id?['work:'+string(input.work_id)]:[])];
 if(new URL(path,'https://workbench.invalid').pathname.startsWith('/api/learning/'))return ['learning','foundation','studio'];
 if(new URL(path,'https://workbench.invalid').pathname.startsWith('/api/media/'))return ['media','works','studio','distribution','creator',...(input.work_id?['work:'+string(input.work_id)]:[])];
 const response=record(result),payload=record(response.result??response),provided=record(response.cache_invalidation??payload.cache_invalidation);
 if(Array.isArray(provided.tags)&&provided.tags.length<=100&&provided.tags.every(tag=>typeof tag==='string'&&tag.length>0&&tag.length<=200))return [...new Set(provided.tags as string[])];
 const p=url(path).pathname;
 if(p==='/api/news/read'&&(response.changed===false||payload.changed===false))return [];
 if(p.startsWith('/api/news/'))return ['news',...(input.article_id?['news:'+string(input.article_id)]:[])];
 if(p.startsWith('/api/notifications/'))return ['notifications'];
 if(p.startsWith('/api/collection/'))return ['collection','news','studio'];
 if(p==='/api/completion/defaults')return ['completion-defaults'];
 if(p.startsWith('/api/distribution/'))return p==='/api/distribution/commands'&&!string(input.action).startsWith('connection-')?['distribution','publications','studio']:['distribution'];
 const proposal=record(payload.proposal);
 const work=p.match(/^\/api\/works\/([^/]+)/)?.[1]||string(payload.work_id)||string(record(payload.job).work_id)||string(input.work_id)||(proposal.scope==='work'?string(proposal.target_id):'');
 const workTags=['works','studio',...(work?['work:'+work]:[]),...(input.article_id?['news','news:'+string(input.article_id)]:[])];
 if(p.startsWith('/api/works/')||p==='/api/works'||p==='/api/text-works'||p==='/api/drafts'||p==='/api/article-drafts'||p.startsWith('/api/tasks/')||p==='/api/topic-research')return [...workTags,...(/\/actions$/.test(p)&&['accept','reject'].includes(string(input.kind))?['publications','distribution']:[])];
 if(p==='/api/style-presets')return ['foundation','studio'];
 if(p==='/api/studio/commands'){
  const action=string(input.action);
  if(/^(foundation|config|configuration|preset|workflow|context)-/.test(action)||action==='work-context')return ['foundation','studio',...(work?['work:'+work]:[])];
  if(action.startsWith('publication-'))return ['publications','studio','distribution'];
  if(action.startsWith('metric-'))return ['metrics','publications','studio'];
  if(action.startsWith('comment-'))return ['comments','publications','studio'];
  if(action==='review-complete')return ['publications','studio'];
  if(action.startsWith('analysis-')||action.startsWith('proposal-')||action.startsWith('queue-'))return [...workTags,'publications','foundation'];
 }
 return null;
}

export function withServerTime<T>(value:T,serverTime?:string):T{
 if(!serverTime||Number.isNaN(Date.parse(serverTime)))return value;
 const visit=(item:unknown):unknown=>{
  if(Array.isArray(item)){let changed=false;const next=item.map(child=>{const result=visit(child);changed||=result!==child;return result});return changed?next:item}
  if(item===null||typeof item!=='object')return item;
  const source=item as JsonRecord;let next:JsonRecord|undefined;
  for(const [key,child] of Object.entries(source)){
   const recovery=record(child);
   const result=key==='recovery'&&typeof recovery.job_id==='string'&&typeof recovery.failure_kind==='string'&&typeof recovery.max_auto_retries==='number'&&typeof recovery.server_now==='string'?{...recovery,server_now:serverTime}:visit(child);
   if(result!==child){next??={...source};next[key]=result}
  }
  return next??item;
 };
 return visit(value) as T;
}
