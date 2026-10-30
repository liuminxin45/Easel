import {useResource,string,type NewsListing,type NewsItem,type CollectionStatus} from '@workbench/core';
import type {NewsNavigationContext} from '@workbench/platform';
import type {TrendManagedSource} from '../../lib/api';
import type {TrendViewGroup} from '../../components/TrendsView';

export interface ManagedNewsSource extends TrendManagedSource {revision:number}
export interface NewsSources {version:1;sources:ManagedNewsSource[];warnings:string[];scripts:{id:string;label:string}[];python_template:string;script_max_bytes:number}
export function useNewsSources(){return useResource<NewsSources>('/api/collection/sources',{interval:10000})}
export function useNewsListing(source:string,context:NewsNavigationContext={}){
 const {day,issue}=context;
 return useResource<NewsListing>(source?'/api/news?'+new URLSearchParams({source,...(day?{day}:{}),...(issue?{issue}:{})}):null,{interval:20000});
}
export function newsGroup(source:ManagedNewsSource,data:NewsListing|null,error:string,status:CollectionStatus|null,context:NewsNavigationContext={}):TrendViewGroup{
 const state=status?.sources.find(row=>row.id===source.id),task=state?.last_task;
 const rows=(data?.items||[]).filter(row=>(!context.section||row.section===context.section)&&(!context.theme||row.theme===context.theme));
 return {platform:source.id,label:source.label,ok:!error&&task?.status!=='failed',
   fetched_at:string(data?.items[0]?.fetched_at)||string(data?.items[0]?.run_at)||string(state?.last_success_at)||undefined,
   error:error?{message:error}:task?.error?{message:task.error}:undefined,
   items:rows.map(row=>({id:row.id,title:string(row.original_title)||row.title,hot:string(row.hot)}))};
}
export function fullWindow(source:string,data:NewsListing|null,context:NewsNavigationContext):NewsNavigationContext{
 return {source,...context,...(!context.issue&&data?.day?{day:data.day}:{}),...(data?.issue&&typeof data.issue==='object'?{issue:string(data.issue.id)}:{})};
}
export async function newsArticle(client:{api:{get:<T>(path:string)=>Promise<T>}},id:string){return client.api.get<NewsItem>('/api/news/'+encodeURIComponent(id))}
