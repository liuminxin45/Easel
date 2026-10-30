import {ActionButton} from './common';
import React,{useCallback,useEffect,useMemo,useRef,useState} from 'react';
import {useWorkbench,useResource,useAsyncAction,useOperation,interactionState,creatorSelection,workPath,string,record,array,collectionSummary,collectionTaskLabel,collectionAllActive,type NewsListing,type NewsItem,type CollectionStatus,type CreatorBootstrap} from '@workbench/core';
import {newsListPath,newsDetailPath,newsItemContext,newsWindows,type NewsNavigationContext} from '@workbench/platform';
import TrendsView,{type TrendViewGroup,type TrendViewItem} from '../../components/TrendsView';
import TrendSourcesDialog,{type SourceUpdateResult} from '../../components/TrendSourcesDialog';
import EaselSubNav from '../../components/SubNav';
import type {Page} from '../../components/Sidebar';
import {Notice,Markdown,SourceLink,Pending} from './common';
import {useNewsSources,useNewsListing,newsGroup,fullWindow,newsArticle,type ManagedNewsSource,type NewsSources} from './newsResources';

const routes:Partial<Record<Page,string>>={dashboard:'/toolbox',trends:'/news',ideas:'/toolbox?section=research&pane=topics',calendar:'/toolbox?section=calendar',publish:'/toolbox?section=publications',breakdown:'/toolbox?section=research&pane=breakdown'};
function NewsNav(){const vm=useWorkbench();return <EaselSubNav current="trends" onNavigate={page=>vm.navigate(routes[page]||'/toolbox')}/>}
interface ListingState {data:NewsListing|null;loading:boolean;error:string;requestKey:string}
const windowKey=(context:NewsNavigationContext)=>JSON.stringify({day:context.day,issue:context.issue});
function SourceLoader({source,context,onResult}:{source:string;context:NewsNavigationContext;onResult:(id:string,state:ListingState)=>void}){
 const r=useNewsListing(source,context);
 const requestKey=windowKey(context);
 useEffect(()=>{onResult(source,{data:r.data,loading:r.loading,error:r.error,requestKey})},[source,r.data,r.loading,r.error,requestKey,onResult]);
 return null;
}
export default function NativeNews({id,search}:{id?:string;search:URLSearchParams}){
 return id?<NewsReading id={id} search={search}/>:<NewsRadar search={search}/>;
}

