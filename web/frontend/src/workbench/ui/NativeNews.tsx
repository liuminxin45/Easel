import {NativeTrends} from './nativePages';
import CopyableText from '../../components/CopyableText';
import {useResource,string,type JsonRecord} from '@workbench/core';
import {Notice,PageHead,Panel,SourceLink} from './common';
export default function NativeNews({onUseTopic,id}:{id?:string;search:URLSearchParams;onUseTopic:(title:string,sourceId?:string,note?:string)=>void}){
 const source=useResource<JsonRecord>(id?'/api/news/'+encodeURIComponent(id):null);
 if(!id)return <NativeTrends onUseTopic={onUseTopic}/>;
 return <div className="ew-page"><PageHead title="新闻原文"/><Notice sources={[source]}/>{source.data&&<Panel title={string(source.data.title)}><SourceLink value={source.data.url}/><CopyableText label="采集原文" text={string(source.data.body)}/><button className="btn btn-primary" onClick={()=>onUseTopic(string(source.data!.title),id)}>做内容</button></Panel>}</div>;
}
