import type {ReactNode, MouseEvent} from 'react';
import {IconFire, IconRefresh, IconBookmark, IconCheck} from './icons';
import {InteractionNotice} from './InteractionNotice';
import type {InteractionFeedback} from '../lib/interaction';

export interface TrendViewItem {id:string;title:string;url?:string;hot?:string}
export interface TrendViewGroup {platform:string;label:string;items:TrendViewItem[];ok:boolean;fetched_at?:string|null;stale?:boolean;error?:{message:string}|null;statusContent?:ReactNode;tools?:ReactNode}
export interface TrendsViewProps {
  sources:{id:string;label:string}[];selected:string[];groups:TrendViewGroup[];ready:boolean;loading:boolean;refreshing?:boolean;
  updated?:number;error?:string;feedback?:InteractionFeedback;warnings?:string[];saved:ReadonlySet<string>;notice?:ReactNode;
  onToggle:(id:string)=>void;onRefresh:()=>void;onManage:()=>void;
  onSave:(group:TrendViewGroup,item:TrendViewItem)=>void;onUse:(group:TrendViewGroup,item:TrendViewItem)=>void;
  onRead?:(group:TrendViewGroup,item:TrendViewItem)=>void;
  itemHref?:(group:TrendViewGroup,item:TrendViewItem)=>string;
}

/** Shared presentation only. Callers own transport, navigation and authorization. */
export default function TrendsView(p:TrendsViewProps){
  const refreshing=p.refreshing??p.loading;
  const read=(event:MouseEvent<HTMLAnchorElement>,g:TrendViewGroup,it:TrendViewItem)=>{
    if(p.onRead&&!event.ctrlKey&&!event.metaKey&&!event.shiftKey&&!event.altKey&&event.button===0){event.preventDefault();p.onRead(g,it)}
  };
  return <div className="page-scroll trends-page" aria-busy={p.loading}>
    <div className="page-head"><div>
      <h1 className="page-title"><IconFire size={22}/> 热点雷达</h1>
      <p className="page-subtitle">汇集平台热搜与自定义数据源，挑选题，一键交给 AI 做成你的内容。
        {!!p.updated&&<span style={{color:'var(--text-tertiary)'}}> · {new Date(p.updated*1000).toLocaleTimeString('zh-CN',{hour:'2-digit',minute:'2-digit'})} 查询</span>}
      </p>
    </div><div className="trend-actions"><button className="btn btn-sm" onClick={p.onManage}>数据源</button>
      <button className="btn btn-sm" onClick={p.onRefresh} disabled={refreshing}><IconRefresh size={14}/> {refreshing?'采集中…':'刷新'}</button>
    </div></div>
    <div className="trend-platforms">{p.sources.map(s=><button key={s.id} className={`chip ${p.selected.includes(s.id)?'active':''}`} aria-pressed={p.selected.includes(s.id)} onClick={()=>p.onToggle(s.id)}>{s.label}</button>)}</div>
    <InteractionNotice message={p.error} sources={[{feedback:p.feedback}]}/>
    {p.warnings?.map((w,i)=><InteractionNotice sources={[{feedback:{kind:'status',message:w}}]} key={i}/>)}
    {p.notice}
    {!p.ready&&!p.error&&<div className="trend-platforms" role="status">正在加载数据源…</div>}
    {p.ready&&!p.sources.length&&<div className="trend-platforms">尚未启用数据源，请在数据源中添加或启用。</div>}
    {p.ready&&!!p.sources.length&&!p.selected.length&&<div className="trend-platforms">请选择上方的数据源查看热点。</div>}
    {p.loading&&<div className="trend-platforms" role="status">正在读取已采集热点…</div>}
    <div className="trend-grid">{p.groups.map(g=><div key={g.platform} className="card trend-col" data-source={g.platform}>
      <div className="trend-col-head">{g.label}<span className="trend-count">{g.items.length}</span></div>
      <div className="trend-source-status">{g.fetched_at&&<span>采集于 {new Date(g.fetched_at).toLocaleString('zh-CN')}</span>}{g.stale&&<span> · 缓存已过期</span>}
        {g.error&&<div role="status">{g.error.message}{g.stale?'，暂用上次结果':''}</div>}{g.statusContent}
      </div>{g.tools}
      <div className="trend-list" role="region" aria-label={g.label+'热点列表'} tabIndex={g.items.length>15?0:undefined} data-native-scroll-region={'news:'+g.platform}>{!g.items.length&&!p.loading&&<div className="trend-empty">{!g.ok?'该数据源暂时不可用':'采集成功，暂无热点'}</div>}
        {g.items.map((it,i)=><div key={it.id} className="trend-item" data-native-anchor={'news:'+it.id}>
          <span className={`trend-rank ${i<3?'top':''}`} aria-label={`第 ${i+1} 条`}>{i+1}</span>
          <div className="trend-main"><a className="trend-title" href={p.itemHref?.(g,it)||it.url||undefined} target={p.onRead?undefined:'_blank'} rel="noreferrer" title={it.title} onClick={event=>read(event,g,it)}>{it.title}</a>{it.hot&&<span className="trend-hot">{it.hot}</span>}</div>
          <button className="trend-save" title={p.saved.has(`${g.platform}:${it.id}`)?'已收藏到选题库':'收藏到选题库'} aria-label={`收藏选题：${it.title}`} onClick={()=>p.onSave(g,it)}>{p.saved.has(`${g.platform}:${it.id}`)?<IconCheck size={14}/>:<IconBookmark size={14}/>}</button>
          <button className="trend-use" title="做成内容" onClick={()=>p.onUse(g,it)}>做内容</button>
        </div>)}
      </div>
    </div>)}</div>
  </div>;
}

export function DashboardTrends({groups,onRead}:{groups:TrendViewGroup[];onRead:(group:TrendViewGroup,item:TrendViewItem)=>void}){
  return <>{!groups.length&&<div className="dash-empty">暂无热点，请到热点雷达查看数据源状态。</div>}{groups.map(g=><div key={g.platform} className="dash-trend-group">
    <div className="dash-trend-plat">{g.label}{g.stale?' · 过期缓存':''}</div>
    {g.error&&<div className="dash-empty">{g.error.message}</div>}
    {g.ok&&!g.items.length&&<div className="dash-empty">采集成功，暂无热点</div>}
    {g.items.slice(0,3).map(it=><div key={it.id} className="dash-trend-item"><button className="dash-trend-title" onClick={()=>onRead(g,it)}>{it.title}</button></div>)}
  </div>)}</>;
}