function NewsRadar({search}:{search:URLSearchParams}){
 const vm=useWorkbench(),sources=useNewsSources(),collection=useResource<CollectionStatus>('/api/collection/status',{interval:5000}),action=useAsyncAction(),operation=useOperation('collection:start'),sourceOperation=useOperation('collection:sources');
 const recoveredSource=useRef('');
 const [sourceRecoveryRevision,setSourceRecoveryRevision]=useState(0);
 useEffect(()=>{if(sourceOperation.pending?.uncertain)recoveredSource.current=sourceOperation.pending.id;else if(!sourceOperation.pending&&!sourceOperation.busy&&recoveredSource.current){recoveredSource.current='';setSourceRecoveryRevision(value=>value+1);void sources.reload()}},[sourceOperation.pending?.id,sourceOperation.pending?.uncertain,sourceOperation.busy,sources.reload]);
 const [manager,setManager]=useState(false),[records,setRecords]=useState<Record<string,ListingState>>({}),[saved,setSaved]=useState<Set<string>>(new Set());
 const available=(sources.data?.sources||[]).filter(s=>s.enabled),selected=search.has('sources')?(search.get('sources')||'').split(',').filter(id=>available.some(s=>s.id===id)):search.get('source')?[search.get('source')!]:available.filter(s=>s.default).map(s=>s.id);
 const windows=newsWindows(search.get('windows'));
 if(!search.has('windows')&&search.get('source'))windows[search.get('source')!]=Object.fromEntries(['day','issue','section','theme'].flatMap(k=>search.get(k)?[[k,search.get(k)!]]:[]));
 const currentRecord=(id:string)=>records[id]?.requestKey===windowKey(windows[id]||{})?records[id]:undefined;
 const resolved={...windows,...Object.fromEntries(selected.map(id=>[id,fullWindow(id,currentRecord(id)?.data||null,windows[id]||{})]).map(([id,context])=>{const {source:_,...window}=context as NewsNavigationContext;return [id,window]}))};
 const select=(ids:string[],next=resolved)=>vm.replace(newsListPath({sources:ids.join(','),windows:JSON.stringify(next)}),{preserveScroll:true,preserveLayers:true});
 const onResult=useCallback((id:string,state:ListingState)=>setRecords(prev=>prev[id]?.data===state.data&&prev[id]?.loading===state.loading&&prev[id]?.error===state.error&&prev[id]?.requestKey===state.requestKey?prev:{...prev,[id]:state}),[]);
 useEffect(()=>{if(sources.data&&selected.every(id=>records[id]?.requestKey===windowKey(windows[id]||{})&&!records[id].loading&&(records[id].data!==null||records[id].error)))vm.navigation.contentReady?.()},[sources.data,records,selected.join(','),search.toString()]);
 const lastMarker=useRef(''),marker=collection.data?.latest_run?collection.data.latest_run.id+':'+collection.data.latest_run.status:'';
 useEffect(()=>{if(lastMarker.current&&marker!==lastMarker.current&&!collection.data?.active_runs.length)void vm.client.invalidate(['news']);lastMarker.current=marker},[marker]);
 useEffect(()=>{if(manager)return vm.navigation.registerLayer?.(()=>setManager(false))},[manager]);
 const revisions=useRef<Record<string,number>>({});
 const management=useMemo(()=>({
   load:async()=>{const result=await vm.client.read<NewsSources>('/api/collection/sources');if(!result)throw Object.assign(new Error('暂不可读取来源列表'),{unreachable:true});revisions.current=Object.fromEntries(result.sources.map(s=>[s.id,s.revision]));return result},
   update:async(value:Record<string,unknown>)=>{const {id,...fields}=value;const result=await vm.client.mutate<SourceUpdateResult>('collection:sources','/api/collection/sources',{...fields,...(id?{source_id:id,expected_revision:revisions.current[String(id)]}:{})});if(typeof result.revision==='number')revisions.current[result.id]=result.revision;return result},
 }),[vm.client]);
 const refreshAction=useAsyncAction();
 const refresh=()=>void refreshAction.run(async()=>{await vm.service.collectAll();});
 const readContext=(source:string)=>({...fullWindow(source,currentRecord(source)?.data||null,windows[source]||{}),sources:selected.join(','),windows:JSON.stringify(resolved)});
 const read=(g:TrendViewGroup,it:TrendViewItem)=>{select(selected);vm.navigation.updateReturnAnchor?.('news:'+it.id);vm.navigate(newsDetailPath(it.id,readContext(g.platform)),{anchor:'news:'+it.id})};
 const save=(g:TrendViewGroup,it:TrendViewItem)=>void action.run(async()=>{
   if(saved.has(g.platform+':'+it.id))return;
   const [article,creators]=await Promise.all([newsArticle(vm.client,it.id),vm.api.get<CreatorBootstrap>('/api/creator/bootstrap')]);
   await vm.service.createWork('news-topic:'+it.id,{title:article.title,material:article.body||article.title,files:[],format:'poster',article_id:it.id,creative:{schema_version:2,creator:creatorSelection(creators,creators.default_profile_id,'poster'),recipe:{pack_id:'editorial-poster'}}},'draft');
   setSaved(prev=>new Set(prev).add(g.platform+':'+it.id));
 });
 const groups=selected.flatMap(id=>{const source=available.find(s=>s.id===id);if(!source)return [];const state=currentRecord(id),context=windows[id]||{},data=state?.data||null,g=newsGroup(source,data,state?.error||'',collection.data,context),task=collection.data?.sources.find(s=>s.id===id)?.last_task;
   return [{...g,statusContent:task?<div role="status">{collectionTaskLabel(task)}</div>:state?.loading?<div>正在读取…</div>:null,tools:<GroupControls source={source} data={data} context={fullWindow(id,data,context)} onChange={next=>select(selected,{...resolved,[id]:next})}/> }];
 });
 return <><NewsNav/>{selected.map(id=><SourceLoader key={id} source={id} context={windows[id]||{}} onResult={onResult}/>)}
   <TrendsView sources={available} selected={selected} groups={groups} ready={!!sources.data} loading={selected.some(id=>!currentRecord(id)||currentRecord(id)?.loading)} refreshing={refreshAction.busy||operation.busy||!!collectionAllActive(collection.data)}
     feedback={interactionState([sources,collection,action,refreshAction,operation])} warnings={sources.data?.warnings} saved={saved}
     notice={<><div className="trend-platforms ew-muted">后台按来源计划定时采集；进入页面只读取已有结果。刷新会立即采集全部已启用来源。</div>{collection.data?.latest_run&&<div className="trend-platforms" role="status">最近采集：{collectionSummary(collection.data.latest_run)}</div>}</>}
     onToggle={id=>select(selected.includes(id)?selected.filter(s=>s!==id):[...selected,id])} onManage={()=>setManager(true)} onRefresh={refresh}
     onRead={read} itemHref={(g,it)=>'/native/?path='+encodeURIComponent(newsDetailPath(it.id,readContext(g.platform)))} onSave={save}
     onUse={(_,it)=>vm.navigate('/posters/new?'+new URLSearchParams({article:it.id,draft:'new:news:'+it.id}),{intent:'flow'})}/>
   {manager&&<TrendSourcesDialog management={{...management,revision:sources.revision+sourceRecoveryRevision,operationSource:{busy:sourceOperation.busy,feedback:sourceOperation.feedback}}} onClose={()=>setManager(false)} onChanged={added=>{if(added)select([...new Set([...selected,added])])}}/>}
 </>;
}

