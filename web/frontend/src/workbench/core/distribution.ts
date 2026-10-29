import {array, record, string, type Artifact, type JsonRecord, type Version, type Work} from './models';

export type DistributionAction = 'draft' | 'publish';
export type DistributionPane = 'pending' | 'connections' | 'history';
export type DistributionCommand = 'connection-save' | 'channel-prepare' | 'batch-approve' | 'delivery-enqueue' | 'delivery-cancel' | 'delivery-retry' | 'delivery-reconcile';
export interface DistributionCapability extends JsonRecord {
  status: 'unknown' | 'unsupported' | 'trial' | 'available'; verified?: boolean;
  account?: string; account_verified?: boolean; code_verified?: boolean; reason?: string;
  last_checked_at?: string; checked_at?: string; evidence?: unknown;
}
export interface DistributionPlatform {id:string;name:string;channel_id:string;content_kinds:string[]}
export interface DistributionConnection extends JsonRecord {
  id:string;platform:string;account:string;label:string;enabled:boolean;revision:number;
  secret_configured:boolean;created_at:string;updated_at:string;
  capabilities:Partial<Record<DistributionAction|'verify',DistributionCapability>>;
}
export interface DistributionAsset extends Artifact {source_id:string;version_id:string;sha256:string}
export interface DistributionRevision extends JsonRecord {
  id:string;hash:string;work_id:string;version_id:string;publication_id:string;connection_id:string;
  connection_revision:number;platform:string;account:string;content_kind:string;title:string;body:string;
  source_token:string;source_fingerprint:string;source_snapshot:JsonRecord;asset_manifest:DistributionAsset[];
  publication_hash:string;created_at:string;valid?:boolean;invalid_reason?:string;
}
export interface DistributionApproval extends JsonRecord {
  id:string;batch_id:string;revision_id:string;revision_hash:string;connection_id:string;connection_revision:number;
  platform:string;account:string;action:DistributionAction;schedule_at:string|null;pilot:boolean;actor:string;approved_at:string;hash:string;
}
export interface DistributionDelivery extends JsonRecord {
  id:string;approval_id:string;batch_id:string;revision_id:string;publication_id:string;work_id:string;
  connection_id:string;account:string;platform:string;action:DistributionAction;schedule_at:string|null;pilot:boolean;
  status:'queued'|'leased'|'succeeded'|'failed'|'unknown'|'blocked'|'cancelled';
  remote_state:null|'draft'|'pending_review'|'published'|'unknown'|'failed';verified:boolean;attempt_ids:string[];
  created_at:string;updated_at:string;error:string|null;result?:JsonRecord;
}
export interface DistributionAttempt extends JsonRecord {id:string;delivery_id:string;runner_id:string;status:string;created_at:string;dispatched_at?:string;finished_at?:string;lease_until?:string;result?:JsonRecord}
export interface DistributionBatch extends JsonRecord {id:string;actor:string;created_at:string;approval_ids:string[];note?:string;status?:string}
export interface DistributionBootstrap extends JsonRecord {
  schema_version:number;work_id:string;platforms:DistributionPlatform[];connections:DistributionConnection[];
  revisions:DistributionRevision[];approvals:DistributionApproval[];batches:DistributionBatch[];
  deliveries:DistributionDelivery[];attempts:DistributionAttempt[];
  runner:{runtime:JsonRecord;instances:JsonRecord[]};publications:JsonRecord[];tasks?:JsonRecord;
}
export interface DistributionChannelDraft {title:string;body:string;image_ids:string[];content_kind:string;publication_id?:string;platform_options?:JsonRecord}
export interface DistributionApprovalChoice {action:DistributionAction;pilot:boolean;scheduled:boolean;schedule_local:string;acknowledged:boolean}
export interface DistributionConnectionDraft {platform:string;account:string;label:string;enabled:boolean;expected_revision?:number}
export interface DistributionProps {workId?:string;versionId?:string;onTitle?:(title:string,back?:boolean)=>void}
export const distributionPaneLabel:Record<DistributionPane,string>={pending:'待发布',connections:'账号连接',history:'分发历史'};
export const distributionActionLabel:Record<DistributionAction|'verify',string>={draft:'存平台草稿',publish:'发布到平台',verify:'核对平台回执'};
export const distributionCapabilityLabel:Record<DistributionCapability['status'],string>={unknown:'未验证',unsupported:'不支持',trial:'可申请试运行',available:'已验证可用'};
const capabilityReasons:Record<string,string>={needs_extension_origin:'需要在专用浏览器完成插件连接',no_credentials:'尚未配置安全凭据',account_mismatch:'当前登录账号与目标账号不一致',connector_has_no_image_post_method:'此连接器尚不支持公众号贴图',connector_supports_longform_article_only:'此连接器仅支持长文章',no_readback_method:'此连接器尚不能读取并核验平台回执',no_publish_method:'此连接器尚不支持直接发布',no_draft_method:'此连接器尚不支持保存平台草稿',not_installed:'连接器尚未安装',not_connected:'专用浏览器尚未连接',not_verified:'此账号尚未通过实际验证',bridge_unavailable:'专用浏览器连接尚不可用',unknown_account:'尚未取得平台登录账号'};
export function distributionCapabilityReason(value:unknown,fallback='尚未取得本账号的实际核验结果'):string {const code=string(value);if(!code)return fallback;if(capabilityReasons[code])return capabilityReasons[code]!;return /[\u3400-\u9fff]/.test(code)?code:fallback}
export const distributionStatusLabel:Record<string,string>={queued:'已入队',leased:'后台执行中',succeeded:'已取得回执',failed:'执行失败',unknown:'回执待核对',blocked:'执行受阻',cancelled:'已取消',approved:'已确认',partial:'部分完成',needs_attention:'需要处理',draft:'平台草稿',pending_review:'平台审核中',published:'平台已发布',offline:'未连接',unavailable:'未接入',available:'可用',running:'运行中',idle:'空闲',ready_for_account_probe:'待检查账号',not_configured:'尚未配置',stopped:'已停止',fixture_only:'隔离样例'};
export function distributionStatus(value:unknown):string{return distributionStatusLabel[string(value)]||string(value,'未取得')}
export function distributionRuntimeLabel(runtime:JsonRecord):string{return runtime.running===true?'运行中':runtime.running===false?'未运行':distributionStatus(runtime.status)}
export function distributionInstallationSummary(runtime:JsonRecord):string{return [typeof runtime.installed==='boolean'?runtime.installed?'工具已安装':'工具未安装':'工具状态未取得',typeof runtime.extension_installed==='boolean'?runtime.extension_installed?'扩展已安装':'扩展未安装':'扩展状态未取得',distributionStatus(runtime.status)].join(' · ')}
export function distributionCapability(connection:DistributionConnection|undefined,action:DistributionAction|'verify'):DistributionCapability {
  return connection?.capabilities?.[action]||{status:'unknown',verified:false,reason:'尚未取得本账号的验证结果'};
}
export function distributionPermission(connection:DistributionConnection|undefined,action:DistributionAction|'verify',pilot=false):{allowed:boolean;reason:string}{
  if(!connection)return {allowed:false,reason:'未取得账号连接'};
  if(!connection.enabled)return {allowed:false,reason:'账号连接已停用'};
  const cap=distributionCapability(connection,action);
  if(cap.account!==connection.account)return {allowed:false,reason:distributionCapabilityReason(cap.reason,'尚未取得本账号的验证结果')};
  if(cap.status==='available'&&cap.verified===true)return {allowed:true,reason:distributionCapabilityReason(cap.reason,'已通过本账号验证')};
  if(pilot&&cap.status==='trial'&&cap.code_verified===true&&cap.account_verified===true)return {allowed:true,reason:'仅授权本次试运行'};
  return {allowed:false,reason:distributionCapabilityReason(cap.reason,distributionCapabilityLabel[cap.status])};
}
export function distributionCommandInput(action:DistributionCommand,fields:JsonRecord):JsonRecord{return {...fields,action,operation_id:crypto.randomUUID()}}
export function distributionResult(value:JsonRecord):JsonRecord{return record(value.result??value)}
export function distributionSource(work:Work,version:Version,platform?:DistributionPlatform):DistributionChannelDraft {
  return {title:version.editable_text?.title||version.copy?.title||version.article?.title||work.title,
    body:version.editable_text?.body||version.copy?.caption||version.article?.body||string(record(version).prompt),
    image_ids:version.artifacts.filter(a=>a.mime.startsWith('image/')||work.format!=='poster'&&work.format!=='article'&&a.mime.startsWith('video/')).map(a=>a.id),content_kind:platform?.content_kinds[0]||'article'};
}
export function distributionRevisionDraft(revision:DistributionRevision):DistributionChannelDraft{return {title:revision.title,body:revision.body,image_ids:revision.asset_manifest.map(a=>a.source_id),content_kind:revision.content_kind,publication_id:revision.publication_id,platform_options:record(revision.platform_options)}}
export function distributionMove(ids:string[],index:number,direction:-1|1):string[]{const next=[...ids],to=index+direction;if(to<0||to>=next.length)return next;[next[index],next[to]]=[next[to]!,next[index]!];return next}
export function distributionSchedule(choice:DistributionApprovalChoice):string|null {
  if(!choice.scheduled)return null;
  if(!/^\d{4}-\d\d-\d\dT\d\d:\d\d$/.test(choice.schedule_local))throw Error('请选择完整的执行时间');
  const value=choice.schedule_local+':00+08:00';if(!Number.isFinite(Date.parse(value))||Date.parse(value)<=Date.now())throw Error('执行时间应晚于当前时间');return value;
}
export function distributionApprovalIssue(revision:DistributionRevision,connection:DistributionConnection|undefined,choice:DistributionApprovalChoice):string {
  if(revision.valid===false)return revision.invalid_reason||'渠道稿依据已变化，请重新准备';
  if(!connection||revision.connection_revision!==connection.revision||revision.account!==connection.account)return '账号已变化，请重新准备渠道稿';
  const permission=distributionPermission(connection,choice.action,choice.pilot);if(!permission.allowed)return permission.reason;
  try{distributionSchedule(choice)}catch(error){return error instanceof Error?error.message:'执行时间无效'}
  return choice.acknowledged?'':'请确认此账号、准确稿件及执行动作';
}
export function distributionRetryAllowed(delivery:DistributionDelivery,attempts:DistributionAttempt[]):boolean {
  if(delivery.status!=='failed')return false;
  const related=attempts.filter(a=>a.delivery_id===delivery.id),last=related[related.length-1];
  return !!last&&!last.dispatched_at&&record(last.result).phase==='pre_send';
}
export function distributionReceiptUrl(value:unknown):string {const raw=string(value);try{const url=new URL(raw);return url.protocol==='https:'&&!url.username&&!url.password?url.href:''}catch{return ''}}
export function distributionRevisionAssets(revision:DistributionRevision):Artifact[]{return array<DistributionAsset>(revision.asset_manifest).map(a=>({...a,image_url:'/api/files/'+encodeURIComponent(a.id)}))}
