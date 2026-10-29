import catalog from './distribution-platforms.json';
import {record,string} from './models';

export interface ReviewChannelOption {value:string;label:string}
const names=new Map(catalog.platforms.map(platform=>[platform.channel_id,
 catalog.providers[platform.provider as keyof typeof catalog.providers]?.name||platform.name]));
/** Read projection only. Actual publication channels do not create templates. */
export function reviewChannelOptions(data:unknown,includePublications=true):ReviewChannelOption[]{
 const root=record(data),configured=record(record(record(record(root.foundation).configuration).document).channels),options=new Map<string,ReviewChannelOption>();
 for(const [key,value] of Object.entries(configured)){if(!key)continue;const row=record(value);options.set(key,{value:key,label:string(row.name)||names.get(key)||key})}
 if(includePublications&&Array.isArray(root.publications))for(const item of root.publications){const key=string(record(item).channel_id);if(key&&!options.has(key))options.set(key,{value:key,label:names.get(key)||key})}
 return [...options.values()];
}
export function reviewChannelLabel(value:unknown,data?:unknown):string{
 const key=string(value);return reviewChannelOptions(data).find(option=>option.value===key)?.label||names.get(key)||key||'未记录渠道';
}
