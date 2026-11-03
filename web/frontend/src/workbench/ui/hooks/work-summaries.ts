import {useEffect,useState} from 'react';
import {useResource} from './context';

export interface WorkSummary {id:string;title:string;format:string;creator?:{id:string;name:string;revision:number}}
export interface WorkSummaryPage {items:WorkSummary[];next_cursor:string|null;total:number}
const merge=(before:WorkSummary[],after:WorkSummary[])=>{const rows=new Map(before.map(row=>[row.id,row]));for(const row of after)rows.set(row.id,row);return [...rows.values()]};

/** The picker owns summaries only; selected IDs remain in the parent's draft. */
export function useWorkSummaries(profileId=''){
 const [request,setRequest]=useState({profile:profileId,cursor:''}),cursor=request.profile===profileId?request.cursor:'';
 const query=new URLSearchParams({view:'summary',limit:'50',...(profileId?{profile_id:profileId}:{}),...(cursor?{cursor}:{})});
 const resource=useResource<WorkSummaryPage>('/api/works?'+query);
 const [loaded,setLoaded]=useState<{profile:string;items:WorkSummary[];next_cursor:string|null;total:number}>({profile:profileId,items:[],next_cursor:null,total:0});
 useEffect(()=>{if(!resource.data)return;const page=resource.data;setLoaded(previous=>({profile:profileId,items:cursor&&previous.profile===profileId?merge(previous.items,page.items):page.items,next_cursor:page.next_cursor,total:page.total}))},[profileId,cursor,resource.data]);
 const current=loaded.profile===profileId?loaded:{items:[],next_cursor:null,total:0};
 const busy=resource.loading||resource.refreshing===true;
 return {...resource,...current,more:()=>{if(current.next_cursor&&!busy)setRequest({profile:profileId,cursor:current.next_cursor})}};
}