function GroupControls({source,data,context,onChange}:{source:ManagedNewsSource;data:NewsListing|null;context:NewsNavigationContext;onChange:(next:NewsNavigationContext)=>void}){
 const vm=useWorkbench(),weekly=vm.config?.sources[source.id]?.kind==='periodical',sections=array<string>(data?.sections),themes=array<string>(data?.themes);
 if(!weekly&&!data?.previous_day&&!data?.next_day||weekly&&!array(data?.issues).length)return null;
 return <div className="native-news-controls">
   <div className="native-news-window">{weekly?string(record(data?.issue).title):data?.day||'暂无日期'}
     {!weekly&&<><button className="btn btn-sm" disabled={!data?.previous_day} onClick={()=>onChange({day:data?.previous_day})}>前一天</button><button className="btn btn-sm" disabled={!data?.next_day} onClick={()=>onChange({day:data?.next_day})}>后一天</button></>}
   </div>
   {weekly&&<label>期号<select className="field" value={context.issue||''} onChange={event=>onChange({issue:event.target.value})}>{array<{id:string;title:string}>(data?.issues).map(issue=><option key={issue.id} value={issue.id}>{issue.title}</option>)}</select></label>}
   {!!sections.length&&<label>栏目<select className="field" value={context.section||''} onChange={event=>onChange({...context,section:event.target.value})}><option value="">本期全部</option>{sections.map(s=><option key={s}>{s}</option>)}</select></label>}
   {!!themes.length&&<label>主题<select className="field" value={context.theme||''} onChange={event=>onChange({...context,theme:event.target.value})}><option value="">全部主题</option>{themes.map(s=><option key={s}>{s}</option>)}</select></label>}
 </div>;
}

function NewsReading({id,search}:{id:string;search:URLSearchParams}){
 const vm=useWorkbench(),item=useResource<NewsItem>('/api/news/'+encodeURIComponent(id)),context=item.data?newsItemContext(item.data,Object.fromEntries(search)):Object.fromEntries(search),source=string(context.source)||Object.keys(vm.config?.sources||{})[0]||'',r=useNewsListing(source,context),action=useAsyncAction();
 const rows=(r.data?.items||[]).filter(n=>(!context.section||n.section===context.section)&&(!context.theme||n.theme===context.theme)),current=rows.findIndex(n=>n.id===id);
 useEffect(()=>{if(item.data)vm.navigation.contentReady?.()},[item.data]);
 const save=()=>void action.run(async()=>{if(!item.data)return;const creators=await vm.api.get<CreatorBootstrap>('/api/creator/bootstrap'),n=item.data,result=await vm.service.createWork('news-topic:'+n.id,{title:n.title,material:n.body||n.title,files:[],format:'poster',article_id:n.id,creative:{schema_version:2,creator:creatorSelection(creators,creators.default_profile_id,'poster'),recipe:{pack_id:'editorial-poster'}}},'draft');vm.navigate(workPath({id:string(result.work_id)||string(result.id),format:'poster'}))});
 return <><NewsNav/><div className="page-scroll native-news-reading"><div className="page-head"><h1 className="page-title">{item.data?.title||'资讯阅读'}</h1></div><Notice sources={[item,r,action]}/>{item.data&&<>
   <div className="ew-toolbar"><button className="btn" onClick={()=>vm.back()}>返回热点</button><SourceLink value={item.data.url}/><button className="btn btn-primary" onClick={()=>vm.navigate('/posters/new?'+new URLSearchParams({article:id,draft:'new:news:'+id}),{intent:'flow'})}>用内容生产技能制作</button><ActionButton action={action} className="btn" disabled={action.busy} onClick={save}>保存为选题</ActionButton>
     <button className="btn" disabled={current<=0} onClick={()=>{const next=rows[current-1];if(next){vm.navigation.updateReturnAnchor?.('news:'+next.id);vm.replace(newsDetailPath(next.id,context))}}}>上一篇</button>
     <button className="btn" disabled={current<0||current>=rows.length-1} onClick={()=>{const next=rows[current+1];if(next){vm.navigation.updateReturnAnchor?.('news:'+next.id);vm.replace(newsDetailPath(next.id,context))}}}>下一篇</button>
   </div><article className="ew-reading"><Markdown text={item.data.body||''}/></article></>}</div></>;
}
