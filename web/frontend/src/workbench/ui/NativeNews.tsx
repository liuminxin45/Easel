import {NativeTrends} from './nativePages';
import CopyableText from '../../components/CopyableText';
import {string,type JsonRecord} from '@workbench/core';
import {useResource,useWorkbench} from './hooks';
import {useEffect} from 'react';
import {Notice,PageHead,Panel,SourceLink} from './common';
export default function NativeNews({onUseTopic,id,search}:{id?:string;search:URLSearchParams;onUseTopic:(title:string,sourceId?:string,note?:string)=>void}){
 const vm=useWorkbench(),source=useResource<JsonRecord>(id?'/api/news/'+encodeURIComponent(id):null);
 useEffect(()=>{if(id&&(source.data||source.error))vm.navigation.contentReady?.({entryId:vm.navigation.entryKey})},[id,source.data,source.error,vm.navigation.entryKey]);
 if(!id)return <NativeTrends onUseTopic={onUseTopic} search={search}/>;
 return <div className="page-scroll ew-news-reading"><PageHead title="新闻原文"/><Notice sources={[source]}/>{source.data&&<Panel title={string(source.data.title)}><SourceLink value={source.data.url}/><CopyableText label="采集原文" text={string(source.data.body)}/><button className="btn btn-primary" onClick={()=>onUseTopic(string(source.data!.title),id)}>做内容</button></Panel>}</div>;
}
