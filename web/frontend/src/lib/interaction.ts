/** Shared by the original Easel views and the private host. No business state. */
export interface InteractionFeedback {kind:'error'|'status';message:string;operationScope?:string}
export interface InteractionSource {busy?:boolean;refreshing?:boolean;error?:string;feedback?:InteractionFeedback}

export function interactionState(sources:InteractionSource[],message?:string):InteractionFeedback|undefined{
 const values=sources.map(source=>source.feedback||(source.error?{kind:'error' as const,message:source.error}:undefined));
 const error=message||values.find(value=>value?.kind==='error')?.message;
 if(error)return {kind:'error',message:error};
 const status=values.find(value=>value?.kind==='status')?.message||(sources.some(source=>source.busy)?'正在处理…':sources.some(source=>source.refreshing)?'正在刷新…':'');
 return status?{kind:'status',message:status}:undefined;
}

export async function requestFingerprint(fields:unknown):Promise<string>{const bytes=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(fields)));return Array.from(new Uint8Array(bytes),value=>value.toString(16).padStart(2,'0')).join('')}

export function commandScope(domain:string,action:string,fields:Record<string,unknown>):string{
 const target=['profile_id','skill_id','proposal_id','publication_id','work_id','import_id','task_id','connection_id'].map(key=>fields[key]).find(value=>typeof value==='string'&&value.length);
 return domain+':'+action+':'+(target||'');
}

export function interactionFeedback(error:unknown):InteractionFeedback|undefined{
 const value=error&&typeof error==='object'?error as {message?:unknown;uncertain?:boolean;unreachable?:boolean;timedOut?:boolean;cancelled?:boolean;operationScope?:string}:{};
 if(value.cancelled&&!value.uncertain)return undefined;
 if(value.uncertain)return {kind:'status',message:'连接暂时中断，正在恢复操作状态。输入已保留。',...(value.operationScope?{operationScope:value.operationScope}:{})};
 if(value.unreachable||value.timedOut)return {kind:'status',message:'连接暂时中断，请稍后重试。'};
 return {kind:'error',message:typeof value.message==='string'?value.message:'操作未完成，请重试。'};
}

/** Refresh view data after an acknowledgement; never include it in submit time. */
export function refreshViews(...reads:Array<()=>Promise<unknown>>):void{
 for(const read of reads)void Promise.resolve().then(read).catch(()=>{/* Resource stores expose their own read errors. */});
}
