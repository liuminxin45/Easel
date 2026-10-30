import {Notice} from './common';
import {useResource,type CollectionStatus} from '@workbench/core';
import {DashboardTrends} from '../../components/TrendsView';
import {useNewsSources,useNewsListing,newsGroup,type ManagedNewsSource} from './newsResources';

export function DashboardNews({onUseTopic}:{onUseTopic:(title:string)=>void}){
 const sources=useNewsSources(),status=useResource<CollectionStatus>('/api/collection/status');
 return <><Notice sources={[sources]}/>{sources.data?.sources.filter(s=>s.enabled&&s.default).map(s=><SourceSummary key={s.id} source={s} status={status.data} onUseTopic={onUseTopic}/>)}{sources.data&&!sources.data.sources.some(s=>s.enabled&&s.default)&&<div className="dash-empty">暂无启用来源，请到热点雷达查看。</div>}</>;
}
function SourceSummary({source,status,onUseTopic}:{source:ManagedNewsSource;status:CollectionStatus|null;onUseTopic:(title:string)=>void}){
 const r=useNewsListing(source.id),group=newsGroup(source,r.data,r.error,status);
 return <DashboardTrends groups={[group]} onRead={(_,it)=>onUseTopic(it.title)}/>;
}
