import {NativeTrends} from './nativePages';
import Drawer from '../../components/Drawer';
import {string,type JsonRecord} from '@workbench/core';
import {useResource,useWorkbench} from './hooks';
import {useEffect,useRef,useState} from 'react';
import {Notice,PageHead,SourceLink} from './common';
import NewsCreationDrawer from './NewsCreationDrawer';
import {creationContextPath,creationRequest,linkedCreationSession,readingParagraphs,type NewsCreationContext,type NewsCreationRequest} from './newsCreation';
import './news-creation.css';
export interface NativeNewsProps {
 id?:string;profileId:string;search:URLSearchParams;
 onUseTopic:(title:string,sourceId?:string,note?:string)=>void;
 onStart:(articleId:string,creation:NewsCreationRequest,sessionId?:string)=>Promise<void>;
}
export default function NativeNews({onUseTopic,id,search,profileId,onStart}:NativeNewsProps){
 const vm=useWorkbench(),source=useResource<JsonRecord>(id?'/api/news/'+encodeURIComponent(id):null),context=useResource<NewsCreationContext>(id?creationContextPath(id,profileId):null);
 const [drawer,setDrawer]=useState<'records'|'creation'|null>(null),[busy,setBusy]=useState(false),[error,setError]=useState(''),lock=useRef(false);
 useEffect(()=>{setDrawer(null);setError('')},[id,profileId]);
 useEffect(()=>{if(id&&(source.data||source.error))vm.navigation.contentReady?.({entryId:vm.navigation.entryKey})},[id,source.data,source.error,vm.navigation.entryKey]);
 if(!id)return <NativeTrends onUseTopic={onUseTopic} search={search}/>;
 const data=source.data,meta=context.data?.source,title=meta?.title||string(data?.title),publisher=meta?.publisher||string(data?.publisher),published=meta?.published_at||string(data?.published_at);
 const linked=context.data&&linkedCreationSession(context.data,profileId),pending=linked&&(context.data?.linked_session?.pendingTurnId||context.data?.linked_session?.pendingSubmissionId);
 const discuss=async()=>{
  if(lock.current||!context.data)return;lock.current=true;setBusy(true);setError('');
  const linked=linkedCreationSession(context.data,profileId);
  if(linked){vm.navigate('/chat/'+encodeURIComponent(linked));lock.current=false;setBusy(false);return}
  try{await onStart(id,creationRequest(context.data,'discuss',{style:{writing:'',visual:'',character:'',layout:''},note:''}),linkedCreationSession(context.data,profileId))}
  catch(reason){setError(reason instanceof Error?reason.message:'对话未打开，请重试。')}
  finally{lock.current=false;setBusy(false)}
 };
 return <div className="page-scroll ew-news-reading ew-news-page"><PageHead title="新闻详情"/><Notice sources={[source]}/>
  {data&&<div className="ew-news-layout"><article className="ew-news-article"><header><h1>{title}</h1><div className="ew-news-byline">{publisher&&<span>{publisher}</span>}{published&&<time dateTime={published}>{published}</time>}<SourceLink value={meta?.url||data.url}/></div></header>
   <div className="ew-news-prose">{readingParagraphs(meta?.reading_summary||string(data.reading_summary)||string(data.body)).map((paragraph,index)=><p key={index}>{paragraph}</p>)}</div>
  </article><aside className="ew-news-actions" aria-label="新闻创作操作"><p className="ew-news-muted">围绕这条新闻，先交流想法，或选择写法开始制作。</p>
   <Notice sources={[context]}/>{error&&<p role="alert" className="ew-news-error">{error}</p>}
   <button className="btn" type="button" disabled={busy||!context.data} onClick={()=>void discuss()}>{busy?'正在打开…':pending?'查看会话':linked?'继续讨论':'讨论怎么写'}</button>
   <button className="btn btn-primary" type="button" disabled={busy||!context.data} onClick={()=>setDrawer('creation')}>制作内容</button>
   <button className="btn btn-ghost" type="button" onClick={()=>setDrawer('records')}>采集记录</button>
  </aside></div>}
  {drawer==='records'&&data&&<Drawer title="采集记录" onClose={()=>setDrawer(null)}><div className="ew-news-record"><dl><dt>标题</dt><dd>{string(data.title)}</dd><dt>来源</dt><dd>{string(data.publisher)||'—'}</dd><dt>发布时间</dt><dd>{string(data.published_at)||'—'}</dd><dt>采集时间</dt><dd>{string(data.collected_at)||string(data.run_at)||'—'}</dd><dt>来源链接</dt><dd><SourceLink value={data.url}/></dd></dl><h3>采集原文</h3><div className="ew-news-raw">{string(data.body)}</div></div></Drawer>}
  {drawer==='creation'&&<NewsCreationDrawer articleId={id} profileId={profileId} onClose={()=>setDrawer(null)} onStart={onStart}/>}
 </div>;
}
