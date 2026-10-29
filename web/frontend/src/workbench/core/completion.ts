import {array,record,string,type JsonRecord,type WorkSummary} from './models';

export type CompletionMode='archive'|'distribute'|'manual_published';
export interface CompletionTarget {connection_id:string;action:'draft'|'publish'}
export interface CompletionManualPublication {channel_id:string;account:string;status:'draft'|'published';url:string;published_at:string|null}
export interface CompletionPlan {mode:CompletionMode;targets:CompletionTarget[];manual_publications:CompletionManualPublication[];plan_hash?:string}
export interface CompletionChannel extends JsonRecord {channel_id:string;account:string;action:string;status:string;publication_id?:string;delivery_id?:string}
export interface CompletionRecord extends JsonRecord {id:string;decision_id:string;work_id:string;version_id:string;scope:string[];whole_work:boolean;status:string;archive:JsonRecord;project_archive?:JsonRecord;publications:CompletionChannel[];created_at:string;plan_hash:string;error?:string}
export interface CompletionOptions {creator?:{id:string;name:string;account_ids:string[]};account_notice?:string;work_id:string;version_id:string;format:string;required_scopes:string[];available_scopes:string[];whole_ready:boolean;default:CompletionPlan;defaults?:{completion:CompletionPlan;revision:number};targets:{connection_id:string;platform:string;channel_id:string;account:string;label:string;actions:{action:'draft'|'publish';available:boolean;reason:string}[]}[];manual_channels:{id:string;name:string}[];history:CompletionRecord[]}
export interface CompletionPreview {plan_hash:string;summary:string;whole_work:boolean;archive:JsonRecord;publications:CompletionChannel[];warnings:string[]}
export interface CompletionState {items:CompletionRecord[];latest:CompletionRecord|null}
export const completionOptionsPath=(workId:string,versionId:string)=>'/api/works/'+encodeURIComponent(workId)+'/versions/'+encodeURIComponent(versionId)+'/completion-options';
export const completionPreviewPath=(workId:string,versionId:string)=>'/api/works/'+encodeURIComponent(workId)+'/versions/'+encodeURIComponent(versionId)+'/completion-preview';
export const blankCompletion:CompletionPlan={mode:'archive',targets:[],manual_publications:[]};
export function initialCompletionSelection(options:Pick<CompletionOptions,'required_scopes'|'available_scopes'|'whole_ready'|'default'|'defaults'>&Partial<Pick<CompletionOptions,'creator'|'targets'>>):{scope:string[];plan:CompletionPlan}{const scope=options.required_scopes.filter(item=>options.available_scopes.includes(item)),whole=options.whole_ready&&options.required_scopes.length>0&&options.required_scopes.every(item=>scope.includes(item));let plan=whole?(options.defaults?.completion||options.default||blankCompletion):{...blankCompletion};if(options.creator){const allowed=new Set((options.targets||[]).map(t=>t.connection_id));plan={...plan,targets:plan.targets.filter(t=>allowed.has(t.connection_id)),manual_publications:[]};if(plan.mode==='distribute'&&!plan.targets.length)plan={...blankCompletion}}return {scope,plan}}
export const completionActionName=(action:string)=>action==='publish'?'发布到平台':action==='draft'?'存平台草稿':action==='manual_published'?'登记已发布':action==='manual'?'人工登记':'等待手动发布';
export const completionChannelStatus=(item:CompletionChannel)=>item.action==='manual'&&item.status==='draft'?'待手动发布':completionStage(item.status);
export const completionScopeName=(scope:string)=>({article:'正文',images:'图片',copy:'标题与配文'}[scope]||scope);
export function completionPlanInput(plan:CompletionPlan):CompletionPlan{return {mode:plan.mode,targets:plan.mode==='distribute'?plan.targets.map(target=>({connection_id:target.connection_id,action:target.action})):[],manual_publications:plan.mode!=='archive'?plan.manual_publications.map(item=>({channel_id:item.channel_id,account:item.account.trim(),status:plan.mode==='manual_published'?'published':item.status,url:item.url.trim(),published_at:item.published_at||null})):[]}}
export function completionDefaultPlan(plan:CompletionPlan):CompletionPlan {return plan.mode==='manual_published'?{...blankCompletion}:completionPlanInput({...plan,manual_publications:plan.manual_publications.map(item=>({...item,status:'draft',url:'',published_at:null}))})}
export function completionStage(value:unknown):string {return ({pending:'等待处理',planned:'待保存',queued:'排队中',leased:'交付中',running:'处理中',verified:'已核验',succeeded:'已取得回执',completed:'已完成',failed:'需处理',blocked:'需处理',unknown:'待核对',cancelled:'已停止',published:'已发布',draft:'平台草稿',pending_review:'平台审核中',not_verified:'未核验',ready:'待发布',archive_pending:'等待项目归档',archived:'项目已归档',partial:'部分完成',needs_attention:'需处理'} as Record<string,string>)[string(value)]||string(value,'待处理')}
export function completionArchiveLabel(item:CompletionRecord):string {return item.project_archive?.status==='verified'?(record(item.project_archive.decision_metadata).status==='needs_review'?'项目已归档 · 决定记录待核对':'项目已归档'):item.project_archive?.status==='failed'?'项目归档需处理':item.project_archive?.status==='unknown'?'项目归档待核对':item.archive.status==='verified'?'完成快照已保存 · 项目归档中':'完成快照待保存'}
export function completionDecisionTitle(work:Pick<WorkSummary,'decision'>,item:CompletionRecord):string {if(work.decision?.kind==='reject'&&work.decision.candidate_id===item.version_id)return '本版已不采纳';if(item.current===false||work.decision?.id!==item.decision_id)return '历史采纳记录';return item.whole_work?'制作已完成':'已记录局部采纳'}
export type PublicationPhase='pending'|'processing'|'published'|'attention';
export function publicationPhase(publication:JsonRecord,deliveries:JsonRecord[]=[]):PublicationPhase {
 if(publication.status==='published')return 'published';
 const matching=deliveries.filter(item=>item.publication_id===publication.id),latest=matching.at(-1);
 if(publication.status==='withdrawn'||latest&&['failed','unknown','blocked'].includes(string(latest.status)))return 'attention';
 if(latest&&['queued','leased','running'].includes(string(latest.status)))return 'processing';
 return 'pending';
}
export const publicationPhaseName:Record<PublicationPhase,string>={pending:'待发布',processing:'处理中',published:'已发布',attention:'需处理'};
export interface PublicationGroup {work_id:string;title:string;work?:WorkSummary;items:JsonRecord[];phases:PublicationPhase[];completions:CompletionRecord[]}
export function publicationGroupCompletionTitle(group:PublicationGroup):string {const item=group.completions.at(-1);if(group.work?.decision?.kind==='reject')return '本版已不采纳';if(!item||item.current===false||item.current!==true&&group.work?.decision?.id!==item.decision_id)return '历史采纳记录';return '已采纳，待安排发布'}
export function groupPublications(publications:JsonRecord[],works:WorkSummary[],deliveries:JsonRecord[]=[],completions:CompletionRecord[]=[]):PublicationGroup[]{
 const groups=new Map<string,PublicationGroup>();
 const ensure=(id:string,title:string)=>{let group=groups.get(id);if(!group){const work=works.find(item=>item.id===id);group={work_id:id,title:work?.title||title,work,items:[],phases:[],completions:[]};groups.set(id,group)}return group};
 for(const item of publications){const group=ensure(string(item.work_id)||string(item.id),string(item.title,'未命名作品'));group.items.push(item);const phase=publicationPhase(item,deliveries);if(!group.phases.includes(phase))group.phases.push(phase)}
 for(const item of completions){if(!item.whole_work)continue;const group=ensure(item.work_id,'已采纳作品');group.completions.push(item)}
 for(const group of groups.values()){if(group.items.length)continue;const item=group.completions.slice().sort((a,b)=>string(a.created_at).localeCompare(string(b.created_at))).at(-1);if(!item)continue;group.phases=[group.work?.decision?.kind==='reject'||['failed','unknown','needs_attention'].includes(item.status)?'attention':['pending','queued','running','archive_pending','awaiting_archive'].includes(item.status)?'processing':'pending']}
 return [...groups.values()];
}
export function readCompletionState(value:unknown):CompletionState {const source=record(record(value).completion??value);return {items:array<CompletionRecord>(source.items),latest:record(source.latest).id?source.latest as CompletionRecord:null}}
