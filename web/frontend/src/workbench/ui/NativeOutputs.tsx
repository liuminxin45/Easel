import React from 'react';
import ArtifactGallery from '../../components/ArtifactGallery';
import {useWorkbench,useResource,array,record,string,type JsonRecord} from '@workbench/core';
import {nativeArtifacts} from './ChatSessionView';
export function NativeOutputs({query=''}:{query?:string}){
 const vm=useWorkbench(),result=useResource<JsonRecord>('/api/chat/artifacts',{interval:10000});
 const items=array<JsonRecord>(result.data?.items).filter(item=>!query||string(item.title).includes(query));
 if(!items.length)return null;
 return <section><h2>近期 Easel 原生产物</h2><div className="ew-grid">{items.map(item=><article className="panel" key={string(item.turn_id)}><h3>{string(item.title)}</h3><ArtifactGallery artifacts={nativeArtifacts({output_files:array(item.files)})}/><button className="btn" onClick={()=>vm.navigate('/chat/'+encodeURIComponent(string(item.session_id)))}>打开原对话</button></article>)}</div></section>;
}
