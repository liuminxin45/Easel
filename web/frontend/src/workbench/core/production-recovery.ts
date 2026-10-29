import type {ProductionRecovery,Version,WorkSummary} from './models';
import {scopeConflict} from './revision-scope';
const object=(value:unknown):Record<string,unknown>=>value!==null&&typeof value==='object'&&!Array.isArray(value)?value as Record<string,unknown>:{};
const text=(value:unknown)=>typeof value==='string'?value:'';
const count=(value:unknown)=>typeof value==='number'&&Number.isSafeInteger(value)&&value>=0?value:0;
/** Classification comes from server facts, never error-message heuristics. */
export function readProductionRecovery(value:unknown):ProductionRecovery|null{
 const source=object(value),issue=object(source.production_issue),row=object(source.recovery||issue.recovery||source);
 if(!text(row.job_id)||!['dispatch','production','uncertain'].includes(text(row.failure_kind))||!['not_sent','submitted','unknown'].includes(text(row.send_state))||row.action!==null&&!['resend','edit_materials','reconcile'].includes(text(row.action)))return null;
 const revision=typeof row.revision==='number'&&Number.isSafeInteger(row.revision)&&row.revision>=0?row.revision:-1;
 const safe=row.failure_kind==='dispatch'&&row.send_state==='not_sent'&&row.action==='resend';
 const phase=(text(row.phase)||text(row.status)||(row.action==='resend'?'failed':row.action==='reconcile'?'unknown':row.action==='edit_materials'?'production_failed':'idle')) as ProductionRecovery['phase'];
 return {job_id:text(row.job_id),phase,status:phase,failure_kind:row.failure_kind as ProductionRecovery['failure_kind'],send_state:row.send_state as ProductionRecovery['send_state'],action:row.action as ProductionRecovery['action'],
  can_retry:safe&&revision>=0&&row.can_retry===true,attempt_count:count(row.attempt_count),auto_retry_count:count(row.auto_retry_count),max_auto_retries:3,
  next_retry_at:safe&&row.automatic_enabled===true&&typeof row.next_retry_at==='string'&&Number.isFinite(Date.parse(row.next_retry_at))?row.next_retry_at:null,
  retry_exhausted:row.retry_exhausted===true,revision,server_now:text(row.server_now),automatic_enabled:safe&&row.automatic_enabled===true,error_code:text(row.error_code),message:text(row.message)};
}
/** An old selected version cannot borrow a different job's resend authority. */
export function workProductionRecovery(work:WorkSummary,version?:Version|null):ProductionRecovery|null{
 const own=readProductionRecovery(work);if(!version)return own;
 return readProductionRecovery(version)||(own?.job_id===version.id?own:null);
}
export interface ProductionRecoveryView {recovery:ProductionRecovery;title:string;message:string;action:'resend'|'edit_materials'|'adjust_settings'|'reconcile';can_resend:boolean;attempts:string;countdown:string;exhausted:string}
export function productionRecoveryView(value:unknown,serverNow=Date.now()):ProductionRecoveryView|null{
 const recovery=readProductionRecovery(value);if(!recovery||recovery.action===null||['idle','sending','submitted'].includes(recovery.phase))return null;
 const uncertain=recovery.failure_kind==='uncertain'||recovery.send_state==='unknown'||recovery.action==='reconcile';
 const production=!uncertain&&(recovery.failure_kind==='production'||recovery.send_state==='submitted'||recovery.action==='edit_materials');
 const settings=!uncertain&&scopeConflict(recovery),action=uncertain?'reconcile':settings?'adjust_settings':production?'edit_materials':'resend';
 const seconds=recovery.next_retry_at?Math.max(0,Math.ceil((Date.parse(recovery.next_retry_at)-serverNow)/1000)):null;
 const countdown=action==='resend'&&seconds!==null?(seconds?'将在 '+seconds+' 秒后自动重试（'+Math.min(recovery.auto_retry_count+1,3)+'/3）':'等待后台自动重试'):'';
 return {recovery,title:uncertain?'回执待核对':settings?'修改范围待确认':production?'制作未完成':'发送失败',
  message:recovery.message||(uncertain?'原任务的发送结果尚未确认，请核对同一次结果。':production?'查看制作说明，补充素材或调整要求后继续。':'原任务与输入已保留。'),action,
  can_resend:action==='resend'&&recovery.can_retry,attempts:action==='resend'?(recovery.attempt_count?'本轮发送尝试 '+recovery.attempt_count+' 次':'历史尝试次数未记录')+' · 自动重试 '+recovery.auto_retry_count+'/3':'',countdown,
  exhausted:action==='resend'&&recovery.retry_exhausted?'已自动重试 3 次，本轮最多 4 次发送尝试。':''};
}
