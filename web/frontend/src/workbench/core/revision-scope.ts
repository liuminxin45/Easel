import {record,string,type CreativeOptions,type Version} from './models';
import {revisionCreative} from './learning';

export type TextPolicy=Record<'title'|'body','follow_request'|'preserve'>;
export const scopeConflict=(value:unknown)=>['FROZEN_TEXT_SCOPE_CONFLICT','TEXT_SCOPE_CONFLICT'].includes(string(record(value).code)||string(record(value).error_code));
export const revisionPolicy=(value:CreativeOptions):TextPolicy=>({title:value.target==='images'?'preserve':value.text_policy?.title||'follow_request',body:value.target==='images'?'preserve':value.text_policy?.body||'follow_request'});
/** A new round inherits style, never the previous round's frozen literal locks. */
export function changeCreative(version?:Version,draft?:CreativeOptions):CreativeOptions{
 if(draft?.text_policy)return revisionCreative(draft);
 const next={...revisionCreative(version?.creative),...revisionCreative(draft)},parent:NonNullable<CreativeOptions['text']>=version?.editable_text||{},text:NonNullable<CreativeOptions['text']>={},policy:TextPolicy={title:'follow_request',body:'follow_request'};
 for(const key of ['title','body'] as const)if(draft?.text&&Object.hasOwn(draft.text,key)&&draft.text[key]!==parent[key]){text[key]=draft.text[key];policy[key]='preserve'}
 if(scopeConflict(version?.production_issue))policy.title='preserve';
 return {...next,target:'all',keep_text:false,text,text_policy:policy};
}
export function patchTextPolicy(value:CreativeOptions,key:'title'|'body',mode:TextPolicy['title']):CreativeOptions{
 const text={...value.text};if(mode==='follow_request')delete text[key];
 return {...value,keep_text:false,target:mode==='follow_request'?'all':value.target,text,text_policy:{...revisionPolicy(value),[key]:mode}};
}
export function patchRevisionTarget(value:CreativeOptions,target:'all'|'images'):CreativeOptions{return {...value,target,keep_text:false,text:{},text_policy:{title:target==='images'?'preserve':'follow_request',body:target==='images'?'preserve':'follow_request'}}}
