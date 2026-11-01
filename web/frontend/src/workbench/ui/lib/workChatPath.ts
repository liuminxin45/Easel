import {record,string,type Work,type Version} from '@workbench/core';

export function nativeWorkChatPath(work:Work,version:Version|undefined,change=false):string|null{
 const binding=record(record(work).native_chat),sessionId=string(binding.session_id);if(!sessionId)return null;
 const versionId=version?.id||string(binding.version_id),params=new URLSearchParams({work:work.id,...(versionId?{version:versionId}:{})});
 if(change){const root=version?.creative?.creator?.skills?.find(skill=>skill.id==='content-production');if(!root?.version||!Number.isSafeInteger(root.version))return null;params.set('action','change');params.set('skill','content-production');params.set('skill_version',String(root.version))}
 return '/chat/'+encodeURIComponent(sessionId)+'?'+params;
}
