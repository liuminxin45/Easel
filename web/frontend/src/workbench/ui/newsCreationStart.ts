import {type WorkbenchClient} from '@workbench/core';
import {sessionRuntime,type FrozenTurn,type SessionDraft} from './chatRuntime';
import type {NewsCreationRequest} from './newsCreation';

/** Select inputs; the existing runtime alone owns execution and recovery. */
export async function startNewsTurn(client:WorkbenchClient,articleId:string,profileId:string,creation:NewsCreationRequest,options:{sessionId?:string;open:()=>Promise<string|undefined>;navigate:(path:string)=>void}):Promise<void>{
 const id=options.sessionId||await options.open();if(!id)throw Error('会话尚未核对，原设置已保留。');
 const {session}=await client.api.get<{session:Record<string,unknown>}>('/api/chat/sessions/'+encodeURIComponent(id)+'?limit=1');
 if(session.profile_id!==profileId)throw Error('已有会话保持原画像，请返回新闻页选择对应画像。');
 if(session.archived||session.deleted_at)throw Error('此会话已归档或删除，请从新闻页明确重新开始。');
 if(session.source_article_id&&session.source_article_id!==articleId)throw Error('会话绑定的新闻与当前材料不一致。');
 const runtime=sessionRuntime(client,id),pending=client.drafts.get<SessionDraft>('chat:'+id)?.pending;
 if(session.pendingTurnId||session.pendingSubmissionId||runtime.state.getState().running||pending&&pending.state!=='rejected'){
  options.navigate('/chat/'+encodeURIComponent(id));throw Error('原任务仍在进行或待核对，请查看原会话，不会重复发送。');
 }
 const message=(creation.intent==='discuss'?'讨论这条新闻怎么写。':creation.format==='poster'?'请制作微信公众号贴图。':'请写文章。')+(creation.note?'\n\n'+creation.note:'');
 const turn:FrozenTurn={turnId:crypto.randomUUID(),message,attachments:[],context:{profile_id:profileId,article_id:articleId,creation,...(creation.intent==='produce'?{skill_id:'content-production',action_id:'native'}:{})},inputs:{text:message,files:[],article_id:articleId,creation},state:'connecting'};
 options.navigate('/chat/'+encodeURIComponent(id));await runtime.submit(turn,profileId);
 const state=runtime.state.getState();if(!state.accepted&&state.error)throw Error(state.error);
 void client.invalidate(['chat','news']);
}
